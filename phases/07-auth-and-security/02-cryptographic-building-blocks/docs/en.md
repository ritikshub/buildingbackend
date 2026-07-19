# Cryptographic Building Blocks

> The word "encrypt" gets used for three unrelated operations, and confusing them is how the AcmeNotes token from Lesson 1 got forged. This lesson pulls apart the small set of primitives every later mechanism is made of — encoding, hashing, MACs, symmetric and asymmetric encryption, key derivation, and the one random generator you're allowed to use — and builds the keyed ones by hand from Python's standard library, so a hashed password, a signed JWT, an HMAC'd webhook, and an encrypted secret stop being magic.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Authentication, Authorization & the Security Mindset](../01-authn-authz-and-the-security-mindset/)
**Time:** ~75 minutes

## The Problem

A developer is handed a ticket: *"encrypt the sensitive stuff."* They ship three changes that afternoon, feel productive, and introduce three vulnerabilities — because "encrypt" in a stand-up means at least three different operations, and they used the wrong one each time.

**Change one.** The session cookie holds `{"user":"alice","admin":false}`. They Base64-encode it so "users can't read or edit it," and ship:

```python
cookie = base64.b64encode(b'{"user":"alice","admin":false}').decode()
# 'eyJ1c2VyIjoiYWxpY2UiLCJhZG1pbiI6ZmFsc2V9'
```

Base64 is an **encoding**. It has no key and hides nothing — it exists to make bytes survive a text channel, not to keep a secret. Anyone runs `base64.b64decode` (the browser's dev console does it in one line), reads `admin:false`, changes it to `admin:true`, re-encodes, and sends it back. This is the Lesson 1 forged token exactly.

**Change two.** Passwords are stored "encrypted" with MD5:

```python
stored = hashlib.md5(password.encode()).hexdigest()
```

Two misconceptions in one line. MD5 is not encryption — it's a **hash**, one-way, and there is no "decrypt" (that's actually the point of using it for passwords). But MD5 is a *broken, blazingly fast* hash: a consumer GPU computes billions per second, so an attacker who steals the table reverses common passwords by brute force in minutes. And with no salt, identical passwords produce identical hashes. Right *category* (one-way), catastrophically wrong *choice* — the subject of [Lesson 3](../03-password-storage-and-hashing/).

**Change three.** An incoming webhook carries a signature; they verify it:

```python
if request_signature == expected_signature:      # looks fine. isn't.
    process(request)
```

The `==` on two byte strings returns the instant it finds a differing byte. That timing difference is measurable over many requests, and it lets an attacker recover the correct signature **one byte at a time** — a *timing attack*. The comparison has to take the same time whether the first byte or no byte matches.

Three changes, three different primitives needed, zero correct. The fix is not "try harder" — it's a **vocabulary**. Encoding, hashing, MAC, symmetric encryption, asymmetric encryption, key derivation, and secure randomness are seven distinct tools with seven distinct jobs, and almost every auth bug in this phase is one of them used for a job it can't do. This lesson defines all seven and builds the keyed ones from `hashlib`, `hmac`, and `secrets` — no third-party code — so you know exactly what each one guarantees.

## The Concept

### Three things people all call "encryption"

Start by separating the three operations the ticket conflated. They differ on two yes/no questions — *is it reversible?* and *does it need a key?* — and those two questions determine what security property you actually get.

| | **Encoding** | **Hashing** | **Encryption** | **MAC / HMAC** |
|---|---|---|---|---|
| Reversible? | Yes — by anyone | **No** (one-way) | Yes — with the key | **No** (one-way) |
| Needs a key? | No | No | **Yes** | **Yes** (shared secret) |
| Output size | grows with input | **fixed** (e.g. 256-bit) | ciphertext + nonce | **fixed** (e.g. 256-bit tag) |
| Gives you | transport safety | a fingerprint / integrity | **confidentiality** | **integrity + authenticity** |
| Examples | Base64, hex, URL-encode | SHA-256, SHA-3 | AES-GCM, ChaCha20 | HMAC-SHA256 |
| The classic misuse | "hiding" a secret with it | using a fast hash for passwords | encrypting without authenticating | comparing tags with `==` |

