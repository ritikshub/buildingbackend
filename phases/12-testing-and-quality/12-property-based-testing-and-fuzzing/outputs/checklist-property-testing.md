---
name: checklist-property-testing
description: For the engineer adding property-based tests or a fuzzer to a real module — choosing the properties, writing the generator, setting the budgets, wiring the regression database into CI, and deciding what to do the morning a property test goes red on someone else's pull request.
phase: 12
lesson: 12
---

# Checklist: Property-Based Testing & Fuzzing

For the engineer sitting in front of a module deciding what to assert about it. Use it when
adding property tests to existing code, when reviewing a property someone else wrote, and on
the day a property test goes red on an unrelated PR.

Every number below was measured by this lesson's `code/property_testing.py`. It is standard
library only, needs no network, and exits in about five seconds — run it twice and `diff` the
output if you want to check the claims.

---

## 0. Is this module a property-testing target? — 2 minutes

Property testing pays when the input space is large and the assertion is short. It does not
pay when the rule *is* a table.

- [ ] **The module takes data whose shape you do not fully control** — user strings, client
      integers, ids, bytes, sequences of calls.
- [ ] **You can state something true about *every* input**, not just about the three you have
      in mind. If you cannot, run the catalogue in section 1 before giving up.
- [ ] **It is deterministic.** Non-determinism breaks shrinking specifically: a candidate that
      fails intermittently gets accepted, and the reported "minimal" case may not fail at all.
- [ ] **It is fast enough to call thousands of times.** Anything doing I/O per case is a
      property-test target only after the decision logic is extracted (Lesson 5).

**Not a target:** "Gold-tier customers in the EU get free shipping over €50, except on
furniture." That is a table. Use `pytest.mark.parametrize` (Lesson 3).

---

## 1. Choose the properties — the catalogue, top to bottom

Read down the list and stop at each shape that fits. Most modules match two or three.

| shape | the assertion | typical target |
|---|---|---|
| **round-trip** | `decode(encode(x)) == x` | cursors, tokens, serializers, compression |
| **invariant** | output is sorted / disjoint / non-negative / ≤ limit | anything returning a collection |
| **idempotence** | `f(f(x)) == f(x)` | normalisers, upserts, retried handlers |
| **commutativity** | order of two events does not change the state | event consumers, CRDTs |
| **oracle / differential** | fast impl agrees with obvious slow one | anything you optimised |
| **metamorphic** | adding an item never decreases the total | when you cannot compute the answer |
| **never crashes** | no unexpected exception on any input | parsers, decoders, untrusted bytes |

- [ ] **Every encode/decode pair in the module has a round-trip property.** One line. It caught
      two of this lesson's three bugs.
- [ ] **No property was written by reading the implementation.** Measured: a property that
      recomputed the encoder's own expression killed **0 of 3** bugs while generating 3,000
      cases and looking identical to its neighbours. State properties in the *caller's*
      vocabulary — "a cursor survives a URL", "a page never loses a row".
- [ ] **The property models the world the value passes through**, not just the function. The
      URL property in this lesson is `decode(encode(x).replace("+", " ")) == x`; that one
      `replace` is the entire reason it can see the bug.
- [ ] **You wrote more than one.** The best single property here killed **2 of 3**, the others
      **1 of 3**, the set killed **3 of 3**. There is no strongest property to find.

---

## 2. Write the generator — this decides what is findable

The generator is the hypothesis about where the bugs are. It matters more than the property.

- [ ] **You did not narrow a library strategy without a reason you can state.** Measured on one
      bug: uniform over `int32` would need **4.29 billion** cases; boundary-biased found it in
      **8** — a **536,870,912×** difference from nothing but the draw.
- [ ] **The range is not a number you picked in two seconds.** `rng.randint(0, 1000)` found two
      of three bugs and was *structurally blind* to the third, because it cannot emit a negative.
- [ ] **Text generators reach past ASCII.** `st.text()` already draws combining marks,
      surrogates and `\x00`. Do not replace it with `st.text(alphabet=string.ascii_letters)`
      unless the field genuinely rejects everything else — and if it does, test *that*.
- [ ] **Related values are generated together**, not independently. Use `st.composite` or
      `.flatmap()`: drawing `total` and `page` independently essentially never lands on the
      last page. Measured analogue: the same differential bug took **4 cases** at coordinates
      `0..20` and **35,648** at `0..1,000,000` — an **8,912×** spread.
- [ ] **`assume()` is not doing heavy lifting.** If it rejects most draws you will get
      `FailedHealthCheck: filter_too_much`. Build the constraint into the strategy.

---

## 3. Stateful tests — for anything with memory

Caches, rate limiters, queues, session stores, connection pools, state machines.

- [ ] **There is a model, and it is obviously right rather than fast.** A linear scan is a fine
      model for a hash map. If the model is as complex as the implementation, you have written
      a second copy of the bug.
- [ ] **The sequence length is well above your guess at the minimal counterexample.** Measured:
      an LRU eviction bug needs **5 operations**, and at a cap of **4 it is never found in
      20,000 sequences and never will be, at any budget**. This is a cliff, not a gradient.
- [ ] **The key space is small.** Three or four keys with capacity 3, so collisions and
      evictions actually happen. A large key space means nothing ever interacts.
- [ ] **Invariants are checked after every step**, not only at the end.
- [ ] **You are not afraid of long sequences.** 21 operations shrank to 5 in 112 evaluations,
      and landed on a 5-operation counterexample on **60 seeds out of 60**.

