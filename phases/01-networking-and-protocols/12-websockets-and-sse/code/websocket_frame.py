"""
WebSockets & SSE — build and parse a masked WebSocket frame by hand.

Two offline demos of RFC 6455 mechanics using only the standard library:
(1) compute the Sec-WebSocket-Accept handshake value from a client's
Sec-WebSocket-Key with hashlib.sha1 + base64 + the RFC 6455 magic GUID, and
(2) encode a masked text frame (FIN / opcode / MASK / length / masking-key /
payload) and parse it back, XOR-unmasking the payload and asserting a round trip.

Docs: phases/01-networking-and-protocols/12-websockets-and-sse/docs/en.md
Spec: RFC 6455 §1.3 (handshake), §5.2 (base framing protocol)

Run:
    python websocket_frame.py
Prints the handshake value and the decoded frame, asserts round-trip, exits 0.
"""

import base64
import hashlib
import os
import struct
from typing import Dict

# The fixed GUID (Globally Unique Identifier) every RFC 6455 server appends to
# the client's key before hashing. It never changes; it is defined by the RFC.
WS_MAGIC_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OPCODE_TEXT = 0x1  # a UTF-8 text frame (RFC 6455 §5.6)


def compute_accept(sec_websocket_key: str) -> str:
    """Sec-WebSocket-Accept = base64(SHA1(key + magic GUID)) — RFC 6455 §4.2.2."""
    combined = (sec_websocket_key + WS_MAGIC_GUID).encode("ascii")
    digest = hashlib.sha1(combined).digest()          # 20 raw SHA-1 bytes
    return base64.b64encode(digest).decode("ascii")   # 28-char base64 text


def build_masked_text_frame(payload: bytes, masking_key: bytes) -> bytes:
    """Encode one final, masked text frame exactly as a browser client would."""
    assert len(masking_key) == 4, "the masking key is always 4 bytes"
    # Byte 0: FIN=1 (this frame is the whole message) + the 4-bit text opcode.
    b0 = 0x80 | OPCODE_TEXT
    # Byte 1 onward: MASK=1 (0x80), then the length in one of three forms.
    n = len(payload)
    if n < 126:
        header = struct.pack(">BB", b0, 0x80 | n)          # length fits in 7 bits
    elif n <= 0xFFFF:
        header = struct.pack(">BBH", b0, 0x80 | 126, n)    # 126 -> 16-bit length
    else:
        header = struct.pack(">BBQ", b0, 0x80 | 127, n)    # 127 -> 64-bit length
    # Client->server payloads MUST be masked: XOR each byte with the key,
    # cycling the 4-byte key (RFC 6455 §5.3).
    masked = bytes(b ^ masking_key[i % 4] for i, b in enumerate(payload))
    return header + masking_key + masked


def parse_frame(frame: bytes) -> Dict[str, object]:
    """Decode a frame into its fields; XOR-unmask the payload if the MASK bit is set."""
    b0, b1 = struct.unpack(">BB", frame[:2])
    fin = (b0 & 0x80) >> 7          # top bit of byte 0
    opcode = b0 & 0x0F              # low 4 bits of byte 0
    masked = (b1 & 0x80) >> 7       # top bit of byte 1
    length = b1 & 0x7F              # low 7 bits of byte 1
    offset = 2
    if length == 126:              # extended length lives in the next 2 bytes
        (length,) = struct.unpack(">H", frame[offset:offset + 2])
        offset += 2
    elif length == 127:            # ...or the next 8 bytes for huge frames
        (length,) = struct.unpack(">Q", frame[offset:offset + 8])
        offset += 8
    masking_key = b""
    if masked:
        masking_key = frame[offset:offset + 4]
        offset += 4
    data = frame[offset:offset + length]
    if masked:                     # undo the XOR to recover the plaintext bytes
        data = bytes(b ^ masking_key[i % 4] for i, b in enumerate(data))
    return {
        "fin": fin,
        "opcode": opcode,
        "masked": masked,
        "payload_len": length,
        "masking_key": masking_key,
        "payload": data,
    }


def main() -> None:
    # --- 1) The handshake value ----------------------------------------------
    # This exact key/accept pair is the worked example in RFC 6455 §1.3.
    sample_key = "dGhlIHNhbXBsZSBub25jZQ=="
    accept = compute_accept(sample_key)
    print("WebSocket handshake (RFC 6455 §1.3):")
    print(f"  Sec-WebSocket-Key ...... {sample_key}")
    print(f"  Sec-WebSocket-Accept ... {accept}")
    assert accept == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=", "must match the RFC 6455 example"
    print("  matches the value published in RFC 6455.")

    # --- 2) Round-trip a masked text frame -----------------------------------
    message = "hello, full-duplex world".encode("utf-8")
    masking_key = os.urandom(4)  # a real client picks a fresh random key per frame
    frame = build_masked_text_frame(message, masking_key)
    print()
    print(f"Built a masked text frame: {len(frame)} bytes on the wire")
    print(f"  raw bytes .............. {frame.hex()}")

    decoded = parse_frame(frame)
    print("Parsed it back:")
    print(f"  FIN .................... {decoded['fin']}")
    print(f"  opcode ................. {decoded['opcode']:#04x} (0x1 = text)")
    print(f"  MASK ................... {decoded['masked']}")
    print(f"  payload length ......... {decoded['payload_len']} bytes")
    print(f"  masking key ............ {decoded['masking_key'].hex()}")  # type: ignore[union-attr]
    print(f"  payload ................ {decoded['payload'].decode('utf-8')!r}")  # type: ignore[union-attr]

    assert decoded["payload"] == message, "unmasking must recover the original bytes"
    print()
    print("[done] handshake computed and frame round-tripped byte-for-byte.")


if __name__ == "__main__":
    main()
