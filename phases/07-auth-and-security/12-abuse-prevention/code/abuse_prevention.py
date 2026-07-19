#!/usr/bin/env python3
"""
A login-abuse defender: the strategy-level controls that stop credential
stuffing, brute force, and account takeover — layered on Phase 2's rate-limit
algorithms (which this does NOT re-implement).

Companion to docs/en.md (Phase 07, Lesson 12). What it makes concrete:

  * Uniform responses (same message + timing for unknown-user and wrong-password)
    so an attacker can't enumerate which accounts exist.
  * Progressive backoff instead of hard lockout — the account never fully locks,
    so an attacker can't DoS a victim by failing their login on purpose.
  * A CAPTCHA/challenge triggered only on SUSPICION (adaptive friction), not for
    every user.
  * Credential-stuffing detection: one IP touching many distinct accounts.
  * Breach-password screening + MFA — the two account-takeover killers, because
    a stuffing attacker holds CORRECT passwords.

Stdlib only:  python3 abuse_prevention.py
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field


def hash_pw(pw: str) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), b"demo-salt", 10_000)


USERS = {"alice@acme.com": {"hash": hash_pw("correct-horse-battery")}}
BREACHED = {"password123", "hunter2", "correct-horse-battery"}   # known-leaked (HIBP-style, Lesson 3)


def verify_password(password: str, user: dict | None) -> bool:
    computed = hash_pw(password)                    # ALWAYS run the hash — timing must not leak
    if user is None:
        return False
    return hmac.compare_digest(computed, user["hash"])


# ── Per-IP / per-account abuse state ─────────────────────────────────────────

@dataclass
class IPState:
    failures: int = 0
    distinct_accounts: set = field(default_factory=set)
    blocked_until: float = 0.0


def backoff_delay(failures: int) -> float:
    return 0.0 if failures <= 3 else min(2 ** (failures - 1), 30)   # 0,0,0,8,16,30s — never a hard lock


def require_captcha(ip: IPState) -> bool:
    return ip.failures >= 5 or len(ip.distinct_accounts) >= 10       # friction only when suspicious


def is_stuffing(ip: IPState, threshold: int = 10) -> bool:
    return len(ip.distinct_accounts) >= threshold                    # one IP, many accounts


# ── The login flow ───────────────────────────────────────────────────────────

def login(email: str, password: str, *, now: float, ip: str, states: dict,
          captcha_solved: bool = False) -> str:
    st = states.setdefault(ip, IPState())
    st.distinct_accounts.add(email)
    if require_captcha(st) and not captcha_solved:
        return "captcha_required"
    if now < st.blocked_until:
        return "slow_down"
    user = USERS.get(email)
    if not verify_password(password, user):
        st.failures += 1
        st.blocked_until = now + backoff_delay(st.failures)
        return "invalid email or password"          # identical for unknown user AND wrong password
    if password in BREACHED:
        return "reset_required: password found in a breach"   # correct pw, but known-leaked
    return "ok (then require MFA)"                   # a correct password is not the end — MFA next


# ── Demos ────────────────────────────────────────────────────────────────────

def demo_uniform() -> None:
    print("== 1 · UNIFORM RESPONSES (no user enumeration) ==")
    st: dict = {}
    print(f"  wrong password for real user  -> {login('alice@acme.com', 'wrong', now=0, ip='a', states=st)!r}")
    print(f"  login for a non-existent user -> {login('ghost@acme.com', 'wrong', now=0, ip='b', states=st)!r}"
          "   (same message + timing)")


def demo_backoff() -> None:
    print("\n== 2 · PROGRESSIVE BACKOFF, NOT LOCKOUT ==")
    delays = [backoff_delay(f) for f in range(1, 7)]
    print(f"  fails 1..6 -> delay: {delays} s   (grows, but the account never hard-locks)")
    print("  a legitimate user can still get in after waiting; no attacker-triggered lockout")


def demo_captcha() -> None:
    print("\n== 3 · CAPTCHA ONLY WHEN SUSPICIOUS ==")
    normal = IPState()
    print(f"  normal user (0 fails)                 -> captcha? {require_captcha(normal)}")
    failed = IPState(failures=5)
    print(f"  after 5 failures on this IP           -> captcha? {require_captcha(failed)}")
    spread = IPState(distinct_accounts={f"u{i}@x.com" for i in range(10)})
    print(f"  one IP hitting 10 distinct accounts   -> captcha? {require_captcha(spread)}   (credential-stuffing shape)")


def demo_stuffing() -> None:
    print("\n== 4 · CREDENTIAL STUFFING DETECTION ==")
    st: dict = {}
    for i in range(12):
        login(f"victim{i}@acme.com", "leaked-pw", now=0, ip="203.0.113.9", states=st, captcha_solved=True)
    flagged = is_stuffing(st["203.0.113.9"])
    print(f"  IP 203.0.113.9 tried {len(st['203.0.113.9'].distinct_accounts)} distinct accounts in the window "
          f"-> {'flagged as stuffing  ✓' if flagged else 'not flagged'}")
    normal = {}
    login("alice@acme.com", "x", now=0, ip="198.51.100.7", states=normal)
    print(f"  a normal user tries 1-2 accounts -> "
          f"{'flagged' if is_stuffing(normal['198.51.100.7']) else 'not flagged'}")


def demo_breach_mfa() -> None:
    print("\n== 5 · BREACH-PASSWORD SCREENING + MFA ==")
    st: dict = {}
    r1 = login("alice@acme.com", "correct-horse-battery", now=0, ip="c", states=st)
    print(f"  login with correct BUT breached password -> {r1!r}")
    USERS["bob@acme.com"] = {"hash": hash_pw("Zx9$clean-passphrase")}
    r2 = login("bob@acme.com", "Zx9$clean-passphrase", now=0, ip="d", states=st)
    print(f"  login with correct, clean password       -> {r2!r}   <- MFA still required")


def main() -> None:
    demo_uniform()
    demo_backoff()
    demo_captcha()
    demo_stuffing()
    demo_breach_mfa()


if __name__ == "__main__":
    main()
