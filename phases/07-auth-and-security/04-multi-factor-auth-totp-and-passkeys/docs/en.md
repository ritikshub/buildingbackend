# Multi-Factor Authentication: TOTP & Passkeys

> A password is a shared secret, and shared secrets get phished on a fake login page, reused from a site that already leaked, and guessed in bulk — none of which the world's best Argon2 hash can stop, because the attacker never touches your database. A second factor is proof of identity the attacker *can't* obtain that way. This lesson builds the six digits in your authenticator app from scratch — they're just an HMAC over the clock — verifies it against the official RFC test vectors, then explains passkeys (WebAuthn), the phishing-proof successor that deletes the shared secret entirely.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Cryptographic Building Blocks](../02-cryptographic-building-blocks/) · [Password Storage & Hashing](../03-password-storage-and-hashing/)
**Time:** ~80 minutes

## The Problem

You did everything in Lesson 3 right: Argon2id, per-user salts, a pepper in a separate vault, breach screening at signup. Your password *storage* is excellent. And your users still get their accounts taken over, because the three most common ways a password reaches an attacker never involve your database at all:

- **Phishing.** A user gets an email — "unusual sign-in, verify your account" — clicks a link to `acme-support.com`, and types their real password into a pixel-perfect copy of your login page. The attacker now has the plaintext. Your Argon2 hash never entered the story; the user handed over the password before hashing was ever relevant.
- **Reuse.** The user picked a strong password — and used the same one on a hobby forum that stored passwords as MD5 and got breached in 2021. The attacker takes that plaintext and tries it against your login (**credential stuffing**). Your storage is irrelevant; you're being attacked with a *correct* password.
- **Bulk guessing.** Automated tools spray the ten thousand most common passwords across a million usernames. Most fail; a few percent succeed, because some users always pick `Summer2024!`.

