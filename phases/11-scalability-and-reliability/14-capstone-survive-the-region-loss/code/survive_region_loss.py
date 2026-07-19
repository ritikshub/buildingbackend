#!/usr/bin/env python3
"""Phase 11, Lesson 14 - Capstone: Survive the Region Loss.
Companion to phases/11-scalability-and-reliability/14-capstone-survive-the-region-loss/docs/en.md

One simulated global service (2 regions x 3 AZs, sharded data tier, fan-out read
path) taken through seven escalating failures, run against a NAIVE and a HARDENED
configuration, then ablated one defence at a time.  Stdlib only, seeded, ~30 s.

Sources: Dean & Barroso, "The Tail at Scale", CACM 56(2), 2013.
         Bronson et al., "Metastable Failures in Distributed Systems", HotOS 2021.
         Beyer et al., "Site Reliability Engineering", O'Reilly, 2016 (error budgets).
         RFC 8767, "Serving Stale Data to Improve DNS Resiliency" (the DNS long tail).
"""

from __future__ import annotations

import math
import random
import sys
import time
from dataclasses import dataclass, replace

# --------------------------------------------------------------------------
# The service, at 1:100 scale.  Ratios - utilization, availability, blast
# radius, budget burn - are scale invariant, and ratios are what we measure.
# Real: 40M users, 60,000 req/s at peak, instances that do 2,500 req/s.
# Sim:                  600 req/s at peak, instances that do   25 req/s.
# --------------------------------------------------------------------------
TICK = 0.5            # simulated seconds per step
PEAK_RPS = 600.0      # simulated peak arrival rate
INST_CAP = 25.0       # work units per second one instance retires
DEADLINE = 0.400      # 400 ms end-to-end client deadline
N_REGIONS = 2
N_AZ = 3              # availability zones per region
MAX_PER_AZ = 18       # autoscaling group hard maximum, per AZ
N_TENANTS = 60        # customers
SHARDS = 8            # data-tier shards
FANOUT = 5            # shards read per request
WRITE_SHARE = 0.15    # fraction of requests that write
SUBSET = 3            # shuffle-shard subset size, per region (Lesson 9)
POISON_TENANT = 17
POISON_COST = 200.0   # the pathological path costs 200x a normal request
HEDGE_AT = 0.020      # hedge a shard read that has not answered in 20 ms (Lesson 11)
APP_MS = 0.006        # application time on top of the fan-out
DEP_CAP = 2.2         # capacity divisor while the dependency is degraded
DEP_LAT = 2.0         # latency multiplier while the dependency is degraded
SAFETY = 0.020        # admission-control safety margin inside the deadline
DETECT_S = 15.0       # health-checked GSLB: time to fail a region out
DNS_TAU = 22.0        # resolver decay constant after the record changes
DNS_FLOOR = 0.018     # resolvers that ignore TTL entirely (RFC 8767 stale serving)
XREGION_MS = 0.080    # extra latency once the edge re-routes to the far region
PROMOTE_S = 45.0      # replica promotion, measured from the decision
BOOT_S = 90.0         # instance boot + warm-up before it takes traffic
SEED = 7

# --------------------------------------------------------------------------
# The failure script.  One continuous timeline; the stages are segments of it.
# --------------------------------------------------------------------------
STAGES = [
    ("1 baseline",        0.0,  30.0),
    ("2 instance dies",  30.0,  60.0),
    ("3 grey failure",   60.0, 105.0),
    ("4 poison tenant", 105.0, 155.0),
    ("5 retry storm",   155.0, 225.0),
    ("6 AZ lost",       225.0, 275.0),
    ("7 region lost",   275.0, 385.0),
]
T_END = STAGES[-1][2]
POISON_FOR = 25.0     # seconds of stage 4 with the poison tenant active
DEGRADE_FOR = 30.0    # seconds of stage 5 with the dependency degraded


@dataclass(frozen=True)
class Cfg:
    name: str
    per_az: int          # L12 - fleet sizing
    p2c: bool            # L03 - power-of-two-choices least-request
    ejection: bool       # L04 - L7 health checks + passive outlier ejection
    shuffle: bool        # L09 - shuffle sharding of tenants onto subsets
    deadlines: bool      # L11 - deadline propagation, drop expired work at dequeue
    retry_budget: bool   # P8 L11 - retries as a fraction of traffic, not a count
    shedding: bool       # P8 L11 - deadline-aware admission control
    hedging: bool        # L11 - hedged requests on the fan-out
    autoscale: bool      # L13 - a control loop
    damped: bool         # L13 - and one that does not chase its own retries
    failover: bool       # L10/L07 - cross-region replicas + health-checked GSLB


NAIVE = Cfg("naive", per_az=5, p2c=False, ejection=False, shuffle=False,
            deadlines=False, retry_budget=False, shedding=False, hedging=False,
            autoscale=True, damped=False, failover=False)

HARDENED = Cfg("hardened", per_az=10, p2c=True, ejection=True, shuffle=True,
               deadlines=True, retry_budget=True, shedding=True, hedging=True,
               autoscale=True, damped=True, failover=True)


# --------------------------------------------------------------------------
# Pre-sampled fan-out service times.  Drawing 5 shard reads per observation a
# million times is the whole runtime budget, so draw 4096 of each shape once
# and index into them.  The distribution is real; only the draws are reused.
# --------------------------------------------------------------------------
def _one_read(rng: random.Random, degraded: bool) -> float:
    u = rng.random()
    t = rng.uniform(0.004, 0.012) if u < 0.96 else rng.uniform(0.030, 0.075)
    return t * (DEP_LAT if degraded else 1.0)


def _fanout(rng: random.Random, degraded: bool, hedge: bool) -> float:
    worst = 0.0
    for _ in range(FANOUT):
        t = _one_read(rng, degraded)
        if hedge and t > HEDGE_AT:                    # a second copy, 20 ms late
            t = min(t, HEDGE_AT + _one_read(rng, degraded))
        if t > worst:
            worst = t
    return worst + APP_MS


def build_tables(rng: random.Random):
    tab, p99 = {}, {}
    for d in (False, True):
        for h in (False, True):
            v = [_fanout(rng, d, h) for _ in range(4096)]
            tab[(d, h)] = v
            p99[(d, h)] = sorted(v)[int(0.99 * len(v))]
    return tab, p99


