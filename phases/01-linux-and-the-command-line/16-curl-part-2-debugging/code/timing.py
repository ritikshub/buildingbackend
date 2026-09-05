"""
curl, Part 2 — the timing breakdown behind `curl -w`, rebuilt from socket
and ssl, plus retry-with-backoff and a --resolve, so that "the request is
slow" becomes "the DNS/connect/TLS/server/transfer step is slow".

One HTTP request is five waits in a row: resolve the name, complete the TCP
handshake, complete the TLS handshake, wait for the server's first byte,
receive the rest. curl's -w variables (time_namelookup, time_connect,
time_appconnect, time_starttransfer, time_total) are stopwatch readings at
those boundaries, cumulative from the start. This script takes the same
readings with a raw socket and prints both the cumulative and the per-step
numbers, against the lesson 15 echo server (plain HTTP, including its /slow
route) and against a public HTTPS host. It then does what --resolve does
(connect to an address you choose while keeping the Host header and SNI),
and what --retry does (retry transient failures with growing delays), with
the exit-code discipline a script needs. Self-terminating.

Docs: phases/01-linux-and-the-command-line/16-curl-part-2-debugging/docs/en.md
Spec: RFC 9112 (HTTP/1.1), RFC 8446 (TLS 1.3 handshake), RFC 6066 (SNI);
      curl's -w variables are documented in curl(1) under --write-out

Run:
    python ../15-curl-part-1-requests/code/echo_server.py &     # for the local parts
    python timing.py
"""

import socket
import ssl
import sys
import time
from urllib.parse import urlparse


def timed_request(url, resolve_to=None, timeout=10.0, path_override=None):
    """Return the cumulative stopwatch readings curl -w prints, plus the status line."""
    u = urlparse(url)
    host = u.hostname
    port = u.port or (443 if u.scheme == "https" else 80)
    path = path_override or (u.path or "/") + (("?" + u.query) if u.query else "")
    t = {}
    t0 = time.perf_counter()

    addr = resolve_to or socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
    t["namelookup"] = time.perf_counter() - t0                   # DNS done (0 when --resolve supplied the address)

    sock = socket.create_connection((addr, port), timeout=timeout)
    t["connect"] = time.perf_counter() - t0                      # TCP handshake done (SYN, SYN-ACK, ACK)

    if u.scheme == "https":
        ctx = ssl.create_default_context()
        sock = ctx.wrap_socket(sock, server_hostname=host)       # SNI = the hostname, whatever address we dialled
        t["appconnect"] = time.perf_counter() - t0               # TLS handshake done
        tls = f"{sock.version()} {sock.cipher()[0]}"
    else:
        t["appconnect"] = t["connect"]
        tls = "none"

    req = f"GET {path} HTTP/1.1\r\nHost: {u.netloc}\r\nUser-Agent: timing.py\r\nAccept: */*\r\nConnection: close\r\n\r\n"
    sock.sendall(req.encode())
    t["pretransfer"] = time.perf_counter() - t0                  # request written

    first = sock.recv(1)
    t["starttransfer"] = time.perf_counter() - t0                # first byte of the response: server think time ends here

    data = first
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            break
        data += chunk
    t["total"] = time.perf_counter() - t0                        # last byte received
    sock.close()
    status = data.split(b"\r\n", 1)[0].decode(errors="replace")
    return t, status, len(data), addr, tls


def show(label, t, status, size, addr, tls):
    ms = lambda k: f"{t[k] * 1000:8.1f}"
    steps = [("DNS", t["namelookup"]), ("TCP", t["connect"] - t["namelookup"]), ("TLS", t["appconnect"] - t["connect"]),
             ("server", t["starttransfer"] - t["pretransfer"]), ("transfer", t["total"] - t["starttransfer"])]
    print(f"\n   {label}")
    print(f"   {status}   {size:,} bytes   via {addr}   tls {tls}")
    print(f"   cumulative (curl -w):  namelookup {ms('namelookup')}  connect {ms('connect')}  appconnect {ms('appconnect')}  starttransfer {ms('starttransfer')}  total {ms('total')} ms")
    print("   per step:              " + "  ".join(f"{n} {v * 1000:.1f}" for n, v in steps) + " ms")
    biggest = max(steps, key=lambda s: s[1])
    print(f"   the time went to: {biggest[0]} ({biggest[1] / t['total'] * 100:.0f}% of the total)")


