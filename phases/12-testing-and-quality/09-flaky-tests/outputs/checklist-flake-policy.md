---
name: checklist-flake-policy
description: A written flake policy with real numbers in it — the thresholds, commands and decision rules for a gating test suite, plus the arithmetic that justifies each one.
phase: 12
lesson: 9
---

# Flake Policy

A policy, not a lecture. Adopt it, adjust the constants to your build volume, and put it
in the repository next to `pytest.ini` so it is a thing people can point at in review.

Every threshold below is derived, not asserted, and the derivation is one line. Recompute
them for your numbers — several of them scale with build volume and suite size, and the
defaults here are for a **3,000-test suite at 6 builds/day**.

Source for the delta-debugging section: Zeller, A. & Hildebrandt, R., "Simplifying and
Isolating Failure-Inducing Input", IEEE TSE 28(2):183-200, 2002.

---

## 0 · The three numbers to compute before anything else

- [ ] **n** — tests in the gating suite. `pytest --collect-only -q | tail -1`
- [ ] **f** — per-test flake rate, measured (section 2 below). Not estimated. Not remembered.
- [ ] **B** — builds per week of the gating suite.

Then compute these, and write them at the top of this file for your repo:

| quantity | formula | at n=3,000, f=0.2%, B=30 |
|---|---|---|
| green rate on a clean commit | `(1-f)^n` | **0.25%** |
| red builds per week caused by nothing | `B x (1-(1-f)^n)` | **30** |
| f you need for a 95% green build | `1 - 0.95^(1/n)` | **0.00171%** (1 in 58,488) |
| flake-fix break-even rate `p*` | `fix_h x 60 / (B x triage_min x 52)` | **2.56%** |
| weekly cost of the flake population | `B x n x f x triage_min / 60` | **27 engineer-hours** |

If the last row is more than a day of engineering time a week, this is a funded programme,
not a series of individual judgement calls. Ours was **0.8 full-time engineers**, and
*every individual flake in it was below `p*`* — which is exactly why nobody fixed any of them.

---

## 1 · Retry policy (the one that matters)

**Rule: never retry an assertion failure. Retry infrastructure errors only.**

- [ ] `--reruns N` alone does not appear anywhere in CI config. Grep for it.
- [ ] Every `--reruns` is paired with at least one `--only-rerun`.
- [ ] `AssertionError` is **not** in any allowlist, and never will be.
- [ ] Whole-pipeline "re-run all jobs" is not a routine response (see §3 for the cost).

```bash
pytest --reruns 2 --reruns-delay 1 \
       --only-rerun 'ConnectionError' \
       --only-rerun 'ConnectionResetError' \
       --only-rerun 'TimeoutError' \
       --only-rerun 'OperationalError' \
       --only-rerun 'ContainerNotReady'
```

Measured over 600 builds (100 days) on a suite with 14 environmental flakes and 6 genuine
intermittent product races:

| policy | green on clean commit | races found | worst detection latency | extra CI |
|---|---:|---:|---:|---:|
| no retries | 35.2% | 5 / 6 | never (1 race) | — |
| `--reruns 2` blanket | **98.4%** | 4 / 6 | **never (2 races)** | +0.4% |
| `--reruns 2 --only-rerun` | 90.9% | **6 / 6** | **3.0 days** | +0.3% |

Why: under `--reruns R` a race manifesting *p* of the time is reported at rate `p^(R+1)`.

| p | reported at R=0 | reported at R=2 |
|---:|---:|---:|
| 35% | 35.00% | 4.2875% |
| 14% | 14.00% | 0.2744% |
| **3%** | **3.00%** | **0.0027%** — 1 build in 37,037 |

- [ ] Anyone proposing blanket retries has been shown the 3% row.

**Known limitation, stated up front so nobody discovers it as a surprise:** an error-signature
allowlist is imperfect. Roughly 15% of races surface as timeouts and get retried anyway. It is
still 945x more visible than blanket retry on the hardest case. Do not claim it is airtight.

---

## 2 · Measurement (the prerequisite for every other section)

You cannot detect a 1-in-500 flake by remembering. At 6 builds/day, a quarter of normal CI
traffic only gives you 95% confidence down to **1 in 182**.

- [ ] Every test failure emits a record. Minimum schema:

```python
# conftest.py
def pytest_runtest_logreport(report):
    if report.when == "call" and report.failed:
        emit_flake_record(
            test_id=report.nodeid,
            duration_s=report.duration,
            commit=os.environ.get("GIT_SHA"),
            worker=os.environ.get("PYTEST_XDIST_WORKER", "master"),
            random_seed=os.environ.get("PYTEST_RANDOMLY_SEED"),
            runner=os.environ.get("RUNNER_NAME"),
            error_class=report.excinfo.typename if report.excinfo else None,
            was_real=None,      # filled by triage. NEVER left null.
        )
```

- [ ] **`was_real` is populated by triage on every record.** This single field is what makes
      per-test flake rate and bugs-caught-per-test computable. Without it §5 is guesswork.
- [ ] The dashboard shows **first-attempt green rate**, not final green rate. Final green
      rate is the number your retry policy is designed to flatter.
- [ ] Per-test flake rate is a tracked metric with an alert on the rate, not on individual
      failures.
- [ ] `pytest-randomly` is enabled (it shuffles order and reseeds per test). Expect one bad
      week; the tests it breaks were already broken.
- [ ] Under `pytest-xdist`, every worker gets its own database / port / temp path:
      `f"postgresql://localhost/test_{worker_id}"`.

---

## 3 · Diagnosing one flake

**Re-run the test, never the pipeline.** Confirming a 1-in-100 flake costs 2 minutes of
re-running the test and **60 hours** of re-running the suite.

