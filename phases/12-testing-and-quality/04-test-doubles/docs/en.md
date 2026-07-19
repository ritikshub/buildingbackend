# Test Doubles: Mocks, Stubs, Fakes & the Lies They Tell

> A hand-written mock stayed **green on all twelve releases** of a payment provider that changed underneath it four times. Measured here: **three releases were genuinely green, then nine were green while broken** — and at the worst of them **1,902 of 2,000 real orders (95.1%) got the wrong outcome** with the suite still reporting zero failures. One renamed status string cost **90.7% of a day's traffic**. Then the fix, measured on the same twelve releases: a **shared contract suite** run against the double *and* the real thing took defect exposure from **22 release-months to 0** — and a bare `Mock()` caught **1 of 7** test mistakes where `create_autospec()` caught 5.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Anatomy of a Unit Test](../03-anatomy-of-a-unit-test/), [Request Validation & Error Contracts](../../02-api-design/03-request-validation-error-contracts/)
**Time:** ~75 minutes

## The Problem

It is 11:20 on a Tuesday and the payments integration goes live behind a feature flag. You have earned this. The suite is green — every test, every time — and the checkout module has more tests than it has lines. The flag goes to 5% of traffic.

**11:24 — the first real order.** `POST /orders` returns `500`. So does the second. So does every one after it. The error in the log is not a timeout, not a credential problem, not a rate limit:

```text
TransportError: unknown status 'succeeded'
```

Here is the code that raised it, which has been under test since the day it was written:

```python
if body["status"] == "success":
    return ChargeOutcome(ok=True, charge_id=body["id"], receipt=body["receipt_url"])
if body["status"] == "declined":
    return ChargeOutcome(ok=False, decline_code=body["decline_code"])
raise TransportError(f"unknown status {body['status']!r}")
```

And here is the double every one of those tests ran against, in `tests/doubles.py`, last modified nineteen months ago:

```python
return 200, {"id": "ch_test_1", "status": "success",
             "receipt_url": "https://pay.example/r/ch_test_1"}
```

The provider returns `"succeeded"`. The double returns `"success"`. Both files were written by the same person on the same afternoon from the same skim of the same documentation page, and **the test and the code are wrong in exactly the same way**, which is precisely why the test passes. A test that agrees with the bug is not a check on the code. It is a second copy of it.

**11:31 — someone finds the changelog.** The rename shipped in **release 4**. It is now release 12. The provider has since made three more changes: `receipt_url` became optional and is omitted on small charges, validation errors moved from `400` to `422`, and one request in four now comes back `429` and expects a retry. None of them is exotic. Every one is the kind of change a provider considers minor, publishes in a changelog, and reasonably expects a client to absorb.

**Your suite went green through all four.** Not "mostly green" — *identically* green, 8 out of 8 on the scenario set measured in this lesson, on every single release from R1 to R12, because nothing in it was ever connected to the provider at all. Run the same eight scenarios against the real provider and by R12 **seven of the eight fail**. Run a realistic 2,000-order day through it and **1,902 orders get the wrong outcome**.

The uncomfortable part is not that the double was wrong. Doubles go wrong; that is a normal, expected, survivable condition. The uncomfortable part is the arithmetic on the *duration*: the double drifted at R4 and nothing anywhere in your organisation was capable of noticing until a customer's card did.

> **A test double is a second implementation of someone else's contract — written by you, from your reading of their docs, and verified by nobody.**

Everything in this lesson follows from that sentence. Not "mocks are bad": mocks are fine, and sometimes they are the only thing that works. The problem is unverified doubles, and the fix is not to use fewer doubles. It is to point something at them.

## The Concept

### The five doubles, precisely

Almost everyone says "mock" for all five of these. The names come from Gerard Meszaros, *xUnit Test Patterns: Refactoring Test Code* (Addison-Wesley, 2007), and the distinction is worth holding because **it decides what your test is allowed to prove**.

A **test double** is any object you put in place of a real dependency for the duration of a test — the name is from stunt doubles in film, and it is a good analogy: it looks like the real thing from the camera angle the test happens to use.

- A **dummy** is never called. It exists to fill a parameter that the code path under test does not touch.
- A **stub** returns canned answers. It has no memory and no logic. It lets you drive the code down a branch.
- A **spy** is a stub that records what happened, so the test can inspect the calls *afterwards*.
- A **mock** carries the expectation itself. You tell it what must happen before the code runs, and it fails **at the call site** rather than at the end of the test.
- A **fake** is a real, working implementation with a shortcut — an in-memory repository, an in-process queue, a `sqlite3` database standing in for Postgres. It has state, it has behaviour, and you can ask it questions.

Implemented by hand against one `PaymentGateway` port, the program prints exactly what each one buys you:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 396" width="100%" style="max-width:840px" role="img" aria-label="A matrix of the five kinds of test double against what a test using each one is able to assert. A dummy is never called and asserts nothing. A stub returns a canned answer and lets the test assert on the output only. A spy records the calls so the test can assert on the input after the fact. A mock carries the expectation before the call and fails at the call site, reporting expected charge with amount 9999 but got 2500. Only the fake, a working in-memory implementation, lets the test assert on state, which is why only the fake can answer whether a customer was charged twice: measured, one charge recorded after two place-order calls with the same idempotency key.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Five doubles. The question is not how each is built — it is what a test can prove.</text>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="30" y="62">THE DOUBLE</text><text x="130" y="62">WHAT IT IS</text><text x="482" y="62" text-anchor="middle">INPUT</text><text x="566" y="62" text-anchor="middle">OUTPUT</text><text x="654" y="62" text-anchor="middle">STATE</text><text x="778" y="62" text-anchor="middle">FAILS AT THE CALL</text>
    </g>
    <path d="M24 70 L 856 70" fill="none" stroke="currentColor" stroke-width="1.3" opacity="0.45"/>

    <rect x="24" y="74" width="832" height="36" rx="6" fill="#7f7f7f" fill-opacity="0.10"/>
    <rect x="24" y="146" width="832" height="36" rx="6" fill="#7f7f7f" fill-opacity="0.10"/>
    <rect x="24" y="218" width="832" height="36" rx="6" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f" stroke-width="1.6"/>

    <g font-size="11" font-weight="700">
      <text x="30" y="97" fill="#7f7f7f">dummy</text><text x="30" y="133" fill="#e0930f">stub</text><text x="30" y="169" fill="#e0930f">spy</text><text x="30" y="205" fill="#3553ff">mock</text><text x="30" y="241" fill="#0fa07f">fake</text>
    </g>
    <g font-size="9.5" fill="currentColor" opacity="0.9">
      <text x="130" y="97">fills a parameter; never called</text><text x="130" y="133">a canned answer, no memory, no logic</text><text x="130" y="169">a stub that records every call it received</text><text x="130" y="205">carries the expectation; verified as it happens</text><text x="130" y="241">a working implementation, in memory</text>
    </g>

    <g font-size="9.5" text-anchor="middle" fill="currentColor">
      <text x="482" y="97" opacity="0.4">—</text><text x="566" y="97" opacity="0.4">—</text><text x="654" y="97" opacity="0.4">—</text><text x="778" y="97" opacity="0.4">n/a</text>
      <text x="482" y="133" opacity="0.4">—</text><text x="566" y="133" font-weight="700" fill="#0fa07f">yes</text><text x="654" y="133" opacity="0.4">—</text><text x="778" y="133" opacity="0.4">no</text>
      <text x="482" y="169" font-weight="700" fill="#0fa07f">after</text><text x="566" y="169" font-weight="700" fill="#0fa07f">yes</text><text x="654" y="169" opacity="0.4">—</text><text x="778" y="169" opacity="0.4">no</text>
      <text x="482" y="205" font-weight="700" fill="#3553ff">before</text><text x="566" y="205" font-weight="700" fill="#0fa07f">yes</text><text x="654" y="205" opacity="0.4">—</text><text x="778" y="205" font-weight="700" fill="#3553ff">yes</text>
      <text x="482" y="241" font-weight="700" fill="#0fa07f">after</text><text x="566" y="241" font-weight="700" fill="#0fa07f">yes</text><text x="654" y="241" font-weight="700" fill="#0fa07f">yes</text><text x="778" y="241" opacity="0.4">no</text>
    </g>

    <rect x="24" y="272" width="832" height="56" rx="8" fill="#3553ff" fill-opacity="0.08" stroke="#3553ff" stroke-opacity="0.5" stroke-width="1.4"/>
    <text x="36" y="291" font-size="9.5" font-weight="700" fill="#3553ff">the mock reports at the call site, which is the one thing only a mock does:</text>
    <text x="36" y="309" font-size="9" fill="currentColor" opacity="0.92">expected charge('idem-A0001', 9999, 'usd', 'ok'), got charge('idem-A0001', 2500, 'usd', 'ok')</text>
    <text x="36" y="322" font-size="8.5" fill="currentColor" opacity="0.72">a spy would have reported the same mismatch — but only after the code under test had already finished running.</text>

    <text x="440" y="352" text-anchor="middle" font-size="11.5" font-weight="700" fill="#0fa07f">Only the fake can answer "was this customer charged twice?"</text>
    <text x="440" y="370" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">Measured: two place_order calls, same idempotency key — 1 charge recorded, amount 2500c. A stub has nowhere to put the first one.</text>
    <text x="440" y="388" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.75">Meszaros, xUnit Test Patterns: Refactoring Test Code, Addison-Wesley, 2007.</text>
  </g>