def wpercentile(pairs: list, p: float) -> float:
    """Percentile over (value, weight) observations."""
    if not pairs:
        return 0.0
    pairs.sort(key=lambda kv: kv[0])
    total = sum(w for _, w in pairs)
    want, seen = total * p, 0.0
    for v, w in pairs:
        seen += w
        if seen >= want:
            return v
    return pairs[-1][0]


def choose(n: int, k: int) -> int:
    return math.comb(n, k) if n >= k >= 0 else 0


# --------------------------------------------------------------------------
# The simulation.  One call runs the whole 385-second failure script.
# --------------------------------------------------------------------------
def run(cfg: Cfg, seed: int = SEED, sample_latency: bool = True) -> dict:
    rng = random.Random(seed)
    tables, svc_p99 = build_tables(random.Random(seed + 1))

    # --- fleet -----------------------------------------------------------
    n_slots = N_REGIONS * N_AZ * MAX_PER_AZ
    reg = [0] * n_slots
    az = [0] * n_slots
    active = [False] * n_slots       # in service and taking traffic
    alive = [True] * n_slots         # process answering at all
    slowf = [1.0] * n_slots          # service-time multiplier
    ejected = [False] * n_slots      # removed from the pool by the LB
    q = [0.0] * n_slots              # queued work units
    lam = [0.0] * n_slots            # EWMA of admitted work rate
    boot_at = [0.0] * n_slots
    bad_since = [-1.0] * n_slots     # when the LB first saw it misbehave

    for r in range(N_REGIONS):
        for a in range(N_AZ):
            for k in range(MAX_PER_AZ):
                i = ((r * N_AZ) + a) * MAX_PER_AZ + k
                reg[i], az[i] = r, a
                active[i] = k < cfg.per_az

    by_region = [[i for i in range(n_slots) if reg[i] == r] for r in range(N_REGIONS)]
    base_active = [i for i in range(n_slots) if active[i]]

    # --- shuffle shards: each tenant gets SUBSET instances per region -----
    # Assignment is a deterministic hash over the LIVE endpoint set, so it
    # rebalances when the fleet changes shape. A static assignment would leave
    # tenants stranded on a dead AZ, which is a real way to get this wrong.
    subsets = [[[] for _ in range(N_REGIONS)] for _ in range(N_TENANTS)]
    shard_sig = [-1] * N_REGIONS

    def rebuild_subsets(r: int) -> None:
        live = [i for i in by_region[r] if active[i]]
        if not live:
            return
        srng = random.Random(seed * 1000 + r * 31 + len(live))
        k = min(SUBSET, len(live))
        for ten in range(N_TENANTS):
            subsets[ten][r] = srng.sample(live, k)
        shard_sig[r] = len(live)

    for r in range(N_REGIONS):
        rebuild_subsets(r)

    # --- pre-drawn randomness (deterministic, and much faster than calling) --
    rpool = [rng.randrange(1 << 30) for _ in range(200003)]
    tpool = [rng.randrange(N_TENANTS) for _ in range(100003)]
    rp = tp = rr = 0

    # --- state -----------------------------------------------------------
    t = 0.0
    dead_inst = dead_az = dead_region = -1
    grey_set: list = []
    t_region_dead = -1.0
    retry_carry = 0.0
    repl_lag = 0.30
    desired = {r: cfg.per_az * N_AZ for r in range(N_REGIONS)}
    util_ewma = {r: 0.0 for r in range(N_REGIONS)}
    next_scale = 20.0
    inst_seconds = 0.0
    good_run = 0.0
    metastable = False

    stage_stats = {s[0]: dict(req=0.0, ok=0.0, shed=0.0, fail=0.0, lat=[],
                              util=0.0, ticks=0, err_s=0.0) for s in STAGES}
    served_curve = []
    tenant = {"req": [0.0] * N_TENANTS, "ok": [0.0] * N_TENANTS}
    notes = {"eject_dead": None, "eject_grey": None, "recover": None,
             "restart": None, "rpo": 0.0, "scale_events": 0,
             "peak_offered": 0.0, "shed_total": 0.0, "fleet_max": 0,
             "p99_dep": 0.0, "resets": [], "trig_avail": 0.0, "trig_n": 0,
             "rpo_lag": 0.0}
    stage_idx = 0
    ti = 0

    while t < T_END - 1e-9:
        while stage_idx + 1 < len(STAGES) and t >= STAGES[stage_idx + 1][1]:
            stage_idx += 1
            # Game-day discipline: each stage is a clean experiment. If the
            # system is still on the floor when the previous one ends, the
            # operator does the only thing left -- restarts the fleet, which is
            # dropping all the load at once with extra steps (Phase 8 L11).
            recent = [v for (tt, v) in served_curve[-10:]]
            if recent and sum(recent) / len(recent) < 0.50:
                for i in range(n_slots):
                    q[i] = lam[i] = 0.0
                retry_carry = 0.0
                notes["resets"].append((STAGES[stage_idx - 1][0], round(t, 1)))
        stage, st0, _ = STAGES[stage_idx]

        # ---------------- fault injection --------------------------------
        if stage_idx == 1 and dead_inst < 0:
            dead_inst = base_active[0]
            alive[dead_inst] = False           # accepts TCP, never answers
        if stage_idx == 2 and not grey_set:
            # 6.7% of EACH fleet, so a bigger fleet does not get an easier fault
            n_grey = max(1, round(0.0667 * len(base_active)))
            grey_set = [i for i in base_active if reg[i] == 1][:n_grey]
            for i in grey_set:
                slowf[i] = 8.0
            alive[dead_inst] = True            # stage 2's instance was replaced
            ejected[dead_inst] = False
            bad_since[dead_inst] = -1.0
        if stage_idx == 3 and grey_set and slowf[grey_set[0]] != 1.0:
            for i in grey_set:                 # grey instances repaired
                slowf[i] = 1.0
                ejected[i] = False
                bad_since[i] = -1.0
        poison = stage_idx == 3 and t - st0 < POISON_FOR
        degraded = stage_idx == 4 and t - st0 < DEGRADE_FOR
        if stage_idx == 5 and dead_az < 0:
            dead_az = 2
            for i in range(n_slots):
                if reg[i] == 0 and az[i] == dead_az:
                    active[i] = False
        if stage_idx == 6 and dead_region < 0:
            dead_region = 0
            t_region_dead = t
            for i in range(n_slots):
                if reg[i] == 0:
                    active[i] = False
                    boot_at[i] = 0.0
            if cfg.failover:   # acknowledged writes that had not replicated yet
                notes["rpo_lag"] = repl_lag
                notes["rpo"] = PEAK_RPS * WRITE_SHARE * 0.5 * repl_lag
            desired[1] = N_AZ * MAX_PER_AZ

        # ---------------- global traffic split (L10) ---------------------
        offered_users = PEAK_RPS * TICK
        share = [0.5, 0.5]
        blackhole = 0.0
        if dead_region >= 0:
            dt = t - t_region_dead
            share = [0.0, 1.0]
            if cfg.failover:
                s_dead = (0.5 if dt < DETECT_S
                          else max(DNS_FLOOR,
                                   0.5 * math.exp(-(dt - DETECT_S) / DNS_TAU)))
                # before the GSLB notices, requests to the dead region time out;
                # after it does, the edge re-routes them (Lesson 5) at +80 ms.
                blackhole = s_dead if dt < DETECT_S else 0.0
            else:
                blackhole = 0.5    # static weighted DNS; the runbook is manual

        arrivals = offered_users * (1.0 - blackhole) + retry_carry
        notes["peak_offered"] = max(notes["peak_offered"], arrivals / TICK)
        retry_carry = 0.0
        lost_blackhole = offered_users * blackhole

        # ---------------- health checks / outlier ejection (L04) ---------
        for i in base_active:
            if not active[i]:
                continue
            bad = (not alive[i]) or slowf[i] > 3.0
            if bad and bad_since[i] < 0:
                bad_since[i] = t
            elif not bad:
                bad_since[i] = -1.0
                ejected[i] = False
            if bad_since[i] >= 0 and not ejected[i]:
                age = t - bad_since[i]
                if cfg.ejection:
                    limit = 6.0 if not alive[i] else 12.0   # L7 probe / outlier detect
                else:
                    limit = 90.0 if not alive[i] else 1e9   # L4 TCP probe; grey invisible
                if age >= limit:
                    ejected[i] = True
                    key = "eject_dead" if not alive[i] else "eject_grey"
                    if notes[key] is None:
                        notes[key] = round(age, 1)

        pool = [[i for i in by_region[r] if active[i] and not ejected[i]]
                for r in range(N_REGIONS)]
        if cfg.shuffle:
            for r in range(N_REGIONS):
                if sum(1 for i in by_region[r] if active[i]) != shard_sig[r]:
                    rebuild_subsets(r)

        # ---------------- route (this is where the LB algorithm lives) ----
        arr_n = [0.0] * n_slots
        arr_w = [0.0] * n_slots
        pairs = {} if (stage_idx == 3 and poison) else None
        for r in range(N_REGIONS):
            cand_all = pool[r]
            if not cand_all or share[r] <= 0.0:
                continue
            for _ in range(int(arrivals * share[r])):
                ten = tpool[tp]
                tp = tp + 1 if tp < 100002 else 0
                if cfg.shuffle:
                    cand = [i for i in subsets[ten][r] if active[i] and not ejected[i]]
                    if not cand:
                        cand = cand_all
                else:
                    cand = cand_all
                n = len(cand)
                if cfg.p2c:
                    a = cand[rpool[rp] % n]
                    b = cand[rpool[rp + 1] % n]
                    rp = rp + 2 if rp < 200000 else 0
                    i = a if q[a] <= q[b] else b
                else:
                    i = cand[rr % n]
                    rr += 1
                arr_n[i] += 1.0
                arr_w[i] += POISON_COST if (poison and ten == POISON_TENANT) else 1.0
                if pairs is not None:
                    k = (ten, i)
                    pairs[k] = pairs.get(k, 0.0) + 1.0

        # ---------------- data tier (L07 / L08 / L10) --------------------
        if dead_region >= 0 and not cfg.failover:
            avail_shards = SHARDS // 2          # no cross-region replica: gone
        else:
            avail_shards = SHARDS
        read_ok = choose(avail_shards, FANOUT) / choose(SHARDS, FANOUT)
        write_fail = 0.0
        if dead_region >= 0 and cfg.failover and (t - t_region_dead) < PROMOTE_S:
            write_fail = WRITE_SHARE * 0.5      # half the shards await promotion
        repl_lag = 0.30 + 1.2 * max(0.0, (arrivals / TICK) / PEAK_RPS - 0.9)

        # ---------------- serve ------------------------------------------
        tab = tables[(degraded, cfg.hedging)]
        p99s = svc_p99[(degraded, cfg.hedging)]
        notes["p99_dep"] = max(notes["p99_dep"], p99s if degraded else 0.0)
        wb = max(0.03, DEADLINE - p99s - SAFETY)   # wait budget the queue may use
        tick_req = tick_ok = tick_shed = tick_fail = 0.0
        work_sum = 0.0
        ok_by_inst = {}
        for i in range(n_slots):
            n_req = arr_n[i]
            if n_req <= 0.0 and q[i] <= 0.0:
                continue
            if not alive[i]:
                tick_req += n_req                # black hole: burns the deadline
                tick_fail += n_req
                ok_by_inst[i] = 0.0
                continue
            cap_rate = INST_CAP / slowf[i] / (DEP_CAP if degraded else 1.0)
            svc = 1.0 / cap_rate
            avg_cost = arr_w[i] / n_req if n_req > 0 else 1.0
            work_sum += arr_w[i] / TICK

            shed_w = 0.0
            if cfg.shedding:
                # Admission control sized from the DEADLINE, not from a constant.
                # W = S*rho/(1-rho) <= wb  =>  rho <= wb / (S + wb)
                rho_max = wb / (svc + wb)
                room = max(0.0, rho_max * cap_rate * TICK - q[i])
                if arr_w[i] > room:
                    shed_w = arr_w[i] - room
            admitted = arr_w[i] - shed_w
            lam[i] = 0.6 * lam[i] + 0.4 * (admitted / TICK)
            rho = min(0.9875, lam[i] / cap_rate)
            backlog = q[i] + admitted
            after = max(0.0, backlog - cap_rate * TICK)
            wait = svc * rho / (1.0 - rho) + after / cap_rate
            if cfg.deadlines and wait > DEADLINE and after > 0.0:
                drop = min(after, (wait - DEADLINE) * cap_rate)   # free to delete
                after -= drop
                shed_w += drop
                wait = svc * rho / (1.0 - rho) + after / cap_rate
            q[i] = after

            k0 = ti * 7 + i
            hits = 0
            for s in range(4):
                if wait + tab[(k0 + s * 977) % 4096] <= DEADLINE:
                    hits += 1
            frac = hits * 0.25 * read_ok * (1.0 - write_fail)
            shed_n = min(n_req, shed_w / avg_cost)
            served_n = n_req - shed_n
            ok = served_n * frac
            tick_req += n_req
            tick_ok += ok
            tick_shed += shed_n
            tick_fail += served_n - ok
            ok_by_inst[i] = frac * served_n / n_req if n_req > 0 else frac
            if sample_latency and ok > 0.0:
                extra = XREGION_MS if (dead_region >= 0 and cfg.failover
                                       and t - t_region_dead >= DETECT_S) else 0.0
                lat = stage_stats[stage]["lat"]
                seen = 0
                for s in range(6):               # latency of what we actually served
                    v = wait + tab[(k0 + s * 1583) % 4096]
                    if v <= DEADLINE:
                        lat.append((v + extra, ok))
                        seen += 1
                if seen == 0:
                    lat.append((DEADLINE + extra, ok))

        tick_fail += lost_blackhole
        # A retry lands at least one tick (500 ms) after the attempt it replaces,
        # which is past the 400 ms deadline, so a retry that succeeds is never a
        # user-visible success. Availability is therefore the FIRST-ATTEMPT
        # success rate applied to real user demand -- retries only ever add load.
        attempts = tick_req or 1.0
        avg_frac = tick_ok / attempts
        user_ok = offered_users * (1.0 - blackhole) * avg_frac

        # ---------------- retries at fleet scale (P8 L11) -----------------
        # each failed attempt produces at most one more attempt next tick, so
        # offered load settles at base/(1-f): benign at f=5%, runaway at f=50%.
        missed = tick_fail + tick_shed
        if cfg.retry_budget:
            retry_carry = min(missed, 0.10 * PEAK_RPS * TICK)
        else:
            retry_carry = min(missed, 7.0 * PEAK_RPS * TICK)

        # ---------------- autoscaler (L13) --------------------------------
        if cfg.autoscale and t >= next_scale:
            next_scale = t + 20.0
            for r in range(N_REGIONS):
                live = [i for i in by_region[r] if active[i]]
                if not live or (dead_region == r):
                    continue
                cap_r = sum(INST_CAP / slowf[i] for i in live if alive[i]) or 1.0
                dem = sum(arr_w[i] for i in by_region[r]) / TICK
                u = dem / cap_r
                # the naive group's max_size was set equal to its desired size,
                # which makes it a monitoring system, not an autoscaler (L13)
                cap_max = N_AZ * MAX_PER_AZ if cfg.damped else cfg.per_az * N_AZ
                if cfg.damped:
                    # scale on ADMITTED demand, smoothed, and never scale in fast
                    util_ewma[r] = 0.55 * util_ewma[r] + 0.45 * min(u, 1.05)
                    tgt = math.ceil(len(live) * util_ewma[r] / 0.60)
                    tgt = max(cfg.per_az * N_AZ, min(tgt, cap_max))
                    if tgt > desired[r]:
                        desired[r] = tgt
                        notes["scale_events"] += 1
                else:
                    tgt = max(N_AZ, min(math.ceil(len(live) * u / 0.60), cap_max))
                    if tgt != desired[r]:
                        desired[r] = tgt
                        notes["scale_events"] += 1
                booting = sum(1 for i in by_region[r] if boot_at[i] > 0.0)
                have = len(live) + booting
                if desired[r] > have:
                    for i in by_region[r]:
                        if (not active[i] and boot_at[i] == 0.0
                                and not (reg[i] == 0 and az[i] == dead_az)):
                            boot_at[i] = t + BOOT_S
                            have += 1
                            if have >= desired[r]:
                                break
                elif desired[r] < len(live):           # scale in
                    for i in reversed(live):
                        if len(live) <= desired[r]:
                            break
                        if i != dead_inst and i not in grey_set:
                            active[i] = False
                            q[i] = lam[i] = 0.0
                            live.remove(i)
        for i in range(n_slots):
            if boot_at[i] > 0.0 and t >= boot_at[i]:
                active[i] = True
                boot_at[i] = 0.0

        # ---------------- bookkeeping ------------------------------------
        ss = stage_stats[stage]
        ss["req"] += offered_users
        ss["ok"] += user_ok
        ss["shed"] += tick_shed
        ss["fail"] += tick_fail
        ss["ticks"] += 1
        n_live = sum(1 for i in range(n_slots) if active[i])
        notes["fleet_max"] = max(notes["fleet_max"], n_live)
        live_cap = sum(INST_CAP / slowf[i] for i in range(n_slots)
                       if active[i] and alive[i]) or 1.0
        ss["util"] += work_sum / live_cap
        avail = user_ok / offered_users if offered_users > 0 else 1.0
        ss["err_s"] += (1.0 - avail) * TICK
        notes["shed_total"] += tick_shed
        inst_seconds += n_live * TICK
        served_curve.append((t, avail))

        if stage_idx == 4:
            if degraded:
                notes["trig_avail"] += avail
                notes["trig_n"] += 1
                if avail < 0.5:
                    metastable = True
            else:
                good_run = good_run + TICK if avail > 0.98 else 0.0
                if good_run >= 5.0 and notes["recover"] is None:
                    notes["recover"] = max(
                        0.0, round(t + TICK - good_run - (st0 + DEGRADE_FOR), 1))
        if pairs is not None:
            for (ten, i), c in pairs.items():
                tenant["req"][ten] += c
                tenant["ok"][ten] += c * ok_by_inst.get(i, 0.0)

        t += TICK
        ti += 1

    out = {"cfg": cfg, "stages": {}, "curve": served_curve, "notes": notes,
           "inst_seconds": inst_seconds}
    tot_req = tot_ok = tot_err_s = 0.0
    for name, a, b in STAGES:
        s = stage_stats[name]
        out["stages"][name] = {
            "avail": s["ok"] / s["req"] if s["req"] > 0 else 1.0,
            "p50": wpercentile(list(s["lat"]), 0.50) * 1000.0,
            "p99": wpercentile(list(s["lat"]), 0.99) * 1000.0,
            "goodput": s["ok"] / max(1e-9, s["ticks"] * TICK),
            "util": s["util"] / max(1, s["ticks"]),
            "err_s": s["err_s"],
            "shed": s["shed"],
        }
        tot_req += s["req"]
        tot_ok += s["ok"]
        tot_err_s += s["err_s"]
    out["avail"] = tot_ok / tot_req if tot_req else 1.0
    out["err_s"] = tot_err_s
    tav = [tenant["ok"][i] / tenant["req"][i]
           for i in range(N_TENANTS) if tenant["req"][i] > 0]
    out["blast99"] = sum(1 for a in tav if a < 0.99)   # measurably touched
    out["blast"] = sum(1 for a in tav if a < 0.95)     # materially degraded
    out["blast50"] = sum(1 for a in tav if a < 0.50)   # effectively down
    out["blast_n"] = len(tav)
    out["worst_tenant"] = min(tav) if tav else 1.0
    out["poison_tenant"] = (tenant["ok"][POISON_TENANT] / tenant["req"][POISON_TENANT]
                            if tenant["req"][POISON_TENANT] > 0 else 1.0)
    return out


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------
def bar(v: float, hi: float, w: int = 24) -> str:
    n = int(round(w * max(0.0, min(1.0, v / hi)))) if hi > 0 else 0
    return "#" * n + "." * (w - n)


