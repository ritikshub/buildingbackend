# HTTP Server from a TCP Socket

> A web framework is not magic. It is an accept loop, a text parser, and a string builder — the exact three things you are about to write by hand on a raw socket.

**Type:** Build
**Languages:** Python
**Prerequisites:** Lessons 05 and 08 — the TCP socket and HTTP. You should know the socket lifecycle (`socket` → `bind` → `listen` → `accept`) and the shape of an HTTP request and response.
**Time:** ~75 minutes

## The Problem

You have climbed the whole stack. You started with **bits on a wire** (the physical layer), watched the data-link layer group them into **frames**, saw the network layer wrap those into **packets** addressed to a machine, learned how the transport layer turns unreliable packets into a **TCP byte stream** addressed to a program (Lesson 05), and then read the **HTTP** (HyperText Transfer Protocol) request and response that ride on top of that stream (Lesson 08).

At every level you refused to accept magic: you built the thing by hand, then ran it through the real tool. One box is still sealed, though — the web server. You have typed `app.get("/hello")` or `@app.route("/")` and something answered the browser. What *is* that something? Where does the raw TCP stream from Lesson 05 become the tidy `request.path` and `return "hello"` of a framework?

This is the capstone of the fundamentals arc, and the answer is smaller than you think. In this lesson you assemble everything below it into the thing above it: **an HTTP/1.1 server on a raw TCP socket, in about fifty lines, with no framework at all.** By the end, FastAPI and Flask will look like exactly what they are — the code you are about to write, hardened for concurrency.

## The Concept

