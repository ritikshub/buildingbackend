#!/usr/bin/env python3
"""
A tiny transaction manager: Atomicity, Consistency, and Durability you can watch.

Companion to docs/en.md (Phase 03, Lesson 11 - Transactions & ACID). A transaction buffers
its writes and the store applies them in one atomic swap - but only if a consistency
invariant still holds - then flushes committed state to disk so it survives a restart.
Reference: Haerder & Reuter, "Principles of Transaction-Oriented Database Recovery" (1983),
which introduced the ACID term.

Runs standalone on the Python standard library only:  python transactions.py
"""
import json
import os
import tempfile


class ConsistencyError(Exception):
    """Raised when a commit would leave the database in an invalid state."""


class Transaction:
    def __init__(self, db: "Database"):
        self._db = db
        self.writes: dict[str, int] = {}   # buffered, provisional writes
        self.active = True

    def read(self, key: str):
        # Isolation (basic): see my own pending writes over the committed base.
        if key in self.writes:
            return self.writes[key]
        return self._db._data.get(key)

    def write(self, key: str, value: int) -> None:
        if not self.active:
            raise RuntimeError("transaction is no longer active")
        self.writes[key] = value      # NOT applied to the live store yet

    def commit(self) -> None:
        self._db._commit(self)
        self.active = False

    def rollback(self) -> None:
        self.writes.clear()           # throw the buffered writes away
        self.active = False


class Database:
    def __init__(self, path: str, invariant=None):
        self._path = path
        self._invariant = invariant or (lambda state: None)
        self._data: dict[str, int] = self._load()

    # --- durability: committed state lives in a file --------------------------
    def _load(self) -> dict:
        if os.path.exists(self._path) and os.path.getsize(self._path) > 0:
            with open(self._path) as f:
                return json.load(f)
        return {}

    def _flush(self) -> None:
        # Write to a temp file then atomically rename - a real durability trick.
        tmp = self._path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._data, f)
            f.flush()
            os.fsync(f.fileno())      # force bytes to disk before we trust them
        os.replace(tmp, self._path)   # atomic swap into place

    # --- the transaction API --------------------------------------------------
    def begin(self) -> Transaction:
        return Transaction(self)

    def _commit(self, txn: Transaction) -> None:
        # Build the would-be new state WITHOUT touching live data.
        new_state = {**self._data, **txn.writes}
        self._invariant(new_state)    # consistency: raises -> nothing changes
        self._data = new_state        # atomicity: one swap, all writes or none
        self._flush()                 # durability: committed state reaches disk

    def snapshot(self) -> dict:
        return dict(self._data)


def no_negative_balances(state: dict) -> None:
    bad = {k: v for k, v in state.items() if v < 0}
    if bad:
        raise ConsistencyError(f"negative balance(s): {bad}")


def total(db: Database) -> int:
    return sum(db.snapshot().values())


def main() -> None:
    tmp = tempfile.NamedTemporaryFile(prefix="txn_", suffix=".json", delete=False)
    tmp.close()
    path = tmp.name
    try:
        db = Database(path, invariant=no_negative_balances)
        db._data = {"alice": 100, "bob": 50}
        db._flush()
        print(f"Start: {db.snapshot()}   total={total(db)}\n")

        # 1) A successful transfer: atomic + durable, total conserved.
        print("1) Transfer $30 Alice -> Bob:")
        t = db.begin()
        t.write("alice", t.read("alice") - 30)
        t.write("bob", t.read("bob") + 30)
        t.commit()
        print(f"   committed: {db.snapshot()}   total={total(db)}  (conserved)\n")

        # 2) An overdraft: the invariant refuses the commit -> atomic rollback.
        print("2) Transfer $1000 Alice -> Bob (would overdraw):")
        t = db.begin()
        t.write("alice", t.read("alice") - 1000)   # buffered: alice would be -930
        t.write("bob", t.read("bob") + 1000)
        try:
            t.commit()
        except ConsistencyError as e:
            t.rollback()
            print(f"   commit REFUSED ({e})")
        print(f"   after:     {db.snapshot()}   <- Alice NOT debited (atomicity)\n")

        # 3) A crash mid-transaction: buffered writes never committed or flushed.
        print("3) Crash mid-transaction (write, then process dies before commit):")
        t = db.begin()
        t.write("alice", t.read("alice") - 20)      # buffered only
        # ... process 'crashes' here: we simply never call commit() ...
        del t
        reopened = Database(path)                    # reload from disk (a restart)
        print(f"   after restart: {reopened.snapshot()}  "
              f"<- uncommitted change never persisted (atomicity + durability)\n")

        # Self-checks so the demo verifies itself and exits non-zero on regression.
        assert db.snapshot() == {"alice": 70, "bob": 80}
        assert total(db) == 150, "money must be conserved across the committed transfer"
        assert reopened.snapshot() == {"alice": 70, "bob": 80}, "crash left no partial write"
        print("All self-checks passed.")
    finally:
        for p in (path, path + ".tmp"):
            if os.path.exists(p):
                os.unlink(p)


if __name__ == "__main__":
    main()