</svg>
```

Read the STATE column. It has one `yes` in it, and that single column is most of this lesson's argument. "Was this customer charged twice?" is a question about *state*, and four of the five doubles have nowhere to keep the first charge, so four of the five make that assertion literally impossible to write. In the program the fake answers it directly: two `place_order` calls with the same idempotency key produce **1 charge recorded, amount 2500c**.

Note also what the mock column buys and what it costs. Failing *at the call site* is genuinely valuable — the stack trace points at the line that made the wrong call, not at an assertion forty lines later. That is the legitimate case for a mock, and it is narrower than most suites assume.

### A double is a second implementation of someone else's contract

Strip the vocabulary away and look at what you have actually built. Somewhere in your repository there is a file that answers HTTP requests with JSON bodies, chooses status codes, decides which fields appear, and models idempotency. That is a server. You wrote it. You maintain it. It is a **second implementation of the provider's API**, and its only specification is what you remembered from the docs on the day you wrote it.

Now ask the question you would ask about any other piece of production code: **what tests it?** For the code under test, the answer is the suite. For the double, the answer is nothing. It is the only implementation in your repository with no verification of any kind, and it is the one on which every other verdict depends.

This is the whole failure mode, and it has a specific shape worth naming: **the double and the code drift together, from the same misunderstanding, so the suite's agreement is guaranteed rather than earned**. In the incident above, the mock said `"success"` and the parser looked for `"success"`, and there is no possible provider behaviour that makes that test fail — including the correct one.

### Mock drift, measured across twelve releases

Here is the experiment. One payment provider, twelve releases. Four changes land, each realistic, each announced:

| release | the change | what a client must do |
|---|---|---|
| R4 | success status renamed `"success"` → `"succeeded"` | read the new string |
| R6 | `receipt_url` becomes optional, omitted below 500c | tolerate an absent field |
| R9 | validation errors move from `400 {"error": …}` to `422 {"errors": […]}` | handle a new status and shape |
| R11 | one key in four returns `429` on first attempt | retry |

`422 Unprocessable Content` and `Retry-After` are defined in RFC 9110, *HTTP Semantics* (2022), §15.5.21 and §10.2.3; `429 Too Many Requests` in RFC 6585, *Additional HTTP Status Codes* (2012), §4. None of these is a hostile change. Two of them are the provider *improving* their API.

Against that, two things run. The CI suite runs eight scenarios against a hand-written stub frozen at R1. Production runs the same code against the provider. Nothing compares them.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 520" width="100%" style="max-width:840px" role="img" aria-label="A line chart over twelve provider releases. The dashed blue line is what continuous integration reports against a frozen hand-written stub: eight of eight scenarios green, one hundred percent, flat across all twelve releases. The solid line is what production actually does against the real provider: one hundred percent correct for releases one to three, then it collapses to 9.3 percent at release four when the success status string is renamed, to 5.8 percent at release nine when validation errors become 422, and to 4.9 percent at release eleven when retries become required. Three releases were genuinely green and nine were green while broken. At the worst release 1902 of 2000 orders received the wrong outcome.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Twelve releases. The suite never moved once.</text>
    <text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">same eight scenarios, same code — only the thing underneath the adapter changes</text>

    <g fill="none" stroke="currentColor" stroke-width="1.4"><path d="M88 300 L 830 300"/><path d="M88 300 L 88 72"/></g>
    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.4">
      <path d="M83 300 L 88 300"/><path d="M83 245 L 88 245"/><path d="M83 190 L 88 190"/><path d="M83 135 L 88 135"/><path d="M83 80 L 88 80"/>
    </g>
    <g fill="currentColor" font-size="8.5" text-anchor="end" opacity="0.72">
      <text x="78" y="303">0%</text><text x="78" y="248">25%</text><text x="78" y="193">50%</text><text x="78" y="138">75%</text><text x="78" y="83">100%</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.1" stroke-dasharray="3 5" opacity="0.35">
      <path d="M288 72 L 288 300"/><path d="M416 72 L 416 300"/><path d="M608 72 L 608 300"/><path d="M736 72 L 736 300"/>
    </g>

    <path d="M96 80 L 800 80" fill="none" stroke="#3553ff" stroke-width="3" stroke-dasharray="7 5"/>
    <path d="M96 80 L 160 80 L 224 80 L 288 279.5 L 352 279.5 L 416 279.5 L 480 279.5 L 544 279.5 L 608 287.2 L 672 287.2 L 736 289.2 L 800 289.2" fill="none" stroke="#d64545" stroke-width="2.8" stroke-linejoin="round"/>
    <path d="M96 80 L 160 80 L 224 80" fill="none" stroke="#0fa07f" stroke-width="4"/>
    <g fill="#d64545"><circle cx="288" cy="279.5" r="3.8"/><circle cx="608" cy="287.2" r="3.8"/><circle cx="736" cy="289.2" r="3.8"/></g>
    <g fill="#0fa07f"><circle cx="96" cy="80" r="3.8"/><circle cx="160" cy="80" r="3.8"/><circle cx="224" cy="80" r="3.8"/></g>

    <g fill="currentColor" font-size="8.5" text-anchor="middle" opacity="0.75">
      <text x="96" y="318">R1</text><text x="160" y="318">R2</text><text x="224" y="318">R3</text><text x="288" y="318">R4</text><text x="352" y="318">R5</text><text x="416" y="318">R6</text><text x="480" y="318">R7</text><text x="544" y="318">R8</text><text x="608" y="318">R9</text><text x="672" y="318">R10</text><text x="736" y="318">R11</text><text x="800" y="318">R12</text>
    </g>

    <text x="440" y="66" text-anchor="middle" font-size="9.5" font-weight="700" fill="#3553ff">what CI reports: 8/8 green, every release</text>
    <text x="330" y="245" font-size="9.5" font-weight="700" fill="#d64545">what production does</text>
    <text x="330" y="259" font-size="9" fill="#d64545" opacity="0.9">9.3% of orders correct</text>
    <text x="218" y="100" font-size="9" font-weight="700" fill="#0fa07f" text-anchor="end">they agree — 3 releases</text>
    <text x="812" y="292" font-size="9" font-weight="700" fill="#d64545">4.9%</text>

    <rect x="24" y="336" width="832" height="112" rx="9" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4"/>
    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="38" y="354">THE CHANGE THE PROVIDER SHIPPED</text><text x="524" y="354">LANDS</text><text x="596" y="354">SUITE</text><text x="676" y="354">% OF A 2,000-ORDER DAY WRONG</text>
    </g>
    <g fill="currentColor" font-size="9.5">
      <text x="38" y="374">success status renamed "success" → "succeeded"</text><text x="524" y="374" font-weight="700">R4</text><text x="596" y="374" fill="#0fa07f" font-weight="700">8/8</text><text x="676" y="374" font-weight="700" fill="#d64545">90.7%</text>
      <text x="38" y="393">receipt_url becomes optional below 500c</text><text x="524" y="393" font-weight="700">R6</text><text x="596" y="393" fill="#0fa07f" font-weight="700">8/8</text><text x="676" y="393" font-weight="700" fill="#d64545">36.1%</text>
      <text x="38" y="412">validation error 400 → 422</text><text x="524" y="412" font-weight="700">R9</text><text x="596" y="412" fill="#0fa07f" font-weight="700">8/8</text><text x="676" y="412" font-weight="700" fill="#e0930f">3.5%</text>
      <text x="38" y="431">one key in four needs a retry (429)</text><text x="524" y="431" font-weight="700">R11</text><text x="596" y="431" fill="#0fa07f" font-weight="700">8/8</text><text x="676" y="431" font-weight="700" fill="#d64545">25.5%</text>
    </g>

    <text x="440" y="474" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">3 releases genuinely green, then 9 green while broken — 75% of the year.</text>
    <text x="440" y="494" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">Worst release: 1,902 of 2,000 orders (95.1%) got the wrong outcome. The suite reported 0 failures.</text>
    <text x="440" y="512" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.7">RFC 9110 §15.5.21 (422 Unprocessable Content), §10.2.3 (Retry-After) · RFC 6585 §4 (429 Too Many Requests)</text>
  </g>
</svg>
```

