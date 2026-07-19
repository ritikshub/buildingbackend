"""
Protocol Buffers — the wire format, built by hand with the standard library.

We implement varint (variable-length integer) encoding, the tag byte
tag = (field_number << 3) | wire_type, and encode/decode a small `Person`
message (int32 id = field #1, string name = field #2), then assert the round
trip is byte-for-byte exact. Nothing is imported but the stdlib — no protobuf.

Docs: phases/01-networking-and-protocols/13-grpc-and-protocol-buffers/docs/en.md
Spec: Protocol Buffers Encoding (https://protobuf.dev/programming-guides/encoding/)
Run:  python3 protobuf_wire.py   # prints the bytes, decodes them, exits 0
"""

# Wire types from the Protocol Buffers encoding spec. A field's tag packs the
# field number and one of these into a single varint.
WIRE_VARINT = 0  # int32/int64/uint32/uint64/sint*/bool/enum
WIRE_I64 = 1     # fixed64/sfixed64/double
WIRE_LEN = 2     # string/bytes/embedded messages/packed repeated
WIRE_I32 = 5     # fixed32/sfixed32/float


def encode_varint(value: int) -> bytes:
    """Encode a non-negative integer as a base-128 varint.

    Each byte carries 7 bits of the value, little-endian (least significant
    group first). The high bit (MSB = most significant bit, 0x80) is a
    'continuation' flag: 1 means "more bytes follow", 0 means "last byte".
    So small numbers cost few bytes; 0..127 fit in a single byte.
    """
    if value < 0:
        raise ValueError("varint here encodes only non-negative integers")
    out = bytearray()
    while True:
        seven_bits = value & 0x7F      # take the low 7 bits
        value >>= 7                    # shift them off
        if value:                      # more bits remain -> set continuation flag
            out.append(seven_bits | 0x80)
        else:                          # last group -> continuation flag stays 0
            out.append(seven_bits)
            break
    return bytes(out)


def decode_varint(data: bytes, pos: int) -> tuple:
    """Decode one varint starting at `pos`; return (value, next_pos)."""
    result = 0
    shift = 0
    while True:
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift   # append this byte's 7 bits
        if not (byte & 0x80):              # continuation flag clear -> done
            break
        shift += 7
    return result, pos


def encode_tag(field_number: int, wire_type: int) -> bytes:
    """A field's key is the varint tag = (field_number << 3) | wire_type."""
    return encode_varint((field_number << 3) | wire_type)


def encode_person(id_: int, name: str) -> bytes:
    """Serialize {id: field #1 (int32), name: field #2 (string)} to protobuf."""
    out = bytearray()
    # field #1, int32 -> wire type 0 (varint): tag then the value
    out += encode_tag(1, WIRE_VARINT)
    out += encode_varint(id_)
    # field #2, string -> wire type 2 (length-delimited): tag, length, then bytes
    name_bytes = name.encode("utf-8")
    out += encode_tag(2, WIRE_LEN)
    out += encode_varint(len(name_bytes))
    out += name_bytes
    return bytes(out)


def decode_person(data: bytes) -> dict:
    """Parse protobuf bytes back into {field_number: value}, tag by tag."""
    fields = {}
    pos = 0
    while pos < len(data):
        tag, pos = decode_varint(data, pos)
        field_number = tag >> 3        # the top bits are the field number
        wire_type = tag & 0x07         # the low 3 bits are the wire type
        if wire_type == WIRE_VARINT:
            value, pos = decode_varint(data, pos)
            fields[field_number] = value
        elif wire_type == WIRE_LEN:
            length, pos = decode_varint(data, pos)
            value = data[pos:pos + length]
            pos += length
            fields[field_number] = value.decode("utf-8")
        else:
            raise ValueError(f"wire type {wire_type} not handled in this demo")
    return fields


def hexdump(data: bytes) -> str:
    """Space-separated hex, the way protobuf's own docs show wire bytes."""
    return data.hex(" ")


def main() -> None:
    person_id, person_name = 150, "Ada"   # id=150 is the protobuf spec's own example

    encoded = encode_person(person_id, person_name)
    print("Encoding Person{ id=150 (#1, int32), name='Ada' (#2, string) }")
    print(f"  wire bytes ({len(encoded)} bytes): {hexdump(encoded)}")
    print("  reading the tags:")
    print("    08        tag: (1 << 3) | 0  -> field #1, wire type 0 (varint)")
    print("    96 01     varint 150         -> id = 150")
    print("    12        tag: (2 << 3) | 2  -> field #2, wire type 2 (length)")
    print("    03        length 3           -> 'Ada' is 3 bytes")
    print("    41 64 61  'Ada' in UTF-8     -> name = 'Ada'")

    decoded = decode_person(encoded)
    print(f"\nDecoded back to fields: {decoded}")
    assert decoded[1] == person_id, "id must round-trip exactly"
    assert decoded[2] == person_name, "name must round-trip exactly"
    print("Round trip verified: decode(encode(x)) == x")

    # Small numbers cost few bytes — that is the whole point of varint.
    print("\nVarint is compact for small integers:")
    for n in (0, 1, 127, 128, 300, 16_384, 2_000_000):
        vb = encode_varint(n)
        back, _ = decode_varint(vb, 0)
        assert back == n
        print(f"  {n:>9} -> {len(vb)} byte(s): {hexdump(vb)}")

    print("\nProtocol Buffers wire format implemented by hand. Exiting 0.")


if __name__ == "__main__":
    main()
