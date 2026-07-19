# API Keys, HMAC Signing & Webhooks

> Most of the auth in this phase assumed a human at a keyboard. But a huge share of backend traffic has no user at all — one service calling another, a cron job hitting your API, a `payment_succeeded` webhook arriving from Stripe. This is **machine identity**, and it has its own toolkit: **API keys** done right (prefixed, hashed at rest, scoped, rotatable), **HMAC request signing** so a request can't be tampered or replayed, and **webhook verification** so you can trust a POST that arrives at a public URL claiming to be from someone you trust. You'll build all three from the standard library.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Cryptographic Building Blocks](../02-cryptographic-building-blocks/) · [JWT & Token Auth from Scratch](../06-jwt-and-token-auth/)
**Time:** ~70 minutes

## The Problem

Two machine-to-machine situations, both of which the browser-centric tools so far don't cover.

**A partner's backend needs to call your API.** There's no login page, no browser, no user to click "consent" — just a server, at 3am, making a request. The standard answer is an **API key**: a long secret string the partner sends with each request. Simple, and easy to get catastrophically wrong. Teams routinely store API keys in the database **in plaintext** (so one DB leak exposes every customer's key), put them in **URL query strings** (so they're logged by every proxy, CDN, and `access.log` on the path), give them **no scope** (so a key meant to read reports can also delete accounts), and provide **no way to rotate** one without downtime. An API key is a **bearer token** — whoever holds it *is* the caller — so each of those mistakes is a full compromise waiting for a leak.

**A webhook arrives at your public endpoint.** Stripe (or GitHub, or Slack) sends you an HTTP POST: `{"type":"payment_succeeded","amount":49900,"customer":"cus_123"}`. Your handler is about to ship physical goods based on it. But that endpoint is a public URL — *anyone* on the internet can POST to it. How do you know this request is really from Stripe and not an attacker who read your API docs and is forging "payment succeeded" events to get free merchandise? A bare API key doesn't help here: the request is *inbound*, and even if it carried a shared secret, an attacker who captured one legitimate webhook could **replay** it verbatim. You need a way to verify that (a) the payload was produced by someone holding the shared secret and (b) it hasn't been altered or replayed.

Both problems reduce to the same three properties, which a plain bearer token doesn't give you: **authenticity** (it really came from who it claims), **integrity** (nobody changed it in flight), and **freshness** (it's not a replay of an old valid request). API keys give you a weak form of authenticity and nothing else; **HMAC signing** ([Lesson 2](../02-cryptographic-building-blocks/)) gives you all three. This lesson builds keys correctly, then upgrades to signed requests, then applies signing to inbound webhooks — the exact mechanism Stripe and GitHub use.

## The Concept

### Machine identity: authentication with no user and no browser

When the caller is a program, the interactive flows are gone — no password prompt, no MFA, no OAuth consent screen. What remains is a **credential the machine holds** and presents on each call. Three tiers, in rough order of strength: a **static API key** (a shared secret, simplest), a **signed request** (the key never travels; a per-request signature does), and **mutual TLS** (mTLS — both sides present certificates, the heavyweight option from [Phase 1, Lesson 10](../../01-networking-and-protocols/10-tls-certificates-mtls/)). OAuth's **Client Credentials** grant ([Lesson 7](../07-oauth2-and-oidc/)) is the token-based cousin. This lesson lives in the first two tiers, which cover the vast majority of API and webhook auth.

### API keys: bearer credentials for services