Three numbers from that chart are worth saying out loud.

**Three releases of genuine green, then nine of theatre.** The stub was a faithful model of the provider for R1, R2 and R3. From R4 it was fiction, and the suite could not tell the difference because it was never in a position to. **Releases-to-first-silent-failure: 3.** After that, **9 of 12 releases were green while production was broken — 75%.**

**One renamed string cost 90.7% of a day.** Run each change in isolation and the status rename alone puts **90.7% of a 2,000-order day** on the wrong path — every successful charge becomes a `500`. Compare that with the `400 → 422` change at **3.5%**: same class of change, same "minor" label in the changelog, twenty-six times the damage. You cannot rank these by how they read in a release note. You can only rank them by measuring, which requires something that talks to the provider.

**The blast radius does not correlate with the test-suite damage either.** The `429` change broke exactly **1 of 8 scenarios** and **25.5% of the day**, because the scenario set happened to contain one order id in the rate-limited bucket while a quarter of real orders are. A scenario count is a sample; it is not a traffic estimate, and a suite that "mostly passes" against a new release is telling you about your fixtures, not about your users.

### The contract suite: one set of clauses, two implementations

Now the fix, and it is the senior-level idea in the lesson.

The problem was never that the double existed. The problem is that the double was an *unverified* implementation. So verify it — with the only thing that can possibly do the job: **one shared suite of assertions about the provider's behaviour, executed against both the double and the real provider.** Same clauses, two targets. When the two disagree, the double has drifted, and you know it before your customers do.

Each clause is one request and one predicate over the response:

```python
("success status is the string 'success'",
 clause("contract-fixture-01", 2500, "usd", "ok",
        lambda c, b: c == 200 and b.get("status") == "success")),
```

This is the same relationship you will meet in [Contract Testing](../10-contract-testing/) at a larger scale — there, the contract sits between *two services* and two teams negotiate it. Here it sits between **your double and the real dependency**, and both sides of it are yours. The mechanism is identical and the reason is identical: an interface nobody checks is a guess, and guesses expire.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 512" width="100%" style="max-width:840px" role="img" aria-label="A diagram of the contract loop. One contract suite in the centre runs against two targets: our in-memory fake on the left, in every CI build in milliseconds, and the provider's real sandbox on the right, nightly over the network. When the two disagree the fake has drifted. The measured detection table below shows that the frozen hand-written stub never detected any of the four provider changes, contract version one detected two of four, and contract version two detected all four at the release each landed. Exposure falls from twenty-two defect-releases and nine green-while-broken releases for the frozen stub, to nine and seven for contract version one, to zero and zero for contract version two.">
  <defs>
    <marker id="p12-04-loop-a" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#7c5cff"/></marker>
    <marker id="p12-04-loop-b" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">One suite of clauses. Two implementations. Divergence is the signal.</text>

    <rect x="330" y="56" width="220" height="62" rx="10" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff" stroke-width="2"/>
    <text x="440" y="79" text-anchor="middle" font-size="11.5" font-weight="700" fill="#7c5cff">THE CONTRACT SUITE</text>
    <text x="440" y="96" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.9">8 clauses: one request each,</text>
    <text x="440" y="109" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.9">one predicate over the response</text>

    <g fill="none" stroke="#7c5cff" stroke-width="2">
      <path d="M330 87 L 224 87" marker-end="url(#p12-04-loop-a)"/><path d="M550 87 L 656 87" marker-end="url(#p12-04-loop-a)"/>
    </g>

    <rect x="34" y="56" width="190" height="62" rx="10" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f" stroke-width="2"/>
    <text x="129" y="79" text-anchor="middle" font-size="11" font-weight="700" fill="#e0930f">your in-memory fake</text>
    <text x="129" y="96" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.9">every build, milliseconds,</text>
    <text x="129" y="109" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.9">no network, no credentials</text>

    <rect x="656" y="56" width="190" height="62" rx="10" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f" stroke-width="2"/>
    <text x="751" y="79" text-anchor="middle" font-size="11" font-weight="700" fill="#0fa07f">the provider's sandbox</text>
    <text x="751" y="96" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.9">nightly, slow, over the wire,</text>
    <text x="751" y="109" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.9">and the only source of truth</text>

    <path d="M224 138 L 656 138" fill="none" stroke="#d64545" stroke-width="1.8" stroke-dasharray="6 4" marker-end="url(#p12-04-loop-b)"/>
    <text x="440" y="132" text-anchor="middle" font-size="10" font-weight="700" fill="#d64545">the two answers differ → the fake has drifted → update it, and your unit suite goes red on its own</text>

    <text x="440" y="176" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">measured: which guard notices each provider change, and when</text>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="38" y="204">THE PROVIDER CHANGE</text><text x="392" y="204">LANDS</text><text x="470" y="204">FROZEN STUB</text><text x="608" y="204">CONTRACT v1</text><text x="736" y="204">CONTRACT v2</text>
    </g>
    <path d="M30 210 L 850 210" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.4"/>
    <g fill="currentColor" font-size="9.5">
      <text x="38" y="230">status string renamed</text><text x="392" y="230" font-weight="700">R4</text><text x="470" y="230" font-weight="700" fill="#d64545">never</text><text x="608" y="230" font-weight="700" fill="#0fa07f">R4</text><text x="736" y="230" font-weight="700" fill="#0fa07f">R4</text>
      <text x="38" y="250">receipt_url now optional</text><text x="392" y="250" font-weight="700">R6</text><text x="470" y="250" font-weight="700" fill="#d64545">never</text><text x="608" y="250" font-weight="700" fill="#d64545">never</text><text x="736" y="250" font-weight="700" fill="#0fa07f">R6</text>
      <text x="38" y="270">validation error 400 → 422</text><text x="392" y="270" font-weight="700">R9</text><text x="470" y="270" font-weight="700" fill="#d64545">never</text><text x="608" y="270" font-weight="700" fill="#0fa07f">R9</text><text x="736" y="270" font-weight="700" fill="#0fa07f">R9</text>
      <text x="38" y="290">429 retry now required</text><text x="392" y="290" font-weight="700">R11</text><text x="470" y="290" font-weight="700" fill="#d64545">never</text><text x="608" y="290" font-weight="700" fill="#d64545">never</text><text x="736" y="290" font-weight="700" fill="#0fa07f">R11</text>
      <text x="38" y="312" font-weight="700">CHANGES CAUGHT</text><text x="470" y="312" font-weight="700" fill="#d64545">0 of 4</text><text x="608" y="312" font-weight="700" fill="#e0930f">2 of 4</text><text x="736" y="312" font-weight="700" fill="#0fa07f">4 of 4</text>
    </g>

    <rect x="30" y="332" width="820" height="104" rx="9" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4"/>
    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="44" y="352">GUARD</text><text x="240" y="352">FIRST SILENT RELEASE</text><text x="470" y="352">DEFECT-RELEASES EXPOSED</text><text x="722" y="352">GREEN WHILE BROKEN</text>
    </g>
    <g fill="currentColor" font-size="10">
      <text x="44" y="374" font-weight="700" fill="#d64545">frozen stub</text><text x="240" y="374">R4</text><text x="470" y="374" font-weight="700" fill="#d64545">22</text><text x="722" y="374" font-weight="700" fill="#d64545">9 of 12</text>
      <text x="44" y="396" font-weight="700" fill="#e0930f">contract v1 (6 clauses)</text><text x="240" y="396">R6</text><text x="470" y="396" font-weight="700" fill="#e0930f">9</text><text x="722" y="396" font-weight="700" fill="#e0930f">7 of 12</text>
      <text x="44" y="418" font-weight="700" fill="#0fa07f">contract v2 (8 clauses)</text><text x="240" y="418">none</text><text x="470" y="418" font-weight="700" fill="#0fa07f">0</text><text x="722" y="418" font-weight="700" fill="#0fa07f">0 of 12</text>
    </g>

    <text x="440" y="464" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">Two extra clauses took exposure from 22 release-months to 0.</text>
    <text x="440" y="484" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">And v1 missing two of four is the honest half: a contract covers exactly what it exercises, and nothing else.</text>
    <text x="440" y="504" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">The fake passes its own contract 8/8. That proves nothing until the same clauses run against the provider.</text>
  </g>
