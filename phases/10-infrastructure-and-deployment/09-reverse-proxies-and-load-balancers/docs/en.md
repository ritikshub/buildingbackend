# Reverse Proxies, Load Balancers & Ingress

> You put a machine in the middle of every request, and two things broke that nobody warned you about. Your admin IP allowlist started returning `403` to your own office, because every request now arrives from the proxy's address — three distinct clients collapsed to **one** at the backend. And your deploy started dropping requests: killing a backend that had three requests inside it cost **15 failed requests**, while draining it properly — stop new traffic, wait ~400 ms, then stop — cost **zero**. Same removal, same traffic, one added `while inflight > 0`. This lesson is the machine in the middle: what it can see, what it terminates, what it rewrites, and how it removes a backend without dropping a request.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Service Discovery & Health-Aware Routing](../08-service-discovery-and-routing/), [Build an HTTP Server from TCP](../../01-networking-and-protocols/09-http-server-from-tcp/), [TLS, Certificates & mTLS](../../01-networking-and-protocols/10-tls-certificates-mtls/)
**Time:** ~80 minutes

## The Problem

You have one public IP address, one TLS certificate, and six backend services whose addresses change every deploy. Something has to sit at the front door. You install a reverse proxy, point DNS at it, and it works immediately — which is the dangerous part, because the two failures below are not configuration mistakes. They are direct consequences of the fact that there is now a machine in the middle.

**Tuesday, 11:04 — the deploy.** You are replacing four instances of the orders service, one at a time. The script does what deploy scripts do: it stops the container, waits for the new one to report healthy, moves on. Each stop takes a few hundred milliseconds and the graphs barely move. Your error rate for the deploy window is 0.3%, which rounds to nothing on a dashboard averaged over five minutes.

Underneath that 0.3% are two distinct populations of dead request, and they die for different reasons.

The first population was **already inside** the instance when you killed it. A request that had spent 300 ms of its 400 ms of work is not "pending" — it is a half-written response on a socket that just got a `RST`. The client sees a connection reset, not a `500`, so your own error metrics never counted it. One of them had already charged a card and had not yet written the order row.

The second population is worse, because it is entirely avoidable and it is much larger. The proxy did not know you had stopped that instance. Health checks run on an interval — call it every 3 seconds — and until the next one fails, the proxy keeps its share of round-robin turns pointed at an address where nothing is listening. Every one of those gets `ECONNREFUSED` and becomes a `502`. **The instance was dead for a few hundred milliseconds and the proxy sent it traffic the entire time.**

**Tuesday, 14:30 — the 403.** Your internal admin tool has an IP allowlist. It has worked for two years. It stops working the hour the proxy goes in, and the error is not a timeout or a certificate warning. It is a clean, fast, correct-looking `403 Forbidden`.

The reason is the same machine. Your application reads the client's address from its own socket — the peer address, `request.remote_addr`, the thing every framework calls "the client IP". That value used to be the user's address. It is now the **proxy's** address, on every single request, because the proxy is the one that opened the connection. Your allowlist compares the user's office IP to the proxy's internal IP and denies. Your rate limiter now sees all traffic as one client. Your audit log has recorded one address for every action taken by every user since 11:00.

The fix looks obvious — the proxy sends the real address in a header, so read the header — and the obvious fix is where the security bug lives. That header arrives on a request that a client sent you, and a client can send you anything.

Both failures come from the same move: you inserted a participant into a conversation that used to have two ends. Everything in this lesson follows from that.

## The Concept

### Forward proxy and reverse proxy: same machinery, opposite direction

A **proxy** is a program that accepts a connection and makes another connection on your behalf. The two kinds differ by exactly one thing — **who it acts for** — and everything else about their trust position follows from that.

A **forward proxy** sits in front of *clients* and acts for them. The clients know it is there; they are configured to use it. The server does not know it is there, and sees only the proxy's address. Corporate egress filters, a caching proxy on a campus network, and `HTTPS_PROXY=…` in your shell are all forward proxies.

A **reverse proxy** sits in front of *servers* and acts for them. The client does not know it is there — it thinks it is talking to `shop.example`, and by any observable measure it is. The servers know it is there and are usually reachable *only* through it. This is the load balancer, the CDN edge, the Kubernetes ingress controller, the API gateway.

Machinery: identical. Both terminate a connection and open another. The difference is which side you own, and therefore which side you can trust. **A forward proxy's operator does not control the clients' payloads; a reverse proxy's operator does not control the clients at all but does control every hop after itself.** That asymmetry is the entire basis of the `X-Forwarded-For` rule later in this lesson, and the reason the same header is authoritative in one deployment and attacker-controlled in another.

Note that "load balancer" is not a fourth category. A load balancer is a reverse proxy whose job emphasis is distributing traffic across a pool rather than routing it to distinct services. Most real deployments do both in the same process.

### Layer 4 and layer 7: what it can see decides what it can do

Phase 1's [OSI and TCP/IP models](../../01-networking-and-protocols/01-osi-and-tcp-ip-models/) lesson gave you the layer numbering. Two of those numbers name the two kinds of proxy you will ever deploy.

**Layer 4 is the transport layer** — TCP (Transmission Control Protocol) and UDP (User Datagram Protocol). An **L4 proxy** accepts a TCP connection, opens another TCP connection to a backend, and copies bytes between them. It never parses those bytes. It cannot, because to a byte-copier `GET /api/orders` and the middle of a JPEG are the same thing.

