"""
Physical Layer — model each network topology as a hand-built graph and measure it.

A topology is just *which node connects to which*. We build five of them (bus,
ring, star, full mesh, tree) as adjacency sets — no networkx, only the standard
library — then compute, by hand: link count, node degrees, single-point-of-
failure nodes/links (does one removal disconnect the network?), and the network
diameter (the worst-case hop distance between any two nodes).

Docs: phases/01-networking-and-protocols/02-physical-layer-topologies-cables-signals/docs/en.md
Spec: IEEE 802.3 (Ethernet star/switched LANs); graph terms per standard usage.

Run:
    python3 topologies.py
Builds every topology, prints per-topology metrics and a comparison table, exits 0.
"""

from __future__ import annotations

from collections import deque


# --- Building graphs by hand: an adjacency map {node: set(neighbours)} --------

def undirected(edges):
    """Turn a list of (u, v) links into an undirected adjacency map."""
    adj = {}
    for u, v in edges:
        adj.setdefault(u, set()).add(v)
        adj.setdefault(v, set()).add(u)
    return adj


def bus(hosts):
    # A shared backbone tapped in series: a break anywhere splits the cable,
    # so we model it as a linear chain where every link is load-bearing.
    return undirected([(hosts[i], hosts[i + 1]) for i in range(len(hosts) - 1)])


def ring(hosts):
    # Each node wired to the next, and the last back to the first (a cycle).
    edges = [(hosts[i], hosts[(i + 1) % len(hosts)]) for i in range(len(hosts))]
    return undirected(edges)


def star(hub, leaves):
    # Every leaf wired only to one central device (switch/hub).
    return undirected([(hub, leaf) for leaf in leaves])


def full_mesh(hosts):
    # Every node wired to every other node: n(n-1)/2 links.
    edges = []
    for i in range(len(hosts)):
        for j in range(i + 1, len(hosts)):
            edges.append((hosts[i], hosts[j]))
    return undirected(edges)


def tree(edges):
    # A hierarchy: stars of stars (core switch -> distribution -> hosts).
    return undirected(edges)


# --- Measuring graphs by hand -------------------------------------------------

def link_count(adj):
    """Each undirected link is counted twice in the adjacency map."""
    return sum(len(nbrs) for nbrs in adj.values()) // 2


def edge_set(adj):
    """Every link as a sorted (u, v) tuple, so each appears exactly once."""
    edges = set()
    for u, nbrs in adj.items():
        for v in nbrs:
            edges.add(tuple(sorted((u, v))))
    return edges


def degrees(adj):
    """Degree = how many links touch a node."""
    return {node: len(nbrs) for node, nbrs in adj.items()}


def reachable(adj, start, blocked_nodes=frozenset(), blocked_edge=None):
    """Breadth-first flood fill from `start`, skipping blocked nodes/one edge."""
    seen = {start}
    queue = deque([start])
    while queue:
        u = queue.popleft()
        for v in adj[u]:
            if v in blocked_nodes:
                continue
            if blocked_edge is not None and tuple(sorted((u, v))) == blocked_edge:
                continue
            if v not in seen:
                seen.add(v)
                queue.append(v)
    return seen


def is_connected(adj, blocked_nodes=frozenset(), blocked_edge=None):
    """True if every non-blocked node can still reach every other."""
    remaining = [n for n in adj if n not in blocked_nodes]
    if len(remaining) <= 1:
        return True
    reached = reachable(adj, remaining[0], blocked_nodes, blocked_edge)
    return set(remaining) <= reached


def spof_nodes(adj):
    """Nodes whose removal disconnects the rest — single points of failure."""
    return [n for n in sorted(adj) if not is_connected(adj, blocked_nodes=frozenset([n]))]


def bridge_links(adj):
    """Links whose removal disconnects the network."""
    return [e for e in sorted(edge_set(adj)) if not is_connected(adj, blocked_edge=e)]


def diameter(adj):
    """Longest shortest-path (in hops) between any pair; inf if disconnected."""
    worst = 0
    for source in adj:
        dist = {source: 0}
        queue = deque([source])
        while queue:
            u = queue.popleft()
            for v in adj[u]:
                if v not in dist:
                    dist[v] = dist[u] + 1
                    queue.append(v)
        if len(dist) < len(adj):
            return float("inf")
        worst = max(worst, max(dist.values()))
    return worst


# --- Report -------------------------------------------------------------------

def analyse(name, adj):
    n = len(adj)
    links = link_count(adj)
    deg = degrees(adj)
    spof = spof_nodes(adj)
    bridges = bridge_links(adj)
    dia = diameter(adj)

    print(f"{name}")
    print(f"  nodes ............... {n}")
    print(f"  links ............... {links}")
    deg_str = ", ".join(f"{node}:{d}" for node, d in sorted(deg.items()))
    print(f"  degree per node ..... {deg_str}")
    print(f"  single-point-of-failure node(s) ... "
          f"{', '.join(spof) if spof else 'NONE (survives any 1 node loss)'}")
    print(f"  survives any single link loss? .... "
          f"{'no — every link is critical' if len(bridges) == links and links else ('no' if bridges else 'YES')}")
    print(f"  network diameter (max hops) ....... {dia}")
    print()

    return {
        "name": name,
        "nodes": n,
        "links": links,
        "spof": "yes" if spof else "no",
        "one_link_kills": "yes" if bridges else "no",
        "diameter": dia,
    }


def comparison_table(rows):
    header = ("Topology", "Nodes", "Links", "SPOF node?", "1 link cut kills?", "Diameter")
    widths = [max(len(str(r[k])) for r in ([dict(zip(
        ["name", "nodes", "links", "spof", "one_link_kills", "diameter"], header))] + rows))
        for k in ["name", "nodes", "links", "spof", "one_link_kills", "diameter"]]

    def fmt(vals):
        return " | ".join(str(v).ljust(w) for v, w in zip(vals, widths))

    print("Comparison")
    print("  " + fmt(header))
    print("  " + "-+-".join("-" * w for w in widths))
    for r in rows:
        print("  " + fmt([r["name"], r["nodes"], r["links"], r["spof"],
                          r["one_link_kills"], r["diameter"]]))


def main():
    hosts5 = ["A", "B", "C", "D", "E"]
    tree_edges = [
        ("Core", "Dist1"), ("Core", "Dist2"),
        ("Dist1", "H1"), ("Dist1", "H2"),
        ("Dist2", "H3"), ("Dist2", "H4"),
    ]

    topologies = [
        ("Bus (chain of 5)", bus(hosts5)),
        ("Ring (cycle of 5)", ring(hosts5)),
        ("Star (hub SW + 5)", star("SW", hosts5)),
        ("Full mesh (5)", full_mesh(hosts5)),
        ("Tree (core+2+4)", tree(tree_edges)),
    ]

    rows = [analyse(name, adj) for name, adj in topologies]

    # Prove the full-mesh link formula n(n-1)/2 holds for our 5-node mesh.
    n = len(hosts5)
    expected = n * (n - 1) // 2
    got = link_count(full_mesh(hosts5))
    print(f"Full-mesh link formula: n(n-1)/2 = {n}*{n-1}/2 = {expected}; "
          f"measured = {got}  -> {'match' if expected == got else 'MISMATCH'}")
    print()

    comparison_table(rows)


if __name__ == "__main__":
    main()
