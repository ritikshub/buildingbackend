"""
HTTP in Depth — a raw HTTP/1.1 client built by hand.

Builds an HTTP/1.1 GET request as bytes, sends it over a plain socket to a local
http.server running on a background thread, then parses the status line, headers,
and body from the raw byte stream. Sends TWO requests over the SAME socket to
demonstrate keep-alive (a persistent connection), avoiding one TCP handshake.

Docs: phases/01-networking-and-protocols/08-http-in-depth/docs/en.md
Spec: RFC 9110 (HTTP Semantics), RFC 9112 (HTTP/1.1 message syntax)

Run:
    python3 http_client.py
It starts a server, runs the client against it, prints the exchange, and exits 0.
"""

import http.server
import json
import socket
import threading

HOST = "127.0.0.1"
PORT = 54_808  # an ephemeral, unprivileged port for the demo
CRLF = "\r\n"   # HTTP lines end in carriage-return + line-feed (RFC 9112 §2.1)


class Handler(http.server.BaseHTTPRequestHandler):
    """A minimal HTTP/1.1 server. Setting protocol_version to HTTP/1.1 turns on
    persistent connections: the socket stays open for more requests as long as
    every response carries a Content-Length and no one asks to close."""

    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        body = json.dumps({"path": self.path, "ok": True}).encode("utf-8")
        self.send_response(200)                          # status line + Date/Server
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))  # frames the body
        self.end_headers()                               # the blank line
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass  # keep the demo output clean


def build_get_request(path: str, host: str, keep_alive: bool) -> bytes:
    """Assemble a raw HTTP/1.1 GET request: request line, headers, blank line."""
    connection = "keep-alive" if keep_alive else "close"
    lines = [
        f"GET {path} HTTP/1.1",              # request line: METHOD target VERSION
        f"Host: {host}",                     # mandatory in HTTP/1.1
        "Accept: application/json",          # what representations we'll take
        "User-Agent: scratch-http/1.0",      # who is asking
        f"Connection: {connection}",         # keep-alive == reuse this socket
    ]
    # Headers end with a blank line; a GET has no body, so nothing follows it.
    return (CRLF.join(lines) + CRLF + CRLF).encode("ascii")


def read_response(sock: socket.socket, buffer: bytes):
    """Parse exactly one HTTP response from the byte stream.

    Returns (status_line, headers, body, leftover). `leftover` is any bytes read
    past this response's body — they belong to the NEXT response and are fed back
    in on the next call. This is why we must honor Content-Length: on a persistent
    connection there is no close to mark the end, only the declared length.
    """
    while b"\r\n\r\n" not in buffer:                 # read until end of headers
        chunk = sock.recv(4096)
        if not chunk:
            break
        buffer += chunk

    head, _, buffer = buffer.partition(b"\r\n\r\n")
    raw_lines = head.split(b"\r\n")
    status_line = raw_lines[0].decode("ascii")

    headers = {}
    for line in raw_lines[1:]:
        key, _, value = line.partition(b":")
        headers[key.decode("ascii").strip().lower()] = value.decode("ascii").strip()

    length = int(headers.get("content-length", "0"))
    while len(buffer) < length:                      # read exactly the body bytes
        chunk = sock.recv(4096)
        if not chunk:
            break
        buffer += chunk

    body = buffer[:length]
    leftover = buffer[length:]
    return status_line, headers, body, leftover


def show(label: str, status_line: str, headers: dict, body: bytes) -> None:
    print(f"[client] {label}")
    print(f"  status line ......... {status_line}")
    print(f"  Content-Type ........ {headers.get('content-type')}")
    print(f"  Content-Length ...... {headers.get('content-length')}")
    print(f"  Connection .......... {headers.get('connection', '(unset -> keep-alive)')}")
    print(f"  body ................ {body.decode('utf-8')}")


def main() -> None:
    server = http.server.ThreadingHTTPServer((HOST, PORT), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # ONE TCP connection, TWO requests — that is keep-alive in action.
        with socket.create_connection((HOST, PORT)) as sock:
            print(f"[client] opened one TCP connection to {HOST}:{PORT}\n")

            request_one = build_get_request("/first", f"{HOST}:{PORT}", keep_alive=True)
            print("[client] request 1 (raw bytes over the socket):")
            print(request_one.decode("ascii").replace("\r\n", "\\r\\n\n    ").rstrip())
            sock.sendall(request_one)
            status, headers, body, buffer = read_response(sock, b"")
            show("response 1 (connection kept open):", status, headers, body)

            print()
            # Reusing the SAME socket: no second TCP three-way handshake here.
            request_two = build_get_request("/second", f"{HOST}:{PORT}", keep_alive=False)
            print("[client] request 2 sent on the SAME socket (Connection: close)")
            sock.sendall(request_two)
            status, headers, body, buffer = read_response(sock, buffer)
            show("response 2 (server will now close):", status, headers, body)

        print("\n[done] Two HTTP requests, one TCP connection — one handshake saved.")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
