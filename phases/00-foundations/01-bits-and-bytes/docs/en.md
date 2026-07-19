# Bits & Bytes

> Every photo, message, and bank balance a computer has ever touched is, underneath, just a pattern of on/off switches. Once you can read that pattern, nothing about computers is magic anymore.

**Type:** Learn
**Languages:** Python
**Prerequisites:** none — this is the very first lesson
**Time:** ~40 minutes

## The Problem

A computer is, at its heart, a huge collection of tiny electrical switches. Each
switch can only be in one of two states: **on** or **off**. That's it. There is no
switch for the letter "A", no switch for the colour red, no switch for the number
42.

So here is the puzzle this whole field is built on: **using only "on" and "off",
how do you represent a number? A word? A photo? A bank balance?**

Every single thing in this curriculum — HTTP requests, databases, encryption — is
ultimately built on the answer. So we start exactly there.

## The Concept

### A bit: one switch

The smallest piece of information a computer has is a single switch. We call it a
**bit** (short for *binary digit*). We don't write it as "on/off" — we write it as
a number:

- **0** means off.
- **1** means on.

One bit isn't very interesting on its own: it can only say one of two things (yes
or no, true or false). The power comes from lining up many bits in a row.

### Counting with only 0 and 1

You already know how to count. You just do it in **base 10** (decimal): you have
ten symbols, `0` through `9`, and when you run out you carry over to a new column —
`9`, then `10`, then `11`. Each column is worth ten times the one to its right:
ones, tens, hundreds.

A computer counts the same way, but with only **two** symbols, `0` and `1`. This is
**base 2**, or **binary**. When you run out (after `1`), you carry over. Each column
is worth **twice** the one to its right instead of ten times:

| Column value | 8 | 4 | 2 | 1 |
|---|---|---|---|---|
| Binary digits | 1 | 0 | 1 | 1 |

To read a binary number, add up the column values wherever there's a `1`. The
example above is `8 + 0 + 2 + 1 = 11`. So binary `1011` is the number **11**.

Counting up from zero looks like this:

| Decimal | Binary |
|---|---|
| 0 | 0 |
| 1 | 1 |
| 2 | 10 |
| 3 | 11 |
| 4 | 100 |
| 5 | 101 |
| 6 | 110 |
| 7 | 111 |
| 8 | 1000 |

Notice the pattern: every time you need a new column, the value doubles — 1, 2, 4,
8, 16, 32… These are the **powers of two**, and they show up everywhere in this
field once you start looking.

### A byte: eight bits together

One bit is tiny, so computers almost never work with a single bit. They work with
groups of **8 bits**, and a group of 8 bits has its own name: a **byte**.

Why 8? History and convenience — 8 bits turned out to be a handy chunk, enough to
represent a useful range of values, and hardware standardised around it.

