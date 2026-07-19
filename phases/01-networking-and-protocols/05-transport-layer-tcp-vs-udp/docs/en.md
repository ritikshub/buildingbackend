# The Transport Layer: TCP vs UDP

> The network layer gets a packet to the right *machine*. The transport layer gets it to the right *program* — and decides whether "getting there" is guaranteed or just attempted.

**Type:** Build
**Languages:** Python
**Prerequisites:** Phase 1 · Lessons 01–04 — the OSI/TCP-IP models through the network layer. You should know that an IP (Internet Protocol) address identifies a machine and that data travels in packets.
**Time:** ~75 minutes

## The Problem

Your laptop has one IP address, but right now it is talking to a dozen servers
at once: a browser tab, a music stream, a chat app, a background update. Packets
for all of them arrive at the same network card, addressed to the same IP. How
does the kernel know that *this* packet belongs to the browser and *that* one to
the music stream?

And a harder question: the network underneath loses packets, reorders them, and
sometimes delivers the same one twice. Yet your file download arrives byte-for-byte
perfect, while your video call tolerates a dropped frame and keeps going. Same
unreliable network, two completely different guarantees.

Both answers live in **the transport layer** — layer 4. It adds two things the
network layer doesn't have: **ports**, so bytes reach the right *program*, and a
choice of **delivery contract**. That choice is TCP or UDP. By the end of this
lesson you will have built both, by hand, in Python, and decoded their headers
byte by byte.

## The Concept

The network layer (IP) is a postal service that delivers envelopes to a
*building*. The transport layer delivers to a *person* inside it, and either
signs for every envelope (TCP) or drops it in the mailbox and walks away (UDP).

### Ports: the address within the address

An IP address picks a machine. A **port** — a 16-bit number, so `0`–`65535` —
picks a program on that machine. The pair `(IP address, port)` is called a
**socket**, and a connection is fully identified by *four* numbers: source IP,
source port, destination IP, destination port. That 4-tuple is why your machine
can hold hundreds of simultaneous connections to the same server — each one has a
different source port.

Ports fall into three ranges (IANA, the Internet Assigned Numbers Authority,
governs them):

| Range | Name | Used for |
|---|---|---|
| `0`–`1023` | Well-known | Standard services: 80 (HTTP), 443 (HTTPS), 22 (SSH), 53 (DNS). Binding these usually needs admin rights. |
| `1024`–`49151` | Registered | Applications register these: 3306 (MySQL), 5432 (PostgreSQL), 6379 (Redis). |
| `49152`–`65535` | Ephemeral | Temporary source ports the OS hands out for *outgoing* connections. |

When your browser connects to `93.184.216.34:443`, your OS assigns it a random
ephemeral source port like `54321`. The reply comes back to that port, and the
kernel routes it to your browser and no one else.

### TCP: a reliable, ordered byte stream

**TCP** (Transmission Control Protocol, RFC 9293) makes the unreliable network
*look* reliable. It gives you four guarantees:

- **Connection-oriented** — a handshake establishes shared state before any data moves.
- **Reliable** — every byte is acknowledged; unacknowledged bytes are retransmitted.
- **Ordered** — bytes arrive in the order they were sent, even if packets took different paths.
- **A byte stream, not messages** — TCP does not preserve your `send()` boundaries. Two `send()`s of 10 bytes may arrive as one `recv()` of 20, or as 5 + 15. You frame messages yourself (that is what `Content-Length` in HTTP is for).

