# JWT & Token Auth from Scratch

> The signed cookie you built in Lesson 5 was a JWT in miniature. The real thing is that same idea — a payload made tamper-proof by a signature — standardized into a compact, self-contained token that any service holding the key can verify with no database lookup, which is exactly what a world of many services needs. This lesson builds a JWT byte by byte, then spends its second half on the part that actually matters: **verification**, where getting the algorithm check wrong produced two forgeries — `alg:none` and HS/RS key confusion — that have unlocked real production systems.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Cryptographic Building Blocks](../02-cryptographic-building-blocks/) · [Sessions & Secure Cookies](../05-sessions-and-secure-cookies/)
**Time:** ~85 minutes

## The Problem

Your app grew from one server into a dozen services — an API gateway, an orders service, a payments service, a notifications worker. A request authenticated at the gateway now has to prove *who it's for* to each service it touches. The Lesson 5 answer, a server-side session, strains here: every service, on every request, would have to call the central session store to resolve the session ID into an identity. That's a network hop and a shared dependency on the hot path of every call, and if the store is slow or down, the whole fleet is down.

What you want is a token the services can verify **themselves**, with no callback — a token that *carries* the identity and *proves* it's authentic. The naive attempts are the same three from Lesson 1, now between services:

- **Base64 the identity** (`{"user":"alice","role":"admin"}`) and trust it. Forgeable by anyone — this is the very first bug in this phase, and it does not improve with distance.
- **Encrypt the identity.** Now the services can't read the claims without the decryption key, encryption is heavier than you need, and you didn't actually want secrecy — the claims aren't secret, you just need them *unforgeable*.
- **Sign the identity.** The gateway signs a small JSON document; every service verifies the signature and trusts the claims inside. No shared store, no callback, and the token is self-contained. This is a **JWT**.

A **JWT** (JSON Web Token, RFC 7519) is a signed — sometimes encrypted — JSON claim set, compact enough to sit in an HTTP header. It is the backbone of modern service-to-service and API auth, and the token format OAuth and OIDC hand you in [Lesson 7](../07-oauth2-and-oidc/). But here is the thing that makes this lesson different from the last: **a JWT's entire security is in how you verify it**, and the format's flexibility created two forgeries that broke real systems. A verifier that trusts the token to tell it *how* to check the token can be talked into not checking it at all. So you'll build the happy path in fifteen lines, and then spend real time on the traps — because "we use JWTs" is not a security property; "we verify JWTs correctly" is.

## The Concept

### A JWT is three Base64url parts: header, payload, signature

