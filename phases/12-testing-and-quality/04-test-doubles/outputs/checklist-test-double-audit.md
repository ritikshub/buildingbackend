---
name: checklist-test-double-audit
description: For the engineer auditing what a green suite actually proves about a third-party dependency — at code review, before an integration goes live, or the morning after a provider release broke production while CI stayed green.
phase: 12
lesson: 04
---

# Checklist: Test Double Audit

For the engineer auditing what a green suite actually proves about a dependency it does not
own. Use it at code review, before an integration goes live, and the morning after a
provider change broke production while CI stayed green.

Every number below was measured by this lesson's `code/test_doubles.py`. Run it yourself —
it needs no network and exits in under a second.

**Scope:** doubles for dependencies you do not own (HTTP providers, queues, caches, third-party
SDKs). Not database semantics (Lesson 6), not the clock (Lesson 8), not the seam between two
services you both own (Lesson 10).

---

## 0. Is a stale double implicated? — 3 minutes

The signature is that **nothing looks wrong**. Two or more of these means yes.

- [ ] **The suite is green and production is not.** Measured: a frozen hand-written stub
      reported **8/8 green on all 12 releases** while production correctness fell to **4.9%**.
- [ ] **The failure is a `KeyError`, an unexpected status, or an "unknown value" branch** —
      the code met a shape it was never shown.
- [ ] **`git log` on your doubles file shows months of silence** while the provider's
      changelog does not. Compare the two dates. That gap is your exposure window.
- [ ] **Nothing in CI has ever made a request to the provider.** Grep for the base URL. If it
      appears only in production config, no test has ever seen a real response.
- [ ] **The double and the parser were written in the same commit.** They encode one reading
      of the docs, so the test cannot disagree with the code.

```bash
# how long has the double been unverified?
git log -1 --format=%ci -- tests/doubles.py tests/fakes/
# does anything in the test tree actually reach the provider?
grep -rn "api.provider.example" --include='*.py' tests/ ci/
```

**If the double's last commit predates the provider's last release, you have no evidence
about anything between those two dates.**

---

## 1. Classify every double you have

| double | asserts input | asserts output | asserts STATE | fails at the call site |
|---|---|---|---|---|
| dummy | — | — | — | n/a |
| stub | — | yes | — | no |
| spy | after | yes | — | no |
| mock | before | yes | — | yes |
| **fake** | after | yes | **yes** | no |

- [ ] **Every double you own is one of these five, and you can say which.** "Mock" used for
      all five hides the fact that four of them cannot assert on state at all.
- [ ] **Anything replacing a repository, queue, cache or clock is a fake, not a stub.**
      Measured: identical assertions killed **2/10** bugs over a stub and **7/10** over a fake.
- [ ] **Mocks are reserved for interactions that genuinely are the behaviour** — "not charged
      twice", "logged before commit", "not consulted after invalidation".
- [ ] **No double of the class under test.** A partial mock asserts against your own assumption.

---

## 2. Every double has a contract suite — non-negotiable

A double is a second implementation of someone else's contract. Something must check it.

- [ ] **One clause file, run against both the fake and the real dependency.** Same assertions,
      two targets. Divergence is the signal.
- [ ] **The fake-side run is in every build** (milliseconds, no network, no credentials).
- [ ] **The real-side run is on a schedule** — nightly is enough. Measured: this took defect
      exposure from **22 release-months to 0** and green-while-broken releases from **9 to 0**.
- [ ] **The scheduled job fails loudly and names the clause**, not just the job.
- [ ] **Clauses are derived from what your code reads**, not from what looks representative.
      Six reasonable clauses caught only **2 of 4** provider changes; two more took it to 4 of 4.

**Write a clause for every one of these, per response your code parses:**

- [ ] The exact value of every string your code compares against (`status == "success"`).
- [ ] Every field your code reads **without** `.get()` — and a case where it might be absent.
- [ ] Every status code your code branches on, plus "no other status is ever returned".
- [ ] Idempotency: the same key twice returns the same identity and charges once.
- [ ] At least one fixture **outside** the typical range — a small amount, an empty list, a
      long string. Measured: the receipt clause missed R6 purely because it charged 2500c
      while the provider drops the receipt below 500c.

---

## 3. When the contract goes red — the loop

1. [ ] **Confirm which clause failed** and against which target.
2. [ ] **Update the fake to match the provider.** Do not touch production code yet.
3. [ ] **Run the ordinary unit suite.** It should now go red on its own. Measured: the fake
       synced to R4 gave **3/8**, identical to the real provider at R4.
