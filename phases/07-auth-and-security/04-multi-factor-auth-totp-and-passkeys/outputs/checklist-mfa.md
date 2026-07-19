---
name: checklist-mfa
description: Implementation checklist for adding a second factor to an auth system — choosing factor types by threat, TOTP enrollment and verification rules, passkey/WebAuthn essentials, recovery paths that don't become the weak link, and the endpoint defenses MFA still needs. Run when designing or reviewing any MFA feature.
phase: 7
lesson: 04
---

# MFA Implementation Checklist

MFA is only as strong as the weakest factor you accept and the recovery path behind it. Design both,
not just the happy path.

## 1 — Choose factors by threat, not by convenience

- [ ] Offer **passkeys / WebAuthn** where possible — the only factor that resists phishing (origin
      binding) and stores no secret server-side. Aim to make it the primary credential over time.
- [ ] Offer **TOTP** (authenticator app) as the accessible, universal option. Good: kills SIM-swap
      and reuse. Limit: the typed code is still phishable by a real-time proxy.
- [ ] Avoid **SMS** for anything valuable (phishable *and* SIM-swappable; telco in the path). If you
      must offer it, treat it as the weakest tier and not for high-value actions.
- [ ] "Two factors" means two **different categories** (know / have / are). A password plus a
      security question is not MFA.

## 2 — TOTP: enrollment

- [ ] Secret is generated server-side from a **CSPRNG** (≥ 20 bytes / 160 bits), Base32-encoded.
- [ ] Delivered via an `otpauth://totp/...` URI rendered as a **QR code**; offer manual entry too.
- [ ] The stored secret is **encrypted at rest** (it is a shared secret — a plaintext leak lets the
      attacker mint codes). See Lesson 13.
- [ ] Enrollment is **confirmed**: the user must submit one valid code before MFA is marked active,
      so a mis-scanned secret doesn't lock them out.

## 3 — TOTP: verification

- [ ] Verify with a **small skew window** (±1 step / ±30s), not a large one.
- [ ] Compare in **constant time** (`hmac.compare_digest`), never `==`.
- [ ] **Reject reused codes**: track the counter(s) redeemed in the current window and refuse a
      repeat, so a sniffed code can't be replayed seconds later.
- [ ] **Rate-limit** the verify endpoint (Lesson 12) — 6 digits is only a million values.
- [ ] Codes are **6+ digits**, 30s period, SHA-1 (per RFC 6238 / authenticator-app compatibility).

## 4 — Passkeys / WebAuthn

- [ ] Use a maintained library (e.g. `py_webauthn`) — do **not** hand-roll attestation/COSE parsing.
- [ ] Registration stores the **public key + credential ID** per user (public keys need no secrecy).
- [ ] Authentication verifies: the **signature** against the stored public key, the **origin/rpId**
      matches your domain, the **challenge** is the one you issued (random, single-use), and the
      **signature counter** did not go backwards (clone detection).
- [ ] Challenges are random (CSPRNG), single-use, and short-lived.
- [ ] Allow **multiple** passkeys per user (phone + laptop + hardware key) so losing one device isn't
      lockout.

## 5 — Recovery (guard it like the front door)

- [ ] Provide **one-time recovery codes** at enrollment: ~10 random codes, shown once.
- [ ] Store them **hashed**, mark each **single-use** (delete on redemption), allow **regeneration**.
- [ ] The account-recovery flow is **not weaker** than the factor it backs up — no resetting MFA on a
      knowledge question ("pet's name"). Recovery is a common MFA bypass; treat it with equal rigor.
- [ ] Notify the user (email/push) on MFA changes, recovery-code use, and new-device enrollment.

## 6 — What MFA still doesn't cover

- [ ] Session/token theft **after** login (Lesson 5) — protect the session cookie/token too.
- [ ] Endpoint compromise / malware — MFA authenticates the login, not the device.
- [ ] Real-time phishing proxies against TOTP/SMS — only passkeys close this; prioritize them for
      admins and high-value accounts.
- [ ] Step-up: require re-authentication (ideally a passkey) for **sensitive actions** (changing
      email, disabling MFA, moving money), not just at login.
