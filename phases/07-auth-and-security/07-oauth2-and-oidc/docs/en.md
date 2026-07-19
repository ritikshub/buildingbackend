# OAuth 2.0 & OIDC

> "Sign in with Google" and "let this app access your calendar" look like one feature, and conflating them is the most common security mistake in this whole area. OAuth 2.0 answers a question a password can't: *how do I let one app act on my behalf at another service without handing it my password?* That is **delegation**, not login. This lesson builds the Authorization Code flow with PKCE from scratch — the one flow you should actually use — and then shows how **OIDC** layers a real login system (an ID token, the JWT from Lesson 6) on top, so you finally see why the two are different and where each belongs.

**Type:** Build
**Languages:** Python
**Prerequisites:** [JWT & Token Auth from Scratch](../06-jwt-and-token-auth/) · [Sessions & Secure Cookies](../05-sessions-and-secure-cookies/)
**Time:** ~90 minutes

## The Problem

You're building a photo-printing app. To print someone's photos, you need to read them from their Google Photos. How does the user let you in?

The tempting answer — **ask for their Google password** — is a catastrophe wearing a login form. If the user types their Google password into your app, you now have a credential that does *everything* their Google account can do: read all their email, empty their Drive, change their password. You have it forever, or until they change it. There's no way to grant "read photos, nothing else," no way for them to revoke just your access, and no way for Google to tell your traffic from the user's. This is the **password anti-pattern**, and it's why "give us your password for site X" is a phishing red flag, not an integration.

What the user actually wants to grant is narrow and revocable: *this specific app may read (not delete) my photos, until I say stop, without ever seeing my password.* Delivering that needs a third party — Google itself — to stand between the user and your app: the user proves who they are **to Google** (never to you), tells Google exactly what to permit, and Google hands your app a **scoped, revocable token** instead of the password. That protocol is **OAuth 2.0** (RFC 6749), and the token is an **access token**.

Now the second half of the confusion. Because "connect your Google account" and "log in with Google" feel identical to a user, developers reach for OAuth to implement *login* — "Sign in with Google." But OAuth was designed to answer *"what is this app allowed to do?"* (authorization), not *"who is this user?"* (authentication). An access token says "the bearer may read photos"; it says nothing reliable about *who* the user is, and treating it as proof of identity is a real, exploited vulnerability. Login needs an extra layer that OAuth doesn't provide by itself — **OpenID Connect (OIDC)**, which adds an **identity** token. Keeping these two straight — *OAuth authorizes, OIDC authenticates* — is the single most valuable thing this lesson gives you.

## The Concept

### Four roles, one delegation

