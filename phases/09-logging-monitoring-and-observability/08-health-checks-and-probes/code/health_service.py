#!/usr/bin/env python3
"""health_service.py -- health checks, readiness and graceful shutdown from scratch.

Builds one HTTP service with three probe endpoints and the correct semantics for each:
  /startupz  startup   "has it finished booting?"    -> suspends the other two probes
  /healthz   liveness  "is this process broken?"     -> failure means KILL and restart
  /readyz    readiness "send me traffic right now?"  -> failure means remove from the LB
plus /healthz-naive, the anti-pattern liveness probe that checks the database, so you can
watch a 30s blip turn into a fleet-wide restart. Checks carry a hard/soft flag, a timeout
and a TTL cache. The finale is a real SIGTERM drain: fail readiness, wait for the load
balancer, finish in-flight work, flush telemetry, exit 0.
Follows the Kubernetes probe model and RFC 9110 section 15.6.4 (503 Service Unavailable).

Runs on the Python standard library only:  python3 health_service.py
"""

from __future__ import annotations

import json
import signal
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Tuple

WARMUP_SECONDS = 0.6          # simulated boot: config load, pool warm, cache prime
LIVENESS_MAX_STALL = 1.0      # the worker loop must tick at least this often
DRAIN_WAIT = 0.5              # "preStop: sleep" -- time for the LB to notice we are unready
DRAIN_DEADLINE = 5.0          # give up waiting for in-flight work after this

# ─── Fake dependencies you can break at runtime ──────────────────────────────
@dataclass
class FakeDependency:
    """A downstream service. Flip .healthy or raise .latency_s to break it."""
    name: str
    healthy: bool = True
    latency_s: float = 0.01

    def ping(self) -> None:
        time.sleep(self.latency_s)
        if not self.healthy:
            raise RuntimeError("connection refused")

# ─── A dependency check: named, classified, timed out, and cached ────────────
@dataclass
class DependencyCheck:
    """One readiness check. hard=True means "no traffic without it".

    Cached for ttl_s so 40 replicas probing once a second do not become 40 QPS of
    pure health traffic; the lock collapses concurrent probes into one in-flight
    check (single-flight, Phase 5 Lesson 6) instead of a stampede.
    """
    name: str
    probe: Callable[[], None]
    hard: bool = True
    timeout_s: float = 0.25
    ttl_s: float = 0.5
    probes: int = 0
    cache_hits: int = 0
    _ok: bool = True
    _detail: str = "ok"
    _expires: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def status(self) -> Tuple[bool, str]:
        with self._lock:
            now = time.monotonic()
            if now < self._expires:
                self.cache_hits += 1
                return self._ok, self._detail
            self.probes += 1
            ok, detail = self._run_with_timeout()
            self._ok, self._detail, self._expires = ok, detail, now + self.ttl_s
            return ok, detail

    def _run_with_timeout(self) -> Tuple[bool, str]:
        """Run the probe in a thread and abandon it at the deadline. A check with no
        timeout is worse than no check: the probe hangs and the pod dies waiting."""
        out: Dict[str, Any] = {}
        def run() -> None:
            try:
                self.probe()
                out["ok"], out["detail"] = True, "ok"
            except Exception as exc:                       # noqa: BLE001
                out["ok"], out["detail"] = False, "down: %s" % exc

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(self.timeout_s)
        if worker.is_alive():
            return False, "timeout after %dms" % int(self.timeout_s * 1000)
        return bool(out.get("ok")), str(out.get("detail", "unknown"))

