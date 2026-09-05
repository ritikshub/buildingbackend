#!/usr/bin/env python3
"""
The log as a primitive: offsets, replay, retention and compaction.

Companion to docs/en.md (Phase 06, Lesson 05 - The Log: Offsets, Replay & Retention).
Builds a segmented append-only log by hand: length-prefixed CRC32 records, rolling
segment files, a sparse offset index, consumer groups that own their own position,
whole-segment retention by time and size, keyed compaction with tombstones, and
recovery that truncates a torn trailing write. The record framing is deliberately the
same shape as the write-ahead log of Phase 03 Lesson 13 - one data structure, two jobs.
Reference: Kreps, Narkhede & Rao, "Kafka: a Distributed Messaging System for Log
Processing" (NetDB 2011).

Standard library only, seeded, virtual clock:  python append_only_log.py
"""

from __future__ import annotations

import json
import os
import random
import shutil
import struct
import tempfile
import time
import zlib
from bisect import bisect_right
from dataclasses import dataclass

SEED = 20110611                     # the NetDB paper's year, for luck
N_RECORDS = 2_000
N_KEYS = 400                        # distinct order ids -> compaction has something to do
TOMBSTONE_RATE = 0.03               # 3% of writes are deletes
SEGMENT_BYTES = 32 * 1024           # roll a new segment file at 32 KiB
INDEX_INTERVAL = 8                  # one sparse index entry per 8 records

BASE_MS = 1_700_000_000_000         # fixed epoch: the clock is virtual, output never drifts
MS_PER_RECORD = 432_000             # 7.2 minutes -> 2,000 records span exactly 10 days
DAY_MS = 86_400_000

# ── the on-disk record ───────────────────────────────────────────────────────
# frame:   [ 4B payload length ][ 4B crc32 of payload ][ payload ]
# payload: [ 8B offset ][ 8B timestamp_ms ][ 1B flags ][ 2B key length ][ key ][ value ]
#
# Length prefix so a reader knows where the next record starts without a delimiter;
# CRC so a half-written or bit-rotted record is detected rather than believed.
FRAME = struct.Struct(">II")
HEAD = struct.Struct(">QQBH")
FRAME_SIZE = FRAME.size             # 8
HEAD_SIZE = HEAD.size               # 19
TOMBSTONE = 0x01


class OffsetOutOfRange(Exception):
    """The requested offset has already been deleted by retention."""


class TornRecord(Exception):
    """A trailing record was not fully written. Recovery truncates it."""


@dataclass(frozen=True)
class Record:
    offset: int
    timestamp_ms: int
    key: bytes
    value: bytes | None             # None == tombstone: "this key is deleted"


def encode(rec: Record) -> bytes:
    flags = TOMBSTONE if rec.value is None else 0
    payload = HEAD.pack(rec.offset, rec.timestamp_ms, flags, len(rec.key))
    payload += rec.key + (rec.value or b"")
    return FRAME.pack(len(payload), zlib.crc32(payload)) + payload


def decode(payload: bytes) -> Record:
    offset, ts, flags, klen = HEAD.unpack_from(payload, 0)
    key = payload[HEAD_SIZE:HEAD_SIZE + klen]
    value = None if flags & TOMBSTONE else payload[HEAD_SIZE + klen:]
    return Record(offset, ts, key, value)


def record_bytes(key: bytes, value: bytes | None) -> int:
    return FRAME_SIZE + HEAD_SIZE + len(key) + len(value or b"")


# ── segments ─────────────────────────────────────────────────────────────────

class Segment:
    """One log file. Retention deletes whole segments; nothing is ever removed
    from the middle of a file, which is why deletion costs an unlink and not a
    rewrite."""

    def __init__(self, path: str, base_offset: int):
        self.path = path
        self.base_offset = base_offset
        self.index_offsets: list[int] = []      # sparse: every INDEX_INTERVAL records
        self.index_positions: list[int] = []
        self.n_records = 0
        self.size_bytes = 0
        self.first_ts: int | None = None
        self.last_ts: int | None = None

    name = property(lambda self: os.path.basename(self.path))
    # (offset, file position) as two int64s -- the whole index, in RAM
    index_bytes = property(lambda self: 16 * len(self.index_offsets))


