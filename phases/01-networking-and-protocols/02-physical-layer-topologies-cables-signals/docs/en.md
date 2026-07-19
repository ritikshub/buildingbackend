# The Physical Layer: Topologies, Cables & Signals

> Every byte your backend ever sends ends its journey as a physical event — a voltage on copper, a pulse of light in glass, a radio wave in air. This is the layer where bits stop being an abstraction and become physics.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Lesson 01 — the OSI / TCP-IP models](../01-osi-and-tcp-ip-models/). You should know that a network is described as a stack of layers and that the bottom one is called the physical layer.
**Time:** ~60 minutes

## The Problem

In Lesson 01 you learned the network is a stack of layers, and that the very
bottom — **layer 1, the physical layer** — is where "sending data" finally means
something physical. But that leaves two concrete questions unanswered, and every
real network has to answer both before a single byte moves.

First: **how are the machines even wired together?** Five computers in a room can
be connected in wildly different ways — one shared cable, a loop, a central box,
or every machine to every other. Each choice decides what happens when one cable
is cut: does the whole office go down, or just one desk? That shape is the
network's **topology**, and picking the wrong one is a failure you cannot patch
in software.

Second: **what actually carries the bits, and how is a bit even represented?** A
`1` is not a `1` on the wire — it is a change in voltage, or the presence of
light, that the receiver has to detect and decode without a shared clock to tell
it where one bit ends and the next begins. Get the encoding or the cable length
wrong and the receiver reads garbage.

By the end of this lesson you will have modelled all five topologies as graphs in
Python — computing, by hand, which ones survive a failure and which have a single
weak point — and encoded a bit string into two real signal formats. The physical
layer will stop being the mystery box at the bottom of the diagram.

## The Concept

The physical layer has one job: **move raw bits between two directly connected
devices as a physical signal over a medium.** It does not understand addresses,
packets, or reliability — those belong to layers above. It cares about three
things only: the **shape** of the connections (topology), the **medium** that
carries the signal (copper, glass, air), and the **encoding** that turns bits
into signal transitions. We take them in that order.

### Topologies: the shape of the wiring

A **topology** is the map of which node connects to which. The same five
computers can be arranged in fundamentally different shapes, and the shape — not
the software — decides three things: how many cables you buy, what happens when
one fails, and how many hops a message takes to cross the network. We will judge
each topology by four hand-computed metrics (this is exactly what
[`code/topologies.py`](../code/topologies.py) measures):

- **Link count** — how much cable you pay for.
- **Node degree** — how many links touch each node.
- **Single point of failure (SPOF)** — is there one node or link whose loss
  disconnects the network?
- **Diameter** — the worst-case number of hops between any two nodes (lower is
  faster and lower-latency).

### Bus topology

A **bus** connects every node to one shared backbone cable. Electrically all
nodes tap into the same line, so a break anywhere splits the network in two — we
model that as a chain where every link is load-bearing.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 180" width="100%" style="max-width:580px" role="img" aria-label="Bus topology: five nodes A, B, C, D and E all tap into one shared horizontal backbone cable. Because every node shares the same wire, a break anywhere splits the network in two and only one node can transmit at a time.">
  <text x="300" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="13.5" font-weight="700" fill="currentColor">Bus — one shared backbone, nodes tap in</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- shared backbone (the wire) -->
    <g stroke="#7f7f7f" stroke-width="2.5" stroke-linecap="round">
      <path d="M55 95 L70 95"/>
      <path d="M110 95 L182 95"/>
      <path d="M222 95 L294 95"/>
      <path d="M334 95 L406 95"/>
      <path d="M446 95 L518 95"/>
      <path d="M558 95 L573 95"/>
    </g>
    <!-- nodes -->
    <g fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f" stroke-width="1.8">
      <circle cx="90" cy="95" r="20"/>
      <circle cx="202" cy="95" r="20"/>
      <circle cx="314" cy="95" r="20"/>
      <circle cx="426" cy="95" r="20"/>
      <circle cx="538" cy="95" r="20"/>
    </g>
    <g fill="currentColor" text-anchor="middle" font-size="13" font-weight="700">
      <text x="90" y="100">A</text>
      <text x="202" y="100">B</text>
      <text x="314" y="100">C</text>
      <text x="426" y="100">D</text>
      <text x="538" y="100">E</text>
    </g>
    <text x="300" y="135" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.6">all five share one collision domain</text>
    <text x="300" y="162" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">Any break in the backbone splits the network — every link is load-bearing.</text>
  </g>
