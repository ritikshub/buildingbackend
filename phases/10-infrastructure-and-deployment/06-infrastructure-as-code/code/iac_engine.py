#!/usr/bin/env python3
"""
iac_engine.py - a miniature infrastructure-as-code engine.

Lesson: phases/10-infrastructure-and-deployment/06-infrastructure-as-code/docs/en.md
Models the whole loop against a fake in-memory cloud: a desired-state
declaration, a state file (address -> real id), plan, apply, a dependency DAG,
update-vs-replace cascades, lifecycle guards and drift. No network, no
credentials, stdlib only, seeded, self-terminating.
Plan verbs (+ / ~ / -/+ / -), the "N to add, N to change, N to destroy" summary
and the state model (version + serial + lineage + resource->id mapping) follow
HashiCorp's documented Terraform CLI output and state format.
Provisioning DURATIONS in section 3 are MODELLED, not measured - see PROVISION_S.
"""

from __future__ import annotations

import copy
import json
import random
import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# schema: what the fake provider knows about each resource type
# ---------------------------------------------------------------------------

# Attributes that CANNOT be changed on a live resource. Changing one forces the
# provider to destroy the old object and create a new one: "-/+ replace".
IMMUTABLE: dict[str, set[str]] = {
    "network": {"cidr", "region"},
    "subnet": {"network_id", "cidr", "zone"},
    "server": {"subnet_id", "zone", "image"},
    "database": {"subnet_id", "engine"},
    "lb": set(),  # everything on a load balancer can be changed in place
}

ID_PREFIX = {"network": "net", "subnet": "sub", "server": "srv",
             "database": "db", "lb": "lb"}

# MODELLED wall-clock cost of provisioning each type, in seconds. These are not
# measured here - nothing is really created. They are plausible cloud numbers
# used to show what the DAG buys you.
PROVISION_S = {"network": 3.0, "subnet": 2.0, "server": 25.0,
               "database": 240.0, "lb": 45.0}

UNKNOWN = "(known after apply)"
REF = re.compile(r"^\$\{([a-z_]+\.[a-z0-9_]+)\.([a-z_]+)\}$")

CREATE, UPDATE, REPLACE, DELETE, NOOP = "create", "update", "replace", "destroy", "noop"
VERB = {CREATE: "+", UPDATE: "~", REPLACE: "-/+", DELETE: "-", NOOP: " "}


@dataclass(frozen=True)
class Res:
    """One declared resource block. `attrs` may contain "${type.name.attr}"."""
    type: str
    name: str
    attrs: dict
    prevent_destroy: bool = False

    @property
    def addr(self) -> str:
        return f"{self.type}.{self.name}"


# ---------------------------------------------------------------------------
# the fake cloud: an API that hands out opaque ids and forgets who asked
# ---------------------------------------------------------------------------

class Cloud:
    """An in-memory cloud. It knows objects by id and nothing about your code."""

    def __init__(self, seed: int = 7) -> None:
        self.rng = random.Random(seed)
        self.objects: dict[str, dict] = {}
        self.calls = {"create": 0, "update": 0, "delete": 0, "read": 0}

    def _new_id(self, type_: str) -> str:
        return f"{ID_PREFIX[type_]}-{self.rng.randrange(16 ** 6):06x}"

    def create(self, type_: str, attrs: dict) -> str:
        self.calls["create"] += 1
        rid = self._new_id(type_)
        self.objects[rid] = {"type": type_, "attrs": dict(attrs)}
        return rid

    def update(self, rid: str, attrs: dict) -> None:
        self.calls["update"] += 1
        self.objects[rid]["attrs"].update(attrs)

    def delete(self, rid: str) -> None:
        self.calls["delete"] += 1
        self.objects.pop(rid, None)

    def read(self, rid: str) -> dict | None:
        self.calls["read"] += 1
        obj = self.objects.get(rid)
        return dict(obj["attrs"]) if obj else None

    def list(self, type_: str) -> list[str]:
        return sorted(k for k, v in self.objects.items() if v["type"] == type_)


# ---------------------------------------------------------------------------
# the state file: the recorded mapping from your declarations to real ids
# ---------------------------------------------------------------------------

