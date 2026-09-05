"""
A small HTTP server that shows you exactly what it received, so every curl
option in lessons 15 and 16 can be tried offline and read back.

GET /            -> a text page with the method, path, headers and cookies it saw
GET /json        -> a JSON document
POST|PUT|PATCH /anything -> echoes the body back with its length and Content-Type
GET /redirect    -> 302 to /  (and /redirect3 -> three hops)
GET /auth        -> 401 unless Basic auth user:secret is presented
GET /cookie      -> sets a cookie, and reports the ones it got
GET /slow?ms=N   -> waits N ms before answering (lesson 16)
GET /status/N    -> answers with status N
GET /big?kb=N    -> N kilobytes of body (lesson 16)
GET /gzip        -> a gzip-compressed body when Accept-Encoding allows it

Docs: phases/01-linux-and-the-command-line/15-curl-part-1-requests/docs/en.md
Run:  python echo_server.py [port]    (default 8089; Ctrl+C to stop)
"""

import base64
import gzip
import http.server
import json
import sys
import time
from urllib.parse import parse_qs, urlparse


class Echo(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "echo/1.0"

    def log_message(self, fmt, *args):
        print("server:", fmt % args, flush=True)

    def _send(self, status, body, ctype="text/plain; charset=utf-8", extra=()):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _seen(self):
        lines = [f"you sent: {self.command} {self.path} {self.request_version}", "headers:"]
        for k, v in self.headers.items():
            lines.append(f"  {k}: {v}")
        cookies = self.headers.get("Cookie")
        lines.append(f"cookies: {cookies or '(none)'}")
        return "\n".join(lines) + "\n"

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path == "/":
            self._send(200, self._seen())
        elif url.path == "/json":
            self._send(200, json.dumps({"service": "echo", "ok": True, "items": [1, 2, 3], "nested": {"k": "v"}}) + "\n", "application/json")
        elif url.path == "/redirect":
            self._send(302, "", extra=[("Location", "/")])
        elif url.path.startswith("/redirect"):
            n = int(url.path[len("/redirect"):] or 1)
            self._send(302, "", extra=[("Location", f"/redirect{n - 1}" if n > 1 else "/")])
        elif url.path == "/auth":
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Basic ") and base64.b64decode(auth[6:]).decode() == "user:secret":
                self._send(200, "welcome, user\n")
            else:
                self._send(401, "auth required\n", extra=[("WWW-Authenticate", 'Basic realm="echo"')])
        elif url.path == "/cookie":
            self._send(200, f"cookies you sent: {self.headers.get('Cookie') or '(none)'}\n",
                       extra=[("Set-Cookie", "session=abc123; Path=/; HttpOnly")])
        elif url.path == "/slow":
            time.sleep(int(q.get("ms", ["500"])[0]) / 1000)
            self._send(200, "slow but done\n")
        elif url.path.startswith("/status/"):
            code = int(url.path.rsplit("/", 1)[1])
            extra = [("Location", "/")] if code in (301, 302, 303, 307, 308) else []
            self._send(code, f"status {code} as requested\n", extra=extra)
        elif url.path == "/big":
            kb = int(q.get("kb", ["64"])[0])
            self._send(200, ("x" * 1023 + "\n") * kb)
        elif url.path == "/gzip":
            body = ("compressible text " * 200).encode()
            if "gzip" in self.headers.get("Accept-Encoding", ""):
                self._send(200, gzip.compress(body), extra=[("Content-Encoding", "gzip")])
            else:
                self._send(200, body)
        else:
            self._send(404, f"no route for {url.path}\n")

    do_HEAD = do_GET

    def _echo_body(self):
        url = urlparse(self.path)
        n = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(n) if n else b""              # always consume the body: the connection is reused
        if url.path.startswith("/redirect") or url.path.startswith("/status/"):
            return self.do_GET()                              # redirects and status codes answer every method
        ctype = self.headers.get("Content-Type", "(none)")
        text = body.decode("utf-8", "replace")
        self._send(200, f"you sent: {self.command} {self.path}\ncontent-type: {ctype}\nbody ({n} bytes):\n{text}\n")

    do_POST = do_PUT = do_PATCH = do_DELETE = _echo_body


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8089
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Echo)
    print(f"echo server on http://127.0.0.1:{port}  (Ctrl+C to stop)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
