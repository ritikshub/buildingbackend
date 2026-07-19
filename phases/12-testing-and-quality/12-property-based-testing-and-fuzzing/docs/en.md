# Property-Based Testing & Fuzzing: The Cases You Would Never Have Written

> Forty hand-written tests for a pagination cursor codec caught **0 of its 3 real bugs** and stayed **40/40 green** through every one of them. Three properties — fifteen lines — caught **3 of 3**, in **5, 4 and 10 generated cases**. Then the number that makes it usable: a failing input of **4,000 characters shrank to 2** in **58 property evaluations**, and the two characters are the bug report. And the result nobody guesses: swapping only the *generator*, with the property and the code and the budget all identical, moved one bug from "found in 8 cases" to "expected in 4,294,967,296" — a **537-million-fold** difference produced by nothing but how you draw an integer.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Anatomy of a Unit Test](../03-anatomy-of-a-unit-test/), [Determinism: Time, Randomness, IDs & Order](../08-determinism-time-randomness-order/)
**Time:** ~80 minutes

## The Problem

It is 14:06 on a Thursday and the mobile team files a bug that reads like a support ticket rather than an engineering one: *"some users can't scroll past page 3."* Not all users. Not any user you can name. Some.

The endpoint is `GET /v1/orders?limit=50&cursor=…`. Keyset pagination — the client hands back an opaque cursor naming the last row it saw, and the server returns everything after it. The cursor is base64 of `sort_key` and `row_id`. It is fifteen lines of code. It has **forty tests**, they are good tests, and they have been green on every commit for eight months.

**14:19 — you get one reproduction.** A cursor arrives at the server as `eyJrIjoiTWFyaWEgR2FyY 2lhIn0`, with a space in the middle of it, and `base64` silently drops the space and decodes to garbage. The client did not put a space there. The client put a `+` there, which is what standard base64 produces for one six-bit group in sixty-four, and the browser's `URLSearchParams` decoded that `+` as a space, because `application/x-www-form-urlencoded` says a `+` **is** a space. Two correct implementations, one broken cursor.

**14:41 — a second reproduction, and it is not the same bug.** A customer whose display name arrived from an iOS device as `Maria García` — where `í` is the letter `i` followed by U+0301 COMBINING ACUTE ACCENT — gets a cursor that decodes to a *different* name than the one that was encoded, because `encode` runs `unicodedata.normalize("NFC", …)` to match the database's collation and `decode` has nothing that can undo it. The round trip is not a round trip.

**15:02 — the third.** Two orders share a `created_at` to the second. The cursor's `WHERE` clause compares the sort key only, not the `(sort_key, id)` pair, so when the page boundary falls between two rows that tie, the second one is skipped. Forever. It is not on page 3 and it is not on page 4.

None of the three is exotic and none is the result of carelessness. Each is a place where two correct-looking components disagree about a convention: base64's alphabet versus a form decoder's, an encoder's normalisation versus a decoder's, a cursor's comparison versus a sort's. Code review cannot find these, because every individual line reads as correct — and it *is* correct, in isolation.

Three bugs, one afternoon, in fifteen lines that had forty tests. Run the measurement in this lesson's program and each bug is switched on one at a time against that suite: **40 of 40 green, every time, for all three.** The suite is not bad. Read it and you would approve it: it covers empty keys, 200-character keys, negative ids, `2**31 - 1`, CJK, an emoji, an apostrophe, a pipe, a newline, a tab. It is a careful engineer's forty tests.

And it could not have found any of these, because of the property that every example-based suite has and nobody says out loud:

> **An example test can only check a case you already thought of — which is very nearly the same set of cases you already got right.**

You do not write a test for the input you failed to imagine. That is not a discipline problem you can fix by trying harder, and no amount of code review adds the case nobody has in their head. It is a *sampling* problem, and it has a mechanical answer: stop choosing the inputs.

## The Concept

### From "for this input, this output" to "for all inputs, this holds"

An example test names an input and an expected output: `assert decode(encode("alice", 1)) == ("alice", 1)`. A **property** names a *relationship* that must hold for every input in some set, and lets a machine choose the inputs:

```python
def prop_roundtrip(case):
    key, row_id = case
    return decode_cursor(encode_cursor(key, row_id)) == (key, row_id)
```

That is one line longer than the example and it is a strictly stronger statement. The example asserts something about `"alice"`. The property asserts something about *every string*, and then goes looking for the one that breaks it. In the program's run it takes **4 generated cases** to find the unicode bug and **5** to find the `+`.

Notice what the property does *not* say. It does not name a key, an id, an expected token, or a length. Everything specific has been removed, and what is left is the only thing you actually believe about the codec — which is why the property is both stronger than the example and shorter than three of them. The specifics were never the assertion; they were scaffolding you had to invent in order to state the assertion at all.

Here is the fair comparison. Same codec, same three bugs, two suites, each bug switched on alone so the failure is attributed to what actually caused it:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 452" width="100%" style="max-width:840px" role="img" aria-label="A comparison of forty hand-written example tests against three property tests over one pagination cursor codec with three seeded bugs. For the url alphabet bug, triggered when a token contains a plus sign, the example suite stayed forty out of forty green and the property survives-a-URL found it in five generated cases. For the unicode normalisation bug, triggered by any key that is not already NFC normalised, the example suite stayed forty out of forty green and the round-trip property found it in four cases. For the tie ordering bug, triggered when two rows share a sort key across a page boundary, the example suite stayed forty out of forty green and the pagination property found it in ten cases. Total: the example suite killed zero of three bugs across about one hundred and twenty lines of test code; the three properties killed three of three across fifteen lines.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Forty examples, zero bugs. Three properties, three bugs.</text>
    <text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">one codec, three bugs, each switched on alone so the blame lands where it belongs</text>

    <rect x="34" y="60" width="392" height="54" rx="9" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f" stroke-width="1.8"/>
    <text x="230" y="82" text-anchor="middle" font-size="11.5" font-weight="700" fill="#e0930f">40 hand-written example tests</text>
    <text x="230" y="101" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.9">~120 lines · inputs chosen by a careful engineer</text>

    <rect x="454" y="60" width="392" height="54" rx="9" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.8"/>
    <text x="650" y="82" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">3 properties</text>
    <text x="650" y="101" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.9">15 lines · inputs chosen by a generator</text>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="34" y="146">THE BUG</text><text x="212" y="146">THE INPUT THAT TRIGGERS IT</text><text x="558" y="146" text-anchor="middle">EXAMPLE SUITE</text><text x="652" y="146">FOUND BY A PROPERTY</text>
    </g>
    <path d="M28 152 L 852 152" fill="none" stroke="currentColor" stroke-width="1.3" opacity="0.45"/>

    <rect x="28" y="158" width="824" height="34" rx="6" fill="#7f7f7f" fill-opacity="0.07"/>
    <rect x="28" y="230" width="824" height="34" rx="6" fill="#7f7f7f" fill-opacity="0.07"/>

    <g font-size="10" font-weight="700">
      <text x="34" y="180" fill="#d64545">url alphabet</text><text x="34" y="216" fill="#d64545">unicode normalisation</text><text x="34" y="252" fill="#d64545">tie ordering</text>
    </g>
    <g font-size="9" fill="currentColor" opacity="0.9">
      <text x="212" y="180">a token containing "+"</text>
      <text x="212" y="216">a sort key that is not NFC-normalised</text>
      <text x="212" y="252">two rows sharing a sort key at a page edge</text>
    </g>
    <g font-size="10" font-weight="700" text-anchor="middle">
      <text x="558" y="180" fill="#0fa07f">40/40 green</text><text x="558" y="216" fill="#0fa07f">40/40 green</text><text x="558" y="252" fill="#0fa07f">40/40 green</text>
    </g>
    <g font-size="9">
      <text x="652" y="180" font-weight="700" fill="#3553ff">survives a URL</text><text x="846" y="180" text-anchor="end" font-weight="700" fill="currentColor">case 5</text>
      <text x="652" y="216" font-weight="700" fill="#3553ff">round-trip</text><text x="846" y="216" text-anchor="end" font-weight="700" fill="currentColor">case 4</text>
      <text x="652" y="252" font-weight="700" fill="#3553ff">pagination complete</text><text x="846" y="252" text-anchor="end" font-weight="700" fill="currentColor">case 10</text>
    </g>

    <path d="M28 272 L 852 272" fill="none" stroke="currentColor" stroke-width="1.3" opacity="0.45"/>
    <text x="34" y="296" font-size="11" font-weight="700" fill="currentColor">BUGS KILLED</text>
    <text x="558" y="296" text-anchor="middle" font-size="15" font-weight="700" fill="#d64545">0 of 3</text>
    <text x="756" y="296" text-anchor="middle" font-size="15" font-weight="700" fill="#0fa07f">3 of 3</text>

    <rect x="28" y="316" width="824" height="78" rx="9" fill="#3553ff" fill-opacity="0.07" stroke="#3553ff" stroke-opacity="0.5" stroke-width="1.4"/>
    <text x="42" y="336" font-size="9.5" font-weight="700" fill="#3553ff">the tie bug, shrunk by the engine in 34 evaluations — this is the whole ticket:</text>
    <text x="42" y="356" font-size="9.5" fill="currentColor" opacity="0.95">rows = [("", 0), ("", 1)]   page_size = 1</text>
    <text x="42" y="373" font-size="9.5" fill="currentColor" opacity="0.95">walk_pages returned [("", 0)] — expected [("", 0), ("", 1)]. One row vanished.</text>
    <text x="42" y="388" font-size="8.5" fill="currentColor" opacity="0.72">two rows, one shared sort key, page size 1. No hand-written pagination fixture looks like this.</text>

    <text x="440" y="420" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">The example suite is not lazy. It covers empty keys, 200-char keys, CJK, emoji, −1, 2³¹−1.</text>
    <text x="440" y="440" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">It cannot contain the input nobody imagined, and all three bugs live exactly there.</text>
  </g>
