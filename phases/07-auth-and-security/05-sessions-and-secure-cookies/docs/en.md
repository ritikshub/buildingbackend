# Sessions & Secure Cookies

> Login proves who you are exactly once. Then HTTP forgets — every one of the next thousand requests arrives as a stranger, because the protocol is stateless. A **session** is how the server remembers you across them, and the **cookie** that carries the session is a bearer token: whoever holds it *is* you, no password required. This lesson builds server-side sessions and signed cookies from scratch, and gets the four cookie attributes — `HttpOnly`, `Secure`, `SameSite`, and the `__Host-` prefix — exactly right, because each one is the entire defense against a specific, common attack.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Cryptographic Building Blocks](../02-cryptographic-building-blocks/) · [HTTP in Depth](../../01-networking-and-protocols/08-http-in-depth/)
**Time:** ~65 minutes

## The Problem

Your login endpoint works: it checks the password ([Lesson 3](../03-password-storage-and-hashing/)), maybe a second factor ([Lesson 4](../04-multi-factor-auth-totp-and-passkeys/)), and confirms this request is from `alice`. Then the response goes out, the connection closes, and the *next* request Alice makes — clicking to her dashboard — arrives at your server carrying **nothing** that says it's her. HTTP is **stateless**: each request is independent, with no memory of any request before it ([Phase 1, Lesson 8](../../01-networking-and-protocols/08-http-in-depth/)). You proved who Alice was, and the protocol immediately forgot.

The naive fixes are each a vulnerability:

