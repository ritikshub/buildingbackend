# Flaky Tests: The Trust Arithmetic

> A 0.2% per-test flake rate sounds like a rounding error. At 3,000 tests it means a clean commit comes back green **0.25% of the time** — the suite is red 99.75% of the time and nobody wrote a bug. Then it gets worse, because the arithmetic is not the interesting part: measured here, a red build in that suite carries **0.003 bits** of evidence about whether a real bug exists, against 4.32 bits in a deterministic one, and an engineer who learns that stops investigating. Effective suite power fell **87.5% → 16.2%** without a single test being edited. And the standard fix makes it worse in the one way that matters: blanket `--reruns 2` left **2 of 6 genuine product races completely undiscovered after 100 days** while making the build look healthier than ever.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Determinism: Time, Randomness, IDs & Order](../08-determinism-time-randomness-order/), [CI/CD: From Commit to Artifact to Environment](../../10-infrastructure-and-deployment/10-ci-cd-pipelines/)
**Time:** ~70 minutes

## The Problem

It is 16:12 on a Thursday and the deploy train leaves at 17:00.

Your change is four lines in a currency formatter. CI has been running for eleven minutes. It comes back red: `test_webhook_delivery_retries_on_502` failed in the `integration` job, worker `gw3`, and the assertion is a timeout waiting for a queue depth to reach zero. Your change does not touch webhooks, or queues, or retries. It touches a formatter.

You do what everyone does. You click **Re-run failed jobs**. Eleven more minutes. It goes green. You merge at 16:38, twenty-two minutes before the train, and you feel mildly annoyed rather than alarmed, because this is Thursday and this is what Thursday is like.

Here is what that twenty-two minutes actually contained, and none of it was visible to you.

The suite has **3,000 tests**. Someone measured the flake rate last quarter and reported **0.2%** — one failure per test per 500 runs — and the number was received as good news, because 0.2% sounds like nothing. Run the arithmetic that nobody ran in that meeting. A build with no real bug in it comes back green only if *every one* of the 3,000 tests behaves:

```text
P(green | clean commit) = (1 - 0.002)^3000 = 0.0025 = 0.25%
```

**Four builds in a thousand.** At six merges a day that is **5.99 red builds every day** caused by nothing whatsoever. Not one of them has an owner, because not one of them has a cause — the failing test is different every time, and each individual test, examined alone, is 99.8% reliable and would pass any review you could design.

So the team did the reasonable thing eight months ago and added `--reruns 2` to the pytest invocation. The build has been green ever since. Everyone is happier. Deploy frequency went up.

And in the eleven weeks since a concurrency bug was merged into the order-cancellation path — a genuine race, in production code, that corrupts an order total when a cancellation and a payment capture interleave — the test that covers it has failed **eighteen times**. Every one of those eighteen failures passed on the second attempt, was filed green, and was never rendered anywhere a human could see it. The race manifests about 3% of the time. Under `--reruns 2` it is reported as a hard failure only when it loses three coin flips in a row, which is **0.0027%** of builds — one build in 37,037, or seventeen years at your merge rate.

The suite ran that test every single build. The test failed. The failure was correct. The information was generated, and then deliberately discarded by a flag someone added to make Thursdays better.

> **A retried flake and a retried race are the same event to your CI system, and it suppresses both. The question is not whether your suite is flaky. It is what your suite's output still means once you have decided how to respond to it.**

## The Concept

Two definitions first, because both get used loosely.

A **flaky test** is a test that produces different results on unchanged inputs — same commit, same code, same test, sometimes pass and sometimes fail. The word describes an *observation*, not a cause. Critically, it does not tell you which side of the boundary the non-determinism lives on: a flaky test may be a bad test, or it may be a perfectly good test correctly reporting a non-deterministic *product*. Section 4 measures how badly those two are confusable, and it is the hinge of the whole lesson.

A **gating suite** is one whose result blocks a merge or a deploy. That is what makes any of this matter. A non-gating suite that is wrong is a bad dashboard; a gating suite that is wrong is a governance failure, because you have written a rule that says "this program's opinion decides whether code ships" and then broken the program.

[CI/CD: From Commit to Artifact to Environment](../../10-infrastructure-and-deployment/10-ci-cd-pipelines/) already established the basic shape of this — that pipeline reliability compounds across jobs, and that retrying until green is retrying until the race hides. This lesson takes that from a warning to a measurement: how much information a red build actually carries, how a rational engineer responds to that, exactly how many real bugs blanket retries bury and for how long, and what to do instead.

### The arithmetic nobody does

Start from first principles, because everything else is a consequence of one line.

Let **f** be the probability that a given test fails on a given run for reasons unrelated to the code under test. Assume, for now, that tests flake independently. A build passes only if *no* test flakes, and there are **n** of them:

```text
P(build green | no real bug) = (1 - f)^n
```

That is it. There is no modelling, no simulation and no assumption beyond independence. The reason it surprises people is that human intuition treats "0.2% per test" as though it stays 0.2% at the build level, and it does not — it compounds, exactly the way compound interest does, and in the same direction as a fan-out amplification.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 520" width="100%" style="max-width:840px" role="img" aria-label="A grid showing the probability that a build containing no real bug comes back green, computed as one minus the per-test flake rate raised to the number of tests. Rows are per-test flake rates from one in ten thousand to one in a hundred; columns are suite sizes of 100, 300, 1000, 3000 and 10000 tests. The grid is green in the top left and red across the bottom right. The highlighted cell is a 0.2 percent flake rate at 3000 tests, which yields a green build on only 0.25 percent of clean commits. A note below states that at 3000 tests every individual test must be reliable to one flake in 58,488 runs before the suite is 95 percent trustworthy.">
<defs><marker id="p12-09-a1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker></defs>
<text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">A 0.2% flake rate is not small. At 3,000 tests it is a 0.25% green build.</text>
<g font-family="'JetBrains Mono', ui-monospace, monospace">
<text x="440" y="48" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.85">P(a build with NO real bug comes back green) = (1 &#8722; f)&#8319;&#8195;&#183;&#8195;computed, not sampled</text>
<text x="164" y="82" text-anchor="end" font-size="9.5" font-weight="700" fill="currentColor" opacity="0.7">per-test flake rate f</text>
<text x="239" y="82" text-anchor="middle" font-size="10" font-weight="700" fill="#3553ff">100 tests</text> <text x="361" y="82" text-anchor="middle" font-size="10" font-weight="700" fill="#3553ff">300 tests</text>
<text x="483" y="82" text-anchor="middle" font-size="10" font-weight="700" fill="#3553ff">1,000 tests</text> <text x="605" y="82" text-anchor="middle" font-size="10" font-weight="700" fill="#3553ff">3,000 tests</text>
<text x="727" y="82" text-anchor="middle" font-size="10" font-weight="700" fill="#3553ff">10,000 tests</text> <text x="164" y="116" text-anchor="end" font-size="11" font-weight="700" fill="currentColor">0.01%</text>
<text x="164" y="126" text-anchor="end" font-size="8" fill="currentColor" opacity="0.6">1 in 10,000</text>
<rect x="180" y="95" width="118" height="32" rx="5" fill="#0fa07f" fill-opacity="0.2" stroke="#0fa07f" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="239" y="115" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">99.00%</text>
<rect x="302" y="95" width="118" height="32" rx="5" fill="#0fa07f" fill-opacity="0.2" stroke="#0fa07f" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="361" y="115" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">97.04%</text>
<rect x="424" y="95" width="118" height="32" rx="5" fill="#0fa07f" fill-opacity="0.2" stroke="#0fa07f" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="483" y="115" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">90.48%</text>
<rect x="546" y="95" width="118" height="32" rx="5" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="605" y="115" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">74.08%</text>
<rect x="668" y="95" width="118" height="32" rx="5" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="727" y="115" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">36.79%</text> <text x="164" y="154" text-anchor="end" font-size="11" font-weight="700" fill="currentColor">0.05%</text>
<text x="164" y="164" text-anchor="end" font-size="8" fill="currentColor" opacity="0.6">1 in 2,000</text>
<rect x="180" y="133" width="118" height="32" rx="5" fill="#0fa07f" fill-opacity="0.2" stroke="#0fa07f" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="239" y="153" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">95.12%</text>
<rect x="302" y="133" width="118" height="32" rx="5" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="361" y="153" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">86.07%</text>
<rect x="424" y="133" width="118" height="32" rx="5" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="483" y="153" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">60.65%</text>
<rect x="546" y="133" width="118" height="32" rx="5" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="605" y="153" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">22.30%</text>
<rect x="668" y="133" width="118" height="32" rx="5" fill="#d64545" fill-opacity="0.2" stroke="#d64545" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="727" y="153" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">0.67%</text> <text x="164" y="192" text-anchor="end" font-size="11" font-weight="700" fill="currentColor">0.10%</text>
<text x="164" y="202" text-anchor="end" font-size="8" fill="currentColor" opacity="0.6">1 in 1,000</text>
<rect x="180" y="171" width="118" height="32" rx="5" fill="#0fa07f" fill-opacity="0.2" stroke="#0fa07f" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="239" y="191" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">90.48%</text>
<rect x="302" y="171" width="118" height="32" rx="5" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="361" y="191" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">74.07%</text>
<rect x="424" y="171" width="118" height="32" rx="5" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="483" y="191" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">36.77%</text>
<rect x="546" y="171" width="118" height="32" rx="5" fill="#d64545" fill-opacity="0.2" stroke="#d64545" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="605" y="191" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">4.97%</text>
<rect x="668" y="171" width="118" height="32" rx="5" fill="#d64545" fill-opacity="0.2" stroke="#d64545" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="727" y="191" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">&lt;0.05%</text> <text x="164" y="230" text-anchor="end" font-size="11" font-weight="700" fill="currentColor">0.20%</text>
<text x="164" y="240" text-anchor="end" font-size="8" fill="currentColor" opacity="0.6">1 in 500</text>
<rect x="180" y="209" width="118" height="32" rx="5" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="239" y="229" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">81.86%</text>
<rect x="302" y="209" width="118" height="32" rx="5" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="361" y="229" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">54.85%</text>
<rect x="424" y="209" width="118" height="32" rx="5" fill="#e0930f" fill-opacity="0.2" stroke="#e0930f" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="483" y="229" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">13.51%</text>
<rect x="546" y="209" width="118" height="32" rx="5" fill="#d64545" fill-opacity="0.2" stroke="#d64545" stroke-width="2.6" stroke-opacity="1"/>
<text x="605" y="229" text-anchor="middle" font-size="11.5" font-weight="700" fill="#d64545">0.25%</text>
<rect x="668" y="209" width="118" height="32" rx="5" fill="#d64545" fill-opacity="0.2" stroke="#d64545" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="727" y="229" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">&lt;0.05%</text> <text x="164" y="268" text-anchor="end" font-size="11" font-weight="700" fill="currentColor">0.50%</text>
<text x="164" y="278" text-anchor="end" font-size="8" fill="currentColor" opacity="0.6">1 in 200</text>
<rect x="180" y="247" width="118" height="32" rx="5" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="239" y="267" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">60.58%</text>
<rect x="302" y="247" width="118" height="32" rx="5" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="361" y="267" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">22.23%</text>
<rect x="424" y="247" width="118" height="32" rx="5" fill="#d64545" fill-opacity="0.2" stroke="#d64545" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="483" y="267" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">0.67%</text>
<rect x="546" y="247" width="118" height="32" rx="5" fill="#d64545" fill-opacity="0.2" stroke="#d64545" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="605" y="267" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">&lt;0.05%</text>
<rect x="668" y="247" width="118" height="32" rx="5" fill="#d64545" fill-opacity="0.2" stroke="#d64545" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="727" y="267" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">&lt;0.05%</text> <text x="164" y="306" text-anchor="end" font-size="11" font-weight="700" fill="currentColor">1.00%</text>
<text x="164" y="316" text-anchor="end" font-size="8" fill="currentColor" opacity="0.6">1 in 100</text>
<rect x="180" y="285" width="118" height="32" rx="5" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="239" y="305" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">36.60%</text>
<rect x="302" y="285" width="118" height="32" rx="5" fill="#d64545" fill-opacity="0.2" stroke="#d64545" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="361" y="305" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">4.90%</text>
<rect x="424" y="285" width="118" height="32" rx="5" fill="#d64545" fill-opacity="0.2" stroke="#d64545" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="483" y="305" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">&lt;0.05%</text>
<rect x="546" y="285" width="118" height="32" rx="5" fill="#d64545" fill-opacity="0.2" stroke="#d64545" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="605" y="305" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">&lt;0.05%</text>
<rect x="668" y="285" width="118" height="32" rx="5" fill="#d64545" fill-opacity="0.2" stroke="#d64545" stroke-width="1.1" stroke-opacity="0.55"/>
<text x="727" y="305" text-anchor="middle" font-size="10.5" font-weight="400" fill="currentColor">&lt;0.05%</text> <path d="M605 354 L 605 242" fill="none" stroke="#d64545" stroke-width="1.6" marker-end="url(#p12-09-a1)"/>
<text x="605" y="368" text-anchor="middle" font-size="10" font-weight="700" fill="#d64545">the house scenario</text>
<text x="605" y="381" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.85">3,000 tests &#215; 0.2% &#8594; 99.75% of clean builds are lies</text>
<rect x="40" y="396" width="800" height="86" rx="10" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.8"/>
<text x="58" y="418" font-size="11" font-weight="700" fill="#7c5cff">Now invert it: the per-test reliability a 95% green build actually demands</text>
<text x="60" y="440" font-size="9.5" fill="currentColor" opacity="0.7">100 tests</text> <text x="60" y="456" font-size="10.5" font-weight="700" fill="currentColor">1 in 1,950</text>
<text x="218" y="440" font-size="9.5" fill="currentColor" opacity="0.7">300 tests</text> <text x="218" y="456" font-size="10.5" font-weight="700" fill="currentColor">1 in 5,849</text>
<text x="376" y="440" font-size="9.5" fill="currentColor" opacity="0.7">1,000 tests</text> <text x="376" y="456" font-size="10.5" font-weight="700" fill="currentColor">1 in 19,496</text>
<text x="534" y="440" font-size="9.5" fill="currentColor" opacity="0.7">3,000 tests</text> <text x="534" y="456" font-size="11" font-weight="700" fill="#d64545">1 in 58,488</text>
<text x="692" y="440" font-size="9.5" fill="currentColor" opacity="0.7">10,000 tests</text> <text x="692" y="456" font-size="10.5" font-weight="700" fill="currentColor">1 in 194,958</text>
<text x="58" y="474" font-size="9.5" fill="currentColor" opacity="0.9">At 3,000 tests EVERY test must be reliable to 1-in-58,488 runs. Nobody measures a test that far out.</text>
<text x="440" y="506" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">Nobody wrote a bug. The suite is red 99.75% of the time because of multiplication.</text> </g></svg>
```

Read the highlighted cell, and then read the row and the column it sits in. **A 0.2% per-test flake rate at 3,000 tests produces a green build on 0.25% of clean commits.** Read the same row at 100 tests and it is 81.86% — perfectly liveable. Nothing about the *tests* changed between those two cells. The suite got bigger, which is the thing every healthy engineering organisation does on purpose, every sprint, forever. **Suite growth is a flake-rate amplifier, and nobody budgets for it.**

The program simulates this rather than only asserting it: 500,000 clean builds at n = 3,000 and f = 0.2% produced **0.237% green** against the closed form's **0.246%**, which is agreement to within sampling noise on a 0.25% event. The formula is the reality, not an approximation of it.

Now invert the question, because this is the version that should go in your team's charter. What per-test reliability does a **95% green build** require?

```text
f_max = 1 - 0.95^(1/n)
```

| suite size | maximum tolerable f | i.e. no worse than |
|---:|---:|---|
| 100 | 0.05128% | 1 flake in **1,950** runs |
| 300 | 0.01710% | 1 flake in **5,849** runs |
| 1,000 | 0.00513% | 1 flake in **19,496** runs |
| **3,000** | **0.00171%** | 1 flake in **58,488** runs |
| 10,000 | 0.00051% | 1 flake in **194,958** runs |

At 3,000 tests, **every single test must be reliable to one failure in 58,488 runs** before the *suite* is 95% trustworthy. Nobody measures a test that far out — section 6's R ≈ 3K rule puts observing a 1-in-58,488 event at 95% confidence at roughly 3 × 58,488 ≈ 175,000 runs — so in practice no team has any evidence at all that its suite meets the bar its merge policy assumes.

This is why "we have a few flaky tests" is not a small statement. There is no such thing as a few flaky tests in a large suite. There is only the rate, and the rate is multiplied by a number that grows every sprint.

### The trust collapse: what a red build actually tells you

The arithmetic above is the well-known half. This section is the half that changes how you argue about it, and it needs one tool: **Bayes' theorem**, which is just the statement that the probability of a hypothesis after seeing evidence depends on how *surprising* that evidence would be under each hypothesis.

Set up the two worlds honestly. Let **P(bug) = 5%** — five commits in a hundred contain a regression this suite is capable of detecting. Let the suite's intrinsic detection power be **90%** — when such a regression is present and no flake interferes, the suite fails 90% of the time. Then:

- **P(red | clean commit)** = `1 - (1-f)^n`. A clean commit goes red only if a flake fires.
- **P(red | buggy commit)** = `1 - (1 - 0.90)(1-f)^n`. A buggy commit goes red if the suite catches it *or* a flake fires.

And the thing you actually want:

```text
                     P(bug) . P(red | bug)
