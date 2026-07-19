"""
Timeouts — bounding a socket so a slow or silent peer can't hang you forever.

Starts a deliberately-slow local server, then runs a client with settimeout():
a too-short read timeout raises socket.timeout (caught and reported) instead of
blocking forever, while a generous timeout lets the same reply through. Also
contrasts a refused connection (instant) with a timeout (waited-then-gave-up).
Stdlib only (socket, threading, time); localhost only; exits 0.

Docs: phases/01-networking-and-protocols/14-keep-alive-pooling-timeouts/docs/en.md
Spec: RFC 9112 §9.5 (idle/failed persistent connections must be recovered from)

Run:
    python3 timeouts.py
It starts a server, demonstrates each timeout case, prints them, and exits 0.
"""

from __future__ import annotations

import socket
import threading
import time

HOST = "127.0.0.1"
SERVER_DELAY_S = 0.60   # the server sits silent this long before replying


class SlowServer:
    """A TCP server that accepts a connection, then deliberately stalls for
    SERVER_DELAY_S before replying — a stand-in for an overloaded or wedged
    peer that has gone silent mid-request."""

    def __init__(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((HOST, 0))            # port 0 => OS picks a free port
        self.port = self._sock.getsockname()[1]
        self._sock.listen(8)

    def serve_forever(self) -> None:
        while True:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            threading.Thread(
                target=self._handle, args=(conn,), daemon=True
            ).start()

    def _handle(self, conn: socket.socket) -> None:
        with conn:
            conn.recv(1024)                   # read the request
            time.sleep(SERVER_DELAY_S)        # ...then go silent on purpose
            try:
                conn.sendall(b"finally, a reply")
            except OSError:
                pass                          # client may have already given up

    def close(self) -> None:
        self._sock.close()


def read_with_timeout(host: str, port: int, timeout_s: float) -> None:
    """Send a request, then read with a bounded timeout. A read that outlasts
    the timeout raises socket.timeout instead of hanging forever."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        # settimeout() bounds every blocking call on this socket: connect(),
        # recv(), and send() alike. Here the connect succeeds instantly; it is
        # the recv() that has to wait on the deliberately-slow server.
        sock.settimeout(timeout_s)
        sock.connect((host, port))
        sock.sendall(b"are you there?")
        try:
            reply = sock.recv(1024)
            print(f"[read timeout={timeout_s:.2f}s] got a reply: {reply!r}")
        except socket.timeout:
            # Without this timeout, recv() would block for the full server delay
            # (or forever, if the peer never replied at all).
            print(f"[read timeout={timeout_s:.2f}s] socket.timeout raised — the "
                  f"peer went silent; we gave up instead of hanging")


def refused_is_not_a_timeout(host: str) -> None:
    """A closed port refuses the connection instantly. That is a *different*
    failure from a timeout: refused = an active 'no', timeout = silence."""
    # Grab a free port, then close it so nothing is listening there.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind((host, 0))
    dead_port = probe.getsockname()[1]
    probe.close()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)                  # guard so we never actually hang
        start = time.perf_counter()
        try:
            sock.connect((host, dead_port))
            print("[connect] unexpectedly connected")
        except ConnectionRefusedError:
            elapsed_ms = (time.perf_counter() - start) * 1000
            print(f"[connect] ConnectionRefusedError after {elapsed_ms:.1f} ms — "
                  f"refused is instant and explicit, not a timeout")
        except socket.timeout:
            print("[connect] socket.timeout — no route/response to the port")


def main() -> None:
    server = SlowServer()
    threading.Thread(target=server.serve_forever, daemon=True).start()

    # 1) Read timeout shorter than the server delay -> socket.timeout fires.
    read_with_timeout(HOST, server.port, timeout_s=0.20)
    # 2) Read timeout longer than the server delay -> the reply gets through.
    read_with_timeout(HOST, server.port, timeout_s=1.50)
    # 3) Connection refused is a distinct, instant failure (not a timeout).
    refused_is_not_a_timeout(HOST)

    server.close()
    print("[done] a bounded socket fails fast and recoverably; an unbounded one "
          "hangs on the first silent peer.")


if __name__ == "__main__":
    main()
