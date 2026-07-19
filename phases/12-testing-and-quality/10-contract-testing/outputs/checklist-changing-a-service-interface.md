---
name: checklist-changing-a-service-interface
description: For the engineer about to change a request or response shape that another service reads — at design review, in the PR, and in the deploy job. Includes the breaking-change decision table, the deploy-order rule, and the gates to actually wire up.
phase: 12
lesson: 10
---

# Checklist: Changing a Service Interface

Use this when you are about to change the shape of anything another service reads or
writes — a JSON response, a request body, an event payload. Every number below was
measured by this lesson's `code/contract_testing.py`; the run parameters are printed by
the program itself.

**Scope:** the seam between two services. Not database schema changes (Phase 10 L13), not
event schema registries in depth (Phase 6 L12), not async delivery semantics (L11).

---

## 0. Before you open the PR — 5 minutes

- [ ] **Name every consumer of the field you are touching.** Not "we grepped our repo" —
      the change in this lesson's incident was verified against the *provider's own*
      repository and broke three downstream services.
- [ ] **If you cannot name them, that is the finding.** Ship a consumer contract, a
      request-log field-usage report, or a schema-registry subject *first*. Everything
      below assumes you know who reads what.
- [ ] **Classify the change against §1.** Put the classification in the PR description in
      one sentence: *"response-side, backward-only, consumers deploy first."* That single
      line is what makes review possible for someone who is not in your domain.
- [ ] **Check whether it is semantic** (§5). If the field keeps its name and type and
      changes its meaning, no gate in this document will catch it. Stop and read §5.

---

## 1. Is it breaking? — the decision table

Compatibility is a property of a **(reader, writer) pair**, never of a schema alone.

- **BACKWARD** = the new reader can read old data → **the reader may ship first.**
- **FORWARD** = old readers can read new data → **the writer may ship first.**
- For a **RESPONSE** the reader is the **consumer**. For a **REQUEST** it is the **provider**.

| # | The change | Where | Backward | Forward | Ship first |
|---|---|---|---|---|---|
| 1 | add an optional field with a default | response | 400/400 | 400/400 | either |
| 2 | remove an optional field | response | 400/400 | 400/400 | either |
| 3 | remove a required field | response | 400/400 | **0/400** | consumer |
| 4 | rename a field | response | **0/400** | **0/400** | **no safe order** |
| 5 | widen a type `integer → number` | response | 400/400 | **0/400** | consumer |
| 6 | narrow a type `number → integer` | response | **104/400** | 400/400 | provider |
| 7 | **add a value to an enum** | response | 400/400 | **318/400** | consumer |
| 8 | **remove a value from an enum** | response | **296/400** | 400/400 | provider |
| 9 | **required → optional** | response | 400/400 | **296/400** | consumer |
| 10 | add a required field | request | **0/400** | 400/400 | consumer |
| 11 | required → optional | request | 400/400 | **282/400** | provider |
| 12 | **same name, same type, new units** | response | 400/400 | 400/400 | **SILENT — see §5** |

**Rows 7, 8, 9 are the ones people get wrong**, and all three feel permissive:

- [ ] **Adding an enum value is breaking.** Every consumer with an exhaustive
      `match`/`switch` and no default arm fails on the first message carrying it.
      *Adding to your output is a restriction on your reader's assumptions.*
- [ ] **Removing an enum value you no longer emit is breaking.** Old provider instances
      are still emitting it during the rollout, and stored rows may emit it forever.
- [ ] **Relaxing `required` to `optional` on a response is breaking.** The old reader
      still demands the field. Relaxation is safe on the **request** side only.

- [ ] **Row 4 is the one that needs expand–contract**, not a deploy order. Add the new
      field, dual-write both, migrate consumers, verify nobody reads the old one, then
      remove it (Phase 10 L13). Measured: 1,521 failures consumer-first and 1,546
      provider-first — there is no ordering that works.

---

## 2. Deploy order

- [ ] **Write down the order in the PR and in the deploy runbook.** "We'll deploy them
      together" is not an order — it is all four version pairings at once.