# ─── Process state: what liveness actually looks at ──────────────────────────
@dataclass
class ServiceState:
    warm: bool = False              # startup probe: has boot finished?
    accepting: bool = True          # are we still taking new work?
    draining: bool = False          # has SIGTERM arrived?
    worker_stalled: bool = False    # simulate a deadlocked worker loop
    last_tick: float = field(default_factory=time.monotonic)
    inflight: int = 0
    telemetry: List[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def alive(self) -> Tuple[bool, str]:
        """Liveness: shallow and local. It never touches a dependency."""
        age = time.monotonic() - self.last_tick
        if age > LIVENESS_MAX_STALL:
            return False, "no worker tick for >%.1fs" % LIVENESS_MAX_STALL
        return True, "worker loop responsive"


STATE = ServiceState()
DB = FakeDependency("database")
RECS = FakeDependency("recommendations")
CHECKS = [
    DependencyCheck("database", DB.ping, hard=True, timeout_s=0.25, ttl_s=0.5),
    DependencyCheck("recommendations", RECS.ping, hard=False, timeout_s=0.25, ttl_s=0.5),
]

# ─── The endpoints ───────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:
        pass                                              # keep the transcript clean

    def _send(self, code: int, payload: Dict[str, Any], close: bool = False) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if close:                                          # tell keep-alive clients to go away
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:                              # noqa: N802
        route, _, query = self.path.partition("?")
        if route == "/startupz":
            self._startup()
        elif route in ("/healthz", "/healthz-naive"):
            self._liveness(check_db=route.endswith("naive"))
        elif route == "/readyz":
            self._readiness()
        elif route == "/work":
            self._work(query)
        else:
            self._send(404, {"error": "not found"})

    def _startup(self) -> None:
        ok = STATE.warm
        self._send(200 if ok else 503, {"status": "started"} if ok else
                   {"status": "warming", "detail": "loading config, warming pool"})

    def _liveness(self, check_db: bool) -> None:
        ok, detail = STATE.alive()
        if ok and check_db:                                # THE ANTI-PATTERN
            ok, detail = CHECKS[0].status()
        self._send(200 if ok else 503,
                   {"status": "alive" if ok else "dead", "detail": detail})

    def _readiness(self) -> None:
        if not STATE.warm:
            return self._send(503, {"status": "starting"})
        if STATE.draining:
            return self._send(503, {"status": "draining", "detail": "SIGTERM received"})
        checks, hard_down, soft_down = {}, False, False
        for chk in CHECKS:
            ok, checks[chk.name] = chk.status()
            hard_down = hard_down or (not ok and chk.hard)
            soft_down = soft_down or (not ok and not chk.hard)
        status = "unready" if hard_down else ("degraded" if soft_down else "ready")
        self._send(503 if hard_down else 200, {"status": status, "checks": checks})

    def _work(self, query: str) -> None:
        if not STATE.accepting:
            return self._send(503, {"error": "shutting down"}, close=True)
        ms = int(query.split("=")[1]) if query.startswith("ms=") else 20
        with STATE.lock:
            STATE.inflight += 1
        try:
            time.sleep(ms / 1000.0)
            STATE.telemetry.append("span:/work took_ms=%d" % ms)
            self._send(200, {"result": "ok", "took_ms": ms})
        finally:
            with STATE.lock:
                STATE.inflight -= 1

# ─── Client helpers ──────────────────────────────────────────────────────────
def probe(base: str, path: str) -> Tuple[int, Dict[str, Any]]:
    try:
        with urllib.request.urlopen(base + path, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())

def show(base: str, path: str) -> None:
    code, body = probe(base, path)
    print("  GET %-15s -> %d  %s" % (path, code, json.dumps(body)))

def worker_loop(stop: threading.Event) -> None:
    """The heartbeat liveness watches. A real one drains a queue or runs a scheduler."""
    while not stop.is_set():
        if not STATE.worker_stalled:
            STATE.last_tick = time.monotonic()
        time.sleep(0.05)

# ─── main ────────────────────────────────────────────────────────────────────
def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    base = "http://127.0.0.1:%d" % server.server_address[1]
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    stop = threading.Event()
    threading.Thread(target=worker_loop, args=(stop,), daemon=True).start()

    print("== SCENARIO A - STARTUP ==")
    threading.Timer(WARMUP_SECONDS, lambda: setattr(STATE, "warm", True)).start()
    show(base, "/startupz")
    show(base, "/readyz")
    print("  ...booting (%.1fs of config load + pool warm)" % WARMUP_SECONDS)
    time.sleep(WARMUP_SECONDS + 0.2)
    show(base, "/startupz")
    show(base, "/readyz")
    print("  startup probe gates the other two: no traffic before boot finished")
    print("\n== SCENARIO B - HARD DEPENDENCY DOWN ==")
    DB.healthy = False
    time.sleep(0.6)                                        # let the cached result expire
    show(base, "/readyz")
    show(base, "/healthz")
    print("  -> removed from the load balancer, NOT restarted. Reversible.")
    DB.healthy, DB.latency_s = True, 0.5                   # now slow instead of down
    time.sleep(0.6)
    show(base, "/readyz")
    print("  -> a 500ms database beats a 250ms check timeout: same verdict, no hang")
    DB.latency_s = 0.01
    time.sleep(0.6)
    show(base, "/readyz")
    print("  -> dependency recovered, instance back in rotation with no restart")
    print("\n== SCENARIO C - SOFT DEPENDENCY DOWN ==")
    RECS.healthy = False
    time.sleep(0.6)
    show(base, "/readyz")
    print("  -> 200 with status=degraded: serve without recommendations, stay in rotation")
    RECS.healthy = True
    time.sleep(0.6)
    print("\n== DEPENDENCY CHECK CACHING ==")
    for chk in CHECKS:
        chk.probes, chk.cache_hits = 0, 0
    for _ in range(5):
        probe(base, "/readyz")
    for chk in CHECKS:
        print("  %-16s real probes=%d  cache hits=%d  (ttl=%.1fs)"
              % (chk.name, chk.probes, chk.cache_hits, chk.ttl_s))
    print("  40 replicas x 1 probe/s = 40 QPS uncached; a 10s TTL makes it 4 QPS")
    print("\n== SCENARIO D - THE ANTI-PATTERNS ==")
    DB.healthy = False
    time.sleep(0.6)
    show(base, "/healthz")
    show(base, "/healthz-naive")
    print("  naive liveness checks the DB, so with periodSeconds=5 failureThreshold=3")
    print("  every one of 40 replicas is SIGKILLed 15s into a 30s blip -- a recoverable")
    print("  blip becomes a full outage plus a cold-start thundering herd")
    DB.healthy = True
    time.sleep(0.6)
    STATE.worker_stalled = True                            # simulate a deadlocked process
    time.sleep(LIVENESS_MAX_STALL + 0.3)
    sock = socket.create_connection(("127.0.0.1", server.server_address[1]), timeout=2)
    sock.close()
    print("  tcpSocket probe   -> PASS (the socket still accepts; the app is deadlocked)")
    show(base, "/healthz")
    print("  -> only an httpGet probe that exercises the app catches this. Restart is right.")
    STATE.worker_stalled = False
    time.sleep(0.2)
    print("\n== PROBE TUNING ARITHMETIC ==")
    print("  detection = periodSeconds x failureThreshold + timeoutSeconds")
    print("  period  threshold  timeout   detect   worst   tolerates blip up to")
    for period, threshold, timeout in ((10, 3, 1), (5, 3, 1), (5, 2, 1), (2, 3, 1)):
        print("  %5ds %9d %8ds %7ds %7ds %20ds"
              % (period, threshold, timeout,
                 period * threshold + timeout,
                 period * (threshold + 1) + timeout,
                 period * (threshold - 1)))
    print("  faster detection costs flap tolerance: 2s/3 catches a corpse in 7s but")
    print("  restarts on any 5-second hiccup. Liveness slow, readiness fast.")
    print("\n== SCENARIO E - GRACEFUL SHUTDOWN ==")
    result: Dict[str, Any] = {}
    def long_request() -> None:
        result["code"], result["body"] = probe(base, "/work?ms=900")
    inflight_thread = threading.Thread(target=long_request, daemon=True)
    inflight_thread.start()
    time.sleep(0.1)
    print("  (a /work request needing 900ms is already in flight)")
    t0 = time.monotonic()
    # The timeline label is the step's SCHEDULED offset, derived from the
    # constants below -- not a stopwatch reading. Measuring it would make the
    # transcript jitter by a few tens of milliseconds on every run. Every
    # *outcome* printed below (status codes, the in-flight result) is real.
    LB_NOTICE = 0.2                      # how long before the LB routes one more request
    IN_FLIGHT_DONE = 0.8                 # the 900ms request began 100ms before t0
    FLUSH_AT = IN_FLIGHT_DONE + 0.1
    STOPPED_AT = FLUSH_AT + 0.1

    def at(t: float, msg: str) -> None:
        print("  T+%4.1fs  %s" % (t, msg))

    def on_sigterm(signum: int, frame: Any) -> None:
        STATE.draining = True
    signal.signal(signal.SIGTERM, on_sigterm)
    signal.raise_signal(signal.SIGTERM)
    at(0.0, "SIGTERM received -> readiness fails NOW, but we keep serving")
    show(base, "/readyz")
    show(base, "/healthz")
    at(0.0, "drain wait %.1fs -- the LB has not noticed yet (k8s: preStop sleep 5)" % DRAIN_WAIT)
    time.sleep(LB_NOTICE)
    code, _ = probe(base, "/work?ms=20")
    at(LB_NOTICE, "a request the LB routed before it noticed -> %d, still served" % code)
    time.sleep(max(0.0, t0 + DRAIN_WAIT - time.monotonic()))
    STATE.accepting = False
    at(DRAIN_WAIT, "stop accepting new work (a real server closes its listening socket here)")
    code, body = probe(base, "/work?ms=20")
    at(DRAIN_WAIT, "new request -> %d %s  (Connection: close ends keep-alive)" % (code, json.dumps(body)))
    deadline = time.monotonic() + DRAIN_DEADLINE
    while STATE.inflight > 0 and time.monotonic() < deadline:
        time.sleep(0.02)
    # STATE.inflight hits 0 when the *handler* returns, a moment before the
    # client has finished reading the response -- so join the caller too, or
    # this line races the assignment of `result`.
    inflight_thread.join(timeout=max(0.0, deadline - time.monotonic()))
    at(IN_FLIGHT_DONE, "in-flight drained -> the 900ms request returned %d %s"
       % (result["code"], json.dumps(result["body"])))
    time.sleep(0.1)
    at(FLUSH_AT, "telemetry flushed: %d buffered records (Lessons 2, 4 and 7)" % len(STATE.telemetry))
    time.sleep(0.1)
    stop.set()
    at(STOPPED_AT, "worker stopped, connection pools closed")
    server.shutdown()
    server.server_close()
    print("           listening socket closed -> exit 0")
    try:
        probe(base, "/healthz")
        print("           ...still answering?")
    except (urllib.error.URLError, OSError):
        print("           a new connection is now refused: nothing died mid-request")
    print("  terminationGracePeriodSeconds=30 -> SIGKILL never fired")


if __name__ == "__main__":
    main()
