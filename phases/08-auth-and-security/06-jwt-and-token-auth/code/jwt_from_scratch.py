#!/usr/bin/env python3
"""
A JWT (JSON Web Token, RFC 7519 / JWS RFC 7515) from scratch — and the two
forgeries a naive verifier falls for.

Companion to docs/en.md (Phase 07, Lesson 06). What it makes concrete:

  * A JWT is header.payload.signature, each Base64url. The first two are just
    ENCODED (readable), the signature makes them tamper-proof (Lesson 2).
  * Verification is the whole security. The one rule: never trust the token's
    own `alg` — the server PINS the algorithm. Breaking that rule yields:
      - alg:none      — attacker sets alg=none, empty signature, no check runs.
      - HS/RS confusion — server verifies RS256 with a PUBLIC key; attacker
        signs HS256 using that public key as the HMAC secret.
  * exp is not optional — a stateless token can't be revoked, so it must expire.

Production ships PyJWT with algorithms=[...] pinned (see "Use It"). Stdlib only:
    python3 jwt_from_scratch.py
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json


class BadToken(Exception):
    pass


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def ub64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ── Encode (HS256) ───────────────────────────────────────────────────────────

def encode_hs256(payload: dict, key: bytes) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    compact = lambda d: b64url(json.dumps(d, separators=(",", ":")).encode())
    segments = compact(header) + "." + compact(payload)
    sig = hmac.new(key, segments.encode(), hashlib.sha256).digest()
    return segments + "." + b64url(sig)


# ── The CORRECT verifier: pins the algorithm ─────────────────────────────────

def verify_hs256(token: str, key: bytes, *, now: int, expected_alg: str = "HS256") -> dict:
    header_b64, payload_b64, sig_b64 = token.split(".")
    header = json.loads(ub64(header_b64))
    if header.get("alg") != expected_alg:               # PIN — kills alg:none and HS/RS confusion
        raise BadToken(f"unexpected alg {header.get('alg')!r}")
    expected = hmac.new(key, f"{header_b64}.{payload_b64}".encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(ub64(sig_b64), expected):   # constant-time signature check
        raise BadToken("bad signature")
    claims = json.loads(ub64(payload_b64))
    if "exp" in claims and now >= claims["exp"]:        # expiry is mandatory
        raise BadToken("expired")
    return claims


# ── The NAIVE verifier: trusts the token's alg (every JWT CVE lives here) ─────

def verify_naive(token: str, key: bytes, *, now: int) -> dict:
    header_b64, payload_b64, sig_b64 = token.split(".")
    header = json.loads(ub64(header_b64))
    alg = header.get("alg")                             # <-- trusting attacker-controlled input
    signing_input = f"{header_b64}.{payload_b64}".encode()
    if alg == "none":
        pass                                            # "nothing to verify" — the trap
    elif alg == "HS256":
        expected = hmac.new(key, signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(ub64(sig_b64), expected):
            raise BadToken("bad signature")
    elif alg == "RS256":
        # would RSA-verify with the public key here (see the Use It half)
        raise BadToken("RS256 path not exercised in this stdlib demo")
    else:
        raise BadToken(f"unknown alg {alg!r}")
    return json.loads(ub64(payload_b64))


# ── Demos ────────────────────────────────────────────────────────────────────

SECRET = b"a-256-bit-secret-from-the-vault-01"
NOW = 1_700_000_000


def demo_encode() -> str:
    print("== 1 · ENCODE A JWT (HS256) ==")
    token = encode_hs256({"sub": "alice", "role": "user", "exp": 1_700_000_900}, SECRET)
    head, payload, _ = token.split(".")
    print(f"  token: {'.'.join(token.split('.')[:2])}.<sig>")
    print(f"  header  : {json.dumps(json.loads(ub64(head)))}")
    print(f"  payload : {json.dumps(json.loads(ub64(payload)))}   <- readable by anyone (encoding, not encryption)")
    return token


def demo_correct_verify(token: str) -> None:
    print("\n== 2 · CORRECT VERIFY: signature + expiry, algorithm PINNED ==")
    print(f"  valid token           -> {verify_hs256(token, SECRET, now=NOW)}")
    # tamper: flip the payload to role=admin, keep the old signature
    head, payload, sig = token.split(".")
    forged_payload = b64url(json.dumps({"sub": "alice", "role": "admin", "exp": 1_700_000_900},
                                       separators=(",", ":")).encode())
    tampered = f"{head}.{forged_payload}.{sig}"
    try:
        verify_hs256(tampered, SECRET, now=NOW)
    except BadToken as e:
        print(f"  tampered role=admin   -> rejected: {e}")
    expired = encode_hs256({"sub": "alice", "exp": NOW - 1}, SECRET)
    try:
        verify_hs256(expired, SECRET, now=NOW)
    except BadToken as e:
        print(f"  expired token         -> rejected: {e}")


def demo_alg_none() -> None:
    print("\n== 3 · FORGERY A · alg:none ==")
    header = b64url(b'{"alg":"none","typ":"JWT"}')
    payload = b64url(json.dumps({"sub": "attacker", "role": "admin"}, separators=(",", ":")).encode())
    forged = f"{header}.{payload}."               # empty signature
    print('  crafted: {"alg":"none"} . {"sub":"attacker","role":"admin"} . (empty sig)')
    got = verify_naive(forged, SECRET, now=NOW)
    print(f"  naive verifier (trusts header alg) -> ACCEPTED as role={got['role']}   ✗ forged")
    try:
        verify_hs256(forged, SECRET, now=NOW)
    except BadToken as e:
        print(f"  correct verifier (pins HS256)      -> rejected: {e}   ✓")


def demo_key_confusion() -> None:
    print("\n== 4 · FORGERY B · HS/RS key confusion (the shape of it) ==")
    # The server publishes an RSA PUBLIC key (public by design). Stand it in as bytes.
    public_key = b"-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkq...AB\n-----END PUBLIC KEY-----\n"
    print("  server 'expects' RS256 and verifies with a PUBLIC key (public by design)")
    # Attacker signs an HS256 token using the PUBLIC key as the HMAC secret.
    header = b64url(b'{"alg":"HS256","typ":"JWT"}')
    payload = b64url(json.dumps({"sub": "attacker", "role": "admin"}, separators=(",", ":")).encode())
    sig = b64url(hmac.new(public_key, f"{header}.{payload}".encode(), hashlib.sha256).digest())
    forged = f"{header}.{payload}.{sig}"
    print("  attacker signs HS256 using that public key as the HMAC secret")
    # Naive verifier reads alg=HS256 and HMAC-verifies with the only key it has: the public key.
    got = verify_naive(forged, public_key, now=NOW)
    print(f"  naive verifier (alg from token)    -> ACCEPTED as role={got['role']}   ✗ forged")
    try:
        verify_hs256(forged, public_key, now=NOW, expected_alg="RS256")
    except BadToken as e:
        print(f"  correct verifier (pins RS256)      -> rejected: {e}   ✓")


def main() -> None:
    token = demo_encode()
    demo_correct_verify(token)
    demo_alg_none()
    demo_key_confusion()


if __name__ == "__main__":
    main()
