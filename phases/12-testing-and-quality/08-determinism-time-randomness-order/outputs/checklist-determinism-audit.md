---
name: checklist-determinism-audit
description: Audit a test suite for hidden inputs — clock, timezone, randomness, ids, iteration order, test order, floats and the scheduler — with the commands to run and the thresholds to compare against.
phase: 12
lesson: 8
---

# Test Suite Determinism Audit

Run this against one suite. Every reference number came from the measured runs in
`code/determinism.py`; replace them with your own once you have measured.

Work top to bottom — items 0 and 1 are free and find most of it. A suite that fails items
1, 2 or 6 has flakes it has not noticed yet.

## 0 · Establish the baseline (10 minutes, no plugins)

```bash
pytest -q                                  # green in file order? if not, stop and fix that
pytest -q -p no:randomly --co -q | wc -l   # how many tests are we auditing
```

- [ ] Suite is green in file order. **This proves nothing.** A 200-test suite with three
      real order dependencies was green in file order — that is the normal starting state.
- [ ] Record the test count. You need it to size the shuffle budget in item 6.

## 1 · The reversed run — do this before installing anything

```bash
# pytest has no --reverse; a conftest hook is 3 lines and is worth committing
# conftest.py:
#   def pytest_collection_modifyitems(items):
#       if os.environ.get("REVERSE"): items.reverse()
REVERSE=1 pytest -q
```

- [ ] **Reversed run is green.** If not, you have found precedence dependencies for free.
      Reference: one reversed run caught **2 of 3** planted dependencies, with certainty —
      a green file order means every "A before B" pair is satisfied by file order, so
      reversing violates all of them.
- [ ] Understand what it cannot catch: a **count** dependency (N tests each leak one item;
      an assertion trips at a threshold) is invisible to any fixed order. In the reference
      suite 20 leakers sat before the assertion and 19 after, with 39 needed — file order
      saw 20, reverse saw 19. Only sampling reaches it.

## 2 · The clock

- [ ] `grep -rn "datetime.now()\|date.today()\|time.time()\|utcnow()" --include="*.py" src/`
      — every hit in non-test code is an untestable-by-construction dependency.
- [ ] **`datetime.utcnow()` is zero-tolerance.** Deprecated in 3.12; returns a *naive*
      datetime that lies about being UTC. Use `datetime.now(tz=timezone.utc)`.
- [ ] Every timeout, TTL, retry, backoff, lease and schedule takes a **clock port**
      (`now()` / `sleep()`), not a module-level import.
- [ ] **Freeze vs control is decided per test.** Freeze when asserting about an *instant*;
      control when asserting about a *duration*.

| The test asserts about | Tool | Reference measurement |
|---|---|---|
| what is true at time T | `@time_machine.travel(..., tick=False)` | frozen reached 4/6 behaviours |
| a duration, timeout, backoff, TTL sweep | controllable clock / `time_machine.shift()` | controllable reached **6/6**, cost **0 s** |
| nothing time-related | leave it alone | — |
| real time, no injection | last resort | 6/6 but **937 s = 15.6 min** for six assertions |

- [ ] **Hunt for the silent pass.** A timeout test that is green AND fast is the signature.
      Under a frozen clock `wait_for()` returned the expected `False` having advanced
      **0.0 s** — it never reached a deadline. Assert on elapsed logical time, not just the
      return value:

```python
started = clock.now()
assert wait_for(...) is False
assert clock.now() - started >= timeout      # <- the assertion that catches a frozen clock
```

- [ ] Prefer `time-machine` over `freezegun` (C-level patching, ~an order of magnitude
      faster). Prefer a port over both for code you own.

## 3 · Timezones and the calendar

- [ ] All stored instants are UTC and timezone-aware. All arithmetic happens in UTC.
- [ ] `zoneinfo` + IANA names (`"Europe/Berlin"`), never fixed offsets. `tzdata` is a
      pinned explicit dependency — slim container images may ship no tz database at all.
- [ ] Where a wall-clock *intention* exists ("bill on the 1st at 09:00 local"), the user's
      IANA zone name is stored alongside the instant.
- [ ] **Month/year arithmetic has an explicit clamp rule, written down.** Reference: an
      annual renewal from `2024-02-29` is due `2025-02-28` — because the code decided,
      not because a library did. `dt.replace(month=...)` raises `ValueError` on 31 Jan.
