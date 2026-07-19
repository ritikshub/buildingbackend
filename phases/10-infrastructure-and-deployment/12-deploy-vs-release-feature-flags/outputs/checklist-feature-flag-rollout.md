---
name: checklist-feature-flag-rollout
description: Take one change from merged-and-dark to fully released and the flag deleted — bucketing, defaults, ramp criteria, the kill-switch drill, and the removal that is part of done.
phase: 10
lesson: 12
---

# Shipping behind a flag — creation to deletion

Work top to bottom. Sections 1–3 happen before the flag is created, section 4 before the first
user sees anything, sections 5–7 during the ramp, section 8 is the incident path, and section 9
is the part teams skip — which is why the median flag system has 13 dead flags in it.

Every item here exists because skipping it caused a real outage, a corrupted experiment, or a
flag nobody dared delete.

---

## 1 · Decide what kind of flag this is — before you name it

- [ ] The flag is classified as exactly one of: **release**, **operational / kill switch**,
      **experiment**, **permission / entitlement**. Write the kind into the flag's description.
- [ ] **Release toggle** → short-lived, owned by the feature team, deleted at 100%.
- [ ] **Operational / kill switch** → permanent, owned by whoever is on call, exercised on a schedule.
- [ ] **Experiment** → lives as long as the experiment, owned by product/data, has a stop date.
- [ ] **Permission / entitlement** → permanent business logic. It is **not** debt, it belongs under
      test, and it must never be swept up in a flag cleanup. Its source of truth is the billing or
      entitlement system, not the flag console.
- [ ] If the answer is "it's a bit of both", split it into two flags. Conflated kinds are why flag
      systems rot.

## 2 · Owner and expiry, recorded at creation

- [ ] **An owning team** (not an individual who may leave) is set as a required field.
- [ ] **An expiry date** is set: release ~60 days, experiment ~90 days, operational/permission `--`.
- [ ] The cleanup ticket exists **now**, in the same sprint as the rollout, not "next quarter".
- [ ] The flag key is final. Renaming a flag re-rolls every user's bucket, because the key is the
      hash salt — mid-rollout, that moves everybody's variant at once.

## 3 · Reversibility: is this actually a two-way door?

- [ ] Answer in writing: **if I flip this back after an hour of production traffic, is every row,
      event and cache entry the new path produced still readable by the old path?**
- [ ] New/renamed columns: both shapes are readable and both are being written (expand/contract).
- [ ] New event or message schema: the old consumer tolerates it, or it goes to a new topic.
- [ ] New cache key format: old and new keys coexist; flipping back does not serve stale wrong data.
- [ ] Anything irreversible (a destructive migration, an external side effect, an email send) is
      **not** behind this flag, or is behind a separate one-way gate with its own review.
- [ ] If any answer above is "no", stop. The flag is a one-way door wearing a two-way door's costume.

## 4 · Evaluation mechanics — get these right once

- [ ] Bucketing is a **deterministic hash of a stable identifier**, never a per-request random draw.
      `sha256(flag_key + ":" + stable_id)`, first 8 bytes as an integer, `% 10000` for basis points.
- [ ] The hash is **cryptographic**, not the language's built-in `hash()` — Python randomises
      `str.__hash__` per interpreter, so buckets would differ across processes and restarts.
- [ ] The **flag key is mixed into the hash** (the per-flag salt). Without it every flag at 10%
      selects the identical users — measured overlap 100% instead of 9.74%.
- [ ] The identifier is stable across the whole journey: not a session id, not a device id, not an
      IP. If anonymous→authenticated matters, carry the anonymous id forward and keep hashing it.
- [ ] Evaluation is **local, in-process, against a cached ruleset**. No network call per evaluation.
- [ ] The SDK has a **bounded initialization timeout**, so a slow control plane at boot cannot stop
      your pods passing readiness. The flag service is a **soft** dependency; wire it as one.
- [ ] The **coded default** is this flag's known-good value, and it was chosen deliberately:
      risky new path → `False`; kill switch → `True`. There is no globally safe direction.
- [ ] The flag is read **once per request** into a local variable. Two reads can straddle a ruleset
      update and disagree within one response.
- [ ] Services that must agree on the same flag for the same request use the **same identifier and
      salt**, or the decision is propagated in request context rather than recomputed downstream.
- [ ] Rule order is checked: narrow blocking rules (a region hold, a compliance gate) sit **above**
      the percentage rollout, so a ramp can never expose a population you fenced off.

## 5 · Before the first user: observability

- [ ] Every evaluation on a flagged path logs the **flag key, evaluated variant, matching rule, and
      request/trace id**. Without this, "what did this user see?" is unanswerable mid-incident.