The most common JWT is a **JWS** (JSON Web Signature) — a signed token in three parts joined by dots: `header.payload.signature`. The header and payload are JSON objects, each **Base64url-encoded** (URL-safe Base64, no padding); the signature is computed over the first two:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 360" width="100%" style="max-width:880px" role="img" aria-label="Anatomy of a JWT. It is three Base64url parts joined by dots. The first part decodes to the header JSON, which names the algorithm HS256 and type JWT. The second decodes to the payload JSON of claims: sub alice, role user, exp timestamp. The third is the signature: HMAC-SHA256 of the header-dot-payload string using the secret key. The header and payload are readable by anyone — encoding is not encryption — while the signature makes the whole thing tamper-proof.">
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">A JWT is header . payload . signature — the first two are readable, the third makes it unforgeable</text>
  <text x="450" y="58" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="12" fill="currentColor"><tspan fill="#7c5cff">eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9</tspan><tspan fill="currentColor">.</tspan><tspan fill="#0fa07f">eyJzdWIiOiJhbGljZSIsInJvbGUiOiJ1c2VyIiwiZXhwIjoxNzAwMDAwOTAwfQ</tspan><tspan fill="currentColor">.</tspan><tspan fill="#e0930f">3vJ8...Kf9</tspan></text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-linejoin="round" stroke-width="1.7">
      <rect x="30" y="92" width="250" height="120" rx="10" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff"/>
      <rect x="325" y="92" width="290" height="120" rx="10" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f"/>
      <rect x="660" y="92" width="210" height="120" rx="10" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f"/>
    </g>
    <text x="155" y="112" font-size="11" font-weight="700" text-anchor="middle" fill="#7c5cff">① HEADER</text>
    <text x="45" y="134" font-size="10" fill="currentColor">{</text>
    <text x="55" y="150" font-size="10" fill="currentColor">"alg": "HS256",</text>
    <text x="55" y="166" font-size="10" fill="currentColor">"typ": "JWT"</text>
    <text x="45" y="182" font-size="10" fill="currentColor">}</text>
    <text x="155" y="204" font-size="8" text-anchor="middle" opacity="0.7">how it was signed</text>

    <text x="470" y="112" font-size="11" font-weight="700" text-anchor="middle" fill="#0fa07f">② PAYLOAD (claims)</text>
    <text x="340" y="134" font-size="10" fill="currentColor">{ "sub": "alice",</text>
    <text x="350" y="150" font-size="10" fill="currentColor">"role": "user",</text>
    <text x="350" y="166" font-size="10" fill="currentColor">"exp": 1700000900,</text>
    <text x="350" y="182" font-size="10" fill="currentColor">"iss": "acme-gw" }</text>
    <text x="470" y="204" font-size="8" text-anchor="middle" opacity="0.7">who + what, readable by anyone</text>

    <text x="765" y="112" font-size="11" font-weight="700" text-anchor="middle" fill="#e0930f">③ SIGNATURE</text>
    <text x="765" y="140" font-size="9" text-anchor="middle" fill="currentColor">HMAC-SHA256(</text>
    <text x="765" y="156" font-size="9" text-anchor="middle" fill="currentColor">header "." payload,</text>
    <text x="765" y="172" font-size="9" text-anchor="middle" fill="currentColor">secret )</text>
    <text x="765" y="204" font-size="8" text-anchor="middle" opacity="0.7">only the key-holder can make it</text>
  </g>
  <text x="450" y="248" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="11" font-weight="700" fill="#d64545">Base64url is ENCODING, not encryption — never put a secret (password, card, PII) in the payload.</text>
  <text x="450" y="286" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Anyone can read the claims; nobody without the key can change them, because editing the payload breaks the signature.</text>
  <text x="450" y="312" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">The signature is computed over the exact Base64url text of header + "." + payload — so a single changed character invalidates it.</text>
  <text x="450" y="338" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.72">(A token whose payload is also encrypted is a JWE — JSON Web Encryption — a separate, less common format.)</text>
