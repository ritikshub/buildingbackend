#!/usr/bin/env python3
"""
Rollback, Backups & Disaster Recovery — Phase 10, Lesson 14.
Docs: phases/10-infrastructure-and-deployment/14-rollback-backups-and-disaster-recovery/docs/en.md
Six arguments: which releases you can actually roll back to, why one rollback is
really three, how an incremental chain dies at its weakest link, point-in-time
recovery from a write-ahead log, RTO measured instead of asserted, and a backup
job that is green every night and useless.
Sources: PostgreSQL 16 manual ch. 25-26 (backup, continuous archiving & PITR);
RFC 6234 (SHA-256); Google SRE Book ch. 26, "Data Integrity".
Stdlib only. Seeded with random.Random(7). Self-terminating, ~12 s.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import statistics
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

RNG = random.Random(7)


def rule(title: str) -> None:
    print("\n== %s ==" % title)


def hms(seconds: float) -> str:
    """Format a duration the way an incident channel says it out loud."""
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "%dh %02dm %02ds" % (h, m, s)
    if m:
        return "%dm %02ds" % (m, s)
    return "%ds" % s


def clock(t: float, base: float = 0.0) -> str:
    """Seconds-since-midnight -> HH:MM:SS.mmm."""
    t = base + t
    h, rem = divmod(t, 3600.0)
    m, s = divmod(rem, 60.0)
    return "%02d:%02d:%06.3f" % (int(h), int(m), s)


# ----------------------------------------------------------------------------
# 1 · ROLLBACK REACHABILITY
# ----------------------------------------------------------------------------
# A release is reachable by rollback only if every schema element and every wire
# contract its code touches STILL EXISTS in the world the later releases left
# behind. Elements are namespaced: db:<table>.<column> and topic:<name>.<ver>.


@dataclass(frozen=True)
class Release:
    n: int
    build: str
    summary: str
    needs: Tuple[str, ...]           # elements this build reads or writes
    adds: Tuple[str, ...] = ()       # elements this release created
    drops: Tuple[str, ...] = ()      # elements this release removed from the world
    config: Tuple[Tuple[str, str], ...] = ()   # full config snapshot
    irreversible: Tuple[str, ...] = ()         # side effects with no undo


CORE = ("db:user.email", "db:user.prefs_json")
V1_CFG = (("FULLNAME_READ", "off"), ("ORDERS_PAYLOAD", "v1"), ("PRICE_ROUNDING", "half-up"))
V5_CFG = (("FULLNAME_READ", "on"), ("ORDERS_PAYLOAD", "v1"), ("PRICE_ROUNDING", "half-up"))
V9_CFG = (("FULLNAME_READ", "on"), ("ORDERS_PAYLOAD", "v2"), ("PRICE_ROUNDING", "half-up"))
V10_CFG = (("FULLNAME_READ", "on"), ("ORDERS_PAYLOAD", "v2"), ("PRICE_ROUNDING", "banker"))

HISTORY: Tuple[Release, ...] = (
    Release(1, "a1c3e0", "baseline",
            CORE + ("db:user.name", "topic:orders.v1"),
            adds=CORE + ("db:user.name", "topic:orders.v1"), config=V1_CFG),
    Release(2, "b7e042", "artifact only: null-pointer fix in checkout",
            CORE + ("db:user.name", "topic:orders.v1"), config=V1_CFG),
    Release(3, "c2f9a8", "expand: ADD COLUMN user.full_name (nullable)",
            CORE + ("db:user.name", "db:user.full_name", "topic:orders.v1"),
            adds=("db:user.full_name",), config=V1_CFG),
    Release(4, "d4a17b", "backfill user.full_name (18.2M rows), dual-write",
            CORE + ("db:user.name", "db:user.full_name", "topic:orders.v1"), config=V1_CFG),
    Release(5, "e8b6cc", "config: FULLNAME_READ=on (reads switch over)",
            CORE + ("db:user.name", "db:user.full_name", "topic:orders.v1"), config=V5_CFG),
    Release(6, "f1d803", "artifact: stop writing user.name",
            CORE + ("db:user.full_name", "topic:orders.v1"), config=V5_CFG),
    Release(7, "9a2c5e", "contract: DROP COLUMN user.name",
            CORE + ("db:user.full_name", "topic:orders.v1"),
            drops=("db:user.name",), config=V5_CFG),
    Release(8, "3e5f11", "expand: ADD user.email_verified NOT NULL DEFAULT",
            CORE + ("db:user.full_name", "db:user.email_verified", "topic:orders.v1"),
            adds=("db:user.email_verified",), config=V5_CFG),
    Release(9, "6b0d7a", "orders payload v1->v2, consumers now v2-only",
            CORE + ("db:user.full_name", "db:user.email_verified", "topic:orders.v2"),
            adds=("topic:orders.v2",), drops=("topic:orders.v1",), config=V9_CFG,
            irreversible=("12,412 'verify your email' messages sent to real inboxes",)),
    Release(10, "8c7419", "CURRENT: artifact+config, banker's rounding",
            CORE + ("db:user.full_name", "db:user.email_verified", "topic:orders.v2"),
            config=V10_CFG,
            irreversible=("1,204 cards charged under the new rounding rule",)),
)


def world_after(history: Tuple[Release, ...], upto: int) -> Dict[str, int]:
    """Elements that exist after applying releases 1..upto, and who added them."""
    world: Dict[str, int] = {}
    for rel in history:
        if rel.n > upto:
            break
        for elem in rel.adds:
            world[elem] = rel.n
        for elem in rel.drops:
            world.pop(elem, None)
    return world


def killed_by(history: Tuple[Release, ...], elem: str, upto: int) -> Optional[Release]:
    """The most recent release at or before `upto` that removed `elem`."""
    for rel in reversed([r for r in history if r.n <= upto]):
        if elem in rel.drops:
            return rel
    return None


def reachability(history: Tuple[Release, ...]) -> List[Dict[str, Any]]:
    current = history[-1]
    world = world_after(history, current.n)
    rows: List[Dict[str, Any]] = []
    for target in history[:-1]:
        missing = [e for e in target.needs if e not in world]
        barriers = []
        for elem in sorted(missing):
            killer = killed_by(history, elem, current.n)
            if killer is not None:
                barriers.append((killer.n, elem))
        barriers.sort(reverse=True)
        cfg_now = dict(current.config)
        cfg_then = dict(target.config)
        cfg_diff = sorted(k for k in cfg_now if cfg_now[k] != cfg_then.get(k))
        rows.append({
            "rel": target,
            "reachable": not barriers,
            "barriers": barriers,
            "config_diff": cfg_diff,
        })
    return rows


def section_1() -> Tuple[int, int]:
    rule("1 · ROLLBACK REACHABILITY: WHICH RELEASES CAN YOU ACTUALLY GO BACK TO")
    current = HISTORY[-1]
    print("  current release: v%d (%s) — %s" % (current.n, current.build, current.summary))
    print("  a release is REACHABLE if every element its code touches still exists.")
    print()
    print("   rel  build   change                                        rollback?  why")
    for row in reachability(HISTORY):
        rel = row["rel"]
        verdict = "REACHABLE" if row["reachable"] else "BLOCKED  "
        if row["reachable"]:
            why = ("revert %d config key(s): %s" % (len(row["config_diff"]),
                   ",".join(row["config_diff"]))) if row["config_diff"] else "clean"
        else:
            why = "  +  ".join("v%d removed %s" % (bn, be) for bn, be in row["barriers"])
        print("   v%-3d %-7s %-45s %s  %s" % (rel.n, rel.build, rel.summary[:45], verdict, why))

    reach = [r for r in reachability(HISTORY) if r["reachable"]]
    print()
    print("  %d of %d prior releases are reachable by rollback. The other %d are not,"
          % (len(reach), len(HISTORY) - 1, len(HISTORY) - 1 - len(reach)))
    print("  and nothing in your deploy pipeline told you so.")
    print("  the two walls:")
    for rel in HISTORY:
        for elem in rel.drops:
            blocked = [r for r in reachability(HISTORY)
                       if any(b[1] == elem for b in r["barriers"])]
            print("    v%-2d removed %-22s -> blocks %d earlier release(s): %s"
                  % (rel.n, elem, len(blocked),
                     ",".join("v%d" % r["rel"].n for r in blocked)))
    print("  irreversible side effects still in the window (rollback does NOT undo these):")
    for rel in HISTORY:
        for eff in rel.irreversible:
            print("    v%-2d %s" % (rel.n, eff))

    # The mitigation: release 9's consumers accept BOTH payload versions.
    tolerant = tuple(
        Release(r.n, r.build, r.summary, r.needs, r.adds, (), r.config, r.irreversible)
        if r.n == 9 else r
        for r in HISTORY
    )
    reach2 = [r for r in reachability(tolerant) if r["reachable"]]
    print()
    print("  WHAT IF release 9's consumers had accepted v1 AND v2 (no drop)?")
    print("    reachable releases: %d -> %d  (%s)"
          % (len(reach), len(reach2), ",".join("v%d" % r["rel"].n for r in reach2)))
    print("    one line of consumer tolerance is worth %d releases of rollback range."
          % (len(reach2) - len(reach)))
    return len(reach), len(reach2)


# ----------------------------------------------------------------------------
# 2 · THREE ROLLBACKS, NOT ONE
# ----------------------------------------------------------------------------
# Release 42 changed the artifact, the config and the schema in one shot — and
# contracted in the same release it expanded, which is the root cause of all of
# the below. Each attempt below reverts a different subset and serves traffic.


@dataclass
class World:
    artifact: str
    config: Dict[str, str]
    columns: set
    rows: List[Dict[str, Any]] = field(default_factory=list)


def serve(world: World, n: int) -> Dict[str, Any]:
    """Serve n order-total requests against the current world. Returns outcomes."""
    errors, wrong_price, ok = 0, 0, 0
    charged = 0.0
    correct = 0.0
    for i in range(n):
        row = world.rows[i % len(world.rows)]
        want = "orders.total" if world.artifact == "v41" else "orders.total_cents"
        if want not in world.columns:
            errors += 1
            continue
        raw = row[want.split(".")[1]]
        # v41 reads whole currency units; v42 reads integer cents.
        if world.artifact == "v41":
            price = float(raw)
            # catalog-v2 hands back cents; v41 code does not know that.
            if world.config["PRICE_SOURCE"] == "catalog-v2":
                price = float(raw) * 100.0
                wrong_price += 1
            else:
                ok += 1
        else:
            price = float(raw) / 100.0
            ok += 1
        charged += price
        correct += float(row["total"])
    return {"errors": errors, "wrong_price": wrong_price, "ok": ok,
            "charged": charged, "correct": correct}


def section_2() -> Dict[str, Any]:
    rule("2 · A RELEASE HAS THREE ROLLBACKS: ARTIFACT, CONFIG, SCHEMA")
    n_req = 200
    base_rows = [{"id": i, "total": round(RNG.uniform(4.0, 240.0), 2)} for i in range(n_req)]
    for r in base_rows:
        r["total_cents"] = int(round(r["total"] * 100))

    print("  release 42 shipped THREE changes at once:")
    print("    artifact  v41 -> v42        (reads orders.total_cents)")
    print("    config    PRICE_SOURCE      catalog-v1 -> catalog-v2 (returns cents)")
    print("    schema    ADD orders.total_cents; DROP orders.total   (expand+contract, same release)")
    print("  v42 is bad. %d requests are served under each rollback attempt." % n_req)
    print()

    def fresh(artifact: str, price_source: str, columns: set) -> World:
        return World(artifact, {"PRICE_SOURCE": price_source}, set(columns),
                     [dict(r) for r in base_rows])

    post42 = {"orders.total_cents"}
    attempts = [
        ("A. artifact only        (v42->v41)", fresh("v41", "catalog-v2", post42)),
        ("B. artifact + config    (v42->v41)", fresh("v41", "catalog-v1", post42)),
        ("C. artifact + schema    (v42->v41)", fresh("v41", "catalog-v2", post42 | {"orders.total"})),
        ("D. artifact+config+schema, in order", fresh("v41", "catalog-v1", post42 | {"orders.total"})),
    ]
    print("  attempt                                 5xx   silent-wrong-price       charged     should be")
    results = {}
    for label, world in attempts:
        out = serve(world, n_req)
        results[label[0]] = out
        print("  %-36s   %3d   %10d       $%11.2f  $%10.2f"
              % (label, out["errors"], out["wrong_price"], out["charged"], out["correct"]))
    print()
    a, b, c, d = results["A"], results["B"], results["C"], results["D"]
    print("  A: rolling back the artifact alone -> %d/%d requests fail with" % (a["errors"], n_req))
    print("     'column orders.total does not exist'. The rollback made the outage total.")
    print("  B: reverting the config changed NOTHING (%d errors, identical)." % b["errors"])
    print("     Two of three rolled back and the outage is 100% unchanged: the schema")
    print("     stops every request at the first query, so the config never gets read.")
    print("  C: restore the column but forget the config and the errors go to %d —" % c["errors"])
    print("     dashboards green, and %d of %d orders overcharged 100x" % (c["wrong_price"], n_req))
    print("     ($%.2f charged against $%.2f owed, a $%.2f error nobody alerts on)."
          % (c["charged"], c["correct"], c["charged"] - c["correct"]))
    print("     This is WORSE than the outage. A 5xx stops. A wrong number persists.")
    print("  D: the correct coordinated sequence — errors %d, wrong prices %d." % (d["errors"], d["wrong_price"]))
    print()
    print("  the sequence D actually ran, and how long each step is:")
    t0 = time.perf_counter()
    restored = 0
    for r in base_rows:                      # re-expand: derive total from total_cents
        r["total"] = round(r["total_cents"] / 100.0, 2)
        restored += 1
    backfill_s = time.perf_counter() - t0
    per_row = backfill_s / max(restored, 1)
    print("    1. ADD COLUMN orders.total            schema, forward-only")
    print("    2. backfill from total_cents          %d rows in %.2f ms (%.2f us/row)"
          % (restored, backfill_s * 1e3, per_row * 1e6))
    print("       -> the real table is 18.2M rows: %dx this work, batched to respect"
          % (18_200_000 // restored))
    print("          lock and replication limits. Step 2 is O(rows) and cannot be skipped.")
    print("    3. revert config PRICE_SOURCE         seconds, but ONLY after step 2")
    print("    4. revert artifact v42 -> v41         seconds")
    print("    5. verify: %d/%d served, %d wrong prices" % (d["ok"], n_req, d["wrong_price"]))
    print("  note step 1: 'rolling back' a dropped column is a FORWARD migration.")
    print("  It only worked because total was derivable from total_cents. Drop a column")
    print("  whose data exists nowhere else and no sequence gets you back at all.")
    return {"A": a, "B": b, "C": c, "D": d, "per_row_us": per_row * 1e6,
            "backfill_18m": per_row * 18_200_000}


# ----------------------------------------------------------------------------
# 3 · THE BACKUP CHAIN AND ITS WEAKEST LINK
# ----------------------------------------------------------------------------


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()[:16]


@dataclass
class BackupPart:
    day: int
    kind: str                  # "full" | "incr"
    payload: bytes
    checksum: str
    corrupt: bool = False

    def verify(self) -> bool:
        return digest(self.payload) == self.checksum


def build_chain(days: int, full_days: Tuple[int, ...]) -> Tuple[List[BackupPart], Dict[int, Dict[str, int]]]:
    """Simulate `days` days of an orders table and back it up each night."""
    rng = random.Random(11)
    store: Dict[str, int] = {"order-%04d" % i: rng.randrange(500, 90_000) for i in range(1200)}
    parts: List[BackupPart] = []
    snapshots: Dict[int, Dict[str, int]] = {}
    next_id = 1200
    for day in range(days):
        if day > 0:
            delta: Dict[str, Optional[int]] = {}
            for _ in range(120):                      # new orders
                key = "order-%04d" % next_id
                next_id += 1
                store[key] = rng.randrange(500, 90_000)
                delta[key] = store[key]
            for key in rng.sample(sorted(store), 40):  # amended orders
                store[key] = rng.randrange(500, 90_000)
                delta[key] = store[key]
            body = json.dumps(delta, sort_keys=True).encode()
            kind = "incr"
            if day in full_days:
                body = json.dumps(store, sort_keys=True).encode()
                kind = "full"
        else:
            body = json.dumps(store, sort_keys=True).encode()
            kind = "full"
        parts.append(BackupPart(day, kind, body, digest(body)))
        snapshots[day] = dict(store)
    return parts, snapshots


def restore_chain(parts: List[BackupPart], start_day: int) -> Tuple[Dict[str, int], int, Optional[int]]:
    """Apply the full at start_day then every incremental after it. Stop at a bad link."""
    state: Dict[str, int] = {}
    applied = 0
    for part in parts:
        if part.day < start_day:
            continue
        if not part.verify():
            return state, applied, part.day
        chunk = json.loads(part.payload.decode())
        if part.kind == "full":
            state = dict(chunk)
        else:
            state.update(chunk)
        applied += 1
    return state, applied, None


def section_3() -> Dict[str, Any]:
    rule("3 · AN INCREMENTAL CHAIN IS ONLY AS GOOD AS ITS WEAKEST LINK")
    days = 12
    parts, snapshots = build_chain(days, full_days=())
    truth = snapshots[days - 1]
    print("  %d nights: 1 full (night 0) + %d incrementals. %d orders at the end."
          % (days, days - 1, len(truth)))
    print("  night 5's incremental gets one flipped byte on the object store.")
    bad = parts[5]
    bad.payload = bad.payload[:40] + bytes([bad.payload[40] ^ 0x20]) + bad.payload[41:]

    state, applied, broke_at = restore_chain(parts, 0)
    missing = [k for k in truth if k not in state]
    stale = [k for k in truth if k in state and state[k] != truth[k]]
    print()
    print("  restore, chain of %d, one full at night 0:" % days)
    print("    applied %d part(s), then night %d failed checksum verification" % (applied, broke_at))
    print("    recovered state = end of night %d" % (applied - 1))
    print("    orders MISSING entirely : %d" % len(missing))
    print("    orders STALE (wrong amt): %d" % len(stale))
    print("    data lost               : %s of writes (%d of %d orders unrecoverable)"
          % (hms((days - 1 - (applied - 1)) * 86400), len(missing), len(truth)))

    parts2, snapshots2 = build_chain(days, full_days=(7,))
    parts2[5].payload = parts2[5].payload[:40] + bytes([parts2[5].payload[40] ^ 0x20]) + parts2[5].payload[41:]
    truth2 = snapshots2[days - 1]
    state2, applied2, broke2 = restore_chain(parts2, 7)
    missing2 = [k for k in truth2 if k not in state2]
    stale2 = [k for k in truth2 if k in state2 and state2[k] != truth2[k]]
    print()
    print("  same corruption, same night, one change — a weekly full at night 7:")
    print("    restore path = full(night 7) + %d incrementals, checksum failures: %s"
          % (applied2 - 1, "none" if broke2 is None else "night %d" % broke2))
    print("    orders missing %d, stale %d — the bad link is no longer on the path."
          % (len(missing2), len(stale2)))

    # Chain length is a reliability multiplier, not a storage detail.
    print()
    print("  chain length is a reliability number. Per-part probability of an")
    print("  unreadable object p_fail = 0.20% (bit rot, truncated upload, expired key):")
    print("    links   P(whole chain restores)")
    for links in (4, 7, 11, 30, 90):
        p = 0.998 ** links
        print("    %5d   %6.2f%%%s" % (links, p * 100.0,
              "   <- nightly incrementals, quarterly full" if links == 90 else ""))
    return {"applied": applied, "broke_at": broke_at, "missing": len(missing),
            "stale": len(stale), "total": len(truth), "days_lost": days - 1 - (applied - 1),
            "missing2": len(missing2)}


# ----------------------------------------------------------------------------
# 4 · POINT-IN-TIME RECOVERY FROM A WRITE-AHEAD LOG
# ----------------------------------------------------------------------------


def section_4() -> Dict[str, Any]:
    rule("4 · POINT-IN-TIME RECOVERY: THE WAL IS THE RPO")
    rng = random.Random(23)
    backup_at = 2 * 3600.0                    # 02:00:00, the nightly base backup
    base: Dict[int, int] = {i: rng.randrange(100, 50_000) for i in range(6000)}
    next_id = 6000

    wal: List[Tuple[float, str, int, Optional[int], str]] = []   # (ts, op, id, amt, status)
    t = backup_at
    state = dict(base)
    status: Dict[int, str] = {k: ("pending" if rng.random() < 0.55 else "settled") for k in base}
    while t < 8 * 3600 + 58 * 60:
        t += rng.expovariate(1 / 5.0)
        roll = rng.random()
        if roll < 0.62:
            oid, amt = next_id, rng.randrange(100, 50_000)
            next_id += 1
            st = "pending" if rng.random() < 0.55 else "settled"
            wal.append((t, "INSERT", oid, amt, st))
            state[oid], status[oid] = amt, st
        elif roll < 0.93:
            oid = rng.choice(list(state))
            amt = rng.randrange(100, 50_000)
            wal.append((t, "UPDATE", oid, amt, status[oid]))
            state[oid] = amt
        else:
            oid = rng.choice(list(state))
            wal.append((t, "DELETE", oid, None, status[oid]))
            del state[oid]
            del status[oid]

    rows_before = len(state)
    t_disaster = t + rng.expovariate(1 / 5.0)
    doomed = [k for k, v in status.items() if v == "pending"]
    wal.append((t_disaster, "DELETE-WHERE", -1, None, "pending"))

    print("  base backup taken at %s.  %s later, at %s, someone runs"
          % (clock(backup_at), hms(t_disaster - backup_at), clock(t_disaster)))
    print("    DELETE FROM orders WHERE status = 'pending';     -- no tenant filter")
    print("  %d rows before, %d after. %d orders gone in one statement."
          % (rows_before, rows_before - len(doomed), len(doomed)))
    print()
    print("  WAL: %d records between the base backup and the statement," % (len(wal) - 1))
    print("       mean inter-record gap %.2f s, longest gap %.2f s"
          % (statistics.fmean(wal[i][0] - wal[i - 1][0] for i in range(1, len(wal) - 1)),
             max(wal[i][0] - wal[i - 1][0] for i in range(1, len(wal) - 1))))
    print()

    target = t_disaster - 1.0
    t0 = time.perf_counter()
    recovered = dict(base)
    replayed = 0
    reached = backup_at
    for ts, op, oid, amt, _st in wal:
        if ts > target:
            break
        replayed += 1
        reached = ts
        if op in ("INSERT", "UPDATE"):
            recovered[oid] = amt
        elif op == "DELETE":
            recovered.pop(oid, None)
    replay_s = time.perf_counter() - t0

    achieved = target - reached
    loss_window = t_disaster - reached
    backup_only = t_disaster - backup_at
    print("  recovery target: %s  (1.000 s before the statement)" % clock(target))
    print("  last replayable WAL record at %s -> replayed %d records in %.0f ms"
          % (clock(reached), replayed, replay_s * 1e3))
    print()
    print("    restored rows                        : %d" % len(recovered))
    print("    rows in the base backup alone        : %d" % len(base))
    print("    rows the disaster left behind        : %d" % (rows_before - len(doomed)))
    print()
    print("    ACHIEVED RPO vs the target instant   : %.3f s   (WAL record granularity)" % achieved)
    print("    data-loss window vs the statement    : %.3f s" % loss_window)
    print("    RPO from the backup interval ALONE   : %s  (%.0f s)" % (hms(backup_only), backup_only))
    print("    PITR improvement                     : %.0fx" % (backup_only / max(loss_window, 1e-9)))
    print()
    print("  restoring the base backup and stopping there would have thrown away")
    print("  %d orders written after 02:00. PITR gives them all back except the"
          % (len(recovered) - len(base)))
    print("  %.3f s of writes between the last replayed record and the target." % achieved)
    print("  your RPO is not your backup schedule. It is your WAL shipping interval.")
    return {"achieved_rpo": achieved, "loss_window": loss_window, "backup_only": backup_only,
            "ratio": backup_only / max(loss_window, 1e-9), "replayed": replayed,
            "restored": len(recovered), "base": len(base), "doomed": len(doomed),
            "rows_before": rows_before, "wal_len": len(wal) - 1}


# ----------------------------------------------------------------------------
# 5 · RTO, MEASURED RATHER THAN ASSERTED
# ----------------------------------------------------------------------------


def make_dump(path: str, n: int) -> int:
    rng = random.Random(97)
    with open(path, "w", encoding="utf-8") as fh:
        for i in range(n):
            fh.write(json.dumps({
                "id": i,
                "customer": "cust-%07d" % rng.randrange(1_000_000),
                "amount_cents": rng.randrange(100, 500_000),
                "currency": "EUR",
                "status": rng.choice(("pending", "settled", "refunded")),
                "created_at": "2026-07-%02dT%02d:%02d:%02dZ" % (
                    rng.randrange(1, 29), rng.randrange(24), rng.randrange(60), rng.randrange(60)),
            }, separators=(",", ":")))
            fh.write("\n")
    return os.path.getsize(path)


def restore_dump(path: str) -> Tuple[int, str]:
    """Read, parse, load into a keyed table and build a secondary index — the
    same three costs pg_restore pays: I/O, parse, index build."""
    table: Dict[int, Dict[str, Any]] = {}
    by_customer: Dict[str, List[int]] = {}
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for raw in fh:
            h.update(raw)
            row = json.loads(raw)
            table[row["id"]] = row
            by_customer.setdefault(row["customer"], []).append(row["id"])
    return len(table), h.hexdigest()[:16]


REPEATS = 5


def section_5() -> Dict[str, Any]:
    rule("5 · RTO IS A MEASUREMENT, NOT A TARGET")
    tmp = tempfile.mkdtemp(prefix="l14-restore-")
    sizes = (5_000, 20_000, 80_000, 320_000)
    print("  restoring a logical dump: read + parse + load + build one index.")
    print("  each size restored %d times; we report the MEDIAN, because a benchmark" % REPEATS)
    print("  run once is an anecdote and an RTO built on an anecdote is a wish.")
    print("     rows        bytes    dump s   restore s    MB/s   rows/s")
    points: List[Tuple[float, float]] = []
    spread: List[float] = []
    try:
        for n in sizes:
            path = os.path.join(tmp, "dump-%d.jsonl" % n)
            t0 = time.perf_counter()
            nbytes = make_dump(path, n)
            dump_s = time.perf_counter() - t0
            runs: List[float] = []
            for _ in range(REPEATS):
                t0 = time.perf_counter()
                rows, _ = restore_dump(path)
                runs.append(time.perf_counter() - t0)
            restore_s = statistics.median(runs)
            mbps = (nbytes / 1e6) / restore_s
            print("  %9d %12d  %7.2f    %8.2f  %6.1f  %7.0f"
                  % (rows, nbytes, dump_s, restore_s, mbps, rows / restore_s))
            points.append((nbytes / 1e6, restore_s))
            if n == sizes[-1]:
                spread = sorted((nbytes / 1e6) / r for r in runs)
            os.remove(path)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    mb, secs = points[-1]
    throughput = mb / secs
    print()
    print("  throughput is NOT a constant: %.1f MB/s at %.1f MB, %.1f MB/s at %.1f MB."
          % (points[0][0] / points[0][1], points[0][0],
             points[-1][0] / points[-1][1], points[-1][0]))
    print("  it DEGRADES as the dataset grows — the small dumps fit in page cache and")
    print("  your production restore will not. Across the whole range bytes x%.1f cost"
          % (points[-1][0] / points[0][0]))
    print("  time x%.1f (super-linear, all of it cache); between the two LARGEST samples"
          % (points[-1][1] / points[0][1]))
    print("  bytes x%.1f cost time x%.1f, close enough to linear to extrapolate from."
          % (points[-1][0] / points[-2][0], points[-1][1] / points[-2][1]))
    print("  So use the largest sample's %.1f MB/s and treat it as OPTIMISTIC, not as"
          % throughput)
    print("  a best estimate: benchmarking on the SMALLEST dump would have over-read")
    print("  your real throughput by %.1fx." % ((points[0][0] / points[0][1]) / throughput))
    print("  the same restore, %d times, ranged %.1f - %.1f MB/s on an idle sandbox."
          % (REPEATS, spread[0], spread[-1]))
    print("  your RTO is a distribution, not a scalar. Plan against the slow end.")
    print()
    for prod_gb, target_h in ((80, 4.0), (500, 4.0), (2000, 4.0)):
        est_s = (prod_gb * 1000.0) / throughput
        slow_s = (prod_gb * 1000.0) / spread[0]
        verdict = "MEETS" if est_s <= target_h * 3600 else "MISSES by %.1fx" % (est_s / (target_h * 3600))
        print("  EXTRAPOLATION: %5d GB at %.1f MB/s -> %-12s (slow end %-12s) vs a %.0fh RTO: %s"
              % (prod_gb, throughput, hms(est_s), hms(slow_s), target_h, verdict))
    print()
    print("  read that as an extrapolation and nothing more. It is also OPTIMISTIC:")
    print("  it assumes one stream on a warm local file, no network transfer, no")
    print("  constraint or foreign-key validation, no vacuum, no replica rebuild,")
    print("  and an engineer who types the right command first time at 03:00.")
    print("  An RTO you have not timed is a wish. Time it, then write it down.")
    return {"throughput": throughput, "points": points,
            "slow": spread[0], "fast": spread[-1]}


# ----------------------------------------------------------------------------
# 6 · THE BACKUP THAT WAS NEVER RESTORED
# ----------------------------------------------------------------------------

LIVE_SCHEMA = {
    "users": 4_800,
    "orders": 12_000,
    "payments": 9_120,     # added by a migration 31 nights ago
    "sessions": 31_400,
    "audit_log": 58_000,
}
# The backup job's table list. It is a static list in a config file.
BACKUP_INCLUDES = ("users", "orders", "sessions", "audit_log")


def run_backup_job(night: int) -> Dict[str, Any]:
    rng = random.Random(400 + night)
    tables = {}
    for name in BACKUP_INCLUDES:
        growth = 1.0 + 0.004 * night + rng.uniform(-0.001, 0.001)
        tables[name] = int(LIVE_SCHEMA[name] * growth)
    payload = json.dumps(tables, sort_keys=True).encode()
    return {"exit_code": 0, "tables": tables,
            "bytes": sum(v for v in tables.values()) * 148,
            "checksum": digest(payload)}


def verify_restore(job: Dict[str, Any], live: Dict[str, int]) -> List[str]:
    """Restore into a scratch namespace and assert on schema and row counts."""
    faults: List[str] = []
    restored = job["tables"]
    for name, expected in sorted(live.items()):
        if name not in restored:
            faults.append("MISSING TABLE   %-10s expected %d rows, restored none"
                          % (name, expected))
            continue
        got = restored[name]
        drift = abs(got - expected) / max(expected, 1)
        if drift > 0.25:
            faults.append("ROW-COUNT DRIFT %-10s expected ~%d, restored %d (%.0f%%)"
                          % (name, expected, got, drift * 100))
    return faults


def section_6() -> Dict[str, Any]:
    rule("6 · A BACKUP YOU HAVE NOT RESTORED IS NOT A BACKUP")
    print("  the live schema has %d tables. The backup job's include-list has %d:"
          % (len(LIVE_SCHEMA), len(BACKUP_INCLUDES)))
    print("    live    : %s" % ", ".join(sorted(LIVE_SCHEMA)))
    print("    included: %s" % ", ".join(sorted(BACKUP_INCLUDES)))
    print("  'payments' was created by a migration 31 nights ago. Nobody edited the list.")
    print()
    print("  what the monitoring saw — the last 5 of 31 nights:")
    print("    night   exit   tables   bytes      verdict")
    for night in range(27, 32):
        job = run_backup_job(night)
        print("    %5d   %4d   %6d   %8d   %s"
              % (night, job["exit_code"], len(job["tables"]), job["bytes"],
                 "OK (green)" if job["exit_code"] == 0 else "FAIL"))
    print("  31 consecutive green nights. Backup size grows ~0.4%/night, so a")
    print("  size-anomaly alert would not have fired either. Exit code 0 every time.")

    job = run_backup_job(31)
    print()
    print("  now the restore, at 04:12 during the incident:")
    for name in sorted(LIVE_SCHEMA):
        got = job["tables"].get(name)
        if got is None:
            print("    %-10s  -> ABSENT. %d rows unrecoverable." % (name, LIVE_SCHEMA[name]))
        else:
            print("    %-10s  -> %d rows restored" % (name, got))
    lost = sum(v for k, v in LIVE_SCHEMA.items() if k not in job["tables"])
    print("  %d payment rows are gone, and every restored order row now references" % lost)
    print("  a payment that does not exist. The backup succeeded 31 times.")

    print()
    print("  the same job with automated restore verification bolted on:")
    faults = verify_restore(job, LIVE_SCHEMA)
    print("    restore into scratch namespace ... done")
    print("    assert table set matches live catalog ... %d fault(s)" % len(faults))
    for f in faults:
        print("      %s" % f)
    print("    VERIFY EXIT CODE: %d  ->  page the owning team" % (1 if faults else 0))
    print("  it fires on the FIRST run, 31 nights before anyone needed the backup.")
    print("  the check is four lines: restore, list tables, diff against the live")
    print("  catalog, compare row counts. Nothing about it requires a vendor.")
    return {"lost": lost, "faults": len(faults), "nights": 31}


def main() -> None:
    t0 = time.perf_counter()
    reach_before, reach_after = section_1()
    s2 = section_2()
    s3 = section_3()
    s4 = section_4()
    s5 = section_5()
    s6 = section_6()

    rule("SUMMARY")
    print("  reachable rollback targets, 9 releases of history : %d (%d with a tolerant consumer)"
          % (reach_before, reach_after))
    print("  rollback attempts that left the system correct    : 1 of 4")
    print("  incremental chain: orders lost to one bad link    : %d of %d (%s of writes)"
          % (s3["missing"], s3["total"], hms(s3["days_lost"] * 86400)))
    print("  PITR achieved RPO vs backup-interval-only RPO     : %.3f s vs %s (%.0fx)"
          % (s4["loss_window"], hms(s4["backup_only"]), s4["ratio"]))
    print("  measured restore throughput (median of %d)         : %.1f MB/s (%.1f-%.1f)"
          % (REPEATS, s5["throughput"], s5["slow"], s5["fast"]))
    print("  2 TB restore against a 4-hour RTO                 : %s  (%.1fx over)"
          % (hms((2000 * 1000.0) / s5["throughput"]),
             ((2000 * 1000.0) / s5["throughput"]) / (4 * 3600)))
    print("  green backup nights before verification found it  : %d" % s6["nights"])
    print("\n  (total wall time %.1f s)" % (time.perf_counter() - t0))


if __name__ == "__main__":
    main()
