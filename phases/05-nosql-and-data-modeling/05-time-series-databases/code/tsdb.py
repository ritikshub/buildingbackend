#!/usr/bin/env python3
"""
A mini time-series database with Gorilla-style compression, built from scratch.

Companion to docs/en.md (Phase 04, Lesson 05 - Time-Series Databases). A time
series is a stream of (timestamp, value) points for one identity (a "series").
This engine exploits the three things that make time-series data special, the
same three every production TSDB exploits:

  * Writes are append-only and ordered by time -> store points in time-bucketed,
    immutable CHUNKS. Dropping old data (retention) is then an O(1) drop of a
    whole chunk, not a DELETE of millions of rows.
  * Timestamps arrive at near-constant intervals -> DELTA-OF-DELTA encoding
    turns each one into (usually) a single bit.
  * Consecutive float values are similar -> XOR-with-previous leaves mostly
    zero bits, so only a handful of "meaningful" bits are stored per point.

Delta-of-delta + XOR is the compression scheme from Facebook's Gorilla paper
(Pelkonen et al., "Gorilla: A Fast, Scalable, In-Memory Time Series Database",
VLDB 2015), which also underlies Prometheus's on-disk TSDB. The bit widths here
are lightly simplified for clarity; the ideas are faithful.

Runs standalone on the Python standard library only:  python tsdb.py
"""

from __future__ import annotations
import math
import struct


# ─── Bit-level I/O: a TSDB packs values to the bit, not the byte ──────────────

class BitWriter:
    """Append individual bits; flush to bytes at the end (last byte zero-padded)."""
    def __init__(self):
        self.buf = bytearray()
        self._cur = 0            # the partial byte being filled, MSB-first
        self._nbits = 0          # how many bits of _cur are used (0..7)

    def write_bit(self, bit: int) -> None:
        self._cur = (self._cur << 1) | (bit & 1)
        self._nbits += 1
        if self._nbits == 8:
            self.buf.append(self._cur)
            self._cur, self._nbits = 0, 0

    def write_bits(self, value: int, count: int) -> None:
        for i in range(count - 1, -1, -1):       # most-significant bit first
            self.write_bit((value >> i) & 1)

    def to_bytes(self) -> bytes:                 # non-mutating: safe to call repeatedly
        out = bytearray(self.buf)
        if self._nbits:
            out.append(self._cur << (8 - self._nbits))
        return bytes(out)


class BitReader:
    """Read bits back in the order BitWriter wrote them."""
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0                              # bit position

    def read_bit(self) -> int:
        byte = self.data[self.pos >> 3]
        bit = (byte >> (7 - (self.pos & 7))) & 1
        self.pos += 1
        return bit

    def read_bits(self, count: int) -> int:
        v = 0
        for _ in range(count):
            v = (v << 1) | self.read_bit()
        return v


def _sign_extend(v: int, bits: int) -> int:
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


# ─── Timestamp compression: delta-of-delta ───────────────────────────────────
# A regular interval (say every 1s) gives a constant delta, so the *change in
# the delta* (the "delta of delta") is 0 -> one bit. An occasional jitter costs
# a few more. Written with a variable-length prefix so the common case is tiny.

def _encode_dod(w: BitWriter, dod: int) -> None:
    if dod == 0:
        w.write_bit(0)                                        # '0'          most common
    elif -64 <= dod <= 63:
        w.write_bits(0b10, 2);  w.write_bits(dod & 0x7F, 7)   # '10'  + 7 bits
    elif -256 <= dod <= 255:
        w.write_bits(0b110, 3); w.write_bits(dod & 0x1FF, 9)  # '110' + 9 bits
    elif -2048 <= dod <= 2047:
        w.write_bits(0b1110, 4); w.write_bits(dod & 0xFFF, 12)  # '1110' + 12 bits
    else:
        w.write_bits(0b1111, 4); w.write_bits(dod & 0xFFFFFFFF, 32)  # '1111' + 32 bits


def _decode_dod(r: BitReader) -> int:
    if r.read_bit() == 0:
        return 0
    if r.read_bit() == 0:
        return _sign_extend(r.read_bits(7), 7)
    if r.read_bit() == 0:
        return _sign_extend(r.read_bits(9), 9)
    if r.read_bit() == 0:
        return _sign_extend(r.read_bits(12), 12)
    return _sign_extend(r.read_bits(32), 32)


