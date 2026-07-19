# HTTP/2 & HTTP/3 (QUIC)

> HTTP/1.1 sends one request at a time down a connection and writes its headers out in full text every time. HTTP/2 turns that connection into many parallel streams of compact binary frames — and HTTP/3 moves the whole thing off TCP to dodge a stall TCP can't avoid.

**Type:** Build
**Languages:** Python
**Prerequisites:** Lessons 05 and 08 — TCP/UDP and HTTP/1.1. You should know that TCP (Transmission Control Protocol) is a reliable, ordered byte stream, that UDP (User Datagram Protocol) is fire-and-forget, and that an HTTP (HyperText Transfer Protocol) request is a method, a path, headers, and an optional body.
**Time:** ~60 minutes

## The Problem

Open a modern web page and your browser needs a hundred things at once: the HTML,
a dozen stylesheets and scripts, fonts, and a swarm of images. With **HTTP/1.1**
each connection carries **one request at a time** — the client sends a request,
waits for the whole response, then sends the next. A response that is slow to
generate blocks every request queued behind it on that connection. This is
**head-of-line (HOL) blocking** at the HTTP layer: the line moves at the speed of
its slowest front element.

Browsers worked around it by opening six connections per host and firing requests
across them, but six is not a hundred, and every extra connection pays for its own
TCP handshake and TLS (Transport Layer Security) setup. Worse, HTTP/1.1 headers are
**text, resent in full on every request** — the same `User-Agent`, `Cookie`, and
`Accept` lines, hundreds of bytes, over and over.

Two protocols answer this. **HTTP/2** keeps TCP but multiplexes many requests over
a single connection as compact binary frames. **HTTP/3** goes further and swaps the
transport underneath. By the end of this lesson you will have built and parsed the
9-byte header that makes HTTP/2 multiplexing work, byte by byte, in Python.

## The Concept

HTTP/1.1 is a conversation you must finish before starting the next one. HTTP/2 is
a conversation where every sentence is tagged with which topic it belongs to, so
many topics interleave on one line. HTTP/3 keeps that idea but rebuilds the line
itself so one dropped word can't freeze the others.

### HTTP/1.1 and the one-request-at-a-time wall

