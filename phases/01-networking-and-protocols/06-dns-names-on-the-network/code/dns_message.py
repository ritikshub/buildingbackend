"""
DNS — build a real query and decode a real response, fully offline.

Constructs a DNS (Domain Name System) query for "example.com": a 12-byte header
packed with struct plus a QNAME encoded as length-prefixed labels. Then it decodes
a HARDCODED response packet (bytes included below) and extracts the answer A record's
IPv4 address. No network is touched; everything here is deterministic.

Docs: phases/01-networking-and-protocols/06-dns-names-on-the-network/docs/en.md
Spec: RFC 1035 §4.1 (message format), §4.1.4 (name compression)

Run:
    python dns_message.py
Prints the raw query bytes, the decoded response, and the extracted IP, then exits 0.
"""

from __future__ import annotations

import struct

# Record TYPE and CLASS codes we care about (RFC 1035 §3.2.2 / §3.2.4).
TYPE_A = 1        # A = a single IPv4 address
CLASS_IN = 1      # IN = the Internet class

# Human names for the common record types, so the decoder can label what it sees.
TYPE_NAMES = {
    1: "A", 2: "NS", 5: "CNAME", 6: "SOA",
    12: "PTR", 15: "MX", 16: "TXT", 28: "AAAA",
}


# --- Building a query -------------------------------------------------------

def encode_qname(name: str) -> bytes:
    """Encode 'example.com' as length-prefixed labels: 7 'example' 3 'com' 0.

    A DNS name is a sequence of labels. Each label is one length byte followed by
    that many characters; a zero-length label (a single 0x00 byte) marks the root
    and ends the name. There are no dots on the wire — the lengths replace them.
    """
    out = bytearray()
    for label in name.split("."):
        out.append(len(label))          # one length byte per label
        out.extend(label.encode("ascii"))
    out.append(0)                       # the root label terminates the name
    return bytes(out)


def build_query(name: str, query_id: int = 0x1234) -> bytes:
    """Build a standard recursive query for one name's A record."""
    # Header: ID, flags, and four section counts, each 16 bits (RFC 1035 §4.1.1).
    # Flags 0x0100 sets just RD (Recursion Desired): "resolver, do the walk for me."
    header = struct.pack(
        ">HHHHHH",
        query_id,   # ID: the reply must echo this so we can match it
        0x0100,     # flags: QR=0 (query), Opcode=0 (standard), RD=1
        1,          # QDCOUNT: one question
        0,          # ANCOUNT: no answers in a query
        0,          # NSCOUNT: no authority records
        0,          # ARCOUNT: no additional records
    )
    # Question: QNAME + QTYPE + QCLASS (RFC 1035 §4.1.2).
    question = encode_qname(name) + struct.pack(">HH", TYPE_A, CLASS_IN)
    return header + question


# --- Decoding a response ----------------------------------------------------

# A REAL response to "A? example.com", captured as raw bytes so this file stays
# offline and deterministic. The answer's RDATA is 93.184.216.34.
#   0x1234              ID (echoes the query)
#   0x8180              flags: QR=1, RD=1, RA=1, RCODE=0 (no error)
#   0x0001 0x0001       QDCOUNT=1, ANCOUNT=1
#   0x0000 0x0000       NSCOUNT=0, ARCOUNT=0
#   question:  07 'example' 03 'com' 00  + TYPE A + CLASS IN
#   answer:    C0 0C (pointer back to the name at offset 12) + A + IN
#              + TTL 3600 + RDLENGTH 4 + 93.184.216.34
RESPONSE = bytes.fromhex(
    "123481800001000100000000"          # header: id, flags, QD=1 AN=1 NS=0 AR=0
    "076578616d706c6503636f6d0000010001"  # question: 7 example 3 com 0 + A + IN
    "c00c0001000100000e1000045db8d822"    # answer: ptr->12, A, IN, TTL 3600, 93.184.216.34
)


def read_name(msg: bytes, offset: int) -> tuple[str, int]:
    """Read a (possibly compressed) name and return it plus the next offset.

    A name is a run of length-prefixed labels ending in a zero byte. To save space
    a name may instead end in a 2-byte *compression pointer* — the top two bits set
    (0xC0) mark it, and the low 14 bits give an offset elsewhere in the message to
    continue from (RFC 1035 §4.1.4). We follow the pointer but report the offset
    just past it, so the caller keeps parsing where the record actually continues.
    """
    labels: list[str] = []
    jumped = False
    next_offset = offset
    while True:
        length = msg[offset]
        if length & 0xC0 == 0xC0:                       # a compression pointer
            pointer = ((length & 0x3F) << 8) | msg[offset + 1]
            if not jumped:
                next_offset = offset + 2                # a pointer is 2 bytes wide
            offset = pointer
            jumped = True
            continue
        if length == 0:                                 # root label: name ends
            if not jumped:
                next_offset = offset + 1
            break
        offset += 1
        labels.append(msg[offset:offset + length].decode("ascii"))
        offset += length
    return ".".join(labels), next_offset


def decode_flags(flags: int) -> str:
    """Spell out the 16-bit flags field as human-readable bits (RFC 1035 §4.1.1)."""
    qr = "response" if flags & 0x8000 else "query"
    rd = "yes" if flags & 0x0100 else "no"
    ra = "yes" if flags & 0x0080 else "no"
    rcode = flags & 0x000F
    return f"QR={qr}, RD={rd}, RA={ra}, RCODE={rcode}"


def decode_response(msg: bytes) -> str:
    """Decode a DNS response and return the first A record's IPv4 address."""
    query_id, flags, qd, an, ns, ar = struct.unpack(">HHHHHH", msg[:12])
    print(f"DNS response — {len(msg)} bytes")
    print(f"  id .................. {query_id:#06x}")
    print(f"  flags ............... {flags:#06x}  -> {decode_flags(flags)}")
    print(f"  counts .............. QD={qd} AN={an} NS={ns} AR={ar}")

    offset = 12
    for _ in range(qd):                                 # walk the question section
        qname, offset = read_name(msg, offset)
        qtype, qclass = struct.unpack(">HH", msg[offset:offset + 4])
        offset += 4
        print(f"  question ............ {qname}  "
              f"TYPE={TYPE_NAMES.get(qtype, qtype)} CLASS={qclass}")

    answer_ip = ""
    for _ in range(an):                                 # walk the answer section
        name, offset = read_name(msg, offset)
        rtype, rclass, ttl, rdlength = struct.unpack(">HHIH", msg[offset:offset + 10])
        offset += 10
        rdata = msg[offset:offset + rdlength]
        offset += rdlength
        type_name = TYPE_NAMES.get(rtype, str(rtype))
        if rtype == TYPE_A and rdlength == 4:
            answer_ip = ".".join(str(b) for b in rdata)  # 4 bytes -> dotted IPv4
            print(f"  answer .............. {name} {type_name} "
                  f"TTL={ttl}s -> {answer_ip}")
        else:
            print(f"  answer .............. {name} {type_name} "
                  f"TTL={ttl}s -> {rdata!r}")
    return answer_ip


def main() -> None:
    # 1) Build a query and show the bytes that would go on the wire.
    query = build_query("example.com")
    print(f"DNS query for example.com — {len(query)} bytes")
    print(f"  hex: {query.hex()}")
    print()

    # 2) Decode the hardcoded response and pull out the address.
    ip = decode_response(RESPONSE)
    print()
    print(f"Resolved example.com -> {ip}")

    # Deterministic self-check: the bytes above always decode to this address.
    assert ip == "93.184.216.34", f"unexpected address: {ip}"


if __name__ == "__main__":
    main()
