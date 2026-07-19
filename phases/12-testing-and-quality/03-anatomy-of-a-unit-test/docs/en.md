# Anatomy of a Unit Test

> Two test suites over the same pricing module, **59 lines each**, scored against the same 25 seeded bugs. One catches **11**. The other catches **23**. The weak one is not lazy — it has *more* assertions (31 against 17) and one test carrying **fourteen** of them, of which only **six** were ever the failure you were shown while the other eight broke 26 times in silence. And when a refactor that provably changes no money at all lands, **6 of the 10 weak tests go red and 0 of the 14 good ones do**. Same language, same module, same budget. Everything that separates them is in this lesson.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Why Tests Exist: The Cost of Finding a Bug Late](../01-why-tests-exist/), [The Shape of a Test Suite](../02-the-shape-of-a-test-suite/)
**Time:** ~70 minutes

## The Problem

**Tuesday, 09:12.** Pull request #4417 is open in front of you: *"add tests for pricing"*. **Ten new tests, 59 lines, 31 assertions.** The CI badge is green. The whole file runs in well under a second. Coverage on `pricing.py` clears the gate the team argued about for a month, and every line of the module is executed. Two colleagues have already approved it.

**Nine days ago** the same module shipped a one-character change. In the tier-discount lookup, `subtotal >= threshold` became `subtotal > threshold`. Every order for **exactly £50.00** — the boundary of the 5% tier — was charged 5% too much. Not orders near £50.00. Orders *at* it. Round numbers are what a catalogue of round prices produces, so this was not a freak event; it ran for nine days before finance noticed the refund pattern and someone went looking.

So the honest question about PR #4417 is not "does it pass". It is: **would these ten tests have caught that?**

Take the bug, re-apply it, run the new suite. It stays green. Take twenty-four more one-line bugs of the same character — a threshold moved by one, a rounding mode flipped, an error type swapped, a default changed — and run the suite against each. It catches **11 of 24**. It catches **one boundary bug out of seven**, and **zero of three** rounding bugs. The bug that cost nine days of refunds is not among them.

Read three of the ten and it stops being a mystery.

The first is called `test_1`. It makes three calls, then fourteen assertions about the result: the subtotal, the discount, the tax, the total, that the total is an integer, that the debug label tuple is `("tier:500", "coupon:0")`, that the receipt string starts with `Subtotal: $130.00`. It reads like diligence. Measured, it is the opposite: when any of the 24 bugs is present it reports **one** broken fact and never evaluates the rest, and across the whole bug set **74% of what that test knows is never printed**.

The second is called `test_happy_path`. Its first two lines replace the tier lookup and the coupon lookup with stubs that return fixed numbers. Then it asserts the discount. It is green, it is about pricing, and there are **nine bugs it cannot detect at any input whatsoever** — it is asserting that a stub returned the value the test configured the stub to return.

The third is called `test_pricing`. It asserts that a formatted receipt string equals `"Subtotal: $100.00 | Discount: -$5.00 | Tax: $7.84 | Total: $102.84"`. That one does check real arithmetic. It also goes red the day somebody changes a pipe to a comma.

Every one of the three passes. Every one of the three runs the code. Coverage counts all three. And here is the sentence the whole lesson turns on:

> **A test that cannot fail when the code is wrong is not a test — it is a line of code that runs, and running a line is not testing it.**

The rest of this lesson is about the difference, measured. Everything below comes from `code/unit_tests.py`, which builds a real pricing module, seeds 25 one-line bugs into it, writes two suites of *identical size* over it, and scores them. Seeding faults and counting which ones a suite detects is called **mutation testing**; [Lesson 13](../13-coverage-and-mutation-testing/) builds the engine that generates the bugs automatically and explains why the score means what it means. Here it is used only as the measuring instrument, hand-seeded, so that every claim in this lesson has a number behind it instead of an opinion.

## The Concept

### What a "unit" actually is — and the ceiling your answer sets

The word "unit" has been the source of more bad test suites than any other word in this phase, because the obvious reading — *a unit is a function, or a class* — is wrong in a way that costs you before you write a single assertion.

The module under test is 77 lines. It has five public names, two private helpers (`_tier_bps`, `_coupon_bps`) and four exception types. It turns a list of line items plus an optional coupon into a `Quote`: subtotal, discount, tax, total. All money is **integer cents** — `0.1 + 0.2 != 0.3` in binary floating point, and a pricing engine that drifts by a cent per order drifts by real money at volume.

Now seed 25 bugs into it, one edit each, and ask a purely structural question before any test exists: **if you point a test at function X, which bugs can it possibly reach?** A test can only detect a bug in code it actually runs, so the reach of a test aimed at a function is that function plus everything the function calls.

```text
  if you point a test at...               it also runs  bugs in reach  ceiling
  div_round()                                        -              2      8%
  subtotal_cents()                                   -              3     12%
  _tier_bps()                                        -              5     21%
  _coupon_bps()                                      -              4     17%
  price_order()                       all four helpers             24    100%
```

Testing `_tier_bps()` directly — which is precisely what the "one test file per class, one test per method" convention pushes you toward — **caps you at 21%**. Not because your assertions are weak. Because nothing you write inside that file can reach the rounding, the coupon window or the tax base. You chose your ceiling when you chose your unit, before you thought about a single input.

This is what the sharper definition is for. **A unit is a behaviour the caller can name**, not whichever function your IDE generated a stub for. "An order of exactly £50.00 gets the 5% tier." "A coupon still applies on its last valid day." "Tax is charged on the discounted amount." Each of those is falsifiable, each is stated in the vocabulary of the person paying for the software, and each is driven through the public entry point — which is why the last row of that table reads 100%.

There is a second, quieter payoff, and section 8 measures it: a test bound to a behaviour survives a refactor that moves the behaviour between functions. A test bound to `_tier_bps` does not, because `_tier_bps` is not a promise to anyone.

One honest note before the numbers start. Of the 25 seeded bugs, **24 change an observable result** on at least one of 808 systematically chosen inputs. One does not: `q % 2 == 1` became `q % 2 != 0`, and `q` is never negative, so the two are the same program. That is an **equivalent mutant** — a source change with no behavioural consequence — and no test can ever kill it. Detecting them in general is undecidable, which is why a 100% kill rate is not a target and why every rate below is quoted over the 24 that are killable.

### Arrange, Act, Assert — and why the shape is not decoration

**Arrange, Act, Assert (AAA)** is the claim that a test should have exactly three parts in exactly that order: build the world the assertion depends on, perform *one* operation, then check the result. It gets taught as a formatting convention, which is why it gets ignored.

