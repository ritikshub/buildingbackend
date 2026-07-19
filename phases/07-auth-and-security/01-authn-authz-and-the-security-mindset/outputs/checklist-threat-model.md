---
name: checklist-threat-model
description: A lightweight STRIDE threat-modeling worksheet to run before shipping a new endpoint or feature — the four Shostack questions, a per-input STRIDE pass, an authN/authZ split, and the security principles as a final gate. Four minutes at a whiteboard, not a compliance ceremony.
phase: 7
lesson: 01
---

# Threat-Model Worksheet (per feature or endpoint)

Run this before you ship anything that crosses a trust boundary — a new endpoint, a webhook
receiver, a background job that reads user input, a new third-party integration. It is meant to
take **a few minutes**, not a week. If a row makes you pause, that pause is the point.

## 1 — What are we building? (draw the data flow)

- [ ] Name the feature in one sentence and list its **entry points** (routes, queues, callbacks).
- [ ] For each entry point, write down **where the input comes from** and **who the caller is**
      (an end user? another service? an unauthenticated stranger? a third party's webhook?).
- [ ] Mark every **trust boundary** the data crosses: internet → app, app → database, service →
      service, third party → app. Threats live on these lines.
- [ ] List the **sensitive data** touched (credentials, PII, payment data, secrets) and where it
      rests. If any leaves in a response or a log, note that too.

## 2 — What can go wrong? (one STRIDE line per input)

For each input crossing a boundary, ask each question. Skip fast where it doesn't apply; stop and
write a control where it does.

- [ ] **S — Spoofing:** Can the caller lie about who they are? Is identity *proven*, or merely
      *asserted* (a trusted header, a client-supplied user id, an unsigned token)?  → authentication
- [ ] **T — Tampering:** Can the request, its parameters, or a stored value be altered undetectably?
      Is anything trusted after it crossed the boundary without verification?  → hashing / HMAC / signatures
- [ ] **R — Repudiation:** If this action is later disputed or found fraudulent, can you prove who
      did it? Is there an audit record the actor cannot quietly delete?  → tamper-evident audit log
- [ ] **I — Information disclosure:** Could this leak data the caller shouldn't see — in the
      response, an error message, a log line, a timing difference, or an enumerable id?  → encryption / access control / redaction
- [ ] **D — Denial of service:** Can a caller make this expensive, or call it enough to exhaust a
      resource (CPU, connections, a downstream quota, the login endpoint)?  → rate limits / quotas / timeouts
- [ ] **E — Elevation of privilege:** Can a low-privilege caller reach a high-privilege action or
      another user's resource (IDOR, a missing role check, mass-assignment of an `is_admin` field)?  → authorization on every access

## 3 — AuthN and AuthZ, stated explicitly

- [ ] **Authentication:** Exactly how is the caller's identity established here, and what happens if
      the credential is missing, expired, or forged? (A valid-but-unauthenticated caller gets **401**.)
- [ ] **Authorization:** For every object this endpoint touches, what check proves *this* identity
      may perform *this* action on *this* resource? Ownership and role are checked **server-side, per
      request**, not assumed from the fact that the caller is logged in. (A valid-but-forbidden caller
      gets **403**.)
- [ ] The check runs on **every** access, including the second and hundredth (complete mediation) —
      not once at load and then trusted.

## 4 — Did we do a good job? (principles as a final gate)

- [ ] **Never trust the client.** Every value the client controls — params, headers, cookies, hidden
      fields, ids, prices — is re-validated and re-authorized on the server.
- [ ] **Least privilege.** The identity, the token, and the database account each hold the minimum
      rights this feature needs — nothing wider "just in case."
- [ ] **Fail closed.** Every error, timeout, or ambiguous state in a security check results in
      **deny**, never a default allow.
- [ ] **Defense in depth.** There is more than one thing standing between an attacker and the data;
      no single missing check is a full breach.
- [ ] **No security through obscurity.** Nothing here relies on a path, parameter, or algorithm being
      secret. The only secrets are keys, and they live in a secret store (Lesson 13), not in code.
- [ ] **Nothing sensitive leaves.** Responses, error bodies, and logs carry identifiers, never
      payloads — no credentials, tokens, card data, or PII (Phase 9 logging hygiene).

## The four-minute version

> For each thing the client sends me across a boundary: **can they lie about who they are** (spoof),
> **change what I trust** (tamper), **reach what isn't theirs** (elevate), or **see/leak what they
> shouldn't** (disclosure)? Whatever I can't answer with a concrete server-side check is this
> feature's threat model — write the check, or write down the accepted risk with a name next to it.
