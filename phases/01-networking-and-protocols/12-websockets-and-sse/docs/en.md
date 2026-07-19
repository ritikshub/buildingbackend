# WebSockets & Server-Sent Events

> Plain HTTP only answers when spoken to — the server cannot start a sentence. WebSockets and Server-Sent Events are the two ways to let the server push, and both begin life as an ordinary HTTP request.

**Type:** Build
**Languages:** Python
**Prerequisites:** Phase 1 · Lessons 08–09 — HTTP. You should know that an HTTP (HyperText Transfer Protocol) message is a request the client sends and a response the server sends back, that both carry headers, and that a status line like `200 OK` opens the response.
**Time:** ~75 minutes

## The Problem

You are building a chat app. Alice sends a message; Bob should see it *now*.
But HTTP is strictly request/response: the client asks, the server answers, and
then the exchange is over. The server has no way to tap Bob on the shoulder and
say "a message arrived." It can only wait to be asked.

The old workaround was **polling** — Bob's browser asks "anything new?" every two
seconds, forever. Most of those requests come back empty. Cut the interval to
feel instant and you multiply the wasted requests; widen it to save the server
and the app feels laggy. Either way you are paying for a full HTTP round trip,
headers and all, to usually hear "no."

What you actually want is a connection the server can *write to whenever it
likes*. Two standards give you exactly that, and both are clever precisely
because they start as a normal HTTP request and then change the rules mid-stream:

- **WebSockets** turn the connection into a two-way channel — either side can
  send at any time.
- **Server-Sent Events (SSE)** keep it one-way — the server streams to the
  client over a response that never closes.

By the end of this lesson you will have computed a WebSocket handshake key,
built and parsed a WebSocket frame byte by byte, and streamed real SSE events
between a server and client — all in Python, all by hand.

## The Concept

HTTP gives you one round trip: one request in, one response out, connection done.
Both mechanisms here escape that by *reusing the very first HTTP request* to
negotiate something longer-lived. Where they differ is what the connection
becomes afterward.

### The WebSocket handshake: upgrading an HTTP connection

A **WebSocket** (RFC 6455) does not open on a new port or a new protocol from
scratch. It starts as a normal HTTP `GET` that politely asks to switch
protocols. The client sends headers that say "I would like to stop speaking HTTP
and start speaking WebSocket on this same TCP connection":

```http
GET /chat HTTP/1.1
Host: example.com
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==
Sec-WebSocket-Version: 13
```

`Upgrade: websocket` and `Connection: Upgrade` are the request. The
`Sec-WebSocket-Key` is a random 16-byte value the client base64-encodes — it is
**not** a security token; it is a handshake check that proves the server
actually understood the WebSocket request and isn't a cache blindly replaying an
old response.

The server proves it by computing a specific answer. It concatenates the key
with a fixed **magic GUID** (Globally Unique Identifier) defined in the RFC —
`258EAFA5-E914-47DA-95CA-C5AB0DC85B11` — takes the SHA-1 hash of that string, and
base64-encodes the result. That value goes back in `Sec-WebSocket-Accept`
alongside the status line `101 Switching Protocols`:

```http
HTTP/1.1 101 Switching Protocols
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=
```

