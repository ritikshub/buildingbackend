#!/usr/bin/env python3
"""
Time-based one-time passwords (the authenticator-app code) from scratch.

Companion to docs/en.md (Phase 07, Lesson 04). What it makes concrete:

  * HOTP (RFC 4226) is just HMAC-SHA1 over a counter, squeezed to 6 digits by
    "dynamic truncation" — and we prove it against the RFC's official test
    vector (counter 0 of key '12345678901234567890' must be 755224).
  * TOTP (RFC 6238) is HOTP with the counter = current_time // 30, so the two
    sides agree with no communication and no synchronized state.
  * Verification allows a small clock-skew window, compares in constant time,
    and REJECTS a code already spent in its window (replay).
  * Enrollment ships an otpauth:// URI (rendered as a QR the app scans).
  * Recovery codes are random, stored hashed, and single-use — like passwords.

Production ships pyotp / py_webauthn (see the "Use It" half). Stdlib only:
    python3 mfa_totp.py
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import urllib.parse


# ── HOTP / TOTP (RFC 4226 / RFC 6238) ────────────────────────────────────────

def hotp(secret: bytes, counter: int, digits: int = 6) -> str:
    mac = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()  # 20 bytes
    offset = mac[-1] & 0x0F                              # last nibble picks the offset
    chunk = mac[offset:offset + 4]                       # 4 bytes from there
    number = struct.unpack(">I", chunk)[0] & 0x7FFFFFFF  # clear the top bit -> 31-bit int
    return str(number % (10 ** digits)).zfill(digits)    # zero-padded 6-digit string


def totp(secret: bytes, now: int, step: int = 30, digits: int = 6) -> str:
    return hotp(secret, now // step, digits)             # the counter is just the clock


def verify_totp(secret: bytes, code: str, now: int, *, used: set,
                step: int = 30, window: int = 1) -> bool:
    for drift in range(-window, window + 1):             # previous, current, next step
        counter = (now // step) + drift
        if hmac.compare_digest(hotp(secret, counter), code):   # constant-time
            if counter in used:                          # already redeemed -> reject replay
                return False
            used.add(counter)
            return True
    return False


# ── Enrollment ───────────────────────────────────────────────────────────────

def new_secret(nbytes: int = 20) -> bytes:
    return secrets.token_bytes(nbytes)


def b32(secret: bytes) -> str:
    return base64.b32encode(secret).decode().rstrip("=")


def otpauth_uri(secret: bytes, account: str, issuer: str) -> str:
    # ':' and '@' are legal in a URI path segment (RFC 3986), so the label stays
    # readable — exactly the form an authenticator app displays.
    label = f"{issuer}:{account}"
    return (f"otpauth://totp/{label}?secret={b32(secret)}"
            f"&issuer={urllib.parse.quote(issuer)}&digits=6&period=30")


# ── Recovery codes ───────────────────────────────────────────────────────────

def new_recovery_codes(n: int = 10) -> list[str]:
    return [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(n)]


def store_recovery(codes: list[str]) -> set:
    return {hashlib.sha256(c.encode()).hexdigest() for c in codes}   # store hashed


def redeem_recovery(code: str, store: set) -> bool:
    h = hashlib.sha256(code.encode()).hexdigest()
    if h in store:
        store.remove(h)                                  # single-use
        return True
    return False


# ── Demos ────────────────────────────────────────────────────────────────────

RFC_KEY = b"12345678901234567890"                        # the RFC 4226 test key
RFC_VECTORS = {0: "755224", 1: "287082", 2: "359152"}


def demo_rfc_vectors() -> None:
    print("== 1 · HOTP MATCHES THE RFC 4226 TEST VECTOR ==")
    print(f"  secret = {RFC_KEY!r}  (the RFC's test key)")
    for counter, expected in RFC_VECTORS.items():
        got = hotp(RFC_KEY, counter)
        print(f"  counter {counter} -> {got}   expected {expected}   ok? {got == expected}")


def demo_totp_clock() -> None:
    print("\n== 2 · TOTP: THE CODE IS A FUNCTION OF THE CLOCK ==")
    t = 1_700_000_000
    print(f"  at t={t} (step 30) -> counter {t // 30} -> code {totp(RFC_KEY, t)}")
    print(f"  30s later                 -> counter {(t + 30) // 30} -> code {totp(RFC_KEY, t + 30)}   (rolled over)")


def demo_skew() -> None:
    print("\n== 3 · VERIFY WITH A ±1 SKEW WINDOW ==")
    t = 1_700_000_000
    prev_code = totp(RFC_KEY, t - 30)                    # code the user's slow clock still shows
    print(f"  user's clock 25s slow, submits the previous code -> accepted? "
          f"{verify_totp(RFC_KEY, prev_code, t, used=set())}")
    print(f"  a wrong code '000000'                             -> accepted? "
          f"{verify_totp(RFC_KEY, '000000', t, used=set())}")


def demo_replay() -> None:
    print("\n== 4 · REPLAY REJECTION (a code is single-use in its window) ==")
    t = 1_700_000_000
    used: set = set()
    code = totp(RFC_KEY, t)
    print(f"  first use of {code}  -> accepted? {verify_totp(RFC_KEY, code, t, used=used)}")
    print(f"  same code again      -> accepted? {verify_totp(RFC_KEY, code, t, used=used)}   <- replay blocked")


def demo_enrollment() -> None:
    print("\n== 5 · ENROLLMENT: SECRET + otpauth:// URI (becomes a QR) ==")
    secret = b"acme-demo-alice-key!"                     # fixed here so output is reproducible;
    #                                                      production uses new_secret() (CSPRNG)
    print(f"  secret (base32): {b32(secret)}")
    print(f"  {otpauth_uri(secret, 'alice@acme.com', 'Acme')}")


def demo_recovery() -> None:
    print("\n== 6 · RECOVERY CODES (random, shown once, stored hashed, single-use) ==")
    codes = new_recovery_codes()
    store = store_recovery(codes)
    print(f"  issued:  {codes[0]}  {codes[1]}  {codes[2]}  ... ({len(codes)} total)")
    first = codes[0]
    print(f"  stored:  sha256(code) x{len(store)}   redeem {first!r} -> ok {redeem_recovery(first, store)}"
          f"   reuse -> ok {redeem_recovery(first, store)}")


def main() -> None:
    demo_rfc_vectors()
    demo_totp_clock()
    demo_skew()
    demo_replay()
    demo_enrollment()
    demo_recovery()


if __name__ == "__main__":
    main()
