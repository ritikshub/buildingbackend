---
name: checklist-config-and-environments
description: Ship configuration that can answer "which value is live right now?" — schema and boot validation, precedence and provenance, secret handling on every output path, release identity for config-only changes, and an environment parity check that runs in CI.
phase: 10
lesson: 05
---

# Config & environments — pre-ship checklist

Run this before a service takes production traffic, and again every time you add a key,
add an environment, or promote a config change. Every item exists because skipping it
has caused a real outage or a real leak.

## 1 · The schema

- [ ] Every config key is **declared in one place** with a type, and nothing reads config
      outside that declaration. Grep for `os.environ`, `os.getenv`, `process.env`,
      `System.getenv` outside the config module; each hit is a key with no schema.
- [ ] Every key declares: **type**, **required or default**, **bounds** (range, allowed
      values, min length), **secret or not**, and a one-line **doc** string.
- [ ] Booleans are parsed explicitly (`true/false/1/0/yes/no/on/off`). Never `bool(str)` —
      every non-empty string is truthy, so `bool("false")` is `True`.
- [ ] Numbers have units in the name (`_MS`, `_S`, `_MB`, `_PCT`). `TIMEOUT=30` has caused
      an outage in both directions.
- [ ] The schema is **closed**: unknown keys are an error, not a shrug. In pydantic-settings
      this is `extra="forbid"`, and it is **not** the default.
- [ ] Unknown-key errors offer a suggestion (`difflib.get_close_matches`, cutoff 0.6).
      "did you mean LOG_LEVEL?" is one line and saves a deploy cycle.
- [ ] No key has a default that is only correct in one environment. If production is the
      only place a value is right, it has no business being a default.

## 2 · Boot validation

- [ ] The whole config is **resolved and validated at startup**, before the listening
      socket opens — not lazily on first read.
- [ ] Validation **collects every problem and reports them together.** Failing on the first
      error turns three typos into three deploy cycles.
- [ ] An invalid config **exits non-zero with a readable message**. A crash loop with a
      clear cause is a bad deploy; a process that starts wrong is an incident.
- [ ] Config validation runs inside whatever the startup probe gates, so a bad config can
      never be mistaken for a slow boot.
- [ ] The boot log records the **release id** and the **config hash** — the first two lines
      anyone will want during an incident.
