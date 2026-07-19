"""Phase 11, Lesson 07 — Read Replicas & Replication Lag (docs/en.md).

Simulates one primary and three asynchronous replicas over a WAL/LSN model to
measure stale reads, the three read-routing fixes, monotonic-read violations,
sync/async/quorum write latency and RPO, failover loss and split brain, and why
replicas never scale writes.  Stdlib only, seeded, deterministic.
Sources: PostgreSQL 16 docs ch.27 (High Availability, Load Balancing, Replication)
and ch.52.4 (pg_stat_replication); Terry et al., "Session Guarantees for Weakly
Consistent Replicated Data", PDIS 1994 (read-your-writes, monotonic reads).
"""

import math
import random
from bisect import bisect_right

SEED = 7
HORIZON_MS = 120_000          # 120 simulated seconds
GRID_MS = 2                   # lag traces are sampled every 2 ms
NG = HORIZON_MS // GRID_MS
WRITE_RATE_PER_MS = 0.4       # 400 commits/second on the primary, baseline
BURST_FROM, BURST_TO = 86_000.0, 94_000.0    # a nightly batch job
BURST_X = 6.0                 # ...at 6x the write rate
T_KILL = 90_000.0             # the primary dies in the middle of it
CALM_TO = BURST_FROM - 2_000  # sections 1-3 study STEADY STATE only

REPLICA_READ_MS = 1.1         # a read served by a replica (idle, close by)
PRIMARY_READ_MS = 1.8         # the same read on the busy primary


def pct(xs, p):
    """Percentile of an already-sorted list."""
    if not xs:
        return 0.0
    k = min(len(xs) - 1, max(0, int(round((p / 100.0) * (len(xs) - 1)))))
    return xs[k]


# ---------------------------------------------------------------------------
# THE WORLD: a primary WAL and three replicas, each with send / flush / replay
# positions that trail it by their own amount.
# ---------------------------------------------------------------------------

def ar1(rng, base, sigma, phi, floor):
    """A slow-moving, mean-reverting lag component sampled on the 2 ms grid."""
    out = [0.0] * NG
    x = base
    for i in range(NG):
        x = base + phi * (x - base) + rng.gauss(0.0, sigma)
        out[i] = x if x > floor else floor
    return out


