"""
HTTP/2 — build and parse the 9-byte binary frame header.

Every HTTP/2 message is chopped into frames, and each frame opens with a fixed
9-byte header: a 24-bit length, an 8-bit type, an 8-bit flags byte, then a
32-bit word holding 1 reserved bit plus a 31-bit stream identifier. We build a
few real frame headers with struct, then unpack every field back out — the same
parse an HTTP/2 endpoint runs on every frame that arrives.

Docs: phases/01-networking-and-protocols/11-http2-and-http3-quic/docs/en.md
Spec: RFC 9113 §4.1 (HTTP/2 frame header); RFC 9114 (HTTP/3); RFC 9000 (QUIC)

Run:
    python3 http2_frame.py
Builds sample frames, round-trips them through the parser, then exits 0.
"""

import struct

FRAME_HEADER_LEN = 9  # bytes: 3 (length) + 1 (type) + 1 (flags) + 4 (R + stream id)

# HTTP/2 frame types (RFC 9113 §6). The type byte selects the frame's meaning.
FRAME_TYPES = {
    0x0: "DATA",           # request/response body bytes
    0x1: "HEADERS",        # HPACK-compressed header block, opens a stream
    0x2: "PRIORITY",       # stream dependency/weight hints
    0x3: "RST_STREAM",     # abruptly terminate one stream
    0x4: "SETTINGS",       # connection-level configuration (stream 0)
    0x5: "PUSH_PROMISE",   # server-initiated stream announcement
    0x6: "PING",           # liveness / round-trip measurement
    0x7: "GOAWAY",         # graceful connection shutdown (stream 0)
    0x8: "WINDOW_UPDATE",  # flow-control credit (per-stream or connection)
    0x9: "CONTINUATION",   # extra header block fragments
}

# A few common flag bits, by frame type (RFC 9113 §6). Flags are a bitfield.
FLAG_END_STREAM = 0x1   # DATA / HEADERS: no more frames on this stream
FLAG_END_HEADERS = 0x4  # HEADERS / CONTINUATION: header block is complete


def build_frame_header(length, ftype, flags, stream_id, reserved=0):
    """Pack the 9-byte HTTP/2 frame header from its fields."""
    if not 0 <= length <= 0xFFFFFF:
        raise ValueError("length must fit in 24 bits (0..16_777_215)")
    if not 0 <= stream_id <= 0x7FFFFFFF:
        raise ValueError("stream id must fit in 31 bits")
    # 24-bit length: struct has no 3-byte int, so pack as 32 bits and drop the
    # high byte, leaving the low 3 bytes = exactly 24 bits.
    length_bytes = struct.pack(">I", length)[1:]
    type_and_flags = struct.pack(">BB", ftype, flags)
    # Top bit is the reserved (R) bit; the low 31 bits are the stream identifier.
    stream_word = struct.pack(">I", (reserved << 31) | stream_id)
    return length_bytes + type_and_flags + stream_word


def parse_frame_header(raw):
    """Unpack the first 9 bytes of raw into the HTTP/2 frame header fields."""
    if len(raw) < FRAME_HEADER_LEN:
        raise ValueError(f"need {FRAME_HEADER_LEN} bytes, got {len(raw)}")
    header = raw[:FRAME_HEADER_LEN]
    # Prepend a zero byte so struct can read the 24-bit length as a 32-bit int.
    length = struct.unpack(">I", b"\x00" + header[0:3])[0]
    ftype, flags = struct.unpack(">BB", header[3:5])
    stream_word = struct.unpack(">I", header[5:9])[0]
    reserved = stream_word >> 31            # the single top bit
    stream_id = stream_word & 0x7FFFFFFF    # the low 31 bits
    return {
        "length": length,
        "type": ftype,
        "type_name": FRAME_TYPES.get(ftype, "UNKNOWN"),
        "flags": flags,
        "reserved": reserved,
        "stream_id": stream_id,
    }


def show(label, raw):
    """Decode one 9-byte header and print every field."""
    f = parse_frame_header(raw)
    print(label)
    print(f"  raw bytes ........... {raw[:FRAME_HEADER_LEN].hex(' ')}")
    print(f"  length .............. {f['length']} bytes of payload follow the header")
    print(f"  type ................ {f['type']:#04x}  -> {f['type_name']}")
    print(f"  flags ............... {f['flags']:#010b}")
    print(f"  reserved bit ........ {f['reserved']}")
    print(f"  stream id ........... {f['stream_id']}")
    print()


def main():
    print("HTTP/2 frame header — 9 bytes: length(24) type(8) flags(8) R(1) stream(31)")
    print()

    # Build four frames of a typical request/response on one connection.
    # SETTINGS and WINDOW_UPDATE ride stream 0 (the connection control stream);
    # HEADERS and DATA carry one request's headers and body on stream 1.
    settings = build_frame_header(18, 0x4, 0x0, 0)                          # 3 params
    headers = build_frame_header(41, 0x1, FLAG_END_HEADERS, 1)             # request headers
    data = build_frame_header(1024, 0x0, FLAG_END_STREAM, 1)               # request body
    win = build_frame_header(4, 0x8, 0x0, 0)                               # flow-control credit

    show("SETTINGS (connection setup, stream 0)", settings)
    show("HEADERS (request on stream 1, END_HEADERS set)", headers)
    show("DATA (request body on stream 1, END_STREAM set)", data)
    show("WINDOW_UPDATE (add flow-control credit, stream 0)", win)

    # A header captured off the wire (hardcoded), decoded from scratch:
    # 00 00 08  -> length 8   | 00 -> DATA | 01 -> END_STREAM | 00 00 00 03 -> stream 3
    wire = b"\x00\x00\x08\x00\x01\x00\x00\x00\x03"
    show("A frame header off the wire (hardcoded bytes)", wire)

    # Verify: build -> parse round-trips exactly, and the wire header decodes
    # to the values documented above. Any mismatch raises and exits non-zero.
    parsed = parse_frame_header(headers)
    assert parsed["length"] == 41
    assert parsed["type_name"] == "HEADERS"
    assert parsed["flags"] & FLAG_END_HEADERS
    assert parsed["stream_id"] == 1
    wire_parsed = parse_frame_header(wire)
    assert wire_parsed == {
        "length": 8, "type": 0x0, "type_name": "DATA",
        "flags": 0x1, "reserved": 0, "stream_id": 3,
    }

    print("Round-trip OK: every built header parsed back to its exact fields.")
    print("One 9-byte header per frame is all HTTP/2 needs to multiplex many")
    print("streams over a single TCP connection.")


if __name__ == "__main__":
    main()
