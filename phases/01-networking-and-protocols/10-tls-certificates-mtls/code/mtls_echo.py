"""
mTLS echo — mutual TLS, where BOTH sides prove their identity.

Extends tls_echo.py: in plain TLS only the server presents a certificate; in
mTLS (mutual TLS, RFC 8446 section 4.4.2) the CLIENT presents one too, so each
end authenticates the other. Both sides here trust the same self-signed cert as
their CA (Certificate Authority) root, so each can verify the other's leaf.

Docs: phases/01-networking-and-protocols/10-tls-certificates-mtls/docs/en.md
Spec: RFC 8446 (TLS 1.3), section 4.4.2 (client certificate authentication).

Run:
    python3 mtls_echo.py
It runs a mutually-authenticated exchange on localhost, prints it, and exits 0.
"""

import os
import socket
import ssl
import subprocess
import threading

HOST = "127.0.0.1"
PORT = 54_444  # a second demo port so it never clashes with tls_echo.py

HERE = os.path.dirname(os.path.abspath(__file__))
CERT = os.path.join(HERE, "cert.pem")  # the demo leaf certificate...
KEY = os.path.join(HERE, "key.pem")   # ...and its private key
# The cert is self-signed (issuer == subject), so it is simultaneously a leaf
# AND its own trust anchor. We hand it to each side as the CA to verify against.
CA = CERT


def ensure_cert() -> None:
    """Generate the throwaway self-signed pair if it isn't on disk yet.

    Shared with tls_echo.py — whichever you run first creates the pair. A
    private key is never committed to version control, not even a demo one
    that protects nothing; both files are in .gitignore.
    """
    if os.path.exists(CERT) and os.path.exists(KEY):
        return
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
         "-keyout", KEY, "-out", CERT, "-days", "3650",
         "-subj", "/CN=localhost"],
        check=True, capture_output=True,
    )
    os.chmod(KEY, 0o600)  # a private key is readable by its owner and nobody else
    print(f"generated a throwaway self-signed pair (CN=localhost) in {HERE}\n")


def subject_of(peer_cert: dict) -> str:
    """Flatten getpeercert()'s subject tuple into 'commonName=localhost'."""
    if not peer_cert:
        return "<no certificate>"
    return ", ".join(
        f"{name}={value}" for rdn in peer_cert["subject"] for name, value in rdn
    )


def serve(ready: threading.Event) -> None:
    """A TLS server that REQUIRES the client to present a valid certificate."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=CERT, keyfile=KEY)  # the server's identity
    # CERT_REQUIRED plus a trusted CA is what turns TLS into mTLS: the handshake
    # now fails unless the client sends a certificate signed by a CA we trust.
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_verify_locations(cafile=CA)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp:
        tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tcp.bind((HOST, PORT))
        tcp.listen(1)
        ready.set()
        raw_conn, _ = tcp.accept()
        with context.wrap_socket(raw_conn, server_side=True) as tls_conn:
            # If we reach this line, the client's certificate already verified.
            client_id = subject_of(tls_conn.getpeercert())
            print(f"[server] verified the client's certificate: {client_id}")
            data = tls_conn.recv(1024)
            tls_conn.sendall(data)
            print("[server] echoed the request back to the authenticated client")


def client() -> None:
    """A TLS client that presents its own certificate AND verifies the server."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_cert_chain(certfile=CERT, keyfile=KEY)  # the client's identity
    context.load_verify_locations(cafile=CA)  # trust the demo CA...
    context.verify_mode = ssl.CERT_REQUIRED   # ...and require a valid server cert
    # We still skip HOSTNAME checking because the demo cert has no Subject
    # Alternative Name for 127.0.0.1. The certificate SIGNATURE is fully
    # verified; only the name match is relaxed. Real deployments keep
    # check_hostname=True and issue certs that list the expected name.
    context.check_hostname = False

    with socket.create_connection((HOST, PORT)) as raw:
        with context.wrap_socket(raw, server_hostname=HOST) as tls:
            server_id = subject_of(tls.getpeercert())  # populated: we verified it
            print(f"[client] verified the server's certificate: {server_id}")
            print(f"[client] channel: {tls.version()} / {tls.cipher()[0]}")
            message = b"authenticated request from a known client"
            tls.sendall(message)
            echo = tls.recv(1024)
            assert echo == message, "the round trip must return the same bytes"
            print("[client] both sides authenticated; echo verified")


def main() -> None:
    ensure_cert()
    ready = threading.Event()
    server_thread = threading.Thread(target=serve, args=(ready,), daemon=True)
    server_thread.start()
    ready.wait(timeout=5)
    client()
    server_thread.join(timeout=5)
    print("[done] mTLS: each side proved who it was before any data moved.")


if __name__ == "__main__":
    main()