</svg>
```

The single most misunderstood fact about JWTs is right there in the diagram: **the payload is not secret.** Base64url is encoding ([Lesson 2](../02-cryptographic-building-blocks/)) — anyone with the token pastes it into a decoder and reads every claim. The signature guarantees *integrity and authenticity* (nobody changed it, it came from the key-holder), not *confidentiality*. So never put a password, card number, or anything you wouldn't hand the user in a JWT. If you truly need the claims hidden, that's a **JWE** (encrypted), which is a different and less common tool.

### Claims: the standard ones carry the security

The payload is a set of **claims**. Some are **registered** (RFC 7519) with defined meanings, and several of them are load-bearing for security, not just metadata:

- **`exp`** (expiration) — the token is invalid after this time. *The* most important claim, because a stateless token can't be revoked, so a short lifetime is your main damage-control (below).
- **`iat`** (issued-at), **`nbf`** (not-before) — when it was minted and when it becomes valid.
- **`iss`** (issuer), **`aud`** (audience) — who created the token and who it's *for*. Verifying `aud` stops a token minted for service A from being replayed against service B.
- **`sub`** (subject) — the principal the token is about (the user ID).
- **`jti`** (JWT ID) — a unique ID, used to blocklist or de-duplicate a specific token.

Everything else — `role`, `tier`, `email` — is a **custom claim**. The discipline: a claim is only trustworthy *after* you verify the signature and the standard claims (`exp`, `aud`, `iss`). An unverified claim is just attacker-supplied text.

### Signing: one shared secret, or a key pair

How the signature is made determines who can verify — and who can *forge*:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 340" width="100%" style="max-width:880px" role="img" aria-label="Two JWT signing families. Left, HS256 symmetric: the issuer and every verifier share one secret key; anyone who can verify can also mint tokens, so it fits within a single trust boundary. Right, RS256 or ES256 asymmetric: the issuer signs with a private key that only it holds, and any number of services verify with the public key, fetched from a JWKS endpoint, so verifiers cannot forge tokens — which is what lets third parties and separate services trust the issuer.">
  <defs>
    <marker id="l6s-ar" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">How it's signed decides who can verify — and who can forge</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="44" width="424" height="278" rx="12" fill="#3553ff" fill-opacity="0.06" stroke="#3553ff" stroke-opacity="0.8"/>
    <rect x="460" y="44" width="424" height="278" rx="12" fill="#0fa07f" fill-opacity="0.06" stroke="#0fa07f" stroke-opacity="0.8"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="228" y="70" font-size="12.5" font-weight="700" text-anchor="middle" fill="#3553ff">HS256 — one shared secret</text>
    <text x="672" y="70" font-size="12.5" font-weight="700" text-anchor="middle" fill="#0fa07f">RS256 / ES256 — key pair</text>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor" font-size="9.5">
    <text x="228" y="104" text-anchor="middle" font-weight="700">issuer + every verifier hold the SAME key</text>
    <text x="228" y="150" text-anchor="middle">🔑 sign with secret  ·  🔑 verify with secret</text>
    <text x="228" y="196" text-anchor="middle" opacity="0.85">Anyone who can VERIFY can also MINT.</text>
    <text x="228" y="216" text-anchor="middle" opacity="0.85">Fine inside one trust boundary</text>
    <text x="228" y="232" text-anchor="middle" opacity="0.85">(one app, your own services).</text>
    <text x="228" y="272" text-anchor="middle" opacity="0.7">Fast, simple. Every verifier is a</text>
    <text x="228" y="288" text-anchor="middle" opacity="0.7">place the signing secret can leak.</text>

    <text x="672" y="104" text-anchor="middle" font-weight="700">issuer holds PRIVATE; world holds PUBLIC</text>
    <text x="672" y="150" text-anchor="middle">🔒 sign with private  ·  🔓 verify with public</text>
    <text x="672" y="196" text-anchor="middle" opacity="0.85">Verifiers CANNOT mint tokens.</text>
    <text x="672" y="216" text-anchor="middle" opacity="0.85">Public keys published at a</text>
    <text x="672" y="232" text-anchor="middle" opacity="0.85">JWKS URL (/.well-known/jwks.json).</text>
    <text x="672" y="272" text-anchor="middle" opacity="0.7">The right choice across services and</text>
    <text x="672" y="288" text-anchor="middle" opacity="0.7">for third parties — this is how OIDC works.</text>
  </g>
</svg>
```

**HS256** (HMAC-SHA256) uses one **shared secret** — the issuer and every verifier hold the same key. Simple and fast, but *anyone who can verify can also forge*, so it only makes sense inside a single trust boundary, and every service that verifies is another place the secret can leak. **RS256/ES256** (RSA / ECDSA signatures, [Lesson 2](../02-cryptographic-building-blocks/)) use a **key pair**: the issuer signs with a private key it alone holds, and everyone else verifies with the *public* key — so verifiers can check tokens but can't mint them. The public keys are published at a **JWKS** endpoint (JSON Web Key Set, usually `/.well-known/jwks.json`), which also lets the issuer rotate keys without redeploying every verifier. This asymmetric model is what makes cross-organization auth possible and is the foundation of OIDC ([Lesson 7](../07-oauth2-and-oidc/)).

### Verification is the whole security — and here are the two forgeries

