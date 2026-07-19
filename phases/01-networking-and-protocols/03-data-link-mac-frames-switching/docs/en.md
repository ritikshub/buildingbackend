# The Data Link Layer: MAC, Frames & Switching

> The network layer knows how to reach a machine across the whole internet. But the very first hop — from your laptop to the box on the other end of the cable — is handled one layer down, by hardware addresses and frames you can build by hand.

**Type:** Build
**Languages:** Python
**Prerequisites:** Lessons 01–02 — the physical layer (bits on a wire) and the layered model. You should know that data travels in chunks and that a network has more than one machine on it.
**Time:** ~60 minutes

## The Problem

Picture the simplest possible network: a few computers plugged into the same
switch in a room. One of them wants to send data to another. But the wire it
shares carries only raw bits — it has no idea what a "computer" is, let alone
which one you mean.

So two questions have to be answered before a single useful byte moves:

1. **Who is this for?** Every machine on the local wire needs a name the hardware
   understands, so a receiver can tell "this is addressed to me" from "this is for
   my neighbor."
2. **How do I know I got it intact?** Wires pick up electrical noise. A bit that
   left as `1` can arrive as `0`. The receiver needs a way to *detect* that the
   bits it got are not the bits that were sent, and throw the bad ones away.

These are the jobs of the **data link layer** — layer 2, the one directly above
the physical wire. It groups bits into **frames** (the layer-2 unit of data),
addresses each frame with a **MAC** (Media Access Control) address, checks each
frame for corruption, and — when a **switch** is involved — delivers each frame
to exactly the machine it is for instead of shouting it at everyone. By the end
of this lesson you will have built an Ethernet frame byte by byte and simulated
the switch that learns where everyone lives.

## The Concept

The network layer (which you meet later) worries about reaching a machine
*anywhere*. The data link layer only cares about the **next hop**: moving one
frame between two nodes on the *same* physical network. Everything below is about
how it names, packages, checks, and steers those frames.

### MAC addresses: the hardware's name for a machine

A **MAC address** is a 48-bit (6-byte) number burned into a network interface at
the factory. Written for humans, it is six pairs of hexadecimal digits — each
pair one byte — separated by colons:

| `00:1a:2b` | `3c:4d:5e` |
|---|---|
| **OUI** (first 3 bytes) — the vendor | device-specific (last 3 bytes) |

The first three bytes are the **OUI** (Organizationally Unique Identifier): a
block the IEEE (Institute of Electrical and Electronics Engineers) assigns to a
hardware vendor. So `00:1a:2b` tells you *who made the card*; the last three
bytes are that vendor's serial-number-like value for the specific device. The
combination is meant to be globally unique.

One MAC address is special. `ff:ff:ff:ff:ff:ff` — all bits set — is the
**broadcast address**: a frame sent to it is meant for *every* machine on the
local network at once. We will need it in a moment.

Unlike an IP address (which changes when you move to a new network), a MAC
address travels with the hardware and only ever has to be unique on the *local*
link.

### The Ethernet II frame: fields with fixed sizes

**Ethernet** (standardized as IEEE 802.3) is the dominant layer-2 technology on
wired networks. It wraps your data in a **frame** with a fixed layout, so any
receiver can find each field by counting bytes. The common "Ethernet II" frame
looks like this:

| Field | Size | What it holds |
|---|---|---|
| Destination MAC | 6 bytes | Who the frame is for (a MAC, or the broadcast address) |
| Source MAC | 6 bytes | Who sent it |
| EtherType | 2 bytes | Which protocol the payload is (`0x0800` = IPv4, `0x0806` = ARP, `0x86DD` = IPv6) |
| Payload | 46–1500 bytes | The actual data (e.g. an IP packet) |
| FCS | 4 bytes | Frame Check Sequence — a checksum over everything above |

Two numbers in that table matter beyond the layout:

- The payload maxes out at **1500 bytes**. That ceiling is the **MTU** (Maximum
  Transmission Unit) — the largest chunk one frame can carry. Data bigger than
  the MTU must be split into multiple frames higher up.
- The payload has a *minimum* of **46 bytes**, which makes the smallest legal
  frame `6 + 6 + 2 + 46 + 4 = 64` bytes. If your data is shorter, it is padded
  with zeros up to the minimum. (This minimum comes from how collisions were
  detected on old shared Ethernet.)

