#!/usr/bin/env python3
"""
Secrets management logic: load from the environment (never code), scan source for
leaked secrets, and rotate a signing key through a versioned keyring.

Companion to docs/en.md (Phase 07, Lesson 13). What it makes concrete:

  * Secrets come from the ENVIRONMENT (twelve-factor), and a missing one fails
    CLOSED — refuse to start rather than default to something insecure.
  * A secret scanner catches hardcoded credentials (AWS keys, Stripe live keys,
    high-entropy values assigned to *_KEY / *_SECRET / *_TOKEN) — exactly what
    GitHub secret scanning / GitGuardian flag before a leak reaches production.
  * Zero-downtime rotation: keys are versioned, you always SIGN with the current
    version and VERIFY against all active versions, with an overlap window so old
    tokens keep working until they're retired (maps to JWT `kid` + JWKS, L6).

Envelope encryption (DEK/KEK/KMS) and dynamic secrets are the "Use It" half.
Stdlib only:  python3 secrets_rotation.py
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets


# ── 1 · Load from the environment, fail closed ───────────────────────────────

def load_secret(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"missing secret {name} — refusing to start")   # fail closed, no default
    return val


# ── 2 · Secret scanning ──────────────────────────────────────────────────────

PATTERNS = [
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Stripe live key", re.compile(r"sk_live_[0-9A-Za-z_-]{20,}")),
    ("high-entropy string assigned to a *_KEY / *_SECRET / *_TOKEN name",
     re.compile(r"""(?i)\w*(?:KEY|SECRET|TOKEN)\s*=\s*['"][A-Za-z0-9+/=_-]{20,}['"]""")),
]


def scan_for_secrets(source: str) -> list[tuple[int, str, str]]:
    findings = []
    for lineno, line in enumerate(source.splitlines(), 1):
        for label, pat in PATTERNS:
            m = pat.search(line)
            if m:
                findings.append((lineno, label, m.group(0)))
                break                               # one finding per line is enough
    return findings


# ── 3 · Versioned keyring for zero-downtime rotation ─────────────────────────

class KeyRing:
    def __init__(self) -> None:
        self.keys: dict[int, bytes] = {}
        self.current = 0

    def add(self, version: int, key: bytes) -> None:    # introduce a new version (start the overlap)
        self.keys[version] = key
        self.current = version

    def retire(self, version: int) -> None:             # end the overlap — old tokens now fail
        self.keys.pop(version, None)

    def sign(self, msg: bytes) -> tuple[int, str]:      # always sign with the CURRENT version
        tag = hmac.new(self.keys[self.current], msg, hashlib.sha256).hexdigest()
        return self.current, tag

    def verify(self, msg: bytes, version: int, tag: str) -> bool:
        key = self.keys.get(version)                    # verify against whichever ACTIVE version signed it
        if key is None:
            return False                                # retired/unknown version → reject
        expected = hmac.new(key, msg, hashlib.sha256).hexdigest()
        return hmac.compare_digest(tag, expected)       # constant-time


# ── Demos ────────────────────────────────────────────────────────────────────

def demo_env() -> None:
    print("== 1 · SECRETS FROM THE ENVIRONMENT, FAIL CLOSED ==")
    os.environ.setdefault("SIGNING_KEY", secrets.token_hex(16))    # injected at runtime by the platform
    key = load_secret("SIGNING_KEY")
    print(f"  load_secret('SIGNING_KEY')     -> loaded from env (len {len(key)})")
    try:
        load_secret("MISSING_SECRET")
    except RuntimeError as e:
        print(f"  load_secret('MISSING_SECRET')  -> RuntimeError: {e}")


def demo_scan() -> None:
    print("\n== 2 · SECRET SCANNING (catch leaks before they're committed) ==")
    source = '''import os
def connect():
    aws = "AKIAIOSFODNN7EXAMPLE"
    stripe = "sk_live_EXAMPLE-not-a-real-key"
    region = "us-east-1"
    timeout = 30
    API_SECRET = "9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c"
    return aws, stripe
'''
    print("  scanning a source file for hardcoded secrets:")
    findings = scan_for_secrets(source)
    for lineno, label, match in findings:
        shown = match if len(match) < 45 else match
        print(f"    line {lineno}: {label if 'high-entropy' in label else label + '   ' + shown}")
    print(f"  -> {len(findings)} findings: block the commit, rotate anything real")


def demo_rotation() -> None:
    print("\n== 3 · KEY ROTATION WITH AN OVERLAP WINDOW ==")
    kr = KeyRing()
    kr.add(1, secrets.token_bytes(32))
    msg = b"session=alice"
    v1_ver, v1_tag = kr.sign(msg)
    print("  v1 active. token signed with v1.")
    print(f"  verify (only v1)          -> {kr.verify(msg, v1_ver, v1_tag)}")

    kr.add(2, secrets.token_bytes(32))                  # introduce v2 → overlap begins
    v2_ver, v2_tag = kr.sign(msg)
    print("  introduce v2 (overlap): sign new tokens with v2")
    print(f"  old v1 token verifies?    -> {kr.verify(msg, v1_ver, v1_tag)}    (overlap: both active)")
    print(f"  new v2 token verifies?    -> {kr.verify(msg, v2_ver, v2_tag)}")

    kr.retire(1)                                        # end overlap
    print("  retire v1.")
    print(f"  old v1 token verifies?    -> {kr.verify(msg, v1_ver, v1_tag)}   (v1 retired — but it had already expired)")
    print(f"  new v2 token verifies?    -> {kr.verify(msg, v2_ver, v2_tag)}    (rotation complete, no downtime)")


def main() -> None:
    demo_env()
    demo_scan()
    demo_rotation()


if __name__ == "__main__":
    main()
