"""
Transport Layer — UDP echo, the Build It implementation.

A self-contained demo of UDP (User Datagram Protocol, RFC 768): connectionless,
unreliable, message-oriented datagrams. There is no handshake, no connection,
and no ordering or delivery guarantee — you send a datagram and hope. Compare
this side by side with tcp_echo.py: no listen(), no accept(), no connect(); just
sendto()/recvfrom() on a single socket per side.

Docs: phases/01-networking-and-protocols/05-transport-layer-tcp-vs-udp/docs/en.md
Spec: RFC 768 (UDP), Python `socket` (SOCK_DGRAM)

Run:
    python udp_echo.py
It starts a server, runs a client against it, prints the exchange, and exits 0.
"""

import socket
import threading

HOST = "127.0.0.1"
PORT = 54_322


def serve(ready: threading.Event) -> None:
    """A one-datagram UDP echo server: socket -> bind -> recvfrom -> sendto."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
        # SOCK_DGRAM = UDP. No listen(), no accept() — a datagram socket is
        # never "connected"; it just receives whatever arrives on the port.
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        ready.set()
        # recvfrom() returns the payload AND the sender's address, because there
        # is no persistent connection telling us who is on the other end.
        data, sender = server.recvfrom(1024)
        print(f"[server] received {len(data)} bytes from "
              f"{sender[0]}:{sender[1]}: {data!r}")
        server.sendto(data, sender)   # echo it straight back to that address
        print("[server] echoed the datagram back")


def client() -> None:
    """A UDP client: socket -> sendto -> recvfrom. No connect, no handshake."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(2.0)   # UDP can silently lose packets — never block forever
        message = b"hello over a fire-and-forget datagram"
        print(f"[client] sending {len(message)} bytes: {message!r}")
        sock.sendto(message, (HOST, PORT))
        try:
            echo, _ = sock.recvfrom(1024)
            print(f"[client] got the echo back: {echo!r}")
            print("[client] this time it arrived — but UDP made no promise it would")
        except socket.timeout:
            # This branch is what makes UDP different: loss is normal, not an error.
            print("[client] no reply within the timeout — a lost datagram is normal for UDP")


def main() -> None:
    ready = threading.Event()
    server_thread = threading.Thread(target=serve, args=(ready,), daemon=True)
    server_thread.start()
    ready.wait(timeout=5)
    client()
    server_thread.join(timeout=5)
    print("[done] UDP sent the datagram with no setup and no delivery guarantee.")


if __name__ == "__main__":
    main()