def main() -> int:
    t_start = time.time()
    budget_min = 43830.0 * 0.0005
    naive_cap = NAIVE.per_az * N_AZ * N_REGIONS * INST_CAP
    hard_cap = HARDENED.per_az * N_AZ * N_REGIONS * INST_CAP

    print("== 0 . THE SERVICE, THE SLO, AND THE ARITHMETIC ==")
    print(f"  40,000,000 users. Peak {PEAK_RPS*100:,.0f} req/s real; this simulator")
    print(f"  runs 1:100 of it -- {PEAK_RPS:.0f} req/s across {N_REGIONS} regions"
          f" x {N_AZ} AZs (AZ =")
    print(f"  Availability Zone). Every ratio below is scale invariant.")
    print(f"  one instance retires {INST_CAP:.0f} req/s; client deadline"
          f" {DEADLINE*1000:.0f} ms; each read")
    print(f"  fans out to {FANOUT} of {SHARDS} shards; {WRITE_SHARE:.0%} of traffic writes;"
          f" {N_TENANTS} customers.")
    print()
    print("  the SLO leadership signed: 99.95% availability, monthly window.")
    print("    a month averages 365.25/12 = 30.44 days = 43,830 minutes")
    print(f"    0.05% of 43,830 min = {budget_min:.1f} minutes of downtime per month")
    print(f"    = {budget_min*60:.0f} error-seconds for everything: deploys, dependencies,")
    print(f"      DNS, human error, and every failure in this script.")
    print()
    print("  the two fleets, sized by Lesson 12's arithmetic:")
    print(f"    naive     {NAIVE.per_az:2d}/AZ x {N_AZ*N_REGIONS} AZs ="
          f" {NAIVE.per_az*N_AZ*N_REGIONS:2d} instances = {naive_cap:.0f} req/s"
          f"    peak util {PEAK_RPS/naive_cap:.0%}")
    print(f"              peak / (cap x 0.80). Defensible, and it has no headroom")
    print(f"              for losing anything at all.")
    print(f"    hardened  {HARDENED.per_az:2d}/AZ x {N_AZ*N_REGIONS} AZs ="
          f" {HARDENED.per_az*N_AZ*N_REGIONS:2d} instances = {hard_cap:.0f} req/s"
          f"   peak util {PEAK_RPS/hard_cap:.0%}")
    print(f"              peak / (cap x 0.80) x R/(R-1), R = {N_REGIONS} regions, so ONE")
    print(f"              region alone runs the entire service at 80%.")
    print(f"    the list price of surviving a region loss is"
          f" {hard_cap/naive_cap:.1f}x the fleet.")
    print()

    print("  running the 7-stage failure script against both configurations ...",
          flush=True)
    res = {}
    for cfg in (NAIVE, HARDENED):
        t0 = time.time()
        res[cfg.name] = run(cfg)
        print(f"    {cfg.name:9s} {T_END:.0f} simulated seconds in"
              f" {time.time()-t0:5.1f} s wall", flush=True)
    print()
    nv, hd = res["naive"], res["hardened"]

    def header():
        print(f"  {'':26s} {'NAIVE':>8s} {'p99 ms':>7s} {'good/s':>7s}"
              f"  | {'HARDENED':>8s} {'p99 ms':>7s} {'good/s':>7s}")

    def p99s(d):
        return f"{d['p99']:.0f}" if d["p99"] > 0 else "n/a"

    def row(tag, key):
        n, h = nv["stages"][key], hd["stages"][key]
        print(f"  {tag:<26s} {n['avail']:>8.2%} {p99s(n):>7s} {n['goodput']:>7.0f}"
              f"  | {h['avail']:>8.2%} {p99s(h):>7s} {h['goodput']:>7.0f}")

    print("== 1 . STAGE 1 - BASELINE AT PEAK ==")
    print("  (p99 is over the requests actually served; availability is beside it,")
    print("   because a fast service that answers nobody has a beautiful p99.)")
    header()
    row("steady state, 600 req/s", "1 baseline")
    n1, h1 = nv["stages"]["1 baseline"], hd["stages"]["1 baseline"]
    print(f"    fleet utilization      naive {n1['util']:.0%}"
          f"        hardened {h1['util']:.0%}")
    print(f"    p50 latency            naive {n1['p50']:.0f} ms"
          f"      hardened {h1['p50']:.0f} ms")
    print("    both meet the SLO. Note the p99 gap on a day when nothing is wrong:")
    print("    W = S/(1-rho) is already charging the naive fleet for running at 80%.")
    print("    Headroom is not only insurance -- you are paid in latency every day.")
    print()

    print("== 2 . STAGE 2 - ONE INSTANCE STOPS ANSWERING ==")
    print("    the process does not exit. It accepts the TCP connection and never")
    print("    replies -- the common case, and the one a layer-4 check cannot see.")
    header()
    row("1 of 30 / 1 of 60 hung", "2 instance dies")
    print(f"    ejected after   hardened {hd['notes']['eject_dead']} s"
          f"  (L7 probe, 3 failures x 2 s)")
    ed = nv['notes']['eject_dead']
    print(f"                    naive    {ed if ed else 'never within the stage'}"
          f"  (L4 TCP probe, 3 x 30 s = 90 s)")
    print("    a layer-4 probe asks 'is the port open'. The port is open. The naive")
    print("    fleet keeps sending 1/30 of its traffic into it, and every one of")
    print("    those requests burns the full 400 ms deadline before it fails.")
    print()

    print("== 3 . STAGE 3 - GREY FAILURE: SLOW, NOT DEAD ==")
    ng_n = round(0.0667 * NAIVE.per_az * N_AZ * N_REGIONS)
    ng_h = round(0.0667 * HARDENED.per_az * N_AZ * N_REGIONS)
    print(f"    6.7% of EACH fleet ({ng_n} naive, {ng_h} hardened -- a bigger fleet must")
    print("    not get an easier fault) degrades to 8x its normal service time.")
    print("    They still accept connections and still return 200s. Only slow.")
    header()
    row("8x slow: RR vs P2C", "3 grey failure")
    n3, h3 = nv["stages"]["3 grey failure"], hd["stages"]["3 grey failure"]
    sick = round(0.0667 * NAIVE.per_az * N_AZ * N_REGIONS) / (NAIVE.per_az * N_AZ * N_REGIONS)
    print(f"    goodput gap     {h3['goodput'] - n3['goodput']:+.0f} req/s"
          f"   ({h3['goodput']/max(1e-9, n3['goodput']):.2f}x)")
    print(f"    naive lost {1-n3['avail']:.2%} of its traffic. The sick fraction of")
    print(f"    its fleet is {sick:.2%}. Those two numbers are the same number, and")
    print(f"    that is round-robin's signature: its failure rate equals the")
    print(f"    fraction of the fleet that is broken, by construction.")
    print(f"    ejected after   hardened {hd['notes']['eject_grey']} s"
          f"  (passive outlier detection on latency)")
    eg = nv['notes']['eject_grey']
    print(f"                    naive    {eg if eg else 'never'}"
          "     -- a TCP check cannot see a slow process")
    print("    round-robin is an algorithm that decided in advance to send exactly")
    print("    1/N of your traffic to your worst machine, forever. Least-request")
    print("    reads the queue depth it already has and stops feeding it.")
    print()

    print("== 4 . STAGE 4 - A POISON TENANT ==")
    print(f"    customer #{POISON_TENANT} of {N_TENANTS} hits a path costing"
          f" {POISON_COST:.0f}x a normal request")
    print(f"    for {POISON_FOR:.0f} s. Same API, same code, same deploy.")
    header()
    row(f"{POISON_COST:.0f}x cost, 1 of {N_TENANTS} tenants", "4 poison tenant")
    print(f"    BLAST RADIUS -- how many of the {N_TENANTS} customers felt it:")
    print(f"      {'':10s} {'<99% (touched)':>15s} {'<95% (degraded)':>16s}"
          f" {'<50% (down)':>12s}")
    for tag, r in (("naive", nv), ("hardened", hd)):
        print(f"      {tag:<10s} {r['blast99']:>10d}/{r['blast_n']:<4d}"
              f" {r['blast']:>11d}/{r['blast_n']:<4d}"
              f" {r['blast50']:>7d}/{r['blast_n']:<4d}")
    print(f"      worst-hit customer:  naive {nv['worst_tenant']:.1%}"
          f"    hardened {hd['worst_tenant']:.1%}")
    print(f"      the customer who CAUSED it: naive {nv['poison_tenant']:.1%},"
          f" hardened {hd['poison_tenant']:.1%}")
    print(f"    shuffle sharding puts every tenant on {SUBSET} instances of"
          f" {HARDENED.per_az*N_AZ} per region.")
    print(f"    Sharing 2 of 3 with the poisoned tenant has probability"
          f" {3*(HARDENED.per_az*N_AZ-3)/choose(HARDENED.per_az*N_AZ,3):.1%}; sharing all")
    print(f"    3 is 1 in {choose(HARDENED.per_az*N_AZ,3):,}. Without it every customer"
          f" shares every instance,")
    print(f"    so one customer's bad query is the whole fleet's bad query.")
    print()

    print("== 5 . STAGE 5 - A DEPENDENCY DEGRADES, THEN THE RETRIES ARRIVE ==")
    print(f"    the data tier loses 55% of its capacity for {DEGRADE_FOR:.0f} s and is then")
    print("    fully restored. Watch what happens AFTER it is restored.")
    header()
    row("dep -55%, retry storm", "5 retry storm")
    print(f"    peak offered load     naive {nv['notes']['peak_offered']:.0f} req/s"
          f"    hardened {hd['notes']['peak_offered']:.0f} req/s"
          f"   (real demand {PEAK_RPS:.0f})")
    print(f"    load shed on purpose  naive {nv['stages']['5 retry storm']['shed']:.0f}"
          f"          hardened {hd['stages']['5 retry storm']['shed']:.0f} requests")
    print(f"    availability WHILE the dependency was degraded:")
    print(f"      naive     {nv['notes']['trig_avail']/max(1,nv['notes']['trig_n']):.1%}"
          f"         hardened"
          f" {hd['notes']['trig_avail']/max(1,hd['notes']['trig_n']):.1%}")
    print("    time to recover once the trigger was removed:")
    hr = hd['notes']['recover']
    nr = nv['notes']['recover']
    print(f"      hardened  {hr} s"
          f"{'  (inside one 0.5 s tick: it never left the healthy state)' if hr == 0.0 else ''}")
    print(f"      naive     {'NEVER -- still collapsed 40 s later' if nr is None else str(nr)+' s'}")
    print("    a metastable failure (Bronson et al., HotOS 2021): the system now")
    print("    sustains its own outage out of retries. Removing the cause does not")
    print("    remove the effect, because the effect stopped depending on it.")
    print()

    print("== 6 . STAGE 6 - AN ENTIRE AZ IS LOST ==")
    print("    the arithmetic that matters is PER REGION, not fleet-wide: DNS is")
    print("    still splitting traffic 50/50, so us-east must serve 300 req/s")
    print(f"    with {N_AZ-1} of its {N_AZ} zones.")
    nleft = NAIVE.per_az * (N_AZ - 1) * INST_CAP
    hleft = HARDENED.per_az * (N_AZ - 1) * INST_CAP
    half = PEAK_RPS / N_REGIONS
    print(f"    naive     {NAIVE.per_az*(N_AZ-1)} instances left = {nleft:.0f} req/s"
          f" vs {half:.0f} offered = rho {half/nleft:.2f}")
    print(f"    hardened  {HARDENED.per_az*(N_AZ-1)} instances left = {hleft:.0f} req/s"
          f" vs {half:.0f} offered = rho {half/hleft:.2f}")
    header()
    row("us-east-1c gone", "6 AZ lost")
    n6, h6 = nv["stages"]["6 AZ lost"], hd["stages"]["6 AZ lost"]
    print(f"    at rho = {half/nleft:.2f} the queueing wait is S/(1-rho) ="
          f" {1/(1-min(0.99, half/nleft)):.0f}x the service time,")
    print(f"    and rho > 1 is not a percentage at all -- it is a deficit that")
    print(f"    accumulates forever. The naive fleet did not lose 1/6 of its")
    print(f"    capacity; it drove off the knee. This is what Lesson 12's N/(N-1)")
    print(f"    rule buys: hardened needed {half/hleft:.0%} of a zone-down region"
          f" and had it.")
    print()

    print("== 7 . STAGE 7 - THE REGION IS LOST ==")
    header()
    row("us-east gone: evacuate", "7 region lost")
    print(f"    naive     shard primaries AND their replicas both lived in us-east.")
    print(f"              {SHARDS//2} of {SHARDS} shards are gone, and a read that fans out to"
          f" {FANOUT} of {SHARDS}")
    print(f"              cannot be satisfied from {SHARDS - SHARDS//2}: C(4,5)/C(8,5) = 0.")
    print(f"              Data gravity beat the compute plan -- even the SURVIVING")
    print(f"              region serves 0%. DNS is static weighted and the runbook")
    print(f"              is manual, so nothing moved inside the"
          f" {STAGES[6][2]-STAGES[6][1]:.0f} s window either.")
    print(f"    hardened  GSLB health check fails the region out after {DETECT_S:.0f} s;")
    print(f"              resolvers decay with tau = {DNS_TAU:.0f} s toward a"
          f" {DNS_FLOOR:.1%} floor that")
    print(f"              never clears (RFC 8767). The edge re-routes those anyway,")
    print(f"              at +{XREGION_MS*1000:.0f} ms. Replica promotion took"
          f" {PROMOTE_S:.0f} s; writes to the {SHARDS//2}")
    print(f"              promoted shards failed for that window.")
    print(f"              RPO = {hd['notes']['rpo']:.0f} acknowledged writes lost"
          f" ({PEAK_RPS*WRITE_SHARE*0.5:.0f} writes/s to the")
    print(f"              affected shards x {hd['notes']['rpo_lag']:.2f} s of replication lag at the cut).")
    print(f"              autoscaler added capacity to the survivor:"
          f" {HARDENED.per_az*N_AZ} -> {hd['notes']['fleet_max']} instances")
    print(f"              at a {BOOT_S:.0f} s boot delay.")
    print()
    print("    served fraction, 10-second buckets from the moment of the loss:")
    per = int(10.0 / TICK)
    for tag, r in (("naive   ", nv), ("hardened", hd)):
        pts = [v for (tt, v) in r["curve"] if tt >= STAGES[6][1]]
        b = [sum(pts[k:k + per]) / per for k in range(0, len(pts) - per + 1, per)]
        print(f"      {tag}  " + " ".join(f"{x*100:4.0f}" for x in b[:11]))
    print("      t+ (s)    " + " ".join(f"{k*10:4d}" for k in range(11)))
    print()

    print("== 8 . THE SEVEN STAGES, SIDE BY SIDE ==")
    print(f"  {'stage':<18s} {'NAIVE':>9s} {'p99':>6s} {'good/s':>7s} {'util':>6s}"
          f" | {'HARDENED':>9s} {'p99':>6s} {'good/s':>7s} {'util':>6s}")
    for name, a, b in STAGES:
        n, h = nv["stages"][name], hd["stages"][name]
        print(f"  {name:<18s} {n['avail']:>9.2%} {p99s(n):>6s} {n['goodput']:>7.0f}"
              f" {min(n['util'],9.99):>6.0%} | {h['avail']:>9.2%} {p99s(h):>6s}"
              f" {h['goodput']:>7.0f} {h['util']:>6.0%}")
    print(f"  {'WHOLE RUN':<18s} {nv['avail']:>9.2%} {'':>6s} {'':>7s} {'':>6s}"
          f" | {hd['avail']:>9.2%}")
    print()

    print("== 9 . ERROR BUDGET ACCOUNTING ==")
    print(f"  the budget: 99.95% x 43,830 min/month = {budget_min:.1f} min ="
          f" {budget_min*60:.0f} error-seconds")
    print(f"  the exercise: {T_END:.0f} simulated seconds ({T_END/60:.1f} min) of")
    print(f"  deliberate failure injection, identical for both configurations.")
    print()
    print(f"  {'':10s} {'error-seconds':>14s} {'minutes':>9s} {'% of budget':>12s}"
          f" {'exercises/month':>17s}")
    for r in (nv, hd):
        pct = r["err_s"] / (budget_min * 60.0)
        print(f"  {r['cfg'].name:<10s} {r['err_s']:>14.1f} {r['err_s']/60:>9.2f}"
              f" {pct:>11.1%} {1.0/pct if pct > 0 else 999:>17.1f}")
    pn = nv["err_s"] / (budget_min * 60.0)
    ph = hd["err_s"] / (budget_min * 60.0)
    print()
    print(f"  the naive configuration spent {pn:.0%} of an entire month's error")
    print(f"  budget in {T_END/60:.1f} minutes. It can afford {1.0/pn:.1f} such days per month")
    print(f"  and nothing else may ever go wrong -- no deploy, no dependency, no")
    print(f"  human error. The hardened one can afford {1.0/ph:.0f}.")
    print(f"  ratio: {nv['err_s']/max(1e-9, hd['err_s']):.1f}x less budget burned."
          f" Same faults, same traffic,")
    print(f"  same code paths. The difference is architecture.")
    print()

    print("== 10 . ABLATION - WHAT EACH DEFENCE WAS ACTUALLY WORTH ==")
    print("  the same 7-stage script, re-run with exactly ONE defence disabled at")
    print("  a time. The delta against the hardened baseline is that defence's")
    print("  measured contribution. This is the only honest way to know which")
    print("  techniques earned their complexity.")
    defences = [
        ("cross-region replicas L10", dict(failover=False)),
        ("capacity headroom    L12", dict(per_az=NAIVE.per_az)),
        ("load shedding      P8L11", dict(shedding=False)),
        ("deadline propagation L11", dict(deadlines=False)),
        ("retry budget       P8L11", dict(retry_budget=False)),
        ("shuffle sharding     L09", dict(shuffle=False)),
        ("outlier ejection     L04", dict(ejection=False)),
        ("least-request LB     L03", dict(p2c=False)),
        ("hedged reads         L11", dict(hedging=False)),
        ("autoscaling          L13", dict(autoscale=False)),
    ]
    rows = []
    for label, off in defences:
        r = run(replace(HARDENED, **off), sample_latency=False)
        rows.append((label, r["avail"], r["err_s"], r["blast"]))
        print(f"    ablating {label:<26s} avail {r['avail']:7.2%}"
              f"   err-s {r['err_s']:8.1f}   blast {r['blast']:2d}/{r['blast_n']}",
              flush=True)
    print()
    rows.sort(key=lambda x: -x[2])
    base_av, base_es, base_bl = hd["avail"], hd["err_s"], hd["blast"]
    hi = max(max(r[2] - base_es for r in rows), 1.0)
    print(f"  {'defence removed':<26s} {'avail':>8s} {'cost of removing it':>21s}"
          f" {'blast':>7s}")
    for label, av, es, bl in rows:
        print(f"  {label:<26s} {av:>8.2%} {es-base_es:>+14.1f} err-s {bl:>4d}/60  "
              f"{bar(es - base_es, hi)}")
    print(f"  {'-- none (hardened) --':<26s} {base_av:>8.2%} {0.0:>+14.1f} err-s"
          f" {base_bl:>4d}/60")
    print()
    neg = [r for r in rows if r[2] - base_es < -0.5]
    print(f"  {len(neg)} of those rows {'is' if len(neg)==1 else 'are'} NEGATIVE:"
          f" removing the defence made aggregate")
    print("  availability BETTER. That is not a bug, it is the most useful line in")
    print("  the table. Shuffle sharding does not reduce total damage -- it decides")
    print("  WHO receives it. Read its two columns together: aggregate availability")
    print(f"  {base_av:.2%} -> {neg[0][1]:.2%} if you remove it, and customers driven"
          f" below 95%")
    print(f"  {base_bl}/60 -> {neg[0][3]}/60. It trades a point of fleet-wide")
    print("  availability for the promise that one customer's bad query cannot")
    print("  become every customer's bad query. That is the trade; make it knowingly.")
    print()
    print("  == the order of defences: measured interactions ==")
    print("  a defence worth ~nothing on its own can be the only thing holding up")
    print("  another. Removing PAIRS shows the dependency:")
    solo = {lab: es - base_es for lab, _, es, _ in rows}
    combos = [
        ("shedding + retry budget",
         ["load shedding      P8L11", "retry budget       P8L11"],
         dict(shedding=False, retry_budget=False)),
        ("headroom + autoscaling",
         ["capacity headroom    L12", "autoscaling          L13"],
         dict(per_az=NAIVE.per_az, autoscale=False)),
        ("shedding + deadlines",
         ["load shedding      P8L11", "deadline propagation L11"],
         dict(shedding=False, deadlines=False)),
        ("least-request + ejection",
         ["least-request LB     L03", "outlier ejection     L04"],
         dict(p2c=False, ejection=False)),
    ]
    print(f"  {'pair removed':<26s} {'measured':>10s} {'sum of parts':>13s}"
          f" {'interaction':>12s}")
    for label, parts, off in combos:
        r = run(replace(HARDENED, **off), sample_latency=False)
        got = r["err_s"] - base_es
        expect = sum(solo[p] for p in parts)
        ratio = got / expect if abs(expect) > 0.5 else float("nan")
        rs = f"{ratio:.1f}x" if ratio == ratio else "n/a"
        print(f"  {label:<26s} {got:>+9.1f} {expect:>+12.1f} {rs:>12s}")
    print()
    print("  the first three pairs cost far MORE than the sum of their parts:")
    print("  each is a dependency, not an addition. Shedding without a retry")
    print("  budget is a system that sheds a request and is immediately handed")
    print("  it back. Headroom without an autoscaler cannot be reclaimed, and an")
    print("  autoscaler without headroom has nothing to reclaim -- it is still")
    print("  booting when the deadline passes. The fourth pair is the honest")
    print("  null result: against THIS script the two routing defences do not")
    print("  interact, because the fleet had the headroom to absorb the sick")
    print("  instances either way. A predicted interaction that does not appear")
    print("  is a finding; publishing only the three that worked is not.")
    print()

    print("== 11 . THE BILL ==")
    n_cost, h_cost = nv["inst_seconds"], hd["inst_seconds"]
    scale = 100.0 * (30.44 * 86400.0 / T_END) / 3600.0 * 0.096
    print(f"  instance-seconds consumed across the run (autoscaling included):")
    print(f"    naive     {n_cost:>10,.0f}")
    print(f"    hardened  {h_cost:>10,.0f}   ({h_cost/n_cost:.2f}x)")
    print(f"  extrapolated at $0.096 per instance-hour, at 1:100 scale, per month:")
    print(f"    naive     ${n_cost*scale:>12,.0f}")
    print(f"    hardened  ${h_cost*scale:>12,.0f}"
          f"   (+${(h_cost-n_cost)*scale:,.0f}/month)")
    print(f"  so: {nv['err_s']/max(1e-9, hd['err_s']):.0f}x less error budget burned for"
          f" {h_cost/n_cost:.1f}x the compute spend.")
    print(f"  whether that trade is worth making is a business decision, not an")
    print(f"  engineering one -- but it is now a decision with two numbers in it.")
    print()
    print(f"  operator restarts needed to get through the exercise:")
    for tag, r in (("naive", nv), ("hardened", hd)):
        rs = r["notes"]["resets"]
        print(f"    {tag:<10s} {len(rs)}"
              + ("   after: " + ", ".join(f"{n} (t={x} s)" for n, x in rs) if rs else ""))
    print(f"  a restart is not a recovery. It is the absence of any other option,")
    print(f"  and each one is a full cold-start of every queue and cache you had.")
    print()
    print(f"  total wall time: {time.time()-t_start:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