An API key is a long, random, high-entropy secret ([Lesson 2](../02-cryptographic-building-blocks/)) that identifies and authenticates a caller. Because it's a bearer token, everything about how you generate, store, and transmit it is a security decision. The industry-standard design — popularized by Stripe — packs identification and secrecy into one string:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 330" width="100%" style="max-width:880px" role="img" aria-label="Anatomy and storage of an API key. The key sk_live_EXAMPLE-not-a-real-key has three parts: sk marks it a secret key, live marks the environment, and the rest is a 128-plus-bit random secret. On creation the full key is shown to the user exactly once. The database stores only a fast hash of the key plus a searchable prefix and metadata like scope and last-used. On each request the server hashes the presented key and looks up the hash, comparing in constant time. The prefix lets dashboards identify and revoke a key without ever storing the secret.">
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">An API key: identifiable prefix + secret, shown once, stored only as a hash</text>
  <text x="450" y="60" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" fill="currentColor"><tspan fill="#7c5cff">sk</tspan>_<tspan fill="#e0930f">live</tspan>_<tspan fill="#0fa07f">EXAMPLEnotarealkey000000</tspan></text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5">
    <g fill="none" stroke-width="1.5">
      <path d="M362 70 L 362 92 L 392 92" stroke="#7c5cff"/>
      <path d="M400 70 L 400 116 L 430 116" stroke="#e0930f"/>
      <path d="M500 70 L 500 140 L 530 140" stroke="#0fa07f"/>
    </g>
    <text x="398" y="96" fill="#7c5cff" font-weight="700">sk = secret key (vs pk = publishable). Signals "treat as a secret."</text>
    <text x="436" y="120" fill="#e0930f" font-weight="700">live / test — environment, so a test key can never touch production data</text>
    <text x="536" y="144" fill="#0fa07f" font-weight="700">≥128 bits of CSPRNG randomness — the actual secret</text>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-linejoin="round" stroke-width="1.7">
      <rect x="30" y="168" width="250" height="130" rx="10" fill="#3553ff" fill-opacity="0.08" stroke="#3553ff"/>
      <rect x="325" y="168" width="250" height="130" rx="10" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f"/>
      <rect x="620" y="168" width="250" height="130" rx="10" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f"/>
    </g>
    <text x="155" y="190" font-size="11" font-weight="700" text-anchor="middle" fill="#3553ff">CREATE</text>
    <text x="155" y="212" font-size="9" text-anchor="middle">generate random key</text>
    <text x="155" y="228" font-size="9" text-anchor="middle">show FULL key to user</text>
    <text x="155" y="244" font-size="9" text-anchor="middle" font-weight="700">exactly once</text>
    <text x="155" y="266" font-size="8.5" text-anchor="middle" opacity="0.7">never retrievable again —</text>
    <text x="155" y="280" font-size="8.5" text-anchor="middle" opacity="0.7">lost means rotate</text>

    <text x="450" y="190" font-size="11" font-weight="700" text-anchor="middle" fill="#0fa07f">STORE</text>
    <text x="450" y="212" font-size="9" text-anchor="middle">DB keeps only:</text>
    <text x="450" y="228" font-size="9" text-anchor="middle">hash(key) + prefix</text>
    <text x="450" y="244" font-size="9" text-anchor="middle">+ scope, owner, last_used</text>
    <text x="450" y="266" font-size="8.5" text-anchor="middle" opacity="0.7">a DB leak exposes hashes,</text>
    <text x="450" y="280" font-size="8.5" text-anchor="middle" opacity="0.7">not usable keys</text>

    <text x="745" y="190" font-size="11" font-weight="700" text-anchor="middle" fill="#e0930f">VERIFY</text>
    <text x="745" y="212" font-size="9" text-anchor="middle">hash the presented key</text>
    <text x="745" y="228" font-size="9" text-anchor="middle">look it up, compare</text>
    <text x="745" y="244" font-size="9" text-anchor="middle">constant-time</text>
    <text x="745" y="266" font-size="8.5" text-anchor="middle" opacity="0.7">prefix identifies the key in</text>
    <text x="745" y="280" font-size="8.5" text-anchor="middle" opacity="0.7">logs/dashboards, not the secret</text>
  </g>
  <text x="450" y="320" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.85">Unlike a password, an API key is already high-entropy random, so a fast hash (SHA-256) at rest is fine — no slow KDF needed.</text>