**Layer 7 is the application layer** — HTTP, gRPC, Postgres' wire protocol. An **L7 proxy** reads and understands the messages. It parses the request line, the `Host` header and every other header, decides what to do, and constructs a *new* request to send upstream.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 474" width="100%" style="max-width:840px" role="img" aria-label="A layer 4 proxy and a layer 7 proxy side by side. The layer 4 proxy relays opaque TCP bytes, can see only addresses and ports, routes on the listening port alone, passes TLS straight through to the backend, and cannot add a forwarded header. The layer 7 proxy terminates the connection and parses HTTP, can see method, path, Host and every header, routes on any of them, must terminate TLS to read anything, and pays for it with buffering and a second connection. Measured: the same eight requests reached four distinct backends through the layer 7 proxy and one backend through the layer 4 proxy, which relayed 1714 bytes and added zero headers.">
  <defs>
    <marker id="l09-a1" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Same box in the middle. What it can SEE decides what it can DO.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="16" y="44" width="414" height="366" rx="13" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.45"/>
      <rect x="450" y="44" width="414" height="366" rx="13" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff"/>
    </g>

    <rect x="112" y="115" width="202" height="14" rx="7" fill="#7f7f7f" fill-opacity="0.34" stroke="#7f7f7f" stroke-width="1.1"/>
    <g fill="none" stroke-width="1.9" stroke-linejoin="round">
      <rect x="32" y="100" width="86" height="44" rx="8" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
      <rect x="152" y="100" width="122" height="44" rx="8" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="308" y="100" width="86" height="44" rx="8" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
      <rect x="466" y="100" width="86" height="44" rx="8" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
      <rect x="586" y="100" width="122" height="44" rx="8" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
      <rect x="742" y="100" width="86" height="44" rx="8" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.7">
      <path d="M552 122 L 580 122" marker-end="url(#l09-a1)"/>
      <path d="M708 122 L 736 122" marker-end="url(#l09-a1)"/>
    </g>

    <g fill="currentColor" text-anchor="middle">
      <text x="75" y="120" font-size="10.5" font-weight="700" fill="#3553ff">client</text>
      <text x="75" y="134" font-size="8.5" opacity="0.8">one IP</text>
      <text x="213" y="120" font-size="10.5" font-weight="700" fill="#7c5cff">L4 proxy</text>
      <text x="213" y="134" font-size="8.5" opacity="0.8">relays bytes</text>
      <text x="351" y="120" font-size="10.5" font-weight="700" fill="#0fa07f">backend</text>
      <text x="351" y="134" font-size="8.5" opacity="0.8">TLS ends here</text>
      <text x="509" y="120" font-size="10.5" font-weight="700" fill="#3553ff">client</text>
      <text x="509" y="134" font-size="8.5" opacity="0.8">one IP</text>
      <text x="647" y="120" font-size="10.5" font-weight="700" fill="#7c5cff">L7 proxy</text>
      <text x="647" y="134" font-size="8.5" opacity="0.8">parses HTTP</text>
      <text x="785" y="120" font-size="10.5" font-weight="700" fill="#0fa07f">backend</text>
      <text x="785" y="134" font-size="8.5" opacity="0.8">TLS ended</text>
      <text x="213" y="160" font-size="8.5" opacity="0.85">one connection of opaque bytes, straight through</text>
      <text x="647" y="160" font-size="8.5" opacity="0.85">TWO connections, own keep-alive pool</text>
    </g>

    <g text-anchor="middle">
      <text x="223" y="70" font-size="13.5" font-weight="700" fill="currentColor">L4 — TRANSPORT (TCP)</text>
      <text x="223" y="87" font-size="9.5" fill="currentColor" opacity="0.85">a very fast, very stupid wire</text>
      <text x="657" y="70" font-size="13.5" font-weight="700" fill="#7c5cff">L7 — APPLICATION (HTTP)</text>
      <text x="657" y="87" font-size="9.5" fill="currentColor" opacity="0.85">a full participant in the conversation</text>
    </g>

    <g fill="currentColor" font-size="9" font-weight="700" opacity="0.6">
      <text x="34" y="192">WHAT IT CAN SEE</text><text x="468" y="192">WHAT IT CAN SEE</text>
      <text x="34" y="264">SO IT CAN ROUTE ON</text><text x="468" y="264">SO IT CAN ROUTE ON</text>
      <text x="34" y="322">TLS</text><text x="468" y="322">TLS</text>
      <text x="34" y="366">THE BILL</text><text x="468" y="366">THE BILL</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.28">
      <path d="M34 198 L 412 198"/><path d="M468 198 L 846 198"/>
      <path d="M34 270 L 412 270"/><path d="M468 270 L 846 270"/>
      <path d="M34 328 L 412 328"/><path d="M468 328 L 846 328"/>
      <path d="M34 372 L 412 372"/><path d="M468 372 L 846 372"/>
    </g>

    <g fill="currentColor" font-size="9.5">
      <text x="34" y="216">source IP, destination IP, ports</text>
      <text x="34" y="231">TCP flags, byte counts, timing</text>
      <text x="34" y="246" fill="#d64545" font-weight="700">and nothing else at all</text>
      <text x="468" y="216">method, path, query, Host, cookies</text>
      <text x="468" y="231">every header, the body, the status code</text>
      <text x="468" y="246" fill="#0fa07f" font-weight="700">it can also ADD and REWRITE them</text>

      <text x="34" y="288">the port you connected to</text>
      <text x="34" y="303" fill="#d64545">no path routing &#8226; no Host routing &#8226; no XFF</text>
      <text x="468" y="288">prefix /api/ &#8226; Host: img.internal &#8226; a header</text>
      <text x="468" y="303" fill="#0fa07f">retry, rewrite, buffer, drain per REQUEST</text>

      <text x="34" y="346">passthrough: the cert lives on the backend</text>
      <text x="468" y="346">must TERMINATE it to read one byte</text>

      <text x="34" y="390">cheap: no parse, no buffer, no cert</text>
      <text x="468" y="390">CPU to parse, memory to buffer, a cert to rotate</text>
    </g>

    <text x="440" y="434" font-size="10.5" text-anchor="middle" fill="currentColor">measured: 8 requests through the L7 proxy reached <tspan font-weight="700" fill="#0fa07f">4 distinct backends</tspan>; the same requests through the L4 proxy reached <tspan font-weight="700" fill="#d64545">1</tspan></text>
    <text x="440" y="460" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">The L4 proxy relayed 1714 bytes and added 0 headers. It never learned there was such a thing as a path.</text>
  </g>
</svg>
```

The Build It measures the gap. Eight requests through the L7 proxy reached **four distinct backends**, chosen by `Host` header and path prefix. The same requests through an L4 proxy reached **one backend**, because the only routing input an L4 proxy has is *which port you connected to*. It relayed **1,714 bytes and added zero headers**.

L7 is more capable, and the honest way to teach it is to state the bill:

- **It must terminate TLS to read anything.** Encrypted bytes are opaque bytes. An L7 proxy that cannot decrypt is an L4 proxy with extra configuration.
- **It buffers.** To make a routing decision it must read the request line and headers; to retry a failed request it must have kept the body. Buffering costs memory per in-flight request and adds latency to the first byte.
- **It is a participant, not a wire.** It has its own connection state, its own timeouts, its own idea of when a request is finished, and its own bugs. Every semantic difference between it and your backend is a potential request smuggling vulnerability.

L4 remains the right answer more often than fashion suggests: non-HTTP protocols, extreme throughput where per-request CPU matters, and — importantly — **anywhere the backend must see the original TLS session**, such as mutual TLS where the backend authenticates the client certificate itself.

### TLS termination, passthrough and re-encryption

TLS (Transport Layer Security, RFC 8446 for version 1.3) is where "who holds the certificate" becomes an architecture decision. Three arrangements, and the difference is where the encrypted tunnel ends:

- **Termination.** The proxy holds the certificate and private key. It decrypts, reads, routes, and talks to the backend over **plain HTTP**. The backend sees cleartext and has no idea TLS was ever involved — which is why it needs `X-Forwarded-Proto` to know whether to issue a redirect or set a `Secure` cookie. One cert to rotate, full L7 capability, and one network segment you must trust.
- **Passthrough.** The proxy never decrypts. It is an L4 proxy by definition, forwarding the TLS stream to a backend that holds the certificate. Routing is limited to what is visible in the clear during the handshake: essentially the **SNI** (Server Name Indication, RFC 6066 §3) field, in which the client announces the hostname it wants before encryption starts. The backend gets the real TLS session and can authenticate a client certificate. You get no path routing, no header rewriting, and a certificate on every backend.
- **Re-encryption (TLS bridging).** The proxy terminates one TLS session and opens a *new* one to the backend. Full L7 capability and no cleartext on the wire, at the cost of two handshakes and two certificate lifecycles. This is the default in service meshes, where the mesh's own certificate authority issues short-lived backend certs automatically.

The decision rule is short. **Terminate at the edge** unless something forces otherwise. **Passthrough** when the backend must see the client certificate or you are not permitted to hold the key. **Re-encrypt** when the network between proxy and backend is not trusted — which, in a shared cloud VPC, is a defensible position.

### What a proxy actually does to a request

The client's connection and the upstream connection are **two separate TCP connections with independent lifetimes**. This is not an implementation detail; it is the source of half of this lesson's behaviour.

The proxy maintains its own **keep-alive pool** to each backend ([Keep-Alive, Pooling & Timeouts](../../01-networking-and-protocols/14-keep-alive-pooling-timeouts/)). In the Build It, **8 client requests produced 4 upstream connections opened and 4 reused** — one per backend, then reuse. A thousand client connections can be served over a handful of upstream ones, which is exactly why putting a proxy in front of a connection-hungry backend reduces its load even when it changes nothing else.

Because it is constructing a new request, the proxy must decide what to carry over. RFC 9110 §7.6.1 draws the line: **hop-by-hop** header fields are meaningful only for a single connection and MUST NOT be forwarded — `Connection`, `Keep-Alive`, `TE`, `Trailer`, `Transfer-Encoding`, `Upgrade`, `Proxy-Authenticate`, `Proxy-Authorization`. Everything else is end-to-end and passes through. A proxy that forwards `Connection: close` upstream tears down its own pooled connection on every request.

And it adds the forwarding headers, which is where the interesting failure lives:

| header | carries | note |
|---|---|---|
| `X-Forwarded-For` | the chain of client addresses | de facto, not standardised; **append**, comma-separated |
| `X-Forwarded-Proto` | `http` or `https` | the only way a TLS-terminated backend knows the client used TLS |
| `X-Forwarded-Host` | the original `Host` | needed when the proxy rewrites `Host` upstream |
| `Forwarded` | all of the above, structured | **RFC 7239**, the standardised replacement |

`Forwarded` exists because the `X-` headers grew by convention and have no specification to point at when two implementations disagree. It carries the same information with defined syntax: `Forwarded: for=192.0.2.60;proto=https;host="shop.example"`, multiple hops comma-separated. Emit both — `Forwarded` because it is the standard, `X-Forwarded-*` because that is what your framework, your WAF and your logging pipeline actually read.

### `X-Forwarded-For` is client input until a trusted hop overwrites it

This is the security section, and it is short enough to memorise.

`X-Forwarded-For` is **appended** at each hop. Each proxy adds *the address it saw as its peer* to the end of the list. After two hops the backend sees `X-Forwarded-For: 127.0.0.9, 127.0.0.2` — the client, then the edge — and its own socket peer is the ingress at `127.0.0.3`. Three addresses, three different meanings, and the full path is only reconstructable if you know how many hops you run.

Now the trap. **The list arrives on a request the client sent.** Nothing stops a client from including its own `X-Forwarded-For` header, and a well-behaved appending proxy will keep it and append to it. So the left-most entry is not "the client" — it is **the first thing anybody wrote**, which for an attacker is a free-text field.

Which makes this line, present in an enormous amount of production code, a vulnerability:

```python
client_ip = request.headers["X-Forwarded-For"].split(",")[0].strip()   # SPOOFABLE
```

The Build It runs exactly this. A client sends `X-Forwarded-For: 10.0.0.1`; the backend receives `10.0.0.1, 127.0.0.9, 127.0.0.2`; the naive parser reports the client IP as **`10.0.0.1`** and the admin allowlist **lets it in**. The trusted-hop parser reports **`127.0.0.9`** and returns `403`. Same request, same headers, two lines of parsing code.

The correct rule: **count backwards from the right by the number of proxies you actually operate.** The right-most entry was written by your last hop, which you control, so it is trustworthy. Walking left, each entry is trustworthy only if the hop that wrote it is yours. The first entry written by something you do not control is the last one you may believe.

```python
def trusted_client_ip(xff, remote_addr, trusted_hops):
    """Entry -n is the address the n-th trusted hop observed as its peer."""
    if not xff:
        return remote_addr
    chain = [p.strip() for p in xff.split(",") if p.strip()]
    if len(chain) < trusted_hops:
        return remote_addr        # fewer hops than expected: do not guess
    return chain[-trusted_hops]
