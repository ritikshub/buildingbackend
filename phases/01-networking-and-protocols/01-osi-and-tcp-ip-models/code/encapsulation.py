"""
OSI & TCP/IP models — encapsulation and decapsulation, by hand.

Model a tiny four-layer stack. On the way down (send), each layer wraps the
layer above's bytes in its own header, built with struct; on the way up (recv),
each layer peels its header off and hands the rest upward. The original message
falls out the top, byte-for-byte identical — that is the whole point of layering.

Docs: phases/01-networking-and-protocols/01-osi-and-tcp-ip-models/docs/en.md
Spec: RFC 1122 §1.1.3 (host layering), IEEE 802.3 (link/MAC), RFC 791 (IPv4)

Run:
    python encapsulation.py
It encapsulates a message down the stack, decapsulates it back up, and exits 0.
"""

import struct

# Each layer's header is a fixed-size byte prefix. We keep them tiny and mock —
# real headers carry far more (see the lesson's header tables) — but the shape
# is exactly what a kernel builds: a struct packed in front of the payload.
TRANSPORT = struct.Struct(">HH")    # src port (16 bits), dst port (16 bits)  -> 4 bytes
NETWORK = struct.Struct(">4s4s")    # src IPv4 (4 bytes), dst IPv4 (4 bytes)  -> 8 bytes
LINK = struct.Struct(">6s6s")       # src MAC (6 bytes),  dst MAC (6 bytes)   -> 12 bytes


def ip_to_bytes(dotted: str) -> bytes:
    """'192.168.1.10' -> b'\\xc0\\xa8\\x01\\x0a' (four octets, one byte each)."""
    return bytes(int(octet) for octet in dotted.split("."))


def bytes_to_ip(raw: bytes) -> str:
    """Four raw bytes -> dotted-decimal string."""
    return ".".join(str(octet) for octet in raw)


def mac_to_bytes(mac: str) -> bytes:
    """'02:00:00:00:00:01' -> six raw bytes."""
    return bytes.fromhex(mac.replace(":", ""))


def bytes_to_mac(raw: bytes) -> str:
    """Six raw bytes -> colon-separated hex string."""
    return ":".join(f"{octet:02x}" for octet in raw)


def preview(raw: bytes, keep: int = 16) -> str:
    """A short hex preview of a byte string, so long frames stay readable."""
    shown = raw[:keep].hex(" ")
    return shown + (" ..." if len(raw) > keep else "")


# --- Sending: wrap the message layer by layer, top (L7) down to the wire (L1) --

def encapsulate(message: bytes) -> bytes:
    """Take an application message and wrap it down through three headers."""
    print("SEND — down the stack (each layer prepends its own header)\n")

    # Application (L7): the raw message. Its PDU is just "data".
    print(f"  Application  data     {len(message):>3} bytes  {message!r}")

    # Transport (L4): prepend ports so the bytes reach the right *program*.
    # The PDU is now a "segment".
    segment = TRANSPORT.pack(49152, 80) + message   # ephemeral src port -> port 80 (HTTP)
    print(f"  Transport    segment  {len(segment):>3} bytes  +4B ports "
          f"(49152 -> 80)   {preview(segment)}")

    # Network (L3): prepend source/destination IPv4 addresses so the segment
    # reaches the right *machine*. The PDU is now a "packet".
    packet = NETWORK.pack(ip_to_bytes("192.168.1.10"),
                          ip_to_bytes("93.184.216.34")) + segment
    print(f"  Network      packet   {len(packet):>3} bytes  +8B IPs "
          f"(192.168.1.10 -> 93.184.216.34)   {preview(packet)}")

    # Link (L2): prepend source/destination MAC addresses so the packet reaches
    # the right *next hop* on the local wire. The PDU is now a "frame".
    frame = LINK.pack(mac_to_bytes("02:00:00:00:00:01"),
                      mac_to_bytes("02:00:00:00:00:fe")) + packet
    print(f"  Link         frame    {len(frame):>3} bytes  +12B MACs "
          f"(02:..:01 -> 02:..:fe)   {preview(frame)}")

    print(f"\n  On the wire: {len(frame)} bytes leave the network card as bits.\n")
    return frame


# --- Receiving: peel each header off, bottom (L1) up to the application (L7) ---

def decapsulate(frame: bytes) -> bytes:
    """Reverse the wrapping: strip each header and report what each layer sees."""
    print("RECV — up the stack (each layer reads, then strips, its own header)\n")

    # Link (L2): read the MAC header, keep the rest as the packet.
    src_mac, dst_mac = LINK.unpack(frame[:LINK.size])
    packet = frame[LINK.size:]
    print(f"  Link         reads MACs {bytes_to_mac(src_mac)} -> {bytes_to_mac(dst_mac)}; "
          f"hands up a {len(packet)}-byte packet")

    # Network (L3): read the IP header, keep the rest as the segment.
    src_ip, dst_ip = NETWORK.unpack(packet[:NETWORK.size])
    segment = packet[NETWORK.size:]
    print(f"  Network      reads IPs  {bytes_to_ip(src_ip)} -> {bytes_to_ip(dst_ip)}; "
          f"hands up a {len(segment)}-byte segment")

    # Transport (L4): read the port header, keep the rest as the application data.
    src_port, dst_port = TRANSPORT.unpack(segment[:TRANSPORT.size])
    message = segment[TRANSPORT.size:]
    print(f"  Transport    reads ports {src_port} -> {dst_port}; "
          f"hands up {len(message)} bytes of data")

    # Application (L7): the original message, recovered untouched.
    print(f"  Application  sees the message: {message!r}\n")
    return message


def main() -> None:
    original = b"GET /index.html HTTP/1.1"
    print(f"Application message: {original!r}  ({len(original)} bytes)\n")

    frame = encapsulate(original)
    recovered = decapsulate(frame)

    assert recovered == original, "decapsulation must recover the exact bytes sent"
    print("[ok] the bytes that came out the top equal the bytes that went in —")
    print("     every layer added and removed exactly its own header, nothing else.")


if __name__ == "__main__":
    main()