Minting a JWT is easy. *Verifying* one safely is the entire job, and the checks must happen in the right way. A correct verifier: decides the acceptable algorithm(s) itself, recomputes the signature over `header.payload` and compares it in **constant time**, then checks `exp`/`nbf`, `iss`, and `aud`. The catastrophic mistakes come from letting the **token** influence *how* it's verified — and two of them are famous because they hit real libraries and real companies.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 386" width="100%" style="max-width:880px" role="img" aria-label="The two classic JWT forgeries. Forgery A, alg none: the attacker sets the header algorithm to none and sends an empty signature; a naive verifier that reads the algorithm from the token skips the signature check and accepts the forged claims. Forgery B, HS/RS key confusion: the server expects RS256 and verifies with its RSA public key, which is public; the attacker crafts a token with algorithm HS256 and signs it using that public key as the HMAC secret; a naive verifier reads HS256 from the header and uses the public key as an HMAC key, so the signature matches and the forgery is accepted. The fix for both is the same: the server pins the allowed algorithm and never lets the token choose.">
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Two forgeries that broke real systems — both from trusting the token's own `alg`</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="20" y="44" width="860" height="128" rx="11" fill="#d64545" fill-opacity="0.06" stroke="#d64545" stroke-opacity="0.6"/>
    <text x="36" y="66" font-size="12" font-weight="700" fill="#d64545">FORGERY A · alg:none</text>
    <text x="36" y="90" font-size="10" fill="currentColor">attacker sends header {"alg":"none"} · payload {"role":"admin"} · signature = (empty)</text>
    <text x="36" y="112" font-size="10" fill="currentColor">naive verifier: "the header says alg=none, so there's nothing to check" → ACCEPTS the forged admin token ✗</text>
    <text x="36" y="140" font-size="10" fill="#0fa07f">fix: the server only accepts alg ∈ {HS256}; "none" is never an allowed algorithm → REJECTED</text>
    <text x="36" y="160" font-size="9" fill="currentColor" opacity="0.7">(the RFC even defines an "unsecured JWT" with alg=none — which is exactly why a verifier must refuse it)</text>

    <rect x="20" y="184" width="860" height="150" rx="11" fill="#e0930f" fill-opacity="0.06" stroke="#e0930f" stroke-opacity="0.6"/>
    <text x="36" y="206" font-size="12" font-weight="700" fill="#e0930f">FORGERY B · HS/RS key confusion</text>
    <text x="36" y="230" font-size="10" fill="currentColor">server expects RS256 and verifies with its RSA PUBLIC key P — and P is public, by design</text>
    <text x="36" y="252" font-size="10" fill="currentColor">attacker crafts header {"alg":"HS256"} and signs with HMAC using P (the public key) as the secret</text>
    <text x="36" y="274" font-size="10" fill="currentColor">naive verifier: reads alg=HS256 from the header, runs HMAC-verify with key P → signature matches → ACCEPTS ✗</text>
    <text x="36" y="302" font-size="10" fill="#0fa07f">fix: the server pins alg=RS256; a token claiming HS256 is rejected before any key is chosen → REJECTED</text>
    <text x="36" y="322" font-size="9" fill="currentColor" opacity="0.7">the trap: the verifier let the token pick both the algorithm AND, implicitly, how to interpret the key</text>
  </g>
  <text x="450" y="360" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="11" font-weight="700" fill="currentColor">The one rule that kills both: NEVER trust the `alg` in the token. The server decides the algorithm and key.</text>
  <text x="450" y="380" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.75">Corollary: a verifier must also reject a valid signature if the token's alg isn't in its allow-list, even when the math checks out.</text>