</svg>
```

Read the middle column and the right column together. The example suite did not *nearly* catch these — it was **40/40 green** on all three, which is the same verdict it gives on correct code. And the properties did not need a large budget: 5, 4 and 10 cases. The inputs were never rare. They were only *unimagined*.

### Finding properties: the catalogue, because that is the hard part

"Write a property" is unhelpful advice, in the same way "think of the edge case" is. What actually works is a short catalogue you run down. Seven shapes cover most backend code:

- **Round-trip.** `decode(encode(x)) == x`. Encoders, serializers, cursors, JWTs, compression, any pair with `to_` and `from_` in the names. This is the highest-value property in a backend and it is usually one line.
- **Invariant.** Something is always true of the output: a balance is never negative, a page is never longer than `limit`, a merged interval list is sorted and disjoint.
- **Idempotence.** `f(f(x)) == f(x)`. Normalisers, upserts, retried handlers ([Idempotency & Safe Retries](../../02-api-design/07-idempotency-safe-retries/) is the whole lesson).
- **Commutativity / order-independence.** Applying two events in either order gives the same state — which is exactly the assertion an event consumer needs and almost never has ([Testing Async & Event-Driven Systems](../11-testing-async-and-event-driven/)).
- **Oracle / differential.** The fast implementation agrees with an obviously-correct slow one. You need no property at all for this, which is why it is the escape hatch.
- **Metamorphic.** A relation between two runs rather than an absolute answer: adding an item never *decreases* the total; searching a superset never returns fewer hits. Use it when you cannot compute the right answer but you know how it must move.
- **Never crashes.** The weakest one, and never worthless — it is what a fuzzer asserts, and it found the `+` bug in this lesson's run at case 5.

The way to use that list is mechanical, and that is the point: read it top to bottom against the function in front of you and stop at the first shape that fits. Most backend functions match two or three. A cursor codec matches round-trip and never-crashes. A rate limiter matches invariant and stateful. An optimised query planner matches oracle. If none of the seven fits, that is real information — you probably have a business rule rather than a computation, and the last section of this lesson says what to do instead.

The last section of this lesson also measures which of these caught what, and no single one caught everything. Properties compose. The practical instruction is always "write another one", not "write a better one".

### Shrinking is the feature that makes any of this usable

A generator that finds a bug and reports it as 4,000 characters of arbitrary Unicode has not helped you. It has moved the work from *finding* to *understanding*, and understanding is the expensive part. **Shrinking** is what closes that gap, and it is the reason property testing is a practical technique rather than an interesting one.

The algorithm is simpler than its reputation. Given a failing value, propose smaller values; keep any that still fails; repeat until nothing smaller fails. "Smaller" is per-type: delete blocks of a list or string (largest blocks first), halve an integer toward zero, replace a character with an earlier one. The only rule that matters is that every proposal must be *strictly* smaller by some measure, or the search cycles forever — a mistake this lesson's engine made on its first draft, oscillating `0 → 1 → 0` until it hit its evaluation cap.

Here is the real trace from the program, on the unicode bug, starting from a 4,000-character key:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 520" width="100%" style="max-width:840px" role="img" aria-label="A staircase chart of a real shrink trace. The failing sort key starts at 4000 characters and is reduced through fifteen accepted reductions to two characters. The first six reductions halve the input each time, from 4000 to 2000 to 1000 to 500 to 250 to 125, costing two property evaluations each. Then block deletion gets finer: 124, 93, 47, 24, 12, 6, 3, 2 characters. The final two accepted reductions simplify a character to the letter a and reduce the row id from 727 to 0. The whole reduction cost 58 property evaluations, of which 15 were accepted. The minimal failing input is the two-character string a followed by U+0328 combining ogonek with row id 0, which NFC-normalises to a single precomposed character and so does not survive the round trip.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">4,000 characters of noise → a 2-character bug report, in 58 evaluations</text>
    <text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">every bar is a reduction that STILL FAILS; a proposal that stops failing is discarded and costs one call</text>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="34" y="72">ACCEPTED</text><text x="104" y="72">AFTER N EVALS</text><text x="196" y="72">KEY CHARS</text><text x="292" y="72">THE INPUT THAT STILL FAILS  (log scale)</text>
    </g>
    <path d="M28 78 L 852 78" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.42"/>

    <g fill="#d64545" fill-opacity="0.26" stroke="#d64545" stroke-width="1.2">
      <rect x="292" y="86" width="536" height="12" rx="2"/>
      <rect x="292" y="108" width="491" height="12" rx="2"/>
      <rect x="292" y="130" width="446" height="12" rx="2"/>
      <rect x="292" y="152" width="402" height="12" rx="2"/>
      <rect x="292" y="174" width="357" height="12" rx="2"/>
      <rect x="292" y="196" width="312" height="12" rx="2"/>
      <rect x="292" y="218" width="311" height="12" rx="2"/>
      <rect x="292" y="240" width="293" height="12" rx="2"/>
      <rect x="292" y="262" width="249" height="12" rx="2"/>
      <rect x="292" y="284" width="205" height="12" rx="2"/>
      <rect x="292" y="306" width="161" height="12" rx="2"/>
      <rect x="292" y="328" width="116" height="12" rx="2"/>
      <rect x="292" y="350" width="71" height="12" rx="2"/>
    </g>
    <rect x="292" y="372" width="45" height="12" rx="2" fill="#0fa07f" fill-opacity="0.34" stroke="#0fa07f" stroke-width="1.6"/>

    <g fill="currentColor" font-size="9" text-anchor="middle" opacity="0.85">
      <text x="52" y="96">0</text><text x="52" y="118">1</text><text x="52" y="140">2</text><text x="52" y="162">3</text><text x="52" y="184">4</text><text x="52" y="206">5</text><text x="52" y="228">6</text><text x="52" y="250">7</text><text x="52" y="272">8</text><text x="52" y="294">9</text><text x="52" y="316">10</text><text x="52" y="338">11</text><text x="52" y="360">12</text><text x="52" y="382">13</text>
      <text x="136" y="96">0</text><text x="136" y="118">2</text><text x="136" y="140">4</text><text x="136" y="162">6</text><text x="136" y="184">8</text><text x="136" y="206">10</text><text x="136" y="228">14</text><text x="136" y="250">18</text><text x="136" y="272">21</text><text x="136" y="294">23</text><text x="136" y="316">26</text><text x="136" y="338">28</text><text x="136" y="360">31</text><text x="136" y="382">33</text>
    </g>
    <g fill="currentColor" font-size="9.5" text-anchor="end" font-weight="700">
      <text x="266" y="96">4000</text><text x="266" y="118">2000</text><text x="266" y="140">1000</text><text x="266" y="162">500</text><text x="266" y="184">250</text><text x="266" y="206">125</text><text x="266" y="228">124</text><text x="266" y="250">93</text><text x="266" y="272">47</text><text x="266" y="294">24</text><text x="266" y="316">12</text><text x="266" y="338">6</text><text x="266" y="360">3</text><text x="266" y="382" fill="#0fa07f">2</text>
    </g>

    <text x="618" y="206" font-size="8.5" fill="currentColor" opacity="0.72">— halving: 2 evaluations each, 5 in a row</text>
    <text x="600" y="272" font-size="8.5" fill="currentColor" opacity="0.72">— finer blocks: 3 evaluations each</text>

    <rect x="28" y="398" width="824" height="70" rx="9" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f" stroke-opacity="0.55" stroke-width="1.4"/>
    <text x="42" y="418" font-size="9.5" font-weight="700" fill="#0fa07f">evaluations 37 and 48 stop shortening and start simplifying — the last two reductions:</text>
    <text x="42" y="437" font-size="10" fill="currentColor" opacity="0.95">('\xc2\u0328', 727)   &#8594;   ('a\u0328', 727)   &#8594;   ('a\u0328', 0)</text>
    <text x="42" y="456" font-size="8.5" fill="currentColor" opacity="0.78">"a" + U+0328 COMBINING OGONEK. NFC composes it to one character, so encode and decode disagree. UAX #15.</text>

    <text x="440" y="492" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">58 evaluations bought a 2,000× reduction. 15 were accepted; the other 43 cost one call each.</text>
    <text x="440" y="512" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">Zeller &amp; Hildebrandt, "Simplifying and Isolating Failure-Inducing Input", IEEE TSE 28(2), 2002.</text>
  </g>
</svg>
```

Three things in that trace are worth naming. **The first five reductions cost two evaluations each** — propose "delete the second half", it still fails, keep it. Halving a failing input is almost free, and it is where nearly all the reduction happens. **The search does not stop at length.** Evaluation 37 replaces a character with `a`, and evaluation 48 takes the row id from 727 to 0, because neither is load-bearing and a bug report with an arbitrary number in it invites the reader to wonder whether the number matters. **And the result is diagnostic, not merely small.** `("ą", 0)` says, without any prose, that the bug is about a combining character — because that is the only thing left.