P(bug | red) = ------------------------------------------
               P(bug).P(red|bug) + P(clean).P(red | clean)
```

Measured across flake rates at n = 3,000:

| flake rate f | P(red \| clean) | P(red \| bug) | **P(bug \| red)** | evidence (bits) |
|---|---:|---:|---:|---:|
| 0 (perfect) | 0.00% | 90.00% | **100.00%** | **4.322** |
| 0.001% | 2.96% | 90.30% | 61.66% | 3.624 |
| 0.010% | 25.92% | 92.59% | 15.83% | 1.662 |
| 0.050% | 77.70% | 97.77% | 6.21% | 0.313 |
| 0.100% | 95.03% | 99.50% | 5.22% | 0.063 |
| **0.200%** | **99.75%** | **99.98%** | **5.01%** | **0.003** |

The "evidence" column is `log2(P(bug|red) / P(bug))` — the bits of information the red build gave you about the hypothesis you care about. In a deterministic suite a red build carries **4.322 bits**: it takes you from 5% certain to *certain*, which is the entire justification for making it a required check. In the house scenario it carries **0.003 bits**, which is **1,420× less**.

Look at what those numbers mean rather than at the ratio. P(bug | red) is **5.01%** against a prior of **5%**. The build went red and your belief about whether there is a bug moved by one part in a thousand. **You learned nothing.** That is not rhetoric or exaggeration for effect; it is the measured information content, and it is the honest answer to "why does nobody read the CI output any more".

The mechanism is worth naming because it explains why this creeps up on teams. As f rises, `P(red | clean)` climbs toward 1 — and `P(red | bug)` also climbs toward 1. Once *both* worlds produce a red build essentially always, red stops distinguishing between them. A signal carries information only when it is more likely under one hypothesis than the other, and a suite at f = 0.2% is 99.75% red when clean and 99.98% red when buggy. Those are the same number.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 520" width="100%" style="max-width:840px" role="img" aria-label="Two panels. The left panel plots the bits of evidence a red build carries about whether a real bug exists, against the per-test flake rate, at a suite size of 3000. A perfectly deterministic suite gives 4.322 bits; the curve falls to 1.662 bits at a 0.01 percent flake rate and to 0.003 bits at 0.2 percent, a 1420-fold collapse. The right panel is a measured simulation of 8000 builds in which engineers learn how often a red build is real and investigate accordingly: as the flake rate rises, the probability they investigate a red falls from 99.7 percent to 20.7 percent and the suite effective power to stop a regression falls from 87.5 percent to 16.2 percent, without a single test being edited.">
<defs><marker id="p12-09-a2" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker></defs>
<text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">A red build stops carrying information long before anyone stops trusting it</text>
<g font-family="'JetBrains Mono', ui-monospace, monospace">
<text x="88" y="52" font-size="10.5" font-weight="700" fill="#3553ff">EVIDENCE IN ONE RED BUILD (n = 3,000)</text>
<text x="88" y="68" font-size="9.5" fill="currentColor" opacity="0.8">log&#8322; P(bug|red) / P(bug) &#8212; bits gained over the 5% prior</text>
<path d="M88 92 L 88 288 L 468 288" fill="none" stroke="currentColor" stroke-width="1.5"/> <path d="M83 288.0 L 468 288.0" fill="none" stroke="currentColor" stroke-width="1" opacity="0.16"/>
<text x="78" y="291.5" text-anchor="end" font-size="9" fill="currentColor" opacity="0.75">0</text> <path d="M83 243.5 L 468 243.5" fill="none" stroke="currentColor" stroke-width="1" opacity="0.16"/>
<text x="78" y="247.0" text-anchor="end" font-size="9" fill="currentColor" opacity="0.75">1</text> <path d="M83 198.9 L 468 198.9" fill="none" stroke="currentColor" stroke-width="1" opacity="0.16"/>
<text x="78" y="202.4" text-anchor="end" font-size="9" fill="currentColor" opacity="0.75">2</text> <path d="M83 154.4 L 468 154.4" fill="none" stroke="currentColor" stroke-width="1" opacity="0.16"/>
<text x="78" y="157.9" text-anchor="end" font-size="9" fill="currentColor" opacity="0.75">3</text> <path d="M83 109.8 L 468 109.8" fill="none" stroke="currentColor" stroke-width="1" opacity="0.16"/>
<text x="78" y="113.3" text-anchor="end" font-size="9" fill="currentColor" opacity="0.75">4</text>
<text x="30" y="190.0" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.9" transform="rotate(-90 30 190.0)">bits of evidence</text>
<polyline points="88.0,95.5 164.0,126.6 240.0,214.0 316.0,274.1 392.0,285.2 468.0,287.9" fill="none" stroke="#d64545" stroke-width="2.6" stroke-linejoin="round"/> <circle cx="88.0" cy="95.5" r="4" fill="#0fa07f"/>
<text x="88.0" y="306" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">0</text> <text x="88.0" y="318" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.6">100.0%</text>
<circle cx="164.0" cy="126.6" r="4" fill="#e0930f"/> <text x="164.0" y="306" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">0.001%</text>
<text x="164.0" y="318" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.6">61.66%</text> <circle cx="240.0" cy="214.0" r="4" fill="#e0930f"/>
<text x="240.0" y="306" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">0.01%</text> <text x="240.0" y="318" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.6">15.8%</text>
<circle cx="316.0" cy="274.1" r="4" fill="#e0930f"/> <text x="316.0" y="306" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">0.05%</text>
<text x="316.0" y="318" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.6">6.2%</text> <circle cx="392.0" cy="285.2" r="4" fill="#e0930f"/>
<text x="392.0" y="306" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">0.10%</text> <text x="392.0" y="318" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.6">5.2%</text>
<circle cx="468.0" cy="287.9" r="4" fill="#d64545"/> <text x="468.0" y="306" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">0.20%</text>
<text x="468.0" y="318" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.6">5.0%</text>
<text x="278" y="334" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.75">per-test flake rate f&#8195;(second line: P(bug | red))</text>
<text x="100" y="87" font-size="10" font-weight="700" fill="#0fa07f">4.322 bits &#8212; a required check</text> <path d="M358 238 L 460 278" fill="none" stroke="#d64545" stroke-width="1.5" marker-end="url(#p12-09-a2)"/>
<text x="348" y="218" text-anchor="end" font-size="10.5" font-weight="700" fill="#d64545">0.003 bits</text>
<text x="348" y="232" text-anchor="end" font-size="9" fill="currentColor" opacity="0.9">1,420&#215; less. You learned nothing.</text>
<rect x="508" y="60" width="336" height="278" rx="10" fill="#7c5cff" fill-opacity="0.09" stroke="#7c5cff" stroke-width="1.8"/>
<text x="524" y="82" font-size="10.5" font-weight="700" fill="#7c5cff">MEASURED &#8212; 8,000 builds, engineers learning</text>
<text x="524" y="104" font-size="8.5" font-weight="700" fill="currentColor" opacity="0.7">flake rate</text> <text x="636" y="104" font-size="8.5" font-weight="700" fill="currentColor" opacity="0.7" text-anchor="end">true</text>
<text x="636" y="115" font-size="8.5" font-weight="700" fill="currentColor" opacity="0.7" text-anchor="end">P(bug|red)</text>
<text x="726" y="104" font-size="8.5" font-weight="700" fill="currentColor" opacity="0.7" text-anchor="end">they</text>
<text x="726" y="115" font-size="8.5" font-weight="700" fill="currentColor" opacity="0.7" text-anchor="end">investigate</text>
<text x="828" y="104" font-size="8.5" font-weight="700" fill="currentColor" opacity="0.7" text-anchor="end">EFFECTIVE</text>
<text x="828" y="115" font-size="8.5" font-weight="700" fill="currentColor" opacity="0.7" text-anchor="end">suite power</text> <path d="M520 122 L 832 122" fill="none" stroke="currentColor" stroke-width="1" opacity="0.35"/>
<text x="524" y="142" font-size="10" font-weight="700" fill="#0fa07f">0 (perfect)</text> <text x="636" y="142" font-size="10" text-anchor="end" fill="currentColor">100.0%</text>
<text x="726" y="142" font-size="10" text-anchor="end" fill="currentColor">99.7%</text> <text x="828" y="142" font-size="11" text-anchor="end" font-weight="700" fill="#0fa07f">87.5%</text>
<text x="524" y="172" font-size="10" font-weight="400" fill="currentColor">0.01%</text> <text x="636" y="172" font-size="10" text-anchor="end" fill="currentColor">15.8%</text>
<text x="726" y="172" font-size="10" text-anchor="end" fill="currentColor">36.4%</text> <text x="828" y="172" font-size="10" text-anchor="end" font-weight="400" fill="currentColor">29.5%</text>
<text x="524" y="202" font-size="10" font-weight="400" fill="currentColor">0.05%</text> <text x="636" y="202" font-size="10" text-anchor="end" fill="currentColor">6.2%</text>
<text x="726" y="202" font-size="10" text-anchor="end" fill="currentColor">23.2%</text> <text x="828" y="202" font-size="10" text-anchor="end" font-weight="400" fill="currentColor">25.2%</text>
<text x="524" y="232" font-size="10" font-weight="700" fill="#d64545">0.20%</text> <text x="636" y="232" font-size="10" text-anchor="end" fill="currentColor">5.0%</text>
<text x="726" y="232" font-size="10" text-anchor="end" fill="currentColor">20.7%</text> <text x="828" y="232" font-size="11" text-anchor="end" font-weight="700" fill="#d64545">16.2%</text>
<path d="M520 272 L 832 272" fill="none" stroke="currentColor" stroke-width="1" opacity="0.35"/> <text x="524" y="292" font-size="9.5" fill="currentColor" opacity="0.95">Not one test was edited. Not one</text>
<text x="524" y="306" font-size="9.5" fill="currentColor" opacity="0.95">assertion was weakened. The suite&#8217;s</text>
<text x="524" y="320" font-size="9.5" font-weight="700" fill="#d64545">power fell 87.5% &#8594; 16.2% anyway.</text>
<rect x="40" y="378" width="800" height="88" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.8"/>
<text x="58" y="400" font-size="11" font-weight="700" fill="#0fa07f">The mirror image, and it is the reason this is fixable</text>
<text x="58" y="420" font-size="10" fill="currentColor" opacity="0.95">P(clean | GREEN) = 99.48% at every flake rate in the table &#8212; identical, because that is algebra, not luck.</text>
<text x="58" y="436" font-size="10" fill="currentColor" opacity="0.95">A flake can turn a green build red. It can never turn a red build green. So green keeps all of its meaning.</text>
<text x="58" y="454" font-size="10.5" font-weight="700" fill="#0fa07f">The signal was never destroyed. Only the delivery channel was &#8212; and you get green just 0.25% of the time.</text>
<text x="440" y="506" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">Engineers ignoring a red build are not being lazy. They are being correctly Bayesian.</text> </g></svg>
```

