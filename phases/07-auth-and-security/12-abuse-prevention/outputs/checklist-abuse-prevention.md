---
name: checklist-abuse-prevention
description: Checklist for defending login, signup, and public endpoints against automated abuse — credential stuffing, brute force, fake accounts, scraping, and account takeover. Covers rate limiting, MFA and breach screening, throttle-not-lockout, anti-enumeration, and adaptive friction. Run for any authentication or high-value endpoint.
phase: 7
lesson: 12
---

# Abuse Prevention Checklist

Abuse is your features used correctly at hostile scale — there's no bug to fix, so the goal is to make
abuse expensive and detectable while keeping the human path frictionless.

## 1 — Account takeover (highest leverage first)

- [ ] **MFA** available and encouraged (required for high-value/admin accounts) — the single most
      effective ATO defense; a correct password alone can't log in (Lesson 4).
- [ ] **Breach-password screening** at signup and password change (HIBP k-anonymity, Lesson 3) — the
      reused password credential stuffing relies on is never allowed.
- [ ] **Device recognition / step-up**: a login from a new device or location triggers extra
      verification (email confirm, MFA, re-auth).
- [ ] **Notify** users of new-device logins, password/MFA changes, and suspicious activity.

## 2 — Rate limiting (the floor — Phase 2 · L9 algorithms)

- [ ] Applied at **multiple keys**: per-account, per-IP, and per-endpoint (login, reset, signup are
      more sensitive than reads).
- [ ] Know its limit: distributed stuffing spreads across **many IPs** and slips under per-IP limits —
      so pair it with account-level limits and bot/behavioral detection.
- [ ] Rate-limit **password reset** and **MFA-verify** endpoints too (6-digit codes are brute-forceable).

## 3 — Throttling, not lockout

- [ ] Use **progressive backoff** (increasing delay) + a challenge after repeated failures — **never a
      hard lockout** that an attacker can trigger to DoS a victim.
- [ ] Backoff/challenge keyed to the right dimensions (account + IP), so one abusive source doesn't lock
      a shared identity.

## 4 — Anti-enumeration (don't hand out target lists)

- [ ] **Uniform login responses**: identical message and status for unknown-user vs wrong-password.
- [ ] **Constant timing**: run the password hash even when the user doesn't exist, so response time
      doesn't reveal account existence.
- [ ] Same discipline on **signup** ("if this email is new, we'll create it" / don't reveal
      "already registered") and **password reset** (always "if an account exists, we sent an email").

## 5 — Bot detection & adaptive friction

- [ ] **Behavioral/reputation signals**: IP & ASN reputation, known-proxy/VPN lists, headless-browser
      and automation fingerprints, request velocity, missing JS/cookies.
- [ ] **Challenge only on suspicion** (adaptive): CAPTCHA (reCAPTCHA v3 / hCaptcha / Turnstile) or
      proof-of-work for risky requests — **never a universal CAPTCHA** (a tax on real users).
- [ ] A **WAF / bot-management** layer at the edge (Cloudflare, Akamai, AWS WAF) for the broad filter.
- [ ] Protect **scraping-prone** endpoints (pricing, search, profile) with rate limits, auth, and
      pagination limits.

## 6 — Detection & response

- [ ] **Monitor** login-failure rates, per-ASN spikes, signup velocity, and MFA-challenge rates
      (Phase 9) — abuse you can't see, you can't respond to.
- [ ] Alert on stuffing signatures (one IP → many accounts; many IPs → one account; sudden success-rate
      change) and have a **response playbook** (raise friction, force resets, block ranges).
- [ ] Track **fake-account / fraud** signals (disposable emails, referral abuse, velocity) for signup.

## The economics rule

> You can't make abuse impossible — make it a **worse deal than the next site**. Raise the attacker's
> cost per attempt (rate limit, proof-of-work), make a correct password worthless without a second
> factor (MFA), and put the friction on the bot, not the human (adaptive challenges).
