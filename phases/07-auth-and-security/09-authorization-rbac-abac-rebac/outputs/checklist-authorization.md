---
name: checklist-authorization
description: Checklist for designing and enforcing authorization — pick a model (RBAC/ABAC/ReBAC), separate enforcement from decision, and get the enforcement discipline right (deny by default, object-level checks, server-side, every access) so the IDOR can't exist. Run when adding any access-controlled resource.
phase: 7
lesson: 09
---

# Authorization Checklist

Authorization bugs are the #1 web/API vulnerability, and almost all of them are *enforcement*
mistakes, not model mistakes. Get section 3 right above all.

## 1 — Model (pick, and combine)

- [ ] **RBAC** for coarse gates ("admins reach the admin panel"): users → roles → permissions.
- [ ] **ABAC** when the decision depends on **attributes/context** (department, sensitivity, time, IP,
      MFA present): the decision is a boolean over subject/resource/action/context.
- [ ] **ReBAC** (Zanzibar) when access is about **relationships** (owner, shared-with, group member,
      folder hierarchy): relationship tuples + a path check (OpenFGA / SpiceDB / Ory Keto).
- [ ] Watch for **role explosion** (`editor_contractor_eu_non_confidential`) — the signal to move
      conditions out of role names into ABAC/ReBAC.

## 2 — Architecture (separate the concerns)

- [ ] **PEP ≠ PDP**: the enforcement point (in each service) is separate from the decision logic, so
      the decision is centralized, auditable, and changeable without editing every handler.
- [ ] Consider **externalizing** the decision into a policy engine — **OPA/Rego**, **Cedar**
      (Amazon Verified Permissions), or a Zanzibar engine (**OpenFGA/SpiceDB**) — for one source of truth.
- [ ] The decision takes `(subject, action, resource, context)` and returns allow/deny — a clean,
      testable interface.

## 3 — Enforcement discipline (where breaches happen)

- [ ] **Deny by default.** No matching allow rule ⇒ denied. Never "allow unless explicitly denied."
- [ ] **Authorize the OBJECT, not just the route.** Passing "may call this endpoint" is necessary but
      NOT sufficient — check "may act on THIS record" (owner/shared/relationship). Skipping this is the
      IDOR / Broken Object-Level Authorization.
- [ ] **Check on EVERY access** (complete mediation) — every read and write, not once at load then
      trusted; re-check after any state that could change permissions.
- [ ] **Decide from server-side state**, never from a client-supplied role/owner — and not even from a
      stale token claim (a demoted user still holds a signed `role: admin` until it expires). Use the
      token to identify the subject; compute the decision from current data.
- [ ] Enforce at a consistent layer (a middleware/decorator or the data-access layer), so a new
      endpoint can't silently skip the check.
- [ ] Filter **list** endpoints too (return only objects the user may see) — collection endpoints are a
      common IDOR blind spot.

## 4 — Operability

- [ ] **Least privilege** by default: grant the minimum; review and prune roles/grants periodically.
- [ ] **Log authorization decisions** (subject, action, resource, allow/deny) so you can answer "who
      accessed X and were they allowed?" — a security and compliance requirement.
- [ ] **Test authorization** explicitly: negative tests (a non-owner is denied), object-level tests,
      deny-by-default tests. Authorization bugs pass functional tests silently.
- [ ] Separate **authorization** (what may they do) from **business validation** (is the input valid);
      don't let a 200 leak that an object exists to someone not allowed to know.

## The one rule that prevents most breaches

> **Deny by default, and authorize the specific object on every access, from server-side state.**
> "The user is an editor" is not "the user may edit *this* document."
