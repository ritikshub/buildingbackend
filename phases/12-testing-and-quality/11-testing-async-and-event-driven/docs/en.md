# Testing Async & Event-Driven Systems

> A fixed `sleep` cannot win. Measured here on a real completion-time distribution: `sleep(p99.9)` costs **16.3 minutes** across a 500-test suite and still leaves **46.5% of builds red for no reason**; the only fixed sleep that gets a 500-test suite to 99% green is **3.0 seconds — 74× the median, and essentially the slowest of 200,000 observations** — costing **25.1 minutes** of pure waiting. A 12-line polling primitive reached **100% green in 30.7 seconds**, 49× faster and strictly less flaky. Then the rest of what your async suite is not testing: an at-least-once consumer that over-credited **$3,571.20** across 400 orders, **2 of 5 invariants** that secretly depended on arrival order and broke in **480 and 360 of 720** permutations, and a retry that wrote **4 rows for 1 order** while the dead-letter queue stayed empty.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Determinism: Time, Randomness, IDs & Order](../08-determinism-time-randomness-order/), [Delivery Semantics & Idempotent Consumers](../../06-messaging-and-pub-sub/06-delivery-semantics-and-idempotency/), [Coroutines & Async/Await from the Ground Up](../../08-concurrency-and-performance/05-coroutines-and-async-await/)
**Time:** ~80 minutes

## The Problem

It is 09:14 on a Wednesday and `test_order_is_visible_after_checkout` is red on `main`. Nobody touched checkout. Nobody touched the worker. The diff on the failing commit fixes a typo in a README.

Here is the test, in full:

```python
def test_order_is_visible_after_checkout(client, db):
    resp = client.post("/orders", json={"sku": "A-1", "qty": 2})
    assert resp.status_code == 202
    assert db.orders.get(resp.json()["order_id"]) is not None
```

`202` is `202 Accepted`, and RFC 9110, *HTTP Semantics* (2022), §15.3.3 defines it as: the request has been accepted for processing, *but the processing has not been completed*. The status code is telling the test, in the specification's own words, that the thing on the next line has not happened yet. The test asserts it anyway. Roughly seven times in ten the row is already there, because the queue was empty and the consumer was warm.

**09:31 — the fix goes in.** One line: `time.sleep(0.5)` between the POST and the assertion. The suite has 180 asynchronous assertions in it and this is the eleventh one to get the treatment. CI goes green at 10:02 and everyone moves on.

**Six weeks later** the build agents move to a cheaper instance type, and four of those eleven tests start failing again. The sleeps become `2.0`. The suite is now **six minutes** of a computer waiting for nothing, which nobody has budgeted for and nobody can point at, because the cost is distributed across 180 lines that each look reasonable in isolation.

**And it still fails on Tuesdays**, when the nightly reindex holds a lock and the consumer group rebalances. Not often. Roughly one build in three, one Tuesday in four. The team's policy for this is a button labelled *Re-run failed jobs*.

Every instinct says the sleep is too short and should be longer. That instinct is correct and it is also a trap, because there is no length that is right. The completion time is not a number, it is a distribution with a tail, and a fixed sleep is a horizontal line drawn across that distribution: everything to the right of the line is a flaky test and everything to the left of it is time the suite spent asleep on purpose.

> **A fixed sleep is a guess about somebody else's scheduler, and the two ways of being wrong — too short, and too long — are not alternatives. You get both.**

## The Concept

### There is no instant at which "done" happens

A synchronous test has an unfair advantage that is easy to miss because it is never stated: the function returns. The return is the completion signal. `result = charge(order)` cannot execute the next line until charging is finished, so "when do I assert?" is a question the language has already answered.

Delete the return and the question comes back unanswered. `POST /orders` hands you a `202` and a receipt; somewhere behind it a message is enqueued, a consumer picks it up, a row is written and a projection catches up. From outside, **there is no event you can subscribe to that means "done"** — only states you can observe, none of which distinguishes *not yet* from *never*.

That distinction is not merely hard, it is provably unavailable in the general case. Fischer, Lynch and Paterson, *Impossibility of Distributed Consensus with One Faulty Process* (JACM 32(2), 1985) turns on exactly this: in an asynchronous system a process that has not answered is indistinguishable from a process that never will. Your test is a participant in that system. It cannot tell a slow consumer from a crashed one, and neither can you.

So the test has to supply the missing definition itself. Every asynchronous assertion is really three decisions, and most suites make only the first one on purpose:

1. **What observable state counts as done?** (the row exists / the status is `paid` / the event was published)
2. **How long am I willing to wait for it?** (the deadline)
3. **What do I say when it never arrives?** (the failure message)

`time.sleep(0.5)` answers the first two badly and the third not at all. The rest of this lesson prices each of those answers.

### The completion-time distribution behind every sleep you have ever written

Before choosing a wait, look at what you are waiting for. The program models one `POST /orders` → row-visible latency as a lognormal body — the ordinary path of enqueue, dequeue, handle, commit — plus two additive tails that every real event pipeline has: a redelivery with a backoff, and a consumer-group rebalance or garbage-collection pause. Then it draws 200,000 of them.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 452" width="100%" style="max-width:840px" role="img" aria-label="A log-scale density plot of 200,000 measured end-to-end completion times for one POST slash orders until the row is visible. Almost all the mass sits between 10 and 150 milliseconds: the median is 41 milliseconds and 97.8 percent of runs finish inside 150 milliseconds. The tail is long and nearly empty: p99 is 404 milliseconds, p99.9 is 2.0 seconds which is 48 times the median, and the slowest of the 200,000 observations is 3.1 seconds, 77 times the median. The fixed sleep required for a 500-test suite to go green 99 percent of the time is 3.0 seconds, which is essentially the maximum of the whole sample.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">200,000 completions. The mass is on the left. The sleep you need is on the right.</text>
    <text x="440" y="45" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">POST /orders returns 202 · time until the row is visible · log scale</text>

    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.22" stroke-dasharray="3 4">
      <path d="M90 108 L 90 200"/><path d="M366 108 L 366 200"/><path d="M641 108 L 641 200"/>
    </g>

    <g fill="#7c5cff" fill-opacity="0.28" stroke="#7c5cff" stroke-width="1">
      <rect x="90" y="152" width="110" height="48"/>
      <rect x="200" y="110" width="56" height="90"/>
      <rect x="256" y="119" width="48" height="81"/>
      <rect x="304" y="157" width="49" height="43"/>
      <rect x="353" y="187" width="61" height="13"/>
      <rect x="414" y="196" width="117" height="4"/>
      <rect x="531" y="198" width="110" height="2"/>
      <rect x="641" y="198.5" width="150" height="1.5"/>
    </g>

    <path d="M90 200 L 820 200" fill="none" stroke="currentColor" stroke-width="1.5"/>

    <g stroke-width="1.6">
      <path d="M259 104 L 259 200" stroke="#0fa07f"/>
      <path d="M340 118 L 340 200" stroke="#0fa07f"/>
      <path d="M533 132 L 533 200" stroke="#e0930f"/>
      <path d="M721 104 L 721 200" stroke="#d64545"/>
      <path d="M778 118 L 778 200" stroke="#d64545" stroke-dasharray="4 3"/>
    </g>
    <g font-size="9.5" font-weight="700">
      <text x="259" y="98" text-anchor="middle" fill="#0fa07f">p50 41 ms</text>
      <text x="340" y="112" text-anchor="middle" fill="#0fa07f">p90 81 ms</text>
      <text x="533" y="126" text-anchor="middle" fill="#e0930f">p99 404 ms</text>
      <text x="721" y="98" text-anchor="middle" fill="#d64545">p99.9 2.0 s</text>
      <text x="800" y="112" text-anchor="middle" fill="#d64545">max 3.1 s</text>
    </g>

    <g fill="currentColor" font-size="8.5" text-anchor="middle" opacity="0.7">
      <text x="90" y="216">10 ms</text><text x="366" y="216">100 ms</text><text x="641" y="216">1 s</text><text x="820" y="216">4 s</text>
    </g>

    <rect x="90" y="230" width="324" height="26" rx="5" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f" stroke-width="1.3"/>
    <text x="252" y="247" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">97.8% of all runs live in here</text>
    <rect x="414" y="230" width="406" height="26" rx="5" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="1.3" stroke-dasharray="5 4"/>
    <text x="617" y="247" text-anchor="middle" font-size="9.5" font-weight="700" fill="#d64545">2.2% of runs, and 100% of the sleep you must budget for</text>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="90" y="288">QUANTILE</text><text x="240" y="288">COMPLETION</text><text x="384" y="288">MULTIPLE OF p50</text><text x="552" y="288">WHAT ACTUALLY LIVES OUT HERE</text>
    </g>
    <path d="M84 294 L 826 294" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.42"/>
    <g fill="currentColor" font-size="9.5">
      <text x="90" y="312">p50</text><text x="240" y="312">41 ms</text><text x="384" y="312" font-weight="700" fill="#0fa07f">1.0x</text><text x="552" y="312">enqueue, dequeue, handle, commit</text>
      <text x="90" y="330">p90</text><text x="240" y="330">81 ms</text><text x="384" y="330" font-weight="700" fill="#0fa07f">2.0x</text><text x="552" y="330">the same path, slightly unlucky</text>
      <text x="90" y="348">p99</text><text x="240" y="348">404 ms</text><text x="384" y="348" font-weight="700" fill="#e0930f">9.9x</text><text x="552" y="348">one redelivery, one backoff</text>
      <text x="90" y="366">p99.9</text><text x="240" y="366">2.0 s</text><text x="384" y="366" font-weight="700" fill="#d64545">48.1x</text><text x="552" y="366">a consumer-group rebalance or a GC pause</text>
      <text x="90" y="384">max</text><text x="240" y="384">3.1 s</text><text x="384" y="384" font-weight="700" fill="#d64545">77.3x</text><text x="552" y="384">the slowest of 200,000</text>
    </g>

    <text x="440" y="416" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">p99.9 is 48x the median. That ratio is the entire problem.</text>
    <text x="440" y="435" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">A sleep sized for the body is wrong constantly; a sleep sized for the tail is wrong-by-waiting on every single run.</text>
    <text x="440" y="450" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.7">Nearest-rank quantiles over 200,000 draws, seed 20260718 — every value printed is a value that was actually observed.</text>
  </g>
