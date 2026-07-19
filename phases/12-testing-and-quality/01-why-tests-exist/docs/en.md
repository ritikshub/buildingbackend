# Why Tests Exist: The Cost of Finding a Bug Late

> One character changed — `>=` became `>` — and 75 of a day's 2,000 orders were priced wrong. That is **3.75%**, which is why nothing noticed: every other invoice in the day was byte-identical to the correct one, and the day's revenue moved **0.16%** against a staging alarm set at 2%. The overcharge was **$408.00 a day**. The incident it caused cost **702 engineer-minutes — $1,053 — of which 35 minutes was the actual fix and 467 was finding out.** This lesson prices the same bug at six moments in its life, runs 40 real bugs through five real gates, and measures what each gate catches *that the one before it did not*. Two gates catch nothing at all.

**Type:** Build
**Languages:** Python
**Prerequisites:** [CI/CD Pipelines](../../10-infrastructure-and-deployment/10-ci-cd-pipelines/), [Deployment Strategies](../../10-infrastructure-and-deployment/11-deployment-strategies/)
**Time:** ~65 minutes

## The Problem

**Friday, 16:40.** The ticket says the volume discount is confusing customers whose cart lands exactly on the fifty-dollar threshold. You open `pricing.py`, find the line, and read it:

```python
def volume_bps(subtotal_cents: int) -> int:
    """The 10% volume discount applies from 50.00 upwards, inclusive."""
    if subtotal_cents >= VOLUME_THRESHOLD_CENTS:
        return VOLUME_BPS
    return 0
```

You are wrong about which way the confusion runs. You delete one character. `>=` becomes `>`. The diff is one line and it is green in your editor, because it is perfectly valid Python that does something slightly different from what the sentence directly above it says.

**16:52.** A colleague approves the pull request. They are not careless — they read the diff, and a comparison operator changing in a pricing function is exactly the kind of thing a reviewer looks at. But nothing *in the diff* tells them which way the boundary is supposed to go. The sentence that does is one line up, outside the hunk. Hold on to that detail: later in this lesson a modelled reviewer catches this exact bug, and the only thing standing between the two outcomes is whether three lines of context were on the screen.

**17:04.** CI is green. There are tests. None of them prices an order at exactly `5000` cents, because nobody has ever thought to.

**17:20.** It deploys. Staging looked fine. Staging always looks fine, because staging has no oracle: nobody there knows what the right invoice is, only what an obviously wrong one looks like — a negative total, a discount larger than the subtotal, a revenue number that moved by more than 2%. Measured over the same day, this bug moves revenue by **0.16%** on **$252,065.04**. It is an order of magnitude below the only alarm that could have seen it.

Now the part that decides how expensive this gets. Here is what the change actually did, measured over one seeded day of 2,000 orders:

```text
invoices priced differently  75 = 3.75% of the day
money moved                  $408.00 overcharged, $5.44 per affected order
revenue for the day          $252,065.04 correct, so the bug
                             moves it 0.16% against a 2% alarm threshold
```

**Seventy-five orders.** Not seven hundred. Not two. Every other invoice in that day is byte-for-byte identical to the invoice the correct code would have produced, which means every dashboard you own is flat, every alert is quiet, and every engineer who looks at the graphs on Monday will correctly conclude that nothing is wrong.

**Tuesday, 11:15.** A customer emails. Two items at 2,500 cents each: their receipt reads `Total           $57.65` where the correct one reads `Total           $52.21`. One customer, $5.44. What follows is not $5.44 of work:

```text
time to detection                  1 x  47.0 min =   47.0
incident response                  3 x  40.0 min =  120.0
rollback and hotfix                1 x  35.0 min =   35.0
write the refund tooling           1 x  90.0 min =   90.0
run and reconcile the refunds      2 x  55.0 min =  110.0
postmortem                         4 x  60.0 min =  240.0
customer comms and credits         1 x  60.0 min =   60.0
                                                    702.0 engineer-minutes
```

**702 engineer-minutes. $1,053.** The same character, caught by a unit test, would have cost **2 minutes**. That is a factor of **351**, and it is not a citation — it is the sum of the seven lines above, each one a number of people multiplied by a number of minutes, all of which you can argue with.

Argue with them. It will not help. Change every one of those components by up to 60% in either direction, two thousand times over, and the *decision* they produce — which gates are worth running — comes out identical in **100%** of draws. The constants are a guess. What they imply is not.

And look at where the 702 minutes went. Thirty-five of them were the code change. **Four hundred and sixty-seven — 67% — were spent finding out, responding, and explaining.** The money you refund, $408.00 for a full day of the bug, is 0.39× the labour cost of the incident it triggers.

> **A bug's cost is not the damage it does. It is the distance between the moment you wrote it and the moment you found out.**

Everything in this lesson is an attempt to shorten that distance, and an honest accounting of what shortening it costs.

## The Concept

### What a test actually is

A test is a program that runs your program and asserts a fact about it. That is the whole idea. There is nothing else in it, and the amount of ceremony that has accumulated on top of that sentence has convinced a lot of engineers that a test framework is doing something mysterious.

It is not. Here is the entire framework this lesson uses, counted from its own source at run time: **13 non-blank lines.**

```python
def assert_eq(actual, expected, what):
    if actual != expected:
        FAILURES.append(f"{what}\n      expected: {expected!r}\n      actual:   {actual!r}")


def run_suite(tests):
    del FAILURES[:]
    for name, fn in tests:
        n = len(FAILURES)
        try:
            fn()
        except Exception as exc:                     # a crash is a failure too
            FAILURES.append(f"raised {type(exc).__name__}: {exc}")
        FAILURES[n:] = [f"{name}: {f}" for f in FAILURES[n:]]
    return list(FAILURES)
```