def segment_name(base_offset: int) -> str:
    return "%020d.log" % base_offset


# ── the log ──────────────────────────────────────────────────────────────────

class Log:
    """A segmented append-only log.

    Writes only ever append to the tail segment. Reads are positional: give an
    offset, get records from there. The broker keeps NO per-message delivery
    state - a consumer's position is one integer, and the consumer owns it.
    """

    def __init__(self, directory: str, segment_bytes: int = SEGMENT_BYTES,
                 index_interval: int = INDEX_INTERVAL):
        self.dir = directory
        self.segment_bytes = segment_bytes
        self.index_interval = index_interval
        self.segments: list[Segment] = []
        self._next_offset = 0
        self._fh = None
        self.torn_bytes = 0
        os.makedirs(directory, exist_ok=True)
        self._load()

    # -- lifecycle ----------------------------------------------------------

    def _load(self) -> None:
        """Open from disk: scan every segment, rebuild the sparse index, and
        truncate a torn trailing record if the last write did not complete."""
        names = sorted(n for n in os.listdir(self.dir) if n.endswith(".log"))
        for name in names:
            seg = Segment(os.path.join(self.dir, name), int(name[:-4]))
            self._scan(seg)
            self.segments.append(seg)
        if not self.segments:
            seg = Segment(os.path.join(self.dir, segment_name(0)), 0)
            open(seg.path, "wb").close()
            self.segments.append(seg)
        # the next offset to hand out is one past the highest offset on disk
        self._next_offset = 0
        for seg in reversed(self.segments):
            if seg.n_records:
                self._next_offset = self._last_offset(seg) + 1
                break
        self._fh = open(self.segments[-1].path, "ab")

    def _last_offset(self, seg: Segment) -> int:
        """Offset of the final record in a segment (compaction leaves gaps, so
        base_offset + n_records - 1 is not good enough)."""
        last = -1
        for rec, _pos in self._iter_segment(seg):
            last = rec.offset
        return last

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None

    # -- scanning -----------------------------------------------------------

    def _iter_segment(self, seg: Segment, start_pos: int = 0):
        """Yield (record, file position) from a segment, stopping cleanly at a
        torn tail. This is the only place bytes become records."""
        with open(seg.path, "rb") as f:
            f.seek(start_pos)
            pos = start_pos
            while True:
                header = f.read(FRAME_SIZE)
                if len(header) < FRAME_SIZE:
                    if header:
                        raise TornRecord(pos)         # frame header itself was cut short
                    return
                plen, crc = FRAME.unpack(header)
                payload = f.read(plen)
                if len(payload) < plen:
                    raise TornRecord(pos)             # declared N bytes, found fewer
                if zlib.crc32(payload) != crc:
                    raise TornRecord(pos)             # bytes present but corrupt
                yield decode(payload), pos
                pos += FRAME_SIZE + plen

    def _scan(self, seg: Segment) -> None:
        """Rebuild a segment's metadata and sparse index from its bytes."""
        good_bytes = 0
        try:
            for rec, pos in self._iter_segment(seg):
                if seg.n_records % self.index_interval == 0:
                    seg.index_offsets.append(rec.offset)
                    seg.index_positions.append(pos)
                if seg.first_ts is None:
                    seg.first_ts = rec.timestamp_ms
                seg.last_ts = rec.timestamp_ms
                seg.n_records += 1
                good_bytes = pos + record_bytes(rec.key, rec.value)
        except TornRecord as exc:
            good_bytes = exc.args[0]
            torn = os.path.getsize(seg.path) - good_bytes
            os.truncate(seg.path, good_bytes)         # drop the partial tail
            self.torn_bytes += torn
        seg.size_bytes = good_bytes

    def scan_all(self):
        for seg in self.segments:
            yield from (rec for rec, _ in self._iter_segment(seg))

    # -- writing ------------------------------------------------------------

    def _roll(self, base_offset: int) -> Segment:
        self._fh.close()
        seg = Segment(os.path.join(self.dir, segment_name(base_offset)), base_offset)
        open(seg.path, "wb").close()
        self.segments.append(seg)
        self._fh = open(seg.path, "ab")
        return seg

    def _append_record(self, rec: Record) -> int:
        blob = encode(rec)
        seg = self.segments[-1]
        if seg.n_records and seg.size_bytes + len(blob) > self.segment_bytes:
            seg = self._roll(rec.offset)
        elif seg.n_records == 0 and seg.base_offset != rec.offset:
            # empty tail segment adopting a different base (compaction preserves
            # the original offsets, so the first kept record may not be offset 0)
            new_path = os.path.join(self.dir, segment_name(rec.offset))
            self._fh.close()
            os.replace(seg.path, new_path)
            seg.path, seg.base_offset = new_path, rec.offset
            self._fh = open(seg.path, "ab")
        pos = seg.size_bytes
        self._fh.write(blob)
        self._fh.flush()
        if seg.n_records % self.index_interval == 0:
            seg.index_offsets.append(rec.offset)
            seg.index_positions.append(pos)
        if seg.first_ts is None:
            seg.first_ts = rec.timestamp_ms
        seg.last_ts = rec.timestamp_ms
        seg.n_records += 1
        seg.size_bytes += len(blob)
        self._next_offset = rec.offset + 1
        return rec.offset

    def append(self, key: bytes, value: bytes | None, timestamp_ms: int) -> int:
        return self._append_record(Record(self._next_offset, timestamp_ms, key, value))

    # -- positional reading -------------------------------------------------

    earliest_offset = property(lambda self: self.segments[0].base_offset)
    next_offset = property(lambda self: self._next_offset)
    total_bytes = property(lambda self: sum(s.size_bytes for s in self.segments))
    total_records = property(lambda self: sum(s.n_records for s in self.segments))
    index_bytes = property(lambda self: sum(s.index_bytes for s in self.segments))
    n_index_entries = property(lambda self: sum(len(s.index_offsets) for s in self.segments))

    def read_from(self, offset: int, max_records: int) -> tuple[list[Record], int, int]:
        """Read up to max_records starting at `offset`.

        Returns (records, records_scanned, records_skipped). `scanned` counts
        records this read had to deserialize and throw away to find the target;
        `skipped` counts the ones a naive scan-from-the-beginning would have had
        to deserialize and this one did not. That difference is the index.
        """
        if offset < self.earliest_offset:
            raise OffsetOutOfRange(
                "offset %d is below the earliest available offset %d" % (offset, self.earliest_offset))
        naive = max(0, offset - self.earliest_offset)
        if offset >= self._next_offset:
            return [], 0, naive

        bases = [s.base_offset for s in self.segments]
        si = max(0, bisect_right(bases, offset) - 1)
        seg = self.segments[si]
        i = bisect_right(seg.index_offsets, offset) - 1      # nearest index entry at or before
        start_pos = seg.index_positions[i] if i >= 0 else 0

        out: list[Record] = []
        scanned = 0
        for s in range(si, len(self.segments)):
            pos = start_pos if s == si else 0
            for rec, _ in self._iter_segment(self.segments[s], pos):
                if rec.offset < offset:
                    scanned += 1                             # overshoot from the sparse index
                    continue
                out.append(rec)
                if len(out) >= max_records:
                    return out, scanned, naive - scanned
        return out, scanned, naive - scanned

    # -- retention ----------------------------------------------------------

    def _delete_oldest(self) -> tuple[str, int, int]:
        seg = self.segments.pop(0)
        os.remove(seg.path)                    # deletion is an unlink, not a rewrite
        return seg.name, seg.n_records, seg.size_bytes

    def retain_by_time(self, now_ms: int, max_age_ms: int) -> list[tuple[str, int, int]]:
        """Delete whole segments whose newest record is older than max_age.
        The active segment is never deleted."""
        removed = []
        while len(self.segments) > 1:
            seg = self.segments[0]
            if seg.last_ts is None or now_ms - seg.last_ts <= max_age_ms:
                break
            removed.append(self._delete_oldest())
        return removed

    def retain_by_size(self, max_bytes: int) -> list[tuple[str, int, int]]:
        """Delete whole segments oldest-first until the log fits in max_bytes."""
        removed = []
        while len(self.segments) > 1 and self.total_bytes > max_bytes:
            removed.append(self._delete_oldest())
        return removed

    # -- compaction ---------------------------------------------------------

    def compact_into(self, dest_dir: str) -> "Log":
        """Keyed retention: keep only the LAST record per key, drop keys whose
        last record is a tombstone. Original offsets are preserved, so the
        compacted log has gaps - a consumer's offset still means the same thing.
        """
        latest: dict[bytes, Record] = {}
        for rec in self.scan_all():
            latest[rec.key] = rec                            # last write wins
        keep = sorted((r for r in latest.values() if r.value is not None),
                      key=lambda r: r.offset)
        out = Log(dest_dir, self.segment_bytes, self.index_interval)
        for rec in keep:
            out._append_record(rec)
        return out