class World:
    """A primary WAL and three replicas.

    A replica's position is bounded two different ways, and both bind at
    different times.  A LATENCY floor (wire + fsync + apply scheduling) sets how
    far behind it sits when it is keeping up.  A THROUGHPUT ceiling (bytes/ms it
    can flush and replay) sets what happens when the primary outruns it.  Real
    lag is min(latency floor, throughput ceiling), and the interesting failures
    are all in the second term.
    """

    def __init__(self, seed=SEED):
        rng = random.Random(seed)
        self.rng = rng

        # --- the primary's write-ahead log --------------------------------
        # Baseline traffic, plus a batch job at 6x from t=86 s to t=94 s. The
        # batch job is also what kills the primary; that is not a coincidence.
        t, lsn = 0.0, 0
        self.wt, self.wl = [], []            # commit time (ms), LSN after it
        while True:
            rate = WRITE_RATE_PER_MS * (BURST_X if BURST_FROM <= t < BURST_TO else 1.0)
            t += rng.expovariate(rate)
            if t >= HORIZON_MS:
                break
            lsn += 200 + int(rng.expovariate(1 / 50.0))   # ~250 B of WAL/commit
            self.wt.append(t)
            self.wl.append(lsn)
        self.total_lsn = lsn

        # --- three replicas ------------------------------------------------
        # net/disk/apply are latency components in ms.  flush_bw and apply_bw
        # are throughput ceilings in bytes/ms.  The primary produces ~100 B/ms
        # at baseline and ~600 B/ms during the batch job.
        # r2 hits a 12 s replay conflict at t=40 s: it RECEIVES everything and
        # applies almost nothing (a long analytics query holding a snapshot).
        specs = [
            # name          net  ns  disk  ds  apply as  flush_bw apply_bw conflict
            ("r1-same-az",  0.9, .15,  3.0, .6,   7.0, 2.5,  560.0,  500.0, None),
            ("r2-same-az",  1.1, .20,  4.0, .8,  11.0, 3.0,  580.0,  470.0, (40_000, 52_000)),
            ("r3-cross-az", 2.4, .40, 11.0, 2.0, 28.0, 9.0,  400.0,  320.0, None),
        ]
        self.names = [s[0] for s in specs]
        self.send_lag, self.flush_lag, self.replay_lag = [], [], []
        self.send_pos, self.flush_pos, self.replay_pos = [], [], []
        for (name, nb, ns, db, ds, ab, asg,
             flush_bw, apply_bw, conflict) in specs:
            net = ar1(rng, nb, ns, 0.97, 0.2)
            disk = ar1(rng, db, ds, 0.98, 0.5)
            appl = ar1(rng, ab, asg, 0.99, 1.0)
            abw = [apply_bw] * NG
            if conflict:
                lo, hi = conflict[0] // GRID_MS, conflict[1] // GRID_MS
                for i in range(lo, hi):
                    abw[i] = 30.0                 # replay is blocked, not slow
                for i in range(hi, min(NG, hi + 6_000)):
                    abw[i] = apply_bw * 1.8       # then it catches up flat out
            # The batch job congests the link and the standby's disk too.
            b0, b1 = int(BURST_FROM) // GRID_MS, int(BURST_TO) // GRID_MS
            for i in range(b0, min(NG, b1 + 1_500)):
                net[i] *= 3.5
                disk[i] *= 2.5

            sp = self._positions(net, None, None)
            fp = self._positions(disk, sp, flush_bw)
            rp = self._positions(appl, fp, abw)
            self.send_pos.append(sp)
            self.flush_pos.append(fp)
            self.replay_pos.append(rp)
            self.send_lag.append(self._lag_of(sp))
            self.flush_lag.append(self._lag_of(fp))
            self.replay_lag.append(self._lag_of(rp))
        self.k = len(specs)

    def lsn_at(self, t):
        """The primary's LSN at wall-clock time t."""
        i = bisect_right(self.wt, t)
        return self.wl[i - 1] if i else 0

    def t_of_lsn(self, lsn):
        """When the primary committed the write that produced this LSN."""
        i = bisect_right(self.wl, lsn)
        return self.wt[i - 1] if i else 0.0

    def _positions(self, lag, upstream, bw):
        """Position under a latency floor, an upstream bound and a bandwidth cap."""
        out = [0] * NG
        run = 0
        for i in range(NG):
            p = self.lsn_at(i * GRID_MS - lag[i])
            if upstream is not None:
                if upstream[i] < p:
                    p = upstream[i]
                cap = run + (bw[i] if isinstance(bw, list) else bw) * GRID_MS
                if cap < p:
                    p = int(cap)
            if p > run:                       # never un-apply WAL
                run = p
            out[i] = run
        return out

    def _lag_of(self, pos):
        """Honest lag: wall-clock age of the newest record this node has."""
        return [i * GRID_MS - self.t_of_lsn(pos[i]) for i in range(NG)]

    def cell(self, t):
        i = int(t) // GRID_MS
        return 0 if i < 0 else (NG - 1 if i >= NG else i)

    def replay(self, k, t):
        return self.replay_pos[k][self.cell(t)]

    def flush(self, k, t):
        return self.flush_pos[k][self.cell(t)]

    def lag_ms(self, k, t):
        return self.replay_lag[k][self.cell(t)]


def banner(s):
    print(f"\n== {s} ==")


# ---------------------------------------------------------------------------
# 1 · ASYNC REPLICATION AND THE STALE-READ RATE
# ---------------------------------------------------------------------------

