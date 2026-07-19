"""
TLS echo — the Build It implementation for "TLS, Certificates & mTLS".

A self-contained demo of TLS (Transport Layer Security, RFC 8446 for TLS 1.3):
a server on a background thread wraps a TCP socket with the stdlib `ssl` module,
loads its self-signed demo certificate, and a client completes the handshake,
sends one line, and reads the encrypted echo — printing the negotiated version,
the cipher suite, and the certificate the server presented.

Docs: phases/01-networking-and-protocols/10-tls-certificates-mtls/docs/en.md
Spec: RFC 8446 (TLS 1.3); Python standard-library `ssl` module.

Run:
    python3 tls_echo.py
It starts a TLS server, runs a client against it, prints the exchange, exits 0.
"""

import os
import socket
import ssl
import subprocess
import threading

HOST = "127.0.0.1"
PORT = 54_443  # an ephemeral, unprivileged port for the demo

# Load the certificate and private key by paths relative to THIS file, so the
# script runs from any working directory. cert.pem/key.pem are a throwaway
# self-signed pair (Common Name = localhost) generated on first run.
HERE = os.path.dirname(os.path.abspath(__file__))
CERT = os.path.join(HERE, "cert.pem")
KEY = os.path.join(HERE, "key.pem")


def ensure_cert() -> None:
    """Generate the throwaway self-signed pair if it isn't on disk yet.

    A private key is never committed to version control — not even a demo one
    that protects nothing. Generating it on first run is the habit worth
    building; see phases/07-auth-and-security/13-secrets-management-and-rotation.
    Both files land in .gitignore, so a fresh clone regenerates its own pair.
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


def cert_subject(pem_path: str) -> str:
    """Decode a PEM certificate's subject using only the stdlib `ssl` module.

    ssl has no public "parse this file" call, but load_verify_locations() +
    get_ca_certs() will parse any PEM cert we hand it as if it were a trusted
    CA (Certificate Authority) root — which is all we need to read its fields.
    """
    probe = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    probe.load_verify_locations(pem_path)
    parsed = probe.get_ca_certs()
    if not parsed:
        return "<none>"
    # 'subject' is a tuple of relative distinguished names, e.g.
    # ((('commonName', 'localhost'),),). Flatten it to "commonName=localhost".
    pairs = [f"{name}={value}" for rdn in parsed[0]["subject"] for name, value in rdn]
    return ", ".join(pairs)


def serve(ready: threading.Event) -> None:
    """A one-connection TLS echo server: TCP accept -> TLS wrap -> echo."""
    # PROTOCOL_TLS_SERVER auto-negotiates the highest TLS version both sides
    # support. load_cert_chain gives the server its identity: the public
    # certificate it presents and the private key that proves it owns it.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=CERT, keyfile=KEY)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp:
        tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tcp.bind((HOST, PORT))
        tcp.listen(1)
        ready.set()  # tell the client the listener is up
        raw_conn, addr = tcp.accept()  # plain TCP connection first
        # wrap_socket runs the TLS handshake: it sends ServerHello + the
        # certificate, and derives the shared symmetric key with the client.
        with context.wrap_socket(raw_conn, server_side=True) as tls_conn:
            print(f"[server] TLS handshake done with {addr[0]}:{addr[1]}")
            data = tls_conn.recv(1024)  # decrypted for us by the ssl layer
            print(f"[server] received {len(data)} bytes (decrypted): {data!r}")
            tls_conn.sendall(data)  # re-encrypted on the way out
            print("[server] echoed the bytes back over the encrypted channel")


def client() -> None:
    """A TLS client: connect -> handshake -> send -> recv, then inspect."""
    # PROTOCOL_TLS_CLIENT defaults to verifying the server's certificate against
    # the system trust store AND checking the hostname. Our cert is SELF-SIGNED
    # (signed by no real CA) and issued for "localhost", so verification would
    # fail. We disable it *only because this is a local demo*.
    #
    # WARNING: CERT_NONE means "trust any certificate" — it defeats TLS
    # authentication and exposes you to man-in-the-middle attacks. Real clients
    # MUST keep check_hostname=True and verify_mode=CERT_REQUIRED (the defaults)
    # so a forged certificate is rejected. Never ship the two lines below.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False  # must clear this BEFORE setting CERT_NONE
    context.verify_mode = ssl.CERT_NONE

    with socket.create_connection((HOST, PORT)) as raw:
        with context.wrap_socket(raw, server_hostname=HOST) as tls:
            message = b"hello over an encrypted channel"
            print(f"[client] sending {len(message)} bytes: {message!r}")
            tls.sendall(message)
            echo = tls.recv(1024)
            print(f"[client] got the echo back: {echo!r}")
            assert echo == message, "the plaintext must survive the round trip"

            # What did we negotiate? version() and cipher() report the outcome
            # of the handshake — the protocol version and the symmetric cipher
            # suite that now protects every byte.
            print(f"[client] negotiated TLS version : {tls.version()}")
            cipher_name, cipher_proto, secret_bits = tls.cipher()
            print(f"[client] negotiated cipher suite: {cipher_name} ({secret_bits}-bit)")

            # The server presented a certificate during the handshake. Even with
            # verification off we still RECEIVE it — grab its raw DER bytes and
            # confirm they are exactly cert.pem, then print its subject.
            wire_der = tls.getpeercert(binary_form=True)
            with open(CERT) as fh:
                disk_der = ssl.PEM_cert_to_DER_cert(fh.read())
            same = "matches cert.pem" if wire_der == disk_der else "DIFFERS from cert.pem"
            print(f"[client] server presented a {len(wire_der)}-byte certificate ({same})")
            print(f"[client] certificate subject    : {cert_subject(CERT)}")


def main() -> None:
    ensure_cert()
    ready = threading.Event()
    server_thread = threading.Thread(target=serve, args=(ready,), daemon=True)
    server_thread.start()
    ready.wait(timeout=5)  # don't connect until the listener is bound
    client()
    server_thread.join(timeout=5)
    print("[done] TLS gave us confidentiality, integrity, and a server identity.")


if __name__ == "__main__":
    main()