@dataclass
class State:
    version: int = 4
    serial: int = 0
    lineage: str = "7f0c1e2a-3b4d-4e5f-8a91-0d2c4b6e8f00"
    resources: dict[str, dict] = field(default_factory=dict)  # addr -> {id, attrs}

    def ids(self) -> dict[str, str]:
        return {a: r["id"] for a, r in self.resources.items()}

    def render_map(self) -> str:
        """The part that matters: your address -> the cloud's opaque id."""
        rows = "\n".join(f'    "{a}"{" " * (16 - len(a))} -> "{r["id"]}"'
                         for a, r in sorted(self.resources.items()))
        return (f'{{\n  "version": {self.version},  "serial": {self.serial},'
                f'  "lineage": "{self.lineage}",\n  "resources": {{\n{rows}\n  }}\n}}')

    def render_one(self, addr: str, redact: bool = True) -> str:
        r = self.resources[addr]
        body = {"id": r["id"], "attributes": _mask(r["attrs"]) if redact else r["attrs"]}
        return json.dumps({addr: body}, indent=2)


def _mask(attrs: dict) -> dict:
    return {k: ("***" if "password" in k or "secret" in k else v) for k, v in attrs.items()}


# ---------------------------------------------------------------------------
# graph
# ---------------------------------------------------------------------------

def deps_of(res: Res) -> set[str]:
    out: set[str] = set()
    for value in res.attrs.values():
        for item in (value if isinstance(value, list) else [value]):
            if isinstance(item, str):
                m = REF.match(item)
                if m:
                    out.add(m.group(1))
    return out


def build_graph(decl: list[Res]) -> dict[str, set[str]]:
    return {r.addr: deps_of(r) for r in decl}


def find_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    """Depth-first search; returns the cycle as a path, or None."""
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {n: WHITE for n in graph}
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        colour[node] = GREY
        stack.append(node)
        for dep in sorted(graph.get(node, ())):
            if dep not in colour:
                continue
            if colour[dep] == GREY:
                return stack[stack.index(dep):] + [dep]
            if colour[dep] == WHITE:
                found = visit(dep)
                if found:
                    return found
        stack.pop()
        colour[node] = BLACK
        return None

    for n in sorted(graph):
        if colour[n] == WHITE:
            found = visit(n)
            if found:
                return found
    return None


def topo_waves(graph: dict[str, set[str]]) -> list[list[str]]:
    """Group nodes into waves; every node in a wave may run concurrently."""
    remaining = {n: set(d for d in deps if d in graph) for n, deps in graph.items()}
    waves: list[list[str]] = []
    done: set[str] = set()
    while remaining:
        ready = sorted(n for n, d in remaining.items() if not (d - done))
        if not ready:
            raise ValueError("cycle")
        waves.append(ready)
        done |= set(ready)
        for n in ready:
            remaining.pop(n)
    return waves


def schedule(graph: dict[str, set[str]], kinds: dict[str, str]) -> dict[str, tuple[float, float]]:
    """Earliest-start schedule: a node starts when its own deps finish."""
    finish: dict[str, tuple[float, float]] = {}
    for wave in topo_waves(graph):
        for node in wave:
            start = max((finish[d][1] for d in graph[node] if d in finish), default=0.0)
            finish[node] = (start, start + PROVISION_S[kinds[node]])
    return finish


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------

@dataclass
class Change:
    addr: str
    action: str
    diffs: dict            # attr -> (before, after)
    forces: list[str]      # immutable attrs that force replacement
    reason: str = ""


def resolve(res: Res, ids: dict[str, str], unknown: set[str]):
    """Interpolate "${addr.attr}" against known ids; unknown ids stay unknown."""
    def one(item):
        if isinstance(item, str):
            m = REF.match(item)
            if m:
                addr = m.group(1)
                if addr in unknown or addr not in ids:
                    return UNKNOWN
                return ids[addr]
        return item

    return {k: ([one(i) for i in v] if isinstance(v, list) else one(v))
            for k, v in res.attrs.items()}


