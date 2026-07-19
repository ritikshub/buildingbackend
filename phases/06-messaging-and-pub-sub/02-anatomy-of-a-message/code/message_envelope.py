#!/usr/bin/env python3
"""
The anatomy of a message: envelope, payload, and the serialization decision.

Companion to docs/en.md (Phase 6, Lesson 02 - Anatomy of a Message). Builds the
thing a broker actually carries, encodes it three ways by hand, and measures
every claim: the naive path failing, an annotated hex dump per format, size and
CPU and compression across a 4,000-event order corpus, the correlation-vs-
causation tree, the claim-check pattern, and the messages validation must reject.

Sources: RFC 4122 (UUID), W3C Trace Context Level 1, CloudEvents 1.0,
RFC 8949 (CBOR), the Protocol Buffers encoding spec.
Standard library only, seeded, deterministic:  python message_envelope.py
"""

from __future__ import annotations

import base64
import hashlib
import json
import pickle
import random
import struct
import time
import uuid
import zlib
from dataclasses import dataclass

SEED = 20260718
EPOCH_US = 1_750_000_000_000_000       # fixed clock base so output never drifts
N_EVENTS = 4_000
GB = 1024 ** 3
BROKER_MAX_BYTES = 262_144             # SQS's 256 KiB ceiling, the tightest common limit
SUPPORTED_VERSIONS = (1, 2)            # what THIS consumer can parse

ALLOWED_CONTENT_TYPES = {"application/json", "application/msgpack",
                         "application/vnd.shop.order.v1+binary",
                         "application/vnd.shop.claimcheck.v1+json"}
ALLOWED_ENCODINGS = {"identity", "deflate"}

# Dictionaries the schema-ful binary format may assume both sides hold.
# This is precisely what a schema registry buys you (lesson 12).
TYPE_IDS = {"com.shop.order.placed": 1, "com.shop.payment.authorized": 2,
            "com.shop.inventory.reserved": 3, "com.shop.shipment.requested": 4,
            "com.shop.receipt.emailed": 5, "com.shop.checkout.requested": 6}
SOURCE_IDS = {"urn:svc:orders": 1, "urn:svc:payments": 2, "urn:svc:inventory": 3,
              "urn:svc:shipping": 4, "urn:svc:notifications": 5, "urn:svc:web-bff": 6}
CT_IDS = {ct: i + 1 for i, ct in enumerate(sorted(ALLOWED_CONTENT_TYPES))}
ENC_IDS = {"identity": 0, "deflate": 1}
CURRENCY_IDS, STATUS_IDS = {"EUR": 1, "USD": 2, "GBP": 3}, {"placed": 1, "authorized": 2}
CHANNEL_IDS = {"web": 1, "ios": 2, "android": 3, "partner-api": 4}
_rev = lambda d: {v: k for k, v in d.items()}                                # noqa: E731
TYPE_BY_ID, SOURCE_BY_ID, CT_BY_ID, ENC_BY_ID = map(_rev, (TYPE_IDS, SOURCE_IDS, CT_IDS, ENC_IDS))
CUR_BY_ID, STATUS_BY_ID, CHANNEL_BY_ID = map(_rev, (CURRENCY_IDS, STATUS_IDS, CHANNEL_IDS))


class EnvelopeError(ValueError):
    """Raised when a message cannot be trusted. Never partially applied."""


# ─── varint + Protobuf-style framing (Protocol Buffers encoding spec) ────────

def uvarint(n: int) -> bytes:
    out = bytearray()
    while True:
        b, n = n & 0x7F, n >> 7
        out.append(b | 0x80 if n else b)
        if not n:
            return bytes(out)


def read_uvarint(buf: bytes, i: int) -> tuple[int, int]:
    n = shift = 0
    while True:
        b, i = buf[i], i + 1
        n |= (b & 0x7F) << shift
        if not b & 0x80:
            return n, i
        shift += 7


# wire types: 0 = varint, 2 = length-delimited, 5 = fixed32
def bvar(f: int, n: int) -> bytes:
    return uvarint(f << 3) + uvarint(n)


def bbytes(f: int, b: bytes) -> bytes:
    return uvarint(f << 3 | 2) + uvarint(len(b)) + b


def bfix32(f: int, n: int) -> bytes:
    return uvarint(f << 3 | 5) + struct.pack("<I", n)


# ─── MessagePack subset: self-describing binary, written by hand ─────────────

