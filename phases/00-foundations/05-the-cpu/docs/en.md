# The CPU: Cores, Clock & Execution

> The CPU is the part that actually does the work — and it does one absurdly simple thing, billions of times a second. Once you see that loop, "GHz" and "cores" stop being marketing.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Transistors & Logic Gates](../03-transistors-and-logic-gates/)
**Time:** ~50 minutes

## The Problem

You've now got transistors → gates → an adder, all etched onto a chip. But a pile of
adders isn't a computer. How does that chip actually **run a program** — step through
your instructions and produce a result? And when a spec sheet says **3.5 GHz** and **8
cores**, what do those numbers really mean for your backend?

## The Concept

### What's inside a CPU

The **CPU** (Central Processing Unit) is the worker. It's built from the gate circuits of
the last lesson, arranged into a few key parts:

- **ALU** (Arithmetic Logic Unit) — the adder/comparator from lesson 3. It does the actual
  math and logic.
- **Registers** — a *handful* of tiny, ultra-fast storage slots *inside* the CPU that hold
  the few numbers it's working on *right now*. These are the fastest memory that exists
  (top of the hierarchy in the next lesson).
- **Control unit** — the coordinator that fetches instructions and tells the ALU and
  registers what to do.

### The fetch–decode–execute cycle

Here's the entire job of a CPU, repeated forever:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 652" width="100%" style="max-width:880px" role="img" aria-label="The fetch-decode-execute cycle drawn as a closed loop. Three purple stage boxes sit around a ring inside a large box labelled CPU, Central Processing Unit, and purple arrows curve clockwise from each stage to the next so the loop never ends. Stage 1, FETCH, sits at the top: get the next instruction from memory, with a program counter tracking which instruction is next. A blue arrow leaves the CPU to the left carrying the address of the next instruction out to RAM, Random Access Memory, drawn in gray outside the CPU boundary because it is separate and far slower; a second blue arrow brings the instruction bytes back. Stage 2, DECODE, sits at the lower right: figure out what operation it is and what it acts on, while the control unit turns those bytes into control signals for the rest of the chip. Stage 3, EXECUTE, sits at the lower left: the ALU, Arithmetic Logic Unit, does the math or logic, or a value moves. It can add, compare, move a value, or jump somewhere else, and a green arrow carries the result down into the registers. From EXECUTE the ring returns to FETCH, because the program counter now points at the next instruction. In the middle of the ring sits the CLOCK, the metronome that drives the loop: it ticks a fixed number of times per second and each tick pushes the cycle forward. Hz, hertz, means ticks per second, so 3.5 GHz is 3.5 billion ticks per second. A gray panel on the right explains that instructions are just numbers, a few bytes each, and that every CPU understands one fixed vocabulary of them called its instruction set, x86 or ARM, into which your Python or Go is translated before the CPU ever runs it. An amber panel on the left warns that GHz is only one dimension of speed: a CPU can also do more work per tick, called IPC or instructions per cycle, so a well-designed 3 GHz chip can out-run a lazy 4 GHz one. Along the bottom inside the CPU sit its three parts: registers, a handful of tiny ultra-fast storage slots inside the chip holding the few numbers it is working on right now; the ALU, the adder and comparator that does the actual math and logic; and the control unit, the coordinator that fetches instructions and tells the ALU and registers what to do.">
  <defs>
    <marker id="p0l05a-arp" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#7c5cff"/></marker>
    <marker id="p0l05a-arb" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
    <marker id="p0l05a-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">One loop, forever: fetch → decode → execute, 3.5 billion ticks a second</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g fill="none" stroke-linejoin="round">
      <rect x="212" y="58" width="672" height="520" rx="14" fill="#7c5cff" fill-opacity="0.04" stroke="#7c5cff" stroke-width="2" stroke-opacity="0.75"/>
      <rect x="16" y="92" width="176" height="176" rx="10" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f" stroke-width="1.8"/>
      <rect x="16" y="288" width="176" height="236" rx="10" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f" stroke-width="1.6" stroke-opacity="0.8"/>
      <rect x="702" y="100" width="174" height="196" rx="10" fill="#7f7f7f" fill-opacity="0.08" stroke="#7f7f7f" stroke-width="1.6"/>
      <rect x="356" y="88" width="222" height="82" rx="11" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff" stroke-width="2"/>
      <rect x="262" y="312" width="214" height="100" rx="11" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff" stroke-width="2"/>
      <rect x="526" y="312" width="214" height="100" rx="11" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff" stroke-width="2"/>
      <rect x="366" y="186" width="230" height="116" rx="11" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff" stroke-width="1.8"/>
      <rect x="228" y="470" width="200" height="96" rx="10" fill="#7c5cff" fill-opacity="0.07" stroke="#7c5cff" stroke-width="1.5" stroke-opacity="0.85"/>
      <rect x="448" y="470" width="200" height="96" rx="10" fill="#7c5cff" fill-opacity="0.07" stroke="#7c5cff" stroke-width="1.5" stroke-opacity="0.85"/>
      <rect x="668" y="470" width="200" height="96" rx="10" fill="#7c5cff" fill-opacity="0.07" stroke="#7c5cff" stroke-width="1.5" stroke-opacity="0.85"/>
    </g>

    <text x="228" y="78" font-size="9" font-weight="700" fill="#7c5cff">CPU — Central Processing Unit — the whole loop happens on this one chip</text>

    <g fill="none" stroke="#7c5cff" stroke-width="2.2">
      <path d="M580 150 Q726 205 660 310" marker-end="url(#p0l05a-arp)"/>
      <path d="M594 412 Q509 458 424 412" marker-end="url(#p0l05a-arp)"/>
      <path d="M306 312 Q268 234 354 166" marker-end="url(#p0l05a-arp)"/>
    </g>

    <g fill="none" stroke="#3553ff" stroke-width="1.8">
      <path d="M354 106 L198 106" marker-end="url(#p0l05a-arb)"/>
      <path d="M194 134 L352 134" marker-end="url(#p0l05a-arb)"/>
    </g>
    <g fill="none" stroke="#0fa07f" stroke-width="1.8">
      <path d="M300 414 L300 466" marker-end="url(#p0l05a-arg)"/>
    </g>

    <g text-anchor="middle" fill="currentColor">
      <text x="108" y="116" font-size="12" font-weight="700" fill="#7f7f7f">RAM</text>
      <text x="108" y="132" font-size="8" opacity="0.9">Random Access Memory</text>
      <text x="278" y="98" font-size="7" fill="#3553ff" font-weight="700">the address of the next</text>
      <text x="278" y="118" font-size="7" fill="#3553ff" font-weight="700">instruction goes out to RAM</text>
      <text x="278" y="150" font-size="7" fill="#3553ff" font-weight="700">the instruction bytes arrive</text>
      <text x="278" y="162" font-size="7" opacity="0.8">— just numbers (lesson 1)</text>
    </g>
    <g fill="currentColor" font-size="7" opacity="0.9">
      <text x="26" y="156">Outside the CPU — a</text>
      <text x="26" y="168">separate, far slower chip.</text>
      <text x="26" y="190">Holds the program: its</text>
      <text x="26" y="202">instructions and its data.</text>
      <text x="26" y="224">The CPU would spend most</text>
      <text x="26" y="236">of its time waiting on it —</text>
      <text x="26" y="248">which is why an on-chip</text>
      <text x="26" y="260">cache exists (lesson 6).</text>
    </g>

    <text x="26" y="312" font-size="8.5" font-weight="700" fill="#e0930f">GHz IS ONE DIMENSION</text>
    <g fill="currentColor" font-size="7" opacity="0.9">
      <text x="26" y="336">Hertz (Hz) = ticks per second.</text>
      <text x="26" y="348">3.5 GHz = 3.5 billion ticks</text>
      <text x="26" y="360">per second. More ticks means</text>
      <text x="26" y="372">more steps per second —</text>
      <text x="26" y="384">roughly, a faster CPU.</text>
      <text x="26" y="410">But a CPU can also do more</text>
      <text x="26" y="422">WORK PER TICK: IPC,</text>
      <text x="26" y="434">instructions per cycle.</text>
      <text x="26" y="460">A well-designed 3 GHz chip</text>
      <text x="26" y="472">can out-run a lazy 4 GHz one.</text>
      <text x="26" y="498">So clock speed is ONE</text>
      <text x="26" y="510">dimension of speed, not all.</text>
    </g>

    <text x="789" y="124" text-anchor="middle" font-size="8.5" font-weight="700" fill="#7f7f7f">INSTRUCTION SET</text>
    <g fill="currentColor" font-size="7" opacity="0.9">
      <text x="712" y="146">Each instruction is just a</text>
      <text x="712" y="158">NUMBER — a few bytes</text>
      <text x="712" y="170">(lesson 1), nothing more.</text>
      <text x="712" y="196">A CPU understands one fixed</text>
      <text x="712" y="208">vocabulary of them: its</text>
      <text x="712" y="220">INSTRUCTION SET — x86, ARM.</text>
      <text x="712" y="246">Your Python or Go is</text>
      <text x="712" y="258">translated down to these</text>
      <text x="712" y="270">before the CPU ever runs it.</text>
    </g>
    <text x="712" y="288" font-size="7" font-weight="700" fill="#7f7f7f">Fetched bytes are one of these.</text>

    <g text-anchor="middle" fill="currentColor">
      <text x="467" y="112" font-size="11" font-weight="700" fill="#7c5cff">1 · FETCH</text>
      <text x="467" y="132" font-size="7.5">get the next instruction from memory</text>
      <text x="467" y="148" font-size="7.5" opacity="0.9">a PROGRAM COUNTER (PC) tracks</text>
      <text x="467" y="160" font-size="7.5" opacity="0.9">which instruction is next</text>

      <text x="633" y="334" font-size="11" font-weight="700" fill="#7c5cff">2 · DECODE</text>
      <text x="633" y="354" font-size="7.5">figure out what operation it is,</text>
      <text x="633" y="366" font-size="7.5">and what it acts on</text>
      <text x="633" y="386" font-size="7.5" opacity="0.9">the CONTROL UNIT turns these bytes</text>
      <text x="633" y="398" font-size="7.5" opacity="0.9">into control signals for the chip</text>

      <text x="369" y="334" font-size="11" font-weight="700" fill="#7c5cff">3 · EXECUTE</text>
      <text x="369" y="354" font-size="7.5">the ALU does the math or logic,</text>
      <text x="369" y="366" font-size="7.5">or a value moves</text>
      <text x="369" y="386" font-size="7.5" opacity="0.9">add · compare · move a value ·</text>
      <text x="369" y="398" font-size="7.5" opacity="0.9">jump somewhere else</text>
    </g>

    <g text-anchor="middle" fill="currentColor">
      <text x="481" y="206" font-size="10.5" font-weight="700" fill="#7c5cff">CLOCK — the metronome</text>
      <text x="481" y="222" font-size="7">ticks a fixed number of times per second;</text>
      <text x="481" y="234" font-size="7">each tick pushes the cycle forward</text>
      <text x="481" y="266" font-size="8">Hz (hertz) = ticks per second</text>
      <text x="481" y="286" font-size="9" font-weight="700" fill="#7c5cff">3.5 GHz = 3.5 BILLION ticks/second</text>
    </g>
    <g stroke="#7c5cff" stroke-width="1.4" stroke-opacity="0.55">
      <path d="M392 242 L392 252"/><path d="M406 242 L406 252"/><path d="M420 242 L420 252"/><path d="M434 242 L434 252"/>
      <path d="M448 242 L448 252"/><path d="M462 242 L462 252"/><path d="M476 242 L476 252"/><path d="M490 242 L490 252"/>
      <path d="M504 242 L504 252"/><path d="M518 242 L518 252"/><path d="M532 242 L532 252"/><path d="M546 242 L546 252"/>
      <path d="M560 242 L560 252"/><path d="M574 242 L574 252"/>
    </g>

    <g text-anchor="middle" font-size="7" fill="currentColor" opacity="0.85">
      <text x="640" y="118">the fetched</text>
      <text x="640" y="130">bytes move on</text>
      <text x="640" y="142">to be decoded</text>
      <text x="509" y="458" fill="#7c5cff" font-weight="700" opacity="1">control signals</text>
      <text x="250" y="234">loop again:</text>
      <text x="250" y="247">the program</text>
      <text x="250" y="260">counter now</text>
      <text x="250" y="273">points at the</text>
      <text x="250" y="286">next one</text>
    </g>
    <g font-size="7" font-weight="700" fill="#0fa07f">
      <text x="312" y="438">the result lands</text>
      <text x="312" y="449">in a register</text>
    </g>
    <text x="868" y="462" text-anchor="end" font-size="7.5" fill="currentColor" opacity="0.7">the three parts of the chip these steps actually run on</text>

    <g text-anchor="middle" fill="currentColor">
      <text x="328" y="492" font-size="10" font-weight="700" fill="#7c5cff">REGISTERS</text>
      <text x="328" y="508" font-size="7">a handful of tiny, ultra-fast</text>
      <text x="328" y="520" font-size="7">storage slots INSIDE the CPU</text>
      <text x="328" y="532" font-size="7">holding the few numbers it is</text>
      <text x="328" y="544" font-size="7">working on right now</text>
      <text x="328" y="558" font-size="7" font-weight="700" fill="#0fa07f">→ where the result lands</text>

      <text x="548" y="492" font-size="10" font-weight="700" fill="#7c5cff">ALU</text>
      <text x="548" y="508" font-size="7">Arithmetic Logic Unit</text>
      <text x="548" y="520" font-size="7">the adder/comparator from</text>
      <text x="548" y="532" font-size="7">lesson 3 — it does the actual</text>
      <text x="548" y="544" font-size="7">math and logic</text>
      <text x="548" y="558" font-size="7" font-weight="700" fill="#7c5cff">→ the muscle of EXECUTE</text>

      <text x="768" y="492" font-size="10" font-weight="700" fill="#7c5cff">CONTROL UNIT</text>
      <text x="768" y="508" font-size="7">the coordinator</text>
      <text x="768" y="520" font-size="7">fetches instructions and tells</text>
      <text x="768" y="532" font-size="7">the ALU and registers what to do</text>
      <text x="768" y="544" font-size="7">it is what DECODE means</text>
      <text x="768" y="558" font-size="7" font-weight="700" fill="#7c5cff">→ drives FETCH and DECODE</text>
    </g>
  </g>
  <text x="450" y="602" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">This is the entire job of a CPU: fetch, decode, execute — then round again, with nothing else in between.</text>
  <text x="450" y="620" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">At 3.5 GHz the clock ticks 3.5 billion times a second, and every tick pushes this loop one step further round.</text>
  <text x="450" y="638" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.75">A core is one complete copy of this ring — an 8-core chip runs eight of them at the very same instant.</text>