```

`trusted_hops` is not a preference. It is a fact about your topology, and **it must change when your topology changes**. Add a CDN in front of your load balancer and every value derived from that header silently shifts by one position: your rate limiter starts limiting your own edge, and your audit log starts recording it.

The stronger version, when you can do it: have the outermost proxy you control **overwrite** the header rather than append, discarding whatever the client sent. Then the chain contains only addresses your own infrastructure wrote. The Build It measures this too — with the edge overwriting, even the naive left-most parser returns the correct address, because there is no longer a lie for it to read. You lose the genuine chain from any upstream CDN, which is the trade-off.

Three defaults worth checking today, because each has produced a real incident:

- Anything derived from a client IP — rate limits, allowlists, geo rules, fraud signals, audit logs — must use the trusted-hop value, not `remote_addr` and not the left-most entry.
- Your framework's `trust proxy` / `ProxyFix` / `ForwardedHeaders` setting takes a **hop count**. Set it to your real number. Setting it to "trust everything" is identical to using the naive parser.
- If the header is absent, fall back to the socket peer address, and never to a default that means "allowed".

### Timeouts at every hop, and the rule for choosing them

Every hop in the chain has its own timeout, and the failure mode you must engineer against is not "a timeout fired" — it is **two timeouts that disagree**.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 500" width="100%" style="max-width:840px" role="img" aria-label="A request travelling from client through an edge proxy and an ingress proxy to the backend. Each hop appends its own peer address to X-Forwarded-For and sets X-Forwarded-Proto and X-Forwarded-Host, so the backend sees the chain 127.0.0.9 comma 127.0.0.2 while its own socket peer is only 127.0.0.3. Above the path, nested timeout budgets show the correct arrangement, each inner timeout shorter than the one outside it. Below, the mismatch case in red: a 250 millisecond proxy timeout against a 2000 millisecond backend produced 20 gateway timeouts while the backend completed all 20 requests anyway, 40 seconds of work written to closed sockets.">
  <defs>
    <marker id="l09-a2" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Every hop adds a header and starts a clock. Both must nest.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <text x="30" y="56" font-size="9" font-weight="700" fill="currentColor" opacity="0.6">TIMEOUT BUDGETS — each one strictly INSIDE the one outside it</text>
    <g stroke-width="1.6" stroke-linejoin="round">
      <rect x="30" y="64" width="810" height="17" rx="6" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="196" y="85" width="644" height="17" rx="6" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="404" y="106" width="436" height="17" rx="6" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
      <rect x="572" y="127" width="268" height="17" rx="6" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="704" y="148" width="136" height="17" rx="6" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/>
    </g>
    <g fill="currentColor" font-size="9">
      <text x="38" y="77">client deadline 10 s</text>
      <text x="204" y="98">edge proxy_read_timeout 5 s</text>
      <text x="412" y="119">ingress proxy_read_timeout 3 s</text>
      <text x="580" y="140">app request timeout 2 s</text>
      <text x="712" y="161">DB query 1 s</text>
    </g>

    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="30" y="176" width="150" height="52" rx="9" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
      <rect x="238" y="176" width="150" height="52" rx="9" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="446" y="176" width="150" height="52" rx="9" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
      <rect x="654" y="176" width="186" height="52" rx="9" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.8">
      <path d="M180 202 L 232 202" marker-end="url(#l09-a2)"/>
      <path d="M388 202 L 440 202" marker-end="url(#l09-a2)"/>
      <path d="M596 202 L 648 202" marker-end="url(#l09-a2)"/>
    </g>
    <g fill="currentColor" text-anchor="middle">
      <text x="105" y="199" font-size="11.5" font-weight="700" fill="#3553ff">client</text>
      <text x="105" y="216" font-size="9" opacity="0.85">peer 127.0.0.9</text>
      <text x="313" y="199" font-size="11.5" font-weight="700" fill="#7c5cff">edge proxy</text>
      <text x="313" y="216" font-size="9" opacity="0.85">TLS ends &#8226; peer 127.0.0.2</text>
      <text x="521" y="199" font-size="11.5" font-weight="700" fill="#7c5cff">ingress proxy</text>
      <text x="521" y="216" font-size="9" opacity="0.85">peer 127.0.0.3</text>
      <text x="747" y="199" font-size="11.5" font-weight="700" fill="#0fa07f">backend app</text>
      <text x="747" y="216" font-size="9" opacity="0.85">socket peer = 127.0.0.3</text>
    </g>

    <g fill="currentColor" font-size="8.5">
      <text x="238" y="248" font-weight="700" fill="#7c5cff">edge APPENDS its peer</text>
      <text x="238" y="262">X-Forwarded-For: 127.0.0.9</text>
      <text x="238" y="274">X-Forwarded-Proto: https</text>
      <text x="238" y="286">X-Forwarded-Host: shop.example</text>
      <text x="238" y="298">Forwarded: for=127.0.0.9;proto=https</text>
      <text x="446" y="248" font-weight="700" fill="#7c5cff">ingress APPENDS its peer</text>
      <text x="446" y="262">X-Forwarded-For: 127.0.0.9, 127.0.0.2</text>
      <text x="446" y="274">X-Forwarded-Proto: https  (unchanged)</text>
      <text x="446" y="286">Host: shop.example survives both hops</text>
      <text x="446" y="298">Connection: hop-by-hop, NOT forwarded</text>
    </g>

    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="654" y="238" width="186" height="66" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
    </g>
    <g fill="currentColor" font-size="8.5">
      <text x="666" y="254" font-weight="700" fill="#0fa07f">what the app must parse</text>
      <text x="666" y="269">trusted hops = 2, count from the</text>
      <text x="666" y="281">RIGHT &#8594; client is 127.0.0.9</text>
      <text x="666" y="296" fill="#d64545">split(&quot;,&quot;)[0] trusts the client</text>
    </g>

    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="30" y="326" width="400" height="122" rx="11" fill="#0fa07f" fill-opacity="0.09" stroke="#0fa07f"/>
      <rect x="450" y="326" width="390" height="122" rx="11" fill="#d64545" fill-opacity="0.09" stroke="#d64545"/>
    </g>
    <g fill="currentColor">
      <text x="230" y="350" font-size="12" font-weight="700" text-anchor="middle" fill="#0fa07f">NESTED: inner &lt; outer</text>
      <text x="46" y="372" font-size="9.5">10 s &gt; 5 s &gt; 3 s &gt; 2 s &gt; 1 s</text>
      <text x="46" y="390" font-size="9.5">Whoever gives up first is the one who</text>
      <text x="46" y="404" font-size="9.5">can still say something useful about it.</text>
      <text x="46" y="424" font-size="9.5" font-weight="700">measured with a 250 ms upstream timeout:</text>
      <text x="46" y="438" font-size="9.5">40 of 60 served, 0 refused, p99 253 ms</text>

      <text x="645" y="350" font-size="12" font-weight="700" text-anchor="middle" fill="#d64545">MISMATCHED: proxy gives up first</text>
      <text x="466" y="372" font-size="9.5">proxy 250 ms &#8226; backend still working 2000 ms</text>
      <text x="466" y="390" font-size="9.5">The proxy closes the socket and returns 504.</text>
      <text x="466" y="404" font-size="9.5">The backend never hears about it.</text>
      <text x="466" y="424" font-size="9.5" font-weight="700" fill="#d64545">20 x 504 to users &#8212; and the backend</text>
      <text x="466" y="438" font-size="9.5" font-weight="700" fill="#d64545">completed all 20: 40.0 s of work, 0 delivered</text>
    </g>

    <text x="440" y="476" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">A timeout never cancels work. It only stops YOU waiting &#8212; you still pay for it, twice.</text>
  </g>
</svg>
```

