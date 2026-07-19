#!/usr/bin/env python3
"""Phase 11 · Lesson 05 — Service Discovery, Client-Side Balancing & Subsetting.

Companion program for
phases/11-scalability-and-reliability/05-service-discovery-and-subsetting/docs/en.md

Sources: Beyer et al., *Site Reliability Engineering* (O'Reilly, 2016), ch. 20
("Load Balancing in the Datacenter") for the deterministic subsetting algorithm;
RFC 1035 §4.1.1 / §4.1.4 / §4.2.1 for DNS message layout, name compression and
TC-bit truncation; RFC 6891 (EDNS(0)) for larger advertised UDP buffers.
Standard library only, seeded from SEED = 7, self-terminating in about 8 seconds.
"""

from __future__ import annotations

import math
import random
import statistics
from collections import Counter

SEED = 7

# The subsetting algorithm seeds its shuffle with a small integer (the round
# number), exactly as published, and round numbers here reach 999. Every
# SIMULATION rng is therefore given an explicit large integer seed, so it can
# never share a stream with a round shuffle and manufacture a correlation that
# is not really there. (Seeding with a tuple containing a string would depend on
# PYTHONHASHSEED and would not be reproducible across runs.)

SIM_SEEDS = {
    "lease":         SEED * 1_000_000 + 11,
    "dns":           SEED * 1_000_000 + 22,
    "random-subset": SEED * 1_000_000 + 33,
    "kill":          SEED * 1_000_000 + 44,
    "control-plane": SEED * 1_000_000 + 55,
}


def sim_rng(name: str) -> random.Random:
    return random.Random(SIM_SEEDS[name])


def banner(title: str) -> None:
    print(f"\n== {title} ==")


def human_mem(kb: float) -> str:
    if kb < 1024:
        return f"{kb:.0f}KB"
    if kb < 1024 * 1024:
        return f"{kb / 1024:.1f}MB"
    return f"{kb / 1024 / 1024:.1f}GB"


# --------------------------------------------------------------------------
# 1 · A REGISTRY WITH LEASES
# --------------------------------------------------------------------------
# An instance registers, then renews its lease every `hb` seconds. The registry
# drops it when no renewal has arrived for `ttl` seconds. Clients (or a sidecar)
# refresh their endpoint list every `poll` seconds. Two questions:
#   (a) an instance dies SILENTLY — for how long does traffic keep arriving?
#   (b) how often is a HEALTHY instance evicted because renewals were lost?
#       That is the price of setting the heartbeat interval close to the TTL.

LEASE_CONFIGS = [
    #  label                     ttl   hb  poll
    ("aggressive",                 6,   2,   1),
    ("Consul-style TTL check",    15,   5,   2),
    ("k8s node lease default",    40,  10,   1),
    ("Eureka default",            90,  30,  30),
    ("hb too close to ttl",       30,  25,   2),
    ("hb ABOVE ttl (broken)",     30,  35,   2),
]

HB_LOSS = 0.02       # 2% of renewals lost: packet loss, a GC pause, a busy registry
LEASE_TRIALS = 20000
LEASE_INSTANCES = 400
LEASE_HOURS = 1.0


def stale_window(ttl: float, hb: float, poll: float, rng: random.Random):
    """How long traffic keeps flowing to an instance that died without deregistering."""
    windows = []
    for _ in range(LEASE_TRIALS):
        # Last successful renewal at t=0; the process is killed at a uniform
        # point before the next renewal would have been sent.
        death = rng.uniform(0.0, hb)
        expiry = ttl                                   # registry evicts here
        offset = rng.uniform(0.0, poll)                # each client polls on its own phase
        learned = expiry + ((offset - expiry) % poll)  # first poll at or after expiry
        windows.append(learned - death)
    return statistics.mean(windows), max(windows)


