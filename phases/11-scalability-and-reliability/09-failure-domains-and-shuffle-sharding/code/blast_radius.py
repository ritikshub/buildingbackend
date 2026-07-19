"""Failure domains, blast radius and shuffle sharding, measured.

Companion program for phases/11-scalability-and-reliability/
09-failure-domains-and-shuffle-sharding/docs/en.md (Phase 11, Lesson 09).
Sources: AWS Builders' Library, "Workload isolation using shuffle-sharding";
AWS Builders' Library, "Static stability using Availability Zones";
Gunawi et al., "Why Does the Cloud Stop Computing? Lessons from Hundreds of
Service Outages", SoCC 2016 (correlated failure in practice).
Standard library only. Seeded with random.Random(7). Exits 0 in ~15 s.
"""

from __future__ import annotations

import math
import random
import time
from itertools import combinations

RNG = random.Random(7)
START = time.perf_counter()


def banner(text: str) -> None:
    print(f"\n== {text} ==")


def nines(availability: float) -> float:
    """How many 'nines' an availability figure is actually worth."""
    if availability >= 1.0:
        return float("inf")
    return -math.log10(1.0 - availability)


# ----------------------------------------------------------------------------
# 1 · BLAST RADIUS OF SHARED INFRASTRUCTURE
# ----------------------------------------------------------------------------
# 800 customers, 8 workers. One customer sends a request that pins a worker
# forever (a backtracking regex, an unbounded query, a 1 GB allocation). The
# request is not malicious. It is a bug. Whichever workers that customer can
# reach are gone, and everyone who shares those workers is gone with them.

N_WORKERS = 8
N_CUSTOMERS = 800
SUBSET_K = 2
SHARD_SIZE = 2
N_SHARDS = N_WORKERS // SHARD_SIZE


def section_1() -> dict[str, float]:
    banner("1 · ONE CUSTOMER'S BUG, THREE PLACEMENT STRATEGIES")
    print(f"  {N_CUSTOMERS} customers, {N_WORKERS} workers, 1 poison customer.")
    print("  'down' = every worker the customer can reach is pinned.")
    print("  'degraded' = some but not all of them are.\n")

    rng = random.Random(7)
    victim = 0  # customer id 0 ships the bug

    # (a) shared fleet: any request may land on any worker.
    shared_down = N_CUSTOMERS - 1  # all of them; the poison reaches every worker
    shared_poisoned = N_WORKERS

    # (b) regular sharding: hash(customer) -> one shard of 2 workers.
    shards = [[s * SHARD_SIZE + i for i in range(SHARD_SIZE)] for s in range(N_SHARDS)]
    assign_shard = [rng.randrange(N_SHARDS) for _ in range(N_CUSTOMERS)]
    poisoned_shard = set(shards[assign_shard[victim]])
    sharded_down = sum(
        1
        for c in range(N_CUSTOMERS)
        if c != victim and assign_shard[c] == assign_shard[victim]
    )

    # (c) shuffle sharding: hash(customer) -> a random 2-of-8 combination.
    pool = list(range(N_WORKERS))
    assign_sub = [frozenset(rng.sample(pool, SUBSET_K)) for _ in range(N_CUSTOMERS)]
    vset = assign_sub[victim]
    shuf_down = shuf_degraded = 0
    for c in range(N_CUSTOMERS):
        if c == victim:
            continue
        overlap = len(assign_sub[c] & vset)
        if overlap == SUBSET_K:
            shuf_down += 1
        elif overlap:
            shuf_degraded += 1

    combos = math.comb(N_WORKERS, SUBSET_K)
    rows = [
        ("shared fleet (no isolation)", shared_poisoned, shared_down, 0),
        ("4 fixed shards of 2", len(poisoned_shard), sharded_down, 0),
        (f"shuffle shard, {SUBSET_K} of {N_WORKERS}", len(vset), shuf_down, shuf_degraded),
    ]
    print(f"  {'placement':<30}{'workers hit':>12}{'down':>8}{'blast':>9}{'degraded':>11}")
    for name, hit, down, deg in rows:
        pct = 100.0 * down / (N_CUSTOMERS - 1)
        print(f"  {name:<30}{hit:>12}{down:>8}{pct:>8.2f}%{deg:>11}")

    untouched = N_CUSTOMERS - 1 - shuf_down - shuf_degraded
    others = N_CUSTOMERS - 1
    print(f"\n  fixed sharding put the poison customer on shard "
          f"{assign_shard[victim]} = workers {sorted(poisoned_shard)}.")
    print(f"  shuffle sharding drew it workers {sorted(vset)}.\n")
    print(f"  outcome for the other {others}   {'down':>12}{'degraded':>14}"
          f"{'untouched':>14}")
    print(f"  {'measured':<28}{shuf_down:>5} {100.0 * shuf_down / others:>5.2f}%"
          f"{shuf_degraded:>6} {100.0 * shuf_degraded / others:>5.2f}%"
          f"{untouched:>6} {100.0 * untouched / others:>5.2f}%")
    t_down = 100.0 / combos
    t_deg = 100.0 * SUBSET_K * (N_WORKERS - SUBSET_K) / combos
    t_unt = 100.0 * math.comb(N_WORKERS - SUBSET_K, SUBSET_K) / combos
    print(f"  {'theory  1/28, 12/28, 15/28':<28}{'':>5} {t_down:>5.2f}%"
          f"{'':>6} {t_deg:>5.2f}%{'':>6} {t_unt:>5.2f}%")

    p = 1.0 / combos
    sigma = math.sqrt(others * p * (1 - p))
    z = (others * p - shuf_down) / sigma
    print(f"\n  C({N_WORKERS},{SUBSET_K}) = {combos} possible subsets, so an unlucky twin")
    print(f"  is drawn about 1 time in {combos}: expected {others * p:.1f}"
          f" of {others}, measured {shuf_down}")
    print(f"  (sigma = {sigma:.2f}, so the run sits {z:.1f} standard deviations low —")
    print("   ordinary sampling noise, not a result).")
    print(f"  {shuf_degraded} more customers lost 1 of their 2 workers — 50% of their")
    print("  capacity, 0% of their availability IF the client retries the other one.")
    return {
        "shared": 100.0 * shared_down / (N_CUSTOMERS - 1),
        "sharded": 100.0 * sharded_down / (N_CUSTOMERS - 1),
        "shuffled": 100.0 * shuf_down / (N_CUSTOMERS - 1),
        "shuffled_down": shuf_down,
        "shuffled_degraded": shuf_degraded,
    }