The **EtherType** is the glue between layers: when a frame arrives and passes its
checksum, the receiver reads this 2-byte field to decide *who gets the payload* —
hand `0x0800` to the IPv4 code, hand `0x0806` to the ARP code.

### Hubs vs. switches: flooding vs. learning

How does a frame get from the sender's port to the right receiver's port? That
depends entirely on the box in the middle.

A **hub** is the dumb version: every bit that arrives on one port is copied to
*all* the other ports. Machine A talks and machines B, C, and D all hear it, then
throw away anything not addressed to them. Because everyone shares one wire, only
one machine can talk at a time — the whole hub is a single **collision domain**,
and two machines transmitting at once *collide* and must retry.

A **switch** is the smart version. It **learns**. Every frame that arrives tells
the switch one fact for free: *the sender's MAC address lives behind the port
this frame came in on.* The switch records that in a **MAC table** (also called a
CAM table, for Content-Addressable Memory). Once it knows where a destination
lives, it forwards the frame out **only that one port** — a private conversation,
no collision with anyone else.

The one time a switch still floods (copies to every other port) is when it
*doesn't* know where the destination is yet, or when the destination is the
broadcast address:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 400" width="100%" style="max-width:780px" role="img" aria-label="A switch's forwarding decision as a flowchart. A frame arrives on a port. The switch first learns that the source MAC lives on the port the frame came in on. Then it checks the destination MAC. If the destination is the broadcast address ff:ff:ff:ff:ff:ff, or if it is not yet in the MAC table, the switch floods the frame to all other ports. If the destination is known in the MAC table, the switch forwards the frame out only that one port.">
  <defs>
    <marker id="l03a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="400" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="13.5" font-weight="700" fill="currentColor">A switch's forwarding decision: learn, then flood or forward</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- vertical spine boxes -->
    <g stroke-width="1.6" stroke-linejoin="round">
      <rect x="300" y="46" width="200" height="32" rx="9" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
      <rect x="270" y="96" width="260" height="44" rx="9" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
    </g>
    <text x="400" y="66" text-anchor="middle" font-size="10" fill="currentColor">Frame arrives on a port</text>
    <text x="400" y="113" text-anchor="middle" font-size="10" fill="currentColor">Learn: source MAC</text>
    <text x="400" y="129" text-anchor="middle" font-size="10" fill="currentColor">lives on this in-port</text>

    <!-- decision diamond -->
    <path d="M400,150 L498,188 L400,226 L302,188 Z" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.6" stroke-linejoin="round"/>
    <text x="400" y="192" text-anchor="middle" font-size="10.5" font-weight="700" fill="currentColor">Destination MAC?</text>

    <!-- spine arrows -->
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M400,78 L400,94" marker-end="url(#l03a-ar)"/>
      <path d="M400,140 L400,148" marker-end="url(#l03a-ar)"/>
    </g>

    <!-- outcome boxes -->
    <g stroke-width="1.8" stroke-linejoin="round">
      <rect x="95" y="312" width="250" height="50" rx="11" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
      <rect x="470" y="312" width="290" height="50" rx="11" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
    </g>
    <text x="220" y="335" text-anchor="middle" font-size="13" font-weight="700" fill="#e0930f">FLOOD</text>
    <text x="220" y="351" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">to all other ports</text>
    <text x="615" y="335" text-anchor="middle" font-size="13" font-weight="700" fill="#0fa07f">FORWARD</text>
    <text x="615" y="351" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">out that one port only</text>

    <!-- branch arrows -->
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M302,188 L185,308" marker-end="url(#l03a-ar)"/>
      <path d="M400,226 L285,308" marker-end="url(#l03a-ar)"/>
      <path d="M498,188 L560,308" marker-end="url(#l03a-ar)"/>
    </g>

    <!-- branch labels -->
    <g font-size="9" fill="currentColor" opacity="0.85" text-anchor="middle">
      <text x="150" y="246">Broadcast ff:ff:&#8230;</text>
      <text x="432" y="260">Not in MAC table</text>
      <text x="600" y="253">Known in MAC table</text>
    </g>

    <text x="400" y="388" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">Learn the source first; forward when the port is known, flood when it is not.</text>
  </g>
</svg>
```

Here is the payoff over a few frames. Watch the table fill and the behavior
switch from flooding to forwarding:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 418" width="100%" style="max-width:780px" role="img" aria-label="A switch learning over three frames between Host A on port 1 and Host B on port 2. First A sends a frame for B: the switch learns A is on port 1, but B is unknown, so it floods the frame to every other port. Then B replies with a frame for A: the switch learns B is on port 2, and since A is already known it forwards only out port 1. Finally A sends to B again: B is now known, so the switch forwards only out port 2 with no flooding.">
  <defs>
    <marker id="l03b-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="400" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">The MAC table fills up: flooding gives way to forwarding</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- actor headers -->
    <g stroke-width="1.7" stroke-linejoin="round">
      <rect x="70"  y="40" width="120" height="36" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="340" y="40" width="120" height="36" rx="8" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
      <rect x="610" y="40" width="120" height="36" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    </g>
    <text x="130" y="58" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">Host A</text>
    <text x="130" y="70" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">port 1</text>
    <text x="400" y="58" text-anchor="middle" font-size="11.5" font-weight="700" fill="#7c5cff">Switch</text>
    <text x="400" y="70" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">MAC table</text>
    <text x="670" y="58" text-anchor="middle" font-size="11.5" font-weight="700" fill="#0fa07f">Host B</text>
    <text x="670" y="70" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">port 2</text>

    <!-- lifelines -->
    <g stroke="currentColor" stroke-opacity="0.25" stroke-width="1.3" stroke-dasharray="4 5">
      <path d="M130 76 L130 382"/>
      <path d="M400 76 L400 382"/>
      <path d="M670 76 L670 382"/>
    </g>

    <!-- message arrows -->
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M136 104 L394 104" marker-end="url(#l03b-ar)"/>
      <path d="M406 166 L664 166" marker-end="url(#l03b-ar)"/>
      <path d="M664 196 L406 196" marker-end="url(#l03b-ar)"/>
      <path d="M394 258 L136 258" marker-end="url(#l03b-ar)"/>
      <path d="M136 288 L394 288" marker-end="url(#l03b-ar)"/>
      <path d="M406 350 L664 350" marker-end="url(#l03b-ar)"/>
    </g>
    <g fill="currentColor" text-anchor="middle" font-size="9">
      <text x="265" y="98">frame A &#8594; B</text>
      <text x="535" y="160">flood: every other port</text>
      <text x="265" y="190">frame B &#8594; A</text>
      <text x="265" y="252">forward: only out port 1</text>
      <text x="265" y="282">frame A &#8594; B</text>
      <text x="535" y="344">forward: only out port 2</text>
    </g>

    <!-- note bands over the switch -->
    <rect x="250" y="116" width="300" height="26" rx="6" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f" stroke-opacity="0.6" stroke-width="1"/>
    <text x="400" y="133" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.9">learns A &#8594; port 1 &#183; B unknown &#8594; FLOOD</text>
    <rect x="250" y="208" width="300" height="26" rx="6" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f" stroke-opacity="0.6" stroke-width="1"/>
    <text x="400" y="225" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.9">learns B &#8594; port 2 &#183; A known &#8594; FORWARD</text>
    <rect x="250" y="300" width="300" height="26" rx="6" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f" stroke-opacity="0.6" stroke-width="1"/>
    <text x="400" y="317" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.9">B now known &#8594; FORWARD &#183; no flooding</text>

    <text x="400" y="404" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">Every frame teaches the switch one MAC &#8212; soon it steers each one to a single port.</text>
  </g>
</svg>
```

### ARP: finding the MAC behind an IP

There is a gap to close. Software up the stack wants to send to an **IP address**
like `10.0.0.5`, but a frame needs a *MAC* address in its destination field. How
does a host translate one into the other on the local network?

That is the job of **ARP** (Address Resolution Protocol, RFC 826). It is beautifully
simple: **ask everyone, and let the owner answer.** The host broadcasts a
question to `ff:ff:ff:ff:ff:ff` — "who has `10.0.0.5`? tell me your MAC" — every
machine on the link receives it, and only the one that owns that IP replies
directly with its MAC address:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 316" width="100%" style="max-width:780px" role="img" aria-label="ARP resolving an IP to a MAC on the local link. Host A at 10.0.0.1 broadcasts an ARP request to everyone on the link asking who has 10.0.0.5. Every host on the link hears the request, but only the owner answers. Host B at 10.0.0.5 replies with a unicast ARP reply saying 10.0.0.5 is at 00:1a:2b:00:00:0b. Host A then caches the mapping from 10.0.0.5 to that MAC address.">
  <defs>
    <marker id="l03c-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="400" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">ARP: ask the whole link, let the owner answer</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- actor headers -->
    <g stroke-width="1.7" stroke-linejoin="round">
      <rect x="70"  y="42" width="120" height="36" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="340" y="42" width="120" height="36" rx="8" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/>
      <rect x="610" y="42" width="120" height="36" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    </g>
    <text x="130" y="60" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">Host A</text>
    <text x="130" y="72" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">10.0.0.1</text>
    <text x="400" y="60" text-anchor="middle" font-size="11" font-weight="700" fill="#e0930f">Everyone</text>
    <text x="400" y="72" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">on the link</text>
    <text x="670" y="60" text-anchor="middle" font-size="11.5" font-weight="700" fill="#0fa07f">Host B</text>
    <text x="670" y="72" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">10.0.0.5</text>

    <!-- lifelines -->
    <g stroke="currentColor" stroke-opacity="0.25" stroke-width="1.3" stroke-dasharray="4 5">
      <path d="M130 78 L130 258"/>
      <path d="M400 78 L400 258"/>
      <path d="M670 78 L670 258"/>
    </g>

    <!-- broadcast request -->
    <path d="M136 118 L394 118" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l03c-ar)"/>
    <text x="265" y="112" text-anchor="middle" font-size="9" fill="currentColor">ARP request &#183; "Who has 10.0.0.5?"</text>

    <!-- note over everyone -->
    <rect x="250" y="130" width="300" height="26" rx="6" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f" stroke-opacity="0.6" stroke-width="1"/>
    <text x="400" y="147" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.9">every host hears it &#8212; only the owner replies</text>

    <!-- unicast reply -->
    <path d="M664 196 L136 196" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l03c-ar)"/>
    <text x="400" y="190" text-anchor="middle" font-size="8.5" fill="currentColor">ARP reply (unicast) &#183; "10.0.0.5 is at 00:1a:2b:00:00:0b"</text>

    <!-- note over A: cache -->
    <rect x="20" y="210" width="250" height="26" rx="6" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-opacity="0.6" stroke-width="1"/>
    <text x="145" y="227" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.9">caches 10.0.0.5 &#8594; 00:1a:2b:00:00:0b</text>

    <text x="400" y="298" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">One broadcast resolves the MAC; the cached answer skips the question next time.</text>
  </g>
