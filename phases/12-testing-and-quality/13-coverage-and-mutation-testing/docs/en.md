# Coverage Lies, Mutation Testing Doesn't

> Six tests that call every function in a pricing module and contain **not one assertion** score **100.0% line coverage** — 48 of 48 executable lines — and walk through a `fail_under = 90` gate without an argument. Measured here against 70 seeded faults, that suite catches **zero of them**. Then the result that reframes the metric: across five suites of rising quality, line coverage is already at its maximum on the *first* one and never moves again, while the mutation score climbs **0% → 30.0% → 78.6% → 88.6% → 95.7%**. Every bit of quality difference between those five suites is invisible to the number your CI gate reads. And two suites of eight tests, both reporting **100% line and 100% branch coverage**, detected **52.9%** and **95.7%** of the same faults.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Anatomy of a Unit Test](../03-anatomy-of-a-unit-test/), [Property-Based Testing & Fuzzing](../12-property-based-testing-and-fuzzing/)
**Time:** ~75 minutes

## The Problem

The pricing service sits at 87% line coverage. The gate in `.coveragerc` says `fail_under = 90`. Every pull request has been red for eleven days, and the sprint goal — written on a card, agreed in planning, visible on a dashboard — is "reach 90% coverage".

**Thursday, 14:05.** Someone works out what the shortest path to 90 looks like. It is not subtle:

```python
def test_pricing_module_does_not_explode():
    for qty in (-1, 5, 50, 150):
        for tier in ("gold", "standard"):
            try:
                discount_pct(qty, tier)
            except Exception:
                pass
```

Six tests in that shape, one per function. Every function called, every guard clause reached, every exception swallowed. **Zero assertions.** The suite runs in milliseconds and it is green, because a test with no assertions cannot fail.

**14:40 — coverage comes back at 100.0%.** Not 90: 48 of 48 executable lines. The gate is satisfied by a margin nobody expected. The PR is approved in four minutes, because there is nothing in it to disagree with — no logic, no expectations, no opinion about what the code should do. It is a set of six loops.

**Two weeks later, 09:12.** Finance opens a ticket. Gold-tier customers ordering 150 units are being charged a 23% discount where the rate card caps the discount at 20%. The clamp — `if pct > 20: pct = 20` — is present, correct, and covered by tests. It has been covered since 14:40 on that Thursday. It was never *checked* by anything.

Run the arithmetic that the coverage report cannot. Seed 70 single-line faults into that module — an `<` that becomes `<=`, a `+` that becomes `-`, a `raise` that becomes a `pass`, a deleted assignment — and run the 100%-coverage suite against each one. **It detects 0 of 70.** Every fault survives. The suite executes every line of the module and is, in the only sense that matters, not connected to it at all.

This is not a story about one lazy afternoon. It is the *existence proof* that settles what coverage is: a suite can reach the maximum of the metric while having exactly zero detection power, so the metric and detection power are independent quantities. Any number in between is somewhere on a line whose endpoints are 100% coverage with 0% detection at one end and 100% coverage with real detection at the other, and **coverage cannot tell you which end you are on.**

> **Coverage measures which lines ran. Running a line is not testing it.**

## The Concept

### What coverage actually measures

Coverage is the answer to one question: *of the things in this program that could have been executed, which ones were?* The disagreements are all about what "thing" means, and there are five standard answers, each strictly stronger than the last.

**Line (or statement) coverage** counts statements executed. **Branch (or decision) coverage** counts *outcomes* of each two-way decision — an `if` contributes two, taken and not-taken, and it takes both to score. **Condition coverage** counts the individual boolean sub-expressions inside a decision: `a and b` has two conditions and four combinations. **MC/DC — Modified Condition/Decision Coverage**, the criterion mandated for the highest software levels by RTCA DO-178C (2011) — requires each condition be shown to *independently* flip the decision, which needs a pair of tests differing in that condition alone. **Path coverage** counts distinct routes through the whole function.

The gap between the first two is not exotic. Here is the shipping function from this lesson's module and a single test against it:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 452" width="100%" style="max-width:840px" role="img" aria-label="A control-flow diagram of a six-line shipping function under a single test, shipping_cents with subtotal six thousand and express true. Every one of the six statements executes, so line coverage reports six of six, one hundred percent. But each of the two if statements has a false outcome that is never taken: the standard-shipping path where the subtotal is under five thousand, and the no-express path. Branch coverage is therefore two of four, fifty percent. Below, the four coverage criteria on a decision with four conditions: line coverage is satisfied by one test, branch coverage by two, MC/DC by five, and full condition-combination coverage needs sixteen.">
  <defs>
    <marker id="p12-13-a-yes" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p12-13-a-no" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">One test. Every line ran. Half the decisions never happened.</text>
    <text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.82">measured: shipping_cents(6000, True) — line 6/6 = 100.0%, branch 2/4 = 50.0%</text>

    <rect x="24" y="62" width="392" height="128" rx="9" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.6"/>
    <g font-size="10" fill="currentColor">
      <text x="40" y="82">def shipping_cents(subtotal_cents, express):</text>
      <text x="40" y="100">&#160;&#160;&#160;&#160;fee = 499</text>
      <text x="40" y="118">&#160;&#160;&#160;&#160;if subtotal_cents &gt;= 5000:</text>
      <text x="40" y="136">&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;fee = 0</text>
      <text x="40" y="154">&#160;&#160;&#160;&#160;if express:</text>
      <text x="40" y="172">&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;fee = fee + 1200</text>
    </g>
    <text x="220" y="206" text-anchor="middle" font-size="9" fill="#0fa07f" font-weight="700">all six statements execute — line coverage is satisfied</text>

    <g stroke-width="1.9">
      <rect x="470" y="56" width="182" height="30" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f"/>
      <rect x="470" y="112" width="182" height="30" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f"/>
      <rect x="470" y="182" width="182" height="30" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f"/>
    </g>
    <g font-size="9.5" text-anchor="middle" fill="currentColor" font-weight="700">
      <text x="561" y="75">if subtotal &gt;= 5000</text><text x="561" y="131">if express</text><text x="561" y="201">return fee</text>
    </g>

    <g fill="none" stroke="#0fa07f" stroke-width="2.2">
      <path d="M561 86 L 561 106" marker-end="url(#p12-13-a-yes)"/>
      <path d="M561 142 L 561 176" marker-end="url(#p12-13-a-yes)"/>
    </g>
    <g fill="none" stroke="#d64545" stroke-width="2" stroke-dasharray="5 4">
      <path d="M652 64 L 700 64 L 700 120 L 660 120" marker-end="url(#p12-13-a-no)"/>
      <path d="M652 136 L 776 136 L 776 204 L 660 204" marker-end="url(#p12-13-a-no)"/>
    </g>
    <g font-size="8.5" fill="#0fa07f" font-weight="700">
      <text x="570" y="102">TRUE — taken</text><text x="570" y="164">TRUE — taken</text>
    </g>
    <g font-size="8.5" fill="#d64545" font-weight="700">
      <text x="708" y="96">FALSE — never</text><text x="784" y="174">FALSE — never</text>
    </g>
    <text x="600" y="234" text-anchor="middle" font-size="9" fill="#d64545" font-weight="700">the standard-shipping path and the no-express path</text>
    <text x="600" y="248" text-anchor="middle" font-size="9" fill="#d64545" font-weight="700">are the two most common orders you take. Untested.</text>

    <rect x="24" y="258" width="832" height="126" rx="9" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4"/>
    <text x="40" y="278" font-size="10" font-weight="700" fill="currentColor">the five criteria, measured on one decision with four conditions:  (a and b) or (c and d)</text>
    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="40" y="300">CRITERION</text><text x="330" y="300">TESTS NEEDED</text><text x="470" y="300">WHAT IT PROVES</text>
    </g>
    <g fill="currentColor" font-size="9.5">
      <text x="40" y="320" font-weight="700" fill="#d64545">line / statement</text><text x="330" y="320" font-weight="700" fill="#d64545">1</text><text x="470" y="320">the statement was executed at least once</text>
      <text x="40" y="338" font-weight="700" fill="#e0930f">branch / decision</text><text x="330" y="338" font-weight="700" fill="#e0930f">2</text><text x="470" y="338">the decision came out both ways</text>
      <text x="40" y="356" font-weight="700" fill="#0fa07f">MC/DC</text><text x="330" y="356" font-weight="700" fill="#0fa07f">5</text><text x="470" y="356">each condition independently flipped the decision  (n+1)</text>
      <text x="40" y="374" font-weight="700" fill="#7c5cff">every condition combination</text><text x="330" y="374" font-weight="700" fill="#7c5cff">16</text><text x="470" y="374">every assignment of the four conditions  (2ⁿ)</text>
    </g>

    <text x="440" y="410" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">An `if` with no `else` costs nothing in line coverage and half your branch coverage.</text>
    <text x="440" y="430" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.88">MC/DC's 5 was found by exhaustive search over all 16 assignments, not assumed from the n+1 rule.</text>
    <text x="440" y="446" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.7">MC/DC as defined in RTCA DO-178C, Software Considerations in Airborne Systems and Equipment Certification, 2011.</text>
  </g>
