#!/usr/bin/env python3
"""
A self-balancing B-tree: the structure under almost every relational index.

Companion to docs/en.md (Phase 03, Lesson 09 - Indexes & the B-Tree). A B-tree keeps keys
sorted with high fanout, so any key on a huge table is only a few node-reads (page reads)
away, and it stays balanced by SPLITTING full nodes and pushing the median upward.
Reference: Bayer & McCreight, "Organization and Maintenance of Large Ordered Indexes" (1972).

Runs standalone on the Python standard library only:  python btree.py
"""


class BTreeNode:
    def __init__(self, leaf: bool = True):
        self.entries: list[tuple] = []   # sorted list of (key, value)
        self.children: list[BTreeNode] = []
        self.leaf = leaf


class BTree:
    """CLRS-style B-tree of minimum degree t: each node holds t-1 .. 2t-1 entries."""

    def __init__(self, t: int = 50):
        if t < 2:
            raise ValueError("minimum degree t must be >= 2")
        self.t = t
        self.root = BTreeNode(leaf=True)

    # --- search --------------------------------------------------------------
    def search(self, key):
        """Return (value, nodes_visited). nodes_visited = page reads to find it."""
        node, visited = self.root, 0
        while node is not None:
            visited += 1
            i = 0
            while i < len(node.entries) and key > node.entries[i][0]:
                i += 1
            if i < len(node.entries) and node.entries[i][0] == key:
                return node.entries[i][1], visited
            if node.leaf:
                return None, visited
            node = node.children[i]
        return None, visited

    # --- insert --------------------------------------------------------------
    def insert(self, key, value) -> None:
        root = self.root
        if len(root.entries) == 2 * self.t - 1:      # root full: grow UP a level
            new_root = BTreeNode(leaf=False)
            new_root.children.append(root)
            self._split_child(new_root, 0)
            self.root = new_root
            self._insert_nonfull(new_root, key, value)
        else:
            self._insert_nonfull(root, key, value)

    def _split_child(self, parent: BTreeNode, i: int) -> None:
        """Split full child parent.children[i]; lift its median entry into parent."""
        t = self.t
        full = parent.children[i]
        right = BTreeNode(leaf=full.leaf)
        median = full.entries[t - 1]                 # moves up into the parent
        right.entries = full.entries[t:]             # top t-1 entries -> new node
        full.entries = full.entries[:t - 1]          # bottom t-1 entries stay
        if not full.leaf:
            right.children = full.children[t:]
            full.children = full.children[:t]
        parent.entries.insert(i, median)
        parent.children.insert(i + 1, right)

    def _insert_nonfull(self, node: BTreeNode, key, value) -> None:
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

    # --- ordered traversal (range scans) ------------------------------------
    def range_scan(self, lo, hi):
        """Yield (key, value) for lo <= key <= hi, in sorted order."""
        yield from self._range(self.root, lo, hi)

    def _range(self, node, lo, hi):
        for i, (key, value) in enumerate(node.entries):
            if not node.leaf:
                yield from self._range(node.children[i], lo, hi)
            if lo <= key <= hi:
                yield key, value
        if not node.leaf:
            yield from self._range(node.children[len(node.entries)], lo, hi)

    # --- shape ---------------------------------------------------------------
    def height(self) -> int:
        h, node = 1, self.root
        while not node.leaf:
            node, h = node.children[0], h + 1
        return h


def _scramble(n: int):
    """A deterministic non-sorted key order (no randomness, so runs reproduce)."""
    # Multiply by a large odd constant mod n -> a fixed permutation of 0..n-1.
    step = 2654435761
    return [(i * step) % n for i in range(n)]


def main() -> None:
    N = 100_000
    t = 50                       # up to 2t-1 = 99 keys per node (fanout ~100)
    tree = BTree(t=t)
    for k in _scramble(N):
        tree.insert(k, f"row@{k}")

    print(f"Inserted {N:,} keys into a B-tree (min degree t={t}, up to "
          f"{2 * t - 1} keys/node).")
    print(f"Tree height: {tree.height()} levels  "
          f"->  finding ANY key is <= {tree.height()} node reads.\n")

    # One lookup: nodes visited vs. what a linear scan would average.
    needle = 61_803
    value, visited = tree.search(needle)
    print(f"search({needle}) -> {value!r}")
    print(f"  B-tree visited {visited} nodes; a linear scan averages ~{N // 2:,}. "
          f"That's ~{(N // 2) // visited:,}x fewer reads.\n")

    # Range scan returns keys already in sorted order (leaf-walk in a real B+-tree).
    lo, hi = 100, 115
    hits = list(tree.range_scan(lo, hi))
    print(f"range_scan({lo}, {hi}) -> {[k for k, _ in hits]}")
    print("  (already sorted - the tree maintains order for free)\n")

    # Height barely grows as size explodes: log_fanout(n).
    print("Height vs. size (why databases scale):")
    print("  keys        height")
    for n in (100, 1_000, 10_000, 100_000):
        sub = BTree(t=t)
        for k in _scramble(n):
            sub.insert(k, k)
        print(f"  {n:>9,}   {sub.height():>6}")

    # Self-checks so the demo verifies itself and exits non-zero on regression.
    assert value == f"row@{needle}"
    assert tree.search(N + 999) == (None, tree.search(N + 999)[1])  # missing key -> None
    assert [k for k, _ in hits] == sorted(k for k, _ in hits)
    assert visited <= tree.height()
    all_keys = [k for k, _ in tree.range_scan(0, N)]
    assert all_keys == sorted(set(range(N))), "range scan must return every key, in order"
    print("\nAll self-checks passed.")


if __name__ == "__main__":
    main()
