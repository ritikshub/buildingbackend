---
name: checklist-idempotency
description: A checklist for making an unsafe POST retry-safe with idempotency keys — claim before executing, fingerprint the request, replay stored responses, and expire the keys
phase: 02
lesson: 07
---

# Idempotency Checklist

Use this on any non-idempotent write a client might retry (payments, order creation,
transfers). The goal: a retried request executes the operation **at most once**.

## The server contract

- [ ] Accept a client-supplied **`Idempotency-Key`** header (a UUID is the norm).
- [ ] Store keys scoped per **tenant/account**, keyed `(tenant, key)`.
- [ ] **Claim then execute** — insert the key row *before* doing the work, atomically
      (unique constraint / `INSERT ... ON CONFLICT`). Never check-then-insert: that's a
      race.
- [ ] **Fingerprint** the request (hash of method + path + body). Same key + different
      body → **`422`** (a client bug, not a retry).
- [ ] Duplicate while the original is still running → **`409`** + `Retry-After`, not a
      second execution.
- [ ] On completion, **store the response** (status + body) and **replay it verbatim**
      for later duplicates.
- [ ] **Expire** keys after a bounded window (Stripe: 24h) so the table doesn't grow
      forever.

## Failure policy (decide explicitly)

- [ ] A `5xx` failure generally **clears the claim** so the retry can re-execute — don't
      replay a transient failure forever.
- [ ] A deterministic `4xx` can be safely replayed.
- [ ] Persisting the outcome and doing the work should be **one transaction** where
      possible, so a crash between them doesn't strand a claimed-but-unexecuted key.

## The client's half

- [ ] Generate the key **once per logical operation** (when the user taps "Pay"),
      persist it, and reuse the *same* key on every retry. A fresh key per retry defeats
      the mechanism entirely.
- [ ] Retry only on timeouts / `5xx` / `429`, with backoff + jitter (lesson 09).
- [ ] Don't retry deterministic `4xx` — fix the request instead.
