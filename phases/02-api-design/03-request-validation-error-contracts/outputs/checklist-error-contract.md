---
name: checklist-error-contract
description: A checklist for designing one API-wide error envelope — so every consumer writes a single error handler, and no endpoint leaks internals or invents its own error shape
phase: 02
lesson: 03
---

# Error-Contract Checklist

The test of a good error contract: a client can write **one** error handler for your
whole API. Walk this before you ship the first endpoint — retrofitting an envelope
across live consumers is painful.

## One envelope, everywhere

- [ ] Every error — validation, auth, not-found, conflict, server fault — uses the
      **same shape** (RFC 9457 `application/problem+json`, or a documented equivalent).
- [ ] The envelope carries a **machine `code`** that is frozen forever. Clients branch
      on `code`, **never** on the human `detail` string.
- [ ] The human `detail`/`title` is for logs and developers; it may change any time.
- [ ] The correct HTTP **status** is set and matches the envelope's `status` field.

## Validation specifics

- [ ] Validation runs **at the edge**, before any business logic.
- [ ] **All** field errors are returned at once — never fail-fast one at a time.
- [ ] Each field error is `{field, code, message}` with a **path** (`items[0].quantity`)
      the client can map onto its inputs.
- [ ] `400` for malformed syntax/shape; `422` for well-formed-but-invalid. Pick the
      split once and apply it consistently.

## Never leak internals

- [ ] No stack traces, SQL, hostnames, or internal IDs in any error body.
- [ ] Every response carries a **request id** (`instance`, or an `X-Request-Id` echo).
- [ ] The full error + traceback is logged **server-side**, keyed by that request id,
      so support can correlate a user's complaint to one log line.
- [ ] `5xx` bodies are generic — the detail lives in the log, not on the wire.

## Contract hygiene

- [ ] The set of `code` values is documented and treated as part of the public API.
- [ ] A new error `code` is an **additive** change; renaming one is **breaking**.
- [ ] `type` URIs (if used) resolve to docs but are treated as opaque by clients.