</svg>
```

Every statement in that function executes under the single test `shipping_cents(6000, True)`, so line coverage reports **6/6, 100.0%**. Both `if` statements only ever came out true, so branch coverage reports **2/4, 50.0%**. The two untaken outcomes are the standard-shipping path and the non-express path — which between them are most of your orders.

The general rule falls out of the shapes: **an `if` with no `else` is free in line coverage.** There is no statement on the false side to leave unexecuted, so the metric has nothing to notice. Backend code is largely `if`-with-no-`else`: guard clauses, early returns, feature flags, null checks, the retry that only happens sometimes. Line coverage is systematically blindest exactly where backend code is densest. Turning on `--branch` is not an optional refinement; it is the difference between measuring statements and measuring decisions.

### The no-assert suite: 100% coverage, 0% detection

The suite from The Problem is worth staring at, because it is the cleanest possible disproof of "coverage measures quality".

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 424" width="100%" style="max-width:840px" role="img" aria-label="On the left, the entire body of the no-assert test suite: six tests that loop over inputs, call each function, and swallow every exception, containing zero assertions. On the right, three measured bars for that suite against a pricing module of forty-eight executable lines: line coverage one hundred percent, forty-eight of forty-eight; branch coverage eighty-seven point five percent, twenty-one of twenty-four; and mutants killed zero point zero percent, zero of seventy. The suite passes a fail-under-ninety gate and detects nothing.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">The whole suite, and the three numbers it produces</text>

    <rect x="24" y="48" width="386" height="146" rx="9" fill="#3553ff" fill-opacity="0.09" stroke="#3553ff" stroke-width="1.6"/>
    <text x="40" y="68" font-size="9" font-weight="700" fill="#3553ff">one of the six tests — the other five are the same shape</text>
    <g font-size="10" fill="currentColor">
      <text x="40" y="90">def test_discount_does_not_explode():</text>
      <text x="40" y="108">&#160;&#160;&#160;&#160;for qty in (-1, 5, 50, 150):</text>
      <text x="40" y="126">&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;try:</text>
      <text x="40" y="144">&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;discount_pct(qty, "gold")</text>
      <text x="40" y="162">&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;except Exception:</text>
      <text x="40" y="180">&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;pass</text>
    </g>
    <g font-size="9.5" fill="currentColor">
      <text x="40" y="218" font-weight="700">6 tests</text><text x="150" y="218" opacity="0.85">every function called</text>
      <text x="40" y="236" font-weight="700" fill="#d64545">0 assertions</text><text x="150" y="236" opacity="0.85">nothing is ever compared</text>
      <text x="40" y="254" font-weight="700" fill="#0fa07f">6 / 6 pass</text><text x="150" y="254" opacity="0.85">a test with no assertion cannot fail</text>
    </g>

    <path d="M446 48 L 446 268" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.35"/>

    <text x="652" y="66" text-anchor="middle" font-size="9" font-weight="700" fill="currentColor" opacity="0.85">same module: 48 executable lines &#183; 12 branches &#183; 70 seeded faults</text>

    <g fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.35">
      <path d="M580 82 L 580 250"/><path d="M820 82 L 820 250"/>
    </g>

    <rect x="580" y="92" width="240" height="26" rx="4" fill="#d64545" fill-opacity="0.30" stroke="#d64545" stroke-width="1.6"/>
    <rect x="580" y="148" width="210" height="26" rx="4" fill="#e0930f" fill-opacity="0.30" stroke="#e0930f" stroke-width="1.6"/>
    <rect x="580" y="204" width="3" height="26" rx="1" fill="#0fa07f" fill-opacity="0.55" stroke="#0fa07f" stroke-width="1.6"/>

    <g font-size="10" text-anchor="end" fill="currentColor">
      <text x="570" y="103" font-weight="700">line coverage</text><text x="570" y="116" font-size="8.5" opacity="0.72">48 of 48 lines</text>
      <text x="570" y="159" font-weight="700">branch coverage</text><text x="570" y="172" font-size="8.5" opacity="0.72">21 of 24 outcomes</text>
      <text x="570" y="215" font-weight="700">faults detected</text><text x="570" y="228" font-size="8.5" opacity="0.72">0 of 70 mutants</text>
    </g>
    <g font-size="13" font-weight="700">
      <text x="828" y="112" fill="#d64545">100.0%</text><text x="798" y="168" fill="#e0930f">87.5%</text><text x="592" y="224" fill="#0fa07f">0.0%</text>
    </g>
    <g fill="currentColor" font-size="8.5" text-anchor="middle" opacity="0.6">
      <text x="580" y="264">0%</text><text x="820" y="264">100%</text>
    </g>

    <rect x="24" y="286" width="832" height="52" rx="8" fill="#d64545" fill-opacity="0.09" stroke="#d64545" stroke-opacity="0.55" stroke-width="1.4"/>
    <text x="440" y="308" text-anchor="middle" font-size="11" font-weight="700" fill="#d64545">A gate of `fail_under = 90` passes this suite by ten points.</text>
    <text x="440" y="326" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">Coverage is at its ceiling and detection is at zero — so the two quantities are independent.</text>

    <text x="440" y="366" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">Note the middle bar: even branch coverage reads 87.5% on a suite that proves nothing.</text>
    <text x="440" y="386" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.88">`--branch` is a strictly better metric. It is still a metric about execution, not about checking.</text>
    <text x="440" y="408" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">Fault seeding follows DeMillo, Lipton &amp; Sayward, Hints on Test Data Selection, IEEE Computer 11(4), 1978.</text>
  </g>
</svg>
```

The middle bar is the part that surprises people who already know the punchline. Switching to branch coverage does not rescue the suite — it still reports **87.5%**, comfortably above most gates, on a suite with no assertions in it. Branch coverage is a genuinely better metric than line coverage and it is still a metric about *execution*. Neither one can see the thing that distinguishes a test from a function call, which is that a test **compares a result to an expectation and refuses to continue when they differ**.

There is a mechanical reason this suite is not merely a contrived stunt: it is what a suite decays toward under pressure. Every `try/except Exception: pass` in a real test file, every assertion on a mock's own configured return value, every `assert result is not None`, every snapshot test whose snapshot was regenerated to match the new output — each is a small step toward the no-assert suite, and none of them costs a single point of coverage.

Which means you can look for it, and you should, because the degenerate cases are cheap to find. A test function whose body contains no `assert`, no `pytest.raises` and no `unittest` assertion method is a call, not a test — `grep` will list them in a second, and every one you find is a line item on your coverage report that is contributing nothing. The subtler version needs a human: a test whose only assertion constrains the *type* or the *shape* of a result rather than its *value*. Suite 2 in the divergence measurement below is exactly that suite, and it is the one most real test files resemble.