An HTTP server is a program that does the same four socket calls you already know — `socket`, `bind`, `listen`, `accept` — and then, for every connection, runs a three-step pipeline: **read** the request bytes, **parse** them into a method and a path, and **build** a correct response string to write back. That is the entire job. HTTP is a plain-text protocol layered on the TCP stream, so "parse" and "build" are just careful string handling.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 700 540" width="100%" style="max-width:680px" role="img" aria-label="The HTTP server accept loop drawn as a flowchart. Once at startup the server calls socket, bind, and listen. Then it enters a loop: accept blocks for a client; read the request bytes with recv until the blank line CRLF CRLF; parse the request line and headers with three string splits; route on the method and path to a handler; build the response with the correct Content-Length; then sendall and close. A return arrow loops from the final step back to accept, so the server handles one client per trip and then waits for the next.">
  <defs>
    <marker id="l09a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="300" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">The accept loop: one request in, one response out — repeat</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- forward arrows -->
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M300 92 L300 114"  marker-end="url(#l09a-ar)"/>
      <path d="M300 158 L300 180" marker-end="url(#l09a-ar)"/>
      <path d="M300 224 L300 246" marker-end="url(#l09a-ar)"/>
      <path d="M300 290 L300 312" marker-end="url(#l09a-ar)"/>
      <path d="M300 356 L300 378" marker-end="url(#l09a-ar)"/>
      <path d="M300 422 L300 444" marker-end="url(#l09a-ar)"/>
    </g>
    <!-- loop-back arrow: last step returns to accept -->
    <path d="M450 466 L520 466 L520 136 L450 136" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" marker-end="url(#l09a-ar)"/>
    <text x="538" y="301" text-anchor="middle" transform="rotate(-90 538 301)" font-size="9" fill="currentColor" opacity="0.8">loop back to accept — one client per trip</text>

    <!-- boxes -->
    <g stroke-width="1.8" stroke-linejoin="round">
      <rect x="150" y="48"  width="300" height="44" rx="10" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
      <rect x="150" y="114" width="300" height="44" rx="10" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="150" y="180" width="300" height="44" rx="10" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
      <rect x="150" y="246" width="300" height="44" rx="10" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
      <rect x="150" y="312" width="300" height="44" rx="10" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
      <rect x="150" y="378" width="300" height="44" rx="10" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="150" y="444" width="300" height="44" rx="10" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    </g>

    <!-- main box labels -->
    <g fill="currentColor" text-anchor="middle" font-size="11">
      <text x="300" y="67">socket · bind · listen</text>
      <text x="300" y="133">accept()</text>
      <text x="300" y="199">read request bytes</text>
      <text x="300" y="265">parse request line + headers</text>
      <text x="300" y="331">route on method + path</text>
      <text x="300" y="397">build response</text>
      <text x="300" y="463">sendall + close</text>
    </g>
    <!-- sub labels -->
    <g fill="currentColor" text-anchor="middle" font-size="7.5" opacity="0.6">
      <text x="300" y="82">once, at startup</text>
      <text x="300" y="148">block for a client</text>
      <text x="300" y="214">recv() until \r\n\r\n</text>
      <text x="300" y="280">three string splits</text>
      <text x="300" y="346">(method, path) → handler</text>
      <text x="300" y="412">Content-Length = body bytes</text>
      <text x="300" y="478">write exactly N bytes, then close</text>
    </g>

    <!-- takeaway -->
    <text x="300" y="512" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">A web server is this cycle — accept, read, parse, route, build, send, close —</text>
    <text x="300" y="527" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">run forever; a framework is the same loop hardened for many clients at once.</text>
  </g>
</svg>
```

That loop is the whole lesson. Walk each box.

### The accept loop: a socket that keeps answering

Lesson 05 built a TCP echo server and stopped after one connection. A web server is the same four calls with `accept()` in a loop — each trip round the loop is one client, one request, one response:

- `socket(AF_INET, SOCK_STREAM)` — ask the kernel for a TCP socket. `SOCK_STREAM` *is* the request for TCP.
- `setsockopt(SO_REUSEADDR, 1)` — let us re-bind the port immediately after a restart instead of waiting out TCP's `TIME_WAIT` window. Without it, restarting your server throws "Address already in use."
- `bind((host, port))` — claim a port. Port 80 is HTTP's well-known port; we use a high, unprivileged one for the demo.
- `listen(backlog)` — mark the socket passive and set the **backlog**: how many fully-established connections the kernel will queue while your code is busy handling the current one. Overflow that queue and new clients get refused.
- `accept()` — block until a client completes the TCP handshake, then hand back a *new* connected socket for that one client. The listening socket keeps listening.

### Reading the request bytes

TCP is a **byte stream, not a message stream** (Lesson 05): a single `recv()` may hand you half a request, or two requests glued together. So you cannot assume one `recv()` equals one request. You read in a loop and stop when you have enough to act.

For a request with no body — every `GET` — "enough" means you have seen the **blank line** that ends the headers. In HTTP, every line ends with **CRLF** (Carriage Return + Line Feed, the two bytes `\r\n`), and an *empty* line — `\r\n\r\n` — marks the boundary between the headers and the body (RFC 9112 §2.1). So the read loop is: keep calling `recv()` and appending until `\r\n\r\n` appears in the buffer.

### Parsing the request line and headers

Once you have the header block, parsing it is pure string splitting, because HTTP is designed to be read by humans. An HTTP request looks like this on the wire:

```http
GET /hello HTTP/1.1
Host: 127.0.0.1:54309
Connection: close

```

- **Split head from body** at the first blank line: `raw.partition(b"\r\n\r\n")`.
- **The first line is the request line**: three space-separated tokens — the **method** (`GET`), the **target path** (`/hello`), and the **version** (`HTTP/1.1`), per RFC 9112 §3.
- **Every remaining line is a header**: `Name: value`. Header names are case-insensitive (RFC 9110 §5.1), so lowercase them as you store them into a dictionary.

That is it. `GET /hello HTTP/1.1` becomes `method="GET"`, `path="/hello"` with three string operations. There is no hidden machinery.

### Routing on method and path

**Routing** is deciding which response a `(method, path)` pair earns. In a framework you write `@app.get("/hello")`; by hand it is a dictionary lookup and a couple of `if`s:

- Method is not `GET`? Return **405 Method Not Allowed**, and include an `Allow: GET` header — RFC 9110 §15.5.6 requires it so the client learns what *is* allowed.
- Path is in your route table? Return **200 OK** with that route's body.
- Otherwise return **404 Not Found**.

A production router adds path parameters (`/users/{id}`), wildcards, and precedence rules, but the core is exactly this: match `(method, path)`, pick a handler.

### Content-Length: the header that prevents a hang

Here is the single most important detail, and the classic bug. Because TCP is a stream with no message boundaries, the client needs to know **where your response body ends**. The `Content-Length` header tells it: "the body is exactly *N* bytes." You send those *N* bytes, the client reads *N* bytes, everyone moves on.

Get it wrong and it fails in the two ways every backend engineer eventually debugs:

- **`Content-Length` too large** — the client reads the body you sent, sees it is short of the promised count, and **blocks waiting for bytes that never arrive.** That is the hang.
- **`Content-Length` too small** — the client stops early and **truncates** your body; leftover bytes pollute the next response on a reused connection.

The subtlety: `Content-Length` is a count of **bytes, not characters.** In the code you will run, the `/` route's body contains an em-dash (`—`), which is three bytes in UTF-8 (Unicode Transformation Format, 8-bit). The visible text is 61 characters but the correct `Content-Length` is `63`. Measure the *encoded bytes*, always. A well-formed response is the status line, the headers, a blank line, then exactly that many body bytes:

```http
HTTP/1.1 200 OK
Content-Type: text/plain; charset=utf-8
Content-Length: 63
Connection: close

Welcome — this page came off a raw TCP socket, no framework.
```

### The exchange, end to end

Put the client and server side by side and the protocol is one round trip over the socket you built in Lesson 05:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 840 360" width="100%" style="max-width:820px" role="img" aria-label="Sequence diagram of one HTTP request and response between a Client and the Server's accept loop over an already-connected TCP socket. First a note spans both sides: TCP is already connected from the SYN, SYN-ACK, ACK handshake in Lesson 05. The client sends GET /hello HTTP/1.1 followed by a Host header and the blank line. A note over the server: read until the blank line CRLF CRLF, parse the request line and headers, then route. The server replies HTTP/1.1 200 OK with Content-Length 51, the blank line, and the body. A note over the client: read the status, the headers, then exactly 51 body bytes. Finally a note spans both sides: Connection close means both sides close the socket.">
  <defs>
    <marker id="l09b-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="420" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">One HTTP round trip over the Lesson 05 socket</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- actor headers -->
    <g stroke-width="1.7" stroke-linejoin="round">
      <rect x="110" y="44" width="160" height="30" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="570" y="44" width="160" height="30" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    </g>
    <text x="190" y="63" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">Client</text>
    <text x="650" y="63" text-anchor="middle" font-size="10.5" font-weight="700" fill="#0fa07f">Server (accept loop)</text>
    <!-- lifelines -->
    <g stroke="currentColor" stroke-opacity="0.25" stroke-width="1.3" stroke-dasharray="4 5">
      <path d="M190 74 L190 242"/>
      <path d="M190 266 L190 320"/>
      <path d="M650 74 L650 166"/>
      <path d="M650 190 L650 320"/>
    </g>

    <!-- note band 1: precondition (both) -->
    <rect x="30" y="86" width="780" height="24" rx="6" fill="#7f7f7f" fill-opacity="0.1" stroke="currentColor" stroke-opacity="0.25" stroke-width="1"/>
    <text x="420" y="102" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.8">TCP already connected (SYN / SYN-ACK / ACK — Lesson 05)</text>

    <!-- message 1: request -->
    <text x="420" y="140" text-anchor="middle" font-size="9.5" fill="currentColor">GET /hello HTTP/1.1\r\nHost: ...\r\n\r\n</text>
    <path d="M196 148 L644 148" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l09b-ar)"/>

    <!-- note band 3: server work (over Server) -->
    <rect x="480" y="166" width="340" height="24" rx="6" fill="#0fa07f" fill-opacity="0.1" stroke="#0fa07f" stroke-opacity="0.5" stroke-width="1"/>
    <text x="650" y="182" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.85">read until \r\n\r\n · parse line + headers · route</text>

    <!-- message 2: response -->
    <text x="420" y="216" text-anchor="middle" font-size="9.5" fill="currentColor">HTTP/1.1 200 OK\r\nContent-Length: 51\r\n\r\n + body</text>
    <path d="M644 224 L196 224" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l09b-ar)"/>

    <!-- note band 5: client work (over Client) -->
    <rect x="20" y="242" width="340" height="24" rx="6" fill="#3553ff" fill-opacity="0.1" stroke="#3553ff" stroke-opacity="0.5" stroke-width="1"/>
    <text x="190" y="258" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.85">read status, headers, then exactly 51 body bytes</text>

    <!-- note band 6: close (both) -->
    <rect x="30" y="286" width="780" height="24" rx="6" fill="#d64545" fill-opacity="0.1" stroke="#d64545" stroke-opacity="0.55" stroke-width="1"/>
    <text x="420" y="302" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.9">Connection: close — both sides close the socket</text>

    <!-- takeaway -->
    <text x="420" y="342" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">Request in, response out, then close — one HTTP/1.1 exchange on the raw TCP socket.</text>
  </g>
</svg>
```

## Build It

The full server is in [`code/http_server.py`](../code/http_server.py) — about fifty lines, every one of them yours. It runs the server on a background thread, fires four client requests at `127.0.0.1` (a 200, another 200, a 404, and a 405), prints the raw bytes going each way, and exits. Run it:

```bash
python code/http_server.py
```

The accept loop is Lesson 05, now answering HTTP:

```python
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(16)                 # backlog: pending connections the kernel queues
    conn, addr = server.accept()      # blocks until a client connects
    raw = read_request(conn)          # recv() in a loop until \r\n\r\n
    method, path, version, headers = parse_request(raw)
    conn.sendall(route(method, path)) # build the response, write it, close
```

Parsing is three string operations — split the head from the body, split the request line, split each header:

```python
def parse_request(raw):
    head, _, body = raw.partition(b"\r\n\r\n")   # blank line ends the headers
    lines = head.split(b"\r\n")
    method, path, version = lines[0].decode("ascii").split(" ", 2)  # request line
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(b": ")
        headers[name.decode("ascii").lower()] = value.decode("ascii")  # case-insensitive
    return method, path, version, headers
```

And building the response is one careful string, with the `Content-Length` computed from the encoded body — never guessed:

```python
def build_response(status, reason, body_text, extra_headers=None):
    body = body_text.encode("utf-8")             # measure BYTES, not characters
    header_lines = [
        "HTTP/1.1 {} {}".format(status, reason),
        "Content-Type: text/plain; charset=utf-8",
        "Content-Length: {}".format(len(body)),  # the header that prevents a hang
        "Connection: close",
    ]
    for name, value in (extra_headers or []):
        header_lines.append("{}: {}".format(name, value))
    head = ("\r\n".join(header_lines) + "\r\n\r\n").encode("ascii")  # blank line, then body
    return head + body
```

Read the printed output and match it to the code: the `GET /` and `GET /hello` requests return `200 OK`; `GET /does-not-exist` returns `404 Not Found`; `POST /hello` returns `405 Method Not Allowed` with the `Allow: GET` header. Notice the `/` response reports `Content-Length: 63` even though the sentence is 61 characters — those two extra bytes are the em-dash, encoded. That is the byte-vs-character distinction made visible.

## Use It

Nobody hand-rolls the parser in production, because getting HTTP fully right — chunked bodies, keep-alive, header folding, malformed input — is a lot of careful code. The Python standard library ships that code as `http.server`. Its `BaseHTTPRequestHandler` **is** the accept loop, the request parser, and the response framing you just wrote, already done. You only supply the handlers.

[`code/framework_server.py`](../code/framework_server.py) serves the identical routes through it. Run it:

```bash
python code/framework_server.py
```

The whole server collapses to a class. You get `self.path` already parsed for you, and `send_response`/`send_header`/`end_headers` write the status line and CRLF framing:

```python
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        body = ROUTES.get(self.path)          # routing: a dict lookup, same as before
        if body is None:
            self._respond(404, "No resource at {}\n".format(self.path))
        else:
            self._respond(200, body)

    def _respond(self, status, text, extra_headers=None):
        payload = text.encode("utf-8")
        self.send_response(status)            # writes "HTTP/1.1 <status> <reason>"
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))  # STILL your job to measure
        self.end_headers()                    # writes the blank line
        self.wfile.write(payload)
```

Look at what stayed and what left. The socket lifecycle, the `recv()` loop, the request-line split, the CRLF framing — gone, absorbed into the base class. But `do_GET` versus `do_POST` is still routing on the method; the `ROUTES` dict lookup is still routing on the path; and `Content-Length` is *still computed by hand* — the library sends the header you give it, but it does not measure your body for you. The parts that disappeared are the mechanical ones; the parts that are your application stayed exactly where they were.

Now scale the mental model up. **FastAPI, Flask, Express, and Go's `net/http` are this same three-part machine** — accept loop, parser, response builder — hardened for the real world: many connections at once (threads, async event loops, or worker processes), keep-alive so one TCP connection serves many requests, strict limits so a malformed request cannot exhaust memory, and a routing table that matches `/users/{id}` instead of a fixed dict. The decorator `@app.get("/hello")` is sugar over the exact dictionary lookup you wrote. There is no additional layer of magic underneath — you have now seen all the way down.

## Ship It

The artifact for this lesson is an HTTP debugging prompt: [`outputs/prompt-http-debugging.md`](../outputs/prompt-http-debugging.md). It walks from a symptom — a request that hangs, a truncated body, a 404 that should be a 200, a 405, a connection that closes early — down to the exact stage of the read → parse → route → respond pipeline responsible. You can use it because you now know every stage from the inside: you built it.

## Key takeaways

- An HTTP server is three things on top of a TCP socket: an **accept loop**, a **request parser**, and a **response builder**. Nothing else.
- The accept loop is Lesson 05's `socket` → `bind` → `listen` → `accept`, with `accept()` in a loop and `SO_REUSEADDR` set so the port frees on restart.
- HTTP is **plain text over the byte stream**: lines end in **CRLF** (`\r\n`), and a **blank line** (`\r\n\r\n`) separates headers from body. Read until you see it — one `recv()` is never guaranteed to hold a whole request.
- Parsing a request is three string splits: head from body, the **request line** into method/path/version, and each **header** into a case-insensitive name/value.
- **`Content-Length` must equal the body's length in bytes** (not characters). Too large and the client hangs; too small and it truncates. This is the classic HTTP-server bug.
- A web framework (FastAPI, Flask, `http.server`) is this exact pipeline hardened for concurrency and edge cases. `@app.get("/hello")` is sugar over the accept-loop-plus-parser-plus-builder you just wrote — no magic remains.