Two things make shrinking behave badly, and both are worth recognising early. If your property is *slow* — a database round trip per case — then 58 evaluations is 58 queries and the shrink dominates the run; that is the real argument for keeping properties over pure functions and pushing I/O out of them ([Designing for Testability](../05-designing-for-testability/) is the general version). And if your property is *non-deterministic*, shrinking degenerates: a candidate that fails intermittently gets accepted and then cannot be reproduced, and the reported "minimal" case may not fail at all. Determinism is a precondition for shrinking, not a nicety.

This is the difference between a tool that finds bugs and a tool people use. Compare the same failure unshrunk: 4,000 characters of mixed-plane Unicode, in which the ogonek is one character among four thousand, and you have a bug report nobody will read.

### The generator is a hypothesis about where the bugs are

Now the result that changed how I write generators, and it is the one that is genuinely non-obvious.

Take a target with nothing subtle in it — clamp a client-supplied `?limit=` into `[1, 100]` — and give it three independent edge bugs: it passes negatives through, it returns `0` for `0`, and it returns `101` for exactly `100`. State one property: `1 <= normalise_limit(raw) <= 100`. Now change nothing except how the integer is drawn.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 448" width="100%" style="max-width:840px" role="img" aria-label="A three by three grid measuring how many generated cases three different integer generators need to find three different edge-case bugs in a limit-clamping function, with a budget of two hundred thousand cases per cell. Uniform over the full int32 range found the negative bug in 2 cases but never found the zero bug or the upper-boundary bug. Uniform over zero to one thousand never found the negative bug, found the zero bug in 1122 cases and the upper bug in 5215 cases. A boundary-biased generator that draws a known-interesting value one time in four found all three: the negative bug in 1 case, the zero bug in 8, and the upper bug in 117. Because a uniform int32 draw hits exactly zero with probability 2.33e-10, finding the zero bug uniformly would take about 4.29 billion cases, which is 537 million times the boundary-biased generator's 8.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Same property. Same code. Same budget. Only draw() changes.</text>
    <text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">cases needed to find each bug · budget 200,000 per cell · target: normalise_limit(raw) ∈ [1, 100]</text>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62" text-anchor="middle">
      <text x="414" y="76">uniform over int32</text><text x="574" y="76">uniform over 0..1000</text><text x="734" y="76">boundary-biased (25%)</text>
    </g>
    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="28" y="76">THE BUG</text><text x="150" y="76">TRIGGERS ON</text><text x="256" y="76">SHARE OF int32</text>
    </g>
    <path d="M22 82 L 858 82" fill="none" stroke="currentColor" stroke-width="1.3" opacity="0.45"/>

    <g stroke-width="1.4">
      <rect x="340" y="90" width="148" height="34" rx="5" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="340" y="132" width="148" height="34" rx="5" fill="#d64545" fill-opacity="0.14" stroke="#d64545"/>
      <rect x="340" y="174" width="148" height="34" rx="5" fill="#d64545" fill-opacity="0.14" stroke="#d64545"/>
      <rect x="500" y="90" width="148" height="34" rx="5" fill="#d64545" fill-opacity="0.14" stroke="#d64545"/>
      <rect x="500" y="132" width="148" height="34" rx="5" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
      <rect x="500" y="174" width="148" height="34" rx="5" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
      <rect x="660" y="90" width="148" height="34" rx="5" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="660" y="132" width="148" height="34" rx="5" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="660" y="174" width="148" height="34" rx="5" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
    </g>

    <g font-size="10.5" font-weight="700" text-anchor="middle">
      <text x="414" y="112" fill="#0fa07f">2 cases</text><text x="414" y="154" fill="#d64545">NOT FOUND</text><text x="414" y="196" fill="#d64545">NOT FOUND</text>
      <text x="574" y="112" fill="#d64545">NOT FOUND</text><text x="574" y="154" fill="#e0930f">1,122 cases</text><text x="574" y="196" fill="#e0930f">5,215 cases</text>
      <text x="734" y="112" fill="#0fa07f">1 case</text><text x="734" y="154" fill="#0fa07f">8 cases</text><text x="734" y="196" fill="#0fa07f">117 cases</text>
    </g>

    <g font-size="10" font-weight="700">
      <text x="28" y="112">negative</text><text x="28" y="154">zero</text><text x="28" y="196">upper</text>
    </g>
    <g font-size="9.5" fill="currentColor" opacity="0.9">
      <text x="150" y="112">raw &lt; 0</text><text x="150" y="154">raw == 0</text><text x="150" y="196">raw == 100</text>
      <text x="256" y="112">5.00e-01</text><text x="256" y="154">2.33e-10</text><text x="256" y="196">2.33e-10</text>
    </g>

    <path d="M22 220 L 858 220" fill="none" stroke="currentColor" stroke-width="1.3" opacity="0.45"/>
    <text x="440" y="244" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">the multiple, boundary-biased versus honest uniform</text>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="28" y="272">BUG</text><text x="200" y="272">BOUNDARY-BIASED</text><text x="390" y="272">UNIFORM int32</text><text x="676" y="272">MULTIPLE</text>
    </g>
    <g font-size="10">
      <text x="28" y="294" font-weight="700">negative</text><text x="200" y="294">1 case</text><text x="390" y="294">2 cases</text><text x="676" y="294" font-weight="700">2.0×</text>
      <text x="28" y="316" font-weight="700">zero</text><text x="200" y="316">8 cases</text><text x="390" y="316">4,294,967,296 expected</text><text x="676" y="316" font-weight="700" fill="#d64545">536,870,912×</text>
      <text x="28" y="338" font-weight="700">upper</text><text x="200" y="338">117 cases</text><text x="390" y="338">4,294,967,296 expected</text><text x="676" y="338" font-weight="700" fill="#d64545">36,709,122×</text>
    </g>

    <rect x="22" y="356" width="836" height="52" rx="9" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f" stroke-opacity="0.55" stroke-width="1.4"/>
    <text x="440" y="376" text-anchor="middle" font-size="10" font-weight="700" fill="#e0930f">the middle column is the one to stare at: rng.randint(0, 1000) is what a person writes</text>
    <text x="440" y="394" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.9">it beats the honest uniform generator on two bugs and is structurally blind to the third. Nobody chose that trade.</text>

    <text x="440" y="432" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">A generator is a hypothesis about where the bugs are. An unstated hypothesis is still a hypothesis.</text>
  </g>
</svg>
```

Read the top-right cell against the top-middle. **The honest generator — uniform over the full `int32` range, which is genuinely "all the values a client could send" — never once produced `0` in 200,000 draws**, and it never will in any budget you would pay for: the probability is `2.33e-10`, so the expected wait is **4.29 billion cases**. The boundary-biased generator found it in **8**. That is a **537-million-fold** difference, produced by adding a pool of `{0, 1, -1, 100, 2**31-1, …}` and drawing from it one time in four.

And then the middle column, which is the part that should make you uncomfortable. `rng.randint(0, 1000)` is what a normal person writes when asked to generate "a page size". It finds two of the three bugs — **better than the correct-looking uniform generator** — and it cannot find the third at all, because it never emits a negative number. Nobody deliberated over that trade. It fell out of a range chosen in two seconds.

The cost side is real and under-discussed, so state it: a boundary-biased generator spends a quarter of its budget on a handful of values, which is a quarter it does not spend on the bulk of the input space. If your bug lives in ordinary values — a rounding error at typical amounts, a collation problem in ordinary names — you have made it slightly harder to find. That trade is almost always worth taking, because edge-case bugs vastly outnumber middle-of-the-distribution bugs in practice, but it is a trade and not a free lunch.

This is why every real property-testing library ships boundary-biased generators rather than uniform ones. `hypothesis` draws `0`, `1`, `-1`, `2**n ± 1`, `NaN`, `''`, `'\x00'`, surrogate pairs and combining marks far more often than chance, and that bias is not a convenience — it is the entire product.

### Differential testing: when you cannot state a property, state an equivalence

The hardest part of property testing is stating the property, and there is one technique that skips it entirely. Write the obvious, slow, unmistakably-correct implementation; assert that the fast one agrees with it on every generated input. You have asserted nothing about *what* the function does and everything about whether the optimisation was safe — which is usually the actual question.

The program does this with two interval mergers: `merge_fast` sorts and sweeps in one pass, `merge_slow` unions any two ranges that overlap or touch until nothing changes. `merge_fast` has a `<` where `<=` belongs, so ranges that touch at exactly one point are not merged. It needs two coordinates to be *equal*, which is where the generator comes back in:

```text
    coordinates drawn from   cases to first disagreement   expected   (budget 60,000)
    0..20                                              4          2
    0..5,000                                         235        417
    0..1,000,000                                  35,648     83,333