### Coverage is a ceiling, not a floor

Here is the correct mental model, and it is an asymmetry that almost nobody states precisely.

Take an ordinary suite — eight tests, real assertions on real values, **89.6% line coverage** — and split the 70 seeded faults by whether the suite executed the line the fault sits on:

```text
    mutants sited on...        count   killed   kill rate
    a line the suite ran          65       55    84.6%
    a line it did not run          5        0     0.0%
```

The bottom row is not an empirical finding. It is **0.0% by construction, and it will be 0.0% in every program, every language, every suite, forever.** A test cannot observe a difference in code that never runs during it. So an uncovered line is proof of an untested line — an implication with no exceptions and no counterexamples.

The top row is the empirical part, and it is **84.6%, not 100%.** Executing a line buys you the *possibility* of detection and nothing more. So:

- **`P(fault detected | line never executed) = 0`** — exact, universal, and therefore real information.
- **`P(fault detected | line executed)` = 84.6%** here, and some other number in your codebase, and never 1.

That asymmetry is the whole correct reading. **Low coverage is hard evidence of a gap. High coverage is evidence of nothing at all.** Coverage bounds your detection from above — it is a *ceiling* — and a team that treats it as a floor to be reached has inverted the only thing the metric is good for. Chase down the uncovered lines, because each one is a guaranteed hole. Then stop, because the covered ones have told you nothing.

The practical corollary is that "we are at 91%" and "we went from 78% to 91%" carry completely different information. The second says somebody read some previously-unread code, which is genuinely useful. The first says nothing whatsoever.

The asymmetry also pays for itself operationally, which is the part to remember when you configure a tool. Because a mutant on an unexecuted line is a *guaranteed* survivor, a mutation runner can read your existing coverage data and skip those mutants without losing any information at all — `mutmut --use-coverage` is precisely this optimisation, and it is free in a way very few optimisations are. Coverage's one true use, "these lines definitely have no tests", turns out to be exactly the input that makes the expensive metric affordable.

### Path explosion: why 100% path coverage is unreachable

If branch coverage is better than line coverage, why not go further and demand every *path* — every distinct route through a function? Because the count is exponential, and the exponent is the number of branches. Enumerated by tracing a function over every input combination:

```text
    branches    2^n predicts         measured        dependent conds    2-test cov
           4              16               16                      9          100% / 100%
           8             256              256                     86          100% / 100%
          10            1024             1024                    265          100% / 100%
```

Ten independent branches is a small function — a validation routine, a fee calculator, an eligibility check. It has **1,024 paths**, and the program confirms all 1,024 are reachable by actually walking them. Meanwhile **two tests** — all conditions true, all conditions false — reach **100% line and 100% branch coverage** and **2 of 1,024 paths, or 0.2%.**

At a generous 1 ms per test, exhausting a 10-branch function takes **1.0 s**; 20 branches takes **17.5 minutes**; 30 branches takes **12.4 days**. One function. And a loop with a branch in its body and no static bound has infinitely many paths, so the criterion is not merely expensive there — it is undefined.

The third column is the honest counterweight. Make each condition depend on the previous one and the 1,024 paths collapse to **265 feasible ones**, because conditions in real code are correlated. That helps the arithmetic and not the conclusion: 265 is still far more tests than anyone writes for one function, and *deciding* which combinations are feasible is itself a program-analysis problem. This is why every practical coverage tool stops at branch, and why the honest position is that **there is no coverage criterion you can max out and then relax**. You need a different kind of measurement.

### Mutation testing: seed the bug and see if anyone notices

The different kind of measurement is thirty years older than most of the tools that ignore it.

DeMillo, Lipton and Sayward, *Hints on Test Data Selection: Help for the Practicing Programmer* (IEEE Computer 11(4), 1978), proposed inverting the question. Instead of asking what your tests touched, **change the program on purpose and ask whether the suite objects.** Take one line, make one small edit — a `<` becomes a `<=` — and run the suite. If some test fails, the mutant is **killed**: your suite can detect that class of fault. If the suite is still green, the mutant **survived**: you have a demonstrated, reproducible fault that ships past your tests. Mutation score is killed ÷ total, and unlike coverage it is a direct measurement of the property you actually want.

Two arguments carry it, and they are both stated in the 1978 paper. The **competent programmer hypothesis**: real programs are written by people who are nearly right, so real faults look like small deviations from a correct program — which is exactly what a mutant is. And the **coupling effect**: a test set that detects simple single-token faults tends also to detect the complex faults built out of them, which is why mutating one token at a time is not as reductive as it sounds. Jia and Harman's survey, *An Analysis and Survey of the Development of Mutation Testing* (IEEE TSE 37(5), 2011), collects three decades of empirical work on both.

The difference in kind is worth stating plainly. Coverage asks a question about your *program* — which lines ran. Mutation testing asks a question about your *suite* — what can it detect. Only one of those is the question you have.

### The six operators that matter for backends

A mutation operator is a rewrite rule over the syntax tree. The engine in this lesson implements six, chosen because they are the six mistakes that actually reach production in backend code:

| operator | rewrite | the real bug it stands for |
|---|---|---|
| **boundary** | `<`↔`<=`, `>`↔`>=` | the off-by-one at a tier, a limit, a page size |
| **conditional negation** | `if C` → `if not C`, `==`↔`!=` | the inverted guard, the flag read backwards |
| **arithmetic** | `+`↔`-`, `*`↔`//` | the wrong operator in a total, a fee, a proration |
| **return value** | `return X` → `return None` | the early return that forgets its result |
| **exception removal** | `raise E` → `pass` | the swallowed failure that becomes a silent success |
| **statement deletion** | `stmt` → `pass` | the line lost in a merge, the missing increment |

Over one 48-line module those six produce **70 mutants — 1.46 per executable line**: 25 deletions, 13 arithmetic, 13 conditional, 9 boundary, 7 return, 3 exception. That density is the number to remember, because it is what makes mutation testing expensive: your cost is `mutants × suite runtime`, and mutants scale with lines of code.

A mutant is not an abstraction. It is a program you could have written, and the engine prints it as one:

```python
# original                          # mutant, operator: boundary, line 42
if remaining < 0:                   if remaining <= 0:
    remaining = 0                       remaining = 0

# original                          # mutant, operator: exception, line 6
if qty < 0:                         if qty < 0:
    raise ValueError(...)               pass
```

Read the second one as a code review comment. "This guard clause no longer raises — does any test notice?" That is the entire question mutation testing asks, seventy times, without getting bored.

One operator behaves differently from the rest and the engine has to handle it. Delete `i = i + 1` from a `while` loop and the mutant never terminates. Real tools apply a wall-clock timeout and classify the mutant as **timed out** — detected, on the reasonable grounds that a suite hanging is a suite noticing. This lesson's engine counts *executed lines* against a fixed budget instead of counting seconds, so the classification is identical but the report is byte-reproducible on any machine. **3 of the 70 mutants time out**, all of them in the one function containing a `while`.

One caution about the number itself before anyone puts it on a dashboard: **a mutation score is not comparable across codebases.** It depends on which operators you enabled, on how many equivalent mutants your particular code happens to admit, and on the shape of the module — a file of thin data classes will score differently from a file of arithmetic for reasons that have nothing to do with test quality. What the score is good for is comparison *against itself over time*, and comparison between two suites over the *same* code. That second use is the next section.

### The divergence: where coverage stops and detection keeps going