**The nesting rule: each inner timeout must be strictly shorter than the one outside it.** If the app allows 2 s and the proxy allows 3 s, the app fails first and can return a real error with a request ID and a trace. If the proxy allows 2 s and the app allows 3 s, the proxy fails first, the user gets a bare `504 Gateway Timeout`, and the app never learns anything happened.

Which is the worst outcome, and it is worth being precise about why. A timeout **does not cancel work.** It closes a socket. The backend is not listening for socket closure — it is executing a query — so it finishes the whole request and writes the response to a connection nobody is reading. The Build It measures the bill: with a 250 ms upstream timeout against a 2,000 ms backend, **20 requests timed out at the proxy, the backend completed all 20 anyway, and delivered 0 — 40.0 seconds of backend work written to sockets the proxy had already closed.** You pay twice: once in backend capacity, once in the `504` the user actually sees.

The other half of the same measurement is why you need the timeout regardless. With **no** upstream timeout, six slow requests occupied all six of the proxy's worker slots for two seconds each, and **42 of 60 requests (70%) were refused at the proxy's own door with a 503**. The proxy failed because a backend was slow. Adding the 250 ms timeout took served requests from 18 to 40 (**2.2×**) and refusals from 42 to 0, and dropped p99 from **2,003 ms to 253 ms** — pinned to the timeout you chose rather than to the slowest backend you have. That is [Backpressure & Load Shedding](../../08-concurrency-and-performance/11-backpressure-and-load-shedding/) seen from the proxy's side: a bounded wait is the only thing that keeps one slow dependency from consuming a shared resource.

Name every timeout you have, because they are not one number. Connect timeout (opening the upstream TCP connection — should be small, tens of milliseconds on a LAN). Send/write timeout. **Read timeout** (waiting for the upstream response — the big one, `proxy_read_timeout` in nginx). Idle timeout on pooled connections. And the client-side keep-alive idle timeout, which must be *shorter* on the proxy than on the backend, or the backend will close a pooled connection at the moment the proxy is writing a request into it.

### Health checking and connection draining

Lesson 8 built the registry and measured how long it takes for the truth about a dead instance to reach the things routing to it. This lesson is what the proxy does with that knowledge, and specifically what "removing a backend" must mean.

**Active health checking**: the proxy polls each backend on an interval — `GET /readyz` every 3 s, two failures to eject. **Passive health checking** (outlier detection): the proxy watches real traffic and ejects a backend after N consecutive `5xx` or connection errors. Active gives you a clean signal at a known cost; passive detects instantly but only after real users have absorbed the failures. Production systems run both.

Two rules, both from [Health Checks & Probes](../../09-logging-monitoring-and-observability/08-health-checks-and-probes/): **check a real HTTP endpoint, not a TCP connect** — a deadlocked process still completes the TCP handshake forever — and **check readiness, not liveness**, because the proxy's question is "should I route here?", not "is this process broken?".

Now the part that produces zero-downtime deploys. Removing a backend is **three steps, and the middle one is the one everybody skips**:

1. Mark it not-routable so it receives **no new requests**.
2. **Wait** for the requests already inside it to finish.
3. Stop the process.

Skipping step 1 means the pool keeps sending traffic to a dead address. Skipping step 2 means you sever whatever was in flight. The Build It runs all three variants against an identical 45-request schedule with a backend holding 3 requests at the moment of removal:

- **(a) kill it** — 3 requests severed mid-flight, **12 more refused** by the pool that never learned, **15 failed**.
- **(b) remove from the pool, then kill** — the 12 refusals are gone, but **the 3 already inside still die. 3 failed.**
- **(c) drain** — remove, wait ~400 ms for in-flight work to finish, then stop. **0 failed. Not "few". Zero.**

The measured cost of correctness is about 400 milliseconds of waiting, once, per instance. The measured cost of skipping it is 15 dropped requests per instance per deploy — times four instances, times a dozen deploys a day.

**This is the mechanism every zero-downtime rollout is built on.** Lesson 11 covers rolling, blue-green and canary deployments, and all three of them assume draining already works. A rolling deploy without draining is just an outage spread thinly enough that the graph hides it.

### Load-balancing algorithms belong to the next phase

You now have a pool of backends and something in front of it, so the obvious next question is *which* backend gets the next request. Round robin, weighted round robin, least connections, latency-weighted EWMA (exponentially weighted moving average), power-of-two-choices, and consistent hashing are all answers, and they differ sharply under load: least-connections and power-of-two-choices absorb heterogeneous backends that round robin does not, and consistent hashing is what lets a cache tier keep most of its hits when a node leaves.

That is a topic with its own measurements, and it belongs to **Phase 11: Scalability and Reliability**, alongside autoscaling, sharding and replication. The Build It here uses plain round robin deliberately, so that nothing in the draining and timeout results is an artefact of a clever picker. **The proxy as infrastructure — what it sees, terminates, rewrites and drains — is independent of which member it picks.**

### Ingress: proxy configuration generated by a control loop

You now have a reverse proxy and a config file listing backends by address. Both change every deploy. Editing that file by hand is the problem Lesson 6 and Lesson 7 already solved for infrastructure and workloads, and **Ingress is that same solution applied to proxy configuration**.

The shape is exactly Lesson 7's control loop. You write a declarative object — "requests for `shop.example/api/` go to the `orders` service on port 8080" — and a **controller** watches for such objects, watches the service endpoints, and continuously regenerates the configuration of a real proxy (nginx, Envoy, HAProxy, Traefik) to match. You never write the proxy config. You declare intent; a loop maintains the artifact.

Three pieces make it work:

- **`Ingress`** — the declarative object: hostnames, paths, target services, TLS secret.
- **`IngressClass`** — which controller owns this object. A cluster can run several (a public one and an internal-only one), and an `Ingress` with no class may be picked up by all of them or none.
- **The controller** — the loop, plus the proxy it configures. The proxy is a normal workload in the cluster, usually exposed by a cloud load balancer.

Ingress's limitation is that it standardised very little. Anything beyond host-and-path routing — timeouts, retries, header rewriting, canary weights, gRPC — lives in **controller-specific annotations**, which means an `Ingress` is portable in shape and non-portable in every detail that matters. That is precisely why the **Gateway API** exists: a role-oriented replacement (`GatewayClass`, `Gateway`, `HTTPRoute`) that puts traffic splitting, header matching and cross-namespace delegation into the specification itself, and separates the infrastructure owner's concerns from the application team's. It is the successor; new clusters should start there.

### Ingress, API gateway, service mesh — the distinction worth money

These three get conflated constantly, and the confusion is expensive because it leads teams to buy or build the wrong one. All three are reverse proxies. They differ in **what traffic they see** and **what they are for**.

**Ingress controller — north-south, infrastructure concern.** North-south means traffic entering the cluster from outside. Its job is *connectivity*: terminate TLS, match a hostname and path, forward to a service. It is deliberately dumb about your application's semantics. Owned by the platform team, one per cluster.

**API gateway — north-south, product concern.** Same direction of traffic, different altitude. It is about the **API as a product**: authentication and authorisation, API keys and quotas, rate limiting, request/response transformation, aggregating several backend calls into one client-facing endpoint, versioning, developer-facing documentation. [API Gateways & BFF](../../02-api-design/10-api-gateways-bff/) covers it in full. A gateway usually *replaces* the ingress controller rather than sitting beside it — it does the routing too, plus the product layer.

**Service mesh — east-west, uniform policy.** East-west means service-to-service traffic *inside* the cluster, which the other two never see. A mesh puts a proxy next to **every** instance (a sidecar, or increasingly a per-node or kernel-level proxy) so that every internal call passes through infrastructure you control. That buys you three things that are impractical to retrofit into application code across dozens of services: **mTLS everywhere** with automatic certificate rotation, **uniform retry/timeout/circuit-breaker policy**, and **complete telemetry** for every call without touching a single service. The cost is a proxy per instance — real memory, real latency, and a control plane that becomes a critical dependency.

The one-line test: **is this traffic entering my system, or moving inside it?** Entering, and you want connectivity → ingress. Entering, and you want product policy → API gateway. Moving inside, and you want uniform security and observability → mesh. Many organisations run all three, and that is not redundancy.

## Build It