After that `101`, the HTTP conversation is over and the *same TCP connection* is
now a bidirectional WebSocket. From here either side can send whenever it wants:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 424" width="100%" style="max-width:740px" role="img" aria-label="WebSocket upgrade and full-duplex sequence. The exchange starts as ordinary HTTP over one TCP connection. The client sends an HTTP GET with Upgrade: websocket and a Sec-WebSocket-Key. The server replies 101 Switching Protocols with the matching Sec-WebSocket-Accept. The handshake is now done and the same socket carries full-duplex frames. The client sends a masked frame hi, the server sends welcome, then sends another client joined unprompted, and the client sends a masked frame bye. Either side may send a frame at any time with no request needed.">
  <defs>
    <marker id="l12a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="380" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">An HTTP GET upgrades into a full-duplex WebSocket</text>
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
    <!-- note band 1 -->
    <rect x="95" y="86" width="570" height="22" rx="6" fill="#7f7f7f" fill-opacity="0.1" stroke="currentColor" stroke-opacity="0.25" stroke-width="1"/>
    <text x="380" y="101" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.8">It starts as ordinary HTTP over one TCP connection</text>
    <!-- handshake messages -->
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M196 140 L564 140" marker-end="url(#l12a-ar)"/>
      <path d="M564 176 L196 176" marker-end="url(#l12a-ar)"/>
    </g>
    <g fill="currentColor" text-anchor="middle" font-size="9.5">
      <text x="380" y="134">GET /chat&#8195;Upgrade: websocket, Sec-WebSocket-Key: dGhl...</text>
      <text x="380" y="170">101 Switching Protocols&#8195;Sec-WebSocket-Accept: s3pP...</text>
    </g>
    <!-- note band 2 -->
    <rect x="95" y="190" width="570" height="22" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-opacity="0.6" stroke-width="1"/>
    <text x="380" y="205" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.9">Handshake done — same socket, now full-duplex frames</text>
    <!-- frame messages -->
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M196 244 L564 244" marker-end="url(#l12a-ar)"/>
      <path d="M564 280 L196 280" marker-end="url(#l12a-ar)"/>
      <path d="M564 316 L196 316" marker-end="url(#l12a-ar)"/>
      <path d="M196 352 L564 352" marker-end="url(#l12a-ar)"/>
    </g>
    <g fill="currentColor" text-anchor="middle" font-size="9.5">
      <text x="380" y="238">frame "hi" (masked)</text>
      <text x="380" y="274">frame "welcome"</text>
      <text x="380" y="310">frame "another client joined"</text>
      <text x="380" y="346">frame "bye" (masked)</text>
    </g>
    <!-- note band 3 -->
    <rect x="95" y="366" width="570" height="22" rx="6" fill="#7f7f7f" fill-opacity="0.1" stroke="currentColor" stroke-opacity="0.25" stroke-width="1"/>
    <text x="380" y="381" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.8">Either side may send at any time; no request needed</text>
    <!-- footer -->
    <text x="380" y="410" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.7">The same TCP socket now carries frames both ways, unprompted.</text>
  </g>
</svg>
```

SHA-1 = Secure Hash Algorithm 1, a function that maps any input to a fixed
20-byte digest; base64 = an encoding that packs bytes into ASCII text. You will
compute this exact value in Build It.

### WebSocket frames: the binary message format

Once upgraded, data no longer travels as HTTP messages. It travels as
**frames** — a compact binary format defined in RFC 6455 §5.2. A frame is a few
header bytes followed by the payload. The first byte carries the **FIN** bit
(is this the final frame of a message?) and a 4-bit **opcode** (is this text,
binary, a ping, a pong, or a close?). The second byte carries the **MASK** bit
and the payload length:

| Field | Size | What it does |
|---|---|---|
| FIN | 1 bit | 1 = this is the last (or only) frame of the message |
| RSV1–3 | 3 bits | Reserved for extensions; normally 0 |
| Opcode | 4 bits | Frame type: `0x1` text, `0x2` binary, `0x8` close, `0x9` ping, `0xA` pong |
| MASK | 1 bit | 1 = the payload is masked (always 1 for client→server) |
| Payload length | 7 bits | `0`–`125` inline; `126` = read next 2 bytes; `127` = read next 8 bytes |
| Extended length | 0 / 16 / 64 bits | The real length when the 7-bit field is 126 or 127 |
| Masking key | 0 / 32 bits | Present only when MASK = 1; the 4 bytes used to unmask |
| Payload | length bytes | The actual message data (masked if MASK = 1) |

The variable-length encoding is the clever part: a tiny message spends just two
header bytes, but the same format still addresses a 64-bit payload length when
you need it. Small is cheap, large is possible.

### Masking: why client frames are XOR-scrambled

Every frame a client sends to a server **must be masked** (RFC 6455 §5.3), and
this trips up everyone the first time. The client picks a random 4-byte
**masking key**, then XORs each payload byte with a byte of that key, cycling
through the four key bytes. XOR (exclusive-or) is a reversible bitwise
operation: `byte ^ key`, applied twice with the same key, returns the original
byte — so the server unmasks by XOR-ing again with the same key it reads from
the frame.

Masking is **not encryption** — the key travels in the clear inside the same
frame, so anyone reading the bytes can undo it instantly. Its real job is to
scramble the payload so it can't be mistaken for a valid HTTP request by a
confused intermediary (an old proxy or cache) sitting between client and server.
That defends against a **cache-poisoning** attack where a masked-looking payload
would otherwise be interpreted as a genuine HTTP message. Server→client frames
are *not* masked, because that attack only runs in the client→server direction.

### Server-Sent Events: a one-way text stream

**Server-Sent Events (SSE)** — standardized in the WHATWG HTML specification —
take the opposite approach: no protocol switch at all. The response *stays* HTTP;
it just never ends. The client makes a normal `GET`, and the server replies
`200 OK` with `Content-Type: text/event-stream` and then holds the connection
open, writing events as they happen:

```text
retry: 2000

id: 1
data: server tick #1

id: 2
data: server tick #2
```

The format is deliberately trivial: UTF-8 text, one field per line
(`data:`, `id:`, `event:`, `retry:`), and a **blank line** terminates each
event. Because it is just a long-lived HTTP response, SSE works through ordinary
proxies and needs no framing, no masking, no opcodes:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 352" width="100%" style="max-width:740px" role="img" aria-label="Server-Sent Events sequence. The client sends an HTTP GET for /events with Accept: text/event-stream. The server replies 200 OK with Content-Type: text/event-stream and keeps the response open. Over that single open response the server pushes data server tick number one, then tick number two, then tick number three, one after another. The server pushes as events occur while the client just reads, and if the socket drops the browser auto-reconnects.">
  <defs>
    <marker id="l12b-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="380" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">One kept-open HTTP response streams events one way</text>
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
      <path d="M190 74 L190 262"/>
      <path d="M570 74 L570 262"/>
    </g>
    <!-- messages -->
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M196 106 L564 106" marker-end="url(#l12b-ar)"/>
      <path d="M564 142 L196 142" marker-end="url(#l12b-ar)"/>
      <path d="M564 178 L196 178" marker-end="url(#l12b-ar)"/>
      <path d="M564 214 L196 214" marker-end="url(#l12b-ar)"/>
      <path d="M564 250 L196 250" marker-end="url(#l12b-ar)"/>
    </g>
    <g fill="currentColor" text-anchor="middle" font-size="9.5">
      <text x="380" y="100">GET /events&#8195;Accept: text/event-stream</text>
      <text x="380" y="136">200 OK&#8195;Content-Type: text/event-stream (stays open)</text>
      <text x="380" y="172">data: server tick #1</text>
      <text x="380" y="208">data: server tick #2</text>
      <text x="380" y="244">data: server tick #3</text>
    </g>
    <!-- note band 1 -->
    <rect x="95" y="264" width="570" height="22" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-opacity="0.6" stroke-width="1"/>
    <text x="380" y="279" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.9">Server pushes as events occur; client just reads</text>
    <!-- note band 2 -->
    <rect x="95" y="294" width="570" height="22" rx="6" fill="#7f7f7f" fill-opacity="0.1" stroke="currentColor" stroke-opacity="0.25" stroke-width="1"/>
    <text x="380" y="309" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.8">If the socket drops, the browser auto-reconnects</text>
    <!-- footer -->
    <text x="380" y="338" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.7">One request, then a one-way stream — server to client, over plain HTTP.</text>
  </g>
</svg>
```

SSE's best-loved feature is **automatic reconnection**: if the stream drops, the
browser's built-in `EventSource` reconnects on its own, and the `retry:` field
lets the server tune the delay. You get server push with almost no client code —
but only in one direction, and only for text.

### Choosing between WebSockets and SSE

Both let the server push. The choice is about *direction* and *shape*:

| | WebSockets | Server-Sent Events |
|---|---|---|
| Direction | Bidirectional (full-duplex) | One-way, server→client only |
| Data | Text **and** binary | Text (UTF-8) only |
| Protocol | Upgrades off HTTP, then custom frames | Stays a plain HTTP response |
| Reconnect | You implement it | Built in (`EventSource` auto-reconnects) |
| Overhead per message | ~2–14 header bytes/frame | A few lines of text |
| Works through dumb proxies | Sometimes needs configuration | Almost always (it is just HTTP) |
| Reach for it when | Chat, multiplayer games, collaborative editing, live trading | Notifications, live feeds, progress bars, dashboards, log tailing |

The rule of thumb: if the **client also needs to push** — chat, gaming, shared
cursors — use WebSockets. If the server is the only one talking — a stock
ticker, a progress bar, a notification feed — reach for SSE first; it is simpler,
survives proxies, and reconnects for free.

## Build It

The full implementations are in [`code/`](../code/). Both are fully offline and
self-terminating: no browser, no external network, no `pip install`.

### Compute the handshake and round-trip a frame

[`code/websocket_frame.py`](../code/websocket_frame.py) does the two byte-level
operations at the heart of RFC 6455. First it computes `Sec-WebSocket-Accept`
from a client key — SHA-1 of the key plus the magic GUID, base64-encoded:

```python
import base64
import hashlib

WS_MAGIC_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

def compute_accept(sec_websocket_key: str) -> str:
    combined = (sec_websocket_key + WS_MAGIC_GUID).encode("ascii")
    digest = hashlib.sha1(combined).digest()          # 20 raw SHA-1 bytes
    return base64.b64encode(digest).decode("ascii")   # 28-char base64 text
```

The sample key `dGhlIHNhbXBsZSBub25jZQ==` yields
`s3pPLMBiTxaQ9kYGzzhZRbK+xOo=` — the exact worked example printed in RFC 6455
§1.3, so the code asserts that match.

Then it builds a **masked text frame** and parses it back. Encoding sets FIN and
the text opcode in byte 0, the MASK bit and length in byte 1, appends the 4-byte
masking key, and XOR-masks the payload:

```python
import struct

def build_masked_text_frame(payload: bytes, masking_key: bytes) -> bytes:
    b0 = 0x80 | 0x1                     # FIN=1, opcode=0x1 (text)
    n = len(payload)
    if n < 126:
        header = struct.pack(">BB", b0, 0x80 | n)       # MASK=1 + 7-bit length
    elif n <= 0xFFFF:
        header = struct.pack(">BBH", b0, 0x80 | 126, n) # 126 -> 16-bit length
    else:
        header = struct.pack(">BBQ", b0, 0x80 | 127, n) # 127 -> 64-bit length
    masked = bytes(b ^ masking_key[i % 4] for i, b in enumerate(payload))
    return header + masking_key + masked
```

Parsing reverses every step — read the bits out of the first two bytes, follow
the length encoding, read the masking key, then XOR the payload back to
plaintext — and the program asserts the recovered bytes equal the original. Run
it:

```bash
python code/websocket_frame.py
```

You will see the handshake value, the raw frame bytes in hex, and every decoded
field. The round-trip assertion is the payoff: masking is fully reversible, and
you just proved it.

### Stream real SSE events

[`code/sse_demo.py`](../code/sse_demo.py) starts a tiny HTTP server on a
background thread that streams `data:` events with
`Content-Type: text/event-stream`, and a `urllib` client that reads a few events
and hangs up. The server side is just a normal HTTP response you keep writing to:

```python
self.send_response(200)
self.send_header("Content-Type", "text/event-stream")   # the SSE contract
self.end_headers()
self.wfile.write(b"retry: 2000\n\n")                     # auto-reconnect hint
for i in range(1, EVENTS_TO_SEND + 1):
    self.wfile.write(f"id: {i}\ndata: server tick #{i}\n\n".encode("utf-8"))
    self.wfile.flush()                                   # push now, don't buffer
```

The client reads the stream line by line, accumulating `data:` lines until a
blank line closes each event, and stops once it has enough — closing the
connection, exactly as a real browser would when you navigate away:

```python
for raw in resp:                       # HTTPResponse yields the stream line by line
    line = raw.decode("utf-8").rstrip("\n")
    if line == "":                     # blank line = one complete event
        if data_lines:
            collected.append("\n".join(data_lines))
            data_lines = []
            if len(collected) >= want:
                break
    elif line.startswith("data:"):
        data_lines.append(line[len("data:"):].lstrip())
```

Run it:

```bash
python code/sse_demo.py
```

It prints each event as it arrives and exits cleanly. Notice there was no framing
and no handshake — SSE is just an HTTP response the server refuses to finish.

## Use It

In production you would not hand-roll frames. A server framework speaks both
protocols for you — but every byte it moves is exactly what you just built.

With **FastAPI** (a Python web framework), a WebSocket endpoint hides the entire
handshake and framing behind two calls:

```python
from fastapi import FastAPI, WebSocket

app = FastAPI()

@app.websocket("/chat")
async def chat(ws: WebSocket):
    await ws.accept()                      # performs the 101 handshake for you
    while True:
        msg = await ws.receive_text()      # unmasks and reassembles frames
        await ws.send_text(f"echo: {msg}") # frames and sends (unmasked) back
```

`accept()` is the `101 Switching Protocols` and `Sec-WebSocket-Accept` you
computed by hand; `receive_text()` unmasks and defragments frames; `send_text()`
builds them. The magic GUID, the XOR, the FIN bit — all still there, just
underneath.

SSE is even lighter: it is a normal HTTP response whose body is a generator that
never returns until you want it to. The only thing that makes it SSE is the
`Content-Type` and the `data: ...\n\n` shape — the same two things your
`sse_demo.py` sends.

Knowing what is underneath tells you how each fails. A WebSocket that "won't
connect" is usually a proxy stripping the `Upgrade` header before the `101` ever
arrives. An SSE stream that keeps reconnecting is usually a proxy or load
balancer buffering or timing out the long-lived response. You debug them at the
layer you now understand.

## Ship It

The artifact for this lesson is a decision prompt:
[`outputs/prompt-realtime-transport-choice.md`](../outputs/prompt-realtime-transport-choice.md).
Given a real-time feature, it walks from the traffic's *direction and shape* to a
recommendation of WebSockets, SSE, or plain polling — and names the failure modes
of each so the choice survives contact with a proxy. You can reason about its
advice because you just built both transports from their bytes up.

## Key takeaways

- Plain HTTP is request/response — the server cannot push. **WebSockets** and
  **SSE** are the two standard ways to get server→client streaming, and both
  begin as an ordinary HTTP request.
- A **WebSocket** upgrades off an HTTP `GET` with `Upgrade: websocket`; the server
  replies `101 Switching Protocols` with
  `Sec-WebSocket-Accept = base64(SHA1(key + magic GUID))`. The same TCP
  connection then carries bidirectional **frames**.
- A WebSocket **frame** is FIN + opcode, a MASK bit, a variable-length payload
  length, an optional masking key, then the payload. **Client→server frames must
  be masked** (XOR with the 4-byte key) — a proxy-safety measure, not encryption.
- **SSE** is a one-way server→client stream over a normal HTTP response with
  `Content-Type: text/event-stream`; events are `data: ...` blocks separated by
  blank lines, and the browser **auto-reconnects** for free.
- Choose by direction and shape: **WebSockets** when the client also pushes and
  you need binary (chat, games); **SSE** when only the server talks and text is
  enough (feeds, notifications, dashboards) — it is simpler and proxy-friendly.