def fold(log: Log) -> dict[bytes, bytes]:
    """Read the log as a STREAM of changes and fold it into a TABLE of current
    state. This function is the stream-table duality, in six lines."""
    table: dict[bytes, bytes] = {}
    for rec in log.scan_all():
        if rec.value is None:
            table.pop(rec.key, None)                          # tombstone = delete
        else:
            table[rec.key] = rec.value
    return table


# ── consumers: the position lives with the reader, not the broker ────────────

class OffsetStore:
    """Committed offsets in their own compacted keyed log - which is exactly
    what a real broker does with an internal __consumer_offsets topic. The log
    stores its own bookkeeping in a log."""

    def __init__(self, directory: str):
        self.log = Log(directory, segment_bytes=4096, index_interval=4)
        self.commits = 0

    def commit(self, group: str, offset: int, timestamp_ms: int) -> None:
        self.log.append(group.encode(), str(offset).encode(), timestamp_ms)
        self.commits += 1

    def committed(self, group: str) -> int | None:
        raw = fold(self.log).get(group.encode())
        return int(raw) if raw is not None else None


class ConsumerGroup:
    """One integer of broker-side state, and everything else follows from it."""

    def __init__(self, name: str, log: Log, store: OffsetStore, start: int = 0):
        self.name = name
        self.log = log
        self.store = store
        committed = store.committed(name)
        self.position = start if committed is None else committed
        self.consumed = 0
        self.digest = 0                     # order-sensitive checksum of what it saw

    def poll(self, max_records: int) -> list[Record]:
        records, _scanned, _skipped = self.log.read_from(self.position, max_records)
        for rec in records:
            self.digest = zlib.crc32(
                b"%d|%s|%s" % (rec.offset, rec.key, rec.value or b"<tombstone>"), self.digest)
        if records:
            self.position = records[-1].offset + 1
        self.consumed += len(records)
        return records

    def drain(self, batch: int) -> None:
        while self.poll(batch):
            pass

    def commit(self, timestamp_ms: int) -> None:
        self.store.commit(self.name, self.position, timestamp_ms)

    def seek(self, offset: int) -> None:
        self.position = offset
        self.consumed = 0
        self.digest = 0

    @property
    def lag(self) -> int:
        return self.log.next_offset - self.position