</svg>
```

Both forgeries share one root cause: **the verifier let the token tell it how to verify the token.** The token's `alg` header is attacker-controlled input, so a verifier that reads `alg` and does whatever it says can be pointed at "none" (skip the check) or at "HS256 when I expected RS256" (reinterpret the public key as an HMAC secret). The fix is one rule with no exceptions: **the server decides the algorithm out of band and pins it; the `alg` header is used only to confirm it matches the expectation, never to choose the behavior.** Every reputable library now forces you to pass the expected algorithm(s) explicitly for exactly this reason.

### Expiry and the revocation problem

The property that makes JWTs scale — no server lookup — is also their sharpest limitation: **you can't easily revoke one.** A server-side session dies the instant you delete it from the store (Lesson 5); a stateless JWT is trusted on its signature alone, so a stolen token stays valid until it **expires**, no matter what. That makes `exp` the load-bearing control, and it drives the standard **two-token pattern**:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 268" width="100%" style="max-width:880px" role="img" aria-label="Access and refresh token pattern. A short-lived access token, minutes long, is a stateless JWT sent on every request and never stored server-side. A long-lived refresh token, days or weeks, is opaque, stored server-side, and revocable; it is used only against the auth server to mint a new access token, and it rotates on each use. This bounds the damage of a stolen access token to minutes while keeping instant revocation via the refresh token.">
  <defs>
    <marker id="l6r-ar" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Two tokens: short stateless access + long revocable refresh</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="30" y="54" width="380" height="150" rx="11" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f"/>
      <rect x="490" y="54" width="380" height="150" rx="11" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff"/>
    </g>
    <text x="220" y="78" font-size="12" font-weight="700" text-anchor="middle" fill="#0fa07f">ACCESS TOKEN</text>
    <text x="220" y="100" font-size="9.5" text-anchor="middle">stateless JWT, short-lived (~5–15 min)</text>
    <text x="220" y="120" font-size="9.5" text-anchor="middle">sent on EVERY request; verified locally</text>
    <text x="220" y="140" font-size="9.5" text-anchor="middle">not stored server-side; NOT revocable</text>
    <text x="220" y="170" font-size="9" text-anchor="middle" opacity="0.75">stolen → attacker has only minutes,</text>
    <text x="220" y="186" font-size="9" text-anchor="middle" opacity="0.75">then exp kills it</text>

    <text x="680" y="78" font-size="12" font-weight="700" text-anchor="middle" fill="#7c5cff">REFRESH TOKEN</text>
    <text x="680" y="100" font-size="9.5" text-anchor="middle">opaque, long-lived (days–weeks)</text>
    <text x="680" y="120" font-size="9.5" text-anchor="middle">stored server-side → REVOCABLE</text>
    <text x="680" y="140" font-size="9.5" text-anchor="middle">used only to mint new access tokens</text>
    <text x="680" y="170" font-size="9" text-anchor="middle" opacity="0.75">rotates on each use; reuse of an old</text>
    <text x="680" y="186" font-size="9" text-anchor="middle" opacity="0.75">one signals theft → revoke the family</text>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M490 130 L 414 130" marker-end="url(#l6r-ar)"/>
  </g>
  <text x="452" y="126" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="8" text-anchor="end" fill="currentColor" opacity="0.75">mints</text>
  <text x="450" y="238" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">You get stateless scale on the hot path AND real revocation — the refresh token is the one you can kill,</text>
  <text x="450" y="256" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">and a short access-token lifetime bounds how long a theft is useful. Rotating refresh tokens detect replay.</text>
</svg>
```

A **short-lived access token** (a stateless JWT, minutes) rides every request and is verified locally; a **long-lived refresh token** (opaque, stored server-side, revocable) is presented only to the auth server to mint a new access token. Killing the refresh token (logout, password change, theft) stops new access tokens, and the short access lifetime bounds how long a stolen one works. If you need *immediate* revocation of access tokens too, you're back to a server lookup — a token **denylist** (by `jti`) — which trades away some of the statelessness you came for. That tension is fundamental: **stateless verification and instant revocation are in direct opposition, and the two-token pattern is the pragmatic middle.**

### When to reach for a JWT (and where to keep it)

Use a JWT when tokens cross services or organizations and you want local, lookup-free verification — API access tokens, service-to-service calls, OIDC identity. Prefer a **server-side session** (Lesson 5) for a classic single web app with a browser, where you get instant revocation for free and don't need cross-service portability. And on the client, storing a JWT in **`localStorage`** exposes it to any XSS ([Lesson 10](../10-browser-trust-boundary-cors-csrf-xss/)), so for browser apps an **`HttpOnly` cookie** is usually safer than the popular `localStorage` habit — the token being a JWT doesn't change the Lesson 5 rules for carrying it. The format is a tool; the security is the verification and the lifetime.

## Build It

Standard library only — `hmac`, `hashlib`, `json`, `base64`, `secrets` — to encode a JWT, verify it with the algorithm **pinned**, and then *run both forgeries* against a naive verifier and a correct one, so the difference is concrete rather than cautionary.