</svg>
```

Read the shape rather than the numbers first. **The mass and the width are on opposite sides of the picture.** Half the pixels of that plot cover 2.2% of the observations, and that 2.2% is the only part a sleep is ever sized for. Nothing you would call typical is anywhere near the value you have to wait for.

The ratio that matters is **p99.9 / p50 = 48×**. Not because 48 is a special number — it falls out of the two tails and yours will differ — but because the shape is universal: any pipeline with a retry and a pause in it has a completion-time distribution whose useful tail is one to two orders of magnitude past its median. That is the same tail Phase 8 measures for latency in [Benchmarking & Load Testing](../../08-concurrency-and-performance/14-benchmarking-and-load-testing/); here it is the *test suite* paying for it instead of the user.

### The two-dimensional trap: flakiness × duration

Now put the two costs on the same picture, because arguing about them one at a time is how teams end up with both. Fix a suite of **500 asynchronous assertions**, draw 200 independent builds of it out-of-sample from the same distribution (100,000 test runs per strategy), and measure two things for each waiting strategy: how often a single test flakes, and how long the whole suite takes.

The build-level number is the one that decides whether anybody trusts the suite. A build is green only if **all 500** pass, so a per-test flake rate of *f* gives a green build with probability (1−*f*)^500 — the arithmetic [Flaky Tests: The Trust Arithmetic](../09-flaky-tests/) is built on.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 620" width="100%" style="max-width:840px" role="img" aria-label="A log-log scatter plot of per-test flake rate against total suite time for five waiting strategies across 500 tests. The four fixed sleeps trace a frontier from top-left to bottom-right: sleep at p50 costs 20.3 seconds with a 49.75 percent flake rate, sleep at p90 costs 40.4 seconds at 9.91 percent, sleep at p99 costs 3.4 minutes at 1.02 percent, and sleep at p99.9 costs 16.3 minutes at 0.129 percent. Moving along that frontier trades duration for flakiness and never escapes it. The polling primitive sits alone in the bottom-left corner at 30.7 seconds with a zero percent flake rate, in a region no fixed sleep can reach. The fixed sleep that would be needed for a 99 percent green build is 3.0 seconds per test, 25.1 minutes for the suite. Measured green-build rates over 200 builds: zero percent for the p50 and p90 sleeps, 0.5 percent for p99, 53.5 percent for p99.9, and 100 percent for polling.">
  <defs>
    <marker id="p12-11-frontier-tip" markerUnits="userSpaceOnUse" markerWidth="14" markerHeight="14" refX="8" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10 Z" fill="#e0930f"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">A fixed sleep can move along this curve. It cannot leave it.</text>
    <text x="440" y="45" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">500 asynchronous assertions · 200 builds · 100,000 test runs per strategy · both axes log</text>

    <rect x="100" y="318" width="365" height="47" rx="6" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f" stroke-width="1.4" stroke-dasharray="5 4"/>
    <text x="106" y="312" font-size="8.5" font-weight="700" fill="#0fa07f">fast AND green — no fixed sleep is anywhere in this box</text>

    <g fill="none" stroke="currentColor" stroke-width="1.4"><path d="M100 65 L 100 365"/><path d="M100 365 L 830 365"/></g>
    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.2">
      <path d="M100 95 L 830 95"/><path d="M100 165 L 830 165"/><path d="M100 235 L 830 235"/><path d="M100 305 L 830 305"/>
      <path d="M186 65 L 186 365"/><path d="M465 65 L 465 365"/><path d="M657 65 L 657 365"/>
    </g>
    <g fill="currentColor" font-size="8.5" text-anchor="end" opacity="0.72">
      <text x="94" y="98">100%</text><text x="94" y="168">10%</text><text x="94" y="238">1%</text><text x="94" y="308">0.1%</text><text x="94" y="356">0</text>
    </g>
    <text x="32" y="215" font-size="9" font-weight="700" fill="currentColor" opacity="0.72" transform="rotate(-90 32 215)" text-anchor="middle">PER-TEST FLAKE RATE</text>
    <text x="465" y="400" font-size="9" font-weight="700" fill="currentColor" opacity="0.72" text-anchor="middle">TOTAL SUITE TIME (500 TESTS)</text>
    <g fill="currentColor" font-size="8.5" text-anchor="middle" opacity="0.72">
      <text x="186" y="381">20 s</text><text x="465" y="381">3.4 min</text><text x="657" y="381">16 min</text><text x="770" y="381">30 min</text>
    </g>

    <path d="M186 116 L 270 165 L 465 234 L 645 291" fill="none" stroke="#e0930f" stroke-width="2.6" stroke-dasharray="7 5" marker-end="url(#p12-11-frontier-tip)"/>
    <g fill="#e0930f">
      <circle cx="186" cy="116" r="5.5"/><circle cx="270" cy="165" r="5.5"/><circle cx="465" cy="234" r="5.5"/><circle cx="657" cy="297" r="5.5"/>
    </g>
    <g font-size="9" font-weight="700" fill="#e0930f">
      <text x="196" y="109">sleep(p50) 41 ms · 49.75% · 0% green</text>
      <text x="280" y="158">sleep(p90) 81 ms · 9.91% · 0% green</text>
      <text x="475" y="227">sleep(p99) 404 ms · 1.02% · 0.5% green</text>
      <text x="598" y="292" text-anchor="end">sleep(p99.9) 2.0 s · 0.129% · 53.5% green</text>
    </g>

    <circle cx="200" cy="341" r="8.5" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="2"/>
    <path d="M200 336 L 200 346 M195 341 L 205 341" stroke="#0fa07f" stroke-width="2.2"/>
    <text x="218" y="338" font-size="10.5" font-weight="700" fill="#0fa07f">eventually(10 ms, 10 s)</text>
    <text x="218" y="353" font-size="9" font-weight="700" fill="#0fa07f">30.7 s · 0.000% · 100% green</text>

    <path d="M710 330 L 710 276" fill="none" stroke="#d64545" stroke-width="1.8"/>
    <circle cx="710" cy="330" r="5" fill="#d64545"/>
    <text x="846" y="258" text-anchor="end" font-size="9" font-weight="700" fill="#d64545">the fixed sleep a 99% green build needs:</text>
    <text x="846" y="270" text-anchor="end" font-size="9" font-weight="700" fill="#d64545">3.0 s each — 25.1 min of waiting</text>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="34" y="432">STRATEGY</text><text x="262" y="432">PER-TEST FLAKE</text><text x="418" y="432">SUITE TIME</text><text x="546" y="432">P(GREEN) PREDICTED</text><text x="740" y="432">MEASURED, 200 BUILDS</text>
    </g>
    <path d="M28 438 L 852 438" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.42"/>
    <g font-size="9.5" fill="currentColor">
      <text x="34" y="456">sleep(p50) = 41 ms</text><text x="262" y="456">49.754%</text><text x="418" y="456">20.3 s</text><text x="546" y="456">0.0%</text><text x="740" y="456" font-weight="700" fill="#d64545">0.0%</text>
      <text x="34" y="474">sleep(p90) = 81 ms</text><text x="262" y="474">9.907%</text><text x="418" y="474">40.4 s</text><text x="546" y="474">0.0%</text><text x="740" y="474" font-weight="700" fill="#d64545">0.0%</text>
      <text x="34" y="492">sleep(p99) = 404 ms</text><text x="262" y="492">1.020%</text><text x="418" y="492">3.4 min</text><text x="546" y="492">0.6%</text><text x="740" y="492" font-weight="700" fill="#d64545">0.5%</text>
      <text x="34" y="510">sleep(p99.9) = 2.0 s</text><text x="262" y="510">0.129%</text><text x="418" y="510" font-weight="700" fill="#d64545">16.3 min</text><text x="546" y="510">52.4%</text><text x="740" y="510" font-weight="700" fill="#e0930f">53.5%</text>
      <text x="34" y="528" font-weight="700" fill="#0fa07f">eventually(10 ms, 10 s)</text><text x="262" y="528" font-weight="700" fill="#0fa07f">0.000%</text><text x="418" y="528" font-weight="700" fill="#0fa07f">30.7 s</text><text x="546" y="528">100.0%</text><text x="740" y="528" font-weight="700" fill="#0fa07f">100.0%</text>
    </g>

    <text x="440" y="566" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">Polling beat every sleep that has any chance of a green build, on BOTH axes at once.</text>
    <text x="440" y="585" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">The only sleep that is faster is sleep(p50) at 20.3 s — which produced 0 green builds out of 200.</text>
    <text x="440" y="604" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">Predicted P(green) = (1 − f)^500; measured is the fraction of 200 simulated builds with zero failures. They agree.</text>
  </g>
</svg>
```

