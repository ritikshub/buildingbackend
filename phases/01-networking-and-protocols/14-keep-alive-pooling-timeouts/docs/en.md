# Keep-Alive, Connection Pooling & Timeouts

> Opening a TCP connection costs a round-trip you pay before sending a single useful byte. Keep-alive reuses the connection, a pool bounds and shares them, and timeouts make sure a silent peer can never hang you forever.

**Type:** Build
**Languages:** Python
**Prerequisites:** Lessons [05](../05-transport-layer-tcp-vs-udp/) and [08](../08-http-in-depth/) — the TCP handshake cost and HTTP keep-alive.
**Time:** ~60 minutes

## The Problem

You wrote a service that calls another service once per request. Under light
load it's fine. Then traffic climbs, and two things break that have nothing to do
with your business logic.

First, latency creeps up. Every call opens a brand-new connection, and opening a
connection isn't free: **TCP** (Transmission Control Protocol) requires a
three-way handshake — a full network round-trip — before your first byte moves,
and if the call is over **HTTPS** (**HTTP** — HyperText Transfer Protocol —
secured over TLS), a **TLS** (Transport Layer
Security) handshake stacks one or two more round-trips on top. You're spending
more time saying hello than doing work.

Second, the service starts failing with `cannot assign requested address`. Every
connection you close doesn't vanish; it lingers in a TCP state called
**TIME_WAIT** for a couple of minutes. Open thousands of short-lived connections
and you run the machine out of **ephemeral ports** — the temporary source-port
numbers the **OS** (operating system) hands out for outgoing connections — and
new connections simply can't be made.

Both problems have the same fix, and it's the one every production HTTP client and
database driver already uses: stop throwing connections away. Reuse them
(**keep-alive**), keep a bounded set of them ready (a **pool**), and put
**timeouts** on every wait so one stuck peer can't freeze the whole thing. In
this lesson you'll build a thread-safe connection pool and a timeout demo by
hand, in Python, with nothing but the standard library.

## The Concept

A connection is a resource, like a file handle or a lock. The naive pattern —
open, use once, close — is the same mistake as opening a file for every line you
write. The fix is the same too: open it once, reuse it, and bound how many you
hold.

### The cost of a new connection

From Lesson 05 you know a TCP connection starts with a three-way handshake:
`SYN`, `SYN-ACK`, `ACK`. That's one round-trip of pure setup before any request
data flows. The **RTT** (round-trip time) to a server across a data center might
be 1 ms; across the internet, 50–150 ms. For HTTPS, the TLS handshake adds
another one or two round-trips to negotiate keys. So the *first byte* of a cold
HTTPS request can cost three round-trips of overhead — and you pay it again for
every connection you open and discard.

On localhost the handshake is near-instant, which hides the cost entirely. That's
why the Build-It code adds a small fixed delay to each new connection: to make
visible the round-trip that a real network would charge you.

### Keep-alive: reuse the connection

**Keep-alive** (also called a *persistent connection*) means: after a
request/response completes, don't close the connection — keep it open and send
the next request over the same socket. HTTP/1.1 made this the default (RFC 9112
§9); the connection stays open until one side sends `Connection: close` or an
idle timeout reaps it.

