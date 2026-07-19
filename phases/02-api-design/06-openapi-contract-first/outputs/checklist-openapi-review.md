---
name: checklist-openapi-review
description: A checklist for keeping an OpenAPI spec honest and drift-free — response models on every route, documented errors, and a CI spec-diff so breaking changes fail review loudly
phase: 02
lesson: 06
---

# OpenAPI Review Checklist

Whether you write the spec by hand (contract-first) or generate it (code-first), the
enemy is the same: the document drifting from the running behavior. This keeps them
married.

## Completeness

- [ ] Every route declares a **response model/schema** — not a bare `200`. (In
      code-first frameworks, the response model also *filters* the payload; without it,
      internal fields leak.)
- [ ] Every operation documents its **error responses** (`4xx`, and `5xx` where real),
      each with a schema — ideally the shared `Problem` (RFC 9457) shape.
- [ ] Path/query/header parameters list `required`, `type`, and constraints.
- [ ] Schemas carry `example`s and human `description`s where a name isn't obvious.
- [ ] Each operation has a stable, unique **`operationId`** (SDK method name).

## Consistency (enforce with a linter, e.g. Spectral)

- [ ] Naming convention is uniform (e.g. snake_case fields) across all schemas.
- [ ] Shared shapes (`Order`, `LineItem`, `Problem`) are defined once in
      `components/schemas` and **`$ref`-ed**, never copy-pasted inline.
- [ ] Enums are declared where a field has a fixed value set.
- [ ] Auth schemes are declared in `components/securitySchemes` and applied.

## Drift control (the part teams skip)

- [ ] The spec is **generated from or checked against the code** — not maintained by
      hand in a separate file that rots.
- [ ] `/openapi.json` (or the YAML) is **snapshotted in the repo** and **diffed in CI**.
- [ ] A diff that renames a field, narrows a type, or removes an operation **fails the
      build** — a breaking change should be a loud review event, not a silent ship.
- [ ] The version in `info.version` is bumped deliberately, per the versioning policy.
