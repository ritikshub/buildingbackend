#!/usr/bin/env python3
"""
A distributed tracer built from scratch: the span, the span tree, W3C trace
context across a real HTTP hop, head and tail sampling, and a waterfall
renderer. Companion to docs/en.md (Phase 10, Lesson 07).

  * A SPAN is an INTERVAL, not a point: ids, parent id, name, kind, start/end,
    attributes, events, links, status. A TRACE is the tree those spans form.
  * Context flows in-process through a contextvars.ContextVar and across
    processes through the `traceparent` header (W3C Trace Context, Level 1).
  * The span model, the tree and sampling come from Google's Dapper paper
    (Sigelman et al., 2010).
  * HEAD sampling decides at the root and propagates one bit; TAIL sampling
    buffers whole traces and decides on the outcome (section 5 makes this
    trade-off numeric).

Time is a fake microsecond clock advanced by hand instead of sleeping and the
RNG is seeded, so every number reproduces exactly.

Runs on the Python standard library only:  python mini_tracer.py
"""

from __future__ import annotations
import contextvars
import json
import random
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple
from urllib import request as urlrequest


# ─── A fake monotonic clock, so durations reproduce exactly ───────────────────

class FakeClock:
    """Microsecond clock advanced by hand. work(n) means "n microseconds passed"."""
    def __init__(self, start_us: int):
        self._now = start_us
        self._lock = threading.Lock()

    def now(self) -> int:
        return self._now

    def work(self, micros: int) -> None:
        with self._lock:
            self._now += micros


CLOCK = FakeClock(start_us=1_773_544_447_000_000)   # 2026-03-14T03:14:07Z
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_RNG = random.Random(20260314)
_RNG_LOCK = threading.Lock()


def iso(us: int) -> str:
    return (_EPOCH + timedelta(microseconds=us)).strftime("%H:%M:%S.") + "%06d" % (us % 10**6)


def _hex_id(n_bytes: int) -> str:
    """A random id as lowercase hex. Real SDKs use a CSPRNG; ids are not secrets."""
    with _RNG_LOCK:
        return "%0*x" % (n_bytes * 2, _RNG.getrandbits(n_bytes * 8))


# ─── The span: the atom of a trace ────────────────────────────────────────────

class SpanKind:
    """Why the span exists. Backends use it to pair client spans with server ones."""
    SERVER = "SERVER"        # handling an inbound request
    CLIENT = "CLIENT"        # making an outbound request, blocked on the reply
    PRODUCER = "PRODUCER"    # enqueuing work; does NOT wait for it
    CONSUMER = "CONSUMER"    # processing work off a queue, later
    INTERNAL = "INTERNAL"    # in-process work; the default


class Status:
    UNSET = "UNSET"          # no opinion — backends read this as "not an error"
    OK = "OK"                # explicitly successful
    ERROR = "ERROR"          # explicitly failed


@dataclass(frozen=True)
class SpanContext:
    """The only fields that cross a process boundary. Nothing else does."""
    trace_id: str                 # 16 bytes / 32 hex chars, same for the whole trace
    span_id: str                  # 8 bytes / 16 hex chars, unique per span
    trace_flags: int = 0          # bit 0 = sampled
    remote: bool = False          # did it arrive in a header?

    @property
    def sampled(self) -> bool:
        return bool(self.trace_flags & 0x01)


@dataclass
class SpanEvent:
    name: str
    time_us: int
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Link:
    """A causal edge that is not parent/child — e.g. a consumer to its producer."""
    context: SpanContext
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Span:
    name: str
    context: SpanContext
    parent_span_id: Optional[str]
    kind: str
    resource: Dict[str, str]                            # service.name lives here
    start_us: int
    end_us: Optional[int] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[SpanEvent] = field(default_factory=list)
    links: List[Link] = field(default_factory=list)
    status: str = Status.UNSET
    status_message: str = ""

    @property
    def duration_us(self) -> int:
        return (self.start_us if self.end_us is None else self.end_us) - self.start_us

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
        self.events.append(SpanEvent(name, CLOCK.now(), dict(attributes or {})))

    def record_exception(self, exc: BaseException) -> None:
        self.add_event("exception", {"exception.type": type(exc).__name__,
                                     "exception.message": str(exc)})
        self.status, self.status_message = Status.ERROR, str(exc)


# ─── W3C Trace Context: the wire format (recap of Lesson 3) ───────────────────

def inject(ctx: SpanContext) -> str:
    """version-traceid-spanid-flags  ->  00-4bf9...c31-00f067aa0ba902b7-01"""
    return "00-%s-%s-%02x" % (ctx.trace_id, ctx.span_id, ctx.trace_flags & 0xFF)