Append to a list when two values differ. Catch exceptions so that one crash cannot hide the tests after it. Return the list. Fourteen tests written against that runner take **0 failures** on the module as written, and **3 failures** the moment `>=` becomes `>`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 452" width="100%" style="max-width:840px" role="img" aria-label="A test framework demystified in three panels. The first panel shows the entire test runner used in this lesson: thirteen non-blank lines of Python that append a message to a list when two values differ, catch exceptions so one crash cannot hide the rest, and return the list. The second panel shows one test as a name plus a function that calls the code and compares one value. The third panel shows what the runner prints when that test fails: the test name, the intent string, the expected value 1000 and the actual value 0. Below, the measured run: fourteen tests against the module as written give zero failures, and the same fourteen tests after one character was changed from greater-or-equal to greater give three failures, including a whole invoice whose discount fell from 750 to 250 and whose total rose from 5221 to 5765.">
  <defs>
    <marker id="p12-01-a1" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#3553ff"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">A test is a program that runs your program and asserts a fact about it</text>
    <text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">that sentence is the whole idea. this is the whole implementation — no framework anywhere in it.</text>

    <text x="160" y="72" text-anchor="middle" font-size="11" font-weight="700" fill="#3553ff">1 · the runner — 13 non-blank lines</text>
    <text x="436" y="72" text-anchor="middle" font-size="11" font-weight="700" fill="#7c5cff">2 · one test</text>
    <text x="718" y="72" text-anchor="middle" font-size="11" font-weight="700" fill="#d64545">3 · what it prints when it fails</text>

    <rect x="30" y="80" width="260" height="186" rx="8" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff" stroke-width="1.6"/>
    <rect x="316" y="80" width="240" height="186" rx="8" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="1.6"/>
    <rect x="582" y="80" width="268" height="186" rx="8" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="1.6"/>

    <g fill="currentColor" font-size="8.4">
      <text x="42" y="99">def assert_eq(actual, expected, what):</text>
      <text x="42" y="112.5">&#160;&#160;&#160;&#160;if actual != expected:</text>
      <text x="42" y="126">&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;FAILURES.append(...)</text>
      <text x="42" y="152">def run_suite(tests):</text>
      <text x="42" y="165.5">&#160;&#160;&#160;&#160;del FAILURES[:]</text>
      <text x="42" y="179">&#160;&#160;&#160;&#160;for name, fn in tests:</text>
      <text x="42" y="192.5">&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;n = len(FAILURES)</text>
      <text x="42" y="206">&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;try:</text>
      <text x="42" y="219.5">&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;fn()</text>
      <text x="42" y="233">&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;except Exception as exc:</text>
      <text x="42" y="246.5">&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;FAILURES.append(...)</text>
      <text x="42" y="260">&#160;&#160;&#160;&#160;return list(FAILURES)</text>
    </g>

    <g fill="currentColor" font-size="8.4">
      <text x="326" y="99">(&quot;volume_discount_at_threshold&quot;,</text>
      <text x="326" y="112.5">&#160;lambda: assert_eq(</text>
      <text x="326" y="132">&#160;&#160;&#160;&#160;&#160;volume_bps(5000),</text>
      <text x="326" y="158">&#160;&#160;&#160;&#160;&#160;1000,</text>
      <text x="326" y="184">&#160;&#160;&#160;&#160;&#160;&quot;50.00 is INCLUSIVE&quot;))</text>
    </g>
    <g font-size="8" font-weight="700">
      <text x="468" y="132" fill="#7c5cff">&#8592; act</text>
      <text x="468" y="158" fill="#0fa07f">&#8592; expected</text>
      <text x="468" y="196" fill="#7f7f7f">&#8592; the intent</text>
    </g>
    <text x="326" y="220" font-size="8.4" fill="currentColor" opacity="0.9">a name, and a function that calls</text>
    <text x="326" y="234" font-size="8.4" fill="currentColor" opacity="0.9">the code and compares exactly one</text>
    <text x="326" y="248" font-size="8.4" fill="currentColor" opacity="0.9">value. that is all a test case is.</text>

    <g fill="currentColor" font-size="8.4">
      <text x="594" y="99">volume_discount_at_threshold:</text>
      <text x="594" y="112.5">&#160;&#160;50.00 is INCLUSIVE</text>
      <text x="594" y="126">&#160;&#160;&#160;&#160;&#160;&#160;expected: 1000</text>
      <text x="594" y="139.5">&#160;&#160;&#160;&#160;&#160;&#160;actual:&#160;&#160;&#160;0</text>
    </g>
    <text x="594" y="168" font-size="8.4" fill="currentColor" opacity="0.9">the name says WHICH promise broke.</text>
    <text x="594" y="182" font-size="8.4" fill="currentColor" opacity="0.9">the intent string says what it MEANT.</text>
    <text x="594" y="196" font-size="8.4" fill="currentColor" opacity="0.9">the two values say HOW it broke.</text>
    <text x="594" y="224" font-size="8.4" font-weight="700" fill="#0fa07f">everything pytest adds on top of</text>
    <text x="594" y="238" font-size="8.4" font-weight="700" fill="#0fa07f">this is ergonomics, not capability.</text>

    <path d="M290 160 L 310 160" fill="none" stroke="#3553ff" stroke-width="1.6" marker-end="url(#p12-01-a1)"/>
    <path d="M556 160 L 576 160" fill="none" stroke="#3553ff" stroke-width="1.6" marker-end="url(#p12-01-a1)"/>

    <rect x="30" y="286" width="820" height="126" rx="9" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.5"/>
    <text x="46" y="306" font-size="9" font-weight="700" fill="currentColor" opacity="0.7">MEASURED — 14 TESTS, ONE MODULE, ONE CHARACTER OF DIFFERENCE</text>
    <text x="46" y="326" font-size="10" fill="currentColor">the module as written</text>
    <text x="330" y="326" font-size="10" font-weight="700" fill="#0fa07f">0 failures</text>
    <text x="46" y="346" font-size="10" fill="currentColor">after&#160;&#160;<tspan font-weight="700">&gt;= VOLUME_THRESHOLD_CENTS</tspan>&#160;&#160;became&#160;&#160;<tspan font-weight="700">&gt; VOLUME_THRESHOLD_CENTS</tspan></text>
    <text x="614" y="346" font-size="10" font-weight="700" fill="#d64545">3 failures</text>
    <text x="46" y="370" font-size="8.6" fill="currentColor">price_order_gold_at_boundary: the whole invoice at exactly 50.00</text>
    <text x="46" y="386" font-size="8.6" font-weight="700" fill="#0fa07f">expected</text>
    <text x="46" y="402" font-size="8.6" font-weight="700" fill="#d64545">actual</text>
    <text x="112" y="386" font-size="8.6" fill="currentColor">{'subtotal': 5000, 'discount': <tspan font-weight="700">750</tspan>, 'taxable': 4250, 'tax': 372, 'shipping': 599, 'total': <tspan font-weight="700">5221</tspan>}</text>
    <text x="112" y="402" font-size="8.6" fill="currentColor">{'subtotal': 5000, 'discount': <tspan font-weight="700" fill="#d64545">250</tspan>, 'taxable': 4750, 'tax': 416, 'shipping': 599, 'total': <tspan font-weight="700" fill="#d64545">5765</tspan>}</text>
    <text x="440" y="438" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">One customer, one order at exactly $50.00, charged $57.65 instead of $52.21 — found in 0.4 seconds.</text>
  </g>
</svg>
```

Three things in that failure output are doing separate jobs, and it is worth naming them once because every framework you will ever use is a more polished version of exactly these three.

The **name** — `volume_discount_at_threshold` — tells you which promise broke. The **intent string** — `"50.00 is INCLUSIVE"` — tells you what the promise meant, in the words of whoever made it. The **two values** tell you how it broke. A test that gets all three right can be read by someone who has never seen the codebase; a test named `test_1` that asserts `assert result` gets none of them.

Everything pytest adds on top — discovery, fixtures, parametrisation, assertion rewriting, plugins, a hundred flags — is ergonomics. It is *good* ergonomics, and the `Use It` section below is about getting it, but none of it is capability. If you can write the thirteen lines above, you can write a test, today, with no dependencies at all.

### The escape-cost curve, and why only its shape survives contact

The interesting question is not "does a test find the bug". It is: **what does finding it later cost?**

This is the one number in the lesson that no program can measure, because no program can measure what a postmortem costs. So it is not measured — it is *built*, out of people and minutes, with every component printed so you can substitute your own. Six stages, from the moment the character is typed to the moment a customer notices:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 452" width="100%" style="max-width:840px" role="img" aria-label="The escape-cost ladder for one one-character change, on a logarithmic scale. Found as you type it costs half an engineer-minute; found by a unit test, two minutes; by a reviewer, thirty-four; by continuous integration, forty; in staging, one hundred and forty-three; in production, seven hundred and two minutes, which is three hundred and fifty-one times the unit-test price. Below, production's seven hundred and two minutes broken into components: time to detection, incident response, postmortem and customer communication together account for four hundred and sixty-seven minutes, sixty-seven percent, while the actual code change is thirty-five minutes, five percent. The day's overcharge of four hundred and eight dollars is only 0.39 times the labour cost.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">One bug, six moments, six prices — and the ladder is a log scale</text>
    <text x="440" y="45" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">costs built from people × minutes, not cited. the constant is a guess; the shape is not.</text>

    <rect x="30" y="56" width="820" height="28" rx="7" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff" stroke-width="1.4"/>
    <text x="440" y="74" text-anchor="middle" font-size="9.5" fill="currentColor">the bug itself, over one measured day: <tspan font-weight="700">75 of 2,000 orders wrong (3.75%)</tspan> · <tspan font-weight="700">$408.00 overcharged</tspan> · every other invoice byte-identical</text>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="30" y="106">STAGE</text><text x="125" y="106">FOUND WHEN</text><text x="270" y="106">ENGINEER-MINUTES  (log)</text>
      <text x="745" y="106" text-anchor="end">MIN</text><text x="805" y="106" text-anchor="end">COST</text><text x="855" y="106" text-anchor="end">×UNIT</text>
    </g>
    <path d="M30 112 L 860 112" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.4"/>

    <g stroke="currentColor" stroke-width="1" opacity="0.22" stroke-dasharray="3 4">
      <path d="M332.9 118 L 332.9 316"/><path d="M458.6 118 L 458.6 316"/><path d="M584.3 118 L 584.3 316"/><path d="M710 118 L 710 316"/>
    </g>

    <g>
      <rect x="270" y="124" width="25.1" height="22" rx="3" fill="#0fa07f" fill-opacity="0.35" stroke="#0fa07f" stroke-width="1.4"/>
      <rect x="270" y="158" width="100.6" height="22" rx="3" fill="#0fa07f" fill-opacity="0.35" stroke="#0fa07f" stroke-width="1.4"/>
      <rect x="270" y="192" width="255.2" height="22" rx="3" fill="#e0930f" fill-opacity="0.35" stroke="#e0930f" stroke-width="1.4"/>
      <rect x="270" y="226" width="264.0" height="22" rx="3" fill="#e0930f" fill-opacity="0.35" stroke="#e0930f" stroke-width="1.4"/>
      <rect x="270" y="260" width="334.4" height="22" rx="3" fill="#e0930f" fill-opacity="0.35" stroke="#e0930f" stroke-width="1.4"/>
      <rect x="270" y="294" width="421.2" height="22" rx="3" fill="#d64545" fill-opacity="0.40" stroke="#d64545" stroke-width="1.8"/>
    </g>

    <g fill="currentColor" font-size="10" font-weight="700">
      <text x="30" y="139">types</text><text x="30" y="173">unit</text><text x="30" y="207">review</text>
      <text x="30" y="241">integration</text><text x="30" y="275">staging</text><text x="30" y="309" fill="#d64545">production</text>
    </g>
    <g fill="currentColor" font-size="8.6" opacity="0.85">
      <text x="125" y="139">the editor underlines it</text><text x="125" y="173">a unit test goes red</text><text x="125" y="207">a reviewer comments</text>
      <text x="125" y="241">CI fails on the branch</text><text x="125" y="275">QA files a ticket</text><text x="125" y="309">a customer notices</text>
    </g>
    <g fill="currentColor" font-size="9.5" text-anchor="end">
      <text x="745" y="139">0.5</text><text x="805" y="139">$1</text><text x="855" y="139">0×</text>
      <text x="745" y="173">2.0</text><text x="805" y="173">$3</text><text x="855" y="173">1×</text>
      <text x="745" y="207">34.0</text><text x="805" y="207">$51</text><text x="855" y="207">17×</text>
      <text x="745" y="241">40.0</text><text x="805" y="241">$60</text><text x="855" y="241">20×</text>
      <text x="745" y="275">143.0</text><text x="805" y="275">$214</text><text x="855" y="275">72×</text>
      <text x="745" y="309" font-weight="700" fill="#d64545">702.0</text><text x="805" y="309" font-weight="700" fill="#d64545">$1,053</text><text x="855" y="309" font-weight="700" fill="#d64545">351×</text>
    </g>

    <g fill="currentColor" font-size="8.5" text-anchor="middle" opacity="0.7">
      <text x="332.9" y="330">1 min</text><text x="458.6" y="330">10 min</text><text x="584.3" y="330">100 min</text><text x="710" y="330">1,000 min</text>
    </g>

    <text x="30" y="358" font-size="9" font-weight="700" fill="currentColor" opacity="0.62">WHERE PRODUCTION'S 702 MINUTES GO — AND ALMOST NONE OF IT IS THE FIX</text>
    <g>
      <rect x="30" y="366" width="50.9" height="26" fill="#d64545" fill-opacity="0.40" stroke="#d64545" stroke-width="1.3"/>
      <rect x="80.9" y="366" width="130.0" height="26" fill="#d64545" fill-opacity="0.40" stroke="#d64545" stroke-width="1.3"/>
      <rect x="210.9" y="366" width="37.9" height="26" fill="#0fa07f" fill-opacity="0.45" stroke="#0fa07f" stroke-width="1.6"/>
      <rect x="248.8" y="366" width="97.4" height="26" fill="#e0930f" fill-opacity="0.35" stroke="#e0930f" stroke-width="1.3"/>
      <rect x="346.2" y="366" width="119.1" height="26" fill="#e0930f" fill-opacity="0.35" stroke="#e0930f" stroke-width="1.3"/>
      <rect x="465.3" y="366" width="259.9" height="26" fill="#d64545" fill-opacity="0.40" stroke="#d64545" stroke-width="1.3"/>
      <rect x="725.2" y="366" width="65.0" height="26" fill="#d64545" fill-opacity="0.40" stroke="#d64545" stroke-width="1.3"/>
    </g>
    <g fill="currentColor" font-size="8" text-anchor="middle">
      <text x="55" y="383">47</text><text x="146" y="383">120</text><text x="230" y="383" font-weight="700" fill="#0fa07f">35</text><text x="297" y="383">90</text><text x="406" y="383">110</text><text x="595" y="383">240</text><text x="758" y="383">60</text>
    </g>
    <g fill="currentColor" font-size="8" text-anchor="middle" opacity="0.85">
      <text x="55" y="404">detect</text><text x="146" y="404">respond</text><text x="230" y="404" font-weight="700" fill="#0fa07f">FIX</text><text x="297" y="404">refund tool</text><text x="406" y="404">reconcile</text><text x="595" y="404">postmortem</text><text x="758" y="404">comms</text>
    </g>

    <text x="440" y="428" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">Finding out costs 467 of 702 minutes — 67%. Fixing costs 35 — 5%.</text>
    <text x="440" y="445" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">And the money you refund, $408.00, is 0.39× the labour. The incident is the cost; the damage is a rounding error.</text>
  </g>
</svg>
```

Read the multiplier column, not the dollar column. **0.5 minutes → 2 → 34 → 40 → 143 → 702.** The jumps are not smooth and they are not arbitrary: cost multiplies every time a stage adds *people* or an *environment*. Typing is one person and no deploy. Review is two people. Staging is a deploy plus a QA cycle plus a triage plus a second deploy. Production is seven people, two deploys, a refund run, and a customer who now has an opinion about you.

The figure usually quoted for the production-to-unit ratio is **100×**, and it traces back to work from the 1970s on waterfall projects with six-month release cycles. This ladder says **351×** for a service that deploys daily. Both numbers are made up in the same way — they are sums of estimated labour — and neither deserves to be quoted as a fact.

What *does* deserve to be trusted is the shape, and the way to establish that is to attack it. Multiply every stage cost by a random factor in `[0.4, 1.6]` and re-derive which gates are worth running, two thousand times:

```text
exact ranking of all five unchanged:  1,048/2,000 =  52%
SET of gates worth running unchanged: 2,000/2,000 = 100%
```

That pair is the honest answer, and it is more useful than a single confident number. The *exact ordering* is not robust — two of the gates sit 0.5 minutes per release apart and swap places under any jitter at all. The *decision* — which gates earn their keep — does not move once in two thousand draws. **A made-up cost ladder is allowed to be used at the resolution of "yes or no", and no finer.** If someone shows you a testing ROI model with two significant figures, they have not run this experiment.

### What each gate catches that the last one did not

Now the measurement this lesson exists for.

Take one small pricing module — thirteen functions, integer cents, a discount, a tax, a shipping rule, a SQLite row round-trip and a rendered receipt. Make **40 single-token edits** to it, each one a bug that has shipped in a real billing system, across nine classes: boundary, arithmetic, rounding, type-shape, constant, wiring, serialization, error-handling, formatting.

Then run all forty through five gates. Four of them are genuinely executed:

- **types** — call each function with well-typed arguments and check the result against its return annotation. This is what a static type checker approximates: shapes, never values.
- **unit** — the fourteen boundary-driven tests from the previous section.
- **integration** — price three orders end to end, write each to SQLite, read it back, compare against a golden invoice.
- **staging** — run the full 2,000-order day and check only what a monitor can check *with no oracle*: self-consistency of each invoice, sane ranges, revenue within 2% of yesterday.

The fifth, **review**, is a model of a human and is labelled as one everywhere its number appears. A reviewer is not a subprocess. What is encoded is four rules an attentive reviewer genuinely applies to a small diff with no domain knowledge: the change contradicts the docstring beside it; the change deletes a `raise`; the new code reads as nonsense in place; a named constant changed with no explanation.

Before the numbers, one detail from The Problem, because it is the most useful thing the review model has to say. The modelled reviewer **does** catch the discount bug — its strongest rule is "the diff contradicts the docstring beside it", and the docstring one line above `volume_bps` says "inclusive". In the scene at 16:52 the reviewer missed it because that line was outside the hunk. Same bug, same reviewer, same rule: the outcome turned on three lines of context. That is what a human gate's reliability actually rests on, and it is why the number below is a model and not a measurement.

Here is what happens:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 496" width="100%" style="max-width:840px" role="img" aria-label="Forty seeded bugs run through five gates. The top bar shows where each bug is first caught: types catches five, unit tests catch twenty-five more, code review catches zero that the earlier gates missed, integration catches four, staging catches zero, and six escape everything. The middle chart contrasts what each gate catches on its own with what it adds to the pipeline: review catches seventeen of forty alone but zero marginally, and staging catches eighteen alone but zero marginally, because everything they see has already been caught. The bottom panel lists the six survivors and what each one costs, including a serialization bug that keeps a perfect round-trip while cutting a finance job's tax total by seventy-two percent, and an equivalent mutant that no test can ever kill.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">A gate is worth what it catches that the last gate did not</text>
    <text x="440" y="45" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">40 single-token edits to one pricing module · 9 bug classes · 5 gates, four of them genuinely executed</text>

    <text x="30" y="74" font-size="9" font-weight="700" fill="currentColor" opacity="0.62">MARGINAL — WHERE EACH OF THE 40 BUGS IS <tspan font-weight="700">FIRST</tspan> CAUGHT (one bug = 20 px)</text>
    <g>
      <rect x="30" y="82" width="100" height="42" fill="#3553ff" fill-opacity="0.30" stroke="#3553ff" stroke-width="1.6"/>
      <rect x="130" y="82" width="500" height="42" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="1.6"/>
      <rect x="630" y="82" width="80" height="42" fill="#e0930f" fill-opacity="0.30" stroke="#e0930f" stroke-width="1.6"/>
      <rect x="710" y="82" width="120" height="42" fill="#d64545" fill-opacity="0.32" stroke="#d64545" stroke-width="2"/>
    </g>
    <g text-anchor="middle" font-size="10" font-weight="700">
      <text x="80" y="100" fill="#3553ff">types</text><text x="80" y="115" fill="currentColor">5</text>
      <text x="380" y="100" fill="#0fa07f">unit tests</text><text x="380" y="115" fill="currentColor">25</text>
      <text x="670" y="100" fill="#e0930f">integration</text><text x="670" y="115" fill="currentColor">4</text>
      <text x="770" y="100" fill="#d64545">ESCAPED</text><text x="770" y="115" fill="currentColor">6</text>
    </g>
    <g stroke="#d64545" stroke-width="2.4">
      <path d="M630 78 L 630 128"/><path d="M710 78 L 710 128"/>
    </g>
    <text x="630" y="142" font-size="8.6" text-anchor="middle" fill="#d64545" font-weight="700">review: 0</text>
    <text x="710" y="142" font-size="8.6" text-anchor="middle" fill="#d64545" font-weight="700">staging: 0</text>

    <text x="30" y="172" font-size="9" font-weight="700" fill="currentColor" opacity="0.62">ALONE (pale) VERSUS MARGINAL (solid) — THE SAME FIVE GATES, SAME 40 BUGS</text>
    <g stroke-width="1.4">
      <rect x="115" y="182" width="100" height="18" fill="#7f7f7f" fill-opacity="0.16" stroke="#7f7f7f"/>
      <rect x="115" y="182" width="100" height="18" fill="#3553ff" fill-opacity="0.45" stroke="#3553ff"/>
      <rect x="115" y="208" width="560" height="18" fill="#7f7f7f" fill-opacity="0.16" stroke="#7f7f7f"/>
      <rect x="115" y="208" width="500" height="18" fill="#0fa07f" fill-opacity="0.45" stroke="#0fa07f"/>
      <rect x="115" y="234" width="340" height="18" fill="#7f7f7f" fill-opacity="0.16" stroke="#7f7f7f"/>
      <rect x="115" y="260" width="520" height="18" fill="#7f7f7f" fill-opacity="0.16" stroke="#7f7f7f"/>
      <rect x="115" y="260" width="80" height="18" fill="#e0930f" fill-opacity="0.45" stroke="#e0930f"/>
      <rect x="115" y="286" width="360" height="18" fill="#7f7f7f" fill-opacity="0.16" stroke="#7f7f7f"/>
    </g>
    <g fill="currentColor" font-size="9.5" text-anchor="end">
      <text x="107" y="195">types</text><text x="107" y="221">unit</text><text x="107" y="247" font-weight="700" fill="#d64545">review</text>
      <text x="107" y="273">integration</text><text x="107" y="299" font-weight="700" fill="#d64545">staging</text>
    </g>
    <g fill="currentColor" font-size="9.5" font-weight="700">
      <text x="225" y="195">5 alone · <tspan fill="#3553ff">5 marginal</tspan></text>
      <text x="685" y="221">28 alone · <tspan fill="#0fa07f">25 marginal</tspan></text>
      <text x="465" y="247">17 alone · <tspan fill="#d64545">0 marginal</tspan></text>
      <text x="645" y="273">26 alone · <tspan fill="#e0930f">4 marginal</tspan></text>
      <text x="485" y="299">18 alone · <tspan fill="#d64545">0 marginal</tspan></text>
    </g>
    <text x="30" y="326" font-size="9.5" fill="currentColor" opacity="0.9">review and staging are not weak gates — they are <tspan font-weight="700">late</tspan> gates. everything they can see, something cheaper already saw.</text>

    <rect x="30" y="340" width="820" height="118" rx="9" fill="#d64545" fill-opacity="0.07" stroke="#d64545" stroke-opacity="0.5" stroke-width="1.5"/>
    <text x="44" y="358" font-size="9" font-weight="700" fill="#d64545">THE 6 THAT ESCAPED ALL FIVE GATES — GREEN BUILD, WRONG INVOICE</text>
    <g fill="currentColor" font-size="8.6">
      <text x="44" y="376"><tspan font-weight="700">W01</tspan>  apply_bps(a, b) → apply_bps(b, a). the body multiplies them, so NO input tells the two apart — an <tspan font-weight="700">equivalent mutant</tspan>. L13.</text>
      <text x="44" y="393"><tspan font-weight="700">S01</tspan>  tax/shipping columns swapped on write AND read. round-trip perfect; the finance job's tax total goes <tspan font-weight="700">$19,839.25 → $5,498.82 (−72%)</tspan>. L04, L06.</text>
      <text x="44" y="410"><tspan font-weight="700">R03</tspan>  tax switches to banker's rounding via float — differs on exact half-cents only: <tspan font-weight="700">17 of 2,000 orders, −$0.17</tspan> a day.</text>
      <text x="44" y="427"><tspan font-weight="700">E03</tspan>  refunds render as charges: <tspan font-weight="700">-$4.05 becomes $4.05</tspan>. 0 orders affected — the day's 2,000 orders contained no refund. L07.</text>
      <text x="44" y="444"><tspan font-weight="700">F01/F02</tspan>  receipt rendering: $4.05 prints as $4.5 on <tspan font-weight="700">181 of 2,000</tspan>, and a column width changes <tspan font-weight="700">2,000 of 2,000</tspan>. Nothing asserts on rendered output.</text>
    </g>

    <text x="440" y="482" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">These are not gaps in effort. They are gaps in KIND — and no amount of unit testing reaches them.</text>
  </g>
</svg>
```

The `alone` column is the number everyone quotes. The `marginal` column is the only one that can justify a minute of anybody's time.

**The unit suite catches 28 of 40 on its own, and 25 once the type checker has already run.** Fine — the type checker is nearly free and the overlap is small. Now read the two rows that matter.

**Code review catches 17 of 40 on its own — 42% — and 0 that the gates before it did not.** Not "a small number". Zero, in this pipeline, over these forty bugs. Every diff-level judgement the model makes is a judgement something cheaper and faster has already made.

**Staging catches 18 of 40 on its own, and 0 marginally.** Also zero. And staging's zero has a cleaner explanation than review's: staging has no oracle. It is running your code against realistic data with nobody there who knows the right answer. **An environment with no oracle cannot beat a test that has one** — the best it can do is notice that something is obviously broken, and by then CI has noticed the same thing at 40 engineer-minutes instead of 143.

Say the uncomfortable part plainly, and then say the correction. In this pipeline, on this bug population, code review has **zero** defect-detection value. That is a real result and you should not soften it. But defect detection is not why code review exists — it exists for design feedback, for shared context, for the second person who knows how this module works when you are on holiday. If you justify code review by the bugs it catches, this measurement takes the justification away from you. Justify it by something it is actually good at.

### Marginal value is path-dependent, so there is no ranking of test types

Ten thousand releases. Bugs per release drawn from a distribution, each bug one of the forty real mutations, each one stopped by the first gate in the pipeline that actually catches it, priced with the ladder from two sections ago. Then remove one gate and re-run to price it:

```text
    gate           extra prod bugs   extra escape cost   its own cost   NET / release
    types                      368             258,998         20,000           +23.9 min
    unit                       182             297,767         64,000           +23.4 min
    review                       0                   0        340,000           -34.0 min
    integration                775             513,050        150,000           +36.3 min
    staging                      0                   0        250,000           -25.0 min
```

Across the whole run: no gates at all costs **5,231,304 engineer-minutes and puts 7,452 bugs into production**. The full pipeline costs **1,649,556** — 825,556 of escaped-bug cost plus 824,000 of just running the gates every release — and puts **1,118** bugs into production. Net saving **3,581,748 engineer-minutes, $5,372,622**, over ten thousand releases.

Note what that arithmetic includes that most testing arguments leave out: **the gates cost 824,000 minutes to run whether or not they catch anything.** Half the total spend of the "good" pipeline is the gates themselves. A gate is not free because it is automated.

Now the subtle result, and it is the one to carry into every conversation about the "testing pyramid" you will ever have. Add the same five gates in a different order:

```text
    cheap first          types: 5        unit:25       revie: 0       integ: 4       stagi: 0
    expensive first      stagi:18       integ: 9       revie: 4        unit: 1       types: 2
```

Identical gates. Identical bugs. Only the order changed — and staging goes from **0** to **18**, while unit tests go from **25** to **1**.

**A gate's marginal value is a property of the pipeline it joins, not a property of the gate.** There is therefore no context-free ranking of test types, and anybody who hands you one is quoting the marginal values of a pipeline that is not yours. [The Shape of a Test Suite](../02-the-shape-of-a-test-suite/) turns this into a budget-allocation problem, and [the capstone](../15-capstone-a-suite-that-catches-real-bugs/) ablates nine layers this way over 31 seeded bugs.

### What a test is really buying: bounded regret

Here is where beginners are usually told something false: that tests make your code correct. They do not, and the next section but one proves they cannot.

What a suite buys is more specific and more useful. A refactor is a stream of edits. Some fraction of them are slips. A suite with kill rate `k` lets `(1 − k)` of those slips through. So for the **same expected number of escapes**, you can make `1/(1 − k)` times as many edits.

The slip rate cancels. You never have to estimate it — which is what makes this the rare piece of testing arithmetic you can actually do.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 442" width="100%" style="max-width:840px" role="img" aria-label="What a test suite actually buys, plotted as a hyperbola. The horizontal axis is the suite's kill rate; the vertical axis, on a logarithmic scale, is how many edits you can afford to make for the same expected number of escaped defects, which equals one divided by one minus the kill rate. The measured fourteen-test unit suite kills seventy percent and buys 3.3 times the headroom; all five gates together kill eighty-five percent and buy 6.7 times. The curve is flat at the left and vertical at the right: moving from no suite to fifty percent doubles the headroom, and moving from ninety to ninety-five percent doubles it again. On the right, a simulation of four thousand refactors of sixty edits each confirms the closed form: escape rates of 0.0402, 0.0124 and 0.0060 defects per edit, whose ratios are 3.2 and 6.7.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">A suite does not buy correctness. It buys 1/(1−k) times the change.</text>
    <text x="440" y="45" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">k = kill rate. same expected escapes, more edits — and the slip rate cancels, so you never have to estimate it.</text>

    <g fill="none" stroke="currentColor" stroke-width="1.4">
      <path d="M80 340 L 480 340"/><path d="M80 340 L 80 100"/>
    </g>
    <g stroke="currentColor" stroke-width="1" opacity="0.2" stroke-dasharray="3 4">
      <path d="M80 286.8 L 480 286.8"/><path d="M80 216.4 L 480 216.4"/><path d="M80 163.2 L 480 163.2"/><path d="M80 110 L 480 110"/>
    </g>
    <g fill="currentColor" font-size="8.5" text-anchor="end" opacity="0.75">
      <text x="72" y="343">1×</text><text x="72" y="290">2×</text><text x="72" y="219">5×</text><text x="72" y="166">10×</text><text x="72" y="113">20×</text>
    </g>
    <g fill="currentColor" font-size="8.5" text-anchor="middle" opacity="0.75">
      <text x="80" y="356">0%</text><text x="177.5" y="356">25%</text><text x="275" y="356">50%</text><text x="372.5" y="356">75%</text><text x="470" y="356">100%</text>
    </g>
    <text x="280" y="371" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.85">kill rate k — the share of your slips the suite catches</text>
    <text x="34" y="220" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.85" transform="rotate(-90 34 220)">edits you can afford</text>

    <path d="M80 340 L119 331.9 L158 322.9 L197 312.6 L236 300.8 L275 286.8 L314 269.6 L353 247.6 L392 216.4 L411.5 194.4 L431 163.2 L442.7 135.8 L450.5 110" fill="none" stroke="#3553ff" stroke-width="2.8" stroke-linejoin="round"/>

    <circle cx="353" cy="247.6" r="5" fill="#0fa07f"/><circle cx="411.5" cy="194.4" r="5" fill="#7c5cff"/>
    <path d="M353 247.6 L 353 340" fill="none" stroke="#0fa07f" stroke-width="1.2" stroke-dasharray="3 3" opacity="0.7"/>
    <path d="M411.5 194.4 L 411.5 340" fill="none" stroke="#7c5cff" stroke-width="1.2" stroke-dasharray="3 3" opacity="0.7"/>
    <text x="340" y="250" font-size="9.5" font-weight="700" text-anchor="end" fill="#0fa07f">14 unit tests · 70% · 3.3×</text>
    <text x="398" y="178" font-size="9.5" font-weight="700" text-anchor="end" fill="#7c5cff">all five gates · 85% · 6.7×</text>
    <path d="M344 247 L 347 247" fill="none" stroke="#0fa07f" stroke-width="1.2"/>
    <path d="M403 181 L 409 190" fill="none" stroke="#7c5cff" stroke-width="1.2"/>

    <g stroke="#e0930f" stroke-width="2" fill="none">
      <path d="M80 386 L 275 386"/><path d="M80 381 L 80 391"/><path d="M275 381 L 275 391"/>
      <path d="M431 386 L 450.5 386"/><path d="M431 381 L 431 391"/><path d="M450.5 381 L 450.5 391"/>
    </g>
    <text x="177" y="404" font-size="9" text-anchor="middle" fill="#e0930f" font-weight="700">0 → 50% buys 2×</text>
    <text x="441" y="404" font-size="9" text-anchor="middle" fill="#e0930f" font-weight="700">90 → 95% buys 2× again</text>

    <rect x="510" y="86" width="340" height="196" rx="9" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.5"/>
    <text x="526" y="106" font-size="9" font-weight="700" fill="currentColor" opacity="0.65">SIMULATED, NOT ASSUMED</text>
    <g fill="currentColor" font-size="8.8">
      <text x="526" y="124">4,000 refactors × 60 edits, 4% slip rate</text>
      <text x="526" y="138">= 240,000 edits per row</text>
    </g>
    <g fill="currentColor" font-size="9">
      <text x="526" y="164">no suite</text><text x="676" y="164" text-anchor="end">9,658</text><text x="836" y="164" text-anchor="end">0.0402 / edit</text>
      <text x="526" y="184" fill="#0fa07f" font-weight="700">unit suite</text><text x="676" y="184" text-anchor="end">2,975</text><text x="836" y="184" text-anchor="end" fill="#0fa07f" font-weight="700">0.0124 / edit</text>
      <text x="526" y="204" fill="#7c5cff" font-weight="700">all gates</text><text x="676" y="204" text-anchor="end">1,443</text><text x="836" y="204" text-anchor="end" fill="#7c5cff" font-weight="700">0.0060 / edit</text>
    </g>
    <text x="676" y="150" font-size="8" text-anchor="end" fill="currentColor" opacity="0.65">ESCAPES</text>
    <path d="M526 218 L 836 218" fill="none" stroke="currentColor" stroke-width="1" opacity="0.35"/>
    <g fill="currentColor" font-size="8.8">
      <text x="526" y="238">the simulation and the algebra agree:</text>
      <text x="526" y="254">0.0402 / 0.0124 = <tspan font-weight="700" fill="#0fa07f">3.2×</tspan>   ·   0.0402 / 0.0060 = <tspan font-weight="700" fill="#7c5cff">6.7×</tspan></text>
      <text x="526" y="272">no free parameter was fitted to make that true.</text>
    </g>

    <text x="440" y="428" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">The last five points of detection are worth as much as the first fifty. Test budgets are set backwards.</text>
  </g>
</svg>
```

The measured fourteen-test unit suite kills **70%**, which buys **3.3×**. All five gates together kill **85%**, which buys **6.7×**. And because the closed form is derived rather than fitted, it is worth checking it against a simulation that knows nothing about it — 4,000 refactors of 60 edits each at a 4% slip rate gave escape rates of **0.0402, 0.0124 and 0.0060 per edit**, whose ratios are **3.2× and 6.7×**. No free parameter was tuned to make that agree.

Two things follow, and the second one is a management result, not an engineering one.

First: **this is not proof, it is a bound on how surprised you should be.** A suite does not tell you the code is right. It tells you roughly how much you can change before you should expect to be wrong, which is exactly the property you need in order to keep the *option* to refactor. Code you are afraid to change is code that will not improve, and "afraid" is not a personality trait — it is a correct response to an unbounded downside.

Second: the curve is a hyperbola, so the returns are backwards from how test effort is budgeted. Going from no suite to a 50% suite doubles your headroom. Going from **90% to 95% doubles it again.** The last five points of detection are worth as much as the first fifty, and they are the ones every team cuts first because "we already have good coverage". [Coverage Lies, Mutation Testing Doesn't](../13-coverage-and-mutation-testing/) is about how to know where on that curve you actually are, and the short version is that coverage percentage will not tell you.

### Tests as executable specification, and the three questions

Every test answers one of three questions, and it is worth knowing which one you are writing.

**Does it work?** — the first time, before it has ever shipped. This is the test you write while writing the code, and it is the cheapest bug you will ever fix, because you have not yet closed the file.

**Does it still work?** — every time after. This is regression, and it is the overwhelming majority of the value: the previous section is entirely about this question.

**What did I mean?** — the question the test answers to a stranger, at 03:00, two years from now. `volume_discount_at_threshold` asserting `volume_bps(5000) == 1000` states a business rule more precisely than any prose you will write about it, and it states it in a form that **fails when it stops being true**.

That last property is the whole argument for the assertion as documentation, and this lesson can put a number on it. The pricing module has thirteen functions; three of them carry a docstring stating the rule they implement, including the one directly above the bug in The Problem. Across all forty mutations:

```text
comments and docstrings detected 0 of 40; the executable gates detected 34 of 40
```

A comment cannot go red. The docstring said "from 50.00 upwards, inclusive" before the edit and it said exactly the same thing afterwards, while the code beneath it did the opposite. **The assertion is the only part of your documentation that fails when it stops being true** — and the corollary is that a test suite is a specification that is verified on every commit, which no other document you own can claim.

### The other side of the ledger: a test that costs more than the bug

Tests are not free, and a lesson that only counts their benefits is selling something.

Take two suites over the same module, **seven tests each**, matched on size so the comparison is about the assertion and nothing else. One asserts on values and structure. The other asserts on rendered strings:

```python
# structural — asserts what you promised
assert_eq(price_order(((2500, 2),), "gold")["total"], 5221)

# brittle — asserts how it happened to be printed
assert_eq(receipt_line("Total", 5221), "Total           $52.21")
```

Run all 40 mutations past both. Then apply **eight refactors that change no behaviour a customer can observe** — widen a column, swap `$` for `USD `, add a thousands separator, rename a local, extract a helper, rename a dict key, replace an accumulator loop with `sum()` — and count the tests that break:

| | bugs caught (of 40) | tests broken by 8 no-op refactors | churn |
|---|---|---|---|
| structural | **26** | **1** | 6 min · $9 |
| brittle | **4** | **14** | 84 min · $126 |

The brittle suite caught a sixth as many bugs and cost fourteen times as much to maintain. On this evidence it is a straightforwardly bad trade.

But do not stop at the comfortable conclusion, because the measurement does not. **The brittle suite uniquely caught 2 bugs that the structural suite could not see at all** — `$4.05` printing as `$4.5`, and a receipt column silently changing width. Those are real bugs. A customer sees them. Nothing that asserts on a dictionary will ever notice.

So the question is never "is this test worthless". It is **"does this test cost less than what it catches"**, and that is arithmetic you can do on a Tuesday. Seven string assertions cost **84 minutes** of churn across those eight refactors and bought two bugs. The same two bugs are visible to one or two assertions — and the churn scales with the number of assertions, not with the number of bugs they find. **Keep exactly as many string assertions as you have rendering promises** — usually one or two, not seven — and assert on structure for everything else. [Anatomy of a Unit Test](../03-anatomy-of-a-unit-test/) takes this apart properly.

### What tests cannot do — Dijkstra's limit

Be honest about this early, because a reader who believes tests prove correctness will draw wrong conclusions from everything above.

> "Program testing can be used to show the presence of bugs, but never to show their absence."
> — Dijkstra, *Notes on Structured Programming* (EWD249), 1970

This is not a philosophical caution. It is arithmetic, and here it is priced:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 396" width="100%" style="max-width:840px" role="img" aria-label="Dijkstra's limit priced. On the left, exhaustive testing at a billion cases per second: a function of one 32-bit argument has 4,294,967,296 inputs and takes 4.29 seconds to test completely, while a function of two 32-bit arguments has 18,446,744,073,709,551,616 input pairs and takes 584.9 years. On the right, sampling 200 cases against an add32 that is wrong at exactly one point in that space: uniform random generation found the bug in 0 of 200 runs, while a boundary-biased generator drawing from a pool of fifteen edge values found it in 199 of 200 runs, with a median of 31 cases to the first failure. Below, the honest conclusion: 200 passing cases say nothing about the remaining 18,446,744,073,709,551,416 pairs.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Testing shows the presence of bugs, never their absence — priced</text>
    <text x="440" y="45" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">Dijkstra, Notes on Structured Programming (EWD249), 1970 — measured here on a signed 32-bit add</text>

    <rect x="30" y="58" width="396" height="212" rx="9" fill="#d64545" fill-opacity="0.07" stroke="#d64545" stroke-opacity="0.55" stroke-width="1.5"/>
    <text x="46" y="78" font-size="9" font-weight="700" fill="#d64545">EXHAUSTIVE, AT 1,000,000,000 CASES PER SECOND</text>
    <text x="46" y="102" font-size="9.5" fill="currentColor">one 32-bit argument</text>
    <text x="46" y="118" font-size="9" fill="currentColor" opacity="0.85">4,294,967,296 cases</text>
    <text x="410" y="118" font-size="20" font-weight="700" text-anchor="end" fill="#0fa07f">4.29 seconds</text>
    <path d="M46 142 L 410 142" fill="none" stroke="currentColor" stroke-width="1" opacity="0.3"/>
    <text x="46" y="166" font-size="9.5" fill="currentColor">two 32-bit arguments</text>
    <text x="46" y="182" font-size="9" fill="currentColor" opacity="0.85">18,446,744,073,709,551,616 cases</text>
    <text x="410" y="182" font-size="20" font-weight="700" text-anchor="end" fill="#d64545">584.9 years</text>
    <text x="46" y="216" font-size="9" fill="currentColor" opacity="0.9">one extra argument turns four seconds into six centuries.</text>
    <text x="46" y="232" font-size="9" fill="currentColor" opacity="0.9">`add` is the simplest function you own. price_order() takes</text>
    <text x="46" y="248" font-size="9" fill="currentColor" opacity="0.9">a list of (price, qty) pairs — its input space has no bound</text>
    <text x="46" y="264" font-size="9" fill="currentColor" opacity="0.9">at all, so exhaustion is not slow. it is undefined.</text>

    <rect x="454" y="58" width="396" height="212" rx="9" fill="#3553ff" fill-opacity="0.07" stroke="#3553ff" stroke-opacity="0.55" stroke-width="1.5"/>
    <text x="470" y="78" font-size="9" font-weight="700" fill="#3553ff">SO WE SAMPLE — 200 CASES, TWO WAYS OF CHOOSING THEM</text>
    <text x="470" y="98" font-size="9" fill="currentColor" opacity="0.9">the target: an add32 wrong at exactly ONE point in the 2⁶⁴.</text>
    <text x="470" y="114" font-size="9" fill="currentColor" opacity="0.9">200 independent runs of 200 cases each.</text>

    <rect x="600" y="132" width="170" height="20" rx="3" fill="#7f7f7f" fill-opacity="0.16" stroke="#7f7f7f" stroke-width="1.2"/>
    <rect x="600" y="132" width="0.001" height="20" fill="#d64545"/>
    <text x="592" y="146" font-size="9.5" text-anchor="end" fill="currentColor">uniform random</text>
    <text x="838" y="146" font-size="10" font-weight="700" text-anchor="end" fill="#d64545">0 / 200</text>

    <rect x="600" y="164" width="170" height="20" rx="3" fill="#7f7f7f" fill-opacity="0.16" stroke="#7f7f7f" stroke-width="1.2"/>
    <rect x="600" y="164" width="169.2" height="20" rx="3" fill="#0fa07f" fill-opacity="0.45" stroke="#0fa07f" stroke-width="1.4"/>
    <text x="592" y="178" font-size="9.5" text-anchor="end" fill="currentColor">boundary-biased</text>
    <text x="838" y="178" font-size="10" font-weight="700" text-anchor="end" fill="#0fa07f">199 / 200</text>
    <text x="600" y="200" font-size="8.5" fill="currentColor" opacity="0.7">runs in which 200 cases found the bug</text>

    <text x="470" y="226" font-size="9" fill="currentColor" opacity="0.9">median cases to first failure: <tspan font-weight="700" fill="#0fa07f">31</tspan> boundary-biased,</text>
    <text x="470" y="242" font-size="9" fill="currentColor" opacity="0.9"><tspan font-weight="700" fill="#d64545">never</tspan> uniform. the bug lives on a boundary, and boundaries</text>
    <text x="470" y="258" font-size="9" fill="currentColor" opacity="0.9">are a measure-zero slice of a uniform distribution.</text>

    <rect x="30" y="288" width="820" height="52" rx="9" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.5"/>
    <text x="440" y="310" text-anchor="middle" font-size="10" fill="currentColor">and the honest part: 200 passing cases say nothing about the other <tspan font-weight="700">18,446,744,073,709,551,416</tspan> pairs.</text>
    <text x="440" y="330" text-anchor="middle" font-size="10" fill="currentColor">testing showed the <tspan font-weight="700" fill="#0fa07f">presence</tspan> of this bug. nothing here shows the <tspan font-weight="700" fill="#d64545">absence</tspan> of the next one.</text>

    <text x="440" y="368" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">Every suite is a sample. The only question you get to answer is how well you chose it.</text>
  </g>
</svg>
```

A function of one 32-bit argument has 4,294,967,296 possible inputs. At a billion cases a second you can test all of them in **4.29 seconds** — genuinely exhaustive, genuinely proof. Add one more 32-bit argument and the space is 18,446,744,073,709,551,616 pairs, which takes **584.9 years**. One extra argument turns four seconds into six centuries, and `add` is the simplest function you own. The `price_order()` in this lesson takes a list of `(price, quantity)` pairs and a string; its input space has no bound at all, so exhaustion is not slow, it is *undefined*.

So every suite is a sample, and the only question you get to answer is how well you chose it. Take an `add32` that is wrong at exactly **one point** in that 2⁶⁴, and give two generators 200 cases each, 200 independent runs:

```text
    uniform random     found it in   0/200 runs of 200 cases   median cases to first failure:    —
    boundary-biased    found it in 199/200 runs of 200 cases   median cases to first failure:   31
```

**Uniform random never found it. Not once in forty thousand cases.** Drawing from a pool of fifteen boundary values — `0`, `1`, `-1`, `2**31 - 1`, `-2**31`, and so on — found it in **199 of 200 runs, with a median of 31 cases.**

That result is worth sitting with, because "random testing" sounds like it should explore the space and it does exactly the opposite: it covers the space *evenly*, and bugs do not live evenly. They live on boundaries, and a boundary is a measure-zero slice of a uniform distribution. This is why real property-testing libraries are not uniform generators, and [Property-Based Testing & Fuzzing](../12-property-based-testing-and-fuzzing/) builds one — generators, shrinker and all — from scratch.

And the honest close: 200 passing boundary cases say nothing about the other **18,446,744,073,709,551,416** pairs. Testing showed the presence of that bug. Nothing here shows the absence of the next one.

### Where the curve breaks: the bugs no unit test will find

Six of the forty escaped all five gates. They are not a gap in effort. They are a gap in *kind*, and each one is a later lesson.

**W01 — the equivalent mutant.** `apply_bps(subtotal, bps)` became `apply_bps(bps, subtotal)`. The arguments are swapped and the answer is identical, because the body multiplies them. There is no input on which the two behave differently, so **no test can ever kill it** — and deciding in general whether a mutation is equivalent is undecidable. This is why a 100% mutation kill rate is not a target ([Coverage Lies, Mutation Testing Doesn't](../13-coverage-and-mutation-testing/)).

**S01 — the double lie that agrees with itself.** Two columns swapped on *both* the write and the read. The round-trip is perfect, the integration test is green, the invoice that comes back out of the database is correct in every field. And a finance job that reads column 3 as the tax column sums the day at **$5,498.82 instead of $19,839.25 — 72% low.** The code and the test agree, and both are wrong. This is the exact failure mode of a hand-written test double ([Test Doubles](../04-test-doubles/)) and of a schema nobody validates at the seam ([Contract Testing](../10-contract-testing/), [Integration Testing Against a Real Database](../06-integration-testing-real-database/)).

**E03 — the case the data never contained.** Refunds render as charges: `-$4.05` prints as `$4.05`. Affected orders in the measured day: **0 of 2,000**, because the generated day contains no refunds. The bug is not hiding from the tests. It is hiding from the *data* ([Test Data & Fixtures](../07-test-data-and-fixtures/)).

**R03 — the case that is too rare to trip an aggregate.** Tax switches to banker's rounding via a float, which differs from half-up only on exact half-cents: **17 of 2,000 orders, −$0.17 a day.** No revenue alert will ever fire on that, and it will still be a finding in an audit two years later.

**F01/F02 — the output nothing asserts on.** `$4.05` prints as `$4.5` on 181 of 2,000 receipts; a column width changes on 2,000 of 2,000. Every gate in the pipeline checks structured values. Nobody looks at what the customer actually sees.

Two whole classes are missing from this list because a single-process pricing module cannot host them: anything involving **time** ([Determinism](../08-determinism-time-randomness-order/)), **concurrency and duplicate delivery** ([Testing Async & Event-Driven Systems](../11-testing-async-and-event-driven/)), and **emergent failure under load** ([Chaos Engineering & Testing in Production](../14-chaos-engineering-and-testing-in-production/)). Adding more unit tests reaches none of them either.

## Build It

[`code/cost_of_a_bug.py`](code/cost_of_a_bug.py) is seven numbered sections tracking the sub-headings above: one each for the runner, the cost ladder, the catch matrix, the ablation, bounded regret, the brittle-suite ledger and Dijkstra's limit — with the survivor analysis and the docstring count folded into section 3. Standard library only, one seed, about half a second. Everything quoted in this lesson comes out of that one run.

The module under test is held as **source text**, not imported, for one reason: we are going to edit it forty times the way a careless engineer edits code, one token at a time.

```python
def build(edits: Edits = ()) -> Dict[str, Any]:
    src = PRICING_SRC
    for old, new in edits:
        if src.count(old) != 1:
            raise AssertionError(f"edit {old!r} matched {src.count(old)} times")
        src = src.replace(old, new, 1)
    ns: Dict[str, Any] = {}
    exec(compile(src, "<pricing>", "exec"), ns)
    return ns
```

The `count(old) != 1` guard is the load-bearing line. An anchor that silently matched twice, or zero times, would corrupt every number downstream without ever raising — so the program refuses to run a mutation it cannot place exactly. That check is why the anchors can be as short as `">= FREE_SHIPPING"`: uniqueness is asserted, not assumed.

Each mutation is a class, an edit list and a description. Two of them need *two* edits, which is how the interesting survivors are built:

```python
("S01", "serialization", (('priced["tax"], priced["shipping"]',
                           'priced["shipping"], priced["tax"]'),
                          ('"tax": row[3], "shipping": row[4]',
                           '"shipping": row[3], "tax": row[4]')),
 "tax/shipping columns swapped on BOTH write and read"),
```

Swapping the columns on the write *and* the read is what makes S01 pass every gate. A round-trip test compares what it wrote with what it read, and both are wrong in the same direction.

The staging gate is the one worth reading closely, because getting it right is what makes its result honest:

```python
def gate_staging(m: Dict[str, Any]) -> bool:
    """Staging has no oracle — nobody there knows the right answer. It has
    invariants and yesterday's revenue number, so that is all this checks."""
    revenue = 0
    for _oid, lines, tier in DAY:
        p = m["price_order"](lines, tier)
        ...
        if p["taxable"] + p["tax"] + p["shipping"] != p["total"]:
            return True
        revenue += p["total"]
    return abs(revenue - BASELINE_REVENUE) / BASELINE_REVENUE > STAGING_REVENUE_TOLERANCE
```

It would have been easy — and wrong — to give staging the correct module to compare against. Real pre-production environments have no such thing. They have self-consistency checks and a revenue number from yesterday, and that is precisely why staging's marginal catch comes out at zero.

The ablation is deliberately blunt. To price a gate, delete it and re-run the same ten thousand releases:

```python
for g in order:
    esc, _gt, out = simulate(tuple(x for x in order if x != g), matrix, mins, SEED + 10)
    own = RELEASES * GATE_COST_MIN[g]
    rows.append((g, esc - full_esc, own, (esc - full_esc - own) / RELEASES))
```

And the sensitivity sweep uses a closed form rather than the Monte Carlo, because bugs are drawn uniformly from the forty, so the expectation needs no sampling at all — which is what makes two thousand re-derivations of the whole ablation cheap enough to run inside a lesson.

Run it:

```bash
docker compose exec -T app python \
  phases/12-testing-and-quality/01-why-tests-exist/code/cost_of_a_bug.py
```

```console
Phase 12 · Lesson 01 · Why Tests Exist: The Cost of Finding a Bug Late
seed = 20260718; standard library only; every number below is produced here
== 1 · A TEST IS A PROGRAM THAT RUNS YOUR PROGRAM ==
  the entire runner is 13 lines, counted from its own source:
  append to a list on mismatch, catch exceptions so one crash cannot hide
  the rest, return the list. no decorators, no discovery, no plugins.

  14 tests against the module as written: 0 failures
  the same 14 tests with ONE character changed (>= VOLUME_THRESHOLD_CENTS -> > VOLUME_THRESHOLD_CENTS): 3 failures

    volume_discount_at_threshold: 50.00 is INCLUSIVE
          expected: 1000
          actual:   0
    discount_bps_combines_and_caps: gold + volume
          expected: 1500
          actual:   500
    price_order_gold_at_boundary: the whole invoice at exactly 50.00
          expected: {'subtotal': 5000, 'discount': 750, 'taxable': 4250, 'tax': 372, 'shipping': 599, 'total': 5221}
          actual:   {'subtotal': 5000, 'discount': 250, 'taxable': 4750, 'tax': 416, 'shipping': 599, 'total': 5765}

  what the customer sees on that order — two items at 2,500 cents each:
    correct   Total           $52.21
    with bug  Total           $57.65

  that is a test: it ran the program, compared one value, printed the
  difference. everything pytest adds is ergonomics, not capability.

== 2 · THE ESCAPE-COST LADDER: ONE BUG, SIX PRICES ==
  what the section-1 bug actually DOES over one day of 2,000 orders:
    invoices priced differently  75 = 3.75% of the day
    money moved                  $408.00 overcharged, $5.44 per affected order
    revenue for the day          $252,065.04 correct, so the bug
                                 moves it 0.16% against a 2% alarm threshold
  every other invoice is byte-identical to the correct one, so no dashboard
  moves and no alert fires. that is why nobody notices for days.

    stage         found when                        engineer-min    cost   x unit
    types         the editor underlines it                0.5       $1       0x
    unit          a unit test goes red                    2.0       $3       1x
    review        a reviewer comments                    34.0      $51      17x
    integration   CI fails on the branch                 40.0      $60      20x
    staging       QA files a ticket                     143.0     $214      72x
    production    a customer notices                    702.0    $1053     351x

  … trimmed — the full run prints 245 lines …
    production =
      time to detection                  1 x  47.0 min =   47.0
      incident response                  3 x  40.0 min =  120.0
      rollback and hotfix                1 x  35.0 min =   35.0
      write the refund tooling           1 x  90.0 min =   90.0
      run and reconcile the refunds      2 x  55.0 min =  110.0
      postmortem                         4 x  60.0 min =  240.0
      customer comms and credits         1 x  60.0 min =   60.0

  production / unit = 351x, from first principles. the figure usually quoted for
  this ratio is 100x, from 1970s waterfall projects on six-month cycles;
  the constant is not the point and never was. the SHAPE is: cost jumps
  every time a stage adds PEOPLE or an ENVIRONMENT.
  and inside production, finding out costs 467 of 702 minutes = 67%; the
  code change is 35 minutes = 5%. the day's overcharge, $408.00, is
  0.39x the labour. the incident is the cost; the damage is a rounding error.

== 3 · FORTY REAL BUGS, FIVE GATES, AND THE MARGINAL CATCH ==
  40 single-token edits, 9 bug classes. each gate is asked twice: what do you
  catch, and what do you catch that nothing before you caught?

    gate           catches   alone   cumulative   MARGINAL   of what reached it
    types                5     12%            5          5   5/40 =   12%
    unit                28     70%           30         25   25/35 =   71%
    review              17     42%           30          0   0/10 =    0%
    integration         26     65%           34          4   4/10 =   40%
    staging             18     45%           34          0   0/6 =    0%
    ESCAPES              6     15%

  the unit suite catches 28/40 on its own. added after types it is worth 25 more.
  that gap is the whole argument for measuring gates in order rather than alone.

  by bug class — where each class actually dies:
    class             n  types   unit  revie  integ  stagi   escapes
    boundary          5      0      5      3      3      1         0
    arithmetic        7      0      7      2      7      7         0
    rounding          4      0      3      2      2      1         1
    type-shape        4      4      2      1      2      2         0
    constant          6      1      6      6      6      5         0
    wiring            5      0      3      1      3      2         1
    serialization     4      0      0      0      3      0         1
    error-handling    3      0      2      2      0      0         1
    formatting        2      0      0      0      0      0         2

  the survivors — five gates green, and the invoice still wrong:
    id   class          orders visibly wrong   money on the total   what it is
    E03  error-handling       0 of 2,000 =   0.0%           $0.00       refunds render as charges
    F01  formatting         181 of 2,000 =   9.0%           $0.00       4.05 renders as $4.5
    F02  formatting       2,000 of 2,000 = 100.0%           $0.00       receipt column width 12 -> 14
    R03  rounding            17 of 2,000 =   0.9%          -$0.17       tax switches to banker's rounding, via float
    S01  serialization        0 of 2,000 =   0.0%           $0.00       tax/shipping columns swapped on BOTH write and read
    W01  wiring               0 of 2,000 =   0.0%           $0.00       apply_bps arguments swapped

  three of those read zero, and the zero is the interesting part — the
  day's data never contained the case. ask each a different question:
    S01  a finance job sums column 3 as tax:  correct $19,839.25   with S01 $5,498.82  (-72%)
         the round-trip is perfect. every OTHER reader of that table is wrong,
         and the suite that wrote it will never say so (lessons 04, 06).
    E03  render a refund of -4.05:  correct '-$4.05'   with E03 '$4.05'
         2,000 orders, not one refund among them. the bug is not hiding
         from the tests; it is hiding from the DATA (lesson 07).
    W01  apply_bps(subtotal, bps) became apply_bps(bps, subtotal) — and the
         body multiplies them, so NO input distinguishes the two. an
         EQUIVALENT MUTANT: undecidable in general, and the reason a 100%
         kill rate is not a target (lesson 13).

  … trimmed — the full run prints 245 lines …
== 4 · THE MARGINAL VALUE OF A GATE, IN MONEY ==
  10,000 releases; bugs per release drawn from {0: 55, 1: 27, 2: 11, 3: 5, 4: 2} (weights),
  each one of the 40 real mutations, stopped by the first gate that catches it.

    no gates at all:     5,231,304 engineer-min  = $  7,846,956   7,452 bugs in production
    the full pipeline: escape    825,556 + running   824,000 =  1,649,556 min   1,118 in production
    net saving 3,581,748 engineer-minutes over 10,000 releases = $5,372,622
  what each gate costs to RUN, per release, caught or not:  types 2.0  unit 6.4  review 34.0  integration 15.0  staging 25.0

  ABLATION — remove one gate, keep the rest, see what it was worth:
    gate           extra prod bugs   extra escape cost   its own cost   NET / release
    types                      368             258,998         20,000           +23.9 min
    unit                       182             297,767         64,000           +23.4 min
    review                       0                   0        340,000           -34.0 min
    integration                775             513,050        150,000           +36.3 min
    staging                      0                   0        250,000           -25.0 min
    positive NET means the gate saves more than it costs to run. best: integration at
    +36.3 min/release; worst: review at -34.0, which catches nothing the others miss.

  PATH DEPENDENCE — the same five gates, added in a different order:
                                1              2              3              4              5
    cheap first          types: 5        unit:25       revie: 0       integ: 4       stagi: 0
    expensive first      stagi:18       integ: 9       revie: 4        unit: 1       types: 2
    identical gates, only the order changed. a gate's marginal value is a
    property of the pipeline it joins, not of the gate — so there is no
    context-free ranking of test types (lesson 15 ablates nine layers).

  SENSITIVITY — does any of this survive changing the cost ladder?
    every stage cost multiplied by a random factor in [0.4, 1.6], 2,000 times:
    exact ranking of all five unchanged:  1,048/2,000 =  52%
    SET of gates worth running unchanged: 2,000/2,000 = 100%
    that pair is the honest answer. the exact ordering is NOT robust —
    types and unit sit 0.5 min/release apart and swap under any jitter.
    the DECISION — which gates earn their keep — does not move at all.

== 5 · BOUNDED REGRET: HOW MUCH CODE YOU CAN AFFORD TO CHANGE ==
  a refactor is a stream of edits and some fraction of them are slips. a
  suite with kill rate k lets (1-k) through, so for the SAME expected number
  of escapes you can make 1/(1-k) times as many edits. the slip rate cancels;

  … trimmed — the full run prints 245 lines …
              all five gates together kill  85%  ->   6.7x

  simulated rather than trusted — 4,000 refactors x 60 edits, 4% slip rate:
    no suite       9658 escaped defects over 240,000 edits  = 0.0402/edit
    unit suite     2975 escaped defects over 240,000 edits  = 0.0124/edit
    all gates      1443 escaped defects over 240,000 edits  = 0.0060/edit
    the ratios the simulation produces, against 3.3x and 6.7x predicted:
      0.0402 / 0.0124 = 3.2x   ·   0.0402 / 0.0060 = 6.7x   — no free parameter was fitted

  the shape is a hyperbola, and that is the management lesson: no suite to
  50% doubles your headroom, and 90% to 95% doubles it AGAIN. the last few
  points of detection are worth as much as the first fifty — exactly
  backwards from how test effort is usually budgeted. and note what this is
  NOT: not proof, but a bound on how surprised you should be.

== 6 · THE OTHER SIDE OF THE LEDGER: A TEST THAT COSTS MORE THAN IT SAVES ==
  two suites, seven tests each, over the same module. one asserts on values,
  one on rendered strings — matched on size so the comparison is about the
  assertion and nothing else.

    suite         bugs caught (of 40)   caught that the other did not
    structural              26          A01, A02, A03, A04, A05, A06, A07, B01, B04, … (24)
    brittle                  4          F01, F02

  now eight refactors that change no behaviour a customer can observe:
    refactor                                       structural  brittle
    widen the receipt name column to 14                     0        3
    right-align the amount in 12 not 10                     0        3
    use USD instead of the dollar sign                      0        7
    thousands separator on the units                        0        1
    rename the local `c` to `abs_cents`                     0        0
    extract a `_units` helper out of format_money           0        0
    rename the dict key `taxable` to `taxable_cents`          1        0
    replace the accumulator loop with sum()                 0        0
    TOTAL broken tests                                      1       14

  at 6 minutes to read, diagnose and update each broken test:
    structural     1 breakages x 6 min =     6 min of pure churn  ($9)
    brittle       14 breakages x 6 min =    84 min of pure churn  ($126)

  the brittle suite is not worthless: it uniquely caught 2 (F01, F02),
  and formatting bugs are real bugs that only a rendered assertion sees. the
  question is never 'is this test worthless' but 'does it cost less than what
  it catches', which is arithmetic. keep exactly as many string assertions as
  you have rendering promises — usually one or two, not seven.

== 7 · WHAT TESTING CANNOT DO, PRICED IN YEARS ==
  exhaustive testing of a 32-bit function, at a billion cases per second:
    one 32-bit argument                4,294,967,296 cases  =     4.29 seconds
    two 32-bit arguments  18,446,744,073,709,551,616 cases  =    584.9 years
  one extra argument turns four seconds into six centuries. `add` is the
  simplest function you own; price_order() takes a list of pairs and a
  string, and its input space has no bound at all.

  so we sample. 200 cases, two ways of choosing them, against an add32 that
  is wrong at exactly one point in the 2**64:
    uniform random     found it in   0/200 runs of 200 cases   median cases to first failure:    —
    boundary-biased    found it in 199/200 runs of 200 cases   median cases to first failure:   31

    uniform random covers the space evenly and therefore never goes anywhere
    interesting: the bug lives on a boundary, and boundaries are a
    measure-zero slice of a uniform distribution. a pool of 15 boundary
    values finds it almost every time. this is why real property-testing
    libraries are not uniform generators — lesson 12 builds one.

  and the honest part: 200 passing cases say nothing about the other
  18,446,744,073,709,551,416 pairs. testing showed the presence of this bug.
  nothing here shows the absence of the next one. (Dijkstra, EWD249, 1970.)

  (total wall time 0.5 s)
```

Four things in that output are arguments rather than demonstrations.

**Section 3's `MARGINAL` column is the lesson.** Two of five gates contribute nothing. If you had ranked these gates by what they catch *alone*, review (17) and staging (18) would both have outranked types (5) — and both are worth exactly zero once types and unit tests have run.

**Section 3's survivor list is what honest looks like.** A lesson that ended at "34 of 40 caught, tests are good" would be a worse lesson. The six that escaped are the map of the rest of this phase.

**Section 4's sensitivity result contradicts the comfortable version of the argument.** The exact ranking of gates is stable in only 52% of jittered draws. Anyone quoting a precise cost-of-a-bug multiple is over-reading their own model; the only conclusion the model supports is binary.

**Section 7 is the one to reread before you start writing tests.** Two hundred well-chosen cases beat forty thousand uniformly random ones, and neither proves anything about the remaining 18,446,744,073,709,551,416.

## Use It

You will not write the thirteen-line runner again. You will use **pytest**, and this section is genuinely first-contact — if you have never run a test, start here.

**Install it and name the file correctly.** Collection is convention-driven, and this is where beginners lose an hour:

```bash
pip install pytest
```

```text
files      test_*.py   or   *_test.py        <- anything else is INVISIBLE to pytest
functions  test_*                            <- a function named check_total is never run
classes    Test*  and it must have NO __init__
```

A file called `tests.py` containing a function called `check_pricing` is collected as **zero tests**, pytest exits 0, and CI is green. That is the single most common first hour of using pytest.

**A test is a function whose name starts with `test_` and that uses a bare `assert`:**

```python
# test_pricing.py
from pricing import volume_bps, price_order

def test_volume_discount_applies_at_exactly_the_threshold():
    assert volume_bps(5000) == 1000

def test_volume_discount_does_not_apply_below_it():
    assert volume_bps(4999) == 0
```

```console
$ pytest -q
.F                                                                       [100%]
=================================== FAILURES ===================================
______________ test_volume_discount_applies_at_exactly_the_threshold ___________

    def test_volume_discount_applies_at_exactly_the_threshold():
>       assert volume_bps(5000) == 1000
E       assert 0 == 1000
E        +  where 0 = volume_bps(5000)
```

That `+ where 0 = volume_bps(5000)` line is **assertion rewriting**, and it is the single best thing pytest does. Python's built-in `assert` throws away everything it knows on failure — `AssertionError` with no message. Pytest rewrites the bytecode of your test modules at import time so that a failing `assert a == b` re-evaluates and prints both sides, plus a diff for dicts, lists and strings. It is why you write `assert x == y` in pytest and not `self.assertEqual(x, y)`.

Note the one place it bites: assertion rewriting only applies to test modules and to packages you register with `pytest.register_assert_rewrite`. An assertion inside a helper in your application code fails bare.

**The flags that matter on day one:**

```bash
pytest                      # everything, from the rootdir down
pytest -q                   # quiet: one char per test. what you want in CI
pytest -x                   # stop at the first failure. what you want while fixing
pytest -k "volume or tax"   # substring match on test names — no marker setup needed
pytest --lf                 # --last-failed: rerun ONLY what failed last time
pytest --ff                 # --failed-first: run those first, then the rest
pytest -vv                  # full diffs, no truncation, when a dict comparison is elided
pytest --tb=short           # tracebacks you can actually read
pytest -s                   # don't capture stdout (your print() statements reappear)
```

`--lf` and `--ff` are the two that change how the tool feels. Pytest caches the last run's failures in `.pytest_cache/`, so a red suite becomes a two-second loop instead of a two-minute one. Add `.pytest_cache/` to `.gitignore`; keep it in your CI cache.

**Exit codes**, because CI reads them and nothing else:

```text
0  all passed              3  internal error
1  some tests failed       4  bad command line
2  interrupted (Ctrl-C)    5  NO TESTS COLLECTED   <- the dangerous one
```

**Exit code 5 is the one to gate on.** A refactor that renames a directory, a bad `testpaths` setting, or a missing `__init__.py` can silently collect nothing — and a naive CI step that only checks for non-zero will treat "no tests ran" as… also a failure, fortunately. But a step that runs `pytest || true`, or one that filters with `-k` on a name that no longer exists, will pass with zero tests executed. Assert a minimum test count in CI if this has ever happened to you; it will have.

**`conftest.py`** is pytest's one piece of real magic, so it is worth demystifying too. It is a file pytest imports automatically for every test in its directory and below — no import statement, no registration. Fixtures and hooks defined there are available to those tests. That is all it is.

```python
# tests/conftest.py
import pytest

@pytest.fixture
def gold_order():
    """Arrange-once data. Any test can now take `gold_order` as a parameter."""
    return (((2500, 2),), "gold")

def test_total_at_the_boundary(gold_order):
    assert price_order(*gold_order)["total"] == 5221
```

Directory scoping is the part people get wrong: a `conftest.py` at the repo root applies to *everything*, and one in `tests/integration/` applies only there. Put slow, shared setup in the narrowest `conftest.py` that needs it.

**Configuration** goes in `pyproject.toml` (or `pytest.ini`) at the repo root, which is also how pytest decides what "rootdir" means:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q --strict-markers --tb=short"
markers = ["slow: takes more than a second"]
```

`--strict-markers` is not optional. Without it, `@pytest.mark.slwo` (typo) is silently accepted as a new marker, and `pytest -m "not slow"` quietly runs the test you were trying to skip.

**What to actually do, in order, if you are starting from nothing:**

1. `pip install pytest`, make a `tests/` directory, write **one** test for the boundary case of the most business-critical function you own. Not a suite. One test. Section 3 of this lesson measured 25 of 40 bugs dying at the unit gate.
2. Add `pytest -q -x` to CI as a required check. A test that does not gate a merge is a document, not a gate.
3. When a bug reaches production, write the test that would have caught it **before** you write the fix. That single habit is what moves bugs down the 351× ladder, permanently, one bug at a time.
4. Do not buy a coverage target yet. [Lesson 13](../13-coverage-and-mutation-testing/) shows a suite with 100% line coverage and zero detection.

Two tools to know exist but not to install today: **hypothesis**, which is section 7's boundary-biased generation done properly ([Lesson 12](../12-property-based-testing-and-fuzzing/)), and **mutmut** or **cosmic-ray**, which are section 3's forty mutations done automatically against your real suite ([Lesson 13](../13-coverage-and-mutation-testing/)). Both are how you find out whether the suite you just wrote can detect anything at all.

## Think about it

1. Code review's marginal defect-detection value measured **exactly zero** in this pipeline — 17 of 40 alone, 0 after types and unit tests — while costing 34 minutes per release. Your team spends roughly that. Construct the argument for keeping code review that survives this measurement, and then name the one change to the *pipeline* that would give review a non-zero marginal value again.
2. The same five gates in reverse order gave staging a marginal catch of **18** instead of **0**, and unit tests **1** instead of **25**. Your CI runs integration tests before unit tests because they share a fixture. What does that ordering do to the numbers you would use to justify each suite — and is your pipeline's order chosen or inherited?
3. S01 swapped two database columns on both the write and the read: the round-trip test is green, the invoice is correct, and a finance job reads the day **72% low**. Describe the cheapest test that catches S01, and then explain why almost no team writes it.
4. Boundary-biased generation found a one-in-2⁶⁴ bug in a median of **31** cases; uniform random missed it in **40,000**. Both are "random testing". What property of your own code's input space decides which of those two outcomes you get — and how would you find that property without already knowing where the bug is?
5. The measured escape ladder makes a production bug **351×** a unit-test bug, but the sensitivity sweep says the *exact ranking* of gates is stable in only **52%** of jittered draws while the *set* worth running is stable in **100%**. Write the sentence you would put in a design doc that uses this model correctly, and the sentence a colleague would write that over-reads it.

## Key takeaways

- **A bug's cost is the distance between writing it and finding out, not the damage it does.** The same one-character change costs **0.5 → 2 → 34 → 40 → 143 → 702 engineer-minutes** at six stages — **351×** end to end. Of production's 702 minutes, **467 (67%)** is detection, response, postmortem and comms; the actual code change is **35 minutes (5%)**; and the day's overcharge, **$408.00**, is 0.39× the labour it triggers.
- **A test framework is not magic — it is thirteen lines.** `assert_eq` plus a loop that catches exceptions caught the discount bug in **3 of 14** tests and printed the whole wrong invoice. Everything pytest adds is ergonomics: assertion rewriting, `--lf`, fixtures. Capability was never the missing piece.
- **Rank gates by what they catch that the previous gate did not, never by what they catch alone.** Over 40 seeded bugs: types **5 alone / 5 marginal**, unit **28 / 25**, review **17 / 0**, integration **26 / 4**, staging **18 / 0**. Two of the five most expensive gates in a normal pipeline contributed **zero** detection — and staging's zero is structural, because an environment with no oracle cannot beat a test that has one.
- **Marginal value is path-dependent, so no ranking of test types is portable.** Reversing the order moved staging from **0 to 18** and unit tests from **25 to 1**, with identical gates and identical bugs. Anyone who tells you integration tests are worth more than unit tests is quoting a pipeline that is not yours.
- **The gates cost 824,000 of the 1,649,556 minutes** spent over 10,000 simulated releases — half the total. Running a gate is not free because it is automated, which is why the ablation subtracts each gate's own cost before calling it worthwhile.
- **A suite buys `1/(1 − k)` times the change for the same regret — not correctness.** The 14-test unit suite kills **70% → 3.3×**; all five gates kill **85% → 6.7×**; an independent simulation over 240,000 edits agreed at **3.2× and 6.7×**. The curve is a hyperbola: 0→50% doubles your headroom and **90→95% doubles it again**, so the last five points are worth as much as the first fifty.
- **The assertion is the only documentation that fails when it stops being true.** Across 40 mutations, comments and docstrings detected **0**; the executable gates detected **34**. The docstring above the bug said "inclusive" before and after the edit that made it exclusive.
- **Testing shows presence, never absence — and the price of trying is 584.9 years.** One 32-bit argument is exhaustible in **4.29 seconds**; two is **18,446,744,073,709,551,616** pairs. Sampling is therefore mandatory, and *how* you sample decides everything: uniform random found a one-point bug in **0 of 200** runs, boundary-biased in **199 of 200**, median **31** cases (Dijkstra, EWD249, 1970).
- **Some bugs are a gap in kind, not in effort.** Six of forty escaped every gate: an **equivalent mutant** no test can kill, a serialization swap whose round-trip is perfect while a finance job reads **72% low**, a refund-formatting bug the test data never contained, a rounding bug on **17 of 2,000** orders, and two rendering bugs nothing asserts on. More unit tests reach none of them.

Next: [The Shape of a Test Suite: Pyramid, Trophy & the Honest Trade-off](../02-the-shape-of-a-test-suite/) — turns this lesson's marginal-value measurement into a budget-allocation problem, and solves for the suite shape that catches the most bugs in a fixed number of CI seconds.
