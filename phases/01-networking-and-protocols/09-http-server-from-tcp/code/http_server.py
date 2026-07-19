"""
Capstone — an HTTP/1.1 server on a raw TCP socket, no framework.

This is Lesson 05's socket lifecycle (socket/bind/listen/accept) plus Lesson 08's
HTTP anatomy, assembled by hand: accept a connection, read the request bytes,
parse the request line + headers, route on method+path, and write a response with
a correct Content-Length. It is self-terminating (server on a thread, a few client
requests, then exit 0).

Docs: phases/01-networking-and-protocols/09-http-server-from-tcp/docs/en.md
Spec: RFC 9112 (HTTP/1.1 message syntax), Python `socket` (SOCK_STREAM)

Run:
    python http_server.py
"""

import socket
import threading

HOST = "127.0.0.1"
PORT = 54_309  # an ephemeral, unprivileged port for the demo

# The whole "web app": a path -> body table. Everything else is HTTP plumbing.
ROUTES = {
    "/": "Welcome — this page came off a raw TCP socket, no framework.\n",
    "/hello": "Hello from an HTTP server you can read end to end.\n",
}


# --------------------------------------------------------------------------- #
# Parse: turn the request bytes into (method, path, version, headers).
# HTTP/1.1 is a text protocol. Lines end in CRLF (\r\n), and a *blank* line
# (\r\n\r\n) separates the headers from the body — RFC 9112 §2.1, §2.2.
# --------------------------------------------------------------------------- #
def parse_request(raw):
    # Everything before the first blank line is the "head"; the rest is the body.
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")

    # The very first line is the request line: METHOD SP PATH SP VERSION.
    method, path, version = lines[0].decode("ascii").split(" ", 2)

    # Each remaining line is "Name: value". Header names are case-insensitive.
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(b": ")
        headers[name.decode("ascii").lower()] = value.decode("ascii")

    return method, path, version, headers


# --------------------------------------------------------------------------- #
# Build: assemble a well-formed HTTP/1.1 response as bytes.
# The response is: status line, headers (one per CRLF line), a blank line, body.
# Content-Length MUST equal len(body) in bytes. Get it wrong and the client
# either hangs waiting for bytes that never come, or truncates the body.
# --------------------------------------------------------------------------- #
def build_response(status, reason, body_text, extra_headers=None):
    body = body_text.encode("utf-8")  # measure bytes, not characters
    header_lines = [
        "HTTP/1.1 {} {}".format(status, reason),
        "Content-Type: text/plain; charset=utf-8",
        "Content-Length: {}".format(len(body)),  # the header that prevents a hang
        "Connection: close",
    ]
    for name, value in (extra_headers or []):
        header_lines.append("{}: {}".format(name, value))

    # Join the headers with CRLF, then add the CRLF-CRLF that ends the header
    # block, then the raw body bytes.
    head = ("\r\n".join(header_lines) + "\r\n\r\n").encode("ascii")
    return head + body


def route(method, path):
    """Map a parsed request to a response — the whole decision tree."""
    if method != "GET":
        # We only implement GET. Anything else is 405, and RFC 9110 §15.5.6
        # requires an Allow header listing the methods we do support.
        return build_response(
            405, "Method Not Allowed",
            "{} is not allowed here; this server only speaks GET.\n".format(method),
            extra_headers=[("Allow", "GET")],
        )
    if path in ROUTES:
        return build_response(200, "OK", ROUTES[path])
    return build_response(404, "Not Found", "No resource at {}\n".format(path))


def read_request(conn):
    """Read from the socket until we have the full header block (\\r\\n\\r\\n)."""
    buffer = b""
    # TCP is a stream, not messages (Lesson 05): one recv() may return a partial
    # request, so we loop until the blank line that ends the headers arrives.
    while b"\r\n\r\n" not in buffer:
        chunk = conn.recv(1024)
        if not chunk:
            break  # peer closed the connection
        buffer += chunk
    return buffer


# --------------------------------------------------------------------------- #
# The accept loop — Lesson 05's four calls, now answering HTTP.
# --------------------------------------------------------------------------- #
def serve(ready, num_requests):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        # SO_REUSEADDR lets us re-bind the port immediately after a restart
        # instead of waiting out the kernel's TIME_WAIT window.
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(16)  # backlog: how many pending connections the kernel queues
        ready.set()        # signal the client that the listener is up

        # A real server loops forever (accept()); we serve a fixed number so the
        # demo terminates. Each iteration is one full request/response exchange.
        for _ in range(num_requests):
            conn, addr = server.accept()  # blocks until a client connects
            with conn:
                raw = read_request(conn)
                method, path, _version, _headers = parse_request(raw)
                conn.sendall(route(method, path))


# --------------------------------------------------------------------------- #
# A tiny raw client, so we can print the exact bytes on the wire both ways.
# --------------------------------------------------------------------------- #
def request(method, path):
    req = (
        "{} {} HTTP/1.1\r\n"
        "Host: {}:{}\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).format(method, path, HOST, PORT).encode("ascii")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((HOST, PORT))
        sock.sendall(req)
        response = b""
        while True:
            chunk = sock.recv(1024)
            if not chunk:
                break
            response += chunk

    print("--- REQUEST ({} {}) ".format(method, path) + "-" * 30)
    print(req.decode("ascii").rstrip("\r\n"))
    print("--- RESPONSE " + "-" * 42)
    print(response.decode("utf-8").rstrip("\r\n"))
    print()


def main():
    # method, path pairs covering 200 (twice), 404, and 405.
    exchanges = [
        ("GET", "/"),
        ("GET", "/hello"),
        ("GET", "/does-not-exist"),
        ("POST", "/hello"),
    ]

    ready = threading.Event()
    server_thread = threading.Thread(
        target=serve, args=(ready, len(exchanges)), daemon=True
    )
    server_thread.start()
    ready.wait(timeout=5)  # don't send requests until the socket is listening

    for method, path in exchanges:
        request(method, path)

    server_thread.join(timeout=5)
    print("[done] A web server is an accept loop + a parser + a response builder.")


if __name__ == "__main__":
    main()