</svg>
```

Four rules make an API key safe. **Generate** it from a CSPRNG with ≥128 bits of entropy and a meaningful **prefix** (`sk_live_`), which lets you recognize a leaked key on sight and scope environments. **Show it once** — the full key is displayed at creation and never again; if it's lost, you rotate, you don't recover. **Store only a hash** — the database keeps `hash(key)`, a searchable prefix, and metadata; because the key is already high-entropy random (unlike a human password), a **fast hash like SHA-256 is fine** here — no bcrypt/Argon2 needed, since there's nothing to brute-force. **Verify** by hashing the presented key and comparing in constant time. Then two operational rules: **scope** each key to the minimum it needs (least privilege — a read key can't write), and make **rotation** a normal, zero-downtime operation (support multiple active keys per account so you can roll one while the other still works). And always transmit keys in a **header** (`Authorization: Bearer ...`), never a query string, which lands in every log.

### The limits of a bare key — and what signing adds

Even a perfectly managed API key has a ceiling: it's still a **bearer secret sent on every request**. It proves *weak authenticity* (whoever sent it holds the key) but provides **no integrity** (an attacker on the path — or a buggy proxy — could alter the request body and the key wouldn't notice) and **no freshness** (a captured request can be **replayed** verbatim). And the key itself is on the wire every single call, so every log, every intermediary, every crash dump is a chance to leak it. **HMAC request signing** fixes all three, and its central trick is that the **secret never travels** — instead, each request carries a *signature* computed from it.

### HMAC request signing: authenticity + integrity + freshness

The client and server share a secret. For each request, the client builds a **canonical string** — a deterministic serialization of the parts that matter (method, path, a timestamp, a hash of the body) — HMACs it with the secret, and sends the signature in a header. The server rebuilds the same canonical string from what it received, recomputes the HMAC, and compares. If a single byte of the request changed, the signatures differ.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 400" width="100%" style="max-width:880px" role="img" aria-label="HMAC request signing with replay protection. The client builds a canonical string from the method, path, a timestamp, and a SHA-256 of the body, then HMAC-SHA256s it with the shared secret to produce a signature, sent in headers along with the timestamp. The secret itself never leaves the client. The server rebuilds the same canonical string from the received request, recomputes the HMAC, and compares in constant time — a mismatch means the request was tampered. Then two freshness checks: reject if the timestamp is outside a five-minute window, and reject if this signature or nonce has already been seen, defeating replay of a captured request.">
  <defs>
    <marker id="l8h-ar" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">HMAC request signing — the secret never travels; the signature does</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="20" y="46" width="410" height="210" rx="12" fill="#3553ff" fill-opacity="0.06" stroke="#3553ff" stroke-opacity="0.8"/>
    <rect x="470" y="46" width="410" height="210" rx="12" fill="#0fa07f" fill-opacity="0.06" stroke="#0fa07f" stroke-opacity="0.8"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="225" y="70" font-size="12" font-weight="700" text-anchor="middle" fill="#3553ff">CLIENT (holds secret)</text>
    <text x="675" y="70" font-size="12" font-weight="700" text-anchor="middle" fill="#0fa07f">SERVER (holds secret)</text>
    <text x="40" y="96" font-size="9" opacity="0.75">canonical string:</text>
    <text x="40" y="114" font-size="9.5">POST\n/v1/charges\n</text>
    <text x="40" y="130" font-size="9.5">1700000000\n</text>
    <text x="40" y="146" font-size="9.5">sha256(body)</text>
    <text x="40" y="176" font-size="9.5" fill="#3553ff">sig = HMAC-SHA256(secret, canonical)</text>
    <text x="40" y="206" font-size="9" opacity="0.85">send headers:</text>
    <text x="40" y="222" font-size="9">X-Timestamp: 1700000000</text>
    <text x="40" y="238" font-size="9">X-Signature: v1=3f9c...  (NOT the secret)</text>

    <text x="490" y="96" font-size="9" opacity="0.75">rebuild canonical from received</text>
    <text x="490" y="112" font-size="9" opacity="0.75">method, path, timestamp, body</text>
    <text x="490" y="140" font-size="9.5" fill="#0fa07f">recompute HMAC, compare_digest</text>
    <text x="490" y="168" font-size="9.5">① signatures match? → authentic + intact</text>
    <text x="490" y="196" font-size="9.5">② |now - timestamp| &lt; 5 min? → fresh</text>
    <text x="490" y="224" font-size="9.5">③ signature/nonce unseen? → not a replay</text>
    <text x="490" y="246" font-size="8.5" opacity="0.7">all three must pass, or reject</text>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.7">
    <path d="M430 150 L 466 150" marker-end="url(#l8h-ar)"/>
  </g>
  <text x="448" y="144" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="8" text-anchor="end" fill="currentColor" opacity="0.7">request</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <rect x="20" y="272" width="860" height="110" rx="10" fill="#d64545" fill-opacity="0.05" stroke="#d64545" stroke-opacity="0.5"/>
    <text x="34" y="294" font-size="11" font-weight="700" fill="#d64545">Why each check exists</text>
    <text x="34" y="316" font-size="9.5">① integrity + authenticity: the signature covers the body, so tampering with the amount changes sha256(body) → HMAC no longer matches.</text>
    <text x="34" y="336" font-size="9.5">② + ③ freshness: without them, an attacker who captures one valid signed request can resend it forever. The timestamp bounds the window;</text>
    <text x="34" y="352" font-size="9.5">the nonce/signature cache rejects a repeat inside it. Signing without replay protection is a common, real bug.</text>
    <text x="34" y="374" font-size="9.5" opacity="0.8">Contrast a bare API key: it rides on every request (leak risk), proves only weak authenticity, and a captured request replays perfectly.</text>
  </g>
</svg>
```

