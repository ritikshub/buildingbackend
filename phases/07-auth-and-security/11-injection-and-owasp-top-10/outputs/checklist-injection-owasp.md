---
name: checklist-injection-owasp
description: Two checklists in one — preventing injection (SQL, command, path, SSRF) by separating code from data, and running through the OWASP Top 10 as a security review of a backend. Use before shipping any endpoint that touches a database, shell, filesystem, or outbound fetch, and as a periodic app-wide review.
phase: 7
lesson: 11
---

# Injection & OWASP Top 10 Checklist

Injection is one bug — data interpreted as code — against many interpreters. Separate code from data,
then validate and constrain as defense in depth.

## 1 — Injection: separate code from data (the primary fix)

- [ ] **SQL / NoSQL**: **parameterized queries / prepared statements** everywhere — never string
      concatenation or f-strings into a query. ORMs do this by default; audit every `raw()`/`text()`.
- [ ] **Identifiers** (table/column names) that can't be parameters use a strict **allowlist**, never
      interpolation.
- [ ] **OS commands**: pass an **argument list with `shell=False`** (or don't spawn a process). Never
      build a shell command line from user input.
- [ ] **Filesystem**: **confine** the resolved absolute path to a base directory (`realpath` +
      startswith check); reject `..`, absolute paths, and symlink escapes.
- [ ] **Outbound fetches (SSRF)**: **allowlist** destinations; resolve the host and **block loopback,
      private, and link-local ranges** (IPv4 and IPv6), **disable redirects**, restrict schemes to
      http/https, and re-check after DNS resolution (rebinding). Enforce **IMDSv2** in the cloud.
- [ ] **Templates/HTML (XSS)**: context-aware **output encoding** (Lesson 10); sanitize rich HTML.
- [ ] **LDAP / XML / template engines / eval**: same rule — never build the query/document from raw
      input; use safe APIs, disable dangerous features (XXE: disable external entities).

## 2 — Defense in depth (after separation)

- [ ] **Input validation with allowlists** (define what's valid), not blocklists (chasing what's bad).
- [ ] **Least privilege on the interpreter**: the DB user can't `DROP`/`ALTER`/read other schemas; the
      service account can't reach what it doesn't need — so a successful injection is contained.
- [ ] **Verbose errors off** in production (no stack traces / SQL echoed to the client).
- [ ] A **WAF** as a backstop that buys time — never as the fix.

## 3 — OWASP Top 10 (2021) review pass

- [ ] **A01 Broken Access Control** — object-level authz, deny by default, server-side (Lesson 9).
- [ ] **A02 Cryptographic Failures** — no plaintext secrets/passwords, strong hashing, TLS (L2/L3/L13).
- [ ] **A03 Injection** — section 1 above (SQLi, command, path, XSS).
- [ ] **A04 Insecure Design** — threat model the feature; secure defaults (Lesson 1).
- [ ] **A05 Security Misconfiguration** — CORS allowlist, security headers, no default creds, least
      privilege, hardened error handling (Lesson 10/13).
- [ ] **A06 Vulnerable & Outdated Components** — dependency scanning (Dependabot, `pip-audit`, Snyk);
      patch cadence; remove unused deps.
- [ ] **A07 Identification & Authentication Failures** — strong password storage, MFA, secure
      sessions/tokens, rate-limited login (L3–L6, L12).
- [ ] **A08 Software & Data Integrity Failures** — verify signatures/JWTs, sign artifacts, secure CI/CD
      and update channels (L6/L8).
- [ ] **A09 Security Logging & Monitoring Failures** — audit trails, alerting, and detection so a breach
      is noticed (Phase 9, Lesson 1).
- [ ] **A10 SSRF** — allowlist + internal-range blocking (section 1).

## 4 — Toolchain

- [ ] **SAST** (static analysis) and **DAST** (dynamic scanning) in CI for injection/misconfig.
- [ ] **SCA / dependency scanning** for A06; **secret scanning** for leaked keys (Lesson 13).
- [ ] Security tests for the negative cases (injection payloads rejected, object-level authz enforced).

## The one rule for injection

> Wherever user data meets an interpreter (SQL, shell, path, URL, HTML), **make the data a value, not
> syntax** — parameterize, argument-list, confine, allowlist. Escaping is the last line; separation is
> the fix.