- [ ] Tests exist for the four dates that break things: **the gap** (Berlin 2024-03-31
      02:30 → **0** UTC instants), **the fold** (2024-10-27 02:30 → **2**, at 00:30Z and
      01:30Z), **29 February**, and **the last day of a 31-day month**.
- [ ] `fold` (PEP 495) is set deliberately wherever a local time can be ambiguous. If you
      never set it, `fold=0` chose the first occurrence for you.

> Reference: a wall-clock renewal implementation was wrong at **1,454 of 8,784 hours
> (16.6%)** of 2024 — **1,438** an hour out across DST, **16** a whole day out from
> disagreeing clamps. Moving to UTC fixes 1,438 of them; the other 16 need the clamp rule.
> The same-day-of-month property failed at **704 hours (8.0%)**, **572** of them at 22:00
> and 23:00 UTC. If your suite "only fails at night", this is why.

## 4 · Randomness

- [ ] No module-level `random.seed(N)` in `conftest.py` as the only seeding strategy.
      With 8 xdist workers that produced **3,501 of 4,000 duplicates (87.52%)**, only
      **499** distinct values.
- [ ] Unique fields come from a **per-worker namespace**, not a random draw:

```python
WORKER = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
email = f"u{WORKER}-{next(counter)}@test.invalid"      # 0 collisions, by construction
```

- [ ] Understand why per-worker *seeding* is not enough: 4,000 draws from 10^6 gives
      **7.99 expected collisions** and a **99.9664%** chance of at least one. Model and
      simulation agreed (measured: **7**). Widening the space makes the flake rarer and
      less reproducible, not absent.
- [ ] `Faker` is seeded (`Faker.seed()`) — unseeded it is the same generator with nicer
      output. `pytest-randomly` reseeds it per test for you.
- [ ] `secrets` / `os.urandom` are used only where unpredictability is the point; they
      cannot be seeded and must never feed a reproducible assertion.
- [ ] Seeded RNGs are owned instances (`random.Random(n)`), not the module-level functions
      that share one global state.

## 5 · Identifiers and iteration order

- [ ] No assertion on a generated id value. Assert on what you put in the row.
- [ ] No `ORDER BY`-less query whose result order is asserted on. Reference: the same
      query on the same five rows returned `[50, 40, 30, 20, 10]` before a migration and
      `[10, 20, 30, 40, 50]` after `CREATE INDEX` — and `[50, 40, 20, 10, 30]` after a
      fixture deleted and re-inserted one row.
- [ ] No assertion on `set` iteration order. Reference: 4 tags across 512 hash seeds
      produced **all 24 possible orderings**; the order your machine showed you holds on
      **4.30%** of processes. `hash(int)` is *not* randomised, which is why half your sets
      look fine and the bug reads as pedantry.
- [ ] `sorted(glob.glob(...))` in every fixture loader — directory order is filesystem
      order and differs between ext4, APFS and a container overlay.
- [ ] Sort before comparing collections, or compare as sets so the assertion says so.
- [ ] If ordering by id: know that UUIDv7 is ordered only **to the millisecond**. Two ids
      created back to back inverted **49.68%** of the time — indistinguishable from
      UUIDv4's 50.00%. Add an explicit `created_at` and `ORDER BY created_at, id`.
- [ ] Know your schema's sequence semantics: `assert order.id == 1` passed with
      `INTEGER PRIMARY KEY` and failed with `INTEGER PRIMARY KEY AUTOINCREMENT` (id = 4)
      on identical data. Postgres `SERIAL`/`IDENTITY` sequences are non-transactional and
      burn values on rollback.

## 6 · Test execution order

```bash
pip install pytest-randomly
pytest -q                                   # shuffles + reseeds random/Faker per test
pytest -q -p no:randomly                    # turn OFF to bisect a failure
pytest -q --randomly-seed=<seed from the failure>   # replay
```

- [ ] `pytest-randomly` is installed and NOT disabled in `pytest.ini`.
- [ ] **The printed seed is recorded on every CI failure.** A failure report without the
      seed is not reproducible. Record: test id, seed, xdist worker, duration, commit.
- [ ] With `pytest-xdist`, use `--dist loadfile` if any ordering assumption is per-file;
      `--dist load` distributes tests in a way a seed alone will not reproduce.
