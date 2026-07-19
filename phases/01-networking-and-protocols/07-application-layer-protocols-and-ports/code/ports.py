"""
Application Layer — a well-known-ports registry plus a localhost port scanner.

A port number maps an arriving packet to a service. This file holds a small dict
of well-known ports (0-1023, assigned by IANA), a lookup() helper, and a scanner
that starts a couple of throwaway TCP listeners on localhost, then probes a port
range with short-timeout connect() calls to report which are open and name them.

Docs: phases/01-networking-and-protocols/07-application-layer-protocols-and-ports/docs/en.md
Spec: IANA Service Name and Port Number Registry; RFC 6335 (port ranges)

Run:
    python ports.py
Starts local listeners, scans a range on 127.0.0.1, prints results, and exits 0.
"""

import socket
import threading

HOST = "127.0.0.1"

# A small slice of the IANA well-known-ports registry (0-1023). In the real
# registry every entry names the transport too; the common ones use TCP, UDP,
# or both. Keyed by port number for O(1) lookup.
WELL_KNOWN_PORTS = {
    20: ("FTP-data", "tcp", "File Transfer Protocol — bulk data channel"),
    21: ("FTP", "tcp", "File Transfer Protocol — control/command channel"),
    22: ("SSH", "tcp", "Secure Shell — encrypted remote login and tunnels"),
    23: ("Telnet", "tcp", "Remote login in cleartext (obsolete, insecure)"),
    25: ("SMTP", "tcp", "Simple Mail Transfer Protocol — server-to-server mail"),
    53: ("DNS", "udp/tcp", "Domain Name System — name-to-address lookups"),
    67: ("DHCP-server", "udp", "Dynamic Host Configuration Protocol — server"),
    68: ("DHCP-client", "udp", "Dynamic Host Configuration Protocol — client"),
    80: ("HTTP", "tcp", "HyperText Transfer Protocol — the plaintext web"),
    110: ("POP3", "tcp", "Post Office Protocol v3 — download-and-delete mail"),
    123: ("NTP", "udp", "Network Time Protocol — clock synchronization"),
    143: ("IMAP", "tcp", "Internet Message Access Protocol — server-side mailbox"),
    443: ("HTTPS", "tcp", "HTTP over TLS — the encrypted web"),
    587: ("SMTP-submission", "tcp", "Mail submission from clients (authenticated)"),
    993: ("IMAPS", "tcp", "IMAP over TLS"),
    995: ("POP3S", "tcp", "POP3 over TLS"),
}


def lookup(port: int) -> str:
    """Return a human name for a port, or '(unassigned/unknown)' if we have none."""
    entry = WELL_KNOWN_PORTS.get(port)
    if entry is None:
        return "(unassigned/unknown)"
    name, transport, purpose = entry
    return f"{name} [{transport}] — {purpose}"


def port_range_name(port: int) -> str:
    """Classify a port into its IANA range (RFC 6335)."""
    if port <= 1023:
        return "well-known"
    if port <= 49151:
        return "registered"
    return "ephemeral"


def start_listener(port: int, ready: threading.Event) -> None:
    """Bind a throwaway TCP listener on `port` so the scanner finds it 'open'."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, port))
        server.listen(1)
        ready.set()
        try:
            # Accept one probe connection so the scan's connect() fully succeeds,
            # then fall through and close. daemon=True means we never block exit.
            conn, _ = server.accept()
            conn.close()
        except OSError:
            pass


def is_open(port: int, timeout: float = 0.2) -> bool:
    """Probe one TCP port on localhost. A completed connect() => something listens."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(timeout)   # short timeout: a closed port refuses instantly
        return probe.connect_ex((HOST, port)) == 0   # 0 == success, else errno


def scan(ports: range) -> list[int]:
    """Return the sorted list of open TCP ports in `ports` on 127.0.0.1."""
    return [p for p in ports if is_open(p)]


def main() -> None:
    # 1) Registry lookups — mapping a port number to the service behind it.
    print("Well-known port lookups (IANA registry, ports 0-1023):")
    for port in (22, 53, 80, 443, 25):
        print(f"  {port:>3} -> {lookup(port)}")
    print(f"  9999 -> {lookup(9999)}  (range: {port_range_name(9999)})")
    print()

    # 2) Stand up two throwaway listeners on chosen ports in the ephemeral range,
    #    so the scan has something real to find on localhost.
    listen_ports = [49_501, 49_517]
    threads = []
    for port in listen_ports:
        ready = threading.Event()
        thread = threading.Thread(
            target=start_listener, args=(port, ready), daemon=True
        )
        thread.start()
        ready.wait(timeout=5)   # don't scan until the socket is actually bound
        threads.append(thread)

    # 3) Scan a small range that straddles our two listeners.
    scan_range = range(49_500, 49_520)
    print(f"Scanning 127.0.0.1 ports {scan_range.start}-{scan_range.stop - 1} "
          f"(all in the {port_range_name(scan_range.start)} range):")
    open_ports = scan(scan_range)
    if open_ports:
        for port in open_ports:
            print(f"  OPEN  {port}  -> {lookup(port)}")
    else:
        print("  (no open ports found)")
    print(f"\nFound {len(open_ports)} open port(s) out of {len(scan_range)} scanned.")

    assert set(open_ports) == set(listen_ports), "scanner should find exactly our listeners"
    print("[done] The scanner found exactly the ports we opened.")


if __name__ == "__main__":
    main()
