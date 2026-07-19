"""
gRPC framing — wrap a protobuf message the way gRPC does, by hand (stdlib only).

gRPC sends each message inside a "Length-Prefixed-Message": 1 compression-flag
byte + a 4-byte big-endian length + the serialized bytes, carried in HTTP/2
(Hypertext Transfer Protocol version 2) DATA frames. We build that frame around
a protobuf payload, then parse it back and assert the round trip. No grpc import.

Docs: phases/01-networking-and-protocols/13-grpc-and-protocol-buffers/docs/en.md
Spec: gRPC over HTTP/2 (https://github.com/grpc/grpc/blob/master/doc/PROTOCOL-HTTP2.md)
Run:  python3 grpc_frame.py   # builds a frame, parses it, exits 0
"""

import struct

WIRE_VARINT = 0
WIRE_LEN = 2


def encode_varint(value: int) -> bytes:
    """Base-128 varint (see protobuf_wire.py for the fully commented version)."""
    out = bytearray()
    while True:
        seven_bits = value & 0x7F
        value >>= 7
        if value:
            out.append(seven_bits | 0x80)
        else:
            out.append(seven_bits)
            break
    return bytes(out)


def encode_person(id_: int, name: str) -> bytes:
    """The same Person{ id #1, name #2 } payload, serialized to protobuf bytes."""
    out = bytearray()
    out += encode_varint((1 << 3) | WIRE_VARINT)   # tag for field #1
    out += encode_varint(id_)
    name_bytes = name.encode("utf-8")
    out += encode_varint((2 << 3) | WIRE_LEN)      # tag for field #2
    out += encode_varint(len(name_bytes))
    out += name_bytes
    return bytes(out)


def grpc_frame(message: bytes, compressed: bool = False) -> bytes:
    """Wrap a serialized message as a gRPC Length-Prefixed-Message.

    Layout: [compressed-flag: 1 byte][message-length: 4 bytes big-endian][message].
    The flag is 0 for identity (no compression), 1 if a Message-Encoding applies.
    """
    flag = 1 if compressed else 0
    return struct.pack(">BI", flag, len(message)) + message


def parse_grpc_frame(frame: bytes) -> tuple:
    """Return (compressed_flag, message_bytes) from one gRPC frame."""
    flag, length = struct.unpack(">BI", frame[:5])   # 1 + 4 fixed prefix bytes
    message = frame[5:5 + length]
    if len(message) != length:
        raise ValueError("frame is shorter than its declared length")
    return flag, message


def main() -> None:
    payload = encode_person(150, "Ada")
    print(f"protobuf payload ({len(payload)} bytes): {payload.hex(' ')}")

    frame = grpc_frame(payload)
    print(f"gRPC frame     ({len(frame)} bytes): {frame.hex(' ')}")
    print("  byte 0      -> compression flag (0 = identity, not compressed)")
    print("  bytes 1..4  -> message length, 4-byte big-endian uint32")
    print("  bytes 5..   -> the protobuf message itself")

    flag, message = parse_grpc_frame(frame)
    print(f"\nparsed flag: {flag}, message ({len(message)} bytes): {message.hex(' ')}")
    assert flag == 0, "we sent it uncompressed"
    assert message == payload, "the framed payload must come back byte-for-byte"
    print("Round trip verified: the framed protobuf message is intact. Exiting 0.")


if __name__ == "__main__":
    main()
