#!/usr/bin/env python3
"""Ship one service end to end, and measure every guard on the way.

Lesson: phases/10-infrastructure-and-deployment/15-capstone-ship-a-service/docs/en.md
Commit -> image -> registry -> declared infrastructure -> orchestrated fleet ->
routed traffic -> a risky change landed three ways -> an incident -> recovery.
Sources: OCI Image Format Specification v1.1 (manifest, descriptor, rootfs.diff_ids);
OCI Distribution Specification v1.1 (blob/manifest resolution); RFC 2104 (HMAC);
NIST FIPS 180-4 (SHA-256); PostgreSQL 16 manual 13.3 (Explicit Locking);
Kubernetes API reference (Deployment strategy, probes, progressDeadlineSeconds);
Humble & Farley, Continuous Delivery (2010); Google SRE Workbook ch. 5 & 16.

Standard library only. Seeded with random.Random(7). Self-terminating.
Time is SIMULATED in whole seconds; every "s" in the output is simulated time.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

SEED = 7
RNG = random.Random(SEED)

SIGNING_KEY = b"org.checkout.build-signer.v3"

# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def sha(*parts: object) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode())
        h.update(b"\x1f")
    return h.hexdigest()


def short(digest: str, n: int = 12) -> str:
    return digest.split(":")[-1][:n]


def bucket(salt: str, uid: str) -> int:
    """Sticky bucketing in basis points: 10,000 slots, 0.01% granularity."""
    d = hashlib.sha256(("%s:%s" % (salt, uid)).encode()).digest()
    return int.from_bytes(d[:8], "big") % 10_000


def head(n: int, title: str) -> None:
    print("\n== %d · %s ==" % (n, title))


GUARDS: List[Tuple[str, str, str, str, str]] = []  # stage, lesson, guard, fired, saved


def guard(stage: str, lesson: str, name: str, fired: str, saved: str) -> None:
    GUARDS.append((stage, lesson, name, fired, saved))


# ---------------------------------------------------------------------------
# 1 - BUILD & PIN
# ---------------------------------------------------------------------------

SOURCE: Dict[str, str] = {
    "Containerfile": "FROM base:1 / deps / app",
    "requirements.lock": "flask==3.1.4\npsycopg==3.2.1\nquotesdk==0.4.0\n",
    "app/__init__.py": "__version__ = '4.2.0'\n",
    "app/checkout.py": "def quote(order): return order.shipping_fee\n",
    "app/orders.py": "SELECT id, user_id, zone, shipping_fee FROM orders\n",
    "app/health.py": "def ready(): return db.ok() and config.ok()\n",
    "tests/test_quote.py": "assert quote(o) >= 0\n",
}

# (layer name, the files this layer's cache key depends on, modelled seconds)
GOOD_ORDER = [
    ("base image", [], 0.0),
    ("system packages", ["Containerfile"], 74.0),
    ("copy requirements.lock", ["requirements.lock"], 0.4),
    ("pip install -r requirements.lock", ["requirements.lock"], 393.0),
    ("copy app/", ["app/__init__.py", "app/checkout.py", "app/orders.py", "app/health.py"], 0.6),
    ("copy tests/", ["tests/test_quote.py"], 0.2),
]
BAD_ORDER = [
    ("base image", [], 0.0),
    ("system packages", ["Containerfile"], 74.0),
    ("copy . .", sorted(SOURCE), 1.2),
    ("pip install -r requirements.lock", ["requirements.lock"], 393.0),
]


def build(order, src: Dict[str, str], cache: Dict[str, str]) -> Tuple[str, List[str], float, int]:
    """Merkle-chained layer cache: a miss invalidates every layer below it."""
    chain = "sha256:root"
    rebuilt: List[str] = []
    seconds = 0.0
    for name, inputs, cost in order:
        key = sha(chain, name, *[src[f] for f in inputs])
        if key in cache:
            chain = cache[key]
            continue
        chain = sha(chain, key)
        cache[key] = chain
        rebuilt.append(name)
        seconds += cost
    return "sha256:" + chain, rebuilt, seconds, len(order)


def naive_manifest(src: Dict[str, str], clock: int, order: Sequence[str]) -> str:
    """As people write it: wall-clock mtimes, readdir() entry order."""
    body = "|".join("%s@%d=%s" % (p, clock + i, src[p]) for i, p in enumerate(order))
    return "sha256:" + sha(body)


def normalised_manifest(src: Dict[str, str], clock: int, order: Sequence[str]) -> str:
    """SOURCE_DATE_EPOCH for every mtime, entries sorted, versions pinned."""
    body = "|".join("%s@0=%s" % (p, src[p]) for p in sorted(order))
    return "sha256:" + sha(body)


def act_build_and_pin() -> Tuple[str, str, Dict[str, str]]:
    head(1, "BUILD & PIN  (lessons 3, 4, 5, 10)")

    cache: Dict[str, str] = {}
    d1, r1, s1, n1 = build(GOOD_ORDER, SOURCE, cache)
    print("  cold build, dependency-ordered:   %d/%d layers built, %6.1f s" % (len(r1), n1, s1))

    edited = dict(SOURCE)
    edited["app/checkout.py"] = "def quote(order): return order.shipping_fee + 0\n"
    d2, r2, s2, _ = build(GOOD_ORDER, edited, cache)
    print("  one-line edit to app/checkout.py: %d/%d layers built, %6.1f s"
          % (len(r2), n1, s2))

    bad_cache: Dict[str, str] = {}
    build(BAD_ORDER, SOURCE, bad_cache)
    _, r3, s3, n3 = build(BAD_ORDER, edited, bad_cache)
    print("  the same edit, COPY . . on top:   %d/%d layers built, %6.1f s"
          % (len(r3), n3, s3))
    print("  layer ordering alone: %.1f s vs %.1f s for the identical change (%.0fx)"
          % (s2, s3, s3 / max(s2, 0.001)))
    guard("build", "L3", "dependency-ordered layers",
          "yes", "%.0fx faster rebuild (%.1f s vs %.1f s)" % (s3 / max(s2, 0.001), s2, s3))

    order_a = list(SOURCE)
    order_b = list(SOURCE)
    RNG.shuffle(order_b)
    na, nb = naive_manifest(SOURCE, 1_760_000_000, order_a), naive_manifest(SOURCE, 1_760_000_311, order_b)
    xa, xb = normalised_manifest(SOURCE, 1_760_000_000, order_a), normalised_manifest(SOURCE, 1_760_000_311, order_b)
    print("  determinism, same source built twice on two machines:")
    print("    as people write it   %s  %s  identical=%s" % (short(na), short(nb), na == nb))
    print("    normalised           %s  %s  identical=%s" % (short(xa), short(xb), xa == xb))
    guard("build", "L3", "reproducible build: fixed mtime + sorted entries",
          "yes", "two machines agreed on one digest instead of two")

    digest = xa
    sig = hmac.new(SIGNING_KEY, digest.encode(), hashlib.sha256).hexdigest()
    provenance = {
        "buildType": "https://internal/build/v1",
        "builder": "ci-runner-prod",
        "sourceRepo": "git@internal:checkout",
        "sourceCommit": "9f31c0a7b4de",
        "materials": len(SOURCE),
        "subject": digest,
    }
    ok = hmac.compare_digest(
        sig, hmac.new(SIGNING_KEY, digest.encode(), hashlib.sha256).hexdigest())
    print("  artifact digest      %s" % digest)
    print("  signature            %s...  verifies=%s" % (short(sig, 16), ok))
    print("  provenance           builder=%s commit=%s materials=%d"
          % (provenance["builder"], provenance["sourceCommit"], provenance["materials"]))

    candidates = [
        ("checkout:latest", False, True, True),
        ("checkout:4.2.0", False, True, True),
        ("checkout@%s (key rotated)" % short(digest, 8), True, False, True),
        ("checkout@%s (laptop)" % short(digest, 8), True, True, False),
        ("checkout@%s" % short(digest, 8), True, True, True),
    ]
    admitted = 0
    print("  admission control at the cluster door:")
    for ref, pinned, signed, provenanced in candidates:
        reasons = []
        if not pinned:
            reasons.append("not pinned by digest")
        if not signed:
            reasons.append("no valid signature")
        if not provenanced:
            reasons.append("no provenance from a trusted builder")
        admitted += 1 if not reasons else 0
        print("    %-6s %-32s %s" % ("ADMIT" if not reasons else "DENY", ref,
                                     "; ".join(reasons)))
    print("  %d of %d candidate references admitted" % (admitted, len(candidates)))
    guard("registry", "L4", "admission: pinned + signed + provenance",
          "yes", "rejected %d of %d references, including 2 mutable tags"
          % (len(candidates) - admitted, len(candidates)))

    configs = {
        "staging": {"QUOTE_API_URL": "https://sandbox.partner", "LOG_LEVEL": "debug", "POOL": "8"},
        "production": {"QUOTE_API_URL": "https://api.partner", "LOG_LEVEL": "info", "POOL": "8"},
        "production+1": {"QUOTE_API_URL": "https://api.partner", "LOG_LEVEL": "info", "POOL": "24"},
    }
    releases: Dict[str, str] = {}
    print("  release = build + config   (one artifact, three releases)")
    for env, cfg in configs.items():
        chash = sha(json.dumps(cfg, sort_keys=True))
        rel = "rel-" + short(sha(digest, chash))
        releases[env] = rel
        print("    %-13s config %s  ->  %s" % (env, short(chash, 10), rel))
    print("  the last two share ONE artifact digest and differ by one key (POOL 8 -> 24).")
    print("  'we did not deploy anything' is false: that is a new release id.")
    guard("pipeline", "L10", "build once, promote the same digest",
          "yes", "%d releases across 3 environments from 1 tested artifact" % len(releases))
    return digest, releases["production"], releases


# ---------------------------------------------------------------------------
# 2 - DECLARE & CONVERGE
# ---------------------------------------------------------------------------

FLEET_SIZE = 6
STARTUP_S = 23  # image pull 9 + process start 3 + readiness 5 + 3 x 2s probes


@dataclass
class Instance:
    name: str
    release: str
    state: str = "pending"      # pending | starting | ready | draining | gone
    ready_at: int = 0
    routable: bool = False      # the ROUTER's belief, not the truth
    build: str = "v1"


DEPENDS_ON = {"service.checkout": "database.orders", "dns.public": "service.checkout"}


def plan(desired: Dict[str, dict], recorded: Dict[str, dict],
         immutable: Dict[str, set]) -> List[Tuple[str, str, str]]:
    """Plan to a fixpoint: a replace makes the resource's id (known after apply),
    which is a CHANGED value for every dependent that references it."""
    verbs: Dict[str, Tuple[str, str]] = {}
    for name, want in desired.items():
        have = recorded.get(name)
        if have is None:
            verbs[name] = ("create", "")
            continue
        diffs = {k for k in want if want[k] != have.get(k)}
        if not diffs:
            continue
        forced = diffs & immutable.get(want["type"], set())
        verbs[name] = (("replace", "forced by " + ",".join(sorted(forced))) if forced
                       else ("update", ",".join(sorted(diffs))))
    for _ in range(8):                     # cascade to a fixpoint
        grew = False
        for child, parent in DEPENDS_ON.items():
            if child in desired and verbs.get(parent, ("", ""))[0] == "replace":
                if verbs.get(child, ("", ""))[0] != "replace":
                    verbs[child] = ("replace", "%s.id is (known after apply)" % parent)
                    grew = True
        if not grew:
            break
    for name in recorded:
        if name not in desired:
            verbs[name] = ("destroy", "")
    return [(v, n, why) for n, (v, why) in sorted(verbs.items())]


def act_declare_and_converge(release: str) -> List[Instance]:
    head(2, "DECLARE & CONVERGE  (lessons 6, 7)")

    immutable = {"network": {"cidr"}, "database": {"engine", "zone"},
                 "service": set(), "dns": {"name"}}
    recorded = {
        "network.core": {"type": "network", "cidr": "10.0.0.0/16"},
        "database.orders": {"type": "database", "engine": "postgres16", "zone": "eu-1a", "size": 100},
        "service.checkout": {"type": "service", "replicas": 4, "release": release},
        "dns.public": {"type": "dns", "name": "checkout.example"},
    }
    desired = {
        "network.core": {"type": "network", "cidr": "10.0.0.0/16"},
        "database.orders": {"type": "database", "engine": "postgres17", "zone": "eu-1a", "size": 100},
        "service.checkout": {"type": "service", "replicas": FLEET_SIZE, "release": release},
        "dns.public": {"type": "dns", "name": "checkout.example"},
    }
    print("  plan (as submitted):")
    changes = plan(desired, recorded, immutable)
    for verb, name, why in changes:
        print("    %-8s %-20s %s" % (verb, name, why))
    protected = {"database.orders"}
    blocked = [c for c in changes if c[0] in ("replace", "destroy") and c[1] in protected]
    print("  Plan: %d to add, %d to change, %d to destroy"
          % (sum(1 for c in changes if c[0] in ("create", "replace")),
             sum(1 for c in changes if c[0] == "update"),
             sum(1 for c in changes if c[0] in ("destroy", "replace"))))
    if blocked:
        print("  APPLY REFUSED: prevent_destroy on %s" % ", ".join(c[1] for c in blocked))
        print("    one edited attribute — a minor-version bump — was IMMUTABLE, so the")
        print("    verb is 'replace', not 'update': the 100 GB production database is")
        print("    destroyed and recreated empty. Its new id is (known after apply),")
        print("    which is a CHANGED value for everything downstream, so %d of %d"
              % (sum(1 for c in changes if c[0] == "replace"), len(desired)))
        print("    resources are replaced by one line nobody thought was risky.")
    guard("infrastructure", "L6", "prevent_destroy on stateful resources",
          "yes", "blocked a replace of the 100 GB orders database")

    desired["database.orders"]["engine"] = "postgres16"
    changes = plan(desired, recorded, immutable)
    print("  plan (corrected): %s" % ", ".join("%s %s" % (v, n) for v, n, _ in changes))

    fleet: List[Instance] = []
    tick = 0
    last = None
    print("  control loop, level-triggered, reconciling to %d ready:" % FLEET_SIZE)
    while tick <= 90:
        ready = sum(1 for i in fleet if i.state == "ready")
        starting = sum(1 for i in fleet if i.state == "starting")
        row = (len(fleet), ready)
        if row != last:
            print("    t=%3ds  desired=%d  running=%d  ready=%d  pending=%d"
                  % (tick, FLEET_SIZE, len(fleet), ready, FLEET_SIZE - len(fleet)))
            last = row
        if ready == FLEET_SIZE:
            break
        deficit = FLEET_SIZE - ready - starting
        for k in range(max(0, min(deficit, 1 if not fleet else 2 * len(fleet)))):
            fleet.append(Instance("checkout-%d" % (len(fleet) + 1), release,
                                  "starting", tick + STARTUP_S))
        for i in fleet:
            if i.state == "starting" and tick >= i.ready_at:
                i.state, i.routable = "ready", True
        tick += 1
    print("    CONVERGED at t=%ds. Slow start doubles the batch: 1, 2, 4 — the same" % tick)
    print("    rate limit that stops a bad spec from creating six thousand instances.")

    fleet.append(Instance("checkout-manual", release, "ready", 0, True))
    print("  drift: someone scaled to %d by hand at 02:40." % len(fleet))
    drift_ticks = 0
    while len(fleet) > FLEET_SIZE:
        fleet.pop()
        drift_ticks += 1
    print("    level-triggered loop re-derived the diff from STATE, not from an event,")
    print("    and removed the extra instance in %d tick. An edge-triggered loop that" % drift_ticks)
    print("    missed the create event would never have known the instance existed.")
    guard("orchestration", "L7", "level-triggered reconciliation",
          "yes", "reverted out-of-band drift in %d tick with no event delivered" % drift_ticks)
    return fleet


# ---------------------------------------------------------------------------
# 3 - ROUTE
# ---------------------------------------------------------------------------

CLIENTS = 120
CLIENT_RPS = 2          # requests per client per simulated second
DRAIN_WAIT_S = 5        # sized from the server's in-flight requests (400 ms)


RECONNECT_BACKOFF = 2       # seconds a client waits before re-dialling


def rolling_replace(max_conn_lifetime: Optional[int], close_on_drain: bool,
                    drain_wait: int) -> Tuple[int, int]:
    """Roll all 6 instances (surge first, then drain) while 120 pooled clients send.

    Returns (failed requests, connections severed by an instance exiting).
    """
    old = ["old-%d" % (i + 1) for i in range(FLEET_SIZE)]
    routable, alive = set(old), set(old)
    conn = {c: old[c % FLEET_SIZE] for c in range(CLIENTS)}
    conn_age = {c: 0 for c in range(CLIENTS)}
    retry_at: Dict[int, int] = {}
    failed = severed = 0

    events: Dict[int, List[Tuple[str, str]]] = {}
    t, made = 0, 0
    for b in range(0, FLEET_SIZE, 2):
        for _ in range(2):                                   # maxSurge: new ones first
            made += 1
            events.setdefault(t + STARTUP_S, []).append(("up", "new-%d" % made))
        for k in range(2):
            events.setdefault(t + STARTUP_S, []).append(("dereg", old[b + k]))
            events.setdefault(t + STARTUP_S + drain_wait, []).append(("exit", old[b + k]))
        t += STARTUP_S + drain_wait

    def repin(c: int, now: int) -> None:
        pool = sorted(routable)
        conn[c] = pool[(c + now) % len(pool)]
        conn_age[c] = now

    for now in range(t + 10):
        for kind, name in events.get(now, []):
            if kind == "up":
                alive.add(name)
                routable.add(name)
            elif kind == "dereg":
                routable.discard(name)
                if close_on_drain:                            # server sends Connection: close
                    for c in range(CLIENTS):
                        if conn[c] == name:
                            repin(c, now)
            else:
                alive.discard(name)
                severed += sum(1 for c in range(CLIENTS) if conn[c] == name)
        for c in range(CLIENTS):
            if conn[c] in alive and max_conn_lifetime is not None \
                    and now - conn_age[c] >= max_conn_lifetime:
                repin(c, now)
            if conn[c] not in alive:
                if c not in retry_at:
                    retry_at[c] = now + RECONNECT_BACKOFF
                elif now >= retry_at[c]:
                    repin(c, now)
                    del retry_at[c]
            failed += 0 if conn[c] in alive else CLIENT_RPS
    return failed, severed


def act_route() -> None:
    head(3, "ROUTE  (lessons 8, 9)")
    print("  %d pooled clients x %d req/s = %d req/s through the router, %d instances."
          % (CLIENTS, CLIENT_RPS, CLIENTS * CLIENT_RPS, FLEET_SIZE))
    print("  every instance is replaced once. Drain wait is %ds — sized, correctly," % DRAIN_WAIT_S)
    print("  from the 400 ms the server needs to finish its in-flight requests.\n")
    rows = [
        ("no max connection lifetime", None, False, DRAIN_WAIT_S),
        ("max lifetime 30s  (> drain)", 30, False, DRAIN_WAIT_S),
        ("max lifetime  3s  (< drain)", 3, False, DRAIN_WAIT_S),
        ("Connection: close at drain", None, True, DRAIN_WAIT_S),
    ]
    print("  client pool setting            drain  failed  severed")
    results = {}
    for label, life, closing, wait in rows:
        f, s = rolling_replace(life, closing, wait)
        results[label] = f
        print("  %-30s %4ds  %6d  %7d" % (label, wait, f, s))
    base = results["no max connection lifetime"]
    bounded = results["max lifetime 30s  (> drain)"]
    fixed = results["max lifetime  3s  (< drain)"]
    print("\n  bounding the connection lifetime at 30s changed nothing: %d -> %d." % (base, bounded))
    print("  the bound has to be SHORTER than the drain window to matter: %d at 3s." % fixed)
    print("  the drain window is a property of the CLIENT's pool, not of your server's")
    print("  in-flight count. Two numbers in two different teams' config, never compared.")
    guard("routing", "L8/L9", "drain window vs client connection lifetime",
          "no", "would have saved %d severed requests per full rollout" % base)


# ---------------------------------------------------------------------------
# 4 - LAND A RISKY CHANGE
# ---------------------------------------------------------------------------

TRAFFIC = 250                # req/s
USERS = 40_000
LEGACY_ZONE_BP = 340         # 3.40% of users are in the legacy shipping zone
FLAG = "quote_engine_v2"
CANARY_MIN_NEW_PATH = 300    # samples of the NEW PATH required before promoting
CANARY_STEP_SOAK = 60        # seconds per exposure step


def zone_of(uid: str) -> str:
    return "legacy-north" if bucket("zone", uid) < LEGACY_ZONE_BP else "std"


@dataclass
class World:
    columns: set = field(default_factory=lambda: {"id", "user_id", "zone", "shipping_fee"})
    exposure_bp: int = 0
    errors: int = 0
    mispriced: int = 0
    bad_reads: int = 0
    served: int = 0


def serve(w: World, build: str, uid: str, kind: str = "write") -> str:
    """One request. Returns 'ok' | 'error' | 'mispriced' | 'bad_read'.

    A missing column is an exception on the WRITE path and a silent default on
    the READ path, because the read is SELECT * followed by row['name'].
    """
    w.served += 1
    if build == "v1":
        if "shipping_fee" not in w.columns:
            return "error" if kind == "write" else "bad_read"
        return "ok"
    if build == "v3":                           # new-only code
        if "shipping_cents" not in w.columns:
            return "error" if kind == "write" else "bad_read"
        return "ok"
    # v2: dual-write, read path chosen by the flag
    if "shipping_fee" not in w.columns or "shipping_cents" not in w.columns:
        return "error" if kind == "write" else "bad_read"
    on = bucket(FLAG, uid) < w.exposure_bp
    if on:
        if zone_of(uid) == "legacy-north":
            return "mispriced"                  # silent: wrong quote, HTTP 200
        return "ok"
    return "ok"


def users(n: int, rng: random.Random) -> List[str]:
    return ["u%06d" % rng.randrange(USERS) for _ in range(n)]


def run_correct(digest: str) -> dict:
    rng = random.Random(SEED + 1)
    w = World()
    t = 0
    log = []

    w.columns.add("shipping_cents")
    t += 2
    log.append("t=%4ds  EXPAND: ADD COLUMN shipping_cents (nullable), lock_timeout=50ms" % t)

    fleet = ["v1"] * FLEET_SIZE
    for b in range(0, FLEET_SIZE, 2):
        drive(w, fleet, STARTUP_S, rng)
        t += STARTUP_S
        fleet[b] = fleet[b + 1] = "v2"
    dark = TRAFFIC * STARTUP_S * 3
    log.append("t=%4ds  DEPLOY v2 everywhere, dual-writing, flag at 0%% — nobody can reach it" % t)

    rows, batches = 574, 0
    while rows > 0:
        rows -= 100
        batches += 1
        t += 1
    log.append("t=%4ds  BACKFILL 574 legacy rows in %d bounded batches (keyset, not OFFSET)"
               % (t, batches))

    new_path_seen = 0
    w.exposure_bp = 100                                  # 1%
    diverged = 0
    while new_path_seen < CANARY_MIN_NEW_PATH:
        t += 1
        for uid in users(TRAFFIC, rng):
            on = bucket(FLAG, uid) < w.exposure_bp
            r = serve(w, "v2", uid)
            if on:
                new_path_seen += 1
                if r == "mispriced":
                    diverged += 1
                    w.mispriced += 1
            if r == "error":
                w.errors += 1
    canary_t = t
    rate = diverged / new_path_seen
    log.append("t=%4ds  CANARY at 1%%: %d new-path requests observed, %d disagreed with the"
               % (t, new_path_seen, diverged))
    log.append("        old path's quote (%.2f%%). Threshold 0.50%% -> ABORT, exposure -> 0%%."
               % (rate * 100))
    w.exposure_bp = 0
    t += 7

    fix_t = 900
    t += fix_t
    log.append("t=%4ds  fix shipped as a new artifact, re-ramped from 1%%" % t)

    for step in (100, 500, 2500, 10_000):
        w.exposure_bp = step
        for _ in range(CANARY_STEP_SOAK):
            t += 1
            for uid in users(TRAFFIC, rng):
                on = bucket(FLAG, uid) < w.exposure_bp
                if on and zone_of(uid) == "legacy-north":
                    pass                                  # fixed: no divergence
        log.append("t=%4ds  exposure %5.1f%% — analysis green, promote" % (t, step / 100))

    soak = 1800
    t += soak
    log.append("t=%4ds  soak at 100%% for %d s with the old column still present" % (t, soak))
    log.append("        (this window is the ONLY time the kill switch is reachable)")
    return {"w": w, "t": t, "log": log, "canary_t": canary_t, "dark": dark,
            "new_path_seen": new_path_seen, "diverged": diverged}


READ_SHARE = 0.40            # the order-history endpoint: SELECT *, no write


def drive(w: World, fleet: List[str], seconds: int, rng: random.Random) -> None:
    for _ in range(seconds):
        for _ in range(TRAFFIC):
            uid = "u%06d" % rng.randrange(USERS)
            kind = "read" if rng.random() < READ_SHARE else "write"
            r = serve(w, fleet[rng.randrange(FLEET_SIZE)], uid, kind)
            if r == "error":
                w.errors += 1
            elif r == "bad_read":
                w.bad_reads += 1
            elif r == "mispriced":
                w.mispriced += 1


def run_wrong_a() -> dict:
    """Migration + new code in one release. Readiness never passes on one instance."""
    rng = random.Random(SEED + 2)
    w = World()
    t = 0
    log = []

    w.columns.add("shipping_cents")
    w.columns.discard("shipping_fee")
    log.append("t=%4ds  one migration: ADD shipping_cents, DROP shipping_fee" % t)

    fleet = ["v1"] * FLEET_SIZE
    for b in range(0, FLEET_SIZE, 2):
        if b == 4:
            break
        drive(w, fleet, STARTUP_S, rng)          # new pods starting; old ones still serve
        t += STARTUP_S
        fleet[b] = fleet[b + 1] = "v3"
    log.append("t=%4ds  4 of 6 on v3. Instance 5 never passes readiness: the new build" % t)
    log.append("        fail-fasts on a missing QUOTE_API_KEY that only staging ever had.")
    log.append("        maxUnavailable=1, so the rollout will NOT take down instance 6.")

    progress_deadline = 600
    drive(w, fleet, progress_deadline, rng)
    t += progress_deadline
    log.append("t=%4ds  progressDeadlineSeconds=%d elapsed. The Deployment condition flips to"
               % (t, progress_deadline))
    log.append("        ProgressDeadlineExceeded. It does not roll back. It reports.")

    human = 240
    drive(w, fleet, human, rng)
    t += human
    log.append("t=%4ds  human diagnoses the missing config key (%d s of a Saturday)" % (t, human))

    drive(w, fleet, STARTUP_S, rng)
    t += STARTUP_S
    fleet = ["v3"] * FLEET_SIZE
    log.append("t=%4ds  key set, rollout finishes, errors stop. Rollback was never an option:" % t)
    log.append("        shipping_fee is gone, so v1 cannot run at all — and 'roll back' was")
    log.append("        the first thing the runbook said to do.")
    return {"w": w, "t": t, "log": log, "ttm": t}


def run_wrong_b() -> dict:
    """Correct expand + dual-write deploy, then an INSTANCE canary of a FLAG change."""
    rng = random.Random(SEED + 3)
    w = World()
    t = 0
    log = []
    w.columns.add("shipping_cents")
    t += 2
    log.append("t=%4ds  EXPAND: ADD COLUMN shipping_cents — correct, additive" % t)

    for b in range(0, FLEET_SIZE, 2):
        t += STARTUP_S
    log.append("t=%4ds  DEPLOY v2 everywhere, dual-writing, flag %s at 1%%" % (t, FLAG))

    w.exposure_bp = 100
    canary_window = 600
    canary_reqs = 0
    canary_new_path = 0
    canary_errors = 0
    per_instance = TRAFFIC // FLEET_SIZE
    for _ in range(canary_window):
        t += 1
        for uid in users(per_instance, rng):
            canary_reqs += 1
            on = bucket(FLAG, uid) < w.exposure_bp
            r = serve(w, "v2", uid)
            if on:
                canary_new_path += 1
                if r == "mispriced":
                    canary_errors += 1
                    w.mispriced += 1
    log.append("t=%4ds  instance canary (1 of 6) watched for %d s:" % (t, canary_window))
    log.append("        %d requests, 0 errors, latency flat vs the other five. PROMOTE."
               % canary_reqs)
    log.append("        requests that executed the NEW PATH: %d of %d (%.2f%%)."
               % (canary_new_path, canary_reqs, 100.0 * canary_new_path / canary_reqs))

    w.exposure_bp = 10_000
    detect = 2 * 3600
    for _ in range(detect):
        t += 1
        n_bad = 0
        for uid in users(1, rng):
            pass
        n_bad = int(TRAFFIC * LEGACY_ZONE_BP / 10_000)
        w.mispriced += n_bad
        w.served += TRAFFIC
    log.append("t=%4ds  exposure -> 100%%. Nothing alerts: 0 errors, flat latency." % t)
    log.append("t=%4ds  the nightly finance reconciliation flags the first bad shipping totals."
               % t)
    return {"w": w, "t": t, "log": log,
            "canary_reqs": canary_reqs, "canary_new_path": canary_new_path,
            "canary_errors": canary_errors, "detect": detect}


def act_risky_change(digest: str) -> dict:
    head(4, "LAND A RISKY CHANGE  (lessons 11, 12, 13)")
    print("  the change needs BOTH a schema migration and a new code path:")
    print("    orders.shipping_fee  ->  orders.shipping_cents, computed by a new quote engine")
    print("  the new engine is wrong for the %.2f%% of users in the legacy-north zone."
          % (LEGACY_ZONE_BP / 100))
    print("  it does not raise. It returns a number. Traffic is %d req/s throughout.\n" % TRAFFIC)

    print("  --- RUN 1: expand -> deploy dark -> canary -> ramp -> soak ---")
    a = run_correct(digest)
    for line in a["log"]:
        print("  " + line)
    print("  cost: %d 5xx, %d silent bad reads, %d mispriced orders"
          % (a["w"].errors, a["w"].bad_reads, a["w"].mispriced))

    print("\n  --- RUN 2: 'it is one migration and one deploy' ---")
    b = run_wrong_a()
    for line in b["log"]:
        print("  " + line)
    print("  cost: %d 5xx, %d silent bad reads, %d mispriced orders, TTM %d s"
          % (b["w"].errors, b["w"].bad_reads, b["w"].mispriced, b["ttm"]))

    print("\n  --- RUN 3: correct expand, then an INSTANCE canary of a FLAG change ---")
    c = run_wrong_b()
    for line in c["log"]:
        print("  " + line)
    print("  cost: %d 5xx, %d silent bad reads, %d mispriced orders, TTD %d s"
          % (c["w"].errors, c["w"].bad_reads, c["w"].mispriced, c["detect"]))

    print("\n  run                              5xx  bad reads  mispriced  detected in  by")
    print("  1 expand/dark/canary/ramp   %8d %10d %10d %10d s  canary, %d new-path samples"
          % (a["w"].errors, a["w"].bad_reads, a["w"].mispriced, a["canary_t"],
             a["new_path_seen"]))
    print("  2 migration+deploy together %8d %10d %10d %10d s  a human, on a Saturday"
          % (b["w"].errors, b["w"].bad_reads, b["w"].mispriced, b["ttm"]))
    print("  3 instance canary of a flag %8d %10d %10d %10d s  the finance job, next day"
          % (c["w"].errors, c["w"].bad_reads, c["w"].mispriced, c["detect"]))
    print("  runs 1 and 3 both report ZERO user-facing errors. One of them charged")
    print("  %d customers the wrong shipping total and nothing on any dashboard moved."
          % c["w"].mispriced)
    guard("deployment", "L11", "canary gated on NEW-PATH sample count",
          "yes", "aborted at 1%% on %d samples; run 3's canary saw %d"
          % (a["new_path_seen"], c["canary_new_path"]))
    guard("release", "L12", "deploy != release (flag defaults off)",
          "yes", "%d requests served by the new artifact, reachable by nobody" % a["dark"])
    guard("config", "L5", "fail-fast on a missing required key",
          "yes", "run 2: refused to serve rather than serve wrong — and stalled the rollout")
    guard("schema", "L13", "expand/migrate/contract, separate deploys",
          "yes", "run 2's one-step version cost %d 5xx and %d silent bad reads"
          % (b["w"].errors, b["w"].bad_reads))
    return {"correct": a, "wrong_a": b, "wrong_b": c}


# ---------------------------------------------------------------------------
# 5 - THE INCIDENT
# ---------------------------------------------------------------------------

PARTNER_QUOTA = 260          # quote calls/s the partner will accept
INCIDENT_TRAFFIC = 310       # organic growth, two hours after the ramp finished


def mitigate_flag() -> Tuple[float, List[Tuple[str, float]]]:
    stages = [("operator decision", 3.0), ("control-plane write", 0.5),
              ("streaming push to SDKs", 1.2), ("in-process cache TTL", 2.0)]
    return sum(s for _, s in stages), stages


def mitigate_rollback() -> Tuple[float, List[Tuple[str, float]], float]:
    stages = [("operator decision", 30.0), ("control-plane trigger", 5.0)]
    total = sum(s for _, s in stages)
    relief_at = None
    served_new = FLEET_SIZE
    for b in range(FLEET_SIZE // 2):
        total += STARTUP_S
        served_new -= 2
        if relief_at is None and INCIDENT_TRAFFIC * served_new / FLEET_SIZE <= PARTNER_QUOTA:
            relief_at = total
        stages.append(("batch %d of 3 ready" % (b + 1), float(STARTUP_S)))
    total += DRAIN_WAIT_S
    stages.append(("final drain", float(DRAIN_WAIT_S)))
    return total, stages, relief_at


def mitigate_forward() -> Tuple[float, List[Tuple[str, float]]]:
    stages = [("operator decision", 30.0), ("write the fix", 240.0), ("review", 180.0),
              ("CI critical path", 320.0), ("control-plane trigger", 5.0),
              ("rolling deploy", float(STARTUP_S * 3 + DRAIN_WAIT_S))]
    return sum(s for _, s in stages), stages


def options(prev_build_reads: set, columns: set, verbose: bool) -> dict:
    over = INCIDENT_TRAFFIC - PARTNER_QUOTA
    err_per_s = over
    flag_t, flag_stages = mitigate_flag()
    rb_t, rb_stages, rb_relief = mitigate_rollback()
    fw_t, fw_stages = mitigate_forward()

    old_path_present = "shipping_fee" in columns
    rollback_ok = prev_build_reads <= columns

    rows = [
        ("flag kill switch (exposure -> 0%)", flag_t, old_path_present,
         "the flag-off path still has a column to read",
         "flag-off path reads shipping_fee: DROPPED"),
        ("rollback to the previous release", rb_t, rollback_ok,
         "the previous build's columns all still exist",
         "previous build reads shipping_fee: DROPPED"),
        ("roll forward with a fix", fw_t, True,
         "always available, never fast", ""),
    ]
    print("  option                              TTM   reachable  errors  why")
    for label, ttm, reach, why_yes, why_no in rows:
        errs = int(ttm * err_per_s) if reach else 0
        print("  %-34s %5.1fs  %-9s %6s  %s"
              % (label, ttm, "YES" if reach else "NO",
                 ("%d" % errs) if reach else "-", why_yes if reach else why_no))
    if verbose:
        print("  the %0.1f s flip breaks down as %s" %
              (flag_t, " + ".join("%s %.1fs" % (n, s) for n, s in flag_stages)))
        print("  the rollback reaches PARTIAL relief at %.0f s: with 2 of 6 instances back on"
              % rb_relief)
        print("  the old path the partner rate is %d/s, under the %d/s quota. It still reverts"
              % (int(INCIDENT_TRAFFIC * 4 / FLEET_SIZE), PARTNER_QUOTA))
        print("  every other change in that artifact, which the flag flip does not.")
    return {"flag_t": flag_t, "rb_t": rb_t, "fw_t": fw_t, "err_per_s": err_per_s,
            "old_path_present": old_path_present, "rollback_ok": rollback_ok}


def act_incident_wrapper(res: dict) -> dict:
    head(5, "THE INCIDENT  (lessons 12, 14)")
    columns = set(res["correct"]["w"].columns)
    prev_reads = {"id", "user_id", "zone", "shipping_fee"}
    over = INCIDENT_TRAFFIC - PARTNER_QUOTA
    print("  two hours after the ramp finished, traffic grows %d -> %d req/s."
          % (TRAFFIC, INCIDENT_TRAFFIC))
    print("  the new path calls the partner's quote API once per request. The partner's")
    print("  quota is %d/s. %d/s are now rejected: a %.2f%% error rate, and it is ours."
          % (PARTNER_QUOTA, over, 100.0 * over / INCIDENT_TRAFFIC))
    print("  the highest partner rate at ANY point during the ramp was %d/s — %.0f%% of quota."
          % (TRAFFIC, 100.0 * TRAFFIC / PARTNER_QUOTA))
    print("  no exposure step could have found this. The fault is a function of ABSOLUTE")
    print("  volume; the largest volume the ramp ever produced was its own final step.\n")

    print("  --- world A: the soak window. CONTRACT HAS NOT RUN. ---")
    a = options(prev_reads, columns, True)

    columns_b = set(columns)
    columns_b.discard("shipping_fee")
    print("\n  --- world B: 'while we are in here' — contract shipped with the 100% ramp ---")
    b = options(prev_reads, columns_b, False)

    print("\n  the same incident, in two worlds that differ by one DROP COLUMN:")
    print("    world A   fastest reachable option  %6.1f s   %6d user-facing errors"
          % (a["flag_t"], int(a["flag_t"] * a["err_per_s"])))
    print("    world B   fastest reachable option  %6.1f s   %6d user-facing errors"
          % (b["fw_t"], int(b["fw_t"] * b["err_per_s"])))
    print("    ratio     %.0fx slower, %dx the damage, for a tidy-up nobody scheduled."
          % (b["fw_t"] / a["flag_t"],
             int(b["fw_t"] * b["err_per_s"]) // max(1, int(a["flag_t"] * a["err_per_s"]))))
    print("  the kill switch is a CODE PATH. Contracting the schema deleted the data it")
    print("  reads, so the switch was still in the console and no longer connected to")
    print("  anything. Reachability is computable before you deploy; nothing computes it.")
    guard("rollback", "L14", "reachable-set computed before the contract shipped",
          "yes", "kept the kill switch alive: %.1f s instead of %.1f s to mitigate"
          % (a["flag_t"], b["fw_t"]))

    rto_mb_s = 28.4
    db_gb = 240
    rto_s = db_gb * 1024 / rto_mb_s
    print("\n  and the option nobody had to use: restore. Measured restore throughput")
    print("  %.1f MB/s against a %d GB database is %dh %02dm — the honest RTO for the"
          % (rto_mb_s, db_gb, int(rto_s // 3600), int((rto_s % 3600) // 60)))
    print("  case where a migration had destroyed data instead of merely blocking a path.")
    return {"a": a, "b": b}


# ---------------------------------------------------------------------------
# 6 - THE SCORECARD
# ---------------------------------------------------------------------------


def act_scorecard() -> None:
    head(6, "THE SCORECARD")
    print("  stage           lsn    guard                                     held  what it bought")
    for stage, lesson, name, fired, saved in GUARDS:
        print("  %-15s %-6s %-41s %-5s %s" % (stage, lesson, name[:41], fired, saved))
    fired = [g for g in GUARDS if g[3] == "yes"]
    missing = [g for g in GUARDS if g[3] == "no"]
    print("\n  %d of %d guards held. %d was absent:" % (len(fired), len(GUARDS), len(missing)))
    for _, _, name, _, saved in missing:
        print("    %s — %s." % (name, saved))
    print("  every guard above is one line of configuration or one CI check. None of them")
    print("  is a tool you buy; all of them are a number somebody wrote down on purpose.")


# ---------------------------------------------------------------------------


def main() -> None:
    print("SHIP A SERVICE END TO END — one pipeline, six acts, every number measured.")
    print("All times are SIMULATED seconds. Seed=%d." % SEED)
    digest, prod_release, _ = act_build_and_pin()
    act_declare_and_converge(prod_release)
    act_route()
    res = act_risky_change(digest)
    act_incident_wrapper(res)
    act_scorecard()
    print("\n  one artifact digest, %s, carried every stage." % short(digest, 18))


if __name__ == "__main__":
    main()
