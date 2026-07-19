---
name: checklist-unit-test-review
description: Review one test file, or one PR full of new tests, against the measured failure modes. 20 minutes per file.
phase: 12
lesson: 03
---

# Unit Test Review — a working checklist

Use this on a PR that adds tests, or on one file of a suite you inherited. Budget 20 minutes per
file. The output is a list of dated edits, not a document.

One rule for the whole exercise: **"it passes" and "coverage went up" are not evidence.** Every
question below is answerable by reading the test, and three of them are answerable by running one
command.

---

## 0. The 60-second triage

Before reading anything closely, run these three and write down the numbers.

```bash
# 1 · how many assertions per test, and where the worst one is
grep -c "assert" tests/test_pricing.py
grep -n "def test_" tests/test_pricing.py       # count lines between defs

# 2 · does anything here assert on a string, a mock, or a repr?
grep -nE "assert.*(str\(|repr\(|\.called|assert_called|== \"|== '\')" tests/

# 3 · THE ONE THAT MATTERS: break the code and see if the suite notices
#     pick the most business-critical comparison in the module and flip it
sed -i.bak 's/>= MIN_ORDER/> MIN_ORDER/' src/pricing.py
pytest -q tests/test_pricing.py ; mv src/pricing.py.bak src/pricing.py
```

If step 3 stays green, stop reviewing style and go write the boundary table. That is mutation
testing done by hand, and it is the only measurement here that cannot be argued with.

Reference numbers from this lesson, both suites 59 lines over the same module:

| | tests | assertions | worst test | single-act | bugs killed / 24 |
|---|---|---|---|---|---|
| weak suite | 10 | 31 | 14 asserts | 7/10 | **11 (46%)** |
| strong suite | 14 | 17 | 2 asserts | 14/14 | **23 (96%)** |

---

## 1. Structure — one act, one reason to fail

- [ ] Each test makes **exactly one call** into the code under test. Two calls means two units
      under test and a failure that cannot say which.
- [ ] Arrange / Act / Assert are visually separable — blank line between them is enough.
- [ ] No test has more than ~3 assertions, and every assertion in it belongs to **one proposition**.
      `assert (tax, total) == (1238, 16238)` is one proposition. Fourteen assertions about six
      subsystems is fourteen tests in a trench coat.
- [ ] No `if` / `try` / loop-with-branching in the test body that changes what is asserted.
      A test with control flow has untested paths of its own.
- [ ] Arrangement is visible in the test body. If the reader must open `conftest.py` to know what
      the assertion depends on, the fixture is hiding the precondition.

**The masking cost, measured on one 14-assertion test against 24 bugs:** 35 assertions broken,
**9 reported, 26 (74%) never printed.** Only 6 of the 14 were ever the failure shown. Mean broken
facts per failing run: **3.89** — that many fix-and-rerun cycles to see them all.

---

## 2. Names — delete the body and see if the name still tells you what broke

- [ ] Every test name is a **falsifiable sentence**, not a topic and not an ordinal.
      Pattern: `test_<unit>_<condition>_<expected>`.
- [ ] The name would be intelligible in a CI log at 02:00, on a phone, with nothing else on screen.
- [ ] Parametrized cases carry `ids=` so the failing case is named, not numbered.

```text
BAD                          WHY
test_1                       an ordinal — cannot be false
test_pricing                 a topic — cannot be false
test_happy_path              a mood
test_discount_works          "works" is not a claim

GOOD
test_tier_discount_changes_only_at_the_documented_thresholds
test_coupon_still_applies_on_its_last_valid_day
test_coupon_is_rejected_the_day_after_it_expires
test_quantity_below_one_is_rejected_before_pricing
```

**Measured:** for every one of the 23 bugs the strong suite caught, a red test's *name alone*
identified the right subsystem — **23/23 against 0/11** for the weak suite.

---

## 3. Inputs — the boundary table is the highest-value thing in the file

For every comparison and every rounding operation in the module, there should be a table.

- [ ] Every threshold has **three cases**: on it, one unit below, one unit above.
- [ ] Every rounding operation has an **exact half in both directions** (a `.5` that rounds down
      and a `.5` that rounds up). One of the two distinguishes half-even from half-up; the other
      does not. Include both, or you have not pinned the mode.
- [ ] Empty, zero, one, and maximum are present where they are legal inputs.
- [ ] Money is asserted **exactly**, in integer minor units. If a currency assertion uses
      `pytest.approx`, it permits the bug it should be catching.

```python
@pytest.mark.parametrize(
    "subtotal_cents, expected_discount_cents",
    [(4999, 0), (5000, 250), (5001, 250),
     (19999, 1000), (20000, 2000), (20001, 2000),
     (99999, 10000), (100000, 15000), (100001, 15000)],
    ids=["below-5pc", "exactly-5pc", "above-5pc",
         "below-10pc", "exactly-10pc", "above-10pc",
         "below-15pc", "exactly-15pc", "above-15pc"],
)
def test_tier_discount_changes_only_at_the_documented_thresholds(
        subtotal_cents, expected_discount_cents):
    assert price_order([("sku", subtotal_cents, 1)]).discount_cents == expected_discount_cents
```