Read the *Gives you* row as the whole point. If you need something to be **secret**, you need encryption (a key). If you need to detect **tampering**, you need a hash or a MAC. If you need to prove a message came from someone who holds a **shared secret**, you need a MAC. Encoding gives you *nothing* security-wise, ever. Keep this table within reach for the rest of the phase; every mechanism picks a column.

### Hashing: a one-way, fixed-size fingerprint

A **cryptographic hash function** takes any input — one byte or a gigabyte — and produces a fixed-size output (SHA-256 = Secure Hash Algorithm, 256-bit output, from the U.S. NIST standard FIPS 180-4). It is **deterministic** (same input → same digest, always) and **one-way** (given the digest, you cannot feasibly find the input). There is no key and no "decrypt": a hash is a *fingerprint*, not a container.

The property that makes it useful is the **avalanche effect** — flip a single bit of input and roughly half the output bits change, unpredictably — so the digest reveals nothing about how close two inputs were.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 296" width="100%" style="max-width:840px" role="img" aria-label="Two nearly identical inputs, password123 and password124, each pass through a one-way SHA-256 box and produce completely different fixed-length digests, illustrating the avalanche effect. A dashed arrow attempting to go back from digest to input is crossed out, showing the function is irreversible.">
  <defs>
    <marker id="l2h-ar" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">A hash is one-way, and one bit in changes half the bits out</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2" font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="20" y="62" width="170" height="44" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.6"/>
    <rect x="260" y="62" width="150" height="44" rx="9" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
    <rect x="470" y="62" width="390" height="44" rx="9" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f" stroke-opacity="0.7"/>
    <rect x="20" y="150" width="170" height="44" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.6"/>
    <rect x="260" y="150" width="150" height="44" rx="9" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
    <rect x="470" y="150" width="390" height="44" rx="9" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f" stroke-opacity="0.7"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.8">
    <path d="M194 84 L 256 84" marker-end="url(#l2h-ar)"/>
    <path d="M414 84 L 466 84" marker-end="url(#l2h-ar)"/>
    <path d="M194 172 L 256 172" marker-end="url(#l2h-ar)"/>
    <path d="M414 172 L 466 172" marker-end="url(#l2h-ar)"/>
  </g>
  <g fill="none" stroke="#d64545" stroke-width="1.8" stroke-dasharray="5 4">
    <path d="M470 220 L 200 220" marker-end="url(#l2h-ar)"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="105" y="88" font-size="12" text-anchor="middle">"password123"</text>
    <text x="335" y="82" font-size="11.5" font-weight="700" text-anchor="middle" fill="#0fa07f">SHA-256</text>
    <text x="335" y="98" font-size="8.5" text-anchor="middle" opacity="0.7">one-way</text>
    <text x="480" y="88" font-size="11">ef92b778…73e94f  (256 bits, fixed)</text>
    <text x="105" y="176" font-size="12" text-anchor="middle">"password124"</text>
    <text x="335" y="170" font-size="11.5" font-weight="700" text-anchor="middle" fill="#0fa07f">SHA-256</text>
    <text x="335" y="186" font-size="8.5" text-anchor="middle" opacity="0.7">one-way</text>
    <text x="480" y="176" font-size="11">33631376…2bb0087  (utterly different)</text>
    <text x="335" y="240" font-size="10.5" font-weight="700" fill="#d64545">irreversible — no key, no inverse function</text>
    <text x="440" y="276" font-size="10.5" text-anchor="middle" opacity="0.85">One character of difference in the input shares nothing between the two digests — that is the avalanche effect.</text>
  </g>