def extract(header: Optional[str]) -> Optional[SpanContext]:
    parts = (header or "").strip().split("-")
    if len(parts) != 4 or parts[0] != "00" or [len(p) for p in parts] != [2, 32, 16, 2]:
        return None
    _, trace_id, span_id, flags = parts
    try:                                                      # all-zero ids are invalid
        if int(trace_id, 16) == 0 or int(span_id, 16) == 0:
            return None
        return SpanContext(trace_id, span_id, int(flags, 16), remote=True)
    except ValueError:
        return None


# ─── Head sampling: decide once, at the root, consistently ────────────────────

class ParentBasedRatioSampler:
    """Honour the parent's decision; at a root, hash the trace id.

    Hashing the trace id rather than flipping a coin makes the decision
    *consistent*: every service that sees this trace id computes the same
    answer, so a trace is never collected half-way.
    """
    def __init__(self, ratio: float):
        self.ratio = ratio
        self._threshold = int(ratio * (1 << 64))

    def should_sample(self, parent: Optional[SpanContext], trace_id: str) -> bool:
        if parent is not None:
            return parent.sampled                             # never split a trace
        return int(trace_id[16:], 16) < self._threshold       # low 8 bytes


# ─── The tracer: in-process context propagation ───────────────────────────────

_CURRENT: "contextvars.ContextVar[Optional[Span]]" = contextvars.ContextVar(
    "current_span", default=None)


class Tracer:
    def __init__(self, service_name: str, exporters: List[Any],
                 sampler: Optional[ParentBasedRatioSampler] = None):
        self.resource = {"service.name": service_name, "telemetry.sdk.name": "mini_tracer"}
        self.exporters = exporters
        self.sampler = sampler or ParentBasedRatioSampler(1.0)

    @contextmanager
    def start_span(self, name: str, kind: str = SpanKind.INTERNAL,
                   attributes: Optional[Dict[str, Any]] = None,
                   links: Optional[List[Link]] = None,
                   remote_parent: Optional[SpanContext] = None) -> Iterator[Span]:
        parent = remote_parent
        if parent is None:                                    # else: the enclosing span
            here = _CURRENT.get()
            parent = here.context if here is not None else None
        trace_id = parent.trace_id if parent else _hex_id(16)
        sampled = self.sampler.should_sample(parent, trace_id)
        span = Span(name, SpanContext(trace_id, _hex_id(8), 0x01 if sampled else 0x00),
                    parent.span_id if parent else None, kind, dict(self.resource),
                    CLOCK.now(), attributes=dict(attributes or {}), links=list(links or []))
        token = _CURRENT.set(span)                             # this span is now "current"
        try:
            yield span
        except BaseException as exc:                           # record, then re-raise
            span.record_exception(exc)
            raise
        finally:
            span.end_us = CLOCK.now()
            _CURRENT.reset(token)
            if sampled:                                        # unsampled spans never ship
                for exporter in self.exporters:
                    exporter.export(span)


def in_new_process(fn: Callable[[], Any]) -> Any:
    """Run fn in an EMPTY context — the honest simulation of a separate process."""
    return contextvars.Context().run(fn)


# ─── Exporters ────────────────────────────────────────────────────────────────

class InMemoryExporter:
    def __init__(self):
        self.spans: List[Span] = []
        self._lock = threading.Lock()

    def export(self, span: Span) -> None:
        with self._lock:
            self.spans.append(span)

    def trace(self, trace_id: str) -> List[Span]:
        return [s for s in self.spans if s.context.trace_id == trace_id]


class ConsoleWaterfallExporter(InMemoryExporter):
    """Draws the span tree the way a tracing UI does: bars on a shared timeline."""
    NAME_W, BAR_W = 28, 36

    def render(self, trace_id: str) -> str:
        spans = self.trace(trace_id)
        kids: Dict[Optional[str], List[Span]] = {}
        for s in spans:
            kids.setdefault(s.parent_span_id, []).append(s)
        for group in kids.values():
            group.sort(key=lambda s: (s.start_us, s.name))
        known = {s.context.span_id for s in spans}
        root = min((s for s in spans if s.parent_span_id not in known),
                   key=lambda s: s.start_us)
        t0, total = root.start_us, max(1, root.duration_us)
        # The slowest LEAF: the span actually holding the time, rather than a
        # parent that is merely blocked waiting on its children.
        parents = {s.parent_span_id for s in spans}
        slow = max((s for s in spans if s.context.span_id not in parents),
                   key=lambda s: s.duration_us)
        out = ["trace %s   %d spans   %.2fms wall" % (trace_id, len(spans), total / 1000)]
        stack: List[Tuple[Span, int]] = [(root, 0)]
        while stack:
            span, depth = stack.pop()
            off = round((span.start_us - t0) / total * self.BAR_W)
            width = max(1, min(round(span.duration_us / total * self.BAR_W), self.BAR_W - off))
            out.append("%-*s %-4s %-*s %8.2fms%s" % (
                self.NAME_W, ("  " * depth + span.name)[:self.NAME_W], span.kind[:3],
                self.BAR_W, " " * off + "█" * width, span.duration_us / 1000,
                "  ← slowest leaf" if span is slow else ""))
            stack.extend(reversed([(k, depth + 1) for k in kids.get(span.context.span_id, [])]))
        return "\n".join(out)