def section1(w):
    banner("1 · ASYNC REPLICATION AND THE STALE-READ RATE")
    print(f"  primary: {len(w.wt):,} commits over {HORIZON_MS//1000} s "
          f"({WRITE_RATE_PER_MS*1000:.0f} commits/s, {w.total_lsn/1e6:.1f} MB of WAL)")
    print(f"  sections 1-3 use the CALM window (0-{CALM_TO/1000:.0f} s). Nothing is")
    print("  wrong here: no incident, no failover, every replica healthy.")

    # The honest lag distribution, sampled every 100 ms on each replica.
    print("  replica replay lag, sampled 1,200x per replica:")
    print("     replica          p50        p90        p99        max")
    for k in range(w.k):
        s = sorted(w.lag_ms(k, t) for t in range(0, int(CALM_TO), 100))
        print(f"     {w.names[k]:<14}{pct(s,50):7.1f}ms {pct(s,90):8.1f}ms "
              f"{pct(s,99):8.1f}ms {s[-1]:8.1f}ms")

    # Write, wait D ms, read from a random replica. Stale iff the replica has
    # not replayed as far as the LSN your own commit produced.
    cut = bisect_right(w.wt, CALM_TO - 6_000)
    samples = [(w.wt[i], w.wl[i]) for i in range(0, cut, 3)]
    rng = random.Random(SEED + 1)
    print(f"\n  {len(samples):,} write-then-read-a-replica trials per row:")
    print("     read delay      stale reads     what that delay is")
    labels = {5: "same-process read-back", 12: "HTTP 302 redirect after POST",
              25: "a fast SPA refetch", 50: "user clicks 'back'",
              100: "a slow page load", 250: "a human re-reads the page",
              1000: "a second later", 5000: "five seconds later"}
    curve = []
    for d in (5, 12, 25, 50, 100, 250, 1000, 5000):
        stale = sum(1 for t, l in samples if w.replay(rng.randrange(w.k), t + d) < l)
        rate = 100.0 * stale / len(samples)
        curve.append((d, rate))
        print(f"     {d:6d} ms    {rate:8.2f}%       {labels[d]}")

    d12 = dict(curve)[12]
    print(f"\n  THE HEADLINE: your redirect takes 12 ms. Your median replica is")
    print(f"  {pct(sorted(w.lag_ms(0,t) for t in range(0,int(CALM_TO),100)),50):.0f}-"
          f"{pct(sorted(w.lag_ms(2,t) for t in range(0,int(CALM_TO),100)),50):.0f} ms behind.")
    print(f"  {d12:.1f}% of read-after-write requests read a value older than the")
    print("  one the user just saved. Every one of them 'fixes itself' on refresh.")
    floor = dict(curve)[5000]
    print(f"\n  And read the bottom of the column: waiting 5 SECONDS still leaves")
    print(f"  {floor:.2f}% stale. The curve does not decay to zero — it decays to")
    print("  your WORST replica. r2 spends 12 s of this window with a replay")
    print("  conflict; a read routed there is stale no matter how long you wait.")
    print("  There is no delay you can add to a request that makes this correct.")
    return curve


# ---------------------------------------------------------------------------
# 2 · THE THREE FIXES COMPARED
# ---------------------------------------------------------------------------