</svg>
```

What makes a hash *cryptographic* (rather than a checksum like CRC32) is three resistances: **preimage resistance** (given a digest, you can't find *an* input that produces it), **second-preimage resistance** (given one input, you can't find a *different* input with the same digest), and **collision resistance** (you can't find *any* two inputs that collide). MD5 and SHA-1 are broken on collisions and must not be used; use **SHA-256** or SHA-3. Hashes are how you fingerprint a file, index data, and — combined with a key — build the MAC below.

### Unpredictable by design: the one random generator you may use

Cryptography runs on secrets an attacker cannot guess: session IDs, tokens, salts, keys, nonces. The ordinary random number generator in every language — Python's `random`, seeded from the clock — is a **PRNG** (pseudo-random number generator) built for *statistical* randomness (simulations, shuffles), and it is **predictable**: observe a handful of outputs and you can reconstruct its internal state and predict every future value. Using it to mint session tokens means an attacker predicts the next user's token.

What you need is a **CSPRNG** (cryptographically secure PRNG), seeded from the operating system's entropy pool (`/dev/urandom`, `getrandom(2)`) and built so that past outputs reveal nothing about future ones. In Python that is the **`secrets`** module (and `os.urandom`); never `random` for anything security-bearing. This is a one-line rule with enormous consequences: *every* secret value in this phase — salts, keys, tokens, nonces, CSRF tokens — comes from a CSPRNG.

### MACs and HMAC: a hash only the key-holder can compute

A plain hash detects *accidental* corruption, but not a deliberate attacker: if a message travels with `sha256(message)` next to it, anyone who edits the message just recomputes the hash. To detect *malicious* tampering you need a **MAC** (Message Authentication Code): a hash that also mixes in a **shared secret key**, so only someone who holds the key can produce or verify a valid tag. A correct tag proves two things at once — the message wasn't altered (**integrity**) and it came from someone holding the key (**authenticity**).

The standard construction is **HMAC** (Hash-based MAC, RFC 2104): `HMAC(key, msg) = H((key ⊕ opad) ∥ H((key ⊕ ipad) ∥ msg))` — the message is hashed under the key twice with two different pads, a design that's provably secure even though naive `H(key ∥ msg)` is not. You'll build exactly this by hand in a dozen lines and confirm it matches the standard library.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 320" width="100%" style="max-width:860px" role="img" aria-label="A sender computes HMAC of a message using a shared key to produce a tag, and sends message plus tag. An attacker in the channel flips a bit of the message. The receiver recomputes HMAC over the received message with the same shared key and compares the two tags using a constant-time comparison; because the message changed, the tags differ and the message is rejected.">
  <defs>
    <marker id="l2m-ar" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">HMAC: a tag only the shared key can make, checked in constant time</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2" font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="20" y="54" width="250" height="150" rx="11" fill="#3553ff" fill-opacity="0.06" stroke="#3553ff" stroke-opacity="0.7"/>
    <rect x="630" y="54" width="250" height="150" rx="11" fill="#0fa07f" fill-opacity="0.06" stroke="#0fa07f" stroke-opacity="0.7"/>
    <rect x="40" y="88" width="150" height="34" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
    <rect x="40" y="146" width="210" height="34" rx="7" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
    <rect x="650" y="88" width="210" height="34" rx="7" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
    <rect x="650" y="146" width="210" height="34" rx="7" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.7">
    <path d="M115 122 L 115 144" marker-end="url(#l2m-ar)"/>
    <path d="M270 163 L 330 163" marker-end="url(#l2m-ar)"/>
    <path d="M570 163 L 646 163" marker-end="url(#l2m-ar)"/>
    <path d="M755 122 L 755 144" marker-end="url(#l2m-ar)"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="145" y="76" font-size="11.5" font-weight="700" text-anchor="middle" fill="#3553ff">SENDER (holds key)</text>
    <text x="115" y="109" font-size="10" text-anchor="middle">message</text>
    <text x="145" y="167" font-size="9.5" text-anchor="middle">HMAC(key, message) = tag</text>
    <text x="450" y="150" font-size="11" text-anchor="middle" font-weight="700">send: (message, tag)</text>
    <text x="450" y="188" font-size="10" text-anchor="middle" fill="#d64545">attacker flips a bit of message ✗</text>
    <text x="450" y="206" font-size="9" text-anchor="middle" opacity="0.7">(tag can't be recomputed — no key)</text>
    <text x="755" y="76" font-size="11.5" font-weight="700" text-anchor="middle" fill="#0fa07f">RECEIVER (holds key)</text>
    <text x="755" y="109" font-size="9.5" text-anchor="middle">recompute HMAC(key, msg')</text>
    <text x="755" y="167" font-size="9.5" text-anchor="middle">compare_digest(tag, tag')</text>
  </g>
  <text x="450" y="250" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="12" font-weight="700" fill="#d64545">tags differ → REJECT (message was altered)</text>
  <text x="450" y="284" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.88">The compare must be constant-time (hmac.compare_digest). A `==` returns early on the first wrong byte,</text>
  <text x="450" y="302" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.88">and that timing difference lets an attacker recover the correct tag one byte at a time.</text>
</svg>
```

