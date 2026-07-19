# Text & Encoding: ASCII to UTF-8

> A byte is just a number. Text only exists because everyone agreed which number means which letter. That agreement is an *encoding* — and getting it wrong is exactly why you sometimes see � instead of an emoji.

**Type:** Learn
**Languages:** Python
**Prerequisites:** [Bits & Bytes](../01-bits-and-bytes/)
**Time:** ~45 minutes

## The Problem

Last lesson ended on a promise: **all data is bytes, plus an agreement about how to
read them.** You saw how a byte holds a number from 0 to 255. But the words you're
reading right now aren't numbers — they're letters. So:

1. How does the number `72` become the letter **H**?
2. One byte only holds 256 different values. The world has **150,000+** characters —
   every alphabet, Chinese, Arabic, emoji. How do you fit all of that into bytes?

The answers — ASCII and UTF-8 — are two of the most important "agreements" in all of
computing. Every web page, every **API** (application programming interface) response, and
every database row depends on them.

## The Concept

### ASCII: the original agreement

In the 1960s people agreed on a table: **each character gets a number from 0 to
127.** It's called **ASCII** (American Standard Code for Information Interchange).
A character fits in 7 bits, so comfortably in one byte.

| Character | ASCII number |
|---|---|
| `A` | 65 |
| `B` | 66 |
| `Z` | 90 |
| `a` | 97 |
| `z` | 122 |
| `0` | 48 |
| `9` | 57 |
| space | 32 |