def mp_pack(o) -> bytes:
    if o is None or o is True or o is False:
        return {None: b"\xc0", False: b"\xc2", True: b"\xc3"}[o]
    if isinstance(o, int):
        for lim, pre, w in ((0x80, b"", 0), (0x100, b"\xcc", 1), (0x10000, b"\xcd", 2),
                            (1 << 32, b"\xce", 4), (1 << 64, b"\xcf", 8)):
            if 0 <= o < lim:
                return bytes([o]) if not w else pre + o.to_bytes(w, "big")
        raise ValueError(f"integer out of MessagePack range: {o}")
    if isinstance(o, str):
        b = o.encode()
        return (bytes([0xA0 | len(b)]) if len(b) < 32 else
                b"\xd9" + bytes([len(b)]) if len(b) < 256 else
                b"\xda" + len(b).to_bytes(2, "big")) + b
    if isinstance(o, (bytes, bytearray)):
        n = len(o)
        return (b"\xc4" + bytes([n]) if n < 256 else b"\xc5" + n.to_bytes(2, "big")) + bytes(o)
    if isinstance(o, (list, dict)):
        lo, hi, n = (0x90, b"\xdc", len(o)) if isinstance(o, list) else (0x80, b"\xde", len(o))
        head = bytes([lo | n]) if n < 16 else hi + n.to_bytes(2, "big")
        body = (b"".join(mp_pack(x) for x in o) if isinstance(o, list) else
                b"".join(mp_pack(k) + mp_pack(v) for k, v in o.items()))
        return head + body
    raise TypeError(type(o))


def mp_unpack(buf: bytes, i: int = 0):
    """Self-describing: the type is in the leading byte, so no schema is needed."""
    c, i = buf[i], i + 1
    if c < 0x80:                                            # positive fixint
        return c, i
    if 0xA0 <= c <= 0xBF:                                   # fixstr
        n = c & 0x1F
        return buf[i:i + n].decode(), i + n
    if 0x80 <= c <= 0x9F:                                   # fixmap / fixarray
        return _mp_seq(buf, i, c & 0x0F, c < 0x90)
    if c in (0xC0, 0xC2, 0xC3):
        return {0xC0: None, 0xC2: False, 0xC3: True}[c], i
    if w := {0xCC: 1, 0xCD: 2, 0xCE: 4, 0xCF: 8}.get(c):    # uint8 .. uint64
        return int.from_bytes(buf[i:i + w], "big"), i + w
    if c in (0xC4, 0xC5, 0xD9, 0xDA, 0xDC, 0xDE):           # counted str/bin/array/map
        w = 1 if c in (0xC4, 0xD9) else 2
        n, i = int.from_bytes(buf[i:i + w], "big"), i + w
        if c in (0xC4, 0xC5):
            return buf[i:i + n], i + n
        if c in (0xD9, 0xDA):
            return buf[i:i + n].decode(), i + n
        return _mp_seq(buf, i, n, c == 0xDE)
    raise EnvelopeError(f"messagepack: unknown type byte 0x{c:02x}")


def _mp_seq(buf: bytes, i: int, n: int, is_map: bool):
    out: dict | list = {} if is_map else []
    for _ in range(n):
        k, i = mp_unpack(buf, i)
        if is_map:
            v, i = mp_unpack(buf, i)
            out[k] = v
        else:
            out.append(k)
    return out, i


# ─── the order payload — the business fact ──────────────────────────────────

def order_json(p: dict) -> bytes:
    return json.dumps(p, sort_keys=True, separators=(",", ":")).encode()


def item_binary(it: dict) -> bytes:
    return bbytes(1, it["sku"].encode()) + bvar(2, it["qty"]) + bvar(3, it["unit_minor"])


def order_binary(p: dict) -> bytes:
    """Schema-ful: field numbers replace names, enums replace strings, a UUID is 16 bytes."""
    return (bbytes(1, uuid.UUID(p["order_id"]).bytes) + bvar(2, p["customer_id"])
            + bvar(3, CURRENCY_IDS[p["currency"]]) + bvar(4, STATUS_IDS[p["status"]])
            + bvar(5, CHANNEL_IDS[p["channel"]]) + bvar(6, p["amount_minor"])
            + b"".join(bbytes(7, item_binary(it)) for it in p["items"]))


def _scan(b: bytes):
    """Walk Protobuf-framed bytes, yielding (field_number, value) with value already unframed."""
    i = 0
    while i < len(b):
        key, i = read_uvarint(b, i)
        f, wire = key >> 3, key & 7
        if wire == 2:
            n, i = read_uvarint(b, i)
            yield f, b[i:i + n]
            i += n
        elif wire == 5:
            yield f, struct.unpack_from("<I", b, i)[0]
            i += 4
        else:
            v, i = read_uvarint(b, i)
            yield f, v


def order_binary_decode(b: bytes) -> dict:
    names = {2: "customer_id", 6: "amount_minor"}
    enums = {3: ("currency", CUR_BY_ID), 4: ("status", STATUS_BY_ID),
             5: ("channel", CHANNEL_BY_ID)}
    p: dict = {"items": []}
    for f, v in _scan(b):
        if f == 1:
            p["order_id"] = str(uuid.UUID(bytes=v))
        elif f == 7:
            p["items"].append({k: w for k, w in _item_fields(v)})
        elif f in enums:
            name, table = enums[f]
            p[name] = table[v]
        else:
            p[names[f]] = v
    return p