HMAC is the workhorse of this phase: it signs JWTs with a shared secret ([Lesson 6](../06-jwt-and-token-auth/)), signs API requests and webhooks ([Lesson 8](../08-api-keys-hmac-and-webhooks/)), and stamps tamper-proof session cookies ([Lesson 5](../05-sessions-and-secure-cookies/)).

### Constant-time comparison: the bug that leaks a secret through a clock

The webhook bug deserves its own name because it recurs everywhere you compare a secret. When you check a MAC, a token, or a password hash with `a == b`, the comparison **short-circuits**: it stops at the first byte that differs. So a guess whose first byte is correct takes *fractionally* longer to reject than one whose first byte is wrong. Feed the server millions of guesses, measure the timing, and you climb the secret byte by byte — turning an impossible 2²⁵⁶ search into a linear one. The defense is a **constant-time comparison** that always inspects every byte and takes the same time regardless of where (or whether) the first difference is: `hmac.compare_digest(a, b)`. Use it for every secret-versus-secret check in this entire phase.

### Symmetric vs asymmetric: one shared key, or a key you give away

Encryption — the tool for *confidentiality* — comes in two shapes, and the difference drives the design of TLS, JWTs, and OAuth.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 356" width="100%" style="max-width:880px" role="img" aria-label="Left panel, symmetric encryption: one shared key both encrypts plaintext into ciphertext and decrypts it back, fast but both parties must already share the secret key. Right panel, asymmetric encryption: a key pair, where the public key encrypts and only the private key decrypts for confidentiality, and the private key signs while the public key verifies for authenticity.">
  <defs>
    <marker id="l2a-ar" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Two shapes of encryption</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="44" width="424" height="296" rx="12" fill="#3553ff" fill-opacity="0.06" stroke="#3553ff" stroke-opacity="0.8"/>
    <rect x="460" y="44" width="424" height="296" rx="12" fill="#7c5cff" fill-opacity="0.06" stroke="#7c5cff" stroke-opacity="0.8"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="228" y="70" font-size="13" font-weight="700" text-anchor="middle" fill="#3553ff">SYMMETRIC — one shared key</text>
    <text x="672" y="70" font-size="13" font-weight="700" text-anchor="middle" fill="#7c5cff">ASYMMETRIC — a key pair</text>
  </g>
  <g fill="none" stroke-linejoin="round" stroke-width="1.8" font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="34" y="96" width="120" height="38" rx="8" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
    <rect x="302" y="96" width="120" height="38" rx="8" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
    <rect x="176" y="150" width="104" height="34" rx="8" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M154 115 L 300 115" marker-end="url(#l2a-ar)"/>
    <path d="M228 149 L 228 137"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="94" y="119" font-size="10" text-anchor="middle">plaintext</text>
    <text x="362" y="119" font-size="10" text-anchor="middle">ciphertext</text>
    <text x="228" y="171" font-size="10" text-anchor="middle" fill="#3553ff">🔑 same key</text>
    <text x="228" y="210" font-size="9.5" text-anchor="middle" opacity="0.85">encrypts AND decrypts (AES-GCM)</text>
    <text x="228" y="230" font-size="9.5" text-anchor="middle" opacity="0.85">— also the basis of HMAC —</text>
    <text x="228" y="270" font-size="9" text-anchor="middle" opacity="0.7">Fast. Problem: both sides must</text>
    <text x="228" y="285" font-size="9" text-anchor="middle" opacity="0.7">already share the secret key.</text>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="672" y="104" font-size="11" font-weight="700" text-anchor="middle" fill="#0fa07f">Confidentiality</text>
    <text x="672" y="124" font-size="9.5" text-anchor="middle">PUBLIC key encrypts →</text>
    <text x="672" y="140" font-size="9.5" text-anchor="middle">only PRIVATE key decrypts</text>
    <line x1="500" y1="156" x2="844" y2="156" stroke="currentColor" stroke-opacity="0.2" stroke-width="1"/>
    <text x="672" y="180" font-size="11" font-weight="700" text-anchor="middle" fill="#e0930f">Authenticity (signatures)</text>
    <text x="672" y="200" font-size="9.5" text-anchor="middle">PRIVATE key signs →</text>
    <text x="672" y="216" font-size="9.5" text-anchor="middle">anyone verifies with PUBLIC key</text>
    <line x1="500" y1="232" x2="844" y2="232" stroke="currentColor" stroke-opacity="0.2" stroke-width="1"/>
    <text x="672" y="256" font-size="9" text-anchor="middle" opacity="0.72">Public key is shareable; private key</text>
    <text x="672" y="271" font-size="9" text-anchor="middle" opacity="0.72">never leaves its owner. Slower — used</text>
    <text x="672" y="286" font-size="9" text-anchor="middle" opacity="0.72">to sign, and to bootstrap a shared key.</text>
    <text x="672" y="315" font-size="9" text-anchor="middle" opacity="0.72">RSA · ECDSA · Ed25519 · X25519</text>
  </g>
</svg>
```

**Symmetric** encryption uses **one key** for both encrypt and decrypt (AES-GCM, ChaCha20-Poly1305). It's fast and it's what actually encrypts your data — but both parties must already share the key, which raises the question of how they got it to each other secretly.

**Asymmetric** (public-key) encryption uses a **key pair**: a **public** key you can hand to anyone and a **private** key you never reveal. It runs in two directions with two different meanings. Encrypt with someone's *public* key and only their *private* key decrypts → **confidentiality** to a recipient. Sign with your *private* key and anyone verifies with your *public* key → **authenticity** (a **digital signature**): proof it came from you and wasn't altered, without sharing any secret. Asymmetric is slower, so in practice it *bootstraps* symmetric — TLS uses public-key to agree on a per-session symmetric key, then encrypts the traffic symmetrically ([Phase 1, Lesson 10](../../01-networking-and-protocols/10-tls-certificates-mtls/)). Signatures are what let a JWT signed with `RS256` be verified by services that never hold the signing key ([Lesson 6](../06-jwt-and-token-auth/)).

One more essential point about symmetric encryption: a raw cipher gives you confidentiality but **not integrity** — an attacker can flip ciphertext bits and you won't notice. That's why modern symmetric encryption is **AEAD** (Authenticated Encryption with Associated Data): AES-**GCM** and ChaCha20-**Poly1305** encrypt *and* attach a MAC in one operation, so tampering fails to decrypt. AEAD also needs a **nonce** (number-used-once): a unique value per encryption so that encrypting the same plaintext twice yields different ciphertext. Reusing a nonce with the same key is catastrophic for GCM — so nonces come from the CSPRNG, never a counter you might repeat.

### Key derivation: turning a password or a master key into keys

Keys have to come from somewhere, and two problems recur. First, humans supply **passwords**, which are low-entropy and the wrong shape for a key — so a **password-based KDF** (key derivation function) like **PBKDF2**, **scrypt**, or **Argon2** stretches a password into a key *slowly and with a salt*, deliberately burning CPU/memory to make brute force expensive (this is the heart of [Lesson 3](../03-password-storage-and-hashing/)). Second, you often have one high-entropy **master key** and need several purpose-specific keys from it — **HKDF** (HMAC-based KDF, RFC 5869) expands one key into many so you never reuse a single key for two jobs. The rule *one key, one purpose* is why KDFs matter: reusing an encryption key as a signing key, or one master secret everywhere, turns a single leak into a total compromise.

### The one rule: know the primitive, use the library

You just built the mental model for hashing, MACs, randomness, and constant-time comparison — and in *Build It* you implement HMAC and a KDF by hand, because understanding beats memorizing. But **the moment you ship, you use a vetted library** — Python's `hashlib`/`hmac`/`secrets` for the keyless primitives, and **PyCA `cryptography`** (or libsodium) for encryption and signatures. Real crypto fails on details a from-scratch version gets wrong invisibly: nonce management, padding, side channels, parameter choices, constant-time field arithmetic. "Don't roll your own crypto" doesn't mean "don't understand it" — it means *understand it well enough to pick and use the library correctly*, which is exactly what this lesson is for.

## Build It

Standard library only — `hashlib`, `hmac`, `secrets`, `base64` — to make each primitive concrete: encoding is public, a hash avalanches and is one-way, HMAC built by hand matches the stdlib, a naive compare leaks timing while `compare_digest` doesn't, a CSPRNG is unpredictable where `random` is not, and PBKDF2 stretches a password on purpose.

HMAC is worth building once, because it demystifies every signed token later. It's just the hash function applied twice with two key-derived pads:

```python
def hmac_sha256(key: bytes, msg: bytes) -> bytes:
    """HMAC-SHA256 by hand (RFC 2104), to prove it's just H applied twice."""
    block = 64                                     # SHA-256 processes 64-byte blocks
    if len(key) > block:
        key = hashlib.sha256(key).digest()         # long keys are hashed down first
    key = key.ljust(block, b"\x00")                # then zero-padded to one block
    ipad = bytes(b ^ 0x36 for b in key)            # inner pad
    opad = bytes(b ^ 0x5c for b in key)            # outer pad
    inner = hashlib.sha256(ipad + msg).digest()
    return hashlib.sha256(opad + inner).digest()   # H(opad ∥ H(ipad ∥ msg))
```

Running it against the standard library on the same input yields identical bytes — proof that HMAC is not magic, just a disciplined double-hash. The verification side is where the timing bug hides, so the tag check must be constant-time:

```python
def verify(key: bytes, msg: bytes, tag: bytes) -> bool:
    expected = hmac.new(key, msg, hashlib.sha256).digest()
    return hmac.compare_digest(tag, expected)      # NEVER `tag == expected`
```

And the difference between the two random generators is the difference between a secure token and a predictable one — given a seed, `random` replays its entire future, while `secrets` cannot be replayed or predicted:

```python
import random, secrets
r = random.Random(1234)                            # seedable == reproducible == predictable
print([r.randint(0, 999) for _ in range(3)])       # same three numbers every run
print(secrets.token_hex(16))                       # 128 bits from the OS CSPRNG — unrepeatable
```

The full script — encoding round-trips, the avalanche demonstration, the by-hand-vs-stdlib HMAC check, tamper detection, a timing-comparison walkthrough, CSPRNG-vs-PRNG, and PBKDF2 stretching — is in [`code/crypto_primitives.py`](code/crypto_primitives.py). Run it:

```console
$ python3 crypto_primitives.py
== 1 · ENCODING IS NOT SECRECY ==
  plaintext : {"user":"alice","admin":false}
  base64    : eyJ1c2VyIjoiYWxpY2UiLCJhZG1pbiI6ZmFsc2V9
  decoded   : {"user":"alice","admin":false}   <- anyone reverses it, no key needed

== 2 · HASH: ONE-WAY, FIXED-SIZE, AVALANCHE ==
  sha256("password123") = ef92b778bafe771e89245b89ecbc08a44a4e166c06659911881f383d4473e94f
  sha256("password124") = 33631376724e5d5480fa397dfcf03b66ad47b934ab495174d7058c38f2bb0087
  bits different: 118 / 256  (~50%, from a 1-character change)

== 3 · HMAC BY HAND == STANDARD LIBRARY ==
  by hand : 2e614ce9...  stdlib : 2e614ce9...   match: True

== 4 · TAMPER DETECTION + CONSTANT-TIME VERIFY ==
  original 'transfer $10 to bob'  tag ok?  True
  tampered 'transfer $99 to bob'  tag ok?  False   <- integrity + authenticity

== 5 · CSPRNG VS PRNG ==
  random.Random(1234) run A: [989, 796, 451]
  random.Random(1234) run B: [989, 796, 451]   <- predictable: same seed, same 'secrets'
  secrets.token_hex(16)   : 412c4ba3c9c0dc24817710f48b972d12        <- unrepeatable, unpredictable

== 6 · KEY DERIVATION (PBKDF2 stretches a password, slowly, with salt) ==
  salt        : 0b84764a... (16 random bytes)
  derived key : 22c63af7...  (32 bytes, 600000 iterations ~ 1.2s on purpose)
```

Read what each section proves. **Section 1** is the cookie bug: Base64 is a public round-trip, so anything you "hide" with it is readable and editable by the client. **Section 2** shows the avalanche — a one-character change flips 118 of 256 output bits (roughly half), and there is no way back from the digest. **Section 3** is the reveal: your twelve-line HMAC produces byte-identical output to `hmac.new`, so the "signature" on every token later in the phase is a mechanism you fully understand. **Section 4** shows integrity in action — editing `$10` to `$99` invalidates the tag, because the attacker can't recompute it without the key. **Section 5** is the token bug: `random` seeded the same way replays the same "secrets," while `secrets` can't be replayed. **Section 6** shows PBKDF2 deliberately taking a quarter-second per hash — the slowness *is* the security, and Lesson 3 explains why.

## Use It

The keyless primitives you just built by hand are exactly what `hashlib`, `hmac`, and `secrets` give you in production — keep using the stdlib for those. For **encryption and signatures**, reach for **PyCA `cryptography`** (a maintained binding over OpenSSL), because those are the primitives where a from-scratch version fails silently.

Symmetric AEAD in three lines — note the fresh random nonce and that tampering *fails to decrypt* rather than returning garbage:

```python
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import os

key = AESGCM.generate_key(bit_length=256)          # from the OS CSPRNG
aes = AESGCM(key)
nonce = os.urandom(12)                              # 96-bit nonce, UNIQUE per encryption
ct = aes.encrypt(nonce, b"card=4111111111111111", b"user=alice")  # last arg: associated data
# decrypt verifies the built-in tag AND the associated data; either mismatch -> InvalidTag
pt = aes.decrypt(nonce, ct, b"user=alice")
# aes.decrypt(nonce, ct[:-1] + b"\x00", b"user=alice")  ->  raises InvalidTag (tamper caught)
```

The "associated data" (`user=alice`) is authenticated but not encrypted — it binds the ciphertext to a context, so a valid ciphertext for one user can't be replayed against another. That's AEAD's *AD*, and it's how you stop a copy-paste attack on encrypted fields.

Asymmetric signatures with **Ed25519** (a modern elliptic-curve scheme — fast, small keys, no parameter footguns):

```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.exceptions import InvalidSignature

priv = Ed25519PrivateKey.generate()
pub = priv.public_key()                            # publish this; never publish priv
sig = priv.sign(b"release v3.14 approved")         # only the private key can produce sig
pub.verify(sig, b"release v3.14 approved")         # anyone with pub verifies; returns None on success
# pub.verify(sig, b"release v9.99 approved")        ->  raises InvalidSignature
```

Two higher-level conveniences worth knowing so you don't hand-assemble primitives: **Fernet** (in the same library) is symmetric encryption with authentication, key format, and timestamp all chosen for you — the right default when you just need to encrypt a blob and don't want to pick a nonce. And **`nacl`/libsodium** (PyNaCl) offers `SecretBox`, `Box`, and `SealedBox` with similarly safe defaults. The pattern is always the same: **pick a high-level, misuse-resistant API; never assemble a cipher, a mode, a padding, and a MAC by hand in production.** You now understand what's inside them, which is precisely what lets you choose correctly.

## Think about it

1. A colleague stores password reset tokens as `sha256(user_id + secret)` and says "it's hashed, so it's secure." Which security property does a plain hash give here, which does it *not*, and what should the construction be instead?
2. You need to encrypt a document so that only the recipient can read it, and separately prove *you* wrote it. Which key (public or private, yours or theirs) do you use for each of the two operations, and why can't one key do both jobs?
3. Your code compares an incoming API signature with `hmac.compare_digest`. A teammate "optimizes" it: `if len(sig) == len(expected) and hmac.compare_digest(sig, expected)`. Explain what the added length check leaks, and whether it matters.
4. An engineer reuses the same 96-bit AES-GCM nonce for every message "to save space, since it's random-looking anyway." What breaks, and is this worse than using no encryption at all for the *integrity* guarantee?
5. You have one 32-byte master secret and need a key to encrypt session data and a *different* key to sign CSRF tokens. Why is deriving both from the master with HKDF (different `info` labels) better than using the master directly for both?

## Key takeaways

- **Encoding, hashing, encryption, and MACs are four different tools.** Encoding (Base64) is reversible, keyless, and secret-free — it hides nothing. Hashing is one-way and keyless — a fingerprint, not a container. Encryption is reversible *with a key* — the only tool for confidentiality. A MAC is a keyed one-way tag — integrity **and** authenticity. Almost every auth bug is one of these used for a job it can't do.
- **A cryptographic hash is one-way and avalanches** (SHA-256, not MD5/SHA-1), so it fingerprints and — combined with a key as **HMAC** — detects deliberate tampering. HMAC is just the hash applied twice with two key-derived pads; you can build it in a dozen lines.
- **Use a CSPRNG (`secrets`, `os.urandom`) for every secret value** — token, salt, key, nonce. The ordinary PRNG (`random`) is predictable from its outputs and must never mint anything security-bearing.
- **Compare secrets in constant time (`hmac.compare_digest`), never with `==`.** A short-circuiting compare leaks the secret one byte at a time through timing.
- **Encryption is symmetric (one shared key, fast, AES-GCM) or asymmetric (a key pair: public encrypts / private decrypts for confidentiality, private signs / public verifies for authenticity).** Prefer **AEAD** (AES-GCM, ChaCha20-Poly1305) so encryption also authenticates, always with a unique CSPRNG **nonce**; asymmetric bootstraps symmetric and powers signatures.
- **Know the primitive, use the library.** Build HMAC and a KDF by hand to understand them, then ship `hashlib`/`hmac`/`secrets` and PyCA `cryptography` (or libsodium) — real crypto fails on nonce, padding, and side-channel details a from-scratch version gets wrong invisibly.

Next: [Password Storage & Hashing](../03-password-storage-and-hashing/) — you now know a hash is one-way and that fast is the enemy; next you turn that into safe password storage with salts, peppers, and the deliberately slow hashes bcrypt, scrypt, and Argon2.
