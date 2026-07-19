#!/usr/bin/env python3
"""
Ordering, partition keys and parallel consumers - measured, not asserted.

Companion to docs/en.md (Phase 6, Lesson 07). Builds on Lesson 05's append-only
log by splitting it into N independent partitions, then runs one causally
ordered workload (Created -> Updated -> Updated -> Deleted per account) through
a consumer group under every partitioning strategy and counts what breaks:
round-robin destroys per-entity order, hash-by-key preserves it exactly, key
skew wastes consumers, growing the partition count remaps most keys, a
rebalance replays uncommitted work, and internal worker pools throw the
ordering away again after the broker went to such trouble to give it to you.

Ordering vocabulary follows Lamport, "Time, Clocks, and the Ordering of Events
in a Distributed System", CACM 21(7), 1978: we enforce a partial order (per
key), never a total one.

Deterministic: every RNG is seeded, the hash is explicit, and the clock is
virtual, so two runs print identical output.

Standard library only:  python partitioned_log.py
"""

from __future__ import annotations

import hashlib
import random
from bisect import bisect
from collections import Counter
from dataclasses import dataclass

SEED = 4093

# The causal sequence every account goes through. Version numbers ARE the
# happens-before relation, written down where a consumer can check it.
LIFECYCLE = [(1, "Created"), (2, "Updated"), (3, "Updated"), (4, "Deleted")]
NEXT_STATE = {"Created": "ACTIVE", "Updated": "ACTIVE", "Deleted": "GONE"}

N_ENTITIES = 300                 # 300 accounts x 4 events = 1,200 records
PARTITIONS = 6
COMMIT_EVERY = 25                # offsets committed every 25 records per partition

# Consumers are never identical: different hosts, different GC timing, noisy
# neighbours. Milliseconds of service time per record, per consumer.
SPEED = [1.0, 1.9, 0.7, 1.4, 1.1, 2.2, 0.9, 1.6, 1.3]


def stable_hash(key: str) -> int:
    """The partitioner's hash must be explicit and stable across processes.

    Python's built-in hash() of a str is randomised per interpreter (PEP 456,
    SipHash), so using it would send the same key to a different partition
    after every restart - silently breaking ordering. Kafka ships its own
    murmur2 for exactly this reason.
    """
    return int.from_bytes(hashlib.blake2b(key.encode(), digest_size=8).digest(), "big")


# --- the record and the partitioned log --------------------------------------

@dataclass
class Record:
    key: str                     # the partition key: the account id
    etype: str
    version: int                 # position in this key's causal sequence
    msg_id: str
    partition: int = -1
    offset: int = -1             # offset within its partition (Lesson 05)
    seq: int = -1                # position in the producer's global stream


class PartitionedLog:
    """N independent append-only logs. Order is total within a partition and
    undefined across partitions. That is the whole guarantee."""

    def __init__(self, n_partitions: int, partitioner) -> None:
        self.n = n_partitions
        self.partitioner = partitioner
        self.partitions: list[list[Record]] = [[] for _ in range(n_partitions)]

    def append(self, rec: Record) -> int:
        p = self.partitioner(rec, self.n)
        rec.partition, rec.offset = p, len(self.partitions[p])
        self.partitions[p].append(rec)
        return p

    def extend(self, records) -> "PartitionedLog":
        for r in records:
            self.append(Record(r.key, r.etype, r.version, r.msg_id, seq=r.seq))
        return self

    @property
    def counts(self) -> list[int]:
        return [len(p) for p in self.partitions]

    @property
    def total(self) -> int:
        return sum(self.counts)


class RoundRobin:
    name = "round-robin"

    def __init__(self) -> None:
        self.i = -1

    def __call__(self, rec: Record, n: int) -> int:
        self.i += 1
        return self.i % n


class HashKey:
    name = "hash(key) % N"

    def __call__(self, rec: Record, n: int) -> int:
        return stable_hash(rec.key) % n


class SaltedHashKey:
    """Composite key: the hottest keys get a salt suffix so their traffic
    spreads. Buys distribution, pays for it with those keys' ordering."""

    def __init__(self, hot: set[str], fanout: int) -> None:
        self.hot, self.fanout, self.i = hot, fanout, -1
        self.name = f"hash(key+salt) % N  (top {len(hot)} keys, fanout {fanout})"

    def __call__(self, rec: Record, n: int) -> int:
        k = rec.key
        if k in self.hot:
            self.i += 1
            k = f"{k}#{self.i % self.fanout}"
        return stable_hash(k) % n