def make_plan(decl: list[Res], state: State, cloud: Cloud) -> list[Change]:
    """Refresh, diff, then propagate replacement through the graph to a fixpoint."""
    actual = {a: cloud.read(r["id"]) for a, r in state.resources.items()}
    ids = state.ids()
    by_addr = {r.addr: r for r in decl}
    unknown: set[str] = set()

    changes: dict[str, Change] = {}
    for _ in range(12):
        changes = {}
        for res in decl:
            cur = actual.get(res.addr)
            if cur is None:
                reason = ("" if res.addr not in state.resources
                          else "in state, but gone from the cloud")
                changes[res.addr] = Change(res.addr, CREATE, {}, [], reason)
                continue
            want = resolve(res, ids, unknown)
            diffs = {k: (cur.get(k), want[k]) for k in want if cur.get(k) != want[k]}
            forces = sorted(k for k in diffs if k in IMMUTABLE[res.type])
            action = REPLACE if forces else (UPDATE if diffs else NOOP)
            changes[res.addr] = Change(res.addr, action, diffs, forces)
        fresh = {a for a, c in changes.items() if c.action in (CREATE, REPLACE)}
        if fresh == unknown:
            break
        unknown = fresh

    for addr in state.resources:
        if addr not in by_addr:
            changes[addr] = Change(addr, DELETE, {}, [], "removed from the declaration")

    order = [a for wave in topo_waves(build_graph(decl)) for a in wave]
    rank = {a: i for i, a in enumerate(order)}
    return sorted((c for c in changes.values() if c.action != NOOP),
                  key=lambda c: (rank.get(c.addr, 10 ** 6), c.addr))


def summary(changes: list[Change]) -> tuple[int, int, int]:
    add = sum(1 for c in changes if c.action in (CREATE, REPLACE))
    chg = sum(1 for c in changes if c.action == UPDATE)
    dele = sum(1 for c in changes if c.action in (DELETE, REPLACE))
    return add, chg, dele


def fmt(v) -> str:
    if isinstance(v, list):
        return "[" + ", ".join(fmt(i) for i in v) + "]"
    if v == UNKNOWN:
        return UNKNOWN
    return json.dumps(v)


def render_plan(changes: list[Change], indent: str = "  ", max_diffs: int = 4) -> None:
    if not changes:
        print(f"{indent}No changes. Your infrastructure matches the configuration.")
        print(f"{indent}Plan: 0 to add, 0 to change, 0 to destroy.")
        return
    for c in changes:
        tail = f"   # {c.reason}" if c.reason else ""
        print(f"{indent}{VERB[c.action]:>3} {c.action:<7} {c.addr}{tail}")
        for i, (k, (before, after)) in enumerate(sorted(c.diffs.items())):
            if i >= max_diffs:
                print(f"{indent}        ... {len(c.diffs) - max_diffs} more attribute(s)")
                break
            mark = "  # forces replacement" if k in c.forces else ""
            print(f"{indent}        {k}: {fmt(before)} -> {fmt(after)}{mark}")
    add, chg, dele = summary(changes)
    print(f"{indent}Plan: {add} to add, {chg} to change, {dele} to destroy.")


def render_apply_order(changes: list[Change], state: State, cbd: bool,
                       indent: str = "        ") -> float:
    """Print the operation sequence for a plan; return the modelled outage gap."""
    gap = 0.0
    step = 0
    ops: list[tuple[str, str]] = []
    for c in changes:
        if c.action == REPLACE:
            rid = state.resources[c.addr]["id"]
            kind = c.addr.split(".")[0]
            if cbd:
                ops.append((f"create  {c.addr}", "new object, new id"))
            else:
                ops.append((f"destroy {c.addr} ({rid})", "the old object is gone NOW"))
                ops.append((f"create  {c.addr}",
                            f"~{PROVISION_S[kind]:.0f}s of zero capacity here (modelled)"))
                gap += PROVISION_S[kind]
    for c in changes:
        if c.action == UPDATE:
            ops.append((f"update  {c.addr}", "references repointed at the new id"))
    if cbd:
        for c in changes:
            if c.action == REPLACE:
                ops.append((f"destroy {c.addr} ({state.resources[c.addr]['id']})",
                            "only after the replacement is serving"))
    for what, why in ops:
        step += 1
        print(f"{indent}{step}. {what:<38} <- {why}")
    return gap