- [ ] Your key metrics can be **sliced by variant** — error rate, latency, and the business metric
      the change is meant to move. A dashboard that cannot split by variant cannot judge a ramp.
- [ ] An alert fires on an **exposure change** itself (e.g. a jump from 5% to 100%), not only on the
      error rate that follows it.
- [ ] Both branches are exercised in CI, **and** there is a test that runs with the flag provider
      unavailable and asserts the coded default.

## 6 · The ramp plan, written before the ramp

- [ ] The steps are written down: internal staff → 1% → 5% → 25% → 100% (or your equivalent).
- [ ] **Each step has a soak time justified by event volume**, not by feel. At 1% exposure you
      collect 1% of the events, so detecting a small regression takes ~100× longer than at full
      traffic. A ten-minute soak at 1% usually proves nothing.
- [ ] The **abort criteria are numeric and pre-agreed**: which metric, which threshold, over which
      window — ideally expressed against an SLO/error budget.
- [ ] A named person is watching each step, or a controller is automating promote/abort.
- [ ] **Exposure does not change during a deploy.** Two moving variables means an incident spent
      arguing about which one did it.
- [ ] Compliance/regional holds are in place as rules above the rollout, with an owner and a
      reason recorded (e.g. a pending data-processing agreement review).

## 7 · During the ramp

- [ ] User-share and request-share of the new path are **the same number**. If they diverge,
      bucketing is not sticky and the rollout is bigger than you think.
- [ ] Variant switches per user is **zero**. Any non-zero value means users are flickering.
- [ ] The cohort is checked for overlap with other in-flight experiments before results are read.
- [ ] Errors are compared **within variant**, not against the fleet average — at 1% exposure a real
      regression is invisible in the aggregate.

## 8 · The kill-switch drill (do this before you need it)

- [ ] The mitigation is a **flag flip, not a deploy**. Measured: 4.3 s versus 304 s for a rollback
      of the same failure — 71×, and the ratio gets *worse* (113×) once you remove the human
      decision from both, because the cost is machinery, not deliberation.
- [ ] You know your SDK's worst-case propagation delay. Streaming + a short cache TTL ≈ 4.3 s;
      a 30-second polling interval ≈ 33.4 s for the identical flip.
- [ ] The runbook names **who can flip this flag at 03:00** and how they authenticate. A kill switch
      behind an approval workflow is not a kill switch.
- [ ] Downstream caches are accounted for: a CDN or client cache in front of you sets the real floor
      on how fast users stop seeing the old behaviour.
- [ ] Kill switches are **flipped on a schedule** — monthly in staging, at least quarterly in
      production during a quiet window. An unexercised kill switch is untested code on the path you
      need most.
- [ ] Flipping back to 0% is verified to be safe against section 3's reversibility answers.

## 9 · Removal — this is what "done" means

- [ ] The rollout is **not done at 100%**. It is done when the flag and the dead branch are gone
      from the code and from the console.
- [ ] The losing code path is deleted, not commented out or left behind an `if True:`.
- [ ] The flag is removed from the flag service after the code that reads it is fully deployed —
      in that order, never the reverse.
- [ ] A **stale-flag review runs weekly**: flags past expiry, flags at 100% for over a week, flags
      at 0% for over a month, flags with no evaluations in 30 days. Each means something different.
- [ ] No release toggle has quietly become business logic. A "temporary" flag parked at 30% for six
      months is a product decision living in an incident tool with no tests — either finish the
      rollout or move it into code as an explicit, tested rule.

---

## The arithmetic that justifies section 9

```text
live flags N   reachable configurations 2^N   tested (baseline + each + pairs)   coverage
          10                         1,024                                 56    1 in 18
          20                     1,048,576                                211    1 in 4,969
          30                 1,073,741,824                                466    1 in 2,304,167
          40             1,099,511,627,776                                821    1 in 1,339,234,625
```

A measured 40-flag inventory: 22 release, 7 experiment, 6 operational, 5 permission — with
**13 past their expiry date and the oldest release toggle 190 days old.** Deleting those 13
`if` statements takes the reachable state space from 2^40 to 2^27: an **8,192× reduction**, for
an afternoon of work that ships no features. Production picks from all of those configurations,
one user at a time, and the one that breaks is by definition one you never ran.

## Five rules, if you keep nothing else

1. **Evaluate locally** against a cached ruleset — never a network call per evaluation.
2. **Default safely, per flag** — the coded fallback is that flag's known-good value.
3. **Bucket deterministically, with a per-flag salt** — same user, same variant, independent cohorts.
4. **Log the evaluated variant with request context** — so an incident can answer "what did this
   user see?"
5. **Delete flags on a schedule** — an owner and an expiry on every one, removal in the
   definition of done.
