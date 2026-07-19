---
name: checklist-test-suite-shape-review
description: For the engineer deciding what to add to a test suite — at a design review, in a postmortem action item, or when the suite has quietly grown past the feedback window and nobody can say which tests are paying for themselves.
phase: 12
lesson: 02
---

# Checklist: Test-Suite Shape Review

For the engineer deciding **what level to add a test at**, or auditing a suite that has grown
past its feedback window. Every reference number below was produced by this lesson's
`code/suite_shape.py`; the model's inputs are declared in that file's header and swept in the
lesson, so you can see which conclusions depend on them.

**Scope:** how many tests at which level, and why. Not how to write one (Lesson 03), not what
to replace the world with (Lesson 04), not how to fix a flaky test (Lesson 09).

**The one-line rule:** *a suite's shape is not a style choice — it is the solution to an
allocation problem determined by your cost ratios, your flake rates, and the capability
ceiling of each level.*

---

## 0. Measure three numbers — 30 minutes, do this before arguing

You cannot have this conversation without these. Each is one command or one afternoon.

- [ ] **Median CI seconds per test, per level.** This ratio determines your shape and it is
      usually not what you assumed.
      ```bash
      pytest --durations=0 -q -m unit        | tail -3
      pytest --durations=0 -q -m contract    | tail -3
      pytest --durations=0 -q -m integration | tail -3
      pytest --durations=0 -q -m e2e         | tail -3
      ```
      Reference ratios used in this lesson: **0.010 / 0.25 / 0.80 / 14.0 s** — a 1,400×
      spread from bottom to top.
- [ ] **Per-test flake rate, per level.** Re-run the suite ten times on an unchanged commit
      and count reds per test-run. Reference: **0.002% / 0.06% / 0.20% / 1.20%**.
      ```bash
      for i in $(seq 1 10); do pytest -p no:randomly -q --tb=no -rf; done | grep -c FAILED
      ```
- [ ] **The capability ceiling of your cheapest level.** Take last quarter's production
      defects, classify them, and count how many your unit tests **could not have expressed
      at any test count** — no database, no real config, no queue, no second component.
      Reference: the unit level reached **34.0%** of the modelled population.

**If per-instance coverage is high and defects keep escaping, the third number is your
answer, and no coverage target will move it.**

---

## 1. The capability ceiling — which level can reach each defect class

A dash is not "unlikely". It is impossible: the environment cannot produce that defect.