def _item_fields(b: bytes):
    for f, v in _scan(b):
        yield {1: "sku", 2: "qty", 3: "unit_minor"}[f], v.decode() if f == 1 else v


# ─── the envelope ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Envelope:
    """Infrastructure metadata. The broker reads this; it never opens the body."""
    message_id: str            # RFC 4122 UUID - the dedup key (lesson 06)
    correlation_id: str        # the whole business transaction
    causation_id: str | None   # the IMMEDIATE parent message. Not the same thing.
    type: str                  # what happened, reverse-DNS
    schema_version: int        # of the BODY, not of the envelope
    source: str                # who published it
    occurred_at: int           # event time - when the fact happened, in micros
    published_at: int          # processing time - when the producer sent it
    recorded_at: int | None    # when the BROKER durably accepted it. Broker-stamped.
    content_type: str          # how to parse the body
    content_encoding: str      # identity | deflate
    traceparent: str           # W3C Trace Context: the async hop stays in the trace
    partition_key: str         # ordering scope (lesson 07)
    body: bytes                # opaque to everything above

    @property
    def crc32(self) -> int:
        return zlib.crc32(self.body)

    def fields(self) -> dict:
        return {**{k: getattr(self, k) for k in self.__dataclass_fields__}, "crc32": self.crc32}

    def validate(self) -> None:
        """Everything checkable without parsing the body. Cheap, and a security boundary."""
        for f in ("message_id", "correlation_id", "type", "source",
                  "content_type", "content_encoding", "partition_key"):
            if not getattr(self, f):
                raise EnvelopeError(f"missing required envelope field: {f}")
        for f in ("message_id", "correlation_id", "causation_id"):
            v = getattr(self, f)
            if v is None:
                continue
            try:
                u = uuid.UUID(v)
            except (ValueError, AttributeError):
                raise EnvelopeError(f"{f} is not an RFC 4122 UUID: {v!r}") from None
            if u.variant != uuid.RFC_4122:
                raise EnvelopeError(f"{f} is a UUID but not the RFC 4122 variant")
        if self.content_type not in ALLOWED_CONTENT_TYPES:
            raise EnvelopeError(f"content_type not on the allowlist: {self.content_type!r}")
        if self.content_encoding not in ALLOWED_ENCODINGS:
            raise EnvelopeError(f"unknown content_encoding: {self.content_encoding!r}")
        if self.schema_version not in SUPPORTED_VERSIONS:
            raise EnvelopeError(
                f"schema_version {self.schema_version} outside supported {SUPPORTED_VERSIONS}")
        if self.published_at < self.occurred_at:
            raise EnvelopeError("published_at precedes occurred_at: clock skew or a forged event")
        if len(self.body) > BROKER_MAX_BYTES:
            raise EnvelopeError(
                f"body {len(self.body):,} B exceeds broker limit {BROKER_MAX_BYTES:,} B")


ENV_TAGS = {"message_id": 1, "correlation_id": 2, "causation_id": 3, "type": 4,
            "schema_version": 5, "source": 6, "occurred_at": 7, "published_at": 8,
            "recorded_at": 9, "content_type": 10, "content_encoding": 11,
            "traceparent": 12, "partition_key": 13, "crc32": 14, "body": 15}


def _finish(d: dict, crc: int | None) -> Envelope:
    missing = set(Envelope.__dataclass_fields__) - set(d)
    if missing:
        raise EnvelopeError(f"missing required envelope field: {sorted(missing)[0]}")
    e = Envelope(**{k: d[k] for k in Envelope.__dataclass_fields__})
    e.validate()
    if crc is not None and crc != e.crc32:
        raise EnvelopeError(f"crc32 mismatch: declared {crc}, computed {e.crc32}")
    return e


def enc_json(e: Envelope) -> bytes:
    d = e.fields()
    d["body"] = (json.loads(e.body) if e.content_type.endswith("json")
                 else base64.b64encode(e.body).decode())   # JSON cannot carry bytes: +33%
    return json.dumps(d, sort_keys=True, separators=(",", ":")).encode()


def dec_json(b: bytes) -> Envelope:
    try:
        d = json.loads(b)
    except json.JSONDecodeError as ex:
        raise EnvelopeError(f"not valid JSON: {ex.msg}") from None
    if not isinstance(d, dict):
        raise EnvelopeError("top-level message is not an object")
    body = d.get("body")
    d["body"] = order_json(body) if isinstance(body, dict) else base64.b64decode(body or b"")
    return _finish(d, d.pop("crc32", None))