- [ ] **Both versions of both sides are live during any rolling deploy.** The measured
      blast radius on a 3,000-request window ranged from **323** to **1,546** failed
      requests for the wrong order.
- [ ] **If the order is wrong, the failures are concentrated in the rollout window** and
      then stop, which is exactly the signature that gets written off as "a blip".
- [ ] **Feature-flag the read side** if you cannot control the order
      (Phase 10 L12: deploy ≠ release).

---

## 3. The three gates — what to run, and what each one proves

Measured over six real cross-service defects:

| Gate | Caught | Its unique catch | Its blind spot |
|---|---|---|---|
| spec diff (`oasdiff`) | **4/6** | a removed field **no consumer reads** — a false alarm | meaning, and who needs what |
| consumer contract | **3/6** | the `404 → 200` error path the happy path never walks | values, ordering, units |
| end-to-end | **4/6** | the redenomination and the reordering — it asserts on **values** | needs 11 services green at once |

- [ ] **Contract verification runs on every provider commit.** It needs the contract file
      and the provider — nothing else deployed. Effective rate **3/6, every time**.
- [ ] **End-to-end is weighted by its environment's availability.** Measured at 11
      services: **42.4%** of days green, longest red streak **52 days**, so its effective
      rate is `4/6 × 0.424 = 1.69/6` per attempt. Keep the suite; keep it thin.
- [ ] **`oasdiff --fail-on ERR` against the PUBLISHED spec**, not the previous commit's
      file — otherwise a PR that changes code and spec together passes trivially.
- [ ] **Do not gate on schema diff alone.** Its only unique catch in the measured set was
      a change that broke nobody, and unactionable alarms are how a gate gets muted.

```bash
# spec diff, breaking changes only
oasdiff breaking https://api.internal/openapi.json openapi.json --fail-on ERR

# property-based conformance straight off the spec
schemathesis run openapi.json --url http://localhost:8080 \
  --checks all --hypothesis-max-examples=200 --stateful=links
```

---

## 4. Contracts — consumer side, then provider side

**Consumer:**

- [ ] **The contract is recorded by running your REAL client code**, not by hand-writing
      expectations. A hand-written double is a second implementation of someone else's
      contract: the measured hand-mock suite stayed **4/4 green** across four provider
      builds, including both broken ones.
- [ ] **Assert with type and pattern matchers, never literal values** — except where your
      code branches on the value (a `status` you switch on). Measured contract: **4 of the
      provider's 11 fields**, **6 matching rules**.
- [ ] **Verify that every declared interaction was exercised** (`3/3` in the run). An
      interaction your code no longer makes is a constraint on the provider that nobody
      needs.
- [ ] **Record the error paths.** The `404` interaction was the contract's unique catch
      over the end-to-end suite.
- [ ] **Publish on every consumer build**, tagged with the branch and the deployed version.

**Provider:**

- [ ] **Verification failure names a JSON path**, e.g. `$.total_cents: MISSING from the
      provider response`. If your verifier reports "response did not match", fix the
      verifier first — nobody debugs that message.
- [ ] **An unimplemented provider state is a FAILURE, not a skip.** A verifier that skips
      unknown states reports green for a contract it never checked.
- [ ] **Verify against consumer versions actually in production**, not every pact ever
      recorded.

```bash
pact-verifier \
  --provider-base-url=http://localhost:8080 \
  --provider-states-setup-url=http://localhost:8080/_pact/provider_states \
  --pact-broker-base-url=https://broker.internal --provider=orders \
  --consumer-version-selectors='{"mainBranch": true}' \
  --consumer-version-selectors='{"deployedOrReleased": true}' \
  --publish-verification-results --provider-app-version=$GIT_SHA
```

**Provider states — the part that stalls adoptions:**

- [ ] **One setup function per state**, run immediately before its own interaction. Not a
      seed file. Measured: without a state hook the same contract verified **1 of 3**, and
      the failures said `expected HTTP 200, got 404` — a message about an empty database,
      not about compatibility.
- [ ] **Expect contradictions.** Four consumers already produced **7 distinct states** and
      **2 contradictory pairs** on the same order id (`confirmed` vs `cancelled`). No
      shared fixture satisfies both.