# ─── Value compression: XOR with the previous value ──────────────────────────
# Two similar float64s share their sign, exponent and high mantissa bits, so
# their XOR has long runs of leading and trailing zeros. Store only the
# "meaningful" window in the middle; reuse the previous window when it fits.

def _float_bits(v: float) -> int:
    return struct.unpack("<Q", struct.pack("<d", v))[0]

def _bits_float(b: int) -> float:
    return struct.unpack("<d", struct.pack("<Q", b))[0]

def _leading_zeros(x: int) -> int:   # x != 0, treated as 64-bit
    return 64 - x.bit_length()

def _trailing_zeros(x: int) -> int:
    return (x & -x).bit_length() - 1


def _encode_xor(w: BitWriter, xor: int, prev_lz, prev_tz):
    if xor == 0:
        w.write_bit(0)                        # value unchanged -> one bit
        return prev_lz, prev_tz
    w.write_bit(1)
    lz, tz = _leading_zeros(xor), _trailing_zeros(xor)
    if prev_lz is not None and lz >= prev_lz and tz >= prev_tz:
        w.write_bit(0)                        # reuse the previous meaningful window
        length = 64 - prev_lz - prev_tz
        w.write_bits((xor >> prev_tz) & ((1 << length) - 1), length)
        return prev_lz, prev_tz
    w.write_bit(1)                            # declare a new window
    length = 64 - lz - tz
    w.write_bits(lz, 6)                       # leading zeros (0..63)
    w.write_bits(length, 7)                   # meaningful-bit count (1..64)
    w.write_bits(xor >> tz, length)
    return lz, tz


def _decode_xor(r: BitReader, prev_bits: int, prev_lz, prev_tz):
    if r.read_bit() == 0:
        return prev_bits, prev_lz, prev_tz
    if r.read_bit() == 0:
        lz, tz = prev_lz, prev_tz
    else:
        lz = r.read_bits(6)
        length = r.read_bits(7)
        tz = 64 - lz - length
    length = 64 - lz - tz
    xor = r.read_bits(length) << tz
    return prev_bits ^ xor, lz, tz


# ─── A time-bucketed, compressed chunk ───────────────────────────────────────

class CompressedChunk:
    """One time bucket's points, held as a single Gorilla-compressed bitstream."""
    def __init__(self, base_ts: int):
        self.base_ts = base_ts
        self.count = 0
        self._w = BitWriter()
        self._prev_ts = 0
        self._prev_delta = 0
        self._prev_bits = 0
        self._prev_lz = None
        self._prev_tz = None

    def append(self, ts: int, value: float) -> None:
        w = self._w
        bits = _float_bits(value)
        if self.count == 0:
            w.write_bits(ts - self.base_ts, 32)     # first timestamp: offset into the bucket
            w.write_bits(bits, 64)                   # first value: full 64 bits
            self._prev_ts, self._prev_delta = ts, 0
        else:
            delta = ts - self._prev_ts
            _encode_dod(w, delta - self._prev_delta)
            self._prev_ts, self._prev_delta = ts, delta
            self._prev_lz, self._prev_tz = _encode_xor(
                w, bits ^ self._prev_bits, self._prev_lz, self._prev_tz)
        self._prev_bits = bits
        self.count += 1

    def points(self):
        """Decode the bitstream back into (ts, value) pairs, in insertion order."""
        r = BitReader(self._w.to_bytes())
        ts = self.base_ts + r.read_bits(32)
        bits = r.read_bits(64)
        yield ts, _bits_float(bits)
        prev_ts, prev_delta, prev_bits = ts, 0, bits
        prev_lz = prev_tz = None
        for _ in range(self.count - 1):
            prev_delta += _decode_dod(r)
            prev_ts += prev_delta
            bits, prev_lz, prev_tz = _decode_xor(r, prev_bits, prev_lz, prev_tz)
            prev_bits = bits
            yield prev_ts, _bits_float(bits)

    def nbytes(self) -> int:
        return len(self._w.to_bytes())


# ─── The database: many series, each a set of time-ordered chunks ────────────

