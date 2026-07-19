# Graph Databases

> Sometimes the connections *between* your records matter more than the records themselves — "friends of friends," "shortest path from A to B," "every account within four hops of this stolen card." In a relational database each hop is another join and the cost explodes; in a graph database a relationship is a pointer you follow in `O(1)`, so a traversal costs what the *answer* costs, not what the whole table costs. Make relationships first-class and a class of queries goes from "melts the server" to "instant."

**Type:** Build
**Languages:** Python
**Prerequisites:** [When Not to Use SQL](../01-when-not-to-use-sql/), [Key-Value Stores](../02-key-value-stores/), [Keys & Relationships](../../03-relational-databases/05-keys-and-relationships/), [Indexes & the B-Tree](../../03-relational-databases/09-indexes-and-the-btree/)
**Time:** ~75 minutes

## The Problem

You're building the "People you may know" feature for a social network. The data is simple — a
`friendships(user_a, user_b)` table — and the first query is easy: *Ada's friends* is one indexed
lookup. Then the product manager asks for *friends of friends* (the people worth suggesting), and
the trouble begins.

In SQL, each additional hop is another **self-join** of the table against itself:

```sql
-- friends of friends of Ada: the table joined to itself, once per hop
SELECT DISTINCT f2.user_b
FROM friendships f1
JOIN friendships f2 ON f2.user_a = f1.user_b   -- hop 2
WHERE f1.user_a = 'Ada';
```

Two hops is tolerable. But recommendation and fraud questions are rarely two hops — they're "within
four hops," "the shortest connection," "is there *any* path." And each hop multiplies the work:
with an average of `d` friends each, hop 1 touches `d` rows, hop 2 touches `d²`, hop `k` touches
`dᵏ`. At `d = 10`, a four-hop query already grinds through the order of ten thousand intermediate
rows; a six-hop one, over a million — to return a few thousand distinct people. The join **re-derives
the relationships from scratch on every query**, and the intermediate result sets multiply until the
database falls over. This is Pressure 2 from Lesson 1 — expensive traversal — in its purest form.

And some of these questions SQL can barely *express*. "The shortest path between Ada and Zoe" needs a
**recursive** query, and "any path, however deep" needs one with no fixed hop count — both awkward,
unbounded, and easy to write in a way that never terminates. The relational model treats a
relationship as a *value to be re-joined*; here, the relationship **is** the thing you care about.

A **graph database** inverts that. It stores relationships as **first-class, physical connections**
— pointers from one record directly to another — so following a relationship is a single step, no
join, no index probe, no re-derivation. In this lesson you'll build one, watch a six-hop traversal do
a fraction of the work a self-join would, and then meet Neo4j and its query language, Cypher.

## The Concept

### The model: nodes, edges, properties

A graph database stores two things, and they're exactly the two you'd draw on a whiteboard:

- A **node** (or **vertex**) is an entity — a user, an account, a product, a city. It has a **label**
  (its type, like `User`) and **properties** (key-value pairs: `name = "Ada"`, `since = 2019`).
- An **edge** (or **relationship**) is a **typed, directed** connection between two nodes: `Ada
  —FOLLOWS→ Bob`, `Card —USED_AT→ Merchant`. Crucially, an edge *also* has a type and its own
  properties (`weight`, `since`, `amount`).

