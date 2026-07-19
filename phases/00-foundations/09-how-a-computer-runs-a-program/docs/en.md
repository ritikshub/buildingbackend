# How a Computer Runs a Program

> You now know the CPU and the RAM. This is how your *software* actually gets onto them — how bytes on disk wake up, become a running process, and get managed by the operating system.

**Type:** Learn
**Languages:** Python
**Prerequisites:** [The CPU](../05-the-cpu/), [RAM & the Memory Hierarchy](../06-ram-and-memory-hierarchy/)
**Time:** ~45 minutes

## The Problem

You've met the hardware: a CPU that runs a fetch–decode–execute loop (lesson 5), and RAM
that holds working data (lesson 6). But your *program* is just a file of bytes sitting on
disk. What does it actually mean to **"run"** it? How do those bytes become a live thing
using the CPU and RAM — and who's in charge of it all?

If "running a program" is a black box, then every crash, every "out of memory," every
"why is my server slow" is a mystery. Open the box and a backend stops being magic: it's a
**process**, living in RAM, executed by the CPU, managed by the **operating system**.

## The Concept

### Running a program: disk → RAM → CPU

A program on disk is inert — just bytes (lesson 1). To run it, the **operating system**
copies its bytes from disk into **RAM**, then points the **CPU** at the first instruction:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 572" width="100%" style="max-width:880px" role="img" aria-label="Running a program, drawn as a vertical hierarchy with the disk at the bottom, RAM in the middle and the CPU at the top, so it rhymes with the memory hierarchy of lesson 6. At the bottom, the disk is a physical device holding your program as a file: a run of twelve bytes, shown in gray as 55 89 E5 8B 45 08 01 02 03 04 05 0F. Nothing is running; the file is inert. An arrow upward is labelled: the operating system LOADS it, copying those bytes from disk into RAM and then pointing the CPU at the first instruction. In RAM the very same twelve bytes are now two things. The first six are INSTRUCTIONS, what to do, drawn in blue, meaningless until the CPU decodes them. The last six are DATA, the values the program works on, drawn in green: 01 02 03 04 05 are the Try It loop's values one through five, and 0F is its total, fifteen, written in hexadecimal from lesson 1. A second arrow upward is labelled: the CPU FETCHES, reading instruction bytes out of RAM one at a time, and the file on disk is never touched again. At the top, the CPU runs the fetch, decode, execute loop you built in lesson 5: FETCH gets the next instruction from RAM, DECODE works out what the byte means, EXECUTE has the ALU, the Arithmetic Logic Unit, carry it out, and the loop repeats forever, one instruction at a time. The point is that no byte is ever transformed: the same bytes sit on disk, in RAM and in the CPU, and only their location and their role change.">
  <defs>
    <marker id="p0l09a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p0l09a-arb" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Running a program: the OS copies the same bytes disk → RAM → CPU</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g fill="none" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4">
      <path d="M36 440 L36 70" marker-end="url(#p0l09a-ar)"/>
    </g>
    <text transform="rotate(-90 18 255)" x="18" y="255" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.72">up the memory hierarchy (lesson 6) — closer to the CPU, faster, smaller</text>

    <g fill="none" stroke-linejoin="round" stroke-width="2">
      <rect x="58" y="56" width="822" height="138" rx="12" fill="#7c5cff" fill-opacity="0.07" stroke="#7c5cff"/>
      <rect x="58" y="234" width="822" height="138" rx="12" fill="#7c5cff" fill-opacity="0.07" stroke="#7c5cff"/>
      <rect x="58" y="412" width="822" height="88" rx="12" fill="#7c5cff" fill-opacity="0.07" stroke="#7c5cff"/>
    </g>

    <text x="76" y="78" font-size="11.5" font-weight="700" fill="#7c5cff">CPU</text>
    <text x="76" y="96" font-size="9" fill="currentColor">executes ONE instruction</text>
    <text x="76" y="110" font-size="9" fill="currentColor">at a time</text>
    <text x="76" y="134" font-size="8.5" fill="currentColor" opacity="0.78">it never runs the file on disk —</text>
    <text x="76" y="147" font-size="8.5" fill="currentColor" opacity="0.78">only this copy, now in RAM</text>

    <text x="565" y="76" text-anchor="middle" font-size="9" font-weight="700" fill="currentColor" opacity="0.85">the fetch → decode → execute loop you built in lesson 5</text>
    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="310" y="84" width="150" height="52" rx="9" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="490" y="84" width="150" height="52" rx="9" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
      <rect x="670" y="84" width="150" height="52" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    </g>
    <g text-anchor="middle">
      <text x="385" y="102" font-size="10.5" font-weight="700" fill="#3553ff">FETCH</text>
      <text x="385" y="116" font-size="7.8" fill="currentColor">get the next</text>
      <text x="385" y="128" font-size="7.8" fill="currentColor">instruction from RAM</text>
      <text x="565" y="102" font-size="10.5" font-weight="700" fill="currentColor">DECODE</text>
      <text x="565" y="116" font-size="7.8" fill="currentColor">what does this</text>
      <text x="565" y="128" font-size="7.8" fill="currentColor">byte actually mean?</text>
      <text x="745" y="102" font-size="10.5" font-weight="700" fill="#0fa07f">EXECUTE</text>
      <text x="745" y="116" font-size="7.8" fill="currentColor">the ALU (Arithmetic</text>
      <text x="745" y="128" font-size="7.8" fill="currentColor">Logic Unit) does it</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M462 110 L486 110" marker-end="url(#p0l09a-ar)"/>
      <path d="M642 110 L666 110" marker-end="url(#p0l09a-ar)"/>
      <path d="M745 136 L745 158 L385 158 L385 140" marker-end="url(#p0l09a-ar)"/>
    </g>
    <text x="565" y="174" text-anchor="middle" font-size="8.5" font-weight="700" fill="currentColor" opacity="0.85">repeat — one instruction at a time, for as long as the program lives</text>

    <g fill="none" stroke="#3553ff" stroke-width="2">
      <path d="M160 230 L160 198" marker-end="url(#p0l09a-arb)"/>
    </g>
    <text x="186" y="212" font-size="10" font-weight="700" fill="#3553ff">the CPU FETCHES</text>
    <text x="186" y="226" font-size="8.5" fill="currentColor" opacity="0.82">reads instruction bytes out of RAM, one at a time — the file on disk is never touched again</text>

    <text x="76" y="256" font-size="11.5" font-weight="700" fill="#7c5cff">RAM</text>
    <text x="76" y="274" font-size="9" fill="currentColor">the running program lives here:</text>
    <text x="76" y="289" font-size="9" font-weight="700" fill="currentColor">instructions + data</text>
    <text x="76" y="304" font-size="9" fill="currentColor">— and both are just bytes</text>
    <text x="76" y="328" font-size="8.5" fill="currentColor" opacity="0.78">the same 12 bytes as on disk,</text>
    <text x="76" y="341" font-size="8.5" fill="currentColor" opacity="0.78">copied, not changed</text>

    <g fill="none" stroke-linejoin="round" stroke-width="1.7">
      <rect x="292" y="262" width="268" height="96" rx="9" fill="#3553ff" fill-opacity="0.06" stroke="#3553ff" stroke-opacity="0.85"/>
      <rect x="570" y="262" width="268" height="96" rx="9" fill="#0fa07f" fill-opacity="0.06" stroke="#0fa07f" stroke-opacity="0.85"/>
    </g>
    <text x="426" y="280" text-anchor="middle" font-size="10.5" font-weight="700" fill="#3553ff">INSTRUCTIONS — what to do</text>
    <text x="704" y="280" text-anchor="middle" font-size="10.5" font-weight="700" fill="#0fa07f">DATA — the values it works on</text>

    <g fill="none" stroke="#3553ff" stroke-width="1.5">
      <rect x="300" y="290" width="42" height="28" rx="5" fill="#3553ff" fill-opacity="0.14"/>
      <rect x="342" y="290" width="42" height="28" rx="5" fill="#3553ff" fill-opacity="0.14"/>
      <rect x="384" y="290" width="42" height="28" rx="5" fill="#3553ff" fill-opacity="0.14"/>
      <rect x="426" y="290" width="42" height="28" rx="5" fill="#3553ff" fill-opacity="0.14"/>
      <rect x="468" y="290" width="42" height="28" rx="5" fill="#3553ff" fill-opacity="0.14"/>
      <rect x="510" y="290" width="42" height="28" rx="5" fill="#3553ff" fill-opacity="0.14"/>
    </g>
    <g fill="none" stroke="#0fa07f" stroke-width="1.5">
      <rect x="578" y="290" width="42" height="28" rx="5" fill="#0fa07f" fill-opacity="0.14"/>
      <rect x="620" y="290" width="42" height="28" rx="5" fill="#0fa07f" fill-opacity="0.14"/>
      <rect x="662" y="290" width="42" height="28" rx="5" fill="#0fa07f" fill-opacity="0.14"/>
      <rect x="704" y="290" width="42" height="28" rx="5" fill="#0fa07f" fill-opacity="0.14"/>
      <rect x="746" y="290" width="42" height="28" rx="5" fill="#0fa07f" fill-opacity="0.14"/>
      <rect x="788" y="290" width="42" height="28" rx="5" fill="#0fa07f" fill-opacity="0.14"/>
    </g>
    <g text-anchor="middle" font-size="10.5" font-weight="700" fill="currentColor">
      <text x="321" y="309">55</text><text x="363" y="309">89</text><text x="405" y="309">E5</text>
      <text x="447" y="309">8B</text><text x="489" y="309">45</text><text x="531" y="309">08</text>
      <text x="599" y="309">01</text><text x="641" y="309">02</text><text x="683" y="309">03</text>
      <text x="725" y="309">04</text><text x="767" y="309">05</text><text x="809" y="309">0F</text>
    </g>
    <g text-anchor="middle" fill="currentColor">
      <text x="426" y="336" font-size="8.5">meaningless bytes until the CPU decodes them</text>
      <text x="426" y="350" font-size="8" opacity="0.75">these are what FETCH pulls up, one by one</text>
      <text x="704" y="336" font-size="8.5">the Try It loop's values 1–5 (01–05)</text>
      <text x="704" y="350" font-size="8" opacity="0.75">and its total 15 (0F in hex — lesson 1)</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="2">
      <path d="M160 408 L160 376" marker-end="url(#p0l09a-ar)"/>
    </g>
    <text x="186" y="390" font-size="10" font-weight="700" fill="currentColor">the OS LOADS it</text>
    <text x="186" y="404" font-size="8.5" fill="currentColor" opacity="0.82">copies the bytes from disk into RAM, then points the CPU at the first instruction</text>

    <text x="76" y="436" font-size="11.5" font-weight="700" fill="#7c5cff">DISK</text>
    <text x="76" y="454" font-size="9" fill="currentColor">your program is a file:</text>
    <text x="76" y="468" font-size="9" fill="currentColor">a run of bytes, nothing more</text>
    <text x="76" y="486" font-size="9" font-weight="700" fill="#7f7f7f">INERT — nothing runs yet</text>

    <g fill="none" stroke="#7f7f7f" stroke-width="1.5">
      <rect x="300" y="428" width="42" height="28" rx="5" fill="#7f7f7f" fill-opacity="0.12"/>
      <rect x="342" y="428" width="42" height="28" rx="5" fill="#7f7f7f" fill-opacity="0.12"/>
      <rect x="384" y="428" width="42" height="28" rx="5" fill="#7f7f7f" fill-opacity="0.12"/>
      <rect x="426" y="428" width="42" height="28" rx="5" fill="#7f7f7f" fill-opacity="0.12"/>
      <rect x="468" y="428" width="42" height="28" rx="5" fill="#7f7f7f" fill-opacity="0.12"/>
      <rect x="510" y="428" width="42" height="28" rx="5" fill="#7f7f7f" fill-opacity="0.12"/>
      <rect x="578" y="428" width="42" height="28" rx="5" fill="#7f7f7f" fill-opacity="0.12"/>
      <rect x="620" y="428" width="42" height="28" rx="5" fill="#7f7f7f" fill-opacity="0.12"/>
      <rect x="662" y="428" width="42" height="28" rx="5" fill="#7f7f7f" fill-opacity="0.12"/>
      <rect x="704" y="428" width="42" height="28" rx="5" fill="#7f7f7f" fill-opacity="0.12"/>
      <rect x="746" y="428" width="42" height="28" rx="5" fill="#7f7f7f" fill-opacity="0.12"/>
      <rect x="788" y="428" width="42" height="28" rx="5" fill="#7f7f7f" fill-opacity="0.12"/>
    </g>
    <g text-anchor="middle" font-size="10.5" font-weight="700" fill="currentColor" opacity="0.85">
      <text x="321" y="447">55</text><text x="363" y="447">89</text><text x="405" y="447">E5</text>
      <text x="447" y="447">8B</text><text x="489" y="447">45</text><text x="531" y="447">08</text>
      <text x="599" y="447">01</text><text x="641" y="447">02</text><text x="683" y="447">03</text>
      <text x="725" y="447">04</text><text x="767" y="447">05</text><text x="809" y="447">0F</text>
    </g>
    <text x="565" y="476" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.9">the SAME 12 bytes you just saw in RAM and in the CPU — one file, not yet split into anything</text>
    <text x="565" y="490" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.68">(the byte values are illustrative — a real binary is millions of them)</text>
  </g>
  <text x="450" y="524" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Nothing is transformed: the same bytes sit on disk, in RAM, and inside the CPU — only their location and role change.</text>
  <text x="450" y="542" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">A running program is instructions + data in memory; the CPU just walks the instructions, one at a time.</text>
  <text x="450" y="562" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.72">That is all "running" means — which is why a crash, an out-of-memory, or a slow server stops being magic.</text>
</svg>
```

A running program is therefore two things sitting in memory: **instructions** (what to do)
and **data** (the values it works on) — both just bytes. The CPU fetches those instructions
from RAM and executes them, exactly as you built in lesson 5.

### A process and its memory layout

A running program is called a **process**: it gets its own identity (a **PID**, process
ID) and its own **protected slice of RAM** that no other process can touch. That slice is
organized into four regions — worth knowing because backend bugs live here:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 570" width="100%" style="max-width:880px" role="img" aria-label="The memory layout of one process, drawn as a real vertical address space with high addresses at the top and low addresses at the bottom. The whole map is outlined in purple because it is the process's own protected slice of RAM, identified by a PID or process ID, that no other process can touch. From the top down there are five bands. First the STACK: local variables, call frames and where to return to, a scratchpad that grows on every function call and shrinks on return. It grows at runtime downward, and a real amber arrow points down out of the stack into the space below it. Next the FREE SPACE, an amber dashed band: unallocated room that the stack and the heap share, and the note says that exhausting this gap kills the process. Below it the HEAP: objects, lists and buffers, memory the program asks for as it runs. It grows at runtime upward, and a second amber arrow points up out of the heap into the same free gap, so the two arrows aim at each other from opposite ends. Below the heap is DATA, the global and constant values, marked fixed size in green. At the bottom is CODE, the instructions themselves, read only and loaded from disk, marked fixed size in blue. To the right are three callouts. Beside the stack, in red: STACK OVERFLOW, when infinite recursion keeps pushing frames until the gap runs out. Beside the gap, a legend contrasting fixed regions, code and data, decided when the program loads, with growing regions, heap and stack, which grow at runtime toward each other. Beside the heap, in red: MEMORY LEAK, when you forget to release memory so the heap grows forever, and running out gets the process killed for being out of memory.">
  <defs>
    <marker id="p0l09b-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p0l09b-arm" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The stack grows DOWN and the heap grows UP — into the same free gap</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <text x="411" y="46" text-anchor="middle" font-size="9.5" font-weight="700" fill="#7c5cff">one process = its own protected slice of RAM, with its own PID (process ID) — no other process can touch it</text>

    <text x="190" y="64" text-anchor="end" font-size="9" font-weight="700" fill="currentColor" opacity="0.85">HIGH addresses</text>
    <text x="190" y="490" text-anchor="end" font-size="9" font-weight="700" fill="currentColor" opacity="0.85">LOW addresses</text>
    <g fill="none" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4">
      <path d="M160 78 L160 476" marker-end="url(#p0l09b-ar)"/>
    </g>
    <text transform="rotate(-90 124 274)" x="124" y="274" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.75">the address space of ONE process</text>

    <g fill="none" stroke-linejoin="round" stroke-width="2">
      <rect x="196" y="56" width="430" height="436" rx="12" fill="#7c5cff" fill-opacity="0.05" stroke="#7c5cff"/>
    </g>

    <g fill="none" stroke-linejoin="round" stroke-width="1.7">
      <rect x="204" y="62" width="414" height="74" rx="8" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
      <rect x="204" y="136" width="414" height="152" rx="8" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f" stroke-dasharray="7 6"/>
      <rect x="204" y="288" width="414" height="74" rx="8" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
      <rect x="204" y="362" width="414" height="62" rx="8" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="204" y="424" width="414" height="62" rx="8" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/>
    </g>

    <text x="216" y="82" font-size="11.5" font-weight="700" fill="currentColor">STACK</text>
    <text x="216" y="98" font-size="9" fill="currentColor" opacity="0.9">local variables, call frames, where to return to</text>
    <text x="216" y="112" font-size="9" fill="currentColor" opacity="0.9">a scratchpad: grows on every call, shrinks on return</text>
    <text x="216" y="128" font-size="8.5" font-weight="700" fill="#e0930f">GROWS AT RUNTIME · downward</text>

    <text x="350" y="170" text-anchor="middle" font-size="11.5" font-weight="700" fill="#e0930f">FREE SPACE</text>
    <text x="350" y="188" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.9">unallocated — the room the two share</text>
    <text x="350" y="204" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.9">the stack grows DOWN into it</text>
    <text x="350" y="220" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.9">the heap grows UP into it</text>
    <text x="350" y="244" text-anchor="middle" font-size="9.5" font-weight="700" fill="#d64545">exhaust this gap and the process dies</text>
    <text x="350" y="262" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">nobody owns it — whichever side grows first takes it</text>

    <g fill="none" stroke="#e0930f" stroke-width="2.4">
      <path d="M520 140 L520 198" marker-end="url(#p0l09b-arm)"/>
      <path d="M520 284 L520 226" marker-end="url(#p0l09b-arm)"/>
    </g>
    <text x="534" y="160" font-size="8.5" font-weight="700" fill="#e0930f">stack grows</text>
    <text x="534" y="172" font-size="8.5" font-weight="700" fill="#e0930f">downward</text>
    <text x="534" y="252" font-size="8.5" font-weight="700" fill="#e0930f">heap grows</text>
    <text x="534" y="264" font-size="8.5" font-weight="700" fill="#e0930f">upward</text>

    <text x="216" y="306" font-size="11.5" font-weight="700" fill="currentColor">HEAP</text>
    <text x="216" y="322" font-size="9" fill="currentColor" opacity="0.9">objects, lists, buffers — memory the program</text>
    <text x="216" y="338" font-size="9" fill="currentColor" opacity="0.9">requests as it runs, and holds until it releases it</text>
    <text x="216" y="354" font-size="8.5" font-weight="700" fill="#e0930f">GROWS AT RUNTIME · upward</text>

    <text x="216" y="384" font-size="11.5" font-weight="700" fill="currentColor">DATA</text>
    <text x="216" y="400" font-size="9" fill="currentColor" opacity="0.9">global and constant values</text>
    <text x="216" y="416" font-size="8.5" font-weight="700" fill="#0fa07f">FIXED SIZE — set when the program loads</text>

    <text x="216" y="446" font-size="11.5" font-weight="700" fill="currentColor">CODE</text>
    <text x="216" y="462" font-size="9" fill="currentColor" opacity="0.9">the instructions themselves — the bytes the CPU fetches</text>
    <text x="216" y="478" font-size="8.5" font-weight="700" fill="#3553ff">FIXED SIZE — read-only, loaded from disk</text>

    <g fill="none" stroke-linejoin="round" stroke-width="1.6">
      <rect x="640" y="62" width="244" height="62" rx="9" fill="#d64545" fill-opacity="0.07" stroke="#d64545" stroke-opacity="0.75"/>
      <rect x="640" y="150" width="244" height="112" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="#7f7f7f" stroke-opacity="0.75"/>
      <rect x="640" y="288" width="244" height="74" rx="9" fill="#d64545" fill-opacity="0.07" stroke="#d64545" stroke-opacity="0.75"/>
      <rect x="640" y="372" width="244" height="110" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="#7f7f7f" stroke-opacity="0.75"/>
    </g>

    <text x="652" y="82" font-size="9.5" font-weight="700" fill="#d64545">STACK OVERFLOW</text>
    <text x="652" y="98" font-size="8.5" fill="currentColor" opacity="0.9">infinite recursion keeps pushing</text>
    <text x="652" y="112" font-size="8.5" fill="currentColor" opacity="0.9">frames until the gap runs out</text>

    <text x="652" y="172" font-size="9.5" font-weight="700" fill="currentColor">FIXED vs GROWING</text>
    <text x="652" y="192" font-size="8.5" font-weight="700" fill="#3553ff">CODE + DATA — fixed size,</text>
    <text x="652" y="206" font-size="8.5" fill="currentColor" opacity="0.9">decided when the program loads</text>
    <text x="652" y="226" font-size="8.5" font-weight="700" fill="#e0930f">HEAP + STACK — grow at runtime,</text>
    <text x="652" y="240" font-size="8.5" fill="currentColor" opacity="0.9">toward each other</text>
    <text x="652" y="256" font-size="8" fill="currentColor" opacity="0.75">only these two can run you out of room</text>

    <text x="652" y="308" font-size="9.5" font-weight="700" fill="#d64545">MEMORY LEAK</text>
    <text x="652" y="324" font-size="8.5" fill="currentColor" opacity="0.9">forget to release and the heap</text>
    <text x="652" y="338" font-size="8.5" fill="currentColor" opacity="0.9">grows forever; run out and the</text>
    <text x="652" y="352" font-size="8.5" fill="currentColor" opacity="0.9">process is KILLED (out of memory)</text>

    <text x="652" y="396" font-size="9.5" font-weight="700" fill="currentColor">LOADED FROM THE FILE</text>
    <text x="652" y="416" font-size="8.5" fill="currentColor" opacity="0.9">these two regions are the bytes</text>
    <text x="652" y="432" font-size="8.5" fill="currentColor" opacity="0.9">the OS copied off disk (above)</text>
    <text x="652" y="452" font-size="8.5" fill="currentColor" opacity="0.78">the heap and the stack did not</text>
    <text x="652" y="468" font-size="8.5" fill="currentColor" opacity="0.78">exist until the process started</text>
  </g>
  <text x="450" y="522" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">The stack grows DOWN and the heap grows UP — they eat into the same free gap from opposite ends.</text>
  <text x="450" y="540" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Code and data are fixed the moment the program loads; only the heap and the stack change size while it runs.</text>
  <text x="450" y="560" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.72">Most backend memory bugs are one of these two arrows never stopping: runaway recursion, or memory you never released.</text>
</svg>
```

*The diagram is drawn with high memory addresses at the top.* The **stack** starts high and
grows **downward** with each function call; the **heap** sits below it and grows **upward** as
you allocate. The two grow toward the free space between them — exhaust that gap and the
process dies.

- **Code** — the instructions themselves.
- **Data** — global and constant values.
- **Heap** — memory the program requests as it runs (your objects, lists, buffers). Forget
  to release it and you get a **memory leak**; run out and the process is killed.
- **Stack** — a scratchpad that grows with every function call and shrinks when it returns
  (local variables, where to return to). Infinite recursion overflows it — a **stack
  overflow**.

### The Operating System: the manager

You run many programs "at once" — a browser, an editor, your server — but there are only a
handful of CPU cores. The **operating system (OS)** — Linux, macOS, Windows — is the
manager that makes this work:

- **Loads** programs from disk into RAM and starts them.
- **Shares the CPU** by rapidly switching it between processes (so fast it *looks*
  simultaneous — that illusion is **concurrency**).
- **Isolates** each process's memory, so one program can't corrupt another (or the whole
  machine).
- **Mediates hardware.** A program can't touch the disk or network directly; it asks the OS
  through a **system call**, and the OS does it safely. (This split — your code in "user
  mode," the OS in privileged "kernel mode" — is why one crashing program doesn't take down
  the computer.)

### Processes and threads

A **process** is one running program with its own memory (above). A process can also split
its work into multiple **threads** that run inside it and **share its memory**. Threads are
how one program does several things at once — e.g. a server handling many users. Sharing
memory is powerful and dangerous (two threads touching the same data is a whole class of
bugs), which is why **Phase 8** is devoted to concurrency. For now: **process = a running
program; thread = a worker inside it.**

### Why this matters for backend

A backend server is just a **long-running process** waiting for requests, and its two hard
limits are the two resources you already know:

- **CPU** — if the work per request is too heavy, the CPU pegs at 100% and requests queue.
- **RAM** — if the process needs more memory than exists, it slows to a crawl or is killed
  ("out of memory").

"Scaling a backend" comes down to these two numbers, plus how many **processes and threads**
you run across the CPU's cores (lesson 5). You'll hear this for the rest of the curriculum.

## Try It

Python is itself a program — a running process executing *your* bytes. Peek at it with
[`code/runs_a_program.py`](../code/runs_a_program.py):

```python
import os, sys

print("This script runs inside process id (PID):", os.getpid())
print("The program executing my code:", sys.executable)  # the python binary on disk

# 'total' lives in RAM; the loop is instructions the CPU fetches and runs.
total = 0
for i in range(1, 6):
    total += i          # one instruction the CPU executes, over and over
print("The CPU stepped through a loop and computed:", total)  # 15
```

**Think about it:**

1. Your laptop runs 200 "programs" but has 8 CPU cores. How is that possible?
2. A program keeps allocating memory and never releasing it. Which region of its memory
   grows without bound, and what's that bug called?
3. A server process is using 100% CPU *and* only 5% of its memory. Which resource is the
   bottleneck — and would adding RAM help?

## Key takeaways

- To **run** a program, the OS copies its bytes from disk into RAM and points the CPU at
  the first instruction; a running program is **instructions + data in memory**.
- A **process** has a PID and its own protected memory, laid out as **code / data / heap /
  stack** — where memory leaks and stack overflows happen.
- The **OS** loads programs, **shares the CPU** (concurrency), **isolates** memory, and
  mediates hardware through **system calls**.
- A **process** is a running program; **threads** are workers inside it that share its
  memory (the root of concurrency, Phase 8).
- A backend is a long-running process bounded by **CPU and RAM**; scaling is about those
  plus processes/threads across cores.

Next: [Files & the Filesystem](../10-files-and-the-filesystem/) — how bytes survive after the
power goes out.