Now the part that surprised me when the program printed it, and that reframes the whole problem. Look at the last column of the program's table: **P(clean | green) = 99.4764% at every single flake rate.** Identical to four decimal places, at f = 0 and at f = 0.2%. That is not a bug in the simulation and it is not a coincidence — it is algebra. A flake can turn a green build red. **A flake can never turn a red build green.** Flakiness is a strictly one-sided error, so a green build retains 100% of its meaning no matter how bad your flake rate gets.

Which gives the correct framing of what has actually gone wrong: **the signal was never destroyed. Only the delivery channel was.** Your suite still knows the answer, and when it manages to tell you, it is right. It just only manages to tell you 0.25% of the time. That is a much more tractable problem than "our tests are bad", and it is why the fixes in this lesson are about *channel* — what you retry, what you quarantine, what you record — rather than about rewriting 3,000 tests.

### The engineer-response model: how a suite trains you to ignore it

A red build's information content is a property of the suite. What happens next is a property of people, and it is entirely predictable — so model it and measure it.

Model an engineer as a Bayesian with a belief about "a red build is real", represented as a Beta distribution and started optimistically at **Beta(3,1)**, a posterior mean of 75%. A new hire genuinely believes three reds in four are worth reading. When a build goes red they investigate it with probability equal to that belief; investigating reveals ground truth and updates the belief. Ignoring a real regression means it ships, and production teaches them the same lesson about 40 builds later — expensively, but it does teach them, so the belief updates then too.

Run 8,000 builds (about 44 months at six a day) at four flake rates:

| flake rate | true P(bug\|red) | P(investigate) start → end | drops below 50% at build | regressions caught in CI | **effective suite power** |
|---|---:|---|---:|---:|---:|
| 0 (perfect) | 100.0% | 75% → **99.7%** | never | 349 / 399 | **87.5%** |
| 0.01% | 15.8% | 75% → 36.4% | 80 | 117 / 397 | 29.5% |
| 0.05% | 6.2% | 75% → 23.2% | 17 | 105 / 416 | 25.2% |
| **0.20%** | 5.0% | 75% → **20.7%** | **3** | 64 / 396 | **16.2%** |

**Not one test was edited. Not one assertion was weakened. The suite's measured power to stop a regression fell from 87.5% to 16.2%** — a 5.4× collapse — purely because of what the humans learned to do with its output. At f = 0.2% the belief crossed 50% at **build 3**. Three builds. Half a day. One sprint later the suite is decoration.

And note the calibration column carefully, because it defends the engineers against the accusation usually levelled at them. Their final belief settles at **20.7%** while the true P(bug|red) is **5.0%** — they are *over*-estimating how often a red build is real, because production keeps teaching them about the ones they ignored. They are not being lazy, careless or unprofessional. They are being correctly Bayesian about a channel that stopped carrying information, and they are being *more* diligent than the evidence strictly justifies, and they still end up ignoring four reds in five.

This is the argument to make when someone proposes a policy of "just take red builds seriously". You cannot policy your way out of an information-theoretic problem. The team is already responding rationally to the signal you are actually sending them. Change the signal.

### The taxonomy, and the five probes that cannot tell you the one thing you need

You cannot fix a flake you cannot name, so here is the catalogue — with, for each, the mechanism and the diagnostic that distinguishes it.

- **Async wait / fixed sleep too short.** The test sleeps a constant and asserts. Fails when the machine is busy. Signature: reproduces under load and under repetition, not under isolation.
- **Order dependence: the test needs a predecessor.** It relies on state some earlier test created. Signature: fails *deterministically* when run alone, passes in the suite.
- **Test pollution: poisoned by a predecessor.** The mirror image — an earlier test leaves global state, an open transaction, a patched module, a stray asyncio task. Signature: passes alone, fails in suite, changes with order.
- **Shared mutable global.** A module-level cache, a singleton, a class attribute. Signature: order-sensitive, and sensitive to *which* tests share the worker.
- **Resource leak.** File descriptors, ports, connections, threads exhausted late in a long run. Signature: fails only deep into a full suite, position-dependent, never alone.
- **Real network dependency.** Something reaches a real host. Signature: correlated with time of day and with the runner's egress.
- **Time-of-day / date boundary.** Midnight UTC, month end, 29 February, a DST transition ([Determinism: Time, Randomness, IDs & Order](../08-determinism-time-randomness-order/) covers this properly). Signature: reproduces on a different machine *at a different time*, not on repetition.
- **Unseeded randomness in a fixture.** A random email, a random ID, a random ordering. Signature: reproduces readily under repetition, independent of order and machine.
- **A real product race.** A genuine concurrency bug in the code under test ([Race Conditions, Atomicity & Critical Sections](../../08-concurrency-and-performance/08-race-conditions-and-atomicity/)). Signature: … and this is the problem.
- **Infrastructure noise.** A CPU-starved or over-subscribed runner. Signature: correlates with the runner, not with the test.

Give each of those ten a probability of reproducing under five diagnostic probes — (A) the test alone with the same seed, (B) the whole suite in the same order, (C) the whole suite shuffled, (D) a different runner hours later, (E) the test alone 200× in a loop — then simulate 40,000 flakes, run all five probes on each, and pick the maximum-likelihood cause. This is a real diagnostic, and it works:

| probe set | accuracy | cost per flake |
|---|---:|---:|
| all five | **44.7%** | 37.7 min |
| A–D (skip the 200× loop) | 36.3% | 36.4 min |
| A, B, C (no second machine) | 32.8% | 24.4 min |
| **A + E (isolate and hammer)** | **28.4%** | **1.7 min** |
| B only (just press re-run) | 18.8% | 12.0 min |

Two practical readings. First, pressing re-run — by far the most common response — is **18.8%** accurate against a 10% random baseline, for twelve minutes of CI. It is very nearly the worst thing you can do with the time. Second, look at the cost column: **A + E gets 28.4% for 1.7 minutes**, while going from there to all five buys another 16 points for an extra *thirty-six minutes*. If you are triaging a queue of flakes rather than one prize specimen, isolate-and-hammer is the correct default and it is not close.

Now the result that matters, and it is the one I did not expect to be this stark. Take the row for a **real product race** — an actual concurrency bug in your shipping code — and ask where the five-probe diagnosis sends it:

```text
   observed 'real product race', diagnosed as:
      59.0%  async wait / fixed sleep too short
      24.5%  unseeded randomness in a fixture
      11.0%  order dependence: needs a predecessor
       2.5%  infrastructure noise (CPU-starved runner)
```

The best diagnostic in this lesson identified a real product race correctly **7 times out of 4,000 — 0.2%**. It never once said "this is your code". Every single time, it said "this is a bad test", and the answer it preferred was a sleep that is too short.

That is not a defect in the probes, and no better probe set fixes it. A race in your product and a `sleep()` twenty milliseconds too short are *genuinely indistinguishable from outside*, because both are exactly "the same input sometimes produces a different answer". The probes localise the **mechanism** well — timing versus order versus state versus environment — which is what the 44.7% buys you. What no re-run strategy can ever tell you is **which side of the test boundary the non-determinism lives on**.

Hold that. It is the entire reason automatic retries are dangerous rather than merely wasteful, and section 7 puts a number on it.

### `sleep()` is a guess about someone else's scheduler

The single most common flake generator deserves its own arithmetic, because the trap is that both failure modes are invisible in the moment you write it.

A test does `POST /orders`, sleeps, then asserts the order exists. The sleep is a bet that the work finished. Measure the completion-time distribution over 200,000 runs — p50 **42 ms**, p90 **132 ms**, p99 **341 ms**, p99.9 **855 ms** — and then price each choice of sleep across 500 such tests:

| sleep set at | D | per-test flake rate | suite time (500 tests) | P(green) at 500 | P(green) at 3,000 |
|---|---:|---:|---:|---:|---:|
| p50 | 42 ms | 50.000% | 21 s | 0.000% | 0.000% |
| p90 | 132 ms | 10.000% | 66 s | 0.000% | 0.000% |
| p99 | 341 ms | 1.000% | 171 s | 0.657% | 0.000% |
| p99.9 | 855 ms | 0.100% | 428 s | 60.638% | 4.971% |
| p99.99 | 3,015 ms | 0.010% | **1,507 s** | 95.123% | 74.081% |

There is no good row, and that is the point. The per-test flake rate of a fixed sleep is *exactly* `1 − the percentile you chose`, by definition, so section 1's table applies directly: sleeping at the p99 leaves a 1% flake rate, which is a **0.657%** green build over 500 tests. To get the flake rate to 0.01% you must sleep at the p99.99, which costs **1,507 seconds** — twenty-five minutes of a suite doing nothing at all — and *still* flakes one run in ten thousand.

A fixed sleep encodes a percentile of someone else's scheduler as a constant in your source code, and a CI runner is not the machine you measured on. The fix is to stop guessing a duration and start polling for the condition with a deadline; [Testing Async & Event-Driven Systems](../11-testing-async-and-event-driven/) measures that properly.

### Detection power: how many re-runs prove a test is flaky

Everything operational in this lesson rests on one formula. A test fails one run in **K**. You re-run it **R** times. The probability you see at least one failure is `1 − (1 − 1/K)^R`, so for 95% confidence:

```text
R = ln(0.05) / ln(1 - 1/K)     ~   3K       (and ~4.6K for 99%)
```

| flake is 1 in K | R for 95% | R for 99% | re-run the TEST (0.4 s) | re-run the SUITE (12 min) |
|---:|---:|---:|---:|---:|
| 10 | 29 | 44 | 0.2 min | 6 h |
| 50 | 149 | 228 | 1.0 min | 30 h |
| **100** | **299** | 459 | **2.0 min** | **60 h** |
| 500 | 1,497 | 2,301 | 10.0 min | 299 h |
| 1,000 | 2,995 | 4,603 | 20.0 min | 599 h |

The rule of thumb — **R ≈ 3K** — is exact enough to do in your head, and the two right-hand columns are the whole operational lesson. Confirming a 1-in-100 flake costs **two minutes** if you re-run the test and **sixty hours of CI** if you re-run the suite. Never chase a flake with a full pipeline; extract the test, hammer it in a loop, and only reach for the suite when the probe you need is specifically "does the suite context matter" (probes B and C above).

The other half of this table is the one that explains why flakes feel like they appear from nowhere. Your normal CI traffic is already running detection experiments for free — just very slow ones:

| window | suite runs | detects flakes down to |
|---|---:|---|
| 1 day | 6 | 1 in 2 |
| 1 week | 42 | 1 in 14 |
| 1 month | 180 | 1 in 60 |
| 1 quarter | 546 | **1 in 182** |

At six builds a day, **a 1-in-500 flake is statistically invisible for an entire quarter**. It is not rare and it is not new. It is *under-observed*. This is the argument for treating flake rate as a recorded metric on every run — test id, commit, worker, seed, duration, outcome — rather than as a thing somebody noticed on a Tuesday. You cannot detect at 1-in-500 by remembering; you can trivially detect it by counting.

### Auto-retry converts a real bug into an invisible one

This is the experiment the lesson exists for.

Build a 400-test suite containing **14 environmental flakes** (genuinely bad tests, failing 1%–20% of runs) and **6 genuine intermittent product bugs** — real races in shipping code, manifesting 3%–35% of runs. Run 200 warm-up builds so the team's belief from section 3 equilibrates on the environmental noise alone. Then merge all six races on the same day and run the clock for **600 builds — 100 days** at six a day. Triage capacity is three opened failures per build, gated by the learned belief.