Encoding is three Base64url segments; the signature covers the exact `header.payload` text:

```python
def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

def encode_hs256(payload: dict, key: bytes) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    segments = b64url(json.dumps(header).encode()) + "." + b64url(json.dumps(payload).encode())
    sig = hmac.new(key, segments.encode(), hashlib.sha256).digest()
    return segments + "." + b64url(sig)
```

Verification is where the security lives — note that the caller states the algorithm, and the token's own header is only *checked against* that expectation, never trusted to choose it:

```python
def verify_hs256(token: str, key: bytes, *, now: int) -> dict:
    header_b64, payload_b64, sig_b64 = token.split(".")
    header = json.loads(ub64(header_b64))
    if header.get("alg") != "HS256":                    # PIN the algorithm — kills alg:none and HS/RS confusion
        raise BadToken(f"unexpected alg {header.get('alg')!r}")
    expected = hmac.new(key, f"{header_b64}.{payload_b64}".encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(ub64(sig_b64), expected):   # constant-time signature check
        raise BadToken("bad signature")
    claims = json.loads(ub64(payload_b64))
    if "exp" in claims and now >= claims["exp"]:        # expiry is not optional
        raise BadToken("expired")
    return claims
```

Contrast that with the *naive* verifier that trusts `header["alg"]` and dispatches on it — the one every JWT CVE was written against. The full script builds both, then attacks them: a tampered payload, an `alg:none` token, and the HS/RS confusion sketch, each run past both verifiers. It's in [`code/jwt_from_scratch.py`](code/jwt_from_scratch.py). Run it:

```console
$ python3 jwt_from_scratch.py
== 1 · ENCODE A JWT (HS256) ==
  token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhbGljZSIsInJvbGUiOiJ1c2VyIiwiZXhwIjoxNzAwMDAwOTAwfQ.<sig>
  header  : {"alg": "HS256", "typ": "JWT"}
  payload : {"sub": "alice", "role": "user", "exp": 1700000900}   <- readable by anyone (encoding, not encryption)

== 2 · CORRECT VERIFY: signature + expiry, algorithm PINNED ==
  valid token           -> {'sub': 'alice', 'role': 'user', 'exp': 1700000900}
  tampered role=admin   -> rejected: bad signature
  expired token         -> rejected: expired

== 3 · FORGERY A · alg:none ==
  crafted: {"alg":"none"} . {"sub":"attacker","role":"admin"} . (empty sig)
  naive verifier (trusts header alg) -> ACCEPTED as role=admin   ✗ forged
  correct verifier (pins HS256)      -> rejected: unexpected alg 'none'   ✓

== 4 · FORGERY B · HS/RS key confusion (the shape of it) ==
  server 'expects' RS256 and verifies with a PUBLIC key (public by design)
  attacker signs HS256 using that public key as the HMAC secret
  naive verifier (alg from token)    -> ACCEPTED   ✗ forged
  correct verifier (pins RS256)      -> rejected: unexpected alg 'HS256'   ✓
```

**Section 2** is the happy path plus the two everyday rejections: a tampered payload fails because the signature no longer matches, and an expired token fails because `exp` is checked. **Sections 3 and 4** are the lesson's point: the *same* forged tokens that a naive verifier accepts as `role=admin` are rejected by the correct verifier for one reason — it pinned the algorithm and refused to let the token choose. That single line, `if header["alg"] != EXPECTED`, is the difference between a broken system and a safe one.

## Use It

You will never hand-roll JWT verification in production — you'll use a vetted library, precisely because these traps are easy to fall into. In Python that's **PyJWT**, and its API is designed to force the safe choice:

```python
import jwt   # PyJWT

token = jwt.encode({"sub": "alice", "role": "user"}, key, algorithm="HS256")

claims = jwt.decode(
    token,
    key,
    algorithms=["HS256"],        # REQUIRED and explicit — PyJWT refuses to infer it from the token
    options={"require": ["exp"]},# make expiry mandatory
    audience="acme-api",         # verifies `aud`
    issuer="acme-gw",            # verifies `iss`
)
```

