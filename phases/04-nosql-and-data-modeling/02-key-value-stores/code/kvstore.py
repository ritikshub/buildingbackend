#!/usr/bin/env python3
"""
A persistent key-value store: an append-only log + an in-memory hash index.

Companion to docs/en.md (Phase 04, Lesson 02 - Key-Value Stores). This is the
"Bitcask" model used by real stores (Riak's default engine): every write is an
APPEND to one log file, and an in-memory dict maps each key to the byte offset of
its latest record. Reads are one dict lookup + one seek. Deletes append a
tombstone. Compaction reclaims space by rewriting only the live records.
Reference: Sheehy & Smith, "Bitcask: A Log-Structured Hash Table for Fast
Key/Value Data" (Basho, 2010).

Runs standalone on the Python standard library only:  python kvstore.py
"""

from __future__ import annotations
import os
import struct
import zlib

# Each record on disk:  [crc32 | key_len | val_len | key bytes | val bytes]
# crc32 is computed over everything after it, so a torn/partial tail record is
# detectable on recovery. val_len == TOMBSTONE marks a delete (no value follows).
HEADER = struct.Struct("<III")   # crc (uint32), key_len (uint32), val_len (uint32)
TOMBSTONE = 0xFFFFFFFF
MISS = object()                  # unique sentinel: distinguishes "no such key" from a stored b""


class KVStore:
    def __init__(self, path: str):
        self.path = path
        self.index: dict[bytes, int] = {}   # key -> byte offset of its latest record
        # Open for append+read; create if missing. Then rebuild the index from the log.
        self.f = open(path, "a+b")
        self._replay()

    # ---- write path: PUT is a single append + one dict update (O(1)) ----
    def put(self, key: bytes, value: bytes) -> None:
        offset = self._append(key, value, tombstone=False)
        self.index[key] = offset

    def delete(self, key: bytes) -> bool:
        if key not in self.index:
            return False
        self._append(key, b"", tombstone=True)  # write a tombstone so the delete survives restart
        del self.index[key]
        return True

    # ---- read path: one dict lookup, one seek+read (O(1)) ----
    def get(self, key: bytes):
        offset = self.index.get(key)
        if offset is None:
            return MISS
        _, value = self._read_at(offset)
        return value

    def keys(self):
        return list(self.index.keys())

    def __len__(self):
        return len(self.index)

    def _append(self, key: bytes, value: bytes, tombstone: bool) -> int:
        val_len = TOMBSTONE if tombstone else len(value)
        body = HEADER.pack(0, len(key), val_len)[4:] + key + (b"" if tombstone else value)
        crc = zlib.crc32(body) & 0xFFFFFFFF
        record = struct.pack("<I", crc) + body
        self.f.seek(0, os.SEEK_END)
        offset = self.f.tell()
        self.f.write(record)
        self.f.flush()                    # hand the bytes to the OS so a crash keeps them
        os.fsync(self.f.fileno())         # durability: force the OS to flush to disk (Phase 3, L13)
        return offset

    def _read_at(self, offset: int):
        self.f.seek(offset)
        header = self.f.read(HEADER.size)
        crc, key_len, val_len = HEADER.unpack(header)
        tomb = val_len == TOMBSTONE
        n = 0 if tomb else val_len
        payload = self.f.read(key_len + n)
        if zlib.crc32(header[4:] + payload) & 0xFFFFFFFF != crc:
            raise ValueError(f"corrupt record at offset {offset} (crc mismatch)")
        key = payload[:key_len]
        value = None if tomb else payload[key_len:]
        return key, value

    def _replay(self) -> None:
        """Rebuild the in-memory index by scanning the log start to end.
        The LAST record for a key wins; a tombstone removes it."""
        self.f.seek(0)
        offset = 0
        while True:
            header = self.f.read(HEADER.size)
            if len(header) < HEADER.size:
                break                      # clean end (or a torn partial header) -> stop
            crc, key_len, val_len = HEADER.unpack(header)
            tomb = val_len == TOMBSTONE
            n = 0 if tomb else val_len
            payload = self.f.read(key_len + n)
            if len(payload) < key_len + n:
                break                      # truncated tail from a crash mid-write -> ignore it
            if zlib.crc32(header[4:] + payload) & 0xFFFFFFFF != crc:
                break                      # corrupt tail -> stop; earlier records are still good
            key = payload[:key_len]
            if tomb:
                self.index.pop(key, None)
            else:
                self.index[key] = offset
            offset += HEADER.size + key_len + n

    def compact(self) -> tuple[int, int]:
        """Reclaim space: rewrite ONLY the live records to a fresh file, then swap.
        Superseded versions and tombstones vanish. Returns (bytes_before, bytes_after)."""
        before = os.path.getsize(self.path)
        tmp_path = self.path + ".compact"
        live = {k: self._read_at(off)[1] for k, off in self.index.items()}
        with open(tmp_path, "wb") as out:
            new_index: dict[bytes, int] = {}
            for key, value in live.items():
                val_len = len(value)
                body = HEADER.pack(0, len(key), val_len)[4:] + key + value
                crc = zlib.crc32(body) & 0xFFFFFFFF
                new_index[key] = out.tell()
                out.write(struct.pack("<I", crc) + body)
            out.flush()
            os.fsync(out.fileno())
        self.f.close()
        os.replace(tmp_path, self.path)    # atomic swap: readers see old-or-new, never half
        self.f = open(self.path, "a+b")
        self.index = new_index
        return before, os.path.getsize(self.path)

    def close(self):
        self.f.close()


def _demo():
    path = "/tmp/kvstore_demo.log"
    if os.path.exists(path):
        os.remove(path)

    print("== PUT / GET / DELETE ==")
    kv = KVStore(path)
    kv.put(b"user:1", b'{"name":"Ada"}')
    kv.put(b"user:2", b'{"name":"Alan"}')
    kv.put(b"session:xyz", b"user:1")
    print("get user:1 ->", kv.get(b"user:1").decode())
    print("get user:2 ->", kv.get(b"user:2").decode())
    print("miss  user:9 ->", kv.get(b"user:9") is MISS)

    kv.put(b"user:1", b'{"name":"Ada Lovelace"}')   # overwrite: append a new record
    print("after overwrite user:1 ->", kv.get(b"user:1").decode())

    kv.delete(b"session:xyz")                        # append a tombstone
    print("after delete session:xyz is MISS ->", kv.get(b"session:xyz") is MISS)
    print("live keys:", sorted(k.decode() for k in kv.keys()))
    kv.close()

    print("\n== DURABILITY: reopen and replay the log ==")
    kv2 = KVStore(path)                              # rebuilds index purely from disk
    print("user:1 survived restart ->", kv2.get(b"user:1").decode())
    print("session:xyz still deleted ->", kv2.get(b"session:xyz") is MISS)

    print("\n== COMPACTION: reclaim superseded + tombstoned bytes ==")
    before, after = kv2.compact()
    print(f"log size: {before} bytes -> {after} bytes  (reclaimed {before - after})")
    print("data intact after compaction ->", kv2.get(b"user:1").decode())
    kv2.close()
    os.remove(path)


if __name__ == "__main__":
    _demo()