Two design points matter. First, **what you sign is a security decision**: sign the method, path, a timestamp, and a hash of the body at minimum — anything you *don't* sign, an attacker can change. (AWS's **SigV4** signs the method, URI, query, selected headers, and a body hash for exactly this reason.) Second, **signing alone doesn't stop replay** — a captured signed request is still validly signed. That's why the **timestamp** (reject requests older than a few minutes) and a **nonce** or the signature itself (remembered briefly, reject duplicates) are part of the scheme, not optional extras. Authenticity and integrity come from the HMAC; freshness comes from the timestamp and nonce.

### Webhooks: verifying what other services send *you*

A webhook flips the direction: instead of you calling an API, a provider calls *your* endpoint when something happens. Since your webhook URL is public, the verification problem is identical to signing — and providers solve it the same way. Stripe, GitHub, Slack, and the rest sign each webhook with a **secret shared only with you** and put the signature in a header; you recompute and compare.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 316" width="100%" style="max-width:880px" role="img" aria-label="Webhook verification. A provider such as Stripe sends an HTTP POST to your public endpoint with the event payload and a signature header containing a timestamp and an HMAC of timestamp-dot-payload computed with the webhook secret shared only with you. Anyone on the internet can also POST to that public URL. Your handler recomputes the HMAC over the received timestamp and raw body with your copy of the secret, compares in constant time, and checks the timestamp is recent. A forged POST from an attacker has no valid signature and is rejected; a replayed old event fails the timestamp check.">
  <defs>
    <marker id="l8w-ar" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Webhook verification — the signature is the only proof it's really the provider</text>
  <g fill="none" stroke-linejoin="round" stroke-width="1.8" font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="30" y="60" width="200" height="80" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
    <rect x="360" y="60" width="200" height="80" rx="10" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
    <rect x="690" y="40" width="190" height="120" rx="10" fill="#3553ff" fill-opacity="0.09" stroke="#3553ff"/>
    <rect x="360" y="200" width="200" height="70" rx="10" fill="#d64545" fill-opacity="0.10" stroke="#d64545"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="130" y="86" font-size="11" font-weight="700" text-anchor="middle" fill="#0fa07f">PROVIDER (Stripe)</text>
    <text x="130" y="108" font-size="8.5" text-anchor="middle">signs: HMAC(secret,</text>
    <text x="130" y="122" font-size="8.5" text-anchor="middle">"timestamp.payload")</text>
    <text x="460" y="86" font-size="11" font-weight="700" text-anchor="middle">YOUR PUBLIC ENDPOINT</text>
    <text x="460" y="108" font-size="8.5" text-anchor="middle">POST /webhooks/stripe</text>
    <text x="460" y="122" font-size="8.5" text-anchor="middle">Stripe-Signature: t=...,v1=...</text>
    <text x="785" y="66" font-size="11" font-weight="700" text-anchor="middle" fill="#3553ff">VERIFY</text>
    <text x="785" y="86" font-size="8.5" text-anchor="middle">recompute HMAC over</text>
    <text x="785" y="100" font-size="8.5" text-anchor="middle">t + raw body with</text>
    <text x="785" y="114" font-size="8.5" text-anchor="middle">YOUR secret</text>
    <text x="785" y="132" font-size="8.5" text-anchor="middle">compare_digest +</text>
    <text x="785" y="146" font-size="8.5" text-anchor="middle">timestamp fresh?</text>
    <text x="460" y="226" font-size="10.5" font-weight="700" text-anchor="middle" fill="#d64545">ATTACKER (anyone)</text>
    <text x="460" y="248" font-size="8.5" text-anchor="middle">POSTs a forged "payment_succeeded"</text>
    <text x="460" y="262" font-size="8.5" text-anchor="middle">— but has no valid signature</text>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M230 100 L 356 100" marker-end="url(#l8w-ar)"/>
    <path d="M560 100 L 686 100" marker-end="url(#l8w-ar)"/>
  </g>
  <g fill="none" stroke="#d64545" stroke-width="1.6" stroke-dasharray="5 4">
    <path d="M460 200 L 460 142" marker-end="url(#l8w-ar)"/>
  </g>
  <text x="450" y="298" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Verify over the RAW body (not the re-serialized JSON), check the timestamp for replay, and for high-value events re-fetch from the API — never trust amounts from an unverified POST.</text>
</svg>
```

Three webhook-specific gotchas: verify over the **raw request body bytes**, not a re-serialized version (re-encoding JSON changes whitespace and key order, breaking the signature); check the **timestamp** to reject replays of an old captured event; and for anything high-value, **don't trust the amounts in the webhook body** — treat the webhook as a *notification* and re-fetch the authoritative object from the provider's API. A webhook is an untrusted input crossing a trust boundary ([Lesson 1](../01-authn-authz-and-the-security-mindset/)); the signature is what lets you trust it.

## Build It

Standard library only — `secrets`, `hashlib`, `hmac`, `time` — to generate and verify API keys the right way, sign and verify a request with replay protection, and verify a Stripe-style webhook, including the attacks each defends against.

API keys: prefix + random secret, hashed at rest, verified in constant time:

```python
def new_api_key(env: str = "live") -> tuple[str, str]:
    secret = secrets.token_urlsafe(24)               # ≥128 bits from the CSPRNG
    full = f"sk_{env}_{secret}"                       # shown to the user exactly once
    stored = hashlib.sha256(full.encode()).hexdigest()   # fast hash is fine: already high-entropy
    return full, stored                              # store `stored` + prefix; never the full key

def verify_api_key(presented: str, stored_hash: str) -> bool:
    h = hashlib.sha256(presented.encode()).hexdigest()
    return hmac.compare_digest(h, stored_hash)       # constant-time
```

Signed requests: a canonical string binds the whole request; verification also enforces freshness:

```python
def sign_request(secret, method, path, body, ts, nonce) -> str:
    canonical = f"{method}\n{path}\n{ts}\n{nonce}\n{hashlib.sha256(body).hexdigest()}"
    return hmac.new(secret, canonical.encode(), hashlib.sha256).hexdigest()

def verify_request(secret, method, path, body, ts, nonce, sig, *, now, seen: set, window=300) -> str:
    expected = sign_request(secret, method, path, body, ts, nonce)
    if not hmac.compare_digest(sig, expected):       # authenticity + integrity
        return "bad signature"
    if abs(now - ts) > window:                       # freshness: timestamp window
        return "stale (replay window)"
    if nonce in seen:                                # freshness: no reuse
        return "replayed nonce"
    seen.add(nonce)
    return "ok"
```

The full script — key generation/verification, a tampered request, a replayed request, and a Stripe-style webhook with a forged attempt — is in [`code/api_keys_hmac.py`](code/api_keys_hmac.py). Run it:

```console
$ python3 api_keys_hmac.py
== 1 · API KEY: PREFIX + SECRET, HASHED AT REST ==
  issued (shown once): sk_live_tuOYEX...   prefix stored: sk_live_tuOYEX
  DB stores hash: 0fd8fb...   (not the key)
  verify correct key -> True    verify wrong key -> False

== 2 · SIGNED REQUEST: TAMPERING BREAKS THE SIGNATURE ==
  POST /v1/charges  body={"amount":4999}  -> ok
  attacker changes amount to 999999        -> bad signature   ✓ (integrity)

== 3 · REPLAY PROTECTION (timestamp + nonce) ==
  first delivery of a valid signed request -> ok
  same request replayed (same nonce)       -> replayed nonce   ✓
  valid signature but timestamp 10 min old -> stale (replay window)   ✓

== 4 · WEBHOOK VERIFICATION (Stripe-style) ==
  header: t=1700000000,v1=658dad...
  genuine webhook (correct secret)  -> verified: True
  forged POST (attacker's secret)   -> verified: False   ✓ rejected
```
(The API key and its hash are random per run; the signed-request and webhook results are stable.)

**Section 1** shows the storage model — the DB holds a hash and a prefix, never the key. **Section 2** is integrity: changing the amount invalidates the signature because the body hash is part of what's signed. **Section 3** is the part people forget — the same validly-signed request is rejected on replay by the nonce cache, and an old one by the timestamp window. **Section 4** is the webhook: the genuine event verifies, the forged POST (signed with the wrong secret) fails, which is exactly what stops an attacker from faking `payment_succeeded` at your public URL.

## Use It

In production you'll lean on the provider's tooling and a couple of standard patterns. For **API keys**, services like Stripe hand you the prefixed key and the show-once flow; your job is to store only the hash, attach a scope, and support rotation — and to **detect leaked keys**, since GitHub and cloud providers run **secret scanning** that revokes keys pushed to public repos automatically ([Lesson 13](../13-secrets-management-and-rotation/)). For **verifying webhooks**, use the provider's SDK, which wraps the exact HMAC check you just built:

```python
import stripe
# Stripe: construct_event verifies the Stripe-Signature header over the RAW body and checks freshness
event = stripe.Webhook.construct_event(
    payload=raw_request_body,                 # the bytes, not parsed JSON
    sig_header=request.headers["Stripe-Signature"],
    secret=os.environ["STRIPE_WEBHOOK_SECRET"],   # Lesson 13
)   # raises SignatureVerificationError on a bad or stale signature

# GitHub: the same idea by hand — HMAC-SHA256 of the raw body, hex, compared constant-time
expected = "sha256=" + hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
ok = hmac.compare_digest(expected, request.headers["X-Hub-Signature-256"])
```

For **signing your own outbound requests** to a partner, the reference design is **AWS Signature Version 4** — study it rather than inventing a scheme, because it gets the canonicalization, the signed-headers list, the body hash, and the time window right. For **service-to-service** auth inside your own infrastructure, the stronger option is **mTLS** ([Phase 1, Lesson 10](../../01-networking-and-protocols/10-tls-certificates-mtls/)) — both sides present certificates, so identity is established by the TLS layer and there's no bearer secret to leak — increasingly automated by a **service mesh** (Istio, Linkerd) or **SPIFFE/SPIRE**, which issue and rotate short-lived service identities for you. The rules that carry across all of it: **keys in headers never URLs, hashed at rest, scoped, and rotatable; sign what matters and add a timestamp + nonce for freshness; verify webhooks over the raw body against a shared secret; and don't trust a webhook's contents for anything high-value without re-fetching from the source.**

## Think about it

1. Your database of API keys leaks. Walk through the difference in impact between storing the keys in plaintext, storing them as `bcrypt(key)`, and storing them as `sha256(key)`. Why is SHA-256 (a *fast* hash you were told never to use for passwords) the right choice here?
2. A partner integration signs requests with HMAC but doesn't include a timestamp or nonce. Describe the exact attack this leaves open even though every request is correctly signed, and the two additions that close it.
3. A webhook handler parses the JSON body, then re-serializes it to verify the signature over the re-serialized string. It works in testing but rejects some real webhooks in production. Explain why, and state the rule for what you must sign/verify.
4. An attacker POSTs a forged `payment_succeeded` event to your public webhook URL with a plausible body. Your handler ships the goods. Which single control was missing, and separately, why should a high-value handler *still* not trust the amount in even a verified webhook?
5. Compare an API key sent on every request with an HMAC-signed request where the secret never travels. Give a threat (a specific attacker capability) that the signed request defends against and the bare key does not — and one operational cost of signing that the bare key avoids.

## Key takeaways

- **Machine identity has no user or browser** — the caller holds a credential. The tiers are a static **API key**, a **signed request** (secret never travels), and **mTLS** (certificates); OAuth **Client Credentials** is the token-based cousin.
- **An API key is a bearer secret, so its handling is the security:** generate from a CSPRNG with a meaningful **prefix**, **show it once**, **store only a hash** (a *fast* SHA-256 is correct here — the key is already high-entropy, unlike a password), **verify in constant time**, **scope** it, **rotate** it, and always send it in a **header, never a URL**.
- **A bare key gives weak authenticity and nothing else** — no integrity, no freshness, and it rides every request. **HMAC signing** gives all three: the client signs a **canonical string** (method, path, timestamp, body hash) with a shared secret and sends only the **signature**; the server recomputes and compares in constant time.
- **Signing alone doesn't stop replay.** A captured signed request is still valid, so freshness needs a **timestamp** (reject old requests) and a **nonce** (reject duplicates). Sign everything that matters — whatever you don't sign, an attacker can change.
- **Webhooks are inbound requests at a public URL, so the signature is the only proof they're genuine.** Verify over the **raw body** against the **shared webhook secret**, check the **timestamp**, and for high-value events treat the webhook as a notification and **re-fetch** the authoritative data from the provider.
- **Use the provider's tooling and proven designs:** provider SDKs for webhook verification, **AWS SigV4** as the reference for signing your own requests, and **mTLS / service mesh / SPIFFE** for service-to-service identity inside your infrastructure.

Next: [Authorization: RBAC, ABAC & ReBAC](../09-authorization-rbac-abac-rebac/) — every lesson so far has been about establishing *who* (or *what*) the caller is; now you build the other half of the phase's opening question — deciding *what they're allowed to do* — with role-, attribute-, and relationship-based access control.