</svg>
```

The loop closes in a way that is worth following all the way round, because it is what makes the technique practical rather than merely correct.

1. The contract runs nightly against the provider's sandbox and **goes red at R4**.
2. You update the fake — one line: the success status is now `"succeeded"`.
3. Your ordinary unit suite, which runs against the fake in milliseconds with no network, **goes red on its own**. Measured: the fake synced to R1 gives **8/8**; synced to R4 it gives **3/8** — *identical to the real provider at R4, which also gives 3/8*.
4. You fix the parser. The suite goes green because the code is right, not because the double agrees with it.

Step 3 is the payoff. After one nightly contract run you can reproduce a production outage **offline, on a laptop, with no vendor sandbox in the loop**, and every subsequent build of every developer inherits that knowledge for free. The contract keeps the fake honest; the fake keeps the suite fast. Neither works alone.

### A contract only covers what it exercises

The measurement contains a result that is more useful than a clean win, and it is worth dwelling on because it is where teams get burned after adopting contract testing and believing it is finished.

**Contract v1 — six perfectly reasonable clauses — caught only two of the four changes.** It missed the optional `receipt_url` and it missed the `429`. Not through any subtlety: v1's receipt clause charges **2500c** and the provider only drops the receipt **below 500c**, and none of v1's six fixture keys happen to land in the rate-limited bucket (`contract-fixture-11` does). The clause set never asked the two questions whose answers had changed.

That is a general property, not an accident of this simulation. **A contract is a set of examples, and an example only detects a change on the path it walks.** The two extra clauses in v2 — one charge under 500c, one key in the rate-limited bucket — are the entire difference between catching 2 of 4 and catching 4 of 4, and between **9 defect-releases exposed and 0**.

The practical rule that follows: **derive your contract's fixtures from what your code actually relies on, not from what looks representative.** If a branch in your adapter reads `body["receipt_url"]`, a clause must exist that exercises the case where it might not be there. In [Contract Testing](../10-contract-testing/) this becomes consumer-driven contract generation — the consumer's own tests record what it used — and that is precisely the mechanism that stops a human from having to remember.

### `Mock()` will agree with anything you say

Python's `unittest.mock.Mock` is superb and its default configuration is a trap, for one specific reason: **a bare `Mock()` manufactures any attribute you ask for and accepts any call signature you offer.**

```text
type(Mock().charge_card)   = Mock      # a method that does not exist
bool(Mock().anything)      = True      # an attribute that does not exist, and it is truthy
Mock().charge()            = Mock      # zero arguments to a four-argument method
```

Every one of those is a test that can never fail. So: seven mistakes a real test actually makes, run against four ways of building the double.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 432" width="100%" style="max-width:840px" role="img" aria-label="A grid measuring seven common test mistakes against four ways of constructing a double. A bare Mock caught one of seven, catching only the misspelled assertion. Mock with spec caught three of seven, adding the renamed method and the attribute that does not exist. create_autospec caught five of seven, adding the wrong arity and the wrong keyword argument, both as TypeError. create_autospec with spec_set caught six of seven, adding assignment of a field the port does not have. No configuration catches an assertion that is referenced but never called, because a bound method is truthy — only a linter sees that one.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Seven mistakes a real test makes. "silent" means the test passed and proved nothing.</text>

    <g font-size="8.5" font-weight="700" text-anchor="middle" fill="currentColor" opacity="0.7">
      <text x="456" y="72">Mock()</text><text x="568" y="72">Mock(spec=…)</text><text x="680" y="72">create_autospec</text><text x="792" y="72">+ spec_set=True</text>
    </g>
    <path d="M24 78 L 856 78" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.42"/>

    <g fill="currentColor" font-size="9.5" text-anchor="end">
      <text x="392" y="103">method renamed in production</text><text x="392" y="136">call with too few arguments</text><text x="392" y="169">keyword argument that does not exist</text><text x="392" y="202">reads an attribute that does not exist</text><text x="392" y="235">misspelled assertion (assert_caled_…)</text><text x="392" y="268">assertion referenced, never called</text><text x="392" y="301">assigns a field the port does not have</text>
    </g>

    <g fill="#d64545" fill-opacity="0.16" stroke="#d64545" stroke-width="1.2">
      <rect x="403" y="86" width="106" height="24" rx="4"/><rect x="403" y="119" width="106" height="24" rx="4"/><rect x="515" y="119" width="106" height="24" rx="4"/><rect x="403" y="152" width="106" height="24" rx="4"/><rect x="515" y="152" width="106" height="24" rx="4"/><rect x="403" y="185" width="106" height="24" rx="4"/><rect x="403" y="251" width="106" height="24" rx="4"/><rect x="515" y="251" width="106" height="24" rx="4"/><rect x="627" y="251" width="106" height="24" rx="4"/><rect x="739" y="251" width="106" height="24" rx="4"/><rect x="403" y="284" width="106" height="24" rx="4"/><rect x="515" y="284" width="106" height="24" rx="4"/><rect x="627" y="284" width="106" height="24" rx="4"/>
    </g>
    <g fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.2">
      <rect x="515" y="86" width="106" height="24" rx="4"/><rect x="627" y="86" width="106" height="24" rx="4"/><rect x="739" y="86" width="106" height="24" rx="4"/><rect x="627" y="119" width="106" height="24" rx="4"/><rect x="739" y="119" width="106" height="24" rx="4"/><rect x="627" y="152" width="106" height="24" rx="4"/><rect x="739" y="152" width="106" height="24" rx="4"/><rect x="515" y="185" width="106" height="24" rx="4"/><rect x="627" y="185" width="106" height="24" rx="4"/><rect x="739" y="185" width="106" height="24" rx="4"/><rect x="403" y="218" width="106" height="24" rx="4"/><rect x="515" y="218" width="106" height="24" rx="4"/><rect x="627" y="218" width="106" height="24" rx="4"/><rect x="739" y="218" width="106" height="24" rx="4"/><rect x="739" y="284" width="106" height="24" rx="4"/>
    </g>

    <g font-size="8.5" text-anchor="middle" fill="currentColor">
      <text x="456" y="102" fill="#d64545" font-weight="700">silent</text><text x="568" y="102">AttributeError</text><text x="680" y="102">AttributeError</text><text x="792" y="102">AttributeError</text>
      <text x="456" y="135" fill="#d64545" font-weight="700">silent</text><text x="568" y="135" fill="#d64545" font-weight="700">silent</text><text x="680" y="135">TypeError</text><text x="792" y="135">TypeError</text>
      <text x="456" y="168" fill="#d64545" font-weight="700">silent</text><text x="568" y="168" fill="#d64545" font-weight="700">silent</text><text x="680" y="168">TypeError</text><text x="792" y="168">TypeError</text>
      <text x="456" y="201" fill="#d64545" font-weight="700">silent</text><text x="568" y="201">AttributeError</text><text x="680" y="201">AttributeError</text><text x="792" y="201">AttributeError</text>
      <text x="456" y="234">AttributeError</text><text x="568" y="234">AttributeError</text><text x="680" y="234">AttributeError</text><text x="792" y="234">AttributeError</text>
      <text x="456" y="267" fill="#d64545" font-weight="700">silent</text><text x="568" y="267" fill="#d64545" font-weight="700">silent</text><text x="680" y="267" fill="#d64545" font-weight="700">silent</text><text x="792" y="267" fill="#d64545" font-weight="700">silent</text>
      <text x="456" y="300" fill="#d64545" font-weight="700">silent</text><text x="568" y="300" fill="#d64545" font-weight="700">silent</text><text x="680" y="300" fill="#d64545" font-weight="700">silent</text><text x="792" y="300">AttributeError</text>
    </g>

    <path d="M24 318 L 856 318" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.42"/>
    <text x="392" y="341" text-anchor="end" font-size="10" font-weight="700" fill="currentColor">CAUGHT</text>
    <g font-size="13" font-weight="700" text-anchor="middle">
      <text x="456" y="343" fill="#d64545">1 / 7</text><text x="568" y="343" fill="#e0930f">3 / 7</text><text x="680" y="343" fill="#0fa07f">5 / 7</text><text x="792" y="343" fill="#0fa07f">6 / 7</text>
    </g>

    <text x="440" y="378" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">`autospec=True` is not a style preference. It is 1 of 7 versus 5 of 7.</text>
    <text x="440" y="398" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">The row nothing catches: `assert m.assert_called_once` with no parentheses is a bound method, and a bound method is truthy.</text>
    <text x="440" y="416" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">Mock does guard names beginning with "assert" — which is why the misspelled-assertion row is green everywhere.</text>
  </g>
</svg>
```