Four numbers out of that, in the order they change your mind.

**`sleep(p99.9)` is not safe.** It is the sleep an experienced engineer picks, it costs **16.3 minutes** on this suite, and it still leaves **46.5% of builds red for no reason** — measured 53.5% green over 200 builds, predicted 52.4% from the per-test rate. A 0.129% per-test flake rate sounds like a rounding error and is not, because 500 independent chances to fail is a lot of chances. This is [Flaky Tests](../09-flaky-tests/)' arithmetic arriving at the door of one specific line of code.

**The sleep that *is* safe is absurd.** Solve for the fixed sleep that makes a 500-test build green 99% of the time and you need a per-test success rate of **0.999980** — the **p99.998** of the distribution, which is **3.0 seconds, 74× the median**. Compare that with the maximum of the entire 200,000-sample calibration: **3.1 seconds**. The safe sleep is, to within a rounding error, *the slowest thing that happened in two hundred thousand tries*. The suite cost is **25.1 minutes**.

**And you cannot measure the number you would need.** Estimating a p99.998 took 200,000 observations. A 500-test suite gives you 500. There is no honest procedure by which a team arrives at a correct fixed sleep, which is exactly why the sleep in your repository was arrived at by doubling until the red went away — a search whose stopping condition is *"nobody complained this week"*.

**Polling wins on both axes simultaneously.** `eventually(interval=10 ms, timeout=10 s)` finished in **30.7 seconds** at a **0.000%** flake rate and **200 green builds out of 200**, issuing **5.6 polls per test** on average. It is **49× faster than the safe sleep** and strictly less flaky than all four of them. The single exception is honest and worth stating: `sleep(p50)` is faster, at 20.3 s. It also produced **zero green builds out of 200**. Being fast is not a property of a suite that never goes green.

The reason polling escapes the frontier is structural, not clever. **A fixed sleep pays the worst case on every test; polling pays each test's own latency.** Since 97.8% of runs finish inside 150 ms, the average test costs almost nothing, and the timeout — the thing that has to be sized for the tail — is only ever *paid* by a test that was going to fail anyway.

That reframes the timeout completely. It is not a wait. It is **the point at which you give up**, and it should be set generously (10 s here, 30 s is fine) precisely because a correct system never reaches it.

### `eventually()`: the failure message is the feature

Polling is the easy half, and it is the half every hand-rolled `wait_for` helper gets right. The half they get wrong is what happens when the condition never becomes true.

```python
def eventually(check, *, timeout, interval, clock, probe=None, what="condition"):
    deadline = clock.now() + timeout
    attempts, last = 0, None
    while True:
        attempts += 1
        try:
            value = check()
            if value:
                return Attempted(value, attempts, clock.now() - deadline + timeout)
            last = AssertionError(f"{what} was falsy: {value!r}")
        except Exception as exc:          # the point is to KEEP it, not swallow it
            last = exc
        if clock.now() >= deadline:
            break
        clock.advance(interval)
    detail = f"; {probe()}" if probe else ""
    raise EventuallyFailed(f"{what} never held: {type(last).__name__}: {last} "
                           f"(last of {attempts} attempts over {timeout:.3f}s{detail})") from last
```

Twelve lines, and three of them are the whole difference. The loop **returns the instant the condition holds**, so a passing test costs its own latency. It **keeps the last exception** and re-raises it as the `__cause__`, so the message describes the system rather than the helper. And `probe` is a diagnostic hook run once on failure — dump the queue depth, the dead-letter contents, the row that *is* there.

The `async` variant is the same twelve lines with `await asyncio.sleep(interval)` in place of `clock.advance(interval)`, and it is the one you will actually import; keep the synchronous version too, because a test that drives an HTTP client and then queries a database has no reason to be a coroutine at all.

To measure whether that matters, the program builds five genuinely different broken systems, points one assertion at all five, and asks each waiting style how many of the five it can tell apart.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 476" width="100%" style="max-width:840px" role="img" aria-label="A comparison of three ways of waiting against five different root causes of the same failing assertion. Sleeping for two seconds then asserting produces the bare string AssertionError for all five causes, so one distinct message out of five. A naive polling helper that swallows exceptions produces TimeoutError condition not met within 2.0 seconds for all five, also one out of five. The proper eventually helper, which keeps the last error and runs a diagnostic probe, produces five distinct messages naming the consumer crash, the wrong order id, the stale projection status, the partial write and the unsubscribed worker. On the cost side, across 500 passing tests with the same two-second give-up point, sleep costs 16.7 minutes and eventually costs 32.7 seconds, a 31 times difference for the same verdict.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Five broken systems, one assertion. Which of them can the message name?</text>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="30" y="60">THE ROOT CAUSE</text><text x="330" y="60">sleep(2.0) THEN assert</text><text x="500" y="60">naive eventually()</text><text x="668" y="60">eventually() + last error + probe</text>
    </g>
    <path d="M24 66 L 856 66" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.42"/>

    <g fill="#d64545" fill-opacity="0.13"><rect x="324" y="72" width="164" height="128" rx="5"/><rect x="494" y="72" width="164" height="128" rx="5"/></g>
    <rect x="664" y="72" width="192" height="128" rx="5" fill="#0fa07f" fill-opacity="0.13"/>

    <g fill="currentColor" font-size="9.5">
      <text x="30" y="90">consumer crashed on the payload</text>
      <text x="30" y="115">test asserts an id nobody emitted</text>
      <text x="30" y="140">projection lag: row exists, stale</text>
      <text x="30" y="165">partial write: order without items</text>
      <text x="30" y="190">worker never subscribed</text>
    </g>
    <g font-size="8.5" fill="#d64545" font-weight="700">
      <text x="330" y="90">AssertionError</text><text x="330" y="115">AssertionError</text><text x="330" y="140">AssertionError</text><text x="330" y="165">AssertionError</text><text x="330" y="190">AssertionError</text>
      <text x="500" y="90">TimeoutError: 2.0s</text><text x="500" y="115">TimeoutError: 2.0s</text><text x="500" y="140">TimeoutError: 2.0s</text><text x="500" y="165">TimeoutError: 2.0s</text><text x="500" y="190">TimeoutError: 2.0s</text>
    </g>
    <g font-size="8" fill="#0fa07f" font-weight="700">
      <text x="668" y="90">LookupError + dlq=[ValidationError]</text>
      <text x="668" y="115">LookupError + rows=['o-1043']</text>
      <text x="668" y="140">status is 'pending', want 'paid'</text>
      <text x="668" y="165">0 items on the order, want 2</text>
      <text x="668" y="190">LookupError + unconsumed=1</text>
    </g>

    <path d="M24 208 L 856 208" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.42"/>
    <text x="30" y="228" font-size="10" font-weight="700" fill="currentColor">DISTINCT MESSAGES</text>
    <g font-size="15" font-weight="700">
      <text x="406" y="230" text-anchor="middle" fill="#d64545">1 / 5</text><text x="576" y="230" text-anchor="middle" fill="#d64545">1 / 5</text><text x="760" y="230" text-anchor="middle" fill="#0fa07f">5 / 5</text>
    </g>

    <rect x="24" y="250" width="832" height="60" rx="8" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-opacity="0.55" stroke-width="1.4"/>
    <text x="36" y="269" font-size="9.5" font-weight="700" fill="#7c5cff">what one of those five messages actually says:</text>
    <text x="36" y="286" font-size="8.5" fill="currentColor" opacity="0.94">EventuallyFailed: order o-1042 is paid with 2 items never held: LookupError: no row for order 'o-1042'</text>
    <text x="36" y="300" font-size="8.5" fill="currentColor" opacity="0.94">(last of 41 attempts over 2.000s; read model has 0 row(s) [], dlq=["o-1042: ValidationError(currency='XBT')"])</text>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="30" y="340">THE OTHER HALF: WHAT 500 PASSING TESTS COST, BOTH GIVING UP AT 2.0 s</text>
    </g>
    <path d="M24 346 L 856 346" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.42"/>
    <rect x="152" y="356" width="648" height="20" rx="4" fill="#d64545" fill-opacity="0.30" stroke="#d64545" stroke-width="1.3"/>
    <rect x="152" y="384" width="21" height="20" rx="4" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="1.3"/>
    <g font-size="9.5" fill="currentColor" text-anchor="end"><text x="146" y="370">sleep(2.0)</text><text x="146" y="398">eventually()</text></g>
    <g font-size="10" font-weight="700"><text x="808" y="370" fill="#d64545">16.7 min</text><text x="183" y="398" fill="#0fa07f">32.7 s — every test pays only its own latency</text></g>

    <text x="440" y="434" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">Same verdict, 31x the wall clock — and a message that names one of five systems instead of none.</text>
    <text x="440" y="454" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">A helper that catches the exception and reports its own deadline throws away the only evidence in the room.</text>
    <text x="440" y="472" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">All fifteen combinations fail. The question is never whether the test failed — it is what you do next.</text>
  </g>
