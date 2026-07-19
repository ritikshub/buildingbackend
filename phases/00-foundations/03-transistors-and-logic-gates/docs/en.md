# Transistors & Logic Gates

> A computer has no idea what a number is. It only has switches. This is the story of how one tiny electrical switch — the transistor — becomes logic, and how logic becomes everything a computer does.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Bits & Bytes](../01-bits-and-bytes/)
**Time:** ~50 minutes

## The Problem

Lesson 1 said a computer is a huge pile of on/off switches, and every bit is one switch.
Fine — but a light switch doesn't *do* anything. How do you get from "a switch is on or
off" to a machine that adds numbers, makes decisions, and runs your code? What is the
switch actually *made of*, and how do switches add up to a computer?

This lesson bridges that gap — from a single physical switch to real arithmetic — and
you'll build the arithmetic yourself from nothing but three logic operations.

## The Concept

### The transistor: a switch with no moving parts

A **transistor** is a tiny switch made from a special material (silicon — next lesson).
It has three connections. A small voltage on one of them (the **gate**) controls whether
electricity can flow between the other two. Apply voltage → current flows (**on**, `1`).
No voltage → no current (**off**, `0`).

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 464" width="100%" style="max-width:880px" role="img" aria-label="A transistor drawn as a real switch, in its two states side by side. In both panels the same three connections appear: a gate at the top, and an input on the left and an output on the right, with the current path running horizontally between them. The gate line comes down perpendicular to that path and ends in a flat plate above it, so the control never touches the current it controls. Left panel, gate voltage on equals 1: the gate's field closes the switch, the bar bridges the two terminals, current flows all the way from in to out, and out equals 1. Right panel, no voltage equals 0: nothing pushes the switch shut, the bar is lifted and there is a real gap between it and the far terminal, so no current flows and out equals 0. The transistor itself is identical in both panels; only the voltage on the gate differs. Underneath are the two things that make it different from a light switch: it is controlled by electricity rather than a finger, so one transistor can flip another and circuits can control themselves; and it is astonishingly small and fast, with billions fitting on a fingernail-sized chip and each switching billions of times per second.">
  <defs>
    <marker id="p0l03a-arb" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">A transistor is a switch that a voltage flips — not a finger</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="20" y="44" width="420" height="262" rx="12" fill="#0fa07f" fill-opacity="0.05" stroke="#0fa07f" stroke-opacity="0.75"/>
      <rect x="460" y="44" width="420" height="262" rx="12" fill="#e0930f" fill-opacity="0.05" stroke="#e0930f" stroke-opacity="0.75"/>
    </g>

    <text x="230" y="68" text-anchor="middle" font-size="12.5" font-weight="700" fill="#0fa07f">GATE VOLTAGE ON = 1</text>
    <text x="230" y="84" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">a small voltage on the third connection</text>
    <text x="670" y="68" text-anchor="middle" font-size="12.5" font-weight="700" fill="#e0930f">GATE VOLTAGE OFF = 0</text>
    <text x="670" y="84" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">the very same transistor, nothing on the gate</text>

    <g fill="none" stroke-linejoin="round" stroke-width="1.7">
      <rect x="150" y="94" width="160" height="32" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="590" y="94" width="160" height="32" rx="8" fill="#3553ff" fill-opacity="0.06" stroke="#3553ff" stroke-opacity="0.5"/>
    </g>
    <text x="230" y="114" text-anchor="middle" font-size="10.5" font-weight="700" fill="#3553ff">gate (control)</text>
    <text x="670" y="114" text-anchor="middle" font-size="10.5" font-weight="700" fill="#3553ff" opacity="0.65">gate (control)</text>

    <path d="M230 126 V156" fill="none" stroke="#3553ff" stroke-width="2.4" marker-end="url(#p0l03a-arb)"/>
    <path d="M670 126 V156" fill="none" stroke="#3553ff" stroke-width="2.4" stroke-opacity="0.3"/>
    <text x="243" y="142" font-size="9.5" font-weight="700" fill="#3553ff">voltage ON = 1</text>
    <text x="243" y="155" font-size="8" fill="currentColor" opacity="0.8">electricity, not a finger</text>
    <text x="683" y="142" font-size="9.5" font-weight="700" fill="#e0930f">no voltage = 0</text>
    <text x="683" y="155" font-size="8" fill="currentColor" opacity="0.8">nothing pushes it shut</text>

    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="162" y="158" width="136" height="76" rx="10" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff"/>
      <rect x="602" y="158" width="136" height="76" rx="10" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff"/>
    </g>

    <path d="M190 176 H270" fill="none" stroke="#3553ff" stroke-width="4.5" stroke-linecap="round"/>
    <path d="M630 176 H710" fill="none" stroke="#3553ff" stroke-width="4.5" stroke-linecap="round" stroke-opacity="0.35"/>

    <g fill="none" stroke="#3553ff" stroke-width="1.6">
      <path d="M205 184 V196"/><path d="M230 184 V196"/><path d="M255 184 V196"/>
    </g>
    <g fill="#3553ff">
      <path d="M201.5 196 L208.5 196 L205 201.5 Z"/>
      <path d="M226.5 196 L233.5 196 L230 201.5 Z"/>
      <path d="M251.5 196 L258.5 196 L255 201.5 Z"/>
    </g>

    <path d="M108 214 H186.4" fill="none" stroke="#0fa07f" stroke-width="2.2"/>
    <path d="M273.6 214 H352" fill="none" stroke="#0fa07f" stroke-width="2.2"/>
    <path d="M190 214 H270" fill="none" stroke="#0fa07f" stroke-width="4" stroke-linecap="round"/>
    <g fill="#0fa07f">
      <path d="M143 209.5 L152 214 L143 218.5 Z"/>
      <path d="M306 209.5 L315 214 L306 218.5 Z"/>
    </g>
    <text x="325" y="196" text-anchor="middle" font-size="8" font-weight="700" fill="#0fa07f">current</text>

    <path d="M548 214 H626.4" fill="none" stroke="#7f7f7f" stroke-width="2.2"/>
    <path d="M713.6 214 H792" fill="none" stroke="#7f7f7f" stroke-width="2.2"/>
    <path d="M630 214 L696 194" fill="none" stroke="#e0930f" stroke-width="4" stroke-linecap="round"/>
    <text x="765" y="196" text-anchor="middle" font-size="7.5" font-weight="700" fill="#e0930f">no current</text>
    <text x="703" y="228" text-anchor="middle" font-size="8" font-weight="700" fill="#e0930f">gap</text>

    <g fill="#7c5cff">
      <circle cx="190" cy="214" r="3.6"/><circle cx="270" cy="214" r="3.6"/>
      <circle cx="630" cy="214" r="3.6"/><circle cx="710" cy="214" r="3.6"/>
    </g>

    <g fill="none" stroke-linejoin="round" stroke-width="1.7">
      <rect x="32" y="198" width="76" height="32" rx="8" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/>
      <rect x="352" y="198" width="76" height="32" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="472" y="198" width="76" height="32" rx="8" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/>
      <rect x="792" y="198" width="76" height="32" rx="8" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
    </g>
    <text x="70" y="219" text-anchor="middle" font-size="12" font-weight="700" fill="#3553ff">in</text>
    <text x="390" y="219" text-anchor="middle" font-size="12" font-weight="700" fill="#0fa07f">out = 1</text>
    <text x="510" y="219" text-anchor="middle" font-size="12" font-weight="700" fill="#3553ff">in</text>
    <text x="830" y="219" text-anchor="middle" font-size="12" font-weight="700" fill="#e0930f">out = 0</text>

    <text x="230" y="248" text-anchor="middle" font-size="10" font-weight="700" fill="#7c5cff">TRANSISTOR — a switch made of silicon</text>
    <text x="670" y="248" text-anchor="middle" font-size="10" font-weight="700" fill="#7c5cff">TRANSISTOR — a switch made of silicon</text>
    <text x="230" y="264" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">3 connections: the gate, plus the two the current flows between</text>
    <text x="670" y="264" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">3 connections: the gate, plus the two the current flows between</text>
    <text x="230" y="288" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">voltage on the gate → path CLOSED → current → out = 1</text>
    <text x="670" y="288" text-anchor="middle" font-size="9.5" font-weight="700" fill="#e0930f">no voltage → path OPEN (a real gap) → no current → out = 0</text>

    <g fill="none" stroke-linejoin="round" stroke-width="1.5">
      <rect x="20" y="322" width="420" height="62" rx="10" fill="#7c5cff" fill-opacity="0.06" stroke="#7c5cff" stroke-opacity="0.55"/>
      <rect x="460" y="322" width="420" height="62" rx="10" fill="#7c5cff" fill-opacity="0.06" stroke="#7c5cff" stroke-opacity="0.55"/>
    </g>
    <text x="230" y="344" text-anchor="middle" font-size="10.5" font-weight="700" fill="#7c5cff">Controlled by electricity, not a finger</text>
    <text x="230" y="362" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">so one transistor can flip another —</text>
    <text x="230" y="375" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">circuits can control themselves</text>
    <text x="670" y="344" text-anchor="middle" font-size="10.5" font-weight="700" fill="#7c5cff">Astonishingly small and fast</text>
    <text x="670" y="362" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">billions fit on a fingernail-sized chip —</text>
    <text x="670" y="375" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">each switches billions of times per second</text>
  </g>
  <text x="450" y="408" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">A modern processor is literally billions of these switches wired together.</text>
  <text x="450" y="428" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">That is the whole hardware story in one sentence — everything else is arrangement.</text>
  <text x="450" y="450" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.72">The gate is perpendicular to the path it controls: it never carries the current, it only decides whether current can pass.</text>
