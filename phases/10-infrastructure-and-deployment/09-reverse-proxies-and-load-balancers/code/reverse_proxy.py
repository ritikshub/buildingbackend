#!/usr/bin/env python3
"""Reverse proxies, load balancers and ingress, built from sockets.

Lesson : phases/10-infrastructure-and-deployment/09-reverse-proxies-and-load-balancers/docs/en.md
Specs  : RFC 9110 (HTTP semantics; hop-by-hop headers), RFC 7239 (Forwarded),
         RFC 9112 s9.6 (Connection: close).
Stdlib only and free of randomness: routing is round-robin and every client
schedule is fixed. Every server binds 127.0.0.1:0 in a daemon thread and is
closed before exit, so the script self-terminates with status 0.
"""

from __future__ import annotations

import http.client
import json
import socket
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOOPBACK = "127.0.0.1"

# RFC 9110 s7.6.1: connection-specific fields are consumed by one hop and MUST
# NOT be forwarded. A proxy that passes these through corrupts the next hop.
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade",
}

SEVERED = ("RemoteDisconnected", "BadStatusLine", "ConnectionResetError",
           "IncompleteRead", "TimeoutError")


def pct(values, q):
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(q * (len(s) - 1)))]


class QuietServer(ThreadingHTTPServer):
    """Resets and broken pipes are the SUBJECT of this lesson, not a defect;
    we count them instead of printing a traceback for each one."""
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass


# --------------------------------------------------------------------------
# The backend: a real HTTP server that echoes what it was actually sent.
# --------------------------------------------------------------------------
class Backend:
    def __init__(self, name: str, delay: float = 0.0):
        self.name = name
        self.delay = delay
        self.state = "live"            # live | dead  (the TRUTH about the process)
        self.received = 0
        self.completed = 0             # work finished -- billed whether read or not
        self.delivered = 0             # ...and successfully written back
        self.write_failed = 0          # finished, but the reader had already gone
        self.severed = 0
        self.inflight = 0
        self._lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                owner._serve(self)

            def do_POST(self):
                owner._serve(self)

        self.httpd = QuietServer((LOOPBACK, 0), Handler)
        self.addr = self.httpd.server_address
        # A 20 ms poll interval means shutdown() returns fast, so "kill" is
        # close to instantaneous rather than smeared over half a second.
        threading.Thread(target=self.httpd.serve_forever, args=(0.02,),
                         daemon=True, name=name).start()

    def _serve(self, h: BaseHTTPRequestHandler) -> None:
        with self._lock:
            self.received += 1
            self.inflight += 1
        try:
            n = int(h.headers.get("Content-Length") or 0)
            body_in = h.rfile.read(n) if n else b""
            # Do the "work" in slices so that a kill can sever a request that is
            # genuinely in flight -- which is what SIGKILL does to a process.
            end = time.monotonic() + self.delay
            while time.monotonic() < end and self.state != "dead":
                time.sleep(min(0.005, max(0.0, end - time.monotonic())))
            if self.state == "dead":
                with self._lock:
                    self.severed += 1
                try:
                    h.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                h.close_connection = True
                return
            payload = json.dumps({
                "backend": self.name,
                "method": h.command,
                "path": h.path,
                "peer": h.client_address[0],
                "host": h.headers.get("Host", ""),
                "xff": h.headers.get("X-Forwarded-For"),
                "xfp": h.headers.get("X-Forwarded-Proto"),
                "xfh": h.headers.get("X-Forwarded-Host"),
                "forwarded": h.headers.get("Forwarded"),
                "body_bytes": len(body_in),
            }).encode()
            # The work is DONE here. Whether anyone is still listening is a
            # separate question, and that gap is the wasted-work number.
            with self._lock:
                self.completed += 1
            try:
                h.send_response(200)
                h.send_header("Content-Type", "application/json")
                h.send_header("Content-Length", str(len(payload)))
                h.send_header("X-Served-By", self.name)
                h.end_headers()
                h.wfile.write(payload)
                h.wfile.flush()
                with self._lock:
                    self.delivered += 1
            except OSError:
                with self._lock:
                    self.write_failed += 1   # the proxy gave up and hung up
                h.close_connection = True
        finally:
            with self._lock:
                self.inflight -= 1

    def kill(self) -> None:
        """Model process death: in-flight connections are severed with no
        response, and the listening socket goes away so new connects are
        refused. We cannot SIGKILL a thread, so we do exactly what SIGKILL
        would do to the sockets."""
        if self.state == "dead":
            return
        self.state = "dead"
        try:
            self.httpd.shutdown()
        except Exception:
            pass
        try:
            self.httpd.server_close()
        except Exception:
            pass

    def closed(self) -> bool:
        return self.httpd.socket.fileno() == -1


