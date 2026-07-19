# Abuse Prevention: Bots, Credential Stuffing & Account Takeover

> Every lesson before this stopped attackers from doing things they *shouldn't*. This one defends against attackers using your system exactly as *designed* — but automated, at machine scale, in bulk. Nobody exploits a bug to run **credential stuffing**; they just call your login a hundred million times with passwords leaked from other sites, and a small percentage work. The defense isn't a patch, it's an economic argument: make abuse **expensive and detectable** for the attacker while keeping it **frictionless** for the human. You'll build a login defender that throttles, screens breached passwords, blocks enumeration, and spots stuffing — layered on the rate-limiting algorithms you built back in Phase 2.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Password Storage & Hashing](../03-password-storage-and-hashing/) · [Multi-Factor Auth: TOTP & Passkeys](../04-multi-factor-auth-totp-and-passkeys/) · [Rate Limiting & Quotas](../../02-api-design/09-rate-limiting-quotas/)
**Time:** ~65 minutes

## The Problem

Your login endpoint is perfect. Argon2 password storage ([Lesson 3](../03-password-storage-and-hashing/)), optional MFA ([Lesson 4](../04-multi-factor-auth-totp-and-passkeys/)), secure sessions ([Lesson 5](../05-sessions-and-secure-cookies/)), no injection, correct authorization. An attacker can't *break* it — so they *use* it, millions of times, and win anyway:

- **Credential stuffing.** The attacker buys a list of 10 million `email:password` pairs leaked from *other* sites' breaches, and replays every pair against your login. Because people reuse passwords, some fraction — typically 0.1–2% — are valid on your site too. That's up to **200,000 account takeovers** from one list, and every single request was a *legitimate-looking* login attempt with a *correct* password. Your Argon2 hashing is irrelevant; the attacker never touched your database.
- **Brute force.** A variant aimed at one high-value account: hammer it with guesses until one lands.
- **Fake accounts.** Bots register thousands of accounts to send spam, farm referral bonuses, launder money, or abuse a free tier — your signup form, used at scale.
- **Scraping.** Bots harvest your catalog, prices, or user data through your public API — your API, used at scale.
- **Account-takeover economy.** A taken-over account is a product: resold, drained, used for fraud, or mined for more reused credentials. ATO is an industry, and your login is its raw material.

None of these are vulnerabilities in the Lesson-1 sense — there's no bug to fix, no `if` statement that's wrong. They're your **features working correctly, at a scale and intent you didn't design for.** That reframes the whole defense. You can't "close the hole" because there is no hole; you can only change the **economics**: make each attempt cost the attacker time, money, or a solved challenge, and make the *pattern* of abuse visible so you can respond — all without adding friction that drives away the humans you actually want. This lesson is that toolkit: rate limiting as the floor, breach-password screening and MFA as the account-takeover killers, bot detection and CAPTCHA as the human test, anti-enumeration so you don't hand out target lists, and throttling-not-lockout so your defense doesn't become the attacker's DoS.

## The Concept

### Credential stuffing: why using leaked passwords works

