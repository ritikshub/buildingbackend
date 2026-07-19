---
name: checklist-coverage-and-mutation-gates
description: For the engineer configuring what CI actually blocks on — replacing a total-coverage threshold with changed-line coverage plus a mutation score, sizing the runs so they fit, and triaging the survivors when they arrive.
phase: 12
lesson: 13
---

# Checklist: Coverage & Mutation Gates

For the engineer who has to decide what the build fails on. Use it when you are setting up
CI for a new service, when a coverage gate has become a ritual nobody believes, and on the
morning after a bug shipped through a green build with a high coverage number.

Every figure below was produced by this lesson's `code/coverage_mutation.py`. It needs no
network, writes nothing outside a temp directory, and finishes in a few seconds. Its output
is byte-identical on CPython 3.9 and 3.13, so you can diff your own run against the numbers
quoted here.

**Scope:** what to measure and what to gate on. Not what to assert (Lesson 3), not which
doubles to use (Lesson 4), not flake policy (Lesson 9).

---

## 0. Is your coverage number lying to you? — 5 minutes

Two or more of these means the number on your dashboard is not measuring what you think.

- [ ] **Some test in the repo has no assertion at all.** Measured: 6 such tests scored
      **100.0% line coverage (48/48)** and **87.5% branch coverage** while killing
      **0 of 70** seeded faults.
- [ ] **`branch` is not enabled.** It is off by default in coverage.py. An `if` with no
      `else` is free in line coverage — one test over a 6-line function measured
      **6/6 lines (100.0%) and 2/4 branches (50.0%)**.
- [ ] **The gate is a total, not a delta.** A total is dominated by code nobody has touched
      in a year and moves too slowly to say anything about today's change.
- [ ] **Coverage went up in a PR that added no assertions.** A broad no-assert loop touches
      more lines per test than a focused boundary case does — measured, a coverage-maximising
      selection filled **6 of 8** slots with assertion-free tests.
- [ ] **Nobody can name what would have to break for a given test to fail.**

```bash
# tests with no assertion of any kind — each one is coverage with no detection
grep -rLE 'assert|pytest\.raises|self\.assert' --include='test_*.py' tests/

# assertions that only constrain shape, not value
grep -rnE 'assert .*(is not None|isinstance|len\(.*\) *[=><])' --include='test_*.py' tests/

# is branch coverage even on?
grep -rn 'branch' pyproject.toml setup.cfg .coveragerc 2>/dev/null
```

**A suite asserting only on types measured 95.8% branch coverage and 30.0% detection.** That
second grep is the highest-yield two seconds in this document.

---

## 1. The mental model, in one line each

- [ ] **`P(fault caught | line never ran) = 0`** — exact, universal, no exceptions. An
      uncovered line is *proof* of an untested line.
- [ ] **`P(fault caught | line ran)` measured 84.6%** — and is never 1. Executing a line
      buys the possibility of detection, nothing more.
- [ ] **Therefore coverage is a ceiling, not a floor.** Chase the uncovered lines, because
      each is a guaranteed hole. Then stop: the covered ones have told you nothing.
- [ ] **"We went from 78% to 91%" is information. "We are at 91%" is not.**
- [ ] **100% path coverage is unreachable, not merely expensive.** A 10-branch function has
      **1,024 paths**, all reachable; two tests give 100% line, 100% branch and **0.2%** of
      paths. At 1 ms per test, 20 branches is 17.5 min and 30 branches is 12.4 days.

---

## 2. Fix the coverage configuration — today

```toml
# pyproject.toml
[tool.coverage.run]
branch = true                    # OFF BY DEFAULT. Turn it on. It is strictly more information.
source = ["app"]
parallel = true                  # one data file per worker; requires `coverage combine`
omit = ["*/migrations/*", "*/__main__.py"]

[tool.coverage.report]
fail_under = 0                   # deliberately zero: gate on the diff, not the total
show_missing = true
exclude_also = ["if TYPE_CHECKING:", "raise NotImplementedError", "@overload"]
```

- [ ] **`branch = true`.** Measured: it separated three of five suites where line coverage
      separated none.
- [ ] **`coverage combine` runs before `report`** if `parallel = true`. Forgetting this is
      the classic cause of coverage mysteriously dropping when you enable `-n auto`.
- [ ] **`exclude_also` patterns in config, not `# pragma: no cover` scattered in source.**
      A pattern is reviewable in one place.
- [ ] **Every `# pragma: no cover` is on a line with no business logic.** The three honest
      uses: a platform-specific branch, a genuinely unreachable defensive case, and
      `if __name__ == "__main__"`. Anything else is a lie with a comment.
- [ ] **The total-coverage gate is deleted, not lowered.** Any named number becomes a target.

---

## 3. The gate that replaces it

```bash
coverage xml
diff-cover coverage.xml --compare-branch=origin/main --fail-under=100
```

- [ ] **`diff-cover --fail-under=100` blocks the merge.** This is the one coverage question
      with a defensible answer, and 100 is achievable because it only concerns the lines in
      front of you.
- [ ] **The HTML report is attached to the PR**, so the uncovered new lines appear inline in
      the diff where a reviewer can act on them.
- [ ] **Total coverage is still recorded on `main`** — alert on a fall, never gate on a level.

---

## 4. Add mutation testing, sized so it fits

Cost is `mutants × suite runtime`, and mutants scale with lines. Measured density:
**1.46 mutants per executable line** (70 mutants from 48 lines).

| scope | mutants | at a 30 s suite / 8 workers | where it belongs |
|---|---|---|---|
| a 60-line pull request | **88** | **5.5 minutes** | blocking gate in the PR |
| one 800-line module | **1,167** | **1.2 hours** | nightly |
| a 12,000-line service | **17,500** | **18.2 hours** | never in a PR |