The jump from **1 of 7 to 5 of 7** comes from a single keyword. `create_autospec()` (and `patch(..., autospec=True)`) reads the real object's signature with `inspect` and builds a double that enforces it, so a call with the wrong arity or an argument name that does not exist raises `TypeError` at the call, exactly as the real object would. `spec_set=True` adds the seventh case by refusing *assignment* of attributes the real object does not have — the sixth of seven becomes possible.

Two honest caveats, both measured:

- **A bare `Mock()` is not completely blind.** It caught the misspelled `assert_caled_once_with`, because `Mock` deliberately raises `AttributeError` for unknown attributes beginning with `assert` — a guard added precisely because this typo silently disabled so many real assertions. Good design. It is also the only thing it caught.
- **Nothing catches the assertion you referenced but never called.** `assert m.assert_called_once` — no parentheses — reads a bound method, and a bound method is truthy, so the assertion passes unconditionally. No spec can see it because nothing is wrong at the object level. Only a linter can; `flake8` and Ruff both have a rule for it, and you should turn it on.

### State verification versus behaviour verification

There are two ways to end a test. **State verification** asserts on the resulting state: the order is `paid`, the charge is 2500c, one row exists. **Behaviour verification** (or interaction verification) asserts on the calls: `gateway.charge` was called once with these four arguments.

The trade is usually described as taste. It is measurable. Three suites of **four tests each** over the same service — one asserting on calls with an autospec mock, one asserting on outcomes with a stub, one asserting on outcomes with a fake — then two refactors that change internals and nothing else, and ten seeded bugs:

```text
    suite                       baseline   kwargs   single_read   false alarms
    assert on calls (mock)      4/4        2/4      3/4           3
    assert on outcome (stub)    4/4        4/4      4/4           0
    assert on outcome (fake)    4/4        4/4      4/4           0

    suite                       bugs killed
    assert on calls (mock)      1/10
    assert on outcome (stub)    2/10
    assert on outcome (fake)    7/10
```

The refactors are deliberately trivial: pass the same four arguments **by keyword** instead of positionally, and read the order record **once instead of twice**. Neither changes the order, the charge, the receipt or anything a user could observe. The interaction suite raised **three false alarms**; the two outcome suites raised **zero**.

That is the cost of over-specification, and it is worse than the number suggests, because a false alarm does not merely waste time — it teaches the team that a red build means "someone refactored" rather than "something broke". Every such lesson is a small withdrawal from the account that lesson 9 of this phase will find empty.

Now the other column, which is the part people expect to go the other way. Over ten seeded bugs, the interaction suite killed **1**, the stub-based outcome suite **2**, and the fake-based outcome suite **7**. The interaction suite did not trade detection for brittleness — **it was both the most brittle and the least sensitive.** The one bug it caught was the one that changes an argument (an idempotency key reused across orders), which is exactly the class asserting-on-calls is good at, and it was blind to the other nine.

And notice the gap between the two outcome suites: **2 versus 7, from the same assertions**. The stub suite cannot detect a bug it cannot observe. Ask "was the right amount sent?" of a stub and there is no answer, because a stub has no memory. Ask it of a fake and you read `provider.recorded(key)["amount_cents"]`. **The strength of state verification is bounded by whether your double has any state.**

### The fake is usually the right answer

Put the three results together and the default falls out. For any dependency you can plausibly reimplement — a repository, a queue, a clock, a key-value store, a payment provider's happy path — **write a fake, govern it with a contract suite, and assert on outcomes.**

The fake costs you real code: the `InMemoryProvider` in this lesson is under sixty lines and it genuinely implements idempotency, validation, receipts and rate limiting. What you get for them:

- Tests that assert on **state**, which is where most bugs actually show up (7/10 killed versus 2/10).
- Tests that survive refactoring (**0 false alarms** across both refactors).
- One place to encode everything you have learned about the provider, so learning it once benefits every test.
- A double whose drift is **detectable**, because a contract can run against it.

Reach for a mock when the interaction genuinely *is* the behaviour under test and there is no observable state to check — "we must not call the payment API twice on a retry", "the audit log must record this before we commit", "the cache must not be consulted after invalidation". Those are real, and they are a minority. And when you do reach for one, reach for `autospec`.

### A double at the wrong layer skips your own code

One more property, and it is the one that explains why the incident in The Problem was invisible to a suite that ran every line of the integration. **The higher up your stack you put the double, the more of your own code it skips.**