It is not a formatting convention. It is a structural constraint with two measurable consequences, and the way to see that is to stop arguing and parse the tests. The program walks the **AST** (Abstract Syntax Tree — the parsed structure of the source, which is how Python sees your code before it runs it) of every test in both suites and counts two things: `assert` statements, and *acts* — calls into the module under test.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 480" width="100%" style="max-width:840px" role="img" aria-label="Two tests over the same pricing module drawn side by side. On the left, a good test in three clearly separated bands: arrange builds one order, act makes a single call to price_order, assert checks one fact about the discount. On the right, the bad test makes three separate calls into the module and stacks fourteen assertions after them, so the arrange, act and assert phases are interleaved and there is no single fact under test. Below, the measured shape of both suites parsed from their own abstract syntax trees: the bad suite has ten tests, fifty-nine lines, thirty-one assertions with fourteen in its worst test and only seven of ten tests making a single call; the good suite has fourteen tests in the same fifty-nine lines, seventeen assertions with a maximum of two, and all fourteen tests make exactly one call.">
  <defs>
    <marker id="p12-03-a1" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#7f7f7f"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="24" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">One act, one reason to fail — versus three acts and fourteen</text>

    <text x="225" y="50" text-anchor="middle" font-size="11.5" font-weight="700" fill="#0fa07f">good_test_tax_is_charged_on_the_discounted_amount</text>
    <text x="655" y="50" text-anchor="middle" font-size="11.5" font-weight="700" fill="#d64545">bad_test_1</text>

    <rect x="30" y="62" width="390" height="196" rx="9" fill="none" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.4"/>
    <rect x="460" y="62" width="390" height="196" rx="9" fill="none" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.4"/>

    <rect x="42" y="74" width="366" height="34" rx="6" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff" stroke-width="1.5"/>
    <text x="52" y="90" font-size="8.5" font-weight="700" fill="#3553ff">ARRANGE</text>
    <text x="52" y="103" font-size="9" fill="currentColor" opacity="0.9">items = ((&quot;sku&quot;, 20000, 1),)  ·  coupon SAVE25</text>

    <rect x="42" y="116" width="366" height="34" rx="6" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="1.5"/>
    <text x="52" y="132" font-size="8.5" font-weight="700" fill="#7c5cff">ACT — exactly one call</text>
    <text x="52" y="145" font-size="9" fill="currentColor" opacity="0.9">q = mod.price_order(items, &quot;SAVE25&quot;, 0)</text>

    <rect x="42" y="158" width="366" height="34" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.5"/>
    <text x="52" y="174" font-size="8.5" font-weight="700" fill="#0fa07f">ASSERT — one fact</text>
    <text x="52" y="187" font-size="9" fill="currentColor" opacity="0.9">assert (q.tax_cents, q.total_cents) == (1238, 16238)</text>

    <text x="225" y="214" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">3 lines. If it goes red, the name already told you what broke.</text>
    <text x="225" y="234" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">kills 9 of the 24 bugs on its own</text>
    <text x="225" y="250" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.75">more than the over-mocked test and the spy combined</text>

    <rect x="486" y="74" width="258" height="20" rx="5" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="1.3"/>
    <text x="496" y="88" font-size="9" fill="currentColor" opacity="0.9">q = mod.price_order(...)</text>
    <g fill="#d64545" fill-opacity="0.14" stroke="#d64545" stroke-width="1.1">
      <rect x="486" y="100" width="258" height="9" rx="2"/><rect x="486" y="112" width="258" height="9" rx="2"/><rect x="486" y="124" width="258" height="9" rx="2"/><rect x="486" y="136" width="258" height="9" rx="2"/><rect x="486" y="148" width="258" height="9" rx="2"/><rect x="486" y="160" width="258" height="9" rx="2"/><rect x="486" y="172" width="258" height="9" rx="2"/><rect x="486" y="184" width="258" height="9" rx="2"/><rect x="486" y="196" width="258" height="9" rx="2"/><rect x="486" y="208" width="258" height="9" rx="2"/><rect x="486" y="220" width="258" height="9" rx="2"/>
    </g>
    <rect x="486" y="232" width="258" height="9" rx="2" fill="#7c5cff" fill-opacity="0.20" stroke="#7c5cff" stroke-width="1.1"/>
    <rect x="486" y="244" width="258" height="9" rx="2" fill="#d64545" fill-opacity="0.14" stroke="#d64545" stroke-width="1.1"/>

    <g font-size="7.5" font-weight="700">
      <text x="752" y="88" fill="#7c5cff">ACT 1</text><text x="752" y="107" fill="#d64545">the one you see</text><text x="752" y="240" fill="#7c5cff">ACT 2 · ACT 3</text>
    </g>
    <path d="M478 100 L 478 229" fill="none" stroke="#d64545" stroke-width="2" opacity="0.85"/>
    <path d="M478 229 L 478 253" fill="none" stroke="#d64545" stroke-width="2" opacity="0.85" marker-end="url(#p12-03-a1)"/>
    <text x="468" y="170" font-size="8" fill="#d64545" text-anchor="middle" transform="rotate(-90 468 170)" font-weight="700">14 asserts</text>

    <text x="225" y="276" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">One act. One proposition. One reason to fail.</text>
    <text x="655" y="276" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">Python evaluates them in order and stops at the first that raises.</text>

    <rect x="30" y="292" width="820" height="122" rx="9" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.5"/>
    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.65">
      <text x="46" y="312">PARSED FROM THE SUITES' OWN ABSTRACT SYNTAX TREES</text><text x="420" y="312">TESTS</text><text x="500" y="312">LINES</text><text x="586" y="312">ASSERTS</text><text x="676" y="312">WORST TEST</text><text x="782" y="312">1 ACT</text>
    </g>
    <g fill="currentColor" font-size="11">
      <text x="46" y="336" font-weight="700" fill="#d64545">bad suite</text><text x="420" y="336">10</text><text x="500" y="336">59</text><text x="586" y="336">31</text><text x="676" y="336" font-weight="700" fill="#d64545">14 asserts</text><text x="782" y="336" fill="#d64545" font-weight="700">7/10</text>
      <text x="46" y="360" font-weight="700" fill="#0fa07f">good suite</text><text x="420" y="360">14</text><text x="500" y="360">59</text><text x="586" y="360">17</text><text x="676" y="360" font-weight="700" fill="#0fa07f">2 asserts</text><text x="782" y="360" fill="#0fa07f" font-weight="700">14/14</text>
    </g>
    <text x="46" y="386" font-size="9.5" fill="currentColor" opacity="0.9">The weaker suite has 82% MORE assertions. Assertion count is not detection, and</text>
    <text x="46" y="401" font-size="9.5" fill="currentColor" opacity="0.9">14 assertions in one body is 1 assertion of reporting with 13 of maintenance.</text>

    <text x="440" y="440" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">More assertions is not more testing. One act per test is what makes a red build readable.</text>
    <text x="440" y="462" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">Both suites are 59 lines over the same 77-line module. Section 3 scores them.</text>
  </g>
</svg>
```

Two acts in one test means two units under test, and a failure cannot tell you which one broke. The good suite is **14 tests in 59 lines with 17 assertions, a maximum of 2 in any test, and all 14 making exactly one call**. The bad suite is **10 tests in the same 59 lines with 31 assertions, 14 in its worst, and 7 of 10 single-act**. The weaker suite has 82% more assertions. Hold that next to everything that follows.

### Same module, same 59 lines, twice the bugs caught

This is the headline, and the matching matters. It is easy to prove a good suite beats a bad suite by writing three times as much of it. Both suites here are **59 lines** of test code by the same counting rule — non-blank, non-comment lines including the `def` — over the same module, run against the same 25 seeded bugs, in the same runner.

The bad suite is not a straw man. Every shape in it ships every day: the fourteen-assertion happy path, the exact-string assertion on a formatted receipt, the test that stubs out the logic it is nominally testing, the test of the constructor, the smoke test, the spy that asserts which calls were made. The good suite is 14 behaviour-named tests, four of which are parametrized tables sitting on boundaries.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 536" width="100%" style="max-width:840px" role="img" aria-label="A dot matrix comparing two test suites of fifty-nine lines each against twenty-four killable seeded bugs, grouped by bug category. For each category a filled circle means the bug was caught and a hollow circle means it survived. The bad suite catches one of seven boundary bugs, zero of three rounding bugs, four of five arithmetic, two of three conditional, one of three exception, one of one default and two of two field bugs, eleven in total. The good suite catches all seven boundary, all three rounding, all five arithmetic, all three conditional, all three exception, the one default and one of two field bugs, twenty-three in total. The bad suite scores forty-six percent and the good suite ninety-six percent, a factor of two point zero nine, for identical suite size.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="24" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">59 lines of tests either way. 11 bugs caught, or 23.</text>
    <text x="440" y="44" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">filled = the suite detected the bug · hollow = the bug shipped green</text>

    <text x="300" y="72" text-anchor="middle" font-size="11.5" font-weight="700" fill="#d64545">BAD SUITE · 10 tests · 59 lines</text>
    <text x="640" y="72" text-anchor="middle" font-size="11.5" font-weight="700" fill="#0fa07f">GOOD SUITE · 14 tests · 59 lines</text>
    <path d="M470 60 L 470 296" fill="none" stroke="currentColor" stroke-width="1.1" stroke-dasharray="4 4" opacity="0.35"/>

    <g fill="currentColor" font-size="9.5" text-anchor="end" opacity="0.9">
      <text x="152" y="104">boundary  (7)</text><text x="152" y="134">rounding  (3)</text><text x="152" y="164">arithmetic  (5)</text><text x="152" y="194">conditional  (3)</text><text x="152" y="224">exception  (3)</text><text x="152" y="254">default  (1)</text><text x="152" y="284">field  (2)</text>
    </g>

    <g stroke="#d64545" stroke-width="1.6">
      <circle cx="176" cy="100" r="7" fill="#d64545" fill-opacity="0.75"/><circle cx="202" cy="100" r="7" fill="none"/><circle cx="228" cy="100" r="7" fill="none"/><circle cx="254" cy="100" r="7" fill="none"/><circle cx="280" cy="100" r="7" fill="none"/><circle cx="306" cy="100" r="7" fill="none"/><circle cx="332" cy="100" r="7" fill="none"/>
      <circle cx="176" cy="130" r="7" fill="none"/><circle cx="202" cy="130" r="7" fill="none"/><circle cx="228" cy="130" r="7" fill="none"/>
      <circle cx="176" cy="160" r="7" fill="#d64545" fill-opacity="0.75"/><circle cx="202" cy="160" r="7" fill="#d64545" fill-opacity="0.75"/><circle cx="228" cy="160" r="7" fill="#d64545" fill-opacity="0.75"/><circle cx="254" cy="160" r="7" fill="#d64545" fill-opacity="0.75"/><circle cx="280" cy="160" r="7" fill="none"/>
      <circle cx="176" cy="190" r="7" fill="#d64545" fill-opacity="0.75"/><circle cx="202" cy="190" r="7" fill="#d64545" fill-opacity="0.75"/><circle cx="228" cy="190" r="7" fill="none"/>
      <circle cx="176" cy="220" r="7" fill="#d64545" fill-opacity="0.75"/><circle cx="202" cy="220" r="7" fill="none"/><circle cx="228" cy="220" r="7" fill="none"/>
      <circle cx="176" cy="250" r="7" fill="#d64545" fill-opacity="0.75"/>
      <circle cx="176" cy="280" r="7" fill="#d64545" fill-opacity="0.75"/><circle cx="202" cy="280" r="7" fill="#d64545" fill-opacity="0.75"/>
    </g>
    <g fill="currentColor" font-size="9.5" font-weight="700" opacity="0.85">
      <text x="366" y="104">1/7</text><text x="366" y="134">0/3</text><text x="366" y="164">4/5</text><text x="366" y="194">2/3</text><text x="366" y="224">1/3</text><text x="366" y="254">1/1</text><text x="366" y="284">2/2</text>
    </g>

    <g stroke="#0fa07f" stroke-width="1.6">
      <circle cx="516" cy="100" r="7" fill="#0fa07f" fill-opacity="0.75"/><circle cx="542" cy="100" r="7" fill="#0fa07f" fill-opacity="0.75"/><circle cx="568" cy="100" r="7" fill="#0fa07f" fill-opacity="0.75"/><circle cx="594" cy="100" r="7" fill="#0fa07f" fill-opacity="0.75"/><circle cx="620" cy="100" r="7" fill="#0fa07f" fill-opacity="0.75"/><circle cx="646" cy="100" r="7" fill="#0fa07f" fill-opacity="0.75"/><circle cx="672" cy="100" r="7" fill="#0fa07f" fill-opacity="0.75"/>
      <circle cx="516" cy="130" r="7" fill="#0fa07f" fill-opacity="0.75"/><circle cx="542" cy="130" r="7" fill="#0fa07f" fill-opacity="0.75"/><circle cx="568" cy="130" r="7" fill="#0fa07f" fill-opacity="0.75"/>
      <circle cx="516" cy="160" r="7" fill="#0fa07f" fill-opacity="0.75"/><circle cx="542" cy="160" r="7" fill="#0fa07f" fill-opacity="0.75"/><circle cx="568" cy="160" r="7" fill="#0fa07f" fill-opacity="0.75"/><circle cx="594" cy="160" r="7" fill="#0fa07f" fill-opacity="0.75"/><circle cx="620" cy="160" r="7" fill="#0fa07f" fill-opacity="0.75"/>
      <circle cx="516" cy="190" r="7" fill="#0fa07f" fill-opacity="0.75"/><circle cx="542" cy="190" r="7" fill="#0fa07f" fill-opacity="0.75"/><circle cx="568" cy="190" r="7" fill="#0fa07f" fill-opacity="0.75"/>
      <circle cx="516" cy="220" r="7" fill="#0fa07f" fill-opacity="0.75"/><circle cx="542" cy="220" r="7" fill="#0fa07f" fill-opacity="0.75"/><circle cx="568" cy="220" r="7" fill="#0fa07f" fill-opacity="0.75"/>
      <circle cx="516" cy="250" r="7" fill="#0fa07f" fill-opacity="0.75"/>
      <circle cx="516" cy="280" r="7" fill="#0fa07f" fill-opacity="0.75"/><circle cx="542" cy="280" r="7" fill="none"/>
    </g>
    <g fill="currentColor" font-size="9.5" font-weight="700" opacity="0.85">
      <text x="706" y="104">7/7</text><text x="706" y="134">3/3</text><text x="706" y="164">5/5</text><text x="706" y="194">3/3</text><text x="706" y="224">3/3</text><text x="706" y="254">1/1</text><text x="706" y="284">1/2</text>
    </g>

    <text x="762" y="288" font-size="8" fill="#e0930f" font-weight="700">D03</text>
    <text x="440" y="312" text-anchor="middle" font-size="9.5" fill="#e0930f" opacity="0.95">D03 is the only bug the bad suite caught and the good one missed: it changes a debug label and no money.</text>
    <text x="440" y="326" text-anchor="middle" font-size="9.5" fill="#e0930f" opacity="0.95">The very same assertion goes red on a behaviour-preserving refactor — section 8.</text>

    <rect x="30" y="340" width="820" height="108" rx="9" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.5"/>
    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.65">
      <text x="48" y="360">25 SEEDED BUGS · 1 EQUIVALENT MUTANT · 24 KILLABLE</text><text x="454" y="360">LINES</text><text x="534" y="360">TESTS</text><text x="616" y="360">KILLED</text><text x="700" y="360">KILL RATE</text><text x="794" y="360">BUGS/LINE</text>
    </g>
    <g fill="currentColor" font-size="11.5">
      <text x="48" y="384" font-weight="700" fill="#d64545">bad suite</text><text x="454" y="384">59</text><text x="534" y="384">10</text><text x="616" y="384">11</text><text x="700" y="384" font-weight="700" fill="#d64545">46%</text><text x="794" y="384">0.186</text>
      <text x="48" y="408" font-weight="700" fill="#0fa07f">good suite</text><text x="454" y="408">59</text><text x="534" y="408">14</text><text x="616" y="408">23</text><text x="700" y="408" font-weight="700" fill="#0fa07f">96%</text><text x="794" y="408">0.390</text>
    </g>
    <text x="48" y="434" font-size="10" fill="currentColor" opacity="0.9">The gap is not spread evenly: it is almost entirely boundary (1/7 vs 7/7) and rounding (0/3 vs 3/3).</text>

    <text x="440" y="476" text-anchor="middle" font-size="12.5" font-weight="700" fill="currentColor">2.09x the detection for the same number of lines — and the difference is which inputs were chosen.</text>
    <text x="440" y="500" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">Not effort. Not assertion count. Not coverage. The bad suite ran every line the good one did.</text>
    <text x="440" y="520" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">Method: DeMillo, Lipton &amp; Sayward, &quot;Hints on Test Data Selection&quot;, IEEE Computer 11(4), 1978.</text>
  </g>
</svg>
```