def section2(w):
    banner("2 · THE THREE FIXES: NAIVE / STICKY WINDOW / LSN-PINNED")
    rng = random.Random(SEED + 2)
    N_READS = 60_000
    RAW_FRAC = 0.20        # share of reads that follow this session's own write
    CROSS_DEVICE = 0.08    # ...of which this share arrive on a second session
    STICKY_MS = 500.0      # how long "route me to the primary" lasts
    PIN_WAIT_MS = 10.0     # how long an LSN-pinned read waits for a replica
    POLL_MS = 2.0

    # Build one read trace, replayed identically through all three policies.
    cutw = bisect_right(w.wt, CALM_TO - 5_000)
    reads = []             # (t, required_lsn, same_session, wrote_at)
    for _ in range(N_READS):
        if rng.random() < RAW_FRAC:
            i = rng.randrange(cutw)
            t_w, lsn = w.wt[i], w.wl[i]
            same = rng.random() >= CROSS_DEVICE
            # the redirect, or a slower human/second-device re-read
            d = rng.lognormvariate(math.log(12.0), 0.45) if same \
                else rng.lognormvariate(math.log(900.0), 0.7)
            if t_w + d >= CALM_TO:
                continue
            reads.append((t_w + d, lsn, same, t_w))
        else:
            reads.append((rng.uniform(0, CALM_TO), 0, False, None))

    def run(policy):
        stale = on_primary = 0
        waited = 0.0
        lat = []
        for t, need, same, t_w in reads:
            if policy == "sticky" and same and t - t_w <= STICKY_MS:
                on_primary += 1
                lat.append(PRIMARY_READ_MS)
                continue
            if policy == "lsn":
                # Ask the router for a replica that has already replayed `need`.
                elapsed = 0.0
                while True:
                    ok = [k for k in range(w.k) if w.replay(k, t + elapsed) >= need]
                    if ok:
                        break
                    if elapsed >= PIN_WAIT_MS:
                        ok = None
                        break
                    elapsed += POLL_MS
                if ok is None:
                    on_primary += 1
                    waited += elapsed
                    lat.append(elapsed + PRIMARY_READ_MS)
                    continue
                waited += elapsed
                lat.append(elapsed + REPLICA_READ_MS)
                continue
            k = rng.randrange(w.k)
            if w.replay(k, t) < need:
                stale += 1
            lat.append(REPLICA_READ_MS)
        lat.sort()
        return stale, on_primary, waited, lat

    print(f"  {len(reads):,} reads. {RAW_FRAC:.0%} follow this session's own write;")
    print(f"  {CROSS_DEVICE:.0%} of those arrive on a second device/session.")
    print(f"  sticky window = {STICKY_MS:.0f} ms; LSN pin waits up to "
          f"{PIN_WAIT_MS:.0f} ms then falls back to the primary.")
    print(f"  replica read = {REPLICA_READ_MS} ms, primary read = {PRIMARY_READ_MS} ms.\n")
    print("     policy                 stale reads      reads on primary   "
          "mean read   p99 read")
    rows = {}
    for name, label in (("naive", "naive: always replica"),
                        ("sticky", "sticky-to-primary 500ms"),
                        ("lsn", "LSN-pinned read")):
        stale, prim, waited, lat = run(name)
        rows[name] = (stale, prim, sum(lat) / len(lat), pct(lat, 99))
        print(f"     {label:<24}{stale:6,} ({100*stale/len(reads):5.2f}%)   "
              f"{prim:7,} ({100*prim/len(reads):5.2f}%)   "
              f"{sum(lat)/len(lat):7.2f}ms  {pct(lat,99):7.2f}ms")

    ns, np_, _, _ = rows["naive"]
    ss, sp, _, _ = rows["sticky"]
    ls, lp, lm, _ = rows["lsn"]
    print(f"\n  sticky removed {100*(ns-ss)/max(1,ns):.1f}% of the stale reads and gave")
    print(f"  back {100*sp/len(reads):.2f}% of read traffic to the primary. The "
          f"{ss:,} it missed are")
    print("  the cross-device ones — the sticky flag lives in the wrong session.")
    print(f"  LSN pinning removed {100*(ns-ls)/max(1,ns):.0f}% of them and sent only "
          f"{100*lp/len(reads):.2f}% to the")
    print(f"  primary — {sp/max(1,lp):.1f}x less primary load than sticky — for "
          f"{lm-REPLICA_READ_MS:+.2f} ms of mean latency.")
    return rows


# ---------------------------------------------------------------------------
# 3 · MONOTONIC READS VIOLATED
# ---------------------------------------------------------------------------