def enc_msgpack(e: Envelope) -> bytes:
    return mp_pack(e.fields())          # body is already bytes -> a native bin8/bin16 header


def dec_msgpack(b: bytes) -> Envelope:
    d, _ = mp_unpack(b)
    return _finish(d, d.pop("crc32", None))


def enc_binary_parts(e: Envelope) -> dict[str, bytes]:
    """Every field's exact bytes, so the size table can be per-field rather than a total."""
    tp = e.traceparent.split("-")
    return {
        "message_id": bbytes(1, uuid.UUID(e.message_id).bytes),
        "correlation_id": bbytes(2, uuid.UUID(e.correlation_id).bytes),
        "causation_id": bbytes(3, uuid.UUID(e.causation_id).bytes) if e.causation_id else b"",
        "type": bvar(4, TYPE_IDS[e.type]),
        "schema_version": bvar(5, e.schema_version),
        "source": bvar(6, SOURCE_IDS[e.source]),
        "occurred_at": bvar(7, e.occurred_at),
        "published_at": bvar(8, e.published_at - e.occurred_at),      # delta: micros, not an epoch
        "recorded_at": bvar(9, (e.recorded_at or e.published_at) - e.published_at),
        "content_type": bvar(10, CT_IDS[e.content_type]),
        "content_encoding": bvar(11, ENC_IDS[e.content_encoding]),
        # 55 ASCII chars -> 26 raw bytes: version, trace-id, parent-id, flags
        "traceparent": bbytes(12, bytes([int(tp[0], 16)]) + bytes.fromhex(tp[1])
                              + bytes.fromhex(tp[2]) + bytes([int(tp[3], 16)])),
        "partition_key": bbytes(13, e.partition_key.encode()),
        "crc32": bfix32(14, e.crc32),
        "body": bbytes(15, e.body),
    }


def enc_binary(e: Envelope) -> bytes:
    return b"".join(enc_binary_parts(e).values())


_B_UUID = {1: "message_id", 2: "correlation_id", 3: "causation_id"}
_B_ENUM = {4: ("type", TYPE_BY_ID), 6: ("source", SOURCE_BY_ID),
           10: ("content_type", CT_BY_ID), 11: ("content_encoding", ENC_BY_ID)}
_B_DELTA = {8: ("published_at", "occurred_at"), 9: ("recorded_at", "published_at")}
_B_PLAIN = {5: "schema_version", 7: "occurred_at"}


def dec_binary(b: bytes) -> Envelope:
    d: dict = {"causation_id": None, "recorded_at": None}
    crc = None
    for f, v in _scan(b):
        if f in _B_UUID:
            d[_B_UUID[f]] = str(uuid.UUID(bytes=v))
        elif f == 12:
            d["traceparent"] = "%02x-%s-%s-%02x" % (v[0], v[1:17].hex(), v[17:25].hex(), v[25])
        elif f == 13:
            d["partition_key"] = v.decode()
        elif f == 15:
            d["body"] = v
        elif f == 14:
            crc = v
        elif f in _B_ENUM:
            name, table = _B_ENUM[f]
            d[name] = table[v]
        elif f in _B_DELTA:
            name, base = _B_DELTA[f]
            d[name] = d[base] + v
        else:
            d[_B_PLAIN[f]] = v
    return _finish(d, crc)


CODECS = {"json": (enc_json, dec_json, "application/json"),
          "msgpack": (enc_msgpack, dec_msgpack, "application/msgpack"),
          "binary": (enc_binary, dec_binary, "application/vnd.shop.order.v1+binary")}
SKUS = ["AX-1042", "BK-2210", "CT-0071", "DM-9930", "EP-3318", "FR-5502", "GN-8814", "HQ-2065"]


def make_corpus(n: int) -> list[tuple[dict, dict]]:
    """(envelope kwargs, payload) pairs, format-independent: all three encode the same facts."""
    rnd, out = random.Random(SEED), []
    uid = lambda: str(uuid.UUID(bytes=rnd.randbytes(16), version=4))          # noqa: E731
    for i in range(n):
        items = [{"sku": rnd.choice(SKUS), "qty": rnd.randrange(1, 5),
                  "unit_minor": rnd.randrange(499, 24_999)} for _ in range(rnd.randrange(1, 6))]
        occurred = EPOCH_US + i * 1_200 + rnd.randrange(0, 900)
        out.append((
            {"message_id": uid(), "correlation_id": uid(), "causation_id": uid(),
             "type": "com.shop.order.placed", "schema_version": 1,
             "source": "urn:svc:orders", "occurred_at": occurred,
             "published_at": occurred + rnd.randrange(300, 4_000),
             "recorded_at": occurred + rnd.randrange(4_100, 9_000),
             "traceparent": "00-%s-%s-01" % (rnd.randbytes(16).hex(), rnd.randbytes(8).hex()),
             "partition_key": "c_%06d" % rnd.randrange(1, 250_000),
             "content_encoding": "identity"},
            {"order_id": uid(), "customer_id": rnd.randrange(1, 250_000),
             "currency": rnd.choice(list(CURRENCY_IDS)), "status": "placed",
             "channel": rnd.choice(list(CHANNEL_IDS)),
             "amount_minor": sum(it["qty"] * it["unit_minor"] for it in items),
             "items": items}))
    return out