This is the **labeled property graph** model — the one Neo4j, Amazon Neptune, and most graph
databases use. (A second family, **RDF triple stores**, models everything as subject–predicate–object
triples queried with SPARQL; it dominates knowledge graphs and the semantic web. Same core idea —
data as a graph — different shape. This lesson builds the property-graph model, the more common
backend choice.)

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 552" width="100%" style="max-width:880px" role="img" aria-label="A small labeled property graph of five User nodes — Ada, Bob, Cy, Dana and Eve — connected by five typed, directed FRIEND relationships: Ada to Bob, Ada to Cy, Bob to Dana, Cy to Dana, and Dana to Eve. The nodes are laid out in columns by hop distance from Ada: Ada at hop zero, Bob and Cy at hop one, Dana at hop two, Eve at hop three. Dana sits at hop two by two distinct paths, Ada to Bob to Dana and Ada to Cy to Dana, and a breadth-first traversal discovers her once, at depth two. Edges are stored directed, so walking against an arrow uses the node's stored incoming edge list rather than a reverse scan. Below, two panels contrast the cost of reaching Eve. In a graph database with index-free adjacency, three hops means three pointer follows: each hop is a constant-time dereference from the node's own edge list, and the cost grows only with that node's degree, never with the size of the database. In a relational database, three hops means three self-joins of the friendships table: each hop is a logarithmic index probe over every edge in the table, and the intermediate rows multiply as degree to the power of hops, re-derived on every query. Measured in the Build It section, a six-hop traversal of a five-thousand-node graph followed 49,992 edges — exactly the edge count — while the six-way self-join materialized 1,445,675 intermediate path-rows, about twenty-eight times the work for the identical answer.">
  <defs>
    <marker id="p4l6a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">A labeled property graph — and what each extra hop costs</text>
  <text x="440" y="46" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.75">nodes carry a label (:User) plus properties; edges are typed (:FRIEND) and directed</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <!-- hop-distance column headers (BFS frontiers from Ada) -->
    <g text-anchor="middle" font-size="9.5" fill="#7f7f7f">
      <text x="108" y="70" font-weight="700">hop 0 · start</text>
      <text x="300" y="70" font-weight="700">hop 1</text>
      <text x="492" y="70" font-weight="700">hop 2</text>
      <text x="684" y="70" font-weight="700">hop 3</text>
    </g>
    <g stroke="#7f7f7f" stroke-width="1.2" stroke-dasharray="4 5" stroke-opacity="0.28">
      <path d="M49 78 L167 78"/>
      <path d="M241 78 L359 78"/>
      <path d="M433 78 L551 78"/>
      <path d="M625 78 L743 78"/>
    </g>

    <!-- FRIEND relationships: typed and directed -->
    <g fill="none" stroke="#0fa07f" stroke-width="1.8">
      <path d="M167 179 L238 127" marker-end="url(#p4l6a-ar)"/>
      <path d="M167 201 L238 253" marker-end="url(#p4l6a-ar)"/>
      <path d="M359 127 L430 179" marker-end="url(#p4l6a-ar)"/>
      <path d="M359 253 L430 201" marker-end="url(#p4l6a-ar)"/>
      <path d="M551 190 L622 190" marker-end="url(#p4l6a-ar)"/>
    </g>
    <g text-anchor="middle" font-size="8.5" fill="#0fa07f" font-weight="700">
      <text x="195.4" y="143.3" transform="rotate(-36.2 195.4 143.3)">:FRIEND</text>
      <text x="191.9" y="241.5" transform="rotate(36.2 191.9 241.5)">:FRIEND</text>
      <text x="401.6" y="143.3" transform="rotate(36.2 401.6 143.3)">:FRIEND</text>
      <text x="405.1" y="241.5" transform="rotate(-36.2 405.1 241.5)">:FRIEND</text>
      <text x="586" y="181">:FRIEND</text>
    </g>

    <!-- the start node: where the traversal is asked from -->
    <rect x="49" y="167" width="118" height="46" rx="23" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="2"/>
    <text x="108" y="184" text-anchor="middle" font-size="9" font-weight="700" fill="#3553ff">:User</text>
    <text x="108" y="201" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">name: 'Ada'</text>

    <!-- the rest of the graph -->
    <g fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.8">
      <rect x="241" y="89" width="118" height="46" rx="23"/>
      <rect x="241" y="245" width="118" height="46" rx="23"/>
      <rect x="433" y="167" width="118" height="46" rx="23"/>
      <rect x="625" y="167" width="118" height="46" rx="23"/>
    </g>
    <g text-anchor="middle" font-size="9" font-weight="700" fill="#7c5cff">
      <text x="300" y="106">:User</text>
      <text x="300" y="262">:User</text>
      <text x="492" y="184">:User</text>
      <text x="684" y="184">:User</text>
    </g>
    <g text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">
      <text x="300" y="123">name: 'Bob'</text>
      <text x="300" y="279">name: 'Cy'</text>
      <text x="492" y="201">name: 'Dana'</text>
      <text x="684" y="201">name: 'Eve'</text>
    </g>

    <text x="440" y="316" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">Dana sits at hop 2 by <tspan font-weight="700">two distinct paths</tspan> — Ada→Bob→Dana and Ada→Cy→Dana — and BFS discovers her once, at depth 2.</text>
    <text x="440" y="334" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">Edges are stored <tspan font-weight="700">directed</tspan>: Ada→Bob is one edge; Bob→Ada would be another.</text>
    <text x="440" y="350" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">Walking against the arrows reads the node's stored incoming list — not a reverse scan.</text>

    <!-- cost of the same 3-hop question, two ways -->
    <rect x="30" y="368" width="400" height="128" rx="11" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f" stroke-width="1.8"/>
    <text x="46" y="392" font-size="11.5" font-weight="700" fill="#0fa07f">GRAPH · index-free adjacency</text>
    <text x="46" y="416" font-size="10" fill="currentColor">Ada → Bob → Dana → Eve</text>
    <text x="46" y="438" font-size="11" font-weight="700" fill="currentColor">3 hops = 3 pointer follows</text>
    <text x="46" y="460" font-size="9" fill="currentColor" opacity="0.85">each hop: an O(1) dereference from the node's own edge list</text>
    <text x="46" y="480" font-size="9" fill="currentColor" opacity="0.85">cost grows with that node's degree — never with the database</text>

    <rect x="450" y="368" width="400" height="128" rx="11" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f" stroke-width="1.8"/>
    <text x="466" y="392" font-size="11.5" font-weight="700" fill="#e0930f">RELATIONAL · one self-JOIN per hop</text>
    <text x="466" y="416" font-size="10" fill="currentColor">friendships f1 JOIN f2 JOIN f3</text>
    <text x="466" y="438" font-size="11" font-weight="700" fill="currentColor">3 hops = 3 self-JOINs</text>
    <text x="466" y="460" font-size="9" fill="currentColor" opacity="0.85">each hop: an O(log n) index probe over ALL edges in the table</text>
    <text x="466" y="480" font-size="9" fill="currentColor" opacity="0.85">intermediate rows multiply ~d^k, re-derived on every query</text>
  </g>
  <text x="440" y="520" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Measured in Build It — 6 hops across a 5,000-node graph: the traversal followed 49,992 edges, exactly |E|;</text>
  <text x="440" y="538" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">the 6-way self-join materialized 1,445,675 intermediate path-rows — ~28× the work for the identical answer.</text>
