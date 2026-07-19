---
name: checklist-collection-endpoint
description: A checklist for any list endpoint — pagination, filtering, sorting — that keeps a single collection from taking down a client, a serializer, and the database in one unbounded request
phase: 02
lesson: 04
---

# Collection-Endpoint Checklist

Every `GET /things` grows filters, sorting, and paging. Consistency across endpoints
is the feature — apply this identically everywhere.

## Never unbounded

- [ ] There is a **default page size** and a **hard maximum** (`limit`, capped, e.g.
      `le=100`). No request can ask for "all rows."
- [ ] The response is enveloped (`{"data": [...], ...}`), never a bare top-level array.

## Pagination

- [ ] **Cursor/keyset** for anything client-facing, hot, or growing — stable under
      concurrent writes, constant cost at any depth.
- [ ] **Offset/limit** only for small internal/admin tables that genuinely need
      "jump to page N" and a total count.
- [ ] The sort key behind a cursor is **unique and immutable** (append `id` as a
      tiebreaker); the comparison is strict so no boundary row skips or repeats.
- [ ] Fetch `limit + 1` to compute `has_more` without a separate `COUNT`.
- [ ] The cursor is **opaque** (base64) and coupled to its sort order — a mismatched
      cursor is a `400`.

## Filtering & sorting

- [ ] Filters are named **exactly like the response field** (`?status=pending`).
- [ ] Ranges use one documented convention (`created_after` / `created[gte]`).
- [ ] Sorting is a single `sort` param; `-` prefix = descending; commas add tiebreakers.
- [ ] **Sortable and filterable fields are whitelisted.** An unknown field is a
      **`400`**, never a silent full-table sort or an ignored filter.
- [ ] Free-text `q` is separate from exact-match filters.
- [ ] `fields=` sparse fieldsets are available for payload-sensitive clients.

## Performance

- [ ] Every sortable/filterable column is **indexed** (an unindexed sort is a
      self-inflicted denial of service).
- [ ] Deep offsets are known-slow — if the endpoint needs depth, it uses a cursor.
