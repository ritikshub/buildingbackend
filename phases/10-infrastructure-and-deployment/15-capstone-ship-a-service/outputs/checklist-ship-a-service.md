---
name: checklist-ship-a-service
description: The end-to-end shipping checklist — build to rollback — with the seam checks that no single stage owns, each item earned by a measured failure.
phase: 10
lesson: 15
---

# Ship a Service End to End

Every item exists because skipping it produced a measured cost in
`code/ship_it.py`. Numbers in parentheses are that cost.

The last section is the important one. Items 1–6 are things one team owns.
**Section 7 is the seams — pairs of numbers, each correct on its own, that
nobody currently compares.** Every failure in the capstone lived there.

---

## 1 · Build & pin

- [ ] **Dependencies are copied and installed above application source** in the
      Containerfile. A cache miss invalidates every layer below it, so a one-line
      source edit under `COPY . .` rebuilds the installer. *(0.8 s vs 394.2 s — 493×)*
- [ ] **The build is reproducible.** `SOURCE_DATE_EPOCH` set, archive entries
      sorted, dependency versions pinned by lockfile. Two machines must produce
      one digest, because the digest is the identifier every later stage keys on.
- [ ] **Nothing downstream references a tag.** Not `:latest`, not `:4.2.0`.
      A tag is a mutable pointer; a digest is the content.
- [ ] **The artifact is signed and carries provenance** naming the builder and
      the source commit. Pinning answers *which* bytes; it says nothing about *whose*.
- [ ] **Admission control enforces all three** — pinned, signed, provenance from a
      trusted builder — at the cluster door, not in the pipeline that could be
      bypassed. *(4 of 5 candidate references denied, two of them correctly digested)*
- [ ] **One build, promoted.** The digest that passed tests is the digest that
      reaches production. A per-environment rebuild voids every test you ran.

## 2 · Config & release identity

- [ ] **`release = build + config`**, and the release id is recorded and shown on
      deploy annotations. A config-only change is a deploy and can cause an incident.
      *(1 artifact, 3 configs, 3 release ids)*
- [ ] **Every required key is validated at boot, before the listening socket
      opens.** Typed, bounded, unknown keys rejected. Refusing to start beats
      serving a wrong default — and be aware this converts a silent outage into a
      loud stall, which is the trade you want.
- [ ] **Config values are never baked into the image** at build time.
- [ ] **Environment parity is diffed in CI**, not discovered during a rollout.

## 3 · Infrastructure

- [ ] **Read the plan, not the summary.** A `replace` counts once in "to add" and
      once in "to destroy", so a full rebuild can show `0 to change` in the middle.
      *(one edited attribute replaced 3 of 4 resources)*
- [ ] **`prevent_destroy` on every stateful resource** — databases, buckets,
      anything holding data you cannot recreate. Cheapest guard in the phase.
- [ ] **Know which attributes are immutable** for each resource type. An immutable
      attribute turns "update" into "destroy and recreate", and a replaced
      resource's id becomes `(known after apply)`, which cascades to dependants.
- [ ] **Remote state with locking.** Two concurrent applies without a lock orphan
      resources that are alive, billed and unmanaged.

## 4 · Orchestration & routing

- [ ] **Reconciliation is level-triggered** — the loop re-derives its work from
      observed state, so a missed event costs one tick, not correctness.
      *(hand-scaled drift reverted in 1 tick)*
- [ ] **Readiness gates registration.** Registered ≠ healthy ≠ ready.
- [ ] **Budget the readiness gap in rollout planning.** Instances were *running*
      at t=3 s and *ready* at t=26 s; every rolling batch pays that interval.
- [ ] **Shutdown order is: deregister → wait longer than propagation → drain
      in-flight → exit.** The wait is the step everyone omits.
- [ ] **The server closes idle connections at drain start** (`Connection: close`,
      or HTTP/2 `GOAWAY`). This is the only drain fix that does not depend on your
      callers' configuration.

## 5 · Landing a risky change

- [ ] **The migration and the code deploy are separate releases.** Expand runs
      *before* its deploy; contract runs *after* its deploy has fully rolled out
      and soaked. *(one-step version: 48,983 5xx + 32,259 silent bad reads)*
- [ ] **Never rename or drop in the same release that changes the readers.**
      Add, dual-write, backfill in bounded batches, move readers, stop writing the
      old, then drop — five separately deployable steps.
- [ ] **`lock_timeout` is set on every DDL statement**, with jittered retry.
      A DDL that is merely *waiting* blocks every query behind it.
- [ ] **The new code path ships behind a flag defaulted off.** The artifact rolls
      out dark; exposure moves separately. *(17,250 requests served before anyone
      could reach the new path)*
- [ ] **Canary analysis counts requests that EXECUTED the new path**, not requests
      that arrived at the canary instance. Emit the metric from inside the new path,
      tagged with the flag variant. *(302 meaningful samples vs 250 accidental ones)*
- [ ] **The analysis compares outcomes, not just errors and latency.** A wrong
      computation returns HTTP 200 and moves no error rate.
      *(0 errors, 57,614 mispriced orders)*
- [ ] **Every exposure step has a pre-agreed abort criterion and a minimum sample
      count**, decided before the ramp starts.

## 6 · Incident readiness

- [ ] **The reachable rollback set is computed in CI**, from each build's declared
      reads against the migration history. Fail the build when a release takes the
      reachable set to zero without a written waiver. Two subset comparisons.
- [ ] **Contract is its own pull request**, with the sentence *"after this merges,
      the fastest mitigation for feature X is a roll-forward taking N minutes"*
      filled in. If nobody can fill in N, it is not ready.
      *(6.7 s → 849 s once the column was dropped)*
- [ ] **The kill switch has been exercised** in the last quarter. An operational
      toggle nobody has flipped in eleven months is a code path nobody has run.
- [ ] **Time-to-mitigate is decomposed and each term is owned.** A flag flip is an
      operator decision plus a control-plane write plus a push plus a cache TTL —
      swap a streaming SDK for a 30-second poller and your fastest mitigation
      is 33 s instead of 6.7 s, with nothing else changed.
- [ ] **RTO is measured on production-sized data**, re-timed whenever the dataset
      grows by half, and restore verification runs on a schedule.
- [ ] **A saturation alert exists on every quota you do not own** — partner rate
      limits, third-party APIs, downstream pools. *(a ramp ran at 96% of a partner
      quota and nothing said so)*

## 7 · The seams — pairs of numbers nobody compares

Write each pair on the same page. Give the pair an owner. Check it automatically.

| The two numbers | The failure when they disagree | Measured |
|---|---|---|
| server drain window **vs** client max connection lifetime | pooled connections outlive the drain and break on exit | 480 severed per rollout |
| canary population **vs** flag cohort | the canary reports clean for a path it never executed | 250 of 24,600 requests |
| soak duration at 100% **vs** when contract ships | the kill switch is deleted before you need it | 6.7 s → 849 s |
| readiness gap **vs** progress deadline | the rollout stalls half-migrated and only *reports* | 909 s, no rollback |
| peak exposure volume **vs** every downstream quota | a fault that only exists at full volume | 96% of quota, unalerted |
| migration ordering **vs** deploy ordering | expand after its deploy, or contract before it | 48,983 5xx + 32,259 bad reads |
| config version **vs** artifact version | "we didn't deploy anything" during an incident | 3 release ids, 1 digest |

---

**The one-line version.** Every stage in your pipeline can be correct while the
system is unsafe, because safety is a property of the joins. When something breaks,
ask which two correct things composed — the answer is almost never a bug in one of them.