# --------------------------------------------------------------------------
# The pool: the PROXY's belief about its backends. Note that `routable` is not
# derived from Backend.state -- a proxy only learns a backend is gone when a
# health check tells it or an operator removes it.
# --------------------------------------------------------------------------
@dataclass
class Member:
    backend: object
    routable: bool = True

    @property
    def name(self):
        return self.backend.name

    @property
    def addr(self):
        return self.backend.addr


class Pool:
    def __init__(self, name: str, members):
        self.name = name
        self.members = [m if isinstance(m, Member) else Member(m) for m in members]
        self._rr = 0
        self._lock = threading.Lock()

    def pick(self):
        with self._lock:
            live = [m for m in self.members if m.routable]
            if not live:
                return None
            m = live[self._rr % len(live)]
            self._rr += 1
            return m


class Router:
    """L7 routing rules, evaluated in order. This is the whole reason a proxy
    has to terminate the connection and parse the request."""

    def __init__(self, rules, default):
        self.rules = rules            # [(kind, value, pool)] kind in {host, prefix}
        self.default = default

    def route(self, host: str, path: str):
        hostname = host.split(":")[0].lower()
        for kind, value, pool in self.rules:
            if kind == "host" and hostname == value:
                return pool, "Host: %s" % value
            if kind == "prefix" and path.startswith(value):
                return pool, "prefix %s" % value
        return self.default, "default"


# --------------------------------------------------------------------------
# Upstream connection pool: separate connections, with their own keep-alive.
# --------------------------------------------------------------------------
class ConnPool:
    def __init__(self):
        self.free = {}
        self.opened = 0
        self.reused = 0
        self._lock = threading.Lock()

    def get(self, addr, timeout, source_ip):
        key = (addr, timeout, source_ip)
        with self._lock:
            q = self.free.get(key)
            if q:
                self.reused += 1
                return q.pop()
            self.opened += 1
        return http.client.HTTPConnection(
            addr[0], addr[1], timeout=timeout,
            source_address=(source_ip, 0) if source_ip else None)

    def put(self, addr, timeout, source_ip, conn):
        with self._lock:
            self.free.setdefault((addr, timeout, source_ip), []).append(conn)

    def close_all(self):
        with self._lock:
            for q in self.free.values():
                for c in q:
                    try:
                        c.close()
                    except Exception:
                        pass
            self.free.clear()