</svg>
```

To avoid broadcasting before every single frame, the answer is stored in an **ARP
cache** for a while. You can see yours right now with `ip neigh` (Linux) or
`arp -a` (macOS/Windows).

### FCS: catching corrupted frames

The last 4 bytes of the frame are the **FCS** (Frame Check Sequence), and they
answer the second question from the top: *did this arrive intact?* The FCS is a
**CRC** (Cyclic Redundancy Check) — a number mathematically derived from all the
other bytes in the frame.

The sender computes the CRC over the frame and writes it into the FCS field. The
receiver runs the *exact same* computation over the bytes it got and compares. If
even one bit flipped in transit, the recomputed CRC won't match the stored FCS,
and the receiver **silently drops the frame**. Layer 2 does not fix the error or
ask for a resend — it just guarantees you never hand corrupted bits upward. (Any
retransmission is a *higher* layer's job, which is exactly what TCP does in a
later lesson.)

## Build It

The full implementations are in [`code/`](../code/). Each file is self-contained,
uses only the standard library (`struct` and `zlib`), runs to completion, and
exits. Together they cover the two things a switch handles: the *shape* of a
frame and the *decision* of where to send it.

### Build and parse an Ethernet frame

[`code/ethernet_frame.py`](../code/ethernet_frame.py) packs the five fields into
bytes with `struct`, appends a CRC-32 FCS, then parses the raw bytes back —
formatting the MACs as colon-hex and decoding the EtherType to a protocol name.
The heart of it is one pack and one unpack:

```python
import struct, zlib

