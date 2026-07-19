---
name: checklist-oauth-oidc
description: Integration checklist for OAuth 2.0 and OIDC as a client — pick the right flow (Authorization Code + PKCE), enforce state/PKCE/nonce, keep OAuth (authorization) and OIDC (authentication) distinct, verify the ID token, request minimal scopes, and never build your own authorization server. Run when adding "Sign in with X" or third-party API access.
phase: 7
lesson: 07
---

# OAuth 2.0 / OIDC Client Checklist

You are almost always the **client**, not the authorization server. Getting these right is the job.

## 1 — Pick the right flow

- [ ] **Authorization Code + PKCE** for web apps, SPAs, and mobile — the default for essentially
      everything (and the OAuth 2.1 default).
- [ ] **Client Credentials** for machine-to-machine (no user / no resource owner).
- [ ] **Device Authorization** for input-constrained devices (TV, CLI).
- [ ] **Do NOT use** the Implicit grant (token in the URL) or Resource Owner Password grant (client
      collects the password) — both are removed in OAuth 2.1.

## 2 — The security parameters (every time)

- [ ] **PKCE** on every authorization request: send `code_challenge` (S256 of a random verifier the
      client keeps); present the verifier at the token endpoint. Use it even for confidential clients.
- [ ] **`state`**: random, stored in the session, verified on callback — reject on mismatch/missing
      (CSRF protection for the redirect).
- [ ] **`nonce`** (OIDC): random, sent in the request, and checked against the ID token's `nonce`
      claim (binds the token to this request).
- [ ] The authorization **code is single-use** and short-lived; exchange it over the **back channel**
      (server-to-server), never expose the token in a URL.

## 3 — Tokens

- [ ] **Access token = authorization.** Treat it as **opaque** — don't parse it to identify the user.
      Send it as `Authorization: Bearer` to the resource server; keep it short-lived.
- [ ] **Refresh token**: store securely (server-side), rotate on use, revoke on logout / password
      change / suspected theft.
- [ ] Request the **narrowest scopes** you actually need (least privilege = the consent screen).
- [ ] At the resource server, **enforce scope** per endpoint (read scope can't write).

## 4 — Login with OIDC (authentication)

- [ ] Use the **ID token** (not the access token) to establish who the user is.
- [ ] **Verify the ID token** fully: signature via the issuer's **JWKS**, `iss` == expected issuer,
      **`aud` == your client_id**, `exp` not passed, `nonce` matches. (Never trust an unverified ID token.)
- [ ] Use OIDC **discovery** (`/.well-known/openid-configuration`) to get endpoints and JWKS.
- [ ] The stable user identifier is **`sub`** (+ `iss`), not `email` (which can change / be unverified).
- [ ] Never accept "a valid access token exists" as proof of identity (access-token-as-login bug).

## 5 — Configuration & operations

- [ ] Register **exact redirect URIs** (no wildcards); the authorization server must match them strictly.
- [ ] `client_secret` (confidential clients) lives in a **secret store** (Lesson 13), never in the
      browser or a public repo. Public clients (SPA/mobile) use PKCE and hold no secret.
- [ ] Use an established **provider** (Auth0, Okta, Keycloak, Google, Entra, Cognito) and a **vetted
      library** (Authlib, etc.). **Do not build your own authorization server.**
- [ ] Handle logout properly (clear local session; use OIDC RP-initiated logout if needed); revoke
      tokens where the provider supports it.

## The one distinction to keep straight

> **OAuth authorizes; OIDC authenticates.** Reach for OAuth when your app must *act on a user's
> behalf at an API*; reach for OIDC when your app must *know who the user is*. Same flow, different
> token consumed — the access token for the API, the ID token for login.
