---
name: checklist-first-test-and-gate-audit
description: Two jobs in one sheet — writing your first real test today, and auditing whether the gates you already pay for catch anything. For the engineer at their desk, with the commands and the thresholds.
phase: 12
lesson: 01
---

# Checklist: Your First Test, and a Gate Audit

Two jobs. **Part A** is for the engineer who has never written a test and wants one
merged this afternoon. **Part B** is for the engineer who has a pipeline and wants to know
which parts of it are earning their keep.

Every number below was produced by this lesson's `code/cost_of_a_bug.py` on a 13-function
pricing module with 40 seeded bugs. Run it yourself before you quote it:

```bash
python3 phases/12-testing-and-quality/01-why-tests-exist/code/cost_of_a_bug.py
```

---

## Part A — write one test today (30 minutes)

- [ ] **`pip install pytest`.** Nothing else. Not a plugin, not a coverage tool.
- [ ] **Make `tests/` and name the file `test_<module>.py`.** Collection is convention-only:

```text
files      test_*.py   or   *_test.py     <- anything else is INVISIBLE
functions  test_*                         <- check_total() is never run
classes    Test*, with NO __init__
```

- [ ] **Pick the most business-critical function you own and test its *boundary*, not its
      middle.** Below the threshold, at it, above it. Measured: the unit gate killed
      **28 of 40** bugs, and boundary bugs were **5 of 5** of its boundary class.

```python
def test_volume_discount_applies_at_exactly_the_threshold():
    assert volume_bps(5000) == 1000     # the case nobody writes

def test_volume_discount_does_not_apply_below_it():
    assert volume_bps(4999) == 0
```

- [ ] **Name it as a proposition.** `test_<unit>_<condition>_<expected>`. You should be able
      to delete the body and still know what broke.
- [ ] **Run it and make it fail once, on purpose.** A test you have never seen red is a
      test you have not verified. Change the expected value, run, change it back.
- [ ] **Add `pytest -q -x` to CI as a required check.** A test that does not gate a merge
      is a document, not a gate.
- [ ] **Do not set a coverage target yet.** Lesson 13 shows a suite with 100% line coverage
      and zero detection.

### The flags worth memorising on day one

```bash
pytest -q                   # one char per test — what you want in CI
pytest -x                   # stop at first failure — what you want while fixing
pytest -k "volume or tax"   # substring match on test names, no setup needed
pytest --lf                 # rerun ONLY what failed last time
pytest --ff                 # those first, then the rest
pytest -vv                  # full diffs when a dict comparison is elided
pytest --tb=short           # readable tracebacks
pytest -s                   # stop capturing stdout; your print()s reappear
```

### Exit codes CI must distinguish

```text
0  all passed              3  internal error
1  some tests failed       4  bad command line
2  interrupted             5  NO TESTS COLLECTED   <- gate on this one
```

- [ ] **Assert a minimum test count in CI**, or a `-k` filter that stops matching will pass
      the build with zero tests executed.

