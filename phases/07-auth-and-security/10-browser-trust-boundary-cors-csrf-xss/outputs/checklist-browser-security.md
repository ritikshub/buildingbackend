---
name: checklist-browser-security
description: Checklist for the browser trust boundary — configure CORS with an allowlist (never * with credentials), defend CSRF with SameSite + tokens, prevent XSS with output encoding + CSP, and set the auth-cookie flags. Run for any web front-end or browser-consumed API.
phase: 7
lesson: 10
---

# Browser Security Checklist

The browser runs any script on your page and auto-attaches cookies to your domain. These are the
server-side controls that make that safe. Mostly: turn the protections ON and don't bypass them.

## 1 — Same-Origin Policy & CORS

- [ ] CORS uses an **explicit origin allowlist**; the server reflects the `Origin` only if it's on the
      list. **Never `Access-Control-Allow-Origin: *` with credentials.**
- [ ] Add **`Vary: Origin`** so shared caches don't serve one origin's CORS grant to another.
- [ ] Scope `Access-Control-Allow-Methods` / `Allow-Headers` to what you actually use; handle the
      **preflight** `OPTIONS`.
- [ ] Remember **CORS protects browsers, not your server** — it is NOT authentication or authorization.
      Enforce real access control server-side on every request (Lesson 9).

## 2 — CSRF (for cookie-authenticated requests)

- [ ] Auth cookie is **`SameSite=Lax` (or Strict)** — the first and biggest defense (Lesson 5).
- [ ] State-changing requests require an **unforgeable CSRF token** (synchronizer or double-submit)
      that the server issues and verifies; the attacker's page can't read it (SOP).
- [ ] **Check `Origin`/`Referer`** on state-changing requests; reject cross-site origins.
- [ ] Only **`POST`/`PUT`/`PATCH`/`DELETE`** change state — `GET` is safe/idempotent, so a `GET` never
      mutates (a `GET` that deletes is CSRF-able via an `<img>` tag).
- [ ] If you use **token-in-header** auth (not auto-sent cookies), you're largely CSRF-resistant — but
      the moment auth lives in a cookie, CSRF is back; don't mix carelessly.

## 3 — XSS

- [ ] **Encode all output, context-aware** (HTML body, attribute, URL, JS, CSS each differ). Rely on
      the template engine's **auto-escaping** (Jinja2, Django, React JSX) — on by default.
- [ ] Treat every **escape bypass** as a security review item: `|safe`, `dangerouslySetInnerHTML`,
      `v-html`, `mark_safe`, building HTML by string concatenation.
- [ ] If you must accept **rich HTML**, run it through a **sanitizer** (`nh3`/`bleach` server-side,
      `DOMPurify` client-side) — never trust user HTML.
- [ ] Ship a **Content-Security-Policy**: start `report-only` to find violations, then enforce
      `script-src 'self'` (avoid `'unsafe-inline'` / `'unsafe-eval'`), `object-src 'none'`,
      `frame-ancestors 'none'`. This is the safety net when an encode is missed.
- [ ] Don't put secrets/tokens where an XSS can read them: prefer **`HttpOnly` cookies** over
      `localStorage` for auth (Lesson 6).

## 4 — Cookie flags (auth cookies)

- [ ] **`HttpOnly`** (XSS can't read it), **`Secure`** (HTTPS only), **`SameSite`** (CSRF), and the
      **`__Host-` prefix** (Lesson 5).

## 5 — Other browser headers worth setting

- [ ] **`Strict-Transport-Security`** (HSTS) to force HTTPS.
- [ ] **`X-Content-Type-Options: nosniff`** (stop MIME sniffing), **`X-Frame-Options: DENY`** or CSP
      `frame-ancestors` (clickjacking), a sane **`Referrer-Policy`**.

## The one-line model

> **SOP isolates origins; CORS relaxes reads; CSRF abuses sends; XSS breaks isolation.** Turn on the
> defenses (allowlist CORS, SameSite + CSRF tokens, output encoding + CSP, cookie flags) — and never
> disable them to "make it work."
