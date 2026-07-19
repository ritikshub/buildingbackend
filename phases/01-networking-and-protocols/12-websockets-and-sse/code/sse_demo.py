"""
WebSockets & SSE — a tiny Server-Sent Events stream, server and client in one.

SSE (Server-Sent Events, the WHATWG HTML Living Standard) is a one-way
server->client stream over an ordinary HTTP response with Content-Type
text/event-stream. The server holds the connection open and writes events as
"data: ...\\n\\n". Here an in-process http.server thread streams a few ticks and
a urllib client reads N of them, then hangs up — no browser, no network needed.

Docs: phases/01-networking-and-protocols/12-websockets-and-sse/docs/en.md
Spec: WHATWG HTML — Server-sent events; media type text/event-stream

Run:
    python sse_demo.py
Starts a local SSE server, reads a few events, closes the stream, exits 0.
"""

import http.server
import threading
import time
import urllib.request
from typing import List

HOST = "127.0.0.1"
EVENTS_TO_SEND = 5   # the server offers this many before ending the response
EVENTS_TO_READ = 3   # the client stops after collecting this many


class SSEHandler(http.server.BaseHTTPRequestHandler):
    """Streams a fixed number of `data:` events as text/event-stream."""

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")  # the SSE contract
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            # `retry:` tells the browser how long (ms) to wait before it
            # auto-reconnects — a feature SSE gives you for free.
            self.wfile.write(b"retry: 2000\n\n")
            for i in range(1, EVENTS_TO_SEND + 1):
                # One event: an `id:` line plus a `data:` line, ended by a blank line.
                event = f"id: {i}\ndata: server tick #{i}\n\n"
                self.wfile.write(event.encode("utf-8"))
                self.wfile.flush()   # push it now, don't buffer the whole response
                time.sleep(0.05)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the client read enough and hung up — normal, expected for SSE

    def log_message(self, *args: object) -> None:
        pass  # silence the default per-request logging to keep output clean


def read_events(url: str, want: int) -> List[str]:
    """A minimal SSE client: read `data:` payloads until we have `want` of them."""
    collected: List[str] = []
    data_lines: List[str] = []
    with urllib.request.urlopen(url, timeout=5) as resp:
        print(f"[client] connected; Content-Type: {resp.headers.get('Content-Type')}")
        for raw in resp:                       # HTTPResponse yields the stream line by line
            line = raw.decode("utf-8").rstrip("\n")
            if line == "":                     # a blank line terminates one event
                if data_lines:
                    event = "\n".join(data_lines)
                    collected.append(event)
                    print(f"[client] event {len(collected)}: {event!r}")
                    data_lines = []
                    if len(collected) >= want:
                        break                  # closing the stream ends the request
                continue
            if line.startswith("data:"):
                data_lines.append(line[len("data:"):].lstrip())
            # `id:` and `retry:` lines are metadata; a real client would track them.
    return collected


def main() -> None:
    # Bind to port 0 so the OS hands us a free ephemeral port for the demo.
    server = http.server.ThreadingHTTPServer((HOST, 0), SSEHandler)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://{host}:{port}/events"
    print(f"[server] streaming SSE at {url}")
    events = read_events(url, want=EVENTS_TO_READ)
    assert len(events) == EVENTS_TO_READ, "client should have read exactly the events it wanted"

    server.shutdown()          # stop accepting; the daemon thread can exit
    thread.join(timeout=5)
    print(f"[done] read {len(events)} SSE events over one open HTTP response, then closed it.")


if __name__ == "__main__":
    main()
