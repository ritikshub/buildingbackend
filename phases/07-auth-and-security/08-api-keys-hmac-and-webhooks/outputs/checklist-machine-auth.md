---
name: checklist-machine-auth
description: Checklist for machine-to-machine authentication — issuing and storing API keys, signing requests with HMAC (and stopping replay), and verifying inbound webhooks. Run when building a public API, a partner integration, or a webhook receiver.
phase: 7
lesson: 08
---

# Machine Authentication Checklist

No user, no browser — just a credential a program holds. Get authenticity, integrity, and freshness
right.

## 1 — API keys (issuing & storing)

- [ ] Generated from a **CSPRNG**, **≥128 bits**, with a meaningful **prefix** (`sk_live_`, `sk_test_`)
      for on-sight identification and environment separation.
- [ ] **Shown to the user exactly once**; never retrievable again (lost → rotate, not recover).
- [ ] Stored as a **hash** (a *fast* SHA-256 is correct — the key is already high-entropy, unlike a
      password) plus the prefix + metadata (owner, scope, created, last_used). Never plaintext, never
      reversibly encrypted.
- [ ] **Verified in constant time** (`hmac.compare_digest` on the hashes).
- [ ] **Scoped** to least privilege (a read key can't write; per-key permissions).
- [ ] **Rotatable with zero downtime**: support multiple active keys per account so one can be rolled
      while the other still works; expire/revoke individually.

## 2 — API keys (transmitting & operating)

- [ ] Sent in a **header** (`Authorization: Bearer ...`), **never** in a URL/query string (URLs are
      logged everywhere).
- [ ] **Never logged** (redact like any credential); short-circuit before logging the request.
- [ ] **Leak detection**: rely on provider/GitHub **secret scanning** and auto-revoke keys pushed to
      repos (Lesson 13); alert on anomalous usage.

## 3 — HMAC request signing (when you need integrity + freshness)

- [ ] The **secret never travels** — the client sends a per-request **signature**, not the key.
- [ ] Sign a **canonical string** covering everything that matters: method, path (and query),
      timestamp, a hash of the body. *Whatever you don't sign, an attacker can change.*
- [ ] Verify by **rebuilding** the canonical string server-side, recomputing the HMAC, and comparing
      **constant-time**.
- [ ] **Replay protection is not optional**: reject requests whose **timestamp** is outside a short
      window (e.g. 5 min), and reject a **nonce** (or signature) seen before.
- [ ] For signing your own outbound requests, follow a **proven design (AWS SigV4)** rather than
      inventing canonicalization.

## 4 — Webhooks (verifying inbound requests)

- [ ] **Verify every webhook** — the endpoint is public, so the signature is the only proof it's real.
- [ ] Compute the HMAC over the **raw request body bytes** as received (before parsing/re-serializing).
- [ ] Compare **constant-time** against the provider's signature header, using the **webhook secret**
      (from a secret store, Lesson 13).
- [ ] Check the signature **timestamp** to reject replays of old events.
- [ ] Use the provider's **SDK** where available (`stripe.Webhook.construct_event`, GitHub
      `X-Hub-Signature-256`), which wraps exactly these checks.
- [ ] Treat the webhook as a **notification**: for high-value actions, **re-fetch** the authoritative
      object from the provider's API rather than trusting amounts/state in the payload.
- [ ] Make handlers **idempotent** (dedupe by event ID) — providers retry and may deliver duplicates.

## 5 — Stronger options for service-to-service

- [ ] Consider **mTLS** (Phase 1, Lesson 10) inside your own infrastructure — identity at the TLS
      layer, no bearer secret to leak.
- [ ] Automate service identity with a **service mesh** (Istio/Linkerd) or **SPIFFE/SPIRE**
      (short-lived, auto-rotated certs).
- [ ] For token-based M2M, use OAuth **Client Credentials** (Lesson 7) against your auth server.

## The one-line test

> Ask three questions of any machine request: **is it really from who it claims** (authenticity),
> **is it unaltered** (integrity — did I sign/verify the body?), and **is it fresh** (not a replay —
> timestamp + nonce)? A bare API key answers only the first, weakly.