```bash
mutmut run --paths-to-mutate app/pricing/ --tests-dir tests/unit/ --use-coverage
mutmut results
mutmut show 47          # the diff for one survivor
mutmut apply 47         # apply it locally, then write the test that kills it
```

- [ ] **`--paths-to-mutate` is set.** Not optional at any real scale — the whole-repo run is
      the 18-hour job.
- [ ] **`--use-coverage` is on.** It skips mutants on lines no test executes. Those are
      *guaranteed* survivors (measured: 0 of 5 killed), so skipping them loses nothing.
- [ ] **The mutation cache is in the CI cache**, not discarded between runs.
- [ ] **Start nightly on the 2-3 modules that move money or decide access.** Pricing, auth,
      permissions, billing. Add the PR-diff gate once the nightly is stable.
- [ ] **The timeout has a real value.** `mutmut` derives one from your baseline runtime,
      which breaks when a fixture dominates it. Pin it if survivors start filling with
      timeouts. Measured here: **3 of 70** mutants fail to terminate, all in the one
      function containing a `while`.
- [ ] **The threshold comes from a measured baseline, never from 100.** See section 6.

---

## 5. Triage the survivors — this is where the value is

A survivor is one of exactly two things, and telling them apart is the whole workflow.

1. [ ] **Run the survivors against a probe set** — a broad grid of inputs, original versus
       mutant, comparing return values and exception types.
2. [ ] **A probe separates them → a genuine test gap.** The probe input *is* your failing
       test case; write the assertion. Measured: against a happy-path-only suite,
       **15 survived and 12 were separated** — twelve missing assertions, each with its
       input attached.
3. [ ] **No probe separates them → an equivalence candidate.** Read it by hand. Measured
       against the strongest suite: **3 survived, 3 indistinguishable, 0 real gaps.**
4. [ ] **Confirm equivalence by argument, not by the probe set.** A probe can prove a mutant
       *killable*; it can never prove one equivalent. That reduces to program equivalence
       and is undecidable in general.
5. [ ] **Record confirmed equivalents with the reasoning**, so the next person does not
       re-derive it.

The three found here, and why each is unkillable:

| the mutant | why no test can kill it |
|---|---|
| `pct > 20` → `pct >= 20` | `pct` only ever takes 0/5/8/13/15/23 — never exactly 20 |
| `return total_cents` → `pass` | a fast path the loop below already computes correctly |
| `remaining < 0` → `remaining <= 0` | setting `remaining` to 0 when it is already 0 is a no-op |

**Notice the second one.** A statement-deletion mutant that survives on a redundant fast
path has just found you a piece of dead optimisation. That is the useful secondary product:
survivors point at code that does not need to exist.

---

## 6. Set the thresholds

- [ ] **Changed-line coverage: 100%**, via `diff-cover`. Blocking.
- [ ] **Total coverage: no gate.** Recorded, alerted on a fall.
- [ ] **Mutation score on the diff: a floor from your own baseline.** Measured here the
      module-wide score was **95.7%** and the diff-only score **92.9%**; the ceiling from
      equivalent mutants was **95.7%**, so the equivalent rate was **4.3% of all mutants**.
      Measure yours once, then set the bar under it.
- [ ] **Mutation score is never gated at 100%.** Provably unreachable, and the gate will be
      met by deleting inconvenient mutants.
- [ ] **Mutation scores are compared against themselves over time and between two suites
      over the same code** — never between codebases. The number depends on your operator
      set, your equivalent-mutant rate and the shape of the module.

---

## 7. Operators to expect, and what each one stands for

| operator | rewrite | the real bug | mutants here |
|---|---|---|---|
| boundary | `<`↔`<=`, `>`↔`>=` | the off-by-one at a tier or limit | 9 |
| conditional | `if C` → `if not C`, `==`↔`!=` | the inverted guard, the flag read backwards | 13 |
| arithmetic | `+`↔`-`, `*`↔`//` | the wrong operator in a total or a fee | 13 |
| return value | `return X` → `return None` | the early return that forgets its result | 7 |
| exception | `raise E` → `pass` | the swallowed failure that becomes a silent success | 3 |
| deletion | `stmt` → `pass` | the line lost in a merge, the missing increment | 25 |

- [ ] **Boundary and deletion survivors get read first.** Against the strongest suite here
      they were the *only* survivors — 2 of 9 boundary and 1 of 25 deletion — which is to
      say the off-by-one and the missing line are exactly what a value-blind suite cannot see.

---

## 8. Questions to answer before closing

1. How many tests in this repo contain no assertion? Multiply by the lines each one touches
   — that is coverage you are already paying for and receiving nothing back on.
2. If someone deleted a random line from your highest-consequence module, which test would
   go red, and would its failure message name the line?
3. What is your equivalent-mutant rate? Until you have measured it, any mutation threshold
   you set is a guess about an unreachable ceiling.
4. Your gate is coverage of changed lines at 100%. Construct the change that passes it and
   is still untested. (It exists; the whole lesson is about it.)
5. Which is bigger in your repo: the number of tests that would fail if the code broke, or
   the number that would fail if the code were merely refactored?

---

**Sources:** DeMillo, Lipton & Sayward, *Hints on Test Data Selection: Help for the
Practicing Programmer*, IEEE Computer 11(4), 1978 · Jia & Harman, *An Analysis and Survey of
the Development of Mutation Testing*, IEEE TSE 37(5), 2011 · RTCA DO-178C, *Software
Considerations in Airborne Systems and Equipment Certification*, 2011 (MC/DC) · Goodhart,
*Problems of Monetary Management: The U.K. Experience*, 1975.