class TimeSeriesDB:
    def __init__(self, chunk_seconds: int = 3600):
        self.chunk_seconds = chunk_seconds
        self.series: dict[str, dict[int, CompressedChunk]] = {}

    def insert(self, name: str, ts: int, value: float) -> None:
        chunks = self.series.setdefault(name, {})
        base = (ts // self.chunk_seconds) * self.chunk_seconds
        chunk = chunks.get(base) or chunks.setdefault(base, CompressedChunk(base))
        chunk.append(ts, value)

    def query(self, name: str, start: int, end: int) -> list[tuple[int, float]]:
        """Points with start <= ts < end. Skips any chunk outside the range entirely."""
        chunks = self.series.get(name, {})
        out = []
        for base in sorted(chunks):
            if base + self.chunk_seconds <= start or base >= end:
                continue                             # whole chunk out of range -> never decoded
            out.extend((ts, v) for ts, v in chunks[base].points() if start <= ts < end)
        return out

    def downsample(self, name, start, end, bucket, agg="avg"):
        """Roll raw points up into fixed time buckets -- a tiny result for a dashboard."""
        groups: dict[int, list[float]] = {}
        for ts, v in self.query(name, start, end):
            groups.setdefault((ts // bucket) * bucket, []).append(v)
        fn = {"avg": lambda xs: sum(xs) / len(xs), "min": min, "max": max,
              "sum": sum, "count": len}[agg]
        return [(b, fn(groups[b])) for b in sorted(groups)]

    def drop_before(self, name: str, cutoff_ts: int) -> int:
        """Retention: drop whole chunks older than cutoff -- no per-row DELETE, no bloat."""
        chunks = self.series.get(name, {})
        dead = [b for b in chunks if b + self.chunk_seconds <= cutoff_ts]
        for b in dead:
            del chunks[b]
        return len(dead)

    def compressed_bytes(self, name: str) -> int:
        return sum(c.nbytes() for c in self.series.get(name, {}).values())

    def point_count(self, name: str) -> int:
        return sum(c.count for c in self.series.get(name, {}).values())


# ─── Demo ────────────────────────────────────────────────────────────────────

def _demo():
    db = TimeSeriesDB(chunk_seconds=3600)          # one chunk per hour
    name = "cpu.usage{host=web1}"

    # Ingest 3 hours of readings, one per second: a slowly varying CPU %.
    START = 1_699_999_200                            # a fixed, hour-aligned epoch second
    raw = []
    for i in range(3 * 3600):
        ts = START + i
        value = round(50 + 10 * math.sin(i / 600) + 2 * math.sin(i / 37), 1)
        db.insert(name, ts, value)
        raw.append((ts, value))

    n = db.point_count(name)
    chunks = len(db.series[name])
    print("== INGEST ==")
    print(f"  ingested {n} points ({name}) into {chunks} hourly chunks")

    # Prove the compression is lossless: decode everything, compare to the input.
    assert db.query(name, START, START + 3 * 3600) == raw, "round-trip must be exact"
    print("  round-trip check: decoded points identical to input  ✓")

    print("\n== COMPRESSION (delta-of-delta timestamps + XOR values) ==")
    raw_bytes = n * 16                               # 8 bytes ts + 8 bytes float64, uncompressed
    comp_bytes = db.compressed_bytes(name)
    print(f"  uncompressed: {raw_bytes:>8} bytes  (16 bytes/point)")
    print(f"  compressed:   {comp_bytes:>8} bytes  ({comp_bytes / n:.2f} bytes/point)")
    print(f"  ratio:        {raw_bytes / comp_bytes:.1f}x smaller")

    print("\n== RANGE QUERY: a 60-second window, only its chunk is decoded ==")
    window = db.query(name, START + 90, START + 150)
    print(f"  points in [START+90, START+150): {len(window)}")
    print(f"  first: ts=START+{window[0][0]-START}, value={window[0][1]}")
    print(f"  last:  ts=START+{window[-1][0]-START}, value={window[-1][1]}")

    print("\n== DOWNSAMPLE: raw 1s points -> 5-minute average buckets ==")
    rolled = db.downsample(name, START, START + 3 * 3600, bucket=300, agg="avg")
    print(f"  {n} raw points -> {len(rolled)} five-minute buckets")
    for b, v in rolled[:4]:
        print(f"    bucket START+{b-START:>5}s  avg={v:.2f}")

    print("\n== RETENTION: drop whole chunks older than a cutoff ==")
    before = len(db.series[name])
    dropped = db.drop_before(name, START + 2 * 3600)   # keep only the last hour's chunk
    print(f"  chunks before: {before}  ->  dropped {dropped} old chunk(s)  ->  {len(db.series[name])} left")
    print(f"  remaining points: {db.point_count(name)}  (dropping a chunk is O(1), no DELETE scan)")


if __name__ == "__main__":
    _demo()
