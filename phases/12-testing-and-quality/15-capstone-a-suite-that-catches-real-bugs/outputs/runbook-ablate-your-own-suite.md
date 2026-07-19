---
name: runbook-ablate-your-own-suite
description: Run the ablation on your own service — seed a bug population, build the layers, measure what each one adds, and decide what goes in the gate and what goes nightly. For the engineer who has to answer "what do we build first, and when do we stop?" with a number.
phase: 12
lesson: 15
---

# Runbook: Ablate Your Own Suite

You cannot copy this lesson's answers. The 31 bugs are this service's bugs, the nine layers
are priced with this service's constants, and the whole point of the measurement is that
**the ranking is a property of your defect population and your build order, not of the test
types.** What you can copy is the procedure.

Budget: **one to two days** for a service of a few thousand lines. It is worth it once; the
matrix stays useful for a year and it settles arguments that otherwise recur every sprint.

Reference numbers from this lesson, for calibration only:

| Quantity | Measured here |
|---|---|
| bugs seeded / classes | 31 / 11 |
| checks / layers | 52 / 9 |
| union detection | **28 of 31 (90.3%)** |
| sum of per-layer catches vs union | 42 vs 28 — **1.50× overlap** |
| whole suite CI cost | **195.36 s** |
| cost per bug, cheapest → dearest layer | **0.14 s → 28.20 s (203×)** |
| optimum under a 90 s budget | layers 2, 4, 5, 6, 7 — **22 of 31 for 67.85 s** |
| suite green on a clean tree | **79.42%**, giving a red build **1.908 bits** |
| bugs no layer caught | **3** |

---

## 0 · Before you start

- [ ] The suite you are about to measure is **green on a healthy tree**. Run it ten times on
      an unchanged commit. If it is not 10/10, you are about to measure your flake rate and
      call it detection. Fix that first.
- [ ] You can switch a bug on and off **without editing a test**. A config flag, an env var,
      a `git stash`-able patch series — anything, as long as the tests never see it.
- [ ] Every test can be run by layer. In `pytest`, that means markers, and it means them now:
      `unit`, `fakes`, `integration`, `contract`, `async_delivery`, `property`, `fault`.

---

## 1 · Build the bug population

**Rule: the population comes from your incident history, not from your imagination.**
Open the last 12-24 months of postmortems, bug tickets and revert commits. You are looking
for what actually broke, at the frequency it actually broke.

- [ ] List every production defect you can reconstruct. Aim for **25-40**. Fewer than 20 and
      the matrix is noise; more than 50 and you will not finish.
- [ ] Classify each one by **what a test would have to reach** in order to see it — not by
      severity. These eleven classes covered everything in this lesson:

| Class | The mistake |
|---|---|
| boundary | an off-by-one on a threshold real data rarely lands on |
| wiring | each part is right; the edge between two of them is not |
| schema | the rule lives in the database and the database was not asked |
| serialization | the wire format moved underneath somebody who reads it |
| duplicate | the same message arrives twice and the second one is not free |
| race | two correct sequences, interleaved, are not a correct sequence |
| timezone | the code asked what time it is and got an untestable answer |
| retry | the second attempt is a second side effect |
| leak | a resource acquired on a path that never releases it |
| grey | the dependency is not down, it is slow, which is worse |
| semantic | correctly typed, correctly shaped, and not what was meant |

- [ ] **Re-introduce each one as a live branch**, one flag per bug. Not a mocked failure, not
      a raised exception — the actual mistake, in the actual code path.
- [ ] Any class with zero entries is a finding. Either you are genuinely immune, or nothing
      you have is able to observe it. Write down which.

---

## 2 · Write the layers, then check for lies

**Rule: no check may know the bug list.** Write each layer from the requirements, the way you
would write it on an ordinary Tuesday. If you find yourself adding an assertion because you
know bug #17 is coming, stop — you have just converted the experiment into a demonstration.

- [ ] Run the full suite against a **zero-bug** build.
- [ ] Record the false-positive rate. This lesson's was **52/52 green, 0.0%**. Anything above
      zero and every cell in your matrix is a coin flip with extra steps.

---

## 3 · Fill the matrix

```bash
# one bug at a time, all layers, per-layer exit status
for bug in $(cat bugs.txt); do
  for layer in types unit fakes integration determinism contract async property fault; do
    BUG=$bug pytest -m "$layer" -q >/dev/null 2>&1
    echo "$bug $layer $?"
  done
done > matrix.txt
```

- [ ] One bug switched on at a time. **Never two.** Compound faults cannot be attributed, and
      attribution is the entire deliverable.
- [ ] Record which *check* failed, not just that the layer did. You will need it in step 6.
- [ ] Compute the **union** and the **sum**. If sum/union is near 1.0 your layers are
      suspiciously disjoint — usually a sign a layer is not really running. Ours was 1.50×.

---

## 4 · Measure the two constants nobody has

Everything downstream is downstream of these. Measure them; do not estimate them.

- [ ] **Seconds per layer.** `pytest -m <layer> --durations=0`, median of five runs on the CI
      runner, not on your laptop.