**Why this is the best line-for-line investment you can make.** Measured on 8,000 realistic
random orders:

| bug | shows up on | random orders for 95% confidence |
|---|---|---|
| swapped arithmetic operator | 49.888% | **5** |
| rounding mode flipped | 3.100% | **96** |
| tier `>=` became `>` | 2.138% | **139** |
| tier threshold off by one | 0.338% | **887** |
| coupon-minimum boundary | 0.000% | **never seen in 8,000** |

That 6-line, 9-case table above killed **10 of 24** bugs on its own. Four such tables — 20 lines,
22 cases — killed **15 of 24**, beating the entire 59-line weak suite by 4 bugs on **34% of the
code**.

---

## 4. Assertions — what you pin is what you pay for

Assert these:

- [ ] the **amount** / the returned value / the resulting state
- [ ] the **exception type**, plus a stable machine-readable `code` attribute
- [ ] whole objects when every field is part of the promise (field-by-field assertions silently
      stop checking the field somebody adds next year)

Never assert these:

- [ ] ~~the text of an error message~~ → use the type, or `pytest.raises(E, match=r"<stable fragment>")`
- [ ] ~~a formatted string / receipt / rendered output~~ → assert the fields it is formatted from
- [ ] ~~`repr()`~~ → it is a debugging aid, not an interface
- [ ] ~~an internal or debug field~~ → if the caller does not depend on it, neither should the test
- [ ] ~~which methods were called~~ → unless the call **is** the observable behaviour (an email
      sent exactly once, a payment not charged twice, a message on a queue)
- [ ] ~~the name of a private helper~~ → bind to the public behaviour and survive the refactor

**The churn measurement.** A refactor that renamed an internal field, reworded one message,
reformatted a receipt, split a private helper and batched two audit calls — verified
behaviour-identical across **8,808 cases** — turned **6 of 10** weak tests red and **0 of 14**
strong ones. None of the six found a bug. All six had to be rewritten by hand.

`pytest.raises` traps worth knowing:

```python
with pytest.raises(InvalidQuantity) as e:   # the TYPE is the contract
    price_order([("sku", 500, 0)])
assert e.value.code == "invalid_quantity"   # a stable code, not the prose

# match= is re.search over the message — a regex, not a literal
with pytest.raises(CouponExpired, match=r"SAVE10"):   # fine: a code, chosen as contract
    ...
with pytest.raises(ValueError, match=re.escape("cost: $5.00 (final)")):  # escape metacharacters
    ...
# NEVER: pytest.raises(Exception) — it will happily catch your own AttributeError and pass
```

---

## 5. The unhappy path

- [ ] Every `raise` in the module has a test that asserts it fires **and** asserts the type.
- [ ] Every validation branch has a test at the rejection boundary (0 and 1, empty and one item).
- [ ] At least one test proves the module rejects input *before* doing partial work.

**Measured:** 4 of 24 seeded bugs changed nothing on any input the module accepts — they live
entirely in the rejection branches — and **3 of those never appeared once in 8,000 generated
orders**, because a generator written by someone thinking about pricing produces prices. Rejection
tests in the two suites: **1 of 10** weak, **3 of 14** strong.

---

## 6. Delete these

A test earns its place by catching something no other test in its file would catch. Six tests in
the weak suite scored **0 unique kills between them, 29 lines, 49% of that file's maintenance
surface, and 2 of them went red on a refactor that changed nothing.**

| Delete | Because it tests |
|---|---|
| `test_getter` | that Python assigns attributes |
| `test_it_works` | that a function returns something truthy |
| `test_repr` | a debugging aid |
| `test_happy_path` (over-mocked) | a `lambda` the test wrote two lines earlier |
| `test_coupon` (call spy) | the implementation's call sequence |
| framework / library behaviour | somebody else's test suite |

Keep a smoke test only if you have nothing better *and* you know what it is worth: it tells you
the module imports and does not crash, and a green one feels like a tested module.

**Before deleting anything**, confirm the unique-kill claim for yourself: comment the test out,
introduce the bug you think it catches, and check that something else goes red.

---

## 7. Sign-off

Do not approve a test PR that fails any of these:

| Check | Threshold |
|---|---|
| Flip one comparison operator in the module — does the suite go red? | yes, or the PR is not done |
| Assertions in the largest test | ≤ 3, one proposition |
| Calls into the code under test, per test | exactly 1 |
| Every threshold in the module has an on/below/above table | yes |
| Every rounding operation has an exact-half case in both directions | yes |
| Assertions on message text, `repr`, formatted strings, call lists | 0 |
| Tests whose name is not a falsifiable sentence | 0 |
| `raise` statements in the module with no test | 0 |
| Suite passes when run against unmutated code | yes (a red-on-correct-code test is broken, not strict) |

Any row that fails gets a dated owner and a ticket, before the PR merges.

---

## 8. Once a quarter, on a suite you inherited

```bash
pip install mutmut
mutmut run --paths-to-mutate src/pricing.py
mutmut results
```

Kill rate is the only number in this checklist that measures the suite rather than describing it.
Run it on the module you are most afraid of, not on the whole repo — full-repo mutation testing is
O(mutants x suite) and belongs in a nightly job. Lesson 13 covers the gates and the thresholds.