| defect class | unit | contract | integration | e2e | weight |
|---|:--:|:--:|:--:|:--:|--:|
| logic | ● | — | ● | ● | 0.20 |
| boundary | ● | — | ● | ● | 0.14 |
| **wiring** (wrong arg / renamed field across a call) | **—** | — | ● | ● | 0.11 |
| serialization (dates, decimals, null vs missing) | — | ● | — | ● | 0.08 |
| contract (provider's shape ≠ your assumption) | — | ● | — | ● | 0.08 |
| auth (middleware, not the handler body) | — | ● | — | ● | 0.07 |
| schema (constraints, types, nullable-unique) | — | — | ● | ● | 0.07 |
| concurrency (lost update, write skew) | — | — | — | ● | 0.06 |
| config (only the real config path) | — | — | — | ● | 0.05 |
| duplicate delivery (needs a queue) | — | — | — | ● | 0.05 |
| N+1 / resource (needs volume) | — | — | — | ● | 0.05 |
| migration | — | — | ● | ● | 0.04 |
| **reachable ceiling** | **34%** | **23%** | **56%** | **100%** | |

- [ ] **Classify your own last-quarter defects into this table.** The exercise takes an hour
      and it settles the pyramid-versus-trophy argument for *your* codebase permanently.
- [ ] **If your ceiling at the unit level is above ~90%, you have a library.** The pyramid is
      simply correct for you: libraries are almost entirely logic and boundary defects.
- [ ] **If it is near 34%, you have a service.** Most of your lines move data across
      boundaries you do not own, and that is where your defects are.

---

## 2. Where to add the test — the postmortem decision

This is the single highest-leverage line in a postmortem template.

- [ ] **Action items say "add a test at the cheapest level that can reach this class",
      never "add an end-to-end test".** Measured over 200 sprints on an identical defect
      stream, the two policies gave the **same detection** (47 escapes versus 46) and:

| policy | CI time | e2e tests | e2e share of CI seconds | clean build green | engineer-minutes |
|---|--:|--:|--:|--:|--:|
| A: always an e2e test | 14.6 min | 48 | **76.6%** | **34.0%** | 153,248 |
| B: cheapest able level | 9.4 min | 23 | 56.9% | 41.8% | **124,296** |

- [ ] **Every new end-to-end test names what it reaches that no cheaper level can.** If the
      answer is "logic" or "a boundary", it belongs one or two levels down.
- [ ] **The e2e count has an explicit cap, expressed in seconds.** The value-maximising optima bought
      **16–37** end-to-end tests across every budget and flake setting tested — a handful is a
      numerical result, not a slogan.
- [ ] **Nothing is ever added without a level named.** The ice-cream cone is built entirely
      out of individually reasonable decisions taken without a global budget.

---

## 3. Audit the shape in the units you pay in

- [ ] **Compute the split by CI seconds, not by test count.** They are near mirror images.
      ```bash
      pytest --collect-only -q -m unit | tail -1        # counts
      pytest --durations=0 -q -m unit | tail -1         # seconds
      ```
- [ ] **Red flag: one level holds >70% of the seconds while holding <5% of the count.**
      Measured cone: **1.6% of the tests, 76.6% of the seconds.** By count it still audits as
      a textbook pyramid at 91% unit tests.
- [ ] **Reference optima (share of CI SECONDS / share of TEST COUNT):**

| budget | unit | contract | integration | e2e | caught | clean build green |
|--:|--:|--:|--:|--:|--:|--:|
| 30 s | 26.1% / 91.7% | 52.5% / 7.4% | 21.3% / 0.9% | 0% / 0% | 50.1% | 93.3% |
| 120 s | 2.4% / 51.1% | 39.6% / 33.6% | 58.0% / 15.4% | 0% / 0% | 70.8% | 74.5% |
| 600 s | 0.1% / 6.1% | 10.8% / 52.1% | 23.9% / 36.2% | 65.3% / 5.7% | 89.0% | 42.7% |
| 4800 s | 0.0% / 0.0% | 2.0% / 42.4% | 3.2% / 21.4% | 94.8% / 36.1% | 99.6% | **1.1%** |

- [ ] **Do not read the last row as a goal.** 99.6% detection with a build that goes green
      1.1% of the time on a clean tree is a suite nobody reads.

---

## 4. Flake gates what you can afford to buy

Flake does not just cost triage. It caps the budget it is worth spending at all.

- [ ] **e2e per-test flake is below 0.6%** before end-to-end runs as a required check. At
      **1.2%** the value-maximising suite bought 20 e2e tests and refused to spend more than
      **401 of 600 s**; at **0.15%** it bought 37, spent the whole budget, and gained
      **3.6 points of detection and 9.1 minutes per build**.
- [ ] **Compute your own build-green probability** and put it on the dashboard next to the
      pass rate:
      ```text
      P(green | clean tree) = prod over levels of (1 - flake_L)^n_L
      180 e2e tests at 1.2%  ->  0.988^180  =  11.4%
      ```
- [ ] **If that number is under ~50%, stop adding tests and fix flake.** Below it the
      re-run reflex is rational behaviour, and a suite nobody reads has no value at any size.
- [ ] **No blanket auto-retry.** A retry policy cannot distinguish a flaky test from a flaky
      product; it suppresses both. See Lesson 09 before enabling `--reruns`.
- [ ] **Break-even flake rates, measured at the 600 s optimum** — above these, one more test
      of that level is worth less than nothing regardless of what it catches:
      unit **0.021%**, contract **0.031%**, integration **0.106%**, e2e **0.898%**.

---

## 5. Make the expensive level cheaper — usually the best available move

Nothing about a test's detection power changes when you speed it up, but the optimum does.

| e2e cost | e2e tests the optimum buys (600 s) | caught |
|--:|--:|--:|
| 1 s | 571 | 99.9% |
| 4 s | 120 | 96.8% |
| 14 s | 28 | 89.0% |
| 60 s | 4 | 80.7% |
| 120 s | 1 | 79.3% |

- [ ] **Session-scoped container, function-scoped data** (`testcontainers-python`).
- [ ] **Template database** (`CREATE DATABASE ... TEMPLATE`) instead of re-running migrations.
- [ ] **Transaction-rollback isolation** where the code under test does not commit (Lesson 06
      covers exactly when this lies).
- [ ] **App booted once per session**, not per test.
- [ ] **`fsync=off` and friends** on the test database instance.

---

## 6. CI wiring

```ini
# pytest.ini
[pytest]
addopts = --strict-markers --strict-config -ra
markers =
    unit: no I/O, no database, no network — under 20 ms
    contract: verifies one seam against a pact or a live provider
    integration: real database, doubled outbound HTTP
    e2e: full stack; justify every single one, in seconds
```

- [ ] **`--strict-markers` is on.** Without it `@pytest.mark.integraton` is a silently ignored
      typo, and `-m "not integraton"` selects your entire suite while looking like a filter.
- [ ] **Jobs split on the same marker line**: `fast` (unit + contract), `slow` (integration),
      `e2e` separate with `--timeout`.
- [ ] **`fast` and `slow` are required checks.** Whether `e2e` is required is decided by §4.
- [ ] **`pytest-xdist` with `--dist loadscope`**, not the default `load`, when setup is
      expensive.
- [ ] **Session-scoped fixtures are per-worker-safe.** Under `-n auto` they run once *per
      worker*: eight workers means eight containers and eight migrations. Key shared resources
      on `PYTEST_XDIST_WORKER` (`test_db_gw0`, `test_db_gw1`, …).
- [ ] **Know what parallelism buys.** It divides **wall time** (the feedback-latency term). It
      does **not** divide CI seconds, which is what you are billed for, and it does nothing to
      flake. Measured: a 405 CI-second optimum was 51 s of wall clock on 8 workers.

---

## 7. Feedback latency, and letting the budget fall out

- [ ] **Critical path under 10 minutes** (Humble & Farley, *Continuous Delivery*, 2010). Past
      it, a failure arrives to someone who has swapped context out.
- [ ] **Do not legislate a suite length — derive one.** Price a caught defect, a false red and
      a minute of waiting, and a length emerges. Measured unconstrained optimum: **405 CI
      seconds, 51 s wall on 8 workers, 83.3% caught** — inside the rule without anyone
      mandating it.
- [ ] **If your suite is far past 10 minutes, the model's reading is that the marginal tests
      up there are not paying for themselves** — a much easier conversation than "we should
      have fewer tests".

---

## 8. Target shape for a backend service

Match the *character*, not the exact counts. Yours depend on your three measured numbers.

- [ ] **A large, near-free unit layer** — kept for **failure localisation**, not detection.
      At the 600 s optimum one more unit test added **0.000000** detection and was still the
      only level with positive net value, because it moves the catch from a **50.3-minute**
      diagnosis to a **9.3-minute** one.
- [ ] **A real contract layer.** 23% of defects live at seams, and contract tests reach them
      at **0.25 s** instead of 14. This is the single line item that made the testing trophy
      (86.6%) beat both pyramids (78.1%) at an identical 600-second budget.
- [ ] **An integration layer against a real database**, carrying most of the detection.
- [ ] **A deliberately small end-to-end layer**, sized in seconds, existing only for the four
      classes nothing else reaches: config, concurrency, duplicate delivery, N+1.

---

## 9. Questions for the review

1. What is your suite's split **by CI seconds**? If you can only answer by test count, you
   cannot yet tell a pyramid from an ice-cream cone.
2. Of last quarter's production defects, how many could your cheapest level have expressed
   **at any test count**? That number is your ceiling, and coverage will not move it.
3. What is P(green | clean tree)? If it is under 50%, every other item here is premature.
4. What did the last five postmortems add, and **at which level** — and who decided?
5. If an end-to-end test became 4× faster tomorrow, would you buy more of them? If yes, that
   speed-up is worth more than any test you could write this sprint.

---

**Sources:** Cohn, *Succeeding with Agile: Software Development Using Scrum*, Addison-Wesley,
2009 (the test pyramid, as a cost argument) · Humble & Farley, *Continuous Delivery*,
Addison-Wesley, 2010 (the ten-minute feedback rule) · Dijkstra, *Notes on Structured
Programming*, EWD249, 1970 (testing shows the presence, never the absence, of bugs). All
numeric reference points measured by `code/suite_shape.py` in this lesson, seed 20260718.
