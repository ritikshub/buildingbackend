"""
RAM & the Memory Hierarchy — a small fast cache in front of a big slow store.
Lesson: phases/00-foundations/06-ram-and-memory-hierarchy/docs/en.md

Models the core idea of the hierarchy: keep hot data on a fast upper rung so
most reads never pay the slow cost. Deterministic, no timing needed.
Run: python cache_demo.py
"""


class SlowStore:
    def __init__(self, data):
        self.data = data
        self.slow_reads = 0

    def get(self, key):
        self.slow_reads += 1          # a slow trip down the hierarchy (RAM/disk)
        return self.data[key]


class Cache:
    def __init__(self, store, size):
        self.store = store
        self.size = size
        self.box = {}
        self.hits = 0
        self.misses = 0

    def get(self, key):
        if key in self.box:           # cache HIT — fast
            self.hits += 1
            return self.box[key]
        self.misses += 1              # cache MISS — go to the slow store
        if len(self.box) >= self.size:
            self.box.pop(next(iter(self.box)))   # evict the oldest entry
        self.box[key] = self.store.get(key)
        return self.box[key]


def main() -> None:
    store = SlowStore({k: k * 10 for k in range(100)})
    cache = Cache(store, size=4)

    # A realistic workload: a few "hot" keys hit over and over (locality).
    hot_keys = [1, 2, 3, 1, 2, 1, 3, 2, 1, 2, 3, 1, 1, 2, 3] * 20
    for k in hot_keys:
        cache.get(k)

    total = cache.hits + cache.misses
    print(f"requests:      {total}")
    print(f"cache hits:    {cache.hits}")
    print(f"cache misses:  {cache.misses}")
    print(f"slow reads:    {store.slow_reads}  (only misses reach the slow store)")
    print(f"hit rate:      {cache.hits / total:.0%}")


if __name__ == "__main__":
    main()