### `pyproject.toml` — the four lines that matter

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q --strict-markers --tb=short"
markers = ["slow: takes more than a second"]
```

- [ ] **`--strict-markers` is not optional.** Without it `@pytest.mark.slwo` is silently
      accepted and `-m "not slow"` runs the test you meant to skip.
- [ ] **`.pytest_cache/` in `.gitignore`, and in the CI cache** — that is what makes `--lf`
      a two-second loop.

---

## Part B — audit the gates you already pay for

### B1. Measure marginal, never absolute — 1 hour

The only defensible question about a gate is *what does it catch that the gate before it
did not*. Reference measurement, 40 seeded bugs, five gates in cheap-first order:

| gate | catches alone | **marginal** | own cost / release | net / release |
|---|---|---|---|---|
| types | 5 (12%) | **5** | 2.0 min | **+23.9 min** |
| unit | 28 (70%) | **25** | 6.4 min | **+23.4 min** |
| review | 17 (42%) | **0** | 34.0 min | **−34.0 min** |
| integration | 26 (65%) | **4** | 15.0 min | **+36.3 min** |
| staging | 18 (45%) | **0** | 25.0 min | **−25.0 min** |
| *escaped everything* | **6 (15%)** | | | |

- [ ] **Seed 20–40 single-token bugs into one real module** — boundary, arithmetic,
      rounding, type-shape, constant, wiring, serialization, error-handling, formatting.
- [ ] **Run each gate against each bug independently**, then compute marginal catch in your
      pipeline's actual order.
- [ ] **Subtract each gate's own run cost** before calling it worthwhile. Measured: over
      10,000 releases the gates cost **824,000 of the 1,649,556 total minutes** — half the
      spend is running them, whether or not they catch anything.
- [ ] **Do not port anyone's ranking, including this one.** Reversing the gate order moved
      staging from **0 → 18** marginal and unit tests from **25 → 1**, with identical gates
      and identical bugs. Marginal value is a property of *your* pipeline.

### B2. The two gates that measured zero — what to do about each

- [ ] **Code review measured 0 marginal.** Do not delete it; delete the *justification*. If
      your team defends review by the bugs it catches, that argument is gone. Defend it by
      design feedback and shared context, and stop counting it as a defect gate.
- [ ] **Staging measured 0 marginal, and its zero is structural.** Staging has no oracle —
      nobody there knows the right answer, only what an obviously wrong one looks like.
      **An environment with no oracle cannot beat a test that has one.** Either give it an
      oracle (replayed production traffic with recorded expectations) or stop paying 25
      minutes a release for confirmation.
- [ ] **Check your revenue/error alarm threshold against a realistic bug's blast radius.**
      Measured: a bug hitting **3.75% of orders** moved daily revenue **0.16%** on
      **$252,065.04** — an order of magnitude under a 2% alarm. Compute the smallest
      revenue deviation your alarms can see, then ask what share of orders that implies.

### B3. Assertion quality — 30 minutes

Two suites, seven tests each, over the same module, put through eight refactors that change
no observable behaviour:

| | bugs caught (of 40) | tests broken by 8 no-op refactors | churn |
|---|---|---|---|
| asserts on **structure** | **26** | **1** | 6 min · $9 |
| asserts on **rendered strings** | **4** | **14** | 84 min · $126 |

- [ ] **Grep your suite for assertions on formatted output** — f-strings, rendered
      templates, log lines, `str(obj)`.
- [ ] **Keep exactly as many as you have rendering promises.** Usually one or two. The
      string suite *uniquely* caught 2 real bugs (`$4.05` printing as `$4.5`; a receipt
      column silently changing width), so the answer is not zero.
- [ ] **The test to apply:** does this assertion cost less than what it catches? Count
      breakages per refactor cycle × 6 minutes, against bugs only it can see.

### B4. Know which bugs your gates structurally cannot reach

Six of 40 escaped every gate. Each is a different lesson, not more of the same effort:

- [ ] **Equivalent mutants** — `apply_bps(a, b)` → `apply_bps(b, a)` where the body
      multiplies. No input distinguishes them; no test can ever kill it. A 100% mutation
      score is not a target. → L13
- [ ] **A double lie that agrees with itself** — two columns swapped on *both* write and
      read. Round-trip green, invoice correct, and a finance job reads the day **72% low**
      (**$5,498.82** instead of **$19,839.25**). → L04, L06, L10
- [ ] **The case your data never contains** — refunds render as charges (`-$4.05` →
      `$4.05`); affected orders in the measured day: **0 of 2,000**, because the fixture had
      no refunds. The bug hides from the *data*, not the tests. → L07
- [ ] **Too rare to trip an aggregate** — banker's vs half-up rounding differs on exact
      half-cents: **17 of 2,000** orders, **−$0.17** a day. No alert will ever fire. → L13
- [ ] **Output nothing asserts on** — **181 of 2,000** receipts render `$4.05` as `$4.5`;
      a column width changes on **2,000 of 2,000**. → L03
- [ ] **Not representable in a single process at all** — time and timezones (L08),
      duplicate delivery and ordering (L11), emergent failure under load (L14).

---

## Reference numbers

**The escape-cost ladder** — the same one-character bug, six moments, built from
people × minutes (every component is printed by the program; substitute your own):

```text
types        the editor underlines it      0.5 min      $1      0x
unit         a unit test goes red          2.0 min      $3      1x
review       a reviewer comments          34.0 min     $51     17x
integration  CI fails on the branch       40.0 min     $60     20x
staging      QA files a ticket           143.0 min    $214     72x
production   a customer notices          702.0 min  $1,053    351x
```

- Inside production, **finding out is 467 of 702 minutes (67%)**; the code change is
  **35 minutes (5%)**. The day's overcharge, **$408.00**, is **0.39×** the labour.
- The commonly quoted production/unit ratio is **100×** and comes from 1970s waterfall
  projects. This ladder derives **351×** for daily deploys. **Use either at the resolution
  of "yes or no" and no finer:** jittering every stage cost by ±60%, 2,000 times, left the
  exact gate ranking stable in only **52%** of draws but the *set of gates worth running*
  stable in **100%**.

**What a suite buys** — `1/(1 − k)` times the change for the same expected regret:

```text
k = 50%  ->  2.0x        measured: 14 unit tests alone,  70%  ->  3.3x
k = 75%  ->  4.0x                  all five gates,       85%  ->  6.7x
k = 90%  -> 10.0x        simulation over 240,000 edits agreed: 3.2x and 6.7x
k = 95%  -> 20.0x
```

The curve is a hyperbola: **0 → 50% doubles your headroom, and 90 → 95% doubles it again.**
Budget the last five points like the first fifty.

**What testing cannot do** — exhaustion at a billion cases per second:

```text
one 32-bit argument                4,294,967,296 cases  =    4.29 seconds
two 32-bit arguments  18,446,744,073,709,551,616 cases  =   584.9 years
```

- Sampling is therefore mandatory, and *how* you sample decides everything: against a bug
  at exactly one point in that space, uniform random found it in **0 of 200** runs of 200
  cases; boundary-biased generation found it in **199 of 200**, median **31** cases.
- **Bias your generators toward `0`, `1`, `-1`, `maxint`, empty, and every threshold in your
  own domain.** Uniform random covers the space evenly, and bugs do not live evenly.

**Documentation** — across all 40 mutations, comments and docstrings detected **0**; the
executable gates detected **34**. The assertion is the only part of your documentation that
fails when it stops being true.

---

## The one habit that moves everything

- [ ] **When a bug reaches production, write the test that would have caught it *before*
      you write the fix.** That single rule moves bugs down the 351× ladder permanently,
      one bug at a time, and it is the only step on this sheet that compounds.

---

**Sources:** Dijkstra, *Notes on Structured Programming* (EWD249), 1970 · DeMillo, Lipton &
Sayward, *Hints on Test Data Selection: Help for the Practicing Programmer*, IEEE Computer
11(4), 1978.