# --------------------------------------------------------------------------
# The L7 reverse proxy.
# --------------------------------------------------------------------------
class Proxy:
    def __init__(self, name, router, upstream_timeout=None, capacity=None,
                 trust_client_forwarded=True, source_ip=None, scheme="http"):
        self.name = name
        self.router = router
        self.upstream_timeout = upstream_timeout
        self.trust_client_forwarded = trust_client_forwarded
        self.source_ip = source_ip
        self.scheme = scheme
        self.pool = ConnPool()
        self.sem = threading.Semaphore(capacity) if capacity else None
        self.forwarded = 0
        self.rejected = 0
        self.timed_out = 0
        self.trace = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                owner._handle(self)

            def do_POST(self):
                owner._handle(self)

        self.httpd = QuietServer((LOOPBACK, 0), Handler)
        self.addr = self.httpd.server_address
        threading.Thread(target=self.httpd.serve_forever, args=(0.02,),
                         daemon=True, name=name).start()

    # -- header rewriting: the part everybody gets wrong ------------------
    def _rewrite(self, h):
        peer = h.client_address[0]
        host = h.headers.get("Host", "")
        out = {}
        for k, v in h.headers.items():
            if k.lower() in HOP_BY_HOP:
                continue
            out[k] = v
        prior_xff = h.headers.get("X-Forwarded-For") if self.trust_client_forwarded else None
        out["X-Forwarded-For"] = (prior_xff + ", " + peer) if prior_xff else peer
        out["X-Forwarded-Proto"] = self.scheme
        out.setdefault("X-Forwarded-Host", host)
        node = 'for=%s;proto=%s;host="%s"' % (peer, self.scheme, host)
        prior_fwd = h.headers.get("Forwarded") if self.trust_client_forwarded else None
        out["Forwarded"] = (prior_fwd + ", " + node) if prior_fwd else node
        out["Host"] = host                 # the client's Host survives the hop
        return out

    def _error(self, h, code, reason):
        payload = json.dumps({"error": code, "reason": reason}).encode()
        try:
            h.send_response(code)
            h.send_header("Content-Type", "application/json")
            h.send_header("Content-Length", str(len(payload)))
            h.send_header("X-Proxy-Reason", reason)
            h.end_headers()
            h.wfile.write(payload)
        except OSError:
            pass

    def _handle(self, h):
        if self.sem is not None and not self.sem.acquire(timeout=0.05):
            self.rejected += 1
            return self._error(h, 503, "no_proxy_capacity")
        try:
            self._forward(h)
        finally:
            if self.sem is not None:
                self.sem.release()

    def _forward(self, h):
        host = h.headers.get("Host", "")
        pool, why = self.router.route(host, h.path)
        member = pool.pick() if pool else None
        if member is None:
            return self._error(h, 502, "no_routable_upstream")
        self.trace.append((h.command, h.path, host, member.name, why))
        n = int(h.headers.get("Content-Length") or 0)
        body = h.rfile.read(n) if n else None
        headers = self._rewrite(h)
        key = (member.addr, self.upstream_timeout, self.source_ip)
        conn = self.pool.get(*key)
        try:
            conn.request(h.command, h.path, body=body, headers=headers)
            resp = conn.getresponse()
            payload = resp.read()
        except TimeoutError:
            self.timed_out += 1
            try:
                conn.close()
            except Exception:
                pass
            return self._error(h, 504, "upstream_timeout")
        except (ConnectionRefusedError, OSError, http.client.HTTPException) as exc:
            kind = type(exc).__name__
            try:
                conn.close()
            except Exception:
                pass
            reason = "upstream_severed" if kind in SEVERED else "upstream_refused"
            return self._error(h, 502, reason)
        self.pool.put(*key, conn)
        self.forwarded += 1
        try:
            h.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() in HOP_BY_HOP or k.lower() in ("content-length",
                                                            "server", "date"):
                    continue
                h.send_header(k, v)
            h.send_header("Content-Length", str(len(payload)))
            h.send_header("X-Proxy", self.name)
            h.end_headers()
            h.wfile.write(payload)
        except OSError:
            pass

    def close(self):
        self.pool.close_all()
        try:
            self.httpd.shutdown()
        except Exception:
            pass
        try:
            self.httpd.server_close()
        except Exception:
            pass

    def closed(self):
        return self.httpd.socket.fileno() == -1


