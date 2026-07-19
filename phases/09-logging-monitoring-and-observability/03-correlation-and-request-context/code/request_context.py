#!/usr/bin/env python3
"""
Correlation from scratch: ambient request context, W3C Trace Context, propagation.

Builds, with nothing but the standard library: a `contextvars`-based request context
(trace id, span id, sampling flag, baggage) readable from any function without being
passed in; spec-correct parse/format for the `traceparent` and `baggage` headers with
every rejection rule; a JSON logger that stamps the ids on every event by READING the
contextvar; a real two-service HTTP hop proving the trace survives a network boundary;
three genuinely concurrent requests interleaved into one stream then filtered back to
one trace_id; and an asyncio+queue demo carrying context in MESSAGE HEADERS.

Follows: W3C Trace Context, Level 1 (W3C Recommendation, 2021-11-23) and W3C Baggage.
Runs on the Python standard library only:  python request_context.py
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import random
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterator, List, Optional
from urllib import parse as urlparse
from urllib import request as urlrequest


# ─── A deterministic clock, so this file prints the same bytes every run ──────

_BASE_MS = (3 * 3600 + 14 * 60 + 7) * 1000        # 03:14:07.000
_tick_lock = threading.Lock()
_tick = 0

def next_ts_ms() -> int:
    """A monotonic fake clock: 3 ms per logged event. Keeps output reproducible."""
    global _tick
    with _tick_lock:
        _tick += 1
        return _BASE_MS + 3 * _tick

def fmt_ts(ms: int) -> str:
    s, milli = divmod(ms, 1000)
    m, sec = divmod(s, 60)
    h, minute = divmod(m, 60)
    return f"{h:02d}:{minute:02d}:{sec:02d}.{milli:03d}"


# ─── The identifiers, and the ambient context that carries them ──────────────

INVALID_TRACE_ID = "0" * 32
INVALID_SPAN_ID = "0" * 16
_HEX = frozenset("0123456789abcdef")

@dataclass(frozen=True)
class SpanContext:
    """One node of a trace. trace_id is shared by the whole request-journey."""

    trace_id: str                                   # 16 bytes / 32 lowercase hex
    span_id: str                                    # 8 bytes  / 16 lowercase hex
    parent_span_id: Optional[str] = None            # None at the root of the trace
    sampled: bool = True                            # traceparent trace-flags bit 0
    baggage: Dict[str, str] = field(default_factory=dict)
    links: tuple = ()                               # span ids this one is LINKED to

# One variable, one process. Each thread starts with an empty Context; each asyncio
# Task gets a COPY of its parent's Context at creation time — that is the whole trick.
_CURRENT: contextvars.ContextVar[Optional[SpanContext]] = contextvars.ContextVar(
    "request_span_context", default=None
)

def current() -> Optional[SpanContext]:
    return _CURRENT.get()

@contextmanager
def use(ctx: SpanContext) -> Iterator[SpanContext]:
    """Bind ctx for the duration of the block, then restore exactly what was there."""
    token = _CURRENT.set(ctx)
    try:
        yield ctx
    finally:
        _CURRENT.reset(token)

def _hex_id(rng: random.Random, n_bytes: int) -> str:
    while True:
        value = rng.getrandbits(n_bytes * 8)
        if value:                                   # all-zero ids are invalid
            return "%0*x" % (n_bytes * 2, value)

def new_trace(rng: random.Random, sampled: bool = True, **baggage: str) -> SpanContext:
    """Mint a brand-new trace: fresh 16-byte trace id, fresh 8-byte root span id."""
    return SpanContext(_hex_id(rng, 16), _hex_id(rng, 8), None, sampled, dict(baggage))

def child_span(parent: SpanContext, rng: random.Random) -> SpanContext:
    """Same trace, new span, parent recorded — this is what builds the tree."""
    return replace(parent, span_id=_hex_id(rng, 8), parent_span_id=parent.span_id, links=())

@contextmanager
def span(rng: random.Random) -> Iterator[SpanContext]:
    """Open a child span of whatever context is ambient right now."""
    parent = current()
    assert parent is not None, "no ambient context — call use(new_trace(...)) first"
    with use(child_span(parent, rng)) as ctx:
        yield ctx


# ─── W3C Trace Context: the wire format ──────────────────────────────────────

class TraceparentError(ValueError):
    """Raised when a traceparent header violates the W3C Recommendation."""

def _is_hex(s: str, n: int) -> bool:
    return len(s) == n and all(c in _HEX for c in s)

def format_traceparent(ctx: SpanContext) -> str:
    """version '-' trace-id '-' parent-id '-' trace-flags, all lowercase hex."""
    return f"00-{ctx.trace_id}-{ctx.span_id}-{'01' if ctx.sampled else '00'}"

def parse_traceparent(header: str) -> SpanContext:
    parts = header.strip().split("-")
    if len(parts) < 4:
        raise TraceparentError(f"expected 4 dash-separated fields, got {len(parts)}")
    version, trace_id, parent_id, flags = parts[0], parts[1], parts[2], parts[3]
    if not _is_hex(version, 2):
        raise TraceparentError("version must be 2 lowercase hex digits")
    if version == "ff":
        raise TraceparentError("version ff is forbidden by the spec")
    if version == "00" and len(parts) != 4:
        raise TraceparentError("version 00 permits exactly 4 fields, no trailing data")
    if not _is_hex(trace_id, 32):
        raise TraceparentError("trace-id must be 32 lowercase hex digits")
    if trace_id == INVALID_TRACE_ID:
        raise TraceparentError("an all-zero trace-id is invalid")
    if not _is_hex(parent_id, 16):
        raise TraceparentError("parent-id must be 16 lowercase hex digits")
    if parent_id == INVALID_SPAN_ID:
        raise TraceparentError("an all-zero parent-id is invalid")
    if not _is_hex(flags, 2):
        raise TraceparentError("trace-flags must be 2 lowercase hex digits")
    # THEIR span-id becomes OUR parent. Bit 0 of the flags byte is 'sampled'.
    return SpanContext(trace_id, parent_id, None, bool(int(flags, 16) & 0x01))

def format_baggage(items: Dict[str, str]) -> str:
    return ",".join(f"{urlparse.quote(k)}={urlparse.quote(v)}" for k, v in items.items())

def parse_baggage(header: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for member in header.split(","):
        member = member.split(";", 1)[0].strip()    # drop the optional ;properties
        if "=" in member:
            k, v = member.split("=", 1)
            out[urlparse.unquote(k.strip())] = urlparse.unquote(v.strip())
    return out

def inject(headers: Dict[str, str]) -> Dict[str, str]:
    """Write the ambient context onto an outbound carrier (HTTP or message headers)."""
    ctx = current()
    if ctx is None:
        return headers
    headers["traceparent"] = format_traceparent(ctx)
    if ctx.baggage:
        headers["baggage"] = format_baggage(ctx.baggage)
    return headers

def extract(headers: Dict[str, str]) -> Optional[SpanContext]:
    """Read a context off an inbound carrier. None if absent or malformed."""
    raw = headers.get("traceparent")
    if not raw:
        return None
    try:
        ctx = parse_traceparent(raw)
    except TraceparentError:
        return None                                 # malformed -> restart the trace
    bag = headers.get("baggage")
    return replace(ctx, baggage=parse_baggage(bag)) if bag else ctx


# ─── The logger that reads the context instead of being told ─────────────────

class Logger:
    """Emits one JSON object per event, auto-stamped with the ambient trace ids."""

    def __init__(self, service: str, sink: Optional[List[Dict[str, Any]]] = None) -> None:
        self.service, self.sink, self._lock = service, sink, threading.Lock()

    def event(self, msg: str, ts_ms: Optional[int] = None, **fields: Any) -> Dict[str, Any]:
        rec: Dict[str, Any] = {
            "ts": fmt_ts(next_ts_ms() if ts_ms is None else ts_ms),
            "level": fields.pop("level", "info"),
            "service": self.service,
            "msg": msg,
        }
        ctx = current()
        if ctx is not None:                         # <- the entire payoff of the lesson
            rec["trace_id"], rec["span_id"] = ctx.trace_id, ctx.span_id
            if ctx.parent_span_id:
                rec["parent_span_id"] = ctx.parent_span_id
            rec.update(ctx.baggage)
        rec.update(fields)
        with self._lock:
            if self.sink is None:
                print("  " + render(rec))
            else:
                self.sink.append(rec)
        return rec

_FIXED = ("ts", "level", "service", "msg", "trace_id", "span_id", "parent_span_id")

def render(rec: Dict[str, Any]) -> str:
    """One line as a log UI would show it: ids truncated, extra fields appended."""
    extra = " ".join(f"{k}={v}" for k, v in rec.items() if k not in _FIXED)
    return (f"{rec['ts']}  {rec['service']:<8} trace={rec.get('trace_id', '-')[:8]} "
            f"span={rec.get('span_id', '-')[:8]}  {rec['msg']:<18} {extra}").rstrip()


# ─── Two services, one real HTTP hop ─────────────────────────────────────────

GATEWAY_LOG = Logger("gateway")
PAYMENT_LOG = Logger("payment")

class PaymentHandler(BaseHTTPRequestHandler):
    """payment-service: extract the inbound context, continue the SAME trace."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:      # silence the default access log
        pass

    def do_POST(self) -> None:
        headers = {k.lower(): v for k, v in self.headers.items()}
        self.rfile.read(int(headers.get("content-length", 0)))
        parent = extract(headers)
        # extract-or-generate: continue their trace, or start one if there wasn't any
        ctx = (child_span(parent, random.Random(int(parent.span_id, 16)))
               if parent else new_trace(random.Random(0)))
        with use(ctx):
            PAYMENT_LOG.event("charge.authorized", amount_cents=4999,
                              parent=parent.span_id[:8] if parent else "none")
            body = json.dumps({"trace_id": ctx.trace_id, "span_id": ctx.span_id}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

def http_hop_demo() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), PaymentHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    rng = random.Random(20260718)

    root = new_trace(rng, tenant="acme")            # the edge mints the trace
    with use(root):
        GATEWAY_LOG.event("checkout.received", route="/checkout", user="u_8842")
        with span(rng):                             # a child span for the outbound call
            headers = inject({"Content-Type": "application/json"})
            print(f"  -> outbound header  traceparent: {headers['traceparent']}")
            print(f"  -> outbound header  baggage:     {headers['baggage']}")
            req = urlrequest.Request(f"http://127.0.0.1:{port}/charge",
                                     data=b'{"amount_cents":4999}',
                                     headers=headers, method="POST")
            with urlrequest.urlopen(req, timeout=5) as resp:
                seen = json.loads(resp.read())
        GATEWAY_LOG.event("checkout.completed", status=200)

    server.shutdown()
    print(f"  gateway trace_id  {root.trace_id}")
    print(f"  payment trace_id  {seen['trace_id']}   same trace: "
          f"{seen['trace_id'] == root.trace_id}")
    print(f"  payment span_id   {seen['span_id']}   (a NEW span, not the gateway's)")