**11 of 24 against 23 of 24. Same size.** The bugs/line figure — 0.186 against 0.390 — is the honest way to say it, because it is per unit of the thing you actually spend.

Now read the category rows, because that is where the lesson is. Both suites do fine on gross arithmetic: swap a `-` for a `+` in the tax base and almost anything notices. The bad suite scores **1 of 7 on boundaries** and **0 of 3 on rounding**. Those are not exotic bug classes. A threshold comparison and a rounding mode are the two places a pricing module keeps its actual business rules, and one entire style of testing is blind to both.

There is one row where the bad suite wins, and it is worth being honest about: **D03**, a change to a debug label from `tier:500` to `tier=500`, which alters no money at all. The bad suite catches it because it asserts on that label. Section 8 charges the same assertion for the same reason.

### One reason to fail: what a fourteen-assertion test hides

The intuition behind cramming assertions into one test is that more checks means more detection. It is worth being precise about why that is wrong, because the reason is mechanical rather than stylistic: **`assert` raises.** The first one that fails ends the function, and every assertion after it is never evaluated. A test with 14 assertions does not report 14 facts. It reports the first broken one and destroys the rest.

Measuring that requires running the assertions independently, which the program does by rewriting `bad_test_1`'s own AST: every `assert X` becomes `_rec(i, lambda: X)`, which records a verdict and carries on. That is exactly the mechanism pytest uses to print operand values on a failure, applied for the opposite purpose. The rewritten version is checked against the real test on every bug, so it is not a hand-made copy that can drift.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 520" width="100%" style="max-width:840px" role="img" aria-label="A ledger of the fourteen assertions inside one test, showing for each how many of the twenty-four seeded bugs actually break it, how often it was the failure the developer was shown, and how often it broke silently behind an earlier failure. Assertion four, the discount check, is broken by five bugs and reported three times. Assertion eight, the total check, is broken by seven bugs and reported once, masking six. Assertion six, the tax check, is broken by six and reported twice. Eight of the fourteen assertions were never once the reported failure despite breaking twenty-six times between them. In total the twenty-four bugs break thirty-five assertions in this single test, the runs report nine, and twenty-six or seventy-four percent are masked.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="24" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">14 assertions in one test. You are ever shown 6 of them.</text>
    <text x="440" y="44" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">measured over the 24 killable bugs: green = the failure you saw · amber = broke, never printed</text>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.65">
      <text x="30" y="70">#</text><text x="52" y="70">THE ASSERTION, AS WRITTEN IN THE TEST</text><text x="470" y="70">BROKEN BY N BUGS  ·  reported / masked</text>
    </g>
    <path d="M28 76 L 852 76" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.4"/>

    <g fill="currentColor" font-size="9">
      <text x="30" y="94">1</text><text x="52" y="94">q is not None</text>
      <text x="30" y="118">2</text><text x="52" y="118">q.subtotal_cents == 13000</text>
      <text x="30" y="142">3</text><text x="52" y="142" opacity="0.6">q.subtotal_cents &gt; 0</text>
      <text x="30" y="166">4</text><text x="52" y="166">q.discount_cents == 650</text>
      <text x="30" y="190">5</text><text x="52" y="190" opacity="0.6">q.discount_cents &lt; q.subtotal_cents</text>
      <text x="30" y="214">6</text><text x="52" y="214">q.tax_cents == 1019</text>
      <text x="30" y="238">7</text><text x="52" y="238" opacity="0.6">q.tax_cents &gt; 0</text>
      <text x="30" y="262">8</text><text x="52" y="262">q.total_cents == 13369</text>
      <text x="30" y="286">9</text><text x="52" y="286" opacity="0.6">q.total_cents &gt; q.subtotal_cents - q.discount_cents</text>
      <text x="30" y="310">10</text><text x="52" y="310" opacity="0.6">isinstance(q.total_cents, int)</text>
      <text x="30" y="334">11</text><text x="52" y="334">q.notes == ('tier:500', 'coupon:0')</text>
      <text x="30" y="358">12</text><text x="52" y="358" opacity="0.6">len(q.notes) == 2</text>
      <text x="30" y="382">13</text><text x="52" y="382" opacity="0.6">q2.total_cents == q.total_cents</text>
      <text x="30" y="406">14</text><text x="52" y="406" opacity="0.6">mod.format_receipt(q).startswith('Subtotal: $130.00')</text>
    </g>

    <g stroke-width="1.2">
      <rect x="470" y="86" width="40" height="11" fill="#0fa07f" fill-opacity="0.65" stroke="#0fa07f"/>
      <rect x="470" y="110" width="40" height="11" fill="#0fa07f" fill-opacity="0.65" stroke="#0fa07f"/><rect x="510" y="110" width="40" height="11" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f"/>
      <rect x="470" y="134" width="40" height="11" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f"/>
      <rect x="470" y="158" width="120" height="11" fill="#0fa07f" fill-opacity="0.65" stroke="#0fa07f"/><rect x="590" y="158" width="80" height="11" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f"/>
      <rect x="470" y="182" width="40" height="11" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f"/>
      <rect x="470" y="206" width="80" height="11" fill="#0fa07f" fill-opacity="0.65" stroke="#0fa07f"/><rect x="550" y="206" width="160" height="11" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f"/>
      <rect x="470" y="230" width="40" height="11" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f"/>
      <rect x="470" y="254" width="40" height="11" fill="#0fa07f" fill-opacity="0.65" stroke="#0fa07f"/><rect x="510" y="254" width="240" height="11" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f"/>
      <rect x="470" y="278" width="80" height="11" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f"/>
      <rect x="470" y="302" width="40" height="11" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f"/>
      <rect x="470" y="326" width="40" height="11" fill="#0fa07f" fill-opacity="0.65" stroke="#0fa07f"/><rect x="510" y="326" width="80" height="11" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f"/>
      <rect x="470" y="350" width="40" height="11" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f"/>
      <rect x="470" y="374" width="80" height="11" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f"/>
      <rect x="470" y="398" width="80" height="11" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f"/>
    </g>

    <g fill="currentColor" font-size="8.5" opacity="0.9">
      <text x="518" y="95">1</text><text x="558" y="119">2</text><text x="518" y="143">1</text><text x="678" y="167">5</text><text x="518" y="191">1</text><text x="718" y="215">6</text><text x="518" y="239">1</text><text x="758" y="263">7</text><text x="558" y="287">2</text><text x="518" y="311">1</text><text x="598" y="335">3</text><text x="518" y="359">1</text><text x="558" y="383">2</text><text x="558" y="407">2</text>
    </g>
    <g fill="#e0930f" font-size="8" font-weight="700">
      <text x="790" y="143">never seen</text><text x="790" y="191">never seen</text><text x="790" y="239">never seen</text><text x="790" y="287">never seen</text><text x="790" y="311">never seen</text><text x="790" y="359">never seen</text><text x="790" y="383">never seen</text><text x="790" y="407">never seen</text>
    </g>

    <rect x="30" y="424" width="820" height="58" rx="9" fill="#d64545" fill-opacity="0.08" stroke="#d64545" stroke-opacity="0.55" stroke-width="1.5"/>
    <g fill="currentColor" font-size="10.5">
      <text x="48" y="446"><tspan font-weight="700" fill="#d64545">35</tspan> assertions broken across the 24 bugs   ·   <tspan font-weight="700" fill="#0fa07f">9</tspan> reported   ·   <tspan font-weight="700" fill="#e0930f">26 masked = 74%</tspan></text>
      <text x="48" y="468">mean facts broken per failing run: <tspan font-weight="700">3.89</tspan>  —  that is how many fix-and-rerun round trips this one test costs</text>
    </g>
    <text x="440" y="506" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">A 14-assertion test does not fail with more information. It fails with the FIRST information.</text>
  </g>
