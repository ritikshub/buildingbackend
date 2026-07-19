#!/usr/bin/env python3
"""CI/CD: From Commit to Artifact to Environment -- runnable companion.

Lesson: phases/10-infrastructure-and-deployment/10-ci-cd-pipelines/docs/en.md
Sources: the twelve-factor app manifesto (https://12factor.net) factor V
(Build, release, run); OCI Image Format Specification v1.1 (content addressing).
Real here: topological DAG scheduling on a bounded runner pool, content-derived
cache keys and their invalidation cascade, critical-path/slack analysis, seeded
Monte-Carlo flake simulation, and digest-based promotion with per-env releases.
Modelled here: stage DURATIONS are seconds on a virtual clock, so a 13-minute
pipeline schedules exactly and instantly. Stdlib only. Deterministic (seed 7).
"""

from __future__ import annotations

import hashlib
import heapq
import random
from dataclasses import dataclass
from typing import Dict, List, Mapping, Sequence, Set, Tuple

SEED = 7
CACHE_RESTORE_S = 5      # restoring a cache is not free: a tarball still moves
RUNNERS = 4              # concurrent CI runners the org pays for


def banner(n: int, title: str) -> None:
    print("\n== %d · %s ==" % (n, title))


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ======================================================================================
# THE WORKSPACE -- the bytes a pipeline is a function of.
# ======================================================================================
WORKSPACE: Dict[str, str] = {
    "requirements.lock": "flask==3.0.3\npsycopg==3.2.1\nredis==5.0.8\n",
    "Dockerfile": "FROM python@sha256:1f2e3d...\nCOPY src/ /app/src\nCMD [\"python\", \"-m\", \"app\"]\n",
    "src/app/main.py": "def main():\n    serve(port=8080)\n",
    "src/app/handlers.py": "def checkout(req):\n    return charge(req.cart)\n",
    "src/app/models.py": "class Cart:\n    items: list\n",
    "tests/unit/test_cart.py": "def test_cart_total():\n    assert total([]) == 0\n",
    "tests/unit/test_models.py": "def test_cart_empty():\n    assert Cart().items == []\n",
    "tests/integration/test_checkout.py": "def test_checkout_e2e():\n    post('/checkout')\n",
}


@dataclass(frozen=True)
class Stage:
    """One node of the pipeline DAG.

    `inputs` are path prefixes this stage READS. The cache key is derived from
    the content of those files plus the transitive inputs of everything it
    depends on -- which is exactly why a manifest change invalidates the world.
    """
    name: str
    deps: Tuple[str, ...]
    seconds: int
    inputs: Tuple[str, ...]
    tool: str


PIPELINE: Tuple[Stage, ...] = (
    Stage("deps-install",       (),                     180, ("requirements.lock",),          "pip 24.2"),
    Stage("lint",               ("deps-install",),       45, ("src/",),                       "ruff 0.6.9"),
    Stage("typecheck",          ("deps-install",),       95, ("src/",),                       "mypy 1.11.2"),
    Stage("unit-tests",         ("deps-install",),      210, ("src/", "tests/unit/"),         "pytest 8.3.3"),
    Stage("build-image",        ("deps-install",),      260, ("src/", "Dockerfile"),          "buildkit 0.16"),
    Stage("integration-tests",  ("build-image",),       300, ("tests/integration/",),         "pytest 8.3.3"),
    Stage("security-scan",      ("build-image",),       120, (),                              "trivy 0.55"),
    Stage("push-artifact",      ("lint", "typecheck", "unit-tests",
                                 "integration-tests", "security-scan"),
                                                         40, (),                              "oras 1.2.0"),
)

BY_NAME: Dict[str, Stage] = {s.name: s for s in PIPELINE}


# ======================================================================================
# 1 · CACHE KEYS -- derived from input CONTENT, never from a branch name or a date.
# ======================================================================================
def effective_inputs(name: str) -> Set[str]:
    """Own declared inputs, plus every input its dependencies transitively read."""
    stage = BY_NAME[name]
    acc: Set[str] = set(stage.inputs)
    for dep in stage.deps:
        acc |= effective_inputs(dep)
    return acc


def matching_files(prefixes: Set[str], workspace: Mapping[str, str]) -> List[str]:
    return sorted(p for p in workspace if any(p == q or p.startswith(q) for q in prefixes))