# ─── Three concurrent requests in one stream ─────────────────────────────────

# Per-request step offsets in ms, chosen so the three stories genuinely interleave.
_REQUESTS = [("u_8842", [0, 31, 96, 118], 200),
             ("u_1197", [7, 22, 45, 131], 402),     # this one fails
             ("u_5563", [13, 58, 74, 89], 200)]
_BASE2_MS = _BASE_MS + 3000

def load_cart(log: Logger, rng: random.Random, ts: int) -> None:
    """Note the signature: no trace id. It reads the ambient context instead."""
    with span(rng):
        log.event("cart.loaded", ts_ms=ts, items=3)

def charge_card(log: Logger, rng: random.Random, ts: int, status: int) -> None:
    with span(rng):
        if status == 200:
            log.event("payment.captured", ts_ms=ts, amount_cents=4999)
        else:
            log.event("payment.declined", ts_ms=ts, level="error",
                      reason="insufficient_funds")

def handle_request(log: Logger, index: int) -> str:
    user, offsets, status = _REQUESTS[index]
    rng = random.Random(4200 + index)
    root = new_trace(rng)
    with use(root):
        log.event("http.received", ts_ms=_BASE2_MS + offsets[0], user=user)
        load_cart(log, rng, _BASE2_MS + offsets[1])
        charge_card(log, rng, _BASE2_MS + offsets[2], status)
        log.event("http.responded", ts_ms=_BASE2_MS + offsets[3], status=status)
    return root.trace_id

