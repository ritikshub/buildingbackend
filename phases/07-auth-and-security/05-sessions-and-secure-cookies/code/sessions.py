#!/usr/bin/env python3
"""
Sessions and secure cookies from scratch.

Companion to docs/en.md (Phase 07, Lesson 05). Two strategies, side by side:

  * Server-side sessions: an opaque, CSPRNG session ID (a bearer token) keyed to
    server-held data. Rotating the ID at login defeats session fixation; idle and
    absolute timeouts bound its life; logout is a real server-side deletion.
  * Signed cookies (stateless): the payload is made TAMPER-EVIDENT with an HMAC
    (Lesson 2), not secret — the client can read it but not forge it. This is the
    JWT idea of Lesson 6 in miniature.

The cookie's security lives in its attributes: HttpOnly, Secure, SameSite, and
the __Host- prefix. Stdlib only:  python3 sessions.py
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def ub64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ── Server-side sessions ─────────────────────────────────────────────────────

class SessionStore:
    def __init__(self, idle: int = 1800, absolute: int = 86400) -> None:
        self._store: dict[str, dict] = {}
        self.idle, self.absolute = idle, absolute

    def new(self, now: int, **data) -> str:
        sid = secrets.token_urlsafe(32)              # 256 bits from the CSPRNG, opaque
        self._store[sid] = {**data, "created": now, "seen": now}
        return sid

    def get(self, sid: str, now: int) -> dict | None:
        s = self._store.get(sid)
        if s is None:
            return None
        if now - s["seen"] > self.idle or now - s["created"] > self.absolute:
            self._store.pop(sid, None)               # expired on either clock
            return None
        s["seen"] = now                              # sliding idle window
        return s

    def rotate(self, old_sid: str, now: int) -> str:
        """On login / privilege change: new ID, same data — defeats fixation."""
        data = self._store.pop(old_sid, {})
        for k in ("created", "seen"):
            data.pop(k, None)
        return self.new(now, **data)

    def destroy(self, sid: str) -> None:
        self._store.pop(sid, None)                    # logout is a real deletion


def set_cookie(sid: str, max_age: int = 1209600) -> str:
    # The security IS the attributes. (http.cookies.SimpleCookie can emit these too.)
    return f"__Host-sid={sid}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age={max_age}"


# ── Signed cookies (stateless, tamper-evident) ───────────────────────────────

def sign(payload: bytes, key: bytes) -> str:
    tag = hmac.new(key, payload, hashlib.sha256).digest()
    return b64(payload) + "." + b64(tag)


def unsign(token: str, key: bytes) -> bytes | None:
    body, tag = token.split(".")
    expected = hmac.new(key, ub64(body), hashlib.sha256).digest()
    if hmac.compare_digest(ub64(tag), expected):     # constant-time
        return ub64(body)
    return None                                       # tampered -> None


# ── Demos ────────────────────────────────────────────────────────────────────

def demo_server_side() -> None:
    print("== 1 · SERVER-SIDE SESSION: OPAQUE ID, DATA STAYS SERVER-SIDE ==")
    store = SessionStore()
    sid = store.new(now=0, user="alice", roles=["user"])
    print(f"  sid = {sid[:8]}... ({len(sid)} chars, 256 bits) — encodes nothing")
    print(f"  Set-Cookie: {set_cookie(sid).replace(sid, sid[:8] + '...')}")
    print(f"  lookup -> {{'user': {store.get(sid, 1)['user']!r}, 'roles': {store.get(sid, 1)['roles']}, ...}}")


def demo_fixation() -> None:
    print("\n== 2 · ROTATION ON LOGIN DEFEATS SESSION FIXATION ==")
    store = SessionStore()
    pre = store.new(now=0, user=None)                 # anonymous pre-login session
    print(f"  pre-login sid  {pre[:6]}... valid before login? {store.get(pre, 1) is not None}")
    new = store.rotate(pre, now=1)                    # login rotates the ID
    print(f"  after login rotate -> new sid {new[:6]}...")
    print(f"  attacker's pre-login sid still valid? {store.get(pre, 2) is not None}   <- fixation defeated")


def demo_expiry() -> None:
    print("\n== 3 · EXPIRY ON TWO CLOCKS (idle + absolute) ==")
    store = SessionStore(idle=1800, absolute=86400)   # 30 min idle, 24 h absolute
    sid = store.new(now=0, user="alice")
    print(f"  active within idle window   -> session alive? {store.get(sid, 60) is not None}")
    sid2 = store.new(now=0, user="alice")
    print(f"  idle 31 min (idle=30)       -> session alive? {store.get(sid2, 31 * 60) is not None}   <- idle timeout")
    sid3 = store.new(now=0, user="alice")
    # touch it periodically so idle never trips, but let absolute age pass
    for t in range(0, 25 * 3600, 1500):
        store.get(sid3, t)
    print(f"  active but 25h old (abs=24h)-> session alive? {store.get(sid3, 25 * 3600) is not None}   <- absolute timeout")


def demo_signed_cookie() -> None:
    print("\n== 4 · SIGNED COOKIE (stateless, tamper-evident, NOT secret) ==")
    key = b"server-signing-key-from-secrets-manager"
    token = sign(b'{"user":"alice"}', key)
    print(f"  token: {token[:22]}...")
    payload = unsign(token, key)
    print(f"  server reads payload: {payload.decode()}   valid? {payload is not None}")
    body, tag = token.split(".")
    forged = b64(b'{"user":"admin"}') + "." + tag     # attacker edits payload, keeps old tag
    print(f"  attacker edits payload to admin           valid? {unsign(forged, key) is not None}   <- HMAC rejects it")


def demo_guessing() -> None:
    print("\n== 5 · WHY THE ID MUST BE RANDOM (guessing) ==")
    print("  sequential IDs: 'session_1','session_2',... -> attacker enumerates in seconds")
    print(f"  256-bit CSPRNG id: 2^256 space -> guessing is infeasible")


def main() -> None:
    demo_server_side()
    demo_fixation()
    demo_expiry()
    demo_signed_cookie()
    demo_guessing()


if __name__ == "__main__":
    main()