</svg>
```

Notice what's different from a relational schema: there's no `friendships` join table, no foreign
keys to follow. The relationship between Ada and Bob is a *direct edge*, an object in its own right.
That representational choice is the whole point, and its payoff comes from *how* the edge is stored.

### The defining trick: index-free adjacency

Here is the one idea that makes a graph database a graph database, and it's worth stating precisely.

In a relational database, "Ada's friends" is an **index lookup**: the query planner consults the
B-tree index on `friendships.user_a`, does an `O(log n)` search to find the matching rows, and reads
them. That index covers *the whole table*, so its cost grows with the total number of relationships
in the system, and you pay a fresh lookup at *every hop* of a traversal.

In a graph database, each node **physically stores direct references to its adjacent edges** — like a
linked list, or the adjacency list you'd build for a graph algorithm. Ada's node holds pointers
straight to her edges, which point straight to Bob's and Cy's nodes. Following a relationship is a
**pointer dereference** — `O(1)`, and *independent of how large the total graph is*. There is no
index to consult, because the adjacency *is* the index, attached to each node. This property has a
name: **index-free adjacency** (the term comes from the Neo4j lineage; see Robinson, Webber & Eifrem,
*Graph Databases*, O'Reilly).

The consequence is the whole reason the category exists:

| | Relational (join per hop) | Graph (index-free adjacency) |
|---|---|---|
| Cost of one hop | `O(log n)` index lookup over *all* edges | `O(1)` pointer dereference from the node |
| Cost grows with | Total relationships in the database | The node's own degree only |
| A `k`-hop traversal | `~O(dᵏ)` intermediate rows, re-derived each hop | `O(nodes + edges actually visited)` |
| Deep / variable-length paths | Recursive query, awkward and unbounded | A native, bounded traversal |

A `k`-hop traversal in a graph database visits each node once and follows each edge once — its cost
is proportional to *the part of the graph the answer actually touches*, not the size of the whole
database. That is why "four hops out" stays fast on a graph with a billion edges, and why the same
query melts a relational database: the graph never pays for the edges it doesn't walk.

### Traversals: BFS, shortest path, and pattern matching

Almost every graph query is a **traversal** — start somewhere and follow edges. The workhorses:

- **Breadth-first search (BFS)** expands the frontier one hop at a time: all 1-hop neighbors, then
  all 2-hop, and so on. It answers "n-hop neighborhood" (friends of friends) and, because it explores
  nearest-first, **unweighted shortest path** (the first time you reach the target, you've found the
  fewest-hop route).
- **Depth-first search (DFS)** follows one path as far as it goes before backtracking — good for
  reachability and cycle detection.
- **Pattern matching** finds a *shape*: "a `User` who `FOLLOWS` a `User` who `LIKES` a `Post` tagged
  `jazz`." This is what a graph query language (Cypher) is built to express, and it compiles down to
  traversals.

You'll build BFS-based n-hop neighborhood and shortest-path below — they're a few lines each once the
adjacency is a pointer walk.

### When a graph database earns its keep — and when it absolutely doesn't

This is where senior judgment lives, because the graph model is *seductive* — everything is
connected, so everything looks like a graph — and reaching for it by reflex is a classic
over-engineering mistake.

**It earns its keep when the query is a deep or variable-length traversal:**

- **Recommendations** — "people/products connected to the ones you like," co-purchase and co-view
  graphs.
- **Fraud detection** — "accounts within N hops of a known-bad one," ring detection (cycles).
- **Networks and dependencies** — social graphs, knowledge graphs, package/permission/org
  hierarchies, "what breaks if this service goes down."
- **Pathfinding** — shortest path, routes, "how is X connected to Y."

**It does *not* earn its keep for shallow, fixed relationships** — and this is the trap. A **foreign
key is already a one-hop edge.** "A user has many posts," "an order has line items" — those are single
joins a relational database does superbly, and moving them to a graph database buys you nothing but a
second system to operate. The threshold is **variable-length or deep traversal** (three-plus hops, or
an unknown number), where the relational self-join's `dᵏ` blow-up actually bites. Below that
threshold, stay relational.

And the Lesson 1 caveat returns: even when you *do* have graph-shaped queries, a modest amount of
bounded traversal is expressible in Postgres with a **recursive CTE** (`WITH RECURSIVE`), and the
**Apache AGE** extension adds a real property graph and Cypher *inside* Postgres. Reach for a
dedicated graph database when the traversals are deep, hot, and central to the product — not for the
occasional two-hop query.

## Build It

Let's build a property graph with the trick that matters — index-free adjacency — and the traversals
that fall out of it: neighbors, friends-of-friends, n-hop neighborhood, and shortest path. Then we'll
*measure* the traversal-cost claim by answering the same k-hop question two ways. Standard library
only; the whole engine is a couple of dictionaries.

The core is the adjacency map: each node id points directly at the list of its outgoing edges. This
one data structure is index-free adjacency — following an edge is a list walk from the node, with no
global index:

```python
class Graph:
    def __init__(self):
        self.nodes = {}     # id -> properties (includes 'label')
        # INDEX-FREE ADJACENCY: a node id maps straight to its outgoing edges.
        # Following an edge is a pointer walk -- O(degree) -- no index, no join.
        self.out = {}       # id -> [(edge_type, dst_id, props), ...]
        self.inn = {}       # id -> [(edge_type, src_id, props), ...]  (reverse)

    def add_edge(self, src, dst, edge_type, **props):
        self.out.setdefault(src, []).append((edge_type, dst, props))
        self.inn.setdefault(dst, []).append((edge_type, src, props))

    def neighbors(self, node, edge_type=None):
        return [dst for (t, dst, _p) in self.out.get(node, ())
                if edge_type is None or t == edge_type]
