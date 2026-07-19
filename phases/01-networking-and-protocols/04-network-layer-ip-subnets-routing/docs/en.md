# The Network Layer: IP, Subnets & Routing

> The link layer moves a frame to the machine next to you. The network layer moves a packet to a machine on the far side of the planet — across networks it has never seen — using one global addressing scheme and one decision repeated at every hop.

**Type:** Build
**Languages:** Python
**Prerequisites:** Phase 1 · Lessons 01–03 — the OSI / TCP-IP layered models and the link layer. You should know that a MAC (Media Access Control) address is a hardware address that only has meaning on the local link.
**Time:** ~75 minutes

## The Problem

A MAC address gets a frame to the machine on the *same* wire or Wi-Fi. But the
server you want is on a different network, behind a different router, in a
different country. Its MAC address is meaningless to your laptop — MAC addresses
don't leave the local link, and there is no global directory of them.

So how does a packet cross dozens of independent networks it was never told
about, run by companies that have never coordinated, and still arrive at exactly
the right machine? And once it arrives at a network, how does that network know
which of its thousands of hosts owns the address — without a lookup table with a
row per machine?

Both answers are the job of **the network layer** — layer 3. It gives every
machine a **logical address** (an IP address) that is independent of its
hardware, groups those addresses into **subnets** with pure arithmetic, and lets
every router forward a packet knowing only *one* thing: which direction is more
specific. By the end of this lesson you will have computed a subnet by hand,
built and checksummed a real IP header, and written the longest-prefix-match loop
that is the beating heart of every router on Earth.

## The Concept

The link layer is a street: it can shout to any house it can see. The network
layer is the postal system: a hierarchical address (`country → city → street →
house`) that lets a letter cross carriers that never coordinate, each one only
deciding "which bag is this closer to?" — never the whole route at once.

### IP addresses: a logical, routable identity

An **IP (Internet Protocol) address** identifies a machine independent of its
hardware. Two versions are in use:

- **IPv4** (RFC 791) is **32 bits**, written as four dotted decimals — `192.168.1.10` — each byte `0`–`255`. That is only ~4.3 billion addresses, which the world ran out of.
- **IPv6** (RFC 4291) is **128 bits**, written as eight hex groups — `2001:0db8:0000:0000:0000:ff00:0042:8329`, shortened to `2001:db8::ff00:42:8329`. Enough addresses to number every atom on the planet's surface many times over.

The key difference from a MAC address: an IP address is **hierarchical and
routable**. Its leading bits name a *network* and its trailing bits name a *host*
within that network, so a router can reason about millions of hosts by looking at
a network *prefix* instead of memorizing individual addresses. This lesson builds
in IPv4 because its 32 bits fit in one integer you can hold in your head; every
idea carries straight over to IPv6's 128.

### The IPv4 header: what every packet carries

Before an IP packet's payload comes a **header** — 20 bytes without options — that
tells every router how to handle it. These are the fields you will pack and parse
in `code/ipv4_header.py`:

| Field | Size | What it does |
|---|---|---|
| Version | 4 bits | `4` for IPv4, `6` for IPv6 |
| IHL (Internet Header Length) | 4 bits | Header length in 32-bit words (`5` = 20 bytes) |
| Type of Service (DSCP + ECN) | 8 bits | Priority / congestion hints |
| Total Length | 16 bits | Header + payload length in bytes |
| Identification | 16 bits | Groups fragments of one original packet |
| Flags + Fragment Offset | 3 + 13 bits | Controls and locates fragmentation |
| TTL (Time To Live) | 8 bits | Hop budget; each router decrements it by 1 |
| Protocol | 8 bits | What's inside: `1` = ICMP, `6` = TCP, `17` = UDP |
| Header Checksum | 16 bits | Error detection over the header only |
| Source Address | 32 bits | Who sent it |
| Destination Address | 32 bits | Where it's going |
| Options | 0–320 bits | Rarely used (timestamps, routing hints) |

The **TTL** is why packets can't loop forever: every hop subtracts 1, and a
packet that reaches `0` is dropped. The **header checksum** is recomputed at every
hop (because the TTL just changed) using the one's-complement algorithm (RFC
1071) you'll implement.

### Subnetting: splitting an address into network and host