# --- consumer group assignment ------------------------------------------------

def range_assign(n_partitions: int, n_consumers: int) -> dict[int, list[int]]:
    """Deal partitions out in contiguous blocks, at most one consumer per
    partition. Consumers past the partition count get an empty list and idle."""
    out: dict[int, list[int]] = {}
    base, extra = divmod(n_partitions, n_consumers)
    p = 0
    for c in range(n_consumers):
        take = base + (1 if c < extra else 0)
        out[c] = list(range(p, p + take))
        p += take
    return out


# --- running a consumer group on a virtual clock ------------------------------

@dataclass
class Applied:
    t: float                     # virtual milliseconds
    who: int                     # consumer (or worker) that applied it
    rec: Record


def poll_order(log: PartitionedLog, parts: list[int]) -> list[Record]:
    """The records one consumer handles, in the order it handles them: a
    round-robin poll across its assigned partitions, each partition's own
    offset order preserved."""
    cur = {p: 0 for p in parts}
    out: list[Record] = []
    while True:
        moved = False
        for p in parts:
            if cur[p] < len(log.partitions[p]):
                out.append(log.partitions[p][cur[p]])
                cur[p] += 1
                moved = True
        if not moved:
            return out


def service_time(rnd: random.Random, speed: float) -> float:
    """Milliseconds to handle one record. Most are quick; roughly one in ten
    misses a cache or retries an upstream and takes several times longer. That
    tail is what lets a later record overtake an earlier one."""
    x = rnd.random()
    return speed * (8.0 * x if x > 0.9 else 1.0 + 0.35 * x)


def run_group(log: PartitionedLog, assignment: dict[int, list[int]],
              seed_offset: int = 0) -> list[Applied]:
    """Each consumer processes its own records serially at its own speed.
    The global apply order is what the outside world observes."""
    rnd = random.Random(SEED + seed_offset)
    timeline: list[Applied] = []
    for c, parts in sorted(assignment.items()):
        t, speed = 0.0, SPEED[c % len(SPEED)]
        for rec in poll_order(log, parts):
            t += service_time(rnd, speed)
            timeline.append(Applied(round(t, 6), c, rec))
    timeline.sort(key=lambda a: (a.t, a.who))
    return timeline


def apply_stream(timeline: list[Applied]):
    """Apply events to per-key state and report the damage.

    An *inversion* is an event applied after a strictly newer version of the
    same key was already applied - the operational definition of out-of-order.
    The anomaly names are what the support ticket says.
    """
    high: dict[str, int] = {}
    state: dict[str, str] = {}
    anomalies: Counter[str] = Counter()
    inversions, damaged = 0, set()
    for a in timeline:
        r = a.rec
        h = high.get(r.key, 0)
        if r.version < h:
            inversions += 1
            damaged.add(r.key)
        high[r.key] = max(h, r.version)
        s = state.get(r.key, "NONE")
        if s == "GONE":
            anomalies["resurrected-deleted-row"] += 1
        elif s == "NONE" and r.etype == "Updated":
            anomalies["update-to-missing-row"] += 1
        elif s == "NONE" and r.etype == "Deleted":
            anomalies["delete-of-missing-row"] += 1
        elif s == "ACTIVE" and r.etype == "Created":
            anomalies["create-over-live-row"] += 1
        state[r.key] = NEXT_STATE[r.etype]
    return inversions, damaged, anomalies, state


def apply_versioned(timeline: list[Applied]):
    """The alternative to buying ordering: reject anything stale by version.
    Last-write-wins converges to the right final state from any arrival order."""
    high: dict[str, int] = {}
    state: dict[str, str] = {}
    rejected = 0
    for a in timeline:
        r = a.rec
        if r.version <= high.get(r.key, 0):
            rejected += 1
            continue
        high[r.key] = r.version
        state[r.key] = NEXT_STATE[r.etype]
    return rejected, state


def makespan(timeline: list[Applied]) -> float:
    return max(a.t for a in timeline) if timeline else 0.0


