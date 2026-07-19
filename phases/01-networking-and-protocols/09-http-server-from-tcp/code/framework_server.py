"""
Capstone (Use It) — the same endpoints via the stdlib http.server.

BaseHTTPRequestHandler is the accept loop + request parser + response builder
from http_server.py, already written and hardened. You supply do_GET/do_POST and
call send_response/send_header; it handles the socket reads, the CRLF framing, and
(via send_header) the Content-Length you computed by hand next door. Also
self-terminating: server on a thread, a few client requests, shutdown, exit 0.

Docs: phases/01-networking-and-protocols/09-http-server-from-tcp/docs/en.md
Spec: RFC 9112 (HTTP/1.1), Python `http.server` (BaseHTTPRequestHandler)

Run:
    python framework_server.py
"""

import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

HOST = "127.0.0.1"
PORT = 54_319

ROUTES = {
    "/": "Welcome — same routes as http_server.py, now via http.server.\n",
    "/hello": "Hello from BaseHTTPRequestHandler.\n",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # advertise HTTP/1.1 in the status line

    def _respond(self, status, text, extra_headers=None):
        """Our own little response builder on top of the handler's plumbing."""
        payload = text.encode("utf-8")
        self.send_response(status)  # writes the "HTTP/1.1 <status> <reason>" line
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        # We still compute Content-Length ourselves — the framework only *sends*
        # the header we give it; it does not measure the body for us.
        self.send_header("Content-Length", str(len(payload)))
        for name, value in (extra_headers or []):
            self.send_header(name, value)
        self.end_headers()          # writes the blank line that ends the headers
        self.wfile.write(payload)

    def do_GET(self):
        body = ROUTES.get(self.path)  # self.path is already parsed for us
        if body is None:
            self._respond(404, "No resource at {}\n".format(self.path))
        else:
            self._respond(200, body)

    def do_POST(self):
        # Mirror the raw server: this API is read-only, so writes get 405.
        self._respond(
            405, "POST is not allowed here; this server only speaks GET.\n",
            extra_headers=[("Allow", "GET")],
        )

    def log_message(self, *args):
        pass  # silence the default one-line-per-request access log


def call(method, path):
    url = "http://{}:{}{}".format(HOST, PORT, path)
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            status, length, body = resp.status, resp.headers["Content-Length"], resp.read()
    except urllib.error.HTTPError as err:
        # urllib raises on 4xx/5xx, but the response is still fully formed.
        status, length, body = err.code, err.headers["Content-Length"], err.read()

    print("{} {}  ->  {}  (Content-Length: {})".format(method, path, status, length))
    print("    body: {!r}".format(body))


def main():
    server = HTTPServer((HOST, PORT), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    for method, path in [("GET", "/"), ("GET", "/hello"),
                         ("GET", "/missing"), ("POST", "/hello")]:
        call(method, path)

    server.shutdown()        # stop serve_forever cleanly
    thread.join(timeout=5)
    server.server_close()
    print("[done] Same accept loop + parser + builder — just already written for you.")


if __name__ == "__main__":
    main()