```

**Four cases versus 35,648** — an **8,912×** spread on the identical bug, the identical property and the identical budget, with nothing changed but the range the coordinates come from. The shrunk counterexample is two ranges: `merge_fast` returns `[(0, 7), (7, 7)]` where `merge_slow` returns `[(0, 7)]`. This is the same lesson as the previous section arriving from a different direction, and together they are the argument for spending your thinking time on the generator rather than on the assertion.

The trap to avoid is writing the "slow" version by copying the fast one and removing the optimisation. Then you have two implementations of the same misunderstanding, and the agreement is guaranteed — exactly the failure the last section of this lesson measures at 0 of 3. The slow one must be written from the specification, ideally by someone who has not read the fast one.

### Stateful testing: the bug is in the sequence, not in the call

Some bugs are not a property of any single call. An LRU (Least Recently Used) cache with a capacity of 3 and one realistic defect — `get()` does not refresh recency, so eviction ends up insertion-ordered — is a good example, because *every individual operation is correct*. Property-test `put` and `get` in isolation and you will never see it: the program draws **50,000 one-operation sequences and finds no disagreement at all**, because a cache holding one item has nothing to evict.

The technique is **model-based testing**: generate a *sequence* of operations, run it against both the real implementation and a deliberately dumb model that is obviously right, and assert they agree after every step. The model here is a list kept in true recency order — quadratic, slow, and unmistakably correct, which is the only requirement a model has.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 464" width="100%" style="max-width:840px" role="img" aria-label="Two measurements of stateful model-based testing against an LRU cache of capacity three whose get operation fails to refresh recency. On the left, the number of generated sequences needed before the implementation and the model first disagree, as a function of the maximum sequence length: at maximum lengths of 2, 3 and 4 the bug is never found in twenty thousand sequences because the minimal counterexample is five operations long; at 5 it takes 2654 sequences, at 6 it takes 327, at 8 it takes 63, at 12 it takes 29, and at 40 it is found on the very first sequence. On the right, the shrunk counterexample: the raw failing sequence was 21 operations and shrank to 5 in 112 evaluations, namely put b, put d, put c, get b, put a, with the disagreement at operation 5, after which the implementation holds a, c and d while the model holds a, b and c. Across sixty different seeds the shrinker landed on a five-operation counterexample all sixty times.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">The minimal counterexample is 5 operations long — so 4 is a wall, not a slowdown</text>

    <text x="222" y="56" text-anchor="middle" font-size="11" font-weight="700" fill="#3553ff">sequences drawn before the first disagreement</text>
    <text x="662" y="56" text-anchor="middle" font-size="11" font-weight="700" fill="#0fa07f">the counterexample, shrunk</text>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="34" y="82">MAX SEQUENCE LENGTH</text><text x="290" y="82" text-anchor="end">SEQUENCES</text>
    </g>
    <path d="M28 88 L 296 88" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.42"/>

    <g stroke-width="1.3">
      <rect x="28" y="94" width="268" height="24" rx="5" fill="#d64545" fill-opacity="0.13" stroke="#d64545"/>
      <rect x="28" y="122" width="268" height="24" rx="5" fill="#d64545" fill-opacity="0.13" stroke="#d64545"/>
      <rect x="28" y="150" width="268" height="24" rx="5" fill="#d64545" fill-opacity="0.13" stroke="#d64545"/>
      <rect x="28" y="178" width="268" height="24" rx="5" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/>
      <rect x="28" y="206" width="268" height="24" rx="5" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/>
      <rect x="28" y="234" width="268" height="24" rx="5" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
      <rect x="28" y="262" width="268" height="24" rx="5" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
      <rect x="28" y="290" width="268" height="24" rx="5" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
    </g>
    <g font-size="10.5" font-weight="700">
      <text x="42" y="111">2</text><text x="42" y="139">3</text><text x="42" y="167">4</text><text x="42" y="195">5</text><text x="42" y="223">6</text><text x="42" y="251">8</text><text x="42" y="279">12</text><text x="42" y="307">40</text>
    </g>
    <g font-size="10" font-weight="700" text-anchor="end">
      <text x="284" y="111" fill="#d64545">never in 20,000</text><text x="284" y="139" fill="#d64545">never in 20,000</text><text x="284" y="167" fill="#d64545">never in 20,000</text>
      <text x="284" y="195" fill="#e0930f">2,654</text><text x="284" y="223" fill="#e0930f">327</text><text x="284" y="251" fill="#0fa07f">63</text><text x="284" y="279" fill="#0fa07f">29</text><text x="284" y="307" fill="#0fa07f">1</text>
    </g>
    <text x="162" y="336" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.82">50,000 sequences of length 1: no disagreement, ever.</text>
    <text x="162" y="350" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.82">A one-operation cache has nothing to evict.</text>

    <rect x="330" y="70" width="524" height="152" rx="9" fill="#0fa07f" fill-opacity="0.09" stroke="#0fa07f" stroke-opacity="0.55" stroke-width="1.5"/>
    <text x="346" y="90" font-size="9" fill="currentColor" opacity="0.75">21 operations drawn → 5 kept, in 112 evaluations</text>
    <g font-size="11" font-weight="700" fill="currentColor">
      <text x="346" y="112">1 ·  put('b', 0)</text><text x="346" y="132">2 ·  put('d', 0)</text><text x="346" y="152">3 ·  put('c', 0)</text><text x="346" y="172" fill="#e0930f">4 ·  get('b')     ← should refresh 'b'</text><text x="346" y="192" fill="#d64545">5 ·  put('a', 0)  ← evicts the wrong key</text>
    </g>
    <text x="346" y="212" font-size="9" fill="currentColor" opacity="0.8">capacity 3, so operation 5 must evict exactly one key</text>

    <rect x="330" y="234" width="524" height="80" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.42" stroke-width="1.4"/>
    <text x="346" y="256" font-size="10" font-weight="700" fill="#d64545">implementation holds   ['a', 'c', 'd']</text>
    <text x="346" y="278" font-size="10" font-weight="700" fill="#0fa07f">model holds            ['a', 'b', 'c']</text>
    <text x="346" y="300" font-size="9" fill="currentColor" opacity="0.85">'b' was read at step 4 and evicted anyway; 'd' was never read and survived.</text>

    <text x="592" y="336" text-anchor="middle" font-size="9.5" font-weight="700" fill="currentColor">over 60 different seeds the shrinker landed on a 5-operation sequence — 60 times out of 60</text>
    <text x="592" y="350" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">different search paths, the same ticket. That convergence is what makes it worth filing.</text>

    <path d="M28 366 L 852 366" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.42"/>
    <text x="440" y="392" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">Every individual operation is correct. The defect only exists in the relationship between five of them.</text>
    <text x="440" y="412" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">This is the bug class no unit test finds — and the one caches, rate limiters, queues and state machines are full of.</text>
    <text x="440" y="436" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.78">Claessen &amp; Hughes, "QuickCheck: A Lightweight Tool for Random Testing of Haskell Programs", ICFP 2000.</text>
  </g>
</svg>
```

The model is the part people over-think, so be blunt about it: **the model may be absurdly slow and it may be wrong about performance, but it must be obviously right about behaviour.** A linear scan through a list is a fine model for a hash map. A `sorted()` call is a fine model for a heap. If writing the model is hard, you have learned that the specification is unclear, which is a finding in itself — and if the model ends up as complex as the implementation, you have written a second copy of the bug rather than a check on it.

The left column contains a hard result: **at maximum sequence lengths of 2, 3 and 4 the bug is not found in 20,000 sequences — and never will be at any budget**, because the minimal counterexample is five operations long. There is a cliff, not a gradient. A stateful test whose sequence length is too short is not "slower at finding bugs"; it is *incapable* of finding a whole class of them, and it reports green forever while doing so. That is the argument for generating long sequences and letting the shrinker deal with the consequences — which it does: 21 operations down to 5, and **60 out of 60 seeds land on a 5-operation sequence**.

### Fuzzing is the same idea, one layer down

**Fuzzing** is property testing where the input is bytes and the property is "do not crash". The technique is older than the vocabulary around it: Miller, Fredriksen and So, *An Empirical Study of the Reliability of UNIX Utilities*, Communications of the ACM 33(12), 1990, fed pseudo-random character streams to 88 utility programs on seven UNIX variants and **crashed or hung 25–33% of them**. No models, no coverage, no cleverness — just bytes.