```

BFS is now just "expand the frontier one hop at a time," discovering each node once. That single
method gives you n-hop neighborhoods directly, and shortest path with parent pointers:

```python
    def bfs_levels(self, start, max_depth, edge_type=None):
        depth_of = {start: 0}
        frontier = [start]
        for d in range(1, max_depth + 1):
            nxt = []
            for node in frontier:
                for dst in self.neighbors(node, edge_type):
                    if dst not in depth_of:          # each node discovered once
                        depth_of[dst] = d
                        nxt.append(dst)
            frontier = nxt
        ...                                          # group nodes by hop distance
```

Now the measurement. To make the "joins explode, traversals don't" claim concrete, answer the same
`k`-hop reachability question two ways on the same random social graph. The graph traversal follows
each edge at most once (bounded by the number of edges). The relational self-join materializes *every
walk*, counted with multiplicity — the `dᵏ` blow-up, computed here without a database by multiplying
the frontier's path-counts hop by hop, exactly as the join's cardinality grows:

```python
def bfs_work(graph, start, depth):
    """Graph BFS: edges-followed is bounded by |E| -- each node is on the frontier once."""
    visited, edges_followed, frontier = {start}, 0, [start]
    for _ in range(depth):
        nxt = []
        for node in frontier:
            for dst in graph.neighbors(node):
                edges_followed += 1
                if dst not in visited:
                    visited.add(dst); nxt.append(dst)
        frontier = nxt
    return len(visited) - 1, edges_followed