def cache_key(name: str, workspace: Mapping[str, str]) -> str:
    """H(stage identity + tool version + content of every effective input).

    Nothing ambient goes in: no hostname, no timestamp, no build number. A key
    that depends on the machine is a key that can never hit on another machine.
    """
    stage = BY_NAME[name]
    parts = [stage.name, stage.tool]
    for path in matching_files(effective_inputs(name), workspace):
        parts.append("%s=%s" % (path, sha(workspace[path].encode())[:16]))
    return sha("\n".join(parts).encode())[:12]


# ======================================================================================
# 2 · THE ENGINE -- topological scheduling onto a bounded pool of runners.
# ======================================================================================
def schedule(durations: Mapping[str, int], runners: int) -> Tuple[List[Tuple[str, int, int]], int]:
    """Event-driven scheduler. Ready stages are dispatched longest-first (a real
    heuristic: the long pole should start as early as it can). Returns the
    timeline as (stage, start, end) and the total wall time."""
    waiting = {s.name: set(s.deps) for s in PIPELINE}
    started: Set[str] = set()
    timeline: List[Tuple[str, int, int]] = []
    running: List[Tuple[int, str]] = []
    free, now = runners, 0

    while len(timeline) < len(PIPELINE) or running:
        ready = sorted((n for n, d in waiting.items() if not d and n not in started),
                       key=lambda n: (-durations[n], n))
        while free and ready:
            name = ready.pop(0)
            started.add(name)
            end = now + durations[name]
            heapq.heappush(running, (end, name))
            timeline.append((name, now, end))
            free -= 1
        if not running:
            raise RuntimeError("dependency cycle: nothing can run")
        now = running[0][0]
        while running and running[0][0] == now:
            _, finished = heapq.heappop(running)
            free += 1
            for deps in waiting.values():
                deps.discard(finished)
    return timeline, max(end for _, _, end in timeline)


def run_pipeline(workspace: Mapping[str, str], cache: Set[str],
                 runners: int = RUNNERS) -> Dict[str, object]:
    """Compute each stage's key, decide hit/miss, schedule, and update the cache."""
    keys = {s.name: cache_key(s.name, workspace) for s in PIPELINE}
    hits = {n: keys[n] in cache for n in keys}
    durations = {n: (CACHE_RESTORE_S if hits[n] else BY_NAME[n].seconds) for n in keys}
    timeline, total = schedule(durations, runners)
    cache.update(keys.values())
    return {"keys": keys, "hits": hits, "durations": durations,
            "timeline": timeline, "total": total,
            "work": sum(durations.values()),
            "executed": sum(BY_NAME[n].seconds for n in keys if not hits[n])}