</svg>
```

Read assertion **#8** — `q.total_cents == 13369`. Seven of the twenty-four bugs break it. It was the reported failure **once**. The other six times, something earlier had already raised. That assertion did real work six times and told nobody.

The totals: across the 24 killable bugs, this single test has **35 broken assertions**, the runs report **9**, and **26 — 74% of everything it knows — are masked**. Eight of its fourteen assertions were never once the failure you were shown, despite breaking 26 times between them. And **3.89 facts break per failing run**, which is the debugging shape that follows: fix the reported one, rerun the whole suite, learn the next, rerun again.

The rule that falls out is not "one assertion per test". It is **one reason to fail per test**. `assert (q.tax_cents, q.total_cents) == (1238, 16238)` is one assertion about two numbers that belong to one proposition, and it is fine. Fourteen assertions about six different subsystems is fourteen tests wearing a trench coat, and you only ever get to read the top one.

### The name is the failure report

At 02:00, in a CI (Continuous Integration) log, on a phone, the *only* thing you see first is a test name. Everything else — the diff, the traceback, the operand values — costs a context switch to a laptop. So the question a test name has to answer is: what proposition just became false?

The measurement: when the suite goes red on a bug, does any failing test's **name alone** identify the part of the system the bug is actually in?

```text
  suite    bugs caught  locatable from  red tests  that named it
                          a name alone
  bad               11            0/11         32         0 (0%)
  good              23           23/23         68       35 (51%)
```

**0 of 11 against 23 of 23.** The bad suite's names are `bad_test_1`, `bad_test_pricing`, `bad_test_happy_path`, `bad_test_it_works`. Look at what kind of thing each of those is. `test_1` is an ordinal. `test_pricing` is a topic. `test_happy_path` is a mood. **None of them is a statement that can be false** — and a name that cannot be false cannot report a failure, because the entire content of a red test is "this name is a lie".

The working convention is `test_<unit>_<condition>_<expected>`:

```python
good_test_tier_discount_changes_only_at_the_documented_thresholds
good_test_coupon_still_applies_on_its_last_valid_day
good_test_coupon_is_rejected_the_day_after_it_expires
good_test_tax_is_charged_on_the_discounted_amount
good_test_quantity_below_one_is_rejected_before_pricing
```

These are long, and that is the correct trade: you write the name once and read it every time the build breaks. The test to apply is **delete the body and see whether the name still tells you what broke.** If it does, the name is doing its job — and as a bonus, the test now has a specification you can check the body against, which is the cheapest review technique in this lesson.

The 51% column is worth reading honestly rather than as a win. It counts *every* red test, and a bug like C03 — which inverts a null check and breaks almost everything — turns 13 good tests red at once, most of which are not about coupons. That is not a naming failure; it is what a wide-blast bug looks like. The column that matters operationally is the middle one: for **every** bug the good suite caught, at least one red name pointed at the right subsystem.

### Boundaries, and the arithmetic of finding one by accident

Here is the result that changed how I write tests, and it is the argument for boundary-value testing that people usually make by assertion rather than by measurement.

Take the 8,000 orders a plausible generator produces: 16 catalogue prices, one to three line items, quantities of one to four, a real coupon or none, a day between 0 and 40. For each seeded bug, ask what fraction of those orders produce a *different answer* than the correct module. That fraction is the probability that a test written around a randomly-chosen realistic order would catch that bug. Turn it into the number you actually care about — how many such orders you would need before you are 95% likely to have tripped it even once — with `ceil(log 0.05 / log(1 − p))`.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 496" width="100%" style="max-width:840px" role="img" aria-label="A logarithmic number line showing, for each of twenty-four seeded bugs, how many randomly chosen realistic orders you would have to test before being ninety-five percent likely to trip it once. Eleven arithmetic, conditional, default, field and exception bugs sit at one to seven orders. The rounding bugs need thirty-six to one hundred and thirty-four. The boundary bugs need one hundred and thirty-nine to eight hundred and eighty-seven. Four bugs never appeared at all in eight thousand random orders. Beneath, a single parametrized boundary table of six lines and nine chosen cases kills ten of the twenty-four bugs, and four such tables totalling twenty lines and twenty-two cases kill fifteen, against the fifty-nine-line bad suite's eleven.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="24" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">How many random orders before you trip this bug by accident?</text>
    <text x="440" y="44" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">orders needed for a 95% chance of one hit — measured on 8,000 realistic orders, log scale</text>

    <g fill="none" stroke="currentColor" stroke-width="1.3">
      <path d="M120 300 L 800 300"/>
      <path d="M120 300 L 120 306"/><path d="M239 300 L 239 306"/><path d="M290 300 L 290 306"/><path d="M409 300 L 409 306"/><path d="M460 300 L 460 306"/><path d="M579 300 L 579 306"/><path d="M630 300 L 630 306"/><path d="M749 300 L 749 306"/><path d="M800 300 L 800 306"/>
    </g>
    <g fill="currentColor" font-size="8.5" text-anchor="middle" opacity="0.75">
      <text x="120" y="320">1</text><text x="239" y="320">5</text><text x="290" y="320">10</text><text x="409" y="320">50</text><text x="460" y="320">100</text><text x="579" y="320">500</text><text x="630" y="320">1,000</text><text x="749" y="320">5,000</text><text x="800" y="320">10,000</text>
    </g>
    <text x="440" y="338" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.75">random realistic orders you must run before a 95% chance of one hit</text>

    <g stroke-width="1.5">
      <circle cx="120" cy="284" r="6" fill="#7f7f7f" fill-opacity="0.6" stroke="#7f7f7f"/>
      <circle cx="239" cy="284" r="6" fill="#7f7f7f" fill-opacity="0.6" stroke="#7f7f7f"/><circle cx="239" cy="270" r="6" fill="#7f7f7f" fill-opacity="0.6" stroke="#7f7f7f"/><circle cx="239" cy="256" r="6" fill="#7f7f7f" fill-opacity="0.6" stroke="#7f7f7f"/><circle cx="239" cy="242" r="6" fill="#7f7f7f" fill-opacity="0.6" stroke="#7f7f7f"/><circle cx="239" cy="228" r="6" fill="#7f7f7f" fill-opacity="0.6" stroke="#7f7f7f"/><circle cx="239" cy="214" r="6" fill="#7f7f7f" fill-opacity="0.6" stroke="#7f7f7f"/><circle cx="239" cy="200" r="6" fill="#7f7f7f" fill-opacity="0.6" stroke="#7f7f7f"/><circle cx="239" cy="186" r="6" fill="#7f7f7f" fill-opacity="0.6" stroke="#7f7f7f"/>
      <circle cx="264" cy="284" r="6" fill="#7f7f7f" fill-opacity="0.6" stroke="#7f7f7f"/>
      <circle cx="309" cy="284" r="6" fill="#7f7f7f" fill-opacity="0.6" stroke="#7f7f7f"/>
      <circle cx="385" cy="284" r="6" fill="#7f7f7f" fill-opacity="0.6" stroke="#7f7f7f"/>
      <circle cx="402" cy="284" r="6" fill="#e0930f" fill-opacity="0.7" stroke="#e0930f"/>
      <circle cx="458" cy="284" r="6" fill="#e0930f" fill-opacity="0.7" stroke="#e0930f"/>
      <circle cx="482" cy="284" r="6" fill="#e0930f" fill-opacity="0.7" stroke="#e0930f"/>
      <circle cx="486" cy="268" r="6" fill="#3553ff" fill-opacity="0.7" stroke="#3553ff"/>
      <circle cx="501" cy="284" r="6" fill="#3553ff" fill-opacity="0.7" stroke="#3553ff"/>
      <circle cx="565" cy="284" r="6" fill="#3553ff" fill-opacity="0.7" stroke="#3553ff"/>
      <circle cx="587" cy="284" r="6" fill="#3553ff" fill-opacity="0.7" stroke="#3553ff"/>
      <circle cx="620" cy="284" r="6" fill="#3553ff" fill-opacity="0.7" stroke="#3553ff"/>
      <circle cx="812" cy="284" r="6" fill="#d64545" fill-opacity="0.75" stroke="#d64545"/><circle cx="812" cy="270" r="6" fill="#d64545" fill-opacity="0.75" stroke="#d64545"/><circle cx="812" cy="256" r="6" fill="#d64545" fill-opacity="0.75" stroke="#d64545"/><circle cx="812" cy="242" r="6" fill="#d64545" fill-opacity="0.75" stroke="#d64545"/>
    </g>
    <path d="M794 208 L 794 300" fill="none" stroke="#d64545" stroke-width="1.4" stroke-dasharray="4 4" opacity="0.7"/>

    <g font-size="8.5">
      <text x="239" y="172" text-anchor="middle" fill="currentColor" opacity="0.85">8 arithmetic, field and exception bugs — 5 orders each</text>
      <text x="120" y="272" text-anchor="middle" fill="currentColor" opacity="0.8">C03</text>
      <text x="402" y="270" text-anchor="middle" fill="#e0930f" font-weight="700">R02 · 46</text>
      <text x="466" y="252" text-anchor="middle" fill="#e0930f" font-weight="700">R01 · 96</text>
      <text x="536" y="264" text-anchor="middle" fill="#3553ff" font-weight="700">B01 · 139</text>
      <text x="565" y="240" text-anchor="middle" fill="#3553ff" font-weight="700">B03 · 405</text>
      <text x="640" y="270" text-anchor="middle" fill="#3553ff" font-weight="700">B04 · 887</text>
      <text x="852" y="228" text-anchor="end" fill="#d64545" font-weight="700">4 bugs, never seen in 8,000</text>
    </g>

    <g font-size="9.5" font-weight="700">
      <text x="46" y="366" fill="#7f7f7f">— arithmetic / conditional / exception / field</text><text x="336" y="366" fill="#e0930f">— rounding</text><text x="452" y="366" fill="#3553ff">— boundary</text><text x="580" y="366" fill="#d64545">— never reached by valid random input</text>
    </g>

    <rect x="30" y="382" width="820" height="74" rx="9" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f" stroke-opacity="0.55" stroke-width="1.5"/>
    <g fill="currentColor" font-size="9.5">
      <text x="48" y="404"><tspan font-weight="700" fill="#0fa07f">ONE 6-line parametrized table, 9 cases on the thresholds</tspan>  —  4999 / 5000 / 5001 · 19999 / 20000 / 20001 · 99999 / 100000 / 100001</text>
      <text x="48" y="422">kills <tspan font-weight="700">10 of the 24 bugs</tspan> on its own. FOUR such tables — 20 lines, 22 cases — kill <tspan font-weight="700">15 of 24</tspan>.</text>
      <text x="48" y="442">The 59-line bad suite kills 11. So: <tspan font-weight="700" fill="#0fa07f">34% of the code, 1.4x the detection</tspan>, from choosing the inputs on purpose.</text>
    </g>
    <text x="440" y="482" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">Boundaries are not rare inputs. They are the values the code branches on — which is exactly why random data misses them.</text>
  </g>
</svg>
```

