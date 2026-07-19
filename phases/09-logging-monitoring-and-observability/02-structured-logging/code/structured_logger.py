#!/usr/bin/env python3
"""
A structured logger built from scratch: JSON Lines events, severity levels,
immutably bound context, redaction, exception capture, and canonical log lines.

Companion to docs/en.md (Phase 10, Lesson 02). The ideas it makes concrete:

  * A log line is an EVENT, not a sentence: the message becomes a stable `event`
    name and every variable becomes a typed, queryable field.
  * Severity levels are a numeric runtime filter applied BEFORE any formatting
    work happens. The five names are the modern reading of the eight syslog
    severities defined in RFC 5424, section 6.2.1.
  * Context binds immutably: log.bind(...) returns a CHILD logger, so a request's
    identity rides along on every line it emits without being passed by hand.
  * Secrets are redacted by key name, recursively, before serialization.
  * One wide "canonical log line" per request beats a dozen narrow ones.

Output is deterministic (fixed clock, seeded RNG) so it can be pasted verbatim
into the lesson. A real logger would read time.time_ns() instead of a fake clock.

Runs on the Python standard library only:  python structured_logger.py
"""

from __future__ import annotations

import io
import json
import os
import random
import sys
import traceback as tb_mod
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, Mapping, TextIO


# ─── Severity levels ──────────────────────────────────────────────────────────

# Numbers, not names, so filtering is one integer comparison per call.
LEVELS: dict[str, int] = {"DEBUG": 10, "INFO": 20, "WARNING": 30,
                          "ERROR": 40, "CRITICAL": 50}


# ─── Time: ISO-8601, UTC, millisecond precision ───────────────────────────────

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def iso_utc(epoch_ms: int) -> str:
    """1773544447912 -> '2026-03-14T03:14:07.912Z'. Sorts lexicographically."""
    dt = _EPOCH + timedelta(milliseconds=epoch_ms)
    return f"{dt.strftime('%Y-%m-%dT%H:%M:%S')}.{epoch_ms % 1000:03d}Z"


class Clock:
    """A fake monotonic clock in whole milliseconds, so output is reproducible.
    `advance` stands in for work actually taking time (a query, an HTTP call)."""

    def __init__(self, start_iso: str) -> None:
        dt = datetime.strptime(start_iso, "%Y-%m-%dT%H:%M:%S.%fZ")
        self.ms = int((dt.replace(tzinfo=timezone.utc) - _EPOCH).total_seconds() * 1000)

    def now(self) -> int:
        return self.ms

    def advance(self, ms: int) -> int:
        self.ms += ms
        return self.ms


# ─── Redaction: never let a secret reach the log stream ───────────────────────

REDACTED = "[REDACTED]"

SENSITIVE_KEYS = frozenset({
    "password", "passwd", "secret", "token", "access_token", "refresh_token",
    "api_key", "apikey", "authorization", "cookie", "session_id",
    "card_number", "cvv", "pan", "ssn", "private_key",
})


def redact(value: Any, keys: frozenset[str] = SENSITIVE_KEYS) -> Any:
    """Blank sensitive keys, recursing into nested dicts and lists.

    Denies by KEY NAME, so field naming is a security control: a secret buried
    inside a `payload` or `body` blob walks straight through this.
    """
    if isinstance(value, Mapping):
        return {k: REDACTED if k.lower() in keys else redact(v, keys)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, keys) for v in value]
    return value


def compact_traceback(exc: BaseException) -> str:
    """A traceback as ONE line (innermost frame first) — multi-line traces break
    line-oriented tooling, a JSON string field never does."""
    return " <- ".join(f"{os.path.basename(f.filename)}:{f.lineno} in {f.name}"
                       for f in reversed(tb_mod.extract_tb(exc.__traceback__)))


# ─── The logger ───────────────────────────────────────────────────────────────