- [ ] **Flake rate per layer.** Re-run an unchanged commit **at least 200 times per layer** and
      count reds. Anything rarer than 1-in-200 you will not measure this way, and the formula
      `R ≈ 3K` for 95% confidence tells you what it would cost.
- [ ] Authoring cost, if you want the third ranking: lines of test code per layer.

---

## 5 · Compute the four numbers

- [ ] **Marginal, in your build order.** Walk the layers in the order you would actually build
      them; count only bugs not already caught. This is what to build next.
- [ ] **Marginal, in at least two other orders.** Reverse it, and try cheapest-first. If your
      numbers do not move, either your layers genuinely do not overlap or the matrix is wrong.
      Ours moved for **8 of 9 layers**.
- [ ] **Shapley value**, over all 2ⁿ subsets — exact and instant for n ≤ 20. This is what to
      credit a layer with. Ours agreed with build order on **1 of 9 positions**.
- [ ] **Drop-one**: remove each layer from the finished suite and recount. This is what to
      delete. Two of ours came out at **0** and we kept both.

> Use the marginal for *build next*, the Shapley for *credit*, and the drop-one for *delete*.
> They are three different questions and they will give you three different orderings.

---

## 6 · Read the survivors — this is the valuable half

- [ ] List every bug **no layer caught**. There will be some. If there are none, your bug
      population came from your test suite rather than from production.
- [ ] For each survivor, answer in writing: **what would have caught this?** In this lesson
      the three answers were a human, a spec, and a monitor.
- [ ] Then run the specific diagnostic that finds the most common cause — **assertions with no
      independent oracle.** Grep your suite for equalities where both sides are outputs of the
      code under test:

```bash
# the shape to hunt: expected values computed by the thing being tested
rg -n 'assert .*== *(compute|calculate|price|serialize|to_dict|repo\.|svc\.)' tests/
rg -n 'assert .*persisted.*==.*computed|assert .*actual.*==.*expected\(' tests/
```

Ours: **16 checks priced a discounted order, 4 asserted an exact money value, 3 did both, and
0 of those 3 compared against a number the test supplied.** A tautology cannot fail.

- [ ] **Write the golden check.** One per money path. Expected values worked out from the
      specification by somebody who did not write the implementation, asserted end to end,
      blocking in CI. Ours was **14 lines and caught 7 of 31 bugs**, including 2 of the 3 that
      nine layers missed. Put the derivation in the docstring so the next person can audit it.

---

## 7 · Split the gate from the nightly

- [ ] Pick a gate budget. **90 seconds** is a good default: long enough to be useful, short
      enough that nobody context-switches.
- [ ] Solve it. With ≤ 20 layers, enumerate every subset and take the best detection at or
      under budget — it is a `for` loop, not an optimisation problem.
- [ ] Everything the gate drops goes **nightly**, explicitly, with an owner. Ours dropped 6
      bugs' worth: a generator-only boundary, two races, and three overload behaviours.
- [ ] Re-solve when your budget changes. The optimum is **not monotone**: at 15 seconds ours
      bought static typing and fakes, and at 90 seconds it dropped them, because integration
      and contract became affordable and cover the same bugs.

---

## 8 · Set the gates, each with its number

| Gate | Threshold | Justify it with |
|---|---|---|
| type check | zero errors | its cost in CI seconds against its drop-one value |
| changed-line coverage | `diff-cover --fail-under=90` | `P(detect \| line never ran) = 0`, exactly |
| total coverage | **no gate** | a no-assert suite reaches 100% and detects nothing |
| retries | `--only-rerun` on infra errors only, never `AssertionError` | blanket retry reports a *p* race at *p*³ |
| suite green rate | ≥95% on clean commits | below that, a red build stops carrying bits |
| mutation score | ≥80% on money modules, nightly | never 100% — equivalent mutants exist |
| golden invoice | 1+ check, blocking | the only assertion that can disagree with the code |

---

## 9 · Keep it alive

- [ ] Add every new production defect to the population when its postmortem closes. One line.
- [ ] Re-run the ablation **quarterly**, or whenever CI cost changes by more than 2×. Both the
      matrix and the budget optimum drift.
- [ ] Re-measure the flake rate whenever the suite grows by 50%. Green rate compounds as
      `(1−f)^n`, and a suite that grows 10× can lose its entire signal without a single test
      being edited — ours goes from **1.908 bits to 0.005** on exactly that path.
- [ ] Publish the matrix where the arguments happen. The point of a day of measurement is that
      "should we write more unit tests" stops being a matter of taste.

---

## The three things to take away

1. **Rank by what a layer adds, never by what it catches.** Ours summed to 42 against a union
   of 28.
2. **Marginal value is path-dependent.** Any ranking of test types that arrived from outside
   your repository is describing somebody else's build order.
3. **Some bugs need an oracle, not a technique.** Nine layers and 52 checks missed 3; one
   14-line assertion with numbers from the spec caught 2 of them, and the third needs a
   monitor in production.