def build(kw: dict, payload: dict, fmt: str) -> Envelope:
    """Same business fact, native body per format. content_type says which."""
    body = {"binary": order_binary, "msgpack": mp_pack}.get(fmt, order_json)(payload)
    return Envelope(**kw, content_type=CODECS[fmt][2], body=body)


# ─── reporting helpers ──────────────────────────────────────────────────────

def dump(data: bytes, regions: list[tuple[int, str]], indent: str = "    ") -> None:
    """Hex + ASCII, wrapped at 8 bytes, with the note on each region's first row."""
    off = 0
    for length, note in regions:
        chunk = data[off:off + length]
        for k in range(0, max(len(chunk), 1), 8):
            row = chunk[k:k + 8]
            print(f"{indent}{off + k:04x}  {' '.join(f'{b:02x}' for b in row):<23}  "
                  f"{''.join(chr(b) if 32 <= b < 127 else '.' for b in row):<8}  "
                  f"{note if k == 0 else ''}".rstrip())
        off += length


def bench(fn, arg, repeats: int = 5) -> float:
    """Best-of-N wall time: the least noisy estimator available here."""
    return min(((lambda t0: (fn(arg), time.perf_counter() - t0)[1])(time.perf_counter())
                for _ in range(repeats)))




_RAN: list[int] = []


def _side_effect() -> str:
    _RAN.append(1)
    return "looks like an innocent string"


class LooksLikeAnOrder:
    def __reduce__(self):
        return (_side_effect, ())      # pickle.loads() will CALL this. That is the whole bug.


# ─── main ───────────────────────────────────────────────────────────────────