def imbalance(counts: list[int]) -> tuple[float, float, float]:
    """(max/min, max/mean, effective parallelism). The busiest partition sets
    the drain time, so effective parallelism is N divided by max/mean."""
    lo, hi = min(counts), max(counts)
    mean = sum(counts) / len(counts)
    return (hi / lo if lo else float("inf")), hi / mean, len(counts) * mean / hi


def trace(timeline: list[Applied], key: str) -> str:
    return " -> ".join(f"{a.rec.etype[:3]}v{a.rec.version}@c{a.who}"
                       for a in timeline if a.rec.key == key)


# --- workloads ----------------------------------------------------------------

def lifecycle_workload(n_entities: int) -> list[Record]:
    """Interleave n_entities' lifecycles into one stream. Per-entity causal
    order is preserved by construction; global order is arbitrary."""
    rnd = random.Random(SEED + 7)
    pending = {f"acct-{i:04d}": list(LIFECYCLE) for i in range(n_entities)}
    live = list(pending)
    stream: list[Record] = []
    while live:
        k = live[rnd.randrange(len(live))]
        v, et = pending[k].pop(0)
        stream.append(Record(k, et, v, f"{k}:v{v}"))
        if not pending[k]:
            live.remove(k)
    for i, r in enumerate(stream):
        r.seq = i
    return stream


def zipf_workload(n_keys: int, n_msgs: int, s: float = 1.0) -> list[Record]:
    """Real tenant traffic is Zipfian: rank r gets traffic proportional to
    1/r^s. One customer is always enormous."""
    rnd = random.Random(SEED + 11)
    cum, acc = [], 0.0
    for i in range(n_keys):
        acc += 1.0 / (i + 1) ** s
        cum.append(acc)
    out = []
    for i in range(n_msgs):
        k = f"tenant-{bisect(cum, rnd.random() * acc):04d}"
        out.append(Record(k, "Event", 1, f"{k}:{i}", seq=i))
    return out


# --- consistent hashing, for the repartitioning comparison --------------------

class HashRing:
    """Keys and vnodes-per-partition land on one ring; a key belongs to the
    next node clockwise. Growing the ring moves only the slice beside the new
    nodes instead of remapping almost everything."""

    def __init__(self, n_partitions: int, vnodes: int = 200) -> None:
        ring = sorted((stable_hash(f"p{p}#{v}"), p)
                      for p in range(n_partitions) for v in range(vnodes))
        self.points = [h for h, _ in ring]
        self.owners = [p for _, p in ring]

    def of(self, key: str) -> int:
        return self.owners[bisect(self.points, stable_hash(key)) % len(self.points)]


# --- the rebalance --------------------------------------------------------------

def simulate_rebalance(log: PartitionedLog, n_consumers: int, dead: int,
                       kill_after: int, mode: str) -> dict:
    """Run a group, kill one consumer mid-flight, reassign, drain.

    'eager'       stop-the-world: every partition is revoked and reassigned,
                  so EVERY partition replays from its last commit.
    'cooperative' only the dead consumer's partitions move; everyone else
                  keeps their assignment and never replays.
    """
    assign = range_assign(log.n, n_consumers)
    processed = {p: 0 for p in range(log.n)}
    committed = {p: 0 for p in range(log.n)}
    delivered: list[str] = []

    def work(parts: list[int], budget: int | None = None) -> None:
        n = 0
        while budget is None or n < budget:
            moved = False
            for p in parts:
                if budget is not None and n >= budget:
                    break
                if processed[p] < len(log.partitions[p]):
                    delivered.append(log.partitions[p][processed[p]].msg_id)
                    processed[p] += 1
                    n += 1
                    moved = True
                    if processed[p] % COMMIT_EVERY == 0:
                        committed[p] = processed[p]
            if not moved:
                return

    for c, parts in sorted(assign.items()):          # steady state
        work(parts, kill_after)

    survivors = [c for c in range(n_consumers) if c != dead]
    revoked = list(range(log.n)) if mode == "eager" else list(assign[dead])
    replay = 0
    for p in revoked:                                # uncommitted work is redone
        replay += processed[p] - committed[p]
        processed[p] = committed[p]

    new_assign: dict[int, list[int]] = {c: [] for c in survivors}
    for i, p in enumerate(sorted(revoked)):
        new_assign[survivors[i % len(survivors)]].append(p)
    if mode == "cooperative":
        for c in survivors:
            new_assign[c] = sorted(set(new_assign[c]) | set(assign[c]))

    for c in survivors:                              # drain
        work(new_assign[c])

    seen: set[str] = set()
    dupes = 0
    for mid in delivered:
        if mid in seen:
            dupes += 1
        seen.add(mid)
    return {"mode": mode, "delivered": len(delivered), "unique": len(seen),
            "duplicates": dupes, "replay_window": replay, "revoked": len(revoked)}