# ----------------------------------------------------------------------------
# 2 · THE COMBINATORICS, COMPUTED AND VERIFIED
# ----------------------------------------------------------------------------
# Two customers are *completely* co-located only if they drew the identical
# subset. With subsets of equal size k that is exactly 1 / C(N, k). Monte-Carlo
# the small cases; the analytic number has to fall out of the sampling.


def section_2() -> None:
    banner("2 · THE COMBINATORICS: C(N,k) AND THE ODDS OF A FULL COLLISION")
    print("  P(another customer draws YOUR exact subset) = 1 / C(N,k)\n")
    table = [(8, 2), (16, 3), (24, 4), (50, 4),
             (100, 2), (100, 3), (100, 4), (100, 5), (100, 8), (1000, 5)]
    print(f"  {'N':>6}{'k':>4}{'C(N,k)':>22}{'P(full overlap)':>18}{'reach':>9}")
    for n, k in table:
        c = math.comb(n, k)
        print(f"  {n:>6}{k:>4}{c:>22,}{1.0 / c:>18.3e}{k / n:>8.1%}")
    print("  'reach' = k/N, the fraction of the fleet one customer can touch —")
    print("  which is also the fraction it can damage. Bigger k buys isolation")
    print("  from your neighbours and costs you exposure to your own bugs.")

    print("\n  Monte-Carlo: draw a victim subset, then draw M customers at random")
    print("  and count how many landed on the identical subset. The +/- column is")
    print("  one standard error of the sample, so the analytic number should sit")
    print("  inside it.\n")
    print(f"  {'N':>6}{'k':>4}{'samples':>12}{'hits':>8}{'analytic':>12}"
          f"{'empirical':>12}{'+/- 1 s.e.':>12}{'emp/exact':>11}{'s.e. off':>10}")
    for n, k, m in [(8, 2, 300_000), (16, 3, 800_000), (24, 4, 4_000_000)]:
        rng = random.Random(7 + n)
        pool = list(range(n))
        victim = set(rng.sample(pool, k))
        hits = 0
        for _ in range(m):
            if set(rng.sample(pool, k)) == victim:
                hits += 1
        analytic = 1.0 / math.comb(n, k)
        empirical = hits / m
        stderr = math.sqrt(max(hits, 1)) / m
        off = (analytic - empirical) / stderr
        print(f"  {n:>6}{k:>4}{m:>12,}{hits:>8}{analytic:>12.3e}"
              f"{empirical:>12.3e}{stderr:>12.1e}{empirical / analytic:>10.2f}x"
              f"{off:>9.1f}")
    print("\n  sampling agrees with the closed form, so the closed form can be")
    print("  trusted where sampling cannot reach: at N=100, k=5 you would need")
    print("  ~75 million draws to expect a single collision.")


