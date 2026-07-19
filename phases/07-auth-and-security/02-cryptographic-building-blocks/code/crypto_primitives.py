#!/usr/bin/env python3
"""
The cryptographic building blocks of the auth phase, from the standard library.

Companion to docs/en.md (Phase 07, Lesson 02). It makes each primitive concrete:

  * Encoding (Base64) is a public, keyless round-trip — it hides nothing.
  * A cryptographic hash (SHA-256, FIPS 180-4) is one-way and avalanches.
  * HMAC (RFC 2104) built BY HAND equals the standard library, byte for byte —
    a MAC gives integrity AND authenticity, unlike a bare hash.
  * Secret comparison must be constant-time (hmac.compare_digest), never `==`.
  * Secrets come from a CSPRNG (secrets / os.urandom), never a seedable PRNG.
  * A password KDF (PBKDF2, RFC 8018) stretches a password slowly, with a salt.

Encryption and signatures are intentionally NOT built here — see the "Use It"
half of the lesson, which uses PyCA `cryptography` (AES-GCM, Ed25519).

Runs on the Python standard library only:  python3 crypto_primitives.py
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import random
import secrets
import time


def rule(n: int, title: str) -> None:
    print(f"\n== {n} · {title} ==")


# ── 1 · Encoding is not secrecy ──────────────────────────────────────────────

def demo_encoding() -> None:
    rule(1, "ENCODING IS NOT SECRECY")
    plaintext = b'{"user":"alice","admin":false}'
    encoded = base64.b64encode(plaintext).decode()
    decoded = base64.b64decode(encoded).decode()
    print(f"  plaintext : {plaintext.decode()}")
    print(f"  base64    : {encoded}")
    print(f"  decoded   : {decoded}   <- anyone reverses it, no key needed")


# ── 2 · Hash: one-way, fixed-size, avalanche ─────────────────────────────────

def bit_diff(a: bytes, b: bytes) -> int:
    """Count differing bits between two equal-length byte strings."""
    return sum(bin(x ^ y).count("1") for x, y in zip(a, b))


def demo_hash() -> None:
    rule(2, "HASH: ONE-WAY, FIXED-SIZE, AVALANCHE")
    a = hashlib.sha256(b"password123").digest()
    b = hashlib.sha256(b"password124").digest()
    print(f'  sha256("password123") = {a.hex()}')
    print(f'  sha256("password124") = {b.hex()}')
    print(f"  bits different: {bit_diff(a, b)} / 256  (~50%, from a 1-character change)")


# ── 3 · HMAC by hand equals the standard library ─────────────────────────────

def hmac_sha256(key: bytes, msg: bytes) -> bytes:
    """HMAC-SHA256 by hand (RFC 2104): H((key^opad) || H((key^ipad) || msg))."""
    block = 64                                     # SHA-256 processes 64-byte blocks
    if len(key) > block:
        key = hashlib.sha256(key).digest()         # long keys are hashed down first
    key = key.ljust(block, b"\x00")                # then zero-padded to one block
    ipad = bytes(k ^ 0x36 for k in key)            # inner pad
    opad = bytes(k ^ 0x5c for k in key)            # outer pad
    inner = hashlib.sha256(ipad + msg).digest()
    return hashlib.sha256(opad + inner).digest()


def demo_hmac_equivalence() -> None:
    rule(3, "HMAC BY HAND == STANDARD LIBRARY")
    key, msg = b"shared-secret-key", b"transfer $10 to bob"
    mine = hmac_sha256(key, msg)
    lib = hmac.new(key, msg, hashlib.sha256).digest()
    print(f"  by hand : {mine.hex()[:8]}...  stdlib : {lib.hex()[:8]}...   "
          f"match: {hmac.compare_digest(mine, lib)}")


# ── 4 · Tamper detection + constant-time verification ────────────────────────

def sign(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


def verify(key: bytes, msg: bytes, tag: bytes) -> bool:
    """Constant-time: always inspects every byte, so timing leaks nothing."""
    return hmac.compare_digest(sign(key, msg), tag)


def demo_tamper() -> None:
    rule(4, "TAMPER DETECTION + CONSTANT-TIME VERIFY")
    key = b"shared-secret-key"
    original = b"transfer $10 to bob"
    tag = sign(key, original)                       # sent alongside the message
    tampered = b"transfer $99 to bob"               # attacker edits the amount
    print(f"  original {original.decode()!r}  tag ok?  {verify(key, original, tag)}")
    print(f"  tampered {tampered.decode()!r}  tag ok?  {verify(key, tampered, tag)}"
          f"   <- integrity + authenticity")


# ── 5 · CSPRNG vs PRNG ───────────────────────────────────────────────────────

def demo_randomness() -> None:
    rule(5, "CSPRNG VS PRNG")
    a = random.Random(1234)
    b = random.Random(1234)
    seq_a = [a.randint(0, 999) for _ in range(3)]
    seq_b = [b.randint(0, 999) for _ in range(3)]
    print(f"  random.Random(1234) run A: {seq_a}")
    print(f"  random.Random(1234) run B: {seq_b}   <- predictable: same seed, same 'secrets'")
    print(f"  secrets.token_hex(16)   : {secrets.token_hex(16)}        <- unrepeatable, unpredictable")


# ── 6 · Key derivation: PBKDF2 stretches a password ──────────────────────────

def demo_kdf() -> None:
    rule(6, "KEY DERIVATION (PBKDF2 stretches a password, slowly, with salt)")
    salt = secrets.token_bytes(16)                  # unique, random, stored alongside the hash
    iterations = 600_000                            # deliberately expensive (OWASP 2023 floor)
    t0 = time.perf_counter()
    key = hashlib.pbkdf2_hmac("sha256", b"correct horse battery staple", salt, iterations)
    dt = time.perf_counter() - t0
    print(f"  salt        : {salt.hex()[:8]}... (16 random bytes)")
    print(f"  derived key : {key.hex()[:8]}...  (32 bytes, {iterations} iterations ~ {dt:.2f}s on purpose)")


def main() -> None:
    demo_encoding()
    demo_hash()
    demo_hmac_equivalence()
    demo_tamper()
    demo_randomness()
    demo_kdf()


if __name__ == "__main__":
    main()
