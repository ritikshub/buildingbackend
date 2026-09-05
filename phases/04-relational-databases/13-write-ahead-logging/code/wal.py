#!/usr/bin/env python3
"""
A write-ahead log (WAL): how a committed change survives a crash.

Companion to docs/en.md (Phase 03, Lesson 13 - Durability: Write-Ahead Logging). Every
change is appended to a sequential log and fsync'd BEFORE the data pages change; a
transaction is committed the instant its commit record is on disk. Recovery replays the
log: REDO committed transactions (durability), UNDO uncommitted ones (crash-safe atomicity).
Reference: Mohan et al., "ARIES: A Transaction Recovery Method..." (ACM TODS, 1992).

Runs standalone on the Python standard library only:  python wal.py
"""
import json
import os
import tempfile


def recover(wal_path: str) -> dict:
    """Rebuild committed state from the log alone (redo committed, drop uncommitted)."""
    if not os.path.exists(wal_path):
        return {}
    with open(wal_path) as f:
        records = [json.loads(line) for line in f if line.strip()]
    committed = {r["t"] for r in records if r["op"] == "commit"}   # who reached commit?
    data: dict = {}
    for r in records:
        if r["op"] == "set" and r["t"] in committed:  # REDO committed writes...
            data[r["k"]] = r["v"]                      # ...uncommitted are UNDONE by omission
    return data


class Transaction:
    def __init__(self, db: "Database", tid: int):
        self._db = db
        self.tid = tid
        self._writes: list[tuple[str, int]] = []

    def write(self, key: str, value: int) -> None:
        self._writes.append((key, value))   # buffered; nothing on disk yet

    def commit(self) -> None:
        # WRITE-AHEAD RULE: log every change, then the commit record, then fsync -
        # all BEFORE we touch the in-memory data pages.
        for key, value in self._writes:
            self._db._log({"t": self.tid, "op": "set", "k": key, "v": value})
        self._db._log({"t": self.tid, "op": "commit"})
        self._db._sync()                    # <-- the durable commit point (one fsync)
        for key, value in self._writes:      # only now update the "data pages" (RAM)
            self._db.data[key] = value

    def rollback(self) -> None:
        self._writes.clear()                 # never logged a commit -> nothing to undo


class Database:
    def __init__(self, wal_path: str):
        self.wal_path = wal_path
        self.data = recover(wal_path)        # replay the log on startup
        self._log_file = open(wal_path, "a")
        existing = self._max_tid()
        self._next_tid = existing + 1

    def _max_tid(self) -> int:
        if not os.path.exists(self.wal_path):
            return 0
        with open(self.wal_path) as f:
            tids = [json.loads(l)["t"] for l in f if l.strip()]
        return max(tids) if tids else 0

    def _log(self, record: dict) -> None:
        self._log_file.write(json.dumps(record) + "\n")

    def _sync(self) -> None:
        self._log_file.flush()
        os.fsync(self._log_file.fileno())    # force the log to durable storage

    def begin(self) -> Transaction:
        tid = self._next_tid
        self._next_tid += 1
        return Transaction(self, tid)

    def close(self) -> None:
        self._log_file.close()


def show_log(wal_path: str) -> None:
    with open(wal_path) as f:
        for line in f:
            print("   " + line.rstrip())


def main() -> None:
    tmp = tempfile.NamedTemporaryFile(prefix="wal_", suffix=".log", delete=False)
    tmp.close()
    path = tmp.name
    try:
        # --- Session 1: two committed transactions -------------------------------
        db = Database(path)
        t = db.begin()
        t.write("alice", 100)
        t.write("bob", 50)
        t.commit()

        t = db.begin()
        t.write("alice", 70)     # transfer $30 alice -> bob
        t.write("bob", 80)
        t.commit()

        print("After two committed transactions:", db.data)
        print("\nThe append-only WAL (intent logged before the deed):")
        show_log(path)

        # --- A transaction that crashes before its commit record -----------------
        # Simulate a process dying mid-commit: its 'set' records reach the log, but
        # the commit record never does (and data pages are never updated).
        print("\nSimulating a crash mid-transaction (logs writes, dies before commit)...")
        crash_tid = db._next_tid
        db._log({"t": crash_tid, "op": "set", "k": "alice", "v": 9999})  # bogus write
        db._sync()               # the partial writes ARE on disk...
        # ...but no commit record is ever written, and the process 'dies':
        db.close()

        # --- Session 2: restart and recover from the log -------------------------
        print("Restarting the database (recovering from the WAL)...")
        recovered = Database(path)
        print("Recovered state:", recovered.data)
        print("  -> committed transfers survived (REDO); the crashed transaction's")
        print("     write to alice=9999 left no trace (UNDO by omission).")
        recovered.close()

        # Self-checks so the demo verifies itself and exits non-zero on regression.
        assert recovered.data == {"alice": 70, "bob": 80}, "recovery must match committed state"
        assert recovered.data["alice"] != 9999, "uncommitted write must not survive"
        print("\nAll self-checks passed.")
    finally:
        if os.path.exists(path):
            os.unlink(path)


if __name__ == "__main__":
    main()