[`code/reverse_proxy.py`](code/reverse_proxy.py) is a working reverse proxy over real sockets — real `ThreadingHTTPServer` backends on ephemeral ports, real TCP connections, real resets. Standard library only, no randomness, ~11 seconds. Four sections, each an argument.

**The router** is why an L7 proxy must parse the request at all. Rules are evaluated in order, `Host` before path prefix:

```python
def route(self, host: str, path: str):
    hostname = host.split(":")[0].lower()
    for kind, value, pool in self.rules:
        if kind == "host" and hostname == value:
            return pool, "Host: %s" % value
        if kind == "prefix" and path.startswith(value):
            return pool, "prefix %s" % value
    return self.default, "default"
```

**The header rewriting** is the part everybody gets wrong, so read it carefully. Hop-by-hop fields are dropped; `X-Forwarded-For` is *appended to*; `Host` survives the hop unchanged; and `trust_client_forwarded` is the one flag that decides whether the edge appends to what the client sent or discards it:

```python
def _rewrite(self, h):
    peer = h.client_address[0]
    host = h.headers.get("Host", "")
    out = {}
    for k, v in h.headers.items():
        if k.lower() in HOP_BY_HOP:      # RFC 9110 s7.6.1 — consumed by one hop
            continue
        out[k] = v
    prior_xff = h.headers.get("X-Forwarded-For") if self.trust_client_forwarded else None
    out["X-Forwarded-For"] = (prior_xff + ", " + peer) if prior_xff else peer
    out["X-Forwarded-Proto"] = self.scheme
    out.setdefault("X-Forwarded-Host", host)
    node = 'for=%s;proto=%s;host="%s"' % (peer, self.scheme, host)   # RFC 7239
    prior_fwd = h.headers.get("Forwarded") if self.trust_client_forwarded else None
    out["Forwarded"] = (prior_fwd + ", " + node) if prior_fwd else node
    out["Host"] = host
    return out
```

**The pool models the thing that causes the outage**: the proxy's *belief* about its backends is a separate variable from whether they are actually alive. `Member.routable` is not derived from `Backend.state`. A proxy only learns a backend is gone when a health check tells it or an operator removes it — and everything in section 4 is a consequence of that gap:

```python
@dataclass
class Member:
    backend: object
    routable: bool = True      # the PROXY's belief, not the truth
```

**The draining controller** is the whole lesson in twelve lines. Three strategies, and the only difference between the last two is a wait:

```python
if strategy == "kill":
    b2.kill()                             # the pool is never told
elif strategy == "remove_then_kill":
    target.routable = False               # stop NEW traffic
    b2.kill()                             # ...and stop, immediately
else:                                     # drain
    target.routable = False               # stop NEW traffic
    while b2.inflight > 0 and time.monotonic() - t0 < 5.0:
        time.sleep(0.002)                 # ...wait for the work already inside
    b2.kill()                             # ...only once it is idle
```

Run it:

```bash
docker compose exec -T app python \
  phases/10-infrastructure-and-deployment/09-reverse-proxies-and-load-balancers/code/reverse_proxy.py
```

```console
== 1 · A REVERSE PROXY IS A ROUTER WITH A SOCKET ON EACH SIDE ==
  one front door: proxy on 127.0.0.1:41699
  four back doors: api-1:44659, api-2:46331, static-1:44339, img-1:34675

  PATH               HOST             -> BACKEND  WHY
  /api/orders/1      shop.internal    -> api-1    prefix /api/
  /api/orders/2      shop.internal    -> api-2    prefix /api/
  /api/orders/3      shop.internal    -> api-1    prefix /api/
  /static/logo.svg   shop.internal    -> static-1 prefix /static/
  /api/orders/4      img.internal     -> img-1    Host: img.internal
  /img/cat.png       img.internal     -> img-1    Host: img.internal
  /static/app.css    shop.internal    -> static-1 prefix /static/
  /healthz           shop.internal    -> api-2    default

  8 client requests -> 4 upstream TCP connections opened, 4 reused
  the proxy keeps its OWN connections to each backend; client
  connections and upstream connections are separate lifetimes.

  the same 4 requests through an L4 (TCP) proxy pointed at api-1:
    /api/orders/1      Host: shop.internal    -> api-1      xff=None
    /api/orders/2      Host: shop.internal    -> api-1      xff=None
    /api/orders/3      Host: shop.internal    -> api-1      xff=None
    /static/logo.svg   Host: shop.internal    -> api-1      xff=None
  L7 proxy: 8 requests -> 4 distinct backends (Host + path)
  L4 proxy: 4 requests -> 1 distinct backend (it read 0 bytes of HTTP)
  L4 relayed 1714 bytes and added 0 headers: no X-Forwarded-For exists

== 2 · WHAT THE BACKEND SEES: X-FORWARDED-* AND THE SPOOF ==
  A · no proxy at all -- the client connects to the backend
      peer=127.0.0.9  Host=shop.internal  X-Forwarded-For=None

  B · client -> edge proxy -> ingress proxy -> backend (honest client)
      peer=127.0.0.3   Host=shop.internal  (the client's Host survived both hops)
      X-Forwarded-For:   127.0.0.9, 127.0.0.2
      X-Forwarded-Proto: http
      X-Forwarded-Host:  shop.internal
      Forwarded:         for=127.0.0.9;proto=http;host="shop.internal", for=127.0.0.2;proto=http;host="shop.internal"
      naive   xff.split(',')[0] -> 127.0.0.9
      trusted count back 2 hops -> 127.0.0.9
      both right -- the naive one only because nobody lied yet.

  C · same request, client sends its OWN X-Forwarded-For: 10.0.0.1
      X-Forwarded-For:   10.0.0.1, 127.0.0.9, 127.0.0.2
      naive   xff.split(',')[0] -> 10.0.0.1     SPOOFED
      trusted count back 2 hops -> 127.0.0.9    correct
      admin allowlist ['10.0.0.1']:
        naive parser   -> ALLOW (200, allowlist bypassed)
        trusted parser -> DENY (403)

  D · same spoof, but the edge OVERWRITES client-supplied X-Forwarded-For
      X-Forwarded-For:   127.0.0.9, 127.0.0.2
      naive   xff.split(',')[0] -> 127.0.0.9    correct now
      trusted count back 2 hops -> 127.0.0.9    correct always

  E · the 403 from The Problem, measured
      3 clients from 3 addresses -> backend socket peer was 127.0.0.3
      3 distinct client addresses collapsed to 1 at the backend.
      any allowlist, rate limit or audit log keyed on the socket
      address now sees one client. X-Forwarded-For recovers all 3: 127.0.0.10, 127.0.0.11, 127.0.0.9

== 3 · TIMEOUTS AT EVERY HOP: THE SLOW BACKEND ==
  60 requests, one every 20 ms, round-robin over 3 backends.
  fast-1 and fast-2 answer in 8 ms; slow-1 takes 2000 ms.
  the proxy has 6 worker slots; a request that cannot get one in
  50 ms is refused with 503 at the door.

  config                      200   504   503      p50      p99    good/s      wall
  no upstream timeout          18     0    42      51ms    2003ms      7.7     2.35s
  proxy_read_timeout 250ms     40    20     0      10ms     253ms     27.9     1.43s

  with no upstream timeout, 6 slow requests held 6 of the proxy's
  6 slots for 2 s each, so 42 of 60 requests (70%) were refused
  at the door -- the proxy failed because a BACKEND was slow.
  with a 250 ms upstream timeout the slots came back 8x faster:
  40 served instead of 18 (2.2x), and 0 refusals.

  the bill for the timeout, measured on the backend side:
  config                      accepted  finished  delivered   wasted work
  no upstream timeout                6         6          6        0 (0.0 s)
  proxy_read_timeout 250ms          20        20          0       20 (40.0 s)
  20 requests timed out at the proxy and the backend finished all 20
  of them anyway -- 40.0 s of backend work written to 20 sockets that
  the proxy had already closed. A timeout does not cancel work.
  It only stops YOU waiting for it: you pay for the work twice, once
  in backend capacity and once in the 504 the user actually sees.

== 4 · TAKING A BACKEND OUT OF ROTATION, THREE WAYS ==
  45 requests, one every 30 ms, round-robin over 3 backends,
  400 ms of work each. be-2 is removed the moment it has 3
  requests in flight. Identical schedule for all three runs.

  strategy                             inflight    wait   200  FAILED   severed  refused
  (a) kill it                                 3     19ms    30      15         3       12
  (b) remove from pool, then kill             3     21ms    42       3         3        0
  (c) drain: stop new work, wait, stop        3    404ms    45       0         0        0

  (a) the pool never learned. 3 requests were severed mid-flight and
      12 more were sent to an address with nothing listening.
  (b) removing it first stopped the 12 refusals -- but the 3 requests
      already inside be-2 still died. 'Remove then stop' is not enough.
  (c) same removal, plus 404 ms of waiting for in-flight work to finish.
      failed requests: 0. Not 'few'. Zero.

  cost of correctness: 404 ms of waiting. Cost of skipping it: 15
  dropped requests per backend, per deploy, times every instance you
  replace. This is the mechanism every zero-downtime rollout is built
  on -- rolling, blue-green and canary all assume it already works.

== SHUTDOWN ==
  10 servers created, 10 listening sockets closed, 0 leaked
  (total wall time 11.5 s)
```