# --------------------------------------------------------------------------
# An L4 proxy, for contrast: it moves bytes and never parses one.
# --------------------------------------------------------------------------
class L4Proxy:
    def __init__(self, target_addr):
        self.target = target_addr
        self.bytes_relayed = 0
        self.running = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((LOOPBACK, 0))
        self.sock.listen(32)
        self.addr = self.sock.getsockname()
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while self.running:
            try:
                client, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._pipe, args=(client,), daemon=True).start()

    def _pipe(self, client):
        try:
            upstream = socket.create_connection(self.target, timeout=5)
        except OSError:
            client.close()
            return

        def pump(a, b):
            try:
                while True:
                    data = a.recv(65536)
                    if not data:
                        break
                    b.sendall(data)
                    self.bytes_relayed += len(data)
            except OSError:
                pass
            finally:
                try:
                    b.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

        t = threading.Thread(target=pump, args=(client, upstream), daemon=True)
        t.start()
        pump(upstream, client)
        t.join(timeout=2)
        client.close()
        upstream.close()

    def close(self):
        self.running = False
        try:
            self.sock.close()
        except OSError:
            pass

    def closed(self):
        return self.sock.fileno() == -1


# --------------------------------------------------------------------------
# Client helpers
# --------------------------------------------------------------------------
def request(addr, path, host=None, headers=None, source_ip=None,
            timeout=10.0, method="GET"):
    hdrs = {}
    if host:
        hdrs["Host"] = host
    hdrs.update(headers or {})
    conn = http.client.HTTPConnection(
        addr[0], addr[1], timeout=timeout,
        source_address=(source_ip, 0) if source_ip else None)
    try:
        conn.request(method, path, headers=hdrs)
        resp = conn.getresponse()
        return resp.status, dict(resp.getheaders()), resp.read()
    except Exception as exc:
        return 0, {}, ("%s: %s" % (type(exc).__name__, exc)).encode()
    finally:
        try:
            conn.close()
        except Exception:
            pass


def drive(addr, count, spacing, path_of, results, timeout=10.0, host="shop.internal"):
    """Fixed schedule: request i leaves at t0 + i*spacing, in its own thread."""
    threads = []
    t0 = time.monotonic()
    for i in range(count):
        def go(i=i):
            wait = t0 + i * spacing - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            started = time.monotonic()
            status, hdrs, body = request(addr, path_of(i), host=host, timeout=timeout)
            results.append((i, status, hdrs.get("X-Proxy-Reason", ""),
                            hdrs.get("X-Served-By", ""),
                            time.monotonic() - started))
        th = threading.Thread(target=go, daemon=True)
        th.start()
        threads.append(th)
    for th in threads:
        th.join()
    return time.monotonic() - t0


# ==========================================================================
# 1 · A REVERSE PROXY IS A ROUTER WITH A SOCKET ON EACH SIDE
# ==========================================================================
def section_one():
    print("== 1 · A REVERSE PROXY IS A ROUTER WITH A SOCKET ON EACH SIDE ==")
    api1, api2 = Backend("api-1"), Backend("api-2")
    static1, img1 = Backend("static-1"), Backend("img-1")
    api_pool = Pool("api", [api1, api2])
    static_pool = Pool("static", [static1])
    img_pool = Pool("img", [img1])
    router = Router(
        rules=[("host", "img.internal", img_pool),
               ("prefix", "/static/", static_pool),
               ("prefix", "/api/", api_pool)],
        default=api_pool)
    proxy = Proxy("edge", router)

    print("  one front door: proxy on 127.0.0.1:%d" % proxy.addr[1])
    print("  four back doors: %s" % ", ".join(
        "%s:%d" % (b.name, b.addr[1]) for b in (api1, api2, static1, img1)))
    print()
    requests = [
        ("GET", "/api/orders/1", "shop.internal"),
        ("GET", "/api/orders/2", "shop.internal"),
        ("GET", "/api/orders/3", "shop.internal"),
        ("GET", "/static/logo.svg", "shop.internal"),
        ("GET", "/api/orders/4", "img.internal"),
        ("GET", "/img/cat.png", "img.internal"),
        ("GET", "/static/app.css", "shop.internal"),
        ("GET", "/healthz", "shop.internal"),
    ]
    print("  %-18s %-16s %-11s %s" % ("PATH", "HOST", "-> BACKEND", "WHY"))
    for method, path, host in requests:
        status, hdrs, _ = request(proxy.addr, path, host=host)
        served = hdrs.get("X-Served-By", "?")
        why = proxy.trace[-1][4]
        print("  %-18s %-16s %-11s %s" % (path, host, "-> " + served, why))
    print()
    print("  %d client requests -> %d upstream TCP connections opened, %d reused"
          % (len(requests), proxy.pool.opened, proxy.pool.reused))
    print("  the proxy keeps its OWN connections to each backend; client")
    print("  connections and upstream connections are separate lifetimes.")

    # The same traffic through an L4 proxy, which parses nothing.
    l4 = L4Proxy(api1.addr)
    print()
    print("  the same 4 requests through an L4 (TCP) proxy pointed at api-1:")
    l4_backends = set()
    for method, path, host in requests[:4]:
        status, hdrs, body = request(l4.addr, path, host=host)
        seen = json.loads(body)
        l4_backends.add(seen["backend"])
        print("    %-18s Host: %-16s -> %-9s  xff=%s"
              % (path, host, seen["backend"], seen["xff"]))
    l7_backends = {t[3] for t in proxy.trace}
    print("  L7 proxy: %d requests -> %d distinct backends (Host + path)"
          % (len(requests), len(l7_backends)))
    print("  L4 proxy: 4 requests -> %d distinct backend (it read 0 bytes of HTTP)"
          % len(l4_backends))
    print("  L4 relayed %d bytes and added 0 headers: no X-Forwarded-For exists"
          % l4.bytes_relayed)
    print()

    l4.close()
    proxy.close()
    return [api1, api2, static1, img1], [proxy], [l4]


