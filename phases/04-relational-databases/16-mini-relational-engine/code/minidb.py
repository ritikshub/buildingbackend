#!/usr/bin/env python3
"""
MiniDB: a tiny relational storage engine - B-tree index + WAL + transactions.

Capstone for Phase 03 (docs/en.md). It composes the pieces built earlier in the phase:
a B-tree access method (Lesson 09) for ordered key->row lookup, a write-ahead log
(Lesson 13) for durable, crash-safe commits, and a transaction manager (Lesson 11) for
atomic all-or-nothing writes. A committed put is logged-and-fsync'd first, THEN applied to
the index; recovery rebuilds the index by replaying committed writes from the log.

Runs standalone on the Python standard library only:  python minidb.py
"""
import json
import os
import tempfile


# --- Access method: a B-tree index (key -> row), with upsert and range scan -----------

class BTreeNode:
    def __init__(self, leaf: bool = True):
        self.entries: list[tuple] = []      # sorted (key, value)
        self.children: list[BTreeNode] = []
        self.leaf = leaf


class BTree:
    """CLRS B-tree of minimum degree t; supports set (upsert), search, and range scan."""

    def __init__(self, t: int = 8):
        self.t = t
        self.root = BTreeNode(leaf=True)

    def search(self, key):
        node, hops = self.root, 0
        while node is not None:
            hops += 1
            i = 0
            while i < len(node.entries) and key > node.entries[i][0]:
                i += 1
            if i < len(node.entries) and node.entries[i][0] == key:
                return node.entries[i][1], hops
            if node.leaf:
                return None, hops
            node = node.children[i]
        return None, hops

    def _find(self, key):
        node = self.root
        while node is not None:
            i = 0
            while i < len(node.entries) and key > node.entries[i][0]:
                i += 1
            if i < len(node.entries) and node.entries[i][0] == key:
                return node, i
            if node.leaf:
                return None
            node = node.children[i]
        return None

    def set(self, key, value) -> None:
        """Upsert: update in place if the key exists, else insert."""
        found = self._find(key)
        if found is not None:
            node, i = found
            node.entries[i] = (key, value)
            return
        root = self.root
        if len(root.entries) == 2 * self.t - 1:
            new_root = BTreeNode(leaf=False)
            new_root.children.append(root)
            self._split_child(new_root, 0)
            self.root = new_root
            self._insert_nonfull(new_root, key, value)
        else:
            self._insert_nonfull(root, key, value)

    def _split_child(self, parent, i) -> None:
        t = self.t
        full = parent.children[i]
        right = BTreeNode(leaf=full.leaf)
        median = full.entries[t - 1]
        right.entries = full.entries[t:]
        full.entries = full.entries[:t - 1]
        if not full.leaf:
            right.children = full.children[t:]
            full.children = full.children[:t]
        parent.entries.insert(i, median)
        parent.children.insert(i + 1, right)

    def _insert_nonfull(self, node, key, value) -> None:
        i = len(node.entries) - 1
        if node.leaf:
            node.entries.append(None)
            while i >= 0 and key < node.entries[i][0]:
                node.entries[i + 1] = node.entries[i]
                i -= 1
            node.entries[i + 1] = (key, value)
        else:
            while i >= 0 and key < node.entries[i][0]:
                i -= 1
            i += 1
            if len(node.children[i].entries) == 2 * self.t - 1:
                self._split_child(node, i)
                if key > node.entries[i][0]:
                    i += 1
            self._insert_nonfull(node.children[i], key, value)

    def items(self):
        yield from self._inorder(self.root)

    def _inorder(self, node):
        for i, entry in enumerate(node.entries):
            if not node.leaf:
                yield from self._inorder(node.children[i])
            yield entry
        if not node.leaf:
            yield from self._inorder(node.children[len(node.entries)])

    def range(self, lo, hi):
        return [(k, v) for k, v in self.items() if lo <= k <= hi]


# --- The engine: transactions + WAL over the B-tree index -----------------------------