# ----------------------------------------------------------------------------
# 3 · THE OVERLAP DISTRIBUTION — AND WHY RETRY IS THE WHOLE TRICK
# ----------------------------------------------------------------------------
# Partial overlap is common. Full overlap is not. The distribution of "how many
# workers do you share with the victim" is hypergeometric:
#   P(overlap = j) = C(k, j) * C(N-k, k-j) / C(N, k)

HIST_N = 100
HIST_K = 5
HIST_CUSTOMERS = 200_000


def section_3() -> list[tuple[int, int, float, float, float, float]]:
    banner("3 · OVERLAP DISTRIBUTION: PARTIAL IS COMMON, FULL IS NOT")
    print(f"  N = {HIST_N} workers, k = {HIST_K} per customer, "
          f"{HIST_CUSTOMERS:,} simulated customers.")
    print("  the poison customer pins all 5 of ITS workers. For everyone else:")
    print("  no failover  -> j/k of your requests hit a dead worker and fail.")
    print("  with failover-> the client retries a live member; you lose j/k of")
    print("                  your capacity but 0% of your availability.\n")

    rng = random.Random(11)
    pool = list(range(HIST_N))
    victim = set(rng.sample(pool, HIST_K))
    hist = [0] * (HIST_K + 1)
    for _ in range(HIST_CUSTOMERS):
        hist[len(victim & set(rng.sample(pool, HIST_K)))] += 1

    total_c = math.comb(HIST_N, HIST_K)
    print(f"  {'shared':>7}{'customers':>12}{'measured':>11}{'analytic':>11}"
          f"{'errors: no':>12}{'errors: w/':>12}{'capacity':>10}")
    print(f"  {'workers':>7}{'':>12}{'share':>11}{'share':>11}"
          f"{'failover':>12}{'failover':>12}{'left':>10}")
    rows = []
    err_no = err_yes = 0.0
    for j in range(HIST_K + 1):
        analytic = (math.comb(HIST_K, j) * math.comb(HIST_N - HIST_K, HIST_K - j)
                    / total_c)
        measured = hist[j] / HIST_CUSTOMERS
        e_no = j / HIST_K
        e_yes = 1.0 if j == HIST_K else 0.0
        cap = 1.0 - j / HIST_K
        err_no += measured * e_no
        err_yes += measured * e_yes
        rows.append((j, hist[j], measured, analytic, e_no, e_yes))
        print(f"  {j:>7}{hist[j]:>12,}{measured:>10.4%}{analytic:>10.4%}"
              f"{e_no:>11.0%}{e_yes:>11.0%}{cap:>9.0%}")

    any_overlap = 1.0 - hist[0] / HIST_CUSTOMERS
    print(f"\n  {any_overlap:.2%} of customers share AT LEAST one worker with the")
    print("  poison customer. That is the number people quote to argue that")
    print("  shuffle sharding does not work. It is the wrong number to look at.\n")

    # The honest comparison: a fixed shard of the same size k.
    fixed_shards = HIST_N // HIST_K
    fixed_affected = 1.0 / fixed_shards
    print(f"  {'scheme':<32}{'customers':>13}{'customers':>13}{'fleet-wide':>13}")
    print(f"  {'':<32}{'w/ errors':>13}{'fully down':>13}{'error rate':>13}")
    table3 = [
        (f"fixed shard of {HIST_K} ({fixed_shards} shards)",
         f"{fixed_affected:.4%}", f"{fixed_affected:.4%}", f"{fixed_affected:.4%}"),
        ("shuffle shard, NO failover",
         f"{any_overlap:.4%}", f"{err_yes:.4%}", f"{err_no:.4%}"),
        ("shuffle shard + failover retry",
         f"{err_yes:.4%}", f"{err_yes:.4%}", f"{1.0 / total_c:.2e}"),
    ]
    for name, a, b, cval in table3:
        print(f"  {name:<32}{a:>13}{b:>13}{cval:>13}")
    print("\n  read the middle row carefully. Without failover, shuffle sharding")
    print(f"  produces the SAME fleet-wide error volume as a fixed shard "
          f"({err_no:.2%} vs")
    print(f"  {fixed_affected:.2%} — both are k/N) and spreads it across "
          f"{any_overlap / fixed_affected:.1f}x more customers.")
    print("  It is not better. It is worse, and more customers file tickets.")
    print(f"  The retry is what converts it. Full overlap is 1 in {total_c:,};")
    print(f"  {HIST_CUSTOMERS:,} sampled customers produced {hist[HIST_K]}, and the")
    print(f"  expected count was {HIST_CUSTOMERS / total_c:.4f}.")
    print("  Shuffle sharding is not a placement trick. It is a placement trick")
    print("  PLUS a client that retries a different member of its own subset.")
    return rows


