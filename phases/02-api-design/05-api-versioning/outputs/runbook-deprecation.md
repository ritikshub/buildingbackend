---
name: runbook-deprecation
description: A step-by-step runbook for retiring an API field, endpoint, or version without breaking consumers you can't see — announce, signal, measure, nudge, remove
phase: 02
lesson: 05
---

# API Deprecation Runbook

Use this whenever you need to remove or change something breaking: a field, an
endpoint, an enum value, or a whole version. A version is a promise to code you can't
update — this runbook is how you take the promise back safely.

## 0. First, can you avoid it?

- [ ] Can this be **additive** instead? New field alongside the old, new endpoint,
      new optional param. If yes, do that and stop — no deprecation needed.
- [ ] If you're changing meaning/units, **add a new field** (`discount_amount`) and
      deprecate the old one. **Never repurpose a field in place** — clients can't
      detect a silent semantic change.

## 1. Announce

- [ ] Write the change in the **changelog** with a migration guide (old → new, with
      examples) and a concrete **sunset date**.
- [ ] Notify known consumers directly (email, dashboard banner, account managers).

## 2. Signal on the wire

- [ ] Add the **`Deprecation`** header (RFC 9745) to affected responses.
- [ ] Add the **`Sunset`** header (RFC 8594) with the removal date.
- [ ] Optionally link docs via a `Link: <...>; rel="deprecation"` header.
- [ ] Keep serving the old behavior unchanged — signaling is not removing.

## 3. Measure

- [ ] Instrument usage of the deprecated surface **per consumer / API key**.
- [ ] Build a dashboard: calls/day to the old field or endpoint, and who is calling.
- [ ] Define "done": usage at or near zero (define the threshold, e.g. < 0.1%).

## 4. Nudge

- [ ] Contact the remaining callers directly with their numbers and the deadline.
- [ ] Consider **brownouts** (brief, scheduled 410 responses) to surface hidden
      dependencies before the real removal — announce them first.

## 5. Remove

- [ ] Only at a **major-version boundary**, only **after the sunset date**, only when
      usage is ~zero.
- [ ] Removed endpoints return **`410 Gone`** (not `404`) so callers get a clear signal.
- [ ] Update docs, changelog, and the OpenAPI spec; snapshot-diff catches stragglers.

## Guardrails

- [ ] Additive-only within a version; the "breaking" list waits for the next major.
- [ ] Clients read **tolerantly** (ignore unknown fields) so your additions are safe.
- [ ] Removal without measured ~zero usage is **an outage you chose to inflict**.