class GuardError(Exception):
    pass


def check_guards(changes: list[Change], decl: list[Res]) -> None:
    guarded = {r.addr for r in decl if r.prevent_destroy}
    for c in changes:
        if c.action in (REPLACE, DELETE) and c.addr in guarded:
            raise GuardError(
                f"Instance cannot be destroyed: resource {c.addr} has\n"
                f"      lifecycle.prevent_destroy set, but the plan calls for it to be "
                f"{'replaced' if c.action == REPLACE else 'destroyed'}."
            )


def apply(changes: list[Change], decl: list[Res], state: State, cloud: Cloud) -> None:
    """Creates/updates in dependency order; destroys in REVERSE order."""
    check_guards(changes, decl)
    by_addr = {r.addr: r for r in decl}
    for c in reversed(changes):
        if c.action == DELETE:
            cloud.delete(state.resources[c.addr]["id"])
            del state.resources[c.addr]
    for c in changes:
        if c.action == DELETE:
            continue
        res = by_addr[c.addr]
        want = resolve(res, state.ids(), set())
        if c.action == REPLACE:
            cloud.delete(state.resources[c.addr]["id"])   # destroy, then create
            state.resources.pop(c.addr)
        if c.action in (CREATE, REPLACE):
            rid = cloud.create(res.type, want)
            state.resources[c.addr] = {"id": rid, "attrs": want}
        else:
            rid = state.resources[c.addr]["id"]
            cloud.update(rid, want)
            state.resources[c.addr]["attrs"] = want
    state.serial += 1


def drift_report(state: State, cloud: Cloud) -> tuple[dict[str, dict], list[str], list[str]]:
    """actual vs RECORDED: what the console did behind the tool's back."""
    changed: dict[str, dict] = {}
    vanished: list[str] = []
    for addr, rec in sorted(state.resources.items()):
        live = cloud.read(rec["id"])
        if live is None:
            vanished.append(addr)
            continue
        delta = {k: (rec["attrs"].get(k), live.get(k))
                 for k in set(rec["attrs"]) | set(live)
                 if rec["attrs"].get(k) != live.get(k)}
        if delta:
            changed[addr] = delta
    managed = set(state.ids().values())
    unmanaged = sorted(rid for rid in cloud.objects if rid not in managed)
    return changed, vanished, unmanaged


# ---------------------------------------------------------------------------
# the declaration under test
# ---------------------------------------------------------------------------

def declaration() -> list[Res]:
    return [
        Res("network", "core",
            {"cidr": "10.0.0.0/16", "region": "eu-west-1", "tags": "prod"}),
        Res("subnet", "app_a",
            {"network_id": "${network.core.id}", "cidr": "10.0.1.0/24",
             "zone": "eu-west-1a"}),
        Res("subnet", "app_b",
            {"network_id": "${network.core.id}", "cidr": "10.0.2.0/24",
             "zone": "eu-west-1b"}),
        Res("server", "api_1",
            {"subnet_id": "${subnet.app_a.id}", "zone": "eu-west-1a",
             "image": "api:1.4.2", "size": "c6i.large", "tags": "prod"}),
        Res("server", "api_2",
            {"subnet_id": "${subnet.app_b.id}", "zone": "eu-west-1b",
             "image": "api:1.4.2", "size": "c6i.large", "tags": "prod"}),
        Res("database", "main",
            {"subnet_id": "${subnet.app_a.id}", "engine": "postgres-16",
             "storage_gb": 100, "password": "hunter2-prod",
             "backup_window": "03:00-04:00"},
            prevent_destroy=True),
        Res("lb", "public",
            {"targets": ["${server.api_1.id}", "${server.api_2.id}"],
             "listener_port": 443, "idle_timeout_s": 60}),
    ]


def edit(decl: list[Res], addr: str, **changes) -> list[Res]:
    """Return a copy of the declaration with one resource's attrs changed."""
    out = []
    for r in decl:
        if r.addr == addr:
            out.append(Res(r.type, r.name, {**r.attrs, **changes}, r.prevent_destroy))
        else:
            out.append(r)
    return out


def head(n: int, title: str) -> None:
    print(f"\n== {n} · {title} ==")