**Section 1** is the capability gap, drawn from real sockets. The routing table is worth reading line by line: `/api/orders/1` and `/api/orders/2` matched the same prefix rule and still went to *different* backends (round robin inside the pool), while `/api/orders/4` matched the `/api/` prefix and went to `img-1` anyway — because the `Host: img.internal` rule is evaluated first and **rule order is a routing decision, not a formatting choice.** Then the connection arithmetic: **8 client requests, 4 upstream connections opened, 4 reused.** Two independent sets of sockets with independent lifetimes.

The L4 comparison is the argument. The same four requests, through a proxy pointed at `api-1`, all reached `api-1`. Not because of a policy — because **the L4 proxy relayed 1,714 bytes without parsing one of them.** It cannot route on a path it never read, and `xff=None` on every row because there is no such thing as adding a header to a byte stream. Everything an L7 proxy can do for you, and everything it can break for you, comes from the fact that it read the request.

**Section 2** is the security result, in five steps. **A** is the baseline: with no proxy, the backend's socket peer *is* the client, `127.0.0.9`, and no forwarding header exists. **B** inserts two proxies and the peer becomes `127.0.0.3` — the ingress — while `X-Forwarded-For: 127.0.0.9, 127.0.0.2` preserves the chain and `Host: shop.internal` survives both hops untouched. Note that both parsers agree here. **The naive parser is not wrong yet; it is merely untested.**

**C** tests it. The client sends its own `X-Forwarded-For: 10.0.0.1`, the honest edge appends to it as it must, and the backend receives `10.0.0.1, 127.0.0.9, 127.0.0.2`. The naive left-most parser reports `10.0.0.1` and the admin allowlist **returns 200 to an attacker who wrote one header.** The trusted-hop parser counts back two positions, reports `127.0.0.9`, and returns `403`. **D** shows the defence in depth: with the edge configured to *overwrite* rather than append, the forgery never enters the chain and even the naive parser is correct — you have removed the lie rather than the code that believes it. Do both.

**E** is The Problem's `403`, measured. Three clients from three addresses arrive at the backend with a socket peer of `127.0.0.3` in every case: **3 distinct client addresses collapsed to 1.** Every allowlist, rate limit and audit log keyed on the socket address now sees one client with triple the traffic. The header recovers all three — if you parse it correctly.

**Section 3** is the timeout, from both sides. Without an upstream timeout the proxy served **18 of 60** requests and refused **42 (70%)** with a `503`. Read that carefully: the failing component here is *the proxy*, and its own backends were 2 of 3 healthy the whole time. Six slow requests consumed all six worker slots for two seconds each, and everything else was rejected at a door that had nothing to do with the slow backend. p99 was **2,003 ms**. Adding `proxy_read_timeout 250ms` served **40 instead of 18 (2.2×)**, refused **0**, and cut p99 to **253 ms** — three milliseconds over the timeout, because p99 is now a number you chose rather than a number the slowest backend chose for you.

Then the bill. On the backend side, the timed-out run shows **20 accepted, 20 finished, 0 delivered — 40.0 seconds of work written to 20 sockets the proxy had already closed.** The timeout did not stop any work; it stopped the proxy waiting. Every one of those 20 requests cost full backend capacity and produced a `504`. This is the number to bring to the argument about whether a timeout is "just giving up early": you were always going to pay for the work, and the only question is whether you also pay a worker slot to wait for it.

**Section 4** is the centrepiece, and the three rows are the whole of zero-downtime deployment. Identical 45-request schedule, identical trigger — remove `be-2` the moment it holds 3 requests.

**(a) Kill it: 15 failed.** Three requests severed mid-flight, and **12 more refused** because the pool went on taking its round-robin turns at a dead address. That 12 is the second population from The Problem, and it dwarfs the first.

**(b) Remove from the pool, then kill: 3 failed.** Removing it first eliminated all 12 refusals — a 4× improvement for one line — and did **nothing at all** for the 3 requests already inside. This is the row that corrects the common intuition: "take it out of the load balancer, then stop it" is not draining, and the requests it drops are the *oldest* ones, the ones that have already done the most work and are most likely to have taken a side effect.