Now put the two metrics side by side over five suites of rising quality against the same module. This is the whole lesson in one chart.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 580" width="100%" style="max-width:840px" role="img" aria-label="A line chart over five test suites of increasing quality against the same forty-eight line module. Line coverage, in red, is already at one hundred percent on suite one, the no-assert suite, and stays flat at one hundred percent across all five. Branch coverage, in amber, starts at eighty-seven point five percent and reaches one hundred percent by suite three, then stays flat. The mutation score, in green, starts at zero percent on the no-assert suite and climbs steadily through thirty percent, seventy-eight point six percent, eighty-eight point six percent and ninety-five point seven percent, never flattening. The shaded region between the flat coverage lines and the climbing mutation score is the quality difference that coverage cannot see. A table below gives the exact figures for each suite along with its test count.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Coverage is finished before the suite has started working</text>
    <text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.82">same module, same 70 seeded faults — only the suite changes</text>

    <g fill="none" stroke="currentColor" stroke-width="1.4"><path d="M108 330 L 840 330"/><path d="M108 330 L 108 84"/></g>
    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.28">
      <path d="M108 90 L 840 90"/><path d="M108 150 L 840 150"/><path d="M108 210 L 840 210"/><path d="M108 270 L 840 270"/>
    </g>
    <g fill="currentColor" font-size="8.5" text-anchor="end" opacity="0.72">
      <text x="100" y="93">100%</text><text x="100" y="153">75%</text><text x="100" y="213">50%</text><text x="100" y="273">25%</text><text x="100" y="333">0%</text>
    </g>

    <path d="M140 90 L 300 90 L 460 90 L 620 90 L 780 90 L 780 100.3 L 620 117.4 L 460 141.4 L 300 258 L 140 330 Z" fill="#7f7f7f" fill-opacity="0.13"/>

    <path d="M140 90 L 300 90 L 460 90 L 620 90 L 780 90" fill="none" stroke="#d64545" stroke-width="3.2"/>
    <path d="M140 120 L 300 100.1 L 460 94 L 620 94 L 780 94" fill="none" stroke="#e0930f" stroke-width="2.6" stroke-dasharray="7 4"/>
    <path d="M140 330 L 300 258 L 460 141.4 L 620 117.4 L 780 100.3" fill="none" stroke="#0fa07f" stroke-width="3.2" stroke-linejoin="round"/>

    <g fill="#d64545"><circle cx="140" cy="90" r="4"/><circle cx="300" cy="90" r="4"/><circle cx="460" cy="90" r="4"/><circle cx="620" cy="90" r="4"/><circle cx="780" cy="90" r="4"/></g>
    <g fill="#0fa07f"><circle cx="140" cy="330" r="4"/><circle cx="300" cy="258" r="4"/><circle cx="460" cy="141.4" r="4"/><circle cx="620" cy="117.4" r="4"/><circle cx="780" cy="100.3" r="4"/></g>

    <g fill="currentColor" font-size="9" text-anchor="middle">
      <text x="140" y="350">suite 1</text><text x="300" y="350">suite 2</text><text x="460" y="350">suite 3</text><text x="620" y="350">suite 4</text><text x="780" y="350">suite 5</text>
    </g>
    <g fill="currentColor" font-size="8" text-anchor="middle" opacity="0.72">
      <text x="140" y="364">no asserts</text><text x="300" y="364">smoke</text><text x="460" y="364">values</text><text x="620" y="364">+ errors</text><text x="780" y="364">+ boundaries</text>
      <text x="140" y="376">6 tests</text><text x="300" y="376">6 tests</text><text x="460" y="376">13 tests</text><text x="620" y="376">18 tests</text><text x="780" y="376">26 tests</text>
    </g>

    <g font-size="10" font-weight="700">
      <text x="150" y="80" fill="#d64545">line coverage — 100.0% on every suite, from the first one</text>
      <text x="150" y="132" fill="#e0930f">branch coverage — done by suite 3</text>
      <text x="330" y="300" fill="#0fa07f">mutation score — still climbing at suite 5</text>
    </g>
    <text x="470" y="230" font-size="10" font-weight="700" fill="currentColor" opacity="0.75">everything in this shaded region</text>
    <text x="470" y="244" font-size="10" font-weight="700" fill="currentColor" opacity="0.75">is quality your gate cannot see</text>

    <rect x="24" y="392" width="832" height="126" rx="9" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4"/>
    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="40" y="410">THE SUITE</text><text x="430" y="410">TESTS</text><text x="530" y="410">LINE</text><text x="640" y="410">BRANCH</text><text x="760" y="410">MUTATION</text>
    </g>
    <path d="M32 416 L 848 416" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.4"/>
    <g fill="currentColor" font-size="9.5">
      <text x="40" y="434">1 · calls everything, asserts nothing</text><text x="430" y="434">6</text><text x="530" y="434" fill="#d64545" font-weight="700">100.0%</text><text x="640" y="434" fill="#e0930f">87.5%</text><text x="760" y="434" fill="#0fa07f" font-weight="700">0.0%</text>
      <text x="40" y="452">2 · smoke: a value came back</text><text x="430" y="452">6</text><text x="530" y="452" fill="#d64545" font-weight="700">100.0%</text><text x="640" y="452" fill="#e0930f">95.8%</text><text x="760" y="452" fill="#0fa07f" font-weight="700">30.0%</text>
      <text x="40" y="470">3 · + happy-path values</text><text x="430" y="470">13</text><text x="530" y="470" fill="#d64545" font-weight="700">100.0%</text><text x="640" y="470" fill="#e0930f">100.0%</text><text x="760" y="470" fill="#0fa07f" font-weight="700">78.6%</text>
      <text x="40" y="488">4 · + error paths</text><text x="430" y="488">18</text><text x="530" y="488" fill="#d64545" font-weight="700">100.0%</text><text x="640" y="488" fill="#e0930f">100.0%</text><text x="760" y="488" fill="#0fa07f" font-weight="700">88.6%</text>
      <text x="40" y="506">5 · + boundary cases</text><text x="430" y="506">26</text><text x="530" y="506" fill="#d64545" font-weight="700">100.0%</text><text x="640" y="506" fill="#e0930f">100.0%</text><text x="760" y="506" fill="#0fa07f" font-weight="700">95.7%</text>
    </g>

    <text x="440" y="548" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">Suites 3, 4 and 5 are identical on both coverage metrics. They detect 78.6%, 88.6% and 95.7%.</text>
    <text x="440" y="568" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.88">The 13 tests that separate suite 3 from suite 5 are worth 17 points of detection and exactly zero points of coverage.</text>
  </g>
