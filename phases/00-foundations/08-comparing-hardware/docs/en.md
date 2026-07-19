# Comparing Hardware: Speed, Units & Cost

> GHz, FLOPS, GB, GB/s, IOPS, ms — hardware is sold in a soup of units. This lesson decodes them so you can compare a CPU, a GPU, RAM, and a disk on the same page, and know why each costs what it does.

**Type:** Build
**Languages:** Python
**Prerequisites:** [The CPU](../05-the-cpu/)
**Time:** ~45 minutes

## The Problem

You've now met the CPU, RAM, the GPU, and storage. But how do you actually **compare**
them, or predict whether something will be fast? Each is sold in a different unit — GHz,
FLOPS, GB, GB/s, IOPS, milliseconds — and mixing them up leads to buying the wrong machine
or chasing the wrong bottleneck. Let's decode the units and turn them into real time.

## The Concept

### The units, decoded

| Unit | Measures | Used for |
|---|---|---|
| **Hz / GHz** | ticks per second | CPU **clock speed** (3.5 GHz = 3.5 billion ticks/s) |
| **FLOPS / TFLOPS** | floating-point operations per second | **compute throughput** (GPUs, ML) |
| **bytes (KB/MB/GB/TB)** | capacity | how much **RAM/storage** holds |
| **bytes/sec (MB/s, GB/s)** | bandwidth | how fast **data moves** (RAM, disk) |
| **bits/sec (Mbps, Gbps)** | bandwidth | **network** speed |
| **seconds (ns/µs/ms)** | latency | how long **one operation** takes |
| **IOPS** | input/output (I/O) operations per second | **disk** random-access rate |

