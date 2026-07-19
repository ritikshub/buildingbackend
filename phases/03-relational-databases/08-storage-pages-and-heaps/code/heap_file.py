#!/usr/bin/env python3
"""
Slotted-page heap file: how a relational table actually stores rows on disk.

Companion to docs/en.md (Phase 03, Lesson 08 - Storage: Pages, Heaps & the Buffer Pool).
A storage engine does I/O in fixed-size PAGES, not rows; a slotted page gives each
variable-length row a stable (page, slot) identity - the row id an index later points at.
Reference: PostgreSQL "Database Page Layout" (official storage documentation).

Runs standalone on the Python standard library only:  python heap_file.py
"""
import os
import struct
import tempfile

PAGE_SIZE = 128  # tiny on purpose (real DBs use 4-8 KB) so a few rows fill a page

# Page header at byte 0: (slot_count, free_end).
#   free_end = offset where the row region currently begins; rows grow DOWN from PAGE_SIZE.
_HEADER = struct.Struct("<HH")
_SLOT = struct.Struct("<HH")  # one slot: (row_offset, row_length)
_H = _HEADER.size


# --- The page: a fixed-size block holding many variable-length rows ------------------

def new_page() -> bytearray:
    page = bytearray(PAGE_SIZE)
    _HEADER.pack_into(page, 0, 0, PAGE_SIZE)  # 0 slots; free region ends at PAGE_SIZE
    return page


def page_insert(page: bytearray, row: bytes):
    """Place a row in the page; return its slot index, or None if the page is full."""
    slot_count, free_end = _HEADER.unpack_from(page, 0)
    slots_end = _H + slot_count * _SLOT.size
    if free_end - slots_end < len(row) + _SLOT.size:  # room for the row AND its new slot?
        return None
    offset = free_end - len(row)
    page[offset:free_end] = row                        # write row bytes at the end
    _SLOT.pack_into(page, slots_end, offset, len(row)) # append the slot pointer
    _HEADER.pack_into(page, 0, slot_count + 1, offset) # bump slot_count, move free_end
    return slot_count


def page_get(page: bytearray, slot: int) -> bytes:
    slot_count, _ = _HEADER.unpack_from(page, 0)
    if not 0 <= slot < slot_count:
        raise IndexError(f"slot {slot} out of range (0..{slot_count - 1})")
    offset, length = _SLOT.unpack_from(page, _H + slot * _SLOT.size)
    return bytes(page[offset:offset + length])


def page_slot_count(page: bytearray) -> int:
    return _HEADER.unpack_from(page, 0)[0]


# --- The buffer pool: a small RAM cache of pages (like Postgres shared_buffers) -------

class BufferPool:
    def __init__(self, path: str, capacity: int = 2):
        self._path = path
        self._cap = capacity
        self._cache: dict[int, bytearray] = {}
        self._lru: list[int] = []  # least-recently-used at the front
        self.hits = 0
        self.misses = 0

    def get_page(self, page_no: int) -> bytearray:
        if page_no in self._cache:
            self.hits += 1
            self._lru.remove(page_no)
            self._lru.append(page_no)
            return self._cache[page_no]
        self.misses += 1
        with open(self._path, "rb") as f:            # a real disk read
            f.seek(page_no * PAGE_SIZE)
            page = bytearray(f.read(PAGE_SIZE))
        if len(self._cache) >= self._cap and self._lru:
            del self._cache[self._lru.pop(0)]        # evict least-recently-used
        self._cache[page_no] = page
        self._lru.append(page_no)
        return page

    def forget(self, page_no: int) -> None:
        self._cache.pop(page_no, None)
        if page_no in self._lru:
            self._lru.remove(page_no)

    def clear(self) -> None:
        """Drop every cached page - simulate a cold start."""
        self._cache.clear()
        self._lru.clear()


# --- The heap file: a table's pages, in no particular order ---------------------------