The mechanism first, because it is one line of arithmetic. Under `--reruns R`, a failure is only reported at all if it loses **R+1 times in a row**. So a race that manifests with probability *p* is reported as a hard red at rate **p^(R+1)**:

| p | R=0 | R=2 | change |
|---:|---:|---:|---|
| 35% | 35.00% | 4.2875% | 8× less visible |
| 14% | 14.00% | 0.2744% | 51× less visible |
| **3%** | **3.00%** | **0.0027%** | **1,111× less visible** |

Retries do not reduce the *rate* at which a race occurs. They reduce the rate at which you are told, and they do it super-linearly — cubing a small probability is a violent operation. Three policies, same suite, same seeds:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 660" width="100%" style="max-width:840px" role="img" aria-label="The headline experiment. A 400-test suite carrying fourteen environmental flakes and six genuine intermittent product races is run for 600 builds under three retry policies. Policy A with no retries goes green on 35.2 percent of clean commits and finds five of six races. Policy B, blanket --reruns 2, goes green on 98.4 percent of clean commits but leaves two of the six races completely undiscovered after 100 days and delays the others by up to 77 days. Policy C, --reruns 2 with --only-rerun restricted to environmental error signatures, goes green on 90.9 percent of clean commits and finds all six races within three days. A bar chart shows detection latency per race for each policy, and a panel explains that a race manifesting 3 percent of the time is reported at rate p cubed under blanket retry, which is 0.0027 percent, or one build in 37,037.">
<defs><marker id="p12-09-a3" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
<text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">A retried flake and a retried race look identical. Only one of them is yours.</text>
<g font-family="'JetBrains Mono', ui-monospace, monospace">
<text x="440" y="48" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.85">400 tests &#183; 14 environmental flakes + 6 genuine product races &#183; 600 builds = 100 days &#183; measured</text>
<rect x="40" y="64" width="262" height="150" rx="10" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff" stroke-width="1.8"/> <text x="54" y="86" font-size="11.5" font-weight="700" fill="#3553ff">A  no retries</text>
<text x="54" y="106" font-size="9" fill="currentColor" opacity="0.7">green on a clean commit</text> <text x="288" y="106" font-size="11" font-weight="700" text-anchor="end" fill="currentColor">35.2%</text>
<text x="54" y="122" font-size="9" fill="currentColor" opacity="0.7">builds red</text> <text x="288" y="122" font-size="10" text-anchor="end" fill="currentColor">70.2%</text>
<text x="54" y="138" font-size="9" fill="currentColor" opacity="0.7">P(investigate) at day 100</text> <text x="288" y="138" font-size="10" text-anchor="end" fill="currentColor">7.4%</text>
<path d="M52 148 L 290 148" fill="none" stroke="currentColor" stroke-width="1" opacity="0.3"/> <text x="54" y="166" font-size="9.5" font-weight="700" fill="currentColor" opacity="0.85">the 6 real product races</text>
<circle cx="64" cy="186" r="9" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="2"/> <path d="M59.8 186.4 L 62.8 189.6 L 68.4 182.4" fill="none" stroke="#0fa07f" stroke-width="2.1" stroke-linecap="round"/>
<circle cx="102" cy="186" r="9" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="2"/> <path d="M97.8 186.4 L 100.8 189.6 L 106.4 182.4" fill="none" stroke="#0fa07f" stroke-width="2.1" stroke-linecap="round"/>
<circle cx="140" cy="186" r="9" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="2"/> <path d="M135.8 186.4 L 138.8 189.6 L 144.4 182.4" fill="none" stroke="#0fa07f" stroke-width="2.1" stroke-linecap="round"/>
<circle cx="178" cy="186" r="9" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="2"/> <path d="M173.8 186.4 L 176.8 189.6 L 182.4 182.4" fill="none" stroke="#0fa07f" stroke-width="2.1" stroke-linecap="round"/>
<circle cx="216" cy="186" r="9" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="2"/> <path d="M211.8 186.4 L 214.8 189.6 L 220.4 182.4" fill="none" stroke="#0fa07f" stroke-width="2.1" stroke-linecap="round"/>
<circle cx="254" cy="186" r="9" fill="#d64545" fill-opacity="0.22" stroke="#d64545" stroke-width="2"/>
<path d="M250.4 182.4 L 257.6 189.6 M257.6 182.4 L 250.4 189.6" fill="none" stroke="#d64545" stroke-width="2.1" stroke-linecap="round"/>
<text x="171" y="208" text-anchor="middle" font-size="9.5" font-weight="700" fill="#d64545">5 found, 1 STILL HIDDEN</text>
<rect x="320" y="64" width="262" height="150" rx="10" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="1.8"/> <text x="334" y="86" font-size="11.5" font-weight="700" fill="#d64545">B  --reruns 2</text>
<text x="334" y="106" font-size="9" fill="currentColor" opacity="0.7">green on a clean commit</text> <text x="568" y="106" font-size="11" font-weight="700" text-anchor="end" fill="currentColor">98.4%</text>
<text x="334" y="122" font-size="9" fill="currentColor" opacity="0.7">builds red</text> <text x="568" y="122" font-size="10" text-anchor="end" fill="currentColor">3.2%</text>
<text x="334" y="138" font-size="9" fill="currentColor" opacity="0.7">P(investigate) at day 100</text> <text x="568" y="138" font-size="10" text-anchor="end" fill="currentColor">46.7%</text>
<path d="M332 148 L 570 148" fill="none" stroke="currentColor" stroke-width="1" opacity="0.3"/> <text x="334" y="166" font-size="9.5" font-weight="700" fill="currentColor" opacity="0.85">the 6 real product races</text>
<circle cx="344" cy="186" r="9" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="2"/> <path d="M339.8 186.4 L 342.8 189.6 L 348.4 182.4" fill="none" stroke="#0fa07f" stroke-width="2.1" stroke-linecap="round"/>
<circle cx="382" cy="186" r="9" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="2"/> <path d="M377.8 186.4 L 380.8 189.6 L 386.4 182.4" fill="none" stroke="#0fa07f" stroke-width="2.1" stroke-linecap="round"/>
<circle cx="420" cy="186" r="9" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="2"/> <path d="M415.8 186.4 L 418.8 189.6 L 424.4 182.4" fill="none" stroke="#0fa07f" stroke-width="2.1" stroke-linecap="round"/>
<circle cx="458" cy="186" r="9" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="2"/> <path d="M453.8 186.4 L 456.8 189.6 L 462.4 182.4" fill="none" stroke="#0fa07f" stroke-width="2.1" stroke-linecap="round"/>
<circle cx="496" cy="186" r="9" fill="#d64545" fill-opacity="0.22" stroke="#d64545" stroke-width="2"/>
<path d="M492.4 182.4 L 499.6 189.6 M499.6 182.4 L 492.4 189.6" fill="none" stroke="#d64545" stroke-width="2.1" stroke-linecap="round"/>
<circle cx="534" cy="186" r="9" fill="#d64545" fill-opacity="0.22" stroke="#d64545" stroke-width="2"/>
<path d="M530.4 182.4 L 537.6 189.6 M537.6 182.4 L 530.4 189.6" fill="none" stroke="#d64545" stroke-width="2.1" stroke-linecap="round"/>
<text x="451" y="208" text-anchor="middle" font-size="9.5" font-weight="700" fill="#d64545">4 found, 2 STILL HIDDEN</text>
<rect x="600" y="64" width="262" height="150" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="2.6"/> <text x="614" y="86" font-size="11.5" font-weight="700" fill="#0fa07f">C  --only-rerun</text>
<text x="614" y="106" font-size="9" fill="currentColor" opacity="0.7">green on a clean commit</text> <text x="848" y="106" font-size="11" font-weight="700" text-anchor="end" fill="currentColor">90.9%</text>
<text x="614" y="122" font-size="9" fill="currentColor" opacity="0.7">builds red</text> <text x="848" y="122" font-size="10" text-anchor="end" fill="currentColor">8.8%</text>
<text x="614" y="138" font-size="9" fill="currentColor" opacity="0.7">P(investigate) at day 100</text> <text x="848" y="138" font-size="10" text-anchor="end" fill="currentColor">26.5%</text>
<path d="M612 148 L 850 148" fill="none" stroke="currentColor" stroke-width="1" opacity="0.3"/> <text x="614" y="166" font-size="9.5" font-weight="700" fill="currentColor" opacity="0.85">the 6 real product races</text>
<circle cx="624" cy="186" r="9" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="2"/> <path d="M619.8 186.4 L 622.8 189.6 L 628.4 182.4" fill="none" stroke="#0fa07f" stroke-width="2.1" stroke-linecap="round"/>
<circle cx="662" cy="186" r="9" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="2"/> <path d="M657.8 186.4 L 660.8 189.6 L 666.4 182.4" fill="none" stroke="#0fa07f" stroke-width="2.1" stroke-linecap="round"/>
<circle cx="700" cy="186" r="9" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="2"/> <path d="M695.8 186.4 L 698.8 189.6 L 704.4 182.4" fill="none" stroke="#0fa07f" stroke-width="2.1" stroke-linecap="round"/>
<circle cx="738" cy="186" r="9" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="2"/> <path d="M733.8 186.4 L 736.8 189.6 L 742.4 182.4" fill="none" stroke="#0fa07f" stroke-width="2.1" stroke-linecap="round"/>
<circle cx="776" cy="186" r="9" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="2"/> <path d="M771.8 186.4 L 774.8 189.6 L 780.4 182.4" fill="none" stroke="#0fa07f" stroke-width="2.1" stroke-linecap="round"/>
<circle cx="814" cy="186" r="9" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="2"/> <path d="M809.8 186.4 L 812.8 189.6 L 818.4 182.4" fill="none" stroke="#0fa07f" stroke-width="2.1" stroke-linecap="round"/>
<text x="731" y="208" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">6 found, none hidden</text>
<text x="40" y="238" font-size="10.5" font-weight="700" fill="#3553ff">DAYS FROM MERGE TO SOMEBODY OPENING IT</text> <text x="696" y="238" font-size="9" fill="currentColor" opacity="0.7">never found</text>
<path d="M128 246 L 128 430" fill="none" stroke="currentColor" stroke-width="1" opacity="0.15"/> <text x="128" y="446" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.7">0 d</text>
<path d="M268 246 L 268 430" fill="none" stroke="currentColor" stroke-width="1" opacity="0.15"/> <text x="268" y="446" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.7">20 d</text>
<path d="M408 246 L 408 430" fill="none" stroke="currentColor" stroke-width="1" opacity="0.15"/> <text x="408" y="446" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.7">40 d</text>
<path d="M548 246 L 548 430" fill="none" stroke="currentColor" stroke-width="1" opacity="0.15"/> <text x="548" y="446" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.7">60 d</text>
<path d="M688 246 L 688 430" fill="none" stroke="currentColor" stroke-width="1" opacity="0.15"/> <text x="688" y="446" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.7">80 d</text>
<text x="32" y="269" font-size="10" fill="currentColor" opacity="0.9">race @ 35%</text> <rect x="128" y="253" width="11.9" height="6" rx="3" fill="#3553ff" fill-opacity="0.85"/>
<rect x="128" y="261" width="10.5" height="6" rx="3" fill="#d64545" fill-opacity="0.85"/> <rect x="128" y="269" width="3.0" height="6" rx="3" fill="#0fa07f" fill-opacity="0.85"/>
<text x="32" y="299" font-size="10" fill="currentColor" opacity="0.9">race @ 22%</text> <rect x="128" y="283" width="18.9" height="6" rx="3" fill="#3553ff" fill-opacity="0.85"/>
<rect x="128" y="291" width="537.6" height="6" rx="3" fill="#d64545" fill-opacity="0.85"/> <text x="672" y="297" font-size="8.5" font-weight="700" fill="#d64545">76.8 d</text>
<rect x="128" y="299" width="7.0" height="6" rx="3" fill="#0fa07f" fill-opacity="0.85"/> <text x="32" y="329" font-size="10" fill="currentColor" opacity="0.9">race @ 14%</text>
<rect x="128" y="313" width="73.5" height="6" rx="3" fill="#3553ff" fill-opacity="0.85"/> <rect x="128" y="321" width="311.5" height="6" rx="3" fill="#d64545" fill-opacity="0.85"/>
<text x="446" y="327" font-size="8.5" font-weight="700" fill="#d64545">44.5 d</text> <rect x="128" y="329" width="7.0" height="6" rx="3" fill="#0fa07f" fill-opacity="0.85"/>
<text x="32" y="359" font-size="10" fill="currentColor" opacity="0.9">race @ 9%</text> <rect x="128" y="343" width="3.0" height="6" rx="3" fill="#3553ff" fill-opacity="0.85"/>
<rect x="128" y="351" width="226.1" height="6" rx="3" fill="#d64545" fill-opacity="0.85"/> <text x="360" y="357" font-size="8.5" font-weight="700" fill="#d64545">32.3 d</text>
<rect x="128" y="359" width="16.1" height="6" rx="3" fill="#0fa07f" fill-opacity="0.85"/> <text x="32" y="389" font-size="10" fill="currentColor" opacity="0.9">race @ 6%</text>
<rect x="128" y="373" width="282.1" height="6" rx="3" fill="#3553ff" fill-opacity="0.85"/> <text x="416" y="379" font-size="8.5" font-weight="700" fill="#3553ff">40.3 d</text>
<rect x="128" y="381" width="560" height="6" rx="3" fill="#d64545" fill-opacity="0.14"/> <text x="696" y="387" font-size="8.5" font-weight="700" fill="#d64545">B NEVER</text>
<rect x="128" y="389" width="11.9" height="6" rx="3" fill="#0fa07f" fill-opacity="0.85"/> <text x="32" y="419" font-size="10" fill="currentColor" opacity="0.9">race @ 3%</text>
<rect x="128" y="403" width="560" height="6" rx="3" fill="#d64545" fill-opacity="0.14"/> <text x="696" y="409" font-size="8.5" font-weight="700" fill="#d64545">A NEVER</text>
<rect x="128" y="411" width="560" height="6" rx="3" fill="#d64545" fill-opacity="0.14"/> <text x="696" y="417" font-size="8.5" font-weight="700" fill="#d64545">B NEVER</text>
<rect x="128" y="419" width="21.0" height="6" rx="3" fill="#0fa07f" fill-opacity="0.85"/> <text x="32" y="462" font-size="9" fill="currentColor" opacity="0.75">bars, top to bottom: A / B / C</text>
<rect x="40" y="470" width="404" height="140" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="1.8"/> <text x="58" y="492" font-size="11" font-weight="700" fill="#e0930f">The mechanism, in one line</text>
<text x="58" y="514" font-size="10" fill="currentColor" opacity="0.95">A race that manifests p of the time is reported</text>
<text x="58" y="529" font-size="10" fill="currentColor" opacity="0.95">as a hard red only at rate <tspan font-weight="700" fill="#e0930f">p^(R+1)</tspan>.</text>
<text x="58" y="552" font-size="9" font-weight="700" fill="currentColor" opacity="0.7">p</text> <text x="196" y="552" font-size="9" font-weight="700" text-anchor="end" fill="currentColor" opacity="0.7">R=0</text>
<text x="300" y="552" font-size="9" font-weight="700" text-anchor="end" fill="currentColor" opacity="0.7">R=2</text>
<text x="426" y="552" font-size="9" font-weight="700" text-anchor="end" fill="currentColor" opacity="0.7">less visible</text> <text x="58" y="570" font-size="9.5" font-weight="400" fill="currentColor">35%</text>
<text x="196" y="570" font-size="9.5" text-anchor="end" fill="currentColor">35.00%</text> <text x="300" y="570" font-size="9.5" text-anchor="end" font-weight="400" fill="currentColor">4.2875%</text>
<text x="426" y="570" font-size="9.5" text-anchor="end" font-weight="400" fill="currentColor">8&#215;</text> <text x="58" y="585" font-size="9.5" font-weight="400" fill="currentColor">14%</text>
<text x="196" y="585" font-size="9.5" text-anchor="end" fill="currentColor">14.00%</text> <text x="300" y="585" font-size="9.5" text-anchor="end" font-weight="400" fill="currentColor">0.2744%</text>
<text x="426" y="585" font-size="9.5" text-anchor="end" font-weight="400" fill="currentColor">51&#215;</text> <text x="58" y="600" font-size="9.5" font-weight="700" fill="#d64545">3%</text>
<text x="196" y="600" font-size="9.5" text-anchor="end" fill="currentColor">3.00%</text> <text x="300" y="600" font-size="9.5" text-anchor="end" font-weight="700" fill="#d64545">0.0027%</text>
<text x="426" y="600" font-size="9.5" text-anchor="end" font-weight="700" fill="#d64545">1,111&#215;</text>
<rect x="460" y="470" width="380" height="140" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.8"/> <text x="478" y="492" font-size="11" font-weight="700" fill="#0fa07f">What to actually run</text>
<text x="478" y="512" font-size="9.5" fill="currentColor" opacity="0.95">Retry only failures matching an environmental</text>
<text x="478" y="526" font-size="9.5" fill="currentColor" opacity="0.95">signature. Let AssertionError through untouched.</text> <text x="478" y="548" font-size="9.5" font-weight="700" fill="#0fa07f">pytest --reruns 2 \</text>
<text x="494" y="562" font-size="9.5" font-weight="700" fill="#0fa07f">--only-rerun ConnectionError \</text> <text x="494" y="576" font-size="9.5" font-weight="700" fill="#0fa07f">--only-rerun TimeoutError</text>
<text x="478" y="598" font-size="9.5" fill="currentColor" opacity="0.95">For the 3% race: <tspan font-weight="700" fill="#0fa07f">945&#215; more visible</tspan> than blanket.</text>
<text x="440" y="646" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">Blanket retry cost 0.4% more CI and buried 2 of 6 real bugs. The case against it is not about money.</text> </g></svg>
```

| policy | green on a clean commit | builds red | test runs/build | P(investigate) at day 100 | races found in 100 d | **races still hidden** |
|---|---:|---:|---:|---:|---:|---:|
| **A** no retries | 35.2% | 70.2% | 400.0 | 7.4% | 5 / 6 | **1** |
| **B** `--reruns 2` blanket | **98.4%** | 3.2% | 401.4 | 46.7% | 4 / 6 | **2** |
| **C** `--reruns 2 --only-rerun` | 90.9% | 8.8% | 401.0 | 26.5% | **6 / 6** | **0** |

Read it in the order the team would.

**Blanket retry delivers exactly what it was added for.** A clean commit goes green **98.4%** of the time instead of **35.2%**. Builds are red on **3.2%** of runs instead of **70.2%**. It costs **0.4% more test executions**. Those are the numbers in the pull request that adds it, and every one of them is true. Note the cost figure in particular, because it kills the usual objection: per-test retries are essentially *free* in CI minutes, since only the handful of tests that actually failed get re-run. **The case against blanket retry cannot be made on money.** It has to be made on information.

**And here is the information.** Blanket retry left **2 of the 6 real product races completely undiscovered after 100 days**, against 1 for no retries at all, and delayed the ones it did surface by up to **76.8 days** against 2.7. The suite ran those tests every build. They failed. Every failure was filed as a pass. The 3% race needs **37,037 builds** to lose three coin flips in a row — **seventeen years** at six builds a day.

Now the column I would have got wrong before running this, and it is worth sitting with. **Policy B has the *highest* trust per red build: P(investigate) 46.7%, against 7.4% for no retries.** That is not a bug in the simulation. Retries suppress noise, so the reds that survive genuinely *are* more likely to be real, and the team is right to believe it. Retries do not make engineers stupid — they make the channel narrow. And a narrow channel is the trap, because it looks exactly like a fixed one from the inside: high confidence in a signal you almost never receive is worth less than moderate confidence in one that arrives on time. Policy B's engineers are more trusting, more diligent per red build, and catching fewer bugs.

**Policy C is the answer, and it is one flag.** `--only-rerun` restricts retries to failures whose error matches an environmental signature — `ConnectionError`, `TimeoutError`, the container-not-ready message — and lets `AssertionError` through completely untouched. The environmental flakes, which raise exactly those errors, get retried away. The races, which fail their assertions, do not. Result: clean-commit green **90.9%**, **6 of 6** races found, worst latency **3.0 days**, and P(investigate) held at **26.5%**.

The residual is honest and it is measured rather than waved away: **15%** of races in this model surface as a timeout rather than an assertion, so they match the allowlist and get retried anyway. C masks something too. Price it. For the hardest 3% race, C reports a hard red on **2.55%** of builds against blanket retry's **0.0027%** — **945× more visible** — for **6× more red builds** on a clean commit. That is the entire trade, and it is not close.

### Delta debugging: minimising a failing test *set*

Some flakes are not properties of a test at all. A 200-test job fails only when three particular tests run in the same worker — one seeds a module global, one mutates it, one asserts on it. No test fails alone. There are 2^200 subsets and you get roughly one oracle call per CI run.

The instinct is to bisect, and **bisection cannot solve this**. Split 200 tests in half; if the three culprits straddle the split, *neither half fails* and the search has nowhere to go. Measured over 40,000 random placements, that happens **75.4%** of the time — against a theoretical `1 − 2·C(100,3)/C(200,3) = 75.4%` — and it happens on the very first step.

The fix is Zeller & Hildebrandt's **ddmin** (*Simplifying and Isolating Failure-Inducing Input*, IEEE TSE 28(2):183–200, 2002). Its insight is that when no subset reproduces the failure, you should test the **complements** — remove a chunk and see if the rest still fails. Removing preserves interactions; keeping splits them.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 512" width="100%" style="max-width:840px" role="img" aria-label="Delta debugging a failing test set. The top half contrasts two strategies on a 200-test job whose failure requires three specific tests to run together. Plain bisection splits the job in half; because the three culprits straddle the split, neither half fails and the search is stuck on its very first step, which happened in 75.4 percent of 40000 measured trials against a theoretical 75.4 percent. The ddmin algorithm instead removes a chunk and tests the complement, which preserves interactions, and succeeded in 100 percent of trials in a median of 158 oracle calls. A table shows ddmin scaling: at 5000 tests it needs 299 CI runs against 5000 for removing one test at a time. A second table shows that when the interaction only fails 40 percent of the time, running the oracle once per call yields the correct minimal set just 17.8 percent of the time, rising to 95.5 percent at six repeats, which is exactly the number the detection-power formula predicts.">
<defs><marker id="p12-09-a4" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
<text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Bisection cannot find an interaction. ddmin&#8217;s complement step is why.</text>
<g font-family="'JetBrains Mono', ui-monospace, monospace">
<text x="440" y="48" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.85">a 200-test job that fails only when tests 41, 118 and 173 all run in it &#8212; no single test fails alone</text>
<text x="44" y="74" font-size="11" font-weight="700" fill="#d64545">1 &#183; HALVE AND KEEP THE RED HALF</text>
<rect x="44" y="86" width="360" height="22" rx="4" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-width="1.2" stroke-opacity="0.45"/>
<rect x="114.8" y="86" width="6" height="22" rx="2" fill="#d64545" fill-opacity="0.9"/> <rect x="253.4" y="86" width="6" height="22" rx="2" fill="#d64545" fill-opacity="0.9"/>
<rect x="352.4" y="86" width="6" height="22" rx="2" fill="#d64545" fill-opacity="0.9"/> <path d="M224 82 L 224 116" fill="none" stroke="#3553ff" stroke-width="2" stroke-dasharray="4 3"/>
<text x="44" y="130" font-size="9" fill="currentColor" opacity="0.8">tests 1-100</text> <text x="404" y="130" text-anchor="end" font-size="9" fill="currentColor" opacity="0.8">tests 101-200</text>
<rect x="44" y="138" width="176" height="24" rx="4" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.4"/>
<text x="132" y="154" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">left half: PASSES</text>
<rect x="228" y="138" width="176" height="24" rx="4" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.4"/>
<text x="316" y="154" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">right half: PASSES</text>
<text x="44" y="182" font-size="10.5" font-weight="700" fill="#d64545">Neither half is red. The search is over.</text>
<text x="44" y="198" font-size="9.5" fill="currentColor" opacity="0.9">Measured over 40,000 random placements: stuck on step 1</text>
<text x="44" y="212" font-size="10.5" font-weight="700" fill="#d64545">75.4% of the time&#8195;(theory: 75.4%)</text>
<text x="468" y="74" font-size="11" font-weight="700" fill="#0fa07f">2 &#183; ddmin: REMOVE A CHUNK, TEST THE COMPLEMENT</text>
<rect x="468" y="86" width="360" height="22" rx="4" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-width="1.2" stroke-opacity="0.45"/>
<rect x="538.8" y="86" width="6" height="22" rx="2" fill="#d64545" fill-opacity="0.9"/> <rect x="677.4" y="86" width="6" height="22" rx="2" fill="#d64545" fill-opacity="0.9"/>
<rect x="776.4" y="86" width="6" height="22" rx="2" fill="#d64545" fill-opacity="0.9"/> <rect x="468" y="86" width="58" height="22" rx="4" fill="#e0930f" fill-opacity="0.32" stroke="#e0930f" stroke-width="1.6"/>
<text x="497" y="130" text-anchor="middle" font-size="9" font-weight="700" fill="#e0930f">removed</text> <rect x="526" y="138" width="302" height="24" rx="4" fill="#d64545" fill-opacity="0.18" stroke="#d64545" stroke-width="1.6"/>
<text x="677" y="154" text-anchor="middle" font-size="9.5" font-weight="700" fill="#d64545">complement: STILL RED &#8212; all 3 culprits survived</text>
<text x="468" y="182" font-size="10.5" font-weight="700" fill="#0fa07f">Removing preserves interactions. Keeping splits them.</text>
<text x="468" y="198" font-size="9.5" fill="currentColor" opacity="0.9">Measured over 600 trials: minimises to exactly 3 tests,</text>
<text x="468" y="212" font-size="10.5" font-weight="700" fill="#0fa07f">100.0% of the time, median 158 oracle calls</text>
<rect x="40" y="240" width="392" height="150" rx="10" fill="#3553ff" fill-opacity="0.08" stroke="#3553ff" stroke-width="1.8"/>
<text x="58" y="262" font-size="10.5" font-weight="700" fill="#3553ff">SCALING &#8212; the reason ddmin wins</text> <text x="58" y="282" font-size="8.5" font-weight="700" fill="currentColor" opacity="0.7">job size n</text>
<text x="270" y="282" font-size="8.5" font-weight="700" text-anchor="end" fill="currentColor" opacity="0.7">one-at-a-time</text>
<text x="360" y="282" font-size="8.5" font-weight="700" text-anchor="end" fill="currentColor" opacity="0.7">ddmin</text>
<text x="414" y="282" font-size="8.5" font-weight="700" text-anchor="end" fill="currentColor" opacity="0.7">ratio</text> <text x="58" y="302" font-size="10" font-weight="400" fill="currentColor">50</text>
<text x="270" y="302" font-size="10" text-anchor="end" fill="currentColor">50</text> <text x="360" y="302" font-size="10" text-anchor="end" font-weight="400" fill="currentColor">108</text>
<text x="414" y="302" font-size="10" text-anchor="end" font-weight="400" fill="currentColor">0.5&#215;</text> <text x="58" y="324" font-size="10" font-weight="400" fill="currentColor">200</text>
<text x="270" y="324" font-size="10" text-anchor="end" fill="currentColor">200</text> <text x="360" y="324" font-size="10" text-anchor="end" font-weight="400" fill="currentColor">163</text>
<text x="414" y="324" font-size="10" text-anchor="end" font-weight="400" fill="currentColor">1.2&#215;</text> <text x="58" y="346" font-size="10" font-weight="400" fill="currentColor">1,000</text>
<text x="270" y="346" font-size="10" text-anchor="end" fill="currentColor">1,000</text> <text x="360" y="346" font-size="10" text-anchor="end" font-weight="400" fill="currentColor">230</text>
<text x="414" y="346" font-size="10" text-anchor="end" font-weight="400" fill="currentColor">4.3&#215;</text> <text x="58" y="368" font-size="10" font-weight="700" fill="#0fa07f">5,000</text>
<text x="270" y="368" font-size="10" text-anchor="end" fill="currentColor">5,000</text> <text x="360" y="368" font-size="10" text-anchor="end" font-weight="700" fill="#0fa07f">299</text>
<text x="414" y="368" font-size="10" text-anchor="end" font-weight="700" fill="#0fa07f">16.7&#215;</text>
<rect x="448" y="240" width="392" height="150" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="1.8"/>
<text x="466" y="262" font-size="10.5" font-weight="700" fill="#e0930f">WHEN THE ORACLE ITSELF IS FLAKY (fails 40%)</text> <text x="466" y="282" font-size="8.5" font-weight="700" fill="currentColor" opacity="0.7">repeats m</text>
<text x="700" y="282" font-size="8.5" font-weight="700" text-anchor="end" fill="currentColor" opacity="0.7">minimal set correct</text>
<text x="822" y="282" font-size="8.5" font-weight="700" text-anchor="end" fill="currentColor" opacity="0.7">CI runs</text> <text x="466" y="302" font-size="10" font-weight="400" fill="#d64545">1</text>
<text x="700" y="302" font-size="10" text-anchor="end" font-weight="700" fill="#d64545">17.8%</text> <text x="822" y="302" font-size="10" text-anchor="end" fill="currentColor">361</text>
<text x="466" y="324" font-size="10" font-weight="400" fill="currentColor">2</text> <text x="700" y="324" font-size="10" text-anchor="end" font-weight="400" fill="currentColor">48.8%</text>
<text x="822" y="324" font-size="10" text-anchor="end" fill="currentColor">431</text> <text x="466" y="346" font-size="10" font-weight="400" fill="currentColor">3</text>
<text x="700" y="346" font-size="10" text-anchor="end" font-weight="400" fill="currentColor">77.2%</text> <text x="822" y="346" font-size="10" text-anchor="end" fill="currentColor">542</text>
<text x="466" y="368" font-size="10" font-weight="700" fill="#0fa07f">6</text> <text x="700" y="368" font-size="10" text-anchor="end" font-weight="700" fill="#0fa07f">95.5%</text>
<text x="822" y="368" font-size="10" text-anchor="end" fill="currentColor">956</text> <rect x="40" y="406" width="800" height="72" rx="10" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.8"/>
<text x="58" y="428" font-size="11" font-weight="700" fill="#7c5cff">The repeat count is not a tuning knob. It is the section-6 confidence calculation.</text>
<text x="58" y="448" font-size="10" fill="currentColor" opacity="0.95">R = ln(0.05) / ln(1 &#8722; 0.40) = 6 repeats for 95% confidence in ONE oracle answer &#8212; and 6 is exactly where the</text>
<text x="58" y="464" font-size="10" fill="currentColor" opacity="0.95">success rate crosses 95%. Delta debugging a flaky failure is delta debugging with a flaky oracle.</text>
<text x="440" y="498" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">At m = 1 you finish holding a &#8220;minimal&#8221; set that is simply wrong, and nothing tells you.</text> </g></svg>
```

