# HTTP in Depth: Methods, Status, Headers & Keep-Alive

> HTTP is just text over a TCP connection — a request you can type by hand and a reply you can read with your eyes. Learn its four moving parts and every web framework stops being magic.

**Type:** Build
**Languages:** Python
**Prerequisites:** Lessons 05 and 07 — TCP and the application layer. You should know that TCP (Transmission Control Protocol) gives you a reliable, ordered byte stream, and that an application protocol is the agreed-upon language two programs speak over that stream.
**Time:** ~75 minutes

## The Problem

You type `example.com` and a page appears. Underneath, your browser opened a TCP
connection and sent a few hundred bytes of *text*, and the server sent text
back. That text follows a protocol — **HTTP** (HyperText Transfer Protocol) — and
almost everything you will build as a backend engineer speaks it: REST APIs,
webhooks, health checks, load balancers, proxies, `curl`.

Yet most people only ever meet HTTP through a library that hides it: `fetch`,
`requests`, an ORM's database-over-HTTP driver. So when something breaks — a `405`
where you expected `200`, a request that mysteriously hangs, an API that's slow
because it opens a fresh connection every call — the protocol is a black box and
you are guessing.

This lesson opens the box. HTTP has exactly four things worth knowing deeply:
its **message shape**, its **methods**, its **status codes**, and its **headers** —
plus one performance idea, **keep-alive**, that explains why modern APIs feel
fast. By the end you will have typed a raw HTTP request as bytes, sent it down a
socket, and parsed the reply by hand.

## The Concept