What changed since 1990 is one idea: **watch which branches the input reached, and keep the inputs that reached new ones.** That is coverage-guided fuzzing, the AFL insight, and the program measures it against a query-string parser whose crash needs a conjunction — a key containing `[` *and* ending in `]`, before an `=`.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 492" width="100%" style="max-width:840px" role="img" aria-label="A comparison of three fuzzers against a query-string parser whose crash requires a key that both contains an opening bracket and ends with a closing bracket. Uniform random bytes, the 1990 experiment, needed 21085 executions to crash. Random printable ASCII needed 6846. Coverage-guided mutation from three seed inputs needed 888, which is 7.7 times fewer than printable random and 23.7 times fewer than uniform random bytes. Below, the branch ladder shows when each fuzzer first reached each branch: random reached a segment containing an equals sign at execution 2, a percent escape at 3, an opening bracket in a key at 8, and a key ending in a closing bracket at 272, but the crash branch requiring both only at 6846. The coverage-guided fuzzer reached those same individual branches later, at 0, 388, 168 and 410, but reached the conjunction at 888. The crashing input shrank from 17 bytes to 2 bytes, an empty pair of brackets, in 34 candidates.">
  <defs>
    <marker id="p12-12-fz" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Guidance is memory, not better random numbers</text>
    <text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">executions to crash a query-string parser · budget 200,000 · log scale · 3 seed inputs for the guided run</text>

    <g fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.45">
      <path d="M296 152 L 296 62"/><path d="M436 152 L 436 62"/><path d="M576 152 L 576 62"/><path d="M716 152 L 716 62"/>
    </g>
    <g fill="currentColor" font-size="8" text-anchor="middle" opacity="0.7">
      <text x="296" y="166">100</text><text x="436" y="166">1,000</text><text x="576" y="166">10,000</text><text x="716" y="166">100,000</text>
    </g>

    <rect x="296" y="70" width="484" height="20" fill="#d64545" fill-opacity="0.30" stroke="#d64545" stroke-width="1.4"/>
    <rect x="296" y="98" width="416" height="20" fill="#e0930f" fill-opacity="0.30" stroke="#e0930f" stroke-width="1.4"/>
    <rect x="296" y="126" width="132" height="20" fill="#0fa07f" fill-opacity="0.36" stroke="#0fa07f" stroke-width="1.6"/>

    <g fill="currentColor" font-size="9.5" text-anchor="end">
      <text x="288" y="84" font-weight="700" fill="#d64545">uniform random bytes (Miller, 1990)</text><text x="288" y="112" font-weight="700" fill="#e0930f">random printable ASCII</text><text x="288" y="140" font-weight="700" fill="#0fa07f">coverage-guided mutation</text>
    </g>
    <g font-size="10.5" font-weight="700">
      <text x="790" y="84" fill="#d64545">21,085</text><text x="722" y="112" fill="#e0930f">6,846</text><text x="438" y="140" fill="#0fa07f">888</text>
    </g>
    <text x="480" y="140" font-size="9" fill="#0fa07f" font-weight="700">← 7.7× fewer than printable ASCII · 23.7× fewer than raw bytes</text>

    <text x="440" y="196" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">the ladder: executions before each branch was FIRST reached (50,000 each)</text>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="34" y="222">BRANCH IN THE PARSER</text><text x="600" y="222" text-anchor="end">RANDOM ASCII</text><text x="810" y="222" text-anchor="end">COVERAGE-GUIDED</text>
    </g>
    <path d="M28 228 L 852 228" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.42"/>

    <g fill="currentColor" font-size="9.5">
      <text x="34" y="248">a segment containing "="</text><text x="600" y="248" text-anchor="end">2</text><text x="810" y="248" text-anchor="end">0 (seeded)</text>
      <text x="34" y="268">a "%" escape</text><text x="600" y="268" text-anchor="end">3</text><text x="810" y="268" text-anchor="end">388</text>
      <text x="34" y="288">an invalid %XX pair</text><text x="600" y="288" text-anchor="end">3</text><text x="810" y="288" text-anchor="end">388</text>
    </g>
    <rect x="28" y="298" width="824" height="66" rx="6" fill="#7c5cff" fill-opacity="0.10"/>
    <g fill="currentColor" font-size="9.5">
      <text x="34" y="318" font-weight="700">"[" inside a key</text><text x="600" y="318" text-anchor="end" font-weight="700" fill="#e0930f">8</text><text x="810" y="318" text-anchor="end" font-weight="700">168</text>
      <text x="34" y="338" font-weight="700">a key ending in "]"</text><text x="600" y="338" text-anchor="end" font-weight="700" fill="#e0930f">272</text><text x="810" y="338" text-anchor="end" font-weight="700">410</text>
      <text x="34" y="358" font-weight="700" fill="#d64545">BOTH — the crash path</text><text x="600" y="358" text-anchor="end" font-weight="700" fill="#d64545">6,846</text><text x="810" y="358" text-anchor="end" font-weight="700" fill="#0fa07f">888</text>
    </g>

    <text x="440" y="384" text-anchor="middle" font-size="9.5" fill="#7c5cff" font-weight="700">the honest surprise: random noise reaches each INDIVIDUAL rung sooner — and cannot build the conjunction</text>

    <rect x="28" y="396" width="824" height="42" rx="8" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f" stroke-opacity="0.5" stroke-width="1.4"/>
    <text x="42" y="414" font-size="9.5" font-weight="700" fill="#0fa07f">then the shrinker, on bytes:</text>
    <text x="216" y="414" font-size="10" fill="currentColor">b'na[me]&amp;licename=&amp;'  (17 bytes)</text>
    <path d="M470 410 L 508 410" fill="none" stroke="#0fa07f" stroke-width="1.8" marker-end="url(#p12-12-fz)"/>
    <text x="518" y="414" font-size="10" font-weight="700" fill="#0fa07f">b'[]'  (2 bytes, 34 candidates)</text>
    <text x="42" y="431" font-size="8.5" fill="currentColor" opacity="0.75">int('') raises ValueError. The whole bug is an empty index between the brackets — and nothing else is left in the input.</text>

    <text x="440" y="460" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.8">Miller, Fredriksen &amp; So, "An Empirical Study of the Reliability of UNIX Utilities", CACM 33(12), 1990.</text>
    <text x="440" y="478" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">Their 1990 result: 25–33% of 88 UNIX utility programs crashed or hung on pseudo-random input.</text>
  </g>