</svg>
```

1. **Fetch** the next instruction from memory (a *program counter* tracks which one).
2. **Decode** it — figure out what operation it is and what it acts on.
3. **Execute** it — add, compare, move a value, or jump somewhere else.
4. Repeat, forever, billions of times a second.

Instructions are just **numbers** (bytes — lesson 1). Each CPU understands a fixed
vocabulary of them called its **instruction set** (like x86 or ARM). Your Python or Go is
translated down to these before the CPU ever runs it.

### Clock speed: what "GHz" means

The CPU is driven by a **clock** — a signal that ticks a fixed number of times per second,
like a metronome. Each tick pushes the cycle forward. **Hertz (Hz)** = ticks per second, so
**3.5 GHz = 3.5 billion ticks per second.** More ticks per second means more steps per
second — roughly, a faster CPU.

But GHz isn't the whole story: a CPU can also do **more work per tick** (called IPC —
instructions per cycle). A well-designed 3 GHz chip can out-run a lazy 4 GHz one. So clock
speed is *one* dimension of speed, not the only one (lesson 8 compares them properly).

### Cores: doing several things *truly* at once

Lesson 9 will show the **OS** (operating system) *juggling* many programs on one CPU by
switching fast (an illusion of simultaneity). A **core** is different: it's a *complete* CPU — its own
fetch–decode–execute loop. A modern chip packs **multiple cores** (4, 8, 16…), so an
8-core CPU genuinely runs **8 instruction streams at the same instant** — real
parallelism. This is *why* backends run several worker processes/threads: to actually use
all the cores instead of leaving them idle.

### Cache: closing the gap to memory

The CPU is far faster than the **RAM** (random-access memory) it reads from, so it would spend most of its time
*waiting*. To fix that, a CPU keeps a small, very fast **cache** of recently-used data
right on the chip. When the data it needs is already in cache (a "hit"), it barely waits;
when it isn't (a "miss"), it pays the full cost of going to RAM. Keeping data cache-friendly
is a real backend performance lever — and the reason the next lesson's *memory hierarchy*
matters so much.

## Build It

A CPU is just fetch–decode–execute over a list of instructions — so you can build a tiny
one in Python. [`code/mini_cpu.py`](../code/mini_cpu.py) runs a little "program" of
`(operation, arguments)` instructions against a set of registers:

```python
def run(program):
    regs = {"A": 0, "B": 0}
    pc = 0                              # program counter: the next instruction
    while pc < len(program):
        op, *args = program[pc]        # FETCH
        if   op == "SET":   regs[args[0]] = args[1]          # DECODE + EXECUTE
        elif op == "ADD":   regs[args[0]] += regs[args[1]]
        elif op == "PRINT": print("   ", args[0], "=", regs[args[0]])
        pc += 1                        # advance to the next instruction
    return regs

run([("SET","A",5), ("SET","B",6), ("ADD","A","B"), ("PRINT","A")])   # A = 11
```

**Think about it:**

1. What are the three steps the CPU repeats, over and over?
2. A 4 GHz CPU is sometimes slower than a 3 GHz one. Name one reason (hint: work per tick).
3. Your server does heavy work but uses only 1 of its 8 cores. What are the other 7 doing,
   and what should you change?

## Key takeaways

- The **CPU** is built from gates: an **ALU** (math/logic), **registers** (tiny fast
  storage), and a **control unit**.
- It repeats the **fetch–decode–execute** cycle billions of times a second, running
  numeric **instructions** from its **instruction set**.
- **Clock speed (GHz)** = ticks per second — more steps per second — but **work per tick
  (IPC)** matters too.
- **Cores** are complete CPUs on one chip; N cores run N instruction streams *truly* at
  once — why backends run multiple workers.
- **Cache** (fast on-chip memory) hides RAM's slowness; cache-friendliness is a real
  performance lever.

Next: [RAM & the Memory Hierarchy](../06-ram-and-memory-hierarchy/) — where the CPU keeps the
data it isn't holding in registers, and why every level is a speed/price trade-off.