OAuth defines four roles, and the whole protocol is choreography among them. The valet-key analogy is apt: a valet key starts the car and opens the door but not the trunk or glovebox — delegated, limited access, without handing over your house keys.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 300" width="100%" style="max-width:880px" role="img" aria-label="The four OAuth roles. The resource owner (the user) owns the data and grants permission. The client (the app) wants access on the user's behalf. The authorization server (e.g. Google's login) authenticates the user, gets their consent, and issues tokens. The resource server (the API holding the data) accepts the access token and returns the data. The user authenticates only to the authorization server, never to the client, and the client receives a scoped token instead of the password.">
  <defs>
    <marker id="l7r-ar" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Four roles — the user authorizes; the client gets a scoped token, never the password</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2" font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="30" y="70" width="200" height="80" rx="11" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/>
    <rect x="30" y="200" width="200" height="72" rx="11" fill="#e0930f" fill-opacity="0.11" stroke="#e0930f"/>
    <rect x="360" y="200" width="200" height="72" rx="11" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    <rect x="680" y="200" width="200" height="72" rx="11" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="130" y="98" font-size="12" font-weight="700" text-anchor="middle" fill="#3553ff">RESOURCE OWNER</text>
    <text x="130" y="118" font-size="9.5" text-anchor="middle">the user — owns the data,</text>
    <text x="130" y="134" font-size="9.5" text-anchor="middle">grants permission</text>
    <text x="130" y="228" font-size="12" font-weight="700" text-anchor="middle" fill="#e0930f">CLIENT</text>
    <text x="130" y="248" font-size="9.5" text-anchor="middle">the app — wants access</text>
    <text x="130" y="263" font-size="9.5" text-anchor="middle">on the user's behalf</text>
    <text x="460" y="228" font-size="12" font-weight="700" text-anchor="middle" fill="#0fa07f">AUTHORIZATION SERVER</text>
    <text x="460" y="248" font-size="9.5" text-anchor="middle">authenticates the user,</text>
    <text x="460" y="263" font-size="9.5" text-anchor="middle">gets consent, issues tokens</text>
    <text x="780" y="228" font-size="12" font-weight="700" text-anchor="middle" fill="#7c5cff">RESOURCE SERVER</text>
    <text x="780" y="248" font-size="9.5" text-anchor="middle">the API holding the data —</text>
    <text x="780" y="263" font-size="9.5" text-anchor="middle">accepts the access token</text>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M130 150 L 130 196" marker-end="url(#l7r-ar)"/>
    <path d="M230 236 L 356 236" marker-end="url(#l7r-ar)"/>
    <path d="M560 236 L 676 236" marker-end="url(#l7r-ar)"/>
  </g>
  <text x="130" y="176" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="8" fill="currentColor" opacity="0.75" text-anchor="middle">authenticates</text>
  <text x="130" y="187" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="8" fill="currentColor" opacity="0.75" text-anchor="middle">+ consents ↓</text>
  <text x="293" y="228" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="8" fill="currentColor" opacity="0.75" text-anchor="middle">token</text>
  <text x="618" y="228" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="8" fill="currentColor" opacity="0.75" text-anchor="middle">bearer token</text>
</svg>
```

- The **resource owner** is the user who owns the data and can grant access.
- The **client** is your app, which wants to act on the user's behalf.
- The **authorization server** (Google's login/consent, an Auth0 tenant, Okta) authenticates the user, asks their consent, and issues tokens. Crucially, **the user's password only ever goes here** — never to the client.
- The **resource server** is the API holding the data (Google Photos API); it accepts the access token and returns data within the granted scope.

### Tokens and scopes

The authorization server issues two kinds of token (the same pair from [Lesson 6](../06-jwt-and-token-auth/)). An **access token** is a **bearer token** — whoever holds it gets in, so it's sent on every API call to the resource server and kept short-lived. A **refresh token** is long-lived and used only to get new access tokens. What the access token *permits* is defined by **scopes** — space-separated strings like `photos.read` or `calendar.write` that the user sees and consents to. Scopes are how "read my photos, nothing else" becomes concrete: the token carries `photos.read` and the resource server refuses anything more. Least privilege ([Lesson 1](../01-authn-authz-and-the-security-mindset/)), expressed as a consent screen.

### The Authorization Code flow with PKCE — the one to use

OAuth has several flows, but for essentially all modern apps the answer is the **Authorization Code flow with PKCE**. Its defining trick: the client never receives the token through the browser. Instead the browser carries a one-time **authorization code**, which the client then swaps for tokens over a direct, back-channel request — so the powerful token never appears in a URL, browser history, or the `Referer` header. Here is the whole dance:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 470" width="100%" style="max-width:880px" role="img" aria-label="The Authorization Code flow with PKCE, eight steps. Step 1: the user clicks connect in the client, which generates a code verifier and its SHA-256 hash, the code challenge. Step 2, front channel: the client redirects the browser to the authorization server's authorize endpoint with client_id, redirect_uri, scope, a random state, and the code_challenge. Step 3: the authorization server authenticates the user and shows a consent screen. Step 4, front channel: it redirects the browser back to the client with a one-time authorization code and the state. Step 5, back channel: the client posts the code plus the original code_verifier to the token endpoint. Step 6, back channel: the server checks that SHA-256 of the verifier equals the stored challenge and returns an access token and, for OIDC, an ID token. Step 7: the client calls the resource server with the access token as a bearer token. Step 8: the resource server validates the token and scope and returns the data. PKCE binds steps 1 and 5 so a stolen code is useless without the verifier; state binds steps 2 and 4 to stop CSRF.">
  <text x="450" y="22" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Authorization Code + PKCE — the token never travels through the browser</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor">
    <text x="255" y="46" font-size="9" text-anchor="middle" opacity="0.65">front channel = browser redirect (amber) · back channel = server-to-server (teal)</text>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g>
      <rect x="20" y="58" width="860" height="42" rx="8" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.3"/>
      <text x="34" y="76" font-size="10.5" font-weight="700" fill="currentColor">1 · User → Client</text>
      <text x="220" y="76" font-size="9.5" fill="currentColor">clicks "Connect Google Photos"</text>
      <text x="34" y="92" font-size="8.5" fill="#0fa07f">client generates code_verifier (random) and code_challenge = SHA256(verifier)</text>
    </g>
    <g>
      <rect x="20" y="106" width="860" height="30" rx="8" fill="#e0930f" fill-opacity="0.11" stroke="#e0930f" stroke-width="1.3"/>
      <text x="34" y="125" font-size="10.5" font-weight="700" fill="#e0930f">2 · Client → Browser → Auth server</text>
      <text x="330" y="125" font-size="9" fill="currentColor">redirect /authorize?client_id&amp;redirect_uri&amp;scope&amp;<tspan font-weight="700">state</tspan>&amp;<tspan font-weight="700">code_challenge</tspan></text>
    </g>
    <g>
      <rect x="20" y="142" width="860" height="30" rx="8" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f" stroke-opacity="0.6" stroke-width="1.3"/>
      <text x="34" y="161" font-size="10.5" font-weight="700" fill="#0fa07f">3 · Auth server ↔ User</text>
      <text x="330" y="161" font-size="9" fill="currentColor">authenticate (password + MFA) and show consent: "App wants: read your photos"</text>
    </g>
    <g>
      <rect x="20" y="178" width="860" height="30" rx="8" fill="#e0930f" fill-opacity="0.11" stroke="#e0930f" stroke-width="1.3"/>
      <text x="34" y="197" font-size="10.5" font-weight="700" fill="#e0930f">4 · Auth server → Browser → Client</text>
      <text x="330" y="197" font-size="9" fill="currentColor">redirect back: ?<tspan font-weight="700">code</tspan>=one-time&amp;<tspan font-weight="700">state</tspan>  — a CODE, not a token</text>
    </g>
    <g>
      <rect x="20" y="214" width="860" height="30" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.3"/>
      <text x="34" y="233" font-size="10.5" font-weight="700" fill="#0fa07f">5 · Client → Auth server (back channel)</text>
      <text x="360" y="233" font-size="9" fill="currentColor">POST /token: code + <tspan font-weight="700">code_verifier</tspan> + client credentials</text>
    </g>
    <g>
      <rect x="20" y="250" width="860" height="30" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.3"/>
      <text x="34" y="269" font-size="10.5" font-weight="700" fill="#0fa07f">6 · Auth server → Client (back channel)</text>
      <text x="360" y="269" font-size="9" fill="currentColor">verify SHA256(verifier)==challenge → <tspan font-weight="700">access_token</tspan> (+ id_token for OIDC)</text>
    </g>
    <g>
      <rect x="20" y="286" width="860" height="30" rx="8" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.3"/>
      <text x="34" y="305" font-size="10.5" font-weight="700" fill="#7c5cff">7 · Client → Resource server</text>
      <text x="330" y="305" font-size="9" fill="currentColor">GET /photos   Authorization: Bearer access_token</text>
    </g>
    <g>
      <rect x="20" y="322" width="860" height="30" rx="8" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.3"/>
      <text x="34" y="341" font-size="10.5" font-weight="700" fill="#7c5cff">8 · Resource server → Client</text>
      <text x="330" y="341" font-size="9" fill="currentColor">validate token + scope (photos.read) → returns the photos</text>
    </g>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor">
    <rect x="20" y="366" width="425" height="86" rx="9" fill="#0fa07f" fill-opacity="0.06" stroke="#0fa07f" stroke-opacity="0.6"/>
    <text x="34" y="386" font-size="10" font-weight="700" fill="#0fa07f">PKCE binds steps 1 ↔ 5–6</text>
    <text x="34" y="404" font-size="9">an attacker who steals the code (step 4) can't</text>
    <text x="34" y="418" font-size="9">use it: step 6 demands the verifier, which never</text>
    <text x="34" y="432" font-size="9">left the client. The challenge proves the redeemer</text>
    <text x="34" y="446" font-size="9">is the same app that started the flow.</text>
    <rect x="455" y="366" width="425" height="86" rx="9" fill="#e0930f" fill-opacity="0.06" stroke="#e0930f" stroke-opacity="0.6"/>
    <text x="469" y="386" font-size="10" font-weight="700" fill="#e0930f">state binds steps 2 ↔ 4</text>
    <text x="469" y="404" font-size="9">the client generates a random `state`, stores it,</text>
    <text x="469" y="418" font-size="9">and checks it on return. A forged callback with</text>
    <text x="469" y="432" font-size="9">the wrong (or missing) state is rejected —</text>
    <text x="469" y="446" font-size="9">this is CSRF protection for the redirect.</text>
  </g>
</svg>
```

Two of those steps are the security, and they're worth stating on their own.

### PKCE: proof that the redeemer started the flow

**PKCE** (Proof Key for Code Exchange, RFC 7636, say "pixy") closes a gap in the code flow. The authorization code comes back through the browser (step 4), where it can be intercepted — a malicious app registered for the same redirect URI on a phone, a leaked `Referer`, a logged URL. Without protection, a stolen code could be exchanged for tokens by the thief. PKCE stops this: at the start, the client invents a random secret, the **code verifier**, and sends only its SHA-256 hash, the **code challenge**, in the authorization request. When it later redeems the code, it must present the *original verifier*, and the server checks that its hash matches the stored challenge. A stolen code is useless without the verifier — which never left the client. PKCE began as a fix for mobile/SPA "public" clients that can't keep a secret, but it's now recommended for **every** client, confidential ones included.

### state: CSRF protection for the redirect

The **`state`** parameter is a random value the client generates, stashes in the user's session, includes in the authorization request (step 2), and verifies when the callback returns (step 4). If they don't match — or `state` is missing — the client rejects the callback. This prevents a **CSRF-style login attack** where an attacker tricks your browser into completing *their* authorization flow, potentially connecting your account to the attacker's resources. `state` is not optional, and OIDC adds a companion, `nonce`, that binds the resulting ID token to this specific request.

### The other grant types (and the ones to avoid)

The Authorization Code + PKCE flow covers web apps, SPAs, and mobile. A few others exist for specific cases:

- **Client Credentials** — no user at all; a service authenticates *as itself* to call another service (machine-to-machine). The service's own credentials get an access token. This is the OAuth answer to service-to-service auth.
- **Device Authorization** (device code) — for inputs-constrained devices (a TV, a CLI): the device shows a code and URL, you approve on your phone.
- **Refresh Token** — exchange a refresh token for a fresh access token.
- **Avoid: Implicit** — an old flow that returned the token directly in the URL fragment (no code exchange). PKCE + code flow replaced it; don't use it. **Avoid: Resource Owner Password Credentials** — the client collects the user's password directly, which is the anti-pattern OAuth exists to kill. Both are effectively deprecated in **OAuth 2.1**, which folds in PKCE-by-default and drops these.

### OAuth authorizes; OIDC authenticates

Now the distinction that trips everyone. An **access token proves permission, not identity.** It means "the bearer may read photos" — it is opaque to the client (often the client can't even read it), it may not identify the user at all, and it can be a token issued to a *different* app that happens to have leaked. So "the app got a valid access token, therefore this is user Alice" is a real vulnerability (the **"confused deputy" / access-token-as-login** bug). To do **login**, you need something that authoritatively answers *who the user is* — and that's **OpenID Connect**.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 322" width="100%" style="max-width:880px" role="img" aria-label="OAuth versus OIDC tokens. The access token is for the resource server, grants access to scopes, is often opaque to the client, answers what you can do, and its audience is the API — it is authorization. The ID token, added by OIDC, is for the client, is always a JWT, contains identity claims like sub, name, email, and nonce, answers who you are, and its audience is the client — it is authentication. Using an access token as proof of identity is a classic vulnerability; the ID token is the login artifact.">
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Two tokens, two jobs — don't use one for the other's job</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="20" y="46" width="424" height="230" rx="12" fill="#7c5cff" fill-opacity="0.07" stroke="#7c5cff" stroke-opacity="0.85"/>
    <rect x="460" y="46" width="424" height="230" rx="12" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f" stroke-opacity="0.85"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="232" y="72" font-size="12.5" font-weight="700" text-anchor="middle" fill="#7c5cff">ACCESS TOKEN — OAuth</text>
    <text x="232" y="90" font-size="10" text-anchor="middle" font-weight="700">"what may the bearer DO?"</text>
    <text x="232" y="122" font-size="9.5" text-anchor="middle">consumed by: the RESOURCE SERVER</text>
    <text x="232" y="142" font-size="9.5" text-anchor="middle">grants: scopes (photos.read)</text>
    <text x="232" y="162" font-size="9.5" text-anchor="middle">format: opaque OR JWT (client shouldn't</text>
    <text x="232" y="176" font-size="9.5" text-anchor="middle">parse it — it's not for the client)</text>
    <text x="232" y="196" font-size="9.5" text-anchor="middle">audience (aud): the API</text>
    <text x="232" y="228" font-size="10" text-anchor="middle" fill="#d64545">Using it as proof of WHO the user is</text>
    <text x="232" y="244" font-size="10" text-anchor="middle" fill="#d64545">is a classic vulnerability.</text>

    <text x="672" y="72" font-size="12.5" font-weight="700" text-anchor="middle" fill="#0fa07f">ID TOKEN — OIDC</text>
    <text x="672" y="90" font-size="10" text-anchor="middle" font-weight="700">"WHO is the user?"</text>
    <text x="672" y="122" font-size="9.5" text-anchor="middle">consumed by: the CLIENT (your app)</text>
    <text x="672" y="142" font-size="9.5" text-anchor="middle">always a JWT (Lesson 6) you verify</text>
    <text x="672" y="162" font-size="9.5" text-anchor="middle">claims: sub, name, email, nonce, exp</text>
    <text x="672" y="182" font-size="9.5" text-anchor="middle">audience (aud): YOUR client_id</text>
    <text x="672" y="202" font-size="9.5" text-anchor="middle">verify: signature (JWKS), iss, aud, nonce</text>
    <text x="672" y="234" font-size="10" text-anchor="middle" fill="#0fa07f">This is the login artifact —</text>
    <text x="672" y="250" font-size="10" text-anchor="middle" fill="#0fa07f">"Sign in with Google" runs on it.</text>
  </g>
  <text x="450" y="300" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">OIDC is a thin identity layer ON TOP of OAuth: same flow, plus an ID token and a standard userinfo endpoint.</text>
</svg>
```

**OIDC** (OpenID Connect) is a thin standard layer on top of OAuth 2.0. You run the *same* Authorization Code + PKCE flow, add the scope `openid`, and the authorization server additionally returns an **ID token**: a **JWT** (exactly the [Lesson 6](../06-jwt-and-token-auth/) artifact) whose claims identify the user — `sub` (their stable ID), `name`, `email`, `iss`, `aud` (your client ID), `exp`, and the `nonce` you sent. Your app **verifies that JWT** (signature via the issuer's JWKS, plus `iss`/`aud`/`exp`/`nonce`) and now *knows who logged in*. OIDC also standardizes a **discovery** document (`/.well-known/openid-configuration`) and a **userinfo** endpoint. So: **OAuth gets you a token to call an API on the user's behalf; OIDC gets you a verified answer to "who is this user," which is what login means.** "Sign in with Google" is OIDC; "let this app post to your calendar" is OAuth.

## Build It

You should never build a production authorization server — but building a miniature one is the fastest way to *see* why PKCE and `state` work. Standard library only, an in-process simulation of the four roles running the Authorization Code + PKCE flow, plus the two attacks it defeats.

The heart of PKCE is three lines — a random verifier, its hash as the challenge, and the check at redemption:

```python
verifier = secrets.token_urlsafe(48)                         # the client's secret, never sent
challenge = b64url(hashlib.sha256(verifier.encode()).digest())  # only this is sent (S256)
# ... later, at the token endpoint, the server checks:
assert b64url(hashlib.sha256(presented_verifier.encode()).digest()) == stored_challenge
```

The authorization server issues a one-time code bound to the client, redirect URI, scope, and challenge; the token endpoint only releases tokens if the presented verifier hashes to that challenge:

```python
def authorize(self, client_id, redirect_uri, scope, state, code_challenge) -> str:
    # (user authenticates + consents here — simulated)
    code = secrets.token_urlsafe(24)
    self._codes[code] = dict(client_id=client_id, redirect_uri=redirect_uri,
                             scope=scope, challenge=code_challenge, used=False)
    return code                                              # comes back via the browser redirect

def token(self, code, code_verifier, client_id) -> dict:
    c = self._codes.get(code)
    if not c or c["used"] or c["client_id"] != client_id:
        raise OAuthError("invalid_grant")
    c["used"] = True                                        # authorization codes are single-use
    if b64url(sha256(code_verifier)) != c["challenge"]:     # PKCE: the whole point
        raise OAuthError("invalid_grant: PKCE mismatch")
    return {"access_token": self._issue_access(c["scope"]),
            "id_token": self._issue_id_token(sub="u_alice")}   # id_token only if openid scope
```

The full simulation — client, authorization server, resource server; the happy path; a stolen-code attack without the verifier; a tampered `state`; and access to the resource server with the scoped token — is in [`code/oauth_pkce.py`](code/oauth_pkce.py). Run it:

```console
$ python3 oauth_pkce.py
== 1 · CLIENT STARTS THE FLOW (PKCE) ==
  code_verifier  (secret, stays in client): 7Q2f...  (64 chars)
  code_challenge (sent in the request)    : k9Xr...  = SHA256(verifier)
  state          (CSRF protection)        : b3d1...

== 2 · AUTH SERVER: user consents -> one-time authorization code ==
  redirect back -> /callback?code=Yh8p...&state=b3d1...
  state matches what the client stored? True

== 3 · CLIENT EXCHANGES CODE + VERIFIER (back channel) ==
  POST /token (code + code_verifier)
  -> access_token: at_79gSC... (scope: openid photos.read)
  -> id_token (OIDC JWT): eyJhbGci...  sub=u_alice  aud=photo-print-app

== 4 · STOLEN CODE WITHOUT THE VERIFIER (PKCE defeats it) ==
  attacker replays the code with a guessed verifier -> invalid_grant: PKCE mismatch  ✓

== 5 · FORGED CALLBACK WITH WRONG state (CSRF defeated) ==
  callback state 'evil' vs stored 'sbiu...' -> rejected  ✓

== 6 · CALL THE RESOURCE SERVER WITH THE ACCESS TOKEN ==
  GET /photos  Authorization: Bearer at_79gSC...
  -> 200  ['beach.jpg', 'cat.png']   (scope photos.read allowed)
  GET /photos (delete)  -> 403 insufficient_scope   (photos.read can't write)
```
(The token/code/verifier values are random per run; the True/False results and status codes are stable.)

**Sections 1–3** are the flow: the verifier stays in the client, only its hash is sent, the code comes back through the browser, and tokens are released only for the back-channel exchange. **Section 4** is PKCE earning its place — the stolen code fails because the attacker can't produce the verifier. **Section 5** is `state` stopping a forged callback. **Section 6** shows scopes enforced at the resource server: the same token that reads photos can't delete them.

## Use It

The headline rule: **do not build an authorization server.** OAuth/OIDC are full of subtle security requirements (redirect-URI validation, token binding, replay, key rotation), and getting one wrong is a breach. Use a provider — **Auth0, Okta, Keycloak, Google, Microsoft Entra, AWS Cognito** — or, if you must self-host, a mature server like Keycloak. Your job is to be a correct *client*, and a good library does the heavy lifting. In Python, **Authlib** is the standard:

```python
from authlib.integrations.starlette_client import OAuth

oauth = OAuth()
oauth.register(
    name="google",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",  # OIDC discovery
    client_id=os.environ["GOOGLE_CLIENT_ID"],
    client_secret=os.environ["GOOGLE_CLIENT_SECRET"],   # a secret — Lesson 13
    client_kwargs={"scope": "openid email profile"},    # 'openid' => this is OIDC login
)

# 1) start login: Authlib generates state + PKCE + nonce for you
async def login(request):
    return await oauth.google.authorize_redirect(request, redirect_uri)

# 2) callback: it validates state, exchanges the code (with PKCE), and verifies the ID token
async def callback(request):
    token = await oauth.google.authorize_access_token(request)   # checks state, does PKCE exchange
    userinfo = token["userinfo"]     # ID-token claims, signature/iss/aud/nonce already verified
    # userinfo['sub'] is the stable user id — THIS is who logged in
```

Everything that made the flow safe — `state`, PKCE, the code exchange, ID-token signature/`iss`/`aud`/`nonce` verification via the discovery document's JWKS — is handled by `authorize_redirect` / `authorize_access_token`. That's the point of using the library: those are exactly the checks that are easy to skip and catastrophic to skip. The rules to carry out: request the **narrowest scopes** you need; treat the **access token as opaque** (don't parse it to identify the user — use the ID token or the userinfo endpoint); **always verify the ID token** (`aud` must be your client ID, `iss` the expected issuer, plus `exp` and `nonce`); register **exact redirect URIs** and prefer the **Authorization Code + PKCE** flow everywhere (it's the default in OAuth 2.1). And keep the mental model sharp: reach for OAuth when your app needs to *call an API on the user's behalf*, and for OIDC when your app needs to *know who the user is* — they share a flow, but they are not the same job.

## Think about it

1. A tutorial tells you to implement "Login with Google" by taking the **access token** Google returns and looking up the user's profile with it, then logging them in as that user. Describe the vulnerability precisely (hint: where did the access token come from, and what is its audience?), and what you should use instead.
2. PKCE was designed for mobile and single-page apps that "can't keep a secret," yet the guidance is now to use it for confidential server-side clients too. Give a concrete attack on the plain authorization-code flow (no PKCE) that PKCE stops even when the client *does* have a secret.
3. Explain what the `state` parameter defends against by describing an attack that succeeds when a client forgets to check it. Why is `state` a client-side responsibility rather than something the authorization server enforces?
4. Your app only needs to read a user's calendar, but the OAuth consent screen you configured requests `calendar.read calendar.write contacts.read`. Name two distinct things that go wrong because of the over-broad scope request — one security, one product.
5. When is it correct to use the Client Credentials grant, and why would using it be wrong for the photo-printing app in *The Problem*? What does "there is no resource owner" change about the flow?

## Key takeaways

- **OAuth 2.0 is delegation, not login.** It exists to let a client act on a user's behalf at another service **without the user's password** — the user authenticates only to the authorization server, which issues a **scoped, revocable access token** to the client. The alternative, sharing the password, is the anti-pattern OAuth kills.
- **Four roles:** the resource owner (user), the client (app), the authorization server (issues tokens after auth + consent), and the resource server (holds the API). **Scopes** are least privilege made into a consent screen.
- **Use the Authorization Code flow with PKCE** for essentially everything. The token comes back via a one-time **code** exchanged over the back channel, never through the browser. **PKCE** (a verifier the client keeps, a challenge it sends) makes a stolen code useless; **`state`** protects the redirect from CSRF. Avoid the Implicit and Password grants (gone in OAuth 2.1).
- **An access token proves permission, not identity.** Treating "we got a valid access token" as "we know who the user is" is a real vulnerability — the token is for the resource server and may not even identify the user.
- **OIDC adds authentication on top of OAuth**: the same flow plus an **ID token** — a JWT (Lesson 6) with identity claims (`sub`, `email`, `aud`, `nonce`) that your app **verifies** (signature via JWKS, `iss`, `aud`, `exp`, `nonce`). "Sign in with Google" is OIDC; "access my Google data" is OAuth.
- **Don't build an authorization server — be a correct client.** Use a provider and a vetted library (Authlib) so `state`, PKCE, the code exchange, and ID-token verification are done right; request minimal scopes, treat access tokens as opaque, and always verify the ID token's `aud`/`iss`.

Next: [API Keys, HMAC Signing & Webhooks](../08-api-keys-hmac-and-webhooks/) — OAuth handles a user delegating to an app; next you handle the other half of machine identity — long-lived API keys, signing requests with HMAC so they can't be tampered or replayed, and verifying the webhooks other services send you.