The stack here is three layers: `CheckoutService` (decides what an order becomes) → `PaymentClient` (builds the request, retries, parses the response) → the wire. Put the double at each layer in turn and trace which of your own lines actually execute:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 448" width="100%" style="max-width:840px" role="img" aria-label="Three stacks showing where a test double is placed and how much of your own code runs as a result. With the double at the port, only CheckoutService executes: 28 of 46 reachable statements, 61 percent, and PaymentClient with all of its parsing and retry logic is skipped entirely, so zero of six adapter bugs are caught and state assertions are impossible. With a fake at the transport layer, both CheckoutService and PaymentClient execute: 35 statements, 76 percent, four of six adapter bugs caught. Against the real provider the same 35 statements and the same seven of ten bugs. All three suites report eight of eight scenarios passing. The takeaway: coverage moved fifteen points while detection moved from zero of six to four of six.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">All three suites say 8/8. They are not testing the same amount of code.</text>

    <g font-size="9.5" font-weight="700" text-anchor="middle" fill="currentColor">
      <text x="146" y="56">1 · double at the PORT</text><text x="440" y="56">2 · fake at the TRANSPORT</text><text x="734" y="56">3 · the real provider</text>
    </g>

    <g stroke-width="1.8">
      <rect x="46" y="70" width="200" height="40" rx="7" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="340" y="70" width="200" height="40" rx="7" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="634" y="70" width="200" height="40" rx="7" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="46" y="118" width="200" height="40" rx="7" fill="#7f7f7f" fill-opacity="0.08" stroke="#7f7f7f" stroke-dasharray="5 4"/>
      <rect x="340" y="118" width="200" height="40" rx="7" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="634" y="118" width="200" height="40" rx="7" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="46" y="166" width="200" height="40" rx="7" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
      <rect x="340" y="166" width="200" height="40" rx="7" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
      <rect x="634" y="166" width="200" height="40" rx="7" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    </g>

    <g font-size="10" text-anchor="middle" fill="currentColor" font-weight="700">
      <text x="146" y="88">CheckoutService</text><text x="440" y="88">CheckoutService</text><text x="734" y="88">CheckoutService</text>
      <text x="146" y="142" fill="#7f7f7f">PaymentClient</text><text x="440" y="142">PaymentClient</text><text x="734" y="142">PaymentClient</text>
      <text x="146" y="184" fill="#e0930f">the double</text><text x="440" y="184" fill="#e0930f">in-memory fake</text><text x="734" y="184" fill="#0fa07f">the sandbox</text>
    </g>
    <g font-size="8" text-anchor="middle" fill="currentColor" opacity="0.75">
      <text x="146" y="102">your code — runs</text><text x="440" y="102">your code — runs</text><text x="734" y="102">your code — runs</text>
      <text x="146" y="154" fill="#d64545" font-weight="700">your code — NEVER RUNS</text><text x="440" y="154">your code — runs</text><text x="734" y="154">your code — runs</text>
      <text x="146" y="197">canned ChargeOutcome</text><text x="440" y="197">real wire shapes, in process</text><text x="734" y="197">real wire shapes, over the network</text>
    </g>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="30" y="244">MEASURED OVER THE SAME 8 SCENARIOS AND THE SAME 10 SEEDED BUGS</text>
    </g>
    <path d="M24 250 L 856 250" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.42"/>

    <g fill="currentColor" font-size="9.5" text-anchor="end" opacity="0.85">
      <text x="300" y="274">your statements executed, of 46 reachable</text><text x="300" y="298">the suite's own verdict</text><text x="300" y="322">adapter bugs caught (of 6)</text><text x="300" y="346">service bugs caught (of 4)</text><text x="300" y="370">total bugs caught (of 10)</text>
    </g>
    <g font-size="11" text-anchor="middle" font-weight="700">
      <text x="400" y="274" fill="#e0930f">28 · 61%</text><text x="580" y="274" fill="#0fa07f">35 · 76%</text><text x="760" y="274" fill="#0fa07f">35 · 76%</text>
      <text x="400" y="298" fill="#0fa07f">8/8 green</text><text x="580" y="298" fill="#0fa07f">8/8 green</text><text x="760" y="298" fill="#0fa07f">8/8 green</text>
      <text x="400" y="322" fill="#d64545">0 of 6</text><text x="580" y="322" fill="#0fa07f">4 of 6</text><text x="760" y="322" fill="#0fa07f">4 of 6</text>
      <text x="400" y="346">3 of 4</text><text x="580" y="346">3 of 4</text><text x="760" y="346">3 of 4</text>
      <text x="400" y="370" fill="#d64545">3 of 10</text><text x="580" y="370" fill="#0fa07f">7 of 10</text><text x="760" y="370" fill="#0fa07f">7 of 10</text>
    </g>

    <text x="440" y="404" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">The port double caught 0 of 6 adapter bugs — and reported 8/8 green while doing it.</text>
    <text x="440" y="424" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">Coverage moved 15 points; detection moved from 0 of 6 to 4 of 6. The skipped layer is where the wire format lives.</text>
    <text x="440" y="442" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">Traced with sys.settrace over CheckoutService and PaymentClient, folded onto AST statement starts — identical on 3.9 and 3.13.</text>
  </g>
</svg>
```

**28 statements versus 35.** The port-level double executes **61% of your own reachable code** and reports 8/8 green; the transport-level fake executes **76%** and reports the same 8/8. The 24% neither reaches is the retry path and the `422` branch, which only a provider that actually does those things will exercise.

Now compare those two gaps, because the relationship between them is the real finding. On coverage the two doubles differ by **15 percentage points** — a difference you would lose in the noise of any dashboard. On bugs they differ by everything: **0 of 6 adapter bugs** at the port versus **4 of 6** at the transport. Coverage *understates* the damage by a wide margin, because the port-level double still executes most of `CheckoutService`; what it removes is not a large quantity of code but the specific code where the provider's shape is interpreted. Sending the amount in dollars instead of cents, dropping the idempotency key, silently swallowing a `400` — every one of those lives in the layer a port-level double deletes from the test. And this is exactly why the incident in The Problem survived a high-coverage suite: the *lines* were covered by tests that ran them, just never with a response the provider would actually send.

The rule: **put the double as deep as you can stand.** Every layer you move it down is a layer of your own code you get back.

### What must never be mocked

Three things, and the reasoning is the same each time: a double replaces behaviour with your belief about that behaviour, so never double the thing whose behaviour is the point.

**Never mock the thing you are testing.** Partial mocks of the class under test — patching one method of `CheckoutService` while testing another — mean the test asserts against an object half of which is your own assumption. If a method is hard to reach, that is a design signal; [Designing for Testability](../05-designing-for-testability/) is the next lesson for a reason.

**Never mock the database's semantics.** A fake repository is fine and useful for testing your *logic*. It is not a database: it has no constraints, no transactions, no isolation level, no unique index and no deadlocks. A `UNIQUE` violation, a rollback, a lost update under concurrency — none of them exists in a `dict`, and none of them will ever fail a test that uses one. [Integration Testing Against a Real Database](../06-integration-testing-real-database/) is where that whole class lives.

**Never mock time by patching the clock globally.** Inject a clock port and control it. Patching `datetime.now` module-wide reaches into code you did not mean to affect, and a *frozen* clock cannot test anything about elapsed time — a timeout, a backoff, a TTL. [Determinism: Time, Randomness, IDs & Order](../08-determinism-time-randomness-order/) builds a controllable clock properly.

And one you *may* mock without guilt: **the failure modes you cannot reproduce.** A connection reset mid-body, a DNS failure, a `503` from a load balancer. There is no way to elicit those on demand from a real provider, and a double is the only instrument available. Just be honest that you are testing your handler against your *belief* about the failure, and put that belief in the contract if the provider will let you.

## Build It

`code/test_doubles.py` is one file, standard library only, no network, and it exits in about a quarter of a second. Every number in this lesson comes out of it. Six numbered sections map onto the concepts above.

The **port** is the seam everything hangs off. Nothing implements it directly — it exists so `create_autospec` has a real signature to check against, and so the five doubles have something to be doubles *of*:

```python
class PaymentGateway:
    def charge(self, idempotency_key: str, amount_cents: int,
               currency: str, card: str) -> ChargeOutcome: ...
    def refund(self, charge_id: str, amount_cents: int) -> bool: ...
```

The **provider** is parameterised by a *set of enabled changes*, not by a release number. That detail is what makes the attribution in section 2 honest: with only a release number, the status rename at R4 breaks five scenarios and every later change is measured against an already-broken baseline, so `receipt_url` and `429` both score zero and look harmless. Enabling one change at a time is the only way to price them:

```python
@classmethod
def at_release(cls, release: int) -> "RealProvider":
    return cls(frozenset(c for c, r in CHANGE_RELEASE.items() if release >= r))

@classmethod
def with_only(cls, change: str) -> "RealProvider":
    return cls(frozenset({change}))
```

The **429 bucket** has to be agreed on by two independently written implementations, so it is a hash of the key rather than a counter. Any run, any object, any order: the same keys are rate-limited:

```python
def rate_limited_key(key: str) -> bool:
    return hashlib.sha256(key.encode()).digest()[0] % 4 == 0
```

The **adapter under test** is written against R1 and never revisited — this is the code the whole lesson is about, and every one of its four defects is a line that looks perfectly correct:

```python
status = resp["status"]
if status == "success":                       # R4 renames this to "succeeded"
    receipt = resp["receipt_url"]             # R6 stops sending it below 500c
    return ChargeOutcome(ok=True, charge_id=resp["id"], receipt=receipt)
```

A **contract clause** is deliberately tiny — one request, one predicate — because the point is that the fixture data, not the assertion, decides what the clause can notice:

```python
def clause(key, amount, currency, card, check) -> ClauseFn:
    return lambda p: check(*_post(p, key, amount, currency, card))