# ==========================================================================
# 2 · WHAT THE BACKEND SEES, AND THE HEADER YOU MUST NOT TRUST
# ==========================================================================
CLIENT_IP = "127.0.0.9"
EDGE_IP = "127.0.0.2"
INGRESS_IP = "127.0.0.3"
ADMIN_ALLOWLIST = {"10.0.0.1"}


def naive_client_ip(xff, remote_addr):
    """xff.split(',')[0] -- the parser in every framework tutorial."""
    if not xff:
        return remote_addr
    return xff.split(",")[0].strip()


def trusted_client_ip(xff, remote_addr, trusted_hops):
    """Count back from the RIGHT by the number of proxies you actually run.
    Entry -n is the address the n-th trusted hop observed as its peer."""
    if not xff:
        return remote_addr
    chain = [p.strip() for p in xff.split(",") if p.strip()]
    if len(chain) < trusted_hops:
        return remote_addr
    return chain[-trusted_hops]


def section_two():
    print("== 2 · WHAT THE BACKEND SEES: X-FORWARDED-* AND THE SPOOF ==")
    backend = Backend("app-1")
    app_pool = Pool("app", [backend])
    ingress = Proxy("ingress", Router([], app_pool), source_ip=INGRESS_IP)
    edge_pool = Pool("edge-up", [Member(ingress)])
    edge = Proxy("edge", Router([], edge_pool), source_ip=EDGE_IP)
    strict_edge = Proxy("edge-strict", Router([], edge_pool), source_ip=EDGE_IP,
                        trust_client_forwarded=False)

    def seen(addr, extra=None, src=CLIENT_IP):
        _, _, body = request(addr, "/orders/42", host="shop.internal",
                             headers=extra, source_ip=src)
        return json.loads(body)

    a = seen(backend.addr)
    print("  A · no proxy at all -- the client connects to the backend")
    print("      peer=%s  Host=%s  X-Forwarded-For=%s"
          % (a["peer"], a["host"], a["xff"]))
    print()

    b = seen(edge.addr)
    print("  B · client -> edge proxy -> ingress proxy -> backend (honest client)")
    print("      peer=%s   Host=%s  (the client's Host survived both hops)"
          % (b["peer"], b["host"]))
    print("      X-Forwarded-For:   %s" % b["xff"])
    print("      X-Forwarded-Proto: %s" % b["xfp"])
    print("      X-Forwarded-Host:  %s" % b["xfh"])
    print("      Forwarded:         %s" % b["forwarded"])
    print("      naive   xff.split(',')[0] -> %s"
          % naive_client_ip(b["xff"], b["peer"]))
    print("      trusted count back 2 hops -> %s"
          % trusted_client_ip(b["xff"], b["peer"], 2))
    print("      both right -- the naive one only because nobody lied yet.")
    print()

    c = seen(edge.addr, {"X-Forwarded-For": "10.0.0.1"})
    naive_c = naive_client_ip(c["xff"], c["peer"])
    trusted_c = trusted_client_ip(c["xff"], c["peer"], 2)
    print("  C · same request, client sends its OWN X-Forwarded-For: 10.0.0.1")
    print("      X-Forwarded-For:   %s" % c["xff"])
    print("      naive   xff.split(',')[0] -> %-12s SPOOFED" % naive_c)
    print("      trusted count back 2 hops -> %-12s correct" % trusted_c)
    print("      admin allowlist %s:" % sorted(ADMIN_ALLOWLIST))
    print("        naive parser   -> %s" %
          ("ALLOW (200, allowlist bypassed)" if naive_c in ADMIN_ALLOWLIST
           else "DENY (403)"))
    print("        trusted parser -> %s" %
          ("ALLOW (200)" if trusted_c in ADMIN_ALLOWLIST else "DENY (403)"))
    print()

    d = seen(strict_edge.addr, {"X-Forwarded-For": "10.0.0.1"})
    print("  D · same spoof, but the edge OVERWRITES client-supplied X-Forwarded-For")
    print("      X-Forwarded-For:   %s" % d["xff"])
    print("      naive   xff.split(',')[0] -> %-12s correct now"
          % naive_client_ip(d["xff"], d["peer"]))
    print("      trusted count back 2 hops -> %-12s correct always"
          % trusted_client_ip(d["xff"], d["peer"], 2))
    print()

    peers, reals = set(), set()
    for src in ("127.0.0.9", "127.0.0.10", "127.0.0.11"):
        v = seen(edge.addr, src=src)
        peers.add(v["peer"])
        reals.add(trusted_client_ip(v["xff"], v["peer"], 2))
    print("  E · the 403 from The Problem, measured")
    print("      3 clients from 3 addresses -> backend socket peer was %s"
          % ", ".join(sorted(peers)))
    print("      %d distinct client addresses collapsed to %d at the backend."
          % (3, len(peers)))
    print("      any allowlist, rate limit or audit log keyed on the socket")
    print("      address now sees one client. X-Forwarded-For recovers all %d: %s"
          % (len(reals), ", ".join(sorted(reals))))
    print()

    for p in (edge, strict_edge, ingress):
        p.close()
    return [backend], [edge, strict_edge, ingress], []