# ── the workload ─────────────────────────────────────────────────────────────

STATUSES = ["created", "paid", "packed", "shipped", "delivered"]


def build_workload(n: int) -> list[tuple[bytes, bytes | None]]:
    """An order-events stream: keyed by order id, occasionally a deletion."""
    rnd = random.Random(SEED)
    keys = ["order-%04d" % i for i in range(N_KEYS)]
    events = []
    for i in range(n):
        key = rnd.choice(keys)
        if rnd.random() < TOMBSTONE_RATE:
            events.append((key.encode(), None))              # GDPR erasure / order cancelled
        else:
            value = json.dumps({
                "order": key,
                "status": rnd.choice(STATUSES),
                "amount_cents": rnd.randrange(500, 250_000),
                "seq": i,
            }, separators=(",", ":")).encode()
            events.append((key.encode(), value))
    return events


# ── sequential vs random writes ──────────────────────────────────────────────

def measure_write_patterns(directory: str, n_writes: int = 8_192, block: int = 512) -> dict:
    """Why append-only is fast, measured two ways.

    The deterministic measurement is head travel: the total absolute distance
    between consecutive write positions. Sequential writing travels exactly the
    file length; random writing travels a multiple of it. That number is the
    physical argument, and it does not depend on this machine.

    The wall-clock measurement is the consequence, and it is the ONLY
    non-deterministic output in this program.
    """
    rnd = random.Random(SEED + 7)
    payload = b"\xa5" * block
    size = n_writes * block

    seq_path = os.path.join(directory, "seq.bin")
    rnd_path = os.path.join(directory, "rnd.bin")

    positions = [i * block for i in range(n_writes)]
    shuffled = positions[:]
    rnd.shuffle(shuffled)

    def travel(seq: list[int]) -> int:
        """Total distance the write position moves: the seek to each block plus
        the block itself. Sequential writing travels exactly the file length."""
        total, head = 0, 0
        for p in seq:
            total += abs(p - head) + block
            head = p + block
        return total

    def discontiguous(seq: list[int]) -> int:
        head, count = 0, 0
        for p in seq:
            if p != head:
                count += 1
            head = p + block
        return count

    start = time.perf_counter()
    with open(seq_path, "wb") as f:
        for _ in range(n_writes):
            f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    seq_secs = time.perf_counter() - start

    with open(rnd_path, "wb") as f:                          # preallocate
        f.write(b"\x00" * size)
    start = time.perf_counter()
    with open(rnd_path, "r+b") as f:
        for pos in shuffled:
            f.seek(pos)
            f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    rnd_secs = time.perf_counter() - start

    mib = size / (1024 * 1024)
    return {
        "writes": n_writes, "block": block, "mib": mib,
        "seq_travel": travel(positions), "rnd_travel": travel(shuffled),
        "seq_disc": discontiguous(positions), "rnd_disc": discontiguous(shuffled),
        "seq_mibs": mib / seq_secs, "rnd_mibs": mib / rnd_secs,
        "seq_secs": seq_secs, "rnd_secs": rnd_secs,
    }


