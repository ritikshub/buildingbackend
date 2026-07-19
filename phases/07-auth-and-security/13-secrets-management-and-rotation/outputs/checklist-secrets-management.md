---
name: checklist-secrets-management
description: Checklist for managing the secrets every auth mechanism depends on — keeping them out of source/images, storing them in a manager, encrypting with envelope encryption, rotating on schedule and on leak, and moving toward short-lived credentials. Run before shipping any service that holds a key, and during incident response for a leaked secret.
phase: 7
lesson: 13
---

# Secrets Management Checklist

Every mechanism in this phase depends on a secret staying secret. This is how you keep it that way.

## 1 — Where secrets live (and don't)

- [ ] **No secrets in source code, git, Docker images, or CI config.** Not even private repos (history
      is forever; scanners are instant).
- [ ] **No secrets in logs, errors, traces, crash dumps, or debug/env endpoints** (Phase 9 hygiene).
- [ ] Secrets are **injected at runtime** — env var, mounted file, or sidecar — sourced **from a secrets
      manager**, not from a committed `.env`.
- [ ] Local dev uses a real (dev) secrets source or `.env` that is **git-ignored**, never committed.

## 2 — Secrets manager

- [ ] Use a **secrets manager** (Vault, AWS Secrets Manager, GCP Secret Manager, Azure Key Vault) as
      the store: **encrypted at rest**, **access-controlled** (per-identity IAM), **audited**,
      **versioned**.
- [ ] **Least privilege**: each service/identity can read only the secrets it needs.
- [ ] The app authenticates to the manager via **workload identity**, not another hardcoded secret.

## 3 — Encryption (envelope encryption)

- [ ] Encrypt data with a per-data **DEK**; wrap the DEK with a **KEK** that lives in a **KMS** and
      never leaves it; store ciphertext + wrapped DEK together.
- [ ] Use a **cloud KMS** (AWS/GCP/Azure KMS) or the AWS Encryption SDK — don't hand-roll (Lesson 2).
- [ ] **One key, one purpose**: separate signing, encryption, and DB keys; a leaked DEK exposes one
      blob, not everything.

## 4 — Rotation

- [ ] Secrets are **rotated on a schedule** (and immediately on suspected leak).
- [ ] **Zero-downtime rotation** via versioning: sign/encrypt with the **current** version, verify/decrypt
      against **all active** versions, retire old ones after an **overlap window**. (JWT: `kid` + JWKS.)
- [ ] Prefer the manager's **automated rotation** for DB and service credentials.

## 5 — Leak response

- [ ] **Revoke first** (disable the leaked credential immediately — it's live now), **then rotate**
      (deploy a new one), **then investigate** (how, what it touched, who accessed it — audit log).
- [ ] Treat any secret-scanning hit as a **real leak** (git history is forever → rotate).

## 6 — Toward no long-lived secrets

- [ ] Use **dynamic secrets** (short-lived, auto-generated DB creds with a lease) where supported.
- [ ] Use **workload identity** (IAM roles, K8s service accounts, cloud workload identity) so the app
      gets **short-lived, auto-rotated** credentials — no static key in an env var.
- [ ] Keep **TTLs short**; a credential that expires in an hour is barely worth stealing.

## 7 — Continuous detection

- [ ] **Secret scanning** on in CI/repo (GitHub secret scanning + push protection, GitGuardian,
      `trufflehog`) so a hardcoded secret is caught before/at commit.
- [ ] **Redact secrets** from logs/errors and alert on anomalous secret access from the audit log.

## The one rule

> The keys that protect everything must not become the thing that leaks. Keep them out of code and
> images, in a manager with access control and audit, encrypted so the master key stays in a KMS,
> rotated routinely, and — best of all — short-lived and identity-derived so a leak expires on its own.