</svg>
```

Read the three curves as one story. **Line coverage is at its maximum on the first suite and never moves.** Branch coverage does slightly better — it separates suite 1 from suite 2 from suite 3 — and is then also finished, at suite 3 of 5. **The mutation score has not stopped climbing when the chart runs out of suites.**

The sharpest way to say it is with the last three rows. Suites 3, 4 and 5 are *indistinguishable* on both coverage metrics: 100.0% line, 100.0% branch, all three. They detect **78.6%, 88.6% and 95.7%** of the same seeded faults. The 13 tests that separate suite 3 from suite 5 — the error-path assertions and the boundary cases — are worth **17 points of detection and precisely zero points of coverage.** If your gate is a coverage number, those thirteen tests are, from the gate's point of view, waste.

And look at suite 2, which is the one most real suites resemble. It asserts something — `isinstance(result, int)` — so it is not the degenerate case. It scores **95.8% branch coverage and 30.0% detection**. Asserting that *a* value came back rather than *the* value catches 3 faults in 10.

### Equivalent mutants: the ceiling nobody can reach

Mutation testing has one honest, permanent limitation, and any tool or lesson that skips it is selling something. **Some mutants do not change what the program computes.** They are syntactically different and semantically identical, so no test can kill them, because there is nothing to detect. These are **equivalent mutants**, and they put the achievable score below 100%.

Deciding whether a given mutant is equivalent reduces to deciding whether two programs compute the same function, which is undecidable in general — Jia and Harman treat it as the central open problem of the field (IEEE TSE 37(5), 2011). What you *can* do is decide it on a finite input set. The program builds **302 probe calls** spanning every function and runs both the original and each survivor over all of them:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 512" width="100%" style="max-width:840px" role="img" aria-label="A survivor-triage diagram. Seventy mutants are generated; the best suite kills sixty-four, three time out, and three survive. Each survivor is run against three hundred and two probe calls alongside the original program. Survivors that some probe distinguishes are genuine test gaps and go on a work list; survivors that no probe distinguishes are equivalent-mutant candidates and are read by hand. The measured table shows that suite three left fifteen survivors, of which three were indistinguishable and twelve were real gaps, while suite five left three survivors, all three indistinguishable and no real gaps. The three equivalents are listed with a hand-written reason each, and the achievable ceiling on this module is ninety-five point seven percent rather than one hundred percent.">
  <defs>
    <marker id="p12-13-d-g" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p12-13-d-r" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#d64545"/></marker>
    <marker id="p12-13-d-n" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#7f7f7f"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">A survivor is either a hole in your suite or a mutant no test could kill</text>

    <rect x="24" y="50" width="150" height="46" rx="8" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff" stroke-width="1.8"/>
    <text x="99" y="70" text-anchor="middle" font-size="10.5" font-weight="700" fill="#7c5cff">70 mutants</text>
    <text x="99" y="86" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">6 operators, 48 lines</text>

    <path d="M174 73 L 236 73" fill="none" stroke="#7f7f7f" stroke-width="1.8" marker-end="url(#p12-13-d-n)"/>
    <rect x="240" y="50" width="150" height="46" rx="8" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff" stroke-width="1.8"/>
    <text x="315" y="70" text-anchor="middle" font-size="10.5" font-weight="700" fill="#3553ff">run the suite</text>
    <text x="315" y="86" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">26 tests, once per mutant</text>

    <path d="M390 62 L 452 62" fill="none" stroke="#0fa07f" stroke-width="1.8" marker-end="url(#p12-13-d-g)"/>
    <path d="M390 84 L 452 84" fill="none" stroke="#d64545" stroke-width="1.8" marker-end="url(#p12-13-d-r)"/>
    <rect x="456" y="42" width="188" height="26" rx="6" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f" stroke-width="1.6"/>
    <text x="550" y="59" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">64 killed + 3 timed out</text>
    <rect x="456" y="76" width="188" height="26" rx="6" fill="#d64545" fill-opacity="0.13" stroke="#d64545" stroke-width="1.6"/>
    <text x="550" y="93" text-anchor="middle" font-size="9.5" font-weight="700" fill="#d64545">3 survived</text>

    <path d="M644 89 L 700 89" fill="none" stroke="#d64545" stroke-width="1.8" marker-end="url(#p12-13-d-r)"/>
    <rect x="704" y="66" width="152" height="46" rx="8" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f" stroke-width="1.8"/>
    <text x="780" y="86" text-anchor="middle" font-size="10" font-weight="700" fill="#e0930f">302 probe calls</text>
    <text x="780" y="102" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">original vs each survivor</text>

    <g fill="none" stroke="#7f7f7f" stroke-width="1.7">
      <path d="M746 112 C 746 138, 300 138, 300 162" marker-end="url(#p12-13-d-n)"/>
      <path d="M814 112 C 814 138, 660 138, 660 162" marker-end="url(#p12-13-d-n)"/>
    </g>
    <rect x="150" y="164" width="300" height="52" rx="8" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="1.6"/>
    <text x="300" y="184" text-anchor="middle" font-size="10.5" font-weight="700" fill="#d64545">some probe separates them</text>
    <text x="300" y="201" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.9">a genuine test gap — write the missing assertion</text>
    <rect x="510" y="164" width="300" height="52" rx="8" fill="#7f7f7f" fill-opacity="0.11" stroke="#7f7f7f" stroke-width="1.6"/>
    <text x="660" y="184" text-anchor="middle" font-size="10.5" font-weight="700" fill="currentColor">no probe separates them</text>
    <text x="660" y="201" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.9">an equivalence candidate — read it, then ignore it</text>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="40" y="248">RUN THE TRIAGE ON TWO SUITES</text><text x="460" y="248">SURVIVORS</text><text x="600" y="248">INDISTINGUISHABLE</text><text x="790" y="248">REAL GAPS</text>
    </g>
    <path d="M32 254 L 848 254" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.4"/>
    <g fill="currentColor" font-size="10">
      <text x="40" y="274">suite 3 — happy-path values, 78.6%</text><text x="460" y="274" font-weight="700">15</text><text x="600" y="274" font-weight="700">3</text><text x="790" y="274" font-weight="700" fill="#d64545">12</text>
      <text x="40" y="294">suite 5 — + boundaries, 95.7%</text><text x="460" y="294" font-weight="700">3</text><text x="600" y="294" font-weight="700">3</text><text x="790" y="294" font-weight="700" fill="#0fa07f">0</text>
    </g>

    <rect x="24" y="312" width="832" height="112" rx="9" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4"/>
    <text x="40" y="332" font-size="10" font-weight="700" fill="currentColor">the three equivalents, each read by hand — this part does not automate:</text>
    <g font-size="9.5" fill="currentColor">
      <text x="40" y="354" font-weight="700" fill="#e0930f">pct &gt; 20  →  pct &gt;= 20</text><text x="330" y="354" opacity="0.9">pct only ever takes 0/5/8/13/15/23 — never exactly 20</text>
      <text x="40" y="376" font-weight="700" fill="#e0930f">return total_cents  →  pass</text><text x="330" y="376" opacity="0.9">a fast path the loop below already computes correctly</text>
      <text x="40" y="398" font-weight="700" fill="#e0930f">remaining &lt; 0  →  remaining &lt;= 0</text><text x="330" y="398" opacity="0.9">setting remaining to 0 when it is already 0 is a no-op</text>
    </g>

    <text x="440" y="452" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">The ceiling on this module is 95.7%, not 100%. The best suite reaches exactly 95.7%.</text>
    <text x="440" y="472" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.88">A probe set proves a mutant killable. It can never prove one equivalent — that reduces to program equivalence.</text>
    <text x="440" y="492" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">Jia &amp; Harman, An Analysis and Survey of the Development of Mutation Testing, IEEE TSE 37(5), 2011.</text>
  </g>
</svg>
```

The triage table is how you use this at a desk. Against suite 3, **15 mutants survive: 12 are separated by some probe and 3 are not.** Those 12 are a work list — each is a concrete input on which the mutant and the original disagree and no test noticed, which means each comes with its own failing test case already written for you. Against suite 5, **3 survive and all 3 are indistinguishable**, so the work list is empty and the score is at its ceiling.

Note carefully what the probe set can and cannot establish. A probe that separates a mutant from the original **proves** the mutant is killable. No number of probes can prove the reverse; 302 agreements is evidence, not a theorem. The three candidates here were then read by hand, one at a time, and each turns out to be genuinely equivalent for a different reason. The clearest:

```python
def apply_credits(total_cents, credits):
    if not credits:
        return total_cents      # <- statement-deletion mutant deletes this
    remaining = total_cents
    for c in credits:
        remaining = remaining - c
        ...
    return remaining
```

Delete that early return and the empty-`credits` case falls through to a loop that does not execute and returns `total_cents` anyway. The mutant computes the same function on every input in its domain. **No test can kill it because there is nothing to detect** — and note what it is: a redundant fast path, which is to say a small piece of dead optimisation the mutation run has just found for you. That is the useful secondary product of the technique.

So: **the achievable ceiling here is 95.7%, not 100%**, and the best suite reaches exactly 95.7%. Set a mutation threshold at 100% and you have set a target that is provably unreachable and will be met by deleting the mutants people find annoying.

### Goodhart, and what to gate on instead

The last measurement is the one that should decide your CI configuration. Take a fixed pool of candidate tests and a fixed budget of eight, and let two teams pick — one maximising coverage, one maximising detection:

```text
    a team that optimises for line coverage    (8 tests)
      line coverage   100.0%      branch 100.0%      mutation score  52.9%
      assertion-free tests it chose: 6 of 8
    a team that optimises for mutants killed   (8 tests)
      line coverage   100.0%      branch 100.0%      mutation score  95.7%
      assertion-free tests it chose: 0 of 8
```