</svg>
```

Two things make it magical compared to a light switch:

- **It's controlled by electricity, not a finger** — so one transistor can flip another,
  and circuits can control themselves.
- **It's astonishingly small and fast** — billions fit on a fingernail-sized chip, and
  each can switch billions of times per second.

A modern processor is literally **billions of these switches** wired together. That's the
whole hardware story in one sentence; everything else is *arrangement*.

### From switches to logic gates

Wire a few transistors together and they compute **logic** — simple true/false rules. The
basic building blocks are **logic gates**. Here are the three you need, as **truth
tables** (every input combination and its output):

**NOT** (flips the input):

| in | out |
|:--:|:--:|
| 0 | 1 |
| 1 | 0 |

**AND** (1 only if *both* inputs are 1):

| a | b | out |
|:--:|:--:|:--:|
| 0 | 0 | 0 |
| 0 | 1 | 0 |
| 1 | 0 | 0 |
| 1 | 1 | 1 |

**OR** (1 if *either* input is 1):

| a | b | out |
|:--:|:--:|:--:|
| 0 | 0 | 0 |
| 0 | 1 | 1 |
| 1 | 0 | 1 |
| 1 | 1 | 1 |

A NOT gate is a couple of transistors; AND and OR are a few more each. A neat fact: one gate —
**NAND** (NOT-AND) — is *universal*: you can build every other gate, and therefore an
entire computer, out of nothing but NAND gates.

### From logic to arithmetic: adding with gates

Here's the leap that turns logic into a computer. Watch what happens when you add two
single bits:

| a | b | sum | carry |
|:--:|:--:|:--:|:--:|
| 0 | 0 | 0 | 0 |
| 0 | 1 | 1 | 0 |
| 1 | 0 | 1 | 0 |
| 1 | 1 | 0 | 1 |

Look closely: the **sum** column is exactly **XOR** (1 when the inputs differ), and the
**carry** column is exactly **AND** (1 only when both are 1). So two gates *add two bits*.
This little circuit is called a **half-adder**:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 434" width="100%" style="max-width:880px" role="img" aria-label="A half-adder drawn beside its truth table. On the left is the circuit: two input bits a and b, each fanning out to both of two gates. The XOR gate is the pointed shield with an extra arc across its back, and its output is the sum. The AND gate is the flat-backed D shape, and its output is the carry. Both gates take the same two bits at the same instant. A dot marks a real join between wires; where one wire hops over another it is only a crossing, not a connection. On the right is the four-row truth table for adding two single bits. With a equal to 0 and b equal to 0 the sum is 0 and the carry is 0. With a equal to 0 and b equal to 1 the sum is 1 and the carry is 0. With a equal to 1 and b equal to 0 the sum is 1 and the carry is 0. With a equal to 1 and b equal to 1 the sum is 0 and the carry is 1. The sum column is tinted the same green as the XOR gate's output, because the sum column is exactly XOR: 1 when the two inputs differ. The carry column is tinted the same amber as the AND gate's output, because the carry column is exactly AND: 1 only when both inputs are 1. The last row is the interesting one, where 1 plus 1 gives a sum of 0 and a carry of 1. Chain these into a full-adder that also takes a carry-in and you can add 8-bit, 32-bit or 64-bit numbers, which is literally how a CPU, a central processing unit, adds.">
  <defs>
    <marker id="p0l03b-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p0l03b-arm" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Two gates add two bits — sum is XOR, carry is AND</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="16" y="44" width="436" height="306" rx="12" fill="#7c5cff" fill-opacity="0.05" stroke="#7c5cff" stroke-opacity="0.6"/>
      <rect x="472" y="44" width="408" height="306" rx="12" fill="#7f7f7f" fill-opacity="0.05" stroke="#7f7f7f" stroke-opacity="0.6"/>
    </g>
    <text x="234" y="68" text-anchor="middle" font-size="12" font-weight="700" fill="#7c5cff">THE CIRCUIT — a half-adder</text>
    <text x="676" y="68" text-anchor="middle" font-size="12" font-weight="700" fill="currentColor" opacity="0.85">THE TRUTH TABLE — adding two single bits</text>

    <g fill="none" stroke-linejoin="round" stroke-width="1.7">
      <rect x="26" y="124" width="54" height="32" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="26" y="248" width="54" height="32" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    </g>
    <text x="53" y="146" text-anchor="middle" font-size="14" font-weight="700" fill="#3553ff">a</text>
    <text x="53" y="270" text-anchor="middle" font-size="14" font-weight="700" fill="#3553ff">b</text>

    <g fill="none" stroke="#3553ff" stroke-width="1.8" stroke-linejoin="round">
      <path d="M80 140 H104"/>
      <path d="M104 122 V250"/>
      <path d="M104 122 H210"/>
      <path d="M104 250 H120 A8 8 0 0 1 136 250 H210"/>
      <path d="M80 264 H128"/>
      <path d="M128 150 V278"/>
      <path d="M128 150 H210"/>
      <path d="M128 278 H210"/>
    </g>
    <g fill="#3553ff">
      <circle cx="104" cy="140" r="3.4"/><circle cx="128" cy="264" r="3.4"/>
    </g>
    <g text-anchor="middle" font-size="8" font-weight="700" fill="#3553ff" opacity="0.9">
      <text x="53" y="196">each input</text>
      <text x="53" y="207">feeds BOTH</text>
      <text x="53" y="218">gates</text>
    </g>

    <path d="M210 108 C250 108 278 118 292 136 C278 154 250 164 210 164 Q234 136 210 108 Z" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="2" stroke-linejoin="round"/>
    <path d="M200 108 Q224 136 200 164" fill="none" stroke="#7c5cff" stroke-width="2" stroke-linecap="round"/>
    <text x="252" y="141" text-anchor="middle" font-size="13" font-weight="700" fill="#0fa07f">XOR</text>
    <text x="246" y="186" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">1 when the inputs DIFFER</text>

    <path d="M210 236 L264 236 A28 28 0 0 1 264 292 L210 292 Z" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="2" stroke-linejoin="round"/>
    <text x="248" y="270" text-anchor="middle" font-size="13" font-weight="700" fill="#e0930f">AND</text>
    <text x="246" y="314" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">1 only when BOTH are 1</text>

    <path d="M292 136 H332" fill="none" stroke="#0fa07f" stroke-width="1.8" marker-end="url(#p0l03b-arg)"/>
    <path d="M292 264 H332" fill="none" stroke="#e0930f" stroke-width="1.8" marker-end="url(#p0l03b-arm)"/>
    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="336" y="114" width="88" height="44" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="336" y="242" width="88" height="44" rx="9" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
    </g>
    <text x="380" y="134" text-anchor="middle" font-size="13" font-weight="700" fill="#0fa07f">sum</text>
    <text x="380" y="149" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.8">= a XOR b</text>
    <text x="380" y="262" text-anchor="middle" font-size="13" font-weight="700" fill="#e0930f">carry</text>
    <text x="380" y="277" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.8">= a AND b</text>
    <text x="234" y="334" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.72">a dot = wires joined · a hop = a crossing, not a connection</text>

    <g fill="none" stroke-linejoin="round" stroke-width="1.6">
      <rect x="492" y="82" width="140" height="164" rx="7" fill="#3553ff" fill-opacity="0.07" stroke="#3553ff" stroke-opacity="0.45"/>
      <rect x="650" y="82" width="98" height="164" rx="7" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/>
      <rect x="756" y="82" width="108" height="164" rx="7" fill="#e0930f" fill-opacity="0.11" stroke="#e0930f"/>
    </g>
    <g stroke="currentColor" stroke-opacity="0.2" stroke-width="1">
      <path d="M492 118 H864"/><path d="M492 150 H864"/><path d="M492 182 H864"/><path d="M492 214 H864"/>
    </g>
    <rect x="488" y="214" width="380" height="32" rx="5" fill="none" stroke="currentColor" stroke-opacity="0.55" stroke-width="1.6"/>

    <g text-anchor="middle" font-size="12" font-weight="700">
      <text x="527" y="99" fill="#3553ff">a</text>
      <text x="597" y="99" fill="#3553ff">b</text>
      <text x="699" y="99" fill="#0fa07f">sum</text>
      <text x="810" y="99" fill="#e0930f">carry</text>
    </g>
    <g text-anchor="middle" font-size="8.5">
      <text x="527" y="112" fill="currentColor" opacity="0.75">input bit</text>
      <text x="597" y="112" fill="currentColor" opacity="0.75">input bit</text>
      <text x="699" y="112" fill="#0fa07f">= XOR</text>
      <text x="810" y="112" fill="#e0930f">= AND</text>
    </g>

    <g text-anchor="middle" font-size="13" font-weight="700" fill="currentColor">
      <text x="527" y="139">0</text><text x="597" y="139">0</text><text x="699" y="139">0</text><text x="810" y="139">0</text>
      <text x="527" y="171">0</text><text x="597" y="171">1</text><text x="699" y="171">1</text><text x="810" y="171">0</text>
      <text x="527" y="203">1</text><text x="597" y="203">0</text><text x="699" y="203">1</text><text x="810" y="203">0</text>
      <text x="527" y="235">1</text><text x="597" y="235">1</text><text x="699" y="235">0</text><text x="810" y="235">1</text>
    </g>
    <g text-anchor="middle" font-size="10" fill="currentColor" opacity="0.55">
      <text x="641" y="139">→</text><text x="641" y="171">→</text><text x="641" y="203">→</text><text x="641" y="235">→</text>
    </g>

    <text x="678" y="272" text-anchor="middle" font-size="10" font-weight="700" fill="#0fa07f">the sum column is exactly XOR — 1 when a and b DIFFER</text>
    <text x="678" y="292" text-anchor="middle" font-size="10" font-weight="700" fill="#e0930f">the carry column is exactly AND — 1 only when BOTH are 1</text>
    <text x="678" y="316" text-anchor="middle" font-size="9.5" font-weight="700" fill="currentColor">the boxed last row is the interesting one: 1 + 1 → sum 0, carry 1</text>
    <text x="678" y="333" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.72">which everyday operation does "carry" remind you of?</text>
  </g>
  <text x="450" y="376" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Chain these — a full-adder that also takes a carry-in — and you can add 8-, 32- or 64-bit numbers.</text>
  <text x="450" y="396" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">That is literally how a CPU (central processing unit) adds: transistors → gates → arithmetic.</text>
  <text x="450" y="418" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.72">Both gates see the SAME two bits at the same instant — sum and carry are computed in parallel, not one after the other.</text>
</svg>
```