```

The **mutation harness** compares against a baseline rather than counting failures, which matters more than it sounds: a suite that is already red scores a free "kill" on every mutant otherwise, and the port-level double in section 6 would have measured 10 out of 10 instead of 3:

```python
baseline = suite("none")
...
dead = any(b and not r for b, r in zip(baseline, res))
```

The **statement tracer** is `sys.settrace` filtered to the four methods we own, with one indirection that is worth more than the tracer itself. Counting raw `f_lineno` values is not a measurement of your program — it is a measurement of your interpreter. CPython changed how it attributes line events for a statement spread over several physical lines, and the first version of this program duly reported a *different* number on Python 3.9 than on 3.13: same source, same inputs, same seed. Folding each line event onto the enclosing statement's first line, taken from the AST, makes the number depend on the source instead:

```python
starts = {sub.lineno for sub in ast.walk(node)
          if isinstance(sub, (ast.stmt, ast.ExceptHandler))}
...
i = bisect.bisect_right(starts, frame.f_lineno) - 1
if i >= 0:
    self.lines.add((name, starts[i]))
```

Lesson 13 of this phase builds a real coverage tool; this is enough to answer "did that layer run at all", and it now answers it identically on every interpreter — verified by running the program on 3.9 and 3.13 and diffing the full output.

Run it:

```bash
python3 phases/12-testing-and-quality/04-test-doubles/code/test_doubles.py
```

```console
== 2 · MOCK DRIFT: THE FROZEN DOUBLE ACROSS TWELVE PROVIDER RELEASES ==
  release   CI suite (frozen stub)   real provider: 8 scenarios   a 2000-order day    green
                                                                                    while broken
    R1       8/8 green                  8/8 correct               2000/2000 (100.0%)    -
    R2       8/8 green                  8/8 correct               2000/2000 (100.0%)    -
    R3       8/8 green                  8/8 correct               2000/2000 (100.0%)    -
    R4       8/8 green                  3/8 correct                186/2000 ( 9.3%)    YES
    R6       8/8 green                  3/8 correct                186/2000 ( 9.3%)    YES
    R9       8/8 green                  1/8 correct                116/2000 ( 5.8%)    YES
    R11      8/8 green                  1/8 correct                 98/2000 ( 4.9%)    YES
    R12      8/8 green                  1/8 correct                 98/2000 ( 4.9%)    YES

  the frozen stub passed 8/8 on every one of 12 releases.
  releases to first silent failure: 3 genuinely green, then R4 onwards.
  total false confidence: 9 of 12 releases green while broken (75% of the year).
  worst release served 1902 of 2000 orders (95.1%) the wrong outcome.

  each change ALONE (one enabled at a time, so a failure is
  attributed to what actually caused it):
    change                          lands  suite  day wrong  scenarios it broke
    status string renamed           R4    3/8    90.7%     standard_charge_is_paid, eur_charge_is_paid, [+3]
    receipt_url now optional        R6    7/8    36.1%     small_charge_is_paid
    validation error 400 -> 422     R9    6/8     3.5%     negative_amount_is_client_error, [+1]
    429 retry now required          R11   7/8    25.5%     rate_limited_order_is_paid

== 3 · THE FIX: ONE CONTRACT SUITE, RUN AGAINST BOTH IMPLEMENTATIONS ==
  contract v2 (8 clauses) against our fake, synced to R1: 8/8 pass

  per change, with ONLY that change enabled: which guard notices?
    change                          lands   frozen stub   contract v1   contract v2
    status string renamed           R4      never         R4            R4
    receipt_url now optional        R6      never         never         R6
    validation error 400 -> 422     R9      never         R9            R9
    429 retry now required          R11     never         never         R11
  contract v1 caught 2 of 4; contract v2 caught 4 of 4.

    guard          first silent release   defect-releases exposed   releases green-while-broken
    frozen stub    R4                     22                        9
    contract v1    R6                     9                         7
    contract v2    none                   0                         0

  and the loop closes: the contract goes red, so we sync the fake,
  and now OUR OWN unit suite reproduces the outage on a laptop.
    fake synced to R1 (stale)    unit suite: 8/8   real provider at R4: 3/8
    fake synced to R4 (updated)  unit suite: 3/8   real provider at R4: 3/8

== 4 · Mock() WILL AGREE WITH ANYTHING YOU SAY ==
    the mistake                             Mock()         Mock(spec=)    autospec       +spec_set
    method renamed in production            silent         AttributeError AttributeError AttributeError
    call with too few arguments             silent         silent         TypeError      TypeError
    keyword argument that does not exist    silent         silent         TypeError      TypeError
    reads an attribute that does not exist  silent         AttributeError AttributeError AttributeError
    misspelled assertion: assert_caled_     AttributeError AttributeError AttributeError AttributeError
    assertion referenced, never called      silent         silent         silent         silent
    assigns a field the port does not have  silent         silent         silent         AttributeError
    CAUGHT                                  1/7            3/7            5/7            6/7

== 5 · INTERACTION ASSERTIONS BREAK ON REFACTORS AND CATCH LESS ==
    suite                       baseline   kwargs   single_read   false alarms
    assert on calls (mock)      4/4        2/4      3/4           3
    assert on outcome (stub)    4/4        4/4      4/4           0
    assert on outcome (fake)    4/4        4/4      4/4           0

    suite                       bugs killed   survivors
    assert on calls (mock)      1/10           a:drops_idempotency_key, a:sends_amount_in_dollars, a:ignores_currency (+6)
    assert on outcome (stub)    2/10           a:drops_idempotency_key, a:sends_amount_in_dollars, a:ignores_currency (+5)
    assert on outcome (fake)    7/10           a:ignores_currency, a:swallows_400, s:maps_client_error_to_server_error

== 6 · A DOUBLE AT THE WRONG LAYER SKIPS YOUR OWN CODE ==
    depth                     our lines run   of 46 reachable   suite   state assertions
    1 · double at the PORT                 28                61%   8/8           IMPOSSIBLE
    2 · fake at the TRANSPORT              35                76%   8/8            available
    3 · the real provider                  35                76%   8/8            available

    depth                     adapter bugs   service bugs   total
    1 · double at the PORT      0/6              3/4            3/10
    2 · fake at the TRANSPORT   4/6              3/4            7/10
    3 · the real provider       4/6              3/4            7/10
```

Three things in that output are arguments rather than demonstrations.

**Section 2's third column is the one to internalise.** The suite column and the traffic column disagree wildly. `429` broke **1 of 8 scenarios and 25.5% of the day**; `422` broke **2 of 8 scenarios and 3.5% of the day**. Scenario counts measure your fixtures. Only traffic measures your customers.

**Section 3's `contract v1` row is the honest result.** Two of four caught, seven releases still green-while-broken. It would have been easy to write a contract suite that scores 4 of 4 on the first attempt and pretend the technique is self-executing. It is not: a contract detects a change only on a path it walks, and the two clauses that close the gap are boringly specific — one small charge, one key in the rate-limited bucket.

**Section 6's `0 of 6` is the sentence from The Problem, measured.** A port-level double reports 8/8 green while catching zero of the six bugs that live one layer below it. The suite is not lying about what it ran. It is lying about what that proves.

## Use It

Everything above is `unittest.mock`, which ships with Python. Here is how to use it without building this lesson's incident.

**`patch` where it is used, not where it is defined.** This is the single most common confusion with `unittest.mock` and it has a precise rule. `patch` rebinds a *name*, and the name the code under test resolves is the one in *its* module:

```python
# app/checkout.py
from app.gateway import charge          # binds `charge` into app.checkout

# tests
patch("app.gateway.charge")             # WRONG — app.checkout.charge still points at the original
patch("app.checkout.charge")            # right — patches the name the code actually looks up
```

If the module does `import app.gateway` and calls `app.gateway.charge(...)`, then patching `app.gateway.charge` is correct, because that is the lookup being performed. The rule is not "patch the definition" or "patch the import" — it is **patch the name at the location where the lookup happens**.

**Always `autospec=True`.** Measured above: 1 of 7 versus 5 of 7.

```python
with patch("app.checkout.gateway", autospec=True) as gw:
    gw.charge.return_value = ChargeOutcome(ok=True, charge_id="ch_1")
    ...
    gw.charge.assert_called_once_with("idem-A1", 2500, "usd", "ok")