An HTTP/1.1 connection is strictly sequential. Even with *pipelining* (sending
requests without waiting), the server must return responses **in request order**,
so a slow response still blocks the ones behind it. The practical rule is
**one request in flight per connection**:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 780 388" width="100%" style="max-width:760px" role="img" aria-label="HTTP/1.1 sequence over one connection. The client sends GET /index.html and waits for the full 200 response before sending GET /style.css, then waits again before sending GET /app.js. Each request and its response form one serial round-trip, and a request cannot start until the previous response has fully returned, so three requests cost three round-trips.">
  <defs>
    <marker id="l11a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="390" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">One request in flight at a time — strictly serial</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- actor headers -->
    <g stroke-width="1.7" stroke-linejoin="round">
      <rect x="120" y="44" width="150" height="30" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="510" y="44" width="150" height="30" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    </g>
    <text x="195" y="63" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">Client</text>
    <text x="585" y="63" text-anchor="middle" font-size="11.5" font-weight="700" fill="#0fa07f">Server</text>
    <!-- lifelines -->
    <g stroke="currentColor" stroke-opacity="0.25" stroke-width="1.3" stroke-dasharray="4 5">
      <path d="M195 74 L195 352"/>
      <path d="M585 74 L585 352"/>
    </g>
    <!-- note band -->
    <rect x="110" y="88" width="560" height="22" rx="6" fill="#7f7f7f" fill-opacity="0.1" stroke="currentColor" stroke-opacity="0.25" stroke-width="1"/>
    <text x="390" y="103" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.8">HTTP/1.1 — one connection, one request at a time</text>
    <!-- round-trip bands -->
    <g fill="#7f7f7f" fill-opacity="0.06" stroke="currentColor" stroke-opacity="0.16" stroke-width="1">
      <rect x="110" y="124" width="560" height="66" rx="8"/>
      <rect x="110" y="198" width="560" height="66" rx="8"/>
      <rect x="110" y="272" width="560" height="66" rx="8"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.3">
      <circle cx="135" cy="157" r="9"/>
      <circle cx="135" cy="231" r="9"/>
      <circle cx="135" cy="305" r="9"/>
    </g>
    <g text-anchor="middle" font-size="10" font-weight="700" fill="currentColor" opacity="0.6">
      <text x="135" y="160.5">1</text>
      <text x="135" y="234.5">2</text>
      <text x="135" y="308.5">3</text>
    </g>
    <!-- messages -->
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M201 150 L579 150" marker-end="url(#l11a-ar)"/>
      <path d="M579 180 L201 180" marker-end="url(#l11a-ar)"/>
      <path d="M201 224 L579 224" marker-end="url(#l11a-ar)"/>
      <path d="M579 254 L201 254" marker-end="url(#l11a-ar)"/>
      <path d="M201 298 L579 298" marker-end="url(#l11a-ar)"/>
      <path d="M579 328 L201 328" marker-end="url(#l11a-ar)"/>
    </g>
    <g fill="currentColor" text-anchor="middle" font-size="9.5">
      <text x="390" y="144">GET /index.html</text>
      <text x="390" y="174" opacity="0.85">200 (full response)</text>
      <text x="390" y="218">GET /style.css</text>
      <text x="390" y="248" opacity="0.85">200 (full response)</text>
      <text x="390" y="292">GET /app.js</text>
      <text x="390" y="322" opacity="0.85">200 (full response)</text>
    </g>
    <!-- footer -->
    <text x="390" y="374" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.75">Each response fully returns before the next request — three requests, three serial round-trips.</text>
  </g>
</svg>
```

Each request waits for the previous response to finish. Three requests cost three
round-trips end to end, even though the server could have worked on all three at
once.

### HTTP/2: streams multiplexed as binary frames

**HTTP/2** (RFC 9113) keeps the same methods, paths, and status codes but changes
how they travel. A single TCP connection carries many independent **streams**, and
each stream is a bidirectional sequence of **frames**. A frame is the smallest unit
on the wire — a short binary header plus a payload. Every frame is stamped with a
**stream identifier**, so frames for different requests can be **multiplexed**:
interleaved on the one connection and sorted back out by stream at the other end.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 780 396" width="100%" style="max-width:760px" role="img" aria-label="HTTP/2 sequence over one connection. The client sends three HEADERS requests back to back without waiting: stream 1 GET /index.html, stream 3 GET /style.css, and stream 5 GET /app.js. The server then returns responses interleaved and out of order — stream 3 (style.css) finishes first, then stream 1 (index.html), then stream 5 (app.js) last. Each stream is drawn in its own color to show the frames interleaving on a single connection.">
  <defs>
    <marker id="l11b-ar1" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
    <marker id="l11b-ar3" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
    <marker id="l11b-ar5" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#7c5cff"/></marker>
  </defs>
  <text x="390" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">Three streams interleaved on one connection</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- actor headers -->
    <g stroke-width="1.7" stroke-linejoin="round">
      <rect x="120" y="44" width="150" height="30" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="510" y="44" width="150" height="30" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    </g>
    <text x="195" y="63" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">Client</text>
    <text x="585" y="63" text-anchor="middle" font-size="11.5" font-weight="700" fill="#0fa07f">Server</text>
    <!-- lifelines -->
    <g stroke="currentColor" stroke-opacity="0.25" stroke-width="1.3" stroke-dasharray="4 5">
      <path d="M195 74 L195 360"/>
      <path d="M585 74 L585 360"/>
    </g>
    <!-- note band -->
    <rect x="110" y="88" width="560" height="22" rx="6" fill="#7f7f7f" fill-opacity="0.1" stroke="currentColor" stroke-opacity="0.25" stroke-width="1"/>
    <text x="390" y="103" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.8">HTTP/2 — one connection, three streams interleaved</text>
    <!-- requests: all three sent back to back -->
    <g fill="none" stroke-width="1.6">
      <path d="M201 142 L579 142" stroke="#3553ff" marker-end="url(#l11b-ar1)"/>
      <path d="M201 176 L579 176" stroke="#e0930f" marker-end="url(#l11b-ar3)"/>
      <path d="M201 210 L579 210" stroke="#7c5cff" marker-end="url(#l11b-ar5)"/>
    </g>
    <g text-anchor="middle" font-size="9.5" font-weight="600">
      <text x="390" y="136" fill="#3553ff">HEADERS stream 1 (GET /index.html)</text>
      <text x="390" y="170" fill="#e0930f">HEADERS stream 3 (GET /style.css)</text>
      <text x="390" y="204" fill="#7c5cff">HEADERS stream 5 (GET /app.js)</text>
    </g>
    <!-- divider note -->
    <rect x="110" y="224" width="560" height="22" rx="6" fill="#7f7f7f" fill-opacity="0.1" stroke="currentColor" stroke-opacity="0.25" stroke-width="1"/>
    <text x="390" y="239" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.8">All three requests in flight — responses return out of order</text>
    <!-- responses: interleaved, out of order -->
    <g fill="none" stroke-width="1.6">
      <path d="M579 282 L201 282" stroke="#e0930f" marker-end="url(#l11b-ar3)"/>
      <path d="M579 316 L201 316" stroke="#3553ff" marker-end="url(#l11b-ar1)"/>
      <path d="M579 350 L201 350" stroke="#7c5cff" marker-end="url(#l11b-ar5)"/>
    </g>
    <g text-anchor="middle" font-size="9.5" font-weight="600">
      <text x="390" y="276" fill="#e0930f">HEADERS+DATA stream 3 (style.css ready first)</text>
      <text x="390" y="310" fill="#3553ff">HEADERS+DATA stream 1 (index.html)</text>
      <text x="390" y="344" fill="#7c5cff">DATA stream 5 (app.js, arrives last)</text>
    </g>
    <!-- footer -->
    <text x="390" y="382" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.75">Stream 3 finishes before stream 1 — frames interleave and sort back out by stream id.</text>
  </g>
</svg>
```

All three requests are in flight at once, and responses come back **in whatever
order the server finishes them** — stream 3 can complete before stream 1. Streams
are identified by number: the client opens odd-numbered streams, the server opens
even ones, and **stream 0** is reserved for connection-wide control frames.

### The HTTP/2 frame header

Every frame begins with a fixed **9-byte** header (RFC 9113 §4.1). Nine bytes is
all it takes to multiplex a connection — the header says how long the frame is,
what kind it is, and which stream it belongs to:

| Field | Size | What it holds |
|---|---|---|
| Length | 24 bits | Size of the payload after the header, in bytes (0–16,777,215) |
| Type | 8 bits | Which kind of frame: `DATA` (0x0), `HEADERS` (0x1), `SETTINGS` (0x4), `WINDOW_UPDATE` (0x8), … |
| Flags | 8 bits | Type-specific bit flags, e.g. `END_STREAM` (0x1), `END_HEADERS` (0x4) |
| Reserved (R) | 1 bit | Unused; must be 0 on send and ignored on receipt |
| Stream Identifier | 31 bits | Which stream this frame belongs to (0 = connection-wide control) |

The last two fields share one 32-bit word: a single reserved bit in the top
position and the 31-bit stream identifier below it. Add them up — 24 + 8 + 8 + 1 +
31 = 72 bits = **9 bytes**. The frame **type** is the verb: `HEADERS` opens a stream
and carries the request/response header block, `DATA` carries the body, `SETTINGS`
configures the connection, and `WINDOW_UPDATE` grants flow-control credit. You will
build and decode this exact header in *Build It*.

### HPACK: compressing repeated headers

HTTP/1.1 resends every header as plaintext on every request. HTTP/2 replaces that
with **HPACK** (RFC 7541), *Header Compression for HTTP/2*. HPACK keeps a shared
table of header fields both sides have already seen; after the first request, a
repeated header like `cookie: …` can be sent as a **single index** into that table
instead of the whole string. Common header names (`:method`, `:path`, `content-type`)
live in a static table baked into the spec. The result: the verbose, repetitive
text headers of HTTP/1.1 shrink to a handful of bytes.

### TCP head-of-line blocking: HTTP/2's ceiling

HTTP/2 solved HOL blocking at the *HTTP* layer — but not at the *transport* layer.
In **Lesson 05** you saw that TCP delivers a single, strictly **ordered** byte
stream: if one segment is lost, TCP holds back every byte that arrived after it
until the missing segment is retransmitted. That is TCP's own head-of-line blocking,
and it is invisible to HTTP/2.

Here is the trap: HTTP/2 runs all its streams over **one** TCP connection. To TCP,
those interleaved frames are just one continuous stream of bytes — TCP has no idea
there are independent streams inside. So a single lost TCP packet stalls **every**
HTTP/2 stream at once, even streams whose bytes already arrived, because TCP won't
release any later byte until the gap is filled. Multiplexing removed the
application-layer stall and exposed the transport-layer one underneath.

### HTTP/3 and QUIC: reliability per stream over UDP

**HTTP/3** (RFC 9114) fixes this by changing transports. It runs over **QUIC**
(RFC 9000) — a transport protocol built on **UDP** instead of TCP. Recall from
Lesson 05 that UDP is fire-and-forget: it gives you ports and nothing else, no
ordering and no retransmission. QUIC rebuilds reliability and ordering on top of
UDP, but with one decisive change: it tracks them **per stream** rather than for the
connection as a whole.

Because QUIC knows about streams (TCP never did), a lost UDP packet only stalls the
**one stream** whose data it carried; every other stream keeps flowing. The
connection-wide head-of-line blocking that limited HTTP/2 is gone. QUIC adds two
more wins:

- **Faster handshakes.** QUIC folds the transport and TLS 1.3 handshakes together,
  reaching first byte in **1-RTT** (round-trip time), and **0-RTT** when resuming a
  prior connection — versus TCP's separate handshake followed by TLS.
- **Connection migration.** A QUIC connection is identified by a connection ID, not
  the IP/port 4-tuple, so it survives a network change — your phone moving from
  Wi-Fi to cellular keeps the same connection instead of starting over.

HTTP/3 uses **QPACK** (RFC 9204) instead of HPACK, a header-compression scheme
redesigned so that reordered streams don't corrupt the shared table.

### Comparing HTTP/1.1, HTTP/2, and HTTP/3

| | HTTP/1.1 | HTTP/2 | HTTP/3 |
|---|---|---|---|
| Transport | TCP | TCP | QUIC over UDP |
| Wire format | Text | Binary frames | Binary frames |
| Concurrency | One request in flight per connection | Many streams multiplexed on one connection | Many streams multiplexed on one connection |
| Header compression | None (full text every time) | HPACK | QPACK |
| Head-of-line blocking | At the HTTP layer, per connection | At the TCP layer — one lost packet stalls all streams | None across streams — per-stream reliability |
| Handshake to first byte | TCP, then TLS round-trips | TCP, then TLS round-trips | QUIC 1-RTT, or 0-RTT on resumption |

Each version keeps the same request/response *semantics* — a `GET /` is a `GET /` in
all three — and changes only how those messages are framed and carried.

## Build It

The full implementation is in [`code/http2_frame.py`](../code/http2_frame.py). It
builds several real HTTP/2 frame headers with `struct`, then unpacks every field
back out — the same parse an HTTP/2 endpoint runs on every frame it receives. No
network is involved: we work directly with the bytes.

### Packing the 9-byte header

`struct` has no 3-byte integer, so the 24-bit length needs one small trick: pack it
as a 32-bit integer and drop the top byte, leaving exactly 24 bits. The reserved bit
and 31-bit stream id share a single 32-bit word:

```python
import struct

def build_frame_header(length, ftype, flags, stream_id, reserved=0):
    length_bytes = struct.pack(">I", length)[1:]        # 32-bit int, drop top byte -> 24 bits
    type_and_flags = struct.pack(">BB", ftype, flags)   # 1 byte type, 1 byte flags
    stream_word = struct.pack(">I", (reserved << 31) | stream_id)  # R bit + 31-bit stream id
    return length_bytes + type_and_flags + stream_word  # 3 + 2 + 4 = 9 bytes
```

### Parsing it back

Parsing reverses the trick — prepend a zero byte so `struct` can read the 24-bit
length as a 32-bit integer — then split the last word into its reserved bit and
stream id with a shift and a mask:

```python
def parse_frame_header(raw):
    length = struct.unpack(">I", b"\x00" + raw[0:3])[0]  # 24-bit length
    ftype, flags = struct.unpack(">BB", raw[3:5])
    stream_word = struct.unpack(">I", raw[5:9])[0]
    reserved = stream_word >> 31           # the single top bit
    stream_id = stream_word & 0x7FFFFFFF   # the low 31 bits
    return length, ftype, flags, reserved, stream_id
```

The program also decodes a header captured off the wire — `00 00 08 00 01 00 00 00
03` — from scratch: length 8, type `0x0` (`DATA`), flags `0x1` (`END_STREAM`),
stream 3. Run it:

```bash
python3 code/http2_frame.py
```

You will see each frame's fields printed and a round-trip check confirming every
built header parses back to its exact values, for example:

```text
DATA (request body on stream 1, END_STREAM set)
  raw bytes ........... 00 04 00 00 01 00 00 00 01
  length .............. 1024 bytes of payload follow the header
  type ................ 0x00  -> DATA
  flags ............... 0b00000001
  reserved bit ........ 0
  stream id ........... 1
```

Seeing `type -> DATA` and `stream id 1` fall out of nine raw bytes is what makes
multiplexing concrete: the stream id is the whole trick.

## Use It

You almost never pack these frames yourself — the protocol version is negotiated for
you, and a library builds and parses frames underneath. Two things pick the version:

- **ALPN** (Application-Layer Protocol Negotiation, RFC 7301) during the TLS
  handshake. The client offers `h2` and `http/1.1`; the server picks one. This is how
  a browser and server agree on HTTP/2 without an extra round-trip.
- **Alt-Svc / HTTPS DNS records** advertise HTTP/3. Because HTTP/3 is on UDP, a client
  usually starts on HTTP/2 over TCP, sees an `Alt-Svc: h3=…` header (or an `HTTPS`
  DNS record), and upgrades to `h3` over QUIC for later requests.

From an application, you just ask for a URL and inspect what you got. With `curl`,
the flags name the version explicitly:

```bash
curl --http2 -sI https://example.org      # negotiate HTTP/2 via ALPN
curl --http3 -sI https://example.org      # force HTTP/3 over QUIC (if supported)
```

In Python, the production HTTP client `httpx` negotiates HTTP/2 for you when built
with HTTP/2 support, and reports the version it actually used:

```python
import httpx  # the Use-It tool; the Build-It half above is stdlib only

with httpx.Client(http2=True) as client:
    r = client.get("https://example.org")
    print(r.http_version)   # "HTTP/2" when the server and ALPN agree, else "HTTP/1.1"
```

Knowing which version is underneath tells you how a slow page will behave. On
HTTP/1.1 a stuck response blocks its connection; on HTTP/2 packet loss stalls all
streams on the connection at once (TCP head-of-line blocking); on HTTP/3 the same
loss stalls only the affected stream. Same request, three different failure shapes.

## Ship It

The artifact for this lesson is an HTTP-version decision prompt:
[`outputs/prompt-http-version-choice.md`](../outputs/prompt-http-version-choice.md) —
it walks from a workload's shape (many small assets, a lossy mobile network, a
long-lived API connection, a legacy proxy in the path) to whether HTTP/1.1, HTTP/2,
or HTTP/3 fits, and names the mechanism — multiplexing, HPACK/QPACK, TCP vs.
per-stream head-of-line blocking — behind the call. You can reason about it because
you just built the frame that makes multiplexing work.

## Key takeaways

- **HTTP/1.1** carries **one request at a time** per connection and resends headers as
  full text every time — head-of-line blocking at the HTTP layer.
- **HTTP/2** (RFC 9113) multiplexes many **streams** over one TCP connection as binary
  **frames**, each with a **9-byte header**: 24-bit length, 8-bit type, 8-bit flags,
  1 reserved bit, and a 31-bit stream identifier. **HPACK** (RFC 7541) compresses the
  repeated headers.
- HTTP/2 still rides one **TCP** stream, so one lost packet stalls **every** stream —
  the transport-layer head-of-line blocking you met in **Lesson 05**.
- **HTTP/3** (RFC 9114) runs over **QUIC** (RFC 9000), which rebuilds reliability and
  ordering **per stream** on top of **UDP**, so a lost packet stalls only its own
  stream; it also gets faster (0-RTT) handshakes and connection migration.
- The request/response **semantics are identical** across all three versions — only
  the framing and the transport change.