# ---------------------------------------------------------------------------
# 1 · declare, plan, apply
# ---------------------------------------------------------------------------

def section_1(decl: list[Res], state: State, cloud: Cloud) -> list[Change]:
    head(1, "DECLARE, PLAN, APPLY")
    print("  the declaration: 7 resources, one network, two subnets, two servers,")
    print("  one database, one load balancer. Nothing exists yet.\n")
    changes = make_plan(decl, state, cloud)
    render_plan(changes)
    apply(changes, decl, state, cloud)
    print(f"\n  applied. cloud API calls: create={cloud.calls['create']} "
          f"update={cloud.calls['update']} delete={cloud.calls['delete']}")
    print("  the state file - the mapping the tool cannot rebuild without:")
    for line in state.render_map().splitlines():
        print("    " + line)
    print("\n  each entry also records every attribute as applied. One entry in full:")
    for line in state.render_one("database.main").splitlines():
        print("    " + line)
    secret = state.resources["database.main"]["attrs"]["password"]
    print(f"  the password is masked above for the page. On disk that field is the")
    print(f"  literal string {secret!r}. State files hold every attribute of every")
    print("  resource, in plaintext, including the ones marked sensitive in the config.")
    return changes


# ---------------------------------------------------------------------------
# 2 · idempotence
# ---------------------------------------------------------------------------

def section_2(decl: list[Res], state: State, cloud: Cloud) -> None:
    head(2, "IDEMPOTENCE, PROVED: THE SECOND PLAN IS EMPTY")
    before = dict(cloud.calls)
    changes = make_plan(decl, state, cloud)
    render_plan(changes)
    reads = cloud.calls["read"] - before["read"]
    print(f"  the re-plan made {reads} read calls and 0 create/update/delete calls.")
    print("  a script would have run 7 create calls again. A declaration re-evaluates")
    print("  to the same 0/0/0 for as long as reality matches it - which is what makes")
    print("  it safe to run on every merge, in CI, unattended.")


# ---------------------------------------------------------------------------
# 3 · the dependency graph
# ---------------------------------------------------------------------------

def section_3(decl: list[Res]) -> None:
    head(3, "THE DEPENDENCY GRAPH (modelled durations)")
    graph = build_graph(decl)
    kinds = {r.addr: r.type for r in decl}
    print("  edges - each one is a reference in the declaration, nothing declared by hand:")
    for addr in sorted(graph):
        if graph[addr]:
            print(f"    {addr:<16} depends on  {', '.join(sorted(graph[addr]))}")
        else:
            print(f"    {addr:<16} (root)")

    waves = topo_waves(graph)
    print("\n  topological order, grouped into waves that may run concurrently:")
    for i, wave in enumerate(waves, 1):
        print(f"    wave {i}: {', '.join(wave)}")

    sched = schedule(graph, kinds)
    serial = sum(PROVISION_S[kinds[a]] for a in graph)
    parallel = max(f for _, f in sched.values())
    print("\n  earliest-start schedule (provisioning times are MODELLED, not measured):")
    for addr in sorted(sched, key=lambda a: (sched[a][0], a)):
        s, f = sched[addr]
        conc = sorted(o for o in sched if o != addr and sched[o][0] < f and sched[o][1] > s)
        conc_s = ", ".join(conc) if conc else "-"
        print(f"    t={s:6.1f}s -> {f:6.1f}s  {addr:<16} runs alongside: "
              f"{conc_s if len(conc_s) < 46 else conc_s[:43] + '...'}")
    print(f"\n  one at a time: {serial:.0f}s.  Following the DAG: {parallel:.0f}s "
          f"({serial / parallel:.2f}x faster).")
    print("  the critical path is network.core -> subnet.app_a -> database.main")
    print(f"  ({parallel:.0f}s); every other resource finishes with time to spare.")
    print("  destroy runs the same order REVERSED, wave by wave:")
    for i, wave in enumerate(reversed(waves), 1):
        print(f"    step {i}: {', '.join(wave)}")

    print("\n  cycle detection - a declaration where two servers reference each other:")
    bad = [Res("server", "a", {"subnet_id": "${server.b.id}", "zone": "z"}),
           Res("server", "b", {"subnet_id": "${server.a.id}", "zone": "z"})]
    cycle = find_cycle(build_graph(bad))
    print(f"    Error: Cycle: {' -> '.join(cycle)}")
    print("    a DAG has no answer to 'which of these do I create first?', so the")
    print("    tool refuses to plan at all rather than guess.")