- **Put the identity in the request.** Set a cookie `user=alice`, read it back on every request. This is the forged-token bug from [Lesson 1](../01-authn-authz-and-the-security-mindset/) again — the client controls the cookie, so anyone sends `user=admin`. Identity the client can *assert* is not identity.
- **Re-send the password every request.** Now the password is in a thousand requests, a thousand log lines, a thousand proxies — vastly more exposure than one login, and MFA becomes meaningless (you can't re-prompt for a code on every click).
- **Hand out a random token and remember it.** This is the right idea, and it's called a session. But now the token *is* the credential — and everything that can happen to a credential can happen to it.

That last point is the whole lesson. A session identifier is a **bearer token**: the server trusts whoever presents it, exactly as a bearer bond pays whoever holds it. So the attacker's goal shifts from stealing Alice's password to stealing Alice's session, and there are five well-worn ways to try:

- **Guessing** the token, if it's short or predictable (sequential IDs, timestamps, a weak RNG — [Lesson 2](../02-cryptographic-building-blocks/)).
- **Stealing** it with cross-site scripting: malicious JavaScript reads `document.cookie` and exfiltrates it ([Lesson 10](../10-browser-trust-boundary-cors-csrf-xss/)).
- **Sniffing** it off the wire if any request goes over plain HTTP (**sidejacking**).
- **Riding** it from another site: the browser attaches your cookie to a forged cross-site request (**CSRF**, [Lesson 10](../10-browser-trust-boundary-cors-csrf-xss/)).
- **Fixing** it: the attacker plants a session ID they know, then tricks you into logging in under it (**session fixation**).

Notice something: four of these five are stopped almost entirely by *how you configure the cookie* and *how you generate the ID* — not by clever code. Sessions are a place where the defaults are the security, and this lesson is about setting them.

## The Concept

### A session: the server's memory of a logged-in client

A **session** is server-side state representing one authenticated period for one client. It has two parts that must not be confused. The **session data** — who the user is, their roles, a CSRF token, when they logged in — lives on the **server** (in memory, Redis, or a database). The **session ID** — a single opaque random string — is the *only* thing given to the client, and on each request the server uses it to look the data back up:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 350" width="100%" style="max-width:880px" role="img" aria-label="Session flow. At login the server verifies the password, generates a random session ID, stores the session data keyed by that ID in a session store, and returns the ID in a Set-Cookie header. On every later request the browser automatically sends the cookie; the server looks the ID up in the store to recover the identity. Only the opaque ID travels; the data stays on the server.">
  <defs>
    <marker id="l5s-ar" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Only the opaque ID travels; the data stays on the server</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="30" y="58" font-size="11.5" font-weight="700" fill="#3553ff">① LOGIN</text>
    <g fill="none" stroke-linejoin="round" stroke-width="1.7">
      <rect x="30" y="68" width="130" height="40" rx="8" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
      <rect x="250" y="64" width="200" height="48" rx="9" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/>
      <rect x="540" y="64" width="330" height="48" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M160 88 L 246 88" marker-end="url(#l5s-ar)"/>
      <path d="M450 88 L 536 88" marker-end="url(#l5s-ar)"/>
    </g>
    <text x="95" y="92" font-size="10" text-anchor="middle">POST /login</text>
    <text x="350" y="84" font-size="9.5" text-anchor="middle">verify password (+MFA)</text>
    <text x="350" y="100" font-size="9.5" text-anchor="middle">generate random ID</text>
    <text x="705" y="82" font-size="9" text-anchor="middle">STORE  sid → {user: alice,</text>
    <text x="705" y="96" font-size="9" text-anchor="middle">roles, csrf, login_at}</text>
    <text x="705" y="108" font-size="8" text-anchor="middle" opacity="0.7">(memory / Redis / DB)</text>
  </g>
  <g fill="none" stroke="#3553ff" stroke-width="1.7">
    <path d="M540 120 L 200 120 L 200 150" marker-end="url(#l5s-ar)"/>
  </g>
  <text x="370" y="136" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9" fill="#3553ff">Set-Cookie: sid=8Kd9x… (the ID only) ↙</text>
  <line x1="30" y1="172" x2="870" y2="172" stroke="currentColor" stroke-opacity="0.18" stroke-width="1"/>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="30" y="200" font-size="11.5" font-weight="700" fill="#0fa07f">② EVERY LATER REQUEST</text>
    <g fill="none" stroke-linejoin="round" stroke-width="1.7">
      <rect x="30" y="210" width="150" height="46" rx="8" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
      <rect x="270" y="210" width="200" height="46" rx="9" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/>
      <rect x="560" y="210" width="310" height="46" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M180 233 L 266 233" marker-end="url(#l5s-ar)"/>
      <path d="M470 233 L 556 233" marker-end="url(#l5s-ar)"/>
    </g>
    <text x="105" y="229" font-size="9" text-anchor="middle">GET /dashboard</text>
    <text x="105" y="245" font-size="8" text-anchor="middle" opacity="0.72">Cookie: sid=8Kd9x…</text>
    <text x="370" y="230" font-size="9.5" text-anchor="middle">look up sid</text>
    <text x="370" y="246" font-size="9" text-anchor="middle">in the store</text>
    <text x="715" y="230" font-size="9.5" text-anchor="middle">→ this is alice</text>
    <text x="715" y="246" font-size="8.5" text-anchor="middle" opacity="0.72">identity recovered, no password</text>
  </g>
  <text x="450" y="300" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">The browser attaches the cookie automatically on every request to the site — which is the convenience</text>
  <text x="450" y="318" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">that makes sessions work, and the mechanism that makes CSRF possible (Lesson 10).</text>
  <text x="450" y="340" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.7">Because the data lives server-side, logout is instant: delete the sid from the store and the token is dead.</text>
</svg>
```

Keeping the data server-side buys two things. The client can't tamper with `roles` or `is_admin` because it never holds them — it holds a meaningless random string. And **logout actually works**: delete the ID from the store and the session is instantly, globally dead. (Hold onto that; it's precisely the property stateless tokens sacrifice in [Lesson 6](../06-jwt-and-token-auth/).)

### The session ID is a bearer token, so it must be unguessable

Everything rests on the ID being impossible to guess. If IDs are sequential (`session_1042`), derived from the user ID, or drawn from a non-cryptographic RNG ([Lesson 2](../02-cryptographic-building-blocks/)), an attacker predicts or enumerates valid sessions and walks into accounts without a password. The rule is exact: a session ID is **≥128 bits of entropy from a CSPRNG** (`secrets.token_urlsafe(32)` gives 256 bits), opaque (it encodes nothing — no user ID, no role, no timestamp the attacker can read or forge), and looked up in constant-relevant time. It is not a place to be clever; it is a place to be random.

### Cookies, and the attributes that are security controls

A **cookie** is the browser's mechanism for carrying the session ID: the server sends `Set-Cookie` once, and the browser then attaches it automatically to every matching request. Cookies carry **attributes**, and the security-critical ones are not tuning knobs — each is the whole defense against one attack:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 330" width="100%" style="max-width:880px" role="img" aria-label="Anatomy of a hardened Set-Cookie header. The session value is 256 random bits, unguessable. HttpOnly means JavaScript cannot read the cookie, so cross-site scripting cannot steal it. Secure means the cookie is sent only over HTTPS, defeating network sniffing. SameSite equals Lax means the cookie is not sent on cross-site POST requests, mitigating CSRF. Path scopes the cookie. Max-Age bounds its lifetime. The __Host- prefix forces Secure, Path=/, and no Domain.">
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Each cookie attribute closes one attack</text>
  <text x="450" y="60" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="12.5" fill="currentColor">Set-Cookie: __Host-sid=8Kd9x2…rQ; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=1209600</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10">
    <g fill="none" stroke-width="1.5">
      <path d="M150 72 L 150 96 L 180 96" stroke="#7c5cff"/>
      <path d="M250 72 L 250 122 L 280 122" stroke="#0fa07f"/>
      <path d="M360 72 L 360 148 L 390 148" stroke="#3553ff"/>
      <path d="M440 72 L 440 174 L 470 174" stroke="#e0930f"/>
      <path d="M560 72 L 560 200 L 590 200" stroke="#d64545"/>
    </g>
    <text x="186" y="100" fill="#7c5cff" font-weight="700">__Host- prefix — forces Secure + Path=/ + no Domain (hardened, un-overridable by subdomains)</text>
    <text x="286" y="126" fill="#0fa07f" font-weight="700">value — 256 random bits from a CSPRNG → unguessable, opaque (encodes nothing)</text>
    <text x="396" y="152" fill="#3553ff" font-weight="700">HttpOnly — JavaScript cannot read document.cookie → XSS can't steal the session</text>
    <text x="476" y="178" fill="#e0930f" font-weight="700">Secure — sent only over HTTPS → no sniffing off the wire (sidejacking)</text>
    <text x="596" y="204" fill="#d64545" font-weight="700">SameSite=Lax — not sent on cross-site POST → mitigates CSRF (Lesson 10)</text>
  </g>
  <line x1="30" y1="228" x2="870" y2="228" stroke="currentColor" stroke-opacity="0.18" stroke-width="1"/>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor">
    <text x="30" y="252" font-weight="700" opacity="0.8">Also:</text>
    <text x="30" y="272">Path / Domain — scope the cookie as narrowly as possible; Max-Age / Expires — bound the lifetime (a session</text>
    <text x="30" y="288">cookie with no Expires dies when the browser closes; a persistent one survives — pick deliberately).</text>
    <text x="30" y="312" opacity="0.9">The defaults ARE the security here: a session cookie missing HttpOnly or Secure is a bug, not a preference.</text>
  </g>
</svg>
```

Commit these to memory, because forgetting one is a real vulnerability:

- **`HttpOnly`** — JavaScript cannot read the cookie via `document.cookie`. This is what stops an XSS bug ([Lesson 10](../10-browser-trust-boundary-cors-csrf-xss/)) from *stealing* the session. (It does not stop XSS from *using* the session in-page, which is why you still fix the XSS.)
- **`Secure`** — the browser sends the cookie only over HTTPS, so it can't be sniffed off a plaintext connection on shared Wi-Fi.
- **`SameSite`** — controls whether the cookie rides along on requests initiated by *other* sites. `Lax` (the modern default) sends it on top-level navigations but not on cross-site `POST`s or subresource loads; `Strict` never sends it cross-site; `None` always does (and then requires `Secure`). This is a primary CSRF defense, completed in [Lesson 10](../10-browser-trust-boundary-cors-csrf-xss/).
- **`__Host-` prefix** — a cookie name starting with `__Host-` is only accepted by the browser if it's `Secure`, has `Path=/`, and has **no** `Domain` — which locks it to the exact origin and prevents a compromised subdomain from overwriting it. The strongest default for a session cookie.

### The stateless alternative: signed cookies

Server-side sessions require a store and a lookup on every request. The alternative is to put the data *in* the cookie and make it **tamper-proof** instead of secret — a **signed cookie**: `value = payload . HMAC(secret, payload)` ([Lesson 2](../02-cryptographic-building-blocks/)). The client can read the payload but can't change it, because editing it invalidates the HMAC, which only the server's key can produce. This trades the store lookup for a signature check and is exactly the idea [Lesson 6](../06-jwt-and-token-auth/) formalizes as a JWT. The tradeoff is the mirror image of server-side sessions: no store, no per-request lookup, but **you can't instantly revoke** one (the server isn't consulted), and the data is *visible* to the client (signed ≠ encrypted — never put secrets in it). Signed cookies are great for small, non-secret, short-lived state; server-side sessions win when instant logout and revocation matter.

### The session lifecycle: rotate, expire, revoke

A session is not just created and destroyed; three lifecycle rules prevent whole attack classes.

**Rotate the ID on every privilege change — especially at login.** This is the fix for **session fixation**, where the attacker plants a session ID they already know (via a link like `?sid=attacker_known`, or a subdomain-set cookie) and waits for the victim to authenticate under it — after which the attacker's copy of the ID is a logged-in session:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 300" width="100%" style="max-width:880px" role="img" aria-label="Session fixation. Top timeline, the attack: the attacker plants a known session ID in the victim's browser, the victim logs in, and if the server keeps the same ID the attacker's copy is now an authenticated session. Bottom timeline, the fix: on successful login the server discards the pre-login ID and issues a brand-new random one, so the attacker's known ID is never authenticated and is now worthless.">
  <defs>
    <marker id="l5f-ar" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Session fixation — and why you rotate the ID at login</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="30" y="58" font-size="11" font-weight="700" fill="#d64545">ATTACK (server keeps the pre-login ID)</text>
    <g fill="none" stroke-linejoin="round" stroke-width="1.6">
      <rect x="30" y="70" width="230" height="44" rx="8" fill="#d64545" fill-opacity="0.10" stroke="#d64545"/>
      <rect x="335" y="70" width="200" height="44" rx="8" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
      <rect x="610" y="70" width="260" height="44" rx="8" fill="#d64545" fill-opacity="0.12" stroke="#d64545"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M260 92 L 331 92" marker-end="url(#l5f-ar)"/>
      <path d="M535 92 L 606 92" marker-end="url(#l5f-ar)"/>
    </g>
    <text x="145" y="88" font-size="8.5" text-anchor="middle">attacker plants known</text>
    <text x="145" y="102" font-size="8.5" text-anchor="middle">sid=ABC in victim's browser</text>
    <text x="435" y="88" font-size="8.5" text-anchor="middle">victim logs in;</text>
    <text x="435" y="102" font-size="8.5" text-anchor="middle">server reuses sid=ABC</text>
    <text x="740" y="88" font-size="8.5" text-anchor="middle" fill="#d64545">attacker's sid=ABC is now</text>
    <text x="740" y="102" font-size="8.5" text-anchor="middle" fill="#d64545">an authenticated session ✗</text>
  </g>
  <line x1="30" y1="140" x2="870" y2="140" stroke="currentColor" stroke-opacity="0.18" stroke-width="1"/>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="30" y="170" font-size="11" font-weight="700" fill="#0fa07f">FIX (rotate the ID on login)</text>
    <g fill="none" stroke-linejoin="round" stroke-width="1.6">
      <rect x="30" y="182" width="230" height="44" rx="8" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
      <rect x="335" y="182" width="200" height="44" rx="8" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/>
      <rect x="610" y="182" width="260" height="44" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M260 204 L 331 204" marker-end="url(#l5f-ar)"/>
      <path d="M535 204 L 606 204" marker-end="url(#l5f-ar)"/>
    </g>
    <text x="145" y="200" font-size="8.5" text-anchor="middle">attacker plants known</text>
    <text x="145" y="214" font-size="8.5" text-anchor="middle">sid=ABC in victim's browser</text>
    <text x="435" y="200" font-size="8.5" text-anchor="middle">victim logs in; server</text>
    <text x="435" y="214" font-size="8.5" text-anchor="middle">issues NEW sid=XYZ</text>
    <text x="740" y="200" font-size="8.5" text-anchor="middle" fill="#0fa07f">attacker's sid=ABC was never</text>
    <text x="740" y="214" font-size="8.5" text-anchor="middle" fill="#0fa07f">authenticated — worthless ✓</text>
  </g>
  <text x="450" y="266" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Rule: on any change of privilege — login, elevation, re-auth for a sensitive action — throw away the old</text>
  <text x="450" y="284" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">session ID and mint a fresh one. The attacker can only ever hold a pre-login ID, which now authenticates no one.</text>
</svg>
```

**Expire on two clocks.** An **idle timeout** ends a session after a period of inactivity (so an abandoned session on a shared computer dies); an **absolute timeout** caps total lifetime regardless of activity (so a stolen long-lived session can't live forever). Both, not one.

**Make logout and revocation real.** Logout must **delete the session server-side**, not merely clear the client cookie — otherwise a copied cookie keeps working after the user "logged out." The same store lets you revoke *all* of a user's sessions (on password change, or "log out everywhere"), invalidate on suspicious activity, and cap concurrent sessions. This revocability is the strongest reason to keep sessions server-side.

### Where the session store lives

For a single process, an in-memory dict works (and is what you'll build). Real deployments run many processes across many machines, so the store must be **shared** — typically **Redis** ([Phase 5](../../05-caching/03-redis-fundamentals/)), which fits perfectly: it's fast, every request does one lookup, and its per-key **TTL** (time-to-live) implements the session timeout for free. The alternatives are sticky-session load balancing (fragile) or stateless signed tokens (Lesson 6). "Session in Redis" is the default backend answer for a reason.

## Build It

Standard library only — `secrets` for the ID, a hand-built `Set-Cookie` (the attributes are the point), `hmac` for the signed-cookie variant. Two session strategies, side by side, plus the lifecycle rules that make them safe.

Server-side sessions are a store keyed by an unguessable ID, with rotation and expiry:

```python
class SessionStore:
    def __init__(self, idle=1800, absolute=86400):
        self._store: dict[str, dict] = {}
        self.idle, self.absolute = idle, absolute

    def new(self, now: int, **data) -> str:
        sid = secrets.token_urlsafe(32)              # 256 bits from the CSPRNG, opaque
        self._store[sid] = {**data, "created": now, "seen": now}
        return sid

    def get(self, sid: str, now: int) -> dict | None:
        s = self._store.get(sid)
        if s is None:
            return None
        if now - s["seen"] > self.idle or now - s["created"] > self.absolute:
            self._store.pop(sid, None)               # expired on either clock
            return None
        s["seen"] = now                              # sliding idle window
        return s

    def rotate(self, old_sid: str, now: int) -> str:
        """On login/privilege change: new ID, same data — defeats fixation."""
        data = self._store.pop(old_sid, {})
        sid = secrets.token_urlsafe(32)
        self._store[sid] = {**data, "created": now, "seen": now}
        return sid

    def destroy(self, sid: str) -> None:
        self._store.pop(sid, None)                   # logout is a real deletion
```

The hardened `Set-Cookie` is worth emitting by hand once, because the attributes are the security:

```python
def set_cookie(sid: str, max_age=1209600) -> str:
    # The security IS the attributes; __Host- also forbids Domain and forces Path=/ + Secure.
    # (http.cookies.SimpleCookie can emit these too.)
    return f"__Host-sid={sid}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age={max_age}"
```

The signed-cookie alternative keeps *no* server state — it makes the payload unforgeable instead of secret:

```python
def sign(payload: bytes, key: bytes) -> str:
    tag = hmac.new(key, payload, hashlib.sha256).digest()
    return b64(payload) + "." + b64(tag)

def unsign(token: str, key: bytes) -> bytes | None:
    body, tag = token.split(".")
    expected = hmac.new(key, ub64(body), hashlib.sha256).digest()
    return ub64(body) if hmac.compare_digest(ub64(tag), expected) else None  # tamper -> None
```

The full script — the store with idle/absolute expiry, ID rotation defeating a fixation attempt, the hardened cookie, the signed-cookie round-trip with a tamper test, and an entropy/guessing demonstration — is in [`code/sessions.py`](code/sessions.py). Run it:

```console
$ python3 sessions.py
== 1 · SERVER-SIDE SESSION: OPAQUE ID, DATA STAYS SERVER-SIDE ==
  sid = mCjwyULE... (43 chars, 256 bits) — encodes nothing
  Set-Cookie: __Host-sid=mCjwyULE...; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=1209600
  lookup -> {'user': 'alice', 'roles': ['user'], ...}

== 2 · ROTATION ON LOGIN DEFEATS SESSION FIXATION ==
  pre-login sid  RuJfnQ... valid before login? True
  after login rotate -> new sid nvgoBD...
  attacker's pre-login sid still valid? False   <- fixation defeated

== 3 · EXPIRY ON TWO CLOCKS (idle + absolute) ==
  active within idle window   -> session alive? True
  idle 31 min (idle=30)       -> session alive? False   <- idle timeout
  active but 25h old (abs=24h)-> session alive? False   <- absolute timeout

== 4 · SIGNED COOKIE (stateless, tamper-evident, NOT secret) ==
  token: eyJ1c2VyIjoiYWxpY2UifQ...
  server reads payload: {"user":"alice"}   valid? True
  attacker edits payload to admin           valid? False   <- HMAC rejects it

== 5 · WHY THE ID MUST BE RANDOM (guessing) ==
  sequential IDs: 'session_1','session_2',... -> attacker enumerates in seconds
  256-bit CSPRNG id: 2^256 space -> guessing is infeasible
```

**Section 2** is the fixation defense made concrete: the attacker's pre-login ID is invalidated the instant the victim authenticates, because login issues a *new* ID. **Section 3** shows both timeout clocks firing independently. **Section 4** shows the stateless path — the payload is readable but the tampered `admin` version fails the HMAC check, exactly the JWT idea of [Lesson 6](../06-jwt-and-token-auth/). **Section 5** is why none of this matters without a CSPRNG ID.

## Use It

You won't write a session store — frameworks provide both strategies, and your job is to *configure the cookie correctly* and *choose the backend*. In Python, Starlette/FastAPI's `SessionMiddleware` gives you a signed cookie in one line, and the flags are the part that matters:

```python
from starlette.middleware.sessions import SessionMiddleware

app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ["SESSION_SECRET"],     # signs the cookie (Lesson 13 for the secret)
    https_only=True,                              # -> Secure
    same_site="lax",                              # -> SameSite=Lax
    max_age=14 * 24 * 3600,
)
# HttpOnly is set by default; the cookie is signed (itsdangerous), so it's tamper-evident, not secret
```

That's the stateless, signed-cookie model — no revocation, data visible to the client. For **server-side** sessions with real logout and revocation, back the session with **Redis**: store the data under the session ID with a TTL matching the timeout, and keep only the ID in the cookie (libraries like `starsessions`, Flask's server-side session extensions, or Django's default database/cache sessions do this). Django, for instance, ships server-side sessions and exposes `request.session.cycle_key()` — that's the ID rotation you built, and you call it on login.

Whichever backend, the non-negotiables are the same everywhere: **`HttpOnly` + `Secure` + `SameSite`** on the cookie (prefer the `__Host-` prefix), a **CSPRNG** session ID with **≥128 bits** of entropy, **rotation on login** (`cycle_key` / `regenerate`), **idle + absolute timeouts**, and **server-side invalidation on logout**. Get the cookie flags wrong and the strongest password and MFA in the world are bypassed by a stolen or ridden cookie — the session is the credential now, and [Lesson 10](../10-browser-trust-boundary-cors-csrf-xss/) is where you finish defending it against the browser's own willingness to send it cross-site.

## Think about it

1. A colleague stores the user's role directly in the cookie as `role=admin` (signed with HMAC so it can't be tampered) to "save a database lookup." Compare this to a server-side session for two scenarios: an admin gets demoted to a regular user, and the signing key leaks. What does each design do in each case?
2. Your session cookie has `Secure` and `SameSite=Lax` but not `HttpOnly`. A stored-XSS bug is found on your site. Walk through exactly what the attacker can now do that `HttpOnly` would have prevented — and what they can *still* do even with `HttpOnly` set.
3. Session fixation is defeated by rotating the ID at login. Precisely *why* does rotation break the attack — what does the attacker end up holding, and why is it worthless? Would rotating only at logout help?
4. You move from one server to three behind a load balancer, and users start getting randomly logged out. Diagnose the likely cause in terms of where the session data lives, and give two fixes with their tradeoffs.
5. Signed cookies (stateless) and server-side sessions both authenticate requests. Give a concrete product requirement that forces you to choose server-side sessions, and a different one that makes signed cookies the better fit.

## Key takeaways

- **HTTP is stateless, so a session is the server's memory of a logged-in client**, and the **session ID is a bearer token** — whoever holds it is treated as the user. The attacker's target shifts from the password to the session.
- **Keep session data server-side and give the client only an opaque, unguessable ID** (≥128 bits from a CSPRNG, encoding nothing). This prevents client tampering and — crucially — makes **logout and revocation instant**, because the server is consulted on every request.
- **The cookie attributes are the security, not preferences:** `HttpOnly` (XSS can't steal it), `Secure` (no sniffing over HTTP), `SameSite` (CSRF mitigation), and the `__Host-` prefix (locks it to the origin). A session cookie missing any of these is a bug.
- **Signed cookies are the stateless alternative** — the payload is made *tamper-proof* with an HMAC rather than kept secret (signed ≠ encrypted; never store secrets in one). No store and no lookup, but **no instant revocation** and the data is client-visible. This is the JWT idea of Lesson 6.
- **The lifecycle prevents attack classes:** **rotate the ID on login and every privilege change** (defeats session fixation), enforce **idle *and* absolute timeouts**, and make **logout a real server-side deletion** with the ability to revoke all of a user's sessions.
- **In production, back sessions with a shared store (Redis) whose TTL is the timeout**, keep only the ID in the cookie, and let the framework emit the cookie — but *you* own getting the flags, entropy, rotation, timeouts, and revocation right.

Next: [JWT & Token Auth from Scratch](../06-jwt-and-token-auth/) — the signed cookie you just built is a JWT in miniature; next you build the real thing, learn when a stateless token beats a server-side session (and when its lack of revocation bites), and dismantle the `alg:none` forgery that has broken real production systems.