</svg>
```

**1 of 5 versus 5 of 5.** A `sleep` followed by a bare `assert` collapses five distinct system states into the string `AssertionError` — Python's assertion rewriting has no sub-expressions to report when the expression is a single call. A naive polling helper does exactly as badly for a different reason: it catches the exception, discards it, and reports its own deadline. `TimeoutError: condition not met within 2.0s` is a fact about the helper. It contains no information about the system, and the four extra lines that keep `last` are the entire difference between an engineer reading the CI log and an engineer trying to reproduce the failure locally.

The cost half of that diagram is the same argument as the previous section, restated at one call site: over 500 passing tests, **16.7 minutes versus 32.7 seconds — 31×**, for an identical verdict.

Two failure modes of polling worth naming before you write one. **Polling with no upper bound on the total suite is not free** — 5.6 queries per test against a real database is 2,800 queries you did not have before; keep the interval at 10–50 ms rather than 1 ms. And **a predicate that is true too early is worse than a sleep**: `eventually(lambda: db.orders.get(id))` returns the moment the row appears, which may be before the projection has filled in its fields. Assert the *final* state, not the first observable one.

### Better than polling: give the test a completion seam

Polling is what you do when you cannot change the system. If you can, do better — because every polling loop is the test guessing at a signal the system already has internally.

Three seams, in increasing order of how much they help:

- **An idempotent status endpoint.** `GET /orders/{id}` returning `{"state": "settled"}` turns a guess into a question with an answer. The test still polls, but it polls something whose meaning is defined rather than inferred.
- **A completion event.** If the worker publishes `order.settled`, the test subscribes and waits on the event rather than on the side effect. One signal, no interval, no query load.
- **The transactional outbox as a test seam.** Phase 6's [Dual Write, the Outbox Pattern & CDC](../../06-messaging-and-pub-sub/10-dual-write-outbox-and-cdc/) exists to make the write and the publish atomic. It also gives the test a table it can read: *the effect and its notification are one row*, so "has this been processed?" becomes a `SELECT`.
- **A test-only drain hook.** `await worker.drain()` — block until the queue is empty and all in-flight handlers have returned. This is the strongest option and the one people resist as "test-only code in production". It is worth it, it is ten lines, and it converts every asynchronous assertion in the suite into a synchronous one.

The rule underneath all four: **if you own the system, do not make the test infer completion. Publish it.** Polling is the fallback for the dependencies you do not control, and it should feel like a fallback.

### Virtual time: twenty minutes of sleeping, run in zero

There is a second, entirely separate class of waiting in an async suite, and no amount of polling helps with it: the waits that are **part of the behaviour under test**. A payment webhook that arrives after 5 seconds. A retry ladder of 1 + 2 + 4 + 8 seconds. A 10-second reconciliation window. That workflow contains **30 seconds of deliberate delay**, and testing it on a real event loop costs 30 seconds because a real event loop honours `asyncio.sleep` — which the program verifies rather than assumes.

The fix is to stop treating time as something that passes and start treating it as a number you control. The program builds a **virtual event loop** in about sixty lines: a heap keyed by virtual time, an awaitable the scheduler understands, and a driver that advances the clock to the next scheduled instant instead of waiting for it.

```python
class _Sleep:
    __slots__ = ("delay",)
    def __init__(self, delay): self.delay = delay
    def __await__(self):
        yield self                      # hand ourselves out to the loop

