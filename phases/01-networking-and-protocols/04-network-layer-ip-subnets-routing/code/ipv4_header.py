"""
Network Layer — build and parse a 20-byte IPv4 header from raw bytes.

We pack every field of an IPv4 header with struct, compute the one's-complement
header checksum ourselves, then unpack it back and re-verify the checksum — the
same construct-and-validate a router does for every packet it forwards. The
example carries protocol 1 (ICMP), the protocol `ping` and `traceroute` ride on.

Docs: phases/01-networking-and-protocols/04-network-layer-ip-subnets-routing/docs/en.md
Spec: RFC 791 §3.1 (IPv4 header), RFC 792 (ICMP), RFC 1071 (checksum algorithm)

Run:
    python ipv4_header.py
Builds a header, prints each field, verifies the checksum, and exits 0.
"""

import socket
import struct

# 20-byte IPv4 header layout (no options), field by field:
#   B  version(4) + IHL(4)            H  total length
#   B  DSCP + ECN (type of service)  H  identification
#   H  flags(3) + fragment offset(13)
#   B  TTL       B  protocol         H  header checksum
#   4s source address   4s destination address
IPV4_FORMAT = ">BBHHHBBH4s4s"

PROTO_NAMES = {1: "ICMP", 6: "TCP", 17: "UDP"}


def checksum(data: bytes) -> int:
    """One's-complement 16-bit checksum (RFC 1071): sum 16-bit words, fold carries, invert."""
    if len(data) % 2:            # pad to an even length so every word is 16 bits
        data += b"\x00"
    total = 0
    for i in range(0, len(data), 2):
        total += (data[i] << 8) | data[i + 1]
    while total >> 16:           # fold the carry bits back into the low 16 bits
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF     # one's complement, masked to 16 bits


def build_header(src: str, dst: str, ttl: int, protocol: int) -> bytes:
    version_ihl = (4 << 4) | 5   # IPv4, IHL = 5 words = 20 bytes (no options)
    tos = 0
    total_length = 20            # header only, no payload in this demo
    identification = 0x1C46
    flags_fragment = 0x4000      # "Don't Fragment" flag set, offset 0

    # First pack with a zero checksum, compute over those bytes, then repack.
    header_zero = struct.pack(
        IPV4_FORMAT,
        version_ihl, tos, total_length, identification, flags_fragment,
        ttl, protocol, 0,
        socket.inet_aton(src), socket.inet_aton(dst),
    )
    csum = checksum(header_zero)
    return struct.pack(
        IPV4_FORMAT,
        version_ihl, tos, total_length, identification, flags_fragment,
        ttl, protocol, csum,
        socket.inet_aton(src), socket.inet_aton(dst),
    )


def parse_header(raw: bytes) -> None:
    (ver_ihl, tos, total_len, ident, flags_frag,
     ttl, proto, csum, src, dst) = struct.unpack(IPV4_FORMAT, raw)
    version = ver_ihl >> 4
    ihl_bytes = (ver_ihl & 0x0F) * 4
    proto_name = PROTO_NAMES.get(proto, "other")

    print(f"IPv4 header — {len(raw)} bytes")
    print(f"  version ............. {version}")
    print(f"  header length (IHL) . {ihl_bytes} bytes")
    print(f"  type of service ..... {tos}")
    print(f"  total length ........ {total_len} bytes")
    print(f"  identification ...... {ident:#06x}")
    print(f"  flags+fragment ...... {flags_frag:#06x}  (Don't-Fragment set)")
    print(f"  TTL ................. {ttl}  (decremented one per hop)")
    print(f"  protocol ............ {proto} ({proto_name})")
    print(f"  header checksum ..... {csum:#06x}")
    print(f"  source address ...... {socket.inet_ntoa(src)}")
    print(f"  destination address . {socket.inet_ntoa(dst)}")

    # Re-running the checksum over the whole header (checksum field included)
    # must yield 0 if nothing was corrupted — that is how a receiver validates.
    assert checksum(raw) == 0, "checksum verification failed — header is corrupt"
    print("  checksum verification: OK (recomputed sum folds to 0)")


def main() -> None:
    header = build_header(src="192.168.1.10", dst="93.184.216.34", ttl=64, protocol=1)
    print(f"raw bytes: {header.hex()}")
    print()
    parse_header(header)
    print()
    print("A router that forwards this packet decrements the TTL and recomputes")
    print("the checksum; a TTL that hits 0 is dropped and triggers ICMP (RFC 792).")


if __name__ == "__main__":
    main()