# ---------------------------------------------------------------------------
# 4 · update vs replace
# ---------------------------------------------------------------------------

def section_4(decl: list[Res], state: State, cloud: Cloud) -> None:
    head(4, "UPDATE vs REPLACE - THE VERB THAT DELETES DATABASES")

    print("  4a · change a MUTABLE attribute (a tag, an instance size):")
    d = edit(decl, "server.api_1", tags="prod,team-checkout", size="c6i.xlarge")
    s, c = copy.deepcopy(state), copy.deepcopy(cloud)
    p = make_plan(d, s, c)
    render_plan(p, indent="      ")
    old_id = s.resources["server.api_1"]["id"]
    apply(p, d, s, c)
    print(f"      id before {old_id} -> after {s.resources['server.api_1']['id']} "
          f"(unchanged: the machine was edited, not rebuilt)")

    print("\n  4b · change an IMMUTABLE attribute on ONE leaf server (its zone):")
    d = edit(decl, "server.api_2", zone="eu-west-1c")
    s, c = copy.deepcopy(state), copy.deepcopy(cloud)
    p = make_plan(d, s, c)
    render_plan(p, indent="      ")
    dragged = [ch.addr for ch in p if ch.addr != "server.api_2"]
    print(f"      1 attribute changed -> 1 resource replaced and {len(dragged)} dependent "
          f"dragged in: {', '.join(dragged)}")
    print("      the load balancer is UPDATED, not replaced, because its target list")
    print("      is a mutable attribute. That is the cascade stopping.")
    print("\n      the apply ORDER for a replace, default (destroy first):")
    gap = render_apply_order(p, s, cbd=False)
    print("      with lifecycle { create_before_destroy = true }:")
    render_apply_order(p, s, cbd=True)
    print(f"      the gap where the zone has no server: {gap:.0f}s -> 0s. The cost is that")
    print("      two objects exist at once - double capacity, and a name collision if any")
    print("      immutable attribute has to be globally unique.")
    print("      Now watch the cascade not stop.")

    print("\n  4c · change ONE immutable attribute on the ROOT of the graph (the CIDR):")
    d = edit(decl, "network.core", cidr="10.1.0.0/16")
    s, c = copy.deepcopy(state), copy.deepcopy(cloud)
    p = make_plan(d, s, c)
    render_plan(p, indent="      ", max_diffs=2)
    replaced = [ch.addr for ch in p if ch.action == REPLACE]
    updated = [ch.addr for ch in p if ch.action == UPDATE]
    print(f"\n      ONE edited attribute. {len(replaced)} of {len(decl)} resources are "
          f"REPLACED, {len(updated)} updated.")
    print(f"      replaced: {', '.join(replaced)}")
    print("      only network.core was edited. The other "
          f"{len(replaced) - 1} were dragged in transitively:")
    print("      an immutable attribute of each one is a reference to something being")
    print("      replaced, so its value is (known after apply) - a change, and a forcing one.")
    print("      database.main is in that list. Its data is in that list.")

    print("\n      the guard: database.main declares lifecycle { prevent_destroy = true }")
    try:
        apply(p, d, s, c)
        print("      apply succeeded - the database was destroyed and recreated.")
    except GuardError as exc:
        print(f"      Error: {exc}")
        print("      NOTHING was applied. The plan is refused as a whole, not partially.")
        print("      Without that one line, `apply` would have deleted 100 GB of data and")
        print("      created an empty database with a new id, and the plan output would")
        print("      have said so - on line 4 of 60, under a heading nobody read.")
    print(f"      cloud state untouched: {len(c.objects)} objects, "
          f"database id still {s.resources['database.main']['id']}")


# ---------------------------------------------------------------------------
# 5 · drift
# ---------------------------------------------------------------------------