def section3(w):
    banner("3 · MONOTONIC READS: WATCHING TIME RUN BACKWARDS")
    rng = random.Random(SEED + 3)
    print("  'backwards' = a read shows LESS committed data than a read this")
    print("  same session already saw. A comment appears, then disappears.")
    print("  A single replica's position only ever moves forward. The SET of")
    print("  replicas does not, and round-robin walks the set.\n")

    def run(mode, sessions, polls, every):
        back = hit_sessions = extra_primary = 0
        for s in range(sessions):
            t0 = rng.uniform(0, CALM_TO - polls * every - 10)
            seen, pin, hit = 0, s % w.k, False
            for i in range(polls):
                t = t0 + i * every
                if mode == "round-robin":
                    k = (s + i) % w.k
                elif mode == "pinned":
                    k = pin
                else:                                   # last-seen-LSN token
                    ok = [x for x in range(w.k) if w.replay(x, t) >= seen]
                    if not ok:
                        extra_primary += 1
                        seen = w.lsn_at(t)
                        continue
                    k = ok[(s + i) % len(ok)]
                pos = w.replay(k, t)
                if pos < seen:
                    back += 1
                    hit = True
                else:
                    seen = pos
            if hit:
                hit_sessions += 1
        return back, hit_sessions, extra_primary

    scenes = (
        ("A · one page load, 8 widgets fanned out 6 ms apart", 4_000, 8, 6.0),
        ("B · a feed polling every 250 ms for 30 s", 400, 120, 250.0),
    )
    for title, sess, polls, every in scenes:
        print(f"  {title}  ({sess:,} sessions)")
        print("     routing                        backwards events   "
              "sessions affected")
        for mode, label in (("round-robin", "round-robin over 3 replicas"),
                            ("pinned", "session pinned to one replica"),
                            ("lsn-token", "last-seen-LSN token")):
            back, hits, extra = run(mode, sess, polls, every)
            note = f"   (+{extra} primary reads)" if extra else ""
            print(f"     {label:<31}{back:10,}       {hits:5,}/{sess:,}{note}")
        print()
    print("  Scene A needs no incident at all: the gap between a 12 ms replica")
    print("  and a 33 ms one is larger than the gap between two parallel API")
    print("  calls on the same page. Scene B needs the replay conflict — a slow")
    print("  poll only goes backwards when one replica is badly behind.")
    print("  Both fixes cost one hash or one integer in a cookie.")


# ---------------------------------------------------------------------------
# 4 · SYNC vs ASYNC vs QUORUM
# ---------------------------------------------------------------------------