- [ ] Size the audit rather than guessing. For a per-run detection probability `p`:

```python
runs = math.ceil(math.log(1 - confidence) / math.log(1 - p))
```

| What you want to know | Per-run p | Runs @95% | Runs @99% |
|---|---|---|---|
| does this suite have *any* order dependency | 0.8353 | 2 | **3** |
| the precedence dependency (A before B) | 0.4928 | 5 | 7 |
| the shared-table + truncate dependency | 0.6645 | 3 | 5 |
| the count dependency (39 leakers, threshold 39) | 0.0265 | 119 | **182** |

- [ ] **A nightly job runs the full suite N times with different seeds and diffs the
      failure sets.** Set N from the table: 3 runs answers "is there a problem"; the
      complete answer is priced by your rarest dependency, and 182 runs at one CI run per
      merge is weeks.
- [ ] `PYTHONHASHSEED` is **not** pinned in the Dockerfile, `tox.ini` or CI config. Pinning
      it to make a suite green hides the bug until production, where it is random again.

## 7 · Floating point and money

- [ ] Money is `Decimal` or integer minor units end to end. No float arithmetic on currency.
- [ ] No bare `assert a == b` on accumulated floats. Reference drift: **1.43e-11** on
      `0.01` added 10,000 times (`100.00000000001425`); `==` produced false alarms on
      **4 of 6** magnitudes.
- [ ] **No bare `pytest.approx` on a currency total.** Its default `rel=1e-6` goes blind to
      a one-cent error at **$10,000** and missed the seeded bug on **3 of 6** magnitudes.
      `math.isclose`'s default `rel_tol=1e-9` missed **1 of 6**.
- [ ] Where floats must be compared, the tolerance is absolute and explicit:

```python
assert total == pytest.approx(expected, rel=0, abs=0.005)     # half a cent
math.isclose(total, expected, rel_tol=0.0, abs_tol=0.005)     # 0 false alarms, 0 misses
```

      `rel_tol` is set explicitly to 0 — `isclose` ORs its two conditions, so a non-zero
      relative tolerance silently reopens the hole.

## 8 · Concurrency

- [ ] Any read-modify-write under concurrency has a test that **enumerates** interleavings
      rather than sampling them. Reference: of the 20 interleavings of two threads doing
      `counter = counter + 1`, **18 (90%) lose the update** and a real test passes anyway.
- [ ] Understand why "we've never seen it in CI" is not evidence. At a per-step switch
      probability of 1e-4 you need **3,466 runs for an even chance** of observing it —
      173 days at 20 CI runs a day, and that run gets closed as a flake.

| Switch prob. per step | P(lost update) | Runs for 50% chance | At 20 CI runs/day |
|---|---|---|---|
| 1e-02 | 2e-02 | 35 | 2 days |
| 1e-03 | 2e-03 | 347 | 17 days |
| 1e-04 | 2e-04 | 3,466 | 173 days |
| 1e-05 | 2e-05 | 34,658 | 1,733 days |

- [ ] Async suites use a virtual/controllable event loop so `sleep(30)` costs 0 ms.
- [ ] `hypothesis` uses `@settings(derandomize=True)` on the CI gate and *not* in the
      nightly job, with `.hypothesis/examples` cached so a found case is pinned.

## 9 · Prove the fix

The whole audit reduces to one property: **the same command twice gives the same answer.**

```bash
pytest -q --randomly-seed=12345 > a.txt
pytest -q --randomly-seed=12345 > b.txt
diff a.txt b.txt                                   # must be empty

PYTHONHASHSEED=random pytest -q --randomly-seed=12345 | diff a.txt -
```

- [ ] Both diffs are empty. If the second is not, you have an iteration-order dependency
      (item 5) — the hash seed is the only thing that changed.
- [ ] The same two commands run against your own experiment/benchmark scripts, not just
      the suite. `code/determinism.py` is byte-identical across runs and across
      `PYTHONHASHSEED` values including `random`; hold your own tooling to that.

## The four settings to turn on today

1. **One reversed run**, now, before installing anything — caught **2 of 3**.
2. **`pytest-randomly`**, with the printed seed recorded on every CI failure.
3. **A clock port** on everything with a timeout, TTL, retry or schedule. Freeze for
   instants, control for durations.
4. **`Decimal` or integer minor units for money**; if you must use `approx`, pass `abs=`.
