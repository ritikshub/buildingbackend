#!/usr/bin/env python3
"""
Multi-Region: Global Traffic, Failover & Data Gravity -- Phase 11, Lesson 10.
Companion to phases/11-scalability-and-reliability/10-multi-region-and-failover/docs/en.md

Sources: ITU-T G.652 (single-mode fibre; group index ~1.468 at 1550 nm) for propagation
speed; RFC 1035 s3.2.1 and RFC 2181 s8 for DNS TTL semantics; Gilbert & Lynch, "Brewer's
Conjecture and the Feasibility of Consistent, Available, Partition-Tolerant Web Services"
(SIGACT News 33(2), 2002); Gray & Lamport, "Consensus on Transaction Commit" (ACM TODS
31(1), 2006). Standard library only, seeded with random.Random(7), exits in ~10 s.
"""

from __future__ import annotations

import bisect
import math
import random
import time

RNG = random.Random(7)
WALL_START = time.perf_counter()

# --- physical constants -----------------------------------------------------
C_VACUUM_KM_S = 299_792.458      # speed of light in vacuum, km/s
N_FIBRE = 1.4682                 # group index of single-mode fibre at 1550 nm (ITU-T G.652)
V_FIBRE_KM_S = C_VACUUM_KM_S / N_FIBRE
EARTH_R_KM = 6371.0


def banner(text: str) -> None:
    print(f"\n== {text} ==")


