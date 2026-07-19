"""
Transport Layer — decode a TCP and a UDP header from raw bytes.

The best way to *believe* a header layout is to unpack one. Below are the exact
bytes of a TCP SYN segment (the first packet of a handshake) and a UDP datagram
header, decoded field by field with struct.unpack. This is what your kernel does
to every segment that arrives; we just do it in the open.

Docs: phases/01-networking-and-protocols/05-transport-layer-tcp-vs-udp/docs/en.md
Spec: RFC 9293 §3.1 (TCP header), RFC 768 (UDP header)

Run:
    python decode_headers.py
Prints every field and its size, then exits 0.
"""

import struct

# --- A real TCP header: 20 bytes, no options (a SYN starting a handshake) ----
# fields, in order:  src(16) dst(16) seq(32) ack(32) off+rsvd(8) flags(8)
#                    window(16) checksum(16) urgent(16)  = 160 bits = 20 bytes
tcp_header = struct.pack(
    ">HH I I BB HHH",
    54_321,        # source port
    443,           # destination port (HTTPS)
    0x12345678,    # sequence number
    0,             # acknowledgment number (0: nothing acked yet on a pure SYN)
    (5 << 4),      # data offset = 5 words (20 bytes); low 4 bits reserved = 0
    0x02,          # flags byte: 0b00000010 -> SYN set
    64_240,        # window size (bytes the sender is willing to receive)
    0x1D2C,        # checksum (a placeholder value here)
    0,             # urgent pointer
)

# --- A real UDP header: 8 bytes flat --------------------------------------
# fields:  src(16) dst(16) length(16) checksum(16)  = 64 bits = 8 bytes
udp_header = struct.pack(
    ">HHHH",
    54_322,        # source port
    53,            # destination port (DNS)
    20,            # length = 8-byte header + 12-byte payload
    0xABCD,        # checksum
)

TCP_FLAGS = ["CWR", "ECE", "URG", "ACK", "PSH", "RST", "SYN", "FIN"]


def decode_tcp(raw: bytes) -> None:
    (src, dst, seq, ack, off_rsvd, flags, window, checksum, urg) = struct.unpack(
        ">HH I I BB HHH", raw
    )
    header_len = (off_rsvd >> 4) * 4  # top 4 bits are the data offset, in 32-bit words
    set_flags = [name for i, name in enumerate(TCP_FLAGS) if flags & (0x80 >> i)]
    print(f"TCP header — {len(raw)} bytes ({len(raw) * 8} bits)")
    print(f"  source port ......... {src}")
    print(f"  destination port .... {dst}")
    print(f"  sequence number ..... {seq}")
    print(f"  ack number .......... {ack}")
    print(f"  data offset ......... {header_len} bytes of header")
    print(f"  flags ............... {flags:#010b}  -> {', '.join(set_flags) or 'none'}")
    print(f"  window size ......... {window}")
    print(f"  checksum ............ {checksum:#06x}")
    print(f"  urgent pointer ...... {urg}")


def decode_udp(raw: bytes) -> None:
    src, dst, length, checksum = struct.unpack(">HHHH", raw)
    print(f"UDP header — {len(raw)} bytes ({len(raw) * 8} bits)")
    print(f"  source port ......... {src}")
    print(f"  destination port .... {dst}")
    print(f"  length .............. {length} bytes (header + payload)")
    print(f"  checksum ............ {checksum:#06x}")


def main() -> None:
    decode_tcp(tcp_header)
    print()
    decode_udp(udp_header)
    print()
    print("Note the cost gap: TCP spends 20 bytes per segment (more with options)")
    print("to carry sequence/ack/flags/window; UDP spends 8 and carries almost nothing.")


if __name__ == "__main__":
    main()