Both suites report **100.0% line and 100.0% branch coverage**. They are indistinguishable to any gate you can configure. One detects **52.9%** of the seeded faults and the other **95.7%**. The coverage-maximising team filled **6 of its 8 slots with assertion-free tests**, and it was right to by its own objective: an assertion-free test that loops over a wide input grid touches more lines per test than a focused boundary test does.

This is Goodhart's law with the numbers attached (Goodhart, *Problems of Monetary Management: The U.K. Experience*, 1975): when a measure becomes a target, it ceases to be a good measure. The damage is not that the coverage target fails to improve quality. It is that **the target actively pays** — in authoring time, in review time, in CI minutes, in maintenance forever — for the tests that have none.

The gates that follow from all of this are specific:

- **Do not gate on total coverage.** It is dominated by code written years ago and it moves too slowly to mean anything about today's change.
- **Do gate on coverage of the *changed lines*** — 100% or close, on the diff only. This uses coverage for the one thing it is valid for: an uncovered new line is definitely untested, and it is right there in the review.
- **Do gate on a mutation score for the modules that matter**, on the diff, in the pull request; run the whole repo nightly. Set the threshold from a measured baseline, never at 100%.
- **Never let a coverage number fall silently.** The delta is information; the level is not.

Those four rules have a shape, and the shape is decided by cost. Mutation testing costs `mutants × suite runtime`, and the program measures mutants at **1.46 per executable line**, so the same technique is a five-minute pull-request gate or an eighteen-hour job depending only on how many lines you point it at:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 476" width="100%" style="max-width:840px" role="img" aria-label="A diagram placing each quality gate in the right stage of a pipeline, sized by its measured cost. In the pull request: the full test suite with branch coverage, diff-cover with fail-under one hundred on changed lines only, and mutation testing on the diff, which at eighty-eight mutants costs five point five minutes on eight workers and blocks the merge. On main: the full suite and total coverage recorded but not gated. Nightly: mutation testing on the two or three highest-consequence modules, one thousand one hundred and sixty-seven mutants and one point two hours, which alerts but does not block. The thing never to do is mutate the whole repository in a pull request: seventeen thousand five hundred mutants and eighteen point two hours. A measured table below compares whole-module mutation at seventy mutants and one thousand eight hundred and twenty test executions against changed-lines-only at twenty-eight mutants and seven hundred and twenty-eight, a two point five times saving.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Same technique, three stages, three costs. Only one of them blocks a merge.</text>
    <text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.82">sized from the measured density: 1.46 mutants per executable line, 30 s suite, 8 workers</text>

    <rect x="24" y="60" width="264" height="150" rx="10" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff" stroke-width="1.9"/>
    <rect x="308" y="60" width="264" height="150" rx="10" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff" stroke-width="1.9"/>
    <rect x="592" y="60" width="264" height="150" rx="10" fill="#e0930f" fill-opacity="0.11" stroke="#e0930f" stroke-width="1.9"/>

    <g font-size="11" font-weight="700" text-anchor="middle">
      <text x="156" y="82" fill="#3553ff">IN THE PULL REQUEST</text><text x="440" y="82" fill="#7c5cff">ON MAIN</text><text x="724" y="82" fill="#e0930f">NIGHTLY</text>
    </g>
    <g font-size="9" fill="currentColor" opacity="0.92">
      <text x="40" y="104">pytest --cov=app --cov-branch</text>
      <text x="40" y="120">diff-cover --fail-under=100</text>
      <text x="40" y="136">mutmut on the changed lines</text>
      <text x="40" y="152" font-weight="700">88 mutants on a 60-line diff</text>
      <text x="324" y="104">the full suite, branch coverage</text>
      <text x="324" y="120">record the total, do not gate on it</text>
      <text x="324" y="136">alert on a fall, never on a level</text>
      <text x="324" y="152" font-weight="700">the suite, once</text>
      <text x="608" y="104">mutmut --paths-to-mutate</text>
      <text x="608" y="120">the 2-3 modules that move money</text>
      <text x="608" y="136">--use-coverage to skip dead mutants</text>
      <text x="608" y="152" font-weight="700">1,167 mutants on one module</text>
    </g>
    <g font-size="10.5" font-weight="700">
      <text x="40" y="176" fill="currentColor">cost: 5.5 minutes</text><text x="324" y="176" fill="currentColor">cost: the suite</text><text x="608" y="176" fill="currentColor">cost: 1.2 hours</text>
    </g>
    <rect x="40" y="186" width="94" height="16" rx="4" fill="#0fa07f" fill-opacity="0.25" stroke="#0fa07f" stroke-width="1.3"/>
    <text x="87" y="198" text-anchor="middle" font-size="8.5" font-weight="700" fill="#0fa07f">BLOCKING</text>
    <rect x="324" y="186" width="94" height="16" rx="4" fill="#7f7f7f" fill-opacity="0.22" stroke="#7f7f7f" stroke-width="1.3"/>
    <text x="371" y="198" text-anchor="middle" font-size="8.5" font-weight="700" fill="currentColor">TRACKED</text>
    <rect x="608" y="186" width="94" height="16" rx="4" fill="#e0930f" fill-opacity="0.25" stroke="#e0930f" stroke-width="1.3"/>
    <text x="655" y="198" text-anchor="middle" font-size="8.5" font-weight="700" fill="#e0930f">ALERTS</text>

    <rect x="24" y="224" width="832" height="42" rx="9" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="1.6" stroke-dasharray="7 4"/>
    <text x="44" y="242" font-size="10.5" font-weight="700" fill="#d64545">the one that kills the adoption:</text>
    <text x="290" y="242" font-size="10" fill="currentColor" opacity="0.92">mutating the whole repository inside a pull request</text>
    <text x="44" y="258" font-size="9" fill="currentColor" opacity="0.85">a 12,000-line service at 1.46 mutants per line = 17,500 mutants x a 30 s suite / 8 workers</text>
    <text x="700" y="258" font-size="11" font-weight="700" fill="#d64545">= 18.2 hours</text>

    <rect x="24" y="282" width="832" height="94" rx="9" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4"/>
    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="40" y="302">MEASURED ON THIS LESSON'S MODULE</text><text x="430" y="302">MUTANTS</text><text x="560" y="302">TEST EXECUTIONS</text><text x="760" y="302">SCORE</text>
    </g>
    <path d="M32 308 L 848 308" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.4"/>
    <g fill="currentColor" font-size="10">
      <text x="40" y="328">the whole module — 48 executable lines</text><text x="430" y="328" font-weight="700">70</text><text x="560" y="328" font-weight="700">1,820</text><text x="760" y="328" font-weight="700">95.7%</text>
      <text x="40" y="348">the changed lines only — 20 of 48</text><text x="430" y="348" font-weight="700" fill="#0fa07f">28</text><text x="560" y="348" font-weight="700" fill="#0fa07f">728</text><text x="760" y="348" font-weight="700">92.9%</text>
      <text x="40" y="368" font-weight="700">saving</text><text x="430" y="368" font-weight="700" fill="#0fa07f">2.5x</text><text x="560" y="368" font-weight="700" fill="#0fa07f">2.5x</text><text x="640" y="368" font-size="9" opacity="0.75">the score that applies to your change</text>
    </g>

    <text x="440" y="404" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">Cost = mutants x suite runtime, and mutants scale with lines. That is the whole design constraint.</text>
    <text x="440" y="424" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.88">--use-coverage skips mutants on unexecuted lines. They are guaranteed to survive, so running them buys nothing.</text>
    <text x="440" y="446" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.88">Coverage of changed lines is the only coverage gate with a defensible answer, and the answer is 100%.</text>
    <text x="440" y="466" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.7">Goodhart, Problems of Monetary Management: The U.K. Experience, 1975 — the reason the total-coverage gate is deleted, not lowered.</text>
  </g>