async def vsleep(delay): await _Sleep(delay)
```

`await` on an object with `__await__` delegates to that generator, so the yielded `_Sleep` propagates straight out to whoever called `coro.send(None)` — which is the loop. [Coroutines & Async/Await from the Ground Up](../../08-concurrency-and-performance/05-coroutines-and-async-await/) builds that machinery; here it is aimed at a test suite. The loop then reschedules the coroutine at `now + delay` and moves on.

Measured over a 40-test suite, each test running the full 30-second workflow: a real loop must spend **20.0 minutes** of wall clock. The virtual loop advanced **20.0 minutes of virtual time in 160 scheduler steps and zero real sleeps**, with all **40/40** tests reaching `settled`.

One honest limitation, because a virtual clock is not a universal solvent. It only controls waits that go **through it**. Code under test that calls `time.sleep()` on a worker thread, or that blocks on a socket with an OS-level timeout, is invisible to the scheduler and will sit there for the full duration regardless. That is an argument for injecting the sleep as a port rather than importing it — the same argument [Designing for Testability](../05-designing-for-testability/) makes about the clock, arriving with a stopwatch attached.

The second thing virtual time buys is less obvious and possibly more valuable: **timeouts become assertable**. Run the workflow to exactly `t = 20.0 s` and the state is `'fulfilment retry backoff'` — exactly, on every run, on every machine. On a real loop that same test takes twenty seconds *and* is still a race, because whether the 20-second mark lands before or after the 20-second step depends on scheduler noise. Determinism here is not a bonus on top of the speed. It is the point; the speed is the bonus.

### Your consumer will see duplicates, so the test must send them

Phase 6's [Delivery Semantics & Idempotent Consumers](../../06-messaging-and-pub-sub/06-delivery-semantics-and-idempotency/) establishes the result this section depends on: exactly-once *delivery* is impossible, exactly-once *effect* is a property of the consumer. A broker that redelivers a message whose acknowledgement it never saw is not malfunctioning — it is doing the only correct thing available to it.

Which means **your consumer will see duplicates in production**, and there is precisely one way for a test to have an opinion about that: send one.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 512" width="100%" style="max-width:840px" role="img" aria-label="Two experiments about delivery assumptions. First, duplicate delivery: 400 payment events with an 8 percent redelivery rate become 436 deliveries of which 36 are repeats. A naive consumer given each event exactly once, which is what a normal test suite does, produces zero wrong balances and a green suite. The same consumer given the duplicates produces 32 of 400 balances wrong and over-credits 357,120 cents, three thousand five hundred seventy one dollars, with the worst single order over-credited by 35,442 cents. An idempotent consumer produces zero wrong balances and suppresses all 36 duplicates. Second, ordering: six events for one order have 720 possible arrival orders and the suite runs exactly one of them. Three invariants hold in all 720 orders; the discounted total invariant fails in 480 of them, 66.7 percent, and the never-ships-before-payment invariant fails in 360, 50 percent. Some invariant fails in 600 of 720 arrival orders, so five random shuffles detect the problem with 100 percent probability.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Two assumptions your suite makes silently: delivered once, and in order.</text>

    <text x="30" y="58" font-size="10.5" font-weight="700" fill="#7c5cff">1 · DUPLICATE DELIVERY — 400 payment_captured events, 8% redelivered = 436 deliveries, 36 repeats</text>
    <path d="M24 64 L 856 64" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.42"/>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="34" y="82">THE CONSUMER, AND WHAT THE TEST DELIVERED</text><text x="470" y="82">BALANCES WRONG</text><text x="626" y="82">OVER-CREDITED</text><text x="756" y="82">VERDICT</text>
    </g>
    <rect x="28" y="88" width="824" height="26" rx="5" fill="#d64545" fill-opacity="0.13"/>
    <rect x="28" y="118" width="824" height="26" rx="5" fill="#d64545" fill-opacity="0.13"/>
    <rect x="28" y="148" width="824" height="26" rx="5" fill="#0fa07f" fill-opacity="0.13"/>
    <g font-size="9.5" fill="currentColor">
      <text x="34" y="105">naive consumer, each event delivered ONCE (the suite you have)</text><text x="470" y="105" font-weight="700" fill="#0fa07f">0 / 400</text><text x="626" y="105">0c</text><text x="756" y="105" font-weight="700" fill="#d64545">GREEN &amp; WRONG</text>
      <text x="34" y="135">naive consumer, duplicates delivered as the broker will</text><text x="470" y="135" font-weight="700" fill="#d64545">32 / 400  (8.0%)</text><text x="626" y="135" font-weight="700" fill="#d64545">357,120c</text><text x="756" y="135" font-weight="700" fill="#0fa07f">RED &amp; RIGHT</text>
      <text x="34" y="165">idempotent consumer (event_id in a seen-set, same transaction)</text><text x="470" y="165" font-weight="700" fill="#0fa07f">0 / 400</text><text x="626" y="165" font-weight="700" fill="#0fa07f">0c</text><text x="756" y="165" font-weight="700" fill="#0fa07f">GREEN &amp; RIGHT</text>
    </g>
    <text x="34" y="192" font-size="9.5" fill="currentColor" opacity="0.92">$3,571.20 over-credited on $42,089.10 of real payments · worst single order 35,442c too much · 36 duplicates suppressed by the key</text>
    <text x="34" y="208" font-size="9.5" font-weight="700" fill="#d64545">Both consumers pass row 1. The test that separates them is one line long.</text>

    <text x="30" y="248" font-size="10.5" font-weight="700" fill="#7c5cff">2 · ARRIVAL ORDER — 6 events for one order, 720 possible arrival orders, the suite runs 1</text>
    <path d="M24 254 L 856 254" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.42"/>
    <text x="34" y="272" font-size="9" fill="currentColor" opacity="0.85">order_created → item_added → item_added → discount_applied → payment_captured → shipped   (all 5 invariants hold in this one)</text>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="34" y="298">THE INVARIANT THE TEST ASSERTS</text><text x="446" y="298">FAILS IN</text><text x="560" y="298">OF 720 ORDERS</text><text x="712" y="298">ORDER-INDEPENDENT?</text>
    </g>
    <path d="M28 304 L 852 304" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.4"/>
    <g font-size="9.5" fill="currentColor">
      <text x="34" y="322">items_total is 4500c</text><text x="446" y="322">0</text><text x="560" y="322">0.0%</text><text x="712" y="322" font-weight="700" fill="#0fa07f">YES</text>
      <text x="34" y="340">item_count is 2</text><text x="446" y="340">0</text><text x="560" y="340">0.0%</text><text x="712" y="340" font-weight="700" fill="#0fa07f">YES</text>
      <text x="34" y="358">discount applied exactly once</text><text x="446" y="358">0</text><text x="560" y="358">0.0%</text><text x="712" y="358" font-weight="700" fill="#0fa07f">YES</text>
      <text x="34" y="376">discounted total is 4050c</text><text x="446" y="376" font-weight="700" fill="#d64545">480</text><text x="560" y="376" font-weight="700" fill="#d64545">66.7%</text><text x="712" y="376" font-weight="700" fill="#d64545">no</text>
      <text x="34" y="394">never ships before payment</text><text x="446" y="394" font-weight="700" fill="#d64545">360</text><text x="560" y="394" font-weight="700" fill="#d64545">50.0%</text><text x="712" y="394" font-weight="700" fill="#d64545">no</text>
    </g>
    <path d="M28 404 L 852 404" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.4"/>
    <g font-size="9.5" fill="currentColor">
      <text x="34" y="422" font-weight="700">ANY of the five fails</text><text x="446" y="422" font-weight="700" fill="#e0930f">600</text><text x="560" y="422" font-weight="700" fill="#e0930f">83.3%</text><text x="712" y="422" font-weight="700">K=5 shuffles → 100%</text>
    </g>

    <text x="440" y="456" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">3 of 5 invariants were genuinely order-independent. Nobody wrote down which 3.</text>
    <text x="440" y="475" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">Five shuffles found it here only because the cheapest dependence fails in 360 of 720. A 2-in-720 dependence needs 1,656.</text>
    <text x="440" y="494" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">Lamport, Time, Clocks, and the Ordering of Events in a Distributed System, CACM 21(7), 1978 — arrival order is not emission order.</text>
  </g>
</svg>
```

The top half is the experiment that matters most, and its first row is the whole point. **A naive consumer, given each event exactly once — which is what your test suite does — produces zero wrong balances and a green build.** Deliver the same 400 events with a realistic 8% redelivery rate and the same consumer gets **32 of 400 balances wrong** and over-credits **357,120c ($3,571.20)** on $42,089.10 of real payments, with one unlucky order over-credited by **35,442c**. The idempotent version — an `event_id` checked against a seen-set inside the same transaction, four lines — gets **0 of 400** wrong and suppresses all **36** duplicates.

Both consumers pass the suite you have. The difference between them is a single line in one test: deliver the event twice.

One detail that is load-bearing and easy to get wrong: the key must be derived from the **business event**, not from the transmission. A key generated by the producer at send time gives every redelivery a fresh key and defeats every dedup mechanism downstream — the trap Phase 6 spells out in full.

### Order is an assumption until you permute it

The bottom half of that diagram is the assumption nobody notices they made. Lamport (*Time, Clocks, and the Ordering of Events in a Distributed System*, CACM 21(7), 1978) is the canonical statement: without something that imposes one, there is no total order of events in a distributed system. Across partitions, retries and parallel consumers, **arrival order is not emission order** — and your projection was written by someone who only ever saw emission order.

Six events for one order have **720** possible arrival orders. Your suite runs one of them. Run all 720 against five invariants and **three are genuinely order-independent** — `items_total`, `item_count`, "discount applied exactly once" — while two are not. "The discounted total is 4050c" fails in **480 of 720 orders (66.7%)**, because the handler applies the discount to whatever the running total happens to be at the moment the event arrives. "Never ships before payment" fails in **360 (50.0%)**, for the obvious reason.

The useful output is not the failure count, it is the split: **you now know which three assertions are safe to make about an unordered stream and which two require a guarantee you must go and obtain** — a partition key, a version check, or a state machine that rejects out-of-order transitions.

And a warning about the detection method, because "just shuffle the events" is about to sound like a complete answer. Some invariant fails in **600 of 720** arrival orders here, so **five random shuffles find it with probability 100%**, confirmed by simulation over 2,000 runs against the exact analytic prediction. That is a property of *this* event set. A dependence that only 2 of 720 orders expose needs **1,656 shuffles** for the same 99% confidence. Shuffling is a policy only once you have computed that number for your own case; [Determinism](../08-determinism-time-randomness-order/) makes the same argument for shuffled *test* order.

### Retries, backoff, and the retry that duplicates the write

A consumer that throws gets retried, backs off, and eventually lands in a dead-letter queue. Phase 6's [Retries, Backoff & Dead-Letter Queues](../../06-messaging-and-pub-sub/08-retries-backoff-and-dead-letter-queues/) builds that path; this is how you assert on it.

The assertions must be **exact**. Not "it retried" — **5 attempts**. Not "it backed off" — **100 ms, 200 ms, 400 ms, 800 ms**, doubling per RFC 6298, *Computing TCP's Retransmission Timer* (2011), §5, for **1,500 ms total** before dead-lettering. Not "the DLQ got something" — **one message, carrying the event id, the attempt count and the last error**. A test that asserts "more than one attempt" passes just as happily against a policy that retries forever, which is how a redelivery storm ships.