# ----------------------------------------------------------------------------
# 4 · CORRELATED FAILURE DESTROYS INDEPENDENCE
# ----------------------------------------------------------------------------
# Model: an instance is unavailable with probability p. A fraction c of that
# probability is COMMON CAUSE — a config push, a deploy, a control-plane
# outage — which takes every instance at once. The rest is independent.
#   P(system down) = c*p  +  (1 - c*p) * ((1-c)*p)^n

P_INSTANCE = 0.001  # 99.9% per instance


def section_4() -> list[tuple[float, float, float]]:
    banner("4 · CORRELATED FAILURE DESTROYS NAIVE AVAILABILITY MATH")
    print(f"  each instance is up {1 - P_INSTANCE:.3%} of the time (p = {P_INSTANCE}).")
    print("  c = the fraction of an instance's downtime that is COMMON CAUSE:")
    print("  a global config push, a deploy, a control plane, a DNS provider,")
    print("  a certificate expiry — things an availability zone boundary does")
    print("  not stop.\n")
    print(f"  {'c':>7}{'2 instances':>16}{'nines':>8}{'3 instances':>16}{'nines':>8}"
          f"{'ceiling':>14}")
    out = []
    for c in (0.0, 0.001, 0.005, 0.01, 0.05, 0.10, 0.25, 0.50):
        row = []
        for n in (2, 3):
            down = c * P_INSTANCE + (1 - c * P_INSTANCE) * ((1 - c) * P_INSTANCE) ** n
            row.append(1.0 - down)
        ceiling = 1.0 - c * P_INSTANCE  # no amount of replication beats this
        cap = "none" if c == 0.0 else f"{nines(ceiling):.2f}n"
        label = f"{c:.3f}"
        print(f"  {label:>7}{row[0]:>15.7%}{nines(row[0]):>8.2f}"
              f"{row[1]:>15.7%}{nines(row[1]):>8.2f}{cap:>14}")
        out.append((c, row[0], row[1]))

    a2_indep = out[0][1]
    a2_1pct = [r for r in out if abs(r[0] - 0.01) < 1e-9][0]
    print(f"\n  with c = 0, two 99.9% instances give {a2_indep:.6%} — the "
          f"{nines(a2_indep):.1f} nines")
    print("  every capacity plan quietly assumes.")
    print(f"  with c = 0.01 — one failure in a hundred is shared — the same pair")
    print(f"  gives {a2_1pct[1]:.5%}: {nines(a2_1pct[1]):.2f} nines, not "
          f"{nines(a2_indep):.2f}.")
    print(f"  adding a THIRD instance moves it to {nines(a2_1pct[2]):.2f} nines. "
          f"Adding a fourth,")
    print("  a fifth, a hundredth moves it nowhere: the ceiling is 1 - c*p.")
    print("  Redundancy multiplies the independent term and does nothing at all")
    print("  to the shared one. Lesson 01 promised this arithmetic; here it is.")
    return out