def with_retry(fn, attempts=4, base_delay=0.2, retry_on=(502, 503, 504)):
    """--retry N --retry-delay: retry connection errors and 5xx, with exponential backoff."""
    for i in range(1, attempts + 1):
        try:
            t, status, size, addr, tls = fn()
            code = int(status.split()[1])
            if code in retry_on and i < attempts:
                delay = base_delay * 2 ** (i - 1)
                print(f"   attempt {i}: {status}; retrying in {delay:.1f}s")
                time.sleep(delay); continue
            print(f"   attempt {i}: {status}" + ("" if code < 400 else "  -> giving up: exit 22 (curl -f)"))
            return 0 if code < 400 else 22
        except (ConnectionRefusedError, socket.timeout, OSError) as e:
            if i < attempts:
                delay = base_delay * 2 ** (i - 1)
                print(f"   attempt {i}: {type(e).__name__}; retrying in {delay:.1f}s")
                time.sleep(delay); continue
            print(f"   attempt {i}: {type(e).__name__}  -> giving up: exit 7 (could not connect)")
            return 7


if __name__ == "__main__":
    echo = "http://127.0.0.1:8089"
    print("=== 1 · where the time goes: five stopwatch readings, one request")
    try:
        show("GET /json on the local echo server", *timed_request(f"{echo}/json"))
        show("GET /slow?ms=400: the server thinks for 400 ms before its first byte", *timed_request(f"{echo}/slow?ms=400"))
        show("GET /big?kb=4096: 4 MiB of body, so the transfer step dominates", *timed_request(f"{echo}/big?kb=4096"))
    except OSError as e:
        print(f"   (echo server not running on 8089: {e}; start lesson 15's echo_server.py for the local parts)")

    print("\n=== 2 · a real HTTPS request: DNS, TCP and TLS each cost a round trip or more")
    try:
        show("GET https://deb.debian.org/", *timed_request("https://deb.debian.org/"))
    except OSError as e:
        print(f"   (no network: {e})")

    print("\n=== 3 · --resolve: dial an address you chose, keep the Host header and the SNI")
    try:
        t, status, size, addr, tls = timed_request("https://deb.debian.org/", resolve_to=socket.gethostbyname("deb.debian.org"))
        print(f"   dialled {addr} directly (namelookup {t['namelookup'] * 1000:.1f} ms: no DNS at all), SNI/Host still deb.debian.org -> {status}, {tls}")
        print("   this is how you test one backend, a canary, or a new server before DNS points at it")
    except OSError as e:
        print(f"   (no network: {e})")

    print("\n=== 4 · --retry: transient failures, exponential delays, an honest exit code")
    print("   against a port nobody listens on (connection refused every time):")
    code = with_retry(lambda: timed_request("http://127.0.0.1:1/", timeout=1))
    print(f"   exit {code}")
    try:
        print("   against /status/503 (a server that says 'later'):")
        code = with_retry(lambda: timed_request(f"{echo}/status/503"))
        print(f"   exit {code}")
        print("   against /json (works first time):")
        code = with_retry(lambda: timed_request(f"{echo}/json"))
        print(f"   exit {code}")
    except OSError:
        pass
    print("\n   curl: --retry 3 --retry-delay 1 retries connect errors and 5xx (with --retry-all-errors, anything);")
    print("   -f turns a final 4xx/5xx into exit 22; --max-time bounds the whole thing. Without all three a script can hang forever and report success.")