</svg>
```

Two details in that figure are worth keeping. The `--use-coverage` line is the ceiling asymmetry paying for itself: mutants sited on lines no test executes are **guaranteed** survivors, measured at 0 of 5 killed, so skipping them costs no information and buys real time. And the reason the total-coverage gate is *deleted* rather than lowered is that a lowered gate still names a number, and any named number is a target.

## Build It

`code/coverage_mutation.py` is one file, standard library only, no network, and it runs in a few seconds. Nine numbered sections map onto the nine concepts above. Two of them are built from scratch and both genuinely work.

**The coverage tracer is about eighty lines and there is no magic in it.** `sys.settrace` installs a *global* trace function that Python calls once per frame creation; return a *local* trace function from it and Python calls that on every line executed in that frame. Filter on `co_filename` and you see the module under test and nothing else:

```python
def _global(self, frame, event, arg):
    if frame.f_code.co_filename != self.path:
        return None
    return self._local([None])
```

Line coverage needs only the set of lines seen. **Branch coverage needs arcs** — ordered `(from_line, to_line)` pairs. An `if` at line `L` whose body starts at line `B` took the true outcome exactly when the arc `(L → B)` was observed, and took the false outcome when any arc `(L → something else)` was. A frame that returns emits no further line event, so a `return` event has to record an arc to a sentinel or a false outcome at the end of a function is invisible:

```python
if event == "line":
    line = self.fold(frame.f_lineno)
    if line != prev[0]:
        if prev[0] is not None:
            self.arcs.add((prev[0], line))
    self.lines.add(line)
    prev[0] = line
elif event == "return" and prev[0] is not None:
    self.arcs.add((prev[0], -1))
```

That `self.fold` is a correctness detail a naive tracer gets wrong, and it matters more here than anywhere else in this curriculum. **`frame.f_lineno` is not a stable identifier for a statement.** CPython has changed which physical line it attributes an event to when a statement spans several of them, so a raw tally of `f_lineno` values measures the interpreter as well as the program — and a lesson arguing that coverage is not what you think it is cannot ship a coverage percentage that depends on your Python version. The fix is to fold every event down onto the first line of its enclosing statement, taken from the AST:

```python
def fold(self, lineno: int) -> int:
    i = bisect.bisect_right(self.starts, lineno) - 1
    return self.starts[i] if i >= 0 else lineno
```

The source decides the unit, not the runtime. The denominator comes from the same place — an AST walk collecting statement lines inside function bodies, and the two-way decisions (`if`, `elif`, `while`) that make up the branch denominator. That AST walk plus that trace function is, in outline, the entire product that is `coverage.py`.

**The mutation engine is about a hundred and fifty lines and its only subtlety is index stability.** Sites are enumerated once over a fresh tree; to build mutant *k* you re-parse, re-enumerate, and apply the *k*-th site's closure — so the ordering has to be identical every time, which is why the site list is sorted on `(lineno, col, operator, before, after)` rather than left in traversal order:

```python
def build_mutant(source: str, index: int) -> Tuple[ast.Module, Site]:
    tree = ast.parse(source)
    sites = mutation_sites(tree)
    site = sites[index]
    site.apply()
    return tree, site
```

The enumeration itself has one trap worth naming because it silently doubles your mutant count. Walking each statement with `ast.walk` finds the expressions of *nested* statements too, so a `Compare` inside an `if` inside a `for` gets discovered three times — once per enclosing compound statement. The fix is a walk that yields a statement's own expressions and refuses to descend into nested statements, which are enumerated in their own right:

```python
for fieldname, value in ast.iter_fields(st):
    if fieldname in ("body", "orelse", "finalbody", "handlers"):
        continue
```

A mutant is killed when a test that passed on the original now fails. Comparing against a **baseline** rather than counting failures is not optional: a suite that is already red would otherwise score a free kill on every mutant.

The last piece is the timeout. A deleted increment inside a `while` produces a mutant that never terminates, and real tools kill it on a wall clock. That would make this program's output different on every machine, so the budget counts *executed lines* instead — same classification, byte-identical report:

```python
def local(frame, event, arg):
    if event == "line":
        steps[0] += 1
        if steps[0] > limit:
            raise BudgetExceeded()
    return local
```

Run it:

```bash
python3 phases/12-testing-and-quality/13-coverage-and-mutation-testing/code/coverage_mutation.py
```

```console
== 1 · THE NO-ASSERT SUITE: 100% LINE COVERAGE, 0% DETECTION ==
  the module under test: 6 functions, 48 executable lines, 12 two-way branches.

    tests                     6
    tests passing             6/6
    assertions in the suite   0
    line coverage             48/48   100.0%
    branch coverage           21/24    87.5%
    mutants killed            0/70     0.0%

  A CI gate of 'fail_under = 90' passes this suite. It detects nothing.

== 3 · COVERAGE IS A CEILING, NOT A FLOOR ==
  a perfectly ordinary suite: 8 tests, line coverage  89.6% (43/48).

    mutants sited on...        count   killed   kill rate
    a line the suite ran          65       55    84.6%
    a line it did not run          5        0     0.0%

== 5 · THE MUTATION ENGINE: SIX OPERATORS OVER ONE MODULE ==
  70 mutants from 48 executable lines (1.46 per line):

    operator      mutants   example
    arithmetic         13   L13  +  ->  -
    boundary            9   L5  <  ->  <=
    conditional        13   L5  qty < 0  ->  not (qty < 0)
    deletion           25   L7  pct = 0  ->  pass
    exception           3   L6  raise ValueError('qty must be non-negative')  ->  pass
    return              7   L16  return pct  ->  return None

  the best suite (26 tests) against all 70 mutants:
    killed      64
    timeout      3   (a non-terminating mutant: also detected)
    survived     3   <- the suite cannot tell these from the original
    mutation score   95.7%

== 6 · THE DIVERGENCE: FIVE SUITES, THREE METRICS ==
    suite                                tests   line     branch   mutation
    1 calls everything, asserts nothing      6   100.0%    87.5%     0.0%
    2 smoke: a value came back               6   100.0%    95.8%    30.0%
    3 + happy-path values                   13   100.0%   100.0%    78.6%
    4 + error paths                         18   100.0%   100.0%    88.6%
    5 + boundary cases                      26   100.0%   100.0%    95.7%

== 9 · COST: FULL-MODULE VERSUS DIFF-ONLY MUTATION ==
    scope             mutants   suite runs   test executions   score
    whole module           70           70              1820    95.7%
    changed lines          28           28               728    92.9%
    ratio                2.5x         2.5x              2.5x

    measured mutant density                 1.46 per executable line
    a 12,000-line service     17500 mutants  x 30 s suite / 8 workers = 18.2 hours
    one 800-line module        1167 mutants  x 30 s suite / 8 workers = 1.2 hours
    a 60-line pull request       88 mutants  x 30 s suite / 8 workers = 5.5 minutes
```

That last section is the one that decides where mutation testing runs. Cost is reported in **test executions** rather than seconds precisely so two runs produce identical output, but the arithmetic transfers unchanged: the cost of a mutation run is `mutants × suite runtime`, and the measured density says mutants ≈ **1.46 × executable lines**. Project that onto a real service at a 30-second suite and eight parallel workers and you get **18.2 hours for 12,000 lines, 1.2 hours for one module, and 5.5 minutes for a 60-line pull request.** Those three numbers are three different jobs in three different places, and only the last one belongs in a gate.

## Use It

Nothing above needs to be hand-rolled in production. Two mature tools do it, and the flags that matter are few.

**`coverage.py`** is the measurement. Turn on branches — it is off by default and it is the single most valuable setting here:

```toml
# pyproject.toml
[tool.coverage.run]
branch = true                       # measures decisions, not statements
source = ["app"]
parallel = true                     # one data file per worker, for pytest-xdist
omit = ["*/migrations/*", "*/__main__.py"]