Two axes run through all of them, and they're the same two from the networking lesson:
**throughput** (how much per second) and **latency** (how long each one takes). The two are
independent: a disk can stream data quickly (high throughput) yet still make each individual
request wait (high latency), while a CPU register answers almost instantly (very low latency)
but only moves a few bytes at a time. You care about *both*, for different reasons.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 626" width="100%" style="max-width:880px" role="img" aria-label="Throughput and latency are two different axes, and every hardware unit belongs to one of them. The left green panel lists throughput units: Hz or GHz, ticks per second, the CPU clock speed, where 3.5 GHz is 3.5 billion ticks per second; FLOPS, floating-point operations per second, the compute throughput of GPUs and machine learning; GB/s, gigabytes per second, the bandwidth at which data moves through RAM and disk; Mbps, megabits per second, network speed, measured in bits not bytes; and IOPS, input/output operations per second, a disk's random-access rate. The right amber panel lists latency units: nanoseconds, a billionth of a second, where a register, CPU cache, or RAM read lands; microseconds, a millionth of a second, where an SSD read lands; and milliseconds, a thousandth of a second, a disk seek or a network round trip. Below, a worked example draws a pipe twice. The first pipe is drawn wide and very long: an SSD streaming about 500 megabytes per second, so 1 GB arrives in about 2 seconds once the stream is flowing, yet the pipe's great length shows that each individual request still has to wait for its first byte. That is high throughput and high latency at the same time. The second pipe is thin and short: a CPU register, which moves only a few bytes at a time but answers almost instantly. The pipe's width is throughput and its length is latency, and the two vary independently. A gray band states the bits-versus-bytes trap: network speed is in bits, storage and RAM in bytes, and 8 bits equal 1 byte, so 100 Mbps is 12.5 megabytes per second and a 100 MB file takes about 8 seconds, not 1. Reading 1 GB takes about 0.05 seconds from RAM at 20 GB/s, about 2 seconds from an SSD at 500 MB/s, and about 80 seconds over a 100 Mbps network: a 1600 times spread.">
  <defs>
    <marker id="p0l08a-ams" markerWidth="9" markerHeight="9" refX="1" refY="3" orient="auto"><path d="M7,0 L0,3 L7,6 Z" fill="#e0930f"/></marker>
    <marker id="p0l08a-ame" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Every hardware spec is either throughput or latency — and they move independently</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-linejoin="round" stroke-width="1.9">
      <rect x="16" y="48" width="424" height="252" rx="12" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f"/>
      <rect x="460" y="48" width="424" height="252" rx="12" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f"/>
    </g>

    <text x="228" y="72" font-size="13" font-weight="700" text-anchor="middle" fill="#0fa07f">THROUGHPUT</text>
    <text x="228" y="90" font-size="9.5" text-anchor="middle" fill="currentColor" opacity="0.85">how MUCH gets through per second</text>
    <path d="M32 102 L424 102" stroke="#0fa07f" stroke-opacity="0.35" stroke-width="1"/>

    <g fill="#0fa07f" font-size="9.5" font-weight="700">
      <text x="32" y="124">Hz / GHz</text>
      <text x="32" y="160">FLOPS</text>
      <text x="32" y="196">GB/s</text>
      <text x="32" y="232">Mbps</text>
      <text x="32" y="268">IOPS</text>
    </g>
    <g fill="currentColor" font-size="9">
      <text x="118" y="124">ticks per second — CPU clock speed</text>
      <text x="118" y="160">floating-point operations per second</text>
      <text x="118" y="196">gigabytes per second — bandwidth</text>
      <text x="118" y="232">megabits per second — network speed</text>
      <text x="118" y="268">input/output operations per second</text>
    </g>
    <g fill="currentColor" font-size="8.5" opacity="0.7">
      <text x="118" y="137">3.5 GHz = 3.5 billion ticks per second</text>
      <text x="118" y="173">compute throughput — GPUs, machine learning</text>
      <text x="118" y="209">how fast data moves: RAM, disk</text>
      <text x="118" y="245">note the little b — BITS, not bytes</text>
      <text x="118" y="281">a disk's random-access rate</text>
    </g>

    <text x="672" y="72" font-size="13" font-weight="700" text-anchor="middle" fill="#e0930f">LATENCY</text>
    <text x="672" y="90" font-size="9.5" text-anchor="middle" fill="currentColor" opacity="0.85">how LONG ONE operation takes</text>
    <path d="M476 102 L868 102" stroke="#e0930f" stroke-opacity="0.35" stroke-width="1"/>

    <g fill="#e0930f" font-size="9.5" font-weight="700">
      <text x="476" y="124">ns</text>
      <text x="476" y="160">µs</text>
      <text x="476" y="196">ms</text>
    </g>
    <g fill="currentColor" font-size="9">
      <text x="530" y="124">nanoseconds — one billionth of a second</text>
      <text x="530" y="160">microseconds — one millionth of a second</text>
      <text x="530" y="196">milliseconds — one thousandth of a second</text>
    </g>
    <g fill="currentColor" font-size="8.5" opacity="0.7">
      <text x="530" y="137">a register, CPU cache, or RAM read (lesson 6)</text>
      <text x="530" y="173">an SSD read lands here</text>
      <text x="530" y="209">a disk seek or a network round trip</text>
    </g>
    <text x="476" y="240" font-size="9" font-weight="700" fill="#e0930f">Independent of throughput:</text>
    <text x="476" y="256" font-size="9" fill="currentColor" opacity="0.85">a wider pipe moves MORE per second —</text>
    <text x="476" y="270" font-size="9" fill="currentColor" opacity="0.85">it does not move any ONE thing sooner.</text>
    <text x="476" y="288" font-size="8.5" fill="currentColor" opacity="0.7">That is how something can be fast and slow at once.</text>

    <text x="450" y="322" font-size="11.5" font-weight="700" text-anchor="middle" fill="currentColor">Drawn literally: the pipe's WIDTH is throughput, its LENGTH is latency</text>

    <rect x="196" y="344" width="568" height="56" rx="10" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f" stroke-width="1.8"/>
    <path d="M176 346 L188 346 M182 346 L182 398 M176 398 L188 398" stroke="#0fa07f" stroke-width="1.5" fill="none"/>
    <text x="168" y="362" font-size="10" font-weight="700" text-anchor="end" fill="#0fa07f">WIDE</text>
    <text x="168" y="376" font-size="9" text-anchor="end" fill="#0fa07f" opacity="0.9">high</text>
    <text x="168" y="390" font-size="9" text-anchor="end" fill="#0fa07f" opacity="0.9">throughput</text>
    <text x="480" y="368" font-size="10.5" font-weight="700" text-anchor="middle" fill="currentColor">SSD / disk — streams ~500 MB/s (megabytes per second)</text>
    <text x="480" y="386" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.8">1 GB arrives in ~2 s once the stream is flowing</text>
    <text x="480" y="414" font-size="9.5" font-weight="700" text-anchor="middle" fill="#e0930f">LONG = HIGH LATENCY</text>
    <path d="M196 422 L764 422" stroke="#e0930f" stroke-width="1.6" fill="none" marker-start="url(#p0l08a-ams)" marker-end="url(#p0l08a-ame)"/>
    <text x="480" y="440" font-size="9" text-anchor="middle" fill="#e0930f" opacity="0.9">each individual request still has to wait for its first byte</text>

    <rect x="196" y="466" width="132" height="14" rx="7" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f" stroke-width="1.8"/>
    <path d="M176 466 L188 466 M182 466 L182 480 M176 480 L188 480" stroke="#0fa07f" stroke-width="1.5" fill="none"/>
    <text x="168" y="470" font-size="10" font-weight="700" text-anchor="end" fill="#0fa07f">THIN</text>
    <text x="168" y="484" font-size="9" text-anchor="end" fill="#0fa07f" opacity="0.9">low throughput</text>
    <text x="344" y="474" font-size="10.5" font-weight="700" fill="currentColor">CPU register — a few bytes at a time</text>
    <text x="344" y="494" font-size="9" fill="currentColor" opacity="0.85">answers almost instantly, but moves almost nothing per second</text>
    <path d="M196 502 L328 502" stroke="#e0930f" stroke-width="1.6" fill="none" marker-start="url(#p0l08a-ams)" marker-end="url(#p0l08a-ame)"/>
    <text x="262" y="518" font-size="9.5" font-weight="700" text-anchor="middle" fill="#e0930f">SHORT = LOW LATENCY</text>

    <rect x="16" y="536" width="868" height="46" rx="10" fill="#7f7f7f" fill-opacity="0.09" stroke="#7f7f7f" stroke-opacity="0.6" stroke-width="1.6"/>
    <text x="32" y="554" font-size="10" font-weight="700" fill="#e0930f">The bits-vs-bytes trap:</text>
    <text x="188" y="554" font-size="9.5" fill="currentColor">network speed is in bits (Mbps), storage and RAM in bytes (MB/s) — and 8 bits = 1 byte.</text>
    <text x="188" y="570" font-size="9.5" fill="currentColor" opacity="0.85">So 100 Mbps = 12.5 MB/s. Expect a 100 MB file in 1 s and you will wait ~8.</text>
  </g>
  <text x="450" y="602" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Reading 1 GB: ~0.05 s from RAM (~20 GB/s), ~2 s from an SSD (~500 MB/s), ~80 s over 100 Mbps — a 1600× spread.</text>
  <text x="450" y="620" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.75">Throughput tells you how many you can serve; latency tells you how long each one waits. Spend on the axis you are actually bound by.</text>
