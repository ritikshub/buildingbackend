# The Application Layer: Protocols & Ports

> The transport layer moves bytes between programs. The application layer decides what those bytes *mean* — the verbs, replies, and rules two programs agree on so a stream of bytes becomes a request for a web page or the delivery of an email.

**Type:** Build
**Languages:** Python
**Prerequisites:** Lessons 05–06 — the transport layer and DNS. You should know that TCP (Transmission Control Protocol) gives you a reliable byte stream, that UDP (User Datagram Protocol) gives you best-effort datagrams, and that a port is a 16-bit number that selects a program on a machine.
**Time:** ~75 minutes

## The Problem

You built a TCP connection in Lesson 05. It hands you a reliable, ordered stream
of bytes between two programs — and nothing more. TCP does not know what a "web
page" is, or an "email," or a "file." It moves bytes; it has no opinion about
their meaning.

So two programs that want to *do* something together — a browser and a web
server, a mail client and a mail server — need a second agreement layered on top
of the connection: **who speaks first, what a request looks like, how a reply is
shaped, when the conversation ends.** That agreement is an **application-layer
protocol**, and this is the layer where the systems you build actually live.

Two questions fall out of this. First: a server machine runs many services at
once — web, mail, SSH. Packets for all of them arrive at the same IP address. How
does the kernel hand *this* connection to the web server and *that* one to the
mail server? Second: once the right program has the bytes, what language do the
two ends speak? By the end of this lesson you will have answered both — you will
build a **port scanner** that finds services by the port they listen on, and a
tiny **text-protocol server** that speaks a line-based dialogue exactly the way
SMTP (Simple Mail Transfer Protocol) does.

## The Concept

An application-layer protocol is a contract for a conversation. It sits on top of
a transport connection (usually TCP, sometimes UDP) and defines the grammar the
two programs use. The web uses HTTP (HyperText Transfer Protocol); mail uses
SMTP, IMAP, and POP3; remote login uses SSH. Each is just an agreed set of
messages flowing over a socket you already know how to open.

### Ports: how a packet finds its service

An IP (Internet Protocol) address gets a packet to the right *machine*. A
**port** — the 16-bit number in the TCP or UDP header — gets it to the right
*program* on that machine. The kernel keeps a table of which program is listening
on which port; when a packet arrives, it reads the destination port and hands the
data to whichever socket claimed it. Port 443 on a server goes to the web server;
port 22 goes to the SSH daemon. Same IP, same network card, different doors.

IANA (the Internet Assigned Numbers Authority) divides the 0–65535 port space
into three ranges (RFC 6335):

| Range | Name | Used for |
|---|---|---|
| `0`–`1023` | Well-known | Standard services with a fixed, universally agreed port: 80 (HTTP), 443 (HTTPS), 22 (SSH). Binding one usually needs admin rights, so a random program can't impersonate the web server. |
| `1024`–`49151` | Registered | Ports vendors register for their software: 3306 (MySQL), 5432 (PostgreSQL), 6379 (Redis). Convention, not privilege. |
| `49152`–`65535` | Ephemeral | Short-lived source ports the OS hands a client for an *outgoing* connection. Your browser's end of a request lives here. |

Because well-known ports are fixed, a client needs no directory to find a
service: "connect to port 443" *means* "talk to the web server." The port number
is the rendezvous point.

### The well-known ports you will actually meet

These are the doors worth memorizing. Every one is a service you will connect to,
run, or debug as a backend engineer:

| Port | Protocol | Transport | Purpose |
|---|---|---|---|
| 20 | FTP-data | TCP | File Transfer Protocol — the bulk data channel |
| 21 | FTP | TCP | File Transfer Protocol — the control/command channel |
| 22 | SSH | TCP | Secure Shell — encrypted remote login and tunnels |
| 23 | Telnet | TCP | Remote login in cleartext — obsolete and insecure, kept for history |
| 25 | SMTP | TCP | Simple Mail Transfer Protocol — server-to-server mail relay |
| 53 | DNS | UDP + TCP | Domain Name System — turns names into IP addresses |
| 67 | DHCP (server) | UDP | Dynamic Host Configuration Protocol — hands out IP leases |
| 68 | DHCP (client) | UDP | Dynamic Host Configuration Protocol — the client's side |
| 80 | HTTP | TCP | HyperText Transfer Protocol — the plaintext web |
| 110 | POP3 | TCP | Post Office Protocol v3 — download-and-delete mailbox access |
| 123 | NTP | UDP | Network Time Protocol — synchronizes machine clocks |
| 143 | IMAP | TCP | Internet Message Access Protocol — server-side mailbox access |
| 443 | HTTPS | TCP | HTTP over TLS — the encrypted web |
| 587 | SMTP (submission) | TCP | Authenticated mail submission from a client to its server |
| 993 | IMAPS | TCP | IMAP over TLS |
| 995 | POP3S | TCP | POP3 over TLS |