The payoff is one handshake amortized over many requests instead of one handshake
per request:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 504" width="100%" style="max-width:720px" role="img" aria-label="Sequence diagram in which a new TCP connection is opened for every request. Three times in a row the client performs a full three-way handshake — SYN, SYN-ACK, ACK — then sends one request, receives one response, and closes the connection with a FIN. The three handshakes are tinted amber and the three closes red to mark them as repeated setup and teardown paid once per request.">
  <defs>
    <marker id="l14a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="l14a-am" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
    <marker id="l14a-cx" markerWidth="12" markerHeight="12" refX="6" refY="6" orient="auto"><path d="M2,2 L10,10 M10,2 L2,10" fill="none" stroke="#d64545" stroke-width="1.8"/></marker>
  </defs>
  <text x="380" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">New connection per request: a fresh handshake every time</text>
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
      <path d="M190 74 L190 462"/>
      <path d="M570 74 L570 462"/>
    </g>
    <!-- note band -->
    <rect x="95" y="88" width="570" height="22" rx="6" fill="#7f7f7f" fill-opacity="0.1" stroke="currentColor" stroke-opacity="0.25" stroke-width="1"/>
    <text x="380" y="103" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.8">New connection per request — 3 requests, 3 handshakes</text>
    <!-- handshake arrows (amber = wasted setup) -->
    <g fill="none" stroke="#e0930f" stroke-width="1.7">
      <path d="M196 140 L564 140" marker-end="url(#l14a-am)"/>
      <path d="M196 252 L564 252" marker-end="url(#l14a-am)"/>
      <path d="M196 364 L564 364" marker-end="url(#l14a-am)"/>
    </g>
    <!-- request / response arrows (the real work) -->
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M196 168 L564 168" marker-end="url(#l14a-ar)"/>
      <path d="M564 196 L196 196" marker-end="url(#l14a-ar)"/>
      <path d="M196 280 L564 280" marker-end="url(#l14a-ar)"/>
      <path d="M564 308 L196 308" marker-end="url(#l14a-ar)"/>
      <path d="M196 392 L564 392" marker-end="url(#l14a-ar)"/>
      <path d="M564 420 L196 420" marker-end="url(#l14a-ar)"/>
    </g>
    <!-- FIN close arrows (red, ending in an X = wasted teardown) -->
    <g fill="none" stroke="#d64545" stroke-width="1.7">
      <path d="M196 224 L560 224" marker-end="url(#l14a-cx)"/>
      <path d="M196 336 L560 336" marker-end="url(#l14a-cx)"/>
      <path d="M196 448 L560 448" marker-end="url(#l14a-cx)"/>
    </g>
    <!-- message labels -->
    <g text-anchor="middle" font-size="9.5">
      <text x="380" y="134" fill="#e0930f">SYN / SYN-ACK / ACK (handshake #1)</text>
      <text x="380" y="162" fill="currentColor">request 1</text>
      <text x="380" y="190" fill="currentColor">response 1</text>
      <text x="380" y="218" fill="#d64545">FIN — close #1</text>
      <text x="380" y="246" fill="#e0930f">SYN / SYN-ACK / ACK (handshake #2)</text>
      <text x="380" y="274" fill="currentColor">request 2</text>
      <text x="380" y="302" fill="currentColor">response 2</text>
      <text x="380" y="330" fill="#d64545">FIN — close #2</text>
      <text x="380" y="358" fill="#e0930f">SYN / SYN-ACK / ACK (handshake #3)</text>
      <text x="380" y="386" fill="currentColor">request 3</text>
      <text x="380" y="414" fill="currentColor">response 3</text>
      <text x="380" y="442" fill="#d64545">FIN — close #3</text>
    </g>
    <!-- footer -->
    <text x="380" y="486" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.7">Every request pays for a full handshake and teardown it never reuses.</text>
  </g>
</svg>
```

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 402" width="100%" style="max-width:720px" role="img" aria-label="Sequence diagram of a kept-alive connection. The client performs a single three-way handshake once, shown in green, then reuses the same open connection to send three requests and receive three responses. Afterward the connection stays open and is returned to the pool for the next caller. One handshake is amortized across all three requests instead of three separate handshakes.">
  <defs>
    <marker id="l14b-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="l14b-gr" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="380" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">Keep-alive: one handshake, reused for every request</text>
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
      <path d="M190 74 L190 332"/>
      <path d="M570 74 L570 332"/>
    </g>
    <!-- note band -->
    <rect x="95" y="88" width="570" height="22" rx="6" fill="#7f7f7f" fill-opacity="0.1" stroke="currentColor" stroke-opacity="0.25" stroke-width="1"/>
    <text x="380" y="103" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.8">One kept-alive connection — 1 handshake, 3 requests</text>
    <!-- handshake, once (green = paid a single time) -->
    <path d="M196 140 L564 140" fill="none" stroke="#0fa07f" stroke-width="1.7" marker-end="url(#l14b-gr)"/>
    <!-- request / response arrows over the same connection -->
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M196 170 L564 170" marker-end="url(#l14b-ar)"/>
      <path d="M564 200 L196 200" marker-end="url(#l14b-ar)"/>
      <path d="M196 230 L564 230" marker-end="url(#l14b-ar)"/>
      <path d="M564 260 L196 260" marker-end="url(#l14b-ar)"/>
      <path d="M196 290 L564 290" marker-end="url(#l14b-ar)"/>
      <path d="M564 320 L196 320" marker-end="url(#l14b-ar)"/>
    </g>
    <!-- message labels -->
    <g text-anchor="middle" font-size="9.5">
      <text x="380" y="134" fill="#0fa07f">SYN / SYN-ACK / ACK (handshake, once)</text>
      <text x="380" y="164" fill="currentColor">request 1</text>
      <text x="380" y="194" fill="currentColor">response 1</text>
      <text x="380" y="224" fill="currentColor">request 2</text>
      <text x="380" y="254" fill="currentColor">response 2</text>
      <text x="380" y="284" fill="currentColor">request 3</text>
      <text x="380" y="314" fill="currentColor">response 3</text>
    </g>
    <!-- closing note band (green = connection still healthy) -->
    <rect x="95" y="338" width="570" height="24" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-opacity="0.6" stroke-width="1"/>
    <text x="380" y="354" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.9">still open — returned to the pool for the next caller</text>
    <!-- footer -->
    <text x="380" y="386" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.7">One handshake amortized over three requests — then handed back to the pool.</text>
  </g>
</svg>
```

### Connection pooling: a bounded set of reusable connections

Keep-alive reuses *one* connection. But a real server handles many requests at
once, and a single connection can only carry one request at a time (in
HTTP/1.1). So you keep several open connections and share them — that's a
**connection pool**.

A pool exposes two operations:

- **acquire()** — give me a ready connection. Reuse an idle one if there is one;
  otherwise open a new one, but only up to a fixed **max size**. If the pool is
  at its limit and all connections are checked out, wait until one is returned.
- **release()** — I'm done; put this connection back for the next caller.

The **max size** is the crucial part. It caps how many connections you hold, so a
traffic spike can't open ten thousand sockets and exhaust your ports or the
peer's accept queue — it just makes callers wait their turn. This is identical to
a thread pool or a database connection pool: a bounded resource, handed out and
returned. Because many threads acquire and release at once, the pool's internals
must be **thread-safe** — guarded so two threads can't grab the same connection.

### Timeouts: connect, read, write, idle

A socket operation blocks by default: `connect()` waits for the handshake,
`recv()` waits for bytes, `send()` waits for buffer space. If the peer crashes,
gets firewalled, or just goes silent, those waits never end — and a hung request
holds its connection (and its thread) hostage. **A timeout turns an unbounded
wait into a bounded, recoverable failure.** There are four kinds, each guarding a
different wait:

| Timeout | Bounds | Fires when | Without it |
|---|---|---|---|
| **Connect** | establishing the connection | the handshake can't complete — host down, or a firewall silently dropping the `SYN` | `connect()` blocks for the OS default (often 1–2 minutes) or indefinitely |
| **Read** | waiting to receive bytes | the peer accepted the connection but sends nothing — overloaded, wedged, or gone silent mid-response | `recv()` blocks forever on a stalled peer |
| **Write** | waiting to send bytes | the send buffer stays full because the peer isn't reading (slow consumer / slow link) | `send()` blocks once buffers fill |
| **Idle** | how long a pooled connection may sit unused | a pooled connection has been idle past the limit | dead or half-closed connections accumulate and get handed to unlucky callers |

Connect, read, and write timeouts are set on the socket with
`settimeout()`, which raises `socket.timeout` when the bound is exceeded. The idle
timeout is a *pool* responsibility: the pool reaps connections that have sat
unused too long, because a connection the peer silently closed looks fine until
you try to use it. **Every wait in a networked program needs a timeout** — a
missing one is how a single bad peer takes down a whole service.

### TIME_WAIT and port exhaustion

When you close a TCP connection, the side that closes first enters a state called
**TIME_WAIT** and stays there for typically 2×MSL (maximum segment lifetime,
usually about 60 seconds total, per RFC 9293 §3.5). This is deliberate: it lets
any late-arriving packets from the old connection drain out before that
four-tuple (source **IP** — Internet Protocol — address, source port,
destination IP address, destination port) can be
reused, so stale bytes can't be mistaken for a new connection's data.

The catch: each outgoing connection consumes one **ephemeral port** (the
`49152`–`65535` range from Lesson 05), and a port stuck in TIME_WAIT can't be
reused yet. Open connections fast enough and you pile up tens of thousands of
TIME_WAIT entries and run out of source ports — the OS then refuses new
connections with `cannot assign requested address`. Pooling fixes this at the
root: reusing a handful of long-lived connections instead of churning through
thousands of short-lived ones means almost nothing ever enters TIME_WAIT.

## Build It

The full implementations are in [`code/`](../code/). Both are self-contained:
they start a local server on a background thread, run clients against it, print
what happened, and exit.

### A thread-safe connection pool

[`code/connection_pool.py`](../code/connection_pool.py) runs the same N requests
two ways against a local keep-alive echo server, and times both. The pool is a
bounded, thread-safe set of reusable sockets:

```python
class ConnectionPool:
    def acquire(self, timeout=5.0):
        try:
            return self._idle.get_nowait()      # reuse an idle connection
        except queue.Empty:
            pass
        with self._lock:                        # decide under a lock: open a new
            may_open = self.opened < self._max_size   # one only if under max size
            if may_open:
                self.opened += 1
        if may_open:
            return open_connection(self._host, self._port)
        return self._idle.get(timeout=timeout)  # at capacity: wait for a release

    def release(self, conn):
        self._idle.put(conn)                    # return it for the next caller
```

Idle connections live in a thread-safe `queue.LifoQueue`; a `threading.Lock`
guards the open-count so the pool never exceeds `max_size`. The "without a pool"
path opens a fresh socket for every request, paying the modeled handshake cost
each time:

```python
def without_pool(host, port):
    for i in range(N_REQUESTS):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((host, port))          # a new handshake every request
            time.sleep(CONNECT_COST_S)          # the round-trip localhost hides
            one_request(sock, f"request {i}".encode())
```

Run it:

```bash
python3 connection_pool.py
```

Sequential requests only ever need one connection, so the pool opens **1** and
reuses it for all N — a large speedup over N handshakes. The final phase throws
eight threads at the pool at once to prove thread-safety: they share the bounded
set, and the pool never opens more than `max_size` connections:

```text
[no pool] 24 requests, 24 new connections (handshakes) ->  146.1 ms
[pool]    24 requests, 1 new connection(s) reused ->    7.9 ms
[result]  pooling reused connections and ran 18.6x faster, opening 1 connection(s) instead of 24
[safety] 8 threads x 24 requests shared the pool with no errors
[safety] connections ever opened: 4 (capped at max_size=4)
```

### Timeouts that fail fast instead of hanging

[`code/timeouts.py`](../code/timeouts.py) starts a server that accepts a
connection and then deliberately goes silent for 0.6 seconds — a stand-in for a
wedged peer. The client sets a read timeout with `settimeout()`:

```python
def read_with_timeout(host, port, timeout_s):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout_s)              # bounds connect(), recv(), send()
        sock.connect((host, port))
        sock.sendall(b"are you there?")
        try:
            reply = sock.recv(1024)
            print(f"got a reply: {reply!r}")
        except socket.timeout:                  # the wait was bounded, not infinite
            print("socket.timeout raised — the peer went silent; we gave up")
```

Run it:

```bash
python3 timeouts.py
```

A 0.2 s read timeout is shorter than the server's 0.6 s stall, so `recv()` raises
`socket.timeout` and the client gives up cleanly. A 1.5 s timeout is generous
enough that the same reply gets through. The demo also connects to a closed port
to show that a *refused* connection is instant and explicit — a different failure
from a *timeout*, which is silence you waited on and gave up:

```text
[read timeout=0.20s] socket.timeout raised — the peer went silent; we gave up instead of hanging
[read timeout=1.50s] got a reply: b'finally, a reply'
[connect] ConnectionRefusedError after 0.1 ms — refused is instant and explicit, not a timeout
```

## Use It

You almost never build a pool by hand in production — your HTTP client and
database driver already have one, tuned by the same acquire/release/max-size/
timeout knobs you just built. The job shifts from *implementing* pooling to
*configuring* it. In Python, `httpx` (the one dependency here; everything above is
stdlib) exposes exactly these controls:

```python
import httpx

# Reuse connections across requests (keep-alive), bound the pool, and set every
# timeout — connect, read, write — so no single call can hang the client.
limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
timeout = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)

with httpx.Client(limits=limits, timeout=timeout) as client:
    for _ in range(10):
        r = client.get("https://example.com/health")   # same connection reused
        print(r.status_code)
```

Every field maps to something you built: `max_connections` is the pool's max
size, `max_keepalive_connections` is how many idle connections to keep warm,
`pool` is how long `acquire()` will wait for a free connection, and
`connect`/`read`/`write` are the socket timeouts. Database drivers expose the
same shape — `SQLAlchemy`'s engine takes `pool_size`, `max_overflow`,
`pool_timeout`, and `pool_recycle` (an idle/lifetime cap so stale connections get
replaced). Different library, identical concepts, because underneath it's the
same sockets you just pooled by hand.

The one rule that survives every library: **set your timeouts explicitly.** Most
clients default to *no* timeout, which means the first silent peer hangs the call
forever. A default pool with no timeouts is a latent outage.

## Ship It

The artifact for this lesson is a connection-tuning checklist-prompt:
[`outputs/prompt-connection-tuning.md`](../outputs/prompt-connection-tuning.md) —
it walks from a symptom (slow first byte, `cannot assign requested address`,
requests hanging, connection resets) to the pool or timeout setting responsible,
and gives the questions to ask before changing a single number. You understand
what each knob does because you just built the thing it tunes.

## Key takeaways

- **Opening a connection costs a round-trip** (TCP handshake) — plus one or two
  more for TLS on HTTPS — before any useful byte moves. Doing it per request
  wastes that cost repeatedly.
- **Keep-alive** reuses one connection for many requests, amortizing a single
  handshake; it's the HTTP/1.1 default (RFC 9112 §9).
- **A connection pool** keeps a bounded, shared set of reusable connections:
  `acquire()` reuses or opens (up to **max size**), `release()` returns. It must
  be **thread-safe**, and its size cap protects you from resource exhaustion.
- **Timeouts are mandatory on every wait** — connect, read, write, and idle —
  each turning an unbounded hang into a bounded, recoverable failure. Most
  libraries default to none; always set them.
- **TIME_WAIT** makes closed connections linger, and churning short-lived
  connections exhausts ephemeral ports (`cannot assign requested address`).
  Pooling avoids the churn and fixes it at the root.