- [ ] Boot validation is fast enough to be free (this lesson's: 0.18 ms for 12 keys).
      If it is not, you are doing I/O in it — move that to a readiness check.

## 3 · Precedence & provenance

- [ ] The precedence order is **written down** in the repo, not inferred from the order of
      `dict.update()` calls. A common one: `defaults → file → environment → command line`.
- [ ] Resolution is **deterministic**: no wall-clock, no hostname branches, no
      "whichever file the glob returned first."
- [ ] The resolver **keeps the whole chain**, not just the winner. For every key you can
      produce: effective value, the layer that supplied it, and every layer that lost.
- [ ] There is an **authenticated** `/debug/config` (or equivalent CLI flag) that prints
      that table with secrets redacted. Unauthenticated is not an option.
- [ ] Any key set in more than two layers is reviewed. Four layers setting one key is how
      "which value is live?" takes eleven minutes to answer.
- [ ] Config that duplicates a default with the same value is deleted. It does nothing and
      the next reader will treat it as load-bearing.

## 4 · Secrets

- [ ] Every secret field is **marked as such in the schema**, so redaction is a property of
      the type and not a rule people remember.
- [ ] Redaction covers **every output path**: config dump, provenance report, log lines,
      exception messages, crash dumps, metrics labels, trace attributes.
- [ ] **Validation errors are built from constraints, never from the value.**
      `length 9, minimum 32` — never `'hunter2xy' is too short`.
      The error path is where secrets leak, because nobody reviews it.
- [ ] Redaction is **useful**: emit a short digest (`<redacted sha256:41a3154e>`) so values
      stay comparable across environments without being revealed.
- [ ] A test asserts that a known secret value appears in **none** of the output surfaces.
- [ ] Secret fingerprints **differ across environments.** If staging and production share a
      signing key, staging can mint production sessions.
- [ ] Secrets are not passed as command-line arguments (visible in `ps`) and, where the
      platform allows it, arrive as **mounted files** rather than environment variables
      (`/proc/<pid>/environ`, child processes, `docker inspect`, exception reporters).
- [ ] Rotation is treated as a **release**: it changes the running system, so it gets a
      release id, a change record and a rollback path like anything else.

## 5 · Release identity — `release = build + config`

- [ ] The artifact is **environment-agnostic.** There is no "staging image." If your build
      pipeline takes an environment name as an input, build and release are merged.
- [ ] A **release id** is derived deterministically: `hash(artifact_digest + config_hash)`.
- [ ] The config hash is **canonical** — sorted keys, normalised formatting — so identical
      configs always produce identical hashes regardless of layer or read order.
- [ ] Deploy history records the **release id**, not just the image. Otherwise config-only
      changes are invisible to it and "roll back" returns you to where you already are.
- [ ] In Kubernetes: a **`checksum/config` annotation** on the pod template carries the
      config hash. Without it, editing a ConfigMap consumed via `envFrom` rolls out
      **nothing** — `kubectl apply` succeeds and every running process keeps its old values.
- [ ] Images are referenced by **digest** (`repo/api@sha256:...`), never by mutable tag.
- [ ] No `.env` file is ever `COPY`'d into an image. A later `RUN rm` does not remove it —
      the earlier layer still contains it and is still pushed to the registry.
- [ ] `.env` is in `.gitignore`; a `.env.example` with keys and no values is committed.

## 6 · Environment parity

- [ ] An **environment matrix** lives in the repo: every key × every environment, showing
      the value or source, with secrets shown as "set in <store>".
- [ ] A **parity check runs in CI** over the config *sources*, before anything boots, and
      fails the build on new findings. Three categories:
  - [ ] **MISSING** — set in one environment, absent in the other. The absent side silently
        takes the default; no error, no log line, and staging sign-off tested a code path
        production is not running.
  - [ ] **SOURCE** — same key, same value, different layer. Invisible until someone edits
        the file that only one environment reads, watches it work there, and ships.
  - [ ] **TYPE** — parses in one environment and not the other. A boot failure discovered
        during the rollout instead of in CI.
- [ ] Deliberate differences are **suppressed explicitly, with an owner and an expiry**, and
      an expired suppression fails the build. An unbounded allowlist ends up matching
      everything.
- [ ] Feature flags are in the matrix. A flag on in staging and unset in production is the
      most common five-week drift there is.
- [ ] Every environment resolves each key from the **same layer**. Value parity is not parity.

## 7 · Anti-patterns to grep for

- [ ] `os.environ` / `process.env` read anywhere outside the config module.
- [ ] `bool(os.environ[...])` or `int(os.environ[...])` with no error handling.
- [ ] A config value read for the first time inside a rare code path (a refund, an error
      handler, a nightly job) — that is a typo you will discover in production, silently.
- [ ] `.get(key, fallback)` scattered through business logic: N implicit, undocumented
      defaults that no schema knows about.
- [ ] An error message, log line or exception that interpolates a config value that might
      be a secret.
- [ ] A ConfigMap edit with no `checksum/config` annotation.
- [ ] `image: repo/api:latest` or any mutable tag in a production manifest.
- [ ] Environment-specific branching in application code (`if ENV == "production":`).
      That is a config value that has not been named yet.
- [ ] A config endpoint that is not authenticated.

> ## Decision shortcut
>
> **"If I change this value, is it a deploy?"**
> Yes → it is **config**: schema it, validate it at boot, hash it into the release id, and
> put it in the environment matrix.
> **"Would I be unhappy if this appeared in a log line?"**
> Yes → it is a **secret**: same delivery, redaction on every path, fingerprint not value,
> and rotation is a release.
> **"Can I tell you where the live value came from, in one command, right now?"**
> No → you do not have a config system, you have four files and a guess.