A **subnet mask** is a run of `1` bits marking the network portion, followed by
`0` bits marking the host portion. **CIDR (Classless Inter-Domain Routing,** RFC
4632**)** notation writes the mask as a slash and a count of network bits: `/24`
means 24 network bits, i.e. mask `255.255.255.0`.

Given an address and a prefix, four values fall out of pure bit-math:

- **Network address** — host bits all `0` (the address AND the mask). Names the subnet itself.
- **Broadcast address** — host bits all `1` (network OR the inverted mask). Reaches every host at once.
- **Usable host range** — everything strictly between them; the network and broadcast addresses can't be assigned to a machine.
- **Host count** — `2^(32 − prefix) − 2` (subtract the network and broadcast addresses).

Here is a full `/26` worked out — a `192.168.1.0/24` network split into four
equal quarters, showing the third quarter:

| Property | Value |
|---|---|
| CIDR block | `192.168.1.128/26` |
| Netmask | `255.255.255.192` |
| Network address | `192.168.1.128` |
| First usable host | `192.168.1.129` |
| Last usable host | `192.168.1.190` |
| Broadcast address | `192.168.1.191` |
| Usable hosts | `2^(32−26) − 2 = 62` |

Some ranges are **private** (RFC 1918) — reusable inside any network and never
routed on the public internet: `10.0.0.0/8`, `172.16.0.0/12`, and
`192.168.0.0/16`. The `192.168.1.10` on your laptop is almost certainly one of
these, shared by millions of home networks at once.

### NAT: how a private address reaches the internet

If private addresses aren't routed publicly, how does your laptop load a web
page? **NAT (Network Address Translation)** — your router rewrites the packet's
private source address (`192.168.1.10`) to its own single public address on the
way out, remembers the mapping, and rewrites the reply back on the way in. One
public address fronts an entire private network, which is the workaround that let
IPv4 survive address exhaustion.

### Routing: longest-prefix match chooses the next hop

No router knows the whole path to a destination. Each one knows only its
**routing table** — a list of `(CIDR block, next hop)` entries — and makes a
single local decision: of all the entries whose network *contains* the
destination, forward to the **most specific** one, i.e. the match with the
**longest prefix**. A longer prefix means a smaller, more precise network.