But the interesting result is the one that has nothing to do with the retry count.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 480" width="100%" style="max-width:840px" role="img" aria-label="A timeline of a retried message handler where the failure happens after the database write. On attempt one the handler writes a row and then the receipt service times out; the same on attempts two and three; on attempt four the write happens again and the receipt service succeeds, so the message is acknowledged. The result is four rows for one order, 16,800 cents charged instead of 4,200, one email sent, and an empty dead-letter queue because the retry succeeded. With an idempotency key on the write the same sequence produces one row and 4,200 cents. At suite scale, 300 events of which 20 fail twice after the write produce 340 rows instead of 300 and 389,902 cents over-charged, with the dead-letter queue empty in both the broken and the fixed version, so nothing alerts and nothing goes red.">
  <defs>
    <marker id="p12-11-retry-arrow" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#7f7f7f"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">The failure landed AFTER the write. The retry re-ran the whole handler.</text>
    <text x="440" y="45" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">one message · one order · 4,200c · max 5 attempts, 100 ms base, doubling (RFC 6298 §5)</text>

    <path d="M60 118 L 812 118" fill="none" stroke="#7f7f7f" stroke-width="1.6" marker-end="url(#p12-11-retry-arrow)"/>
    <g font-size="8" fill="currentColor" opacity="0.62" text-anchor="middle">
      <text x="240" y="112">wait 100 ms</text><text x="418" y="112">wait 200 ms</text><text x="596" y="112">wait 400 ms</text>
    </g>

    <g stroke-width="1.8">
      <rect x="72" y="128" width="128" height="70" rx="7" fill="#d64545" fill-opacity="0.13" stroke="#d64545"/>
      <rect x="250" y="128" width="128" height="70" rx="7" fill="#d64545" fill-opacity="0.13" stroke="#d64545"/>
      <rect x="428" y="128" width="128" height="70" rx="7" fill="#d64545" fill-opacity="0.13" stroke="#d64545"/>
      <rect x="606" y="128" width="128" height="70" rx="7" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
    </g>
    <g font-size="9.5" font-weight="700" text-anchor="middle" fill="currentColor">
      <text x="136" y="146">attempt 1</text><text x="314" y="146">attempt 2</text><text x="492" y="146">attempt 3</text><text x="670" y="146">attempt 4</text>
    </g>
    <g font-size="8.5" text-anchor="middle">
      <text x="136" y="165" fill="#3553ff" font-weight="700">INSERT row ✓</text><text x="314" y="165" fill="#3553ff" font-weight="700">INSERT row ✓</text><text x="492" y="165" fill="#3553ff" font-weight="700">INSERT row ✓</text><text x="670" y="165" fill="#3553ff" font-weight="700">INSERT row ✓</text>
      <text x="136" y="181" fill="#d64545">receipt svc 504</text><text x="314" y="181" fill="#d64545">receipt svc 504</text><text x="492" y="181" fill="#d64545">receipt svc 504</text><text x="670" y="181" fill="#0fa07f" font-weight="700">receipt svc 200</text>
      <text x="136" y="194" fill="currentColor" opacity="0.7">raise → retry</text><text x="314" y="194" fill="currentColor" opacity="0.7">raise → retry</text><text x="492" y="194" fill="currentColor" opacity="0.7">raise → retry</text><text x="670" y="194" fill="#0fa07f" font-weight="700">ack — SUCCESS</text>
    </g>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="30" y="236">WHAT THE SUITE COULD ASSERT AFTERWARDS</text><text x="500" y="236">NO IDEMPOTENCY KEY</text><text x="700" y="236">KEY ON THE WRITE</text>
    </g>
    <path d="M24 242 L 856 242" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.42"/>
    <g font-size="9.5" fill="currentColor">
      <text x="30" y="260">attempts</text><text x="500" y="260">4</text><text x="700" y="260">4</text>
      <text x="30" y="278">emails sent</text><text x="500" y="278">1</text><text x="700" y="278">1</text>
      <text x="30" y="296">dead-letter queue</text><text x="500" y="296" font-weight="700" fill="#e0930f">0 messages</text><text x="700" y="296" font-weight="700" fill="#e0930f">0 messages</text>
      <text x="30" y="314" font-weight="700">rows written for ONE order</text><text x="500" y="314" font-weight="700" fill="#d64545">4</text><text x="700" y="314" font-weight="700" fill="#0fa07f">1</text>
      <text x="30" y="332" font-weight="700">amount charged</text><text x="500" y="332" font-weight="700" fill="#d64545">16,800c</text><text x="700" y="332" font-weight="700" fill="#0fa07f">4,200c</text>
    </g>

    <rect x="24" y="350" width="832" height="58" rx="8" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-opacity="0.55" stroke-width="1.4"/>
    <text x="36" y="369" font-size="9.5" font-weight="700" fill="#7c5cff">at suite scale — 300 events, 20 of which fail twice after the write:</text>
    <text x="36" y="386" font-size="9.5" fill="currentColor" opacity="0.94">naive worker: 340 rows for 300 events (+40) · 389,902c over-charged · dlq = 0</text>
    <text x="36" y="401" font-size="9.5" fill="currentColor" opacity="0.94">guarded worker: 300 rows for 300 events · 0c over-charged · dlq = 0</text>

    <text x="440" y="436" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">The dead-letter queue is empty in BOTH. The retry worked. Nothing goes red.</text>
    <text x="440" y="456" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">The only evidence is the duplicate row — so the only test that can find it is one that counts rows after a retry.</text>
    <text x="440" y="474" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">Assert the exact schedule too: 100 / 200 / 400 / 800 ms, 5 attempts, 1,500 ms to the DLQ. "It retried" also passes for a retry storm.</text>
  </g>
</svg>
```

This is the bug the retry path actually ships, and it is invisible to every instrument on the box. The handler **writes the row, then calls something downstream that fails**. The retry re-runs the handler from the top — including the write. Four attempts produce **4 rows for 1 order and 16,800c charged instead of 4,200c**, and then attempt 4 succeeds, so the message is acknowledged and **the dead-letter queue is empty**.

Follow what that means for your alerting. DLQ depth: zero. Error rate: recovered. Retry count: within policy. Every dashboard is green, because from the pipeline's point of view *nothing went wrong* — a transient failure was retried and succeeded, exactly as designed. At suite scale, 300 events with 20 failing twice after the write gave **340 rows for 300 events and 389,902c over-charged**, with **dlq = 0 in both the broken and the fixed version**.

**The only evidence this bug produces is a duplicate row.** So the only test that can find it is one that provokes a retry and then *counts rows*, and the assertion that matters is the one about the thing that should **not** have happened twice. That is the same idempotency key from the previous section, applied to the write rather than to the delivery.

### The forgotten `await`, and the task that outlives the test

Two Python-specific hazards, both of which produce green suites over broken systems.

**A coroutine object is truthy.** Calling an `async def` function does not run it; it builds a coroutine object, and a coroutine object has no `__bool__`, so Python falls back to "objects are true". The program points six assertions at a system where every answer is `False` and forgets to `await` all six:

```text
assert order_is_paid('o-1')        type=coroutine  bool=True  coroutine=True
assert charged_amount('o-1')       type=coroutine  bool=True  coroutine=True
      6/6 assertions PASSED against a system where every answer is False
```

**6 of 6 passed.** Awaited, the same call returns `False` and the test fails correctly. Nothing about the failing version is subtle — it is a missing five-letter word, in a test whose name says exactly what it checks, and it produces a suite that cannot fail. The guard is four lines and belongs in your `conftest.py`:

```python
def strict_assert(value):
    if inspect.isawaitable(value):
        raise TypeError("assertion on an un-awaited coroutine — you meant `await`")
    assert value