**(c) Drain: 0 failed.** Same removal, plus **404 ms** of waiting for `inflight` to reach zero. Not fewer failures. **None.** 45 of 45 served.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 496" width="100%" style="max-width:840px" role="img" aria-label="Three ways to remove one backend from a pool of three, drawn as timelines with three requests in flight at the moment of removal. Killing the process outright severed the 3 in-flight requests and refused 12 more that the pool kept sending, for 15 failed requests. Removing it from the pool first stopped the 12 refusals but still severed the 3 in-flight requests, for 3 failures. Draining — remove from the pool, wait roughly 400 milliseconds for the in-flight work to finish, then stop — failed zero requests out of 45.">
  <defs>
    <marker id="l09-a3" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Removing one backend, three ways. Only one of them is free.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="46" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.85">45 requests &#8226; one every 30 ms &#8226; 3 backends &#8226; 400 ms of work each &#8226; identical schedule in all three runs</text>

    <g fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.35" stroke-dasharray="4 4">
      <path d="M300 62 L 300 424"/>
    </g>
    <text x="300" y="74" font-size="9" font-weight="700" text-anchor="middle" fill="#e0930f">be-2 removed here</text>
    <text x="300" y="86" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.8">3 requests in flight</text>

    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="24" y="94" width="672" height="98" rx="10" fill="#d64545" fill-opacity="0.08" stroke="#d64545"/>
      <rect x="24" y="204" width="672" height="98" rx="10" fill="#e0930f" fill-opacity="0.09" stroke="#e0930f"/>
      <rect x="24" y="314" width="672" height="98" rx="10" fill="#0fa07f" fill-opacity="0.09" stroke="#0fa07f"/>
      <rect x="708" y="94" width="148" height="98" rx="10" fill="#d64545" fill-opacity="0.14" stroke="#d64545"/>
      <rect x="708" y="204" width="148" height="98" rx="10" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
      <rect x="708" y="314" width="148" height="98" rx="10" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
    </g>

    <g fill="currentColor">
      <text x="38" y="114" font-size="11.5" font-weight="700" fill="#d64545">(a) kill it</text>
      <text x="38" y="129" font-size="8.5" opacity="0.85">SIGKILL. The pool is never told.</text>
      <text x="38" y="224" font-size="11.5" font-weight="700" fill="#e0930f">(b) remove from the pool, then kill</text>
      <text x="38" y="239" font-size="8.5" opacity="0.85">stop NEW traffic &#8212; and stop, at once</text>
      <text x="38" y="334" font-size="11.5" font-weight="700" fill="#0fa07f">(c) drain: stop new work, wait, stop</text>
      <text x="38" y="349" font-size="8.5" opacity="0.85">stop NEW traffic, then wait for idle</text>
    </g>

    <g font-size="8" fill="currentColor" opacity="0.7">
      <text x="196" y="150" text-anchor="end">in flight</text>
      <text x="196" y="176" text-anchor="end">still routed here</text>
      <text x="196" y="260" text-anchor="end">in flight</text>
      <text x="196" y="286" text-anchor="end">still routed here</text>
      <text x="196" y="370" text-anchor="end">in flight</text>
      <text x="196" y="396" text-anchor="end">still routed here</text>
    </g>

    <g stroke-width="1.5">
      <rect x="204" y="140" width="96" height="8" rx="4" fill="#3553ff" fill-opacity="0.5" stroke="#3553ff"/>
      <rect x="228" y="152" width="72" height="8" rx="4" fill="#3553ff" fill-opacity="0.5" stroke="#3553ff"/>
      <rect x="252" y="164" width="48" height="8" rx="4" fill="#3553ff" fill-opacity="0.5" stroke="#3553ff"/>
      <rect x="204" y="250" width="96" height="8" rx="4" fill="#3553ff" fill-opacity="0.5" stroke="#3553ff"/>
      <rect x="228" y="262" width="72" height="8" rx="4" fill="#3553ff" fill-opacity="0.5" stroke="#3553ff"/>
      <rect x="252" y="274" width="48" height="8" rx="4" fill="#3553ff" fill-opacity="0.5" stroke="#3553ff"/>
      <rect x="204" y="360" width="96" height="8" rx="4" fill="#3553ff" fill-opacity="0.5" stroke="#3553ff"/>
      <rect x="228" y="372" width="72" height="8" rx="4" fill="#3553ff" fill-opacity="0.5" stroke="#3553ff"/>
      <rect x="252" y="384" width="48" height="8" rx="4" fill="#3553ff" fill-opacity="0.5" stroke="#3553ff"/>
    </g>

    <g stroke-width="1.5">
      <rect x="300" y="360" width="72" height="8" rx="4" fill="#0fa07f" fill-opacity="0.55" stroke="#0fa07f"/>
      <rect x="300" y="372" width="96" height="8" rx="4" fill="#0fa07f" fill-opacity="0.55" stroke="#0fa07f"/>
      <rect x="300" y="384" width="120" height="8" rx="4" fill="#0fa07f" fill-opacity="0.55" stroke="#0fa07f"/>
      <rect x="300" y="356" width="120" height="40" rx="6" fill="none" stroke="#0fa07f" stroke-width="1.4" stroke-dasharray="5 4"/>
    </g>
    <text x="360" y="405" font-size="8.5" text-anchor="middle" fill="#0fa07f" font-weight="700">the wait: ~400 ms, then stop</text>

    <g stroke="#d64545" stroke-width="2">
      <path d="M300 144 L 316 144"/><path d="M300 156 L 316 156"/><path d="M300 168 L 316 168"/>
      <path d="M300 254 L 316 254"/><path d="M300 266 L 316 266"/><path d="M300 278 L 316 278"/>
    </g>
    <g fill="#d64545" font-size="8.5" font-weight="700">
      <text x="322" y="147">severed mid-request &#215;3</text>
      <text x="322" y="257">severed mid-request &#215;3</text>
    </g>

    <g stroke-width="1.5">
      <rect x="316" y="180" width="336" height="8" rx="4" fill="#d64545" fill-opacity="0.35" stroke="#d64545"/>
    </g>
    <text x="322" y="173" font-size="8.5" fill="#d64545" font-weight="700">the pool keeps sending: &#215;12 refused, connection refused</text>
    <text x="322" y="288" font-size="8.5" fill="#0fa07f" font-weight="700">pool no longer routes here &#8594; 0 refused</text>
    <text x="430" y="398" font-size="8.5" fill="#0fa07f" font-weight="700">every in-flight request finishes normally</text>

    <g text-anchor="middle" fill="currentColor">
      <text x="782" y="120" font-size="21" font-weight="700" fill="#d64545">15</text>
      <text x="782" y="138" font-size="9" opacity="0.9">requests dropped</text>
      <text x="782" y="156" font-size="8.5" opacity="0.85">3 severed + 12 refused</text>
      <text x="782" y="174" font-size="8.5" opacity="0.85">30 of 45 served</text>
      <text x="782" y="230" font-size="21" font-weight="700" fill="#e0930f">3</text>
      <text x="782" y="248" font-size="9" opacity="0.9">requests dropped</text>
      <text x="782" y="266" font-size="8.5" opacity="0.85">3 severed + 0 refused</text>
      <text x="782" y="284" font-size="8.5" opacity="0.85">42 of 45 served</text>
      <text x="782" y="340" font-size="21" font-weight="700" fill="#0fa07f">0</text>
      <text x="782" y="358" font-size="9" opacity="0.9">requests dropped</text>
      <text x="782" y="376" font-size="8.5" opacity="0.85">0 severed + 0 refused</text>
      <text x="782" y="394" font-size="8.5" font-weight="700" fill="#0fa07f">45 of 45 served</text>
    </g>

    <text x="440" y="446" font-size="10.5" text-anchor="middle" fill="currentColor">Removing it from the pool fixes the 12 refusals. It does nothing at all for the 3 already inside.</text>
    <text x="440" y="470" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Cost of correctness: ~400 ms of waiting, once. Cost of skipping it: 15 dropped requests, per instance, per deploy.</text>
  </g>
</svg>
```

One detail in the shutdown line matters for reading the rest of this phase: **10 servers created, 10 listening sockets closed, 0 leaked.** The script asserts its own cleanliness, because a lesson about draining that leaks a listener would be an unusually poor joke.

## Use It

### nginx: the same four behaviours, as config

```text
upstream orders {
    server 10.0.1.11:8080 max_fails=2 fail_timeout=10s;
    server 10.0.1.12:8080 max_fails=2 fail_timeout=10s;
    keepalive 32;                      # the upstream pool from section 1
}

server {
    listen 443 ssl;
    server_name shop.example;

    ssl_certificate     /etc/letsencrypt/live/shop.example/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/shop.example/privkey.pem;

    # WHICH addresses may set X-Forwarded-For. Without these two lines the
    # realip module trusts anybody, which is section 2's spoof.
    set_real_ip_from 10.0.0.0/8;
    real_ip_header   X-Forwarded-For;
    real_ip_recursive on;              # walk left past every trusted hop

    location /api/ {
        proxy_pass http://orders;

        # $proxy_add_x_forwarded_for = the incoming header, plus $remote_addr.
        # It APPENDS. That is correct for an inner hop and WRONG at your edge,
        # where you want:  proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host  $host;
        proxy_set_header Host              $host;
        proxy_set_header Connection        "";   # keep-alive to upstream needs this

        proxy_connect_timeout 2s;      # opening the upstream socket
        proxy_send_timeout    5s;
        proxy_read_timeout    5s;      # THE one. Default is 60s.
        proxy_next_upstream error timeout http_502 http_503;
        proxy_next_upstream_tries 2;   # a retry budget, not "keep trying"
    }
}
```

Three things to notice. `proxy_read_timeout` **defaults to 60 seconds** — a value that permits exactly the section 3 failure, where a slow backend consumes every worker for a minute at a time. `$proxy_add_x_forwarded_for` appends, which is right for an internal hop and wrong at the true edge, where you should overwrite with `$remote_addr` and destroy any client-supplied value. And `proxy_next_upstream` is a retry: safe for `error` and `timeout` on idempotent requests, dangerous on a `POST` unless you have the idempotency key from [Idempotency & Safe Retries](../../02-api-design/07-idempotency-safe-retries/).

**Graceful reload** is nginx's own draining: `nginx -s reload` starts new worker processes with the new config and lets the old workers **finish their in-flight requests** before exiting. That is section 4(c) applied to configuration changes instead of backends — the same three steps, the same reason.

### Envoy: the same ideas, explicit

```yaml
route_config:
  virtual_hosts:
    - name: shop
      domains: ["shop.example"]
      routes:
        - match: { prefix: "/api/" }
          route:
            cluster: orders
            timeout: 5s                     # per-route upstream timeout
            retry_policy:
              retry_on: "5xx,connect-failure,reset"
              num_retries: 2
clusters:
  - name: orders
    connect_timeout: 2s
    health_checks:                          # ACTIVE checking
      - timeout: 1s
        interval: 3s
        unhealthy_threshold: 2
        healthy_threshold: 2
        http_health_check: { path: "/readyz" }
    outlier_detection:                      # PASSIVE checking
      consecutive_5xx: 5
      base_ejection_time: 30s
      max_ejection_percent: 50              # never eject everything at once
```

Envoy's `xff_num_trusted_hops` is `trusted_client_ip`'s `trusted_hops` by another name, and setting it wrong is the same bug. `max_ejection_percent` is the rule that stops a *global* fault — a bad deploy, a dead database — from causing the proxy to eject 100% of backends and turn a degradation into a full outage.

### Kubernetes: `Ingress` today, Gateway API next

```yaml
apiVersion: networking.k8s.io/v1
kind: IngressClass
metadata:
  name: public-nginx
spec:
  controller: k8s.io/ingress-nginx        # WHICH controller owns these objects
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: shop
  annotations:
    # Everything below the routing rules is controller-specific. This is the
    # portability problem the Gateway API exists to fix.
    nginx.ingress.kubernetes.io/proxy-read-timeout: "5"
    nginx.ingress.kubernetes.io/proxy-next-upstream: "error timeout"
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  ingressClassName: public-nginx
  tls:
    - hosts: [shop.example]
      secretName: shop-tls               # cert-manager creates and renews this
  rules:
    - host: shop.example
      http:
        paths:
          - path: /api/
            pathType: Prefix             # Prefix | Exact | ImplementationSpecific
            backend:
              service: { name: orders, port: { number: 8080 } }