# ----------------------------------------------------------------------------
# 5 · CELLS: BLAST RADIUS YOU BUY WITH CAPACITY
# ----------------------------------------------------------------------------
# A cell is a complete, independent copy of the stack serving a slice of
# customers. Cells buy you a deploy blast radius of 1/C. They cost you
# headroom, because statistical multiplexing gets worse as the pool shrinks
# and every cell needs its own spare instance.

TOTAL_CUSTOMERS = 24_000
PEAK_RPS = 240_000
INSTANCE_RPS = 1_000
Z_HEADROOM = 3.0   # provision each cell at mean + 3 sigma of its own arrivals
BAKE_MINUTES = 20  # soak time per deploy wave


def section_5() -> list[tuple[int, int, float, float, int]]:
    banner("5 · CELLS: WHAT A SMALLER BLAST RADIUS COSTS IN CAPACITY")
    print(f"  {TOTAL_CUSTOMERS:,} customers, {PEAK_RPS:,} req/s at peak, "
          f"{INSTANCE_RPS:,} req/s per instance.")
    print(f"  each cell is provisioned for its OWN peak (mean + {Z_HEADROOM:.0f}"
          f" sigma, Poisson arrivals)")
    print("  plus one spare instance so it survives losing a host.\n")
    print(f"  {'cells':>6}{'cust/cell':>11}{'inst/cell':>11}{'instances':>11}"
          f"{'overhead':>10}{'deploy blast':>14}{'deploy time':>13}")
    rows = []
    for c in (1, 2, 4, 8, 12, 24, 48, 120):
        mean = PEAK_RPS / c
        need = mean + Z_HEADROOM * math.sqrt(mean)
        per_cell = math.ceil(need / INSTANCE_RPS) + 1  # +1 spare host
        total = per_cell * c
        overhead = total * INSTANCE_RPS / PEAK_RPS - 1.0
        blast = 100.0 / c
        deploy_min = c * BAKE_MINUTES
        rows.append((c, per_cell, overhead, blast, total))
        print(f"  {c:>6}{TOTAL_CUSTOMERS // c:>11,}{per_cell:>11}{total:>11}"
              f"{overhead:>9.1%}{blast:>13.2f}%{deploy_min:>10} min")

    one = rows[0]
    mid = [r for r in rows if r[0] == 24][0]
    print(f"\n  one big fleet: a bad deploy that reaches every instance is a "
          f"{one[3]:.0f}% outage.")
    print(f"  {mid[0]} cells, deployed one cell at a time: the same bad deploy is a "
          f"{mid[3]:.2f}%")
    print(f"  outage, caught after {BAKE_MINUTES} minutes of bake, and it costs "
          f"{mid[2] - one[2]:.1%} more")
    print(f"  hardware ({mid[4]} instances instead of {one[4]}) and "
          f"{mid[0] * BAKE_MINUTES // 60}h to roll out.")
    print("  Note the shape: overhead climbs slowly, then vertically, because")
    print("  once a cell is down to 2-3 instances the +1 spare IS the cell.")
    return rows


# ----------------------------------------------------------------------------
# 6 · STATIC STABILITY: THE SYSTEM THAT NEEDS NOTHING DURING A FAILURE
# ----------------------------------------------------------------------------
# Both fleets lose an availability zone at t = 60 s. One was pre-provisioned to
# survive it and does nothing. The other has to notice, decide, call a control
# plane, and wait for instances to boot — during the event that broke the
# control plane.

DEMAND = 100.0            # units of load, constant
AZS = 3
DETECT_S = 60.0           # metric aggregation window
ALARM_S = 60.0            # datapoints-to-alarm
LAUNCH_S = 180.0          # API call + boot + health check + LB registration
UNITS_PER_BATCH = 5.0     # capacity that arrives per launch batch
BATCH_S = 30.0            # and how often another batch lands (throttled API)
AZ_LOSS_T = 60.0
HORIZON = 600.0
STEP = 30.0


