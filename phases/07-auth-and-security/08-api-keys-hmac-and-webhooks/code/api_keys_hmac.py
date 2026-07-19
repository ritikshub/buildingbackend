#!/usr/bin/env python3
"""
Machine identity: API keys, HMAC request signing, and webhook verification.

Companion to docs/en.md (Phase 07, Lesson 08). What it makes concrete:

  * An API key is a bearer secret: generate from a CSPRNG with a prefix, show it
    ONCE, store only a (fast) hash, verify in constant time. SHA-256 is fine at
    rest because the key is already high-entropy (unlike a password, Lesson 03).
  * HMAC request signing gives authenticity + integrity (the signature covers a
    canonical string incl. a body hash) — and the secret never travels.
  * Signing alone does not stop replay: a captured signed request is still valid.
    A timestamp window + a nonce cache add freshness.
  * Webhooks are inbound requests at a public URL; the signature (Stripe-style,
    HMAC over "timestamp.payload") is the only proof they're genuine.

Stdlib only:  python3 api_keys_hmac.py
"""

from __future__ import annotations

import hashlib
import hmac
import secrets


# ── API keys ─────────────────────────────────────────────────────────────────

def new_api_key(env: str = "live") -> tuple[str, str]:
    secret = secrets.token_urlsafe(24)               # >=128 bits from the CSPRNG
    full = f"sk_{env}_{secret}"                       # shown to the user exactly once
    stored = hashlib.sha256(full.encode()).hexdigest()   # fast hash: key is already high-entropy
    return full, stored


def verify_api_key(presented: str, stored_hash: str) -> bool:
    h = hashlib.sha256(presented.encode()).hexdigest()
    return hmac.compare_digest(h, stored_hash)       # constant-time


# ── HMAC request signing (+ replay protection) ───────────────────────────────

def sign_request(secret: bytes, method: str, path: str, body: bytes, ts: int, nonce: str) -> str:
    canonical = f"{method}\n{path}\n{ts}\n{nonce}\n{hashlib.sha256(body).hexdigest()}"
    return hmac.new(secret, canonical.encode(), hashlib.sha256).hexdigest()


def verify_request(secret, method, path, body, ts, nonce, sig, *, now, seen, window=300) -> str:
    expected = sign_request(secret, method, path, body, ts, nonce)
    if not hmac.compare_digest(sig, expected):       # authenticity + integrity
        return "bad signature"
    if abs(now - ts) > window:                       # freshness: timestamp window
        return "stale (replay window)"
    if nonce in seen:                                # freshness: no reuse
        return "replayed nonce"
    seen.add(nonce)
    return "ok"


# ── Webhook verification (Stripe-style) ──────────────────────────────────────

def sign_webhook(secret: bytes, ts: int, payload: bytes) -> str:
    signed = f"{ts}.".encode() + payload
    return hmac.new(secret, signed, hashlib.sha256).hexdigest()


def verify_webhook(secret: bytes, header: str, payload: bytes, *, now: int, window=300) -> bool:
    parts = dict(kv.split("=", 1) for kv in header.split(","))
    ts, v1 = int(parts["t"]), parts["v1"]
    if abs(now - ts) > window:                       # reject replays of old events
        return False
    expected = sign_webhook(secret, ts, payload)     # recompute over the RAW body
    return hmac.compare_digest(v1, expected)


# ── Demos ────────────────────────────────────────────────────────────────────

NOW = 1_700_000_000


def demo_api_key() -> None:
    print("== 1 · API KEY: PREFIX + SECRET, HASHED AT REST ==")
    full, stored = new_api_key("live")
    prefix = full[:len("sk_live_") + 6]
    print(f"  issued (shown once): {prefix}...   prefix stored: {prefix}")
    print(f"  DB stores hash: {stored[:6]}...   (not the key)")
    print(f"  verify correct key -> {verify_api_key(full, stored)}    "
          f"verify wrong key -> {verify_api_key('sk_live_wrong', stored)}")


def demo_signing() -> None:
    print("\n== 2 · SIGNED REQUEST: TAMPERING BREAKS THE SIGNATURE ==")
    secret, seen = b"partner-shared-secret", set()
    body = b'{"amount":4999}'
    nonce = secrets.token_hex(8)
    sig = sign_request(secret, "POST", "/v1/charges", body, NOW, nonce)
    r = verify_request(secret, "POST", "/v1/charges", body, NOW, nonce, sig, now=NOW, seen=seen)
    print(f'  POST /v1/charges  body={{"amount":4999}}  -> {r}')
    tampered = b'{"amount":999999}'                  # attacker edits the body, keeps the signature
    r2 = verify_request(secret, "POST", "/v1/charges", tampered, NOW, secrets.token_hex(8), sig,
                        now=NOW, seen=seen)
    print(f"  attacker changes amount to 999999        -> {r2}   ✓ (integrity)")


def demo_replay() -> None:
    print("\n== 3 · REPLAY PROTECTION (timestamp + nonce) ==")
    secret, seen = b"partner-shared-secret", set()
    body, nonce = b'{"amount":4999}', "nonce-abc"
    sig = sign_request(secret, "POST", "/v1/charges", body, NOW, nonce)
    print(f"  first delivery of a valid signed request -> "
          f"{verify_request(secret, 'POST', '/v1/charges', body, NOW, nonce, sig, now=NOW, seen=seen)}")
    print(f"  same request replayed (same nonce)       -> "
          f"{verify_request(secret, 'POST', '/v1/charges', body, NOW, nonce, sig, now=NOW, seen=seen)}   ✓")
    old_ts = NOW - 600
    old_sig = sign_request(secret, "POST", "/v1/charges", body, old_ts, "nonce-xyz")
    print(f"  valid signature but timestamp 10 min old -> "
          f"{verify_request(secret, 'POST', '/v1/charges', body, old_ts, 'nonce-xyz', old_sig, now=NOW, seen=seen)}   ✓")


def demo_webhook() -> None:
    print("\n== 4 · WEBHOOK VERIFICATION (Stripe-style) ==")
    secret = b"whsec_test_secret"
    payload = b'{"type":"payment_succeeded","amount":49900,"customer":"cus_123"}'
    v1 = sign_webhook(secret, NOW, payload)
    header = f"t={NOW},v1={v1}"
    print(f"  header: t={NOW},v1={v1[:6]}...")
    print(f"  genuine webhook (correct secret)  -> verified: {verify_webhook(secret, header, payload, now=NOW)}")
    forged = f"t={NOW},v1={sign_webhook(b'attacker-secret', NOW, payload)}"
    print(f"  forged POST (attacker's secret)   -> verified: {verify_webhook(secret, forged, payload, now=NOW)}   ✓ rejected")


def main() -> None:
    demo_api_key()
    demo_signing()
    demo_replay()
    demo_webhook()


if __name__ == "__main__":
    main()