| strategy | succeeds | oracle calls (= CI runs) |
|---|---:|---|
| halve, keep the red half | 24.6% | 1, then it is stuck |
| remove one test at a time | 100.0% | 200 |
| **ddmin** | **100.0%** | **158 median** (70–189) |

158 against 200 is not much of a win, and at n = 50 ddmin is genuinely *worse* than one-at-a-time. That is fine — it is not supposed to win there. The win is in the scaling, because ddmin is `O(|culprits| · log n)` in the good case while one-at-a-time is `O(n)`:

| job size n | one-at-a-time | ddmin (median) | ratio |
|---:|---:|---:|---:|
| 50 | 50 | 108 | 0.5× |
| 200 | 200 | 163 | 1.2× |
| 1,000 | 1,000 | 230 | 4.3× |
| **5,000** | **5,000** | **299** | **16.7×** |

At 5,000 tests that is the difference between "run this overnight" and "this is not a plan".

Then the version you will actually meet, which ties this section back to section 6. Suppose the interaction only fails **40%** of the time it is present. Now the **oracle lies**: a subset containing all three culprits can come back green, and ddmin cheerfully discards the culprit. Section 6 already told us the repeat count that fixes it — `R = ln(0.05)/ln(1−0.40) = 6` — and the measurement lands exactly there:

| repeats m | minimal set correct | CI runs per debug |
|---:|---:|---:|
| 1 | **17.8%** | 361 |
| 2 | 48.8% | 431 |
| 3 | 77.2% | 542 |
| **6** | **95.5%** | 956 |
| 9 | 99.2% | 1,392 |

One run per oracle call gets the answer right **17.8%** of the time, and — this is the dangerous part — it **fails silently**. You finish the process holding a "minimal" set that is simply wrong, with nothing to tell you so, and then you spend a day staring at three innocent tests. The repeat count is not a tuning knob to fiddle with until it feels right; it is the same confidence calculation as everything else in this lesson. **Delta debugging a flaky failure is delta debugging with a flaky oracle**, and you must budget for it.

### Quarantine, and what an expiry date actually buys

Quarantine is the standard humane answer: mark the flaky test non-gating, keep running and reporting it, assign an owner. The standard advice attached to it is "always give it an expiry date, or quarantine becomes deletion with extra steps". I set out to measure that and got a more uncomfortable answer than the slogan.

Simulate 100 sprints (four years). The suite starts at 3,000 gating tests and grows by 25 a sprint. Each stable test has a 0.06% chance per sprint of acquiring a flake — roughly two new flakes a sprint at this size. Quarantined tests still run and still report but gate nothing. Twelve regressions a sprint land somewhere in the suite's coverage: one aimed at a quarantined test's area **ships**, and one aimed at a *deleted* test's area ships forever after. All four policies share a single seed, so they see the identical sequence of flakes and regressions and only the policy differs.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="Four quarantine policies run over 100 sprints against one shared random seed, so each sees the identical sequence of tests going flaky. With no expiry and half a fix per sprint, 210 tests end up quarantined and 2.08 percent of regressions ship. With a two-sprint expiry and the same half-fix budget, only 10 remain quarantined but 200 have been deleted, and exactly the same 2.08 percent of regressions ship. The two policies that fund two fixes per sprint both ship 0.33 percent, six times better, regardless of whether an expiry date exists. The conclusion drawn is that the fix budget is the variable the measurement responds to, and that the difference an expiry makes is recoverability: quarantined coverage can be bought back, deleted coverage cannot.">
<text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Quarantine and deletion lose identical coverage. Only one is recoverable.</text>
<g font-family="'JetBrains Mono', ui-monospace, monospace">
<text x="440" y="48" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.85">100 sprints &#183; one shared seed, so all four policies see the identical flakes and regressions</text>
<text x="300" y="76" font-size="8.5" font-weight="700" fill="#e0930f">quarantined (recoverable)</text> <text x="510" y="76" font-size="8.5" font-weight="700" fill="#d64545">deleted (gone for good)</text>
<text x="752" y="76" font-size="8.5" font-weight="700" text-anchor="end" fill="currentColor" opacity="0.7">regressions shipped</text>
<text x="40" y="112" font-size="10.5" font-weight="700" fill="currentColor">no expiry &#183; 0.5 fixes/sprint</text> <text x="40" y="126" font-size="9" fill="currentColor" opacity="0.65">under-funded</text>
<rect x="300" y="98" width="323.1" height="26" rx="4" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f" stroke-width="1.4"/>
<text x="462" y="116" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor">210</text> <text x="752" y="117" text-anchor="end" font-size="12.5" font-weight="700" fill="#d64545">2.08%</text>
<text x="40" y="178" font-size="10.5" font-weight="700" fill="currentColor">no expiry &#183; 2 fixes/sprint</text> <text x="40" y="192" font-size="9" fill="currentColor" opacity="0.65">funded</text>
<rect x="300" y="164" width="92.3" height="26" rx="4" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f" stroke-width="1.4"/>
<text x="346" y="182" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor">60</text> <text x="752" y="183" text-anchor="end" font-size="12.5" font-weight="700" fill="#0fa07f">0.33%</text>
<text x="40" y="244" font-size="10.5" font-weight="700" fill="currentColor">2-sprint expiry &#183; 0.5 fixes/sprint</text> <text x="40" y="258" font-size="9" fill="currentColor" opacity="0.65">under-funded</text>
<rect x="300" y="230" width="15.4" height="26" rx="4" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f" stroke-width="1.4"/>
<rect x="315.4" y="230" width="307.7" height="26" rx="4" fill="#d64545" fill-opacity="0.55" stroke="#d64545" stroke-width="1.4"/>
<text x="308" y="226" text-anchor="middle" font-size="9.5" font-weight="700" fill="#e0930f">10</text> <text x="469" y="248" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor">200</text>
<text x="752" y="249" text-anchor="end" font-size="12.5" font-weight="700" fill="#d64545">2.08%</text> <text x="40" y="310" font-size="10.5" font-weight="700" fill="currentColor">2-sprint expiry &#183; 2 fixes/sprint</text>
<text x="40" y="324" font-size="9" fill="currentColor" opacity="0.65">funded</text> <rect x="300" y="296" width="13.8" height="26" rx="4" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f" stroke-width="1.4"/>
<rect x="313.8" y="296" width="78.5" height="26" rx="4" fill="#d64545" fill-opacity="0.55" stroke="#d64545" stroke-width="1.4"/> <text x="307" y="292" text-anchor="middle" font-size="9.5" font-weight="700" fill="#e0930f">9</text>
<text x="353" y="314" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor">51</text> <text x="752" y="315" text-anchor="end" font-size="12.5" font-weight="700" fill="#0fa07f">0.33%</text>
<rect x="40" y="368" width="800" height="84" rx="10" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.8"/>
<text x="58" y="390" font-size="11" font-weight="700" fill="#7c5cff">Rows 1 and 3 have the same fix budget and differ only in the expiry date. Both shipped 2.08%.</text>
<text x="58" y="410" font-size="10" fill="currentColor" opacity="0.95">A quarantined test and a deleted test gate exactly the same amount: none. On the escape metric an expiry date on its</text>
<text x="58" y="426" font-size="10" fill="currentColor" opacity="0.95">own changes nothing. What it changes is recoverability &#8212; 210 quarantined tests are a debt you can still pay down;</text>
<text x="58" y="442" font-size="10.5" font-weight="700" fill="#7c5cff">200 deletions are written off. Fund the budget first; the date is what makes the bill arrive on a known day.</text> </g></svg>
```

| policy | quarantined at sprint 100 | deleted | fixed | **regressions that shipped** |
|---|---:|---:|---:|---:|
| no expiry · 0.5 fixes/sprint | **210** | 0 | 50 | **2.08%** |
| no expiry · 2 fixes/sprint | 60 | 0 | 200 | **0.33%** |
| 2-sprint expiry · 0.5 fixes/sprint | 10 | **200** | 50 | **2.08%** |
| 2-sprint expiry · 2 fixes/sprint | 9 | 51 | 200 | **0.33%** |

**This did not come out the way the slogan says.** Compare rows 1 and 3: same fix budget, differing only in whether an expiry exists. One ends with 210 tests quarantined and the other with 200 deleted, and **both shipped exactly 2.08% of regressions**. Identical — not approximately, exactly, because they share a seed. An expiry date, on its own, changed *nothing* about how much coverage the suite had, for the simple reason that a quarantined test and a deleted test gate precisely the same amount: none.

So on the escape metric, expiry without budget genuinely *is* deletion with extra steps. The slogan is right about what it is and wrong about what it fixes.

What separates the good rows from the bad ones is the **fix budget**, in every pairing. Rows 2 and 4 both shipped **0.33%** — 6× better — and one of them has no expiry date at all.

Which leaves the real difference, and it is **recoverability**. The lax policy's 210 quarantined tests are a debt still sitting on the balance sheet: fund the budget next quarter and that coverage comes back. The expiry policy's 200 deletions have been written off, and no future budget can buy them back. Run the clock to 500 sprints and the lax policy is carrying 2,301 recoverable tests while the expiry-without-budget policy has permanently destroyed 2,290.

So state the opinion precisely rather than as a slogan. **Quarantine needs an expiry date *and* a funded fix budget, and if you can only have one, take the budget** — that is the variable the measurement responds to. What the expiry date buys is not coverage; it is that the bill arrives on a known day, in a diff someone has to approve, instead of never. Which is worth having. Put the date in the marker itself so the test fails when it passes:

```python
@pytest.mark.flaky(reason="ORDERS-4412", expires="2026-09-01")
def test_cancellation_releases_reservation():
    ...
