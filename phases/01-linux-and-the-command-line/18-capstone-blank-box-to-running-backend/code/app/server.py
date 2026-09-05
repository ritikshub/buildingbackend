"""
The capstone's backend: a small HTTP API that behaves like a production
service is supposed to. It reads config from the environment, writes its
state under /var/lib/app and its log to stdout (journald), answers /health
and /api/notes (GET lists, POST adds), drains on SIGTERM, reloads on SIGHUP,
and refuses to run as root.

Docs: phases/01-linux-and-the-command-line/18-capstone-blank-box-to-running-backend/docs/en.md
Run:  PORT=8080 STATE_DIR=/tmp/app python3 server.py
"""

import http.server
import json
import os
import signal
import sys
import time

PORT = int(os.environ.get("PORT", "8080"))
BIND = os.environ.get("BIND", "127.0.0.1")
STATE_DIR = os.environ.get("STATE_DIR", "/var/lib/app")
NOTES = os.path.join(STATE_DIR, "notes.jsonl")
STARTED = time.time()
CONFIG = {"greeting": os.environ.get("GREETING", "hello")}

if os.getuid() == 0:
    print("refusing to run as root: set User= in the unit (lesson 06)", file=sys.stderr, flush=True)
    sys.exit(3)


class Api(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "app/1.0"

    def log_message(self, fmt, *args):
        print(f"request {self.client_address[0]} {fmt % args}", flush=True)

    def _json(self, status, obj):
        body = (json.dumps(obj) + "\n").encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"status": "ok", "uptime_s": round(time.time() - STARTED, 1), "pid": os.getpid(), "uid": os.getuid()})
        elif self.path == "/api/notes":
            notes = []
            if os.path.exists(NOTES):
                with open(NOTES) as f:
                    notes = [json.loads(l) for l in f if l.strip()]
            self._json(200, {"greeting": CONFIG["greeting"], "notes": notes})
        else:
            self._json(404, {"error": "no such route"})

    def do_POST(self):
        if self.path != "/api/notes":
            return self._json(404, {"error": "no such route"})
        n = int(self.headers.get("Content-Length", "0"))
        try:
            note = json.loads(self.rfile.read(n) or b"{}")
            text = str(note["text"])
        except (ValueError, KeyError):
            return self._json(400, {"error": "body must be JSON with a 'text' field"})
        record = {"text": text, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(NOTES, "a") as f:                                   # O_APPEND: safe under concurrent writers (lesson 07)
            f.write(json.dumps(record) + "\n")
        self._json(201, record)


srv = http.server.ThreadingHTTPServer((BIND, PORT), Api)


def on_term(*_):
    print("SIGTERM: draining and exiting 0", flush=True)
    srv.shutdown_request = lambda *a: None
    srv.server_close()
    sys.exit(0)


def on_hup(*_):
    CONFIG["greeting"] = os.environ.get("GREETING", "hello")
    print("SIGHUP: config reloaded", flush=True)


signal.signal(signal.SIGTERM, on_term)
signal.signal(signal.SIGHUP, on_hup)
print(f"app listening on {BIND}:{PORT} as uid {os.getuid()}, state in {STATE_DIR}", flush=True)
srv.serve_forever()
