---
name: checklist-test-data-and-fixtures
description: Auditing a test suite's fixture strategy — measuring shared-seed coupling, setting the unique-field threshold, budgeting SubFactory rows, and refusing the production dump.
phase: 12
lesson: 07
---

# Checklist — Test Data & Fixtures

For a backend service with a relational schema and a suite you did not write alone.
Work top to bottom. Sections 1 and 3 are the ones to run today; everything else can
wait for the migration. Every reference number below was measured in Phase 12 Lesson 07
on a generated 240-test suite over a 4,374-line seed — they are *thresholds to compare
against*, not predictions about your repo. Section 1 tells you your own.

---

## 0. Fill this in before you change anything

| Fact | Your value |
|---|---|
| Shared fixture files, and total lines | ______ |
| Age of the oldest one, and who owns it | ______ |
| Tests in the suite | ______ |
| Tests that reference a hard-coded id (`user_id=1`, `/orders/1`, `as_user=1`) | ______ |
| The single most-referenced id, and its reference count | ______ |
| Factory / mother / builder definitions that already exist | ______ |
| Unique-field strategy for `email`, `username`, external ids | ______ |
| Is `Faker.seed()` pinned anywhere? | ______ |
| Tests that need >1,000 rows to mean anything | ______ |
| Does any test environment hold real production rows? | ______ |

If the last row is "yes", jump to section 6 first. Nothing else on this list is as
expensive to get wrong.

---

## 1. Measure your own coupling — before opinions

Do not argue about fixtures. Count. Four commands, ten minutes, and the argument ends.

```bash
# 1. How big is the shared seed, and how much of it is load-bearing?
wc -l fixtures/*.sql tests/conftest.py

# 2. Which id is the god fixture? The head of this list is your user 1.
grep -rhoE '\b(user_id|as_user|account_id|tenant_id)\s*=\s*[0-9]+' tests/ \
  | sort | uniq -c | sort -rn | head -20

# 3. How many tests are bound to it? (substitute the winner from step 2)
grep -rlE 'as_user\s*=\s*1\b' tests/ | wc -l

# 4. The blast radius, empirically: change ONE field in the seed and run everything.
#    Do it on a branch. Do not fix anything. Just count the red.
pytest -q 2>&1 | tail -1
```

- [ ] Step 2 run, and the top id written into section 0
- [ ] Step 4 run for at least one field the team believes is safe
- [ ] The failing tests were **read**, not just counted — note how many are about a
      different feature than the field you changed
- [ ] The result is in a doc someone else can find

**Compare against (measured, 240 tests / 4,353 rows):**

| What you measured | Reference | Read it as |
|---|---|---|
| Tests bound to the top id | **116 of 240 = 48.3%** | half the suite is one row's hostage |
| Distinct ids the suite touches | **53** | out of thousands of available rows |
| Worst one-field blast radius | **52 of 240 = 21.7%** | pagination ticket, 52 red, 0 code changed |
| Same change, factory world | **0** | the delta is the whole business case |
| Rows that are load-bearing | **57 of 4,353 = 1.31%** | the other **4,296** are free — do not "clean them up" |
| Top 5 cells' share of all reads | **87 of 298 = 29.2%** | a power law; the head is frozen, the tail is noise |
| Cells read by 2+ tests | **34** shared vs **0** factory | this is the number that predicts blast radius |

> If your blast radius is under 5 tests, you do not have this problem and the rest of
> this checklist is optional. If it is over 20, you cannot change your own fixture and
> everything below is urgent.

---

## 2. The fixture policy to adopt

Copy this into `tests/README.md` and make it reviewable. It is four rules.

- [ ] **Rule 1 — a test states its own preconditions.** Every value the assertion reads
      appears in the test body, *even when the default already has it right*.

  ```python
  # The default role is already 'member'. State it anyway.
  user = make_user(role="member")
  assert not can_delete_any_order(user)
  ```

  Measured: factories state **74.5%** of what their assertions read, at **2.2** values
  per test against **1.24** the assertion actually needs — stating more than you read is
  correct, because preconditions are what make a test runnable. The residual is real:
  **61 of 240 (25.4%)** still assert on an unstated default. This rule is how you shrink it.

- [ ] **Rule 2 — no test reads a row it did not create,** with one written exception:
      reference data (VAT rates, currencies, country codes, plan definitions). Measured,
      that exception is **1 cell out of 266**, read by **33 tests in both worlds**. If your
      exception list is longer than a screen, it is not reference data, it is a god fixture
      with a costume.