# --- worker pools inside one consumer ------------------------------------------

def run_workers(records: list[Record], n_workers: int, rnd: random.Random,
                route_by_key: bool, speed: float):
    """Process one partition's records across a pool of worker threads.

    Same per-record service times as run_group, so n_workers=1 reproduces the
    serial consumer exactly and the throughput numbers stay comparable."""
    free = [0.0] * n_workers
    out: list[Applied] = []
    for r in records:
        w = (stable_hash(r.key) % n_workers if route_by_key
             else min(range(n_workers), key=lambda i: (free[i], i)))
        free[w] += service_time(rnd, speed)
        out.append(Applied(round(free[w], 6), w, r))
    out.sort(key=lambda a: (a.t, a.who))
    return out, (max(free) if free else 0.0)


def intra_partition(log: PartitionedLog, n_workers: int, route_by_key: bool,
                    seed_offset: int):
    rnd = random.Random(SEED + seed_offset)
    inv, damaged, anomalies, span = 0, set(), Counter(), 0.0
    for i_p, part in enumerate(log.partitions):
        tl, m = run_workers(part, n_workers, rnd, route_by_key,
                            SPEED[i_p % len(SPEED)])
        i, d, a, _ = apply_stream(tl)
        inv, damaged, anomalies, span = inv + i, damaged | d, anomalies + a, max(span, m)
    return inv, damaged, anomalies, span


# --- report -------------------------------------------------------------------

def row(label, parts, cons, inv, imb, eff, thr):
    print(f"  {label:<38} {parts:>4}  {cons:>4}  {inv:>7,}  {imb:>7.2f}  "
          f"{eff:>6.2f}  {thr:>9,.0f}")


