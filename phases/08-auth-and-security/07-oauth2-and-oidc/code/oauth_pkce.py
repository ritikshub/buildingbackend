#!/usr/bin/env python3
"""
The OAuth 2.0 Authorization Code flow with PKCE (RFC 6749 / RFC 7636), simulated
in-process so the security steps are visible without a network.

Companion to docs/en.md (Phase 07, Lesson 07). What it makes concrete:

  * Four roles: resource owner (user), client (app), authorization server,
    resource server.
  * PKCE: the client keeps a random code_verifier and sends only its SHA-256
    hash (code_challenge). A stolen authorization code is useless without the
    verifier, which never left the client.
  * state: a random value the client checks on callback — CSRF protection.
  * The access token authorizes (scopes at the resource server); the OIDC
    id_token (a JWT, Lesson 6) authenticates (who the user is, for the client).

Stdlib only:  python3 oauth_pkce.py
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def sha256_challenge(verifier: str) -> str:
    return b64url(hashlib.sha256(verifier.encode()).digest())     # PKCE "S256"


class OAuthError(Exception):
    pass


# ── Authorization server (issues codes + tokens) ─────────────────────────────

class AuthServer:
    ISSUER = "https://auth.acme.example"
    ID_KEY = b"auth-server-id-token-signing-key"

    def __init__(self) -> None:
        self._codes: dict[str, dict] = {}
        self._access: dict[str, str] = {}            # access_token -> granted scope

    def authorize(self, client_id, redirect_uri, scope, code_challenge) -> str:
        # The user authenticates and consents here (simulated as success).
        code = secrets.token_urlsafe(24)
        self._codes[code] = dict(client_id=client_id, redirect_uri=redirect_uri,
                                 scope=scope, challenge=code_challenge, used=False)
        return code                                  # returned to the client via browser redirect

    def token(self, code, code_verifier, client_id, redirect_uri) -> dict:
        c = self._codes.get(code)
        if not c or c["used"]:
            raise OAuthError("invalid_grant: unknown or used code")
        if c["client_id"] != client_id or c["redirect_uri"] != redirect_uri:
            raise OAuthError("invalid_grant: client/redirect mismatch")
        c["used"] = True                             # authorization codes are single-use
        if sha256_challenge(code_verifier) != c["challenge"]:
            raise OAuthError("invalid_grant: PKCE mismatch")   # the whole point of PKCE
        access = "at_" + secrets.token_urlsafe(12)
        self._access[access] = c["scope"]
        out = {"access_token": access, "scope": c["scope"], "token_type": "Bearer"}
        if "openid" in c["scope"].split():
            out["id_token"] = self._id_token(sub="u_alice", aud=client_id)
        return out

    def introspect(self, access_token: str) -> str | None:
        return self._access.get(access_token)        # resource server asks: valid? what scope?

    def _id_token(self, sub: str, aud: str) -> str:  # a minimal OIDC ID token (HS256 JWT)
        header = b64url(b'{"alg":"HS256","typ":"JWT"}')
        payload = b64url(json.dumps({"iss": self.ISSUER, "sub": sub, "aud": aud,
                                     "nonce": "n-abc", "exp": 1_700_000_900},
                                    separators=(",", ":")).encode())
        sig = b64url(hmac.new(self.ID_KEY, f"{header}.{payload}".encode(), hashlib.sha256).digest())
        return f"{header}.{payload}.{sig}"


# ── Resource server (the API holding the photos) ─────────────────────────────

class ResourceServer:
    def __init__(self, auth: AuthServer) -> None:
        self.auth = auth
        self.photos = ["beach.jpg", "cat.png"]

    def get_photos(self, access_token: str, action: str = "read"):
        scope = self.auth.introspect(access_token)
        if scope is None:
            return 401, "invalid_token"
        if action == "read" and "photos.read" in scope.split():
            return 200, self.photos
        if action == "write" and "photos.write" in scope.split():
            return 200, "deleted"
        return 403, "insufficient_scope"


# ── Client (the photo-printing app) ──────────────────────────────────────────

class Client:
    CLIENT_ID = "photo-print-app"
    REDIRECT = "https://app.example/callback"

    def __init__(self) -> None:
        self.verifier = secrets.token_urlsafe(48)    # the secret, never sent
        self.challenge = sha256_challenge(self.verifier)
        self.state = secrets.token_urlsafe(12)

    def check_state(self, returned_state: str) -> bool:
        return hmac.compare_digest(self.state, returned_state)


# ── Demo ─────────────────────────────────────────────────────────────────────

def main() -> None:
    auth, client = AuthServer(), Client()
    rs = ResourceServer(auth)
    scope = "openid photos.read"

    print("== 1 · CLIENT STARTS THE FLOW (PKCE) ==")
    print(f"  code_verifier  (secret, stays in client): {client.verifier[:4]}...  ({len(client.verifier)} chars)")
    print(f"  code_challenge (sent in the request)    : {client.challenge[:4]}...  = SHA256(verifier)")
    print(f"  state          (CSRF protection)        : {client.state[:4]}...")

    print("\n== 2 · AUTH SERVER: user consents -> one-time authorization code ==")
    code = auth.authorize(client.CLIENT_ID, client.REDIRECT, scope, client.challenge)
    returned_state = client.state                    # comes back on the redirect
    print(f"  redirect back -> /callback?code={code[:4]}...&state={returned_state[:4]}...")
    print(f"  state matches what the client stored? {client.check_state(returned_state)}")

    print("\n== 3 · CLIENT EXCHANGES CODE + VERIFIER (back channel) ==")
    tokens = auth.token(code, client.verifier, client.CLIENT_ID, client.REDIRECT)
    print(f"  POST /token (code + code_verifier)")
    print(f"  -> access_token: {tokens['access_token'][:8]}... (scope: {tokens['scope']})")
    idt = tokens["id_token"]
    claims = json.loads(base64.urlsafe_b64decode(idt.split('.')[1] + "=="))
    print(f"  -> id_token (OIDC JWT): {idt[:8]}...  sub={claims['sub']}  aud={claims['aud']}")

    print("\n== 4 · STOLEN CODE WITHOUT THE VERIFIER (PKCE defeats it) ==")
    # Attacker intercepts the code (step 4) but lacks the verifier. Fresh flow to get an unused code:
    code2 = auth.authorize(client.CLIENT_ID, client.REDIRECT, scope, client.challenge)
    try:
        auth.token(code2, "attacker-guessed-verifier", client.CLIENT_ID, client.REDIRECT)
    except OAuthError as e:
        print(f"  attacker replays the code with a guessed verifier -> {e}  ✓")

    print("\n== 5 · FORGED CALLBACK WITH WRONG state (CSRF defeated) ==")
    print(f"  callback state 'evil' vs stored '{client.state[:4]}...' -> "
          f"{'accepted' if client.check_state('evil') else 'rejected'}  ✓")

    print("\n== 6 · CALL THE RESOURCE SERVER WITH THE ACCESS TOKEN ==")
    at = tokens["access_token"]
    status, body = rs.get_photos(at, "read")
    print(f"  GET /photos  Authorization: Bearer {at[:8]}...")
    print(f"  -> {status}  {body}   (scope photos.read allowed)")
    status, body = rs.get_photos(at, "write")
    print(f"  GET /photos (delete)  -> {status} {body}   (photos.read can't write)")


if __name__ == "__main__":
    main()