def section_5(decl: list[Res], state: State, cloud: Cloud) -> None:
    head(5, "DRIFT: THE STATE FILE IS A CACHE OF REALITY, AND CACHES GO STALE")
    print("  four things happen in the console at 02:40 during an incident:")
    print("    1. someone re-tags server.api_1 to find it in the billing view")
    print("    2. someone widens the database backup window to run a manual dump")
    print("    3. someone deletes subnet.app_b, believing it is unused")
    print("    4. someone creates a subnet by hand to test a fix, and leaves it\n")

    cloud.update(state.resources["server.api_1"]["id"], {"tags": "DEBUG-do-not-delete"})
    cloud.update(state.resources["database.main"]["id"],
                 {"backup_window": "12:00-13:00"})
    cloud.delete(state.resources["subnet.app_b"]["id"])
    rogue = cloud.create("subnet", {"network_id": state.resources["network.core"]["id"],
                                    "cidr": "10.0.1.0/24", "zone": "eu-west-1a"})

    changed, vanished, unmanaged = drift_report(state, cloud)
    print("  drift report (what the cloud says, versus what the state file recorded):")
    for addr, delta in changed.items():
        for k, (was, now) in sorted(delta.items()):
            print(f"    ~ {addr:<16} {k}: recorded {fmt(was)} -> actual {fmt(now)}")
    for addr in vanished:
        print(f"    - {addr:<16} recorded id {state.resources[addr]['id']} "
              f"no longer exists in the cloud")
    drifted = len(changed) + len(vanished)
    print(f"    {drifted} of {len(state.resources)} managed resources have drifted "
          f"({sum(len(v) for v in changed.values())} attributes changed, "
          f"{len(vanished)} vanished).")

    print("\n  the next plan, after a refresh:")
    p = make_plan(decl, state, cloud)
    render_plan(p, indent="    ")
    corrections = [c.addr for c in p if c.action == UPDATE]
    recreations = [c.addr for c in p if c.action == CREATE]
    collateral = [c.addr for c in p if c.action == REPLACE]
    print(f"    corrected in place: {', '.join(corrections)}")
    print(f"    recreated after the out-of-band delete: {', '.join(recreations)}")
    print(f"    collateral - not touched by anyone, replaced anyway: "
          f"{', '.join(collateral) or 'none'}")
    print("    server.api_2 was healthy and unedited. It is being destroyed because the")
    print("    subnet it sits in will come back with a NEW id, and subnet_id is immutable.")

    print("\n  the second failure mode - a resource the state file has never heard of:")
    _, _, unmanaged = drift_report(state, cloud)
    print(f"    the cloud holds {len(cloud.objects)} objects. State holds "
          f"{len(state.resources)} mappings, one of which ({vanished[0]})")
    print("    points at an id that no longer exists.")
    print(f"    {len(unmanaged)} object is in the cloud and in NO state file: "
          f"{', '.join(unmanaged)}")
    subnets = cloud.list("subnet")
    print(f"    cloud.list('subnet') returns {len(subnets)}: {', '.join(subnets)}")
    twin = cloud.read(rogue)
    mine = state.resources["subnet.app_a"]["attrs"]
    same = all(twin.get(k) == mine.get(k) for k in ("network_id", "cidr", "zone"))
    print(f"    {rogue} and {state.resources['subnet.app_a']['id']} are identical in "
          f"every attribute: {same}")
    print("    (network_id, cidr and zone all match; only the id differs)")
    print("    THIS is why the tool cannot just ask the cloud every time. 'Which of these")
    print("    subnets is subnet.app_a?' has no answer in the cloud's own data. The state")
    print("    file is the only place the answer was ever written down.")
    print(f"    the plan above is silent about {rogue}: unmanaged means invisible, not")
    print("    deleted. `terraform import` writes the mapping in, and only then can the")
    print("    tool see it, plan against it, or destroy it.")


def main() -> None:
    cloud = Cloud(seed=7)
    state = State()
    decl = declaration()
    section_1(decl, state, cloud)
    section_2(decl, state, cloud)
    section_3(decl)
    section_4(decl, state, cloud)
    section_5(decl, state, cloud)
    print("\n  (no network calls, no credentials, no real resources: the cloud above is a "
          "dict)")


if __name__ == "__main__":
    main()
