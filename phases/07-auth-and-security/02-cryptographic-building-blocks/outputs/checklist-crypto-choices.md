---
name: checklist-crypto-choices
description: A decision checklist for reaching for the right cryptographic primitive — which tool for which job (encoding, hashing, MAC, symmetric, asymmetric, KDF), plus the non-negotiable usage rules (CSPRNG, constant-time compare, unique nonces, use the library). Consult before writing any line of security-relevant crypto.
phase: 7
lesson: 02
---

# Crypto Primitive Decision Checklist

Before writing anything that touches secrets, name the *job* first, then pick the tool. Most crypto
bugs are the right effort spent on the wrong primitive.

## Which tool for which job

- [ ] **"Make bytes safe to transport / put in a URL or header."** → **Encoding** (Base64, hex,
      percent-encoding). It is public and reversible. It secures *nothing* — never use it to hide or
      protect a value.
- [ ] **"Fingerprint data / detect accidental corruption / index by content."** → **Hash**
      (SHA-256, SHA-3). One-way, keyless. Not for passwords by itself (see Lesson 3), not for
      authenticating a message from an attacker (use a MAC).
- [ ] **"Prove a message wasn't altered AND came from someone holding our shared secret."** →
      **MAC / HMAC-SHA256**. Keyed, one-way. This signs cookies, JWTs (HS256), API requests, webhooks.
- [ ] **"Keep data secret between two parties who already share a key."** → **Symmetric AEAD**
      (AES-GCM, ChaCha20-Poly1305). Encrypts *and* authenticates. Never a raw/unauthenticated cipher.
- [ ] **"Encrypt to someone using only their public key, or sign so anyone can verify."** →
      **Asymmetric** (Ed25519 / X25519 / RSA / ECDSA). Public key encrypts or verifies; private key
      decrypts or signs. Slower — use it to sign, and to bootstrap a symmetric key.
- [ ] **"Turn a password into a key / store a password."** → **Password KDF** (Argon2id, scrypt,
      bcrypt, PBKDF2). Slow and salted on purpose (Lesson 3).
- [ ] **"Derive several purpose-specific keys from one master secret."** → **HKDF**, with a distinct
      `info` label per purpose. One key, one job.

## Non-negotiable usage rules

- [ ] **Randomness from a CSPRNG only.** `secrets` / `os.urandom` (or the library's key generator).
      Never `random`, `uuid1`, timestamps, or a counter for anything secret: token, salt, key, nonce,
      CSRF token, reset token.
- [ ] **Compare secrets in constant time.** `hmac.compare_digest`, never `==`, for MACs, tokens, and
      hash outputs. A short-circuiting compare leaks the secret through timing.
- [ ] **AEAD, always, for symmetric encryption.** Encryption without authentication lets an attacker
      tamper undetectably. Use AES-GCM / ChaCha20-Poly1305, not AES-CBC alone.
- [ ] **A nonce/IV is unique per encryption under a key.** Fresh from the CSPRNG (or a counter you can
      *prove* never repeats). Nonce reuse in GCM breaks both confidentiality and integrity.
- [ ] **One key, one purpose.** Never reuse an encryption key for signing, or one master secret
      everywhere. Derive per-purpose keys (HKDF); a single leak should not compromise everything.
- [ ] **Bind context into AEAD's associated data** so a valid ciphertext can't be replayed in another
      context (e.g. authenticate `user_id` alongside the encrypted field).

## Don't roll your own

- [ ] Keyless primitives from the **standard library** (`hashlib`, `hmac`, `secrets`).
- [ ] Encryption and signatures from a **vetted library** — PyCA `cryptography`, or libsodium
      (`nacl`). Prefer **misuse-resistant high-level APIs** (Fernet, `SecretBox`) that pick nonce,
      mode, and padding for you.
- [ ] No hand-assembled cipher + mode + padding + MAC in production. No custom hash-of-concatenation
      "MAC" (use HMAC). No inventing a scheme because it "looks random enough."
- [ ] Algorithm agility: record which algorithm/parameters produced each stored value (a version or
      prefix), so you can rotate when a primitive weakens (MD5 → SHA-256 → …).

## The one-line test

> Name the property you need — **transport-safe, fingerprint, integrity+authenticity, confidentiality,
> or a key from a password** — and let the property choose the primitive. If you can't name the
> property, you don't yet know what you're building, and that is the actual bug.
