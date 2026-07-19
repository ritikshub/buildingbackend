---
name: checklist-event-schema-change
description: A pre-merge checklist for changing the schema of an event that is already in production, covering classification, compatibility mode, deploy order, defaults, upcasters, corpus testing and consumer notification
phase: 6
lesson: 12
---

# Checklist — Changing an Event Schema That Is Already in Production

Run this **before** the pull request is approved, not after the incident. Paste it into the PR
description and tick the boxes there, so a reviewer who does not know your domain can still tell
whether the change is safe.

The governing question, asked first:

> **Can every consumer that will ever read this topic — including the one replaying from the
> oldest offset still in retention — still make sense of the bytes?**

If your topic is a durable log rather than a short-lived queue, "ever" is not hyperbole.

## Step 0 — Establish the facts you are about to reason from

- [ ] **Subject and topic name**, and the schema's **owning team** (one team, named — not "platform").
- [ ] **Retention on this topic.** Hours, days, or infinite? Write the number down; every later
      answer depends on it.
- [ ] **Is this topic replayed?** For bug-fix reprocessing, for rebuilding a projection, for
      onboarding a new consumer from offset 0? If yes, your reader is permanently "new code reading
      old data" and you need **transitive backward** compatibility, not just backward.
- [ ] **The oldest schema version still represented in retention.** Not the oldest registered
      version — the oldest one whose records have not yet aged out. These are different numbers and
      the second is the one that binds you.

## Step 1 — Classify the change against the table

State in one sentence which row this is. If it is more than one row, it is more than one change,
and it should probably be more than one pull request.

| Change | Verdict | Note |
|---|---|---|
| Add optional field **with a default** | **SAFE** | The only genuinely free change. |
| Add required field (no default) | breaks backward | And breaks forward too, against any strict reader. |
| Remove optional field | safe-ish | Structurally fine; consumers that *used* it now silently get a default. |
| Remove required field | breaks forward | Old readers still demand it. |
| **Rename a field** | breaks both | A rename is a delete plus an add. There is no rename on the wire. |
| Widen a type (int32→int64) | backward only | Consumers must go first. |
| Narrow a type (int64→int32) | forward only | In practice: don't. Add a new field. |
| **Change units, meaning or timezone, same name** | **UNDETECTABLE** | No checker on earth catches this. See Step 4. |
| Add an enum value | breaks forward | Exhaustive matches throw; a blocked partition, not one bad record. |
| Change cardinality (single ↔ repeated) | breaks both | Different wire shapes, no promotion. |
| Reorder fields | **SAFE** | Identity is name and tag, never position. |
| **Reuse a retired field number** | **SILENT CORRUPTION** | Old bytes decode into the new field. Never. |

- [ ] Row identified, and written into the PR description.
- [ ] If the row is marked **UNDETECTABLE** or **SILENT CORRUPTION**: **stop and re-read Step 4.**
      No amount of testing substitutes for not making the change.

## Step 2 — Choose and verify the compatibility mode

- [ ] The subject's compatibility mode is **explicitly set**, not left on the registry default
      (which is usually plain `BACKWARD` and is usually not what you want).
- [ ] **If the log is retained and replayable, the mode is a `_TRANSITIVE` variant.** A
      non-transitive check compares your candidate against the previous version only, and
      compatibility does not compose: v3 can be compatible with v2 and incompatible with v1.
- [ ] Default recommendation: **`FULL_TRANSITIVE`** for events on a retained log. Weaker modes are
      a deliberate, documented decision with a named owner, not an omission.
- [ ] The compatibility check runs in **CI, before registration**, and a failure **fails the build**.
      A check that runs after deploy is a post-mortem, not a control.
- [ ] The check was run against the **full registered history**, and the output is in the PR.

## Step 3 — Confirm the deploy order the mode actually permits

- [ ] Which order does your mode allow?
      - Backward-compatible → **consumers first**, then producers.
      - Forward-compatible → **producers first**, then consumers.
      - Full → **either order**, which is the only answer that survives contact with five teams
        on five release trains.
- [ ] If the change only permits one order, **name the teams** who must deploy first and confirm
      they have agreed to a date. If you cannot get that agreement, you need a fully compatible
      change instead — not an optimistic rollout.
- [ ] Confirm there is no consumer you have forgotten. See Step 7.

## Step 4 — Defaults, and the rule that has no tool behind it