The spread is three orders of magnitude. A swapped `+` in the tax base shows up on **half** of all orders — you would catch it with five random cases and no thought at all. The tier boundary bug **B04** shows up on **0.338%**, so you would need **887** randomly chosen realistic orders before you were 95% likely to have hit it once. And four bugs — including the coupon-minimum boundary — **never appeared at all in 8,000 orders.**

That gradient *is* the case for boundary-value analysis, and the mechanism is worth saying plainly: **a boundary bug is only visible on the exact input the code branches at.** Everywhere else the mutated program and the correct program agree, which is why plausible data does not find it and why the bug survives review, staging and a week of production before finance notices.

The other half of the result is the payoff. One parametrized table — 6 lines, 9 cases, every one of them a threshold or a cent either side of it — kills **10 of 24 bugs by itself**. Four such tables, **20 lines and 22 cases**, kill **15 of 24**, against the entire 59-line bad suite's 11. That is **34% of the code for 1.4× the detection**, and it comes from nothing more sophisticated than deciding, deliberately, that `4999`, `5000` and `5001` are three different inputs.

The discipline, which takes about thirty seconds per rule: for every comparison in the code, test the value, the value minus one, and the value plus one. For every rounding operation, test an exact half in both directions — `250.5` and `251.5` round to `250` and `252` under banker's rounding (half-to-even, the IEEE 754 default and what `ROUND_HALF_EVEN` means in Python's `decimal`) and to `251` and `252` under half-up. One of those two cases distinguishes them; the other does not. Pick the one that does.

### The unhappy path is where the invisible bugs live

Four of the 24 bugs — B07, E01, E02, E03 — **change nothing on any input the module accepts.** They live entirely in the branches that reject input: the quantity check, the unknown-coupon raise, the expiry raise. No amount of valid data reaches them, at any volume.

And three of those four never appeared in the 8,000 random orders at all, for a reason that generalises beyond this program: **a test-data generator written by someone thinking about pricing produces prices.** It produces valid quantities and real coupon codes, because those are what the author was holding in their head. The malformed order is not rare in the generator's distribution; it is absent from it.

Count the rejection tests in each suite and the pattern completes itself: **1 of 10 in the bad suite, 3 of 14 in the good one.** Error branches are simultaneously the least-exercised code you ship and the code that runs on your worst day — when a client sends garbage, when a partner's schema drifts, when a retry arrives with a stale coupon. Write those tests first, not last, and assert the error *type* and a stable machine-readable `code`, never the message text. Section 8 shows exactly what asserting the message costs.

### Assert on the outcome, not on the calls

There are two ways to check that a function did its job. **State verification** asserts on the result: the quote's numbers, the row in the database, the value returned. **Interaction verification** asserts on the calls the function made on its way there: that it invoked the audit port twice, with these arguments, in this order.

They sound like alternatives. Measured against the same 24 bugs, they are not.

```text
  assertion style                     lines  bugs killed  of   which
  interaction (asserts on calls)          6            0  24   -
  over-mocked (stubs the logic)           5            4  24   A01, A04, C01, D02
  string (asserts the receipt)            4            8  24   A01, A02, A03, A04, C01, C03, D01, D02
  state (asserts the money)               3            9  24   A01, A02, A03, A04, A05, C01, C03, D01, R02
  state (asserts an invariant)            4            4  24   A02, A03, C03, D02
```

The interaction test is **6 lines and kills nothing.** It is green when the discount is right and green when the discount is wrong, because it never looks at the discount — it asserts that `audit("discount", …)` was called and `audit("tax", …)` was called, which remains true no matter what numbers go into them. The three-line state test kills **9**.

The over-mocked test is worse than weak, and the word for it is *structural*. It replaces `_tier_bps` and `_coupon_bps` with stubs, so the **9 bugs living in those two functions cannot reach it at any input whatsoever.** It is not a poor test of the tier logic; it is incapable of being a test of the tier logic. It asserts that a stub returned the value the test configured the stub to return, which is a tautology with a `def` in front of it. [Lesson 04](../04-test-doubles/) prices this properly against a real provider that keeps changing underneath you.

The rule: **assert on the outcome the caller depends on.** Reach for an interaction assertion only when the interaction *is* the outcome — an email that must be sent exactly once, a payment that must not be charged twice, a message that must land on the queue. In those cases the call is the observable behaviour and asserting it is correct. Everywhere else, an interaction assertion is a copy of the current implementation, written in a second file, that will go red the day you change the implementation without changing the behaviour. Which is next.

### The brittle-assert tax: a refactor that changes no money

Now the experiment that prices assertion quality, because "assert on structure, not on strings" is advice until somebody counts.

Take the module and refactor it, five edits, none of which changes an amount:

1. rename the internal `notes` field to `applied` and its labels from `tier:500` to `tier=500`
2. reword one error message — the exception **type** is untouched
3. reformat the receipt string
4. split `_tier_bps()` into `_tier_index()` + `_bps_for_index()`
5. batch the two audit events into one

