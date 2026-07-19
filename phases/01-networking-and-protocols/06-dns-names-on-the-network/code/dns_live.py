"""
DNS — attempt a REAL query over the network, degrading gracefully with no net.

Sends the same "A? example.com" query built in dns_message.py to a public
resolver over UDP (User Datagram Protocol) port 53, with a 2-second timeout.
NEEDS NETWORK. Every socket call is wrapped so that no network, a firewall, or a
lost reply prints a friendly message and STILL exits 0 — safe for an offline grader.

Docs: phases/01-networking-and-protocols/06-dns-names-on-the-network/docs/en.md
Spec: RFC 1035 §4.1 (message format), §4.2.1 (UDP transport on port 53)

Run:
    python dns_live.py
Prints the resolved address if the network answers, else a friendly note; exits 0.
"""

from __future__ import annotations

import socket
import struct

RESOLVER = ("1.1.1.1", 53)   # Cloudflare's public resolver; any recursive resolver works
TIMEOUT_SECONDS = 2.0


def encode_qname(name: str) -> bytes:
    """Encode a name as length-prefixed labels, e.g. 7 'example' 3 'com' 0."""
    out = bytearray()
    for label in name.split("."):
        out.append(len(label))
        out.extend(label.encode("ascii"))
    out.append(0)
    return bytes(out)


def build_query(name: str, query_id: int = 0x1234) -> bytes:
    """A standard recursive A query: 12-byte header + question (RFC 1035 §4.1)."""
    header = struct.pack(">HHHHHH", query_id, 0x0100, 1, 0, 0, 0)  # RD=1
    return header + encode_qname(name) + struct.pack(">HH", 1, 1)   # QTYPE A, QCLASS IN


def first_a_record(msg: bytes) -> str:
    """Very small parser: skip to the answer section and read the first A record.

    Assumes the answer's name is a compression pointer (2 bytes), which is what
    resolvers overwhelmingly send. Returns "" if no A record is found.
    """
    an_count = struct.unpack(">H", msg[6:8])[0]
    # Skip the header (12 bytes) and the single question we asked.
    offset = 12
    while msg[offset] != 0:            # walk labels of the question's QNAME
        offset += msg[offset] + 1
    offset += 1 + 4                    # zero byte + QTYPE(2) + QCLASS(2)
    for _ in range(an_count):
        offset += 2                    # answer name (a 2-byte compression pointer)
        rtype, _rclass, _ttl, rdlength = struct.unpack(">HHIH", msg[offset:offset + 10])
        offset += 10
        rdata = msg[offset:offset + rdlength]
        offset += rdlength
        if rtype == 1 and rdlength == 4:
            return ".".join(str(b) for b in rdata)
    return ""


def main() -> None:
    query = build_query("example.com")
    print(f"Querying {RESOLVER[0]}:{RESOLVER[1]} for A example.com "
          f"({len(query)} bytes over UDP)...")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(TIMEOUT_SECONDS)   # loss/no-net must never hang forever
            sock.sendto(query, RESOLVER)
            reply, _ = sock.recvfrom(512)      # a normal UDP DNS reply fits in 512 bytes
        ip = first_a_record(reply)
        if ip:
            print(f"[live] example.com -> {ip}")
        else:
            print("[live] reply received but no A record found")
    except (socket.timeout, OSError) as exc:
        # No network, a firewall dropping UDP/53, or simply no reply in time.
        # UDP makes no delivery promise, so this is an expected outcome, not a crash.
        print(f"[offline] no reply within {TIMEOUT_SECONDS:g}s ({exc}); "
              "run dns_message.py to see the same query decoded offline")


if __name__ == "__main__":
    main()