```

`create_autospec(SomeClass, instance=True)` is the direct form. Add `spec_set=True` to also reject attribute *assignment*. Both walk the object with `inspect` at construction time, so they cost microseconds and are never the reason a suite is slow.

**`side_effect` is the one to know after `return_value`.** A callable is invoked with the call's arguments; an iterable yields one value per call; an exception class or instance is raised. That last form is how you test the failure paths you cannot elicit from a real dependency:

```python
gw.charge.side_effect = [TransportError("reset"), ChargeOutcome(ok=True, charge_id="ch_1")]
```

**Assertion methods that actually assert.** `assert_called_once_with` is the useful one. `assert_called_with` checks only the *most recent* call, which is a real source of tests that pass by accident. `assert_any_call` and `mock_calls` cover the multi-call cases. And configure a mock's return value with `return_value=`, never by asserting on a `Mock` you configured yourself — that is the "test that asserts on a mock it set up" from [Anatomy of a Unit Test](../03-anatomy-of-a-unit-test/), and it is a tautology with a test name.

**`monkeypatch` versus `patch`.** pytest's `monkeypatch` fixture (`setattr`, `delattr`, `setenv`, `syspath_prepend`, `chdir`) undoes itself at the end of the test and is the cleaner choice for environment variables, module attributes and simple substitutions. Use `unittest.mock.patch` when you want a *mock object* with call recording, `autospec`, and `side_effect`. They are not competitors; `monkeypatch` replaces things, `patch` replaces things *with instruments*.

**For HTTP, fake the transport, not the client.** Both of the good libraries let you keep your real client code — its retries, timeouts, header handling and JSON decoding — and swap only the layer below:

```python
# httpx: a real client, a fake transport. Your request-building code still runs.
transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"status": "succeeded"}))
client = httpx.Client(transport=transport, base_url="https://pay.example")

# responses (for `requests`): registers URL-level stubs
@responses.activate
def test_charge():
    responses.post("https://pay.example/v1/charges", json={"status": "succeeded"}, status=200)
```

This is section 6 as an ecosystem choice. Doubling the transport keeps your adapter under test; doubling the client deletes it. `respx` is the equivalent for `httpx` if you prefer route-style registration, and `vcrpy` records real interactions to replay later — useful, and note that a recorded cassette is a frozen double with exactly this lesson's drift problem unless something re-records it.

**For contract testing against a real provider**, the tools are Pact (consumer-driven contracts with a broker and a `can-i-deploy` gate) and `schemathesis` (property-testing an API straight off its OpenAPI description). Both are [Contract Testing](../10-contract-testing/)'s material. What you can do *today*, with no new dependency, is the thing this lesson measured: put your contract clauses in one file, run them against your fake in every build and against the provider's sandbox on a schedule, and fail the scheduled job loudly. That is about fifty lines of clauses and a runner, and it took defect exposure from **22 release-months to 0**.

**What to actually pick.** In order:

1. **Default to a fake plus a contract suite** for any dependency you can plausibly reimplement — repository, queue, clock, cache, payment provider. Assert on outcomes and on the fake's state. Measured: 7 of 10 bugs versus 2 of 10 for a stub and 1 of 10 for interaction assertions, with zero refactor false alarms.
2. **Run the contract against the real dependency on a schedule**, not in every build. Nightly is enough; it is the difference between a defect living 22 release-months and 0. Track which clause failed, not just that the job is red.
3. **Reserve mocks for interactions that genuinely are the behaviour** — "not twice", "before commit", "not after invalidation" — and always with `autospec=True`.
4. **Put the double as deep in your stack as you can stand.** Transport-level over port-level: 76% of your own code executed versus 61%, and 4 of 6 adapter bugs caught versus 0.
5. **Turn on the linter rule for unparenthesised mock assertions.** No spec configuration catches that one; it was silent in all four columns.

## Think about it

1. Section 2 measured the `422` change as breaking **2 of 8 scenarios but only 3.5% of a day's traffic**, while the `429` change broke **1 of 8 scenarios and 25.5%**. Your suite is the only instrument you have on a Friday afternoon. What would you have to add to it — not to the contract, to the *suite* — to make the scenario count track the traffic impact, and what does that cost you on every build?
2. Contract v1 caught 2 of 4 changes, and the two it missed were missed because of the *amount* and the *key* in its fixtures. Take a dependency in a system you work on and name one clause you would write whose failure depends on a fixture value nobody would think to vary. How would you have discovered that clause was needed without the outage that teaches it?
3. The fake synced to R4 produced **3/8**, exactly matching the real provider at R4. What would have to be true about the fake for those two numbers to differ — and if they did differ, which of the two would you trust, and what would you do next?
4. Section 5's interaction suite was both the most brittle (**3 false alarms**) and the least sensitive (**1 of 10 bugs**). Construct the specific test where that trade reverses — where an interaction assertion catches a bug that no outcome assertion on a fake could catch. What does your example have in common with the three "never mock" cases?
5. A port-level double executed **61% of your own code** and caught **0 of 6** adapter bugs; the transport-level fake executed **76%** and caught **4 of 6**. Suppose you could only report one of those two numbers to a team that currently gates on 90% line coverage. Which would you show them, and what behaviour would you expect it to change? What does the size of the gap between the two say about coverage gates in general?

## Key takeaways

- **A test double is a second implementation of someone else's contract, written by you and verified by nobody.** Measured: a frozen hand-written stub reported **8/8 green on all 12 releases** of a provider that changed four times, with **3 releases genuinely green and 9 green while broken — 75%**. At the worst release **1,902 of 2,000 orders (95.1%)** got the wrong outcome and the suite reported zero failures.
- **You cannot rank a provider's changes by how they read in a changelog.** Isolated, the status rename cost **90.7% of a day's traffic** and the `400 → 422` change cost **3.5%** — a 26× difference between two changes that are both one line of a release note. And scenario counts do not track traffic: `429` broke **1 of 8 scenarios and 25.5% of orders**.
- **One shared contract suite, run against the double and the real thing, is the fix.** It took defect exposure from **22 release-months to 0** and green-while-broken releases from **9 to 0**. The loop that makes it practical: the contract goes red, you sync the fake, and your ordinary unit suite goes red on its own — measured, the fake synced to R4 gives **3/8**, identical to the real provider at R4.
- **A contract covers exactly what it exercises, and nothing else.** Six reasonable clauses caught **2 of 4** changes; they missed the optional receipt because they charged 2500c and the provider only drops it below 500c, and missed the `429` because none of their six fixture keys fell in the bucket. Two more clauses took it to **4 of 4** and exposure from **9 to 0**.
- **`autospec=True` is not a style preference; it is 1 of 7 versus 5 of 7.** A bare `Mock()` caught **1 of 7** real test mistakes, `Mock(spec=…)` caught 3, `create_autospec()` caught **5**, and `spec_set=True` caught **6**. The one nothing catches is `assert m.assert_called_once` without parentheses — a bound method is truthy, so only a linter sees it.
- **Asserting on calls is both more brittle and less sensitive than asserting on outcomes.** Over two behaviour-preserving refactors the interaction suite raised **3 false alarms** to the outcome suites' **0**, and over 10 seeded bugs it killed **1** where the fake-based outcome suite killed **7**. It is not a trade; it is a loss on both axes outside its narrow legitimate use.
- **State verification is only as strong as your double's state.** Identical assertions killed **2 of 10** bugs over a stub and **7 of 10** over a fake, because a stub has nowhere to record the amount, the currency or the fact that a customer was charged twice.
- **The higher you place the double, the more of your own code it deletes from the test.** A port-level double executed **28 of 46 reachable statements (61%)** and caught **0 of 6 adapter bugs** while reporting 8/8 green; moving it down to the transport gave **35 statements (76%)** and **4 of 6**. Coverage moved 15 points; detection moved from nothing to most of them. The skipped layer is where the wire format lives — which is where all four provider changes landed.
- **Default to a fake plus a contract suite; reserve mocks for interactions that genuinely are the behaviour.** Never double the thing under test, the database's semantics, or the clock — and do double the failure modes you cannot elicit, honestly, writing the belief into the contract where the provider allows it.

Next: [Designing for Testability: Seams, Injection & the Untestable Function](../05-designing-for-testability/) — why a function that opens its own connections and reads its own clock forces you into the doubles this lesson just measured, and what to change so it does not.