How many different patterns can 8 on/off switches make? Each bit doubles the
possibilities: 2 × 2 × 2 × 2 × 2 × 2 × 2 × 2 = **256**. So one byte can hold any
value from **0 to 255** (that's 256 values counting zero).

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 686" width="100%" style="max-width:880px" role="img" aria-label="Two registers on one byte. First, a byte drawn as eight cells in a row. Above each cell is its place value, doubling from right to left: 1, 2, 4, 8, 16, 32, 64, 128, which are the powers of two from 2 to the 0 up to 2 to the 7. The cells hold the bit pattern 0, 0, 0, 0, 1, 0, 1, 1. Only the cells holding a 1 contribute, and each contributes its place value: 8, then 2, then 1. Adding those gives 8 plus 2 plus 1 equals 11, so binary 00001011 is the number 11. The four leading zeros add nothing, so it is the same number as the lesson's 1011, and Python prints bin of 11 as 0b1011. Split the byte in half and each half is one hex digit: 0000 is hex 0 and 1011 is hex B, so this byte is 0x0B, and two hex digits are always one byte. Turning every switch on gives 11111111, which is 128 plus 64 plus 32 plus 16 plus 8 plus 4 plus 2 plus 1 equals 255, written FF in hex, the largest value one byte holds. The number of patterns is 2 times 2 times 2 times 2 times 2 times 2 times 2 times 2, which is 256, because each extra switch doubles the count. One of those 256 patterns is zero, which is why a byte spans 0 to 255 rather than 1 to 256. Wider values simply use more bytes: 2 bytes reach 65,535, 4 bytes reach about 4.29 billion, and 8 bytes reach about 18 quintillion. Second, the familiar storage units, drawn as a staircase where every step to the right multiplies by 1000. One byte, about one character of text, becomes 1 kilobyte at roughly 1,000 bytes, about a page of plain text, then 1 megabyte at roughly 1,000 kilobytes or a million bytes, about a song, then 1 gigabyte at roughly 1,000 megabytes or a billion bytes, about a movie. Small print: computers sometimes count in 1024s rather than 1000s because 1024 is 2 to the 10, a round number in binary, but roughly a thousand is the right mental model for now.">
  <defs>
    <marker id="p0l01a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">Eight switches in a row: add up the columns holding a 1 and you have read the byte</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <rect x="16" y="38" width="868" height="222" rx="11" fill="#7f7f7f" fill-opacity="0.06" stroke="#7f7f7f" stroke-opacity="0.55" stroke-width="1.8"/>
    <text x="34" y="60" font-size="11.5" font-weight="700" fill="#7f7f7f">1 · ONE BYTE, DRAWN OUT</text>
    <text x="205" y="60" font-size="9" fill="currentColor" opacity="0.85">eight switches side by side — this one holds the lesson's own example, binary 1011</text>

    <g text-anchor="middle" font-size="10" fill="#3553ff" opacity="0.75">
      <text x="205" y="84">2<tspan font-size="7" dy="-3">7</tspan></text>
      <text x="275" y="84">2<tspan font-size="7" dy="-3">6</tspan></text>
      <text x="345" y="84">2<tspan font-size="7" dy="-3">5</tspan></text>
      <text x="415" y="84">2<tspan font-size="7" dy="-3">4</tspan></text>
      <text x="485" y="84">2<tspan font-size="7" dy="-3">3</tspan></text>
      <text x="555" y="84">2<tspan font-size="7" dy="-3">2</tspan></text>
      <text x="625" y="84">2<tspan font-size="7" dy="-3">1</tspan></text>
      <text x="695" y="84">2<tspan font-size="7" dy="-3">0</tspan></text>
    </g>
    <g text-anchor="middle" font-size="13.5" font-weight="700" fill="#3553ff">
      <text x="205" y="101">128</text><text x="275" y="101">64</text><text x="345" y="101">32</text><text x="415" y="101">16</text>
      <text x="485" y="101">8</text><text x="555" y="101">4</text><text x="625" y="101">2</text><text x="695" y="101">1</text>
    </g>

    <g fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.3" stroke-width="1.5">
      <rect x="175" y="110" width="60" height="44" rx="7"/>
      <rect x="245" y="110" width="60" height="44" rx="7"/>
      <rect x="315" y="110" width="60" height="44" rx="7"/>
      <rect x="385" y="110" width="60" height="44" rx="7"/>
      <rect x="525" y="110" width="60" height="44" rx="7"/>
    </g>
    <g fill="#7f7f7f" fill-opacity="0.24" stroke="#7f7f7f" stroke-width="2.2">
      <rect x="455" y="110" width="60" height="44" rx="7"/>
      <rect x="595" y="110" width="60" height="44" rx="7"/>
      <rect x="665" y="110" width="60" height="44" rx="7"/>
    </g>
    <g text-anchor="middle" font-size="21" font-weight="700" fill="currentColor">
      <text x="205" y="141" opacity="0.4">0</text><text x="275" y="141" opacity="0.4">0</text>
      <text x="345" y="141" opacity="0.4">0</text><text x="415" y="141" opacity="0.4">0</text>
      <text x="485" y="141">1</text>
      <text x="555" y="141" opacity="0.4">0</text>
      <text x="625" y="141">1</text><text x="695" y="141">1</text>
    </g>

    <g text-anchor="middle">
      <text x="205" y="178" font-size="11" fill="currentColor" opacity="0.35">0</text>
      <text x="275" y="178" font-size="11" fill="currentColor" opacity="0.35">0</text>
      <text x="345" y="178" font-size="11" fill="currentColor" opacity="0.35">0</text>
      <text x="415" y="178" font-size="11" fill="currentColor" opacity="0.35">0</text>
      <text x="485" y="178" font-size="13.5" font-weight="700" fill="#0fa07f">8</text>
      <text x="555" y="178" font-size="11" fill="currentColor" opacity="0.35">0</text>
      <text x="625" y="178" font-size="13.5" font-weight="700" fill="#0fa07f">2</text>
      <text x="695" y="178" font-size="13.5" font-weight="700" fill="#0fa07f">1</text>
    </g>

    <g text-anchor="end" font-size="9">
      <text x="165" y="101" fill="#3553ff">place value →</text>
      <text x="165" y="141" fill="currentColor" opacity="0.85">the 8 bits →</text>
      <text x="165" y="178" fill="#0fa07f">each adds →</text>
    </g>

    <path d="M175 188 L725 188" fill="none" stroke="#0fa07f" stroke-width="1.6" stroke-opacity="0.8"/>
    <text x="450" y="210" text-anchor="middle" font-size="15" font-weight="700"><tspan fill="#7f7f7f">00001011</tspan><tspan fill="currentColor" opacity="0.6">&#x2003;=&#x2003;</tspan><tspan fill="#0fa07f">8 + 2 + 1 = 11</tspan></text>
    <text x="450" y="230" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">The four leading zeros add nothing: 00001011 is the same number as the lesson's 1011, and Python prints bin(11) as 0b1011.</text>
    <text x="450" y="247" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">Split it in half and each half is one hex digit: 0000 is hex 0, 1011 is hex B, so this byte is 0x0B — two hex digits, one byte.</text>

    <rect x="16" y="270" width="430" height="130" rx="11" fill="#7f7f7f" fill-opacity="0.06" stroke="#7f7f7f" stroke-opacity="0.55" stroke-width="1.8"/>
    <g text-anchor="middle">
      <text x="231" y="292" font-size="10.5" font-weight="700" fill="#7f7f7f">ALL EIGHT SWITCHES ON</text>
      <text x="231" y="320" font-size="15" font-weight="700" fill="#7f7f7f">11111111</text>
      <text x="231" y="344" font-size="10" fill="currentColor" opacity="0.9">= 128 + 64 + 32 + 16 + 8 + 4 + 2 + 1</text>
      <text x="231" y="368" font-size="13" font-weight="700"><tspan fill="#0fa07f">= 255</tspan><tspan fill="currentColor" opacity="0.6">&#x2003;·&#x2003;hex FF</tspan></text>
      <text x="231" y="389" font-size="8.5" fill="currentColor" opacity="0.75">so one byte runs 0 (all off) to 255 (all on)</text>
    </g>

    <rect x="458" y="270" width="426" height="130" rx="11" fill="#3553ff" fill-opacity="0.05" stroke="#3553ff" stroke-opacity="0.55" stroke-width="1.8"/>
    <g text-anchor="middle">
      <text x="671" y="292" font-size="10.5" font-weight="700" fill="#3553ff">HOW MANY PATTERNS FIT IN 8 SWITCHES?</text>
      <text x="671" y="320" font-size="11.5" fill="currentColor"><tspan>2 × 2 × 2 × 2 × 2 × 2 × 2 × 2 = </tspan><tspan font-weight="700" fill="#0fa07f">256</tspan></text>
      <text x="671" y="344" font-size="9" fill="currentColor" opacity="0.85">each extra switch doubles the count — that is 2<tspan font-size="7" dy="-3">8</tspan></text>
      <text x="671" y="368" font-size="9.5" fill="currentColor"><tspan>256 patterns, one of them zero → a byte holds </tspan><tspan font-weight="700" fill="#0fa07f">0 to 255</tspan></text>
      <text x="671" y="389" font-size="8" fill="currentColor" opacity="0.75">more bytes = bigger range: 2 → 65,535 · 4 → ~4.29 billion · 8 → ~18 quintillion</text>
    </g>

    <rect x="16" y="410" width="868" height="200" rx="11" fill="#7f7f7f" fill-opacity="0.06" stroke="#7f7f7f" stroke-opacity="0.55" stroke-width="1.8"/>
    <text x="34" y="433" font-size="11.5" font-weight="700" fill="#7f7f7f">2 · WHERE KB, MB AND GB COME FROM</text>
    <text x="290" y="433" font-size="9" fill="currentColor" opacity="0.85">every step to the right is × 1000 — the same bytes, counted in bigger heaps</text>

    <g fill="#7f7f7f" stroke="#7f7f7f" stroke-width="1.7">
      <rect x="26"  y="496" width="176" height="64" rx="9" fill-opacity="0.06"/>
      <rect x="250" y="480" width="176" height="64" rx="9" fill-opacity="0.10"/>
      <rect x="474" y="464" width="176" height="64" rx="9" fill-opacity="0.14"/>
      <rect x="698" y="448" width="176" height="64" rx="9" fill-opacity="0.18"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.6" stroke-opacity="0.7">
      <path d="M204 528 L246 512" marker-end="url(#p0l01a-ar)"/>
      <path d="M428 512 L470 496" marker-end="url(#p0l01a-ar)"/>
      <path d="M652 496 L694 480" marker-end="url(#p0l01a-ar)"/>
    </g>
    <g text-anchor="middle" font-size="9" font-weight="700" fill="currentColor" opacity="0.8">
      <text x="225" y="502">× 1000</text>
      <text x="449" y="486">× 1000</text>
      <text x="673" y="470">× 1000</text>
    </g>
    <g text-anchor="middle">
      <text x="114" y="517" font-size="12" font-weight="700" fill="#7f7f7f">1 byte</text>
      <text x="114" y="535" font-size="8.5" fill="currentColor">8 bits · holds 0 to 255</text>
      <text x="114" y="552" font-size="8" fill="currentColor" opacity="0.72">one character of text</text>

      <text x="338" y="501" font-size="12" font-weight="700" fill="#7f7f7f">1 kilobyte (KB)</text>
      <text x="338" y="519" font-size="8.5" fill="currentColor">≈ 1,000 bytes</text>
      <text x="338" y="536" font-size="8" fill="currentColor" opacity="0.72">about a page of plain text</text>

      <text x="562" y="485" font-size="12" font-weight="700" fill="#7f7f7f">1 megabyte (MB)</text>
      <text x="562" y="503" font-size="8.5" fill="currentColor">≈ 1,000 KB = a million bytes</text>
      <text x="562" y="520" font-size="8" fill="currentColor" opacity="0.72">about a song</text>

      <text x="786" y="469" font-size="12" font-weight="700" fill="#7f7f7f">1 gigabyte (GB)</text>
      <text x="786" y="487" font-size="8.5" fill="currentColor">≈ 1,000 MB = a billion bytes</text>
      <text x="786" y="504" font-size="8" fill="currentColor" opacity="0.72">about a movie</text>
    </g>
    <text x="450" y="580" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">Small print: computers sometimes count in 1024s rather than 1000s, because 1024 = 2<tspan font-size="7" dy="-3">10</tspan><tspan dy="3"> is a round number in binary.</tspan></text>
    <text x="450" y="596" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">Don't worry about that yet — "roughly a thousand" is the right mental model for now.</text>
  </g>
  <text x="450" y="636" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">A byte is not a number — it is eight switches. The number only exists because we agree what each column is worth.</text>
  <text x="450" y="654" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Change the agreement and that same 00001011 becomes a letter, a shade of colour, or a slice of sound.</text>
  <text x="450" y="672" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.72">Bigger numbers use more bytes; bigger files use more bytes still — KB, MB and GB are only ways of counting them.</text>
</svg>
```

That's where the familiar units come from: a **kilobyte (KB)** is about a thousand
bytes, a **megabyte (MB)** about a million, a **gigabyte (GB)** about a billion.
(Small print: computers sometimes count in 1024s rather than 1000s because 1024 is
a round number in binary — 2¹⁰. Don't worry about that yet; "roughly a thousand"
is the right mental model for now.)

### Hexadecimal: a shorthand for humans

Writing bytes as 8 binary digits gets tedious fast — `11111111` is hard to read and
easy to miscount. So programmers use a shorthand called **hexadecimal** (base 16,
usually just "hex").

Hex has sixteen symbols: `0`–`9`, then `A`, `B`, `C`, `D`, `E`, `F` stand for 10 to
15. The magic is that **4 bits map to exactly one hex digit** (because 4 bits make
16 combinations), so **2 hex digits = 1 byte**:

| Binary | Hex | Decimal |
|---|---|---|
| 0000 | 0 | 0 |
| 1010 | A | 10 |
| 1111 | F | 15 |
| 11111111 | FF | 255 |

You'll meet hex constantly: colours on the web (`#FF5733`), memory addresses
(`0x7ffe`), and the hardware addresses of network cards all use it. When you see a
`#` or a `0x` prefix, your brain should now whisper "that's just bytes."

### Numbers bigger than one byte

A byte tops out at 255. So how does a computer store 1000, or a million? It uses **more
bytes together**. Each extra byte multiplies the range by 256:

| Bytes | Bits | Largest value (unsigned) | Typical use |
|---|---|---|---|
| 1 | 8 | 255 | a character, a small count |
| 2 | 16 | 65,535 | a network port, an audio sample |
| 4 | 32 | ~4.29 billion | an IPv4 address, most integers |
| 8 | 64 | ~18 quintillion | timestamps, large IDs, file sizes |

Two details you'll meet again later:

- **Signed vs unsigned.** The ranges above assume every bit counts toward the value
  (*unsigned*). To store negatives, a scheme called *two's complement* reinterprets the
  top bit as a sign, so a signed byte spans −128 to 127 instead of 0 to 255.
- **Byte order (endianness).** When a number spans several bytes, machines must agree
  which byte comes first. Network protocols standardize on "big-endian" (most significant
  byte first) — you'll see it called *network byte order* in Phase 1.

You don't need to master these today — just hold onto the rule that **width (how many
bytes) sets the range**, and it's all still only bits.