HEADER = ">6s 6s H"   # dst MAC (6), src MAC (6), EtherType (2), network byte order

def build_frame(dst, src, ethertype, payload):
    if len(payload) < 46:                       # pad up to the 46-byte minimum
        payload += b"\x00" * (46 - len(payload))
    body = struct.pack(HEADER, mac_to_bytes(dst), mac_to_bytes(src), ethertype) + payload
    fcs = zlib.crc32(body) & 0xFFFFFFFF          # the Frame Check Sequence
    return body + struct.pack(">I", fcs)
```

Parsing is the mirror image: unpack the header, slice out the payload, and
recompute the CRC over everything-but-the-FCS to verify nothing changed. The
demo builds a real frame, prints every decoded field, then **flips one bit** and
shows the receiver's checksum reject it:

```bash
python3 ethernet_frame.py
```

Seeing `FCS check ... OK` become `FCS check ... FAIL` after a single flipped bit
is the whole point of the FCS made concrete.

### Simulate a learning switch

[`code/learning_switch.py`](../code/learning_switch.py) is the decision half. It
feeds a scripted list of `(source MAC, destination MAC, in-port)` frames through
a switch that keeps a MAC table. For each frame it does the two steps in order —
learn the source, then decide — and prints `FORWARD` or `FLOOD`:

```python
def process(self, src_mac, dst_mac, in_port):
    self.mac_table[src_mac] = in_port            # 1. LEARN the source's location
    if dst_mac == BROADCAST or dst_mac not in self.mac_table:
        action = "FLOOD"                         # 2a. unknown/broadcast -> all ports
    else:
        action = "FORWARD"                       # 2b. known -> the one right port