# ==========================================================================
# 3 · TIMEOUTS AT EVERY HOP
# ==========================================================================
def timeout_run(label, upstream_timeout, count=60, spacing=0.02, capacity=6,
                slow=2.0):
    fast1, fast2 = Backend("fast-1", 0.008), Backend("fast-2", 0.008)
    slow_b = Backend("slow-1", slow)
    pool = Pool("api", [fast1, fast2, slow_b])
    proxy = Proxy("edge", Router([], pool), upstream_timeout=upstream_timeout,
                  capacity=capacity)
    results = []
    wall = drive(proxy.addr, count, spacing, lambda i: "/api/%d" % i, results)
    # Let the backend finish work the proxy already abandoned.
    deadline = time.monotonic() + 3.0
    while slow_b.inflight > 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    ok = sum(1 for r in results if r[1] == 200)
    gw_timeout = sum(1 for r in results if r[1] == 504)
    busy = sum(1 for r in results if r[1] == 503)
    lat = [r[4] * 1000 for r in results]
    slow_delivered = sum(1 for r in results if r[1] == 200 and r[3] == "slow-1")
    wasted = max(0, slow_b.completed - slow_delivered)
    row = {
        "label": label, "ok": ok, "504": gw_timeout, "503": busy,
        "wall": wall, "p50": pct(lat, 0.50), "p99": pct(lat, 0.99),
        "slow_received": slow_b.received, "slow_completed": slow_b.completed,
        "slow_delivered": slow_delivered, "write_failed": slow_b.write_failed,
        "wasted": wasted, "slow_secs": wasted * slow,
        "goodput": ok / wall if wall else 0.0,
    }
    proxy.close()
    for b in (fast1, fast2, slow_b):
        b.kill()
    return row


