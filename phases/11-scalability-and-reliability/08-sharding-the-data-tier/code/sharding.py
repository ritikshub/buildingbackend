#!/usr/bin/env python3
"""Measured companion to Phase 11, Lesson 08 — Sharding the Data Tier.

docs: phases/11-scalability-and-reliability/08-sharding-the-data-tier/docs/en.md
Sources: Karger et al., "Consistent Hashing and Random Trees", STOC 1997;
DeCandia et al., "Dynamo", SOSP 2007; Dean & Barroso, "The Tail at Scale",
CACM 56(2), 2013. Standard library only, seeded, self-terminating.
"""

import bisect
import hashlib
import math
import random
import time

SEED = 7
N_SHARDS = 8


def h64(key: str) -> int:
    """A stable 64-bit hash. Python's hash() is salted per process; this is not."""
    return int.from_bytes(hashlib.blake2b(key.encode(), digest_size=8).digest(), "big")


def pct(counts, total):
    return [100.0 * c / total for c in counts]


def imbalance(counts):
    hi, lo = max(counts), min(counts)
    return float("inf") if lo == 0 else hi / lo


LBL = 22


def row(label, shares, extra=""):
    cells = "".join(f"{s:6.1f}" for s in shares)
    print(f"  {label:<{LBL}}{cells}{extra}")


def head(first, tail=""):
    cells = "".join(f"{'s' + str(i):>6}" for i in range(N_SHARDS))
    print(f"  {first:<{LBL}}{cells}{tail}")


class Sampler:
    """Alias-free weighted sampler over a fixed categorical distribution."""

    def __init__(self, weights):
        self.cum, run = [], 0.0
        for w in weights:
            run += w
            self.cum.append(run)
        self.total = run

    def pick(self, rng):
        return bisect.bisect_left(self.cum, rng.random() * self.total)


# ---------------------------------------------------------------------------
# 1 · FOUR STRATEGIES, ONE WORKLOAD
# ---------------------------------------------------------------------------

def build_tenant_weights(n_tenants, whale_share, s):
    tail = [1.0 / ((i + 1) ** s) for i in range(n_tenants - 1)]
    t = sum(tail)
    return [whale_share] + [(1.0 - whale_share) * x / t for x in tail]


REGIONS = [
    ("us-east-1", 0.32), ("eu-west-1", 0.18), ("us-west-2", 0.12),
    ("ap-south-1", 0.11), ("ap-northeast-1", 0.08), ("sa-east-1", 0.06),
    ("eu-central-1", 0.09), ("af-south-1", 0.04),
]