- [ ] **Every added field has a default.** No exceptions. "Required" on the wire means "unreadable
      in every historical record".
- [ ] Each default is a **historically correct** value for records that predate the field. Writing
      `currency: "EUR"` is a claim that everything before the multi-currency launch really was in
      euros. Verify it; do not assume it.
- [ ] **Zero-value trap:** if `0`, `""` or `false` is a *legitimate* value for this field, a plain
      default makes "absent" and "legitimately zero" indistinguishable. Use explicit presence
      (proto3 `optional`, a nullable union, a separate `has_x` flag).
- [ ] **NEVER redefine the meaning, units, timezone or currency of an existing field.** Not the
      value range, not the rounding, not the reference frame. No schema checker detects it, every
      automated control stays green, and every downstream number becomes quietly wrong.
      **Add a new field** — `total_eur` alongside `total_cents` — and deprecate the old one on a
      timeline.

## Step 5 — Upcasters, if the log holds older versions

- [ ] Does the log still contain records written under an earlier schema? If yes:
- [ ] An **upcaster** exists for every hop from the oldest retained version to the newest
      (`v1→v2`, `v2→v3`, `v3→v4`), each a **pure function doing exactly one migration**.
- [ ] Each upcaster has its own unit test with a real record as input.
- [ ] Consumer business logic branches on **no** version at all. If you see `if version == 1` in a
      handler, the upcaster chain is incomplete.
- [ ] **The upcasters are documented as permanent.** On a retained log, expand-contract never
      completes for historical data, so these functions are production code for as long as the
      oldest record survives — forever, for an event-sourced topic. Add a comment saying so, or
      someone will delete them as dead code.

## Step 6 — Test against reality, not just the schema

- [ ] A **corpus of real historical messages** is checked into the repo, sampled across the
      retention window and **including the oldest record still retained**.
- [ ] The candidate schema and the changed consumer both run against the whole corpus in CI.
- [ ] The corpus is **refreshed on a schedule** so it tracks the retention window rather than
      slowly becoming fiction.
- [ ] **Consumer contracts:** each consumer publishes what it depends on (fields, types, enum
      symbols it handles), and the producer's CI runs every published contract against the
      candidate. The producer's build should fail before the deploy, not the consumer's pager after.
- [ ] **Replay test:** rewind a test consumer group to offset 0 on a copy of the topic and confirm
      it processes 100% of records. This is the only test that proves failure three cannot happen.
- [ ] **Tolerant-reader audit:** your consumers ignore unknown fields (`additionalProperties` is
      **not** `false`), never fail on extra data, validate only the fields they use, and have a
      **default arm on every enum match**.

## Step 7 — Identify and notify the consumers

- [ ] **Enumerate the consumers** from the broker's consumer groups on this topic, not from memory
      and not from a survey. Consumer groups plus lag metrics *are* the subscriber list.
- [ ] Cross-check against the registry (who else references this subject) and any published
      consumer contracts.
- [ ] For a removal or a deprecation: **verify nobody reads the field** before removing it.
      Contracts and usage telemetry, not a Slack message with no replies.
- [ ] **Deprecation has a real date**, recorded in the schema's doc comment and communicated to
      every owning team: mark deprecated → announce → verify zero readers → stop writing →
      remove from the schema.

## Step 8 — Field numbers and names, permanently

- [ ] **Never reuse a retired field number.** The wire carries the tag, not the name; reusing it
      means every historical record's old field decodes into your new one with no error at all.
- [ ] Retired tags are declared `reserved` **in the same commit that removes the field**. Reserving
      is what makes even a cheap non-transitive check sufficient for this class of bug.
- [ ] **Never re-use a retired field *name* with a different type**, for the same reason one step up
      the stack. Pick a new name: `promo_code_id`, not `promo_code`.
- [ ] The next free tag number is taken from the top, never from the gaps.

## Ship / do-not-ship

**Ship** when: the row is classified, the mode is transitive and enforced in CI, every added field
has a historically correct default, no existing field changed meaning, the upcaster chain covers
the oldest retained version and is marked permanent, the corpus and replay tests pass, and the
consumer list came from the broker rather than from memory.

**Do not ship** when: the change redefines an existing field's units or meaning; it reuses a retired
tag or name; it only passes a non-transitive check on a retained log; it requires a specific deploy
order that no one has agreed to; or any added field has no default. Each of those has a safe
alternative in Step 1's table — take it.
