---
name: checklist-testability-audit-and-extraction
description: For the engineer who has opened a function to test one rule and found four systems in the way — audit the hidden inputs, prove which behaviours are unreachable, and extract a core without changing behaviour.
phase: 12
lesson: 05
---

# Checklist: Testability Audit & Safe Extraction

For the engineer who opened a function to test one rule and found four systems in the way.
Every number below was measured by this lesson's `code/testability.py`. **Scope:** making code
reachable by tests. Not test *style* (Lesson 3), not what a double may claim (Lesson 4), not
clock and RNG discipline (Lesson 8) — those assume you have already got a seam worth using.

**The test to apply, and it is one question:**

> **What does this function read that its caller cannot choose?**

Not "could this be mocked" — in Python everything can be. A dependency is a value the function
**reads from the world instead of receiving**. Those, and only those, are worth injecting.

---

## 0. Triage — is this a testing problem or a design problem? (5 minutes)

Run these before writing a line of test code. Two or more hits means stop and read section 2.

- [ ] **Count the parameters, then count the reads.** Measured on the lesson's legacy function:
      **1 parameter, 10 unparameterised reads of the world.** That ratio is the diagnosis.

```bash
F=path/to/module.py
grep -nE 'datetime\.(now|today|utcnow)\(|time\.(time|monotonic)\(' $F      # the clock
grep -nE '\b(connect|create_engine|Session|urlopen|requests\.|httpx\.)\(' $F  # I/O it opens itself
grep -nE 'os\.environ|getenv\(' $F                                          # the environment
grep -nE 'random\.|uuid[14]\(' $F                                           # the random source
grep -nE '^[A-Z_]{3,}\s*=\s*[A-Za-z_]+\(' $F                                # module-level singletons
```

- [ ] **Count the doubles the smallest test needs.** Measured: **4** (the module's `datetime`,
      a database file, the gateway singleton, the mailer singleton) versus **0** for the core.
- [ ] **Count the setup lines.** Measured: **11 vs 2 — 5.5x** for one assertion about one rule.
- [ ] **Count the real I/O operations per test.** Measured: **8 vs 0.** Multiply by suite size.
- [ ] **Ask what the test cannot construct at all.** If the answer is "I could not make it
      produce that value", you have a reachability problem, not a mocking problem. Go to §1.

**If a test needs more than two doubles to assert one rule, you are testing the wiring by
accident. That is the signal.**

---

## 1. Prove reachability before you argue about design

Opinion loses arguments; a branch that never executes wins them. Add a six-line tracer, run
every harness you can construct, and diff the sets.

```python
BRANCHES: set[str] = set()

def mark(name: str) -> None:      # one call at the top of every decision branch
    BRANCHES.add(name)
```

- [ ] **Enumerate the decision branches** in the module under audit. The lesson's pricing rules
      have **24**: discount tiers, tax classes, FX path, rounding modes, date clamping, late-fee
      bands, payment window, charge outcomes.
- [ ] **Measure three harnesses and record the doubles each costs.** Reference numbers:

| harness | reached | doubles |
|---|---|---|
| tier 0 — seed data, call it, patch nothing | **15 / 24** | 2 |
| tier 1 — + frozen clock, faked gateway | **20 / 24** | 4 |
| the extracted core — pass the value you want | **24 / 24** | **0** |

- [ ] **Name the branches nothing reached.** Measured: `round.halfway`, `round.halfway.even`,
      `round.halfway.up`, `window.timeout`. These are the deliverable of the audit.
- [ ] **Do not accept "uncovered" as an explanation.** Coverage reports a line did not run. It
      cannot report that a line *could not* run, and the difference decides whether you write a
      test or change the design.

### The three blockers to look for by name

- [ ] **Arithmetic** — a fixed collaborator deletes a region of the input space. The sandbox
      quotes one rate, **1.08 = 27/25**; an integer amount times a fraction with an **odd
      denominator** never lands on 1/2, so **0 of 2,000,000** amounts reach the rounding tie.
      At a live **1.125 = 9/8**, **250,000 of 2,000,000 (12.5%)** do, and the two modes return
      **4 and 5**. *Check: write your collaborator's fixed values as exact fractions and ask
      what they make unreachable.*
- [ ] **Calendar / environment** — a value derived from `now()` makes the suite's power a
      property of the run date. Measured: the clamping branch is reachable on **7 of 365 days**
      (2023) and **7 of 366** (2024); the leap anniversary on **exactly one: 2024-02-29**.
- [ ] **The fix itself** — freezing the clock recovers dates and kills elapsed time. The legacy
      function reads the clock **5 times**; frozen, all 5 agree, so `finished - started` is
      always 0. **A frozen clock cannot test a timeout.** Take both instants as parameters.

---

## 2. Extraction procedure — behaviour-preserving, one step per commit

Never combine two steps. When something breaks you must know which move broke it.

- [ ] **Step 1 — Record a characterization corpus first.** Generate cases, capture outputs,
      assert nothing about correctness. **Gate:** the corpus is large enough to contain the rare
      inputs. Measured: an off-by-one in the date clamp was flagged by **4 of 120 cases (3.3%)**
      — and by **0 of 20**. Sweep your own corpus size until the detection count stops rising.