Chain these together (a **full-adder** that also takes a carry-in) and you can add
multi-bit numbers — 8-bit, 32-bit, 64-bit. **That is literally how a CPU** (central
processing unit) **adds.** Stack
enough gates and you get subtraction, comparison, memory, and decisions. Every single
thing your computer does is transistors switching, arranged into gates, arranged into
arithmetic.

## Build It

You don't need transistors to prove this — you can build the logic in Python. In
[`code/logic_gates.py`](../code/logic_gates.py) we define the gates, then build an adder
*out of them* and use it to add real numbers:

```python
def NOT(a):    return 1 - a
def AND(a, b): return 1 if (a and b) else 0
def OR(a, b):  return 1 if (a or b) else 0
def XOR(a, b): return AND(OR(a, b), NOT(AND(a, b)))   # built only from AND/OR/NOT

def full_adder(a, b, carry_in):
    sum_bit   = XOR(XOR(a, b), carry_in)
    carry_out = OR(AND(a, b), AND(carry_in, XOR(a, b)))
    return sum_bit, carry_out

def add(x, y, width=8):          # add two numbers bit-by-bit, gates only
    result, carry = 0, 0
    for i in range(width):
        s, carry = full_adder((x >> i) & 1, (y >> i) & 1, carry)
        result |= s << i
    return result

print(add(5, 6))    # 11 — computed with nothing but AND, OR, NOT
```

**Think about it:**

1. The XOR above is built from AND, OR, and NOT. Why does that matter for a chip designer?
2. Adding `1 + 1` on a single bit gives sum 0, carry 1. Which everyday operation does
   "carry" remind you of?
3. If every gate is just transistors, and every arithmetic circuit is just gates, what is
   a CPU — in one sentence?

## Key takeaways

- A **transistor** is a tiny, electrically-controlled switch (on = 1, off = 0). A chip has
  **billions**, switching billions of times a second.
- Wiring transistors together makes **logic gates** — **NOT**, **AND**, **OR** (and NAND,
  which is universal). Truth tables define exactly what each does.
- Gates combine into **arithmetic**: XOR + AND = a **half-adder** that adds two bits; chain
  them to add any-size numbers. This is how a CPU really adds.
- Everything a computer does bottoms out here: **transistors → gates → arithmetic → a
  processor.**

Next: [From Sand to Chip](../04-from-sand-to-chip/) — how you actually manufacture billions
of these switches on a sliver of silicon, and why it costs a fortune.