class HeapFile:
    def __init__(self, path: str):
        self._path = path
        open(path, "wb").close()  # start empty
        self._page_count = 0
        self.pool = BufferPool(path)

    def _write_page(self, page_no: int, page: bytearray) -> None:
        with open(self._path, "r+b") as f:
            f.seek(page_no * PAGE_SIZE)
            f.write(page)

    def insert(self, row: bytes) -> tuple[int, int]:
        """Append a row; return its stable identity (page_no, slot) - like Postgres ctid."""
        # Try the last page first (the append pattern); heaps keep no order.
        if self._page_count > 0:
            page_no = self._page_count - 1
            page = self.pool.get_page(page_no)
            slot = page_insert(page, row)
            if slot is not None:
                self._write_page(page_no, page)
                return (page_no, slot)
        # Otherwise start a fresh page.
        page = new_page()
        slot = page_insert(page, row)
        if slot is None:
            raise ValueError(f"row of {len(row)} bytes is too big for a {PAGE_SIZE}B page")
        page_no = self._page_count
        self._write_page(page_no, page)
        self._page_count += 1
        self.pool.forget(page_no)  # so the next read comes from disk into the pool
        return (page_no, slot)

    def get(self, rid: tuple[int, int]) -> bytes:
        page_no, slot = rid
        return page_get(self.pool.get_page(page_no), slot)

    def scan(self):
        """Yield ((page_no, slot), row) for every row - the O(n) full scan."""
        for page_no in range(self._page_count):
            page = self.pool.get_page(page_no)
            for slot in range(page_slot_count(page)):
                yield (page_no, slot), page_get(page, slot)

    @property
    def page_count(self) -> int:
        return self._page_count


# --- Demo -----------------------------------------------------------------------------

def main() -> None:
    tmp = tempfile.NamedTemporaryFile(prefix="heap_", suffix=".db", delete=False)
    tmp.close()
    path = tmp.name
    try:
        heap = HeapFile(path)
        rows = [
            b"1,Ada Lovelace,ada@analytical.org",
            b"2,Grace Hopper,grace@navy.mil",
            b"3,Alan Turing,alan@bletchley.uk",
            b"4,Edsger Dijkstra,edsger@eindhoven.nl",
            b"5,Barbara Liskov,barbara@mit.edu",
            b"6,Donald Knuth,don@stanford.edu",
        ]

        print(f"PAGE_SIZE = {PAGE_SIZE} bytes\n")
        print("Inserting rows -> each gets a (page, slot) identity:")
        ids = []
        for row in rows:
            rid = heap.insert(row)
            ids.append(rid)
            print(f"  page {rid[0]}, slot {rid[1]}  <-  {row.decode()}")
        print(f"\n{len(rows)} rows spilled across {heap.page_count} pages "
              f"(a heap appends wherever there's room).")

        # Read one row directly by its id - no scan, one page fetched.
        target = ids[4]
        print(f"\nDirect read of row id {target}: {heap.get(target).decode()}")

        # Full scan - what a query with no usable index must do.
        print("\nFull scan of the heap (every page, every slot):")
        for rid, row in heap.scan():
            print(f"  {rid} -> {row.decode()}")

        # Buffer-pool caching: read every row from a COLD pool, then again WARM.
        # First touch of a page is a disk miss; later rows on that page are RAM hits.
        heap.pool.clear()
        heap.pool.hits = heap.pool.misses = 0
        for rid in ids:
            heap.get(rid)
        cold = (heap.pool.hits, heap.pool.misses)
        heap.pool.hits = heap.pool.misses = 0
        for rid in ids:
            heap.get(rid)
        warm = (heap.pool.hits, heap.pool.misses)
        print(f"\nBuffer pool (capacity {heap.pool._cap} pages), reading all "
              f"{len(ids)} rows:")
        print(f"  cold pool:  {cold[0]} hits, {cold[1]} misses  "
              f"(one disk read per page, then RAM hits within it)")
        print(f"  warm pool:  {warm[0]} hits, {warm[1]} misses  <- pages already in RAM")

        # Self-checks so the demo verifies itself and exits non-zero on any regression.
        assert heap.get(ids[0]) == rows[0]
        assert [row for _, row in heap.scan()] == rows
        assert heap.page_count >= 2, "expected multiple pages with PAGE_SIZE=128"
        print("\nAll self-checks passed.")
    finally:
        os.unlink(path)


if __name__ == "__main__":
    main()
