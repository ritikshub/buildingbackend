#!/usr/bin/env python3
"""
A mini property-graph database with index-free adjacency, built from scratch.

Companion to docs/en.md (Phase 04, Lesson 06 - Graph Databases). A graph
database makes RELATIONSHIPS first-class: an entity is a node, a connection is
a typed, directed edge, and both can carry properties. The defining
implementation trick is INDEX-FREE ADJACENCY -- each node holds direct
references (pointers) to its adjacent edges, so following a relationship is an
O(1) dereference instead of an index lookup or a join. A k-hop traversal then
costs O(nodes+edges actually visited), NOT O(total edges) re-scanned per hop.

To make that concrete, this file measures the same k-hop question two ways on
the same graph:
  * a graph BFS traversal (each node visited once, each edge followed once), and
  * the intermediate rows a naive k-way relational self-join would materialize
    (every walk, with multiplicity) -- the d^k blow-up from Lesson 1, Pressure 2.

Runs standalone on the Python standard library only:  python graphdb.py
"""

from __future__ import annotations
import random
from collections import deque


class Graph:
    """A labeled property graph: nodes with properties, typed+directed edges."""

    def __init__(self):
        self.nodes: dict = {}                 # id -> properties (includes 'label')
        # INDEX-FREE ADJACENCY: each node id maps directly to the list of its
        # outgoing edges. Following an edge is a list walk -- O(degree) -- with
        # NO global index lookup and NO join. This is the whole ballgame.
        self.out: dict = {}                   # id -> [(edge_type, dst_id, props), ...]
        self.inn: dict = {}                   # id -> [(edge_type, src_id, props), ...] (reverse)

    def add_node(self, node_id, label=None, **props):
        self.nodes[node_id] = {"label": label, **props}
        self.out.setdefault(node_id, [])
        self.inn.setdefault(node_id, [])

    def add_edge(self, src, dst, edge_type, **props):
        self.out.setdefault(src, []).append((edge_type, dst, props))
        self.inn.setdefault(dst, []).append((edge_type, src, props))

    def add_friendship(self, a, b):           # an undirected relationship = two directed edges
        self.add_edge(a, b, "FRIEND")
        self.add_edge(b, a, "FRIEND")

    def neighbors(self, node, edge_type=None):
        """Direct out-neighbors -- O(degree), a pointer walk, no index."""
        return [dst for (t, dst, _p) in self.out.get(node, ())
                if edge_type is None or t == edge_type]

    def bfs_levels(self, start, max_depth, edge_type=None):
        """Nodes reachable within max_depth hops, grouped by hop distance.
        Each node is discovered once; each edge is followed at most once."""
        depth_of = {start: 0}
        frontier = [start]
        for d in range(1, max_depth + 1):
            nxt = []
            for node in frontier:
                for dst in self.neighbors(node, edge_type):
                    if dst not in depth_of:
                        depth_of[dst] = d
                        nxt.append(dst)
            frontier = nxt
        levels: dict = {}
        for node, d in depth_of.items():
            if d > 0:
                levels.setdefault(d, []).append(node)
        return levels

    def friends_of_friends(self, node, edge_type="FRIEND"):
        """Classic 2-hop query: friends of my friends, minus my direct friends and me."""
        levels = self.bfs_levels(node, 2, edge_type)
        direct = set(self.neighbors(node, edge_type))
        return [n for n in levels.get(2, []) if n not in direct and n != node]

    def shortest_path(self, src, dst, edge_type=None):
        """Unweighted shortest path via BFS with parent pointers."""
        if src == dst:
            return [src]
        parent = {src: None}
        q = deque([src])
        while q:
            node = q.popleft()
            for nb in self.neighbors(node, edge_type):
                if nb not in parent:
                    parent[nb] = node
                    if nb == dst:
                        path = [dst]
                        while parent[path[-1]] is not None:
                            path.append(parent[path[-1]])
                        return list(reversed(path))
                    q.append(nb)
        return None


# ─── The traversal-cost contrast: graph BFS vs a relational k-way self-join ───

