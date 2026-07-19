#!/usr/bin/env python3
"""orchestrator.py -- a scheduler and a level-triggered control loop, from scratch.

Lesson: phases/10-infrastructure-and-deployment/07-orchestration-and-kubernetes/docs/en.md
Models what kube-scheduler and kube-controller-manager actually do: filter/score
placement under CPU and memory requests, taints and topology spread; then run
observe -> diff -> act forever until observed state equals declared state. Shows
why level-triggered beats edge-triggered, what a node failure costs when replicas
are bin-packed vs spread, and why a replica sits Pending.
Follows the Kubernetes scheduling model (kubernetes.io/docs/concepts/scheduling-eviction).

Standard library only, seeded, self-terminating:  python3 orchestrator.py
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

SEED = 7
STARTUP_TICKS = 2      # a scheduled replica needs 2 ticks before it is Running
MAX_OPS = 4            # creations the controller starts per tick (rate limit)

# ─── The model: nodes, a declared spec, and replicas ─────────────────────────
@dataclass
class Node:
    """One machine. cpu is in millicores (1000m = 1 core); mem in MiB."""
    name: str
    zone: str
    cpu: int = 4000
    mem: int = 8192
    taints: Tuple[str, ...] = ()
    ready: bool = True


@dataclass
class Spec:
    """Declared state. This is the whole input to the control loop."""
    name: str
    replicas: int
    cpu: int                              # request per replica, millicores
    mem: int                              # request per replica, MiB
    tolerations: Tuple[str, ...] = ()
    spread: Optional[str] = None          # None | "node" | "zone"
    max_skew: int = 1
    anti_affinity: bool = False           # hard: at most one replica per node


@dataclass
class Replica:
    name: str
    workload: str
    cpu: int
    mem: int
    node: Optional[str] = None
    state: str = "Pending"                # Pending | Starting | Running
    ready_at: int = 0
    reason: str = ""


class Cluster:
    """A node pool plus every replica currently assigned to it."""

    def __init__(self, nodes: Sequence[Node], startup: int = STARTUP_TICKS) -> None:
        self.nodes: Dict[str, Node] = {n.name: n for n in nodes}
        self.replicas: List[Replica] = []
        self.startup = startup
        self._seq = 0

    # -- capacity -------------------------------------------------------
    def free(self, name: str) -> Tuple[int, int]:
        n = self.nodes[name]
        cpu, mem = n.cpu, n.mem
        for r in self.replicas:
            if r.node == name:
                cpu -= r.cpu
                mem -= r.mem
        return cpu, mem

    def used(self, name: str) -> Tuple[int, int]:
        n = self.nodes[name]
        fc, fm = self.free(name)
        return n.cpu - fc, n.mem - fm

    # -- queries --------------------------------------------------------
    def owned(self, workload: str) -> List[Replica]:
        return [r for r in self.replicas if r.workload == workload]

    def running(self, workload: str) -> int:
        return sum(1 for r in self.replicas
                   if r.workload == workload and r.state == "Running")

    def on_node(self, node: str, workload: str) -> int:
        return sum(1 for r in self.replicas
                   if r.node == node and r.workload == workload)

    def on_zone(self, zone: str, workload: str) -> int:
        return sum(1 for r in self.replicas if r.workload == workload
                   and r.node is not None and self.nodes[r.node].zone == zone)

    def next_name(self, workload: str) -> str:
        self._seq += 1
        return "%s-%02d" % (workload, self._seq)

    # -- mutation -------------------------------------------------------
    def add_node(self, node: Node) -> None:
        self.nodes[node.name] = node

    def fail_node(self, name: str) -> int:
        """The machine dies. Its replicas are gone; nobody was told."""
        self.nodes[name].ready = False
        lost = [r for r in self.replicas if r.node == name]
        self.replicas = [r for r in self.replicas if r.node != name]
        return len(lost)


# ─── The scheduler: filter, then score ───────────────────────────────────────
def _domains(cluster: Cluster, spec: Spec, key: str) -> List[str]:
    """Topology domains that are candidates at all (Ready + taints tolerated)."""
    out = []
    for n in sorted(cluster.nodes.values(), key=lambda x: x.name):
        if not n.ready:
            continue
        if any(t not in spec.tolerations for t in n.taints):
            continue
        out.append(n.name if key == "node" else n.zone)
    return sorted(set(out))


def schedule(cluster: Cluster, spec: Spec, strategy: str) -> Tuple[Optional[str], str]:
    """Return (node, reason). Reason is kubectl-shaped when nothing fits."""
    fails: Dict[str, int] = {}

    def note(msg: str) -> None:
        fails[msg] = fails.get(msg, 0) + 1

    doms = _domains(cluster, spec, spec.spread or "node")
    feasible: List[Node] = []

    for n in sorted(cluster.nodes.values(), key=lambda x: x.name):
        if not n.ready:
            note("node(s) were not Ready")
            continue
        bad = [t for t in n.taints if t not in spec.tolerations]
        if bad:
            note("node(s) had untolerated taint {%s}" % bad[0])
            continue
        fc, fm = cluster.free(n.name)
        if fc < spec.cpu:
            note("Insufficient cpu")
            continue
        if fm < spec.mem:
            note("Insufficient memory")
            continue
        if spec.anti_affinity and cluster.on_node(n.name, spec.name) >= 1:
            note("node(s) didn't match pod anti-affinity rules")
            continue
        if spec.spread:
            if spec.spread == "node":
                here = cluster.on_node(n.name, spec.name)
                low = min(cluster.on_node(d, spec.name) for d in doms) if doms else 0
            else:
                here = cluster.on_zone(n.zone, spec.name)
                low = min(cluster.on_zone(d, spec.name) for d in doms) if doms else 0
            if (here + 1) - low > spec.max_skew:
                note("node(s) didn't match topology spread constraint")
                continue
        feasible.append(n)

    if not feasible:
        detail = ", ".join("%d %s" % (c, m) for m, c in fails.items())
        return None, "0/%d nodes are available: %s." % (len(cluster.nodes), detail)

    if strategy == "binpack":                      # MostAllocated: fill a node up
        pick = min(feasible, key=lambda n: (cluster.free(n.name)[0] - spec.cpu, n.name))
    else:                                          # LeastAllocated: k8s default
        pick = max(feasible, key=lambda n: (cluster.free(n.name)[0], -ord(n.name[-1])))
    return pick.name, "scheduled"


# ─── The control loop: observe -> diff -> act ────────────────────────────────
def advance(cluster: Cluster, tick: int) -> None:
    """Time passes: Starting replicas that have finished booting become Running."""
    for r in cluster.replicas:
        if r.state == "Starting" and tick >= r.ready_at:
            r.state = "Running"


def reconcile(cluster: Cluster, spec: Spec, tick: int, strategy: str,
              max_ops: int = MAX_OPS) -> str:
    """One pass of the loop. Returns a human-readable action string."""
    owned = cluster.owned(spec.name)                       # 1. OBSERVE
    diff = spec.replicas - len(owned)                      # 2. DIFF
    acts: List[str] = []

    if diff > 0:                                           # 3. ACT: create
        for _ in range(min(diff, max_ops)):
            r = Replica(cluster.next_name(spec.name), spec.name, spec.cpu, spec.mem)
            node, why = schedule(cluster, spec, strategy)
            if node:
                r.node, r.state, r.ready_at = node, "Starting", tick + cluster.startup
                acts.append("+%s->%s" % (r.name, node))
            else:
                r.reason = why
                acts.append("+%s->Pending" % r.name)
            cluster.replicas.append(r)
    elif diff < 0:                                         # 3. ACT: delete surplus
        doomed = sorted(owned, key=lambda r: r.name)[diff:]
        for r in doomed:
            cluster.replicas.remove(r)
            acts.append("-%s" % r.name)

    for r in cluster.owned(spec.name):                     # retry every Pending, always
        if r.state == "Pending":
            node, why = schedule(cluster, spec, strategy)
            if node:
                r.node, r.state, r.ready_at = node, "Starting", tick + cluster.startup
                r.reason = ""
                acts.append("~%s->%s" % (r.name, node))
            else:
                r.reason = why
    return " ".join(acts) if acts else "-"


# ─── Reporting helpers ───────────────────────────────────────────────────────
def bar(used: int, total: int, width: int = 12) -> str:
    filled = int(round(width * used / total)) if total else 0
    return "[" + "#" * filled + "." * (width - filled) + "]"


def placement_table(cluster: Cluster, workload: str, indent: str = "  ") -> None:
    print(indent + "node     zone   replicas  cpu used/total       mem used/total")
    for name in sorted(cluster.nodes):
        n = cluster.nodes[name]
        uc, um = cluster.used(name)
        tag = "" if n.ready else "  NotReady"
        if n.taints:
            tag += "  taint=%s:NoSchedule" % n.taints[0]
        print("%s%-8s %-5s  %6d    %s %4d/%4dm  %s %5d/%5dMi%s"
              % (indent, name, n.zone, cluster.on_node(name, workload),
                 bar(uc, n.cpu), uc, n.cpu, bar(um, n.mem), um, n.mem, tag))


def state_counts(cluster: Cluster, workload: str) -> Tuple[int, int, int]:
    owned = cluster.owned(workload)
    return (sum(1 for r in owned if r.state == "Running"),
            sum(1 for r in owned if r.state == "Starting"),
            sum(1 for r in owned if r.state == "Pending"))


# ─── 1 · DESIRED STATE AND A SCHEDULER ───────────────────────────────────────
def pool() -> List[Node]:
    """Six machines, three availability zones, deliberately uneven — as real ones are."""
    return [Node("node-a", "zone-1"), Node("node-b", "zone-1"), Node("node-c", "zone-1"),
            Node("node-d", "zone-2"), Node("node-e", "zone-2"),
            Node("node-f", "zone-3")]


WEB = Spec("web", replicas=12, cpu=500, mem=512)


def section1() -> None:
    print("== 1 · DESIRED STATE AND A SCHEDULER ==")
    print("  declared: workload 'web', 12 replicas, each requesting 500m cpu / 512Mi mem")
    print("  pool: 6 nodes x 4000m cpu / 8192Mi mem  (zone-1: a,b,c  zone-2: d,e  zone-3: f)")
    print("  a node fits floor(4000/500) = 8 replicas on cpu, floor(8192/512) = 16 on mem")
    print("  -> cpu is the binding constraint. That is the whole of capacity planning.\n")

    for strategy, spec, label in (
        ("binpack", Spec("web", 12, 500, 512), "BIN-PACK   (MostAllocated: fill a node before opening another)"),
        ("spread", Spec("web", 12, 500, 512, spread="node"), "SPREAD     (LeastAllocated + topology spread, maxSkew=1)"),
        ("spread", Spec("web", 12, 500, 512, spread="zone"), "ZONE-SPREAD(LeastAllocated + spread over zones, maxSkew=1)"),
    ):
        c = Cluster(pool())
        for _ in range(spec.replicas):
            r = Replica(c.next_name(spec.name), spec.name, spec.cpu, spec.mem)
            node, why = schedule(c, spec, strategy)
            r.node, r.state = node, "Running" if node else "Pending"
            c.replicas.append(r)
        print("  %s" % label)
        placement_table(c, "web")
        occupied = sum(1 for n in c.nodes if c.on_node(n, "web") > 0)
        print("  -> 12 replicas on %d of 6 nodes; largest single node holds %d (%.0f%% of the fleet)\n"
              % (occupied, max(c.on_node(n, "web") for n in c.nodes),
                 100.0 * max(c.on_node(n, "web") for n in c.nodes) / 12))


# ─── 2 · THE CONTROL LOOP CONVERGES ──────────────────────────────────────────
def section2() -> None:
    print("== 2 · THE CONTROL LOOP CONVERGES: OBSERVE -> DIFF -> ACT -> REPEAT ==")
    print("  nobody calls 'create'. The loop reads declared state and closes the gap.")
    print("  controller starts at most %d replicas per tick; a replica needs %d ticks to boot.\n"
          % (MAX_OPS, STARTUP_TICKS))
    c = Cluster(pool())
    spec = Spec("web", 12, 500, 512, spread="node")
    print("  tick  observed(run/start/pend)  declared  diff  action")
    conv_up = conv_down = None
    for tick in range(1, 13):
        if tick == 8:
            spec.replicas = 8
            print("       ---- a human edits the declared replica count: 12 -> 8 ----")
        advance(c, tick)
        run, start, pend = state_counts(c, "web")
        diff = spec.replicas - len(c.owned("web"))
        act = reconcile(c, spec, tick, "spread")
        print("  %4d  %11d/%d/%d %11d  %+5d  %s"
              % (tick, run, start, pend, spec.replicas, diff, act))
        run2 = c.running("web")
        if conv_up is None and run2 == 12:
            conv_up = tick
        if conv_up is not None and conv_down is None and spec.replicas == 8 and run2 == 8:
            conv_down = tick
    print("  converged to 12 Running at tick %d; after the edit, converged to 8 at tick %d."
          % (conv_up, conv_down))
    print("  the loop scaled UP and DOWN with no scale-up or scale-down code path:")
    print("  both directions are the same subtraction, run again every tick.\n")


# ─── 3 · NODE FAILURE, RECOVERY, AND THE COST OF BIN-PACKING ─────────────────
def run_scenario(strategy: str, spec: Spec, kill: Sequence[str], kill_at: int,
                 ticks: int = 22, trace: bool = False,
                 nodes: Optional[Sequence[Node]] = None) -> Dict[str, object]:
    c = Cluster(list(nodes) if nodes else pool())
    hist: List[int] = []
    lost = 0
    at_kill = 0
    recovered: Optional[int] = None
    if trace:
        print("  tick  running  starting  pending  event / action")
    for tick in range(1, ticks + 1):
        advance(c, tick)
        event = ""
        if tick == kill_at:
            at_kill = c.running(spec.name)
            for name in kill:
                lost += c.fail_node(name)
            event = "!! %s LOST -- %d running replicas vanished  " % (
                "+".join(kill), lost)
        act = reconcile(c, spec, tick, strategy)
        run, start, pend = state_counts(c, spec.name)
        hist.append(run)
        if tick > kill_at and recovered is None and run == spec.replicas:
            recovered = tick
        if trace:
            print("  %4d  %7d  %8d  %7d  %s%s" % (tick, run, start, pend, event, act))
    deficit = sum(max(0, spec.replicas - r) for r in hist[kill_at - 1:])
    return {"lost": lost, "at_kill": at_kill, "recovered": recovered,
            "kill_at": kill_at, "deficit": deficit, "history": hist, "cluster": c}


def section3() -> None:
    print("== 3 · A NODE DIES AT 02:00. THE LOOP DOES NOT NEED TO BE TOLD ==")
    print("  12 spread replicas; node-a is destroyed at tick 6. Nobody is paged.\n")
    r = run_scenario("spread", Spec("web", 12, 500, 512, spread="node"),
                     ["node-a"], kill_at=6, ticks=11, trace=True)
    print("  time-to-recovery: %d ticks (lost at tick %d, back to 12 Running at tick %d)."
          % (r["recovered"] - r["kill_at"], r["kill_at"], r["recovered"]))
    print("  no human, no alert, no runbook. The next observation simply disagreed")
    print("  with the declared state, and the loop closed the gap.\n")

    print("  ---- the SAME node failure under three placement strategies ----")
    print("  strategy      worst node   node-a died: lost   capacity lost   recovery   deficit")
    print("                (replicas)                                        (ticks)   (rep-ticks)")
    rows = []
    for strategy, spec, label in (
        ("binpack", Spec("web", 12, 500, 512), "bin-packed"),
        ("spread", Spec("web", 12, 500, 512, spread="node"), "node-spread"),
        ("spread", Spec("web", 12, 500, 512, spread="zone"), "zone-spread"),
    ):
        res = run_scenario(strategy, spec, ["node-a"], kill_at=6)
        c0 = Cluster(pool())
        for _ in range(12):
            rr = Replica(c0.next_name(spec.name), spec.name, spec.cpu, spec.mem)
            n, _w = schedule(c0, spec, strategy)
            rr.node, rr.state = n, "Running"
            c0.replicas.append(rr)
        mx = max(c0.on_node(n, "web") for n in c0.nodes)
        pct = 100.0 * res["lost"] / 12
        print("  %-12s  %6d (%2.0f%%)  %17d   %12.1f%%  %9d   %8d"
              % (label, mx, 100.0 * mx / 12, res["lost"], pct,
                 res["recovered"] - res["kill_at"], res["deficit"]))
        rows.append((label, res, pct))
    print("  bin-packing lost %.1f%% of serving capacity to one machine dying;"
          % rows[0][2])
    print("  spreading lost %.1f%%. Same failure, same cluster, %.1fx the blast radius."
          % (rows[1][2], rows[0][2] / rows[1][2]))
    print("  'deficit' integrates the shortfall over time: %d vs %d replica-ticks (%.1fx).\n"
          % (rows[0][1]["deficit"], rows[1][1]["deficit"],
             rows[0][1]["deficit"] / rows[1][1]["deficit"]))

    print("  ---- now a correlated failure: all of zone-1 (node-a + node-b + node-c) ----")
    print("  strategy      lost   capacity lost   recovery   time at ZERO capacity")
    for strategy, spec, label in (
        ("binpack", Spec("web", 12, 500, 512), "bin-packed"),
        ("spread", Spec("web", 12, 500, 512, spread="node"), "node-spread"),
        ("spread", Spec("web", 12, 500, 512, spread="zone"), "zone-spread"),
    ):
        res = run_scenario(strategy, spec, ["node-a", "node-b", "node-c"], kill_at=6)
        zeros = sum(1 for x in res["history"][res["kill_at"] - 1:] if x == 0)
        print("  %-12s  %4d   %12.1f%%  %9d   %10d ticks"
              % (label, res["lost"], 100.0 * res["lost"] / 12,
                 res["recovered"] - res["kill_at"], zeros))
    print("  spreading across NODES does not protect you from losing a ZONE.")
    print("  zone-1 holds 3 of 6 nodes, so node-spread put half the fleet in it.")
    print("  a failure domain is whatever fails together — pick the right one.\n")


# ─── 4 · LEVEL-TRIGGERED VS EDGE-TRIGGERED ───────────────────────────────────
def trial(mode: str, p_drop: float, rng: random.Random,
          ticks: int = 30, fails: Sequence[int] = (5, 11, 17)) -> Tuple[int, int]:
    """One run. Returns (final Running, events dropped)."""
    spec = Spec("web", 12, 500, 512, spread="node")
    c = Cluster(pool())
    victims = ["node-a", "node-d", "node-f"]
    believed = 0            # what the EDGE-triggered reconciler thinks exists
    dropped = 0
    for tick in range(1, ticks + 1):
        advance(c, tick)
        if tick in fails:
            gone = c.fail_node(victims[list(fails).index(tick)])
            delivered = rng.random() >= p_drop
            if delivered:
                believed -= gone
            else:
                dropped += 1

        if mode == "level":
            reconcile(c, spec, tick, "spread")
        else:
            # Edge-triggered: acts only on its own bookkeeping, never re-observes.
            want = spec.replicas - believed
            for _ in range(min(max(0, want), MAX_OPS)):
                r = Replica(c.next_name(spec.name), spec.name, spec.cpu, spec.mem)
                node, why = schedule(c, spec, "spread")
                if node:
                    r.node, r.state, r.ready_at = node, "Starting", tick + c.startup
                else:
                    r.reason = why
                c.replicas.append(r)
                believed += 1
    return c.running("web"), dropped


def section4() -> None:
    print("== 4 · LEVEL-TRIGGERED VS EDGE-TRIGGERED, WITH LOSSY EVENTS ==")
    print("  identical scenario: 12 replicas, 3 node failures (ticks 5, 11, 17), 30 ticks.")
    print("  the edge-triggered reconciler acts on delivered EVENTS and never re-reads")
    print("  the world. The level-triggered one ignores events and re-observes each tick.\n")
    print("  event loss   edge: converged   avg running   |   level: converged   avg running")
    for p in (0.0, 0.1, 0.2, 0.5):
        rows = []
        for mode in ("edge", "level"):
            ok = 0
            tot = 0
            for run in range(10):
                rng = random.Random(SEED * 1000 + run)   # same draws for both modes
                final, _d = trial(mode, p, rng)
                tot += final
                ok += (final == 12)
            rows.append((ok, tot / 10.0))
        print("  %8.0f%%   %8d of 10   %11.1f   |   %10d of 10   %11.1f"
              % (p * 100, rows[0][0], rows[0][1], rows[1][0], rows[1][1]))
    print("  with 20%% event loss the edge-triggered reconciler converged in %d of 10 runs;"
          % sum(1 for run in range(10)
                if trial("edge", 0.2, random.Random(SEED * 1000 + run))[0] == 12))
    print("  the level-triggered one converged in 10 of 10 at every loss rate, including 50%.")
    print("  a missed event breaks an edge-triggered system PERMANENTLY: nothing later")
    print("  in the run ever re-derives the truth. A missed OBSERVATION costs one tick.\n")


# ─── 5 · PENDING IS A SCHEDULING OUTCOME, NOT AN ERROR ───────────────────────
def section5() -> None:
    print("== 5 · WHY A REPLICA IS 'PENDING' (AND WHY THAT IS NOT AN ERROR) ==")
    nodes = [Node("node-a", "zone-1", 4000, 8192),
             Node("node-b", "zone-1", 4000, 8192),
             Node("node-c", "zone-2", 4000, 8192, taints=("gpu=true",))]
    c = Cluster(nodes)
    web = Spec("web", 6, 1000, 1024)
    for _ in range(6):
        r = Replica(c.next_name("web"), "web", 1000, 1024)
        n, _w = schedule(c, web, "spread")
        r.node, r.state = n, "Running"
        c.replicas.append(r)
    print("  a 3-node cluster already running 6 'web' replicas at 1000m each:")
    placement_table(c, "web")

    batch = Spec("batch", 3, 2000, 2048)
    print("\n  now declare 'batch': 3 replicas, 2000m cpu / 2048Mi each, no toleration.")
    for tick in (1,):
        reconcile(c, batch, tick, "spread")
    for r in c.owned("batch"):
        print("  %-9s %-8s %s" % (r.name, r.state, r.reason or ("-> " + str(r.node))))
    print("  that string is what `kubectl describe pod` prints in its Events section.")
    print("  Pending means the scheduler ran, found no feasible node, and will retry.")
    print("  Nothing crashed. Nothing is retried in a back-off loop. It is a QUEUE.\n")

    print("  add node-d (4000m / 8192Mi) and run one more tick:")
    c.add_node(Node("node-d", "zone-2", 4000, 8192))
    reconcile(c, batch, 2, "spread")
    for r in c.owned("batch"):
        print("  %-9s %-8s %s" % (r.name, r.state, r.reason or ("-> " + str(r.node))))
    print("  two fit (2 x 2000m = 4000m, exactly full). The third still cannot.")
    print("  add node-e and it schedules — the loop never stopped trying:")
    c.add_node(Node("node-e", "zone-2", 4000, 8192))
    reconcile(c, batch, 3, "spread")
    for r in c.owned("batch"):
        print("  %-9s %-8s %s" % (r.name, r.state, r.reason or ("-> " + str(r.node))))

    print("\n  a second cause, same symptom: hard anti-affinity with too few nodes.")
    c2 = Cluster([Node("node-a", "zone-1"), Node("node-b", "zone-1"),
                  Node("node-c", "zone-2")])
    cache = Spec("cache", 4, 250, 256, anti_affinity=True)
    reconcile(c2, cache, 1, "spread")
    for r in c2.owned("cache"):
        print("  %-9s %-8s %s" % (r.name, r.state, r.reason or ("-> " + str(r.node))))
    print("  the cluster has 10250m of free cpu and the replica wants 250m.")
    print("  Capacity was never the problem. A CONSTRAINT was. Read the reason string.\n")


def main() -> None:
    t0 = time.perf_counter()
    section1()
    section2()
    section3()
    section4()
    section5()
    print("  (total wall time %.1f s, seed=%d, fully deterministic)"
          % (time.perf_counter() - t0, SEED))


if __name__ == "__main__":
    main()