</svg>
```

- **Cabling:** cheapest — roughly one cable segment per node, no central device.
- **Failure:** brutal. Any break in the backbone partitions the network, so the
  middle nodes are single points of failure. Our model finds every link is
  critical.
- **Contention:** because everyone shares one wire, only one node can transmit at
  a time. Two transmitting at once **collide** — the whole bus is a single
  *collision domain* (more on that below). This is why the bus died out.

### Ring topology

A **ring** wires each node to the next, and the last back to the first, forming a
loop. Data travels around the ring, often in one direction.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 460 320" width="100%" style="max-width:440px" role="img" aria-label="Ring topology: five nodes A through E are wired in a closed loop — each linked to the next and the last back to the first. Traffic circulates around the loop, and because two paths exist between any two nodes, the ring survives any single link or node failure by re-routing the long way around.">
  <defs>
    <marker id="l02b-flow" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="230" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="13.5" font-weight="700" fill="currentColor">Ring — a closed loop of nodes</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- links -->
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M246.2 71.7 L318.8 124.3"/>
      <path d="M328.8 155.0 L301.2 240.0"/>
      <path d="M275 259 L185 259"/>
      <path d="M158.8 240.0 L131.2 155.0"/>
      <path d="M141.2 124.3 L213.8 71.7"/>
    </g>
    <!-- circulation hint -->
    <path d="M230 130 A40 40 0 1 1 190 170" fill="none" stroke="currentColor" stroke-width="1.4" opacity="0.4" marker-end="url(#l02b-flow)"/>
    <!-- nodes -->
    <g fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f" stroke-width="1.8">
      <circle cx="230" cy="60" r="20"/>
      <circle cx="335" cy="136" r="20"/>
      <circle cx="295" cy="259" r="20"/>
      <circle cx="165" cy="259" r="20"/>
      <circle cx="125" cy="136" r="20"/>
    </g>
    <g fill="currentColor" text-anchor="middle" font-size="13" font-weight="700">
      <text x="230" y="65">A</text>
      <text x="335" y="141">B</text>
      <text x="295" y="264">C</text>
      <text x="165" y="264">D</text>
      <text x="125" y="141">E</text>
    </g>
    <text x="230" y="303" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">Two ways around the loop — a ring survives any single cut.</text>
  </g>
</svg>
```

- **Cabling:** one link per node (`n` links for `n` nodes).
- **Failure:** more resilient than it looks. Because there are *two* paths around
  the loop, our model shows a simple ring survives **any single node or link
  loss** — the survivors just re-route the long way around. That is exactly why
  resilient designs use rings (and dual rings) so a single cut can "wrap."
- **Diameter:** about `n/2` hops — a message may have to travel half the loop.

### Star topology