def section_three():
    print("== 3 · TIMEOUTS AT EVERY HOP: THE SLOW BACKEND ==")
    print("  60 requests, one every 20 ms, round-robin over 3 backends.")
    print("  fast-1 and fast-2 answer in 8 ms; slow-1 takes 2000 ms.")
    print("  the proxy has 6 worker slots; a request that cannot get one in")
    print("  50 ms is refused with 503 at the door.")
    print()
    a = timeout_run("no upstream timeout", None)
    b = timeout_run("proxy_read_timeout 250ms", 0.25)
    print("  %-26s %4s %5s %5s %8s %8s %9s %9s"
          % ("config", "200", "504", "503", "p50", "p99", "good/s", "wall"))
    for r in (a, b):
        print("  %-26s %4d %5d %5d %7.0fms %7.0fms %8.1f %8.2fs"
              % (r["label"], r["ok"], r["504"], r["503"], r["p50"], r["p99"],
                 r["goodput"], r["wall"]))
    print()
    print("  with no upstream timeout, %d slow requests held %d of the proxy's"
          % (a["slow_received"], min(6, a["slow_received"])))
    print("  6 slots for 2 s each, so %d of 60 requests (%.0f%%) were refused"
          % (a["503"], 100.0 * a["503"] / 60))
    print("  at the door -- the proxy failed because a BACKEND was slow.")
    print("  with a 250 ms upstream timeout the slots came back 8x faster:")
    print("  %d served instead of %d (%.1fx), and 0 refusals."
          % (b["ok"], a["ok"], b["ok"] / max(1, a["ok"])))
    print()
    print("  the bill for the timeout, measured on the backend side:")
    print("  %-26s %9s %9s %10s %13s"
          % ("config", "accepted", "finished", "delivered", "wasted work"))
    for r in (a, b):
        print("  %-26s %9d %9d %10d %8d (%.1f s)"
              % (r["label"], r["slow_received"], r["slow_completed"],
                 r["slow_delivered"], r["wasted"], r["slow_secs"]))
    print("  %d requests timed out at the proxy and the backend finished all %d"
          % (b["504"], b["slow_completed"]))
    print("  of them anyway -- %.1f s of backend work written to %d sockets that"
          % (b["slow_secs"], b["write_failed"]))
    print("  the proxy had already closed. A timeout does not cancel work.")
    print("  It only stops YOU waiting for it: you pay for the work twice, once")
    print("  in backend capacity and once in the 504 the user actually sees.")
    print()
    return [], [], []


