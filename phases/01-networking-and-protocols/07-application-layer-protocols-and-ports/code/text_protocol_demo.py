"""
Application Layer — a line-based text protocol, SMTP-style.

Text protocols (HTTP, SMTP) are human-readable: the client sends a verb line,
the server replies with a numeric status code and text, one line at a time. This
starts a tiny in-process TCP server speaking a mock verb protocol (GREET / ECHO
<text> / QUIT) and a client that runs the dialogue, printing every request and
response line so the conversation is visible on the wire.

Docs: phases/01-networking-and-protocols/07-application-layer-protocols-and-ports/docs/en.md
Spec: RFC 5321 (SMTP) as the model for verb + 3-digit-status line protocols

Run:
    python text_protocol_demo.py
Starts a server, runs the client dialogue, prints each line, and exits 0.
"""

import socket
import threading

HOST = "127.0.0.1"
PORT = 49_525
CRLF = "\r\n"   # line-based text protocols end each line with carriage-return + newline


def serve(ready: threading.Event) -> None:
    """A one-connection server speaking a mock, SMTP-style verb protocol."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(1)
        ready.set()
        conn, _ = server.accept()
        with conn, conn.makefile("rw", newline="") as stream:
            # Like SMTP, the server speaks first with a greeting banner.
            stream.write(f"220 mock-service ready{CRLF}")
            stream.flush()
            for raw in stream:                 # iterate the stream line by line
                line = raw.rstrip("\r\n")
                verb, _, rest = line.partition(" ")
                verb = verb.upper()            # verbs are case-insensitive, like SMTP
                if verb == "GREET":
                    stream.write(f"250 hello, glad you dropped by{CRLF}")
                elif verb == "ECHO":
                    stream.write(f"250 {rest}{CRLF}")
                elif verb == "QUIT":
                    stream.write(f"221 bye{CRLF}")
                    stream.flush()
                    break                      # a stateful close: server ends the session
                else:
                    stream.write(f"500 unknown command: {verb}{CRLF}")
                stream.flush()


def client() -> None:
    """Drive the dialogue: send each verb, read and print the status reply."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((HOST, PORT))
        with sock.makefile("rw", newline="") as stream:
            banner = stream.readline().rstrip("\r\n")
            print(f"S: {banner}")   # the server greeted us first

            for command in ("GREET", "ECHO application-layer speaks in lines", "QUIT"):
                print(f"C: {command}")
                stream.write(command + CRLF)
                stream.flush()
                reply = stream.readline().rstrip("\r\n")
                print(f"S: {reply}")
                code = reply.split(" ", 1)[0]
                # 2xx codes mean success in SMTP-style protocols; 5xx mean error.
                assert code.startswith("2"), f"expected a 2xx success code, got {code!r}"


def main() -> None:
    ready = threading.Event()
    server_thread = threading.Thread(target=serve, args=(ready,), daemon=True)
    server_thread.start()
    ready.wait(timeout=5)
    client()
    server_thread.join(timeout=5)
    print("[done] A text protocol is just agreed-upon lines: verb in, status line out.")


if __name__ == "__main__":
    main()