# ── report ───────────────────────────────────────────────────────────────────

def main() -> None:
    root = tempfile.mkdtemp(prefix="phase06-log-")
    try:
        run(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)




def run(root: str) -> None:
    log = Log(os.path.join(root, "orders"))
    span_days = (N_RECORDS - 1) * MS_PER_RECORD / DAY_MS

    print("== 1. THE SEGMENTED APPEND-ONLY LOG ==")
    for i, (key, value) in enumerate(build_workload(N_RECORDS)):
        log.append(key, value, BASE_MS + i * MS_PER_RECORD)
    print(f"  appended {log.total_records:,} records spanning {span_days:.1f} days of virtual time")
    print(f"  offsets {log.earliest_offset} .. {log.next_offset - 1}   {log.total_bytes:,} bytes"
          f"   avg {log.total_bytes / log.total_records:.1f} B/record")
    print(f"  frame: 4B length + 4B crc32 + 19B header + key + value  (overhead {FRAME_SIZE + HEAD_SIZE} B/record)")
    print(f"  {len(log.segments)} segment files, rolling at {SEGMENT_BYTES // 1024} KiB:")
    for seg in log.segments[:4] + [None, log.segments[-1]]:
        if seg is None:
            print(f"    ... {len(log.segments) - 5} more ...")
            continue
        note = "   <- active, appends land here" if seg is log.segments[-1] else ""
        print(f"    {seg.name}  base offset {seg.base_offset:>5,}  {seg.n_records:>4,} records"
              f"  {seg.size_bytes:>7,} B  index {len(seg.index_offsets):>3} entries{note}")
    idx_entries = log.n_index_entries
    print(f"  sparse index: {idx_entries} entries (one per {INDEX_INTERVAL} records), {log.index_bytes:,} B"
          f" = {100 * log.index_bytes / log.total_bytes:.2f}% of the log")

    print("\n== 2. POSITIONAL READS: what the sparse index buys ==")
    for target in (0, 137, 1_337, 1_999):
        recs, scanned, skipped = log.read_from(target, 1)
        print(f"  read_from({target:>5,})  -> offset {recs[0].offset:>5,}  key {recs[0].key.decode():<11}"
              f"  deserialized {scanned} record(s) to get there, skipped {skipped:,}")
    total_scanned = sum(log.read_from(t, 1)[1] for t in range(log.earliest_offset, log.next_offset))
    avg_scanned, naive_avg = total_scanned / N_RECORDS, (N_RECORDS - 1) / 2
    print(f"  averaged over all {N_RECORDS:,} offsets: {avg_scanned:.2f} records scanned per seek")
    print(f"  a full scan from the start would average {naive_avg:,.1f}"
          f"  -> {naive_avg / avg_scanned:,.0f}x fewer records touched")
    print(f"  cost of that: {log.index_bytes:,} B of index for {log.total_bytes:,} B of log")

    print("\n== 3. INDEPENDENT CONSUMERS: one log, three readers, one copy ==")
    store = OffsetStore(os.path.join(root, "__consumer_offsets"))
    fraud = ConsumerGroup("fraud-realtime", log, store)
    nightly = ConsumerGroup("nightly-batch", log, store)
    print("  two groups, deliberately different speeds - the log does not care")
    print(f"  {'round':>5}  fraud-realtime (batch 256)      nightly-batch (batch 40)")
    for i in range(1, 5):
        fraud.poll(256), nightly.poll(40)
        fraud.commit(BASE_MS + i * MS_PER_RECORD), nightly.commit(BASE_MS + i * MS_PER_RECORD)
        print(f"  {i:>5}  pos {fraud.position:>5,}  lag {fraud.lag:>5,}"
              f"              pos {nightly.position:>5,}  lag {nightly.lag:>5,}")
    print("  a new service launches and needs the whole history - it just starts at 0:")
    search = ConsumerGroup("search-indexer", log, store, start=0)
    for group in (fraud, nightly, search):
        group.drain(500)
        group.commit(BASE_MS + N_RECORDS * MS_PER_RECORD)
        print(f"    {group.name:<16} consumed {group.consumed:>5,}  committed {store.committed(group.name):>5,}"
              f"  lag {group.lag}  digest {group.digest:08x}")
    fan_out = log.total_bytes * 3
    print(f"  storage: the log holds {log.total_records:,} records ONCE = {log.total_bytes:,} B")
    print(f"  the fan-out model of lesson 04 gives each subscriber its own queue copy:"
          f" 3 x {log.total_bytes:,} = {fan_out:,} B")
    print(f"  storage amplification {fan_out / log.total_bytes:.2f}x   -- and a 4th subscriber costs the log 0 B"
          f" and the fan-out {log.total_bytes:,} B more")
    print(f"  broker-side state per group: 1 integer.  Queue-model state for the same job:"
          f" 1 record per message per consumer = {log.total_records * 3:,} entries")

    print("\n== 4. REPLAY: the consumer owns the position, so rewinding is free ==")
    baseline = fraud.digest
    fraud.seek(0)
    fraud.drain(500)
    print(f"  reset fraud-realtime to offset 0 -> re-read {fraud.consumed:,} records,"
          f" digest {fraud.digest:08x}  identical: {fraud.digest == baseline}")
    expect = 0
    for rec in log.read_from(1_500, N_RECORDS)[0]:
        expect = zlib.crc32(b"%d|%s|%s" % (rec.offset, rec.key, rec.value or b"<tombstone>"), expect)
    fraud.seek(1_500)
    first = fraud.poll(1)[0]
    fraud.drain(500)
    print(f"  reset to offset 1,500 -> first record back is offset {first.offset:,}, {fraud.consumed:,} records,"
          f" digest {fraud.digest:08x}  matches the original slice: {fraud.digest == expect}")
    print("  nothing was re-sent by a producer and nothing was copied: replay is a seek")

    print("\n== 5. RETENTION: delete whole segments, never single records ==")
    aged_dir = os.path.join(root, "orders-time-retained")
    shutil.copytree(log.dir, aged_dir)
    aged = Log(aged_dir)
    now_ms = BASE_MS + N_RECORDS * MS_PER_RECORD
    before_segments, before_bytes = len(aged.segments), aged.total_bytes
    removed = aged.retain_by_time(now_ms, 7 * DAY_MS)
    print(f"  policy: retention.ms = 7 days   (log spans {span_days:.1f} days)")
    print(f"  deleted {len(removed)} segment(s), {sum(r[1] for r in removed):,} records,"
          f" {sum(r[2] for r in removed):,} B")
    print(f"  earliest readable offset moved 0 -> {aged.earliest_offset:,}   log {before_bytes:,} B ->"
          f" {aged.total_bytes:,} B   ({before_segments} -> {len(aged.segments)} segments)")
    removed = aged.retain_by_size(96 * 1024)
    print(f"  then retention.bytes = 96 KiB: deleted {len(removed)} more segments,"
          f" earliest offset now {aged.earliest_offset:,}, size {aged.total_bytes:,} B")
    stale = ConsumerGroup("stale-reporting", aged, store, start=300)
    try:
        stale.poll(10)
        print("  stale consumer read successfully -- unexpected")
    except OffsetOutOfRange as exc:
        print("  a consumer that fell behind and committed offset 300 now polls:")
        print(f"    OffsetOutOfRange: {exc}")
        print(f"    the operator's choice: reset to earliest ({aged.earliest_offset:,}, reprocess a backlog)"
              f" or to latest ({aged.next_offset:,}, accept the data loss)")
    stale.seek(aged.earliest_offset)
    stale.drain(500)
    print(f"    reset-to-earliest recovers {stale.consumed:,} records"
          f" -- the {aged.earliest_offset:,} deleted ones are gone for good")

    print("\n== 6. COMPACTION: keyed retention turns a history into a table ==")
    compacted = log.compact_into(os.path.join(root, "orders-compacted"))
    tombstoned = sum(1 for r in log.scan_all() if r.value is None)
    full_table, comp_table = fold(log), fold(compacted)
    print(f"  full log:      {log.total_records:>6,} records  {log.total_bytes:>8,} B"
          f"  {len(log.segments)} segments  ({tombstoned} of them tombstones)")
    print(f"  compacted log: {compacted.total_records:>6,} records  {compacted.total_bytes:>8,} B"
          f"  {len(compacted.segments)} segments  ({N_KEYS} keys were written;"
          f" {N_KEYS - compacted.total_records} ended deleted)")
    print(f"  reduction {log.total_records / compacted.total_records:.2f}x by count,"
          f" {log.total_bytes / compacted.total_bytes:.2f}x by bytes")
    print(f"  offsets are PRESERVED, so the compacted log has gaps: first {compacted.earliest_offset},"
          f" last {compacted.next_offset - 1:,}, but only {compacted.total_records:,} records in between")
    print(f"  fold(full log)      -> {len(full_table):,} keys")
    print(f"  fold(compacted log) -> {len(comp_table):,} keys")
    print(f"  the two tables are identical: {full_table == comp_table}   <- stream-table duality, demonstrated")
    aged_table = fold(aged)
    print(f"  for contrast, the age+size-retained log from section 5 holds {aged.total_records} records"
          f" and folds to {len(aged_table)} keys, not {len(full_table)}"
          f" -- {len(full_table) - len(aged_table)} keys have no surviving record")
    print("  a history window is not a snapshot: only compaction guarantees every key is still represented")
    off_compacted = store.log.compact_into(os.path.join(root, "offsets-compacted"))
    print(f"  the offsets log is itself compacted: {store.log.total_records} appends"
          f" for {len(fold(store.log))} groups -> {off_compacted.total_records} records after compaction")

    print("\n== 7. WHY APPENDING IS FAST: sequential vs random writes ==")
    m = measure_write_patterns(root)
    print(f"  same work both ways: {m['writes']:,} writes of {m['block']} B = {m['mib']:.1f} MiB,"
          f" one fsync at the end")
    for label, travel, disc in (("sequential", m["seq_travel"], m["seq_disc"]),
                                ("random    ", m["rnd_travel"], m["rnd_disc"])):
        print(f"  {label}  head travel {travel / (1024 * 1024):>9,.1f} MiB   discontiguous writes {disc:>6,}")
    print(f"  head travel ratio {m['rnd_travel'] / m['seq_travel']:,.0f}x"
          f"   <- deterministic, and the reason the design is append-only")
    print(f"  wall clock on this machine: sequential {m['seq_mibs']:,.0f} MiB/s, random {m['rnd_mibs']:,.0f} MiB/s,"
          f" ratio {m['seq_mibs'] / m['rnd_mibs']:.1f}x")
    print("  (the wall-clock line is the only non-deterministic output here; on a spinning disk it is far wider)")

    print("\n== 8. RECOVERY: reopen from disk, rebuild the index, truncate a torn tail ==")
    crash_dir = os.path.join(root, "orders-crashed")
    shutil.copytree(log.dir, crash_dir)
    tail = sorted(n for n in os.listdir(crash_dir) if n.endswith(".log"))[-1]
    partial = encode(Record(9_999, BASE_MS, b"order-9999", b'{"status":"never-finished"}'))
    with open(os.path.join(crash_dir, tail), "ab") as f:
        f.write(partial[:len(partial) // 2])                  # power cut mid-write
    print(f"  simulated crash: appended {len(partial) // 2} bytes of a {len(partial)}-byte record to {tail}")
    log.close()
    recovered = Log(crash_dir)
    print(f"  reopened: {len(recovered.segments)} segments scanned, {recovered.total_records:,} records,"
          f" next offset {recovered.next_offset:,}")
    print(f"  torn tail detected and truncated: {recovered.torn_bytes} bytes discarded")
    print(f"  sparse index rebuilt from the bytes: {recovered.n_index_entries} entries"
          f"  (matches the pre-crash {idx_entries}: {recovered.n_index_entries == idx_entries})")
    print(f"  state after recovery is byte-identical to before: {fold(recovered) == full_table}")
    recovered.append(b"order-0001", b'{"status":"post-recovery"}', now_ms)
    print(f"  the log accepts writes again at offset {recovered.next_offset - 1:,} -- no gap, no duplicate")
    for handle in (recovered, compacted, aged, off_compacted, store.log):
        handle.close()


if __name__ == "__main__":
    main()