def main() -> None:
    summary = []

    print("== 1. THE WORKLOAD: causally ordered, per entity ==")
    stream = lifecycle_workload(N_ENTITIES)
    print(f"  {N_ENTITIES} accounts x {len(LIFECYCLE)} lifecycle events = {len(stream):,} records")
    print(f"  per account the order is fixed: " +
          " -> ".join(f"{e}(v{v})" for v, e in LIFECYCLE))
    print(f"  across accounts nothing is ordered - we need a PARTIAL order, not a total one")
    print(f"  producer's global stream, first 8: " +
          " ".join(f"{r.key[-4:]}v{r.version}" for r in stream[:8]))

    print("\n== 2. ASSIGNMENT: parallelism is capped at the partition count ==")
    for n_cons in (3, 6, 9):
        a = range_assign(PARTITIONS, n_cons)
        idle = sum(1 for v in a.values() if not v)
        shown = "  ".join(f"c{c}:{v if v else '-'}" for c, v in sorted(a.items()))
        print(f"  {PARTITIONS} partitions, {n_cons} consumers -> {shown}")
        print(f"      {idle} consumer(s) idle, effective parallelism "
              f"{min(n_cons, PARTITIONS)}")

    print("\n== 3. THE CORE CONTRAST: same workload, two partitioners ==")
    results = {}
    for part in (RoundRobin(), HashKey()):
        log = PartitionedLog(PARTITIONS, part).extend(stream)
        tl = run_group(log, range_assign(PARTITIONS, PARTITIONS), seed_offset=3)
        inv, dmg, anom, state = apply_stream(tl)
        _, imb_mean, eff = imbalance(log.counts)
        thr = log.total / (makespan(tl) / 1000.0)
        wrong = sum(1 for v in state.values() if v != "GONE")
        results[part.name] = (log, tl, inv, dmg, anom, wrong)
        print(f"  {part.name:<16} partitions {log.counts}")
        print(f"      inversions {inv:>5,}   accounts damaged {len(dmg):>4} of {N_ENTITIES}"
              f"   wrong final state {wrong:>4}")
        print(f"      anomalies: " + ("  ".join(f"{k}={v}" for k, v in sorted(anom.items()))
                                      or "none - every event applied to a legal state"))
        summary.append((f"{part.name}, 6 consumers", PARTITIONS, PARTITIONS, inv,
                        imb_mean, eff, thr))

    rr_log, rr_tl, rr_inv, rr_dmg, _, _ = results["round-robin"]
    _, hk_tl, _, _, _, _ = results["hash(key) % N"]
    victim = sorted(rr_dmg)[0]
    print(f"  one damaged account, {victim}:")
    print(f"      round-robin : {trace(rr_tl, victim)}")
    print(f"      hash(key)   : {trace(hk_tl, victim)}")
    print(f"  nothing crashed and no record was lost - every consumer was correct alone")

    print("\n== 4. THE OTHER ANSWER: reject stale versions instead of buying order ==")
    rej, vstate = apply_versioned(rr_tl)
    wrong = sum(1 for v in vstate.values() if v != "GONE")
    print(f"  same out-of-order round-robin stream, handler adds `if v <= stored.v: skip`")
    print(f"  rejected {rej:,} stale events   accounts in the WRONG final state: {wrong}"
          f" of {N_ENTITIES}")
    print(f"  {rr_inv:,} inversions, 0 corrupted rows: the ordering requirement was removed,")
    print(f"  not satisfied. Intermediate states are still skipped - that is the price.")

    print("\n== 5. KEY SKEW: Zipfian tenants against a hash partitioner ==")
    n_keys, n_msgs, skew_parts = 500, 20_000, 16
    zstream = zipf_workload(n_keys, n_msgs)
    freq = Counter(r.key for r in zstream)
    top = [k for k, _ in freq.most_common(3)]
    print(f"  {n_msgs:,} messages over {len(freq)} tenants (Zipf s=1.0), {skew_parts} partitions")
    print(f"  hottest tenants: " + "  ".join(
        f"{k}={freq[k]:,} ({100 * freq[k] / n_msgs:.1f}%)" for k in top))
    for part in (HashKey(), SaltedHashKey(set(top), fanout=8)):
        log = PartitionedLog(skew_parts, part).extend(zstream)
        ratio_mm, ratio_mean, eff = imbalance(log.counts)
        print(f"  {part.name}")
        print(f"      counts " + " ".join(f"{c:>5,}" for c in log.counts))
        print(f"      max {max(log.counts):,}  min {min(log.counts):,}  "
              f"mean {log.total / skew_parts:,.0f}   max/min {ratio_mm:.2f}   "
              f"max/mean {ratio_mean:.2f}")
        print(f"      effective parallelism {eff:.2f} of {skew_parts} consumers"
              f"   ({skew_parts - eff:.2f} wasted)")
    print(f"  the salt spreads the top 3 tenants over up to 8 partitions -")
    print(f"  and those 3 tenants, {100 * sum(freq[k] for k in top) / n_msgs:.1f}% of all"
          f" traffic, now have NO ordering guarantee at all")
    print(f"  adding consumers past {skew_parts} cannot help: the busiest partition still"
          f" holds one consumer's work")

    print("\n== 6. THE REPARTITION HAZARD: changing N remaps almost every key ==")
    keys = sorted(freq)
    for old_n, new_n in ((8, 12), (16, 32), (16, 17)):
        moved = sum(1 for k in keys
                    if stable_hash(k) % old_n != stable_hash(k) % new_n)
        ring_old, ring_new = HashRing(old_n), HashRing(new_n)
        rmoved = sum(1 for k in keys if ring_old.of(k) != ring_new.of(k))
        print(f"  {old_n:>3} -> {new_n:<3} partitions   modulo: {moved:>4} of {len(keys)} keys move"
              f" ({100 * moved / len(keys):5.1f}%)   consistent hash: {rmoved:>4}"
              f" ({100 * rmoved / len(keys):5.1f}%)   ideal {100 * (new_n - old_n) / new_n:5.1f}%")
    hazard_key = next(k for k in ("acct-%04d" % i for i in range(N_ENTITIES))
                      if stable_hash(k) % 8 != stable_hash(k) % 12)
    old_p, new_p = stable_hash(hazard_key) % 8, stable_hash(hazard_key) % 12
    print(f"  concrete: {hazard_key} lived in partition {old_p} of 8; after growing to 12"
          f" it lives in {new_p}")
    print(f"  its v1,v2 are still unconsumed backlog in p{old_p} while v3,v4 are appended"
          f" to p{new_p}")
    recs = [Record(hazard_key, e, v, f"{hazard_key}:v{v}") for v, e in LIFECYCLE]
    tl = ([Applied(40.0 + i, 0, r) for i, r in enumerate(recs[:2])] +
          [Applied(1.0 + i, 1, r) for i, r in enumerate(recs[2:])])
    tl.sort(key=lambda a: (a.t, a.who))
    inv, _, anom, _ = apply_stream(tl)
    print(f"  two consumers now own the same key at the same time:")
    print(f"      apply order {trace(tl, hazard_key)}")
    print(f"      inversions {inv}   anomalies "
          + "  ".join(f"{k}={v}" for k, v in sorted(anom.items())))
    print(f"  drain p{old_p} to zero lag BEFORE adding partitions and this window closes")

    print("\n== 7. REBALANCE: a consumer dies and uncommitted work is replayed ==")
    hlog = PartitionedLog(PARTITIONS, HashKey()).extend(stream)
    print(f"  {PARTITIONS} partitions, 3 consumers, offsets committed every"
          f" {COMMIT_EVERY} records; consumer 1 dies")
    for mode in ("eager", "cooperative"):
        r = simulate_rebalance(hlog, 3, dead=1, kill_after=140, mode=mode)
        print(f"  {mode:<12} revoked {r['revoked']}/{PARTITIONS} partitions   "
              f"delivered {r['delivered']:,}   unique {r['unique']:,}   "
              f"duplicates {r['duplicates']:>3} ({100 * r['duplicates'] / r['unique']:.1f}%)")
        print(f"      naive consumer: {r['delivered']:,} side effects, {r['duplicates']}"
              f" of them wrong")
        print(f"      idempotent consumer (Lesson 06, dedup on message id):"
              f" {r['unique']:,} side effects, 0 wrong")
    print(f"  a rebalance is a duplicate generator by construction - idempotency is")
    print(f"  what makes it survivable, and cooperative assignment is what makes it small")

    print("\n== 8. ORDER DIES INSIDE THE CONSUMER TOO ==")
    hash_log = results["hash(key) % N"][0]
    for workers, routed, label in ((1, False, "1 thread per partition (serial)"),
                                   (8, False, "8 threads, next-free-worker"),
                                   (8, True, "8 threads, routed by key")):
        inv, dmg, anom, span = intra_partition(hash_log, workers, routed, seed_offset=3)
        thr = hash_log.total / (span / 1000.0)
        print(f"  {label:<34} inversions {inv:>5,}   accounts damaged {len(dmg):>4}"
              f"   throughput {thr:>7,.0f}/s")
        summary.append((f"hash + {label}", PARTITIONS, PARTITIONS, inv,
                        imbalance(hash_log.counts)[1],
                        imbalance(hash_log.counts)[2], thr))
    print(f"  the broker handed the consumer a perfectly ordered partition and the")
    print(f"  consumer's own thread pool threw it away. Per-key routing keeps both.")

    print("\n== 9. SUMMARY ==")
    one = PartitionedLog(1, HashKey()).extend(stream)
    one_tl = run_group(one, range_assign(1, 1), seed_offset=3)
    one_inv, _, _, _ = apply_stream(one_tl)
    summary.insert(0, ("single partition (total order)", 1, 1, one_inv, 1.00, 1.00,
                       one.total / (makespan(one_tl) / 1000.0)))
    ninelog = PartitionedLog(PARTITIONS, HashKey()).extend(stream)
    nine_tl = run_group(ninelog, range_assign(PARTITIONS, 9), seed_offset=3)
    nine_inv, _, _, _ = apply_stream(nine_tl)
    summary.insert(3, ("hash(key) % N, 9 consumers (3 idle)", PARTITIONS, 9, nine_inv,
                       imbalance(ninelog.counts)[1], imbalance(ninelog.counts)[2],
                       ninelog.total / (makespan(nine_tl) / 1000.0)))
    print(f"  {'strategy':<38} {'part':>4}  {'cons':>4}  {'inver.':>7}  "
          f"{'mx/mean':>7}  {'eff.p':>6}  {'rec/s':>9}")
    for s in summary:
        row(*s)
    print(f"  a total order costs {summary[0][6]:,.0f}/s; partitioning by key buys"
          f" {summary[2][6] / summary[0][6]:.1f}x with the same guarantee where it matters")


if __name__ == "__main__":
    main()
