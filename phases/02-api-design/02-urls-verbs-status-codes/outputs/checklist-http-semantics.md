---
name: checklist-http-semantics
description: A per-endpoint checklist for picking the right HTTP method, success code, and error code — so an API speaks one consistent status vocabulary instead of a per-endpoint dialect
phase: 02
lesson: 02
---

# HTTP Method & Status-Code Checklist

Apply this to every endpoint. The goal is a single, predictable vocabulary: a client
should be able to guess your status codes before reading the docs.

## Pick the method

- [ ] **GET** for reads only — **never** mutates state (crawlers and prefetchers
      issue GETs freely).
- [ ] **POST** to create or trigger an action. Non-idempotent → needs an idempotency
      key if retried (lesson 07).
- [ ] **PUT** to replace a whole resource. Idempotent; omitted fields are reset.
- [ ] **PATCH** for partial updates. Declare the format: JSON Merge Patch (RFC 7396,
      `null` deletes) or JSON Patch (RFC 6902, op list).
- [ ] **DELETE** to remove. Idempotent in effect; a repeat may return `404`.

## Success codes

- [ ] Create → **`201 Created`** + a **`Location`** header + the full body.
- [ ] Read / update → **`200 OK`** with the representation.
- [ ] Delete / empty-body success → **`204 No Content`**.
- [ ] Accepted-but-async → **`202 Accepted`** + a way to poll status.

## Error codes (the routing signal)

- [ ] Malformed syntax/shape → **`400`**.
- [ ] Missing/invalid credentials → **`401`** (+ `WWW-Authenticate`).
- [ ] Authenticated but not permitted → **`403`**.
- [ ] Resource absent or hidden from caller → **`404`**.
- [ ] Method unsupported on this resource → **`405`** (+ **`Allow`**).
- [ ] State conflict / duplicate / illegal transition → **`409`**.
- [ ] Well-formed but semantically invalid → **`422`**.
- [ ] Rate limited → **`429`** (+ `Retry-After`).
- [ ] Server fault → **`5xx`** only, and never leak a stack trace.

## Consistency guards

- [ ] **`5xx` means the server is at fault** — nothing a client sent belongs here.
- [ ] The same failure returns the same code on every endpoint.
- [ ] Safe methods are cacheable; idempotent methods are auto-retryable — and your
      codes reflect that (a client can retry a `503`, not a `400`).
