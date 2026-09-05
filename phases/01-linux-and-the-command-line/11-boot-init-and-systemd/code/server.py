"""
The service that app.service runs: a tiny HTTP server that behaves the way a
supervised process should. It reads its port from the environment (set by
EnvironmentFile=), logs to stdout unbuffered (so the journal gets every line
as it happens), drains and exits 0 on SIGTERM (so `systemctl stop` is clean),
and reloads on SIGHUP (so ExecReload= means something).

Docs: phases/01-linux-and-the-command-line/11-boot-init-and-systemd/docs/en.md
Run:  PORT=8080 python3 server.py        (or install it: see app.service)
"""

import http.server
import os
import signal
import sys

port = int(os.environ.get("PORT", "8080"))


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = f"hello from pid {os.getpid()} as uid {os.getuid()}\n".encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print("request:", fmt % args, flush=True)


srv = http.server.HTTPServer(("127.0.0.1", port), Handler)


def on_term(*_):
    print("SIGTERM: draining, closing the socket, exiting 0", flush=True)
    srv.server_close()
    sys.exit(0)


def on_hup(*_):
    print("SIGHUP: reloading config", flush=True)


signal.signal(signal.SIGTERM, on_term)
signal.signal(signal.SIGHUP, on_hup)
print(f"listening on {port} as uid {os.getuid()}, cwd {os.getcwd()}, HOME={os.environ.get('HOME')}", flush=True)
srv.serve_forever()