A **star** connects every node to one **central device** — a switch (or, in older
networks, a hub). This is the **dominant topology of every modern wired LAN**
(Local Area Network): the wall jack at your desk runs back to a switch in a
closet. It deserves special attention because it is what you will actually build
on.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 480 340" width="100%" style="max-width:460px" role="img" aria-label="Star topology: five nodes A through E each connect by their own dedicated cable to one central switch in the middle. Any single node or cable failure is isolated to that node, every path is just two hops, but the central switch is a single point of failure for the whole network.">
  <text x="240" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="13.5" font-weight="700" fill="currentColor">Star — every node to one central switch</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- spokes -->
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M240 158 L240 78"/>
      <path d="M288 164.4 L336.9 148.6"/>
      <path d="M256.1 202 L300.4 262.5"/>
      <path d="M224.1 202 L180.5 262.4"/>
      <path d="M192 164.4 L143.1 148.6"/>
    </g>
    <!-- hosts -->
    <g fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f" stroke-width="1.8">
      <circle cx="240" cy="60" r="18"/>
      <circle cx="354" cy="143" r="18"/>
      <circle cx="311" cy="277" r="18"/>
      <circle cx="170" cy="277" r="18"/>
      <circle cx="126" cy="143" r="18"/>
    </g>
    <g fill="currentColor" text-anchor="middle" font-size="12" font-weight="700">
      <text x="240" y="64.5">A</text>
      <text x="354" y="147.5">B</text>
      <text x="311" y="281.5">C</text>
      <text x="170" y="281.5">D</text>
      <text x="126" y="147.5">E</text>
    </g>
    <!-- central switch -->
    <rect x="192" y="158" width="96" height="44" rx="10" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
    <text x="240" y="184" text-anchor="middle" font-size="12" font-weight="700" fill="#0fa07f">Switch</text>
    <text x="240" y="320" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">Isolated failures and constant 2-hop paths — but the switch is a SPOF.</text>
  </g>
</svg>
```

- **Cabling:** one dedicated cable per node back to the center (`n` links).
- **Failure — the key property:** a failure of any *single node or its cable is
  isolated* — that desk goes dark and no one else notices. But the **central
  device is a single point of failure**: our model flags the switch `SW` as the
  one node whose loss disconnects everyone. You solve that with a redundant
  switch, not a different topology.
- **Diameter:** always **2** — every path is node → switch → node. Low, constant
  latency, no matter how many nodes you add.
- **No collisions on a switch:** a switch gives each port its own dedicated link,
  so unlike the bus, two nodes can send at the same time. That combination —
  isolated failures, constant diameter, no collisions — is why the star won.

### Mesh topology

A **mesh** connects nodes directly to each other. In a **full mesh** *every* node
links to *every* other node; in a **partial mesh** only the important nodes are
cross-linked.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 440 355" width="100%" style="max-width:420px" role="img" aria-label="Full mesh topology: four nodes A, B, C and D each have a direct link to every other node, for six links in total. Every node reaches every other in a single hop and no single node or link failure can disconnect the network.">
  <text x="220" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="13.5" font-weight="700" fill="currentColor">Full mesh — a link between every pair</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- links (n(n-1)/2 = 6) -->
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M234.14 84.14 L315.86 165.86"/>
      <path d="M315.86 194.14 L234.14 275.86"/>
      <path d="M205.86 275.86 L124.14 194.14"/>
      <path d="M124.14 165.86 L205.86 84.14"/>
      <path d="M220 90 L220 270"/>
      <path d="M310 180 L130 180"/>
    </g>
    <!-- nodes -->
    <g fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f" stroke-width="1.8">
      <circle cx="220" cy="70" r="20"/>
      <circle cx="330" cy="180" r="20"/>
      <circle cx="220" cy="290" r="20"/>
      <circle cx="110" cy="180" r="20"/>
    </g>
    <g fill="currentColor" text-anchor="middle" font-size="13" font-weight="700">
      <text x="220" y="75">A</text>
      <text x="330" y="185">B</text>
      <text x="220" y="295">C</text>
      <text x="110" y="185">D</text>
    </g>
    <text x="220" y="328" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">Every pair linked — diameter 1, no single point of failure.</text>
    <text x="220" y="344" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.65">Cost explodes as n(n-1)/2 links: 6 for 4 nodes, 45 for 10.</text>
  </g>
</svg>
```

- **Cabling:** expensive, and it explodes. A full mesh of `n` nodes needs
  **`n(n-1)/2`** links — 6 links for 4 nodes, 45 for 10, 4,950 for 100. Our code
  verifies this formula against the measured link count.
- **Failure:** maximum resilience. Every node has many independent paths, so no
  single node or link removal disconnects anything — our model reports **no SPOF**.
- **Diameter:** **1** in a full mesh — every node reaches every other in one hop.
- **Where it lives:** not on desktops but in network *cores* and the internet
  backbone, usually as a partial mesh — enough cross-links for resilience without
  paying the `n(n-1)/2` bill.

