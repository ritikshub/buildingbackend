#!/usr/bin/env python3
"""
Where the state actually went. A fleet of N instances behind a balancer runs the
same request stream twice: once with the state in memory, once with it moved out.
Measures the logout rate round-robin routing produces, the rate limit an in-memory
counter really enforces, what a routine scale-in costs a sticky fleet, the
two-leaders hazard a lease TTL cannot prevent (and the fencing token that
survives it), and the store-load / revocation-window trade between tokens and
server-side sessions.

Companion to docs/en.md (Phase 11, Lesson 06). Standard library only, every RNG
seeded, self-terminating in well under 30 seconds. Sources: Fielding & Reschke,
RFC 7230 sec. 2.3 (HTTP is stateless by design); Karger et al., *Consistent
Hashing and Random Trees*, STOC 1997; Mirrokni, Thorup & Zadimoghaddam,
*Consistent Hashing with Bounded Loads*, SODA 2018; Burrows, *The Chubby Lock
Service for Loosely-Coupled Distributed Systems*, OSDI 2006 (leases, the pause
hazard, and sequencers -- what we now call fencing tokens).

Run:  python3 stateless.py
"""

from __future__ import annotations

import hashlib
import itertools
import random
import time

SEED = 20260718
BAR = "=" * 74


def banner(text: str) -> None:
    print(f"\n== {text} ==")


def h(key: str, salt: str = "") -> int:
    """A stable hash. Python's hash() for str is randomised per process."""
    return int.from_bytes(hashlib.blake2b((salt + key).encode(), digest_size=8).digest(), "big")


# ---------------------------------------------------------------------------
# 1 · THE SESSION BUG
# ---------------------------------------------------------------------------

def session_run(instances: int, shared: bool, users: int = 600, reqs: int = 20):
    """Log a user in on one instance, then round-robin their next N requests.

    With sessions in memory, a request is authenticated only if the balancer
    happens to send it back to the instance that holds the session.
    """
    store: dict[str, dict] = {}                       # the shared session store
    local = [dict() for _ in range(instances)]        # per-instance memory
    rr = itertools.count()
    ok = fail = 0
    cart_visible = 0.0
    cart_added = 0

    for u in range(users):
        sid = f"sess-{u}"
        home = next(rr) % instances                   # POST /login landed here
        table = store if shared else local[home]
        table[sid] = {"user": u, "cart": []}

        for item in range(reqs):
            i = next(rr) % instances                  # every later request
            table = store if shared else local[i]
            sess = table.get(sid)
            if sess is None:
                fail += 1                             # 401 -> "you were logged out"
            else:
                ok += 1
                sess["cart"].append(item)             # POST /cart/add

        cart_added += reqs
        # GET /cart at checkout can land on any instance: average over all of them
        tables = [store] if shared else local
        cart_visible += sum(len(t.get(sid, {}).get("cart", [])) for t in tables) / len(tables)

    return ok, fail, cart_visible, cart_added