The critical detail is that `algorithms=[...]` is **mandatory** — modern PyJWT will not decode without it, and it will not accept `alg:none` unless you explicitly pass `algorithms=["none"]` and no key. That single design decision is the library encoding the lesson you just learned. For **RS256**, you pass the private key to `encode` and the *public* key (or a `PyJWKClient` pointed at the issuer's JWKS URL) to `decode` with `algorithms=["RS256"]` — and because you pin `["RS256"]`, the HS/RS confusion attack can't land. Always set `exp` (and verify it), verify `aud` and `iss` for anything cross-service, and keep access-token lifetimes short with a refresh token behind them.

A few production notes that map to the concepts: the equivalents exist everywhere (`jsonwebtoken` in Node, `golang-jwt` in Go, `jsonwebtoken` in Rust) with the same "pass the algorithms explicitly" API; for revocation you either accept the short-lifetime bound or maintain a `jti` denylist checked on sensitive operations; and for browser apps, remember Lesson 5 — an `HttpOnly` cookie beats `localStorage` for holding the token. The rule to carry out of this lesson is blunt: **a JWT is only as safe as its verification, verification means pinning the algorithm and enforcing `exp`/`aud`/`iss`, and you get that by using the library correctly — never by trusting the token to describe how it should be checked.**

## Think about it

1. A developer says "JWTs are secure because they're signed, so I can put the user's role and their email in the payload and trust it everywhere." Two things in that sentence are wrong or dangerous. Identify both, and say what's actually true.
2. Walk through the `alg:none` forgery against a verifier that reads the algorithm from the token's header. What does the attacker send, why does the naive verifier accept it, and what one-line change stops it?
3. HS/RS key confusion turns a *public* key into a forgery tool. Explain how the attacker uses the RSA public key, and why "the public key is public, so it's fine to share" is true yet still leads to the attack if verification is done wrong.
4. Your JWTs have a 24-hour expiry, and a user's laptop with a valid token is stolen. Compare what you can do about it versus if you'd used a server-side session — then describe how the access+refresh pattern would have changed the blast radius.
5. When would you deliberately choose a server-side session over a JWT, and when the reverse? Give one concrete product scenario for each where the other choice would be a mistake.

## Key takeaways

- **A JWT is a signed JSON claim set in three Base64url parts** (`header.payload.signature`), self-contained so any service holding the key verifies it with **no lookup** — which is why it fits multi-service and API auth where a shared session store doesn't.
- **The payload is encoded, not encrypted — it is readable by anyone.** The signature gives integrity and authenticity, not confidentiality. Never put secrets in a JWT; if the claims must be hidden, that's a JWE.
- **The standard claims carry the security:** always set and verify **`exp`** (a stateless token can't be revoked, so lifetime is your control), and verify **`aud`** and **`iss`** for cross-service tokens so a token minted for one audience can't be replayed at another.
- **Verification is the whole security, and the one rule is: never trust the token's `alg`.** Pin the algorithm server-side. The two famous forgeries — **`alg:none`** (skip the check) and **HS/RS key confusion** (verify an HMAC with the RSA public key) — both come from letting the token choose how it's verified.
- **Stateless verification and instant revocation are opposed.** The pragmatic answer is **short-lived access tokens** (stateless JWTs) plus **long-lived, revocable refresh tokens** (opaque, server-side, rotating) — scale on the hot path, real revocation on the token you can kill.
- **Use the library, correctly.** PyJWT (and its cousins) force you to pass `algorithms=[...]` explicitly and can enforce `exp`/`aud`/`iss` — that's the lesson encoded as an API. Choose HS256 inside one trust boundary, RS256/ES256 (with JWKS) across services, and a server-side session for a plain browser app.

Next: [OAuth 2.0 & OIDC](../07-oauth2-and-oidc/) — you can now issue and verify tokens; next you learn the protocol that decides *who is allowed to issue them on whose behalf* — delegated authorization, the Authorization Code flow with PKCE, and how OIDC turns OAuth into a login system built on the very JWTs you just built.