### Tree and hybrid topologies

A **tree** (hierarchical) topology is **stars of stars**: a core switch feeds
distribution switches, which each feed a star of hosts. This is how real
buildings and data centers are actually wired.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 560 320" width="100%" style="max-width:540px" role="img" aria-label="Tree topology: a core switch at the top connects down to two distribution switches, and each distribution switch connects down to two hosts. It is a hierarchy of stars — it scales cleanly, but every switch is a single point of failure whose loss drops its entire sub-tree.">
  <text x="280" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="13.5" font-weight="700" fill="currentColor">Tree — a hierarchy of stars</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- links -->
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M254 90 L178.6 148"/>
      <path d="M306 90 L381.4 148"/>
      <path d="M137.9 192 L103.7 254.2"/>
      <path d="M162.1 192 L196.3 254.2"/>
      <path d="M397.9 192 L363.7 254.2"/>
      <path d="M422.1 192 L456.3 254.2"/>
    </g>
    <!-- hosts -->
    <g fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f" stroke-width="1.8">
      <circle cx="95" cy="270" r="18"/>
      <circle cx="205" cy="270" r="18"/>
      <circle cx="355" cy="270" r="18"/>
      <circle cx="465" cy="270" r="18"/>
    </g>
    <g fill="currentColor" text-anchor="middle" font-size="11" font-weight="700">
      <text x="95" y="274.5">H1</text>
      <text x="205" y="274.5">H2</text>
      <text x="355" y="274.5">H3</text>
      <text x="465" y="274.5">H4</text>
    </g>
    <!-- distribution switches -->
    <g stroke="#7c5cff" stroke-width="2" stroke-linejoin="round">
      <rect x="90" y="148" width="120" height="44" rx="10" fill="#7c5cff" fill-opacity="0.12"/>
      <rect x="350" y="148" width="120" height="44" rx="10" fill="#7c5cff" fill-opacity="0.12"/>
    </g>
    <g fill="#7c5cff" text-anchor="middle" font-weight="700" font-size="10">
      <text x="150" y="166">Distribution</text>
      <text x="150" y="180">switch 1</text>
      <text x="410" y="166">Distribution</text>
      <text x="410" y="180">switch 2</text>
    </g>
    <!-- core switch -->
    <rect x="215" y="50" width="130" height="40" rx="10" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
    <text x="280" y="74" text-anchor="middle" font-size="12" font-weight="700" fill="#0fa07f">Core switch</text>
    <text x="280" y="305" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">Every switch is a SPOF — lose a distribution switch and its whole sub-tree drops.</text>
  </g>
