---
name: checklist-jwt-security
description: The verification-first checklist for issuing and validating JWTs — pin the algorithm, enforce exp/aud/iss, choose HS256 vs RS256 correctly, handle revocation with access+refresh tokens, and avoid the alg:none and key-confusion forgeries. Run in any review that mints or verifies tokens.
phase: 7
lesson: 06
---

# JWT Security Checklist

A JWT is only as safe as its verification. Most of this list is about *verifying*, because that's
where every real JWT breach happened.

## 1 — Verification (the security lives here)

- [ ] **Pin the algorithm.** Pass the accepted algorithm(s) explicitly (`algorithms=["RS256"]`) and
      reject any token whose `alg` isn't in the list — *before* choosing a key. Never read `alg` from
      the token to decide how to verify.
- [ ] **`alg:none` is never accepted.** No unsecured-JWT path in production.
- [ ] **No HS/RS confusion.** A verifier that expects RS256 must not fall back to HMAC with the
      public key. Pinning the algorithm prevents this.
- [ ] Signature compared in **constant time** (the library does this — don't hand-roll).
- [ ] **`exp` is required and checked** (reject the token if missing or past). Consider `nbf`/`iat`.
- [ ] **`aud` and `iss` verified** for any cross-service/third-party token, so a token minted for one
      audience can't be replayed at another.
- [ ] Verification failure **fails closed** (401), and never leaks *why* in a way that helps an attacker.

## 2 — Issuing

- [ ] **Choose the algorithm by trust boundary:** HS256 only inside one app/trust domain; RS256/ES256
      across services or to third parties (verifiers hold only the public key).
- [ ] Sign with a strong key from a **secret store** (Lesson 13); rotate it. For RS256, publish public
      keys at a **JWKS** endpoint and support a `kid` so rotation doesn't break verifiers.
- [ ] **No secrets in the payload** — it's Base64url, readable by anyone. No passwords, cards, or PII
      you wouldn't show the user. (Use JWE only if claims genuinely must be encrypted.)
- [ ] Set a **short `exp`** on access tokens, plus `iss`, `aud`, `sub`, and `iat`.

## 3 — Lifetime & revocation

- [ ] **Access token: short-lived** (minutes), stateless, verified locally, sent on every request.
- [ ] **Refresh token: long-lived, opaque, stored server-side, revocable**, used only to mint new
      access tokens; **rotate it on each use** and treat reuse of an old one as theft (revoke the family).
- [ ] For immediate access-token revocation (logout, password change, compromise), maintain a **`jti`
      denylist** checked on sensitive operations — accepting that this reintroduces some state.
- [ ] Revoke on password change, role change, and logout; don't let a stale token outlive its authority.

## 4 — Client handling

- [ ] In browsers, prefer an **`HttpOnly` cookie** over `localStorage` (which any XSS can read — Lesson 10).
- [ ] Keep cookie-carried tokens under the Lesson 5 rules: `HttpOnly`, `Secure`, `SameSite`.
- [ ] Never log full tokens (they're bearer credentials) — redact like passwords.

## 5 — Use the library

- [ ] A maintained library (PyJWT, `jsonwebtoken`, `golang-jwt`) with **`algorithms=[...]` mandatory**.
- [ ] Enforce claims via library options (`require: ["exp"]`, `audience=`, `issuer=`), not by hand.
- [ ] Keep the library patched — several JWT CVEs were library bugs in exactly these checks.

## The one rule to remember

> **Never trust the token's `alg`.** The server decides the algorithm and the key out of band; the
> token's header is only checked *against* that decision. That single rule kills both `alg:none` and
> HS/RS key confusion.
