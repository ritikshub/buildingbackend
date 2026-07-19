---
name: checklist-session-security
description: The standing checklist for session and cookie security — ID entropy, the four cookie attributes that each stop an attack, rotation and timeouts, real logout/revocation, and the store choice. Run when building or reviewing any session-based auth.
phase: 7
lesson: 05
---

# Session & Cookie Security Checklist

The session cookie is a bearer credential: whoever holds it is the user. Almost every item here is a
default you must set correctly, not clever code.

## 1 — The session ID

- [ ] Generated from a **CSPRNG** (`secrets.token_urlsafe`), **≥128 bits** of entropy.
- [ ] **Opaque** — encodes nothing (no user ID, role, email, or timestamp the client can read/forge).
- [ ] Never placed in a URL (leaks via history, referer, logs, shared links) — cookie only.

## 2 — Cookie attributes (each stops a specific attack)

- [ ] **`HttpOnly`** — JavaScript can't read it → XSS can't steal the session.
- [ ] **`Secure`** — sent only over HTTPS → no sniffing off the wire.
- [ ] **`SameSite`** — `Lax` (default) or `Strict` → mitigates CSRF; `None` only with `Secure` and a
      real cross-site need.
- [ ] **`__Host-` prefix** on the cookie name → forces Secure + Path=/ + no Domain, locking it to the
      exact origin (a compromised subdomain can't overwrite it).
- [ ] **Scope** minimally: narrow `Path`/`Domain`; set a deliberate `Max-Age`/`Expires` (session vs
      persistent) rather than accepting a default.

## 3 — Lifecycle

- [ ] **Rotate the ID on login** and on every privilege change / step-up re-auth → defeats session
      fixation. (Django: `cycle_key()`; most frameworks: `regenerate`.)
- [ ] **Idle timeout** (inactivity) AND **absolute timeout** (max lifetime) — both, not one.
- [ ] **Logout deletes the session server-side**, not just the client cookie — a copied cookie must
      stop working after logout.
- [ ] Support **revoke-all** (on password change, "log out everywhere," suspicious activity) and
      consider a **concurrent-session cap**.
- [ ] Bind or re-check on meaningful change where feasible (e.g. re-auth for sensitive actions); be
      cautious binding to IP/User-Agent (breaks mobile/roaming users).

## 4 — Store & transport

- [ ] Session data lives **server-side** (Redis/DB) with a **TTL = timeout**; only the opaque ID is
      in the cookie. Multi-process deployments need a **shared** store, not per-process memory.
- [ ] The whole site is **HTTPS** (HSTS on), so `Secure` cookies are never dropped.

## 5 — Signed / stateless cookies (if you use them instead)

- [ ] The payload is **signed** (HMAC/`itsdangerous`), so it's tamper-evident — and you remember
      **signed ≠ encrypted**: never put secrets in it, the client can read it.
- [ ] You've accepted the tradeoff: **no instant revocation** without extra state (a denylist), and a
      short expiry to bound the damage of a stolen token.
- [ ] The signing key is strong, from a secret store (Lesson 13), and **rotatable** (support two keys
      during rotation).

## 6 — Handling

- [ ] Session IDs are **never logged** (they're credentials) — redact them like passwords/tokens.
- [ ] Errors around session lookup **fail closed** (treat as unauthenticated), never fall through to
      an authenticated state.
- [ ] The cookie's cross-site behavior is finished with **CSRF defenses** (Lesson 10) — SameSite is a
      strong mitigation, not the whole story for older browsers and `SameSite=None` flows.