```

The controller watches this object and the `orders` service's endpoints, and regenerates real nginx configuration whenever either changes — Lesson 7's control loop, with proxy config as the artifact. The same routing in the Gateway API, where timeouts and traffic splitting are specified rather than annotated:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: shop
spec:
  parentRefs: [{ name: public-gateway }]     # owned by the platform team
  hostnames: ["shop.example"]
  rules:
    - matches: [{ path: { type: PathPrefix, value: /api/ } }]
      timeouts: { request: 5s }              # in the SPEC, not an annotation
      backendRefs:
        - { name: orders, port: 8080, weight: 90 }
        - { name: orders-canary, port: 8080, weight: 10 }
```

Those weights are a canary release expressed as data — which is where Lesson 11 goes next.

### Cloud load balancers: ALB, NLB, and the managed drain

- **ALB (Application Load Balancer)** is L7. Host and path routing, header-based routing, TLS termination with certificates from ACM, and it sets `X-Forwarded-For` / `X-Forwarded-Proto` for you.
- **NLB (Network Load Balancer)** is L4. It forwards TCP, preserves the client's source IP by default, and handles far higher connection rates for far less money. It cannot route on a path, and it cannot add a header — section 1's L4 result, as a product.

The setting that matters most for this lesson is **`deregistration_delay.timeout_seconds`** (AWS calls the feature *connection draining*; GCP and Azure have direct equivalents). On deregistration the load balancer stops sending a target **new** requests but lets existing ones finish for that long. **That is section 4(c), managed.** Its default is 300 seconds, and the number to get right is the relationship between it and your orchestrator's `terminationGracePeriodSeconds`: if the grace period is shorter, the orchestrator kills a pod the load balancer still believes is draining, and you are back to row (b).

TLS certificates are an operational concern, not a one-time setup. Use **cert-manager** in Kubernetes or your cloud's managed certificates; both implement **ACME** (Automatic Certificate Management Environment, RFC 8555) to obtain and renew automatically. Let's Encrypt certificates last 90 days. **An expired certificate is a total outage with a fixed, known date**, and it remains one of the most common self-inflicted incidents in the industry.

### The `trust proxy` setting in your framework

Every framework has this, every framework defaults it off, and turning it fully on is as wrong as leaving it off:

```python
# Flask / Werkzeug — x_for is the HOP COUNT, not a boolean
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=2, x_proto=1, x_host=1)
```

```javascript
// Express — a number is a hop count; `true` means "trust everything", which is
// exactly the spoofable parser from section 2.
app.set('trust proxy', 2);
```

Set it to the number of proxies **you operate**, and treat it as a value that must be reviewed whenever the topology changes. Adding a CDN in front of an existing load balancer changes this number, and nothing will fail loudly when it is wrong — your rate limiter will simply start limiting your own edge, and your audit log will start recording the wrong address.

### Sticky sessions are a smell

Every load balancer offers session affinity: a cookie or a source-IP hash that pins a client to one backend. It works, and it converts every backend into a small stateful singleton. Removing one now destroys sessions rather than shifting load; scaling out does not rebalance existing users; and your draining window is bounded by session length rather than request length. The right fix is to move the state out of the process — a shared session store, or a signed token the client carries. Where affinity is genuinely needed (long-lived WebSocket connections, in-process caches with expensive warmup), it is a **consistent hashing** problem, and that belongs to **Phase 11: Scalability and Reliability**.

### Rules that survive contact with an incident

- **Terminate TLS at the edge.** One certificate, one rotation path, full L7 capability. Passthrough only when the backend must see the client certificate; re-encrypt when the internal network is not trusted.
- **Set a timeout at every hop, with the inner strictly shorter than the outer.** Write the ladder down: client > edge > ingress > app > database. nginx's `proxy_read_timeout` defaults to 60 s, which is not a timeout, it is a hope.
- **Parse `X-Forwarded-For` by trusted hop count, never `split(",")[0]`.** Overwrite the header at your true edge. Set your framework's `trust proxy` to your real hop count, and review it when the topology changes.
- **Drain before you stop.** Mark not-routable, wait for in-flight to reach zero (or a deadline), then exit. Measured: 15 dropped requests without it, 0 with it, for ~400 ms of waiting.
- **Health-check a real endpoint, not a TCP connect.** A deadlocked process completes the TCP handshake forever. Check readiness, not liveness, and cap ejection (`max_ejection_percent`) so a global fault cannot empty the pool.
- **Retry only what is safe to retry, with a budget.** `proxy_next_upstream_tries 2`, not "keep trying". A proxy that retries a `POST` on timeout will double-charge somebody.
- **Log the resolved client IP, not the socket peer** — and log the whole `X-Forwarded-For` chain alongside it, so an incident can distinguish a spoof from a topology change.

## Think about it

1. You add a CDN in front of your existing load balancer. Nothing in your application changes and nothing fails loudly. Trace precisely what happens to your rate limiter, your admin IP allowlist and your audit log over the following week, and say which single value you must change and how you would detect that it is wrong without an incident.
2. Section 3 measured 20 requests timing out at the proxy while the backend completed all 20 — 40 seconds of work delivered to nobody. Design a mechanism that would let the backend learn its caller has gone away, and say what it must be able to do at every layer between the two for that signal to actually stop the work. What does your answer imply about where a request's deadline has to live?
3. Row (b) dropped 3 requests: the ones already inside the backend. Those are the *oldest* requests, and therefore the most likely to have already taken a side effect — a charge, a write, an email. Given that draining always has a deadline, describe what should happen to a request still in flight when that deadline expires, and what the backend must have done earlier for that to be safe.
4. Your edge overwrites `X-Forwarded-For`, which defeats the spoof entirely. Now a genuine CDN in front of you needs to pass through the real client address. Reconcile these two requirements, and say what an attacker must control for your reconciliation to fail.
5. You run an L4 load balancer because your backends do mutual TLS. Your team now wants path-based routing, per-route timeouts, and the real client IP in application logs. List what you would have to give up or add for each of those three, and say whether the mesh, the gateway or the ingress is the right place to put them.

## Key takeaways

- **A reverse proxy's power and its bill both come from parsing the request.** Measured: 8 requests through the L7 proxy reached **4 distinct backends** by `Host` and path prefix; the same requests through an L4 proxy reached **1**, because it relayed **1,714 bytes and added 0 headers**. L7 must terminate TLS to read anything, must buffer, and is a full participant in the connection — not a wire.
- **The proxy runs its own connections.** 8 client requests produced **4 upstream connections opened and 4 reused**, on lifetimes completely independent of the client's. That is why the proxy's keep-alive idle timeout must be shorter than the backend's, and why hop-by-hop headers (RFC 9110 §7.6.1) must never be forwarded.
- **`X-Forwarded-For` is client input until a trusted hop overwrites it.** With a forged header, `xff.split(",")[0]` reported `10.0.0.1` and **the admin allowlist returned 200**; counting back 2 trusted hops reported `127.0.0.9` and returned **403** — same request, two lines of parsing. And the header is not optional: behind a proxy, **3 distinct client addresses collapsed to 1** at the backend socket.
- **A mismatched timeout is worse than a long one.** With **no** upstream timeout, 6 slow requests held all 6 proxy slots and **42 of 60 requests (70%) were refused with a 503** — the proxy failed because a backend was slow, p99 **2,003 ms**. A 250 ms timeout served **40 instead of 18 (2.2×)** with **0 refusals** and p99 **253 ms** — and the backend still **completed all 20 timed-out requests, delivering 0: 40.0 s of work written to closed sockets.** A timeout never cancels work; it only stops you waiting.
- **Draining is three steps and the middle one is the whole point.** Killing a backend holding 3 requests cost **15 failed** (3 severed + 12 refused by a pool that had not been told). Removing it from the pool first cost **3 failed** — the refusals gone, the in-flight requests still dead. Removing it and then **waiting ~400 ms** for in-flight work cost **0 failed, 45 of 45 served.** Rolling, blue-green and canary deployments all assume this already works.
- **Ingress is a control loop that writes proxy config; a gateway and a mesh are different jobs.** Ingress and `IngressClass` are connectivity for north-south traffic, with everything interesting hidden in controller-specific annotations — which is why the **Gateway API** puts timeouts and traffic weights in the spec. An **API gateway** is north-south *product* policy (auth, quotas, aggregation); a **service mesh** is east-west uniform policy (mTLS, retries, telemetry) via a proxy beside every instance. Ask whether the traffic is entering the system or moving inside it.

Next: [CI/CD: From Commit to Artifact to Environment](../10-ci-cd-pipelines/) — you can now put a backend into rotation and take it out without dropping a request; next is the pipeline that decides which artifact goes in, and proves it is the one you tested.