- [ ] **Name states as conditions, not fixtures**: *"an order exists and is confirmed"*,
      never *"order 7hQ2df with the standard seed"*.

---

## 5. The changes no gate catches

- [ ] **Never redefine a field.** Same name, same type, new units round-tripped
      **400/400 in both directions**, verdict **FULL**, **0 errors in either deploy
      order** — and the consumer computed **1,857,277** where the provider meant
      **185,747,545**. A factor of 100, everything green.
- [ ] **Add a new field instead**, dual-write, migrate, remove. Always.
- [ ] **Put the unit in the name** — `_cents`, `_minor`, `_millis`, `_utc` — so a
      redefinition becomes an obvious falsehood in review.
- [ ] **Keep one value assertion per money field**, in a thin end-to-end check or a
      reconciliation against an independent source. In the measured run these were the
      only mechanisms that ever detected a redenomination.
- [ ] **Never `.get(field, default)` on a field your contract requires.** That single line
      is where an exception becomes a wrong number: after one rename, **98 of 200**
      receipts read exactly zero and nothing was logged.

---

## 6. The deployment gate

A verification result that does not block a deploy is a test, not a gate.

- [ ] **`can-i-deploy` runs in the deploy job**, after build, before rollout.
- [ ] **Unknown must fail closed.** `--retry-while-unknown` exists because verification is
      asynchronous; a gate that passes on "unknown" is decoration.
- [ ] **Record deployments** so the broker knows which consumer versions are live.
- [ ] **A blocked deploy names the consumer.** Measured matrix: the renaming build and the
      string-typed build were both `BLOCKED` by `receipts` alone, while `shipping` and
      `analytics` passed — so you know exactly whom to talk to.

```bash
pact-broker can-i-deploy --pacticipant orders --version $GIT_SHA \
  --to-environment production --retry-while-unknown 30 --retry-interval 10
pact-broker record-deployment --pacticipant orders --version $GIT_SHA \
  --environment production
```

For events, gate at registration instead:

```bash
curl -sf -X POST -H "Content-Type: application/vnd.schemaregistry.v1+json" \
  --data @candidate.json \
  https://registry.internal/compatibility/subjects/orders.placed-value/versions/latest \
  | jq -e '.is_compatible'
```

- [ ] **`FULL_TRANSITIVE` on any retained topic**, from day one. Plain `BACKWARD` checks
      only the previous version; a replay reads the oldest record, not the newest.

---

## 7. What to adopt, by size

**At 3 services** — do not deploy a broker.

- [ ] `oasdiff breaking` against the published spec in CI.
- [ ] One golden **value** assertion per money field in a small end-to-end suite.
- [ ] Error paths in that suite, not just the happy path.
- [ ] A Markdown table of which consumer reads which field. Discipline without infrastructure.

**At 10+ services, or as soon as two teams cannot deploy independently** —

- [ ] Pact plus a broker, `can-i-deploy` in the deploy job. At 11 services the trade is
      **19 contracts against 177,147 version combinations**.
- [ ] Adopt edge by edge, along the seams that actually break. Never as a mandate: a
      contract nobody wrote is worse than none, because the provider now believes it has
      coverage.
- [ ] Retire the shared environment as a *gate* (keep it as a place to click around).

---

## 8. Post-incident questions

1. Which gate should have caught this, and did it run? If it exists but was red for
   unrelated reasons, that is the finding — measured, the shared environment was usable on
   **42.4%** of days.
2. Did any consumer *silently* absorb the change? Search for `.get(` with a default on
   every field in the contract. That is where the wrong numbers are.
3. Was the failure an exception or a number? An exception is an incident with a stack
   trace; a number is a reconciliation finding three weeks later.
4. Was the change structural or semantic? If semantic, no gate would have caught it and
   the fix is process — never redefine a field.
5. Who read the field that broke, and could you have answered that *before* the deploy?

---

**Sources:** Postel, *Transmission Control Protocol*, RFC 761 §2.10, 1980 · Thomson &
Pauly, *Maintaining Robust Protocols*, RFC 9413, IETF, 2023 · the Pact Specification v3
(matching rules, provider states) · OpenAPI Specification 3.1.0.