</svg>
```

### The bits-vs-bytes trap

The single most common unit mistake: **network speed is in *bits*, storage and RAM are in
*bytes*.** And **8 bits = 1 byte**. So a "**100 Mbps**" internet connection is 100
*megabits* per second = **12.5 MB/s** (megabytes). If you expected to download a 100 MB
file in 1 second, you'll wait ~8. Always check: little-b `b` = bits, big-B `B` = bytes.

### Turning units into real time

Units only mean something when you compute a real number. How long to read **1 GB** from
different places?

| Source | Typical bandwidth | Time to read 1 GB |
|---|---|---|
| RAM | ~20 GB/s | ~0.05 s |
| SSD | ~500 MB/s | ~2 s |
| 100 Mbps network | 12.5 MB/s | ~80 s |

Same gigabyte, a **1600×** spread — the memory hierarchy (lesson 6) made concrete in
seconds. This is *why* "keep hot data in RAM" and "reduce what you send over the network"
aren't slogans; they're 1000× decisions.

### Cost, and why each part is priced the way it is

You pay for the **scarce** property — speed and parallelism, not raw capacity:

| Part | Priced by | Why it's (relatively) expensive |
|---|---|---|
| CPU | per core + single-thread speed | complex cores, top clock speeds, low yield on big dies |
| RAM | per GB | fast + volatile: constant power, refresh, precise circuitry (lesson 6) |
| GPU | the whole card | huge die + fast VRAM (video memory) + heavy AI demand (lesson 7) |
| SSD / HDD | per GB (cheapest) | dense, persistent, no power to hold data — but slow |

Rule of thumb: **fast and parallel costs more than big and slow.** A terabyte of disk is
cheaper than 32 GB of RAM because you're paying for speed, not space.

### The engineering payoff: match hardware to the bottleneck

Every workload is limited by *one* resource at a time. Find it, then spend there:

- **CPU-bound** (pegged at 100% CPU) → faster or more cores.
- **Memory-bound** (out of RAM / thrashing) → more RAM or better locality.
- **I/O-bound** (waiting on disk or network) → faster storage, a cache, or fewer round trips.

Don't overpay for a dimension you don't need — a GPU won't speed up a disk-bound API, and
more RAM won't help a CPU-pegged one.

## Build It

[`code/compare.py`](../code/compare.py) turns the units into time and catches the
bits/bytes trap:

```python
def transfer_time(size_bytes, bytes_per_sec):
    return size_bytes / bytes_per_sec