def gantt(timeline: Sequence[Tuple[str, int, int]], hits: Mapping[str, bool],
          scale: int, width: int = 46) -> None:
    order = sorted(timeline, key=lambda t: (t[1], t[0]))
    print("  %-19s %6s %6s  %-8s %s" % ("STAGE", "START", "END", "CACHE", "TIMELINE (each block = %ds)" % scale))
    for name, start, end in order:
        lead = " " * min(width, start // scale)
        bar = "#" * max(1, (end - start) // scale)
        print("  %-19s %5ds %5ds  %-8s |%s%s" % (
            name, start, end, "HIT" if hits[name] else "miss", lead, bar[:width]))


# ======================================================================================
# 3 · CRITICAL PATH -- longest path through the DAG; everything else has slack.
# ======================================================================================
def critical_path(durations: Mapping[str, int]) -> Tuple[List[str], int, Dict[str, int]]:
    order = topo_order()
    early_finish: Dict[str, int] = {}
    for name in order:
        start = max([early_finish[d] for d in BY_NAME[name].deps], default=0)
        early_finish[name] = start + durations[name]
    project = max(early_finish.values())

    successors: Dict[str, List[str]] = {s.name: [] for s in PIPELINE}
    for s in PIPELINE:
        for d in s.deps:
            successors[d].append(s.name)

    late_finish: Dict[str, int] = {}
    for name in reversed(order):
        if not successors[name]:
            late_finish[name] = project
        else:
            late_finish[name] = min(late_finish[x] - durations[x] for x in successors[name])
    slack = {n: late_finish[n] - early_finish[n] for n in order}

    path, cursor = [], max((n for n in order if slack[n] == 0), key=lambda n: early_finish[n])
    while True:
        path.append(cursor)
        parents = [d for d in BY_NAME[cursor].deps if slack[d] == 0]
        if not parents:
            break
        cursor = max(parents, key=lambda n: early_finish[n])
    return list(reversed(path)), project, slack


def topo_order() -> List[str]:
    waiting = {s.name: set(s.deps) for s in PIPELINE}
    order: List[str] = []
    while waiting:
        nxt = sorted(n for n, d in waiting.items() if not d)[0]
        order.append(nxt)
        del waiting[nxt]
        for d in waiting.values():
            d.discard(nxt)
    return order


# ======================================================================================
# 4 · FLAKE ARITHMETIC
# ======================================================================================
FLAKY_JOB = 12                 # "integration-shard-3": 70% reliable
FLAKY_RELIABILITY = 0.70
OTHER_RELIABILITY = 0.998
N_JOBS = 20
REGRESSION_JOB = 4             # a normally-solid gating job
RACE_MANIFEST = 0.40           # a genuine concurrency bug that shows 40% of runs


def job_reliability(i: int) -> float:
    return FLAKY_RELIABILITY if i == FLAKY_JOB else OTHER_RELIABILITY


def simulate_green(reliability: float, jobs: int, runs: int, rng: random.Random) -> float:
    green = 0
    for _ in range(runs):
        for _ in range(jobs):
            if rng.random() >= reliability:
                break
        else:
            green += 1
    return green / runs


def run_policy(policy: str, defect: str, rng: random.Random) -> Tuple[bool, int]:
    """One pipeline under one policy. Returns (green, job-runs consumed).

    defect: "none" | "deterministic" | "race" | "in-flaky-job"
    policy: "none" | "rerun-all" | "retry-job" | "quarantine"
    """
    attempts_allowed = 3 if policy == "rerun-all" else 1
    cost = 0
    for _ in range(attempts_allowed):
        pipeline_red = False
        for job in range(N_JOBS):
            tries = 3 if policy == "retry-job" else 1
            passed = False
            for _ in range(tries):
                cost += 1
                ok = rng.random() < job_reliability(job)
                if job == REGRESSION_JOB and defect == "deterministic":
                    ok = False
                if job == REGRESSION_JOB and defect == "race" and rng.random() < RACE_MANIFEST:
                    ok = False
                if job == FLAKY_JOB and defect == "in-flaky-job":
                    ok = False
                if ok:
                    passed = True
                    break
            gating = not (policy == "quarantine" and job == FLAKY_JOB)
            if not passed and gating:
                pipeline_red = True
        if not pipeline_red:
            return True, cost
    return False, cost


def measure(policy: str, defect: str, runs: int, seed: int) -> Tuple[float, float]:
    rng = random.Random(seed)
    green, cost = 0, 0
    for _ in range(runs):
        ok, c = run_policy(policy, defect, rng)
        green += ok
        cost += c
    return green / runs, cost / runs


# ======================================================================================
# 5 · BUILD ONCE, PROMOTE MANY
# ======================================================================================
BASE_IMAGE = "sha256:1f2e3d4c5b6a7988"

ENV_CONFIG: Dict[str, Dict[str, object]] = {
    "dev":     {"LOG_LEVEL": "debug", "DB_POOL": 2,  "REQUEST_TIMEOUT_MS": 5000, "CHECKOUT_V2": True},
    "staging": {"LOG_LEVEL": "info",  "DB_POOL": 10, "REQUEST_TIMEOUT_MS": 2000, "CHECKOUT_V2": True},
    "prod":    {"LOG_LEVEL": "warn",  "DB_POOL": 60, "REQUEST_TIMEOUT_MS": 1500, "CHECKOUT_V2": False},
}


def artifact_digest(workspace: Mapping[str, str], base: str = BASE_IMAGE,
                    build_arg: str = "", stamp: str = "") -> str:
    """The digest of the built image. With no build_arg and no timestamp it is a
    pure function of the source -- which is what makes promotion possible."""
    parts = [base, build_arg, stamp]
    for path in sorted(workspace):
        if path.startswith("src/") or path in ("Dockerfile", "requirements.lock"):
            parts.append("%s=%s" % (path, sha(workspace[path].encode())[:16]))
    return "sha256:" + sha("\n".join(parts).encode())


def config_hash(cfg: Mapping[str, object]) -> str:
    canonical = "\n".join("%s=%r" % (k, cfg[k]) for k in sorted(cfg))
    return sha(canonical.encode())


def release_id(digest: str, cfg: str) -> str:
    return "rel-" + sha(("%s+%s" % (digest, cfg)).encode())[:12]


# ======================================================================================
def main() -> None:
    # ---------------------------------------------------------------- section 1
    banner(1, "A PIPELINE IS A DAG, NOT A LIST OF SCRIPTS")
    print("  %d stages, %d runners, cold cache (nothing has ever been built)" % (len(PIPELINE), RUNNERS))
    cache: Set[str] = set()
    cold = run_pipeline(WORKSPACE, cache)
    gantt(cold["timeline"], cold["hits"], scale=15)
    total_work = sum(s.seconds for s in PIPELINE)
    print("  total work across all stages : %5ds  (%.1f min of runner time billed)"
          % (total_work, total_work / 60))
    print("  wall time on %d runners       : %5ds  (%.1f min the developer waits)"
          % (RUNNERS, cold["total"], cold["total"] / 60))
    print("  parallelism actually achieved : %.2fx" % (total_work / cold["total"]))
    print("  4 stages ran concurrently at t=180s; the graph, not the config, decided that.")

    # ---------------------------------------------------------------- section 2
    banner(2, "CACHING, MEASURED: THE INVALIDATION CASCADE")
    print("  cache keys are H(stage + tool version + content of every effective input).")
    print("  three changes, each one file, each a bigger blast radius:\n")
    scenarios = [
        ("edit tests/unit/test_cart.py", "tests/unit/test_cart.py",
         "def test_cart_total():\n    assert total([]) == 0\n    assert total([1]) == 1\n"),
        ("edit src/app/handlers.py", "src/app/handlers.py",
         "def checkout(req):\n    return charge(req.cart, idempotency_key=req.key)\n"),
        ("edit requirements.lock", "requirements.lock",
         "flask==3.0.3\npsycopg==3.2.2\nredis==5.0.8\n"),
    ]
    warm_results = []
    print("  %-30s %s" % ("CHANGE", " ".join("%-6s" % s.name[:6] for s in PIPELINE)))
    workspace = dict(WORKSPACE)
    for label, path, content in scenarios:
        ws = dict(workspace)
        ws[path] = content
        fresh = set(cold["keys"].values())          # cache as of the cold build
        res = run_pipeline(ws, fresh)
        warm_results.append((label, res))
        marks = " ".join("%-6s" % ("HIT" if res["hits"][s.name] else "miss") for s in PIPELINE)
        print("  %-30s %s" % (label, marks.rstrip()))

    print()
    print("  %-30s %6s %7s %7s %8s %8s" % ("CHANGE", "STAGES", "WORK", "SKIPPED", "WALL", "SPEED-UP"))
    print("  %-30s %5d/%d %6ds %6ds %7ds %8s" % (
        "(cold build, nothing cached)", len(PIPELINE), len(PIPELINE),
        cold["work"], 0, cold["total"], "1.00x"))
    for label, res in warm_results:
        misses = sum(1 for v in res["hits"].values() if not v)
        skipped = total_work - res["executed"]
        print("  %-30s %5d/%d %6ds %6ds %7ds %7.2fx" % (
            label, misses, len(PIPELINE), res["work"], skipped, res["total"],
            cold["total"] / res["total"]))
    a, b, c = (r for _, r in warm_results)
    print("  a test-file edit skipped %d%% of the work and cut wall time %d%%." % (
        round(100 * (total_work - a["executed"]) / total_work),
        round(100 * (cold["total"] - a["total"]) / cold["total"])))
    print("  a source edit skipped only %d%% of the work yet cut wall time %d%% --" % (
        round(100 * (total_work - b["executed"]) / total_work),
        round(100 * (cold["total"] - b["total"]) / cold["total"])))
    print("  because the one stage it DID skip (deps-install) sits on the critical path.")
    print("  one line in requirements.lock invalidated %d/%d stages: the manifest is an" % (
        sum(1 for v in c["hits"].values() if not v), len(PIPELINE)))
    print("  input to deps-install, and every other stage transitively reads it.")
    print("  (a cache HIT is charged %ds here -- restoring a cache still moves bytes;" % CACHE_RESTORE_S)
    print("   a cache 'hit' that costs more than the stage is a cache you should delete.)")

    # ---------------------------------------------------------------- section 3
    banner(3, "THE CRITICAL PATH IS THE ONLY STAGE LIST THAT MATTERS")
    base_durations = {s.name: s.seconds for s in PIPELINE}
    path, project, slack = critical_path(base_durations)
    print("  critical path : %s" % " -> ".join(path))
    print("  its length    : %ds   total work across all stages: %ds  (ratio %.2fx)"
          % (project, total_work, total_work / project))
    print()
    print("  %-19s %8s %7s %10s" % ("STAGE", "SECONDS", "SLACK", "ON PATH?"))
    for s in PIPELINE:
        print("  %-19s %7ds %6ds %10s" % (
            s.name, s.seconds, slack[s.name], "CRITICAL" if slack[s.name] == 0 else "-"))
    print()
    print("  more runners never beat the critical path:")
    print("  %-10s %8s" % ("RUNNERS", "WALL"))
    floored = False
    for r in (1, 2, 3, 4, 6, 8):
        _, tot = schedule(base_durations, r)
        note = ""
        if tot == project and not floored:
            note, floored = "  <- floor reached; every runner after this is idle money", True
        print("  %-9d %7ds%s" % (r, tot, note))
    print()
    print("  now halve one stage's duration, twice -- once off the path, once on it:")
    print("  %-42s %8s %8s %9s" % ("SCENARIO", "WORK", "WALL", "SAVED"))
    _, base_total = schedule(base_durations, RUNNERS)
    print("  %-42s %7ds %7ds %8ds" % ("baseline", total_work, base_total, 0))
    for victim in ("unit-tests", "integration-tests"):
        d = dict(base_durations)
        d[victim] = d[victim] // 2
        _, tot = schedule(d, RUNNERS)
        tag = "CRITICAL" if slack[victim] == 0 else "not on path"
        print("  %-42s %7ds %7ds %8ds" % (
            "halve %s (%s)" % (victim, tag), sum(d.values()), tot, base_total - tot))
    print("  halving unit-tests removed 105s (8%) of billed work and saved the")
    print("  developer ZERO seconds. Halving integration-tests removed 150s and")
    print("  saved exactly 150s. Optimise the path or do not bother.")

    # ---------------------------------------------------------------- section 4
    banner(4, "FLAKY TESTS ARE ARITHMETIC, NOT BAD LUCK")
    rng = random.Random(SEED)
    runs = 60_000
    print("  P(green pipeline) = p^n for n independent jobs each p reliable")
    print("  %-14s %s" % ("PER-JOB p", "  ".join("%-22s" % ("n = %d jobs" % n) for n in (5, 10, 20))))
    print("  %-14s %s" % ("", "  ".join("%-22s" % "analytic   simulated" for _ in (5, 10, 20))))
    for p in (0.99, 0.95, 0.90):
        cells = []
        for n in (5, 10, 20):
            cells.append("%-22s" % ("%7.1f%%   %7.1f%%" % (100 * p ** n, 100 * simulate_green(p, n, runs, rng))))
        print("  %-14s %s" % ("%.2f" % p, "  ".join(cells)))
    print("  (%s runs per cell, seeded; simulation tracks the analytic value to <0.5pp)" % f"{runs:,}")
    print("  a 20-job pipeline of 95%%-reliable jobs is green %.1f%% of the time." % (100 * 0.95 ** 20))
    print("  nobody wrote a bug. Every job is 'basically fine'. The pipeline is not.")
    print()
    print("  now one concrete pipeline: %d jobs, job %d ('integration-shard-3') is" % (N_JOBS, FLAKY_JOB))
    print("  %.0f%% reliable, the other %d are %.1f%%. Four responses:" % (
        100 * FLAKY_RELIABILITY, N_JOBS - 1, 100 * OTHER_RELIABILITY))
    print()
    print("  %-32s %8s %9s %10s %10s %10s" % (
        "RESPONSE", "GREEN", "JOB-RUNS", "det. bug", "RACE 40%", "bug in the"))
    print("  %-32s %8s %9s %10s %10s %10s" % (
        "", "on clean", "per run", "caught", "caught", "flaky job"))
    policies = [
        ("do nothing", "none"),
        ("press re-run (whole pipeline x3)", "rerun-all"),
        ("auto-retry each failed job x3", "retry-job"),
        ("quarantine job %d, then fix" % FLAKY_JOB, "quarantine"),
    ]
    pol_runs = 40_000
    scores = {}
    for label, key in policies:
        green, cost = measure(key, "none", pol_runs, SEED)
        det, _ = measure(key, "deterministic", pol_runs, SEED + 1)
        race, _ = measure(key, "race", pol_runs, SEED + 2)
        inflaky, _ = measure(key, "in-flaky-job", pol_runs, SEED + 3)
        scores[key] = (green, cost, 1 - det, 1 - race, 1 - inflaky)
        print("  %-32s %7.1f%% %9.1f %9.1f%% %9.1f%% %9.1f%%" % (
            label, 100 * green, cost, 100 * (1 - det), 100 * (1 - race), 100 * (1 - inflaky)))
    print("  'caught' = the change was blocked and never merged.")
    print("  a deterministic regression survives nothing: every response catches it 100%.")
    print("  read the RACE column instead -- that is what retries silently trade away.")
    print("  doing nothing catches the race %.0f%% of the time; auto-retrying the failed" % (
        100 * scores["none"][3]))
    print("  job catches it %.0f%%. Retrying until green is retrying until the race" % (
        100 * scores["retry-job"][3]))
    print("  hides, which is the definition of merging it.")
    print("  pressing re-run costs %.1f job-runs per pipeline (%.2fx compute) to buy" % (
        scores["rerun-all"][1], scores["rerun-all"][1] / scores["none"][1]))
    print("  %.0f%% green; quarantine buys %.0f%% green for %.2fx compute and keeps" % (
        100 * scores["rerun-all"][0], 100 * scores["quarantine"][0],
        scores["quarantine"][1] / scores["none"][1]))
    print("  %.0f%% race detection. Its honest cost is the last column: a REAL bug" % (
        100 * scores["quarantine"][3]))
    print("  inside the quarantined job is caught %.1f%% of the time -- and those are" % (
        100 * scores["quarantine"][4]))
    print("  reds from unrelated jobs, not from the bug. Quarantine needs an owner")
    print("  and a deadline, not a skip decorator and a shrug.")

    # ---------------------------------------------------------------- section 5
    banner(5, "BUILD ONCE, PROMOTE THE SAME DIGEST")
    digest = artifact_digest(WORKSPACE)
    print("  built ONCE on commit. build-image cache key %s == this artifact:" % cold["keys"]["build-image"])
    print("  artifact digest: %s" % digest)
    print()
    print("  %-9s %-26s %-18s %-18s %s" % ("ENV", "ARTIFACT DIGEST", "CONFIG HASH", "RELEASE ID", "GATE"))
    gates = {"dev": "auto on merge", "staging": "auto, smoke tests",
             "prod": "manual approval"}
    releases = []
    for env, cfg in ENV_CONFIG.items():
        ch = config_hash(cfg)
        rid = release_id(digest, ch)
        releases.append(rid)
        print("  %-9s %-26s %-18s %-18s %s" % (env, digest[:26], ch[:16], rid, gates[env]))
    print("  1 artifact digest, %d distinct release ids. Only the config moved." % len(set(releases)))
    print("  the bytes that passed integration-tests are the bytes serving production.")
    print()
    print("  THE ANTI-PATTERN -- a 'build' step inside each environment's job:")
    print("  %-9s %-52s %s" % ("ENV", "ARTIFACT DIGEST", "MATCHES TESTED?"))
    rebuilt = []
    for i, env in enumerate(ENV_CONFIG):
        d = artifact_digest(WORKSPACE, build_arg="ENV=%s" % env,
                            stamp="2026-07-18T09:%02d:00Z" % (12 + i * 7))
        rebuilt.append(d)
        print("  %-9s %-52s %s" % (env, d[:52], "yes" if d == digest else "NO"))
    print("  %d rebuilds, %d distinct digests, %d matching the artifact that was tested." % (
        len(rebuilt), len(set(rebuilt)), sum(1 for d in rebuilt if d == digest)))
    print("  a build arg and a timestamp were enough. So is a floating base tag, a")
    print("  transitive dependency that published a new patch, or a different runner")
    print("  image. Rebuilding per environment voids every test you ran: the thing")
    print("  you tested and the thing you shipped are provably different bytes.")


if __name__ == "__main__":
    main()