def section4(w):
    banner("4 · SYNC vs ASYNC vs QUORUM: LATENCY, RPO, AND THE STALL")
    rng = random.Random(SEED + 4)
    N = 30_000
    DUR_MS = 30_000.0
    STALL_FROM, STALL_TO = 12_000.0, 17_000.0

    def local_commit():
        return 0.35 + (rng.expovariate(1 / 0.10) if rng.random() > 0.02
                       else rng.expovariate(1 / 6.0))

    def ack(base):
        """Round trip to a standby: wire + its fsync + an occasional hiccup."""
        v = base + rng.expovariate(1 / (base * 0.35))
        if rng.random() < 0.004:
            v += rng.expovariate(1 / 12.0)
        return v

    BASE = {"same-az": 0.5, "cross-az": 1.4, "cross-region": 71.0}
    modes = {m: [] for m in ("async", "sync-1 same-az", "sync-1 cross-az",
                             "sync-1 cross-region", "quorum ANY 1 of 3",
                             "sync-1 (replica stalls 5 s)")}
    blocked = 0
    for i in range(N):
        t = DUR_MS * i / N
        lc = local_commit()
        a1, a2, a3 = ack(BASE["same-az"]), ack(BASE["same-az"]), ack(BASE["cross-az"])
        modes["async"].append(lc)
        modes["sync-1 same-az"].append(lc + a1)
        modes["sync-1 cross-az"].append(lc + a3)
        modes["sync-1 cross-region"].append(lc + ack(BASE["cross-region"]))
        modes["quorum ANY 1 of 3"].append(lc + min(a1, a2, a3))
        if STALL_FROM <= t < STALL_TO:
            blocked += 1
            modes["sync-1 (replica stalls 5 s)"].append(lc + (STALL_TO - t) + a1)
        else:
            modes["sync-1 (replica stalls 5 s)"].append(lc + a1)

    # RPO: at an instant, how many acknowledged commits are not yet FLUSHED on
    # the best-placed replica?  That is exactly what a failover at that instant
    # loses.  Sample the calm stretch and the batch-job stretch separately: the
    # difference between them is the whole point.
    def rpo_over(lo_t, hi_t, n):
        rows, lags = [], []
        for _ in range(n):
            t = rng.uniform(lo_t, hi_t)
            bk = max(range(w.k), key=lambda k: w.flush(k, t))
            best = w.flush(bk, t)
            rows.append(bisect_right(w.wl, w.lsn_at(t)) - bisect_right(w.wl, best))
            lags.append(w.flush_lag[bk][w.cell(t)])
        rows.sort()
        lags.sort()
        return rows, lags

    lost, lag_calm = rpo_over(1_000, BURST_FROM - 1_000, 600)
    lost_burst, lag_burst = rpo_over(BURST_FROM + 500, BURST_TO - 500, 600)

    print(f"  {N:,} commits. local fsync ~0.4 ms. Same-AZ RTT {BASE['same-az']} ms,")
    print(f"  cross-AZ {BASE['cross-az']} ms, cross-region {BASE['cross-region']} ms "
          "(AZ = Availability Zone).\n")
    print("     mode                            p50       p99       max     "
          "RPO (rows lost on failover)")
    for m, xs in modes.items():
        xs.sort()
        if m == "async":
            rpo = (f"p50 {pct(lost,50)} rows calm / "
                   f"{pct(lost_burst,50)} under load")
        elif m.startswith("quorum"):
            rpo = "0 — if you promote the acking replica"
        elif "stalls" in m:
            rpo = "0 rows, and 0 writes for 5 s"
        else:
            rpo = "0"
        print(f"     {m:<28}{pct(xs,50):7.2f}ms {pct(xs,99):7.2f}ms "
              f"{xs[-1]:8.2f}ms   {rpo}")

    a50 = pct(modes["async"], 50)
    s50 = pct(modes["sync-1 same-az"], 50)
    print(f"\n  Same-AZ sync costs {s50-a50:+.2f} ms at p50 ({s50/a50:.1f}x) — cheap.")
    print(f"  Cross-region sync costs "
          f"{pct(modes['sync-1 cross-region'],50)-a50:+.1f} ms per commit. At 400 "
          "commits/s that is")
    print("  a different product. Quorum ANY 1 of 3 pays min(3 acks), not one ack:")
    print(f"  p99 {pct(modes['quorum ANY 1 of 3'],99):.2f} ms vs "
          f"{pct(modes['sync-1 same-az'],99):.2f} ms for a single named standby.")
    print(f"  The stall row is the availability inversion: {blocked:,} commits "
          "blocked behind")
    print(f"  a healthy-looking replica, max wait {modes['sync-1 (replica stalls 5 s)'][-1]:.0f} ms. "
          "Your primary's uptime is now")
    print("  the AND of every synchronous standby. Quorum turns it into an OR.")
    print("\n  ASYNC RPO IS NOT ONE NUMBER. Rows lost if the primary dies now:")
    print(f"    on a calm system   p50 {pct(lost,50):5,}   p99 {pct(lost,99):5,}   "
          f"worst {lost[-1]:5,} acknowledged commits")
    print(f"    during the batch   p50 {pct(lost_burst,50):5,}   "
          f"p99 {pct(lost_burst,99):5,}   worst {lost_burst[-1]:5,} "
          "acknowledged commits")
    print(f"  {pct(lost_burst,99)/max(1,pct(lost,99)):.0f}x worse, and the batch job "
          "is exactly the thing most likely to")
    print("  kill the primary. Your RPO is your lag DURING the incident, never")
    print("  the median on the dashboard. The arithmetic is just a product:")
    print(f"    calm:  flush lag {pct(lag_calm,50):5.1f} ms x   400 commits/s = "
          f"{pct(lag_calm,50)*0.4:6.1f} rows  (measured {pct(lost,50)})")
    print(f"    load:  flush lag {pct(lag_burst,50):5.1f} ms x 2,400 commits/s = "
          f"{pct(lag_burst,50)*2.4:6.1f} rows  (measured {pct(lost_burst,50)})")
    return lost, lost_burst