HTTP is a **request/response** protocol: a client sends one request, the server
sends one response, and (classically) that's the whole exchange. It is
**text-based** — the header portion is human-readable ASCII — which is why you can
debug it by reading it. And it is **stateless**: the server remembers nothing
between requests unless you make it (that's what cookies are for, below).

Everything rides on a lower layer you already built. HTTP/1.1 is defined by two
specifications: **RFC 9110** (HTTP Semantics — methods, status codes, headers,
what they *mean*) and **RFC 9112** (HTTP/1.1 — the exact byte syntax of a message
on the wire). Both sit on top of TCP.

### Request and response anatomy

Every HTTP message has the same skeleton: a **start line**, zero or more
**header** lines of `Key: Value`, a **blank line**, and an optional **body**. Each
line ends with `CRLF` — a carriage return followed by a line feed (the two bytes
`\r\n`). The blank line (`\r\n` by itself) is how the receiver knows the headers
are over and the body, if any, begins.

A request's start line is the **request line**: `METHOD target HTTP/1.1`.

```http
GET /users/42 HTTP/1.1
Host: api.example.com
Accept: application/json
Connection: keep-alive

```

A response's start line is the **status line**: `HTTP/1.1 CODE REASON`.

```http
HTTP/1.1 200 OK
Content-Type: application/json
Content-Length: 27

{"id":42,"name":"Ada Lovelace"}
```

The single request-and-reply, drawn against the TCP connection underneath it:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 372" width="100%" style="max-width:720px" role="img" aria-label="HTTP request and response over a TCP connection that is already open. The client sends three lines to the server: the request line GET /users/42 HTTP/1.1, the header lines Host, Accept and Connection, and a blank CRLF line that ends the request. The server routes the method and target, then replies with three lines: the status line HTTP/1.1 200 OK, the headers Content-Type and Content-Length, and a blank line followed by the body bytes. Every message is the same four-part skeleton: start line, headers, blank line, optional body.">
  <defs>
    <marker id="l08a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="380" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">One request, one response — the same four-part skeleton each way</text>
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
      <path d="M190 74 L190 334"/>
      <path d="M570 74 L570 334"/>
    </g>
    <!-- note: connection already up -->
    <rect x="95" y="84" width="570" height="22" rx="6" fill="#7f7f7f" fill-opacity="0.1" stroke="currentColor" stroke-opacity="0.25" stroke-width="1"/>
    <text x="380" y="99" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.8">TCP connection already established</text>
    <!-- request: client to server -->
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M196 132 L564 132" marker-end="url(#l08a-ar)"/>
      <path d="M196 164 L564 164" marker-end="url(#l08a-ar)"/>
      <path d="M196 196 L564 196" marker-end="url(#l08a-ar)"/>
    </g>
    <g fill="currentColor" text-anchor="middle" font-size="9.5">
      <text x="380" y="126">Request line:&#8195;GET /users/42 HTTP/1.1</text>
      <text x="380" y="158">Headers:&#8195;Host, Accept, Connection</text>
      <text x="380" y="190">Blank line (CRLF) — end of request</text>
    </g>
    <!-- note over server -->
    <rect x="450" y="208" width="240" height="22" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-opacity="0.6" stroke-width="1"/>
    <text x="570" y="223" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.9">Server routes the method + target</text>
    <!-- response: server to client -->
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M564 256 L196 256" marker-end="url(#l08a-ar)"/>
      <path d="M564 288 L196 288" marker-end="url(#l08a-ar)"/>
      <path d="M564 320 L196 320" marker-end="url(#l08a-ar)"/>
    </g>
    <g fill="currentColor" text-anchor="middle" font-size="9.5">
      <text x="380" y="250">Status line:&#8195;HTTP/1.1 200 OK</text>
      <text x="380" y="282">Headers:&#8195;Content-Type, Content-Length</text>
      <text x="380" y="314">Blank line, then the body bytes</text>
    </g>
    <!-- footer -->
    <text x="380" y="352" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.75">Start line · headers · blank line · optional body — one skeleton, both directions.</text>
  </g>
</svg>
```

### Methods: what you want done

The **method** (also called the *verb*) is the first token of the request line. It
declares your *intent*. HTTP defines a handful; these are the ones you will use:

| Method | Purpose | Safe? | Idempotent? |
|---|---|---|---|
| `GET` | Retrieve a representation; never changes state | Yes | Yes |
| `HEAD` | Like `GET` but headers only, no body | Yes | Yes |
| `OPTIONS` | Ask which methods/features a resource supports | Yes | Yes |
| `POST` | Create a subordinate resource / submit data | No | No |
| `PUT` | Create-or-replace the resource at the target | No | Yes |
| `PATCH` | Apply a partial modification | No | No |
| `DELETE` | Remove the target resource | No | Yes |

Two properties (RFC 9110 §9.2) decide how the network may treat a method:

- **Safe** means the method is read-only — it must not change server state. `GET`,
  `HEAD`, and `OPTIONS` are safe, which is why a proxy may cache them and a
  crawler may follow them freely.
- **Idempotent** means sending the request *N* times has the same effect as
  sending it once. `PUT` (set the resource to this value) and `DELETE` (it's gone)
  are idempotent; `POST` (append a new order) is not. This matters for retries: a
  client may safely re-send an idempotent request after a timeout, but re-sending
  a `POST` might charge a card twice.

Every safe method is idempotent, but not every idempotent method is safe (`PUT`
changes state yet is idempotent).

### Status codes: how it went

The server answers with a three-digit **status code**. The first digit names the
**family**; memorize the five families and you can categorize any code you've
never seen:

| Family | Range | Meaning | Common codes |
|---|---|---|---|
| **1xx** | 100–199 | Informational — interim, keep going | `100 Continue`, `101 Switching Protocols` |
| **2xx** | 200–299 | Success — it worked | `200 OK`, `201 Created`, `204 No Content` |
| **3xx** | 300–399 | Redirection — look elsewhere | `301 Moved Permanently`, `304 Not Modified` |
| **4xx** | 400–499 | Client error — *you* messed up | `400 Bad Request`, `401 Unauthorized`, `403 Forbidden`, `404 Not Found`, `405 Method Not Allowed`, `429 Too Many Requests` |
| **5xx** | 500–599 | Server error — *the server* messed up | `500 Internal Server Error`, `502 Bad Gateway`, `503 Service Unavailable` |

The 4xx/5xx split is the single most useful distinction in debugging: a **4xx**
says the request was wrong (fix the caller), a **5xx** says the server failed on a
request that looked fine (fix the server). A few pairs are easy to confuse:
`401 Unauthorized` means *not authenticated* (who are you?), while
`403 Forbidden` means *authenticated but not allowed* (I know you, no). `301` is a
permanent redirect (update your bookmark), `304 Not Modified` means "your cached
copy is still good, I'm sending no body." `502 Bad Gateway` and
`503 Service Unavailable` are what a proxy or load balancer returns when the thing
behind it is broken or overloaded.

### Headers: the metadata envelope

**Headers** are `Key: Value` lines carrying metadata about the message — who's
asking, what format the body is in, how long it is, how to cache it. Header names
are case-insensitive. The ones you'll touch constantly:

| Header | On | What it says |
|---|---|---|
| `Host` | Request | Which virtual host you want (mandatory in HTTP/1.1 — one IP can serve many sites) |
| `Content-Type` | Both | The body's media type, e.g. `application/json`, `text/html` |
| `Content-Length` | Both | The body's exact size in bytes — this is how the receiver knows where the body ends |
| `Accept` | Request | Which media types the client will take back |
| `Authorization` | Request | Credentials, e.g. `Bearer <token>` |
| `Cache-Control` | Both | Caching rules, e.g. `no-store`, `max-age=60` |
| `Connection` | Both | Whether to keep the TCP connection open (`keep-alive`) or close it (`close`) |

`Content-Length` is load-bearing: recall from the TCP lesson that TCP is a *byte
stream* with no message boundaries. HTTP has to reintroduce boundaries itself, and
`Content-Length` is how — the receiver reads headers up to the blank line, then
reads *exactly* that many more bytes as the body. Your Build-It client depends on
this to read two responses off one connection without them bleeding together.

### Keep-alive: reusing one TCP connection

Opening a TCP connection isn't free — it costs a three-way handshake (a full
network round-trip) before a single byte of HTTP moves. HTTP/1.0's default was one
connection per request: handshake, request, response, close, repeat. Fetch a page
with 30 images and you paid for 30 handshakes.

HTTP/1.1 fixed this with **persistent connections**, a.k.a. **keep-alive**: after
the response, the connection *stays open* and the next request reuses it. In
HTTP/1.1 this is the **default** — the connection persists unless someone sends
`Connection: close`. One handshake, many requests.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 540" width="100%" style="max-width:720px" role="img" aria-label="Keep-alive versus close, drawn as two sequences over the same client and server. In the keep-alive section a single TCP handshake is followed by three request-response pairs on one connection: GET /a then 200 OK, GET /b then 200 OK, GET /c then 200 OK. In the close section every request needs its own handshake: a TCP handshake, GET /a, 200 OK and close, then a second TCP handshake, GET /b, 200 OK and close. The repeated handshakes in the close section are highlighted in amber to mark the wasted round trips.">
  <defs>
    <marker id="l08b-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="l08b-arw" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
  </defs>
  <text x="380" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">Keep-alive reuses one handshake; close pays for a new one each time</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- section backgrounds -->
    <rect x="72" y="78" width="616" height="222" rx="10" fill="#0fa07f" fill-opacity="0.05"/>
    <rect x="72" y="308" width="616" height="196" rx="10" fill="#e0930f" fill-opacity="0.06"/>
    <!-- actor headers -->
    <g stroke-width="1.7" stroke-linejoin="round">
      <rect x="120" y="42" width="140" height="28" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="500" y="42" width="140" height="28" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    </g>
    <text x="190" y="60" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">Client</text>
    <text x="570" y="60" text-anchor="middle" font-size="11.5" font-weight="700" fill="#0fa07f">Server</text>
    <!-- lifelines -->
    <g stroke="currentColor" stroke-opacity="0.25" stroke-width="1.3" stroke-dasharray="4 5">
      <path d="M190 70 L190 504"/>
      <path d="M570 70 L570 504"/>
    </g>
    <!-- section A note: keep-alive -->
    <rect x="95" y="80" width="570" height="22" rx="6" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-opacity="0.6" stroke-width="1"/>
    <text x="380" y="95" text-anchor="middle" font-size="9.5" font-weight="700" fill="currentColor" opacity="0.9">keep-alive — one connection, three requests</text>
    <!-- section A arrows -->
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M196 126 L564 126" marker-end="url(#l08b-ar)"/>
      <path d="M196 154 L564 154" marker-end="url(#l08b-ar)"/>
      <path d="M564 182 L196 182" marker-end="url(#l08b-ar)"/>
      <path d="M196 210 L564 210" marker-end="url(#l08b-ar)"/>
      <path d="M564 238 L196 238" marker-end="url(#l08b-ar)"/>
      <path d="M196 266 L564 266" marker-end="url(#l08b-ar)"/>
      <path d="M564 294 L196 294" marker-end="url(#l08b-ar)"/>
    </g>
    <g fill="currentColor" text-anchor="middle" font-size="9.5">
      <text x="380" y="120">TCP handshake (once)</text>
      <text x="380" y="148">GET /a</text>
      <text x="380" y="176">200 OK</text>
      <text x="380" y="204">GET /b (same connection)</text>
      <text x="380" y="232">200 OK</text>
      <text x="380" y="260">GET /c (same connection)</text>
      <text x="380" y="288">200 OK</text>
    </g>
    <!-- section B note: close -->
    <rect x="95" y="310" width="570" height="22" rx="6" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f" stroke-opacity="0.6" stroke-width="1"/>
    <text x="380" y="325" text-anchor="middle" font-size="9.5" font-weight="700" fill="currentColor" opacity="0.9">Connection: close — a fresh connection each time</text>
    <!-- section B ordinary arrows -->
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M196 384 L564 384" marker-end="url(#l08b-ar)"/>
      <path d="M564 412 L196 412" marker-end="url(#l08b-ar)"/>
      <path d="M196 468 L564 468" marker-end="url(#l08b-ar)"/>
      <path d="M564 496 L196 496" marker-end="url(#l08b-ar)"/>
    </g>
    <!-- section B wasted handshakes (amber) -->
    <g fill="none" stroke="#e0930f" stroke-width="1.7">
      <path d="M196 356 L564 356" marker-end="url(#l08b-arw)"/>
      <path d="M196 440 L564 440" marker-end="url(#l08b-arw)"/>
    </g>
    <g text-anchor="middle" font-size="9.5">
      <text x="380" y="350" fill="#e0930f" font-weight="700">TCP handshake</text>
      <text x="380" y="378" fill="currentColor">GET /a</text>
      <text x="380" y="406" fill="currentColor">200 OK + close</text>
      <text x="380" y="434" fill="#e0930f" font-weight="700">TCP handshake (again!)</text>
      <text x="380" y="462" fill="currentColor">GET /b</text>
      <text x="380" y="490" fill="currentColor">200 OK + close</text>
    </g>
    <!-- footer -->
    <text x="380" y="524" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.8">Keep-alive pays the handshake once; close pays it again for every request.</text>
  </g>
</svg>
```

The saving is one handshake per request after the first — the difference between a
snappy API and a sluggish one under load. This only works because each response
declares its length: to send a second response down the same pipe, the first must
say exactly where it ends.

Two related mechanisms finish the picture:

- **Chunked transfer encoding.** Sometimes the server doesn't know the body's total
  size up front (it's streaming a report as it's generated). Instead of
  `Content-Length`, it sends `Transfer-Encoding: chunked` and writes the body as a
  series of size-prefixed chunks, terminated by a zero-size chunk. That final
  zero-chunk is the boundary that keep-alive needs when the length is unknown.
- **Cookies.** HTTP is stateless, but sessions need memory. The server sends
  `Set-Cookie: session=abc123` on a response; the browser echoes `Cookie:
  session=abc123` on every later request, letting the server re-identify the
  client. Cookies are a workaround *bolted onto* a stateless protocol — the
  statefulness lives in the exchanged header, not in HTTP itself.

## Build It

The full implementations are in [`code/`](../code/). Each file starts a local
server on a background thread, runs against it, prints the exchange, and exits —
no external network, no services.

### Type an HTTP request as bytes

[`code/http_client.py`](../code/http_client.py) builds a GET request the way the
protocol defines it — a request line, header lines, and a blank line — encodes it
to ASCII, and pushes it down a raw socket. There is no HTTP library on the client
side; it's just bytes:

```python
def build_get_request(path, host, keep_alive):
    connection = "keep-alive" if keep_alive else "close"
    lines = [
        f"GET {path} HTTP/1.1",          # request line: METHOD target VERSION
        f"Host: {host}",                 # mandatory in HTTP/1.1
        "Accept: application/json",
        f"Connection: {connection}",     # keep-alive == reuse this socket
    ]
    return (CRLF.join(lines) + CRLF + CRLF).encode("ascii")  # blank line ends headers
```

Parsing the reply is the mirror image: read bytes until the blank line to get the
status line and headers, then read *exactly* `Content-Length` more bytes for the
body. Honoring the length is what lets us read a second response off the same
socket without over-reading into it:

```python
head, _, buffer = buffer.partition(b"\r\n\r\n")   # split headers from body
length = int(headers.get("content-length", "0"))
while len(buffer) < length:                        # read exactly the body
    buffer += sock.recv(4096)
body, leftover = buffer[:length], buffer[length:]  # leftover = next response
```

### Watch keep-alive save a handshake

The client opens **one** TCP connection and sends **two** requests over it. Run it:

```bash
python3 code/http_client.py
```

```text
[client] opened one TCP connection to 127.0.0.1:54808

[client] request 1 (raw bytes over the socket):
GET /first HTTP/1.1\r\n
    Host: 127.0.0.1:54808\r\n
    ...
    Connection: keep-alive\r\n
    \r\n
[client] response 1 (connection kept open):
  status line ......... HTTP/1.1 200 OK
  Content-Length ...... 30
  body ................ {"path": "/first", "ok": true}

[client] request 2 sent on the SAME socket (Connection: close)
[client] response 2 (server will now close):
  status line ......... HTTP/1.1 200 OK
  body ................ {"path": "/second", "ok": true}

[done] Two HTTP requests, one TCP connection — one handshake saved.
```

The server is stdlib `http.server` with one line that matters:
`protocol_version = "HTTP/1.1"`. That switch turns on persistent connections — the
handler keeps reading requests off the same socket until a request says
`Connection: close`.

### Classify any status code

[`code/status_codes.py`](../code/status_codes.py) maps a code to its family by its
first digit and looks up the canonical meaning, then prints a worked example from
each family:

```python
def classify(code):
    family_digit = code // 100                     # 200 -> 2, 404 -> 4
    family_name, family_blurb = FAMILIES[family_digit]
    meaning = MEANINGS.get(code, "(no canonical name)")
    return family_name, family_blurb, meaning
```

```bash
python3 code/status_codes.py
```

It even classifies codes it has no name for — because the family lives in the
first digit, `418` is unambiguously a `4xx` client error whether or not you've
memorized it.

## Use It

You will almost never assemble request bytes by hand in production — a client
library does it. But now you know exactly what it's doing. The stdlib
`http.client` speaks the same protocol you just built, and crucially it
**pools the connection** so keep-alive happens for you:

```python
import http.client

conn = http.client.HTTPConnection("127.0.0.1", 54808)  # one TCP connection
conn.request("GET", "/first")                           # request 1
print(conn.getresponse().read())
conn.request("GET", "/second")                          # request 2, SAME socket
print(conn.getresponse().read())
conn.close()
```

Reusing one `HTTPConnection` (or, in the popular `requests`/`httpx` libraries, one
`Session`) is the single biggest client-side performance win for a service that
makes many calls to the same host: you pay the TCP handshake once, not per
request. On the server side, a framework maps `(method, path)` to a handler and
turns your return value into a status line, headers, and body — the exact three
parts you parsed by hand. When you write `return JSONResponse(status_code=201)`,
you are filling in the status line and `Content-Type`/`Content-Length` headers of
a message shaped precisely like the ones above.

Knowing the protocol changes how you debug. A `405 Method Not Allowed` means your
route exists but not for that verb. A request that hangs after the headers is
usually a `Content-Length` that doesn't match the body's real size. An API that's
inexplicably slow is often opening a fresh connection per call — reuse the session
and the handshakes disappear.

## Ship It

The artifact for this lesson is an HTTP semantics review prompt:
[`outputs/prompt-http-semantics.md`](../outputs/prompt-http-semantics.md) — feed it
an endpoint (its method, the status codes it returns, its headers) and it audits
the design against HTTP's rules: is the method's safe/idempotent contract
honored, is the status code in the right family, are `Content-Type` /
`Content-Length` / `Cache-Control` set correctly, and is keep-alive being used.
You can apply it because you just built both ends of the exchange.

## Key takeaways

- Every HTTP message is **start line · headers · blank line · optional body**, all
  text with `CRLF` line endings, riding on a TCP byte stream (RFC 9110/9112).
- The **method** states intent. **Safe** = read-only (`GET`/`HEAD`/`OPTIONS`);
  **idempotent** = repeat-safe (`GET`, `PUT`, `DELETE`) — which decides what a
  client may retry.
- **Status codes** group by first digit: `1xx` info, `2xx` success, `3xx`
  redirect, `4xx` *client* error, `5xx` *server* error. The 4xx/5xx line tells you
  which side to fix.
- **Headers** carry the metadata; `Content-Length` reintroduces the message
  boundaries that TCP's stream throws away.
- **Keep-alive** (HTTP/1.1's default) reuses one TCP connection for many requests,
  saving a handshake each time — the reason connection pooling makes APIs fast.