Then *prove* it changed nothing that matters: run **8,808 cases** — the 808-case systematic grid plus the 8,000 random orders — through both versions and compare every amount and every exception type. Zero differences. This is not a claim in the prose; the program exits non-zero if it fails.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 512" width="100%" style="max-width:840px" role="img" aria-label="A refactor of five edits that provably changes no behaviour, verified across eight thousand eight hundred and eight cases, run against both test suites. Six of the ten tests in the bad suite go red, each for a different incidental reason: the renamed field, the reformatted receipt, the removed private helper, the reworded error message, the stubbed helper and the batched audit calls. Zero of the fourteen tests in the good suite go red. None of the six red tests found a bug; every one of them has to be read and rewritten by whoever did the refactor.">
  <defs>
    <marker id="p12-03-c1" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#7c5cff"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="24" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Five edits. Zero behaviour change, proved on 8,808 cases. Six red tests.</text>

    <rect x="30" y="42" width="290" height="176" rx="9" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.7"/>
    <text x="175" y="62" text-anchor="middle" font-size="10.5" font-weight="700" fill="#7c5cff">THE REFACTOR</text>
    <g fill="currentColor" font-size="9" opacity="0.92">
      <text x="44" y="84">1 ·  notes  ->  applied   (internal field)</text>
      <text x="44" y="106">2 ·  reword one error message</text>
      <text x="44" y="122" opacity="0.7">      (the exception TYPE is unchanged)</text>
      <text x="44" y="144">3 ·  reformat the receipt string</text>
      <text x="44" y="166">4 ·  split _tier_bps() into two helpers</text>
      <text x="44" y="188">5 ·  batch 2 audit events into 1</text>
      <text x="44" y="210" font-weight="700" fill="#0fa07f">8,808 cases: every amount identical</text>
    </g>
    <path d="M320 130 L 366 130" fill="none" stroke="#7c5cff" stroke-width="1.8" marker-end="url(#p12-03-c1)"/>

    <text x="608" y="62" text-anchor="middle" font-size="11" font-weight="700" fill="#d64545">BAD SUITE — 6 of 10 red</text>
    <g stroke="#d64545" stroke-width="1.5">
      <rect x="376" y="72" width="180" height="20" rx="4" fill="#d64545" fill-opacity="0.16"/><rect x="376" y="96" width="180" height="20" rx="4" fill="#d64545" fill-opacity="0.16"/><rect x="376" y="120" width="180" height="20" rx="4" fill="#d64545" fill-opacity="0.16"/><rect x="376" y="144" width="180" height="20" rx="4" fill="#d64545" fill-opacity="0.16"/><rect x="376" y="168" width="180" height="20" rx="4" fill="#d64545" fill-opacity="0.16"/><rect x="376" y="192" width="180" height="20" rx="4" fill="#d64545" fill-opacity="0.16"/>
    </g>
    <g stroke="#7f7f7f" stroke-width="1.3">
      <rect x="376" y="216" width="180" height="20" rx="4" fill="#7f7f7f" fill-opacity="0.10"/><rect x="376" y="240" width="180" height="20" rx="4" fill="#7f7f7f" fill-opacity="0.10"/><rect x="376" y="264" width="180" height="20" rx="4" fill="#7f7f7f" fill-opacity="0.10"/><rect x="376" y="288" width="180" height="20" rx="4" fill="#7f7f7f" fill-opacity="0.10"/>
    </g>
    <g fill="currentColor" font-size="8.5">
      <text x="386" y="86" font-weight="700" fill="#d64545">bad_test_1</text><text x="386" y="110" font-weight="700" fill="#d64545">bad_test_pricing</text><text x="386" y="134" font-weight="700" fill="#d64545">bad_test_happy_path</text><text x="386" y="158" font-weight="700" fill="#d64545">bad_test_discount</text><text x="386" y="182" font-weight="700" fill="#d64545">bad_test_tier_helper</text><text x="386" y="206" font-weight="700" fill="#d64545">bad_test_coupon</text>
      <text x="386" y="230" opacity="0.6">bad_test_it_works</text><text x="386" y="254" opacity="0.6">bad_test_getter</text><text x="386" y="278" opacity="0.6">bad_test_smoke</text><text x="386" y="302" opacity="0.6">bad_test_repr</text>
    </g>
    <g font-size="8.5">
      <text x="568" y="86" fill="currentColor" opacity="0.9">AttributeError: no attribute 'notes'</text>
      <text x="568" y="110" fill="currentColor" opacity="0.9">the receipt string it pinned changed</text>
      <text x="568" y="134" fill="currentColor" opacity="0.9">it stubbed a helper that moved</text>
      <text x="568" y="158" fill="currentColor" opacity="0.9">the error MESSAGE changed (not the type)</text>
      <text x="568" y="182" fill="currentColor" opacity="0.9">module has no _tier_bps any more</text>
      <text x="568" y="206" fill="currentColor" opacity="0.9">the two audit calls became one</text>
      <text x="568" y="230" fill="currentColor" opacity="0.45">still green — asserts nothing specific</text>
      <text x="568" y="254" fill="currentColor" opacity="0.45">still green — tests the constructor</text>
      <text x="568" y="278" fill="currentColor" opacity="0.45">still green — asserts total &gt;= 0</text>
      <text x="568" y="302" fill="currentColor" opacity="0.45">still green — repr kept its shape</text>
    </g>

    <text x="608" y="336" text-anchor="middle" font-size="11" font-weight="700" fill="#0fa07f">GOOD SUITE — 0 of 14 red</text>
    <g stroke="#0fa07f" stroke-width="1.3">
      <rect x="376" y="348" width="24" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30"/><rect x="406" y="348" width="24" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30"/><rect x="436" y="348" width="24" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30"/><rect x="466" y="348" width="24" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30"/><rect x="496" y="348" width="24" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30"/><rect x="526" y="348" width="24" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30"/><rect x="556" y="348" width="24" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30"/>
      <rect x="586" y="348" width="24" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30"/><rect x="616" y="348" width="24" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30"/><rect x="646" y="348" width="24" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30"/><rect x="676" y="348" width="24" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30"/><rect x="706" y="348" width="24" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30"/><rect x="736" y="348" width="24" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30"/><rect x="766" y="348" width="24" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30"/>
    </g>
    <text x="800" y="360" font-size="8.5" fill="#0fa07f" font-weight="700">all green</text>

    <rect x="30" y="382" width="820" height="52" rx="9" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.4"/>
    <text x="46" y="402" font-size="9" font-weight="700" fill="currentColor" opacity="0.7">WHAT THE SIX RED TESTS HAD ASSERTED ON — a complete taxonomy of the brittle assertion</text>
    <text x="46" y="422" font-size="9.5" fill="currentColor" opacity="0.92">an internal field name  ·  a formatted string  ·  a private function's name  ·  an error MESSAGE rather than its type  ·  which calls were made</text>

    <text x="440" y="456" text-anchor="middle" font-size="12" font-weight="700" fill="currentColor">0 of the 6 found a bug. All 6 must be read, understood and rewritten by hand.</text>
    <text x="440" y="478" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">A test that breaks when behaviour has not changed has negative value: maintenance charged, no detection bought.</text>
    <text x="440" y="498" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">Assert the amount and the exception type. Never the message, the label, the format or the call.</text>
  </g>
</svg>
```

**6 of 10 against 0 of 14.** And the reasons are a complete taxonomy of the brittle assertion: an internal field name, a formatted string, a private function's name, an error *message* rather than its type, and which calls were made.

Not one of the six found a bug. All six have to be read, understood and rewritten by whoever did the refactor — which is the tax the suite charges every single time anyone touches the module. Multiply that by a team and a year and you get the real failure mode: **people stop refactoring**, because the tests punish it, and then the design rots for reasons that started as diligence.

The corollary is the assertion-quality rule, and it is short. Assert the **amount** and the **exception type**. Do not assert the message text (use a stable `code` attribute, or `pytest.raises(..., match=...)` on a fragment you deliberately treat as contract). Do not assert on `repr()`. Do not assert on a whole object when three of its five fields are incidental — but *do* assert on a whole object when every field is part of the promise, because field-by-field assertions silently stop checking the field somebody adds next year.

### The tests you should not write

Six of the bad suite's ten tests fall into a category worth naming, because they are the ones written when you know you should add a test and do not know what to assert.

```text
  test                     lines  kills  unique  red after   what it asserts
  bad_test_getter              6      0       0         no   asserts the constructor assigns its arguments
  bad_test_it_works            4      1       0         no   asserts the return value is truthy
  bad_test_smoke               4      1       0         no   asserts a total is not negative
  bad_test_happy_path          5      4       0        yes   asserts a stub returned the stubbed value
  bad_test_repr                4      7       0         no   asserts on __repr__ output
  bad_test_coupon              6      0       0        yes   asserts which calls were made
  total                       29     13       0          2
```

The column that decides it is **unique**: bugs this test caught that no other test in its own suite would have caught. It is **zero for all six**. Delete all six and the bad suite's detection is *exactly* where it was, minus **29 lines — 49% of its maintenance surface** — and minus two tests that go red on a refactor that changed nothing.

They break one rule between them: **do not test the language, the framework, the constructor, or the double.** `bad_test_getter` tests that Python assigns attributes. `bad_test_it_works` tests that a function returns something. `bad_test_repr` tests a debugging aid. `bad_test_happy_path` tests a `lambda` the test wrote two lines earlier. Each one raises the coverage number and lowers the suite's signal, which is the combination that makes a coverage gate dangerous — [Lesson 13](../13-coverage-and-mutation-testing/) shows the extreme version, a suite with 100% coverage and zero assertions.

The genuinely hard case is the smoke test, because "it doesn't crash" is real information. Keep it if you have nothing better *and* mark it as what it is. But notice it killed one bug the rest of its suite already caught, and understand what it is doing to your confidence: a green smoke test feels like a tested module and is not one.

## Build It

`code/unit_tests.py` is one file with no dependencies beyond the standard library. It runs in about half a second and prints everything above.

**The module under test is kept as source text**, so that a "bug" is a real edit to real code, compiled and imported like anything else:

```python
def load(src: str, name: str) -> types.ModuleType:
    """Compile once, then hand every caller its own fresh module object."""
    code = CODE_CACHE.get(name)
    if code is None:
        code = compile(src, f"<{name}>", "exec")
        CODE_CACHE[name] = code
    mod = types.ModuleType(name)
    exec(code, mod.__dict__)
    return mod
```

A *fresh* module per test run is the point of the last two lines. `bad_test_happy_path` monkey-patches `mod._tier_bps`; without a fresh module that patch would leak into every test that ran after it, and the suite's result would depend on its order. That is a whole lesson of its own ([Determinism](../08-determinism-time-randomness-order/)), and here it is avoided by construction.

**Each bug is a one-line substitution**, checked for uniqueness so a typo cannot silently produce a no-op mutant:

```python
MUTANTS: tuple[Mutant, ...] = (
    ("B01", "boundary", "if subtotal >= threshold:", "if subtotal > threshold:"),
    ("B04", "boundary", "(5000, 500)", "(4999, 500)"),
    ("R03", "rounding", "tax = div_round(taxable * tax_bps, 10000)",
     'tax = div_round(taxable * tax_bps, 10000, "half_up")'),
    ("E02", "exception", "raise CouponExpired(", "raise UnknownCoupon("),
    ("D01", "default", "tax_bps=DEFAULT_TAX_BPS", "tax_bps=800"),
    ...
)