### Everything is bytes

Numbers are the easy case — you just saw how a byte holds a number. The big idea is
that **every other kind of data is also just bytes**, once you agree on a rule for
what the bytes *mean*:

- **Text** — agree that byte `65` means "A", `66` means "B"… (that's the next lesson).
- **A colour** — three bytes for how much red, green, and blue.
- **A photo** — millions of those colour-bytes in a grid.
- **Sound** — thousands of bytes per second measuring the height of a sound wave.

The bytes themselves never change. What changes is the **agreement** about how to
read them. Half of backend engineering is really about those agreements —
protocols and formats — layered on top of plain bytes.

## Try It

Python can show you the binary and hex behind any number. Run
[`code/bits_and_bytes.py`](../code/bits_and_bytes.py):

```python
n = 11
print(bin(n))   # 0b1011   -> the '0b' just means "binary follows"
print(hex(n))   # 0xb
print(n.to_bytes(1, "big"))  # b'\x0b'  -> 11 stored as one byte

# Read a byte back as a number:
print(int("1011", 2))    # 11   (parse a binary string)
print(int("FF", 16))     # 255  (parse a hex string)
print(0xFF)              # 255  (hex literal)
```

**Do this by hand first, then check with the code:**

1. What decimal number is binary `1101`? *(Hint: 8 + 4 + 0 + 1.)*
2. What's the largest number one byte can hold, and why is it 255 and not 256?
3. The colour `#00FF00` is pure green. How much red, green, and blue is that, as
   three decimal numbers 0–255?

## Key takeaways

- A **bit** is one on/off switch, written `0` or `1`. Computers have only bits.
- **Binary** (base 2) counts with just `0` and `1`; each column is worth double the
  one to its right (1, 2, 4, 8, …).
- A **byte** is 8 bits and holds a value from **0 to 255** (256 possibilities).
- **Hex** (base 16) is a human shorthand where 2 digits = 1 byte; you'll see it in
  colours, addresses, and more.
- **All data is bytes** — text, images, sound — plus an *agreement* about how to
  read them. The rest of the curriculum is those agreements.

Next: [Text & Encoding](../02-text-and-encoding/) — the agreement that turns bytes
into the letters you're reading right now.