```

…and fail the build on an expired marker. A quarantine list that only ever grows is not a policy. It is an outbox.

### The economics: fix it, delete it, or live with it

Finally, the number that decides what you do on Monday. At 30 builds a week, one flaky test at rate *p* turns `30p` builds red, and each red costs about **9 engineer-minutes** of re-run, wait and lost context. A root-cause fix costs about **6 engineer-hours**.

| flake rate p | red builds/wk | min/wk | h/quarter | a fix pays back in |
|---:|---:|---:|---:|---:|
| 0.2% | 0.1 | 0.5 | 0.1 | 667 weeks |
| 1.0% | 0.3 | 2.7 | 0.6 | 133 weeks |
| 2.0% | 0.6 | 5.4 | 1.2 | 67 weeks |
| 5.0% | 1.5 | 13.5 | 2.9 | 27 weeks |
| 20.0% | 6.0 | 54.0 | 11.7 | 7 weeks |

The break-even is exact, and it is worth deriving rather than memorising:

```text
p* = fix_hours . 60 / (builds_per_week . triage_min . 52) = 2.56%
```

**Above a 2.6% flake rate, fixing pays for itself inside a year whatever the test is worth**, and there is nothing left to discuss. Below it, one flake genuinely is not worth six engineer-hours — which is the honest reason nobody fixes them, and precisely the mechanism by which a population accumulates. Note also that **p\* is inversely proportional to build volume**: a team shipping 240 builds a week has a break-even of **0.32%**. The busier you get, the less flakiness you can afford, and nobody re-derives this when the team grows.

Then price the *population* rather than the test, which is where the argument actually lives. The house scenario — 3,000 tests at 0.2% — produces **180 flaky test failures a week**. At nine minutes each that is **27 engineer-hours per week**, or **0.8 full-time engineers**, burnt on re-running a suite that already knew the answer. **Every single one of those flakes is individually below p\*.** Every one is individually not worth fixing, and collectively they cost you an engineer. That is the whole trap in one sentence, and it is why flake reduction has to be a funded programme with a budget rather than a series of individual judgement calls.

The decision is therefore never per-test; it is per-test-**value**. A test's worth is the bugs it catches per year × the ~14 engineer-hours an escaped bug costs:

| test catches | worth | p = 0.5% | p = 2% | p = 5% |
|---|---:|---|---|---|
| 0.05 bugs/yr | 0.7 h/yr | DELETE | DELETE | FIX |
| 0.25 bugs/yr | 3.5 h/yr | KEEP | DELETE | FIX |
| 1.00 bugs/yr | 14.0 h/yr | KEEP | KEEP | FIX |
| 3.00 bugs/yr | 42.0 h/yr | KEEP | KEEP | FIX |

Every branch of that table needs **bugs-caught-per-test**, which almost nobody records. Record it. It is one row per failure — test id, commit, worker, seed, duration — plus the single field that makes this entire lesson decidable: **whether the failure turned out to be real.**

## Build It

[`code/flaky.py`](code/flaky.py) is ten numbered arguments, one per `###` heading above. Standard library only, seeded with `SEED = 12`, about 2 seconds, no network and no files. Every number in this lesson is in its output.

The whole lesson rests on one function, and it is worth seeing how small it is:

```python
def green(f: float, n: int) -> float:
    """P(a clean commit produces a green build) = (1 - f)^n."""
    return (1.0 - f) ** n
```

Section 1 also *simulates* it rather than only asserting it, and the simulation had to be fast enough to run 500,000 builds of 3,000 tests each. Drawing 1.5 billion Bernoulli variables is not an option, so it samples the gaps between failures instead — a geometric distribution — which gives the identical failure-count distribution at about seven random numbers per build:

```python
def flake_count(rng: random.Random, n: int, f: float) -> int:
    """Exact count of independently flaking tests in a suite of n at rate f."""
    log1mf = math.log1p(-f)
    i, k = -1, 0
    while True:
        i += int(math.log(1.0 - rng.random()) / log1mf) + 1
        if i >= n:
            return k
        k += 1
```

That is a genuinely exact sampler, not an approximation, which matters because the whole point of the section is that measurement and closed form agree.

The Bayesian model in section 2 is four lines, and the one people get wrong is the second — a buggy commit is subject to flakes *too*, which is exactly why red stops discriminating:

```python
quiet = green(f, n)                                  # P(no flake fires anywhere)
p_red_clean = 1.0 - quiet
p_red_buggy = 1.0 - (1.0 - SUITE_POWER) * quiet      # caught OR a flake fired
p_buggy_red = (BUG_RATE * p_red_buggy) / (
    BUG_RATE * p_red_buggy + (1.0 - BUG_RATE) * p_red_clean)
```

Section 7's retry policy is the centrepiece, and the load-bearing detail is `--only-rerun` being modelled as an **imperfect error-signature match** rather than as a magic oracle. An environmental flake raises a matching error 92% of the time; a race raises one 15% of the time. Without that, the experiment would be rigged:

```python
def _attempt(rng, rate, reruns, only_rerun, match):
    """Run one unstable test under a retry policy -> (hard_red, extra_runs)."""
    if rng.random() >= rate:
        return False, 0
    allowed = reruns
    if only_rerun and rng.random() >= match:
        allowed = 0                       # error did not match the allowlist
    extra = 0
    for _ in range(allowed):
        extra += 1
        if rng.random() >= rate:
            return False, extra           # passed on re-run: filed as green
    return True, extra
```

`return False, extra` is the single most important line in the program. A test failed, was re-run, passed, and the function returns "not a hard red". That is `pytest-rerunfailures` behaving exactly as documented, and it is how eighteen real failures became eighteen green builds.

`ddmin` is implemented from the paper, and the `if not reduced:` complement branch is the part that makes it work where bisection cannot:

```python
    for ch in chunks:                       # reduce to a subset
        if ch and fails(ch):
            c, n, reduced = ch, 2, True
            break
    if not reduced:
        for ch in chunks:                   # reduce to a COMPLEMENT
            drop = set(ch)
            comp = [x for x in c if x not in drop]
            if comp and fails(comp):
                c, n, reduced = comp, max(n - 1, 2), True
                break
```

Run it:

```bash
docker compose exec -T app python \
  phases/12-testing-and-quality/09-flaky-tests/code/flaky.py
```

```console
== 1 . THE ARITHMETIC: A PER-TEST RATE IS A PER-BUILD CATASTROPHE ==
  P(a build with NO real bug in it comes back green) = (1 - f)^n

   per-test flake rate f    n=100    n=300    n=1,000  n=3,000  n=10,000
     0.01%  (1 in 10,000)     99.00%   97.04%   90.48%   74.08%   36.79%
     0.05%  (1 in  2,000)     95.12%   86.07%   60.65%   22.30%    0.67%
     0.10%  (1 in  1,000)     90.48%   74.07%   36.77%    4.97%    0.00%
     0.20%  (1 in    500)     81.86%   54.85%   13.51%    0.25%    0.00%
     0.50%  (1 in    200)     60.58%   22.23%    0.67%    0.00%    0.00%
     1.00%  (1 in    100)     36.60%    4.90%    0.00%    0.00%    0.00%

  simulated 500,000 clean builds at n=3,000, f=0.2%: 0.237% green
  closed form (1-0.002)^3000 = 0.246%  -> the formula is the reality

  at 3,000 tests EVERY test must be reliable to 1-in-58,488 before the suite is
  95% trustworthy. Nobody measures a test that far out. Meanwhile, at 6
  builds/day, 5.99 builds go red every day for no reason at all - 30 a week.

== 2 . THE TRUST COLLAPSE: WHAT A RED BUILD ACTUALLY TELLS YOU ==
   flake rate f    P(red|clean)   P(red|bug)   P(bug|red)   evidence   P(clean|green)
   0 (perfect)          0.00%       90.00%      100.00%     4.322       99.4764%
   0.010%              25.92%       92.59%       15.83%     1.662       99.4764%
   0.200%              99.75%       99.98%        5.01%     0.003       99.4764%

  the same red build at f = 0.2% carries 0.003 bits, 1,420x less. P(bug|red) is
  5.01% against a prior of 5%: the build went red and you learned NOTHING.

== 3 . THE ENGINEER-RESPONSE MODEL: A SUITE THAT TRAINS YOU TO IGNORE IT ==
   flake rate    true         P(investigate)    drops below   regressions   caught   effective
   (n = 3,000)   P(bug|red)   start     end     50% at build     seen        in CI   suite power
   0 (perfect)     100.0%      75%    99.7%          never         399      349       87.5%
   0.01%            15.8%      75%    36.4%             80         397      117       29.5%
   0.05%             6.2%      75%    23.2%             17         416      105       25.2%
   0.20%             5.0%      75%    20.7%              3         396       64       16.2%

== 4 . THE TAXONOMY: FIVE PROBES, AND THE ONE THING THEY CANNOT TELL YOU ==
   probe set                              accuracy   cost per flake
   all five                                 44.7%        37.7 min
   A + E (isolate and hammer)               28.4%         1.7 min
   B only (just press re-run)               18.8%        12.0 min

   observed 'real product race', diagnosed as:
      59.0%  async wait / fixed sleep too short
      24.5%  unseeded randomness in a fixture
      11.0%  order dependence: needs a predecessor

  the five-probe diagnosis named a real product race correctly 7 of 4,000
  times - 0.2%. It never once said 'this is your code'.

== 6 . DETECTION POWER: HOW MANY RE-RUNS TO PROVE A TEST IS FLAKY ==
   flake is    R for 95%   R for 99%   re-run the TEST   re-run the SUITE
   1 in K                              (0.4 s each)      (12 min each)
      100           299         459            2.0 min               60 h
    1,000         2,995       4,603           20.0 min              599 h

   window        suite runs   detects flakes down to
   1 quarter           546   1 in 182     at 95% confidence

== 7 . THE EXPERIMENT THAT MATTERS: RETRIES HIDE REAL BUGS ==
      p      R=0       R=1        R=2      R=2 vs R=0
     35%   35.00%   12.250%   4.2875%            8x less visible
      3%    3.00%   0.090%   0.0027%        1,111x less visible

  policy                       green on   builds   test runs   P(invest-   races    races still
                               a clean      red     per build   igate) at    found     hidden at
                                commit                          the end     in 100d    day 100
  A  no retries                  35.2%    70.2%       400.0       7.4%        5            1
  B  --reruns 2 (blanket)        98.4%     3.2%       401.4      46.7%        4            2
  C  --reruns 2 --only-rerun     90.9%     8.8%       401.0      26.5%        6            0

  per-race detection latency (days from merge to somebody opening it):
   manifests    A no retries     B --reruns 2     C --only-rerun
        35%           1.7 d            1.5 d             0.2 d
        22%           2.7 d           76.8 d             0.0 d
        14%          10.5 d           44.5 d             1.0 d
         9%           0.0 d           32.3 d             2.3 d
         6%          40.3 d            NEVER             1.7 d
         3%           NEVER            NEVER             3.0 d

== 8 . DELTA DEBUGGING: MINIMISING A FAILING TEST *SET*, NOT A TEST ==
   strategy                         succeeds   oracle calls (= CI runs)
   halve, keep the red half           24.6%   1, then it is stuck
   remove one test at a time         100.0%   200
   ddmin                             100.0%   158 median (70-189)

   repeats m   minimal set correct   CI runs per debug   vs m=1
           1                 17.8%                 361     1.0x
           6                 95.5%                 956     2.6x

== 9 . QUARANTINE, AND WHAT AN EXPIRY DATE ACTUALLY BUYS ==
   policy                             quarantined  deleted   fixed   coverage lost   regressions
                                      at sprint 100                   recov'ble/gone   that shipped
   no expiry, 0.5 fixes/sprint              210        0      50      210 / 0            2.08%
   no expiry, 2 fixes/sprint                 60        0     200       60 / 0            0.33%
   2-sprint expiry, 0.5 fixes/spr            10      200      50       10 / 200          2.08%
   2-sprint expiry, 2 fixes/sprint            9       51     200        9 / 51           0.33%

== 10 . THE ECONOMICS: FIX IT, DELETE IT, OR LIVE WITH IT ==
    p* = fix_hours . 60 / (builds_per_week . triage_min . 52) = 2.56%

  and price the POPULATION, not the test. The house scenario - 3,000 tests at
  0.2% - produces 180 flaky test failures a week. At 9 minutes each that is
  27 engineer-hours per week, 0.8 full-time engineers, burnt on re-running
  a suite that already knew the answer. Every single one is below p*.
```