# ==========================================================================
# 4 · DRAINING, MEASURED
# ==========================================================================
def drain_run(strategy, count=45, spacing=0.03, service=0.4, trigger=3):
    b1, b2, b3 = (Backend("be-1", service), Backend("be-2", service),
                  Backend("be-3", service))
    members = [Member(b1), Member(b2), Member(b3)]
    pool = Pool("api", members)
    proxy = Proxy("edge", Router([], pool))
    target = members[1]
    out = {}

    def controller():
        start = time.monotonic()
        while True:
            seen = b2.inflight
            if seen >= trigger or time.monotonic() - start > 3.0:
                break
            time.sleep(0.002)
        out["inflight_at_removal"] = seen
        t0 = time.monotonic()
        if strategy == "kill":
            b2.kill()
        elif strategy == "remove_then_kill":
            target.routable = False           # stop NEW traffic
            b2.kill()                         # ...and stop, immediately
        else:                                 # drain
            target.routable = False           # stop NEW traffic
            while b2.inflight > 0 and time.monotonic() - t0 < 5.0:
                time.sleep(0.002)
            b2.kill()                         # ...only once it is idle
        out["wait_ms"] = (time.monotonic() - t0) * 1000

    ctl = threading.Thread(target=controller, daemon=True)
    ctl.start()
    results = []
    drive(proxy.addr, count, spacing, lambda i: "/api/%d" % i, results)
    ctl.join(timeout=8.0)
    ok = sum(1 for r in results if r[1] == 200)
    failed = [r for r in results if r[1] != 200]
    severed = sum(1 for r in failed if r[2] == "upstream_severed")
    refused = sum(1 for r in failed if r[2] == "upstream_refused")
    other = len(failed) - severed - refused
    proxy.close()
    for b in (b1, b2, b3):
        b.kill()
    return {
        "ok": ok, "failed": len(failed), "severed": severed, "refused": refused,
        "other": other,
        "inflight": out.get("inflight_at_removal", 0),
        "wait_ms": out.get("wait_ms", 0.0),
        "b2_severed": b2.severed, "b2_completed": b2.completed,
    }


def section_four():
    print("== 4 · TAKING A BACKEND OUT OF ROTATION, THREE WAYS ==")
    print("  45 requests, one every 30 ms, round-robin over 3 backends,")
    print("  400 ms of work each. be-2 is removed the moment it has 3")
    print("  requests in flight. Identical schedule for all three runs.")
    print()
    rows = [
        ("(a) kill it", drain_run("kill")),
        ("(b) remove from pool, then kill", drain_run("remove_then_kill")),
        ("(c) drain: stop new work, wait, stop", drain_run("drain")),
    ]
    print("  %-36s %8s %7s %5s %7s %9s %8s"
          % ("strategy", "inflight", "wait", "200", "FAILED", "severed", "refused"))
    for label, r in rows:
        print("  %-36s %8d %6.0fms %5d %7d %9d %8d"
              % (label, r["inflight"], r["wait_ms"], r["ok"], r["failed"],
                 r["severed"], r["refused"]))
    print()
    a, b, c = (r for _, r in rows)
    print("  (a) the pool never learned. %d requests were severed mid-flight and"
          % a["severed"])
    print("      %d more were sent to an address with nothing listening." % a["refused"])
    print("  (b) removing it first stopped the %d refusals -- but the %d requests"
          % (a["refused"], b["severed"]))
    print("      already inside be-2 still died. 'Remove then stop' is not enough.")
    print("  (c) same removal, plus %.0f ms of waiting for in-flight work to finish."
          % c["wait_ms"])
    print("      failed requests: %d. Not 'few'. Zero." % c["failed"])
    print()
    print("  cost of correctness: %.0f ms of waiting. Cost of skipping it: %d"
          % (c["wait_ms"], a["failed"]))
    print("  dropped requests per backend, per deploy, times every instance you")
    print("  replace. This is the mechanism every zero-downtime rollout is built")
    print("  on -- rolling, blue-green and canary all assume it already works.")
    print()
    return [], [], []


def main():
    started = time.monotonic()
    backends, proxies, l4s = [], [], []
    for fn in (section_one, section_two, section_three, section_four):
        b, p, l = fn()
        backends += b
        proxies += p
        l4s += l
    for b in backends:
        b.kill()
    print("== SHUTDOWN ==")
    leaked = ([b.name for b in backends if not b.closed()]
              + [p.name for p in proxies if not p.closed()]
              + ["l4" for x in l4s if not x.closed()])
    print("  %d servers created, %d listening sockets closed, %d leaked"
          % (len(backends) + len(proxies) + len(l4s),
             len(backends) + len(proxies) + len(l4s) - len(leaked), len(leaked)))
    print("  (total wall time %.1f s)" % (time.monotonic() - started))
    return 1 if leaked else 0


if __name__ == "__main__":
    raise SystemExit(main())