def section1(rng):
    print("== 1 · FOUR STRATEGIES OVER THE SAME KEYSPACE ==")
    n_writes, n_tenants = 150_000, 500
    weights = build_tenant_weights(n_tenants, 0.40, 1.1)
    tenants = Sampler(weights)
    regions = Sampler([w for _, w in REGIONS])

    writes = []
    for i in range(n_writes):
        writes.append((tenants.pick(rng), 1_000_000 + i, regions.pick(rng)))

    per_tenant = [0] * n_tenants
    for t, _, _ in writes:
        per_tenant[t] += 1
    whale_pct = 100.0 * per_tenant[0] / n_writes
    next9 = 100.0 * sum(per_tenant[1:10]) / n_writes
    print(f"  {n_writes:,} writes, {n_tenants} tenants, {N_SHARDS} shards.")
    print(f"  tenant 0 (the enterprise account) is {whale_pct:.1f}% of all writes;")
    print(f"  the next 9 tenants together are {next9:.1f}%. tenant_id is assigned at")
    print("  signup, so low ids are old accounts and old accounts are the big ones.")
    print()
    head("strategy", "   max/min   hot   tenant-q")

    # (a) range on tenant_id: 8 contiguous tenant-id ranges
    width = n_tenants // N_SHARDS
    c = [0] * N_SHARDS
    for t, _, _ in writes:
        c[min(t // width, N_SHARDS - 1)] += 1
    row("range(tenant_id)", pct(c, n_writes),
        f"{imbalance(c):9.1f}x    s{c.index(max(c))}{1:>11}")
    range_tenant = c

    # (b) hash on tenant_id
    c = [0] * N_SHARDS
    for t, _, _ in writes:
        c[h64(f"t{t}") % N_SHARDS] += 1
    row("hash(tenant_id)", pct(c, n_writes),
        f"{imbalance(c):9.1f}x    s{c.index(max(c))}{1:>11}")
    hash_tenant = c

    # (c) hash on the row key itself
    c = [0] * N_SHARDS
    for _, oid, _ in writes:
        c[h64(f"o{oid}") % N_SHARDS] += 1
    row("hash(order_id)", pct(c, n_writes),
        f"{imbalance(c):9.1f}x    s{c.index(max(c))}{8:>11}")
    hash_row = c

    # (d) directory: greedy placement of tenants onto the least-loaded shard
    order = sorted(range(n_tenants), key=lambda t: -per_tenant[t])
    load = [0] * N_SHARDS
    placement = {}
    for t in order:
        s = load.index(min(load))
        placement[t] = s
        load[s] += per_tenant[t]
    whale_shard = placement[0]
    others = [load[i] for i in range(N_SHARDS) if i != whale_shard]
    row("directory(tenant_id)", pct(load, n_writes),
        f"{imbalance(load):9.1f}x    s{whale_shard}{1:>11}")
    directory = load

    # (e) geographic
    c = [0] * N_SHARDS
    for _, _, r in writes:
        c[r] += 1
    row("geographic(region)", pct(c, n_writes),
        f"{imbalance(c):9.1f}x    s{c.index(max(c))}{1:>11}")
    geo = c

    print()
    print(f"  hash(tenant_id) spreads 499 tenants perfectly and still puts "
          f"{100.0 * max(hash_tenant) / n_writes:.1f}% on one shard:")
    print("  hashing randomises PLACEMENT, it does not randomise VOLUME.")
    print(f"  directory isolates the whale on s{whale_shard} and balances the other 7 to "
          f"{imbalance(others):.2f}x of each other,")
    print("  but no tenant-keyed scheme can put a 40% tenant on less than 40% of a shard.")
    print(f"  hash(order_id) is the only balanced one ({imbalance(hash_row):.2f}x) and it is "
          "the only one")
    print("  where 'all orders for tenant X' has to ask all 8 shards.")
    print()
    return {
        "range_tenant": range_tenant, "hash_tenant": hash_tenant,
        "hash_row": hash_row, "directory": directory, "geo": geo,
        "whale_pct": whale_pct, "whale_shard": whale_shard,
        "n_writes": n_writes, "others_imb": imbalance(others),
    }


# ---------------------------------------------------------------------------
# 2 · THE MONOTONIC-KEY HOT TAIL
# ---------------------------------------------------------------------------

def section2(rng):
    print("== 2 · THE MONOTONIC KEY: A RANGE SHARD WITH SEVEN IDLE MACHINES ==")
    history = 1_000_000
    edge = history // N_SHARDS
    bounds = [edge * (i + 1) for i in range(N_SHARDS - 1)]
    print(f"  you sharded when the table held {history:,} rows and cut it into 8 equal")
    print(f"  order_id ranges: s0 = [0, {bounds[0]:,}), ... s7 = [{bounds[-1]:,}, inf).")
    n_new = 120_000
    new_ids = list(range(history, history + n_new))

    c = [0] * N_SHARDS
    for oid in new_ids:
        c[bisect.bisect_right(bounds, oid)] += 1
    range_share = pct(c, n_new)

    ch = [0] * N_SHARDS
    for oid in new_ids:
        ch[h64(f"o{oid}") % N_SHARDS] += 1
    hash_share = pct(ch, n_new)

    print(f"  then {n_new:,} new orders arrive. order_id is a sequence. Where do they go?")
    print()
    head("scheme", "   shards taking >1%")
    row("range(order_id)", range_share,
        f"{sum(1 for x in range_share if x > 1):>20}")
    row("hash(order_id)", hash_share,
        f"{sum(1 for x in hash_share if x > 1):>20}")
    print()

    # the cost of the fix: a contiguous scan
    window = 5_000
    lo = history + 40_000
    scan = list(range(lo, lo + window))
    r_shards = {bisect.bisect_right(bounds, o) for o in scan}
    h_shards = {h64(f"o{o}") % N_SHARDS for o in scan}
    print(f"  the fix is not free. 'SELECT * FROM orders WHERE order_id BETWEEN "
          f"{lo:,} AND {lo + window:,}'")
    print(f"    range(order_id): {len(r_shards)} shard   — a contiguous read, one machine")
    print(f"    hash(order_id) : {len(h_shards)} shards  — every row is somewhere else")
    print("  splitting the hot range does not help: split s7 and the new top range")
    print("  inherits 100% of the inserts. The hot tail follows the sequence, not the split.")
    print()
    return {"range": range_share, "hash": hash_share,
            "r_shards": len(r_shards), "h_shards": len(h_shards)}


# ---------------------------------------------------------------------------
# 3 · UNIFORM PLACEMENT, ZIPFIAN ACCESS
# ---------------------------------------------------------------------------

def section3(rng):
    print("== 3 · UNIFORM PLACEMENT IS NOT UNIFORM LOAD ==")
    n_keys, n_access, s = 50_000, 400_000, 1.25
    keys = [f"sku:{i}" for i in range(n_keys)]
    home = [h64(k) % N_SHARDS for k in keys]

    place = [0] * N_SHARDS
    for hshard in home:
        place[hshard] += 1

    zipf = Sampler([1.0 / ((i + 1) ** s) for i in range(n_keys)])
    hits = [0] * n_keys
    for _ in range(n_access):
        hits[zipf.pick(rng)] += 1

    load = [0] * N_SHARDS
    for i, hshard in enumerate(home):
        load[hshard] += hits[i]

    top = sorted(range(n_keys), key=lambda i: -hits[i])
    top_share = 100.0 * hits[top[0]] / n_access
    print(f"  {n_keys:,} keys placed by hash, {n_access:,} accesses drawn Zipf(s={s}).")
    print(f"  the hottest key is {top_share:.1f}% of all traffic and it lives on "
          f"s{home[top[0]]}.")
    print()
    head("measure", "   max/min")
    row("keys placed (%)", pct(place, n_keys), f"{imbalance(place):9.2f}x")
    row("load received (%)", pct(load, n_access), f"{imbalance(load):9.2f}x")
    print()

    # salt the hottest K keys across SALTS suffixes each
    SALTS = 16
    print(f"  now salt the hottest K keys into {SALTS} suffixes each "
          f"(key#0 .. key#{SALTS - 1}):")
    head("salted load", "   max/min   read fan-out")
    salt_rows = {}
    for K in (1, 4, 16):
        hot = set(top[:K])
        hot_traffic = sum(hits[i] for i in hot)
        salted = [0.0] * N_SHARDS
        touches = 0
        for i, hshard in enumerate(home):
            if i in hot:
                per = hits[i] / SALTS
                for r in range(SALTS):
                    salted[h64(f"{keys[i]}#{r}") % N_SHARDS] += per
                touches += hits[i] * SALTS
            else:
                salted[hshard] += hits[i]
                touches += hits[i]
        amp = touches / n_access
        hshare = 100.0 * hot_traffic / n_access
        row(f"salt top {K:<2d} ({hshare:4.1f}%)", pct(salted, n_access),
            f"{imbalance(salted):9.2f}x{amp:14.2f}x")
        salt_rows[K] = (imbalance(salted), amp, hshare)
    print()
    print(f"  salting the single hottest key ({salt_rows[1][2]:.1f}% of traffic) takes "
          f"imbalance from")
    print(f"  {imbalance(load):.2f}x to {salt_rows[1][0]:.2f}x for a "
          f"{salt_rows[1][1]:.2f}x read-amplification. Salting the top 16 buys")
    print(f"  {salt_rows[16][0]:.2f}x and costs {salt_rows[16][1]:.2f}x — because reading a "
          f"salted key means reading all")
    print(f"  {SALTS} pieces and summing them. Zipf has no bottom: there is always a next")
    print("  hottest key. Salt the key that is on fire, never the keyspace.")
    print()
    return {"place_imb": imbalance(place), "load_imb": imbalance(load),
            "top_share": top_share, "load": pct(load, n_access),
            "salt": salt_rows, "salts": SALTS, "hot_shard": home[top[0]]}


# ---------------------------------------------------------------------------
# 4 · SCATTER-GATHER AND THE TAIL
# ---------------------------------------------------------------------------

def quantile(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, int(q * len(sorted_vals)))
    return sorted_vals[idx]


def section4(rng):
    print("== 4 · SCATTER-GATHER: A FAN-OUT IS THE MAX OF S SAMPLES ==")
    pool_n, trials = 300_000, 120_000
    p_slow, xm, alpha = 0.01, 100.0, 1.5
    pool = []
    for _ in range(pool_n):
        if rng.random() < p_slow:
            pool.append(xm / (rng.random() ** (1.0 / alpha)))   # Pareto tail
        else:
            pool.append(12.0 * math.exp(rng.gauss(0.0, 0.45)))
    print(f"  one shard, {pool_n:,} sampled responses: {100 * (1 - p_slow):.0f}% fast,")
    print(f"  {100 * p_slow:.0f}% drawn from a Pareto(alpha={alpha}) tail starting at "
          f"{xm:.0f} ms.")
    print(f"  so p, the chance ONE shard is in the slow path, is exactly "
          f"{p_slow:.2f} by construction.")
    print()
    print("  shards      p50      p99     p999    p99 vs S=1   P(slow) meas    1-(1-p)^S")
    rows, base = [], None
    for S in (1, 2, 4, 8, 16):
        out, over = [], 0
        for _ in range(trials):
            m = pool[rng.randrange(pool_n)]
            for _ in range(S - 1):
                v = pool[rng.randrange(pool_n)]
                if v > m:
                    m = v
            out.append(m)
            if m > xm:
                over += 1
        out.sort()
        p50, p99, p999 = (quantile(out, 0.50), quantile(out, 0.99),
                          quantile(out, 0.999))
        base = p99 if base is None else base
        meas = 100.0 * over / trials
        pred = 100.0 * (1.0 - (1.0 - p_slow) ** S)
        print(f"  {S:6d} {p50:8.0f} {p99:8.0f} {p999:8.0f} {p99 / base:12.2f}x"
              f" {meas:13.2f}% {pred:11.2f}%")
        rows.append((S, p50, p99, p999, meas, pred))
    print()
    print("  a fan-out is only as fast as its slowest shard, so its latency is the")
    print("  MAXIMUM of S draws — and the maximum of S draws lives in the tail.")
    s8 = next(r for r in rows if r[0] == 8)
    print(f"  at S=8 a 1%-slow shard is a {s8[4]:.1f}% chance the QUERY is slow "
          f"(predicted {s8[5]:.1f}%),")
    print(f"  and p99 goes from {base:.0f} ms to {s8[2]:.0f} ms — {s8[2] / base:.1f}x — with "
          "no machine getting slower.")
    print("  every query that does not carry the shard key pays this, every time.")
    print()
    return {"rows": rows, "p99_one": base}


# ---------------------------------------------------------------------------
# 5 · RESHARDING: NAIVE MODULO vs RING vs VIRTUAL BUCKETS
# ---------------------------------------------------------------------------

class Ring:
    """Consistent hash ring (Karger et al., STOC 1997) with vnodes per shard."""

    def __init__(self, n_shards, vnodes):
        self.points = []
        for s in range(n_shards):
            for v in range(vnodes):
                self.points.append((h64(f"shard-{s}#{v}"), s))
        self.points.sort()
        self.keys = [p for p, _ in self.points]

    def owner(self, kh):
        i = bisect.bisect_right(self.keys, kh)
        return self.points[i % len(self.points)][1]


def bucket_map(n_buckets, n_shards, previous=None):
    """buckets -> shards. If `previous` is given, keep every bucket where it is
    unless a shard is over its fair share; that is the whole trick."""
    if previous is None:
        return [b % n_shards for b in range(n_buckets)]
    target = n_buckets / n_shards
    owned = {}
    for b, s in enumerate(previous):
        owned.setdefault(s, []).append(b)
    new = list(previous)
    donors = []
    for s, bs in owned.items():
        keep = int(math.floor(target))
        donors.extend(bs[keep:])
    need = [s for s in range(n_shards) if s not in owned]
    i = 0
    while donors and i < len(need) * math.ceil(target):
        new[donors.pop()] = need[i % len(need)]
        i += 1
    return new


def section5(rng):
    print("== 5 · RESHARDING 8 -> N: THE COST OF THE MAPPING YOU CHOSE ==")
    n_keys, n_buckets = 120_000, 4096
    khash = [h64(f"user:{i}") for i in range(n_keys)]

    base_ring = Ring(N_SHARDS, 160)
    base_ring_owner = [base_ring.owner(k) for k in khash]
    base_mod = [k % N_SHARDS for k in khash]
    base_bmap = bucket_map(n_buckets, N_SHARDS)
    base_bucket_owner = [base_bmap[k % n_buckets] for k in khash]

    print(f"  {n_keys:,} keys currently on {N_SHARDS} shards. How many rows move?")
    print()
    print("  8 ->    naive hash % N    consistent ring    4096 virtual buckets"
          "    buckets moved")
    for target in (9, 10, 12, 16):
        moved_mod = sum(1 for i, k in enumerate(khash)
                        if k % target != base_mod[i])
        r2 = Ring(target, 160)
        moved_ring = sum(1 for i, k in enumerate(khash)
                         if r2.owner(k) != base_ring_owner[i])
        bmap2 = bucket_map(n_buckets, target, base_bmap)
        moved_buk = sum(1 for i, k in enumerate(khash)
                        if bmap2[k % n_buckets] != base_bucket_owner[i])
        nbmoved = sum(1 for b in range(n_buckets) if bmap2[b] != base_bmap[b])
        print(f"  {target:<3d} {100.0 * moved_mod / n_keys:16.1f}%"
              f" {100.0 * moved_ring / n_keys:17.1f}%"
              f" {100.0 * moved_buk / n_keys:22.1f}%"
              f" {nbmoved:12d}/{n_buckets}")
    print()
    print("  going 8 -> 16 costs 50% under every scheme: the new shards have to be filled")
    print("  from somewhere. The difference is what happens when you want ONE more machine.")
    print("  naive hash % N cannot do it — 8 -> 9 rehashes 89% of the database — so it")
    print("  locks you into doubling forever, and doubling means buying 8 machines at once.")
    print()
    print("  and the invariant that matters most is not in the percentages:")
    print("    hash % N     : key -> shard. Change N and EVERY key's identity changes.")
    print("    ring         : key -> point on a ring -> shard. Stable, but the unit of")
    print("                   movement is 'whatever fell in this arc' — unnamed, unbounded.")
    print("    virtual bkt  : key -> bucket (FIXED FOREVER) -> shard (a table you edit).")
    print("                   The unit of movement is bucket 1743: nameable, resumable,")
    print("                   checkpointable, revertible by editing one row.")
    print()

    # ring balance with and without vnodes
    print("  a note on ring balance — vnodes are not optional:")
    for v in (1, 8, 160):
        r = Ring(N_SHARDS, v)
        c = [0] * N_SHARDS
        for k in khash:
            c[r.owner(k)] += 1
        print(f"    ring, {v:3d} vnode(s)/shard   max/min = {imbalance(c):5.2f}x"
              f"   hottest shard {100.0 * max(c) / n_keys:5.1f}%")
    print()

    # bucket count sweep
    print("  and choose the bucket count once, because it is the number you cannot change:")
    print("    buckets    at 9 shards    at 17 shards    at 40 shards")
    for nb in (16, 64, 256, 1024, 4096, 16384):
        cells = []
        for ns in (9, 17, 40):
            per = [0] * ns
            for b in range(nb):
                per[b % ns] += 1
            cells.append(f"{imbalance(per):.3f}x" if min(per) else "idle")
        print(f"    {nb:>7d}    {cells[0]:>11}    {cells[1]:>12}    {cells[2]:>12}")
    print("  16 buckets cannot balance 9 shards at all. 4096 is flat to 3 decimal places")
    print("  at every size you will ever run. Buckets are free; the wrong count is not.")
    print()
    return {"n_keys": n_keys, "n_buckets": n_buckets}


# ---------------------------------------------------------------------------
# 6 · THE MIGRATION: DOUBLE-WRITE, BACKFILL, VERIFY
# ---------------------------------------------------------------------------

def migrate(mode, n_rows=20_000, batch=200, writes_per_batch=60, settle=4_000):
    """Simulate a live backfill from the old topology to the new one.

    old/new are dicts row_id -> version; a production write bumps the version.
    Double-write, when on, upserts the whole row into `new` unconditionally.
      'backfill_first'  copy everything, THEN turn double-write on
      'blind_copy'      double-write on, but the copier writes its stale snapshot
      'guarded'         double-write on FIRST, copier inserts only if absent
    """
    rng = random.Random(SEED)                 # identical write stream in all three
    old = {r: 1 for r in range(n_rows)}
    new = {}
    dw = mode != "backfill_first"
    stale_copies = 0

    for start_id in range(0, n_rows, batch):
        ids = list(range(start_id, min(start_id + batch, n_rows)))
        snapshot = {r: old[r] for r in ids}          # the copier READS here

        for _ in range(writes_per_batch):            # production, mid-batch
            r = rng.randrange(n_rows)
            old[r] += 1
            if dw:
                new[r] = old[r]                      # double-write: blind upsert

        for r, v in snapshot.items():                # the copier WRITES here
            if mode == "guarded":
                if r not in new:                     # insert-if-absent
                    new[r] = v
                continue
            if old[r] != v:
                stale_copies += 1
            new[r] = v                               # unconditional overwrite

    for _ in range(settle):                          # double-write on everywhere now
        r = rng.randrange(n_rows)
        old[r] += 1
        new[r] = old[r]

    wrong = sum(1 for r in range(n_rows) if new.get(r) != old[r])
    return wrong, stale_copies


def section6(rng):
    print("== 6 · THE MIGRATION: ORDERING IS THE ENTIRE ALGORITHM ==")
    n_rows = 20_000
    print(f"  {n_rows:,} rows copied from the 8-shard topology to the 16-shard one while")
    print("  production keeps writing. Every row carries a version; a write bumps it.")
    print("  the write stream is byte-identical across all three runs. verify = compare")
    print("  every row in old against new once the dust has settled.")
    print()
    print(f"  {'procedure':<42}{'stale copies':>13}{'rows wrong':>13}{'verify':>9}")
    results = {}
    for mode, label in (
        ("backfill_first", "1. copy first, double-write after"),
        ("blind_copy", "2. double-write on, copier overwrites"),
        ("guarded", "3. double-write FIRST, insert-if-absent"),
    ):
        wrong, stale = migrate(mode, n_rows=n_rows)
        verdict = "PASS" if wrong == 0 else "FAIL"
        results[mode] = (wrong, stale, 100.0 * wrong / n_rows)
        print(f"  {label:<42}{stale:>13,}{wrong:>13,}{verdict:>9}")
    print()
    print("  run 1 loses every write that landed after its row was copied and before the")
    print("  flag went on. That window is the whole backfill — hours, on a real table.")
    print("  run 2 has double-writes on the entire time and STILL corrupts data: the")
    print("  copier read a value, a live write updated both copies, and then the copier")
    print("  wrote its stale value over the top. Copying is not idempotent unless it is")
    print("  conditional — insert-if-absent, or write-if-my-version-is-newer.")
    print("  run 3 turns double-write on before the first row is read and never writes")
    print("  backwards. 0 wrong rows, same 10,000 concurrent writes.")
    b = results["blind_copy"]
    print(f"  run 2's {b[2]:.2f}% sounds survivable until you scale it. Same rate on a")
    print(f"  500,000,000-row table is {int(5e8 * b[2] / 100):,} rows that are quietly, "
          "permanently wrong,")
    print("  and nothing in the migration reports it. That is what step 3 exists for.")
    print()

    # step 4: shadow reads
    old = {r: 1 for r in range(5_000)}
    new = dict(old)
    dropped = 0
    for _ in range(20_000):                     # a double-write path that drops 1 in 400
        r = rng.randrange(5_000)
        old[r] += 1
        if rng.random() > 0.0025:
            new[r] = old[r]
        else:
            dropped += 1
    sample = [rng.randrange(5_000) for _ in range(20_000)]
    bad = sum(1 for r in sample if new[r] != old[r])
    print("  step 4, shadow reads: serve 20,000 reads from OLD, run the same read against")
    print(f"  NEW, compare, report, discard. {dropped} of 20,000 double-writes were dropped")
    print(f"  ({100.0 * dropped / 20000:.2f}%) and {bad:,} shadow reads disagreed "
          f"({100.0 * bad / len(sample):.2f}%).")
    print("  a double-write path that drops 1 write in 400 shows up in no other metric:")
    print("  not error rate, not latency, not replication lag. Shadow reading is the only")
    print("  step that fails loudly while the blast radius is still zero.")
    print()


def main():
    t0 = time.perf_counter()
    rng = random.Random(SEED)
    section1(rng)
    section2(rng)
    section3(rng)
    section4(rng)
    section5(rng)
    section6(rng)
    print(f"  (total wall time {time.perf_counter() - t0:.1f} s)")


if __name__ == "__main__":
    main()