```

Run it and watch the same source-destination pair flood the first time and
forward the second, once the table has been learned:

```bash
python3 learning_switch.py
```

## Use It

You will almost never build a frame by hand in production — the operating
system's network stack and the switch's hardware do it billions of times a
second. What you *will* do is inspect the very structures you just built, using
standard tools. Everything above is directly visible on a real machine:

```bash
# Your interface's MAC address (the source MAC in every frame it sends):
ip link show          # Linux;  `ifconfig` on macOS

# The ARP cache — IP -> MAC mappings this host has already resolved:
ip neigh              # Linux;  `arp -a` on macOS/Windows

# A switch's learned MAC table, if you administer one (a Linux bridge here):
bridge fdb show
```

When you need to read the frames themselves, `tcpdump -e` prints the layer-2
header — destination and source MAC and EtherType — for every packet, which is
the live version of what `ethernet_frame.py` decodes. And Python can capture real
frames through a raw `AF_PACKET` socket (Linux, root only), where `recv()` hands
you the exact `dst | src | ethertype | payload | FCS` byte layout you packed by
hand here — no library in between. The tools change; the frame does not.

## Ship It

The artifact for this lesson is a layer-2 triage prompt:
[`outputs/prompt-l2-triage.md`](../outputs/prompt-l2-triage.md). It walks from a
local-network symptom — "two machines on the same switch can't see each other,"
"the wrong host answers for an IP," "traffic that should be private is flooding
everywhere" — to the layer-2 mechanism responsible: MAC learning, ARP resolution,
broadcast/flooding, or FCS drops. You can reason about it because you just built
both the frame and the switch that steers it.

## Key takeaways

- The **data link layer** (layer 2) moves **frames** between two nodes on the
  *same* physical network — the next hop, not the whole journey.
- A **MAC address** is a 48-bit hardware address written as six hex octets; the
  first three (the **OUI**) identify the vendor. `ff:ff:ff:ff:ff:ff` is broadcast.
- An **Ethernet II frame** is `dst MAC (6) + src MAC (6) + EtherType (2) + payload
  (46–1500) + FCS (4)`. The **EtherType** says which protocol the payload is; the
  payload ceiling is the **MTU**.
- A **switch learns** which MAC lives on which port and **forwards** to just that
  port; it only **floods** (like a dumb hub) for unknown destinations or
  broadcasts.
- **ARP** resolves an IP to a MAC by broadcasting "who has this IP?" and caching
  the reply; the **FCS/CRC** lets a receiver detect a corrupted frame and drop it.