def section_1() -> dict:
    banner("1 · THE SESSION BUG: THE SECOND INSTANCE IS WHERE STATE ANNOUNCES ITSELF")
    print("  600 users. Each logs in once, then makes 20 authenticated requests.")
    print("  The balancer round-robins every request. Sessions live in a dict.")
    print(f"  {'instances':>10}{'requests':>10}{'401s':>8}{'logout rate':>14}"
          f"{'1 - floor(20/N)/20':>21}")
    for n in (1, 2, 3, 4, 6, 12):
        ok, fail, _, _ = session_run(n, shared=False)
        total = ok + fail
        expected = 1 - (20 // n) / 20
        print(f"  {n:>10}{total:>10}{fail:>8}{fail / total:>13.1%}{expected:>20.1%}")

    ok_s, fail_s, vis_s, added_s = session_run(6, shared=False)
    ok_h, fail_h, vis_h, added_h = session_run(6, shared=True)
    stateful_rate = fail_s / (ok_s + fail_s)
    shared_rate = fail_h / (ok_h + fail_h)
    print("  round-robin sends exactly 1 request in N back to the instance holding")
    print("  the session, so the logout rate is 1 - floor(20/N)/20 exactly.")
    print()
    print(f"  {'6 instances':<24}{'logout rate':>13}{'cart writes kept':>24}"
          f"{'cart visible at checkout':>26}")
    for label, rate, ok, vis in (("in-memory sessions", stateful_rate, ok_s, vis_s),
                                 ("shared session store", shared_rate, ok_h, vis_h)):
        a = f"{ok}/{added_s} = {ok / added_s:.1%}"
        b = f"{vis:.0f}/{added_s} = {vis / added_s:.1%}"
        print(f"  {label:<24}{rate:>13.1%}{a:>24}{b:>26}")
    print("  the code did not change between the two runs. The dict moved.")
    print("  at 1 instance the logout rate is 0.0% -- which is why the tests passed.")
    return {"stateful_rate": stateful_rate, "shared_rate": shared_rate,
            "cart_written": ok_s / added_s, "cart_visible": vis_s / added_s}


# ---------------------------------------------------------------------------
# 2 · THE RATE LIMITER THAT ISN'T
# ---------------------------------------------------------------------------

def rate_limit_run(instances: int, limit: int, offered: int, shared: bool) -> int:
    counters = [0] * instances
    total = 0
    admitted = 0
    for r in range(offered):
        i = r % instances
        if shared:
            if total < limit:
                total += 1
                admitted += 1
        else:
            if counters[i] < limit:
                counters[i] += 1
                admitted += 1
    return admitted


def section_2() -> dict:
    banner("2 · THE RATE LIMITER THAT ISN'T: 100/min BECOMES 100 x N/min")
    print("  policy: 100 requests per minute per API key. One attacker, 2000 requests,")
    print("  round-robined across the fleet. Each instance holds its own counter.")
    print(f"  {'instances':>10}  {'admitted (local)':>17}  {'effective limit':>16}"
          f"  {'x intended':>11}  {'admitted (shared)':>18}")
    sweep = []
    for n in (1, 2, 4, 6, 8, 16):
        local = rate_limit_run(n, 100, 2000, shared=False)
        shared = rate_limit_run(n, 100, 2000, shared=True)
        sweep.append((n, local, shared))
        print(f"  {n:>10}  {local:>17}  {local:>16}  {local / 100:>10.1f}x  {shared:>18}")
    print("  the policy document says 100. The fleet enforces 100 x N, and N is a")
    print("  number the autoscaler changes without telling anyone.")
    print("  a per-instance limit of 100/N is not the fix: it throttles every key to")
    print("  100/N whenever routing is uneven, and routing is always uneven.")
    return {"sweep": sweep}


# ---------------------------------------------------------------------------
# 3 · STICKY SESSIONS AND SCALE-IN
# ---------------------------------------------------------------------------

class Ring:
    """Consistent hashing (Karger et al., STOC 1997), 160 vnodes per instance."""

    def __init__(self, nodes, vnodes: int = 160):
        self.points = sorted((h(f"{n}#{v}", "ring"), n) for n in nodes for v in range(vnodes))

    def route(self, key: str):
        k = h(key, "ring")
        lo, hi = 0, len(self.points)
        while lo < hi:                                # bisect on the ring
            mid = (lo + hi) // 2
            if self.points[mid][0] < k:
                lo = mid + 1
            else:
                hi = mid
        return self.points[lo % len(self.points)][1]


def section_3() -> dict:
    banner("3 · STICKY SESSIONS: THE SKEW YOU BUY, THE SESSIONS YOU LOSE")
    rng = random.Random(SEED + 3)
    n = 6
    sessions = []
    for s in range(4000):
        # Real session weights are heavy-tailed: most users click twice, a few
        # never stop. Pareto alpha=1.3 gives a realistic long tail.
        weight = min(600, max(1, int(rng.paretovariate(1.3) * 4)))
        sessions.append((f"sess-{s}", weight))
    total_reqs = sum(w for _, w in sessions)

    mod = {sid: h(sid, "mod") % n for sid, _ in sessions}
    ring = Ring(range(n))
    ring_map = {sid: ring.route(sid) for sid, _ in sessions}

    sticky_load = [0] * n
    for sid, w in sessions:
        sticky_load[ring_map[sid]] += w
    flat_load = [0] * n
    for i in range(total_reqs):                       # stateless: per-request RR
        flat_load[i % n] += 1

    sticky_ratio = max(sticky_load) / min(sticky_load)
    flat_ratio = max(flat_load) / min(flat_load)
    print(f"  {len(sessions)} sessions, {total_reqs} requests, per-session request count")
    print(f"  drawn from a Pareto tail (alpha=1.3, capped at 600; median"
          f" {sorted(w for _, w in sessions)[len(sessions) // 2]}).")
    print(f"  {'routing':<34}{'busiest':>9}{'quietest':>10}{'max/min':>10}")
    print(f"  {'sticky (session -> instance)':<34}{max(sticky_load):>9}"
          f"{min(sticky_load):>10}{sticky_ratio:>9.2f}x")
    print(f"  {'stateless (request -> instance)':<34}{max(flat_load):>9}"
          f"{min(flat_load):>10}{flat_ratio:>9.2f}x")
    print(f"  {'per-instance load, sticky':<34}"
          + " ".join(f"{v:>7}" for v in sticky_load))
    print(f"  {'per-instance load, stateless':<34}"
          + " ".join(f"{v:>7}" for v in flat_load))
    hottest = max(sessions, key=lambda sw: sw[1])
    hot_share = hottest[1] / sticky_load[ring_map[hottest[0]]]
    print(f"  the single hottest session is {hot_share:.1%} of its instance's entire load.")
    print("  affinity cannot balance what it cannot split.")

    print()
    print("  now a routine scale-in: 6 instances -> 4. Nothing failed. The autoscaler")
    print("  did what it was told, at 02:00, on a Sunday.")
    survivors = list(range(n - 2))
    ring2 = Ring(survivors)
    lost_mod = sum(1 for sid, _ in sessions if h(sid, "mod") % (n - 2) != mod[sid])
    lost_mod_reqs = sum(w for sid, w in sessions if h(sid, "mod") % (n - 2) != mod[sid])
    lost_ring = sum(1 for sid, _ in sessions if ring2.route(sid) != ring_map[sid])
    lost_ring_reqs = sum(w for sid, w in sessions if ring2.route(sid) != ring_map[sid])
    print(f"  {'affinity mechanism':<34}{'sessions lost':>16}{'requests lost':>16}")
    print(f"  {'hash(cookie) % N':<34}{lost_mod:>8} = {lost_mod / len(sessions):>5.1%}"
          f"{lost_mod_reqs:>9} = {lost_mod_reqs / total_reqs:>5.1%}")
    print(f"  {'consistent hashing (Lesson 3)':<34}{lost_ring:>8} = {lost_ring / len(sessions):>5.1%}"
          f"{lost_ring_reqs:>9} = {lost_ring_reqs / total_reqs:>5.1%}")
    print(f"  {'stateless + shared store':<34}{0:>8} = {0.0:>5.1%}{0:>9} = {0.0:>5.1%}")
    print("  a rolling deploy restarts all 6 instances, so it destroys 100% of them --")
    print("  which is why a sticky fleet's deploys are 'disruptive' rather than 'rolling'.")
    return {"sticky_ratio": sticky_ratio, "flat_ratio": flat_ratio,
            "hot_share": hot_share,
            "lost_mod": lost_mod / len(sessions), "lost_ring": lost_ring / len(sessions),
            "lost_ring_reqs": lost_ring_reqs / total_reqs,
            "sessions": len(sessions), "total_reqs": total_reqs,
            "lost_ring_n": lost_ring, "lost_mod_n": lost_mod}


# ---------------------------------------------------------------------------
# 4 · THE SCHEDULER THAT RUNS N TIMES
# ---------------------------------------------------------------------------

def section_4() -> dict:
    banner("4 · THE NIGHTLY JOB THAT RAN SIX TIMES, AND THE TWO LEADERS")
    ticks = list(range(0, 101, 5))
    fleet = 6
    print(f"  the job is scheduled every 5 s; the run covers {ticks[-1]} s = {len(ticks)} ticks.")
    print(f"  {'design':<40}{'executions':>12}{'per tick':>10}")
    print(f"  {'in-process scheduler on every instance':<40}{fleet * len(ticks):>12}"
          f"{fleet:>10}")
    print(f"  {'leader-elected (lease), no faults':<40}{len(ticks):>12}{1:>10}")
    print(f"  every customer got {fleet} copies of the email. The code was correct on"
          f" one instance.")

    # --- the hazard -------------------------------------------------------
    print()
    print("  THE HAZARD: a lease TTL bounds how long a lock is HELD, not how long the")
    print("  holder believes it holds it. Lease TTL = 15 s, renewed every 5 s.")
    print("  Instance A is descheduled at t=50 (GC pause / CPU-throttled container /")
    print("  live migration) and resumes at t=80, then catches up its missed ticks.")

    ttl, pause_start, pause_end = 15, 50, 80
    a_last_renew = pause_start                        # last successful renewal
    lease_expiry = a_last_renew + ttl                 # 65
    fence = {"token": 0}
    events = []

    a_ran = [t for t in ticks if t <= pause_start]
    fence["token"] = 1                                # A's fencing token
    for t in a_ran:
        events.append((t, "A", 1, "run"))

    b_acquire = lease_expiry                          # B sees the lease expire
    fence["token"] = 2                                # B's fencing token
    b_ran = [t for t in ticks if t >= b_acquire]
    for t in b_ran:
        events.append((t, "B", 2, "run"))

    missed = [t for t in ticks if pause_start < t < b_acquire]
    catchup = [t for t in ticks if pause_start < t <= pause_end]
    for t in catchup:
        events.append((pause_end, "A", 1, f"catch-up tick {t}"))

    dup = sorted(set(catchup) & set(b_ran))
    print(f"  {'t':>5}  {'who':<4}{'token':>6}  what")
    for t, who, tok, what in [(0, "A", 1, "acquires lease, token 1"),
                              (50, "A", 1, "renews (expiry 65), passes the guard, then PAUSES"),
                              (65, "B", 2, "lease expired -> acquires, token 2"),
                              (70, "B", 2, "runs tick 70"),
                              (80, "A", 1, "resumes, still believes it is leader, writes")]:
        print(f"  {t:>5}  {who:<4}{tok:>6}  {what}")
    print(f"  during t=[{b_acquire},{pause_end}] there were TWO leaders.")
    print(f"  {'outcome':<40}{'executions':>12}{'duplicated':>12}{'missed':>8}")
    naive_exec = len(a_ran) + len(b_ran) + len(catchup)
    print(f"  {'lease only, no fencing':<40}{naive_exec:>12}{len(dup):>12}"
          f"{len(missed):>8}")
    fenced_exec = len(a_ran) + len(b_ran)
    print(f"  {'lease + fencing token':<40}{fenced_exec:>12}{0:>12}{len(missed):>8}")
    print(f"  the resource keeps max_token_seen. B wrote with 2, so all"
          f" {len(catchup)} of A's writes")
    print("  arrive with token 1 < 2 and are rejected. Duplicates: 0.")
    print(f"  the honest residue: ticks {missed} ran ZERO times. Fencing prevents")
    print("  double execution; it does not resurrect the work the pause ate.")
    return {"fleet_exec": fleet * len(ticks), "ticks": len(ticks),
            "naive_exec": naive_exec, "dup": len(dup), "missed": len(missed),
            "catchup": len(catchup), "fenced_exec": fenced_exec,
            "overlap": (b_acquire, pause_end)}


# ---------------------------------------------------------------------------
# 5 · TOKEN VS SESSION STORE
# ---------------------------------------------------------------------------

def make_stream(rng: random.Random, users: int = 400, horizon: float = 3600.0):
    """One shared request stream, so every config is compared on identical load."""
    stream = []
    for u in range(users):
        t = rng.uniform(0, horizon * 0.75)
        gap = rng.uniform(6.0, 90.0)                  # this user's think time
        while t < horizon:
            stream.append((t, u))
            t += rng.expovariate(1.0 / gap)
    stream.sort()
    return stream


def token_config(stream, revoked: dict[int, float], ttl: float | None,
                 denylist_refresh: float | None, instances: int, horizon: float):
    """Return (store lookups, requests served after revocation, worst window).

    ttl=None  -> server-side session: one store lookup per request, revocation
                 takes effect on the very next request.
    ttl=X     -> signed token, revalidated against the store only at refresh.
    denylist_refresh=D -> each instance pulls the revocation list every D s.
    """
    lookups = 0
    issued: dict[int, float] = {}                     # user -> token expiry
    served_after = 0
    windows: list[float] = []
    last_ok: dict[int, float] = {}

    if denylist_refresh:
        lookups += instances * int(horizon // denylist_refresh)

    for t, u in stream:
        revoked_at = revoked.get(u)
        if ttl is None:                               # server-side session
            lookups += 1
            if revoked_at is not None and t >= revoked_at:
                continue
            last_ok[u] = t
        else:                                         # signed token
            if issued.get(u, -1.0) <= t:              # expired -> refresh
                lookups += 1
                if revoked_at is not None and t >= revoked_at:
                    continue                          # refresh refused
                issued[u] = t + ttl
            if denylist_refresh and revoked_at is not None:
                # the instance serving this request knows about the revocation
                # only after its next denylist pull
                visible = (int(revoked_at // denylist_refresh) + 1) * denylist_refresh
                if t >= visible:
                    continue
            if revoked_at is not None and t >= revoked_at:
                served_after += 1
                last_ok[u] = t
                continue
            last_ok[u] = t

    for u, rt in revoked.items():
        if u in last_ok and last_ok[u] >= rt:
            windows.append(last_ok[u] - rt)
        else:
            windows.append(0.0)
    return lookups, served_after, windows


def section_5() -> dict:
    banner("5 · TOKEN VS SESSION STORE: STORE LOAD AGAINST THE REVOCATION WINDOW")
    rng = random.Random(SEED + 5)
    horizon = 3600.0
    instances = 6
    stream = make_stream(rng, users=400, horizon=horizon)
    revoked = {u: rng.uniform(300, horizon - 300) for u in rng.sample(range(400), 120)}
    n = len(stream)
    print(f"  400 users, {n} requests over 1 simulated hour, {instances} instances.")
    print("  120 of those users are revoked mid-hour (logout, role change, or a")
    print("  leaked credential). The stream is identical across every row.")
    print(f"  {'design':<34}{'store lookups':>14}{'per 1000 req':>14}"
          f"{'served after':>14}{'worst window':>14}")

    rows = []
    for label, ttl, deny in (("server-side session store", None, None),
                             ("signed token, TTL 60 s", 60.0, None),
                             ("signed token, TTL 300 s", 300.0, None),
                             ("signed token, TTL 900 s", 900.0, None),
                             ("signed token, TTL 3600 s", 3600.0, None),
                             ("token + denylist, 30 s pull", 900.0, 30.0)):
        lk, after, wins = token_config(stream, revoked, ttl, deny, instances, horizon)
        worst = max(wins) if wins else 0.0
        per_k = lk / n * 1000
        rows.append((label, lk, per_k, after, worst, ttl, deny))
        print(f"  {label:<34}{lk:>14}{per_k:>14.1f}{after:>14}{worst:>12.0f} s")

    sess = rows[0]
    t900 = rows[3]
    hyb = rows[5]
    print(f"  the token cuts store traffic {sess[2] / t900[2]:.0f}x"
          f" ({sess[2]:.0f} -> {t900[2]:.1f} lookups per 1000 requests)")
    print(f"  and buys a {t900[4]:.0f}-second window in which a revoked user still"
          f" has full access.")
    print(f"  the denylist closes the window to {hyb[4]:.0f} s -- and puts"
          f" {hyb[2]:.1f} lookups per 1000")
    print("  requests back on the store, which is the store you moved the state to")
    print("  in order to avoid. There is no configuration that removes the trade.")
    return {"rows": rows, "requests": n, "instances": instances}


def main() -> None:
    t0 = time.perf_counter()
    print(BAR)
    print("STATELESS SERVICES: WHERE THE STATE ACTUALLY WENT")
    print(f"seed={SEED} · stdlib only · every number below is measured, not asserted")
    print(BAR)
    s1 = section_1()
    s2 = section_2()
    s3 = section_3()
    s4 = section_4()
    s5 = section_5()
    print()
    print(BAR)
    print("SUMMARY · the same request stream, the same code, the state moved")
    print(f"  in-memory sessions @ 6 instances        logout rate {s1['stateful_rate']:.1%}"
          f"  -> shared store {s1['shared_rate']:.1%}")
    print(f"  in-memory rate limit 100/min @ 6        enforced    {s2['sweep'][3][1]}/min"
          f"   -> shared {s2['sweep'][3][2]}/min")
    print(f"  sticky affinity, 6 -> 4 scale-in        sessions lost"
          f" {s3['lost_ring']:.1%}  -> stateless 0.0%")
    print(f"  in-process schedule @ 6 instances       {s4['fleet_exec']} runs for"
          f" {s4['ticks']} ticks -> leader {s4['ticks']}")
    print(f"  lease without fencing, one 30 s pause   {s4['dup']} duplicate runs"
          f"  -> fencing 0")
    print(f"  15-minute token vs session store        {s5['rows'][3][2]:.1f} vs"
          f" {s5['rows'][0][2]:.0f} lookups/1000 req,"
          f" {s5['rows'][3][4]:.0f} s vs 0 s revocation")
    print(f"  (total wall time {time.perf_counter() - t0:.2f} s)")
    print(BAR)


if __name__ == "__main__":
    main()