Four of these are arguments rather than demos, so read them as such.

**Section 1 is arithmetic and section 2 is the reframe.** The measured 0.237% against the closed form's 0.246% confirms the model rather than the model confirming itself. The number to carry from section 2 is not the 0.003 bits — it is that **P(clean | green) is 99.4764% in every single row**. Flakiness is one-sided. Your green builds are still trustworthy; you just get almost none of them.

**Section 3 is the one to show a sceptical manager.** The suite's power falls 87.5% → 16.2% with no change to any test. The belief crosses 50% at build **3**.

**Section 7 is the lesson.** Three policies, one suite. Blanket retry buys the best-looking build (98.4% green, 3.2% red, +0.4% CI) and buries two of six real races for good. `--only-rerun` finds all six inside three days for 6× more red builds. If you take one flag from this lesson, take that one.

**Section 9 contradicted what I expected to write**, and I have left the contradiction in rather than tuning the model until it agreed. Expiry without a funded budget shipped *exactly* the same 2.08% of regressions as no expiry at all. The budget is what moves the number.

## Use It

Everything above is stdlib arithmetic. Here is the real toolchain, with the flags that matter and the defaults that bite.

**`pytest-rerunfailures` is the one to configure carefully**, because its default usage is precisely the harmful policy from section 7:

```bash
# The policy section 7 measured as burying 2 of 6 real races. Do not ship this.
pytest --reruns 2

# The policy that found all six in under 3 days. Ship this.
pytest --reruns 2 --reruns-delay 1 \
       --only-rerun 'ConnectionError' \
       --only-rerun 'ConnectionResetError' \
       --only-rerun 'TimeoutError' \
       --only-rerun 'OperationalError' \
       --only-rerun 'ContainerNotReady'
```

`--only-rerun` takes a regex matched against the exception **name and message**, and it is repeatable — every occurrence adds an alternative. The rule to hold onto: **allowlist the infrastructure, never the assertion.** `AssertionError` must never appear in that list, because an assertion failure is your test doing its job. `--reruns-delay` matters more than it looks for anything container- or connection-related, since an immediate retry usually hits the same not-yet-ready dependency. And prefer the per-test flag over a pipeline-level "re-run failed jobs" button: section 7 measured re-running the *suite* at 12 minutes a go against 0.4 s for one test.

For finer control, mark specific tests rather than the whole run:

```python
@pytest.mark.flaky(reruns=3, reruns_delay=2, only_rerun=["ConnectionError"])
def test_publishes_to_broker(): ...
```

**`pytest-randomly` is the highest-value plugin in this phase and it is on by default once installed.** It shuffles test order every run and reseeds `random` and `Faker` per test, which converts the order-dependence and shared-state causes from section 4 (rows 2, 3 and 4 — collectively the majority of real-world flakes) from invisible into loud. It prints the seed it used; that seed is how you reproduce:

```bash
pytest -p randomly --randomly-seed=12345    # reproduce a specific shuffle
pytest -p no:randomly                       # probe A/B: pin the order deliberately
```

Turn it on, expect a bad week, and understand that the tests it breaks were already broken — you were simply running the one ordering that hid it.

**`pytest-repeat` and `pytest-flakefinder` implement probe E**, and section 6 is how you choose the count:

```bash
pytest tests/test_orders.py::test_cancel --count=300   # 1-in-100 at 95%: R ~ 3K
pytest --flake-finder --flake-runs=50                  # every test, 50x
```

Do not guess this number. `R ≈ 3K` for 95%, `R ≈ 4.6K` for 99%. If you want confidence about a 1-in-500 flake, that is 1,497 runs of one test — ten minutes — and no amount of re-running the pipeline substitutes for it.

**`pytest-xdist` is a flake *source* as well as a speed-up**, and it belongs in this lesson for that reason. `-n auto` distributes tests across processes, which means session-scoped fixtures are constructed once *per worker*, shared external resources (a database, a fixed port, a temp path, a message topic) are now contended, and `--dist loadfile` versus the default `--dist load` changes which tests share a worker — and therefore which order dependencies fire. Give every worker its own resources:

```python
# conftest.py
@pytest.fixture(scope="session")
def db_url(worker_id: str) -> str:                 # "gw0", "gw1", ... or "master"
    return f"postgresql://localhost/test_{worker_id}"
```

**Record every failure, because section 6 proved you cannot detect a 1-in-500 flake by remembering.** A `conftest.py` hook is enough to start; the schema is the point, not the storage:

```python
# conftest.py
def pytest_runtest_logreport(report):
    if report.when == "call" and report.failed:
        emit_flake_record(
            test_id=report.nodeid,
            outcome="failed",
            duration_s=report.duration,
            commit=os.environ.get("GIT_SHA"),
            worker=os.environ.get("PYTEST_XDIST_WORKER", "master"),
            random_seed=os.environ.get("PYTEST_RANDOMLY_SEED"),
            runner=os.environ.get("RUNNER_NAME"),
            error_class=report.excinfo.typename if report.excinfo else None,
            # the field that makes everything in section 10 decidable:
            was_real=None,          # filled in by triage, never left null
        )
```

`was_real` is the whole thing. Without it you cannot compute a per-test flake rate, you cannot compute bugs-caught-per-test, and every decision in section 10 is a guess. With it, `p` and test value are both queries.

**Quarantine mechanically, with the date in the marker.** A custom marker plus a non-blocking job plus a check that fails on expiry:

```python
# conftest.py
def pytest_collection_modifyitems(config, items):
    today = datetime.date.today()
    for item in items:
        m = item.get_closest_marker("flaky_quarantine")
        if not m:
            continue
        expires = datetime.date.fromisoformat(m.kwargs["expires"])
        if expires < today:
            item.add_marker(pytest.mark.fail(          # the bill comes due
                reason=f"quarantine expired {expires} ({m.kwargs['reason']})"))
        else:
            item.add_marker(pytest.mark.quarantined)
```

```yaml
# .github/workflows/ci.yml
  gate:
    run: pytest -m "not quarantined"          # this one blocks the merge
  quarantined:
    continue-on-error: true                   # this one only reports
    run: pytest -m quarantined --count=20     # 20 runs -> a measured rate, not an anecdote
```

Running the quarantined job **20 times** rather than once is the part people skip, and section 6 says why: one run of a 1-in-20 test tells you nothing, twenty runs gives you a rate you can act on.

**On CI platforms**, know what "re-run" means where you are. GitHub Actions' *Re-run failed jobs* re-executes whole jobs against the same commit, which is section 6's 12-minute-per-attempt column — the most expensive possible way to sample a flake. Its `--rerun-individual-job` and the general re-run button both leave the original result in the run history, so *do not* treat "eventually green" as green in your metrics; count first-attempt outcomes. Whatever platform you are on, the number to put on a dashboard is **first-attempt green rate**, not final green rate, because the second is the one the retry policy is designed to flatter.

**What to actually do**, in order, on Monday:

1. **Record failures with `was_real`.** Nothing else in this lesson is decidable without it, and it is an afternoon's work.
2. **Turn on `pytest-randomly`.** It will find the order-dependence and shared-state flakes you already have.
3. **Replace `--reruns N` with `--reruns N --only-rerun <infrastructure errors>`.** One line, and section 7 measured it as 6/6 races found against 4/6.
4. **Dashboard first-attempt green rate** and per-test flake rate. Alert on the rate, not on individual failures.
5. **Fix anything above p\* = 2.6%** (recompute p\* for your build volume — it scales inversely). Quarantine the rest with a date *and* a funded budget, and delete zero-value tests without ceremony.

## Think about it

1. Section 2 found that `P(clean | green)` is 99.4764% at every flake rate, while `P(bug | red)` collapses to 5.01%. Given that asymmetry, design a merge policy that extracts useful information from a suite running at f = 0.2% *without* first fixing any flakes. What does it cost, and what does it still fail to catch?
2. Policy B in section 7 produced the highest per-red-build trust (46.7%) and the second-worst outcomes. Name another engineering metric with this same shape — where improving the measured quality of a signal makes the system worse — and say what the two cases have in common.
3. Your suite has 12,000 tests and you merge 40 times a day. Compute the per-test flake rate you need for a 90% green build, and the break-even flake rate p\* from section 10 at your build volume. Which of the two constraints binds first, and what does that imply about which you should measure?
4. Section 9's rows 1 and 3 shipped *exactly* the same 2.08% of regressions. Construct a scenario in which the expiry-date policy is nonetheless clearly the right choice, and identify what the simulation's escape-rate metric fails to capture about it.
5. Section 4 showed that the five-probe diagnosis identifies a real product race 0.2% of the time. You suspect a specific flaky test is a race in production code rather than a bad test. What evidence *outside* the test suite would move that probability, and what would you have to have instrumented in advance to get it?

## Key takeaways

- **A per-test flake rate is a per-build catastrophe, because it compounds.** `P(green) = (1−f)^n`. At f = 0.2%, 100 tests gives **81.86%** green and 3,000 tests gives **0.25%** — measured at 0.237% over 500,000 simulated builds. Inverted: a 95% green build at 3,000 tests requires every test to be reliable to **1 flake in 58,488 runs**. Suite growth is a flake amplifier nobody budgets for.
- **A red build in a flaky suite carries no information, and this is measurable in bits.** At f = 0.2%, n = 3,000, `P(bug | red)` is **5.01%** against a 5% prior — **0.003 bits**, against **4.322 bits** for a deterministic suite, a **1,420×** collapse. Once both a clean build and a buggy build are red ~99.8% of the time, red has stopped distinguishing them.
- **But flakiness is strictly one-sided, and that is the way out.** `P(clean | green)` measured **99.4764%** at *every* flake rate — identical, by algebra, because a flake can turn green red but never red green. The signal was never destroyed, only the delivery channel. Fix the channel.
- **Flaky suites do not slow teams down; they switch the suite off.** Modelling engineers as Bayesians over 8,000 builds, `P(investigate)` decayed **75% → 20.7%** — crossing 50% at **build 3** — and the suite's effective power to stop a regression fell **87.5% → 16.2%** with no test edited. The engineers settle *above* the true `P(bug|red)` of 5.0%: they are being correctly Bayesian, not lazy.
- **No re-run strategy can tell you whether the non-determinism is in your test or in your product.** A five-probe differential diagnosis reached **44.7%** accuracy on mechanism but identified a genuine product race correctly **7 times in 4,000 (0.2%)** — it *never once* said "this is your code". Cheap wins exist though: isolate-and-hammer gets **28.4% for 1.7 minutes** where pressing re-run gets **18.8% for 12**.
- **Blanket retries bury real bugs, and the cost is information rather than money.** `--reruns 2` reports a race manifesting *p* of the time at rate **p³**: a 3% race goes from 3.00% to **0.0027%** visible — one build in 37,037, seventeen years at six builds a day. Over 100 measured days it left **2 of 6 genuine races undiscovered** and delayed others by up to **76.8 days**, for **0.4% more CI**.
- **`--only-rerun` is the whole fix and it is one flag.** Retry only failures matching infrastructure error signatures; let `AssertionError` through. Measured: **6/6 races found, worst latency 3.0 days**, clean-commit green **90.9%** (against 98.4% blanket, 35.2% bare). Even with 15% of races leaking into the allowlist it is **945× more visible** than blanket retry on the hardest case.
- **Detection is a calculation, not a habit: R ≈ 3K for 95% confidence.** Confirming a 1-in-100 flake costs **2 minutes** re-running the test and **60 hours** re-running the suite. At 6 builds/day your CI only reaches **1-in-182** in a quarter, so a 1-in-500 flake is under-observed rather than rare — which is why per-failure recording, including *whether it was real*, is the prerequisite for everything else.
- **Bisection cannot find a test interaction; ddmin can.** Halving fails on its first step **75.4%** of the time (theory 75.4%) because three culprits straddle the split. ddmin (Zeller & Hildebrandt, IEEE TSE 28(2), 2002) succeeded **100%** in **158** median oracle calls, and scales — **299 calls at n = 5,000 against 5,000** for one-at-a-time. With a 40%-reproducing oracle it needs **6 repeats** for 95% correctness (17.8% at m = 1, and it fails silently) — the same R ≈ 3K formula again.
- **Quarantine needs a funded fix budget more than it needs an expiry date.** Over 100 sprints on a shared seed, no-expiry and 2-sprint-expiry at the same budget shipped **exactly 2.08%** of regressions each — an expiry alone changed nothing, because quarantined and deleted tests gate the same amount: none. Funding 2 fixes/sprint got **0.33%** either way. The expiry's real value is recoverability: 210 quarantined tests are a debt you can still pay down; 200 deletions are written off.
- **Fix above p\* = 2.6%, and fund the population rather than judging tests one at a time.** A fix repays inside a year above `p* = fix_hours·60/(builds_per_week·triage_min·52)` — and p\* scales *inversely* with build volume, so 240 builds/week makes it **0.32%**. The trap: 3,000 tests at 0.2% produce **180 flaky failures a week = 27 engineer-hours = 0.8 FTE**, and **every single one is individually below p\***.

Next: [Contract Testing: The Seam Between Services](../10-contract-testing/) — why an integration environment that has been red for nine days catches nothing, and what the consumer can verify on its own instead.
