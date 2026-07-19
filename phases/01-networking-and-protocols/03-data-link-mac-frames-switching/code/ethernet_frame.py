"""
Data Link Layer — build and parse an Ethernet II frame by hand.

An Ethernet II frame lays its fields out at fixed offsets: destination MAC
(6 bytes), source MAC (6), EtherType (2), payload (46-1500), and a 4-byte Frame
Check Sequence (a CRC-32). Here we pack those fields with struct, append the FCS,
then parse the raw bytes back - decoding the MACs to colon-hex and the EtherType
to a protocol name - and prove the checksum catches a single flipped bit.

Docs: phases/01-networking-and-protocols/03-data-link-mac-frames-switching/docs/en.md
Spec: IEEE 802.3 (Ethernet frame format and the 32-bit FCS/CRC)

Run:
    python3 ethernet_frame.py
Builds a frame, parses it back, verifies the FCS, corrupts a bit, exits 0.
"""

import struct
import zlib

# EtherType tells the receiver which protocol the payload belongs to.
ETHERTYPES = {
    0x0800: "IPv4",
    0x0806: "ARP",
    0x86DD: "IPv6",
}

MIN_PAYLOAD = 46          # pad shorter payloads so the frame reaches 64 bytes total
HEADER = ">6s 6s H"       # dst MAC, src MAC, EtherType — big-endian (network order)
BROADCAST = "ff:ff:ff:ff:ff:ff"


def mac_to_bytes(mac: str) -> bytes:
    """'00:1a:2b:3c:4d:5e' -> 6 raw bytes."""
    octets = mac.split(":")
    if len(octets) != 6:
        raise ValueError(f"a MAC address has 6 octets, got {len(octets)}: {mac!r}")
    return bytes(int(octet, 16) for octet in octets)


def bytes_to_mac(raw: bytes) -> str:
    """6 raw bytes -> '00:1a:2b:3c:4d:5e'."""
    return ":".join(f"{byte:02x}" for byte in raw)


def build_frame(dst: str, src: str, ethertype: int, payload: bytes) -> bytes:
    """Assemble one Ethernet II frame and append its CRC-32 Frame Check Sequence."""
    if len(payload) < MIN_PAYLOAD:
        payload = payload + b"\x00" * (MIN_PAYLOAD - len(payload))  # pad with zeros
    body = struct.pack(HEADER, mac_to_bytes(dst), mac_to_bytes(src), ethertype) + payload
    fcs = zlib.crc32(body) & 0xFFFFFFFF          # the checksum over dst+src+type+payload
    return body + struct.pack(">I", fcs)


def parse_frame(frame: bytes) -> dict:
    """Unpack a frame, recompute its FCS, and decode the human-readable fields."""
    dst_raw, src_raw, ethertype = struct.unpack(HEADER, frame[:14])
    payload = frame[14:-4]
    (fcs_stored,) = struct.unpack(">I", frame[-4:])
    fcs_computed = zlib.crc32(frame[:-4]) & 0xFFFFFFFF   # same math the sender ran
    return {
        "dst": bytes_to_mac(dst_raw),
        "src": bytes_to_mac(src_raw),
        "ethertype": ethertype,
        "protocol": ETHERTYPES.get(ethertype, "unknown"),
        "payload": payload,
        "fcs_stored": fcs_stored,
        "fcs_computed": fcs_computed,
        "fcs_ok": fcs_stored == fcs_computed,
    }


def main() -> None:
    dst = BROADCAST                # send to everyone on the link (an ARP-style frame)
    src = "00:1a:2b:3c:4d:5e"      # OUI 00:1a:2b identifies the card's vendor
    payload = b"hello, data link layer"

    frame = build_frame(dst, src, 0x0806, payload)
    print(f"built an Ethernet II frame of {len(frame)} bytes "
          f"(14 header + {len(frame) - 18} payload + 4 FCS)\n")

    parsed = parse_frame(frame)
    print(f"  destination MAC ..... {parsed['dst']}")
    print(f"  source MAC .......... {parsed['src']}  (OUI {parsed['src'][:8]})")
    print(f"  EtherType ........... {parsed['ethertype']:#06x} -> {parsed['protocol']}")
    print(f"  payload ............. {parsed['payload'][:22]!r} "
          f"(+ padding to {len(parsed['payload'])} bytes)")
    print(f"  FCS stored .......... {parsed['fcs_stored']:#010x}")
    print(f"  FCS recomputed ...... {parsed['fcs_computed']:#010x}")
    print(f"  FCS check ........... {'OK - frame intact' if parsed['fcs_ok'] else 'FAIL'}")

    assert parsed["fcs_ok"], "a freshly built frame must pass its own checksum"
    assert parsed["dst"] == dst and parsed["src"] == src

    # Flip a single bit in the payload, as electrical noise on a wire would, and
    # watch the receiver's recomputed FCS refuse the frame.
    corrupted = bytearray(frame)
    corrupted[20] ^= 0x01
    bad = parse_frame(bytes(corrupted))
    print(f"\nflipped one payload bit -> FCS check "
          f"{'OK' if bad['fcs_ok'] else 'FAIL - receiver drops the frame'}")
    assert not bad["fcs_ok"], "a corrupted frame must fail the checksum"


if __name__ == "__main__":
    main()