# ─── Structured logs that carry the trace id (the pillars joining up) ─────────

LOG_LINES: List[str] = []


def log_event(level: str, event: str, **fields: Any) -> None:
    span, rec = _CURRENT.get(), {"ts": iso(CLOCK.now()), "level": level, "event": event}
    if span is not None:
        rec.update(trace_id=span.context.trace_id, span_id=span.context.span_id)
        rec["service.name"] = span.resource["service.name"]
    rec.update(fields)
    LOG_LINES.append(json.dumps(rec))


# ─── Service 2: payment-service, behind a real HTTP server ────────────────────

class PaymentHandler(BaseHTTPRequestHandler):
    tracer: Tracer                                            # injected in main()

    def do_POST(self) -> None:
        parent = extract(self.headers.get("traceparent"))     # continue the caller's trace
        self.rfile.read(int(self.headers.get("content-length") or 0))
        with self.tracer.start_span(
                "POST /charge", kind=SpanKind.SERVER, remote_parent=parent,
                attributes={"http.request.method": "POST", "url.path": "/charge",
                            "network.protocol.version": "1.1"}) as server:
            with self.tracer.start_span("validate_card", kind=SpanKind.INTERNAL) as v:
                CLOCK.work(28_000)
                v.set_attribute("card.brand", "visa")
            CLOCK.work(500)
            budget = int(self.headers.get("x-demo-bank-us") or 4_036_500)
            with self.tracer.start_span(
                    "bank.authorize", kind=SpanKind.CLIENT,
                    attributes={"server.address": "api.bank.example",
                                "http.request.method": "POST"}) as bank:
                if budget > 1_000_000:                        # the slow path retried once
                    CLOCK.work(3_000_000)
                    bank.add_event("retry", {"attempt": 2, "reason": "upstream timeout"})
                    log_event("warn", "bank_authorize_slow", waited_ms=3000)
                    CLOCK.work(budget - 3_000_000)
                else:
                    CLOCK.work(budget)
                bank.set_attribute("http.response.status_code", 200)
            CLOCK.work(900)
            server.set_attribute("http.response.status_code", 200)
        body = json.dumps({"authorized": True}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:                # silence the access log
        pass


# ─── Service 1: the gateway ───────────────────────────────────────────────────

DB_QUERY = "SELECT * FROM order_item WHERE order_id = $1"


def gateway_checkout(tracer: Tracer, port: int, bank_us: int = 4_036_500) -> str:
    with tracer.start_span("GET /checkout", kind=SpanKind.SERVER,
                           attributes={"http.request.method": "GET", "url.path": "/checkout",
                                       "user.id": "u_8842"}) as root:
        CLOCK.work(1_500)
        with tracer.start_span("cache.get user_profile", kind=SpanKind.CLIENT,
                               attributes={"db.system.name": "redis"}) as cache:
            CLOCK.work(2_800)
            cache.set_attribute("cache.hit", True)
        CLOCK.work(400)
        for micros in (39_000, 41_500, 37_200):               # three identical = N+1
            with tracer.start_span("SELECT order_item", kind=SpanKind.CLIENT,
                                   attributes={"db.system.name": "postgresql",
                                               "db.query.text": DB_QUERY}) as q:
                CLOCK.work(micros)
                q.set_attribute("db.response.returned_rows", 1)
            CLOCK.work(300)
        CLOCK.work(300)
        url = "http://127.0.0.1:%d/charge" % port
        with tracer.start_span("POST /charge", kind=SpanKind.CLIENT,
                               attributes={"http.request.method": "POST",
                                           "server.address": "127.0.0.1",
                                           "server.port": port, "url.full": url}) as client:
            CLOCK.work(4_000)                                 # request on the wire
            req = urlrequest.Request(url, data=b"{}", method="POST", headers={
                "traceparent": inject(client.context),        # <-- context leaves the process
                "content-type": "application/json", "x-demo-bank-us": str(bank_us)})
            with urlrequest.urlopen(req, timeout=5) as resp:
                json.loads(resp.read())
            CLOCK.work(4_500)                                 # response on the wire
            client.set_attribute("http.response.status_code", 200)
        CLOCK.work(2_000)
        root.set_attribute("http.response.status_code", 200)
        return root.context.trace_id


# ─── Tail sampling: buffer the whole trace, then decide ───────────────────────

def synthetic_trace(trace_id: str, duration_us: int, failed: bool) -> List[Span]:
    res = {"service.name": "gateway"}
    root = Span("GET /checkout", SpanContext(trace_id, _hex_id(8), 0x01), None,
                SpanKind.SERVER, res, 0, duration_us)
    child = Span("POST /charge", SpanContext(trace_id, _hex_id(8), 0x01),
                 root.context.span_id, SpanKind.CLIENT, res, 1_000, duration_us - 1_000)
    if failed:
        child.status, child.status_message = Status.ERROR, "502 from payment-service"
        root.status = Status.ERROR
    return [root, child]


class TailSampler:
    """The OpenTelemetry Collector's tail_sampling processor, in miniature.

    The cost is visible in the data structure: complete traces held in RAM until
    they finish, which is why every span of a trace must reach the SAME instance.
    """
    def __init__(self, slow_us: int, base_ratio: float):
        self.slow_us = slow_us
        self.base = ParentBasedRatioSampler(base_ratio)
        self.buffer: Dict[str, List[Span]] = {}

    def add(self, span: Span) -> None:
        self.buffer.setdefault(span.context.trace_id, []).append(span)

    def decide(self, trace_id: str) -> Tuple[bool, str]:
        spans = self.buffer.pop(trace_id)
        if any(s.status == Status.ERROR for s in spans):
            return True, "error"
        if min(spans, key=lambda s: s.start_us).duration_us >= self.slow_us:
            return True, "slow"
        return (True, "probabilistic") if self.base.should_sample(None, trace_id) \
            else (False, "dropped")


# ─── Printing one span field by field ─────────────────────────────────────────

def print_span_record(span: Span, t0: int) -> None:
    rows = [("name", span.name), ("trace_id", span.context.trace_id),
            ("span_id", span.context.span_id),
            ("parent_span_id", span.parent_span_id or "(none — this is a root)"),
            ("kind", span.kind), ("service.name", span.resource["service.name"]),
            ("start / end", "%s -> %s   (%.2fms)" % (iso(span.start_us),
                                                     iso(span.end_us or 0),
                                                     span.duration_us / 1000))]
    rows += [("attributes" if i == 0 else "", "%s=%s" % kv)
             for i, kv in enumerate(span.attributes.items())]
    rows += [("events" if i == 0 else "", "+%.2fms %s %s"
              % ((e.time_us - t0) / 1000, e.name, e.attributes))
             for i, e in enumerate(span.events)]
    rows += [("links" if i == 0 else "", "trace_id=%s span_id=%s %s"
              % (ln.context.trace_id, ln.context.span_id, ln.attributes))
             for i, ln in enumerate(span.links)]
    rows.append(("status", " ".join(x for x in (span.status, span.status_message) if x)))
    for label, value in rows:
        print("  %-15s %s" % (label, value))


# ─── The demo ─────────────────────────────────────────────────────────────────

def main() -> None:
    waterfall = ConsoleWaterfallExporter()                    # stands in for a collector
    gateway = Tracer("gateway", [waterfall])
    PaymentHandler.tracer = Tracer("payment-service", [waterfall])
    server = HTTPServer(("127.0.0.1", 0), PaymentHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    # The port is ephemeral (bound with port 0), so it differs every run --
    # print the fact, not the number, to keep this transcript reproducible.
    print("== 1. ONE TRACE ACROSS TWO SERVICES (real HTTP, ephemeral port) ==")
    slow_id = gateway_checkout(gateway, port)
    fast_id = gateway_checkout(gateway, port, bank_us=85_000)
    server.shutdown()
    slow_spans = waterfall.trace(slow_id)
    print("  trace_id              %s" % slow_id)
    print("  spans / services      %d / %s"
          % (len(slow_spans), ", ".join(sorted({s.resource["service.name"]
                                                for s in slow_spans}))))
    hop = [s for s in slow_spans if s.kind == SpanKind.CLIENT and s.name == "POST /charge"][0]
    print("  crossed the wire as   traceparent: %s" % inject(hop.context))

    print("\n== 2. THE WATERFALL — a 4.2s checkout ==")
    print(waterfall.render(slow_id))
    print("\n== 2b. THE SAME CODE PATH, A FAST CHECKOUT ==")
    print(waterfall.render(fast_id))

    print("\n== 3. SPAN ANATOMY ==")
    root = min(slow_spans, key=lambda s: s.start_us)
    print_span_record([s for s in slow_spans if s.name == "bank.authorize"][0], root.start_us)
    print("\n  -- a failed span, with a LINK back to the trace above --")
    worker = Tracer("email-worker", [waterfall])
    try:
        with worker.start_span("receipt.email process", kind=SpanKind.CONSUMER,
                               links=[Link(root.context, {"link.type": "follows_from"})],
                               attributes={"messaging.system": "rabbitmq"}) as job:
            CLOCK.work(12_000)
            raise ValueError("SMTP relay refused: 550 mailbox unavailable")
    except ValueError:
        pass
    print_span_record(job, job.start_us)

    print("\n== 4. HEAD SAMPLING (probabilistic + parent-based, ratio 0.25) ==")
    head = InMemoryExporter()
    gw2 = Tracer("gateway", [head], ParentBasedRatioSampler(0.25))
    pay2 = Tracer("payment-service", [head], ParentBasedRatioSampler(0.25))
    print("  %-34s %-8s %-6s %s" % ("trace_id", "sampled", "flags", "spans kept"))
    for _ in range(8):
        with gw2.start_span("GET /checkout", kind=SpanKind.SERVER) as r:
            header, tid = inject(r.context), r.context.trace_id
            CLOCK.work(1_000)

            def downstream() -> None:                         # a different process
                with pay2.start_span("POST /charge", kind=SpanKind.SERVER,
                                     remote_parent=extract(header)):
                    CLOCK.work(500)

            in_new_process(downstream)
        print("  %-34s %-8s %-6s %d" % (tid, r.context.sampled, header[-2:],
                                        len(head.trace(tid))))
    probe = random.Random(5)
    kept = sum(1 for _ in range(10_000)
               if ParentBasedRatioSampler(0.25).should_sample(
                   None, "%032x" % probe.getrandbits(128)))
    print("  over 10000 trace ids the same sampler keeps %d (%.1f%%) — it converges"
          % (kept, kept / 100))

    print("\n== 5. TAIL SAMPLING vs A FLAT 10% HEAD SAMPLE (20 traces) ==")
    id_rng, rng = random.Random(4), random.Random(37)
    tail, flat = TailSampler(1_000_000, 0.10), ParentBasedRatioSampler(0.10)
    traces: List[List[Span]] = []
    for _ in range(20):
        failed = rng.random() < 0.15
        slow = rng.random() < 0.12
        dur = rng.randint(1_500_000, 4_500_000) if slow else rng.randint(60_000, 320_000)
        traces.append(synthetic_trace("%032x" % id_rng.getrandbits(128), dur, failed))
    for spans in traces:
        for s in spans:
            tail.add(s)                                       # the collector buffers
    kept_tail, kept_head, why_counts = [], [], {}
    for spans in traces:
        tid = spans[0].context.trace_id
        keep, why = tail.decide(tid)                          # ...then decides
        why_counts[why] = why_counts.get(why, 0) + 1
        if keep:
            kept_tail.append(tid)
        if flat.should_sample(None, tid):
            kept_head.append(tid)
    errors = [t[0].context.trace_id for t in traces if t[0].status == Status.ERROR]
    slows = [t[0].context.trace_id for t in traces if t[0].duration_us >= 1_000_000]
    hit = lambda kept, group: "%d/%d" % (len(set(kept) & set(group)), len(group))
    print("  population: 20 traces, %d with an error, %d slower than 1000ms"
          % (len(errors), len(slows)))
    print("  %-22s %-8s %-14s %s" % ("policy", "kept", "errors kept", "slow kept"))
    for label, kept in (("head, flat 10%", kept_head), ("tail: error|slow|10%", kept_tail)):
        print("  %-22s %-8s %-14s %s" % (label, "%d/20" % len(kept),
                                         hit(kept, errors), hit(kept, slows)))
    print("  tail decisions: %s" % dict(sorted(why_counts.items())))

    print("\n== 6. THE PILLARS JOIN UP ==")
    line = json.loads(LOG_LINES[0])
    match = [s for s in slow_spans if s.context.span_id == line["span_id"]][0]
    print("  log line : %s" % LOG_LINES[0])
    print("  span     : name=%s kind=%s duration=%.2fms"
          % (match.name, match.kind, match.duration_us / 1000))
    print("  the log line's trace_id == the waterfall's trace_id: %s"
          % (line["trace_id"] == slow_id))


if __name__ == "__main__":
    main()