def concurrency_demo() -> tuple:
    sink: List[Dict[str, Any]] = []
    log = Logger("gateway", sink=sink)
    trace_ids: List[Optional[str]] = [None, None, None]
    barrier = threading.Barrier(3)

    def worker(i: int) -> None:
        barrier.wait()                              # make the three genuinely overlap
        trace_ids[i] = handle_request(log, i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return sorted(sink, key=lambda r: r["ts"]), trace_ids   # what a backend shows you


# ─── Across a queue, in asyncio, via message HEADERS ─────────────────────────

@dataclass
class Message:
    headers: Dict[str, str]
    body: Dict[str, Any]

async def producer(queue: "asyncio.Queue[Message]", log: Logger, index: int) -> str:
    """Each Task gets its own COPY of the context — these two never collide."""
    rng = random.Random(900 + index)
    root = new_trace(rng, tenant="acme")
    with use(root):
        log.event("order.placed", order_id=f"o_{index}")
        await asyncio.sleep(0)                      # yield: let the other task run
        with span(rng):
            msg = Message(headers=inject({}), body={"order_id": f"o_{index}"})
        queue.put_nowait(msg)
        log.event("queue.published", queue="orders", headers=len(msg.headers))
    return root.trace_id

async def consumer(queue: "asyncio.Queue[Message]", log: Logger,
                   extract_ctx: bool, seed: int) -> None:
    """A fresh Task with an EMPTY context — everything must come off the headers."""
    rng = random.Random(seed)
    while not queue.empty():
        msg = queue.get_nowait()
        assert current() is None, "a consumer starts with no ambient context"
        remote = extract(msg.headers) if extract_ctx else None
        # Not a plain child: the consumer runs later, so its span is LINKED instead.
        ctx = (replace(child_span(remote, rng), links=(remote.span_id,))
               if remote else new_trace(rng))       # no context -> ORPHAN trace
        with use(ctx):
            log.event("order.processed", order=msg.body["order_id"],
                      linked_to=ctx.links[0][:8] if ctx.links else "none")

async def queue_demo() -> tuple:
    log = Logger("worker")
    queue: asyncio.Queue = asyncio.Queue()
    ids = await asyncio.gather(producer(queue, log, 1), producer(queue, log, 2))
    await consumer(queue, log, extract_ctx=True, seed=7)
    print("  ...and now a consumer that forgets to read the headers:")
    queue.put_nowait(Message(headers={}, body={"order_id": "o_3"}))
    await consumer(queue, log, extract_ctx=False, seed=31)
    return ids


# ─── main ────────────────────────────────────────────────────────────────────

_CASES = [
    "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
    "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-00",
    "00-4BF92F3577B34DA6A3CE929D0E0E4736-00f067aa0ba902b7-01",
    "00-00000000000000000000000000000000-00f067aa0ba902b7-01",
    "00-4bf92f3577b34da6a3ce929d0e0e4736-0000000000000000-01",
    "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01-extra",
    "ff-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
    "01-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01-x9",
]

def main() -> None:
    print("== TRACEPARENT: PARSE AND VALIDATE ==")
    for case in _CASES:
        print(f"  {case}")
        try:
            ctx = parse_traceparent(case)
            print(f"      accept  span={ctx.span_id}  sampled={'yes' if ctx.sampled else 'no'}")
        except TraceparentError as exc:
            print(f"      REJECT  {exc}")

    print("\n== HTTP HOP: TWO SERVICES, ONE TRACE ==")
    http_hop_demo()

    stream, trace_ids = concurrency_demo()
    print("\n== THREE CONCURRENT REQUESTS, ONE INTERLEAVED STREAM ==")
    for rec in stream:
        print("  " + render(rec))

    target = trace_ids[1]
    print("\n== THE SAME STREAM, FILTERED TO ONE trace_id ==")
    print(f"  trace_id = {target}")
    for rec in stream:
        if rec["trace_id"] == target:
            print("  " + render(rec))

    print("\n== ACROSS A QUEUE: CONTEXT RIDES IN THE MESSAGE HEADERS ==")
    queue_ids = asyncio.run(queue_demo())
    print(f"  producer 1 trace_id  {queue_ids[0]}")
    print(f"  producer 2 trace_id  {queue_ids[1]}   (two Tasks, two contexts, no bleed)")

    print("\n== ONE RAW EVENT — WHAT IS ACTUALLY WRITTEN TO STDOUT ==")
    print("  " + json.dumps(stream[3], separators=(",", ":")))

if __name__ == "__main__":
    main()