class Logger:
    """Emits one JSON object per line (JSON Lines) to a text stream."""

    def __init__(self, stream: TextIO, *, clock: Clock, level: str = "INFO",
                 context: Mapping[str, Any] | None = None,
                 sensitive_keys: frozenset[str] = SENSITIVE_KEYS) -> None:
        self.stream = stream
        self.clock = clock
        self.level = level
        self.context: dict[str, Any] = dict(context or {})
        self.sensitive_keys = sensitive_keys
        self._threshold = LEVELS[level]

    def bind(self, **fields: Any) -> "Logger":
        """Return a CHILD logger carrying these fields on every line it emits.

        Immutable on purpose: two concurrent requests bind to two different
        children and can never see each other's fields.
        """
        return Logger(self.stream, clock=self.clock, level=self.level,
                      context={**self.context, **fields},
                      sensitive_keys=self.sensitive_keys)

    def emit(self, level: str, event: str, **fields: Any) -> bool:
        """Assemble, redact, serialize, write. Returns False if level-filtered."""
        if LEVELS[level] < self._threshold:
            return False                       # cheapest possible path: one int compare
        record: dict[str, Any] = {
            "ts": iso_utc(self.clock.now()),   # first key: JSONL sorts by time as text
            "level": level,
            "event": event,                    # a STABLE name, never an English sentence
        }
        record.update(self.context)            # bound fields (service, request_id, ...)
        record.update(fields)                  # call-site fields win
        line = json.dumps(redact(record, self.sensitive_keys),
                          separators=(",", ":"), default=str)
        self.stream.write(line + "\n")
        return True

    def debug(self, event: str, **f: Any) -> bool: return self.emit("DEBUG", event, **f)
    def info(self, event: str, **f: Any) -> bool: return self.emit("INFO", event, **f)
    def warning(self, event: str, **f: Any) -> bool: return self.emit("WARNING", event, **f)
    def critical(self, event: str, **f: Any) -> bool: return self.emit("CRITICAL", event, **f)

    def error(self, event: str, exc: BaseException | None = None, **fields: Any) -> bool:
        """ERROR means a human should care. An exception becomes FIELDS, not text."""
        if exc is not None:
            fields = {"exc_type": type(exc).__name__, "exc_message": str(exc),
                      "traceback": compact_traceback(exc), **fields}
        return self.emit("ERROR", event, **fields)


# ─── Canonical log lines: one wide event per request ──────────────────────────

@dataclass
class RequestLog:
    """A request-scoped accumulator. Collect fields; emit exactly one line."""

    fields: dict[str, Any] = field(default_factory=dict)
    started_ms: int = 0

    def add(self, **fields: Any) -> "RequestLog":
        self.fields.update(fields)
        return self


@contextmanager
def canonical(logger: Logger, event: str, **initial: Any) -> Iterator[RequestLog]:
    """Accumulate fields for the life of a request; emit ONE wide event at the
    end. An exception is recorded as fields before re-raising, so even a failed
    request produces exactly one queryable line."""
    rl = RequestLog(dict(initial), logger.clock.now())
    try:
        yield rl
    except Exception as exc:
        rl.add(outcome="error", status=500, exc_message=str(exc),
               error_kind=getattr(exc, "kind", type(exc).__name__))
        raise
    finally:
        rl.fields.setdefault("outcome", "ok")
        rl.fields.setdefault("status", 200)
        rl.add(duration_ms=logger.clock.now() - rl.started_ms)
        level = "ERROR" if rl.fields["outcome"] == "error" else "INFO"
        logger.emit(level, event, **rl.fields)


# ─── A simulated service, so there is something to log ────────────────────────