# ---------------------------------------------------------------------------
# 5 · FAILOVER, THE DATA-LOSS WINDOW, AND SPLIT BRAIN
# ---------------------------------------------------------------------------

def section5(w):
    banner("5 · FAILOVER: THE LOSS WINDOW AND SPLIT BRAIN")
    print(f"  The primary dies at t = {T_KILL/1000:.0f}s, four seconds into the "
          f"{BURST_X:.0f}x batch job that")
    print("  was overloading it. Everything committed before that instant")
    print("  returned 200 OK to a caller. Here is where each replica actually was:\n")
    acked_lsn = w.lsn_at(T_KILL)
    acked_n = bisect_right(w.wl, acked_lsn)
    print("     replica          sent_lsn     flush_lsn    replay_lsn   "
          "flush lag   rows not durable")
    best_k, best_flush = 0, -1
    for k in range(w.k):
        s, f, r = (w.send_pos[k][w.cell(T_KILL)], w.flush(k, T_KILL),
                   w.replay(k, T_KILL))
        miss = acked_n - bisect_right(w.wl, f)
        flag = w.flush_lag[k][w.cell(T_KILL)]
        print(f"     {w.names[k]:<14}{s/1e6:9.4f} MB {f/1e6:10.4f} MB "
              f"{r/1e6:10.4f} MB {flag:9.1f}ms {miss:12,}")
        if f > best_flush:
            best_k, best_flush = k, f
    lost_n = acked_n - bisect_right(w.wl, best_flush)
    lost_ms = T_KILL - w.t_of_lsn(best_flush)
    print(f"\n  Promote the most-caught-up replica ({w.names[best_k]}):")
    print(f"    acknowledged commits ..................... {acked_n:,}")
    print(f"    acknowledged AND durable on the new primary {acked_n-lost_n:,}")
    print(f"    ACKNOWLEDGED AND GONE .................... {lost_n:,}")
    print(f"    the loss window .......................... the last "
          f"{lost_ms:.0f} ms before death")
    print("    errors returned to any of those callers .. 0")
    print(f"    RPO = flush lag x commit rate = {lost_ms:.0f} ms x 2,400/s = "
          f"{lost_ms*WRITE_RATE_PER_MS*BURST_X:.0f} rows  (measured: {lost_n})")
    worst = min(bisect_right(w.wl, w.flush(k, T_KILL)) for k in range(w.k))
    print(f"    promote the WRONG replica instead and it is {acked_n-worst:,} rows —")
    print(f"    {(acked_n-worst)/max(1,lost_n):.1f}x more. 'Promote by highest LSN' "
          "is not a nicety.")

    # ---- split brain -------------------------------------------------------
    print("\n  SPLIT BRAIN. The primary was not dead — it was partitioned. It")
    print("  cannot reach the replicas or the orchestrator, but the app servers")
    print("  in its own zone can still reach it, so it keeps accepting writes.")
    rng = random.Random(SEED + 5)
    HOT, COLD, HOT_SHARE = 200, 50_000, 0.2     # 20% of writes hit 200 hot rows
    RATE = WRITE_RATE_PER_MS                    # 400 writes/s on each side

    def keys_written(n):
        out = {}
        for _ in range(n):
            k = (rng.randrange(HOT) if rng.random() < HOT_SHARE
                 else HOT + rng.randrange(COLD))
            out[k] = out.get(k, 0) + 1
        return out

    for label, old_ms, promote_at in (
            ("no fencing — old primary runs until a human notices (25 s)",
             25_000.0, 5_000.0),
            ("lease fencing — 2 s TTL, promotion held until 5 s", 2_000.0, 5_000.0)):
        n_old = int(old_ms * RATE)
        overlap = max(0.0, old_ms - promote_at)
        n_new = int(overlap * RATE)
        old_k, new_k = keys_written(n_old), keys_written(n_new)
        both = set(old_k) & set(new_k)
        divergent = sum(old_k[k] for k in both) + sum(new_k[k] for k in both)
        print(f"\n     {label}")
        print(f"       writes the OLD primary accepted after the partition     "
              f"{n_old:,}")
        print(f"       writes the NEW primary accepted while it still ran       "
              f"{n_new:,}")
        print(f"       rows updated on BOTH timelines                           "
              f"{len(both):,}")
        print(f"       writes to those rows — unmergeable by any tool           "
              f"{divergent:,}")
        print(f"       writes that can never reach the new timeline             "
              f"{n_old:,}")
    print("\n  Fencing does not save the old primary's writes — nothing can. It")
    print("  bounds how many exist and it drives the DIVERGENT set to zero, which")
    print("  is the difference between 'we lost 12 s of orders' and 'two rows")
    print("  disagree and we cannot tell which is right'. The old primary can")
    print("  never simply rejoin: it holds WAL the new timeline never saw, so it")
    print("  must be rewound (pg_rewind) or rebuilt from a base backup.")


