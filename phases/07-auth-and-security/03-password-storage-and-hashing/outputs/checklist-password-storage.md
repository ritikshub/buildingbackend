---
name: checklist-password-storage
description: The standing checklist for storing and verifying passwords — algorithm choice and tuning, salting and peppering, the self-describing hash string, constant-time verification, transparent upgrades, and the login-endpoint defenses storage alone can't provide. Run before an auth service ships and in any review that touches password handling.
phase: 7
lesson: 03
---

# Password Storage Checklist

Assume the database *will* leak. Everything here is measured against one question: when the attacker
opens your `users` table, how expensive is it to recover the passwords?

## 1 — Algorithm

- [ ] Passwords are **hashed, never encrypted** (no recoverable key anywhere) and **never plaintext**.
- [ ] The hash is a **slow, memory-hard** password hash — **Argon2id** (first choice), or scrypt;
      **bcrypt** acceptable where already deployed; **PBKDF2** only if a compliance regime demands it.
- [ ] **Never** a general-purpose hash (MD5, SHA-1, SHA-256, SHA-3) — not even with "rounds."
- [ ] For bcrypt specifically: inputs are handled for the **72-byte truncation** (pre-hash long
      passwords with SHA-256 + Base64), and there are no null-byte truncation surprises.

## 2 — Parameters (tune to your hardware)

- [ ] Work factor tuned so **one hash takes ~100–250 ms** on the login server (Argon2: `memory_cost`
      ≥ 64 MiB, `time_cost` ≥ 3; bcrypt cost ≥ 12; PBKDF2-SHA256 ≥ 600,000 iterations).
- [ ] Parameters are **reviewed on a schedule** (yearly) and raised as hardware improves.

## 3 — Salt and pepper

- [ ] A **unique, random salt per password** from a CSPRNG (≥ 16 bytes). The library generates and
      embeds it — you are not reusing one global salt.
- [ ] Salt is stored **with** the hash (it is not secret; it needs to be unique).
- [ ] Optional **pepper**: one secret, same for all users, applied as `HMAC(pepper, password)` before
      the slow hash, and stored **outside the database** (secrets manager/HSM, Lesson 13). It is
      defense in depth, not a replacement for salt or work factor.

## 4 — The stored value and verification

- [ ] Stored as a **self-describing string** (algorithm + parameters + salt + hash), e.g. the PHC
      format — so verification and upgrade need no out-of-band config.
- [ ] Verification re-derives salt/params **from the stored string**, never from current config.
- [ ] Comparison is **constant-time** (the library's verify, or `hmac.compare_digest`), never `==`.
- [ ] A verification error or unparseable hash **fails closed** (login denied), and never leaks
      *why* it failed to the client.

## 5 — Transparent upgrades

- [ ] On each **successful** login, check whether the stored hash used weaker-than-current parameters
      (`check_needs_rehash`); if so, re-hash the just-verified plaintext and store the stronger value.
- [ ] Raising the work factor is a **config change**, not a migration or a forced reset.

## 6 — What storage can't do (the login endpoint)

- [ ] **Rate limiting + lockout/backoff** on login and on password-reset (Lesson 12) — storage does
      nothing against online guessing / credential stuffing.
- [ ] **Breach screening** at registration and change: reject known-leaked passwords via HIBP's
      **k-anonymity** range API (send a 5-char SHA-1 prefix, match suffixes locally — the password
      never leaves your server).
- [ ] **MFA** available and encouraged (Lesson 4), so a cracked or phished password isn't sufficient.
- [ ] Login responses are **uniform** for "no such user" vs "wrong password" (same message, similar
      timing) to avoid username enumeration.

## 7 — Handling and hygiene

- [ ] Passwords are **never logged** — not in access logs, request bodies, analytics, error reports,
      or "temporary" debug columns (this is the most common plaintext leak).
- [ ] Password **policy follows NIST 800-63B**: allow long passphrases, screen against breach lists,
      **no forced periodic rotation**, no arbitrary composition rules, allow paste (password managers),
      minimum length ~8+ (longer for privileged accounts).
- [ ] The password is discarded from memory as soon as it's hashed/verified; not cached, not
      forwarded to another service.