[tool.coverage.report]
fail_under = 0                      # deliberately: gate on the diff, not the total
show_missing = true
exclude_also = ["if TYPE_CHECKING:", "raise NotImplementedError", "@overload"]
```

Run it as `pytest --cov=app --cov-branch` (the `pytest-cov` plugin) or `coverage run -m pytest` directly. With `parallel = true` you must `coverage combine` before reporting, and forgetting that is the classic cause of a coverage number that mysteriously drops when you turn on `-n auto`.

`# pragma: no cover` is honest in exactly three situations: a branch that only executes on a platform you do not test on, a defensive `assert_never`-style unreachable case, and a `if __name__ == "__main__"` block. It is dishonest everywhere else, and the tell is a pragma on a line containing business logic. Prefer `exclude_also` patterns in config over scattered pragmas, because a pattern is reviewable in one place.

**`diff-cover`** is what turns coverage into a gate worth having:

```bash
coverage xml
diff-cover coverage.xml --compare-branch=origin/main --fail-under=100
```

That fails the build when a *newly added or modified* line is not covered, which is the one coverage question with a defensible answer. Set it to 100 and it is achievable, because you are only ever talking about the lines in front of you. `diff-cover` also emits an HTML report showing the uncovered new lines inline in the diff, which is the form a reviewer can act on.

**`mutmut`** is the mutation runner to reach for first in Python. It is genuinely usable and its defaults are close to right:

```bash
mutmut run --paths-to-mutate app/pricing/ --tests-dir tests/unit/ --use-coverage
mutmut results
mutmut show 47          # the diff for one survivor
mutmut apply 47         # apply it locally to write the test that kills it
```

Three flags carry the tool. `--paths-to-mutate` is not optional at any real scale — mutating your whole repository is the 18-hour job above. `--use-coverage` reads an existing `.coverage` file and skips mutants on lines no test executes, which is a free and large speedup that follows directly from the ceiling asymmetry: those mutants are guaranteed to survive, so running them buys nothing. And `mutmut` caches results per mutant in `.mutmut-cache`, so incremental runs after a small change are fast; put that cache in your CI cache, not in `.gitignore`-oblivion.

**`cosmic-ray`** is the alternative when you need control: an explicit TOML config, a pluggable operator set, distributed execution, and a session database you can query. It is more setup and it is what you want when mutation testing becomes a standing part of your process rather than an experiment. **Stryker** is the cross-language reference implementation — JavaScript/TypeScript, C#, Scala — and its documentation on operators and on mutation-score thresholds is the best in the field regardless of which language you work in.

Two operational cautions, both measured above. **Set your threshold from a baseline, never from 100** — the equivalent-mutant rate here was 4.3% of all mutants and it will be different in your code, so measure it once and set the bar under it. And **timeouts need a real value**: `mutmut` derives one from your baseline suite runtime, which breaks when your suite time is dominated by a fixture that a mutant can make slow. Pin it if your survivor list starts filling with timeouts.

**What to actually pick**, in order:

1. **`branch = true` today.** It costs nothing and it is strictly more information. Measured: it separated three of the five suites where line coverage separated none.
2. **`diff-cover --fail-under=100` as the only coverage gate.** Delete `fail_under` on the total. The number you were gating on was dominated by code nobody has touched in a year.
3. **`mutmut --paths-to-mutate` on your two or three highest-consequence modules**, in a nightly job, with the score tracked over time. Pricing, auth, permissions, anything that moves money or decides access.
4. **Mutation on the diff in the pull request** once the nightly is stable. Measured at 1.46 mutants per changed line, a 60-line diff is 88 mutants and about five minutes on eight workers — a gate you can actually keep.
5. **Read your survivors.** This is the part that is not automatable and it is where the value is. Each survivor is either a missing assertion — with the failing input handed to you — or a piece of code that does not need to exist.

## Think about it

1. The eight-test suite in section 3 killed **0 of 5** mutants on lines it never ran and **55 of 65** on lines it did. Suppose you could improve only one of those two numbers, and improving the first means writing tests for the uncovered lines while improving the second means strengthening assertions on lines already covered. Which do you do first, and what property of your codebase decides the answer?
2. Suite 2 asserted `isinstance(result, int)` and scored **95.8% branch coverage with 30.0% detection**. Take a real test file you have written and classify each assertion as "constrains the value" or "constrains the type/shape". What fraction is the second kind, and which of those could be strengthened without making the test brittle?
3. Both teams in section 8 reported **100.0% line and 100.0% branch coverage** at eight tests, detecting 52.9% and 95.7%. Your organisation will not fund mutation testing. Design a *review* practice — something a human does on a pull request in under two minutes — that distinguishes those two suites, and say what it would miss.
4. The equivalent mutant `pct > 20 → pct >= 20` is unkillable because `pct` never takes the value 20 on any input. That is a fact about the *reachable value set*, not about the syntax. What does its existence tell you about the `if pct > 20` clamp itself, and would you change the code?
5. Diff-only mutation ran **28 mutants against 70** and reported **92.9% against the module's 95.7%**. Construct a change where the diff-only score is high and the module-wide score would have fallen — a change whose damage is entirely outside the lines it touches. What kind of gate catches that one?

## Key takeaways

- **A suite with zero assertions reaches the ceiling of the metric.** Six tests calling every function and asserting nothing measured **100.0% line coverage (48/48)** and **87.5% branch coverage** while killing **0 of 70** seeded faults. Coverage and detection are independent quantities, and this is the existence proof.
- **Coverage is a ceiling, not a floor.** `P(fault detected | line never ran) = 0` exactly and universally; `P(fault detected | line ran)` measured **84.6%**, and never 1. An uncovered line is hard evidence of a gap. A covered line is evidence of nothing. Chase the uncovered ones and stop there.
- **An `if` with no `else` is free in line coverage.** One test over a six-line shipping function scored **6/6 lines (100.0%) and 2/4 branches (50.0%)**. Backend code is mostly guard clauses and early returns, so line coverage is blindest exactly where backend code is densest. Turn on `--branch`.
- **Coverage saturates long before a suite is good.** Across five suites, line coverage was maxed on the *first* and branch coverage by the third, while the mutation score ran **0% → 30.0% → 78.6% → 88.6% → 95.7%**. Suites 3, 4 and 5 are identical on both coverage metrics and detect 17 points apart.
- **A coverage target buys assertion-free tests.** Two eight-test suites, both at **100.0% line and 100.0% branch**, detected **52.9%** and **95.7%**. The coverage-maximising one filled **6 of 8** slots with tests that assert nothing — correctly, by its own objective, because a broad no-assert loop touches more lines per test than a boundary case does.
- **100% path coverage is not merely expensive; it is unreachable.** A 10-branch function has **1,024 paths**, all confirmed reachable by tracing, and two tests give **100% line and 100% branch and 0.2% of paths**. At 1 ms per test, 20 branches is 17.5 minutes and 30 branches is 12.4 days — for one function.
- **Mutation score measures the suite, not the program.** Six operators over 48 lines produced **70 mutants at 1.46 per line**; the best suite killed 64, timed out 3, and left 3. Boundary and statement-deletion mutants were the only survivors — the off-by-one and the missing line are exactly the faults a value-blind suite cannot see.
- **A 100% mutation score is not attainable and should not be a target.** Three survivors were indistinguishable from the original across **302 probe calls** and each was then confirmed equivalent by hand, putting the ceiling at **95.7%**. Deciding equivalence in general reduces to program equivalence and is undecidable; a probe set can prove a mutant killable but never prove one equivalent.
- **Gate on the diff, run the repo nightly.** At the measured density, a 12,000-line service is **18.2 hours** of mutation and a 60-line pull request is **5.5 minutes** on the same hardware. Use `diff-cover --fail-under=100` for changed-line coverage, `mutmut --paths-to-mutate --use-coverage` nightly on the modules that move money, and read every survivor.

Next: [Chaos Engineering & Testing in Production](../14-chaos-engineering-and-testing-in-production/) — what to do about the failure modes that no seeded fault in a source file can represent, because they only exist when the system is running.