def mutate(src: str, old: str, new: str) -> str:
    if src.count(old) != 1:
        raise SystemExit(f"mutation target is not unique: {old[:48]!r}")
    return src.replace(old, new, 1)
```

**The runner is twelve lines**, because a test framework is not magic — it collects functions, calls them, and catches what they raise:

```python
def run_test(test: TestFn, src_name: str, src: str) -> str | None:
    """Return None if the test passed, else a one-line failure reason."""
    mod = load(src, src_name)
    try:
        test(mod)
    except AssertionError as exc:
        frame = traceback.extract_tb(exc.__traceback__)[-1]
        return (frame.line or "assert").strip()
    except Exception as exc:  # a crash is a failure, same as any framework
        return f"{type(exc).__name__}: {exc}"
    return None
```

Reporting `frame.line` — the source text of the assertion that failed — is most of what pytest's celebrated assertion rewriting buys you, minus the operand values. Worth knowing that the gap between "no framework" and "pytest" is smaller than it looks, and that what pytest adds is the operand *values*, which is the part that actually saves you time.

**The suites are matched by counting their own source.** Nothing here is asserted by hand:

```python
def logical_lines(fn: TestFn) -> int:
    src = textwrap.dedent(inspect.getsource(fn))
    return sum(1 for line in src.splitlines()
               if line.strip() and not line.strip().startswith("#"))
```

**Section 2 parses the tests rather than describing them.** An "act" is a call into the module under test, found by walking the AST for attribute calls whose name is in the module's public surface:

```python
def shape(fn: TestFn) -> tuple[int, int, int]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    asserts = sum(1 for n in ast.walk(tree) if isinstance(n, ast.Assert))
    asserts += sum(1 for n in ast.walk(tree) if isinstance(n, ast.Raise))
    acts = sum(1 for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr in PUBLIC_CALLS)
    return asserts, acts, logical_lines(fn)
```

**Section 4's masking measurement rewrites the test's own AST** so that each assertion records a verdict instead of raising. `assert X` becomes `_rec(i, lambda: X)`; the lambda defers evaluation so an assertion that *raises* (rather than returning `False`) is caught and counted rather than ending the run:

```python
class Deassert(ast.NodeTransformer):
    def visit_Assert(self, node: ast.Assert) -> ast.Expr:
        self.labels.append(ast.unparse(node.test))
        call = ast.Call(func=ast.Name(id="_rec", ctx=ast.Load()),
                        args=[ast.Constant(len(self.labels) - 1),
                              ast.Lambda(args=..., body=node.test)],
                        keywords=[])
        return ast.fix_missing_locations(ast.copy_location(ast.Expr(call), node))
```

`ast.unparse(node.test)` gives the label for each row of the ledger — the assertion exactly as written, recovered from the parse tree rather than retyped, so the diagram above cannot drift from the code. And the rewritten test is checked against the real one on every bug; if they ever disagree the program exits non-zero.

**The two input grids answer two different questions.** The 808-case systematic grid deliberately contains every threshold, every rounding tie and every coupon expiry day; it exists to prove a bug is observable *at all*, which is how the equivalent mutant was identified. The 8,000-order random grid contains what a plausible generator produces; it exists to measure how often a bug shows up in an input nobody chose on purpose. Confusing those two questions is how people conclude that a boundary bug is "unreachable" when it is merely unlikely.

Run it:

```bash
python3 phases/12-testing-and-quality/03-anatomy-of-a-unit-test/code/unit_tests.py
```

```console
== 3 · SAME MODULE, SAME NUMBER OF LINES, SCORED ON THE SAME 25 BUGS ==
  self-check: all 24 tests pass against the unmutated module.

    bug     category                 bad suite                good suite
    B01     boundary                  SURVIVED               KILLED by 1
    B02     boundary                  SURVIVED               KILLED by 1
    B03     boundary                  SURVIVED               KILLED by 1
    B04     boundary                  SURVIVED               KILLED by 1
    B05     boundary                  SURVIVED               KILLED by 1
    B06     boundary                  SURVIVED               KILLED by 1
    B07     boundary               KILLED by 1               KILLED by 1
    R01     rounding                  SURVIVED               KILLED by 2
    R02     rounding                  SURVIVED               KILLED by 3
    R03     rounding                  SURVIVED               KILLED by 1
    R04     rounding            - equivalent -            - equivalent -
    A05   arithmetic                  SURVIVED               KILLED by 2
    C02  conditional                  SURVIVED               KILLED by 3
    C03  conditional               KILLED by 5              KILLED by 13
    E02    exception                  SURVIVED               KILLED by 1
    E03    exception                  SURVIVED               KILLED by 1
    D02        field               KILLED by 3               KILLED by 6
    D03        field               KILLED by 1                  SURVIVED

  suite           lines  tests   killed  kill rate  bugs/line
  bad                59     10       11       46%      0.186
  good               59     14       23       96%      0.390

  2.09x the bugs caught, for the same number of lines of test code.

  by category — what each style of test is actually good at:
  category        bugs    bad   good
  arithmetic         5      4      5
  boundary           7      1      7
  conditional        3      2      3
  exception          3      1      3
  rounding           3      0      3

