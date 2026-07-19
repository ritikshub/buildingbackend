"""
Transport Layer — TCP echo, the Build It implementation.

A self-contained demo of TCP (Transmission Control Protocol, RFC 9293): a
connection-oriented, reliable, ordered byte stream. The server runs on a
background thread; the client connects, sends one message, and reads the echo.
Both halves use only the standard-library `socket` module — the same four calls
every language exposes.

Docs: phases/01-networking-and-protocols/05-transport-layer-tcp-vs-udp/docs/en.md
Spec: RFC 9293 (TCP), Python `socket` (SOCK_STREAM)

Run:
    python tcp_echo.py
It starts a server, runs a client against it, prints the exchange, and exits 0.
"""

import socket
import threading

HOST = "127.0.0.1"
PORT = 54_321  # an ephemeral, unprivileged port for the demo


def serve(ready: threading.Event) -> None:
    """A one-connection TCP echo server: socket -> bind -> listen -> accept."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        # SOCK_STREAM = TCP. Let us re-bind the port immediately on restart.
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(1)          # backlog: how many pending connections to queue
        ready.set()               # tell the client the listener is up
        conn, addr = server.accept()   # blocks until the 3-way handshake completes
        with conn:
            print(f"[server] accepted a connection from {addr[0]}:{addr[1]}")
            # TCP is a *stream*, not messages: recv() returns whatever bytes have
            # arrived so far, which may be a partial or a merged message. For a
            # single small payload one recv() is enough; a real server loops.
            data = conn.recv(1024)
            print(f"[server] received {len(data)} bytes: {data!r}")
            conn.sendall(data)    # echo the exact bytes back
            print("[server] echoed the bytes back, closing the connection")


def client() -> None:
    """A TCP client: socket -> connect -> send -> recv -> close."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((HOST, PORT))   # performs the SYN / SYN-ACK / ACK handshake
        message = b"hello over a reliable stream"
        print(f"[client] sending {len(message)} bytes: {message!r}")
        sock.sendall(message)
        echo = sock.recv(1024)
        print(f"[client] got the echo back: {echo!r}")
        assert echo == message, "TCP guarantees the bytes come back intact and in order"
        print("[client] echo matched the original bytes exactly")


def main() -> None:
    ready = threading.Event()
    server_thread = threading.Thread(target=serve, args=(ready,), daemon=True)
    server_thread.start()
    ready.wait(timeout=5)   # don't connect until the listener is bound
    client()
    server_thread.join(timeout=5)
    print("[done] TCP delivered every byte, in order, with no loss.")


if __name__ == "__main__":
    main()