def pct(xs, p: float) -> float:
    """Percentile by nearest rank on a sorted copy."""
    s = sorted(xs)
    if not s:
        return 0.0
    k = min(len(s) - 1, max(0, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]


def great_circle_km(a, b) -> float:
    """Haversine distance between two (lat, lon) pairs, in km."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(math.sqrt(h))


def query_ms() -> float:
    """One database query's service time: median ~0.8 ms, long right tail."""
    return RNG.lognormvariate(math.log(0.8), 0.75)


# ---------------------------------------------------------------------------
# 1 - THE LATENCY BUDGET
# ---------------------------------------------------------------------------
# (lat, lon) of the metro each cloud region actually sits in.
SITES = {
    "us-east-1":      (39.04, -77.49),    # Ashburn, Virginia
    "us-west-2":      (45.84, -119.70),   # Boardman, Oregon
    "eu-west-1":      (53.35, -6.26),     # Dublin
    "eu-central-1":   (50.11, 8.68),      # Frankfurt
    "ap-northeast-1": (35.68, 139.69),    # Tokyo
    "ap-southeast-1": (1.35, 103.82),     # Singapore
    "ap-southeast-2": (-33.87, 151.21),   # Sydney
    "sa-east-1":      (-23.55, -46.63),   # Sao Paulo
}

# Typical round-trip times observed on the public internet between these regions.
# These are INPUTS to the model, not outputs of it -- the computed columns are derived.
TYPICAL_RTT_MS = {
    ("us-east-1", "us-west-2"): 62.0,
    ("us-east-1", "eu-west-1"): 75.0,
    ("us-east-1", "eu-central-1"): 88.0,
    ("us-east-1", "sa-east-1"): 116.0,
    ("us-west-2", "ap-northeast-1"): 96.0,
    ("eu-west-1", "ap-southeast-1"): 175.0,
    ("us-east-1", "ap-southeast-2"): 200.0,
}

CROSS_REGION_RTT_MS = TYPICAL_RTT_MS[("us-east-1", "eu-west-1")]   # the number used everywhere below
INTRA_AZ_RTT_MS = 0.10
CROSS_AZ_RTT_MS = 0.55
USER_BUDGET_MS = 200.0


def section1() -> None:
    banner("1 . THE SPEED OF LIGHT IS THE FIRST LINE OF YOUR ARCHITECTURE")
    print(f"  light in vacuum {C_VACUUM_KM_S:,.0f} km/s;  in single-mode fibre (n={N_FIBRE}) "
          f"{V_FIBRE_KM_S:,.0f} km/s")
    print("  minimum RTT = 2 x great-circle / fibre speed. No protocol, cache or CDN beats it.\n")
    print(f"  {'region pair':<32}{'distance':>11}{'min RTT':>10}{'typical':>10}{'overhead':>10}")
    ratios = []
    for (a, b), typical in TYPICAL_RTT_MS.items():
        km = great_circle_km(SITES[a], SITES[b])
        min_rtt = 2 * km / V_FIBRE_KM_S * 1000.0
        ratio = typical / min_rtt
        ratios.append(ratio)
        print(f"  {a + ' <-> ' + b:<32}{km:>9,.0f}km{min_rtt:>9.1f}ms{typical:>9.1f}ms{ratio:>9.2f}x")
    print(f"  the overhead ratio ({min(ratios):.2f}x-{max(ratios):.2f}x) is routing, switching,")
    print("  amplifiers and fibre that does not follow the great circle. Physics sets the floor;")
    print("  engineering only ever adds to it.\n")

    ny, london = (40.71, -74.01), (51.51, -0.13)
    km = great_circle_km(ny, london)
    floor = 2 * km / V_FIBRE_KM_S * 1000.0
    print(f"  New York <-> London: {km:,.0f} km -> one way {floor / 2:.1f} ms, "
          f"round trip {floor:.1f} ms at best.")
    print(f"  The fastest commercial transatlantic route sells {58.95:.2f} ms RTT "
          f"({58.95 / floor:.2f}x the floor).")
    print("  Nobody will sell you less, because nobody has a shorter piece of glass.\n")

    print("  where a round trip actually goes:")
    tiers = [
        ("same rack (top-of-rack switch)", INTRA_AZ_RTT_MS),
        ("same availability zone", 0.25),
        ("cross-AZ, same region", CROSS_AZ_RTT_MS),
        ("cross-region, same continent", 62.0),
        ("cross-region, transatlantic", CROSS_REGION_RTT_MS),
        ("cross-region, antipodal", 200.0),
    ]
    print(f"  {'hop':<34}{'RTT':>9}{'% of a 200 ms budget':>23}")
    for name, rtt in tiers:
        print(f"  {name:<34}{rtt:>7.2f}ms{rtt / USER_BUDGET_MS * 100:>21.1f}%")

    server_ms = 40.0
    print(f"\n  request composition against a {USER_BUDGET_MS:.0f} ms user budget")
    print(f"  (server work {server_ms:.0f} ms, one cross-region round trip "
          f"{CROSS_REGION_RTT_MS:.0f} ms):")
    print(f"  {'sequential cross-region round trips':<38}{'total':>10}   verdict")
    for n in range(0, 5):
        total = server_ms + n * CROSS_REGION_RTT_MS
        spare = USER_BUDGET_MS - total
        verdict = f"fits, {spare:.0f} ms spare" if spare >= 0 else f"BLOWN by {-spare:.0f} ms"
        print(f"  {n:<38}{total:>8.0f}ms   {verdict}")
    afford = int((USER_BUDGET_MS - server_ms) // CROSS_REGION_RTT_MS)
    print(f"  you can afford {afford} cross-region round trips per request. Design for {afford - 1}.")


# ---------------------------------------------------------------------------
# 2 - DATA GRAVITY
# ---------------------------------------------------------------------------
def section2() -> None:
    banner("2 . DATA GRAVITY: THE APP TIER MOVED, THE DATA TIER DID NOT")
    n_req, n_queries = 40_000, 6
    print(f"  one request = {n_queries} sequential queries. Same code, same database, "
          f"same query plan.")
    print(f"  {n_req:,} requests per configuration.\n")

    results = {}

    lat = []
    for _ in range(n_req):
        t = 0.0
        for _ in range(n_queries):
            t += CROSS_AZ_RTT_MS + query_ms()
        lat.append(t)
    results["app + db in the same region"] = lat

    lat = []
    for _ in range(n_req):
        t = 0.0
        for _ in range(n_queries):
            t += CROSS_REGION_RTT_MS + RNG.gauss(0, 1.5) + query_ms()
        lat.append(t)
    results["app in region B, db in region A"] = lat

    lat = []
    for _ in range(n_req):
        t = CROSS_REGION_RTT_MS + RNG.gauss(0, 1.5) + sum(query_ms() for _ in range(n_queries))
        lat.append(t)
    results["  ... batched into 1 round trip"] = lat

    lat = []
    for _ in range(n_req):
        t = CROSS_REGION_RTT_MS + RNG.gauss(0, 1.5) + max(query_ms() for _ in range(n_queries))
        lat.append(t)
    results["  ... parallelised, 1 round trip"] = lat

    base_p50 = pct(results["app + db in the same region"], 50)
    print(f"  {'configuration':<34}{'p50':>10}{'p99':>10}{'vs local':>11}")
    for name, xs in results.items():
        p50, p99 = pct(xs, 50), pct(xs, 99)
        print(f"  {name:<34}{p50:>8.1f}ms{p99:>8.1f}ms{p50 / base_p50:>10.1f}x")

    remote_p50 = pct(results["app in region B, db in region A"], 50)
    batched_p50 = pct(results["  ... batched into 1 round trip"], 50)
    print(f"\n  moving the app tier alone multiplied p50 by {remote_p50 / base_p50:.0f}x "
          f"({base_p50:.1f} ms -> {remote_p50:.1f} ms).")
    print(f"  {n_queries} queries x {CROSS_REGION_RTT_MS:.0f} ms of glass = "
          f"{n_queries * CROSS_REGION_RTT_MS:.0f} ms that no amount of CPU removes.")
    print(f"  batching the same {n_queries} queries into 1 round trip: "
          f"{remote_p50:.1f} ms -> {batched_p50:.1f} ms "
          f"({remote_p50 / batched_p50:.1f}x better, still {batched_p50 / base_p50:.0f}x local).")
    print("  the mitigation is real and it is not a fix: you are still 1 ocean from your data.")

    # egress: the line item nobody forecasts
    rows_per_query, bytes_per_row, rps = 25, 400, 2_000
    per_req_kb = n_queries * rows_per_query * bytes_per_row / 1024
    gb_per_month = (rps * n_queries * rows_per_query * bytes_per_row * 86_400 * 30) / 1e9
    print(f"\n  egress: {rps:,} req/s x {n_queries} queries x {rows_per_query} rows x "
          f"{bytes_per_row} B = {per_req_kb:.0f} KB/request")
    print(f"  = {gb_per_month:,.0f} GB/month crossing a region boundary. At $0.02/GB that is "
          f"${gb_per_month * 0.02:,.0f}/month")
    print("  to run the query you used to run for free. Nobody forecasts this line; everybody "
          "gets the invoice.")


# ---------------------------------------------------------------------------
# 3 - TOPOLOGIES
# ---------------------------------------------------------------------------
LAST_MILE_MS = 15.0          # user -> nearest region edge
SHARE_A, SHARE_B = 0.55, 0.45
WRITE_FRACTION = 0.20
FOREIGN_ENTITY_FRACTION = 0.08   # writes that touch an entity homed in the other region


def _latency_profile():
    """Monte-Carlo read and write latency for each topology."""
    n = 60_000
    out = {}

    def sample(kind: str, topo: str) -> float:
        near_a = RNG.random() < SHARE_A
        work = query_ms() * (3 if kind == "write" else 1)
        if topo == "active-passive":
            hop = LAST_MILE_MS if near_a else LAST_MILE_MS + CROSS_REGION_RTT_MS
        elif topo == "single-write-region":
            if kind == "read":
                hop = LAST_MILE_MS
            else:
                hop = LAST_MILE_MS if near_a else LAST_MILE_MS + CROSS_REGION_RTT_MS
        elif topo == "regional-ownership":
            if kind == "read":
                hop = LAST_MILE_MS
            else:
                foreign = RNG.random() < FOREIGN_ENTITY_FRACTION
                hop = LAST_MILE_MS + (CROSS_REGION_RTT_MS if foreign else 0.0)
        else:  # multi-master
            hop = LAST_MILE_MS
        return hop + work

    for topo in ("active-passive", "single-write-region", "regional-ownership", "multi-master"):
        out[topo] = {
            "read": [sample("read", topo) for _ in range(n)],
            "write": [sample("write", topo) for _ in range(n)],
        }
    return out


def _availability_year():
    """A year at 1-minute resolution. Each region fails independently; each topology
    reacts with its own detection lag, RTO and blast radius."""
    minutes = 365 * 24 * 60
    down = {"A": bytearray(minutes), "B": bytearray(minutes)}
    events = []
    for region in ("A", "B"):
        # ~4 region-impacting events/year, lognormal duration, median 55 min.
        t = 0
        while True:
            t += int(RNG.expovariate(1.0 / (minutes / 4.0)))
            if t >= minutes:
                break
            dur = int(RNG.lognormvariate(math.log(55), 0.9))
            dur = max(5, min(dur, 600))
            for m in range(t, min(minutes, t + dur)):
                down[region][m] = 1
            events.append((region, t, dur))

    # RTO per topology, in minutes: detect + decide + promote + redirect.
    RTO = {
        "active-passive": 34,        # manual: 4 detect, 10 decide, 15 promote, 5 redirect
        "single-write-region": 12,   # only the writer must be promoted
        "regional-ownership": 9,     # promote only the failed region's shards
        "multi-master": 6,           # nothing to promote; just move traffic
    }
    served = {k: 0.0 for k in RTO}
    offered = 0.0
    outage_start = {"A": -1, "B": -1}

    for m in range(minutes):
        a_down, b_down = down["A"][m], down["B"][m]
        for r, d in (("A", a_down), ("B", b_down)):
            if d and outage_start[r] < 0:
                outage_start[r] = m
            elif not d:
                outage_start[r] = -1
        offered += 1.0
        for topo, rto in RTO.items():
            if not a_down and not b_down:
                served[topo] += 1.0
                continue
            if a_down and b_down:
                continue  # both regions gone: nothing helps
            failed = "A" if a_down else "B"
            share = SHARE_A if failed == "A" else SHARE_B
            elapsed = m - outage_start[failed]
            recovered = elapsed >= rto
            if topo == "active-passive":
                # everything lives in A. Losing B costs nothing; losing A costs everything.
                if failed == "B":
                    served[topo] += 1.0
                else:
                    served[topo] += 1.0 if recovered else 0.0
            elif topo == "single-write-region":
                # reads are local everywhere; writes need the write region (A).
                if recovered:
                    lost = 0.0
                elif failed == "A":
                    # A's users are stranded AND every remaining user's writes fail.
                    lost = share + (1 - share) * WRITE_FRACTION
                else:
                    lost = share
                served[topo] += 1.0 - lost
            else:  # regional-ownership and multi-master
                served[topo] += 1.0 - (share if not recovered else 0.0)
    return served, offered, events, RTO


def _replication_lag():
    """Async cross-region replication lag samples, including a batch-write burst."""
    lags = []
    for i in range(30_000):
        base = CROSS_REGION_RTT_MS / 2.0 + RNG.lognormvariate(math.log(45), 0.5)
        if 12_000 <= i < 13_500:          # a bulk job saturates the replication stream
            base += RNG.uniform(400, 9_000)
        lags.append(base)
    return lags


def section3() -> None:
    banner("3 . FOUR TOPOLOGIES, ONE SIMULATED YEAR")
    prof = _latency_profile()
    served, offered, events, RTO = _availability_year()
    lags = _replication_lag()
    rpo_p50, rpo_p99 = pct(lags, 50) / 1000.0, pct(lags, 99) / 1000.0

    print(f"  users: {SHARE_A:.0%} near region A, {SHARE_B:.0%} near region B. "
          f"{WRITE_FRACTION:.0%} of operations are writes.")
    print(f"  cross-region RTT {CROSS_REGION_RTT_MS:.0f} ms, last mile {LAST_MILE_MS:.0f} ms, "
          f"{len(events)} region-impacting failures simulated over 365 days.\n")

    cost = {   # provisioned capacity / capacity a single region would need, and how much idles
        "active-passive": (2.0, 50),
        "single-write-region": (2.0, 0),
        "regional-ownership": (2.0, 0),
        "multi-master": (2.0, 0),
    }
    rpo = {
        "active-passive": rpo_p99,
        "single-write-region": rpo_p99,
        "regional-ownership": rpo_p99,
        "multi-master": rpo_p99,
    }
    print(f"  {'topology':<22}{'p99 read':>10}{'p99 write':>11}{'RTO':>7}{'RPO':>9}"
          f"{'avail':>10}{'cost':>7}{'idle $':>8}{'conflicts':>11}")
    conflicts = {"active-passive": "none", "single-write-region": "none",
                 "regional-ownership": "none", "multi-master": "YES"}
    for topo in ("active-passive", "single-write-region", "regional-ownership", "multi-master"):
        pr = pct(prof[topo]["read"], 99)
        pw = pct(prof[topo]["write"], 99)
        avail = served[topo] / offered
        c, idle = cost[topo]
        print(f"  {topo:<22}{pr:>8.1f}ms{pw:>9.1f}ms{RTO[topo]:>5}min{rpo[topo]:>7.2f}s"
              f"{avail * 100:>9.3f}%{c:>6.1f}x{idle:>7}%{conflicts[topo]:>11}")

    print(f"\n  every topology costs the same {cost['active-passive'][0]:.1f}x compute -- to survive "
          f"losing 1 of 2 regions each must hold 100% of demand.")
    print("  active-passive spends half of that on hardware that serves nobody until the day it "
          "is needed,")
    print("  which is also the day you find out whether it works.")
    ap_r, ro_r = pct(prof["active-passive"]["read"], 99), pct(prof["regional-ownership"]["read"], 99)
    print(f"  p99 read: active-passive {ap_r:.0f} ms vs regional-ownership {ro_r:.0f} ms "
          f"({ap_r / ro_r:.1f}x) -- {SHARE_B:.0%} of users cross an ocean to read.")
    sw_w = pct(prof["single-write-region"]["write"], 99)
    ro_w = pct(prof["regional-ownership"]["write"], 99)
    print(f"  p99 write: single-write-region {sw_w:.0f} ms vs regional-ownership {ro_w:.0f} ms "
          f"({sw_w / ro_w:.1f}x) -- pinning localises the write too.")

    print("\n  note the RPO column: it is IDENTICAL for all four. RPO is a property of the")
    print("  replication mechanism, not of the topology. Changing your topology does not change")
    print("  how much data you lose; only changing your replication does.\n")
    print(f"  RPO is measured, not chosen. Async cross-region replication lag over "
          f"{len(lags):,} samples,")
    print("  including a 5% window where a bulk job saturates the replication stream:")
    print(f"  {'p50':>8}{'p95':>10}{'p99':>10}{'max':>10}")
    print(f"  {pct(lags, 50):>6.0f}ms{pct(lags, 95) / 1000:>9.2f}s{pct(lags, 99) / 1000:>9.2f}s"
          f"{max(lags) / 1000:>9.2f}s")
    print(f"  your RPO is the tail, not the median: {rpo_p99:.2f}s of acknowledged writes exist "
          f"only in the")
    print("  primary at any instant. Lose the region now and they are gone. Quote the p99.\n")
    sync_write = [LAST_MILE_MS + CROSS_REGION_RTT_MS + query_ms() * 3 for _ in range(60_000)]
    ro_w = prof["regional-ownership"]["write"]
    print(f"  {'RPO target':<12}{'mechanism':<34}{'p50 write':>11}{'p99 write':>11}")
    print(f"  {'seconds':<12}{'async streaming replication':<34}{pct(ro_w, 50):>9.1f}ms"
          f"{pct(ro_w, 99):>9.1f}ms")
    print(f"  {'zero':<12}{'synchronous cross-region commit':<34}{pct(sync_write, 50):>9.1f}ms"
          f"{pct(sync_write, 99):>9.1f}ms")
    print(f"  RPO = 0 costs {pct(sync_write, 50) - pct(ro_w, 50):.0f} ms on EVERY write, forever, "
          f"including the 364 days")
    print(f"  nothing fails. That is one full cross-region round trip "
          f"({CROSS_REGION_RTT_MS:.0f} ms) inside your commit path.")


# ---------------------------------------------------------------------------
# 4 - DNS FAILOVER'S LONG TAIL
# ---------------------------------------------------------------------------
RECORD_TTL_S = 60.0
HEALTH_INTERVAL_S = 10.0
HEALTH_FAILURES = 3
DNS_PUSH_S = 5.0


def section4() -> None:
    banner("4 . DNS FAILOVER HAS A LONG TAIL. ANYCAST DOES NOT.")
    detect_s = HEALTH_INTERVAL_S * HEALTH_FAILURES
    switch_s = detect_s + DNS_PUSH_S
    print(f"  record TTL {RECORD_TTL_S:.0f}s. Health check every {HEALTH_INTERVAL_S:.0f}s, "
          f"{HEALTH_FAILURES} failures to declare dead -> {detect_s:.0f}s detection,")
    print(f"  +{DNS_PUSH_S:.0f}s to publish the new record = the authoritative answer changes at "
          f"t={switch_s:.0f}s.")
    print("  Nothing below is about the authoritative server. It is about who believes it.\n")

    # RFC 2181 s8: a TTL is an upper bound on caching. In practice resolvers apply floors,
    # clients cache above the resolver, and some runtimes never re-resolve at all.
    classes = [
        ("resolver honours the 60 s TTL", 0.62, RECORD_TTL_S, "uniform"),
        ("resolver enforces a 300 s floor", 0.22, 300.0, "uniform"),
        ("HTTP client / pool caches 30 min", 0.10, 1800.0, "uniform"),
        ("JVM default: cache forever", 0.05, 21600.0, "exp"),
        ("IP hard-coded in config", 0.01, math.inf, "never"),
    ]
    n = 200_000
    expiry = []
    for label, share, ttl, kind in classes:
        k = int(n * share)
        for _ in range(k):
            if kind == "never":
                expiry.append(math.inf)
            elif kind == "exp":
                expiry.append(switch_s + RNG.expovariate(1.0 / ttl))
            else:
                expiry.append(switch_s + RNG.uniform(0.0, ttl))
    expiry.sort()
    total = len(expiry)

    def stuck_fraction(t: float) -> float:
        """Fraction of clients whose cached answer is still the dead region at time t."""
        return (total - bisect.bisect_right(expiry, t)) / total

    checkpoints = [60, 300, 900, 3600]
    print(f"  {'client population':<36}{'share':>7}{'effective cache':>18}")
    for label, share, ttl, kind in classes:
        t = "forever" if ttl == math.inf else f"{ttl:.0f}s"
        print(f"  {label:<36}{share:>6.0%}{t:>18}")

    print(f"\n  traffic still resolving to the DEAD region, {total:,} clients:")
    print(f"  {'t':>8}{'DNS failover':>16}{'anycast withdrawal':>22}")
    for t in checkpoints:
        # BGP withdrawal: routes reconverge in seconds, and no client holds state.
        any_stuck = 1.0 if t < 2 else (0.004 if t < 30 else 0.0)
        print(f"  {t:>6}s{stuck_fraction(t) * 100:>14.2f}%{any_stuck * 100:>20.2f}%")

    for target in (0.50, 0.10, 0.05, 0.01):
        t = switch_s
        found = None
        while t < 24 * 3600:
            if stuck_fraction(t) < target:
                found = t
                break
            t += 5
        if found is None:
            print(f"  time for the dead region's share to fall below {target:>3.0%}: "
                  f"NEVER within 24 h")
        else:
            print(f"  time for the dead region's share to fall below {target:>3.0%}: "
                  f"{found:>7,.0f}s ({found / 60:>6.1f} min)")

    residual = stuck_fraction(3600)
    print(f"\n  one hour after a 60-second-TTL failover, {residual * 100:.2f}% of clients are still "
          f"aiming at the dead region.")
    print("  a 60 s TTL is a request, not a guarantee (RFC 2181 s8: the TTL is an upper bound on")
    print("  caching, and nothing forces a resolver to be honest about the lower one).")
    print("  anycast moves traffic by withdrawing a BGP route -- the client holds no state, so there")
    print("  is no tail. Note WHY its column starts at 0 immediately: on a hard region loss the BGP")
    print("  session dies with the region, so the withdrawal is automatic and needs no health check")
    print(f"  at all. A PARTIAL failure -- region up, application broken -- still costs the same "
          f"{detect_s:.0f}s")
    print("  of detection, and then reconverges in seconds instead of hours.")
    print("  the price of anycast: a route change can re-anchor an in-flight TCP connection at a")
    print("  different PoP, which resets it. Terminate TLS at the edge and that is a retry, not an")
    print("  outage; run stateful protocols over raw anycast and it is a bug report.")


# ---------------------------------------------------------------------------
# 5 - CONFLICTS
# ---------------------------------------------------------------------------
def section5() -> None:
    banner("5 . CONFLICTS: RESOLVE THEM, OR ARRANGE FOR THEM NOT TO EXIST")
    n_keys, partition_s, write_rate = 800, 120.0, 45.0
    clock_skew_s = 0.250       # region B's clock runs 250 ms fast. This is normal for NTP.
    away_rate = 0.08           # writes that arrive at a region other than the entity's home
    print(f"  a partition splits region A from region B for {partition_s:.0f}s. Both keep accepting "
          f"writes.")
    print(f"  {write_rate:.0f} writes/s over {n_keys} entities (Zipf-ish: 20% of entities take "
          f"80% of writes).")
    print(f"  every entity has a HOME region -- the region its owner lives in. "
          f"{1 - away_rate:.0%} of an entity's")
    print(f"  writes arrive there; {away_rate:.0%} arrive at the other region (roaming user, "
          f"an admin, a batch job).")
    print(f"  region B's clock is {clock_skew_s * 1000:.0f} ms fast -- an ordinary, healthy NTP "
          f"offset.\n")

    hot = int(n_keys * 0.2)
    home = {k: ("A" if RNG.random() < SHARE_A else "B") for k in range(n_keys)}
    writes = []          # (true_time, arrived_at, key, stamped_time)
    n_writes = int(write_rate * partition_s)
    for _ in range(n_writes):
        t = RNG.uniform(0, partition_s)
        key = RNG.randrange(hot) if RNG.random() < 0.8 else RNG.randrange(hot, n_keys)
        h = home[key]
        arrived = h if RNG.random() > away_rate else ("B" if h == "A" else "A")
        stamped = t + (clock_skew_s if arrived == "B" else 0.0)
        writes.append((t, arrived, key, stamped))
    writes.sort()

    per_key = {}
    for t, region, key, stamped in writes:
        per_key.setdefault(key, {"A": [], "B": []})[region].append((t, stamped))

    conflicted = [k for k, v in per_key.items() if v["A"] and v["B"]]
    print(f"  {n_writes:,} writes landed on {len(per_key)} distinct entities during the partition.")
    print(f"  entities written on BOTH sides = {len(conflicted)} "
          f"({len(conflicted) / len(per_key) * 100:.1f}% of entities touched)")
    print(f"  -- an {away_rate:.0%} stray-write rate is enough, because a hot entity is written "
          f"dozens of times.")

    # --- strategy 1: last-write-wins on wall clock.
    #     The losing side's entire divergent history is discarded. Every one of those writes
    #     was ACKNOWLEDGED to a client that has no way to find out.
    def lww(skew_s: float):
        n_lost = n_inv = 0
        for k in conflicted:
            v = per_key[k]
            best_a = max(v["A"], key=lambda x: x[0])
            best_b = max(v["B"], key=lambda x: x[0])
            stamp_a, stamp_b = best_a[0], best_b[0] + skew_s
            if stamp_a > stamp_b:
                n_lost += len(v["B"])
                if best_b[0] > best_a[0]:
                    n_inv += 1
            else:
                n_lost += len(v["A"])
                if best_a[0] > best_b[0]:
                    n_inv += 1
        return n_lost, n_inv

    lost, inversions = lww(clock_skew_s)

    # --- strategy 2: version vectors -- nothing is lost, everything becomes your problem
    vv_merges = len(conflicted)

    # --- strategy 3: home-region pinning. Only an entity's home region may write it.
    #     Normally a stray write is FORWARDED (+1 cross-region RTT). During the partition
    #     it cannot be forwarded, so it is rejected with an error the client can see.
    stray = sum(1 for _, region, key, _ in writes if region != home[key])
    rejected = stray

    print(f"\n  {'strategy':<26}{'conflicts':>11}{'writes lost':>13}{'silent?':>9}"
          f"{'rejected':>10}{'merges owed':>13}")
    print(f"  {'last-write-wins (clock)':<26}{len(conflicted):>11}{lost:>13}{'YES':>9}"
          f"{0:>10}{0:>13}")
    print(f"  {'version vectors':<26}{len(conflicted):>11}{0:>13}{'no':>9}"
          f"{0:>10}{vv_merges:>13}")
    print(f"  {'CRDT (if types fit)':<26}{len(conflicted):>11}{0:>13}{'no':>9}"
          f"{0:>10}{0:>13}")
    print(f"  {'home-region pinning':<26}{0:>11}{0:>13}{'-':>9}"
          f"{rejected:>10}{0:>13}")

    print(f"\n  LWW discarded {lost} acknowledged writes and told nobody -- the losing region's "
          f"entire")
    print(f"  divergent history for {len(conflicted)} entities. Every one of those writes returned "
          f"200 to a client.")
    print("\n  now vary only the clock. Same writes, same partition, different NTP health:")
    print(f"  {'clock offset on region B':<38}{'writes lost':>13}{'earlier write won':>20}")
    for skew, label in ((0.0, "0 ms (perfect clocks)"), (0.050, "50 ms (good NTP)"),
                        (0.250, "250 ms (ordinary NTP)"), (2.0, "2 s (NTP daemon died)"),
                        (10.0, "10 s (host drifted, nobody looked)")):
        l, inv = lww(skew)
        share = inv / max(1, len(conflicted)) * 100
        print(f"  {label:<38}{l:>13}{inv:>13} ({share:>4.1f}%)")
    print("  LWW is not 'the last write wins'. It is 'the write carrying the largest number wins',")
    print("  and that number comes from a clock you do not control and cannot audit after the fact.")
    print(f"  version vectors lose nothing and hand you {vv_merges} merge decisions -- correct, and")
    print("  someone still has to write the merge function for every type you store. CRDTs converge")
    print("  with no merge function, for the types that fit (counters, sets, sequences) -- and they")
    print("  carry per-replica metadata that grows with the number of replicas that ever wrote.")
    print("  home-region pinning has ZERO conflicts by construction. Its cost is honest and loud:")
    print(f"  {rejected:,} writes ({rejected / n_writes * 100:.1f}%) were REJECTED during the "
          f"partition, because their")
    print("  home region was unreachable and a stray write can no longer be forwarded. That is")
    print("  Gilbert & Lynch (2002) charging you for consistency in availability -- but the client")
    print("  got a 503 it can retry, not a silent data loss it will discover in a support ticket.")
    print(f"\n  and in NORMAL operation the same rule costs almost nothing: "
          f"{stray / n_writes * 100:.1f}% of writes arrive at")
    print(f"  the wrong region and are forwarded, paying +{CROSS_REGION_RTT_MS:.0f} ms. "
          f"{(1 - stray / n_writes) * 100:.1f}% of writes never leave "
          f"their region.")
    print(f"  one rule -- 'only the home region may write this entity' -- removed "
          f"{len(conflicted)} conflicts,")
    print(f"  {lost:,} silent losses and every merge function you were about to write.")


# ---------------------------------------------------------------------------
# 6 - THE EVACUATION
# ---------------------------------------------------------------------------
def section6() -> None:
    banner("6 . THE EVACUATION: WHAT HEADROOM ACTUALLY BUYS")
    demand = 20_000.0            # req/s, global
    horizon = 900                # seconds
    detect_s = HEALTH_INTERVAL_S * HEALTH_FAILURES + DNS_PUSH_S
    redirect_s = 20.0            # anycast/edge: traffic re-anchors within ~20 s of the decision
    scale_lag_s = 210            # decide + launch instances + boot + warm caches
    scale_rate = 55.0            # req/s of new capacity per second once instances land

    def still_at_dead_edge(t: float) -> float:
        """Anycast / edge-terminated redirection: complete ~20 s after the decision."""
        if t < detect_s:
            return 1.0
        return max(0.0, 1.0 - (t - detect_s) / redirect_s)

    def still_at_dead_dns(t: float) -> float:
        """The section-4 DNS curve, as a closed form over the same client classes."""
        if t < detect_s:
            return 1.0
        e = t - detect_s
        frac = sum(share * max(0.0, 1.0 - e / ttl)
                   for share, ttl in ((0.62, 60.0), (0.22, 300.0), (0.10, 1800.0)))
        return min(1.0, frac + 0.05 * math.exp(-e / 21600.0) + 0.01)

    def run(cap_b: float, label: str, shift=still_at_dead_edge):
        served_total = errors_total = overflow_total = 0.0
        peak_err = peak_after = 0.0
        recovered_at = None
        curve = []
        for t in range(horizon):
            dead = shift(float(t)) * 0.50 * demand
            to_b = demand - dead
            cap = cap_b
            if t > detect_s + scale_lag_s:
                cap = min(demand * 1.05, cap_b + scale_rate * (t - detect_s - scale_lag_s))
            served = min(to_b, cap)
            overflow = max(0.0, to_b - cap)
            errs = dead + overflow
            served_total += served
            errors_total += errs
            overflow_total += overflow
            rate = errs / demand
            peak_err = max(peak_err, rate)
            if t >= detect_s + redirect_s:
                peak_after = max(peak_after, rate)
            if rate < 0.001 and recovered_at is None and t > detect_s:
                recovered_at = t
            curve.append((t, rate, served, overflow / demand))
        return {"label": label, "served": served_total, "errors": errors_total,
                "overflow": overflow_total, "peak": peak_err, "peak_after": peak_after,
                "recovered": recovered_at, "curve": curve, "cap0": cap_b}

    print(f"  {demand:,.0f} req/s split 50/50 across two regions. Region A dies at t=0.")
    print(f"  detection {detect_s:.0f}s, then edge redirection completes over {redirect_s:.0f}s "
          f"(anycast, per section 4).")
    print(f"  autoscaling in the survivor starts at t={detect_s + scale_lag_s:.0f}s and adds "
          f"{scale_rate:.0f} req/s of capacity per second.\n")

    tight = run(demand * 0.5 / 0.90, "no headroom  (each region 90% utilised)")
    roomy = run(demand * 1.00, "headroom     (each region 50% utilised)")

    print(f"  {'configuration':<42}{'cap':>10}{'peak err':>10}{'peak after':>12}"
          f"{'failed reqs':>14}{'recovery':>11}")
    for r in (tight, roomy):
        rec = f"{r['recovered']}s" if r["recovered"] is not None else ">900s"
        print(f"  {r['label']:<42}{r['cap0']:>8,.0f}/s{r['peak'] * 100:>9.1f}%"
              f"{r['peak_after'] * 100:>11.1f}%{r['errors']:>14,.0f}{rec:>11}")

    print(f"\n  {'t':>6}{'no headroom err%':>19}{'headroom err%':>16}   what is failing")
    notes = {0: "region A is dead, nobody knows yet", 35: "detected; redirection begins",
             55: "redirection complete", 120: "survivor is the only bottleneck now",
             245: "new capacity starts landing", 400: "", 406: "", 600: "", 899: ""}
    for t in (0, 30, 35, 45, 55, 120, 245, 300, 400, 500, 600, 899):
        note = notes.get(t, "")
        print((f"  {t:>5}s{tight['curve'][t][1] * 100:>17.1f}%"
               f"{roomy['curve'][t][1] * 100:>15.1f}%   {note}").rstrip())

    ratio = tight["errors"] / max(1.0, roomy["errors"])
    print(f"\n  identical failure, identical redirection, identical code. The only difference is "
          f"whether")
    print(f"  the survivor had anywhere to put the traffic: {tight['errors']:,.0f} failed requests "
          f"vs {roomy['errors']:,.0f} ({ratio:.1f}x).")
    print(f"  the headroom run was fully recovered {roomy['recovered']}s in; the tight run needed "
          f"{tight['recovered']}s -- and every")
    print(f"  second of that gap was spent serving 500 errors at "
          f"{tight['curve'][120][1] * 100:.0f}% of all traffic.")
    print(f"  peak error rate is the SAME ({tight['peak'] * 100:.0f}%) for both: detection lag "
          f"costs everyone equally.")
    print("  headroom does not shorten detection. It shortens the outage.\n")

    dnsrun = run(demand * 1.00, "headroom, but DNS redirection", shift=still_at_dead_dns)
    print(f"  and the same well-provisioned run redirected by 60-second DNS instead of the edge:")
    print(f"  {'':<42}{'':>10}{'peak err':>10}{'peak after':>12}{'failed reqs':>14}"
          f"{'recovery':>11}")
    rec = f"{dnsrun['recovered']}s" if dnsrun["recovered"] is not None else ">900s"
    print(f"  {dnsrun['label']:<42}{dnsrun['cap0']:>8,.0f}/s{dnsrun['peak'] * 100:>9.1f}%"
          f"{dnsrun['peak_after'] * 100:>11.1f}%{dnsrun['errors']:>14,.0f}{rec:>11}")
    print(f"  {dnsrun['errors'] / max(1.0, roomy['errors']):.1f}x the failed requests of the same "
          f"capacity behind an anycast edge, and it never")
    print("  fully recovers inside the window -- section 4's tail, priced in requests.\n")
    print("  to survive losing 1 of N regions you must run at most (N-1)/N utilisation:")
    print(f"  {'regions':>9}{'max utilisation':>18}{'cost multiplier':>18}")
    for nreg in (2, 3, 4, 6):
        util = (nreg - 1) / nreg
        print(f"  {nreg:>9}{util * 100:>17.1f}%{1 / util:>17.2f}x")
    print("  two regions is the most expensive way to be multi-region. Three is cheaper per unit of")
    print("  survivable traffic, and nobody budgets for the third.")


def main() -> None:
    print("MULTI-REGION: GLOBAL TRAFFIC, FAILOVER & DATA GRAVITY")
    print("Phase 11 . Lesson 10 . seeded random.Random(7), stdlib only")
    section1()
    section2()
    section3()
    section4()
    section5()
    section6()
    print(f"\n  (total wall time {time.perf_counter() - WALL_START:.1f} s)")


if __name__ == "__main__":
    main()