```

mypy's `truthy-bool` check flags some of these when the annotation is present, and Ruff's `ASYNC` and `RUF006` rules cover the adjacent hazards (blocking calls inside a coroutine, a dangling task). None of them sees a coroutine handed back by a helper you did not annotate, which is why the runtime guard earns its four lines.

**A task can outlive the test that created it.** `asyncio.create_task()` schedules work and returns immediately. If the test finishes before the task fires, the task runs *during a later test* and mutates state that test believes it owns. The program models six tests on the virtual loop — three that spawn a reconciliation task firing 50 ms out, three innocent tests that write a balance and read it back 60 ms later. Without cleanup: **3 of 3 innocent tests corrupted, 3 tasks still scheduled when their own test returned.** With cancel-on-teardown: **0 of 3**.

Notice where the failure lands. Not in the test that leaked the task — in the *next* one, which did nothing wrong. That is why this class of flake gets blamed on the wrong file, and why it moves when the suite is shuffled: it is not a property of a test, it is a property of an *ordering*, which is precisely the signature [Flaky Tests](../09-flaky-tests/) teaches you to recognise. `asyncio.TaskGroup` (Python 3.11+) makes it structurally impossible, because the `async with` block cannot exit until its children are done.

## Build It

`code/async_testing.py` is one file, standard library only, no network, and it exits in under a second. Two runs produce **byte-identical output** — there is no wall-clock value anywhere in it, because a lesson whose numbers change between runs cannot be checked against its own prose. Eight numbered sections map onto the concepts above.

The **completion time** is drawn, not measured, and the reason is determinism: depending on real scheduler behaviour would make the file unreproducible and the tail unreachable in a run this short. Two additive tails on a lognormal body is the smallest honest model of a real pipeline:

```python
def draw_completion(rng: random.Random) -> float:
    t = rng.lognormvariate(math.log(0.040), 0.50)   # ordinary path, median 40 ms
    roll = rng.random()
    if roll < 0.002:
        t += rng.uniform(1.0, 3.0)                  # consumer rebalance / GC stall
    elif roll < 0.022:
        t += rng.uniform(0.15, 0.50)                # one retry with backoff
    return t
```

Quantiles are **nearest-rank, never interpolated**. When the entire argument is about what the tail actually contains, a printed p99.9 that no run ever produced would be a small lie in exactly the wrong place:

```python
idx = min(len(sorted_xs) - 1, max(0, math.ceil(q * len(sorted_xs)) - 1))
return sorted_xs[idx]
```

The **flake rates are measured out-of-sample**, over 200 independent 500-test builds drawn from a different RNG stream than the calibration. That matters more than it sounds: an early version of this file estimated the per-test flake rate from a *single* 500-test suite and disagreed with the measured build-green rate by more than sixteen percentage points, because one suite contains one or two tail observations and the exponent 500 amplifies that sampling error enormously. The build-green column is then reported twice — predicted from (1−f)^500 and measured by counting builds — so the arithmetic is checked against a run rather than trusted.

The **polling model** charges for its own queries, so the comparison is not rigged:

```python
step = interval + POLL_QUERY_COST        # 10 ms + a 1 ms query
n = max(1, math.ceil(c / step))
elapsed = n * step
```

The **virtual loop** is a heap keyed by virtual time. Ordering ties by a monotonic sequence number rather than by whatever the OS did, which is what makes a test on it reproducible rather than merely fast:

```python
if when > self.now:
    self.slept += when - self.now
    self.now = when
self.steps += 1
try:
    yielded = coro.send(None)
except StopIteration:
    continue
if isinstance(yielded, _Sleep):
    heapq.heappush(self._heap, (self.now + yielded.delay, self._seq, coro))
```

Each of the 40 tests gets **its own loop**, because a test suite runs tests in sequence — running all 40 concurrently on one virtual clock would have advanced 30 s of virtual time rather than the full 20.0 minutes, quietly flattering the result by 40×.

The **order-dependence** experiment enumerates all 720 permutations rather than sampling, so the per-invariant failure probabilities are exact and the "how many shuffles do I need" table is arithmetic rather than an estimate. The order-dependent line in the projection is one statement, and it looks completely reasonable:

```python
st.total_at_discount = st.items_total * (100 - ev.amount_cents) // 100
```

Run it:

```bash
python3 phases/12-testing-and-quality/11-testing-async-and-event-driven/code/async_testing.py
```

```console
== 2 · THE TWO-DIMENSIONAL TRAP: FLAKINESS x DURATION ==
    strategy                  per-test flake   suite time   P(build green)   measured
    sleep(p50)   = 41 ms            49.754%       20.3 s            0.0%       0.0%
    sleep(p90)   = 81 ms             9.907%       40.4 s            0.0%       0.0%
    sleep(p99)   = 404 ms            1.020%      3.4 min            0.6%       0.5%
    sleep(p99.9) = 2.0 s             0.129%     16.3 min           52.4%      53.5%
    eventually(10 ms, 10 s)          0.000%       30.7 s          100.0%     100.0%

  what fixed sleep would a 99% green build need?
    per-test success required : 0.999980  (= 0.99 ^ (1/500))
    that is the p99.9980 of the distribution
    which is                  : 3.0 s   (74x the median)
    x 500 tests            : 25.1 min of pure sleeping
    polling reaches the same green rate in 30.7 s — 49x faster.

== 3 · eventually(): THE FAILURE MESSAGE IS THE FEATURE ==
    way of waiting                          distinct messages across the 5 causes
    sleep(2.0) then assert                  1/5   <- every failure looks the same
    naive eventually()                      1/5   <- every failure looks the same
    eventually() with last error + probe    5/5

== 4 · VIRTUAL TIME: 20 MINUTES OF SLEEPING, RUN IN ZERO ==
    40 tests, each awaiting 30 s of workflow
    on a real event loop     : 20.0 min of wall clock, unavoidably
    on the virtual loop      : 20.0 min of VIRTUAL time advanced
                               in 160 scheduler steps, 0 real sleeps
    at t=20.0 s the workflow is at 'fulfilment retry backoff 1+2+4+8' — exactly, every run.

== 5 · DUPLICATE DELIVERY: THE SUITE THAT NEVER SENDS ONE ==
      naive consumer, no duplicates    : 0/400 balances wrong  -> the suite is GREEN
      naive consumer                   : 32/400 balances wrong (8.0%)
      total over-credit                : 357,120c ($3,571.20) on 4,208,910c of real payments
      idempotent consumer              : 0/400 balances wrong, 36 duplicates suppressed

== 6 · ORDER DEPENDENCE: EVERY PERMUTATION OF ONE EVENT SET ==
    invariant                          fails in   of 720   survives all orders?
    items_total is 4500c                      0      0.0%   YES
    discounted total is 4050c               480     66.7%   no
    never ships before payment              360     50.0%   no
    K=5   detects some order dependence in 100.0% of 2000 runs   (predicted 100.0%)

== 7 · RETRY, BACKOFF, DLQ — AND THE RETRY THAT WRITES TWICE ==
      attempts            : 4
      rows written        : 4   <- one order, 4 rows, 16,800c charged
      dlq                 : 0 — the retry SUCCEEDED, so nothing is red
      with an idempotency key on the write: 1 row(s), 4,200c
      naive worker   : 340 rows for 300 events (+40), 389,902c over-charged, dlq=0

== 8 · THE FORGOTTEN await, AND THE TASK THAT OUTLIVES THE TEST ==
      6/6 assertions PASSED against a system where every
      answer is False. A coroutine object is always truthy — it has no
      without teardown cleanup : 3/3 innocent tests corrupted, 3 task(s) still scheduled at test exit
      with cancel-on-teardown  : 0/3 innocent tests corrupted, 0 task(s) left over
```

Two rows in that output are arguments rather than demonstrations. **Section 2's `sleep(p50)` row** is the honest exception to the lesson's own headline: it *is* faster than polling, at 20.3 s, and it produced 0 green builds out of 200. And **section 7's `dlq = 0` appearing in both the broken and the fixed column** is the reason that bug survives — there is no signal anywhere except the row count.

## Use It

**`pytest-asyncio`** is the default. Put `asyncio_mode = auto` in your config and stop decorating every test:

```ini
# pytest.ini
[pytest]
asyncio_mode = auto
asyncio_default_fixture_loop_scope = function
timeout = 60
```

The setting that bites is **event-loop scope**. By default each test gets a fresh loop, which is correct and occasionally maddening: a session-scoped fixture that creates a client bound to the loop from the *first* test will fail on the second with `RuntimeError: attached to a different loop`. The fix is to match scopes — `asyncio_default_fixture_loop_scope = session` alongside a session-scoped connection — and to be deliberate about it, because a shared loop also shares any task you forgot to cancel. Set `asyncio_default_fixture_loop_scope` explicitly; leaving it unset emits a deprecation warning and the default has moved between releases.

**`anyio.pytest_plugin`** is the alternative worth knowing. It runs the same test against asyncio *and* trio via the `anyio_backend` fixture, which is only interesting if you ship a library. For an application, `pytest-asyncio` is fewer moving parts.

**`asyncio.TaskGroup` (3.11+) instead of bare `create_task`.** This is the structural fix for the leak measured above — the `async with` block cannot exit until every child has finished or been cancelled, so a task cannot outlive its test:

```python
async def test_worker_drains():
    async with asyncio.TaskGroup() as tg:
        tg.create_task(worker.run())
        await eventually_async(lambda: repo.get(order_id), timeout=10)
    # nothing from this test is still scheduled here — the block guarantees it