def misses_tolerated(ttl: float, hb: float) -> int:
    """Consecutive lost renewals survivable: largest x with (x+1)*hb <= ttl."""
    return int(ttl // hb) - 1


def predicted_evictions(ttl: float, hb: float) -> float:
    """Closed form: evictions per healthy-instance-hour from lost renewals alone."""
    epochs = 3600.0 / hb
    tol = misses_tolerated(ttl, hb)
    if tol < 0:
        return epochs                      # the gap alone exceeds the ttl: always
    return epochs * HB_LOSS ** (tol + 1)


def measured_evictions(ttl: float, hb: float, rng: random.Random) -> float:
    epochs = int(3600 * LEASE_HOURS / hb)
    evictions = 0
    for _ in range(LEASE_INSTANCES):
        last = 0.0
        for i in range(1, epochs + 1):
            t = i * hb
            if rng.random() < HB_LOSS:
                continue                   # renewal lost in flight
            if t - last > ttl:
                evictions += 1             # the registry had already dropped us
            last = t
    return evictions / (LEASE_INSTANCES * LEASE_HOURS)


def section_1() -> None:
    banner("1 · LEASES: HOW LONG TRAFFIC KEEPS ARRIVING AT AN INSTANCE THAT DIED")
    rng = sim_rng("lease")
    print("  the instance is killed -9 mid-request: no deregister, no goodbye.")
    print(f"  renewals are lost {HB_LOSS:.0%} of the time (packet loss, GC pause, busy registry).")
    print(f"  stale window measured over {LEASE_TRIALS:,} random death times per config;")
    print(f"  evictions measured over {LEASE_INSTANCES} healthy instances for 1 hour.")
    print()
    print(f"  {'config':<24}{'ttl':>5}{'hb':>5}{'poll':>6}{'misses':>10}"
          f"{'mean stale':>12}{'max stale':>11}{'bad evictions/instance/hr':>27}")
    print(f"  {'':<24}{'':>5}{'':>5}{'':>6}{'tolerated':>10}"
          f"{'window':>12}{'window':>11}{'measured':>16}{'predicted':>11}")
    for label, ttl, hb, poll in LEASE_CONFIGS:
        mean_w, max_w = stale_window(ttl, hb, poll, rng)
        tol = misses_tolerated(ttl, hb)
        tol_s = str(tol) if tol >= 0 else "none"
        print(f"  {label:<24}{ttl:>4}s{hb:>4}s{poll:>5}s{tol_s:>10}"
              f"{mean_w:>11.1f}s{max_w:>10.1f}s"
              f"{measured_evictions(ttl, hb, rng):>16.3f}{predicted_evictions(ttl, hb):>11.3f}")
    print()
    print("  the stale window averages ttl - hb/2 + poll/2 and peaks at ttl + poll:")
    print("  the registry cannot know the instance is gone until the lease runs out,")
    print("  and the client cannot know the registry knows until it next refreshes.")
    print("  every request sent inside that window hits a socket nobody is listening on.")
    print("  (measured eviction counts are small-sample — 400 instance-hours means")
    print("   anything under 0.01/hr is one or two events; the closed form is")
    print("   (3600/hb) * loss^(tolerated+1), and the two agree where events are common.)")
    print()
    print("  the last two rows are the trap. hb=25s under a 30s ttl tolerates ZERO lost")
    print("  renewals, so 2% renewal loss evicts each healthy instance ~2.8 times an hour;")
    print("  hb=35s under a 30s ttl evicts EVERY instance on EVERY renewal — a fleet that")
    print("  flaps in and out of the registry while every process is perfectly healthy.")
    print("  rule: heartbeat interval <= ttl/3, so two consecutive losses are survivable.")


# --------------------------------------------------------------------------
# 2 · DNS AS SERVICE DISCOVERY, AND HOW IT LIES
# --------------------------------------------------------------------------

DNS_TTL = 30.0
DNS_BACKENDS = 8              # one of these is the instance we remove at t=0
DNS_CLIENTS = 2000
POOL_MAX_LIFETIME = 600.0     # keep-alive connection recycled after 10 minutes

COHORTS = [
    # label,                          share, behaviour
    ("honours the TTL",                0.60, "ttl"),
    ("pinned by a connection pool",    0.30, "pool"),
    ("caches forever (JVM ttl=-1)",    0.10, "forever"),
]

DNS_SAMPLE_TIMES = [0, 15, 30, 60, 120, 300, 600, 900, 3600]

DNS_NAMES = [
    "api.internal",
    "backend.svc.cluster.local",
    "checkout.prod.us-east-1.mesh.corp",
]
DNS_BUDGETS = [("classic UDP (RFC 1035)", 512),
               ("EDNS(0) typical (RFC 6891)", 1232),
               ("EDNS(0) maximum", 4096)]


def section_2() -> None:
    banner("2 · DNS TTL vs REALITY: THE INSTANCE YOU REMOVED AN HOUR AGO")
    rng = sim_rng("dns")
    print(f"  {DNS_BACKENDS} A records behind one name, ttl={DNS_TTL:.0f}s. At t=0 we remove one")
    print(f"  instance from the record set. {DNS_CLIENTS} clients, each sending 1/{DNS_BACKENDS} of its")
    print("  requests to every address it currently believes in.")
    for label, share, _k in COHORTS:
        print(f"    {share:>5.0%}  {label}")
    print()

    clients = []
    for _ in range(DNS_CLIENTS):
        r = rng.random()
        acc = 0.0
        kind = "ttl"
        for _label, share, k in COHORTS:
            acc += share
            if r < acc:
                kind = k
                break
        age = rng.uniform(0.0, DNS_TTL)      # cache filled at a random point in the window
        if kind == "ttl":
            stops = DNS_TTL - age
        elif kind == "pool":
            stops = rng.uniform(0.0, POOL_MAX_LIFETIME)
        else:
            stops = math.inf
        clients.append(stops)

    print(f"  {'t':>8}{'clients still resolving it':>30}{'share of ALL fleet requests':>29}")
    for t in DNS_SAMPLE_TIMES:
        believers = sum(1 for s in clients if s > t)
        frac_clients = believers / DNS_CLIENTS
        frac_reqs = frac_clients / DNS_BACKENDS
        bar = "#" * int(round(frac_reqs * 320))
        print(f"  {t:>7}s{believers:>13} ({frac_clients:>6.1%}){frac_reqs:>17.2%}   {bar}")
    print()
    end = sum(1 for s in clients if s > 3600) / DNS_CLIENTS
    print(f"  one hour after removal, {end:.1%} of clients are still sending it traffic")
    print(f"  = {end / DNS_BACKENDS:.2%} of every request the fleet makes, into a dead address.")
    print("  the TTL is advisory. Java's networkaddress.cache.ttl was historically -1")
    print("  (cache forever) whenever a SecurityManager was installed, and a connection")
    print("  pool re-resolves nothing at all: it holds the socket it opened at startup.")
    print()

    # --- how many A records fit in a UDP DNS response? RFC 1035 §4.1.1 ---
    print("  and there is a hard ceiling on how many addresses one UDP answer can carry:")
    print("  12B header + question (QNAME + 2B QTYPE + 2B QCLASS); each answer A record is")
    print("  2B compression pointer + 2B type + 2B class + 4B ttl + 2B rdlength + 4B address")
    print("  = 16B (RFC 1035 §4.1.4). Records that do not fit are simply left out, TC=1.")
    print()
    print(f"  {'name queried':<36}{'QNAME':>7}", end="")
    for label, _size in DNS_BUDGETS:
        print(f"{label:>29}", end="")
    print()
    for name in DNS_NAMES:
        qname = sum(len(lbl) + 1 for lbl in name.split(".")) + 1
        print(f"  {name:<36}{qname:>6}B", end="")
        for _label, size in DNS_BUDGETS:
            fits = (size - 12 - (qname + 4)) // 16
            print(f"{fits:>26} As", end="")
        print()
    print()
    print("  ~29 instances is enough to overflow a classic 512-byte UDP answer, and ~74")
    print("  to overflow the 1232-byte EDNS(0) buffer most resolvers advertise today.")
    print("  the server sets TC=1 and the resolver is supposed to retry over TCP (RFC 1035")
    print("  §4.2.1) — a middlebox that blocks DNS-over-TCP turns that into a silently")
    print("  truncated list, so part of your fleet is invisible to part of your clients.")
    print("  and an A record carries no health, no weight and no drain state at all.")


# --------------------------------------------------------------------------
# 3 · THE N x M CONNECTION EXPLOSION
# --------------------------------------------------------------------------
# Per-connection memory is a stated parameter, not a guess dressed as a fact:
# 12 KB server-side is a struct sock plus minimum rx/tx buffers plus TLS session
# state plus HTTP/2 stream bookkeeping; 10 KB client-side is the same without the
# request context. A TLS-terminated HTTP/2 connection with default 64 KB flow
# control windows is several times larger, so these numbers are the floor.

MEM_SERVER_KB = 12
MEM_CLIENT_KB = 10
FD_SOFT_DEFAULT = 1024
FD_TYPICAL_RAISED = 65536
HEALTH_CHECK_PERIOD = 10.0     # every client probes every backend every 10 s
DEPLOY_WINDOW = 300.0          # a rolling deploy replaces the callee fleet in 5 min

FLEETS = [(10, 8), (50, 40), (100, 80), (250, 200), (500, 400),
          (1000, 800), (2000, 1600), (5000, 4000)]


def section_3() -> None:
    banner("3 · THE N x M CONNECTION EXPLOSION: A KAPPA TERM YOU CAN COUNT")
    print("  every client holds one connection to every backend — that is what")
    print("  client-side load balancing means. N clients, M backends, N x M sockets.")
    print(f"  assumed floor cost: {MEM_SERVER_KB} KB per connection on the backend,"
          f" {MEM_CLIENT_KB} KB on the client.")
    print()
    print(f"  {'N':>9}{'M':>9}{'N x M':>13}{'inbound':>10}{'mem':>10}{'fleet':>11}"
          f"{'fds':>13}{'probes/s':>11}{'handshakes/s':>14}")
    print(f"  {'clients':>9}{'backends':>9}{'conns':>13}{'/backend':>10}{'/backend':>10}{'memory':>11}"
          f"{'/backend':>13}{'/backend':>11}{'on deploy':>14}")
    for n, m in FLEETS:
        conns = n * m
        srv_mem_mb = n * MEM_SERVER_KB / 1024                     # per backend
        probes = n / HEALTH_CHECK_PERIOD                          # per backend
        handshakes = conns / DEPLOY_WINDOW
        if n > FD_TYPICAL_RAISED:
            fd = "impossible"
        elif n > FD_SOFT_DEFAULT:
            fd = "raise ulimit"
        else:
            fd = "ok"
        print(f"  {n:>9,}{m:>9,}{conns:>13,}{n:>10,}{srv_mem_mb:>8.1f}MB"
              f"{human_mem(conns * (MEM_SERVER_KB + MEM_CLIENT_KB)):>11}"
              f"{fd:>13}{probes:>11,.0f}{handshakes:>14,.0f}")
    print()
    n, m = 1000, 800
    conns = n * m
    print(f"  read the {n}x{m} row. {conns:,} connections is "
          f"{conns * (MEM_SERVER_KB + MEM_CLIENT_KB) / 1024 / 1024:.1f} GB of socket")
    print(f"  state across the two fleets for ZERO requests in flight. Every backend")
    print(f"  answers {n / HEALTH_CHECK_PERIOD:,.0f} health probes per second before it serves one user, and a")
    print(f"  rolling deploy of the callee fleet re-establishes all {conns:,} in "
          f"{DEPLOY_WINDOW:.0f}s")
    print(f"  = {conns / DEPLOY_WINDOW:,.0f} TLS handshakes per second, fleet-wide, on every release.")
    print()
    print("  double BOTH fleets and the connection count quadruples:")
    for a, b in [(500, 400), (1000, 800), (2000, 1600), (5000, 4000)]:
        print(f"    {a:>6,} x {b:>6,} = {a * b:>12,} connections   "
              f"({human_mem(a * b * (MEM_SERVER_KB + MEM_CLIENT_KB)):>8}, "
              f"{a * b / DEPLOY_WINDOW:>9,.0f} handshakes/s on deploy)")
    print("  this is Lesson 2's kappa term with a unit you can read out of `ss -s`:")
    print("  a coherency cost quadratic in fleet size. Add machines and each new one")
    print("  costs more than the last, until adding machines subtracts throughput.")


# --------------------------------------------------------------------------
# 4 · RANDOM vs DETERMINISTIC SUBSETTING
# --------------------------------------------------------------------------


def random_subset(n_clients: int, n_backends: int, k: int, rng: random.Random):
    return [rng.sample(range(n_backends), k) for _ in range(n_clients)]


def deterministic_subset(client_id: int, backends: list[int], k: int) -> list[int]:
    """Beyer et al., *Site Reliability Engineering* (2016), ch. 20.

    Clients are numbered. `subset_count = M // k` consecutive clients form one
    ROUND. Every round reshuffles the whole backend list using the round number
    as the seed, then hands out disjoint slices of length k. One round therefore
    covers the backend list exactly once, so after R complete rounds every
    backend holds exactly R clients — no counting, no coordination, no gossip.
    """
    subset_count = len(backends) // k
    round_id = client_id // subset_count
    shuffled = list(backends)
    random.Random(round_id).shuffle(shuffled)
    subset_id = client_id % subset_count
    start = subset_id * k
    return shuffled[start:start + k]


def deterministic_all(n_clients: int, n_backends: int, k: int):
    backends = list(range(n_backends))
    return [deterministic_subset(c, backends, k) for c in range(n_clients)]


def load_stats(subsets, n_backends: int):
    counts = Counter()
    for s in subsets:
        counts.update(s)
    per = [counts.get(b, 0) for b in range(n_backends)]
    return per, min(per), max(per), statistics.pstdev(per), sum(1 for c in per if c == 0)


SUBSET_CASES = [
    #  clients  backends   k    note
    (     60,       120,   6,  "sparse: fewer clients than backends"),
    (    200,       120,  12,  "balanced"),
    (    600,       120,  10,  "dense"),
    (   1000,       800,  20,  "the fleet from The Problem"),
    (    997,       800,  20,  "clients NOT a whole number of rounds"),
]


def section_4() -> None:
    banner("4 · RANDOM vs DETERMINISTIC SUBSETTING: SAME k, A DIFFERENT WORLD")
    rng = sim_rng("random-subset")
    print("  each client connects to k backends instead of all M. The question is not")
    print("  'how many connections' — both algorithms use exactly N*k. It is: how evenly")
    print("  are clients spread across backends? Perfect would be N*k/M each.")
    print()
    draws = {(n, m, k): (random_subset(n, m, k, rng), deterministic_all(n, m, k))
             for n, m, k, _note in SUBSET_CASES}
    print(f"  {'N':>6}{'M':>6}{'k':>5}{'ideal':>7}  {'algorithm':<15}"
          f"{'min':>6}{'max':>6}{'stddev':>9}{'max/ideal':>11}{'idle backends':>15}")
    for n, m, k, note in SUBSET_CASES:
        ideal = n * k / m
        rnd, det = draws[(n, m, k)]
        for label, subsets in (("random", rnd), ("deterministic", det)):
            _per, lo, hi, sd, zeros = load_stats(subsets, m)
            print(f"  {n:>6}{m:>6}{k:>5}{ideal:>7.1f}  {label:<15}"
                  f"{lo:>6}{hi:>6}{sd:>9.2f}{hi / ideal:>10.2f}x{zeros:>15}")
        print(f"  {'':>26}  -- {note}")
    print()

    n, m, k = 60, 120, 6
    print(f"  that first case drawn out — N={n} clients, M={m} backends, k={k},")
    print(f"  ideal = {n * k / m:.0f} clients per backend:")
    for label, subsets in (("random", draws[(n, m, k)][0]),
                           ("deterministic", draws[(n, m, k)][1])):
        per, lo, hi, sd, zeros = load_stats(subsets, m)
        hist = Counter(per)
        print(f"    {label}:")
        for load in range(0, max(hist) + 1):
            c = hist.get(load, 0)
            mark = "   <-- IDLE: paid for, unreachable" if load == 0 and c else ""
            print(f"      {load:>2} clients |{'#' * c:<45}{c:>4} backends{mark}")
        print(f"      min {lo}  max {hi}  stddev {sd:.2f}  idle backends {zeros}")
    print()
    print("  random subsetting is balls-in-bins (Lesson 3). Independent choices leave")
    print("  some backends at 2-3x the ideal load and some with no clients at all —")
    print("  capacity you are paying for and cannot reach. Deterministic subsetting")
    print("  makes the choices DEPENDENT: one round of clients partitions the backend")
    print("  list, so counts are exactly equal, or differ by exactly 1 when the client")
    print("  count is not a whole number of rounds. Same k. Same connection count.")


# --------------------------------------------------------------------------
# 5 · SUBSET RESILIENCE: CHOOSING k
# --------------------------------------------------------------------------

RES_CLIENTS = 1000
RES_BACKENDS = 800
KILL_FRACTIONS = [0.05, 0.10, 0.20]
K_VALUES = [3, 5, 10, 20, 40, 80, RES_BACKENDS]
KILL_TRIALS = 40


def section_5() -> None:
    banner("5 · CHOOSING k: CONNECTIONS SAVED vs BLAST RADIUS BOUGHT")
    rng = sim_rng("kill")
    n, m = RES_CLIENTS, RES_BACKENDS
    full = n * m
    subsets_by_k = {k: deterministic_all(n, m, k) for k in K_VALUES}
    summary: dict[tuple[float, int], tuple[float, int, int]] = {}
    print(f"  {n} clients, {m} backends, deterministic subsets. We kill a random")
    print(f"  fraction of backends and ask what each individual CLIENT lost, over")
    print(f"  {KILL_TRIALS} independent kill draws.")
    for f in KILL_FRACTIONS:
        n_dead = int(round(f * m))
        draws = [set(rng.sample(range(m), n_dead)) for _ in range(KILL_TRIALS)]
        print()
        print(f"  --- {n_dead} of {m} backends dead ({f:.0%}) — "
              f"survivors must absorb +{1 / (1 - f) - 1:.0%} each ---")
        print(f"  {'k':>5}{'conns':>11}{'vs mesh':>9}{'clients <50%':>16}{'worst':>8}"
              f"{'clients at 0':>14}{'worst client':>15}")
        print(f"  {'':>5}{'':>11}{'':>9}{'of subset (avg)':>16}{'draw':>8}"
              f"{'(any draw)':>14}{'kept':>15}")
        for k in K_VALUES:
            subsets = subsets_by_k[k]
            half, zero, worst = [], 0, 1.0
            for dead in draws:
                surv = [sum(1 for b in s if b not in dead) for s in subsets]
                half.append(sum(1 for s in surv if s < k / 2))
                zero += sum(1 for s in surv if s == 0)
                worst = min(worst, min(surv) / k)
            conns = n * k
            tag = "  <-- full mesh" if k == m else ""
            summary[(f, k)] = (statistics.mean(half), max(half), zero)
            print(f"  {k:>5}{conns:>11,}{conns / full:>8.1%}{statistics.mean(half):>16.1f}"
                  f"{max(half):>8}{zero:>14}{worst:>14.0%}{tag}")
    a_avg, a_worst, a_zero = summary[(0.20, 3)]
    b_avg, _b_worst, b_zero = summary[(0.20, 20)]
    print()
    print(f"  the trade in one line: k=3 costs {3 * n / full:.1%} of the full mesh's connections but")
    print(f"  at a 20% backend loss it leaves {a_avg:.0f} of {n} clients below half capacity on")
    print(f"  average ({a_worst} in the worst draw) and {a_zero} client-draws with NOTHING left.")
    print(f"  k=20 costs {20 * n / full:.1%}, averages {b_avg:.1f} clients below half, and strands {b_zero}.")
    print("  k does not protect against fleet-wide loss (everyone loses 20% either way).")
    print("  It bounds the damage to the single unlucky client whose whole subset was")
    print("  in the rack that lost power. Small k, big variance. That is the entire knob.")
    print()
    # The closed form behind the 'clients at 0' column: a client's whole subset is
    # dead only if all k of its backends are, which for an independent dead
    # fraction f is f^k. Printed rather than asserted so the exponent is checkable.
    f_ref = 0.20
    print(f"  why that column collapses: P(a client's WHOLE subset is dead) = f^k.")
    print(f"  at f = {f_ref:.0%} dead:")
    print(f"    {'k':>5}{'f^k':>14}{'as a percent':>16}{'1 client in':>22}"
          f"{'expected at N=%d' % n:>19}")
    for k in (3, 5, 10, 20):
        p = f_ref ** k
        print(f"    {k:>5}{p:>14.3e}{p * 100:>15.6g}%{1 / p:>22,.0f}"
              f"{p * n:>19.3g}")
    print("  each +1 on k divides the risk by 5. That is why the useful range of k")
    print("  is small: the failure it prevents disappears exponentially, and the")
    print("  connections it costs only grow linearly.")
    print()
    print(f"  k=20 at N={RES_CLIENTS}, M={RES_BACKENDS}: 20,000 connections instead of "
          f"{full:,} ({20000 / full:.1%}),")
    print(f"  {human_mem(20000 * (MEM_SERVER_KB + MEM_CLIENT_KB))} of socket state instead of "
          f"{human_mem(full * (MEM_SERVER_KB + MEM_CLIENT_KB))}.")
    print(f"  {20000 / m / HEALTH_CHECK_PERIOD:.1f} health probes/s per backend instead of "
          f"{full / m / HEALTH_CHECK_PERIOD:.0f}, and {20000 / DEPLOY_WINDOW:.0f} handshakes/s")
    print(f"  on deploy instead of {full / DEPLOY_WINDOW:,.0f}.")
    print("  and inside a subset nothing changes: pick-two-at-random (Lesson 3) over 20")
    print("  endpoints behaves exactly like P2C over 20 endpoints, because it is.")
    print("  subsetting picks WHICH backends; the balancing algorithm picks WHICH ONE.")


# --------------------------------------------------------------------------
# 6 · CONTROL-PLANE OUTAGE
# --------------------------------------------------------------------------

CP_CLIENTS = 600
CP_BACKENDS = 120
CP_K = 10
CP_RPS_PER_CLIENT = 2
CP_DURATION = 240
CP_OUTAGE = (60, 180)
CP_CHURN = 0.05            # 5% of backends are replaced while the registry is down
EJECT_AFTER = 3            # consecutive failures before the client ejects a host

CP_POLICIES = ["no cache (fail closed)", "serve stale", "serve stale + eject"]


def section_6() -> None:
    banner("6 · CONTROL PLANE DOWN: THE DATA PLANE MUST NOT CARE")
    print(f"  {CP_CLIENTS} clients, {CP_BACKENDS} backends, deterministic subsets of k={CP_K},")
    print(f"  {CP_RPS_PER_CLIENT} requests per client per second for {CP_DURATION}s.")
    print(f"  the discovery service is unreachable from t={CP_OUTAGE[0]}s to t={CP_OUTAGE[1]}s.")
    print(f"  during the outage {CP_CHURN:.0%} of backends are replaced, so a cached view rots.")
    print()

    subsets = deterministic_all(CP_CLIENTS, CP_BACKENDS, CP_K)
    buckets = {p: Counter() for p in CP_POLICIES}
    totals = {p: [0, 0] for p in CP_POLICIES}

    for policy in CP_POLICIES:
        rng = sim_rng("control-plane")
        replaced: set[int] = set()
        ejected = [set() for _ in range(CP_CLIENTS)]
        strikes = [Counter() for _ in range(CP_CLIENTS)]
        for t in range(CP_DURATION):
            down = CP_OUTAGE[0] <= t < CP_OUTAGE[1]
            if down:
                target = int(CP_CHURN * CP_BACKENDS * (t - CP_OUTAGE[0] + 1)
                             / (CP_OUTAGE[1] - CP_OUTAGE[0]))
                while len(replaced) < target:
                    replaced.add(rng.randrange(CP_BACKENDS))
            elif t >= CP_OUTAGE[1]:
                replaced = set()                       # registry back: cache refreshed
                ejected = [set() for _ in range(CP_CLIENTS)]
            for c in range(CP_CLIENTS):
                for _ in range(CP_RPS_PER_CLIENT):
                    totals[policy][1] += 1
                    buckets[policy][(t // 20, "n")] += 1
                    if policy == "no cache (fail closed)" and down:
                        continue                        # cannot resolve -> cannot send
                    pool = [b for b in subsets[c] if b not in ejected[c]] or subsets[c]
                    b = pool[rng.randrange(len(pool))]
                    if b in replaced:
                        if policy.endswith("eject"):
                            strikes[c][b] += 1
                            if strikes[c][b] >= EJECT_AFTER:
                                ejected[c].add(b)
                        continue                        # connection refused: host moved
                    totals[policy][0] += 1
                    buckets[policy][(t // 20, "ok")] += 1

    print(f"  {'window':>12}", end="")
    for p in CP_POLICIES:
        print(f"{p:>24}", end="")
    print()
    for w in range(CP_DURATION // 20):
        lo, hi = w * 20, w * 20 + 20
        tag = "  <-- CONTROL PLANE DOWN" if CP_OUTAGE[0] <= lo < CP_OUTAGE[1] else ""
        print(f"  {f'{lo}-{hi}s':>12}", end="")
        for p in CP_POLICIES:
            print(f"{buckets[p][(w, 'ok')] / buckets[p][(w, 'n')]:>24.1%}", end="")
        print(tag)
    print()
    lo_w, hi_w = CP_OUTAGE[0] // 20, CP_OUTAGE[1] // 20
    for p in CP_POLICIES:
        ok, nn = totals[p]
        wok = sum(buckets[p][(w, "ok")] for w in range(lo_w, hi_w))
        wnn = sum(buckets[p][(w, "n")] for w in range(lo_w, hi_w))
        print(f"  {p:<24} whole run {ok / nn:>7.2%}   during the outage {wok / wnn:>7.2%}"
              f"   ({wnn - wok:,} of {wnn:,} failed)")
    print()
    print("  fail-closed is a design choice that converts a control-plane blip into a")
    print("  total outage of every service that depends on it. Serving the last-known-")
    print("  good endpoint list costs only the churn that happened while you were blind,")
    print("  and outlier ejection (Lesson 4) cleans up even that with no registry at all.")
    print("  RULE: the data plane must keep routing when the control plane is gone.")


def main() -> None:
    section_1()
    section_2()
    section_3()
    section_4()
    section_5()
    section_6()
    print()


if __name__ == "__main__":
    main()