</svg>
```

- **Cabling:** scales cleanly — add a branch without re-wiring the whole network.
- **Failure:** inherits the star's weakness at every level. Our model flags each
  internal switch (`Core`, `Dist1`, `Dist2`) as a SPOF: lose a distribution
  switch and its whole sub-tree drops. Higher up the tree, the more that fails
  with it — so cores are the most redundant part of a real design.
- **Hybrid** just means mixing these on purpose — e.g. a mesh between core
  switches for resilience, with a tree of stars hanging off each. Real networks
  are almost always hybrids.

Here is how the five compare, exactly as computed by the code you will run:

| Topology | Links | SPOF node? | Survives 1 link cut? | Diameter |
|---|---|---|---|---|
| Bus | `n-1` | yes (middle nodes) | no | `n-1` (worst) |
| Ring | `n` | no | yes | ~`n/2` |
| Star | `n` | yes (the switch) | no (isolates 1 node) | 2 (constant) |
| Full mesh | `n(n-1)/2` | no | yes | 1 (best) |
| Tree | `n-1` | yes (every switch) | no | up to `2·depth` |

The trade-off is always the same shape: **more links buy more resilience and a
smaller diameter, at higher cost.** The star wins the LAN because it gets
constant-diameter, isolated-failure behavior for only `n` links — you just have
to protect the one device in the middle.

### Transmission media: copper, glass, and air

The topology says *which* nodes connect; the **medium** is the physical stuff the
signal travels through. There are three families, and the choice sets your speed,
your distance limit, and your cost.

- **Twisted pair (copper):** pairs of insulated copper wires twisted together —
  the twist cancels out **EMI** (Electromagnetic Interference). **UTP**
  (Unshielded Twisted Pair) is the cheap, ubiquitous default; **STP** (Shielded
  Twisted Pair) adds foil for noisy environments. Sold in **categories** — Cat5e,
  Cat6, Cat6a — that rate its speed, terminated with an **RJ45** (Registered
  Jack 45) connector. The famous **~100 m** Ethernet limit is a twisted-pair
  limit.
- **Coaxial (copper):** a single core conductor inside a shield. Older LAN
  backbones and today's cable-broadband last mile.
- **Fiber optic (glass):** carries **light**, not electricity, so it is **immune
  to EMI**, and has enormous bandwidth over huge distances. **Multi-mode** (wider
  core, cheaper optics) is for short runs inside a building; **single-mode**
  (hair-thin core, laser light) is for long-haul links that can span tens or
  hundreds of kilometres.
- **Wireless / radio:** no cable at all — bits ride radio waves through the air.
  Maximum convenience, but it is a *shared* medium (like a bus, everyone hears
  everyone) and the most exposed to interference and attenuation.

| Medium | Typical speed | Max segment length | Relative cost | Notes |
|---|---|---|---|---|
| Twisted pair — Cat5e (UTP) | 1 Gbps | 100 m | low | RJ45; the LAN default; susceptible to EMI |
| Twisted pair — Cat6a | 10 Gbps | 100 m | low–medium | tighter twist / shielding for 10 Gbps |
| Coaxial | 10 Mbps – ~1 Gbps | ~500 m | medium | legacy backbones; cable-broadband last mile |
| Multi-mode fiber | 10–100 Gbps | ~400 m – 2 km | medium–high | short-haul; immune to EMI; light, not electricity |
| Single-mode fiber | 100 Gbps+ | 10–100+ km | high | long-haul backbone; laser into a hair-thin core |
| Wireless (Wi-Fi 6/7) | up to several Gbps | ~tens of m indoors | low | shared medium; interference and attenuation |

Speeds and categories are standardized by **IEEE 802.3** (Ethernet) and the
**ANSI/TIA-568** structured-cabling standard; single-mode fiber by **ITU-T
G.652**. (Gbps = gigabits per second; Mbps = megabits per second.)

### Line coding: NRZ and Manchester

A cable carries a signal level, not a digit. **Line coding** is the rule that
maps bits to signal transitions. The simplest is **NRZ** (Non-Return-to-Zero):
hold the line **high for a 1 and low for a 0**, for the whole bit. Compact — but
it has a fatal flaw. Send `0000000000` and the line just sits low; with no
transitions, the receiver's clock has nothing to lock onto and slowly drifts,
until it miscounts how many zeros went by.

**Manchester** encoding fixes this by putting a **transition in the middle of
every bit**. In the **IEEE 802.3** convention a `0` is a high→low (falling) edge
at mid-bit and a `1` is a low→high (rising) edge. Because there is *always* a
mid-bit edge, the receiver recovers the clock from the signal itself — the code
is **self-clocking**. You pay for it in bandwidth: encoding one bit takes up to
two signal transitions, so the **baud rate** (signal changes per second) is
double the **bit rate** (data bits per second). That distinction matters:

- **Bit rate** — how many *data bits* you move per second.
- **Baud rate** — how many *signal symbols* you send per second. Manchester's bit
  rate is half its baud rate; NRZ's are equal.

[`code/line_coding.py`](../code/line_coding.py) encodes `10110` both ways so you
can see the mid-bit transition appear in Manchester and be absent in NRZ.

### Attenuation and why cables have length limits

As a signal travels, it gets weaker and more distorted — this is **attenuation**.
Copper attenuates faster than fiber, and higher frequencies (faster data)
attenuate faster still. Past some distance the signal is too weak for the
receiver to reliably tell a 1 from a 0, so every medium has a **maximum segment
length** — the 100 m in the table above is not arbitrary, it is the distance at
which Cat-cable Ethernet can still be decoded. To go further you must *regenerate*
the signal (a switch, repeater, or optical amplifier) — you cannot just use a
longer cable. This is why fiber, which attenuates far less, dominates long-haul.

### Collision domains: hubs vs switches

One last physical-layer idea, because it explains why the star beat the bus. A
**collision domain** is a set of devices that share one medium, where two
simultaneous transmissions **collide** and corrupt each other.

- A **hub** is a dumb repeater: a signal in one port is blasted out all the
  others. Everything plugged into a hub is **one shared collision domain** — it
  is a physical star that behaves logically like a bus.
- A **switch** is smart: it gives every port its own dedicated link and forwards
  only where a frame needs to go. Each port is **its own collision domain**, so
  two pairs of machines can talk simultaneously with no collision.

That is the real reason modern LANs are switched stars: the star's *shape* plus
the switch's *per-port isolation* removes both the single-shared-wire failure mode
*and* the collisions of the bus.

## Build It

Two self-contained programs, standard library only — no `networkx`, no external
graph package. We build the graph logic by hand so nothing is magic.

### Model and measure every topology

[`code/topologies.py`](../code/topologies.py) represents each topology as an
**adjacency map** — a plain `dict` of `{node: set(neighbours)}` — and computes the
four metrics from scratch. Connectivity and diameter both come from one primitive,
breadth-first search (BFS), that floods the graph hop by hop:

```python
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
```

Single-point-of-failure detection falls straight out of it: **remove one node,
then ask whether everyone else can still reach everyone else.** If not, that node
was a SPOF.

```python
def spof_nodes(adj):
    """Nodes whose removal disconnects the rest — single points of failure."""
    return [n for n in sorted(adj)
            if not is_connected(adj, blocked_nodes=frozenset([n]))]