Credential stuffing deserves its own understanding because it's the dominant account-takeover vector and it exploits human behavior, not code:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 320" width="100%" style="max-width:880px" role="img" aria-label="Credential stuffing. Another site is breached, leaking millions of email and password pairs, which the attacker buys. An automated tool replays every pair against your login. Because people reuse passwords, a small percentage — roughly 0.1 to 2 percent — are valid on your site, yielding thousands of account takeovers, each from a legitimate-looking login with a correct password. The defenses that break it: MFA, so a correct password alone is not enough; breach-password screening, so the reused password was already flagged; and rate limiting plus bot detection, because the volume and pattern are detectable.">
  <defs>
    <marker id="l12s-ar" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Credential stuffing: password reuse turns someone else's breach into your problem</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="24" y="60" width="170" height="66" rx="10" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
      <rect x="256" y="60" width="170" height="66" rx="10" fill="#d64545" fill-opacity="0.10" stroke="#d64545"/>
      <rect x="488" y="60" width="170" height="66" rx="10" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/>
      <rect x="720" y="60" width="156" height="66" rx="10" fill="#d64545" fill-opacity="0.12" stroke="#d64545"/>
    </g>
    <text x="109" y="86" font-size="9.5" text-anchor="middle" font-weight="700">site B breached</text>
    <text x="109" y="104" font-size="8.5" text-anchor="middle">10M email:password</text>
    <text x="109" y="117" font-size="8.5" text-anchor="middle">pairs leak</text>
    <text x="341" y="86" font-size="9.5" text-anchor="middle" font-weight="700" fill="#d64545">attacker's bot</text>
    <text x="341" y="104" font-size="8.5" text-anchor="middle">replays each pair</text>
    <text x="341" y="117" font-size="8.5" text-anchor="middle">against YOUR login</text>
    <text x="573" y="86" font-size="9.5" text-anchor="middle" font-weight="700" fill="#3553ff">reuse → some work</text>
    <text x="573" y="104" font-size="8.5" text-anchor="middle">~0.1–2% valid</text>
    <text x="573" y="117" font-size="8.5" text-anchor="middle">(correct passwords!)</text>
    <text x="798" y="86" font-size="9.5" text-anchor="middle" font-weight="700" fill="#d64545">thousands of</text>
    <text x="798" y="104" font-size="8.5" text-anchor="middle">account takeovers</text>
    <text x="798" y="117" font-size="8.5" text-anchor="middle">→ fraud / resale</text>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M194 93 L 252 93" marker-end="url(#l12s-ar)"/>
    <path d="M426 93 L 484 93" marker-end="url(#l12s-ar)"/>
    <path d="M658 93 L 716 93" marker-end="url(#l12s-ar)"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="24" y="150" width="852" height="140" rx="10" fill="#0fa07f" fill-opacity="0.05" stroke="#0fa07f" stroke-opacity="0.6"/>
    <text x="38" y="172" font-size="11" font-weight="700" fill="#0fa07f">Three defenses that break the chain (each attacks a different link)</text>
    <text x="38" y="196" font-size="10">① <tspan font-weight="700">MFA</tspan> — a correct password is no longer sufficient, so the ~2% that would have worked still can't log in (Lesson 4). The single biggest ATO killer.</text>
    <text x="38" y="220" font-size="10">② <tspan font-weight="700">Breach-password screening</tspan> — reject passwords known to be in leaks (HIBP k-anonymity, Lesson 3), so the reused password was never allowed in the first place.</text>
    <text x="38" y="244" font-size="10">③ <tspan font-weight="700">Rate limiting + bot detection</tspan> — millions of attempts have a shape (one IP, many accounts; headless clients; velocity) that a human login doesn't (Phase 2 · L9).</text>
    <text x="38" y="272" font-size="9.5" opacity="0.8">Note: the attacker isn't guessing — they hold correct credentials. So detection and MFA matter more here than making the hash slow.</text>
  </g>
</svg>
```

The crucial insight: in credential stuffing the attacker is **not guessing** — they hold *correct* passwords harvested elsewhere. So the classic "slow hash + strong password policy" does little, and the effective defenses are the ones that make a correct password *insufficient* (MFA), make a reused password *unavailable* (breach screening), or make the *volume and pattern* detectable (rate limiting, bot detection). This is why MFA is repeatedly cited as blocking the vast majority of automated account attacks.

### Rate limiting is the floor, not the ceiling

**Rate limiting** — capping requests per IP, per account, per endpoint, over a window — is the foundation, and you already built the algorithms (token bucket, sliding window) in [Phase 2, Lesson 9](../../02-api-design/09-rate-limiting-quotas/). Apply it at multiple keys: **per-account** (stop brute force on one user), **per-IP** (stop a flood from one source), and **per-endpoint** (login and password-reset are more sensitive than a product page). But understand its limit against a serious adversary: attackers spread stuffing across **thousands of IPs** (botnets, residential proxies), so a per-IP limit alone sees only a handful of attempts from each address and never trips. Rate limiting stops the lazy attacker and shapes traffic; it is necessary but not sufficient, which is why the layers above it exist.

### The defense funnel: filter abuse, pass humans

No single control stops abuse; you stack them so each layer removes more automated traffic while a real human sails through:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 356" width="100%" style="max-width:820px" role="img" aria-label="The abuse-defense funnel. Login attempts, mostly automated, enter at the top and pass through narrowing layers. Layer one, rate limiting per IP, account, and endpoint, drops floods. Layer two, bot signals such as IP reputation, headless-browser detection, and velocity, drops obvious bots. Layer three, a CAPTCHA or proof-of-work challenge shown on suspicion, drops bots that can't solve it. Layer four, breach-password screening and MFA, means even a correct reused password is not enough. What reaches the bottom is legitimate humans; automated abuse is filtered at each layer without adding friction for normal users.">
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Layer the defenses — each removes more abuse, humans pass through</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="450" y="52" font-size="10" text-anchor="middle" opacity="0.7">login attempts (mostly automated) ↓</text>
    <g stroke-linejoin="round" stroke-width="1.8">
      <polygon points="180,66 720,66 660,108 240,108" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
      <polygon points="243,116 657,116 606,158 294,158" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
      <polygon points="297,166 603,166 552,208 348,208" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <polygon points="351,216 549,216 498,258 402,258" fill="#0fa07f" fill-opacity="0.15" stroke="#0fa07f"/>
    </g>
    <text x="450" y="92" font-size="10.5" font-weight="700" text-anchor="middle" fill="#e0930f">① RATE LIMITING</text>
    <text x="450" y="104" font-size="8" text-anchor="middle">per IP / account / endpoint — drops floods</text>
    <text x="450" y="140" font-size="10.5" font-weight="700" text-anchor="middle" fill="#3553ff">② BOT SIGNALS</text>
    <text x="450" y="152" font-size="8" text-anchor="middle">IP reputation, headless, velocity, no-JS</text>
    <text x="450" y="190" font-size="10.5" font-weight="700" text-anchor="middle" fill="#7c5cff">③ CHALLENGE (on suspicion)</text>
    <text x="450" y="202" font-size="8" text-anchor="middle">CAPTCHA / proof-of-work</text>
    <text x="450" y="240" font-size="10" font-weight="700" text-anchor="middle" fill="#0fa07f">④ BREACH-PW + MFA</text>
  </g>
  <text x="450" y="286" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="11" font-weight="700" fill="#0fa07f">↓ legitimate humans</text>
  <text x="450" y="316" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.9">Key idea: apply friction (CAPTCHA, step-up) ONLY to suspicious traffic, so 99% of users never see it.</text>
  <text x="450" y="336" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.9">A challenge everyone sees is a tax on your users; a challenge only bots see is a tax on the attacker.</text>
</svg>
```

The layers, from cheap-and-broad to targeted: **rate limiting** (drops floods), **bot signals** (IP/ASN reputation, known-proxy lists, headless-browser and automation fingerprints, request velocity, missing JS/cookies), an active **challenge** shown *only on suspicion* (a **CAPTCHA** — Completely Automated Public Turing test — or a **proof-of-work** puzzle that costs the client CPU), and finally the account-level controls (**breach screening + MFA**). The governing principle is **adaptive friction**: never make everyone solve a CAPTCHA — that's a tax on your real users and it hurts conversion. Score each request's risk and apply friction *only* to the risky ones, so the human logging in from their usual device sees nothing and the botnet hits a wall.

### Lockout vs throttling, and the enumeration leak

Two classic mistakes turn a defense into a new vulnerability. The first is **account lockout** — "lock the account after 5 failed attempts." It sounds safe and creates a **denial-of-service**: an attacker who *wants* to lock out a victim just fails their login five times on purpose, and now the real user can't get in. Worse, under credential stuffing, lockouts across millions of accounts become a mass-DoS. The better tool is **progressive throttling**: add an increasing delay (exponential backoff) and a CAPTCHA after repeated failures, which slows an attacker to a crawl without ever fully locking a legitimate user out.

The second is **user enumeration**: a login (or signup, or password-reset) that responds differently for "no such user" than for "wrong password" hands the attacker a way to **discover which emails have accounts** — refining their stuffing list and enabling targeted phishing. The fix is **uniform responses**: the same generic message ("invalid email or password"), the same status code, and similar *timing* (don't skip the expensive password hash when the user doesn't exist, or the fast rejection reveals the absence) for both cases.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 316" width="100%" style="max-width:880px" role="img" aria-label="Two defenses that must not become vulnerabilities. Left: account lockout after N failures can be abused — an attacker deliberately fails a victim's login to lock them out, turning the defense into a denial of service, and mass lockouts under credential stuffing lock out many users at once. Right: progressive throttling adds increasing delay and a CAPTCHA after repeated failures, slowing the attacker without locking the legitimate user out. Bottom: user enumeration — responding 'no such user' differently from 'wrong password' reveals which emails have accounts; the fix is uniform responses with the same message, status, and timing for both.">
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Don't let the defense become the attack</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="20" y="44" width="424" height="130" rx="12" fill="#d64545" fill-opacity="0.06" stroke="#d64545" stroke-opacity="0.8"/>
    <rect x="460" y="44" width="424" height="130" rx="12" fill="#0fa07f" fill-opacity="0.06" stroke="#0fa07f" stroke-opacity="0.8"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="232" y="68" font-size="12" font-weight="700" text-anchor="middle" fill="#d64545">HARD LOCKOUT — becomes a DoS</text>
    <text x="232" y="92" font-size="9.5" text-anchor="middle">"lock after 5 fails" →</text>
    <text x="232" y="112" font-size="9.5" text-anchor="middle">attacker fails a victim's login 5x on</text>
    <text x="232" y="128" font-size="9.5" text-anchor="middle">purpose → victim locked out</text>
    <text x="232" y="152" font-size="9" text-anchor="middle" opacity="0.8">mass-lockout under stuffing = mass DoS</text>
    <text x="672" y="68" font-size="12" font-weight="700" text-anchor="middle" fill="#0fa07f">PROGRESSIVE THROTTLING</text>
    <text x="672" y="92" font-size="9.5" text-anchor="middle">increasing delay (backoff) +</text>
    <text x="672" y="112" font-size="9.5" text-anchor="middle">CAPTCHA after repeated failures</text>
    <text x="672" y="128" font-size="9.5" text-anchor="middle">slows the attacker to a crawl,</text>
    <text x="672" y="152" font-size="9" text-anchor="middle" opacity="0.8">never fully locks a real user out</text>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="20" y="190" width="864" height="106" rx="10" fill="#e0930f" fill-opacity="0.06" stroke="#e0930f" stroke-opacity="0.6"/>
    <text x="34" y="212" font-size="11" font-weight="700" fill="#e0930f">User enumeration — don't reveal which accounts exist</text>
    <text x="34" y="234" font-size="9.5" fill="#d64545">✗ "no such user" (fast, 200) vs "wrong password" (slow, 401)  → attacker maps valid emails, refines the stuffing list, phishes</text>
    <text x="34" y="256" font-size="9.5" fill="#0fa07f">✓ uniform: same message ("invalid email or password"), same status, similar timing (run the hash even when the user is absent)</text>
    <text x="34" y="278" font-size="9" fill="currentColor" opacity="0.8">Same rule applies to signup ("email already registered") and password-reset ("we sent an email" — always).</text>
  </g>
</svg>
```

### The economics, stated plainly

Every control here is an economic lever. Rate limiting and proof-of-work raise the attacker's **cost per attempt**; MFA and breach screening raise the **cost of a successful password to near-infinite**; bot detection raises the **cost of looking human**; anti-enumeration raises the **cost of building a target list**. You will never make abuse impossible — a determined, funded attacker can rotate IPs, solve CAPTCHAs with human farms, and buy fresh credentials. The goal is to make *your* site a worse deal than the next one: expensive enough to attack that the attacker moves on, while staying cheap enough to use that your real users don't. Defense in depth, adaptive friction, and good detection are how you tilt that math.

## Build It

Standard library only — dicts, `time`, `hmac` — to build a login-abuse defender that combines the strategy-level controls this lesson is about (the rate-limit *algorithms* live in [Phase 2, Lesson 9](../../02-api-design/09-rate-limiting-quotas/)): progressive backoff instead of lockout, a suspicion score that triggers a CAPTCHA, breach-password screening, uniform anti-enumeration responses, and credential-stuffing detection.

Progressive throttling replaces lockout — the delay grows with failures but the account never fully locks:

```python
def backoff_delay(failures: int) -> float:
    return 0.0 if failures <= 3 else min(2 ** (failures - 1), 30)   # 0,0,0,8,16,30s — never a hard lock

def require_captcha(ip) -> bool:
    return ip.failures >= 5 or len(ip.distinct_accounts) >= 10      # friction only when suspicious
```

Credential stuffing shows up as *one IP touching many distinct accounts* — a pattern a human login never has — and enumeration is defeated by a single uniform outcome:

```python
def login(email, password, *, now, ip, state, breached):
    ips = state.ip[ip]
    if require_captcha(ips) and not captcha_solved:
        return "captcha_required"                      # challenge the suspicious, not everyone
    if now < ips.blocked_until:
        return "slow_down"                             # progressive backoff in effect
    user = USERS.get(email)
    ok = user is not None and verify_password(password, user["hash"])   # ALWAYS run the hash (timing)
    if not ok:
        register_failure(state, ip, email, now)
        return "invalid email or password"            # identical for unknown user AND wrong password
    if password_is_breached(password, breached):
        return "reset_required: password found in a breach"   # correct pw, but known-leaked
    return "ok (then require MFA)"                     # a correct password is not the end — MFA next
```

The full defender — per-IP/per-account tracking, backoff, CAPTCHA triggers, breach screening, uniform responses, and a stuffing-detection demo — is in [`code/abuse_prevention.py`](code/abuse_prevention.py). Run it:

```console
$ python3 abuse_prevention.py
== 1 · UNIFORM RESPONSES (no user enumeration) ==
  wrong password for real user  -> 'invalid email or password'
  login for a non-existent user -> 'invalid email or password'   (same message + timing)

== 2 · PROGRESSIVE BACKOFF, NOT LOCKOUT ==
  fails 1..6 -> delay: [0.0, 0.0, 0.0, 8, 16, 30] s   (grows, but the account never hard-locks)
  a legitimate user can still get in after waiting; no attacker-triggered lockout

== 3 · CAPTCHA ONLY WHEN SUSPICIOUS ==
  normal user (0 fails)                 -> captcha? False
  after 5 failures on this IP           -> captcha? True
  one IP hitting 10 distinct accounts   -> captcha? True   (credential-stuffing shape)

== 4 · CREDENTIAL STUFFING DETECTION ==
  IP 203.0.113.9 tried 12 distinct accounts in the window -> flagged as stuffing  ✓
  a normal user tries 1-2 accounts -> not flagged

== 5 · BREACH-PASSWORD SCREENING + MFA ==
  login with correct BUT breached password -> 'reset_required: password found in a breach'
  login with correct, clean password       -> 'ok (then require MFA)'   <- MFA still required
```

**Section 1** is anti-enumeration: unknown user and wrong password return the *same* string (and the code runs the hash either way, so timing doesn't leak). **Section 2** shows backoff growing without ever hard-locking — no attacker-triggered DoS. **Section 3** applies the CAPTCHA only to suspicious IPs. **Section 4** catches the credential-stuffing signature — one IP, many accounts. **Section 5** shows the two account-takeover killers: a correct-but-breached password is refused, and even a clean correct password only advances to the MFA step.

## Use It

In production you assemble these from managed services and the tools built earlier in this phase, because doing bot management well at scale is a specialty. For the **broad filter**, a CDN/WAF with **bot management** (Cloudflare, Akamai, AWS WAF, Fastly) scores traffic on IP reputation, ASN, TLS/HTTP fingerprints, and behavioral signals, and blocks or challenges before requests reach you. For the **human challenge**, use a modern **CAPTCHA** (reCAPTCHA v3, hCaptcha, Cloudflare **Turnstile**) invoked *adaptively* on risky requests, not universally. For **account-takeover specifically**, the two highest-leverage controls are the ones you already built: **MFA** ([Lesson 4](../04-multi-factor-auth-totp-and-passkeys/)) — the single most effective ATO defense — and **breach-password screening** at signup and password-change via HIBP's k-anonymity API ([Lesson 3](../03-password-storage-and-hashing/)). Add **device fingerprinting / recognition** so a login from a brand-new device triggers step-up verification, and **anomaly detection** (impossible travel, sudden velocity, new-country logins) feeding a risk score.

For **rate limiting**, use the algorithms from [Phase 2, Lesson 9](../../02-api-design/09-rate-limiting-quotas/) at multiple keys (per-IP, per-account, per-endpoint), typically at the gateway. And wire it all to **monitoring** ([Phase 9](../../09-logging-monitoring-and-observability/01-why-systems-go-dark/)) — a spike in login failures, a surge from one ASN, or an unusual signup rate is your early warning; abuse you can't *see* is abuse you can't respond to. The rules to carry: **rate-limit as the floor, MFA and breach-screening as the ATO killers, throttle-don't-lockout, respond uniformly to avoid enumeration, and apply friction adaptively** — the whole game is to price the attacker out while the human never notices, and to detect the pattern when someone tries anyway.

## Think about it

1. Your login uses Argon2 with a high work factor and a strong password policy, and you're hit with credential stuffing. Explain why your excellent password *storage* barely helps here, and name the two controls that actually stop it — tying each to *why* it works against an attacker who holds correct passwords.
2. A per-IP rate limit of 10 login attempts/minute is deployed, and stuffing continues unabated. What is the attacker almost certainly doing, and which two non-rate-limit layers detect the abuse the per-IP limit misses?
3. "Lock the account for 30 minutes after 5 failed logins" is a common request. Describe the denial-of-service it creates, how it amplifies under credential stuffing, and what you'd build instead.
4. Two login responses: "no account with that email" (returns in 5 ms) and "incorrect password" (returns in 250 ms). Name both ways this leaks information to an attacker (the message *and* the timing), and give the fix for each.
5. A product manager wants a CAPTCHA on every login "to stop bots." Argue the case against a universal CAPTCHA on both security and business grounds, and describe the adaptive approach that gets most of the benefit at a fraction of the user cost.

## Key takeaways

- **Abuse is your features used correctly, at scale and with hostile intent** — credential stuffing, brute force, fake signups, scraping, account takeover. There's no bug to fix; you change the **economics**, making abuse expensive and detectable while keeping the site frictionless for humans.
- **Credential stuffing is the dominant ATO vector and the attacker isn't guessing** — they replay *correct* passwords leaked elsewhere, so slow hashing barely helps. It's broken by **MFA** (a correct password isn't enough), **breach-password screening** (the reused password was never allowed), and **rate limiting + bot detection** (the volume and pattern are visible).
- **Rate limiting is the floor, not the ceiling.** Apply it per-IP, per-account, and per-endpoint (algorithms from Phase 2·L9), but know that botnets spread across thousands of IPs slip under per-IP limits — so it must be layered with bot signals and challenges.
- **Layer defenses into a funnel and apply friction adaptively:** rate limit → bot signals → CAPTCHA/proof-of-work *only on suspicion* → breach-screening + MFA. A challenge everyone sees taxes your users; a challenge only bots see taxes the attacker.
- **Don't let the defense become the attack:** hard **account lockout is a DoS** (an attacker locks out victims on purpose) — use **progressive throttling/backoff** instead; and **user enumeration** (different responses for unknown-user vs wrong-password) hands out target lists — respond **uniformly** in message, status, and timing (and always run the password hash).
- **In production, assemble managed pieces:** a WAF/bot-management layer for the broad filter, adaptive CAPTCHA (Turnstile/hCaptcha), device fingerprinting and anomaly detection for risk scoring, and — the highest leverage of all — **MFA and breach-password screening** for account takeover, all fed by **monitoring** so you can see and respond to abuse.

Next: [Secrets Management & Rotation](../13-secrets-management-and-rotation/) — the final piece: this whole phase runs on secrets — signing keys, pepper, API keys, webhook secrets, database passwords — and next you learn where they live, how they're injected, and how to rotate them, so the keys that protect everything don't become the thing that leaks.