# ---------------------------------------------------------------------------
# 6 · REPLICAS DO NOT SCALE WRITES
# ---------------------------------------------------------------------------

def section6():
    banner("6 · REPLICAS SCALE READS. THEY NEVER SCALE WRITES.")
    C = 20_000        # what one node can do, ops/s
    D = 60_000        # total offered ops/s
    print(f"  One node does {C:,} ops/s. You are offered {D:,} ops/s.")
    print("  EVERY replica applies 100% of the writes; only the reads divide.")
    print("  read capacity of a replica = C - W. If W >= C, no number of")
    print("  replicas is enough.\n")
    print("     write %      W ops/s   R ops/s   replicas   total system work"
          "   amplif.   useful new machine")
    for f in (0.01, 0.05, 0.10, 1/6, 0.20, 0.25, 0.30, 0.33, 0.35):
        W, R = f * D, (1 - f) * D
        head = C - W
        if head <= 0:
            print(f"     {f*100:5.1f}%    {W:9,.0f} {R:9,.0f}   IMPOSSIBLE  "
                  "  — every replica is already saturated by writes alone")
            continue
        K = math.ceil(R / head)
        work = W + K * (W + R / K)          # primary + each replica
        print(f"     {f*100:5.1f}%    {W:9,.0f} {R:9,.0f} {K:10d}   "
              f"{work:15,.0f}   {work/D:6.2f}x   {head/C*100:9.0f}% reads")
    print("\n  Read the last column. It is the fraction of a NEW machine that")
    print("  serves users; the rest replays writes nobody asked it about.")
    print(f"  It crosses 50% at W = C/2 = {C//2:,} ops/s = a "
          f"{100*(C/2)/D:.1f}% write ratio.")
    print("  Past that, each replica you buy adds more write work to the system")
    print("  than the read work it relieves. That is the wall. Lesson 08 is the")
    print("  only way through it: split the write set across shards.")


def main():
    w = World()
    section1(w)
    section2(w)
    section3(w)
    section4(w)
    section5(w)
    section6()

    # A trace for the docs' lag-components diagram: r2 during its replay conflict.
    banner("APPENDIX · SEND vs FLUSH vs REPLAY LAG ON ONE REPLICA (r2)")
    print("  a 12 s query conflict on the standby starting at t = 40 s.")
    print("  send and flush stay flat — the WAL ARRIVED. Replay does not.")
    print("       t      send lag   flush lag   replay lag   replay bytes behind")
    for t in (36_000, 40_000, 43_000, 46_000, 49_000, 52_000, 55_000,
              58_000, 62_000, 70_000):
        i = w.cell(t)
        behind = w.lsn_at(t) - w.replay(1, t)
        print(f"   {t/1000:6.0f}s {w.send_lag[1][i]:9.2f}ms "
              f"{w.flush_lag[1][i]:10.2f}ms {w.replay_lag[1][i]:11.1f}ms "
              f"{behind/1024:14.1f} KB")
    print("\n  Three numbers, three different problems. A replica that has")
    print("  received everything and applied none of it is invisible to any")
    print("  metric that only watches the network.")


if __name__ == "__main__":
    main()