Every one of these defeats a password *by getting a real one*, so hardening how you store passwords does nothing. The only defense is to stop relying on the password as the *sole* proof of identity — to demand a **second factor**: something the attacker who phished the password still doesn't have. That's what MFA is. But — and this is the twist the rest of the lesson turns on — **not all second factors are equal**, and the most popular ones (SMS codes, and even the authenticator app you're about to build) are still *phishable*, because the user can be tricked into typing the second factor into the fake site too. The endpoint of the story is **passkeys**, which are phishing-proof by construction because the credential is cryptographically bound to your real domain and physically cannot be replayed to `acme-support.com`.

## The Concept

### The three factors, and why one is never enough

Authentication factors come in three categories, and "multi-factor" specifically means combining factors from **different** categories — not two passwords, not a password and a security question (both are "something you know"):

- **Something you know** — a password, a PIN. Copyable, phishable, forgettable.
- **Something you have** — a phone with an authenticator app, a hardware security key, a registered device. To misuse it, the attacker needs the *physical thing*.
- **Something you are** — a fingerprint, a face. A biometric, used locally to unlock one of the above.

The point of requiring two categories is that the attacker must now compromise two *independent* things. Phishing your password gives them "something you know"; it does not give them your phone. That independence is the entire value, which is why a password plus a security question is not MFA — one leak (or one guess of your mother's maiden name, which is on your public profile) takes both.

### What MFA defends against — and what it doesn't

Be precise about the win. A second factor defends against exactly the three attacks above: **phishing, reuse, and bulk guessing**, because all three yield only the password. It does **not** defend against a compromised device, malware on the endpoint, session-token theft *after* login ([Lesson 5](../05-sessions-and-secure-cookies/)), or a real-time phishing proxy that relays your TOTP code the instant you type it (more on that below). MFA raises the cost of account takeover enormously — Microsoft and Google have both reported it blocks the overwhelming majority of automated account attacks — but it is a layer, not a force field, and *which* second factor you pick decides how much it actually buys.

### The spectrum of second factors

Second factors are not interchangeable; they form a security ladder. Read this by the columns — a factor is only as strong as the attacks it *resists*:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 356" width="100%" style="max-width:880px" role="img" aria-label="Four second-factor types ranked weakest to strongest. SMS one-time codes resist neither phishing nor SIM-swap and the server/telco holds the secret. TOTP authenticator apps resist SIM-swap but are still phishable and the server stores the shared secret. Push approvals resist SIM-swap but are vulnerable to MFA-fatigue and consent phishing, server holds secret. Passkeys and security keys (WebAuthn) resist phishing and SIM-swap and the server stores only a public key.">
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Not all second factors are equal — a factor is what it resists</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="250" y="58" font-size="9.5" text-anchor="middle" opacity="0.7">RESISTS PHISHING</text>
    <text x="470" y="58" font-size="9.5" text-anchor="middle" opacity="0.7">RESISTS SIM-SWAP</text>
    <text x="720" y="58" font-size="9.5" text-anchor="middle" opacity="0.7">SERVER HOLDS NO SECRET</text>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" font-size="12" font-weight="700">
    <g>
      <rect x="20" y="70" width="200" height="56" rx="9" fill="#d64545" fill-opacity="0.12" stroke="#d64545"/>
      <text x="34" y="94" fill="#d64545">SMS one-time code</text>
      <text x="34" y="114" font-size="8.5" font-weight="400" fill="currentColor" opacity="0.75">"text me a code"</text>
      <text x="250" y="104" text-anchor="middle" fill="#d64545" font-size="16">✗</text>
      <text x="470" y="104" text-anchor="middle" fill="#d64545" font-size="16">✗</text>
      <text x="720" y="104" text-anchor="middle" fill="#d64545" font-size="16">✗</text>
      <text x="810" y="104" font-size="8.5" font-weight="400" fill="currentColor" opacity="0.7">weakest</text>
    </g>
    <g>
      <rect x="20" y="134" width="200" height="56" rx="9" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
      <text x="34" y="158" fill="#e0930f">TOTP app (you build)</text>
      <text x="34" y="178" font-size="8.5" font-weight="400" fill="currentColor" opacity="0.75">6 digits, 30s window</text>
      <text x="250" y="168" text-anchor="middle" fill="#d64545" font-size="16">✗</text>
      <text x="470" y="168" text-anchor="middle" fill="#0fa07f" font-size="16">✓</text>
      <text x="720" y="168" text-anchor="middle" fill="#d64545" font-size="16">✗</text>
      <text x="810" y="168" font-size="8.5" font-weight="400" fill="currentColor" opacity="0.7">good</text>
    </g>
    <g>
      <rect x="20" y="198" width="200" height="56" rx="9" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
      <text x="34" y="222" fill="#3553ff">Push approval</text>
      <text x="34" y="242" font-size="8.5" font-weight="400" fill="currentColor" opacity="0.75">"approve on your phone"</text>
      <text x="250" y="232" text-anchor="middle" fill="#e0930f" font-size="13">~</text>
      <text x="470" y="232" text-anchor="middle" fill="#0fa07f" font-size="16">✓</text>
      <text x="720" y="232" text-anchor="middle" fill="#d64545" font-size="16">✗</text>
      <text x="810" y="232" font-size="8.5" font-weight="400" fill="currentColor" opacity="0.7">MFA-fatigue</text>
    </g>
    <g>
      <rect x="20" y="262" width="200" height="56" rx="9" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
      <text x="34" y="286" fill="#0fa07f">Passkey / security key</text>
      <text x="34" y="306" font-size="8.5" font-weight="400" fill="currentColor" opacity="0.75">WebAuthn / FIDO2</text>
      <text x="250" y="296" text-anchor="middle" fill="#0fa07f" font-size="16">✓</text>
      <text x="470" y="296" text-anchor="middle" fill="#0fa07f" font-size="16">✓</text>
      <text x="720" y="296" text-anchor="middle" fill="#0fa07f" font-size="16">✓</text>
      <text x="810" y="296" font-size="8.5" font-weight="400" fill="currentColor" opacity="0.7">strongest</text>
    </g>
  </g>
  <text x="450" y="342" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.85">SMS is phishable AND SIM-swappable; TOTP fixes SIM-swap but a fake page still harvests the typed code. Only WebAuthn binds the credential to your origin.</text>
</svg>
```

**SMS** is the weakest: codes are phishable (type it into the fake page) *and* the phone number can be stolen via a **SIM swap** (social-engineer the carrier into porting the number), and the telco is a third party in your auth path. It's still far better than nothing, but avoid it for anything valuable. **TOTP** (the authenticator app) removes the telco and SIM-swap risk, which is a real improvement and what you'll build — but a user can still be tricked into typing the 6 digits into a phishing site within the 30-second window. **Passkeys** are the only category that resists phishing itself, because the credential is bound to your domain by the browser and never gets sent anywhere. Build TOTP to understand the mechanism; deploy passkeys where you can.

### HOTP: an HMAC turned into a human-typable code

The authenticator app looks like magic — six digits that both your phone and the server somehow agree on without ever talking — but it's just an HMAC ([Lesson 2](../02-cryptographic-building-blocks/)) with a formatting step, standardized as **HOTP** (HMAC-based One-Time Password, RFC 4226). Both sides share one secret at enrollment. To produce a code, you HMAC a **counter** with that secret, then squeeze the 20-byte result down to six digits:

1. `mac = HMAC-SHA1(secret, counter)` — 20 bytes, where `counter` is an 8-byte integer.
2. **Dynamic truncation**: take the low 4 bits of the last byte as an `offset` (0–15), read the 4 bytes of `mac` starting at `offset`, and clear the top bit → a 31-bit number. (Reading from a variable offset stops any single byte position from biasing the output.)
3. `code = that_number mod 1_000_000`, zero-padded to 6 digits.

That's the whole algorithm, and because it's deterministic, your phone and the server compute the *same* six digits from the same secret and counter with no communication. You'll implement it in fifteen lines and confirm it produces `755224` for the RFC's official test vector — the sign that you built it exactly right.

### TOTP: HOTP with time as the counter

HOTP uses a counter that both sides increment per use, which drifts out of sync easily. **TOTP** (Time-based OTP, RFC 6238) makes the counter *the current time*, so no state has to stay synchronized — both sides just look at the clock:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 340" width="100%" style="max-width:880px" role="img" aria-label="TOTP mechanism. Both the authenticator app and the server share the same secret from enrollment. Each independently computes counter equals current time divided by 30 seconds, then HMAC-SHA1 of the secret and counter, then dynamic truncation to six digits. The user reads the code from the app and submits it; the server compares against its own computed code, allowing a plus or minus one step window for clock skew. No code is ever transmitted from the server.">
  <defs>
    <marker id="l4t-ar" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">TOTP: both sides compute the same 6 digits from the shared secret and the clock</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="20" y="48" width="250" height="240" rx="12" fill="#e0930f" fill-opacity="0.06" stroke="#e0930f" stroke-opacity="0.7"/>
    <rect x="630" y="48" width="250" height="240" rx="12" fill="#0fa07f" fill-opacity="0.06" stroke="#0fa07f" stroke-opacity="0.7"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="145" y="70" font-size="12" font-weight="700" text-anchor="middle" fill="#e0930f">AUTHENTICATOR APP</text>
    <text x="755" y="70" font-size="12" font-weight="700" text-anchor="middle" fill="#0fa07f">SERVER</text>
    <text x="450" y="66" font-size="9.5" text-anchor="middle" opacity="0.75">shared secret</text>
    <text x="450" y="80" font-size="9.5" text-anchor="middle" opacity="0.75">(set at enrollment</text>
    <text x="450" y="94" font-size="9.5" text-anchor="middle" opacity="0.75">via QR code)</text>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.4" opacity="0.5" stroke-dasharray="4 3">
    <path d="M270 80 L 630 80"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" text-anchor="middle">
    <text x="145" y="128">counter = now // 30</text>
    <text x="145" y="164">HMAC-SHA1(secret, counter)</text>
    <text x="145" y="200">dynamic truncation</text>
    <text x="145" y="240" font-size="18" font-weight="700" fill="#e0930f">417 903</text>
    <text x="755" y="128">counter = now // 30</text>
    <text x="755" y="164">HMAC-SHA1(secret, counter)</text>
    <text x="755" y="200">dynamic truncation</text>
    <text x="755" y="232" font-size="14" font-weight="700" fill="#0fa07f">417903 ± 1 step</text>
    <text x="755" y="250" font-size="8" opacity="0.7">(±30s for clock skew)</text>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.7">
    <path d="M145 250 L 145 274 L 630 274" marker-end="url(#l4t-ar)"/>
  </g>
  <text x="388" y="268" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor">user types the 6 digits →</text>
  <text x="450" y="312" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">The server never sends a code — it recomputes and compares. The secret is shared once, at enrollment, and</text>
  <text x="450" y="330" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">the code changes every 30 seconds. A ±1-step window absorbs clock drift; used codes should be rejected on reuse.</text>
</svg>
```

The counter is `floor(current_unix_time / 30)`, so the code rolls over every 30 seconds. Verification allows a **±1 step window** (checking the previous, current, and next code) to tolerate clock skew and the user typing slowly — a deliberate trade of a slightly larger guess space for usability. Two operational rules matter: **reject a code that was already used** within its window (or an attacker who sniffs one code reuses it seconds later), and keep the window small (±1, not ±10).

### Enrollment, and why TOTP is still phishable

The shared secret gets to the app at **enrollment**: the server generates a random secret, encodes it as an `otpauth://` URI (`otpauth://totp/Acme:alice?secret=BASE32...&issuer=Acme`), renders that as a **QR code**, and the app scans it to store the secret. This is also TOTP's ceiling. The secret is *shared* — the server keeps a copy, so a database breach that leaks the TOTP secrets lets the attacker generate valid codes (store them encrypted, [Lesson 13](../13-secrets-management-and-rotation/)). And critically, the code is just six digits the user reads and types, so a **real-time phishing proxy** — a fake login page that forwards whatever you enter to the real site instantly — captures the code and replays it inside the 30-second window. TOTP stops the *reuse* and *bulk-guessing* attacks cold and raises the bar on phishing, but it does not *eliminate* phishing. Only origin-bound public-key credentials do.

### Recovery codes: the "I lost my phone" problem

A second factor you can lose is a second way to get locked out. Every MFA deployment needs a **recovery path**, and the standard one is a set of **one-time recovery codes**: at enrollment, generate ~10 random codes, show them once, and tell the user to store them somewhere safe. Treat each like a password — store them **hashed**, mark each **single-use** (delete on redemption), and regenerate the set if they're used up or exposed. The trap is making recovery *weaker* than the factor it backs up: an account-recovery flow that resets MFA after answering "what's your pet's name?" hands the attacker a bypass, so the recovery path deserves the same scrutiny as the front door.

### WebAuthn and passkeys: authentication with no shared secret

The fix for phishing is to stop having a secret the user can type at all. **WebAuthn** (a W3C standard; the browser-facing half of the FIDO Alliance's **FIDO2**) replaces the shared secret with a **public-key pair** generated on the user's device. A **passkey** is such a credential. The private key never leaves the device's secure hardware (Secure Enclave, TPM, or a hardware key like a YubiKey); the server only ever stores the **public** key. Here is the ceremony:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 384" width="100%" style="max-width:880px" role="img" aria-label="WebAuthn ceremony in two lanes. Registration: the server sends a challenge; the authenticator generates a new key pair bound to the site's origin, keeps the private key in secure hardware, and returns the credential id and public key, which the server stores for the user. Authentication: the server sends a random challenge and the expected origin; the authenticator verifies the origin matches, the user approves with a biometric or PIN, and it signs the challenge with the private key; the server verifies the signature with the stored public key. The private key never leaves the device, the server stores only public keys, and because the signature is bound to the real origin, a phishing site with a different origin cannot obtain a valid signature.">
  <defs>
    <marker id="l4w-ar" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">WebAuthn / passkeys — the server stores only a public key</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="30" y="60" font-size="12" font-weight="700" fill="#3553ff">① REGISTER</text>
    <g fill="none" stroke-linejoin="round" stroke-width="1.7">
      <rect x="30" y="70" width="180" height="66" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="360" y="70" width="230" height="66" rx="9" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
      <rect x="690" y="70" width="180" height="66" rx="9" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M210 92 L 356 92" marker-end="url(#l4w-ar)"/>
      <path d="M590 114 L 686 114" marker-end="url(#l4w-ar)"/>
    </g>
    <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
      <text x="120" y="96" font-size="9.5" text-anchor="middle" font-weight="700" fill="#0fa07f">SERVER</text>
      <text x="120" y="116" font-size="8.5" text-anchor="middle">sends challenge</text>
      <text x="475" y="90" font-size="9.5" text-anchor="middle" font-weight="700" fill="#7c5cff">AUTHENTICATOR (device)</text>
      <text x="475" y="107" font-size="8" text-anchor="middle">generates key pair for this origin</text>
      <text x="475" y="121" font-size="8" text-anchor="middle">private key → secure hardware</text>
      <text x="290" y="86" font-size="7.5" text-anchor="middle" opacity="0.7">challenge</text>
      <text x="640" y="108" font-size="7.5" text-anchor="middle" opacity="0.7">cred id + PUBLIC key</text>
      <text x="780" y="96" font-size="9.5" text-anchor="middle" font-weight="700" fill="#3553ff">SERVER</text>
      <text x="780" y="116" font-size="8.5" text-anchor="middle">stores public key</text>
    </g>
  </g>
  <line x1="30" y1="158" x2="870" y2="158" stroke="currentColor" stroke-opacity="0.18" stroke-width="1"/>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="30" y="186" font-size="12" font-weight="700" fill="#0fa07f">② AUTHENTICATE</text>
    <g fill="none" stroke-linejoin="round" stroke-width="1.7">
      <rect x="30" y="196" width="180" height="72" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="360" y="196" width="230" height="72" rx="9" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
      <rect x="690" y="196" width="180" height="72" rx="9" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M210 220 L 356 220" marker-end="url(#l4w-ar)"/>
      <path d="M590 244 L 686 244" marker-end="url(#l4w-ar)"/>
    </g>
    <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
      <text x="120" y="222" font-size="9.5" text-anchor="middle" font-weight="700" fill="#0fa07f">SERVER</text>
      <text x="120" y="242" font-size="8.5" text-anchor="middle">challenge + origin</text>
      <text x="475" y="214" font-size="8.5" text-anchor="middle" font-weight="700" fill="#7c5cff">AUTHENTICATOR</text>
      <text x="475" y="230" font-size="8" text-anchor="middle">checks origin matches, user gesture</text>
      <text x="475" y="244" font-size="8" text-anchor="middle">(biometric/PIN) → signs challenge</text>
      <text x="475" y="258" font-size="8" text-anchor="middle">with the private key</text>
      <text x="640" y="238" font-size="7.5" text-anchor="middle" opacity="0.7">signature</text>
      <text x="780" y="222" font-size="9.5" text-anchor="middle" font-weight="700" fill="#3553ff">SERVER</text>
      <text x="780" y="242" font-size="8.5" text-anchor="middle">verify w/ public key</text>
    </g>
  </g>
  <text x="450" y="300" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.92" font-weight="700">Why it's phishing-proof: the browser binds the signature to the real origin.</text>
  <text x="450" y="320" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.88">A phishing site at acme-support.com has a different origin, so the authenticator produces no valid signature for it —</text>
  <text x="450" y="338" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.88">there is nothing to type, nothing to relay, and nothing in your database to steal but public keys.</text>
</svg>
```

Three properties fall out of this design, and together they close the gaps TOTP left open. **Phishing-proof**: the browser ties each credential to the **origin** (`rpId`) it was registered for and signs that origin into every assertion, so a credential for `acme.com` simply won't produce a signature for `acme-support.com` — there's no code to relay. **Breach-proof**: your database stores only public keys, which are useless to a thief (they verify signatures, they can't create them), so a leaked user table reveals no login secrets. **Unphishable *and* passwordless**: a passkey can be the *only* factor — it's "something you have" (the device) unlocked by "something you are/know" (biometric/PIN), which is already multi-factor in one gesture, which is why the industry is moving toward passkeys replacing passwords entirely rather than merely supplementing them.

Two practical distinctions to know: **device-bound** passkeys (a hardware key, or a credential that never leaves one phone) versus **synced** passkeys (backed up to iCloud Keychain / Google Password Manager and available on all your devices) — synced passkeys trade a little of the "single hardware device" assurance for the usability that makes them adoptable. And the server's job in both ceremonies is smaller than it looks: generate a random challenge, and verify a signature against a stored public key. You won't hand-roll the crypto (WebAuthn's attestation formats and COSE key parsing are genuinely intricate — this is squarely "use the library" territory), but you now understand exactly what the library does and why it can't be phished.

## Build It

Standard library only — `hmac`, `hashlib`, `struct`, `base64`, `secrets` — to build HOTP and TOTP from scratch, prove correctness against the **RFC 4226 official test vector**, verify with a skew window and one-time-use enforcement, generate an enrollment secret and `otpauth://` URI, and issue hashed single-use recovery codes.

The whole one-time-password algorithm is HMAC plus the dynamic-truncation formatting step:

```python
def hotp(secret: bytes, counter: int, digits: int = 6) -> str:
    mac = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()  # 20 bytes
    offset = mac[-1] & 0x0F                              # last nibble picks the offset
    chunk = mac[offset:offset + 4]                       # 4 bytes from there
    number = struct.unpack(">I", chunk)[0] & 0x7FFFFFFF  # clear the top bit -> 31-bit int
    return str(number % (10 ** digits)).zfill(digits)    # -> zero-padded 6-digit string

def totp(secret: bytes, now: int, step: int = 30, digits: int = 6) -> str:
    return hotp(secret, now // step, digits)             # the counter is just the clock
```

Verification never uses `==` on the code alone — it checks a small window and, crucially, refuses a code already spent in this window:

```python
def verify_totp(secret, code, now, *, used: set, step=30, window=1) -> bool:
    for drift in range(-window, window + 1):             # previous, current, next step
        counter = (now // step) + drift
        if hmac.compare_digest(hotp(secret, counter), code):   # constant-time
            if counter in used:                          # already redeemed -> reject replay
                return False
            used.add(counter)
            return True
    return False
```

The full script — the RFC 4226 vector check, TOTP at a fixed timestamp, the skew window, replay rejection, an `otpauth://` enrollment URI, and hashed single-use recovery codes — is in [`code/mfa_totp.py`](code/mfa_totp.py). Run it:

```console
$ python3 mfa_totp.py
== 1 · HOTP MATCHES THE RFC 4226 TEST VECTOR ==
  secret = b'12345678901234567890'  (the RFC's test key)
  counter 0 -> 755224   expected 755224   ok? True
  counter 1 -> 287082   expected 287082   ok? True
  counter 2 -> 359152   expected 359152   ok? True

== 2 · TOTP: THE CODE IS A FUNCTION OF THE CLOCK ==
  at t=1700000000 (step 30) -> counter 56666666 -> code 921300
  30s later                 -> counter 56666667 -> code 732303   (rolled over)

== 3 · VERIFY WITH A ±1 SKEW WINDOW ==
  user's clock 25s slow, submits the previous code -> accepted? True
  a wrong code '000000'                             -> accepted? False

== 4 · REPLAY REJECTION (a code is single-use in its window) ==
  first use of 921300  -> accepted? True
  same code again      -> accepted? False   <- replay blocked

== 5 · ENROLLMENT: SECRET + otpauth:// URI (becomes a QR) ==
  secret (base32): MFRW2ZJNMRSW23ZNMFWGSY3FFVVWK6JB
  otpauth://totp/Acme:alice@acme.com?secret=MFRW2ZJNMRSW23ZNMFWGSY3FFVVWK6JB&issuer=Acme&digits=6&period=30

== 6 · RECOVERY CODES (random, shown once, stored hashed, single-use) ==
  issued:  ce60-fc12  eb34-9882  2e81-d419  ... (10 total, random each run)
  stored:  sha256(code) x10   redeem 'ce60-fc12' -> ok True   reuse -> ok False
```

**Section 1** is the proof of correctness: matching `755224` for counter 0 means your fifteen lines implement HOTP exactly as the RFC defines it — the authenticator app on your phone runs this same computation. **Section 2** shows the code is purely a function of the shared secret and the clock — no communication. **Sections 3 and 4** are the two verification rules that separate a toy from a safe implementation: tolerate a little clock drift, but never accept the same code twice. **Section 5** is enrollment — that URI, rendered as a QR, is exactly what you scan into Google Authenticator. **Section 6** treats recovery codes with the same discipline as passwords: random, hashed, single-use.

## Use It

For TOTP in production, **`pyotp`** is the standard Python library — the same algorithm you just built, with the enrollment URI and verification window handled:

```python
import pyotp

secret = pyotp.random_base32()                     # store this encrypted, per user (Lesson 13)
uri = pyotp.totp.TOTP(secret).provisioning_uri(name="alice@acme.com", issuer_name="Acme")
# render `uri` as a QR code for the user to scan

totp = pyotp.TOTP(secret)
ok = totp.verify(submitted_code, valid_window=1)   # ±1 step; you still enforce one-time use yourself
```

Two responsibilities `pyotp` does *not* cover, and you must: **encrypt the stored secrets** (they're shared secrets — a plaintext leak lets the attacker mint codes), and **enforce single-use** across the window (track redeemed counters, as you did by hand). Pair TOTP with **rate limiting** on the verify endpoint ([Lesson 12](../12-abuse-prevention/)) — six digits is a million guesses, trivial to brute-force without a limit.

For **passkeys / WebAuthn**, do not hand-roll it — use a maintained library (**`py_webauthn`** in Python, and the equivalents elsewhere), because attestation parsing and COSE key handling are exactly the kind of intricate crypto plumbing Lesson 2 warned you to delegate. The server side is two endpoints mirroring the ceremony: *registration* generates a challenge, then verifies and stores the returned public key + credential ID; *authentication* generates a challenge, then verifies the returned signature against the stored public key. The library validates the pieces that make it phishing-proof — that the signed **origin** matches your domain, that the **challenge** is the one you issued (blocking replay), and that a **signature counter** increases (flagging cloned authenticators). The strategic picture for the 2020s: offer TOTP as an accessible, universal second factor, and offer **passkeys** as the strong, phishing-proof option that is steadily becoming the *primary* credential — with recovery codes behind both, guarded as carefully as the factors themselves.

## Think about it

1. Your team ships MFA and account takeovers via credential stuffing drop to nearly zero — but a month later a targeted user is still phished. Walk through how a real-time phishing proxy defeats the TOTP you deployed, and name the one factor type that would have stopped it and exactly why.
2. A password plus a security question ("mother's maiden name") is sometimes called "two-factor." Why is it not MFA in any meaningful sense, and which single compromise takes both?
3. You store TOTP shared secrets so the server can verify codes. A breach leaks your database. Compare precisely what the attacker can do with leaked *TOTP secrets* versus leaked *passkey public keys*, and what that implies about how each should be stored.
4. Recovery codes let a user back in when they lose their phone. Describe how a poorly designed account-recovery flow can turn strong MFA into security theater, and state the rule that keeps recovery from becoming the weakest link.
5. WebAuthn is "phishing-proof" because of origin binding. Concretely, what does the authenticator refuse to do when the user is on `acme-support.com` instead of `acme.com`, and why can't the attacker simply forward the request to the real site the way they forward a TOTP code?

## Key takeaways

- **A password is a shared secret that gets phished, reused, and bulk-guessed — none of which good storage prevents**, because the attacker obtains a *real* password without touching your database. A second factor from a *different* category (something you have/are) is the defense.
- **Second factors are a ladder, not a checkbox.** SMS is phishable and SIM-swappable; **TOTP** removes the telco and SIM-swap risk but the typed code is still phishable; **passkeys/WebAuthn** are the only category that resists phishing itself, via origin binding.
- **TOTP is just an HMAC over the clock** (HOTP + time, RFC 4226/6238): `HMAC-SHA1(secret, now//30)` truncated to six digits, computed identically on both sides with no communication. Verify in a small skew window, in constant time, and **reject reused codes**.
- **The shared secret is TOTP's ceiling**: the server keeps a copy (store it encrypted), and a real-time phishing proxy can relay a typed code within its 30-second window. It stops reuse and bulk guessing and raises the phishing bar — it does not eliminate phishing.
- **WebAuthn/passkeys delete the shared secret**: the device holds the private key, the server stores only the public key (**breach-proof**), and the browser binds each signature to your origin (**phishing-proof**). A passkey is multi-factor in one gesture and is becoming the primary credential, not just a supplement.
- **Every MFA deployment needs a recovery path guarded as strongly as the factor** — one-time codes stored hashed and single-use — because an account-recovery flow that resets MFA on a weak challenge is a bypass. Build TOTP to understand it; deploy passkeys where you can; never hand-roll WebAuthn's crypto.

Next: [Sessions & Secure Cookies](../05-sessions-and-secure-cookies/) — you can now prove *who* a user is at login with one or more factors; next you keep them logged in across requests without re-authenticating every click, and learn why the cookie that remembers them is a credential an attacker will try just as hard to steal.