```

If you are on 3.10 or earlier, `asyncio.wait_for` plus an explicit `cancel()` in a fixture teardown is the manual version, and an `asyncio.all_tasks()` assertion in a global teardown will catch what you miss.

**`tenacity` for the polling primitive**, if you would rather not own twelve lines. It gives you `stop_after_delay`, `wait_fixed`/`wait_exponential`, and — the part that matters for this lesson — `reraise=True`, which is what makes it report the last error instead of its own `RetryError`:

```python
from tenacity import retry, stop_after_delay, wait_fixed, retry_if_exception_type

@retry(stop=stop_after_delay(10), wait=wait_fixed(0.05),
       retry=retry_if_exception_type(AssertionError), reraise=True)
def assert_order_settled(order_id):
    row = repo.get(order_id)
    assert row is not None, f"no row for {order_id}"
    assert row.status == "settled", f"status is {row.status}"
```

**Without `reraise=True` you get `RetryError` and lose the diagnosis** — that is the 1-of-5 result from this lesson, delivered by a library instead of by hand. `awaitility` (Python port) and `pytest-timeout` cover adjacent ground; `pytest-timeout` in particular belongs in every async suite as a backstop (`timeout = 60`, `timeout_method = thread`) so that a genuinely hung test fails the job instead of hanging the runner for an hour.

**For time, do not reach for `freezegun`.** A frozen clock cannot test a timeout. What you want is a controllable loop clock, and `pytest-asyncio` plus a custom `EventLoopPolicy` whose `time()` you drive is the stdlib route; `anyio`'s testing utilities and `aiotools`/`asynctest`-style virtual clocks package it. If your workflow's waits go through an injected `sleep` port rather than `asyncio.sleep` directly, you can substitute the virtual clock from this lesson wholesale — which is a good argument for injecting it.

**For the broker: an in-memory fake in every build, testcontainers on a schedule.** `testcontainers-python` will start real Kafka or RabbitMQ in a session-scoped fixture, and it is worth doing — but 30 seconds of container startup does not belong in the loop a developer runs 40 times an hour:

```python
@pytest.fixture(scope="session")
def kafka():
    with KafkaContainer("confluentinc/cp-kafka:7.6.0") as c:
        yield c.get_bootstrap_server()      # once per session

@pytest.fixture                             # once per test: fresh topic, no shared state
def topic(kafka):
    name = f"orders-{uuid.uuid4().hex[:8]}"
    admin(kafka).create_topics([NewTopic(name, num_partitions=2)])
    yield name
```

Session-scoped container, function-scoped data — the same split [Integration Testing Against a Real Database](../06-integration-testing-real-database/) makes for Postgres. Note `num_partitions=2`: a single-partition topic gives you total ordering for free and quietly hides every bug this lesson's permutation experiment found.

The rule from [Test Doubles](../04-test-doubles/) applies exactly: **an in-memory broker fake, governed by one shared contract suite that also runs against the real broker nightly.** The clauses to write are this lesson's list — redelivery, out-of-order arrival, the exact retry schedule, DLQ routing after N attempts — because those are the behaviours a naive fake will not have and your consumer depends on.

**Four rules for an async suite.** In order:

1. **No `sleep` in a test, ever.** Grep for it and delete every one. Replace with `eventually`/`tenacity` against an observable state, timeout generous (10–30 s), interval 10–50 ms. Measured: 30.7 s and 100% green against 16.3 minutes and 53.5%.
2. **Give the system a completion seam** — a status endpoint, a completion event, an outbox row, or a test-only `drain()`. Polling is the fallback for what you do not own.
3. **Deliver every event twice, and once out of order,** in at least one test per consumer. Four lines of test code stood between a green suite and $3,571.20 of over-credit across 400 orders.
4. **Assert the exact retry schedule and count rows after a retry.** `5 attempts / 100-200-400-800 ms / 1 DLQ message`, and a row count — because the retry that duplicates a write leaves an empty DLQ and a clean dashboard.

## Think about it

1. The safe fixed sleep for a 500-test suite came out at **3.0 s**, and the maximum of the entire 200,000-sample calibration was **3.1 s**. Explain why those two numbers are nearly the same, and then say what happens to the safe sleep if the suite grows to 5,000 tests — without re-running the program.
2. `sleep(p50)` was the only strategy faster than polling (**20.3 s** versus 30.7 s) and it produced **0 green builds out of 200**. Construct the circumstance in which you would nonetheless ship the p50 sleep, and name the property of your CI pipeline that would have to be true for it to be defensible.
3. Three of the five invariants held across all **720** arrival orders and two did not. Take one of the two that failed and describe the change to the *system* — not to the test — that would make it order-independent. What does that change cost, and which of the three surviving invariants would it put at risk?
4. The retry-after-write bug produced **340 rows for 300 events** with **dlq = 0** and no error-rate signal at all. You have logs, metrics and traces on this pipeline. Design the single alert that would have caught it in production, and say why the obvious candidates — DLQ depth, error rate, retry count — all fail.
5. Five random shuffles detected the order dependence in this event set with probability **100%**, but a 2-in-720 dependence would need **1,656**. You have a budget of 20 shuffles per CI run. Given the failure probabilities in this lesson's table, what is the honest claim you can make in a code review about a consumer that has survived those 20 shuffles for a month?

## Key takeaways

- **A fixed sleep is a horizontal line drawn across a distribution, and it is wrong on both sides of the line.** Measured on 200,000 completions: p50 **41 ms**, p99.9 **2.0 s** — a **48×** multiple. `sleep(p99.9)` costs **16.3 minutes** across 500 tests and still leaves **46.5% of builds red**, measured over 200 builds.
- **The sleep that is actually safe is roughly the maximum of the sample, and you cannot measure it.** A 99% green 500-test build needs a per-test success rate of **0.999980** — the **p99.998**, which is **3.0 s (74× the median)** against a sample maximum of **3.1 s**, and costs **25.1 minutes**. Estimating that quantile took 200,000 observations; a suite gives you 500.
- **Polling wins on both axes at once.** `eventually(10 ms, 10 s)` finished in **30.7 s** with a **0.000%** flake rate and **200/200 green builds**, at **5.6 polls per test** — **49× faster** than the safe sleep. The one sleep that beat it on time, `sleep(p50)` at 20.3 s, went green **0 times out of 200**.
- **The failure message is the feature, and it is four lines.** Across five genuinely different broken systems, `sleep` + `assert` produced **1 distinct message of 5** and a polling helper that swallowed the exception produced **1 of 5**; keeping the last error and adding a diagnostic probe produced **5 of 5**. Use `reraise=True` if you reach for `tenacity`.
- **Virtual time turns 20 minutes of waiting into zero, and turns a timeout into an assertion.** 40 tests × a 30-second workflow: **20.0 minutes** of virtual time advanced in **160 scheduler steps** and zero real sleeps, with the workflow state at `t = 20.0 s` identical on every run.
- **Your consumer will see duplicates, so the test must send one.** A naive consumer given each event once — which is what your suite does — reported **0/400 balances wrong and a green build**. The same consumer at an 8% redelivery rate got **32/400 wrong** and over-credited **$3,571.20**; four lines of idempotency key took it to **0/400** with 36 duplicates suppressed.
- **Order is an assumption until you enumerate it.** Of five invariants over 720 arrival orders, **3 were genuinely order-independent** and 2 were not — failing in **480 (66.7%)** and **360 (50.0%)** of orders. Five shuffles found it because the cheapest dependence fails half the time; a 2-in-720 dependence needs **1,656 shuffles** for 99% confidence, so compute yours before calling shuffling a policy.
- **The retry that duplicates a write leaves no signal but the row count.** A handler failing *after* its write produced **4 rows and 16,800c for one 4,200c order**, and **dlq = 0** because the retry succeeded. At scale: **340 rows for 300 events, 389,902c over-charged, dlq = 0 in both the broken and the fixed version.**
- **A coroutine object is truthy, and a task can outlive its test.** Six assertions with a forgotten `await` passed **6 of 6** against a system where every answer was `False`. Leaked background tasks corrupted **3 of 3** innocent later tests; `asyncio.TaskGroup` and a four-line `strict_assert` take both to zero.

Next: [Property-Based Testing & Fuzzing](../12-property-based-testing-and-fuzzing/) — generating the arrival orders, payloads and duplicate patterns you would never have thought to write by hand, and shrinking the failure to something you can read.