def bfs_work(graph, start, depth, edge_type=None):
    """Return (distinct nodes reached within `depth`, edges the graph followed).
    Edges-followed is bounded by |E|: each node is on the frontier once."""
    visited = {start}
    edges_followed = 0
    frontier = [start]
    for _ in range(depth):
        nxt = []
        for node in frontier:
            for dst in graph.neighbors(node, edge_type):
                edges_followed += 1
                if dst not in visited:
                    visited.add(dst)
                    nxt.append(dst)
        frontier = nxt
    return len(visited) - 1, edges_followed        # exclude the start node itself

def relational_join_rows(graph, start, depth, edge_type=None):
    """Rows a naive k-way self-join materializes to answer the same k-hop question:
    every walk of length 1..depth, counted WITH multiplicity (SQL doesn't dedup paths).
    This is the d^k blow-up -- it is NOT bounded by |V|+|E|."""
    frontier = {start: 1}                           # node -> number of partial paths ending here
    total_rows = 0
    for _ in range(depth):
        nxt: dict = {}
        for node, paths in frontier.items():
            for (t, dst, _p) in graph.out.get(node, ()):
                if edge_type is None or t == edge_type:
                    nxt[dst] = nxt.get(dst, 0) + paths
        total_rows += sum(nxt.values())             # this join stage's output cardinality
        frontier = nxt
    return total_rows


# ─── Demo ────────────────────────────────────────────────────────────────────

def _demo():
    # 1) A tiny, readable social graph to show the traversal queries.
    g = Graph()
    people = ["Ada", "Bob", "Cy", "Dana", "Eve", "Finn", "Gus", "Hana"]
    for p in people:
        g.add_node(p, label="User", name=p)
    for a, b in [("Ada", "Bob"), ("Ada", "Cy"), ("Bob", "Dana"), ("Cy", "Dana"),
                 ("Dana", "Eve"), ("Eve", "Finn"), ("Finn", "Gus"), ("Gus", "Hana")]:
        g.add_friendship(a, b)

    print("== A property graph: nodes (users) + typed edges (FRIEND) ==")
    print(f"  Ada's direct friends: {g.neighbors('Ada')}")
    print(f"  Ada's friends-of-friends (2 hops, new people): {g.friends_of_friends('Ada')}")

    print("\n== Shortest path: how are two people connected? ==")
    path = g.shortest_path("Ada", "Hana")
    print(f"  Ada -> Hana: {' -> '.join(path)}  ({len(path) - 1} hops)")

    print("\n== n-hop neighborhood (index-free adjacency: each hop is O(1) per edge) ==")
    for depth, nodes in sorted(g.bfs_levels("Ada", 3).items()):
        print(f"  {depth} hop(s) from Ada: {sorted(nodes)}")

    # 2) A large random social graph to measure the traversal-cost blow-up.
    rng = random.Random(7)
    N, LINKS_PER_NODE, DEPTH = 5000, 5, 6
    big = Graph()
    for i in range(N):
        big.add_node(i, label="User")
    for i in range(N):
        for _ in range(LINKS_PER_NODE):
            j = rng.randrange(N)
            if j != i:
                big.add_friendship(i, j)
    edges = sum(len(v) for v in big.out.values())

    reached, followed = bfs_work(big, 0, DEPTH)
    join_rows = relational_join_rows(big, 0, DEPTH)

    print(f"\n== Traversal cost: {DEPTH} hops in a {N}-node graph "
          f"(|V|={N}, |E|={edges}) ==")
    print(f"  graph DB (BFS, index-free adjacency):")
    print(f"     reached {reached} distinct people, following {followed} edges "
          f"(bounded by |E|={edges})")
    print(f"  relational ({DEPTH}-way self-join):")
    print(f"     materializes {join_rows} intermediate path-rows "
          f"(grows ~degree^hops, unbounded by |V|+|E|)")
    print(f"  the graph did ~{join_rows // max(followed, 1)}x less work for the same answer")


if __name__ == "__main__":
    _demo()