def section_6() -> list[tuple[float, float, float]]:
    banner("6 · STATIC STABILITY: PRE-PROVISIONED VS AUTOSCALING INTO AN OUTAGE")
    static_per_az = DEMAND / (AZS - 1)          # survive losing one AZ, flat
    elastic_per_az = DEMAND * 1.05 / AZS        # 5% headroom, autoscale the rest
    print(f"  constant demand {DEMAND:.0f} units, {AZS} availability zones, "
          f"AZ-2 lost at t={AZ_LOSS_T:.0f}s.")
    print(f"  static  : {static_per_az:.1f} units per AZ = "
          f"{static_per_az * AZS:.1f} total ({static_per_az * AZS / DEMAND - 1:.0%}"
          f" over demand). Does nothing.")
    print(f"  elastic : {elastic_per_az:.1f} units per AZ = "
          f"{elastic_per_az * AZS:.1f} total (5% over demand). Must react.")
    print(f"  reaction budget: {DETECT_S:.0f}s metrics + {ALARM_S:.0f}s alarm + "
          f"{LAUNCH_S:.0f}s launch, then")
    print(f"  {UNITS_PER_BATCH:.0f} units every {BATCH_S:.0f}s "
          f"(the control plane is throttling — it is in the outage too).\n")

    print(f"  {'t (s)':>7}{'static cap':>12}{'served':>9}{'elastic cap':>13}"
          f"{'served':>9}   note")
    rows = []
    lost_static = lost_elastic = 0.0
    t = 0.0
    while t <= HORIZON + 1e-9:
        if t < AZ_LOSS_T:
            s_cap = static_per_az * AZS
            e_cap = elastic_per_az * AZS
            note = ""
        else:
            s_cap = static_per_az * (AZS - 1)
            e_cap = elastic_per_az * (AZS - 1)
            ready_at = AZ_LOSS_T + DETECT_S + ALARM_S + LAUNCH_S
            if t >= ready_at:
                batches = math.floor((t - ready_at) / BATCH_S) + 1
                e_cap += batches * UNITS_PER_BATCH
            e_cap = min(e_cap, DEMAND)  # the autoscaler stops at its target
            note = "<-- AZ-2 gone" if abs(t - AZ_LOSS_T) < 1e-9 else ""
            if abs(t - (AZ_LOSS_T + DETECT_S + ALARM_S + LAUNCH_S)) < 1e-9:
                note = "<-- first new instance in service"
        s_served = min(1.0, s_cap / DEMAND)
        e_served = min(1.0, e_cap / DEMAND)
        rows.append((t, s_served, e_served))
        lost_static += (1 - s_served) * DEMAND * STEP
        lost_elastic += (1 - e_served) * DEMAND * STEP
        print(f"  {t:>7.0f}{s_cap:>12.1f}{s_served:>8.0%}{e_cap:>13.1f}"
              f"{e_served:>8.0%}   {note}".rstrip())
        t += STEP

    recovered = next(
        (r[0] for r in rows if r[0] > AZ_LOSS_T and r[2] >= 0.999), None
    )
    print(f"\n  static  : served 100% throughout. {lost_static:,.0f} requests lost.")
    print(f"  elastic : dropped to {min(r[2] for r in rows):.0%} at t="
          f"{AZ_LOSS_T:.0f}s and did not recover until t={recovered:.0f}s")
    print(f"            — {recovered - AZ_LOSS_T:.0f}s of degradation, "
          f"{lost_elastic:,.0f} requests lost.")
    print(f"  the static fleet costs {static_per_az * AZS / (elastic_per_az * AZS) - 1:.0%}"
          f" more hardware and has zero dependencies")
    print("  during the failure. The elastic fleet is cheaper right up to the")
    print("  minute it needs an API that is having the same bad day it is.")
    return rows


def main() -> None:
    print("FAILURE DOMAINS, BLAST RADIUS & SHUFFLE SHARDING — measured")
    print("Phase 11 · Lesson 09 · seed=7 · stdlib only")
    section_1()
    section_2()
    section_3()
    section_4()
    section_5()
    section_6()
    print(f"\n  (total wall time {time.perf_counter() - START:.1f} s)")


if __name__ == "__main__":
    main()