A few patterns are worth naming. Mail is split by job: **SMTP** (25/587) *sends*
mail between servers, while **IMAP** (143/993) and **POP3** (110/995) *fetch* it
for reading — POP3 downloads and deletes, IMAP leaves messages on the server and
syncs. **FTP** uses two ports at once (a control channel on 21, a separate data
channel on 20) — a design detail that becomes important below. And the
"secure" ports (443, 993, 995, 587) are almost always the plaintext protocol
wrapped in TLS (Transport Layer Security), which you will build later in the phase.

### Text protocols vs binary protocols

Once bytes reach the right program, the two ends need a shared grammar. Protocols
split into two families by how that grammar is encoded.

A **text protocol** is human-readable and usually **line-based**: messages are
lines of ASCII text terminated by carriage-return + line-feed (`\r\n`), and you
can literally type them by hand. HTTP and SMTP are text protocols — you can open
a raw socket to a web server, type `GET / HTTP/1.1`, and read the reply. This
makes them easy to learn, debug, and inspect with tools like `tcpdump`, at the
cost of verbosity: `Content-Length: 1024` is far more bytes than the number 1024.

A **binary protocol** encodes messages as packed bytes — fixed-width fields,
length prefixes, numeric codes — that are compact and fast to parse but
unreadable without a decoder. DNS is binary (you decoded its cousin, the TCP
header, in Lesson 05); so is gRPC (Google's Remote Procedure Call framework,
which rides HTTP/2). The trade is the same one you saw with headers: text spends
bytes to buy legibility; binary spends legibility to buy density and speed.

### Stateful vs stateless

Protocols also differ in whether the server *remembers* anything between messages.

A **stateless** protocol treats every request independently — the server keeps no
memory of what came before. **HTTP** is the classic example: each request carries
everything the server needs to handle it, and two requests on the same connection
are unrelated as far as the protocol is concerned. This is why HTTP scales so
well horizontally: any server can handle any request, because none of them holds
session state. (Cookies and sessions are how applications *add* state back on top
of a stateless protocol.)

A **stateful** protocol keeps a session alive across messages: the server
remembers where you are in the conversation, and later commands depend on earlier
ones. **FTP** is stateful — after you log in and `CD` into a directory, the server
remembers that directory for your next command; the session has a current
position. SMTP is stateful within a single mail transaction: `MAIL FROM` must come
before `RCPT TO`, which must come before `DATA`. Statefulness makes some
interactions natural but ties a client to one server and complicates recovery
after a dropped connection.

### Request-response vs streaming

A last axis is the *shape* of the conversation. **Request-response** is
lock-step: the client sends one request, waits, gets one reply, repeats. HTTP/1.1
and classic SMTP work this way. It is simple to reason about but idle whenever one
side is waiting.

**Streaming / push** protocols keep data flowing without a request per message:
the server can push events to the client at any time (WebSockets, Server-Sent
Events), or both sides send continuously (gRPC streaming, live video over RTP,
the Real-time Transport Protocol). Streaming fits real-time feeds and long-lived
subscriptions where polling with fresh requests would be wasteful.

### A worked example: the SMTP dialogue