</svg>
```

The middle rows of that ladder are the honest surprise, and they are worth more than the headline. **The random fuzzer reaches each individual rung sooner than the guided one** — `[` in a key at execution 8 versus 168, `]` at the end of a key at 272 versus 410 — because uniform noise contains bracket characters far more often than a mutated query string does. It is *ahead* on every intermediate step and it needs **7.7× more executions to reach the conjunction**, because it throws every near miss away. Coverage guidance is not a better source of randomness. It is **memory**: it keeps the input that got halfway and mutates that instead of starting over.

The practical question is what to point this at, and the answer is narrower than "everything". Fuzz the code that takes bytes from someone who is not you and turns them into structure: HTTP and query-string parsing, JSON and Protobuf decoders, cookie and token parsing, file uploads, CSV and XML importers, image and archive handling. Business logic that only ever sees already-validated objects is a poor fuzz target and an excellent property-test target — the two techniques divide along that line cleanly.

Note also that all three fuzzers discovered the same 13 branches. Branch *count* was not the differentiator; the ability to *stack* two conditions in one input was. That is exactly the shape of real parser bugs, and it is why fuzzing belongs on anything that touches untrusted bytes — deserializers, protocol parsers, image decoders, and every place [Injection & the OWASP Top 10](../../07-auth-and-security/11-injection-and-owasp-top-10/) tells you the attacker chooses the input.

### A failure you cannot replay is not a bug report

A property test that goes red on one seed and green on the next has told you the truth and given you nothing actionable. The fix is a **regression database**: when a property fails, record the shrunk counterexample; on every later run, replay the recorded cases *before* generating anything new.

Measured in the program: run 1 finds the bug at generated case 10 and records the shrunk case `('\u0300\u034e', 0)`. Runs 2 through 8, on seven different seeds, all go red at **case 1**, because the recorded case runs first. The variance in discovery time collapses to zero the moment the first failure is written down. And on fixed code, the same recorded case is replayed three times and passes every time — it is a pinned regression, not a landmine.

There is a second reason to record rather than to derandomise. Pinning a single seed makes the run reproducible, but it also freezes the *set of cases you ever try* — the test now checks the same 100 inputs forever, which is an example suite with extra steps. Recording counterexamples gives you reproducibility of the failures without giving up the search.

`hypothesis` implements exactly this in a `.hypothesis/examples` directory. **That directory belongs in your CI cache, not in `.gitignore`.** If it is discarded between builds, every CI run starts from zero knowledge and you get the flakiness without the memory — the failure mode that makes teams delete property tests. Cache it, keyed on nothing at all so it accumulates across branches, and pin the important cases into the source with `@example(...)` so they survive a cache eviction and are visible in code review.

### Flaky, or working? Reconciling it with Lesson 9 honestly

Here is the apparent contradiction, and it deserves a straight answer rather than a slogan. [Flaky Tests: The Trust Arithmetic](../09-flaky-tests/) defines a flake as a test that produces different verdicts on the same commit, and argues — with the arithmetic — that flakes destroy the suite's value. A property test does exactly that: same commit, different seed, sometimes red.

So measure it. The same property, the same commit, **300 different seeds**, at six budgets, run twice — once with the bug present and once with it fixed:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 428" width="100%" style="max-width:840px" role="img" aria-label="A measurement of how often a property test goes red across three hundred different seeds, at six different max_examples budgets, on buggy code and on fixed code. With the bug present, five examples per run goes red on 59.0 percent of seeds, ten examples on 83.3 percent, twenty-five on 97.7 percent, and fifty, one hundred and two hundred and fifty all go red on 100 percent of seeds. With the bug fixed, every one of the six budgets goes red on 0.0 percent of seeds: zero false alarms out of eighteen hundred runs. The conclusion is that the run-to-run variance is entirely in discovery latency, never in the verdict about correct code, so a property test cannot produce the false alarm that a flaky test produces.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">The verdict varies. It has never once been wrong.</text>
    <text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">300 seeds per row · same commit · a run is "red" if it found the bug within its budget</text>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="34" y="76">max_examples</text><text x="200" y="76">RED RUNS OF 300 — THE BUG IS PRESENT</text><text x="600" y="76">RED RUNS OF 300 — THE BUG IS FIXED</text>
    </g>
    <path d="M28 82 L 852 82" fill="none" stroke="currentColor" stroke-width="1.3" opacity="0.45"/>

    <g fill="#7f7f7f" fill-opacity="0.16" stroke="#7f7f7f" stroke-width="1">
      <rect x="200" y="92" width="330" height="18"/><rect x="200" y="122" width="330" height="18"/><rect x="200" y="152" width="330" height="18"/><rect x="200" y="182" width="330" height="18"/><rect x="200" y="212" width="330" height="18"/><rect x="200" y="242" width="330" height="18"/>
      <rect x="600" y="92" width="220" height="18"/><rect x="600" y="122" width="220" height="18"/><rect x="600" y="152" width="220" height="18"/><rect x="600" y="182" width="220" height="18"/><rect x="600" y="212" width="220" height="18"/><rect x="600" y="242" width="220" height="18"/>
    </g>
    <g fill="#3553ff" fill-opacity="0.42" stroke="#3553ff" stroke-width="1.3">
      <rect x="200" y="92" width="195" height="18"/><rect x="200" y="122" width="275" height="18"/><rect x="200" y="152" width="322" height="18"/>
    </g>
    <g fill="#0fa07f" fill-opacity="0.42" stroke="#0fa07f" stroke-width="1.3">
      <rect x="200" y="182" width="330" height="18"/><rect x="200" y="212" width="330" height="18"/><rect x="200" y="242" width="330" height="18"/>
    </g>

    <g fill="currentColor" font-size="10" font-weight="700">
      <text x="34" y="106">5</text><text x="34" y="136">10</text><text x="34" y="166">25</text><text x="34" y="196">50</text><text x="34" y="226">100</text><text x="34" y="256">250</text>
    </g>
    <g font-size="9" font-weight="700" text-anchor="middle">
      <text x="565" y="106" fill="#3553ff">177 · 59.0%</text><text x="565" y="136" fill="#3553ff">250 · 83.3%</text><text x="565" y="166" fill="#3553ff">293 · 97.7%</text>
      <text x="565" y="196" fill="#0fa07f">300 · 100%</text><text x="565" y="226" fill="#0fa07f">300 · 100%</text><text x="565" y="256" fill="#0fa07f">300 · 100%</text>
    </g>
    <g font-size="9.5" font-weight="700" fill="#0fa07f" text-anchor="middle">
      <text x="710" y="106">0 / 300</text><text x="710" y="136">0 / 300</text><text x="710" y="166">0 / 300</text><text x="710" y="196">0 / 300</text><text x="710" y="226">0 / 300</text><text x="710" y="256">0 / 300</text>
    </g>
    <text x="710" y="278" text-anchor="middle" font-size="9" font-weight="700" fill="#0fa07f">1,800 runs on correct code. Zero red.</text>

    <path d="M28 292 L 852 292" fill="none" stroke="currentColor" stroke-width="1.3" opacity="0.45"/>

    <rect x="28" y="302" width="404" height="76" rx="9" fill="#d64545" fill-opacity="0.09" stroke="#d64545" stroke-opacity="0.5" stroke-width="1.4"/>
    <text x="230" y="322" text-anchor="middle" font-size="10.5" font-weight="700" fill="#d64545">a flaky test</text>
    <text x="42" y="341" font-size="9" fill="currentColor" opacity="0.92">red on code that is CORRECT</text>
    <text x="42" y="357" font-size="9" fill="currentColor" opacity="0.92">costs: trust. Every false alarm teaches</text>
    <text x="42" y="371" font-size="9" fill="currentColor" opacity="0.92">the team that red means "re-run it".</text>

    <rect x="448" y="302" width="404" height="76" rx="9" fill="#0fa07f" fill-opacity="0.09" stroke="#0fa07f" stroke-opacity="0.5" stroke-width="1.4"/>
    <text x="650" y="322" text-anchor="middle" font-size="10.5" font-weight="700" fill="#0fa07f">a property test that found a new bug</text>
    <text x="462" y="341" font-size="9" fill="currentColor" opacity="0.92">red on code that is WRONG — always was</text>
    <text x="462" y="357" font-size="9" fill="currentColor" opacity="0.92">costs: latency. You learned it on build 40</text>
    <text x="462" y="371" font-size="9" fill="currentColor" opacity="0.92">instead of build 1. Record it and it is over.</text>

    <text x="440" y="404" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">The variance is entirely in DISCOVERY. It is never in the verdict about correct code.</text>
    <text x="440" y="422" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">A flake is a false positive. This is a delayed true positive — the opposite defect, with the opposite cost.</text>
  </g>
</svg>
```

The right-hand column settles it. **Across 1,800 runs on correct code, at every budget, the property went red exactly zero times.** A flaky test is a *false positive*: it says "broken" about code that is fine, and the cost of that is trust, which is the thing Lesson 9 shows you cannot get back. A property test that finds a new bug on a new seed is a **delayed true positive**: the code was wrong on build 1 and on build 40, and only your knowledge changed. Those are opposite defects with opposite costs.

The left column is also the practical instruction. At `max_examples=5` the test finds this bug on **59.0%** of seeds; at 25, **97.7%**; at 50 and above, **100%**. The variance is a *budget* setting, and it is yours to choose. So: run a large `max_examples` in the nightly job where minutes are free, run a smaller one on pull requests, cache the examples database so today's discovery is tomorrow's deterministic replay, and — the part people miss — **treat a red property test as a bug in the code, never as a bug in the test**. The one policy that destroys the technique is quarantining it.

One operational note, because this is where the policy actually gets tested. When a property test goes red on an unrelated pull request — and it will, because a new seed found an old bug — the correct response is to file the shrunk counterexample, pin it with `@example`, and decide whether to fix it now or accept it knowingly. The incorrect responses are all variations on making the message go away: re-running until green, lowering `max_examples`, adding an `assume` that excludes the failing shape, or marking it flaky. Each of those converts a true positive into permanent blindness, and unlike a real flake, nothing will ever tell you again.

### What property testing is bad at

Two limits, and the second is a trap you can walk into while feeling productive.

**Business rules with no expressible invariant.** "Gold-tier customers in the EU get free shipping over €50, except on furniture" is not a property; it is a table, and a table is best tested with a table ([Anatomy of a Unit Test](../03-anatomy-of-a-unit-test/) covers parametrized cases). Trying to state it as a property produces a second copy of the rule, which brings us to the trap.

**A property read off the implementation proves nothing.** Write your property by reading the function's body and you get something that is universally quantified, generates thousands of cases, and cannot fail. The program includes one — it recomputes `encode_cursor`'s exact expression and asserts equality — and runs it against all three bugs:

```text
    property                                 url alphabet  unicode normalisation           tie ordering   killed
    round-trip                                     silent                 case 4                 silent   1/3
    survives a URL                                 case 5                 case 4                 silent   2/3
    pagination is complete                         silent                 silent                case 10   1/3
    never crashes (the weakest)                    case 5                 silent                 silent   1/3
    restates the implementation                    silent                 silent                 silent   0/3
    the first four, together                                                                              3/3
```

**0 of 3, from a property that looks exactly like its neighbours.** This is the same failure as the hand-written mock in [Test Doubles](../04-test-doubles/): a check derived from the implementation inherits the implementation's misunderstanding, so its agreement is guaranteed rather than earned. The rule that avoids it: **state properties from the caller's side, in the caller's vocabulary** — "a cursor survives a URL", "a page never loses a row". Note that `never crashes` is honest for exactly this reason, weak as it is: it is written from outside, so nothing in it can agree with a bug.

And note the other result in that table. The best single property kills **2 of 3**; the rest kill **1 of 3**; the set kills **3 of 3**. There is no strongest property to find. There is only another one to write.

## Build It

`code/property_testing.py` is one file, standard library only, no network, seeded with `random.Random(20260718)`, and it exits in about five seconds. Run it twice and diff it: the output is byte-identical. Eight numbered sections map onto the concepts above.

The **target** is designed so the comparison in section 1 is honest rather than rigged. Each of the three bugs is a flag on the same fifteen lines, switched on one at a time, and both suites are run against the bug-free build first to establish a baseline — a suite that is already red would otherwise score a free kill on every bug. The forty examples are written as data, and they are the tests a careful engineer writes: real names, an empty key, a 200-character key, `-1`, `2**31 - 1`, an apostrophe, a pipe, a newline, and pagination fixtures with the distinct sort keys everybody uses.

The **engine** is the centrepiece and it is genuinely small. A generator is two methods — how to draw a value, and how to make one smaller:

```python
class Gen:
    def draw(self, rng: random.Random) -> Any: ...
    def candidates(self, value: Any) -> Iterator[Any]:
        """Smaller values to try, most aggressive first. Yielding a value that
        does not reproduce the failure is free — the driver just moves on."""
```

The **runner** is nine lines and there is nothing else to it. Draw, test, stop at the first failure, shrink:

```python
def check(prop: Callable[[Any], Any], gen: Gen, *, max_examples: int = 200,
          seed: int = SEED, do_shrink: bool = True) -> Result:
    """Draw up to `max_examples` values; stop at the first failure and shrink."""
    rng = random.Random(seed)
    for i in range(1, max_examples + 1):
        value = gen.draw(rng)
        if fails(prop, value):
            small, evals, trace = shrink(prop, gen, value)
            return Result(False, i, value, small, evals, trace, why(prop, small))
    return Result(True, max_examples)
```