== 4 · ONE REASON TO FAIL: WHAT A 14-ASSERTION TEST HIDES ==
    #  the assertion, as written                       broken by  you saw  masked
    4  q.discount_cents == 650                                 5        3       2
    6  q.tax_cents == 1019                                     6        2       4
    8  q.total_cents == 13369                                  7        1       6
    9  q.total_cents > q.subtotal_cents - q.discount_          2        0       2  <-- never seen
   13  q2.total_cents == q.total_cents                         2        0       2  <-- never seen
   14  mod.format_receipt(q).startswith('Subtotal: $1          2        0       2  <-- never seen

  9 of the 24 killable bugs break at least one assertion here, and
  between them they break 35. The runs report 9. The other 26 —
  74% of everything this test knows — are masked behind an
  earlier failure in the same body. Only 6 of the 14 assertions was
  ever the one you were shown; 8 broke repeatedly and reported
  nothing, ever. Mean facts broken per failing run: 3.89, which is
  the number of fix-and-rerun round trips this one test costs you.

== 6 · BOUNDARIES: WHAT A RANDOM INPUT WOULD HAVE TO GET LUCKY TO FIND ==
    bug     category  differs on   random cases for  first hit
                                     95% confidence    at case
    B06     boundary     0.000%            > 8,000      never
    B07     boundary     0.000%            > 8,000      never
    B04     boundary     0.338%                887        241
    B02     boundary     0.525%                570        229
    B01     boundary     2.138%                139          6
    R01     rounding     3.100%                 96         17
    A01   arithmetic    49.888%                  5          0
    C03  conditional    99.500%                  1          0

  all 4 boundary tables together — 20 lines, 22 cases:
    kill 15 of 24, against the 59-line bad suite's 11.

== 8 · A REFACTOR THAT CHANGES NO MONEY, AND WHAT IT COSTS EACH SUITE ==
  proof it is behaviour-preserving: 8,808 cases through both
  versions — every amount and every exception type identical.

  BAD SUITE: 6 of 10 tests go red
    bad_test_1            AttributeError: 'Quote' object has no attribute 'notes'
    bad_test_pricing      assert mod.format_receipt(q) == (
    bad_test_tier_helper  AttributeError: module 'V2' has no attribute '_tier_bps'
    bad_test_discount     assert str(exc) == "quantity for widget must be at least 1, got
  GOOD SUITE: 0 of 14 tests go red
```

Three things in that output are arguments rather than demonstrations.

**The self-check line matters more than it looks.** Every test in both suites passes against the unmutated module before anything is scored. A test that is red on correct code is not a strict test; it is a broken one, and it would inflate every kill rate below it.

**The `KILLED by N` counts are a redundancy measure, not a quality measure.** C03 turns 13 of the good suite's 14 tests red. That is not 13 times the information — it is one bug with a wide blast radius, and it is the reason section 5 measures *locatability* rather than counting red tests.

**`SURVIVED` in the boundary rows is the whole lesson in one column.** Six of the seven boundary bugs walked straight through a 59-line suite with 31 assertions that executed every line of the module. Nothing about that suite was lazy. It simply never chose an input that sat on a threshold.

## Use It

You will not write the runner. You will write pytest tests, and every idea above has a direct expression in it.

**Parametrize instead of copy-pasting, and name the cases.** This is the single highest-value habit in this lesson, because it makes the boundary table cheap enough that you actually write it:

```python
import pytest
from decimal import Decimal
from pricing import price_order, InvalidQuantity, CouponExpired

@pytest.mark.parametrize(
    "subtotal_cents, expected_discount_cents",
    [
        (4999, 0), (5000, 250), (5001, 250),          # 5% tier boundary
        (19999, 1000), (20000, 2000), (20001, 2000),  # 10% tier boundary
        (99999, 10000), (100000, 15000), (100001, 15000),
    ],
    ids=["just-below-5pc", "exactly-5pc", "just-above-5pc",
         "just-below-10pc", "exactly-10pc", "just-above-10pc",
         "just-below-15pc", "exactly-15pc", "just-above-15pc"],
)
def test_tier_discount_changes_only_at_the_documented_thresholds(
        subtotal_cents, expected_discount_cents):
    quote = price_order(items=[("sku", subtotal_cents, 1)])
    assert quote.discount_cents == expected_discount_cents
```

`ids=` is not decoration. Without it pytest names the cases `test_...[4999-0]`, and with it your CI failure reads `test_tier_discount_changes_only_at_the_documented_thresholds[exactly-5pc]` — which is the section-5 result applied to a parameter. Run one case with `pytest -k exactly-5pc`. Note also that parametrize builds **one test per case**: nine independent tests with nine independent failures, not one test with nine assertions. That is section 4's rule for free.

**`pytest.raises` — assert the type, then narrow deliberately.**

```python
def test_quantity_below_one_is_rejected_before_pricing():
    with pytest.raises(InvalidQuantity) as excinfo:
        price_order(items=[("sku", 500, 0)])
    assert excinfo.value.code == "invalid_quantity"     # stable contract

def test_expired_coupon_names_the_coupon():
    with pytest.raises(CouponExpired, match=r"SAVE10"):  # a fragment, not the text
        price_order(items=[("sku", 2000, 1)], coupon="SAVE10", day=31)
```

`match=` takes a **regular expression** and applies `re.search`, so it matches a fragment rather than the whole string — which is the right amount of coupling if you choose the fragment as contract (the coupon code) rather than as prose. Two traps: a bare `pytest.raises(Exception)` will happily catch the `AttributeError` from your own typo and report a pass, and `match=` is a regex, so `match="cost: $5.00 (final)"` silently matches almost nothing because `$` and `()` are metacharacters. Use `re.escape` if you must match literal text.

**`pytest.approx` for floats — and `Decimal` or integer cents for money.**

```python
assert 0.1 + 0.2 == pytest.approx(0.3)                # rel=1e-6 by default
assert measured == pytest.approx(expected, abs=1e-9)  # for values near zero
assert quote.total_cents == 13369                     # money: exact, always
```

`approx` defaults to a *relative* tolerance of `1e-6`, which is meaningless for a value that should be `0.0` — pass `abs=` there. And for money, do not reach for `approx` at all: the correct fix is to stop using floats. `pytest.approx` on a currency assertion is a test that permits the bug it should be catching.

**Fixtures, and the God-object trap pytest makes easy.** A fixture is dependency injection by parameter name. Use them for genuine setup and teardown:

```python
# conftest.py — visible to every test in this directory and below
import pytest

@pytest.fixture
def catalogue():                       # function scope: fresh for every test
    return {"widget": 2500, "cable": 1500}

@pytest.fixture(scope="session")       # built once for the whole run
def tax_table():
    return load_tax_table()
```

`conftest.py` scoping is directory-based and it cascades: a fixture in `tests/conftest.py` is available everywhere, one in `tests/api/conftest.py` only under `tests/api/`. Put shared fixtures at the narrowest level that works, because a session-scoped mutable fixture is a shared-state bug waiting for [Lesson 07](../07-test-data-and-fixtures/) to name it.

The anti-pattern is the fixture that returns everything: `@pytest.fixture def world()` handing back a user, an order, a catalogue and a clock, used by 200 tests of which each needs two fields. It makes every test's real precondition invisible, and it is the direct cause of the "change one seed row, nineteen unrelated tests fail" scene. If a test needs three lines of setup, three lines of setup in the test body is *better* than a fixture — the reader can see what the assertion depends on. Reach for a fixture when there is teardown, when construction is genuinely expensive, or when the same arrangement appears in five or more tests.

**Assertion rewriting is why plain `assert` is enough.** pytest rewrites the AST of your test modules at import to show operand values, which is why `assert a == b` prints a full diff instead of `AssertionError`. Two consequences worth knowing: it only rewrites *test* modules (and plugins registered with `pytest.register_assert_rewrite`), so a helper module of shared assertions gives you bare failures unless you register it; and `assert x, "message"` replaces the diff with your message, so add the message only when it says something the values do not.

**The flags that matter on a red build:**

```bash
pytest -q                      # quiet: the failure list, not the ceremony
pytest -x                      # stop at the first failure
pytest --lf                    # rerun only last-failed; --ff runs them first
pytest --tb=short              # one frame per failure — the readable default
pytest --tb=line               # one line per failure, for a wide sweep
pytest -k "tier and not slow"  # select by name substring
pytest --durations=10          # the ten slowest tests
```

`--tb=short` is the setting to put in your `pytest.ini` and forget about; the default `--tb=long` prints every frame of every failure and buries the assertion under the framework.

**What to actually do.** Four rules, in the order they pay:

1. **One act per test, and a name that is a falsifiable sentence.** This costs nothing and is what makes a red build readable. Everything in sections 2, 4 and 5 follows from it.
2. **Parametrize the boundaries first.** Every comparison in the code gets three cases: on it, one below, one above. Every rounding operation gets an exact half in both directions. Measured here, 20 lines of that outscored a 59-line suite.
3. **Assert the amount and the exception type. Never the message, the label, the format or the call list.** That is the difference between 0 and 6 tests going red on a refactor that changed nothing.
4. **Write the rejection tests.** Four of the 24 bugs lived exclusively in code that only runs on invalid input, and three of those were never reached by 8,000 valid orders.

And the check to run once a quarter on a suite you inherited: pick the module you are most afraid of, change one comparison operator, and run the tests. If they stay green, you have measured something real about what that suite is worth. That is mutation testing done by hand, and [Lesson 13](../13-coverage-and-mutation-testing/) automates it.

## Think about it

1. The bad suite has 31 assertions and catches 11 bugs; the good suite has 17 and catches 23. Assertion count therefore correlates *negatively* with detection here. Construct a suite where the correlation is strongly positive, and say what property of it makes the difference — then explain why that property is not "more assertions".
2. Assertion #8 in `bad_test_1` (`q.total_cents == 13369`) was broken by 7 of the 24 bugs and was the reported failure exactly once. If you split `bad_test_1` into 14 single-assertion tests with the same assertions and the same arranged input, how many bugs would the resulting suite catch — and why is that number not 24?
3. Bug B04 shows up on 0.338% of realistic orders, needing 887 random cases for 95% confidence, while a 9-case boundary table catches it every time. Now suppose the tier threshold were not a round £50.00 but £47.13. Predict what happens to both numbers, and say what that tells you about *which* systems boundary testing matters most for.
4. Four of the 24 bugs cannot be reached by any input the module accepts, and three of them never appeared in 8,000 generated orders. Design a generator that would reach all four — then explain why the property-based testing of [Lesson 12](../12-property-based-testing-and-fuzzing/) would or would not have found them.
5. D03 is the one bug the bad suite caught and the good suite missed: a debug label changing from `tier:500` to `tier=500`. The assertion that caught it is also one of the six that broke on the behaviour-preserving refactor. Decide whether that assertion should exist, and state the general rule your answer implies for any output that is "incidental" today.

## Key takeaways

- **Suite size is not suite power.** Two suites of **59 lines** over the same module caught **11 and 23** of the same 24 killable bugs — **2.09×** for identical cost. The weaker one had **82% more assertions** (31 against 17) and ran every line the stronger one did. What separated them was which inputs they chose.
- **Your definition of "unit" sets a ceiling before you write an assertion.** Aim a test at the private helper `_tier_bps()` and at most **5 of 24 bugs (21%)** are reachable, no matter how good the assertions are. Aim it at the behaviour `price_order()` promises and the ceiling is **100%**. A unit is a behaviour the caller can name, not a function.
- **A 14-assertion test reports one fact and destroys the rest.** Across the 24 bugs it broke **35 assertions**, reported **9**, and masked **26 — 74%**. Eight of its fourteen assertions were *never once* the failure you were shown. Mean facts broken per failing run: **3.89**, which is the number of fix-and-rerun round trips it costs. One act, one reason to fail.
- **A test name that cannot be false cannot report a failure.** For every one of the 23 bugs the good suite caught, a red test's **name alone** identified the right subsystem — **23/23 against 0/11**. `test_1` is an ordinal, `test_pricing` is a topic; `test_coupon_still_applies_on_its_last_valid_day` is a proposition.
- **Boundaries are where the invisible bugs are, and the arithmetic is brutal.** A tier off-by-one showed up on **0.338%** of realistic orders — **887 random cases** for 95% confidence — and the coupon-minimum boundary never appeared in **8,000**. One **6-line, 9-case** parametrized table killed **10 of 24**; four such tables, **20 lines**, killed **15**, beating the entire 59-line bad suite by 4 bugs on **34% of the code**.
- **The unhappy path is unreached by design.** Four bugs changed nothing on any input the module accepts, and three never appeared in 8,000 generated orders — because a generator written by someone thinking about pricing produces prices, not malformed orders. Rejection tests: **1 of 10** in the weak suite, **3 of 14** in the strong one.
- **Assert the outcome, not the calls.** The interaction test was **6 lines and killed 0 bugs**; a 3-line state assertion killed **9**. The over-mocked test was structurally blind to the **9 bugs** living in the two helpers it stubbed — it asserted that a stub returned what the test configured the stub to return.
- **A test that breaks when behaviour has not changed has negative value.** A refactor proved behaviour-identical across **8,808 cases** turned **6 of 10** weak tests red and **0 of 14** strong ones. None of the six found a bug; all six had to be rewritten. Assert the amount and the exception type — never the message, the label, the format or the call list.
- **Some tests cost and buy nothing, measurably.** Six tests, **29 lines, 0 unique kills, 2 of them red after the refactor**. Deleting all six leaves detection exactly where it was and removes **49%** of that suite's maintenance surface. Do not test the language, the framework, the constructor, or the double.

Next: [Test Doubles: Mocks, Stubs, Fakes & the Lies They Tell](../04-test-doubles/) — what you replace the world with when the real thing is a payment gateway, why the mock that made this lesson's over-mocked test blind to 9 bugs is the same mechanism that makes a 96%-coverage suite miss a `"success"`/`"succeeded"` mismatch, and the one technique that keeps a double honest.
