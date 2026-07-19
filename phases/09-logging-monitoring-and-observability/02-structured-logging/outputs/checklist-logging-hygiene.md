---
name: checklist-logging-hygiene
description: The standing checklist for structured logging in a service — field naming, level discipline, what never gets logged, redaction, timestamps, canonical log lines, stdout, and cost — reviewed before a service ships and again in every code review that touches a log call
phase: 09
lesson: 02
---

# Logging Hygiene Checklist

Logging is the one telemetry signal every engineer writes by hand, every day, usually without
review. This is the list to run before a service takes traffic, and to keep open during any code
review that adds or changes a log call.

## 1 — Format and transport

- [ ] Output is **structured**: one JSON object per line (JSON Lines), not prose.
- [ ] Exactly **one line per event**. A stack trace is a string *field*, never extra lines.
- [ ] The app writes to **stdout** and nothing else. No file paths, no rotation, no compression
      in application code — the platform ships it (twelve-factor *Logs*; see Lesson 4).
- [ ] Every line has the same leading keys in the same order (`ts`, `level`, `event`) so a raw
      file is still scannable by a human.
- [ ] Serialization never throws on unexpected types — a logging failure must not break a request.

## 2 — Timestamps

- [ ] **ISO 8601, UTC, millisecond precision**: `2026-03-14T03:14:07.912Z`.
- [ ] Not local time. Not a timezone offset that varies with daylight saving.
- [ ] Not a raw `time.time()` float as the primary timestamp.
- [ ] If using Python's `logging`, `Formatter.converter` is set to `time.gmtime` — the default
      is local time and silently reintroduces the problem.

## 3 — Event names and field naming

- [ ] The message is a **stable event name**, not a sentence: `order.failed`, not
      `"Failed to process order for user 8842"`. Renaming the human wording must never break a query.
- [ ] Event names use a consistent scheme across the service (`noun.verb` is a good default).
- [ ] Field names are **snake_case** and consistent service-wide: `user_id` everywhere, never
      `userId` in one place and `uid` in another.
- [ ] **Units are in the name**: `duration_ms`, `size_bytes`, `timeout_s`. No bare `duration`.
- [ ] Values are **typed**: `retries: 3` (number), `cache_hit: false` (boolean) — not `"3"`, `"true"`.
- [ ] A field name means the same thing in every service that emits it. Write the shared ones down.

## 4 — Levels

- [ ] **CRITICAL** — the process cannot continue. Data loss or total outage.
- [ ] **ERROR** — *a human should care*. Not "something unusual happened". If nobody will act on
      it, it is not an ERROR.
- [ ] **WARNING** — degraded but handled: a retry succeeded, a fallback fired, a quota is 80% used.
- [ ] **INFO** — the story of normal operation, once per request or state change. The default.
- [ ] **DEBUG** — developer-only internals. Off in production; turning it on is a ~40x volume and
      cost decision, not a toggle.
- [ ] Expected client errors (bad password, validation failure, 404) are **not** ERROR.
- [ ] No expensive work inside a call that may be filtered: arguments are evaluated *before* the
      level check, so `log.debug("rows", rows=fetch_all())` runs `fetch_all()` regardless.

## 5 — Context

- [ ] Every line carries `service`, `version`, `env`, `host`. Without them, a line in a central
      store is unattributable.
- [ ] Request-scoped fields (`request_id`, `user_id`, `tier`, `region`) come from a **bound child
      logger**, not from re-typing them at each call site.
- [ ] Binding is **immutable** — it returns a child, never mutating a shared logger. Two concurrent
      requests must never see each other's fields.
- [ ] Every line emitted during a request carries the request/trace ID (Lesson 3).

## 6 — Canonical log lines

- [ ] Each request emits **one wide event** at the end with everything you'd want to filter on:
      route, method, status, `duration_ms`, `db_ms`, `db_queries`, `cache_hit`, `retries`,
      `bytes_out`, `outcome`, `error_kind`, plus identity and tier fields.
- [ ] The wide event is emitted on the **failure path too** — a request that raised still produces
      exactly one queryable line, with `outcome` and `error_kind` set.
- [ ] Narrow lines are the exception, kept deliberately for: long-running jobs, state changes you
      must audit independently, and local DEBUG.
- [ ] New fields are **added to the wide line** rather than emitted as a new narrow line.

## 7 — What never goes in a log

- [ ] No **credentials**: passwords (including wrong ones), tokens, API keys, session cookies,
      `Authorization` headers, private keys.
- [ ] No **payment data**: full card numbers, CVV, expiry. PCI DSS forbids storing the CVV at all,
      and a log file is storage.
- [ ] No **whole request or response bodies**. This is the single most common leak.
- [ ] No **personal data** beyond an opaque ID: emails, phone numbers, addresses, full names.
      Under GDPR a log line containing personal data *is* personal data, with deletion and
      retention obligations attached.
- [ ] **Redaction** by key name exists, runs before serialization, and recurses into nested
      structures — and everyone knows it matches *names, not values*, so it is a backstop.
- [ ] The rule behind the rule: **log identifiers, not payloads.** `user_id` not `user`,
      `card_last4` not `card`, `body_bytes` not `body`.

## 8 — Cost and safety

- [ ] You know your bytes per request and can multiply it by peak requests per second.
- [ ] Logging is not doing extra work purely to be logged (no extra query to enrich a line).
- [ ] Retention is set deliberately per level or stream, not left at a vendor default (Lesson 4).
- [ ] Dependency loggers are turned down (`urllib3`, `botocore`, ORM query logs) rather than
      drowning your own signal.
- [ ] Logging is configured **once**, declaratively (`dictConfig`), at process start — not by a
      `basicConfig()` call hiding in a library.

## Decision shortcut

> Ask three questions at every log call. **Who acts on this?** (that picks the level — if nobody
> acts, it is not ERROR). **What would I want to filter on later?** (that becomes a typed field on
> the canonical line, not a phrase in a sentence). **Would I be comfortable if this line were
> pasted into a shared channel?** (if not, you are logging a payload where an identifier belongs).