Nothing makes "text protocol" concrete like watching one. Here is a real SMTP
conversation (RFC 5321) that hands one message to a mail server. The client's
lines are commands; the server answers each with a **three-digit status code** —
`2xx` means success, `3xx` means "go ahead, send more," `5xx` means error:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 820 492" width="100%" style="max-width:800px" role="img" aria-label="Sequence diagram of one SMTP mail transaction between a client (the sender) and a server (the mail host). The server greets first with 220 ready; the client sends HELO, then MAIL FROM, RCPT TO, and DATA, each answered by a server status code such as 250 or 354; the client sends the message body ending with a lone dot on its own line, the server replies 250 OK queued, and the client sends QUIT, to which the server answers 221 Bye. Client commands go out and three-digit status codes come back.">
  <defs>
    <marker id="l07-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="410" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">One SMTP mail transaction, line by line</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- actor headers -->
    <g stroke-width="1.7" stroke-linejoin="round">
      <rect x="75" y="40" width="130" height="36" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="615" y="40" width="130" height="36" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    </g>
    <text x="140" y="57" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">Client</text>
    <text x="140" y="69" text-anchor="middle" font-size="8" fill="#3553ff" opacity="0.75">sender</text>
    <text x="680" y="57" text-anchor="middle" font-size="11.5" font-weight="700" fill="#0fa07f">Server</text>
    <text x="680" y="69" text-anchor="middle" font-size="8" fill="#0fa07f" opacity="0.75">mail host</text>
    <!-- lifelines -->
    <g stroke="currentColor" stroke-opacity="0.25" stroke-width="1.3" stroke-dasharray="4 5">
      <path d="M140 76 L140 452"/>
      <path d="M680 76 L680 452"/>
    </g>
    <!-- messages -->
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M674 104 L146 104" marker-end="url(#l07-ar)"/>
      <path d="M146 132 L674 132" marker-end="url(#l07-ar)"/>
      <path d="M674 160 L146 160" marker-end="url(#l07-ar)"/>
      <path d="M146 188 L674 188" marker-end="url(#l07-ar)"/>
      <path d="M674 216 L146 216" marker-end="url(#l07-ar)"/>
      <path d="M146 244 L674 244" marker-end="url(#l07-ar)"/>
      <path d="M674 272 L146 272" marker-end="url(#l07-ar)"/>
      <path d="M146 300 L674 300" marker-end="url(#l07-ar)"/>
      <path d="M674 328 L146 328" marker-end="url(#l07-ar)"/>
      <path d="M146 356 L674 356" marker-end="url(#l07-ar)"/>
      <path d="M674 384 L146 384" marker-end="url(#l07-ar)"/>
      <path d="M146 412 L674 412" marker-end="url(#l07-ar)"/>
      <path d="M674 440 L146 440" marker-end="url(#l07-ar)"/>
    </g>
    <g fill="currentColor" text-anchor="middle" font-size="9.5">
      <text x="410" y="98">220 mail.example.com ready</text>
      <text x="410" y="126">HELO relay.example.org</text>
      <text x="410" y="154">250 Hello, pleased to meet you</text>
      <text x="410" y="182">MAIL FROM:&lt;alice@example.org&gt;</text>
      <text x="410" y="210">250 OK</text>
      <text x="410" y="238">RCPT TO:&lt;bob@example.com&gt;</text>
      <text x="410" y="266">250 OK</text>
      <text x="410" y="294">DATA</text>
      <text x="410" y="322">354 Start mail input; end with a lone dot</text>
      <text x="410" y="350">Subject: hi &#8230; message body &#8230; &lt;CRLF&gt;.&lt;CRLF&gt;</text>
      <text x="410" y="378">250 OK, queued as 9F2A1</text>
      <text x="410" y="406">QUIT</text>
      <text x="410" y="434">221 Bye</text>
    </g>
    <!-- footer -->
    <text x="410" y="474" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.75">SMTP is a human-readable, line-based request/response protocol — client commands go out, 3-digit status codes come back.</text>
  </g>
</svg>
```

Read it top to bottom and every property from this lesson is visible at once. It
is **text**: every line is typeable ASCII. It is **line-based**: each message ends
at a `\r\n`. It is **stateful**: `MAIL FROM` opens a transaction, `RCPT TO` adds a
recipient to it, `DATA` sends the body of that same transaction — order matters. It
is **request-response**: the client sends one verb and waits for one status line
before the next. And the **status codes** are how a machine reads a reply meant to
be legible to a human. This is the entire idea of an application-layer protocol,
in twelve lines. The server you build next speaks the same shape.

## Build It

The implementations are in [`code/`](../code/). Each file is self-contained: it
starts a server (or listeners) on a background thread, drives a client against it
on `127.0.0.1`, prints the exchange, and exits. No external network, no services
to install.

### Map ports to services — the registry and a scanner

[`code/ports.py`](../code/ports.py) does two things. First, it holds the
well-known-ports table as a plain dict and looks names up — this *is* what the
kernel's mental model is, a map from port number to service:

```python
WELL_KNOWN_PORTS = {
    22: ("SSH", "tcp", "Secure Shell — encrypted remote login and tunnels"),
    53: ("DNS", "udp/tcp", "Domain Name System — name-to-address lookups"),
    80: ("HTTP", "tcp", "HyperText Transfer Protocol — the plaintext web"),
    443: ("HTTPS", "tcp", "HTTP over TLS — the encrypted web"),
    # ...
}

def lookup(port: int) -> str:
    entry = WELL_KNOWN_PORTS.get(port)
    return "(unassigned/unknown)" if entry is None else f"{entry[0]} — {entry[2]}"
```

Second, it finds *live* services the way a scanner does. A closed port refuses a
connection instantly; an open one completes the TCP handshake. So a **port scan**
is just a `connect()` to each port with a short timeout — success means something
is listening. The file stands up two throwaway listeners on chosen ports, then
sweeps a small range and reports what it found:

```python
def is_open(port: int, timeout: float = 0.2) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(timeout)                 # a closed port fails fast
        return probe.connect_ex((HOST, port)) == 0  # 0 == connected == open
```

`connect_ex` returns an error number instead of raising, which is exactly what
you want when most ports in a scan are closed. Run it:

```bash
python code/ports.py
```

It prints the registry lookups, then scans `49500`–`49519` and reports the two
ports it opened as `OPEN`, naming each through the registry. That connect-and-see
loop is how tools like `nmap` map a machine's services.

### Speak a text protocol — a line-based server

[`code/text_protocol_demo.py`](../code/text_protocol_demo.py) builds the SMTP
shape from the diagram above in miniature. The server speaks first with a banner
(like SMTP's `220`), then answers verbs with three-digit status lines. The trick
that makes a text protocol pleasant to write is `socket.makefile()`, which wraps
the raw socket in a file object so you can iterate it **line by line**:

```python
with conn, conn.makefile("rw", newline="") as stream:
    stream.write(f"220 mock-service ready{CRLF}")   # server greets first
    stream.flush()
    for raw in stream:                              # one loop iteration per line
        verb, _, rest = raw.rstrip("\r\n").partition(" ")
        if verb.upper() == "ECHO":
            stream.write(f"250 {rest}{CRLF}")       # 2xx = success, SMTP-style
        elif verb.upper() == "QUIT":
            stream.write(f"221 bye{CRLF}"); stream.flush(); break
        stream.flush()
```

The client drives the dialogue — `GREET`, `ECHO <text>`, `QUIT` — and prints each
line it sends and receives, so you watch the conversation the way the SMTP
sequence diagram reads:

```bash
python code/text_protocol_demo.py
```

The output is a labeled transcript (`C:` for client lines, `S:` for server
lines). Change `ECHO ...` to a bogus verb and the server answers `500 unknown
command` — the same way a real text protocol rejects a command it doesn't know.

## Use It

You almost never implement HTTP or SMTP by hand in production — the standard
library ships clients for the common application protocols, each one a wrapper
over exactly the socket-and-lines dance you just built. `http.client` speaks HTTP;
`smtplib` speaks the SMTP dialogue from the diagram; `ftplib`, `imaplib`, and
`poplib` cover the rest. Watch `smtplib` run the same verbs you saw above:

```python
import smtplib

# Talks to a mail server on port 587; under the hood it sends EHLO, MAIL FROM,
# RCPT TO, DATA — the exact dialogue from the sequence diagram, framed as lines.
with smtplib.SMTP("smtp.example.com", 587) as server:
    server.set_debuglevel(1)          # prints every protocol line it sends/receives
    server.login("alice", "app-password")
    server.sendmail(
        "alice@example.org",
        ["bob@example.com"],
        "Subject: hi\r\n\r\nsent over a text protocol",
    )
```

Turn on `set_debuglevel(1)` and the library prints the raw `250` and `354` status
lines as it goes — proof that the friendly `sendmail()` call is the SMTP
conversation underneath. The `http.server` module is the mirror image on the
server side: it accepts a TCP connection, parses the text of an HTTP request line
and headers, and calls your handler — the same makefile-and-lines pattern from
`text_protocol_demo.py`, specialized to HTTP.

Knowing the protocol underneath tells you how to debug it. A text protocol you can
reproduce by hand: `nc mail.example.com 25` and type `HELO` to see the server's
reply. A stateless service (HTTP) you can retry blindly, because no request
depends on another; a stateful one (FTP, an SMTP transaction) you must replay in
order after a drop. The port tells you which service you reached; the protocol
family tells you how it will behave when things go wrong.

## Ship It

The artifact for this lesson is a decision prompt:
[`outputs/prompt-choose-app-protocol.md`](../outputs/prompt-choose-app-protocol.md).
Given what you're building — moving files, sending mail, a real-time feed, a
public API — it walks you from requirements (reliability, latency, statefulness,
who initiates messages) to a concrete recommendation: which application protocol,
over which transport, on which port, text or binary. You can reason about it
because you just built the two halves — the port that locates the service and the
line-based grammar it speaks.

## Key takeaways

- The **application layer** is the contract two programs agree on — verbs, replies, and rules — layered on top of a transport connection. HTTP, SMTP, SSH, DNS, and FTP are all just messages over a socket.
- A **port** maps an arriving packet to a service: the kernel reads the 16-bit destination port and hands the bytes to whichever program is listening. Well-known ports (`0`–`1023`) are fixed so clients need no directory; registered (`1024`–`49151`) and ephemeral (`49152`–`65535`) fill the rest.
- **Text protocols** (HTTP, SMTP) are human-readable and line-based — typeable and easy to debug; **binary protocols** (DNS, gRPC) are compact and fast but need a decoder.
- **Stateless** (HTTP) treats each request independently and scales horizontally; **stateful** (FTP, an SMTP transaction) remembers a session, so order matters and recovery is harder.
- **Request-response** is lock-step (HTTP/1.1, SMTP); **streaming/push** keeps data flowing without a request per message (WebSockets, gRPC streaming, RTP).
- A **port scan** is just `connect()` to each port with a short timeout — success means a service is there. That's how you map what's running on a machine.