def main() -> None:
    corpus = make_corpus(N_EVENTS)
    kw0, pay0 = corpus[0]

    print("== 1. THE NAIVE PATH: three ways to fail before you start ==")
    naive = {"order_id": pay0["order_id"], "amount_minor": pay0["amount_minor"],
             "paid": True, "coupon": None}
    s = str(naive)
    print(f"  str(dict)     {len(s):>7,} B   {s[:58]}...")
    try:
        json.loads(s)
    except json.JSONDecodeError as ex:
        print(f"  -> another language parses it as JSON: FAILS ({ex.msg} at col {ex.colno})")
    print("     single quotes, True/None instead of true/null. It is Python's repr, not a format.")
    pk = pickle.dumps(naive)
    print(f"  pickle        {len(pk):>7,} B   opcodes {pk[:12].hex(' ')} ...")
    print(f"  -> {len(pk) - len(order_json(naive)):+,} B vs JSON, and unreadable outside Python")
    exploit = pickle.dumps(LooksLikeAnOrder())
    pickle.loads(exploit)              # the whole point: deserializing IS executing
    print(f"  pickle RCE    {len(exploit):>7,} B   a {len(exploit)}-byte 'message' whose "
          f"__reduce__ ran on load: executed={len(_RAN)}")
    print("     pickle.loads() on attacker-influenced bytes is remote code execution, always.")
    print("  and none of the three carry: message_id, timestamp, type, schema_version, traceparent")
    print("     -> a retry double-charges, a replay looks live, the consumer guesses, the first")
    print("        schema change breaks every consumer, and the async hop leaves no trace.")

    print("\n== 2. THE ENVELOPE: 15 fields, each one a failure that cannot happen ==")
    env = build(kw0, pay0, "binary")
    env.validate()
    why = {
        "message_id": "dedup key: a redelivery is recognised, not re-charged",
        "correlation_id": "one id for the whole business transaction",
        "causation_id": "the IMMEDIATE parent - gives a causal tree, not just a bag",
        "type": "the consumer routes on this without opening the body",
        "schema_version": "of the BODY; lets old and new consumers coexist",
        "source": "who to page when the payload is wrong",
        "occurred_at": "EVENT time: when the fact happened in the world",
        "published_at": "PROCESSING time: when the producer sent it. Skew lives here.",
        "recorded_at": "when the broker durably accepted it. Broker-stamped.",
        "content_type": "how to parse the body - checked BEFORE parsing it",
        "content_encoding": "identity | deflate",
        "traceparent": "W3C Trace Context, so the async hop is not a black hole",
        "partition_key": "ordering scope (lesson 07)",
        "crc32": "corruption and truncation are detected, not applied",
        "body": "the business fact. Opaque to the broker.",
    }
    for k, v in why.items():
        val = env.fields()[k]
        shown = f"<{len(val):,} B>" if isinstance(val, bytes) else str(val)
        print(f"  {k:<17} {shown[:40]:<40} {v}")

    print("\n== 3. THE SAME BYTES, THREE WAYS ==")
    it = pay0["items"][0]
    sku, qty, unit = it["sku"], it["qty"], it["unit_minor"]
    print(f"  one line item: sku={sku!r} qty={qty} unit_minor={unit}")
    j = order_json(it)
    r1, r2 = len(f'{{"qty":{qty},'), len(f'"sku":"{sku}",')
    print(f"  a) JSON  {len(j):>3} B  self-describing text, no schema needed")
    dump(j, [(r1, 'the name "qty" costs 6 B to carry 1 digit'),
             (r2, 'the name "sku" costs 6 B; the value needs quotes too'),
             (len(j) - r1 - r2, 'the name "unit_minor" costs 13 B to carry 5 digits')])
    m = mp_pack({"qty": qty, "sku": sku, "unit_minor": unit})
    print(f"  b) MessagePack-style {len(m):>3} B  self-describing binary (CBOR family, RFC 8949)")
    dump(m, [(1, "0x83 = fixmap, 3 pairs follow"),
             (4, "0xa3 = fixstr(3), then 'qty'"),
             (len(mp_pack(qty)), f"positive fixint = {qty} (1 byte, not 1 char)"),
             (4, "0xa3 'sku'"), (1 + len(sku), f"0xa{len(sku):x} fixstr({len(sku)}) '{sku}'"),
             (11, "0xaa fixstr(10) 'unit_minor'"),
             (len(mp_pack(unit)), f"0xcd = uint16, then {unit} big-endian")])
    b = item_binary(it)
    print(f"  c) schema-ful binary {len(b):>3} B  field NUMBERS, not names (Protobuf wire format)")
    dump(b, [(1, "tag 0x0a = field 1 (sku) << 3 | wire 2"), (1, f"length {len(sku)}"),
             (len(sku), f"'{sku}' - no field name on the wire at all"),
             (1, "tag 0x10 = field 2 (qty) << 3 | wire 0"), (len(uvarint(qty)), f"varint {qty}"),
             (1, "tag 0x18 = field 3 (unit_minor)"),
             (len(uvarint(unit)), f"varint {unit} in {len(uvarint(unit))} bytes, 7 bits each")])
    print(f"  field names cost {len(j) - len(b)} of JSON's {len(j)} bytes here "
          f"({100 * (len(j) - len(b)) / len(j):.0f}%). Multiply by every message, forever.")

    print("\n== 3b. THE ENVELOPE, FIELD BY FIELD (bytes on the wire) ==")
    e_js, e_mp = build(kw0, pay0, "json"), build(kw0, pay0, "msgpack")
    ej, em, eb = enc_json(e_js), enc_msgpack(e_mp), enc_binary(env)
    parts, jd, md = enc_binary_parts(env), json.loads(ej), mp_unpack(em)[0]
    notes = {"message_id": "36-char UUID text -> 16 raw bytes", "correlation_id": "same",
             "causation_id": "same", "schema_version": "small int",
             "type": "reverse-DNS string -> 1-byte registry id",
             "source": "URN string -> 1-byte registry id",
             "occurred_at": "varint micros beats 16 ASCII digits",
             "published_at": "DELTA from occurred_at: micros, not an epoch",
             "recorded_at": "delta from published_at", "content_encoding": "enum",
             "content_type": "MIME string -> registry id",
             "traceparent": "55 ASCII chars -> 26 raw bytes",
             "partition_key": "short string, nothing to win", "crc32": "fixed32",
             "body": "the order itself, natively encoded"}
    print(f"  {'field':<17} {'json':>7} {'msgpk':>7} {'binary':>7}   what the schema buys")
    for k in ENV_TAGS:
        jc = len(json.dumps({k: jd.get(k)}, separators=(",", ":"))) - 1
        print(f"  {k:<17} {jc:>7,} {len(mp_pack(k)) + len(mp_pack(md.get(k))):>7,}"
              f" {len(parts[k]):>7,}   {notes[k]}")
    jbody = len(json.dumps(jd["body"], separators=(",", ":")))
    print(f"  {'TOTAL ON WIRE':<17} {len(ej):>7,} {len(em):>7,} {len(eb):>7,}")
    print(f"  {'of which body':<17} {jbody:>7,} {len(md['body']):>7,} {len(env.body):>7,}")
    print(f"  {'ENVELOPE ONLY':<17} {len(ej) - jbody:>7,} {len(em) - len(md['body']):>7,}"
          f" {len(eb) - len(env.body):>7,}   metadata is "
          f"{(len(ej) - jbody) / (len(eb) - len(env.body)):.1f}x cheaper with a schema")
    print("  (each column carries its own native body and content_type, hence the body rows differ)")

    print(f"\n== 4. THE CORPUS: {N_EVENTS:,} order events, measured ==")
    encoded: dict[str, list[bytes]] = {}
    timing: dict[str, tuple[float, float]] = {}
    for fmt, (enc, dec, _ct) in CODECS.items():
        envs = [build(kw, p, fmt) for kw, p in corpus]
        blobs = [enc(e) for e in envs]
        encoded[fmt] = blobs
        timing[fmt] = (bench(lambda es: [enc(x) for x in es], envs),
                       bench(lambda bs: [dec(x) for x in bs], blobs))
    base, (bte, btd) = sum(map(len, encoded["json"])), timing["json"]
    print(f"  {'format':<9} {'total':>11} {'avg':>6} {'vs json':>9} {'bytes saved/msg':>17}"
          f" {'at 5k msg/s':>14}")
    for fmt, blobs in encoded.items():
        total, avg = sum(map(len, blobs)), sum(map(len, blobs)) / len(blobs)
        print(f"  {fmt:<9} {total:>9,} B {avg:>6.0f} {100 * total / base:>8.1f}%"
              f" {(base - total) / len(blobs):>15.0f} B {avg * 5_000 * 86_400 / GB:>11.0f} GB/d")
    # Wall-clock ratios wobble a few percent per run, so report a band, not a false precision.
    worst = max(max(te / bte, td / btd) for te, td in timing.values())
    print(f"  CPU: every encode and decode landed within {'1.5x' if worst < 1.5 else f'{worst:.1f}x'}"
          f" of the json baseline (best of 5 over {N_EVENTS:,}")
    print("  messages), so a 4x size win cost essentially no CPU. Note the handicap, though:")
    print("  `json` is C inside CPython and our binary codec is interpreted Python. Format and")
    print("  implementation are different variables; a compiled Protobuf moves binary well ahead.")
    rt = order_binary_decode(dec_binary(encoded["binary"][7]).body)
    print(f"  round-trip: binary msg 7 -> same order_id {rt['order_id'] == corpus[7][1]['order_id']}"
          f", same amount {rt['amount_minor'] == corpus[7][1]['amount_minor']}"
          f", same items {rt['items'] == corpus[7][1]['items']}")

    print("\n== 5. COMPRESSION: per message vs per batch ==")
    print(f"  {'format':<9} {'raw':>11} {'per-message':>19} {'per-batch-of-100':>21}"
          f" {'whole corpus':>19}")
    for fmt, blobs in encoded.items():
        raw = sum(map(len, blobs))
        one = sum(len(zlib.compress(x, 6)) for x in blobs)
        hundred = sum(len(zlib.compress(b"".join(blobs[i:i + 100]), 6))
                      for i in range(0, len(blobs), 100))
        whole = len(zlib.compress(b"".join(blobs), 6))
        print(f"  {fmt:<9} {raw:>9,} B {one:>11,} B {raw / one:>5.2f}x {hundred:>13,} B"
              f" {raw / hundred:>5.2f}x {whole:>11,} B {raw / whole:>5.2f}x")
    jb = encoded["json"]
    one_j = sum(len(zlib.compress(x, 6)) for x in jb)
    hun_j = sum(len(zlib.compress(b"".join(jb[i:i + 100]), 6)) for i in range(0, len(jb), 100))
    print(f"  batching 100 JSON messages beats compressing them one by one by {one_j / hun_j:.2f}x"
          f" - repetition ACROSS messages is where the entropy savings live")
    small = encoded["binary"][0]
    print(f"  a single {len(small)} B binary message zlibs to {len(zlib.compress(small, 6))} B:"
          f" the header and empty dictionary cost more than they save")
    b64 = base64.b64encode(env.body)
    print(f"  base64 tax: the {len(env.body)} B binary body becomes {len(b64)} B inside a JSON"
          f" string (+{100 * len(b64) / len(env.body) - 100:.0f}%) - JSON cannot carry bytes")

    print("\n== 6. CORRELATION vs CAUSATION: reconstructing the causal tree ==")
    rnd = random.Random(SEED + 7)
    uid = lambda: str(uuid.UUID(bytes=rnd.randbytes(16), version=4))          # noqa: E731
    corr = uid()
    chain = [("com.shop.checkout.requested", "urn:svc:web-bff", None),
             ("com.shop.order.placed", "urn:svc:orders", 0),
             ("com.shop.payment.authorized", "urn:svc:payments", 1),
             ("com.shop.inventory.reserved", "urn:svc:inventory", 1),
             ("com.shop.shipment.requested", "urn:svc:shipping", 2),
             ("com.shop.receipt.emailed", "urn:svc:notifications", 2)]
    msgs: list[dict] = []
    for i, (typ, src, parent) in enumerate(chain):
        msgs.append({"message_id": uid(), "type": typ, "source": src, "correlation_id": corr,
                     "causation_id": msgs[parent]["message_id"] if parent is not None else None,
                     "occurred_at": EPOCH_US + i * 41_000})
    print(f"  correlation_id {corr}  <- identical on all {len(msgs)} messages")
    kids: dict = {}
    for m in msgs:
        kids.setdefault(m["causation_id"], []).append(m)

    def walk(pid, depth=0):
        for m in kids.get(pid, []):
            lead = "  " + "  " * depth + ("+- " if depth else "")
            print(f"{lead}{m['type']:<{40 - len(lead)}} {m['source']:<22} {m['message_id'][:8]}"
                  f"  t+{(m['occurred_at'] - EPOCH_US) / 1000:.0f}ms")
            walk(m["message_id"], depth + 1)

    walk(None)
    print(f"  correlation alone gives you a BAG of {len(msgs)} messages sharing an id.")
    print("  causation gives you the edges: who caused whom, and where a branch stopped.")
    print(f"  a message whose causation_id {uid()[:8]} names no known message is an ORPHAN - the")
    print("  parent was never published, or was lost. One join is the whole consistency check.")

    print("\n== 7. CLAIM CHECK: a payload the broker will not carry ==")
    rnd2 = random.Random(SEED + 11)
    big_items = [{"sku": rnd2.choice(SKUS), "qty": rnd2.randrange(1, 40),
                  "unit_minor": rnd2.randrange(499, 24_999)} for _ in range(9_000)]
    big = dict(pay0, items=big_items,
               amount_minor=sum(i["qty"] * i["unit_minor"] for i in big_items))
    big_body = order_json(big)
    big_env = Envelope(**kw0, content_type="application/json", body=big_body)
    try:
        big_env.validate()
    except EnvelopeError as ex:
        print(f"  direct publish  {len(enc_json(big_env)):>9,} B  REJECTED: {ex}")
    digest = hashlib.sha256(big_body).hexdigest()
    key = f"s3://shop-msg-payloads/2025/06/{digest[:16]}.json.gz"
    store = {key: zlib.compress(big_body, 6)}
    ticket = {"uri": key, "sha256": digest, "bytes": len(big_body),
              "content_type": "application/json", "content_encoding": "deflate",
              "expires_at": kw0["occurred_at"] + 30 * 86_400 * 1_000_000}
    cc = Envelope(**kw0, content_type="application/vnd.shop.claimcheck.v1+json",
                  body=order_json(ticket))
    cc.validate()
    wire = enc_json(cc)
    print(f"  claim check     {len(wire):>9,} B  a pointer + sha256 + size + expiry")
    print(f"  payload parked in object storage: {len(store[key]):,} B deflated "
          f"({len(big_body) / len(store[key]):.1f}x)")
    print(f"  the message shrank {len(enc_json(big_env)) / len(wire):,.0f}x "
          f"({len(enc_json(big_env)):,} B -> {len(wire):,} B) and now fits every broker")
    fetched = zlib.decompress(store[ticket["uri"]])
    print(f"  consumer fetches, then verifies sha256: "
          f"{hashlib.sha256(fetched).hexdigest() == ticket['sha256']}"
          f"  (without this the pointer is an unvalidated download)")
    print("  the cost: two systems now own one fact. Delete the blob before the message is")
    print("  consumed and it is a dangling pointer; drop the message and the blob leaks.")
    print("  hence expires_at in the ticket, and a lifecycle rule >= retention + DLQ age.")

    print("\n== 8. VALIDATION: six messages that must never reach business logic ==")
    good = json.loads(enc_json(build(kw0, pay0, "json")))
    for label, doc in [
        ("unknown content type", {**good, "content_type": "application/x-python-pickle"}),
        ("missing required field", {k: v for k, v in good.items() if k != "message_id"}),
        ("schema_version from the future", {**good, "schema_version": 9}),
        ("message_id is not a UUID", {**good, "message_id": "order-2291"}),
        ("published before it occurred", {**good, "published_at": good["occurred_at"] - 5_000_000}),
        ("body altered in flight", {**good, "crc32": good["crc32"] ^ 0xFF}),
    ]:
        try:
            dec_json(json.dumps(doc).encode())
            print(f"  {label:<32} ACCEPTED  <- BUG")
        except EnvelopeError as ex:
            print(f"  {label:<32} rejected: {ex}")
    ok = dec_json(enc_json(build(kw0, pay0, "json")))
    print(f"  {'the unmodified message':<32} accepted: type={ok.type} v{ok.schema_version}"
          f", crc ok, {len(ok.body)} B body")
    print("  every reject happened on ENVELOPE fields alone. The body was never parsed.")


if __name__ == "__main__":
    main()