So the text `Hi` is really the two bytes `72 105`. That's the whole trick — **text is
just numbers, and ASCII is the lookup table.** A couple of patterns worth noticing
(they're not accidents — the designers planned them):

- Uppercase and lowercase are exactly **32 apart** (`A`=65, `a`=97). Flipping one bit
  changes case.
- The digits `0`–`9` are **48–57**, in order, so `'7'` minus `'0'` gives the number 7.

### The problem with ASCII: it's tiny

ASCII has room for 128 characters — enough for English. But "é", "ñ", "日", "🙂"?
Not a chance. Even stretching to a full byte (256 values) only buys a little more.
The world's writing needs *hundreds of thousands* of characters. One byte can't do it.

### Unicode: one giant catalog for every character

The fix is **Unicode**: a single, enormous catalog that gives **every character in
every language a unique number**, called a **code point**. Code points are written
`U+` followed by hex (remember hex from lesson 1):

| Character | Code point | (decimal) |
|---|---|---|
| `A` | U+0041 | 65 |
| `é` | U+00E9 | 233 |
| `€` | U+20AC | 8364 |
| `😀` | U+1F600 | 128512 |

Notice `A` is still 65 — Unicode kept ASCII's numbers for the first 128 characters on
purpose. But here's the key distinction, and it trips up almost everyone at first:

> **Unicode says which number a character *is*. It does *not* say how to store that
> number as bytes.** That second job — turning code points into bytes — is what an
> **encoding** does. The most important one is **UTF-8**.

### UTF-8: how code points become bytes

UTF-8 is a **variable-length** encoding: different characters take a different number
of bytes.

- Code points **0–127** (all of ASCII) → **1 byte**. So plain English text in UTF-8 is
  byte-for-byte identical to ASCII. This backward-compatibility is the single biggest
  reason UTF-8 took over the internet.
- Larger code points → **2, 3, or 4 bytes**. `é` takes 2 bytes, `€` takes 3, `😀`
  takes 4.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 768" width="100%" style="max-width:880px" role="img" aria-label="How UTF-8 encodes the character e-acute into bytes. The character is Unicode code point U+00E9, decimal 233, which in binary is 11101001. Unicode says which number the character is; UTF-8 decides how that number becomes bytes. A two-byte UTF-8 sequence carries exactly eleven payload bits, so 233 is padded with three leading zeros to eleven bits and split five plus six: 00011 and 101001. The two-byte template is 110xxxxx 10xxxxxx, where the leading 110 and the leading 10 are wrapper bits and every x is an empty slot for one of the character's own bits. Dropping the payload bits into those slots gives 110 00011 and 10 101001, that is the bytes 11000011 and 10101001, which are 0xC3 equals 195 and 0xA9 equals 169. Decoding runs backwards: strip the wrapper bits, concatenate 00011 and 101001 back into 00011101001, and the number 233 is there again, so the wrapper bits are pure bookkeeping and carry no character data. The length table reads as follows. Pattern 0xxxxxxx is one byte for code points U+0000 to U+007F, so A at U+0041 equals 65 is the single byte 0x41, identical to ASCII. Pattern 110xxxxx 10xxxxxx is two bytes for U+0080 to U+07FF, which is where e-acute lives. Pattern 1110xxxx 10xxxxxx 10xxxxxx is three bytes for U+0800 to U+FFFF, such as the euro sign at U+20AC equals 8364. Pattern 11110xxx followed by three continuation bytes is four bytes for U+10000 to U+10FFFF, such as the grinning face emoji at U+1F600 equals 128512. The count of leading ones in the first byte is the length, and any byte starting with 10 is always a continuation byte, so a program that jumps into the middle of a stream can resynchronise to the next character boundary. Because ASCII code points 0 to 127 encode to a single byte, plain English UTF-8 text is byte-for-byte identical to ASCII, the single biggest reason UTF-8 took over the internet. Finally, the word cafe with an acute e is four characters but five bytes: 63 61 66 C3 A9.">
  <defs>
    <marker id="p0l02a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
    <marker id="p0l02a-arp" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#7f7f7f"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="450" y="24" text-anchor="middle" font-size="15" font-weight="700" fill="currentColor">UTF-8 slices a code point's bits into a byte template that describes itself</text>

    <rect x="16" y="40" width="868" height="72" rx="11" fill="#3553ff" fill-opacity="0.06" stroke="#3553ff" stroke-opacity="0.7" stroke-width="1.8"/>
    <text x="32" y="60" font-size="10.5" font-weight="700" fill="#3553ff">1 · THE CHARACTER — a code point is a number, not yet bytes</text>
    <text x="450" y="90" text-anchor="middle" font-size="15" fill="currentColor"><tspan font-size="21" font-weight="700" fill="#3553ff">é</tspan><tspan>&#x2003;=&#x2003;</tspan><tspan font-weight="700" fill="#3553ff">U+00E9</tspan><tspan>&#x2003;=&#x2003;</tspan><tspan font-weight="700" fill="#3553ff">233</tspan><tspan>&#x2003;=&#x2003;</tspan><tspan font-weight="700" fill="#3553ff">11101001</tspan><tspan font-size="10">&#x2003;(8 bits)</tspan></text>
    <text x="450" y="106" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">Unicode gives the number. UTF-8 decides how that number becomes bytes.</text>

    <text x="450" y="136" text-anchor="middle" font-size="11" font-weight="700" fill="currentColor">2 · PAD 11101001 TO 11 BITS, THEN DROP THEM INTO THE 2-BYTE TEMPLATE</text>

    <g fill="none" stroke-width="1.6">
      <rect x="292" y="156" width="126" height="22" rx="6" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff" stroke-opacity="0.55"/>
      <rect x="534" y="156" width="152" height="22" rx="6" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff" stroke-opacity="0.55"/>
    </g>
    <text x="355" y="150" text-anchor="middle" font-size="8" fill="#3553ff" opacity="0.85">high 5 bits</text>
    <text x="610" y="150" text-anchor="middle" font-size="8" fill="#3553ff" opacity="0.85">low 6 bits</text>
    <text x="196" y="172" text-anchor="end" font-size="9" fill="currentColor" opacity="0.85">pad to 11 bits</text>
    <g font-size="13" font-weight="700" text-anchor="middle">
      <text x="303" y="172" fill="#7f7f7f">0</text><text x="329" y="172" fill="#7f7f7f">0</text><text x="355" y="172" fill="#7f7f7f">0</text>
      <text x="381" y="172" fill="#3553ff">1</text><text x="407" y="172" fill="#3553ff">1</text>
      <text x="545" y="172" fill="#3553ff">1</text><text x="571" y="172" fill="#3553ff">0</text><text x="597" y="172" fill="#3553ff">1</text>
      <text x="623" y="172" fill="#3553ff">0</text><text x="649" y="172" fill="#3553ff">0</text><text x="675" y="172" fill="#3553ff">1</text>
    </g>

    <g stroke="#7f7f7f" stroke-width="1.2" stroke-opacity="0.7">
      <path d="M303 180 L303 197" marker-end="url(#p0l02a-arp)"/>
      <path d="M329 180 L329 197" marker-end="url(#p0l02a-arp)"/>
      <path d="M355 180 L355 197" marker-end="url(#p0l02a-arp)"/>
    </g>
    <g stroke="#3553ff" stroke-width="1.2" stroke-opacity="0.75">
      <path d="M381 180 L381 197" marker-end="url(#p0l02a-ar)"/>
      <path d="M407 180 L407 197" marker-end="url(#p0l02a-ar)"/>
      <path d="M545 180 L545 197" marker-end="url(#p0l02a-ar)"/>
      <path d="M571 180 L571 197" marker-end="url(#p0l02a-ar)"/>
      <path d="M597 180 L597 197" marker-end="url(#p0l02a-ar)"/>
      <path d="M623 180 L623 197" marker-end="url(#p0l02a-ar)"/>
      <path d="M649 180 L649 197" marker-end="url(#p0l02a-ar)"/>
      <path d="M675 180 L675 197" marker-end="url(#p0l02a-ar)"/>
    </g>

    <g fill="none" stroke-width="1.6">
      <rect x="214" y="200" width="74"  height="22" rx="6" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-opacity="0.8"/>
      <rect x="292" y="200" width="126" height="22" rx="6" fill="#7f7f7f" fill-opacity="0.08" stroke="#7f7f7f" stroke-opacity="0.7" stroke-dasharray="4 3"/>
      <rect x="482" y="200" width="48"  height="22" rx="6" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-opacity="0.8"/>
      <rect x="534" y="200" width="152" height="22" rx="6" fill="#7f7f7f" fill-opacity="0.08" stroke="#7f7f7f" stroke-opacity="0.7" stroke-dasharray="4 3"/>
    </g>
    <text x="196" y="216" text-anchor="end" font-size="9" fill="currentColor" opacity="0.85">2-byte template</text>
    <g font-size="13" font-weight="700" text-anchor="middle">
      <text x="225" y="216" fill="#e0930f">1</text><text x="251" y="216" fill="#e0930f">1</text><text x="277" y="216" fill="#e0930f">0</text>
      <text x="303" y="216" fill="#7f7f7f">x</text><text x="329" y="216" fill="#7f7f7f">x</text><text x="355" y="216" fill="#7f7f7f">x</text>
      <text x="381" y="216" fill="#7f7f7f">x</text><text x="407" y="216" fill="#7f7f7f">x</text>
      <text x="493" y="216" fill="#e0930f">1</text><text x="519" y="216" fill="#e0930f">0</text>
      <text x="545" y="216" fill="#7f7f7f">x</text><text x="571" y="216" fill="#7f7f7f">x</text><text x="597" y="216" fill="#7f7f7f">x</text>
      <text x="623" y="216" fill="#7f7f7f">x</text><text x="649" y="216" fill="#7f7f7f">x</text><text x="675" y="216" fill="#7f7f7f">x</text>
    </g>
    <text x="712" y="216" font-size="8.5" fill="#e0930f" opacity="0.95">amber = wrapper bits</text>
    <text x="712" y="228" font-size="8.5" fill="currentColor" opacity="0.7">pure bookkeeping, no data</text>

    <g fill="none" stroke-width="1.6">
      <rect x="214" y="244" width="74"  height="22" rx="6" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-opacity="0.8"/>
      <rect x="292" y="244" width="126" height="22" rx="6" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-opacity="0.7"/>
      <rect x="482" y="244" width="48"  height="22" rx="6" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-opacity="0.8"/>
      <rect x="534" y="244" width="152" height="22" rx="6" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-opacity="0.7"/>
    </g>
    <text x="196" y="260" text-anchor="end" font-size="9" fill="currentColor" opacity="0.85">drop the bits in</text>
    <g font-size="13" font-weight="700" text-anchor="middle">
      <text x="225" y="260" fill="#e0930f">1</text><text x="251" y="260" fill="#e0930f">1</text><text x="277" y="260" fill="#e0930f">0</text>
      <text x="303" y="260" fill="#7f7f7f">0</text><text x="329" y="260" fill="#7f7f7f">0</text><text x="355" y="260" fill="#7f7f7f">0</text>
      <text x="381" y="260" fill="#3553ff">1</text><text x="407" y="260" fill="#3553ff">1</text>
      <text x="493" y="260" fill="#e0930f">1</text><text x="519" y="260" fill="#e0930f">0</text>
      <text x="545" y="260" fill="#3553ff">1</text><text x="571" y="260" fill="#3553ff">0</text><text x="597" y="260" fill="#3553ff">1</text>
      <text x="623" y="260" fill="#3553ff">0</text><text x="649" y="260" fill="#3553ff">0</text><text x="675" y="260" fill="#3553ff">1</text>
    </g>
    <text x="712" y="260" font-size="8.5" fill="#3553ff" opacity="0.95">blue = the character's bits</text>
    <text x="712" y="272" font-size="8.5" fill="#7f7f7f">grey = padding / empty slot</text>

    <g fill="none" stroke-width="1.8">
      <rect x="212" y="294" width="208" height="26" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="480" y="294" width="208" height="26" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    </g>
    <text x="196" y="312" text-anchor="end" font-size="9" fill="currentColor" opacity="0.85">the two bytes</text>
    <g font-size="13.5" font-weight="700" text-anchor="middle" fill="#0fa07f">
      <text x="225" y="312">1</text><text x="251" y="312">1</text><text x="277" y="312">0</text><text x="303" y="312">0</text>
      <text x="329" y="312">0</text><text x="355" y="312">0</text><text x="381" y="312">1</text><text x="407" y="312">1</text>
      <text x="493" y="312">1</text><text x="519" y="312">0</text><text x="545" y="312">1</text><text x="571" y="312">0</text>
      <text x="597" y="312">1</text><text x="623" y="312">0</text><text x="649" y="312">0</text><text x="675" y="312">1</text>
    </g>
    <text x="316" y="336" text-anchor="middle" font-size="9" fill="currentColor">0xC3 = 195 · 110… = 2-byte character</text>
    <text x="584" y="336" text-anchor="middle" font-size="9" fill="currentColor">0xA9 = 169 · 10… = continuation byte</text>
    <text x="450" y="360" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.9">Decoding runs backwards: throw away 110 and 10, concatenate 00011 + 101001 = 00011101001 = 233 = é again.</text>
    <text x="450" y="378" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.75">Trace one bit: the last 1 of 11101001 is still the last 1 of byte 2 — the bits are moved, never changed.</text>

    <text x="450" y="404" text-anchor="middle" font-size="11" font-weight="700" fill="currentColor">3 · EVERY BYTE ANNOUNCES ITS OWN ROLE — the leading 1s of the first byte are the length</text>
    <rect x="16" y="414" width="868" height="124" rx="11" fill="#7f7f7f" fill-opacity="0.06" stroke="#7f7f7f" stroke-opacity="0.6" stroke-width="1.6" fill-rule="evenodd"/>
    <rect x="24" y="464" width="852" height="24" rx="5" fill="#3553ff" fill-opacity="0.09"/>
    <g font-size="9" fill="currentColor" opacity="0.75">
      <text x="34" y="436">byte pattern (x = the character's own bits)</text>
      <text x="300" y="436">len</text>
      <text x="350" y="436">code points</text>
      <text x="530" y="436">example from this lesson</text>
    </g>
    <path d="M28 442 L872 442" stroke="currentColor" stroke-opacity="0.22" stroke-width="1"/>
    <g font-size="10.5" font-weight="700">
      <text x="34" y="458"><tspan fill="#e0930f">0</tspan><tspan fill="#7f7f7f">xxxxxxx</tspan></text>
      <text x="34" y="478"><tspan fill="#e0930f">110</tspan><tspan fill="#7f7f7f">xxxxx</tspan><tspan fill="currentColor"> </tspan><tspan fill="#e0930f">10</tspan><tspan fill="#7f7f7f">xxxxxx</tspan></text>
      <text x="34" y="498"><tspan fill="#e0930f">1110</tspan><tspan fill="#7f7f7f">xxxx</tspan><tspan fill="currentColor"> </tspan><tspan fill="#e0930f">10</tspan><tspan fill="#7f7f7f">xxxxxx</tspan><tspan fill="currentColor"> </tspan><tspan fill="#e0930f">10</tspan><tspan fill="#7f7f7f">xxxxxx</tspan></text>
      <text x="34" y="518"><tspan fill="#e0930f">11110</tspan><tspan fill="#7f7f7f">xxx</tspan><tspan fill="currentColor"> </tspan><tspan fill="#e0930f">10</tspan><tspan fill="#7f7f7f">xxxxxx</tspan><tspan fill="currentColor"> </tspan><tspan fill="#e0930f">10</tspan><tspan fill="#7f7f7f">xxxxxx</tspan><tspan fill="currentColor"> </tspan><tspan fill="#e0930f">10</tspan><tspan fill="#7f7f7f">xxxxxx</tspan></text>
    </g>
    <g font-size="10.5" font-weight="700" fill="currentColor">
      <text x="300" y="458">1</text><text x="300" y="478">2</text><text x="300" y="498">3</text><text x="300" y="518">4</text>
    </g>
    <g font-size="9" fill="currentColor" opacity="0.9">
      <text x="350" y="458">U+0000 – U+007F</text>
      <text x="350" y="478">U+0080 – U+07FF</text>
      <text x="350" y="498">U+0800 – U+FFFF</text>
      <text x="350" y="518">U+10000 – U+10FFFF</text>
    </g>
    <g font-size="9" fill="currentColor">
      <text x="530" y="458"><tspan fill="#0fa07f">A</tspan> = U+0041 = 65 → 0x41, the ASCII byte</text>
      <text x="530" y="478"><tspan fill="#3553ff" font-weight="700">é</tspan><tspan font-weight="700"> = U+00E9 = 233 → C3 A9</tspan>  ← worked out above</text>
      <text x="530" y="498"><tspan fill="#0fa07f">€</tspan> = U+20AC = 8364 → 3 bytes</text>
      <text x="530" y="518"><tspan fill="#0fa07f">😀</tspan> = U+1F600 = 128512 → 4 bytes</text>
    </g>

    <rect x="16" y="548" width="868" height="44" rx="10" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f" stroke-opacity="0.6" stroke-width="1.6" fill-rule="evenodd"/>
    <text x="450" y="568" text-anchor="middle" font-size="9.5" fill="currentColor"><tspan fill="#e0930f" font-weight="700">0…</tspan> a lone ASCII character&#x2003;·&#x2003;<tspan fill="#e0930f" font-weight="700">110… 1110… 11110…</tspan> first byte of a 2/3/4-byte character&#x2003;·&#x2003;<tspan fill="#e0930f" font-weight="700">10…</tspan> continuation</text>
    <text x="450" y="585" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">Continuation bytes are clearly marked, so a program can jump into the middle of a stream and resynchronise to the next character boundary.</text>

    <g fill="none" stroke-width="1.8">
      <rect x="16" y="604" width="430" height="96" rx="10" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f" stroke-opacity="0.8"/>
      <rect x="470" y="604" width="414" height="96" rx="10" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f" stroke-opacity="0.8"/>
    </g>
    <text x="231" y="624" text-anchor="middle" font-size="10" font-weight="700" fill="#0fa07f">ASCII IS A 1-BYTE SUBSET — UTF-8 IS BACKWARD-COMPATIBLE</text>
    <text x="231" y="648" text-anchor="middle" font-size="11.5" fill="currentColor"><tspan font-weight="700" fill="#3553ff">A</tspan> = U+0041 = 65 → <tspan fill="#e0930f" font-weight="700">0</tspan><tspan fill="#3553ff" font-weight="700">1000001</tspan> = <tspan fill="#0fa07f" font-weight="700">0x41</tspan></text>
    <text x="231" y="668" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.9">code points 0–127 need nothing but a single leading 0</text>
    <text x="231" y="686" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.75">plain English UTF-8 is byte-for-byte ASCII — why UTF-8 won</text>

    <text x="677" y="624" text-anchor="middle" font-size="10" font-weight="700" fill="#e0930f">SO CHARACTER COUNT ≠ BYTE COUNT</text>
    <g font-size="10.5" text-anchor="middle" fill="currentColor">
      <text x="573" y="642">c</text><text x="625" y="642">a</text><text x="677" y="642">f</text><text x="755" y="642" fill="#3553ff" font-weight="700">é</text>
    </g>
    <g fill="none" stroke-width="1.5">
      <rect x="550" y="648" width="46" height="26" rx="6" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f" stroke-opacity="0.7"/>
      <rect x="602" y="648" width="46" height="26" rx="6" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f" stroke-opacity="0.7"/>
      <rect x="654" y="648" width="46" height="26" rx="6" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f" stroke-opacity="0.7"/>
      <rect x="706" y="648" width="98" height="26" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    </g>
    <g font-size="11" font-weight="700" text-anchor="middle">
      <text x="573" y="666" fill="#7f7f7f">63</text><text x="625" y="666" fill="#7f7f7f">61</text><text x="677" y="666" fill="#7f7f7f">66</text>
      <text x="729" y="666" fill="#0fa07f">C3</text><text x="781" y="666" fill="#0fa07f">A9</text>
    </g>
    <text x="677" y="690" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">4 characters, 5 bytes — a byte limit and a character limit differ</text>

    <text x="450" y="720" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">Every byte says what it is: how long the character is, or that it is the middle of one.</text>
    <text x="450" y="738" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">That self-description is why UTF-8 survives a truncated stream — and why a byte limit is not a character limit.</text>
    <text x="450" y="756" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">Decode with a different table than the one that encoded, and you get mojibake — the bytes were never wrong.</text>
  </g>
</svg>
```

One direct consequence you *will* hit as a backend engineer: **the number of
characters is not the number of bytes.** The word `café` is 4 characters but **5
bytes** in UTF-8 (because `é` is two bytes). A length limit measured in bytes and one
measured in characters are different limits — mixing them up truncates people's
names and breaks emoji.

### How UTF-8 packs a code point into bytes

How does a reader know whether a byte is a whole character or just the middle of a
bigger one? UTF-8 is **self-describing**: it encodes the length into the **high bits of
the first byte**.

| Code point range | Bytes | Byte pattern (`x` = the character's bits) |
|---|---|---|
| U+0000 – U+007F (ASCII) | 1 | `0xxxxxxx` |
| U+0080 – U+07FF | 2 | `110xxxxx 10xxxxxx` |
| U+0800 – U+FFFF | 3 | `1110xxxx 10xxxxxx 10xxxxxx` |
| U+10000 – U+10FFFF | 4 | `11110xxx 10xxxxxx 10xxxxxx 10xxxxxx` |

Read the leading bits of any byte and you instantly know its role:

- Starts with **`0`** → a lone ASCII character (that's the backward-compatibility again).
- Starts with **`110` / `1110` / `11110`** → the **first** byte of a 2/3/4-byte character
  (the count of leading `1`s is the length).
- Starts with **`10`** → a **continuation** byte, the middle of a character.

Because continuation bytes are clearly marked, a program can jump into the middle of a
stream and **resynchronize** to the next character boundary — one reason UTF-8 is so
robust. Here's `é` encoded step by step:

```text
é  =  U+00E9  =  233  =  binary 11101001  →  pad to 11 bits  →  00011 101001   (5 + 6)

2-byte template:   110 xxxxx   10 xxxxxx
drop the bits in:  110 00011   10 101001
the two bytes:     11000011    10101001   =   0xC3  0xA9
```

Those are exactly the two bytes the demo printed for `é`. The wrapper bits (`110…`,
`10…`) are pure bookkeeping that let any reader regroup the bytes back into the one
number — and the number is the character.

### Mojibake: what a wrong encoding looks like

Bytes carry no label saying which encoding made them. If text is **written** as UTF-8
but **read back** as a different encoding (a common one is Latin-1), each byte gets
looked up in the wrong table and you get garbage:

- `café` written in UTF-8 is the bytes `63 61 66 C3 A9`.
- Read those same bytes back as Latin-1 and you get **`café`** — the classic garble
  called **mojibake**.
- When a program can't even make sense of the bytes, it shows the **replacement
  character** `�`.

That ugly `Ã©` in an email, or a `�` where an emoji should be, is almost always this:
**someone read bytes with a different encoding than the one that wrote them.** The
fix is never "retype it" — it's "decode with the right encoding."

This is why **HTTP** (hypertext transfer protocol) responses carry a header like
`Content-Type: text/html; charset=utf-8`,
why databases have a character-set setting, and why "always use UTF-8, end to end" is
standard backend advice. You're keeping everyone reading from the same table.

## Try It

Run [`code/text_and_encoding.py`](../code/text_and_encoding.py):

```python
print(ord("H"))          # 72   — the code point of a character
print(chr(72))           # H    — the character for a code point

for s in ["Hi", "café", "😀"]:
    b = s.encode("utf-8")            # text -> bytes
    print(s, len(s), "chars", len(b), "bytes", b)
# 'Hi'   2 chars 2 bytes
# 'café' 4 chars 5 bytes   <- é is 2 bytes
# '😀'   1 char  4 bytes

b = "café".encode("utf-8")           # b'caf\xc3\xa9'
print(b.decode("utf-8"))             # café   (right encoding)
print(b.decode("latin-1"))           # cafÃ©  (wrong encoding = mojibake)
```

**Predict before you run:**

1. `ord("A")` is 65. Without looking, what do you expect `ord("B")` and `ord("a")` to be?
2. `"hello"` has 5 characters. How many bytes in UTF-8, and why?
3. `"€"` is 3 bytes in UTF-8. How many *characters* is it?

## Key takeaways

- **ASCII** is the original agreement: 128 characters, each a number 0–127, one byte each.
- **Unicode** is a catalog giving every character (all languages + emoji) a unique
  number called a **code point** (e.g. `U+1F600`). It does *not* define bytes.
- An **encoding** turns code points into bytes. **UTF-8** is the dominant one: ASCII
  stays 1 byte (backward-compatible), other characters take 2–4 bytes.
- **Character count ≠ byte count.** `café` is 4 characters, 5 bytes.
- **Mojibake** (`café`, `�`) happens when bytes are decoded with the wrong encoding.
  Use **UTF-8 everywhere** so reader and writer share one table.

Next: [Transistors & Logic Gates](../03-transistors-and-logic-gates/) — the physical switch
every one of these bits actually lives on.