```

The **diameter** is the largest shortest-path distance over all pairs: run BFS
from every node, record the farthest hop count, keep the maximum. Run it:

```bash
python3 topologies.py
```

```text
Star (hub SW + 5)
  nodes ............... 6
  links ............... 5
  degree per node ..... A:1, B:1, C:1, D:1, E:1, SW:5
  single-point-of-failure node(s) ... SW
  survives any single link loss? .... no — every link is critical
  network diameter (max hops) ....... 2

Full mesh (5)
  nodes ............... 5
  links ............... 10
  single-point-of-failure node(s) ... NONE (survives any 1 node loss)
  survives any single link loss? .... YES
  network diameter (max hops) ....... 1
```

And the summary table it prints makes the whole trade-off legible at a glance:

```text
Comparison
  Topology          | Nodes | Links | SPOF node? | 1 link cut kills? | Diameter
  ------------------+-------+-------+------------+-------------------+---------
  Bus (chain of 5)  | 5     | 4     | yes        | yes               | 4
  Ring (cycle of 5) | 5     | 5     | no         | no                | 2
  Star (hub SW + 5) | 6     | 5     | yes        | yes               | 2
  Full mesh (5)     | 5     | 10    | no         | no                | 1
  Tree (core+2+4)   | 7     | 6     | yes        | yes               | 4
```

Read across: the star buys diameter-2, isolated-failure behavior for just 5
links; the full mesh buys diameter-1 and no SPOF but pays 10 links for the same 5
hosts. That is the whole design conversation in one table.

### Encode bits into signals

[`code/line_coding.py`](../code/line_coding.py) turns the bit string `10110` into
NRZ and Manchester signal levels. Each bit is drawn as two half-bit samples so the
mid-bit transition is visible; `+1` is a high level, `-1` is low:

```python
def manchester(bits):
    """Manchester (IEEE 802.3): a transition at the MIDDLE of each bit."""
    samples = []
    for bit in bits:
        if bit == "1":
            samples.append((LOW, HIGH))   # rising edge at mid-bit
        else:
            samples.append((HIGH, LOW))   # falling edge at mid-bit
    return samples