Re-runs needed to see a 1-in-K flake at least once: **R ≈ 3K for 95%, R ≈ 4.6K for 99%.**

| flake is 1 in K | R for 95% | R for 99% | as a test re-run |
|---:|---:|---:|---:|
| 10 | 29 | 44 | 0.2 min |
| 50 | 149 | 228 | 1.0 min |
| 100 | 299 | 459 | 2.0 min |
| 500 | 1,497 | 2,301 | 10.0 min |

- [ ] Start with **isolate-and-hammer** — 28.4% diagnostic accuracy for 1.7 minutes, against
      18.8% for pressing re-run at 12 minutes:

```bash
pytest 'tests/test_orders.py::test_cancel' -p no:randomly --count=300
```

Then work the probe table. Read the signature, not the vibe:

| probe | command | isolates |
|---|---|---|
| **A** test alone, same seed | `pytest <id> -p no:randomly` | order dependence (fails alone = needs a predecessor) |
| **B** whole suite, same order | `pytest -p no:randomly` | test pollution, resource leaks |
| **C** whole suite, shuffled | `pytest -p randomly` | shared mutable state, order coupling |
| **D** different runner, hours later | re-dispatch the job | time/date boundaries, infra noise |
| **E** test alone, 200x | `pytest <id> --count=200` | timing, unseeded randomness, **and races** |

- [ ] **Understand what the probes cannot do before you trust them.** Measured across 40,000
      simulated flakes, the full five-probe diagnosis identified a *genuine product race*
      correctly 0.2% of the time. It never once said "this is your code" — it said "bad test",
      and usually "sleep too short". A race and a short sleep are indistinguishable from
      outside. **If a flake is timing-shaped, read the production code before you edit the test.**

### When no single test is the culprit

If the job fails only in combination, do not bisect — halving fails on its first step 75.4%
of the time because the culprits straddle the split. Use `ddmin` (remove a chunk, test the
complement). If the failure is itself intermittent, the oracle is flaky too:

| repeats per oracle call | minimal set correct |
|---:|---:|
| 1 | **17.8%** — and it fails silently |
| 3 | 77.2% |
| **6** | **95.5%** |

- [ ] Repeat count set from `R = ln(0.05)/ln(reproduce_rate)`, not guessed.

---

## 4 · Quarantine

**Quarantine requires an expiry date AND a funded fix budget. If you can only have one,
take the budget** — that is the variable that moved the measurement.

Over 100 sprints, at the same fix budget, no-expiry and 2-sprint-expiry shipped *exactly*
the same 2.08% of regressions (210 quarantined vs 200 deleted — a quarantined test and a
deleted test gate the same amount: none). Funding 2 fixes/sprint gave **0.33%** either way.

- [ ] A named fix budget exists in sprint planning. Ours: **2 tests/sprint minimum.**
- [ ] The expiry date lives in the marker, so the test fails when the date passes:

```python
@pytest.mark.flaky_quarantine(reason="ORDERS-4412", expires="2026-09-01")
def test_cancellation_releases_reservation(): ...
```

- [ ] `pytest_collection_modifyitems` converts an expired marker into a hard failure.
- [ ] The quarantined job runs **non-blocking and 20x**, so it produces a rate rather than
      an anecdote: `pytest -m quarantined --count=20` with `continue-on-error: true`.
- [ ] Quarantine size is on the dashboard. If it only ever grows, it is not a policy —
      it is an outbox. Ours reached **210 tests (3.8% of the suite)** in four years at
      0.5 fixes/sprint, and nobody ever decided that.
- [ ] Every quarantined test has a named owner and a ticket.

---

## 5 · Fix, delete, or live with it

Compute `p*` for your build volume first — **it scales inversely with builds/week**, so a
team at 240 builds/week has `p* = 0.32%`, not 2.56%.

```text
p* = fix_hours x 60 / (builds_per_week x triage_minutes x 52)
```

| condition | action |
|---|---|
| `p >= p*` (2.6% here) | **FIX IT.** The flake costs more than the fix inside a year, whatever the test is worth. No discussion. |
| `p < p*` and the test has never caught a real bug | **DELETE IT.** Zero measured value plus nonzero flake rate is negative expected value. |
| otherwise | **KEEP IT**, and if it blocks, quarantine per §4. |

Decision matrix (test value = bugs caught/year x 14 h escape cost):

| test catches | worth | p = 0.5% | p = 2% | p = 5% |
|---|---:|---|---|---|
| 0.05 bugs/yr | 0.7 h/yr | DELETE | DELETE | FIX |
| 0.25 bugs/yr | 3.5 h/yr | KEEP | DELETE | FIX |
| 1.00 bugs/yr | 14.0 h/yr | KEEP | KEEP | FIX |
| 3.00 bugs/yr | 42.0 h/yr | KEEP | KEEP | FIX |

- [ ] "Has this test ever caught a real bug?" is answerable from data (§2), not from opinion.
- [ ] Deleting a zero-value flaky test does not require a ceremony or a debate.

---

## 6 · The escalation nobody schedules

Trigger a review of this whole policy when **any** of these fires:

- [ ] First-attempt green rate on clean commits drops below **80%**.
- [ ] Suite size grows by 50% (recompute the `(1-f)^n` row — this is the silent one).
- [ ] Builds/week grows by 2x (recompute `p*`; your tolerance just halved).
- [ ] Quarantine exceeds **1%** of the suite, or any entry passes its expiry.
- [ ] A production incident's root cause was a test that had been failing and passing on retry.

That last one is the audit that matters. When it happens, pull every failure record for
that test id and count them. In the worked scenario the number was **eighteen failures over
eleven weeks**, every one filed green, before the race reached a customer.