- [ ] **Rule 3 — factory by default, builder for lifecycle states, no object mothers.**

  | Pattern | Definition lines | Call lines | Edits to add one required column |
  |---|---|---|---|
  | object mother | **1,063** | 240 | **145** — and 145 only goes up |
  | builder | **55** | **773** | **1** |
  | **factory** | **55** | **240** | **1** |

  Object mothers scale with *combinations*, not tests: 240 tests demanded **145** distinct
  mothers (**1.7** tests each) against a ceiling of 2^15 = **32768**. That is **19x** the
  fixture code for the same suite. A builder's extra **773** call lines buy one thing —
  every precondition has a greppable name — so use it only where the domain has states
  with rules attached (`suspended()`, `refunded()`), not for plain fields.

- [ ] **Rule 4 — `function` scope unless the object is provably immutable.** See section 5.

---

## 3. Unique fields — do this one today

The line to grep for, in any language:

```bash
grep -rnE 'rand(om|int|range)?\([^)]*\)\s*[^)]*@|uniqid|Math\.random' tests/ | head -40
```

- [ ] No unique field is generated by bounded randomness anywhere in the suite
- [ ] Every `UNIQUE` column has a `Sequence` / `itertools.count` / autoincrement source
- [ ] `Faker.seed(<constant>)` is pinned in `conftest.py`, and `Faker` is used **only**
      for fields nothing asserts on and nothing constrains
- [ ] Anyone who says "we've never seen it collide" has been shown the table below

**The threshold, as reference arithmetic.** This is a birthday problem, so the
probability grows with the **square** of the suite size — with `n` draws from `m` slots
there are `n(n-1)/2` pairs. `randint(1, 10**6)` measured, analytic against simulation:

| Suite size | Analytic | Simulated | Expected duplicate pairs |
|---|---|---|---|
| 100 | 0.4938% | 0.5150% | 0.005 |
| 250 | 3.0648% | 2.9250% | 0.031 |
| 500 | 11.7301% | 11.5250% | 0.125 |
| 1,000 | 39.3267% | 41.6000% | 0.499 |
| 2,000 | 86.4710% | 84.7000% | 1.999 |
| 5,000 | 99.9996% | 100.0000% | 12.498 |

**A 1% chance of a red build per run — for this reason alone — arrives at 143 tests.**
Not 5,000. At 5,000 tests it is **99.999634%**: not a flaky suite, a broken one that
passes **0.000366%** of the time.

Compute your own threshold rather than trusting the table — paste this into a REPL:

```python
import math

def birthday_p(n: int, m: int) -> float:
    """P(at least one collision) drawing n values uniformly from m, exactly.
    log1p/expm1 keep precision where the naive product underflows."""
    if n > m:
        return 1.0
    return -math.expm1(sum(math.log1p(-i / m) for i in range(n)))

birthday_p(YOUR_TEST_COUNT, YOUR_VALUE_SPACE)   # > 0.01 means fix it this sprint
```

**Choosing the replacement** — the gap between these is not a matter of taste:

| Strategy | Distinct values | P(collide) across 5,000 tests |
|---|---|---|
| `randint(1, 10**6)` | 1,000,000 | **99.999634%** |
| `randint(1, 10**12)` | 1,000,000,000,000 | 1.250e-05 |
| random 8-hex suffix (`16**8`) | 4,294,967,296 | 2.906e-03 |
| `uuid4` — 122 random bits (RFC 9562) | 5.317e+36 | 2.351e-30 |
| **`Sequence` / `itertools.count`** | unbounded | **0 by construction** |

An 8-hex suffix *looks* thoroughly random and still collides at **2.906e-03** per run.
Prefer the sequence: it is not "more random", it is a different guarantee — uniqueness
proved rather than probable, for one integer of state per factory.

- [ ] Understood: **seeding does not fix this.** A seeded RNG collides in the same place
      every run, which is better (deterministic failures are debuggable) but not fixed.

---

## 4. SubFactory budget — referential integrity is not free

- [ ] Every test that needs a collection creates the parent **once** and passes it in
      (`create_batch(10, order=order)`, never a loop of `OrderItemFactory()`)
- [ ] Mutual foreign keys are broken with `post_generation`, not with two `SubFactory`
      declarations pointing at each other