def relational_join_rows(graph, start, depth):
    """Rows a naive k-way self-join materializes: every walk of length 1..depth,
    counted WITH multiplicity (SQL doesn't dedup paths). NOT bounded by |V|+|E|."""
    frontier, total_rows = {start: 1}, 0             # node -> # of partial paths ending here
    for _ in range(depth):
        nxt = {}
        for node, paths in frontier.items():
            for (_t, dst, _p) in graph.out.get(node, ()):
                nxt[dst] = nxt.get(dst, 0) + paths
        total_rows += sum(nxt.values())              # this join stage's output cardinality
        frontier = nxt
    return total_rows
```

Running `python graphdb.py` first exercises the traversals on a tiny, readable social graph, then
measures the cost blow-up on a 5,000-node one:

```console
$ python graphdb.py
== A property graph: nodes (users) + typed edges (FRIEND) ==
  Ada's direct friends: ['Bob', 'Cy']
  Ada's friends-of-friends (2 hops, new people): ['Dana']

== Shortest path: how are two people connected? ==
  Ada -> Hana: Ada -> Bob -> Dana -> Eve -> Finn -> Gus -> Hana  (6 hops)

== n-hop neighborhood (index-free adjacency: each hop is O(1) per edge) ==
  1 hop(s) from Ada: ['Bob', 'Cy']
  2 hop(s) from Ada: ['Dana']
  3 hop(s) from Ada: ['Eve']

== Traversal cost: 6 hops in a 5000-node graph (|V|=5000, |E|=49992) ==
  graph DB (BFS, index-free adjacency):
     reached 4999 distinct people, following 49992 edges (bounded by |E|=49992)
  relational (6-way self-join):
     materializes 1445675 intermediate path-rows (grows ~degree^hops, unbounded by |V|+|E|)
  the graph did ~28x less work for the same answer
```

That last block is the entire lesson in numbers. To reach almost everyone within six hops, the graph
traversal followed **49,992 edges — exactly `|E|`**, because it walks each edge at most once; its work
is bounded by the size of the graph, full stop. The equivalent six-way self-join materializes **1.4
million intermediate path-rows**, because it counts every distinct *walk* to each node and re-derives
them hop by hop — and that number keeps multiplying by the average degree with every additional hop,
while the graph's stays pinned at `|E|`. Six hops is already ~28× more work for the identical answer;
at eight or ten hops the join is hopeless and the traversal barely notices. *That* is index-free
adjacency.

## Use It

**Neo4j** is the most widely used graph database, and its query language, **Cypher**, is built to
express traversals as ASCII-art patterns — nodes in `()`, relationships in `-[]->`. Your Build-It maps
onto it almost directly:

```text
// Cypher (Neo4j's query language). Ada's friends of friends -- your friends_of_friends()
MATCH (ada:User {name: 'Ada'})-[:FRIEND]->()-[:FRIEND]->(fof)
WHERE NOT (ada)-[:FRIEND]->(fof) AND fof <> ada
RETURN DISTINCT fof.name;