class Transaction:
    def __init__(self, db: "MiniDB", tid: int):
        self._db = db
        self.tid = tid
        self.writes: list[tuple] = []

    def put(self, key, row) -> None:
        self.writes.append((key, row))         # buffered until commit

    def commit(self) -> None:
        # Layers meet here: WAL first (durable, atomic), THEN the index (findable).
        for key, row in self.writes:
            self._db._log({"t": self.tid, "op": "put", "k": key, "v": row})
        self._db._log({"t": self.tid, "op": "commit"})
        self._db._sync()                       # fsync = the durable commit point
        for key, row in self.writes:
            self._db.index.set(key, row)

    def rollback(self) -> None:
        self.writes.clear()                    # no commit record was ever written


class MiniDB:
    def __init__(self, wal_path: str):
        self.wal_path = wal_path
        self.index = BTree(t=8)
        self._next_tid = 1
        self._recover()                        # rebuild the index from the log
        self._wal = open(wal_path, "a")

    def _recover(self) -> None:
        if not os.path.exists(self.wal_path):
            return
        with open(self.wal_path) as f:
            records = [json.loads(line) for line in f if line.strip()]
        committed = {r["t"] for r in records if r["op"] == "commit"}
        max_tid = 0
        for r in records:
            max_tid = max(max_tid, r["t"])
            if r["op"] == "put" and r["t"] in committed:   # redo committed, in order
                self.index.set(r["k"], r["v"])
        self._next_tid = max_tid + 1

    def begin(self) -> Transaction:
        tid = self._next_tid
        self._next_tid += 1
        return Transaction(self, tid)

    def _log(self, record: dict) -> None:
        self._wal.write(json.dumps(record) + "\n")

    def _sync(self) -> None:
        self._wal.flush()
        os.fsync(self._wal.fileno())

    def get(self, key):
        value, _hops = self.index.search(key)
        return value

    def scan(self, lo, hi):
        return self.index.range(lo, hi)

    def close(self) -> None:
        self._wal.close()


def main() -> None:
    tmp = tempfile.NamedTemporaryFile(prefix="minidb_", suffix=".wal", delete=False)
    tmp.close()
    path = tmp.name
    try:
        db = MiniDB(path)

        # 1) Insert rows in a transaction, then commit.
        t = db.begin()
        t.put(3, {"name": "Grace Hopper", "email": "grace@navy.mil"})
        t.put(1, {"name": "Ada Lovelace", "email": "ada@analytical.org"})
        t.put(2, {"name": "Alan Turing", "email": "alan@bletchley.uk"})
        t.commit()
        print("Committed 3 rows.")

        # 2) Read one back by key (B-tree search).
        print("get(2) ->", db.get(2))

        # 3) Ordered range scan (B-tree keeps keys sorted, though we inserted 3,1,2).
        print("scan(1, 3) ->", [k for k, _ in db.scan(1, 3)])

        # 4) A rollback leaves no trace.
        t = db.begin()
        t.put(99, {"name": "Rolled Back"})
        t.rollback()
        print("after rollback, get(99) ->", db.get(99))

        # 5) An upsert through the same key updates in place.
        t = db.begin()
        t.put(1, {"name": "Ada Lovelace", "email": "ada@newmail.org"})
        t.commit()
        print("after upsert, get(1) ->", db.get(1))

        # 6) Simulate a crash: log a transaction's writes with NO commit record.
        print("\nSimulating a crash mid-transaction (write logged, no commit)...")
        crash_tid = db._next_tid
        db._log({"t": crash_tid, "op": "put", "k": 42, "v": {"name": "Ghost"}})
        db._sync()
        db.close()   # process 'dies' here

        # 7) Restart: rebuild the index from the WAL.
        print("Restarting (recovering from the WAL)...")
        db2 = MiniDB(path)
        print("scan(1, 100) ->", [k for k, _ in db2.scan(1, 100)])
        print("get(42) ->", db2.get(42), " (uncommitted crash write is gone)")
        print("get(1) ->", db2.get(1), " (upsert survived, in order)")

        # Self-checks so the demo verifies itself and exits non-zero on regression.
        assert db2.get(2)["name"] == "Alan Turing"
        assert [k for k, _ in db2.scan(1, 100)] == [1, 2, 3], "committed rows survive, in order"
        assert db2.get(42) is None, "uncommitted crash write must not survive"
        assert db2.get(1)["email"] == "ada@newmail.org", "committed upsert must survive"
        db2.close()
        print("\nAll self-checks passed.")
    finally:
        if os.path.exists(path):
            os.unlink(path)


if __name__ == "__main__":
    main()