class OrderError(Exception):
    """A domain failure that names its own kind — so the log field is stable."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def charge_card(order_id: str) -> None:      # two frames deep, so the
    _call_gateway(order_id)                  # captured traceback has a stack


def _call_gateway(order_id: str) -> None:
    raise OrderError("payment_gateway_timeout", "gateway did not respond in 3000ms")


ERROR_KINDS = ["payment_declined", "inventory_unavailable",
               "payment_gateway_timeout", "address_invalid"]
ROUTES = ["/orders", "/orders/{id}/pay", "/cart/checkout"]
TIERS = ["free", "premium", "premium", "enterprise"]
REGIONS = ["eu-west", "eu-west", "us-east", "ap-south"]


def handle_request(log: Logger, clock: Clock, rng: random.Random, n: int) -> None:
    """One request: do simulated work, accumulate fields, emit one canonical line."""
    tier, region = rng.choice(TIERS), rng.choice(REGIONS)
    req = log.bind(request_id=f"req_{n:04d}", user_id=f"u_{rng.randint(1000, 9999)}")
    with canonical(req, "http.request",
                   method="POST", route=rng.choice(ROUTES),
                   tier=tier, region=region) as rl:
        cache_hit = rng.random() < 0.55
        clock.advance(1 if cache_hit else rng.randint(4, 12))
        queries = rng.randint(1, 5)
        db_ms = sum(rng.randint(2, 25) for _ in range(queries))
        clock.advance(db_ms)
        rl.add(cache_hit=cache_hit, db_queries=queries, db_ms=db_ms,
               retries=0, bytes_out=rng.randint(200, 4000))
        if rng.random() < 0.22:
            retries = rng.randint(1, 3)
            clock.advance(retries * 40)
            rl.add(retries=retries)
            raise OrderError(rng.choice(ERROR_KINDS), f"order rejected after {retries} retries")
        clock.advance(rng.randint(1, 6))


class Tee:
    """Write to two streams at once: the console you read, the sink you query."""

    def __init__(self, *streams: TextIO) -> None:
        self.streams = streams

    def write(self, data: str) -> int:
        for s in self.streams:
            s.write(data)
        return len(data)


# ─── Demo ─────────────────────────────────────────────────────────────────────

def main() -> None:
    rng = random.Random(42)
    clock = Clock("2026-03-14T03:14:07.912Z")
    sink = io.StringIO()                       # stands in for the log file / stdout pipe
    base = Logger(Tee(sys.stdout, sink), clock=clock, level="INFO",
                  context={"service": "order-api", "version": "3.14.2",
                           "env": "prod", "host": "web-07"})

    print("== 1 - PROSE VS STRUCTURED ==")
    print("  prose      : 2026-03-14 04:14:07 ERROR Failed to process order "
          "for user 8842 after 3 retries")
    print("  structured : ", end="")
    base.error("order.failed", user_id="u_8842", retries=3,
               error_kind="payment_declined", tier="premium", region="eu-west")

    print("\n== 2 - LEVEL AS A RUNTIME FILTER (threshold=INFO) ==")
    clock.advance(11)
    suppressed = base.debug("cart.item.priced", sku="SKU-91", price_cents=1299)
    emitted = base.warning("db.pool.saturated", in_use=19, size=20, wait_ms=412)
    print(f"  debug emitted? {suppressed}   warning emitted? {emitted}")

    print("\n== 3 - REDACTION BY KEY NAME (recursive) ==")
    clock.advance(37)
    base.info("auth.login", user_id="u_8842", password="hunter2",
              upstream={"api_key": "sk_live_9f21c", "endpoint": "auth.internal"},
              headers={"authorization": "Bearer eyJhbGci", "user-agent": "curl/8.4"})

    print("\n== 4 - EXCEPTION AS FIELDS, NOT A MULTI-LINE TRACE ==")
    clock.advance(6)
    try:
        charge_card("o_5512")
    except OrderError as exc:
        base.bind(request_id="req_0001").error("order.failed", exc, order_id="o_5512")

    print("\n== 5 - CANONICAL LOG LINES: ONE WIDE EVENT PER REQUEST ==")
    for n in range(1, 4):
        clock.advance(rng.randint(20, 60))
        try:
            handle_request(base, clock, rng, n)
        except OrderError:
            pass

    quiet = Logger(sink, clock=clock, level="INFO", context=base.context)
    for n in range(4, 401):
        clock.advance(rng.randint(5, 90))
        try:
            handle_request(quiet, clock, rng, n)
        except OrderError:
            pass
    print("  ... 397 more requests logged to the same stream (not shown)")

    print("\n== 6 - THE QUERY PROSE COULD NOT ANSWER ==")
    events = [json.loads(line) for line in sink.getvalue().splitlines()]
    requests = [e for e in events if e["event"] == "http.request"]
    counts: dict[str, int] = {}
    for e in requests:
        if e["outcome"] == "error" and e["tier"] == "premium" and e["region"] == "eu-west":
            counts[e["error_kind"]] = counts.get(e["error_kind"], 0) + 1
    print(f"  events on the stream : {len(events)}   canonical request lines: {len(requests)}")
    print("  premium + eu-west order failures, grouped by error kind:")
    for kind, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"    {kind:<24} {count}")

    print("  slowest 3 requests (same lines, different question):")
    for e in sorted(requests, key=lambda e: -e["duration_ms"])[:3]:
        print(f"    {e['request_id']}  {e['duration_ms']:>4}ms  db={e['db_ms']:>3}ms "
              f"queries={e['db_queries']}  cache_hit={e['cache_hit']}  {e['outcome']}")


if __name__ == "__main__":
    main()