It earns "connection-oriented" with the **three-way handshake**. Before a single
byte of your data moves, both sides exchange sequence numbers so each can
acknowledge the other's bytes:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 336" width="100%" style="max-width:720px" role="img" aria-label="TCP three-way handshake sequence. The client sends SYN with its initial sequence number x. The server replies SYN-ACK, acknowledging x plus one and sending its own initial sequence number y. The client replies ACK acknowledging y plus one. After these three messages the connection is established and data can flow in both directions.">
  <defs>
    <marker id="l05a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="380" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">Three messages to agree on where each side's bytes begin</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- actor headers -->
    <g stroke-width="1.7" stroke-linejoin="round">
      <rect x="120" y="44" width="140" height="30" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="500" y="44" width="140" height="30" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    </g>
    <text x="190" y="63" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">Client</text>
    <text x="570" y="63" text-anchor="middle" font-size="11.5" font-weight="700" fill="#0fa07f">Server</text>
    <!-- lifelines -->
    <g stroke="currentColor" stroke-opacity="0.25" stroke-width="1.3" stroke-dasharray="4 5">
      <path d="M190 74 L190 288"/>
      <path d="M570 74 L570 288"/>
    </g>
    <!-- note band 1 -->
    <rect x="95" y="88" width="570" height="22" rx="6" fill="#7f7f7f" fill-opacity="0.1" stroke="currentColor" stroke-opacity="0.25" stroke-width="1"/>
    <text x="380" y="103" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.8">Connection setup — no application data yet</text>
    <!-- messages -->
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M196 142 L564 142" marker-end="url(#l05a-ar)"/>
      <path d="M564 180 L196 180" marker-end="url(#l05a-ar)"/>
      <path d="M196 218 L564 218" marker-end="url(#l05a-ar)"/>
    </g>
    <g fill="currentColor" text-anchor="middle" font-size="9.5">
      <text x="380" y="136">SYN &#8195;seq=x&#8195; "let's talk; my bytes start at x"</text>
      <text x="380" y="174">SYN-ACK &#8195;seq=y, ack=x+1&#8195; "ok; mine start at y"</text>
      <text x="380" y="212">ACK &#8195;ack=y+1&#8195; "got yours too"</text>
    </g>
    <!-- note band 2 -->
    <rect x="95" y="236" width="570" height="22" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-opacity="0.6" stroke-width="1"/>
    <text x="380" y="251" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.9">Established — data can now flow both ways</text>
    <!-- footer -->
    <text x="380" y="284" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.7">The cost is one round trip before any data moves — the price of a reliable, ordered stream.</text>
  </g>
</svg>
```

SYN = *synchronize* (the flag that opens a connection); ACK =
*acknowledgment*. Once established, every segment of data carries a **sequence
number** (the byte offset of its first byte) and every reply carries an **ack
number** (the next byte the receiver expects). Miss an ack and the sender
retransmits — that is the whole reliability mechanism:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 400" width="100%" style="max-width:720px" role="img" aria-label="TCP retransmission sequence. The client sends 500 bytes at sequence 1000; the server acknowledges 1500. The client sends the segment at sequence 1500, but it is lost in the network and the server never sees it. The client then sends sequence 2000; the server, still missing 1500, repeats an acknowledgment for 1500. The client retransmits sequence 1500, and the server finally acknowledges 2500, caught up.">
  <defs>
    <marker id="l05b-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="380" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">One lost segment: a duplicate ACK triggers the retransmit</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- actor headers -->
    <g stroke-width="1.7" stroke-linejoin="round">
      <rect x="120" y="44" width="140" height="30" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="500" y="44" width="140" height="30" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    </g>
    <text x="190" y="63" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">Client</text>
    <text x="570" y="63" text-anchor="middle" font-size="11.5" font-weight="700" fill="#0fa07f">Server</text>
    <!-- lifelines -->
    <g stroke="currentColor" stroke-opacity="0.25" stroke-width="1.3" stroke-dasharray="4 5">
      <path d="M190 74 L190 364"/>
      <path d="M570 74 L570 364"/>
    </g>
    <!-- delivered messages -->
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M196 112 L564 112" marker-end="url(#l05b-ar)"/>
      <path d="M564 148 L196 148" marker-end="url(#l05b-ar)"/>
      <path d="M196 242 L564 242" marker-end="url(#l05b-ar)"/>
      <path d="M196 314 L564 314" marker-end="url(#l05b-ar)"/>
      <path d="M564 350 L196 350" marker-end="url(#l05b-ar)"/>
    </g>
    <!-- lost segment: red dashed, dies in the network -->
    <path d="M196 184 L470 184" fill="none" stroke="#d64545" stroke-width="1.7" stroke-dasharray="5 4"/>
    <path d="M466 179 L478 191 M478 179 L466 191" stroke="#d64545" stroke-width="1.8"/>
    <!-- loss note band -->
    <rect x="95" y="196" width="570" height="22" rx="6" fill="#d64545" fill-opacity="0.12" stroke="#d64545" stroke-opacity="0.55" stroke-width="1"/>
    <text x="380" y="211" text-anchor="middle" font-size="9.5" fill="#d64545">(packet lost in the network — the server never sees seq=1500)</text>
    <!-- message labels -->
    <g text-anchor="middle" font-size="9.5">
      <text x="380" y="106" fill="currentColor">data &#8195;seq=1000, 500 bytes</text>
      <text x="380" y="142" fill="currentColor">ACK &#8195;ack=1500&#8195; "give me byte 1500 next"</text>
      <text x="333" y="178" fill="#d64545">data &#8195;seq=1500, 500 bytes</text>
      <text x="380" y="236" fill="currentColor">data &#8195;seq=2000, 500 bytes</text>
      <text x="380" y="272" fill="#e0930f">ACK &#8195;ack=1500&#8195; "still waiting on 1500"</text>
      <text x="380" y="308" fill="currentColor">retransmit &#8195;seq=1500&#8195; the lost 500 bytes</text>
      <text x="380" y="344" fill="#0fa07f">ACK &#8195;ack=2500&#8195; "caught up"</text>
    </g>
    <!-- footer -->
    <text x="380" y="384" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.7">Everything behind seq=1500 waits until it is resent — the cost of ordered delivery (head-of-line blocking).</text>
  </g>
</svg>
```

Two more mechanisms ride on those numbers:

- **Flow control** — the receiver advertises a **window**: "I have room for N
  more bytes." The sender never overruns a slow receiver.
- **Congestion control** — the sender starts slow and ramps up, backing off when
  it sees loss, so it doesn't overwhelm the *network* in the middle.

Because delivery is strictly ordered, one lost packet stalls everything behind
it until it is retransmitted — **head-of-line blocking**, the cost of the
guarantee. Closing is explicit too: each side sends a **FIN** (finish) and waits
for it to be acknowledged, so no in-flight bytes are lost on the way out.

### The TCP header: 20 bytes of bookkeeping

Every TCP segment starts with a header that is **20 bytes minimum** (up to 60
with options). That is the price of the guarantees — all the sequence, ack,
flag, and window machinery lives here:

| Field | Size | What it does |
|---|---|---|
| Source port | 16 bits | Sending program |
| Destination port | 16 bits | Receiving program |
| Sequence number | 32 bits | Byte offset of this segment's first byte |
| Acknowledgment number | 32 bits | Next byte the sender expects to receive |
| Data offset | 4 bits | Header length in 32-bit words (5 = 20 bytes) |
| Reserved | 4 bits | Must be zero |
| Flags | 8 bits | `SYN`, `ACK`, `FIN`, `RST`, `PSH`, `URG`, … |
| Window size | 16 bits | Bytes the receiver can still accept (flow control) |
| Checksum | 16 bits | Error detection over header + data |
| Urgent pointer | 16 bits | Marks "urgent" data (rarely used) |
| Options | 0–320 bits | MSS, window scaling, timestamps, … |

### UDP: fire-and-forget datagrams

**UDP** (User Datagram Protocol, RFC 768) is the opposite philosophy: do almost
nothing, and do it fast. It is:

- **Connectionless** — no handshake. The first packet *is* the data.
- **Unreliable** — no acknowledgments, no retransmission. A lost datagram is simply gone, and neither side is told.
- **Unordered** — datagrams may arrive in any order, or twice.
- **Message-oriented** — one `sendto()` is one `recvfrom()`. Boundaries are preserved; there is no stream to reframe.

UDP hands you exactly what IP gives you, plus ports and an optional checksum.
That sounds useless until you consider what you *don't* pay for: no round-trip
handshake before the first byte, no head-of-line blocking, no per-packet
acknowledgment overhead. For a live video call, a *late* packet is worse than a
*lost* one — by the time TCP retransmits a dropped audio frame, the moment has
passed. UDP lets the application decide what to do about loss, or ignore it.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 288" width="100%" style="max-width:720px" role="img" aria-label="UDP fire-and-forget sequence. With no connection setup, the client sends datagram measurement one, then measurement two which is lost in the network with no acknowledgment and no retransmission, then measurement three. The server never learns that the second datagram was lost.">
  <defs>
    <marker id="l05c-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="380" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">Send and move on — nothing acknowledges, nothing is resent</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- actor headers -->
    <g stroke-width="1.7" stroke-linejoin="round">
      <rect x="120" y="44" width="140" height="30" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="500" y="44" width="140" height="30" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    </g>
    <text x="190" y="63" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">Client</text>
    <text x="570" y="63" text-anchor="middle" font-size="11.5" font-weight="700" fill="#0fa07f">Server</text>
    <!-- lifelines -->
    <g stroke="currentColor" stroke-opacity="0.25" stroke-width="1.3" stroke-dasharray="4 5">
      <path d="M190 74 L190 252"/>
      <path d="M570 74 L570 252"/>
    </g>
    <!-- note band 1 -->
    <rect x="95" y="88" width="570" height="22" rx="6" fill="#7f7f7f" fill-opacity="0.1" stroke="currentColor" stroke-opacity="0.25" stroke-width="1"/>
    <text x="380" y="103" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.8">No setup — the first datagram is the data</text>
    <!-- delivered datagrams -->
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M196 142 L564 142" marker-end="url(#l05c-ar)"/>
      <path d="M196 238 L564 238" marker-end="url(#l05c-ar)"/>
    </g>
    <!-- lost datagram: red dashed, never arrives -->
    <path d="M196 180 L470 180" fill="none" stroke="#d64545" stroke-width="1.7" stroke-dasharray="5 4"/>
    <path d="M466 175 L478 187 M478 175 L466 187" stroke="#d64545" stroke-width="1.8"/>
    <!-- loss note band -->
    <rect x="95" y="192" width="570" height="22" rx="6" fill="#d64545" fill-opacity="0.12" stroke="#d64545" stroke-opacity="0.55" stroke-width="1"/>
    <text x="380" y="207" text-anchor="middle" font-size="9.5" fill="#d64545">(#2 lost — nobody is told, nobody retransmits)</text>
    <!-- datagram labels -->
    <g text-anchor="middle" font-size="9.5">
      <text x="380" y="136" fill="currentColor">datagram &#8195;"measurement #1"</text>
      <text x="333" y="174" fill="#d64545">datagram &#8195;"measurement #2"</text>
      <text x="380" y="232" fill="currentColor">datagram &#8195;"measurement #3"</text>
    </g>
    <!-- footer -->
    <text x="380" y="272" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.7">Loss is invisible at layer 4 — if #2 mattered, the application must notice and resend it.</text>
  </g>
</svg>
```

### The UDP header: 8 bytes flat

The entire UDP header is **8 bytes** — no sequence numbers, no acks, no window,
because none of those mechanisms exist:

| Field | Size | What it does |
|---|---|---|
| Source port | 16 bits | Sending program |
| Destination port | 16 bits | Receiving program |
| Length | 16 bits | Header + data length in bytes |
| Checksum | 16 bits | Optional error detection |

That 20-vs-8-byte gap is the whole trade-off in miniature: TCP spends bytes and
round-trips to promise delivery; UDP spends almost nothing and promises nothing.

### Choosing between them

| | TCP | UDP |
|---|---|---|
| Connection | Handshake first | None |
| Reliability | Guaranteed, retransmitted | Best-effort |
| Ordering | Guaranteed | None |
| Shape | Byte stream | Discrete messages |
| Header | 20+ bytes | 8 bytes |
| Speed to first byte | Slower (round-trip setup) | Immediate |
| Use when | Correctness matters more than latency | Latency matters more than a lost packet |

Reach for **TCP** when every byte must arrive: web pages (HTTP/1.1 and HTTP/2),
file transfers, database connections, email. Reach for **UDP** when late data is
useless: live video and voice, online games, DNS lookups (small, one-shot,
retried by the app), and modern **QUIC** — the protocol under HTTP/3 — which
rebuilds its *own* reliability on top of UDP precisely to escape TCP's
head-of-line blocking.

## Build It

The full implementations are in [`code/`](../code/). Each file is
self-contained: it starts a server on a background thread, runs a client against
it, prints the exchange, and exits. Run them and watch the two philosophies
diverge.

### TCP echo — the reliable stream

[`code/tcp_echo.py`](../code/tcp_echo.py). The server does the classic four
calls; the client's `connect()` is where the three-way handshake happens under
the hood:

```python
# server: socket -> bind -> listen -> accept
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
    server.bind((HOST, PORT))
    server.listen(1)
    conn, addr = server.accept()      # blocks until the handshake completes
    data = conn.recv(1024)            # a stream: recv() may return partial data
    conn.sendall(data)                # echo the exact bytes back

# client: socket -> connect -> send -> recv
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.connect((HOST, PORT))        # SYN / SYN-ACK / ACK happen here
    sock.sendall(b"hello over a reliable stream")
    echo = sock.recv(1024)            # guaranteed to be the same bytes, in order
```

`SOCK_STREAM` *is* the request for TCP. Run it:

```bash
python code/tcp_echo.py
```

The client asserts the echo equals what it sent — and it always will, because
TCP guarantees it.

### UDP echo — fire and forget

[`code/udp_echo.py`](../code/udp_echo.py). Notice what's *missing*: no
`listen()`, no `accept()`, no `connect()`. A datagram socket is never connected,
so the server learns the client's address only when a datagram arrives:

```python
# server: socket -> bind -> recvfrom -> sendto
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
    server.bind((HOST, PORT))
    data, sender = server.recvfrom(1024)   # payload AND who sent it
    server.sendto(data, sender)            # reply to that address

# client: socket -> sendto -> recvfrom  (no handshake)
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
    sock.settimeout(2.0)                   # loss is normal — never block forever
    sock.sendto(b"hello ...", (HOST, PORT))
    echo, _ = sock.recvfrom(1024)          # may never come; that's allowed
```

`SOCK_DGRAM` requests UDP. The client sets a **timeout** because with UDP a
missing reply isn't an error — it's Tuesday. Run it:

```bash
python code/udp_echo.py
```

### Decode the headers by hand

[`code/decode_headers.py`](../code/decode_headers.py) builds a real TCP SYN
header and a real UDP header as bytes, then unpacks every field with
`struct.unpack` — the same parse your kernel does:

```python
import struct
# TCP: src(16) dst(16) seq(32) ack(32) offset+rsvd(8) flags(8) win(16) csum(16) urg(16)
fields = struct.unpack(">HH I I BB HHH", tcp_header)   # exactly 20 bytes
# UDP: src(16) dst(16) length(16) checksum(16)
src, dst, length, checksum = struct.unpack(">HHHH", udp_header)  # exactly 8 bytes
```

```bash
python code/decode_headers.py
```

Seeing `TCP header — 20 bytes` and `UDP header — 8 bytes` printed from real bytes
is what makes the trade-off stick.

## Use It

You rarely call `recv()` in production. The standard library wraps the socket
dance in `socketserver`, and async servers use `asyncio` — but underneath, every
one is `SOCK_STREAM` or `SOCK_DGRAM` doing exactly what you just built:

```python
import socketserver

class EchoTCP(socketserver.BaseRequestHandler):
    def handle(self):
        data = self.request.recv(1024)   # self.request is a connected TCP socket
        self.request.sendall(data)

with socketserver.TCPServer(("127.0.0.1", 8080), EchoTCP) as srv:
    srv.serve_forever()
```

Swap `TCPServer` for `UDPServer` and `handle` receives a `(data, socket)` pair
instead of a stream — the same two contracts, one class name apart. Above that,
the choice is usually made *for* you by the protocol you pick:

- **HTTP/1.1, HTTP/2, gRPC, database drivers** → TCP. You want the stream and the guarantee.
- **DNS resolvers, video/voice (RTP), game netcode, QUIC / HTTP/3** → UDP, with any reliability they need rebuilt in the application.

Knowing which one is underneath tells you how a system will fail: a TCP service
degrades by *stalling* (retransmits, head-of-line blocking), a UDP service
degrades by *dropping* (missing frames, gaps). You debug them differently
because they promise different things.

## Ship It

The artifact for this lesson is a transport-layer triage prompt:
[`outputs/prompt-transport-triage.md`](../outputs/prompt-transport-triage.md) — it
walks from a symptom (connection refused, connection reset, silent packet loss,
"works locally, times out in prod") to the layer and mechanism responsible, and
tells you which side (TCP vs UDP) the behavior implicates. You understand it
because you just built both sides.

## Key takeaways

- The transport layer adds **ports** (which program) and a **delivery contract** (which guarantees) on top of IP's machine-to-machine delivery.
- A connection is a **4-tuple**: source IP + source port + destination IP + destination port.
- **TCP** = connection-oriented, reliable, ordered byte stream, established by a **three-way handshake**, paid for with a **20-byte** header and round-trips. Its ordering guarantee causes head-of-line blocking.
- **UDP** = connectionless, unreliable, message-oriented datagrams with an **8-byte** header and no setup. Loss is normal; the application decides what to do about it.
- Choose by what hurts more: a **stalled** byte (use UDP) or a **wrong/missing** byte (use TCP).