```

Run it and watch NRZ sit flat within each bit while Manchester flips in the
middle of every one:

```bash
python3 line_coding.py
```

```text
NRZ-L (Non-Return-to-Zero, Level)
  levels ...  +1 +1 -1 -1 +1 +1 +1 +1 -1 -1
  waveform .. ‾‾‾‾____‾‾‾‾‾‾‾‾____

Manchester (IEEE 802.3 convention)
  levels ...  -1 +1 +1 -1 -1 +1 -1 +1 +1 -1
  waveform .. __‾‾‾‾____‾‾__‾‾‾‾__

Per-bit mid-bit transition (why Manchester self-clocks):
   bit | NRZ-L                      | Manchester
     1 | none  (NOT self-clocking)  | rising (low->high)
     0 | none  (NOT self-clocking)  | falling (high->low)
```

In NRZ every "transition" column is *none* — a long run of one bit value gives
the receiver nothing to sync on. In Manchester every bit has an edge, so the clock
rides along for free.

## Use It

You will almost never hand-roll line coding or measure a graph diameter in
application code — the physical layer is handled by hardware and drivers. But two
things carry directly into how you build and reason about backends.

**First, `struct` is the same tool the real stack uses.** In the transport lesson
you will decode TCP and UDP headers with `struct`; here the same idea applies one
layer down, because every physical standard is ultimately a byte/bit layout. The
graph model, too, is not a toy: the algorithms in `topologies.py` — BFS,
articulation-point (SPOF) detection, diameter — are exactly what real tools run.
The standard library ships a graph you can sanity-check against:

```python
# The stdlib doesn't ship a graph library, but it ships enough to build one.
from collections import deque   # the BFS queue you used above

# Production network tooling (e.g. how a switch's spanning-tree protocol avoids
# loops, or how a monitoring system finds a SPOF link) runs these same graph
# algorithms at scale — you just built the core of them by hand.
```

**Second, the topology decision is an operational one you will actually make.**
When you design a service's deployment — how many availability zones, whether the
load balancer is redundant, whether your database has a replica — you are choosing
a topology and reasoning about SPOFs and diameter, exactly like the table above.
"Is there a single box whose failure takes everything down?" is the `spof_nodes`
question, asked about your infrastructure. The physical layer is where that habit
of thinking starts.

## Ship It

The artifact for this lesson is a topology-and-cabling decision prompt:
[`outputs/prompt-topology-cabling-choice.md`](../outputs/prompt-topology-cabling-choice.md).
Give it a scenario — number of nodes, distances, budget, resilience needs — and it
walks from requirements to a recommended topology and cable medium, naming the
SPOFs you are accepting and the failure behavior you are buying. You can trust its
reasoning because you just computed the same metrics by hand.

## Key takeaways

- The **physical layer** moves raw bits as a physical **signal** (voltage, light,
  or radio) over a **medium**; it knows nothing about addresses or packets.
- **Topology** is the shape of the wiring, and it decides cost, failure behavior,
  and latency. The **star** — every node to a central switch — wins the modern LAN
  because a single node/cable failure is isolated and the diameter is a constant
  **2**, for only `n` links; its one weakness is the central device as a **single
  point of failure**.
- A **full mesh** gives maximum resilience (no SPOF, diameter 1) but costs
  **`n(n-1)/2`** links; a **bus** is cheapest but any break kills it; a **ring**
  survives one failure; a **tree** is stars-of-stars and inherits the star's SPOF
  at each level.
- **Media** trade speed, distance, and cost: twisted-pair copper (~100 m, cheap,
  EMI-prone), coax, and **fiber** (light, immune to EMI, huge bandwidth,
  single-mode for long-haul), plus wireless.
- **Line coding** maps bits to transitions: **NRZ** is compact but not
  self-clocking; **Manchester** guarantees a mid-bit transition so it is
  self-clocking, at the cost of double the baud rate.
- Signals **attenuate**, which is why every medium has a **maximum cable length**;
  and a **hub** is one shared collision domain while a **switch** gives every port
  its own — the real reason switched stars replaced the bus.