`fails()` treats *both* a `False` return and any raised exception as a failure. That one decision is what gives you the "never crashes" property class for free, with no extra machinery — a crash is just a failure whose explanation is a traceback.

The **shrinker** is a greedy fixed point. Take the first candidate that still fails, then start the candidate list again from the top — restarting matters, because after a large deletion succeeds another large deletion is usually available, which turns the search into roughly a binary one:

```python
progress = True
while progress and evals < limit:
    progress = False
    for cand in gen.candidates(best):
        evals += 1
        if fails(prop, cand):
            best, progress = cand, True
            trace.append((evals, gen.size(best), best))
            break
```

The subtle part is not in that loop; it is in `candidates()`. **Every proposal must be strictly smaller by some measure**, or the search cycles. The first draft of `Ints.candidates` offered `n-1` and `n+1` symmetrically, so `0` proposed `1`, `1` proposed `0`, and the shrinker spun until it hit its 20,000-evaluation cap and returned a value that was not minimal. The fix is to make the ordering explicit:

```python
    def candidates(self, n: int) -> Iterator[int]:
        floor = min(max(0, self.lo), self.hi)      # the in-range value nearest 0

        def ok(v: int) -> bool:
            return self.lo <= v <= self.hi and abs(v - floor) < abs(n - floor)
```

The **property functions themselves** are the smallest part of the file and deliberately so — this is the whole suite that beat forty hand-written tests:

```python
def prop_roundtrip(case: Tuple[str, int]) -> bool:
    key, rid = case
    return decode_cursor(encode_cursor(key, rid)) == (key, rid)


def prop_survives_url(case: Tuple[str, int]) -> bool:
    key, rid = case
    return decode_cursor(through_url(encode_cursor(key, rid))) == (key, rid)


def prop_pagination(case: Tuple[List[Row], int]) -> bool:
    rows, size = case
    rows = dedupe_ids(rows)
    return walk_pages(rows, size) == sorted(rows)
```

`through_url` is the one piece of modelling in there, and it is three words long: `token.replace("+", " ")`. That single line encodes the fact that a form decoder turns `+` into a space, and it is the entire reason the property can see a bug that no round-trip test in the file could. **A property is only as good as its model of the world the value passes through** — if you never model the URL, you never test the URL.

Text shrinks by deleting blocks largest-first and then simplifying characters toward `a`; lists shrink by deleting blocks and then shrinking each element; tuples shrink component by component. Fifty lines of `candidates()` in total, and they produced every counterexample in this lesson.

The **coverage instrumentation** for the fuzzer is explicit `br(n)` calls rather than `sys.settrace`, and that is an engineering choice worth stating: a tracer costs roughly an order of magnitude per executed line, and a fuzzer's entire game is executions per second. [Coverage Lies, Mutation Testing Doesn't](../13-coverage-and-mutation-testing/) builds the real tracer.

```python
if "[" in key:
    br(11)
if key.endswith("]"):
    br(12)
if "[" in key and key.endswith("]"):
    br(13)
    name, _, idx = key[:-1].partition("[")
    slot = int(idx)                            # BUG: idx may be "" or "x"
```

Branches 11 and 12 exist so the ladder is *climbable*: reaching either one is new coverage, so the guided fuzzer keeps that input and mutates it further. Without those intermediate branches, coverage guidance has nothing to reward and degenerates to random search — which is the single most useful thing to know about instrumenting your own code for a fuzzer.

Run it:

```bash
python3 phases/12-testing-and-quality/12-property-based-testing-and-fuzzing/code/property_testing.py
```

```console
== 1 · FORTY EXAMPLES VERSUS THREE PROPERTIES ==
  baseline (no bugs): example suite 40/40 green, failures none

    bug                     example suite (40 tests)   the property that found it   cases
    url alphabet            silent, 40/40 green        survives a URL            5
    unicode normalisation   silent, 40/40 green        round-trip                4
    tie ordering            silent, 40/40 green        pagination is complete    10

  kill rate: 40 hand-written examples 0/3   ·   3 properties 3/3
  the examples are ~120 lines of test code; the properties are 15.

== 2 · SHRINKING: 4,000 CHARACTERS OF NOISE TO A BUG REPORT ==
  first failing case: a 4,000-character sort key, row id 727
    '\u10c7\u4241iLZ\u88c0m\xd8Ss\u76a1\xd9\u033c0dPk\xcd\u0313=e-\...
  after shrinking:    a 2-character sort key, row id 0
    'a\u0328'  ->  returned False
  58 candidate inputs evaluated, 15 of them accepted as smaller.

    accepted   after N evals   key chars   the input that still fails
           0               0        4000   ('\u10c7\u4241iLZ\u88c0m\xd8Ss\u76a1\xd...
           1               2        2000   ('v\u030e\u2dc4\\\\\u0338Y.3^{\u0323lWt...
           2               4        1000   ('[\u032f4w\ubd77g\ub549i~k\u032d\u214a...
           3               6         500   ('A\u0307C\u0354\\\\7B6\ua5dd\\ue340\\n...
           4               8         250   (';Q\xce+\u5e3a\u030a&5\xa4\u7693r\xc1p...
          ...             ...         ...   (steps 5-10: 125, 124, 93, 47, 24, 12 chars)
          11              28           6   ('p\xc2\u0328\u0360\xafa', 727)
          12              31           3   ('p\xc2\u0328', 727)
          13              33           2   ('\xc2\u0328', 727)
          14              37           2   ('a\u0328', 727)
          15              48           2   ('a\u0328', 0)

  a 2,000x reduction in key length for 58 property evaluations. Shrinking is cheap
  because deleting half of a failing input either still fails — in which
  case you keep it — or does not, in which case you have lost one call.

== 3 · GENERATOR DISTRIBUTION: THE SAME PROPERTY, THREE GENERATORS ==
    bug        triggers when   share of int32     uniform over int32   uniform over 0..1000  boundary-biased (25%)
    negative   raw < 0              5.00e-01                2 cases              NOT FOUND                1 cases
    zero       raw == 0             2.33e-10              NOT FOUND            1,122 cases                8 cases
    upper      raw == 100           2.33e-10              NOT FOUND            5,215 cases              117 cases

    bug        boundary-biased  vs int32 uniform                  multiple
    zero                     8     4,294,967,296 cases expected   536,870,912x
    upper                  117     4,294,967,296 cases expected    36,709,122x

== 4 · STATEFUL TESTING: THE BUG IS IN THE SEQUENCE, NOT THE CALL ==
    sequences of length 1, 50,000 cases: no disagreement
    max sequence length   sequences drawn to the first disagreement
                      4   NOT FOUND in 20,000
                      5   2,654
                      6   327
                     40   1
  shrunk to 5 operations in 112 evaluations:
    1. put('b', 0)   2. put('d', 0)   3. put('c', 0)   4. get('b')   5. put('a', 0)
    implementation holds ['a', 'c', 'd'], model holds ['a', 'b', 'c']

== 5 · DIFFERENTIAL TESTING: THE FAST ONE MUST AGREE WITH THE SLOW ONE ==
    coordinates drawn from   cases to first disagreement   expected   (budget 60,000)
    0..20                                              4          2
    0..5,000                                         235        417
    0..1,000,000                                  35,648     83,333
    0..20 vs 0..1,000,000         8,912x the cases

== 6 · FUZZING: RANDOM BYTES VERSUS COVERAGE-GUIDED MUTATION ==
    fuzzer                       branches   cases to crash   the crashing input
    random bytes (Miller 1990)         13           21,085   b'\\xe4T\\x98[Zl\\x81...
    random printable ASCII             13            6,846   b'3k[?8O?5+]'
    coverage-guided                    13              888   b'na[me]&licename=&'
  shrunk from 17 bytes to 2: b'[]'  (34 candidates)

== 7 · SEEDS: A PROPERTY TEST THAT FINDS A NEW BUG IS NOT FLAKY ==
    max_examples   red runs (bug present)   red runs (bug fixed)
               5      177/300  ( 59.0%)            0/300  (  0.0%)
              25      293/300  ( 97.7%)            0/300  (  0.0%)
              50      300/300  (100.0%)            0/300  (  0.0%)

    run   seed      cases in db   verdict   cases to red
      1   20261118             0       RED   10
      2   20261119             1       RED   1
      3   20261120             1       RED   1
```

## Use It

Nothing above needs to be hand-rolled in production. `hypothesis` is the mature Python implementation and its defaults are good.

**`@given` and the strategies.** A property is a normal `pytest` test with a decorator:

```python
from hypothesis import given, assume, example, settings, HealthCheck
from hypothesis import strategies as st

@given(st.text(), st.integers(min_value=-2**31, max_value=2**31 - 1))
@example("ą", 0)                      # the shrunk case, pinned in source
def test_cursor_roundtrip(key: str, row_id: int) -> None:
    assert decode_cursor(encode_cursor(key, row_id)) == (key, row_id)
```

`st.text()` already draws combining marks, surrogates and `\x00`; `st.integers()` already biases toward `0`, `±1` and word boundaries. That bias is the product — section 3 priced it at **537 million to one**. Do not replace a strategy with `st.integers().map(lambda n: n % 1000)` or an equivalent narrowing unless you mean it; you are choosing which bugs remain findable.