The **default route** `0.0.0.0/0` has a prefix of `0`, so it matches *every*
address but always loses to any more-specific route. It is the fallback — the
**default gateway** a packet takes when nothing more specific applies. This is
exactly the decision in `code/routing_table.py`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 582" width="100%" style="max-width:780px" role="img" aria-label="Longest-prefix-match routing decision as a flowchart. A packet arrives with a destination IP. The router finds every route whose network contains the destination. If none match, it drops the packet and sends an ICMP net-unreachable message. If some match, it keeps only the match with the longest prefix, then checks whether that longest match is the default route 0.0.0.0/0: if so it forwards to the default gateway, otherwise it forwards to that route's next hop.">
  <defs>
    <marker id="l04-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="400" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">Longest-prefix match: one local decision at every hop</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- arrows -->
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M400 92 L400 127"  marker-end="url(#l04-ar)"/>
      <path d="M400 172 L400 200" marker-end="url(#l04-ar)"/>
      <path d="M336 235 L262 235" marker-end="url(#l04-ar)"/>
      <path d="M400 269 L400 297" marker-end="url(#l04-ar)"/>
      <path d="M400 342 L400 370" marker-end="url(#l04-ar)"/>
      <path d="M474 415 L548 415" marker-end="url(#l04-ar)"/>
      <path d="M400 459 L400 482" marker-end="url(#l04-ar)"/>
    </g>
    <!-- branch labels -->
    <g fill="currentColor" font-size="9.5" font-weight="700">
      <text x="299" y="228" text-anchor="middle" fill="#d64545">No</text>
      <text x="411" y="288" text-anchor="start" fill="#0fa07f">Yes</text>
      <text x="510" y="408" text-anchor="middle" fill="#0fa07f">Yes</text>
      <text x="411" y="475" text-anchor="start" fill="#0fa07f">No</text>
    </g>

    <!-- process boxes -->
    <g stroke-width="1.8" stroke-linejoin="round">
      <rect x="285" y="48"  width="230" height="44" rx="10" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
      <rect x="270" y="128" width="260" height="44" rx="10" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
      <rect x="40"  y="213" width="220" height="44" rx="10" fill="#d64545" fill-opacity="0.12" stroke="#d64545"/>
      <rect x="282" y="298" width="236" height="44" rx="10" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
      <rect x="550" y="393" width="200" height="44" rx="10" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="285" y="483" width="230" height="44" rx="10" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    </g>

    <!-- decision diamonds -->
    <g stroke-width="1.8" stroke-linejoin="round" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f">
      <path d="M400 201 L464 235 L400 269 L336 235 Z"/>
      <path d="M400 371 L474 415 L400 459 L326 415 Z"/>
    </g>

    <!-- box text -->
    <g fill="currentColor" text-anchor="middle" font-size="10.5">
      <text x="400" y="66">Packet arrives with a</text>
      <text x="400" y="80">destination IP</text>
      <text x="400" y="146">Find every route whose</text>
      <text x="400" y="160">network contains the destination</text>
      <text x="150" y="231">Drop packet, send</text>
      <text x="150" y="245">ICMP 'net unreachable'</text>
      <text x="400" y="316">Keep only the match</text>
      <text x="400" y="330">with the longest prefix</text>
      <text x="650" y="411">Forward to the</text>
      <text x="650" y="425">default gateway</text>
      <text x="400" y="501">Forward to that route's</text>
      <text x="400" y="515">next hop</text>
    </g>

    <!-- decision text -->
    <g fill="currentColor" text-anchor="middle" font-size="10">
      <text x="400" y="239" font-weight="700">Any matches?</text>
      <text x="400" y="411" font-weight="700">Longest match</text>
      <text x="400" y="425" font-weight="700">is 0.0.0.0/0?</text>
    </g>

    <!-- takeaway -->
    <text x="400" y="562" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">One rule per hop: the most specific containing route wins, with 0.0.0.0/0 as the fallback.</text>
  </g>
</svg>
```

For destination `10.1.2.55` against a table holding `10.0.0.0/8`, `10.1.0.0/16`,
and `10.1.2.0/24`, all three match — but `/24` is the longest, so it wins. Change
the destination to `10.1.9.9` and the `/24` no longer contains it, so `/16` takes
over. That single rule, run independently at every hop, is how the internet
routes without any router knowing the full map.

### ICMP: the network layer's own signalling

**ICMP (Internet Control Message Protocol,** RFC 792**)** is how the network layer
reports problems and answers diagnostics — it rides *inside* IP (protocol number
`1`) but carries no user data. Two everyday tools are built on it:

- **`ping`** sends an ICMP *echo request*; the target replies with an *echo reply*. A reply proves the path works both ways.
- **`traceroute`** is a clever abuse of the TTL. It sends packets with TTL `1`, then `2`, then `3`… Each router that decrements the TTL to `0` drops the packet and sends back an ICMP *time-exceeded* message — revealing its address. Increasing the TTL one step at a time makes each successive hop announce itself, mapping the whole path.

## Build It

The full implementations are in [`code/`](../code/). Each file is
self-contained, derives its answers with raw bit-math, and — where a stdlib
equivalent exists — cross-checks against Python's `ipaddress` module so you can
trust the hand math. Run them and watch layer 3 come apart into arithmetic.

### Subnet math, by hand and cross-checked

[`code/subnet.py`](../code/subnet.py). An IP address is just a 32-bit integer, and
every subnet field is one bitwise operation on it. The mask is `prefix` ones
shifted up into place; ANDing zeroes the host bits, ORing the inverted mask sets
them:

```python
ALL_ONES = 0xFFFFFFFF
netmask   = (ALL_ONES << (32 - prefix)) & ALL_ONES   # e.g. /26 -> 255.255.255.192
network   = ip & netmask                             # host bits -> 0
broadcast = network | (~netmask & ALL_ONES)          # host bits -> 1
host_count = (1 << (32 - prefix)) - 2                # minus network + broadcast
```

Every result is then asserted equal to what `ipaddress.ip_network(...)` produces,
so the hand math is verified, not just plausible. Run it:

```bash
python code/subnet.py
```

It prints the network, broadcast, usable range, and count for a `/24`, a `/26`,
and a `/30`, each with `bit-math == ipaddress: OK`.

### An IPv4 header, packed and checksummed

[`code/ipv4_header.py`](../code/ipv4_header.py). The header is a fixed byte layout,
so `struct` packs it directly. The one subtlety is the **checksum**: you build the
header with the checksum field set to `0`, compute the one's-complement sum over
those bytes, then write it back:

```python
def checksum(data: bytes) -> int:
    total = 0
    for i in range(0, len(data), 2):
        total += (data[i] << 8) | data[i + 1]   # sum 16-bit words
    while total >> 16:                            # fold the carries back in
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF                       # one's complement
```

The neat property: recomputing the checksum over the *whole* header — this time
with the checksum field filled in — yields `0` when nothing is corrupted, which
is exactly how a receiver validates it. Run it:

```bash
python code/ipv4_header.py
```

It prints every field of a real ICMP packet's IP header and confirms
`checksum verification: OK`.

### The routing decision, longest-prefix match

[`code/routing_table.py`](../code/routing_table.py). A route matches when the
destination's network bits equal the route's network bits; among all matches, the
longest prefix wins:

```python
def longest_prefix_match(dest, table):
    dest_int = ip_to_int(dest)
    best, best_prefix = None, -1
    for cidr, next_hop in table:
        network_int, prefix, mask = parse_cidr(cidr)   # 'network/prefix' -> bits
        if (dest_int & mask) == network_int and prefix > best_prefix:
            best, best_prefix = (cidr, next_hop), prefix   # more specific wins
    return best
```

Run it against a five-entry table:

```bash
python code/routing_table.py
```

Watch `10.1.2.55` land on the `/24`, `10.1.9.9` fall back to the `/16`,
`10.9.9.9` to the `/8`, and `8.8.8.8` — matching nothing specific — take the
default route `0.0.0.0/0`. Same table, four different next hops, one rule.

## Use It

You almost never do this arithmetic by hand in production — Python's `ipaddress`
module (standard library since 3.3) is the tool that wraps all of it, and it is
what the Build-It code cross-checks against:

```python
import ipaddress

net = ipaddress.ip_network("192.168.1.0/24")
print(net.network_address)     # 192.168.1.0
print(net.broadcast_address)   # 192.168.1.255
print(net.num_addresses - 2)   # 254 usable hosts
print(ipaddress.ip_address("192.168.1.10") in net)  # True — a containment test

# Longest-prefix match is one sort key away:
routes = [ipaddress.ip_network(c) for c in ("0.0.0.0/0", "10.0.0.0/8", "10.1.2.0/24")]
dest = ipaddress.ip_address("10.1.2.55")
best = max((r for r in routes if dest in r), key=lambda r: r.prefixlen)
print(best)                    # 10.1.2.0/24
```

`ip_network`, `ip_address`, the `in` containment test, and `.prefixlen` collapse
everything you built into a handful of lines — but you now know precisely what
each one does at the bit level, so it is a convenience, not magic. On real
machines the routing table lives in the kernel; you inspect it with `ip route`
(Linux) or `netstat -rn`, and every line you see is a `(CIDR, next hop)` entry
resolved by the exact longest-prefix rule you wrote.

## Ship It

The artifact for this lesson is a subnet-and-routing triage prompt:
[`outputs/prompt-subnet-routing-triage.md`](../outputs/prompt-subnet-routing-triage.md) —
it walks from a symptom ("can't reach that host", "wrong subnet mask", "packets
die a few hops out", "works by IP but the private range collides") to the
network-layer mechanism responsible: subnet boundaries, the routing table, TTL
expiry, NAT, or ICMP being filtered. You can reason about each because you just
built the arithmetic underneath them.

## Key takeaways

- The network layer delivers packets **machine to machine across networks** using logical **IP addresses** (IPv4 = 32 bits, IPv6 = 128), which — unlike link-local MAC addresses — are hierarchical and routable.
- An IPv4 packet carries a **20-byte header** whose **TTL** stops loops and whose **header checksum** (recomputed every hop) catches corruption.
- A **subnet mask / CIDR prefix** splits an address into network and host bits; the network, broadcast, usable range, and host count (`2^(32−prefix) − 2`) all fall out of AND / OR bit-math. **RFC 1918** ranges are private and reached publicly via **NAT**.
- Routers forward by **longest-prefix match**: the most specific containing route wins, with `0.0.0.0/0` (the **default gateway**) as the catch-all fallback.
- **ICMP** carries the network layer's own signalling — `ping` (echo) and `traceroute` (expiring TTLs) are both built on it.