```python
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant

class CacheMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.real, self.model = LRUCache(3), ModelCache(3)

    @rule(k=st.sampled_from("abcd"), v=st.integers(0, 9))
    def put(self, k, v):
        self.real.put(k, v); self.model.put(k, v)

    @rule(k=st.sampled_from("abcd"))
    def get(self, k):
        assert self.real.get(k) == self.model.get(k)

    @invariant()
    def same_keys(self):
        assert sorted(self.real.keys()) == sorted(self.model.keys())
```

---

## 4. Budgets and settings

- [ ] **`max_examples` is set deliberately per job.** Measured red rate on a real bug across
      300 seeds: **59.0% at 5**, **83.3% at 10**, **97.7% at 25**, **100% at 50 and above**.
      Default (100) on pull requests; thousands in a nightly job.
- [ ] **`deadline=None` on anything touching I/O.** The 200 ms default fails a slow example,
      which is right for pure functions and hostile to a database test.
- [ ] **`derandomize=True` is NOT the default fix for reproducibility.** Freezing the seed
      freezes the set of cases you ever try — that is an example suite with extra steps. Record
      counterexamples instead.
- [ ] **The property job's run time is tracked.** A strategy that starts drawing 10,000-element
      lists will quietly become the slowest thing you own.

---

## 5. The regression database — the step everyone skips

- [ ] **`.hypothesis/` is in the CI cache, not in `.gitignore`.** Without it every run starts
      from zero knowledge: you get the variance without the memory.
- [ ] **The cache has a `restore-keys` prefix.** Without it the cache only restores on an exact
      key match and is effectively empty every run.

```yaml
- uses: actions/cache@v4
  with:
    path: .hypothesis
    key: hypothesis-${{ github.run_id }}
    restore-keys: hypothesis-        # restore from ANY previous run
```

- [ ] **Every counterexample worth keeping is pinned in source with `@example(...)`**, where it
      is reviewable and survives a cache eviction. Measured: after the first red run, seven
      later runs on seven different seeds all failed at **case 1**, because the recorded case
      replays before anything is generated.
- [ ] **The pinned cases still pass after the fix** — replayed three times here, all green. A
      regression database is a pinned test, not a landmine.

---

## 6. Fuzzing — for anything parsing untrusted bytes

Scope: HTTP and query-string parsing, JSON/Protobuf decoders, cookies and tokens, uploads,
CSV/XML importers, image and archive handling. Not business logic over validated objects.

- [ ] **The harness is `atheris` or OSS-Fuzz, not a hand-rolled loop.** Real coverage
      instrumentation is the whole advantage. Measured on an approximation: guided mutation
      crashed in **888 executions** versus **6,846** for random printable bytes and **21,085**
      for uniform random bytes.
- [ ] **There is a seed corpus, and it is committed.** Guided fuzzing mutates a corpus; with an
      empty one it degenerates toward random search.
- [ ] **Intermediate conditions are separate branches in your code.** Guidance can only reward
      progress it can see. Measured: the guided fuzzer was *slower* to every individual rung
      (`[` in a key at **168** vs **8**) and **7.7× faster** to the conjunction, purely because
      it kept the near misses.
- [ ] **Every crash is shrunk before filing.** 17 bytes → `b'[]'` in 34 candidates here, which
      is the whole bug report.
- [ ] **Crashing inputs go into the corpus** so they are replayed forever.

---

## 7. When a property test goes red — the policy

The single decision that determines whether the technique survives in your repo.

1. [ ] **Read the shrunk counterexample.** It is usually the whole diagnosis.
2. [ ] **Pin it with `@example(...)` immediately**, before deciding anything else.
3. [ ] **Treat it as a bug in the code, not in the test.** Measured: over **1,800 runs on
       correct code** across six budgets, the property went red **zero** times. It has never
       produced a false alarm.
4. [ ] **Decide explicitly: fix now, or accept knowingly with a ticket.** Both are fine.

**Never do any of these** — each one converts a true positive into permanent blindness, and
unlike a real flake nothing will ever tell you again:

- [ ] Re-run until green.
- [ ] Lower `max_examples` to make it stop.
- [ ] Add an `assume()` that excludes the failing shape.
- [ ] Mark it flaky or quarantine it (Lesson 9's policy is for *false* positives; this is a
      delayed *true* positive — the opposite defect).

---

## 8. Questions to answer before closing

1. For each property you wrote: could you have written it without opening the implementation?
   If not, it may be a tautology — the one measured here killed 0 of 3 while looking normal.
2. What is the shortest sequence of operations that could expose a bug in this module? Is your
   `stateful_step_count` comfortably above it?
3. Which values can your generator never produce? Name them. That is the exact list of bugs
   this test can never find.
4. If your CI cache were wiped tonight, which counterexamples would be lost? Those are the ones
   that should be `@example` lines in the source instead.

---

**Sources:** Claessen & Hughes, *QuickCheck: A Lightweight Tool for Random Testing of Haskell
Programs*, ICFP 2000 · Miller, Fredriksen & So, *An Empirical Study of the Reliability of UNIX
Utilities*, CACM 33(12), 1990 · Zeller & Hildebrandt, *Simplifying and Isolating
Failure-Inducing Input*, IEEE TSE 28(2), 2002 · Unicode Standard Annex #15, *Unicode
Normalization Forms* · RFC 4648, *The Base16, Base32, and Base64 Data Encodings*, 2006, §5.