// Variable-length traversal, 1 to 4 hops -- your bfs_levels(start, 4).
// The `*1..4` is the bounded BFS you built; the engine walks pointers, no join.
MATCH (ada:User {name: 'Ada'})-[:FRIEND*1..4]->(reachable)
RETURN DISTINCT reachable.name;

// Shortest path -- your shortest_path(), as a first-class primitive
MATCH p = shortestPath((ada:User {name:'Ada'})-[:FRIEND*]-(zoe:User {name:'Zoe'}))
RETURN p;
```

The `*1..4` variable-length pattern is exactly the bounded traversal you wrote, and `shortestPath` is
your BFS as a built-in. Beyond Neo4j: **Amazon Neptune** (managed, speaks both property-graph
Gremlin/openCypher *and* RDF/SPARQL), **TigerGraph** and **JanusGraph** (built for scale), and, for
the knowledge-graph world, **RDF triple stores** with **SPARQL**.

Three hard-won lessons that separate people who use a graph database well from people who bolt one on
and regret it:

- **A graph database is for traversal, not for storing everything.** Keep your transactional source
  of truth — orders, payments, the data that needs ACID — in the relational store, and put the
  *relationship-heavy, deep-traversal* slice in the graph. Most systems that use a graph database use
  it *alongside* a relational one, each for what it's best at. That deliberate mix is **polyglot
  persistence** (Lesson 8), and it's the norm here.
- **Beware the supernode.** A node with a huge degree — a celebrity with 50 million followers, a
  hub airport, a popular hashtag — is the graph's version of Lesson 4's hot partition. A traversal
  that passes *through* a supernode fans out into millions of edges and explodes. Real graph systems
  handle them specially (filtering, sampling, capping fan-out); design your traversals to avoid
  routing everything through them.
- **Don't reach for a graph database for one-hop joins.** A foreign key already is an edge. "Users
  have posts," "orders have items" — those are single joins a relational database does beautifully.
  The graph earns its cost only when you have *deep or variable-length* traversal (recommendations,
  fraud rings, pathfinding). Below that bar, a recursive CTE — or just a join — in the Postgres you
  already run is the right, cheaper answer.

## Key takeaways

- A **graph database** makes relationships **first-class**: data is **nodes** (entities with a label
  and properties) and **edges** (typed, directed relationships that also carry properties) — the
  **labeled property graph** model (Neo4j, Neptune). RDF/SPARQL triple stores are the knowledge-graph
  cousin.
- Its defining trick is **index-free adjacency**: each node stores direct pointers to its adjacent
  edges, so following a relationship is an `O(1)` dereference *independent of total graph size* — not
  an index lookup or a join that grows with the whole table.
- Because of that, a **`k`-hop traversal costs `O(nodes + edges visited)`**, while the equivalent
  relational **`k`-way self-join blows up as `~O(dᵏ)`** intermediate rows, re-derived every hop. The
  Build-It measured it: to reach a 5,000-node graph in six hops, the traversal followed exactly `|E|`
  edges; the self-join materialized 1.4 million rows (~28× the work, and widening every hop).
- Graph databases **earn their keep** for deep or variable-length traversal — recommendations, fraud
  rings, pathfinding, dependency graphs — and **don't** for shallow, fixed relationships: **a foreign
  key is already a one-hop edge**, and a simple join beats a whole new system.
- Use it **alongside** your relational store (polyglot persistence, Lesson 8), watch out for
  **supernodes** (the graph's hot partition), and remember Postgres can do bounded traversal with a
  **recursive CTE** or the **Apache AGE** extension before you commit to a dedicated graph database.

Next: [Data Modeling by Access Pattern](../07-data-modeling-by-access-pattern/) — you've now met every
NoSQL family, and each punished you for the same thing: no joins, look up by key, model per query.
That meta-skill — designing the storage around the queries instead of the other way round — is the
next lesson, and single-table design is its sharpest form.
