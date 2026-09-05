#!/usr/bin/env python3
"""
Password storage done right, from the standard library.

Companion to docs/en.md (Phase 07, Lesson 03). It builds up the real thing:

  * A fast unsalted hash (SHA-256) makes identical passwords identical — and a
    GPU reverses it at ~10^10/sec. Salt fixes correlation; it does not fix speed.
  * The fix for speed is a SLOW hash with a tunable work factor. We build on
    hashlib.pbkdf2_hmac (RFC 8018), which is guaranteed in the stdlib on every
    build; production upgrades to memory-hard Argon2id (see the "Use It" half).
  * Store a self-describing string (algorithm, params, salt, hash) so you can
    verify old hashes and transparently upgrade the work factor on next login.
  * Verify in constant time (hmac.compare_digest), never with `==`.
  * A pepper (HMAC with a secret kept outside the DB) is defense in depth.
  * Breach-check a password WITHOUT sending it, via k-anonymity (HIBP-style).

Stdlib only:  python3 password_hashing.py
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time


# ── Base64 helpers (PHC-style, no padding) ───────────────────────────────────

def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def ub64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ── The hasher: slow, salted, self-describing ────────────────────────────────

ITERATIONS = 600_000                                # the work factor (OWASP 2023 PBKDF2 floor)


def _prehash(password: str, pepper: bytes) -> bytes:
    """Apply the pepper (if any) as HMAC before the slow hash."""
    if pepper:
        return hmac.new(pepper, password.encode(), hashlib.sha256).digest()
    return password.encode()


def hash_password(password: str, *, pepper: bytes = b"", iterations: int = ITERATIONS) -> str:
    salt = secrets.token_bytes(16)                  # unique, random, per password
    dk = hashlib.pbkdf2_hmac("sha256", _prehash(password, pepper), salt, iterations, dklen=32)
    return f"pbkdf2-sha256${iterations}${b64(salt)}${b64(dk)}"   # self-describing


def verify_password(password: str, encoded: str, *, pepper: bytes = b"") -> bool:
    algo, iters, salt_b64, dk_b64 = encoded.split("$")
    salt, expected = ub64(salt_b64), ub64(dk_b64)
    actual = hashlib.pbkdf2_hmac("sha256", _prehash(password, pepper),
                                 salt, int(iters), dklen=len(expected))
    return hmac.compare_digest(actual, expected)    # constant-time, always


def needs_rehash(encoded: str, iterations: int = ITERATIONS) -> bool:
    _, iters, _, _ = encoded.split("$")
    return int(iters) < iterations


# ── Demos ────────────────────────────────────────────────────────────────────

def demo_salt() -> None:
    print("== 1 · UNSALTED FAST HASH LEAKS EQUAL PASSWORDS ==")
    a = hashlib.sha256(b"hunter2").hexdigest()
    b = hashlib.sha256(b"hunter2").hexdigest()
    print(f"  user A sha256(hunter2): {a[:4]}...")
    print(f"  user B sha256(hunter2): {b[:4]}...   equal? {a == b}   <- both crack as one")
    s1 = hashlib.sha256(secrets.token_bytes(16) + b"hunter2").hexdigest()
    s2 = hashlib.sha256(secrets.token_bytes(16) + b"hunter2").hexdigest()
    print(f"  with per-user salt      equal? {s1 == s2}             <- but sha256 is still ~10^10/s")


def demo_real_hash() -> None:
    print("\n== 2 · A REAL HASH: SLOW, SALTED, SELF-DESCRIBING ==")
    stored = hash_password("s3cr3t-passphrase")
    algo, iters, salt, _ = stored.split("$")
    print(f"  stored: {algo}${iters}${salt}$q1F8...   (algorithm, iterations, salt, hash)")
    print(f"  verify correct 's3cr3t-passphrase' -> {verify_password('s3cr3t-passphrase', stored)}")
    print(f"  verify wrong   'wrong-guess'       -> {verify_password('wrong-guess', stored)}")


def demo_work_factor() -> None:
    print("\n== 3 · WORK FACTOR = GUESSES PER SECOND (the whole game) ==")
    # SHA-256 throughput
    t0, n = time.perf_counter(), 0
    while time.perf_counter() - t0 < 0.3:
        hashlib.sha256(b"guess").digest()
        n += 1
    sha_rate = n / (time.perf_counter() - t0)
    # PBKDF2 throughput at the configured work factor
    salt = secrets.token_bytes(16)
    reps = 3
    t0 = time.perf_counter()
    for _ in range(reps):
        hashlib.pbkdf2_hmac("sha256", b"guess", salt, ITERATIONS, dklen=32)
    per_hash = (time.perf_counter() - t0) / reps
    slow_rate = 1 / per_hash
    print(f"  sha256          : {sha_rate:>12,.0f} hashes/sec   (a GPU does ~1000x this)")
    print(f"  pbkdf2 (600k)   : {slow_rate:>12,.2f} hashes/sec   "
          f"(~{per_hash:.2f}s/hash, ~{sha_rate/slow_rate:,.0f}x slower per guess, on purpose)")


def demo_upgrade() -> None:
    print("\n== 4 · TRANSPARENT UPGRADE (rehash on login) ==")
    old = hash_password("s3cr3t-passphrase", iterations=100_000)
    print(f"  old hash used 100000 iterations; policy now {ITERATIONS}")
    print(f"  needs_rehash? {needs_rehash(old)}  -> re-hashed on successful login, no password reset")


def demo_pepper() -> None:
    print("\n== 5 · PEPPER: A SECRET THE DB LEAK DOESN'T INCLUDE ==")
    pepper = secrets.token_bytes(32)                # lives in a secrets manager, NOT the DB
    stored = hash_password("s3cr3t-passphrase", pepper=pepper)
    with_pepper = verify_password("s3cr3t-passphrase", stored, pepper=pepper)
    without = verify_password("s3cr3t-passphrase", stored, pepper=b"")
    print(f"  verify WITH pepper: {with_pepper}   verify WITHOUT (db-only attacker): {without}")
    print(f"  db-only attacker is missing the pepper -> cannot begin cracking")


def demo_kanonymity() -> None:
    print("\n== 6 · BREACH CHECK WITHOUT SENDING THE PASSWORD (k-anonymity) ==")
    # A real check calls HIBP's range API; here the "breach set" is local so it runs offline.
    breached = {hashlib.sha1(b"password").hexdigest().upper(),
                hashlib.sha1(b"123456").hexdigest().upper()}

    def is_breached(pw: str) -> bool:
        full = hashlib.sha1(pw.encode()).hexdigest().upper()
        prefix, suffix = full[:5], full[5:]          # only the prefix would be sent to the API
        candidates = {h[5:] for h in breached if h[:5] == prefix}   # server returns these
        return suffix in candidates                  # matched locally — password never leaves

    weak = hashlib.sha1(b"password").hexdigest().upper()
    print(f"  sha1('password') = {weak}")
    print(f"  send prefix '{weak[:5]}' only; match suffix locally -> breached? {is_breached('password')}")
    strong = "7$Kq!v09-zLm2"
    sp = hashlib.sha1(strong.encode()).hexdigest().upper()
    print(f"  sha1({strong!r}) prefix '{sp[:5]}' -> breached? {is_breached(strong)}")


def main() -> None:
    demo_salt()
    demo_real_hash()
    demo_work_factor()
    demo_upgrade()
    demo_pepper()
    demo_kanonymity()


if __name__ == "__main__":
    main()