def mbps_to_MBps(mbps):
    return mbps / 8                     # 8 bits = 1 byte

GB = 1_000_000_000
for name, bw in {
    "RAM (~20 GB/s)":   20 * GB,
    "SSD (~500 MB/s)":  500_000_000,
    "100 Mbps network": mbps_to_MBps(100) * 1_000_000,   # bits -> bytes/s
}.items():
    print(f"{name:20} read 1 GB in {transfer_time(GB, bw):8.2f} s")
```

**Think about it:**

1. Your **ISP** (internet service provider) sells "**1 Gbps**" internet. What's the fastest
   you can actually download a file
   in **megabytes per second**?
2. Reading 1 GB from RAM vs a 100 Mbps network differs by ~1600×. Which lesson-6 idea does
   that reinforce?
3. Your API is stuck at 100% CPU with plenty of free RAM. Would adding RAM help? What would?

## Key takeaways

- Know the units: **GHz** (clock), **FLOPS** (compute), **bytes** (capacity), **bytes/s &
  bits/s** (bandwidth), **seconds** (latency), **IOPS** (disk ops). Everything reduces to
  **throughput** vs **latency**.
- **Bits vs bytes:** network = bits (Mbps), storage/RAM = bytes (MB/s); divide by 8 to
  convert. A classic, costly mix-up.
- Turn units into **time**: reading 1 GB spans ~0.05 s (RAM) to ~80 s (100 Mbps) — the
  hierarchy in seconds.
- You pay for **speed and parallelism, not capacity**; **match the hardware to the
  bottleneck** (CPU-, memory-, or I/O-bound) instead of overspending on the wrong axis.

Next: [How a Computer Runs a Program](../09-how-a-computer-runs-a-program/) — how the OS puts
all this hardware to work running your software.