4. [ ] **Fix the production code** until the suite is green for the right reason.
5. [ ] **Add a clause covering whatever the contract nearly missed**, while it is fresh.

If step 3 stays green, your suite does not exercise the changed behaviour — that is a second
finding, and a more serious one than the drift.

---

## 4. `unittest.mock` configuration

- [ ] **`autospec=True` or `create_autospec(...)` everywhere.** Measured over 7 real test
      mistakes: bare `Mock()` **1/7**, `Mock(spec=…)` **3/7**, `create_autospec()` **5/7**,
      `spec_set=True` **6/7**.
- [ ] **`patch` targets the name at the point of lookup**, not the definition:

```python
# app/checkout.py does:  from app.gateway import charge
patch("app.gateway.charge")     # WRONG — app.checkout.charge still points at the original
patch("app.checkout.charge")    # right
```

- [ ] **A linter rule for unparenthesised mock assertions is enabled.** `assert m.assert_called_once`
      is a bound method and a bound method is truthy — **silent in all four** double configurations.
- [ ] **`assert_called_with` is not used where `assert_called_once_with` is meant.** The former
      checks only the most recent call.
- [ ] **`monkeypatch` for environment and simple substitution; `patch` when you need an
      instrument** (call recording, `side_effect`, autospec).

```bash
# find every unspecced patch in the repo
grep -rn "patch(" --include='*.py' tests/ | grep -v "autospec" | grep -v "spec_set"
# find assertions that were referenced but never called
grep -rn "assert .*\.assert_[a-z_]*$" --include='*.py' tests/
```

---

## 5. Put the double as deep as you can stand

| where the double sits | your statements executed | adapter bugs caught | state assertions |
|---|---|---|---|
| at the port (whole gateway replaced) | **28 / 46 · 61%** | **0 of 6** | impossible |
| at the transport (fake wire) | **35 / 46 · 76%** | **4 of 6** | available |
| the real dependency | 35 / 46 · 76% | 4 of 6 | available |

- [ ] **The double replaces the wire, not your adapter.** For HTTP: `httpx.MockTransport`,
      `respx`, or `responses` — your request-building, retry and parsing code still runs.
- [ ] **No test replaces a layer you own** unless you can name what that layer contains and
      why it does not need testing here.
- [ ] **All three suites reporting 8/8 is not evidence they are equivalent.** They were not — and note
      that coverage moved only **15 points** while adapter-bug detection went from **0 of 6 to 4 of 6**.
      Do not audit double placement with a coverage number; audit it with seeded bugs.

---

## 6. Assertion style

- [ ] **Assert on outcomes and on the fake's state.** Measured: **0 false alarms** across two
      behaviour-preserving refactors, versus **3** for the interaction suite.
- [ ] **Assert on calls only where the call is the contract.** Measured: interaction assertions
      killed **1 of 10** bugs; outcome-plus-fake killed **7 of 10**.
- [ ] **No test asserts on a mock's configured return value.** That is a tautology with a name.
- [ ] **Argument passing style is not behaviour.** A test that breaks when positional arguments
      become keywords is measuring your typing, not your system.

---

## 7. Never doubled

- [ ] **The thing under test.** Hard to reach is a design problem (Lesson 5).
- [ ] **Database semantics** — constraints, transactions, isolation, deadlocks. A `dict` has
      none of them and never will (Lesson 6).
- [ ] **Time, by patching the clock globally.** Inject a clock port; a frozen clock cannot test
      a timeout (Lesson 8).

**Do double**, honestly: failure modes you cannot elicit — connection resets, DNS failures,
a `503` from a load balancer. Write the belief into the contract if the provider will let you.

---

## 8. Questions to answer before closing

1. What is the longest any double in this repo has gone without being compared to the real
   thing? Multiply that by your release cadence — that is your exposure window in releases.
2. Which fields does your parser read without `.get()`, and does a clause exercise each one
   being absent?
3. If the provider renamed one status string tomorrow, which job would go red, and when?
   If the answer is "a customer", you have this lesson's incident already.
4. For each mock in the suite: what would have to break for this test to fail? If the answer
   is "the mock's configuration", delete it.

---

**Sources:** Meszaros, *xUnit Test Patterns: Refactoring Test Code*, Addison-Wesley, 2007 ·
Mackinnon, Freeman & Craig, *Endo-Testing: Unit Testing with Mock Objects*, XP2000, 2000 ·
RFC 9110, *HTTP Semantics*, 2022, §15.5.21 and §10.2.3 · RFC 6585, *Additional HTTP Status
Codes*, 2012, §4.