**`assume` versus filtering.** `assume(cond)` discards a draw that does not satisfy a precondition. It is right for rare rejections and wrong for common ones — reject too much and hypothesis raises `FailedHealthCheck: filter_too_much`. Build the constraint into the strategy instead (`st.integers(min_value=1)`, `st.builds(...)`, `.flatmap(...)`) so every draw is usable.

**`@settings` — the four that matter.** `max_examples` (default 100) is the discovery-latency dial measured in section 7: **59.0% of seeds at 5, 97.7% at 25, 100% at 50**. Use `@settings(max_examples=1000)` on a nightly job and leave the default on pull requests. `deadline` (default 200 ms per example) fails a test that gets slow, which is useful for pure functions and hostile to anything touching a database — set `deadline=None` there. `derandomize=True` fixes the seed so CI is reproducible, at the cost of testing the same cases forever; prefer a random seed plus a cached database. `suppress_health_check=[HealthCheck.function_scoped_fixture]` is the one you will meet when combining `@given` with pytest fixtures — and it is a warning worth reading rather than silencing, because a function-scoped fixture is created *once* for all examples.

**The examples database.** `.hypothesis/examples` is where shrunk failures are recorded and replayed first. In GitHub Actions:

```yaml
- uses: actions/cache@v4
  with:
    path: .hypothesis
    key: hypothesis-${{ github.run_id }}
    restore-keys: hypothesis-        # restore from ANY previous run, not just this one
```

The `restore-keys` prefix is the part that matters: without it the cache only ever restores an exact key match and the database is effectively empty every run. And promote anything important into `@example(...)` in the source, where it is reviewable and permanent.

**Composite and derived strategies.** The generators that find the interesting bugs are usually the ones where two values are *related* — a page index derived from a row count, a substring drawn from a string you already generated. `st.composite` and `.flatmap()` are how you express that, and they are the difference between a generator that draws `(total, page)` independently (and essentially never lands on the last page) and one that draws `page` from `st.integers(0, ceil(total / size))`. Section 3's whole result is that this choice, not the property, decides what you find.

**`RuleBasedStateMachine` for stateful testing.** Section 4 hand-rolled this; hypothesis has it properly, with `@rule`, `@invariant`, `Bundle` for threading created objects between rules, and `@precondition`. Set `stateful_step_count` above the default of 50 only after you know your minimal counterexample length — section 4's cliff at 5 operations is the argument for never setting it *low*.

**Where property tests go in the suite.** They are unit tests with a bigger input set, so they belong in the fast job — but they have a variable, occasionally long, run time, which makes them a poor fit for a per-commit gate at high `max_examples`. The arrangement that works: default settings on pull requests, a nightly job with `max_examples` in the thousands and a cached database, and a hard `@settings(deadline=None)` on anything doing I/O. Track how long the property job takes, because a strategy that starts generating 10,000-element lists will quietly become the slowest thing you own.

**`hypothesis.target()` for guided search.** Property testing and fuzzing converge here: calling `target(score)` inside a property tells hypothesis to prefer inputs that push `score` higher, so you can steer it toward long queues, deep recursion, or large allocations rather than waiting for a uniform draw to get there. It is the same idea as section 6's coverage guidance — keep what got closest — expressed as a number you choose instead of a branch map.

**`schemathesis`** property-tests an HTTP API straight off its OpenAPI description, generating requests that satisfy the schema and asserting the responses conform to it: `schemathesis run --checks all http://localhost:8000/openapi.json`. It finds the class of bug where your handler returns a shape the spec forbids, which is precisely the seam [Contract Testing](../10-contract-testing/) formalises and [OpenAPI Contract-First](../../02-api-design/06-openapi-contract-first/) sets up.

**For bytes, `atheris`.** It is libFuzzer bound to CPython with real coverage instrumentation, so it is a true coverage-guided fuzzer rather than section 6's approximation. Write a `TestOneInput(data: bytes)` harness over your parser, run it with a seed corpus, and keep the corpus in the repository. **OSS-Fuzz** is the continuous version — it runs your harness forever on Google's infrastructure and files issues; it is free for open source and worth it for anything parsing untrusted input.

**What to actually pick.** For any backend module, in this order:

1. **The round-trip property, if the module has an encode/decode pair.** One line, and it caught two of this lesson's three bugs. Cursors, tokens, serializers, IDs.
2. **The invariant that the output is well-formed** — sorted, disjoint, non-negative, no longer than `limit`. Cheap and it never restates the implementation.
3. **A differential test against the obvious slow version**, whenever you have optimised something. You need no property at all; you need a second implementation you would defend in review.
4. **A stateful model test for anything with memory** — a cache, a rate limiter, a queue, a session store. Section 4's bug is invisible to every other kind of test in this phase.
5. **`atheris` or `schemathesis` on anything parsing untrusted input.** Miller's 1990 result — a third of utilities crashing on noise — has been re-measured on every new class of software since, and it keeps holding.

Cache the examples database, pin shrunk failures with `@example`, and never quarantine a property test.

## Think about it

1. Section 3's honest `int32` generator never found the `raw == 0` bug in 200,000 cases, while the naive `rng.randint(0, 1000)` found it in 1,122 and missed the negative bug entirely. You now have to choose one generator for a `limit` parameter in a real service. What do you pick, and what does your answer tell you about where you believe that code's bugs actually are?
2. Section 4 measured a hard cliff: at a maximum sequence length of 4 the LRU bug is unfindable at any budget, and at 5 it takes 2,654 sequences. For a component you work on, how would you *estimate* the minimal counterexample length before you have ever seen a counterexample — and what would you set `stateful_step_count` to given that you cannot?
3. In section 6 the random fuzzer reached `'[' in a key` at execution 8 and the guided fuzzer at 168, yet the guided fuzzer reached the crash 7.7× sooner. Explain the mechanism precisely. Then describe a target where that relationship would reverse and random fuzzing would win.
4. Section 7 shows 0 red runs out of 1,800 on correct code, and between 59.0% and 100% red on broken code depending on `max_examples`. Your team's CI policy auto-retries any failing test twice ([Flaky Tests](../09-flaky-tests/) measured what that costs). What does that policy do to a property test specifically, and is the answer different from what it does to an ordinary test?
5. The tautological property killed 0 of 3 bugs while the weakest honest one — "never crashes" — killed 1. Take a property you would write for a module you own and decide, without running it, which of those two it resembles. What is the test you can apply to a property to tell the difference?

## Key takeaways

- **An example test can only check a case you already thought of.** Measured on one pagination cursor codec with three real bugs: **40 hand-written example tests killed 0 of 3** and stayed **40/40 green** on every one, while **3 properties (15 lines) killed 3 of 3** in **5, 4 and 10 generated cases**. The suite was not careless — it covered empty keys, 200-character keys, CJK, emoji, `-1` and `2**31 - 1`.
- **Shrinking is what makes the technique usable, and it is cheap.** A **4,000-character** failing input reduced to **2 characters** in **58 property evaluations**, of which only **15** were accepted. The first five reductions halved the input for **2 evaluations each**. The result — `("ą", 0)` — names the bug without any prose.
- **The generator is a hypothesis about where the bugs are.** Holding the property, the code and the budget fixed and changing only how an integer is drawn moved one bug from **8 cases** (boundary-biased) to an expected **4,294,967,296** (uniform `int32`) — **537 million to one**. The same effect appears in differential testing: **4 cases** at coordinates `0..20` versus **35,648** at `0..1,000,000`, an **8,912×** difference.
- **Some bugs exist only in the sequence.** An LRU cache whose `get` fails to refresh recency survived **50,000 single-operation cases**, and is **unfindable at any budget** with sequences capped at 4 operations because the minimal counterexample is 5. Generate long sequences and let the shrinker cut them: **21 operations down to 5**, on **60 of 60 seeds**.
- **Coverage guidance is memory, not better randomness.** Against a parser whose crash needs two conditions at once, guided mutation crashed in **888 executions** versus **6,846** for random printable bytes and **21,085** for uniform random bytes — while *losing* the race to every individual branch (`[` in a key at **168** versus **8**). It wins by keeping near misses; random fuzzing discards them.
- **A property test that finds a new bug on a new seed is not flaky.** Over **1,800 runs on correct code** it went red **zero** times. On broken code it went red on **59.0%** of seeds at `max_examples=5` and **100%** at 50. A flake is a false positive that costs trust; this is a delayed true positive that costs latency, and recording the counterexample removes even that — after the first red run, seven different seeds all failed at **case 1**.
- **Cache the regression database; do not `.gitignore` it.** `.hypothesis/examples` is the only thing converting a lucky discovery into a deterministic test, and a CI cache without a `restore-keys` prefix restores nothing.
- **A property read off the implementation proves nothing.** One that recomputed the encoder's own expression killed **0 of 3** bugs while generating 3,000 cases and looking identical to its neighbours — the same failure mode as a hand-written mock. State properties from the caller's side; that is why "never crashes" is weak and honest, and it still killed 1 of 3.
- **No single property is strong; the set is.** The best one killed **2 of 3**, the others **1 of 3**, and together they killed **3 of 3**. When a property test finds nothing, the move is to write another property, not a better one.

Next: [Coverage Lies, Mutation Testing Doesn't](../13-coverage-and-mutation-testing/) — how to measure whether the properties you just wrote actually detect anything, by breaking the code on purpose and seeing whether the suite notices.
