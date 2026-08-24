# Bits & Bytes

> Every photo, message, and bank balance a computer has ever touched is, underneath, just a pattern of on/off switches. Once you can read that pattern, nothing about computers is magic anymore.

## The Problem

A computer is, at its heart, a huge collection of tiny electrical switches. Each
switch can only be in one of two states: **on** or **off**. That's it. There is no
switch for the letter "A", no switch for the colour red, no switch for the number
42.

So here is the puzzle this whole field is built on: **using only "on" and "off",
how do you represent a number? A word? A photo? A bank balance?**

Every single thing in this curriculum (HTTP requests, databases, encryption) is
ultimately built on the answer. So we start exactly there.

## The Concept

### A bit: one switch

The smallest piece of information a computer has is a single switch. We call it a
**bit** (short for *binary digit*). We don't write it as "on/off"; we write it as
a number:

- **0** means off.
- **1** means on.

One bit isn't very interesting on its own: it can only say one of two things (yes
or no, true or false). The power comes from lining up many bits in a row.

### Counting with only 0 and 1

You already know how to count. You just do it in **base 10** (decimal): you have
ten symbols, `0` through `9`, and when you run out you carry over to a new column:
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

Notice the pattern: every time you need a new column, the value doubles into 1, 2,
4, 8, 16, 32… These are the **powers of two**, and they show up everywhere in this
field once you start looking.

### A byte: eight bits together

One bit is tiny, so computers almost never work with a single bit. They work with
groups of **8 bits**, and a group of 8 bits has its own name: a **byte**.

Why 8? History and convenience: 8 bits turned out to be a handy chunk, enough to
represent a useful range of values, and hardware standardised around it.

How many different patterns can 8 on/off switches make? Each bit doubles the
possibilities: 2 × 2 × 2 × 2 × 2 × 2 × 2 × 2 = **256**. So one byte can hold any
value from **0 to 255** (that's 256 values counting zero).

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="70 0 620 268" width="100%" style="max-width:620px" role="img" aria-label="One byte drawn as eight switches in a row. Above each switch is its place value, doubling from right to left: 128, 64, 32, 16, 8, 4, 2, 1. The switches hold the pattern 0, 0, 0, 0, 1, 0, 1, 1. Only the switches holding a 1 contribute, and each contributes its place value: 8, then 2, then 1. Adding those gives 8 plus 2 plus 1 equals 11, so binary 00001011 is the number 11. All eight switches off is 0 and all eight on is 255, which is the whole range of one byte.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="422" y="26" text-anchor="middle" font-size="13" font-weight="700" fill="currentColor">A byte is eight switches: add the columns holding a 1</text>

    <g text-anchor="middle" font-size="14" font-weight="700" fill="#c94a12">
      <text x="205" y="66">128</text><text x="267" y="66">64</text><text x="329" y="66">32</text><text x="391" y="66">16</text>
      <text x="453" y="66">8</text><text x="515" y="66">4</text><text x="577" y="66">2</text><text x="639" y="66">1</text>
    </g>

    <g fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.28" stroke-width="1.5">
      <rect x="178" y="78" width="54" height="52" rx="8"/>
      <rect x="240" y="78" width="54" height="52" rx="8"/>
      <rect x="302" y="78" width="54" height="52" rx="8"/>
      <rect x="364" y="78" width="54" height="52" rx="8"/>
      <rect x="488" y="78" width="54" height="52" rx="8"/>
    </g>
    <g fill="#7f7f7f" fill-opacity="0.24" stroke="#7f7f7f" stroke-width="2.2">
      <rect x="426" y="78" width="54" height="52" rx="8"/>
      <rect x="550" y="78" width="54" height="52" rx="8"/>
      <rect x="612" y="78" width="54" height="52" rx="8"/>
    </g>
    <g text-anchor="middle" font-size="22" font-weight="700" fill="currentColor">
      <text x="205" y="113" opacity="0.35">0</text><text x="267" y="113" opacity="0.35">0</text>
      <text x="329" y="113" opacity="0.35">0</text><text x="391" y="113" opacity="0.35">0</text>
      <text x="453" y="113">1</text>
      <text x="515" y="113" opacity="0.35">0</text>
      <text x="577" y="113">1</text><text x="639" y="113">1</text>
    </g>

    <g text-anchor="middle">
      <text x="205" y="156" font-size="11" fill="currentColor" opacity="0.3">0</text>
      <text x="267" y="156" font-size="11" fill="currentColor" opacity="0.3">0</text>
      <text x="329" y="156" font-size="11" fill="currentColor" opacity="0.3">0</text>
      <text x="391" y="156" font-size="11" fill="currentColor" opacity="0.3">0</text>
      <text x="453" y="156" font-size="14" font-weight="700" fill="#0fa07f">8</text>
      <text x="515" y="156" font-size="11" fill="currentColor" opacity="0.3">0</text>
      <text x="577" y="156" font-size="14" font-weight="700" fill="#0fa07f">2</text>
      <text x="639" y="156" font-size="14" font-weight="700" fill="#0fa07f">1</text>
    </g>

    <g text-anchor="end" font-size="9.5">
      <text x="162" y="66" fill="#c94a12">place value →</text>
      <text x="162" y="113" fill="currentColor" opacity="0.85">the 8 switches →</text>
      <text x="162" y="156" fill="#0fa07f">each adds →</text>
    </g>

    <path d="M178 170 L666 170" fill="none" stroke="#0fa07f" stroke-width="1.6" stroke-opacity="0.8"/>
    <text x="422" y="197" text-anchor="middle" font-size="16" font-weight="700"><tspan fill="#7f7f7f">00001011</tspan><tspan fill="currentColor" opacity="0.6">&#x2003;=&#x2003;</tspan><tspan fill="#0fa07f">8 + 2 + 1 = 11</tspan></text>

    <text x="422" y="230" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">All eight switches off = 0, all eight on = 255. That is the whole range of one byte.</text>
    <text x="422" y="248" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.72">The number only exists because we agree what each column is worth.</text>
  </g>
</svg>
```

That's where the familiar units come from: a **kilobyte (KB)** is about a thousand
bytes, a **megabyte (MB)** about a million, a **gigabyte (GB)** about a billion.
(Small print: computers sometimes count in 1024s rather than 1000s because 1024 is
a round number in binary (2¹⁰). Don't worry about that yet; "roughly a thousand"
is the right mental model for now.)

### Hexadecimal: a shorthand for humans

Writing bytes as 8 binary digits gets tedious fast: `11111111` is hard to read and
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
  byte first); you'll see it called *network byte order* in Phase 1.

You don't need to master these today. Just hold onto the rule that **width (how
many bytes) sets the range**, and it's all still only bits.

### Everything is bytes

Numbers are the easy case: you just saw how a byte holds a number. The big idea is
that **every other kind of data is also just bytes**, once you agree on a rule for
what the bytes *mean*:

- **Text**: agree that byte `65` means "A", `66` means "B"… (that's the next lesson).
- **A colour**: three bytes for how much red, green, and blue.
- **A photo**: millions of those colour-bytes in a grid.
- **Sound**: thousands of bytes per second measuring the height of a sound wave.

The bytes themselves never change. What changes is the **agreement** about how to
read them. Half of backend engineering is really about those agreements
(protocols and formats) layered on top of plain bytes.

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
- **All data is bytes** (text, images, sound) plus an *agreement* about how to
  read them. The rest of the curriculum is those agreements.

Next: [Text & Encoding](../02-text-and-encoding/), the agreement that turns bytes
into the letters you're reading right now.