- [ ] **Step 2 — Turn each hidden input into a parameter, one per commit.** Clock first (it is
      usually the cheapest and unblocks the most), then the repository, then the network client.
      **Gate:** replay the corpus, 100% identical, after every commit.
- [ ] **Step 3 — Split the decision from the I/O.** Pure functions take the values and return a
      value; the shell loads, calls, saves, mails. Reference sizes: core **12 lines** +
      **10 lines**, shell **15 lines**.
- [ ] **Step 4 — Let the shell call the core more than once.** The shell *interleaves* — load,
      read the clock, decide, do I/O, read the clock again, decide again. A core is a set of
      pure functions, not a layer.
- [ ] **Step 5 — Prove equivalence over the full case set.** **Gate:** measured **240 of 240**
      cases identical on every field. Read the qualifier out loud: that is 240 cases the legacy
      version *could be driven into*. For the rest there is no equivalence evidence — which is
      the argument for the refactor, not an objection to it.
- [ ] **Step 6 — Write the tests that were impossible.** Start with the branches §1 named.
- [ ] **Step 7 — Delete the characterization corpus.** Kept forever it pins the bugs in place
      with the behaviour, and turns every intentional fix into a failing build.

---

## 3. Choosing a seam — in this order, stop when the problem is solved

Measured against three behaviour-preserving refactors (hoisting a repeated read, adding a
default argument, aliasing a name at import):

| seam | survives 3 no-op refactors | use it when |
|---|---|---|
| **pass it as a parameter** | **3 / 3** | always, first choice |
| constructor injection | 3 / 3 | a collaborator used by several methods |
| rebind a module global / `mock.patch` | **1 / 3** | code you cannot change |
| argument with a default | 0 / 3 | never as a test seam; it binds at def time |
| `side_effect` call list | **0 / 3** | only when nothing else can reach the branch |

- [ ] **Default to a parameter.** It is free, needs no library, and is the only seam coupled to
      the behaviour rather than to an import path, a definition site or a call count.
- [ ] **Type ports with `typing.Protocol`** (PEP 544) — structural, so the adapter neither
      imports nor subclasses the port. Add `@runtime_checkable` only if you need `isinstance`,
      and know it checks method *names*, not signatures.
- [ ] **If you must patch, use `autospec=True`** and prefer `monkeypatch` over
      `unittest.mock.patch` — `monkeypatch` undoes itself at teardown.
- [ ] **Treat every `patch` as a missing seam.** Write the characterization corpus before you
      remove it.

---

## 4. Do NOT abstract — the cost, measured

Applying the identical refactor to a function with **no hidden inputs**: **+11 lines, +2 names
to learn, +2 call hops from the call site to the arithmetic, 0 behaviours unblocked.**

- [ ] **Never inject arithmetic, formatting, or anything a caller can already vary** by passing
      a different value. Nothing was hidden, so nothing can be revealed.
- [ ] **A `Protocol` with one implementation forever is a synonym, not an abstraction.** Delete it.
- [ ] **A shell with decisions of its own has stopped being a shell.** If you want to unit-test
      the shell rather than the core, the split has drifted — that is not a cue to start mocking.
- [ ] **Concede the point when it is true.** "Test-induced design damage" is real and this is
      what it looks like. The tests get easier and the code gets worse.

---

## 5. FastAPI wiring, and the four things that bite

```python
@app.post("/orders/{order_id}/process")
def process(order_id: int,
            repo: Annotated[OrderRepository, Depends(get_repo)],
            clock: Annotated[Clock, Depends(get_clock)]):
    return process_order(order_id, Deps(repo=repo, clock=clock, ...))
```

```python
app.dependency_overrides[get_clock] = lambda: (lambda: FIXED_INSTANT)
yield TestClient(app)
app.dependency_overrides.clear()          # <- forget this and tests leak
```

- [ ] **Clear `dependency_overrides` in teardown.** It is global mutable state on the app. A
      leaked override passes alone, fails in a suite and passes on re-run — a manufactured flake.
- [ ] **The override key is the function object, not its name.** Override the provider the route
      actually depends on, not a lookalike.
- [ ] **`Depends` caches within a request.** `use_cache=False` if you genuinely need two.
- [ ] **`yield` dependencies tear down after the response** — a trap if your test asserts on
      state that teardown has already rolled back.
- [ ] **Ban module-level singletons.** `GATEWAY = StripeGateway(os.environ["KEY"])` at import
      time is constructed before any test can intervene, shared across the whole process, and
      leaves only the module-global rebind, which survived 1 of 3. Build it in a factory; call it in a
      `Depends`.

---

## Sign-off gate

Do not call a module testable until **all** of these hold:

- [ ] Every hidden input is a parameter — clock, database, network, environment, RNG, module state.
- [ ] The reachability audit names **0** branches that no harness can execute.
- [ ] The smallest test of one rule needs **0 patched collaborators** and does **0 real I/O**.
- [ ] The equivalence replay is **100% identical**, and you have said out loud which cases it
      could not cover.
- [ ] Elapsed-time behaviour is reachable **without** a call-count-dependent double.
- [ ] The characterization corpus has been deleted, and the tests that replaced it name the
      branches it could never reach.
- [ ] No abstraction was added that unblocked **0** behaviours.