- [ ] `sqlalchemy_session_persistence = "flush"` — **never `"commit"`**; a committing
      factory defeats rollback isolation and leaks rows into the next test
- [ ] `build()` vs `create()` is deliberate per factory (a `SubFactory` under `build()`
      still *creates* the parent unless you pass a build strategy)

**The bill, measured.** One requested `order_item` walked the foreign keys and wrote:

```text
      account=2  catalogue=1  order=1  order_item=1  product=1  shipping_address=1  user=2
      TOTAL 9 rows for 1 requested row
```

Note `user=2`: the order made a user and the order's shipping address made another. The
test now holds a graph that satisfies every constraint and models nothing real.

| Pattern | Rows | Orders | Users |
|---|---|---|---|
| each item builds its own parents | **90** | 10 | 20 |
| parents created once and passed | **16** | 1 | 1 |

**5.6x** — and the expensive version is also *wrong*: it builds ten orders of one item
each, not one order of ten. At suite scale the chain costs **240 x 9 = 2,160** rows
written for 240 asked for, which is what makes section 5 necessary.

Mutual FKs have no base case at all: recursion reached **depth 50** and wrote **50 rows**
before an artificial limit stopped it (in `factory_boy`, a `RecursionError` from a line
that looks like a declaration). The two-statement fix writes **2**. Always 2.

---

## 5. Volume — split the suite by whether a test writes

- [ ] **Read-only bulk** → one `session`-scoped corpus, built once, never mutated
- [ ] Immutability is **enforced**, not assumed — a read-only connection, or a
      session-scoped teardown asserting row counts are unchanged
- [ ] **Writers** → per-test data inside a transaction that rolls back, at whatever
      volume that test genuinely needs (usually five rows, not ten thousand)
- [ ] The middle case (needs bulk *and* writes) is batched, and then left alone
- [ ] Checked: `pytest-xdist -n auto` gives every worker its **own** session fixture —
      confirm that is "fine" and not "one container per worker"

**Measured over 300 tests each needing a 1,000-row corpus, real sqlite3, BEGIN/ROLLBACK:**

| Strategy | Rows written | Statements | Corpus builds |
|---|---|---|---|
| per-test, row by row | 300,000 | 300,900 | 300 |
| per-test, one batch (COPY-shaped) | **300,000** | **1,200** | 300 |
| session corpus + per-test writers | **70,000** | 510 | 70 |

Read the first two rows together — they are the trap that looks like a fix. **The batch
writes exactly the same 300,000 rows.** It cuts round trips **251x** and rows **0x**.
Rows are the floor you cannot batch away.

Only sharing removes rows, and it under-delivers: a **300x**-looking win returned **4.3x**,
because **69 of 300 tests (23.0%)** write to the corpus and must build their own.

> You cannot share a corpus with a test that changes it. Do not fight the 4.3x by making
> writers share — the failure mode is order-dependent tests, which cost far more than the
> CI seconds you saved.

---

## 6. Production data — the answer is no

If a production dump is already in a test environment, treat this section as an incident,
not a checklist. That environment is a production data store with none of the controls.

- [ ] No test environment holds real customer rows
- [ ] If overruled, every quasi-identifier is **generalised before the data leaves
      production** — city not postcode, birth *year* not birth date
- [ ] No column is protected by a bare consistent hash on an enumerable domain
- [ ] Nobody has "fixed" anything by shuffling a column within itself
- [ ] The dump is under production access controls, retention and audit — because it is
      still production data

**Attack 1 — the consistent hash.** Replacing `email` with `sha256(email)` preserves
joins, which is why people do it. Corporate address formats are public, so the attacker
does not need to know who is in the dump — they enumerate the whole name space:

```text
  whole name space: 200 x 300 = 60,000 candidates hashed.
  rows re-identified: 20,000 of 20,000 (100.0%)
```

**60,000 SHA-256 calls recovered every row.** A consistent hash is not encryption; it is
an equality check over a domain the attacker can enumerate. Salting it per-dataset breaks
exactly the joins you kept it for.

**Attack 2 — the columns you did not mask** (Sweeney, *k-Anonymity*, IJUFKS 10(5), 2002).
A row is re-identified when its quasi-identifier is unique in the data:

| Quasi-identifier | Distinct cells | k=1 rows | Share |
|---|---|---|---|
| (city, birth_year, gender) | 2,998 | 31 | **0.2%** |
| (postcode, birth_year, gender) | 16,961 | 14,250 | 71.2% |
| (postcode, birth_year, birth_day, gender) | 19,991 | 19,982 | **99.9%** |

Row three is a date of birth — which every "anonymised" dump keeps because the tests
"need realistic ages" — and it leaves **99.9%** of the dump uniquely identifiable from
three facts a stranger can look up. Generalising to row one takes it to **0.2%**, at the
price of exactly the realism you took the dump to get.

**The fix that is worse than either attack.** Shuffling a column within itself:

```text
  marginal distribution preserved exactly               True
  rows whose city still matches their address            971  4.86%
  rows whose country still matches their city          2,650  13.25%
  tests asserting a cross-table invariant                 43  17.9% of the suite
```

Every histogram is perfect and every join is fiction — the worst available combination,
because the data looks real enough that nobody checks it and no invariant in it holds.
**43 of 240 tests (17.9%)** go red for no reason connected to the code.

> The properties you wanted from production data — real distributions, real edge cases —
> are properties you can generate. A factory has no PII to leak.

---

## 7. Golden / approval files

- [ ] Goldens are stored **pretty-printed with sorted keys**, never one-line JSON
- [ ] Every volatile field (timestamps, ids, durations, hostnames) is scrubbed or
      injected before comparison
- [ ] Goldens are small and per-behaviour, not one giant snapshot per endpoint
- [ ] A golden update in a PR is reviewed as a **change to expected behaviour**
- [ ] Nobody has an accept-all command bound to a keystroke

**Format is the test.** Same 60 files, same benign change (one added `currency` field):

| Format | Files | Diff lines | Diff chars | Chars/file |
|---|---|---|---|---|
| `json.dumps(obj)` — one line, no spaces | 60 | 120 | 40,726 | 679 |
| `json.dumps(obj, indent=2, sort_keys=True)` | 60 | 60 | 1,260 | **21** |

**32x the characters to read.** A reviewer approves 679 characters of changed JSON per
file faster than 21 — having read none of it.

**One volatile field destroys the review.** With a `generated_at` timestamp in the golden
and one genuine regression (VAT at 20% instead of 19% on a single response):

```text
  goldens that changed this run                    60 of 60
  goldens with a real behaviour change              1 of 60
  diff lines the reviewer must read               122
  diff lines that mean anything                     4
  signal ratio                                   3.3%
```

A **3.3%** signal ratio is not a review. It is an accept-all with extra steps, and the one
real regression ships inside the noise.

```python
# syrupy: scrub before you compare, or you get the 3.3%.
from syrupy.matchers import path_type

def test_order_response(client, snapshot):
    body = client.get("/orders/1").json()
    assert body == snapshot(matcher=path_type({
        ".*generated_at": (str,),      # present and a string; value ignored
        ".*id": (int,),
    }, regex=True))
```

---

## 8. Migration order

You will not convert 240 tests in a week. Convert in the order the coupling matrix gives
you, so that each day's work removes the most future blast radius per test touched.

- [ ] **1.** Rank cells by tests-reading-them (section 1, step 2). The head is the work.
- [ ] **2.** Convert every test reading the top cell first — measured, the top cell alone
      held **28 tests (11.7%)** and the top five held **29.2%** of all reads
- [ ] **3.** Stop when no seed cell is read by more than one test. That is the finish
      line, and it is checkable: the factory world's number is **cells read by 2+ tests = 0**
- [ ] **4.** Leave the ballast alone. **4,296 of 4,353 rows** cost nothing; deleting them
      feels productive and changes no number on this page
- [ ] **5.** Delete the seed file only when step 3 passes — not before, and not by half

---

## 9. Sign-off

- [ ] Blast radius measured on this repo, written down, and under 5 tests
- [ ] No unique field generated by bounded randomness; `birthday_p` run on the real numbers
- [ ] `Faker.seed()` pinned; factories persist with `flush`, not `commit`
- [ ] Parents created once and passed in; no mutual `SubFactory` pair
- [ ] `function` scope by default; session scope only for provably immutable objects,
      with the immutability enforced
- [ ] No production data in any test environment
- [ ] Goldens pretty-printed, sorted, scrubbed, and reviewed like assertions
- [ ] The fixture policy from section 2 is in the repo, and the last PR that broke it
      was sent back
