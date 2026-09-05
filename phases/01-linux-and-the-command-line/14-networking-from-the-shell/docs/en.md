# Networking from the Shell: ip, ss, ping, dig, nc & tcpdump

> "It cannot connect" has five layers and each one has a command. This lesson rebuilds the tools that read them, `ip addr` and `ip route` from `/sys` and `/proc/net/route`, `ss` from `/proc/net/tcp` with the owning PID found through `/proc/*/fd`, a port check that tells **refused** from **timed out** from **unreachable**, a resolver lookup, and a three-packet `tcpdump` decoded from a raw socket, then runs the real ones on the sandbox: a `SYN` answered by `SYN-ACK` in **17 µs** on loopback, `EADDRINUSE` with the holder named, a `DROP` rule that turns refused into a timeout, and the counters that say whether the accept queue ever overflowed.

## The Problem

Phase 2 will build the network from the wire up: frames, packets, TCP, DNS, HTTP, TLS, each one in Python. This lesson is what you do at 3 a.m. *before* any of that matters: the service cannot reach the database, or a client cannot reach the service, and the error says one of six things, `Name or service not known`, `No route to host`, `Connection timed out`, `Connection refused`, `Address already in use`, or nothing at all. Each is a different layer. Each has a command that answers it in seconds. The people who fix these fast are not the ones who know the most about TCP; they are the ones who ask the layers in order and read the answer literally.

The tools are on every box, and every one of them reads a kernel table or opens a socket. Knowing which table makes the output obvious, and rebuilding four of them in Python makes it impossible to forget.

## The Concept

### The ladder

A connection attempt passes through five things in order, and a failure names the first one that said no. That order is the diagnosis:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 480" width="100%" style="max-width:880px" font-family="'JetBrains Mono', ui-monospace, monospace" role="img" aria-label="Five layers a connection passes through, drawn as a ladder from top to bottom with the command that checks each and the error that points at it. One, the name: getent hosts and dig; failure says name or service not known, NXDOMAIN, or temporary failure in name resolution; sources are /etc/hosts, /etc/resolv.conf and nsswitch.conf. Two, the route: ip route get and ip -br addr; failure says network is unreachable or no route to host; sources are /proc/net/route and the interface state. Three, reachability: ping, traceroute, and nc -zv to the real port; failure is a timeout, meaning no answer at all. Four, the port: ss -tlnp on the server; failure is connection refused, meaning a host answered with RST because nothing listens there, or it listens on 127.0.0.1 only, or EADDRINUSE at start. Five, the firewall, on both ends and in between: nft list ruleset, ufw status, cloud security groups; a DROP rule looks like layer three's timeout, a REJECT rule looks like layer four's refused. Below the ladder, the protocol: curl -v, openssl s_client, for what happens after the connection exists. A note: tcpdump watches the wire when the layers disagree.">
  <defs>
    <marker id="p1l14a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">The ladder: five layers, one command each, and the error that names the layer</text>
  <g stroke-linejoin="round" stroke-width="1.6">
    <rect x="40" y="48"  width="820" height="60" rx="9" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
    <rect x="40" y="118" width="820" height="60" rx="9" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
    <rect x="40" y="188" width="820" height="60" rx="9" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
    <rect x="40" y="258" width="820" height="60" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    <rect x="40" y="328" width="820" height="60" rx="9" fill="#d64545" fill-opacity="0.08" stroke="#d64545"/>
    <rect x="40" y="398" width="820" height="44" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="#7f7f7f" stroke-dasharray="6 4"/>
  </g>
  <g font-size="8.5" fill="currentColor">
    <text x="56" y="68" font-size="10.5" font-weight="700" fill="#7c5cff">1 · THE NAME</text>
    <text x="56" y="84">getent hosts api.internal · dig +short api.internal · cat /etc/resolv.conf · grep api /etc/hosts</text>
    <text x="56" y="99" opacity="0.8">error: Name or service not known · NXDOMAIN · Temporary failure in name resolution      source: nsswitch.conf → hosts, then DNS over UDP 53</text>
    <text x="56" y="138" font-size="10.5" font-weight="700">2 · THE ROUTE</text>
    <text x="56" y="154">ip route get 10.20.30.40 · ip route · ip -br addr · ip -s link show eth0</text>
    <text x="56" y="169" opacity="0.8">error: Network is unreachable · No route to host      source: /proc/net/route, the interface state, the default gateway</text>
    <text x="56" y="208" font-size="10.5" font-weight="700" fill="#e0930f">3 · REACHABILITY</text>
    <text x="56" y="224">ping -c 3 · traceroute -n · nc -zv host port  (the probe to the REAL port is the one that counts)</text>
    <text x="56" y="239" opacity="0.8">error: Connection timed out = nothing answered: the host is down, the path black-holes, or a firewall DROPs (layer 5)</text>
    <text x="56" y="278" font-size="10.5" font-weight="700" fill="#0fa07f">4 · THE PORT (on the server)</text>
    <text x="56" y="294">ss -tlnp · ss -tlnp | grep ':8443' · is it bound to 127.0.0.1 only? · is Recv-Q at Send-Q?</text>
    <text x="56" y="309" opacity="0.8">error: Connection refused = a host answered RST: nothing listens there · EADDRINUSE at start = someone else holds it</text>
    <text x="56" y="348" font-size="10.5" font-weight="700" fill="#d64545">5 · THE FIREWALL (both ends, and in between)</text>
    <text x="56" y="364">nft list ruleset · ufw status verbose · the cloud security group · the load balancer's listener · egress rules and proxies</text>
    <text x="56" y="379" opacity="0.8">a DROP rule looks exactly like layer 3's timeout; a REJECT rule looks exactly like layer 4's refused. Test from inside, then outside</text>
    <text x="56" y="416" font-size="10" font-weight="700">then the protocol</text>
    <text x="56" y="432" opacity="0.85">curl -v · openssl s_client · a raw request through nc: what happens AFTER the connection exists (lessons 15 and 16, Phase 2)</text>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.4" stroke-opacity="0.6">
    <path d="M450 110 L450 116" marker-end="url(#p1l14a-ar)"/>
    <path d="M450 180 L450 186" marker-end="url(#p1l14a-ar)"/>
    <path d="M450 250 L450 256" marker-end="url(#p1l14a-ar)"/>
    <path d="M450 320 L450 326" marker-end="url(#p1l14a-ar)"/>
    <path d="M450 390 L450 396" marker-end="url(#p1l14a-ar)"/>
  </g>
  <text x="450" y="466" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">Ask in order, read the answer literally, and when two layers disagree, tcpdump shows which packets actually left and what came back.</text>
</svg>
```

### ip: the interface and the route

`ip addr` (or `ip -br addr` for the short form) lists interfaces with their addresses and state; `ip -s link` adds the byte, packet, error and drop counters that lesson 12 asked for; `ip route` prints the routing table and `ip route get ADDR` answers the only routing question that matters during an incident: which interface and gateway would a packet to *this* address use?

```console
$ ip -br addr
lo               UNKNOWN        127.0.0.1/8 ::1/128
eth0@if137       UP             192.168.97.2/24
$ ip route;  ip route get 1.1.1.1
default via 192.168.97.1 dev eth0
192.168.97.0/24 dev eth0 proto kernel scope link src 192.168.97.2
1.1.1.1 via 192.168.97.1 dev eth0 src 192.168.97.2 uid 0
```

Two rows: the local subnet, reached directly, and `default`, everything else, via the gateway. The kernel picks the most specific matching row; with no `default`, anything outside the subnet is `Network is unreachable`, before a single packet is sent. Both tables are files: `/sys/class/net/<if>/` holds each interface's address, MTU and state, and `/proc/net/route` holds the routes as little-endian hex, which the **Build It** script decodes.

### ss: who is listening, who is connected

`ss` replaced `netstat`. `-t` TCP, `-l` listening, `-n` numeric (no name lookups), `-p` the owning process (needs root for others' sockets), `-a` all states. Its source is `/proc/net/tcp`, one row per socket in hex, and its two queue columns mean different things on different rows:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 400" width="100%" style="max-width:880px" font-family="'JetBrains Mono', ui-monospace, monospace" role="img" aria-label="Two rows of ss output annotated. First, a LISTEN row: State LISTEN, Recv-Q 1, Send-Q 5, Local Address 0.0.0.0:8080, Peer 0.0.0.0:*, Process python3 pid 13. On a listening socket Recv-Q is the number of completed connections waiting for the server to call accept, and Send-Q is the backlog capacity from listen(); Recv-Q equal to Send-Q means the accept queue is full and new SYNs are dropped, counted in nstat as ListenOverflows. Local 0.0.0.0 means every interface; 127.0.0.1 means loopback only, unreachable from outside. Second, an ESTAB row: State ESTAB, Recv-Q 0, Send-Q 0, Local 127.0.0.1:8080, Peer 127.0.0.1:53180, and its twin from the client side with the addresses swapped. On an established socket Recv-Q is bytes received and not yet read by the application, a growing number means the app is not reading, and Send-Q is bytes sent and not yet acknowledged, a growing number means the peer or the path is slow. A footnote: every column comes from /proc/net/tcp, whose addresses are hex and little-endian, and the pid comes from matching the socket's inode against every process's descriptors.">
  <text x="450" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Reading ss: the same two queue columns mean different things on a LISTEN row and an ESTAB row</text>
  <rect x="40" y="48" width="820" height="150" rx="10" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="56" y="70" font-size="10" font-weight="700" fill="#0fa07f">A LISTEN ROW  (ss -tlnp)</text>
  <text x="56" y="92" font-size="9.5" fill="currentColor">LISTEN   1        5      0.0.0.0:8080      0.0.0.0:*     users:(("python3",pid=13,fd=3))</text>
  <g font-size="8.5" fill="currentColor">
    <text x="56" y="116">Recv-Q = 1:  completed handshakes waiting for the server to call accept()</text>
    <text x="56" y="130">Send-Q = 5:  the backlog capacity the server asked for in listen(5), capped by net.core.somaxconn</text>
    <text x="56" y="146" font-weight="700" fill="#d64545">Recv-Q reaching Send-Q = the accept queue is full: new SYNs are dropped and clients see timeouts (nstat: ListenOverflows)</text>
    <text x="56" y="164">Local 0.0.0.0:8080 = every interface  ·  127.0.0.1:8080 = loopback only, unreachable from any other machine  ·  [::]:8080 = IPv6 (and usually v4 too)</text>
    <text x="56" y="180" opacity="0.8">users:(...) needs root to see other users' processes; the pid is found by matching the socket's inode against /proc/*/fd</text>
  </g>
  <rect x="40" y="214" width="820" height="130" rx="10" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="56" y="236" font-size="10" font-weight="700" fill="#7c5cff">AN ESTAB ROW  (ss -tanp), and its twin on the other side</text>
  <text x="56" y="258" font-size="9.5" fill="currentColor">ESTAB    0        0      127.0.0.1:53180   127.0.0.1:8080     users:(("nc",pid=20,fd=3))</text>
  <text x="56" y="272" font-size="9.5" fill="currentColor">ESTAB    0        0      127.0.0.1:8080    127.0.0.1:53180</text>
  <g font-size="8.5" fill="currentColor">
    <text x="56" y="296">Recv-Q: bytes received by the kernel and not yet read by the application.  Growing = the app is not reading (stuck, or too slow)</text>
    <text x="56" y="310">Send-Q: bytes sent and not yet acknowledged by the peer.  Growing = the peer or the path is slow, or the peer is gone (retransmits, then RST)</text>
    <text x="56" y="328" opacity="0.8">one connection is two rows, one per end, with local and peer swapped. ss -s counts them by state; thousands of TIME-WAIT after a burst is normal</text>
  </g>
  <text x="450" y="372" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">Source: /proc/net/tcp, hex and little-endian. 0100007F:1F90 is 127.0.0.1:8080; state 0A is LISTEN, 01 is ESTAB.</text>
  <text x="450" y="390" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">Lesson 02 decoded this file; the Build It script adds the pid lookup that makes it ss -p.</text>
</svg>
```

On a **listening** socket, `Recv-Q` is the number of completed connections waiting for `accept()` and `Send-Q` is the backlog capacity; when the first reaches the second the accept queue is full, new `SYN`s are dropped, and clients see timeouts on a server that is "up" (`nstat -az | grep -i listen` counts it). On an **established** socket, `Recv-Q` is bytes the application has not read yet (growing: the app is stuck) and `Send-Q` is bytes the peer has not acknowledged (growing: the peer or the path is slow). And `Local Address` tells you the most common inbound failure of all: a service bound to `127.0.0.1` is reachable only from its own box.

### Refused, timed out, unreachable: three different packets

A TCP connect can fail three ways, and the difference is the entire diagnosis:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 380" width="100%" style="max-width:880px" font-family="'JetBrains Mono', ui-monospace, monospace" role="img" aria-label="Four outcomes of a TCP connect drawn as packet exchanges between a client on the left and a server on the right. Open: SYN goes right, SYN-ACK comes back, ACK goes right; connected in one round trip, 0.2 milliseconds on loopback. Refused: SYN goes right, RST comes back immediately; a host is there and nothing listens on that port, or a REJECT firewall rule answered; the error is ECONNREFUSED, instantly. Timed out: SYN goes right, nothing comes back, the client retries with growing gaps for the connect timeout; the host is down, the path black-holes, or a DROP rule ate it; the error is ETIMEDOUT after seconds. Unreachable: no packet is sent at all because the kernel has no route or the interface is down; the error is ENETUNREACH or EHOSTUNREACH, instantly. A footnote maps each to the ladder: refused is layer 4 or a reject at layer 5; timed out is layer 3 or a drop at layer 5; unreachable is layer 2.">
  <defs>
    <marker id="p1l14c-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p1l14c-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p1l14c-ard" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Four answers to one SYN, and what each one proves</text>
  <g stroke-linejoin="round" stroke-width="1.6">
    <rect x="30"  y="48" width="200" height="250" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
    <rect x="250" y="48" width="200" height="250" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
    <rect x="470" y="48" width="200" height="250" rx="10" fill="#d64545" fill-opacity="0.08" stroke="#d64545"/>
    <rect x="690" y="48" width="180" height="250" rx="10" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
  </g>
  <g text-anchor="middle" font-size="10" font-weight="700">
    <text x="130" y="70" fill="#0fa07f">OPEN</text>
    <text x="350" y="70" fill="#e0930f">REFUSED</text>
    <text x="570" y="70" fill="#d64545">TIMED OUT</text>
    <text x="780" y="70" fill="currentColor">UNREACHABLE</text>
  </g>
  <!-- open -->
  <g fill="none" stroke="#0fa07f" stroke-width="1.8">
    <path d="M50 100 L206 100" marker-end="url(#p1l14c-arg)"/>
    <path d="M210 124 L54 124" marker-end="url(#p1l14c-arg)"/>
    <path d="M50 148 L206 148" marker-end="url(#p1l14c-arg)"/>
  </g>
  <g font-size="8" fill="currentColor" text-anchor="middle">
    <text x="130" y="94">SYN</text><text x="130" y="118">SYN-ACK</text><text x="130" y="142">ACK</text>
    <text x="130" y="180">connected in one round trip</text>
    <text x="130" y="194">0.2 ms on loopback here</text>
    <text x="130" y="220" opacity="0.8">nc: succeeded</text>
    <text x="130" y="234" opacity="0.8">the layers below are fine;</text>
    <text x="130" y="248" opacity="0.8">anything wrong now is the</text>
    <text x="130" y="262" opacity="0.8">protocol or the application</text>
  </g>
  <!-- refused -->
  <g fill="none" stroke="#e0930f" stroke-width="1.8">
    <path d="M270 100 L426 100" marker-end="url(#p1l14c-ar)"/>
    <path d="M430 124 L274 124" marker-end="url(#p1l14c-ar)"/>
  </g>
  <g font-size="8" fill="currentColor" text-anchor="middle">
    <text x="350" y="94">SYN</text><text x="350" y="118" font-weight="700">RST</text>
    <text x="350" y="166">a host answered immediately:</text>
    <text x="350" y="180">nothing listens on that port,</text>
    <text x="350" y="194">or a REJECT rule replied</text>
    <text x="350" y="220" opacity="0.8">ECONNREFUSED, instantly</text>
    <text x="350" y="234" opacity="0.8">ladder: layer 4 (ss -tlnp),</text>
    <text x="350" y="248" opacity="0.8">or a reject at layer 5</text>
  </g>
  <!-- timeout -->
  <g fill="none" stroke="#d64545" stroke-width="1.8">
    <path d="M490 100 L646 100" marker-end="url(#p1l14c-ard)"/>
    <path d="M490 124 L646 124" marker-end="url(#p1l14c-ard)" stroke-dasharray="4 3"/>
    <path d="M490 148 L646 148" marker-end="url(#p1l14c-ard)" stroke-dasharray="4 3"/>
  </g>
  <g font-size="8" fill="currentColor" text-anchor="middle">
    <text x="570" y="94">SYN</text><text x="570" y="118">SYN (retry, 1 s)</text><text x="570" y="142">SYN (retry, 3 s) ...</text>
    <text x="570" y="166">nothing ever comes back:</text>
    <text x="570" y="180">host down, path black-holed,</text>
    <text x="570" y="194">or a DROP rule ate it</text>
    <text x="570" y="220" opacity="0.8">ETIMEDOUT, after seconds</text>
    <text x="570" y="234" opacity="0.8">ladder: layer 3 (ping, traceroute),</text>
    <text x="570" y="248" opacity="0.8">or a drop at layer 5</text>
  </g>
  <!-- unreachable -->
  <g font-size="8" fill="currentColor" text-anchor="middle">
    <text x="780" y="100" font-weight="700">(no packet sent)</text>
    <text x="780" y="166">the kernel has no route,</text>
    <text x="780" y="180">or the interface is down:</text>
    <text x="780" y="194">it refuses before trying</text>
    <text x="780" y="220" opacity="0.8">ENETUNREACH / EHOSTUNREACH,</text>
    <text x="780" y="234" opacity="0.8">instantly</text>
    <text x="780" y="248" opacity="0.8">ladder: layer 2 (ip route get)</text>
  </g>
  <text x="450" y="330" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">Refused means someone is there. Timed out means nobody answered. Unreachable means the packet never left. Read the word.</text>
  <text x="450" y="352" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">nc -zv host port produces exactly one of these, in under a second for three of them. It is the single most useful command in this lesson.</text>
</svg>
```

**Refused** means a host received the `SYN` and answered `RST`: it is up, and nothing is listening on that port (or a firewall *rejected*). **Timed out** means nothing answered at all: the host is down, the path drops, or a firewall *dropped* (the default on most cloud security groups, which is why cloud connection problems always look like timeouts). **Unreachable** means the kernel never sent the packet: no route, or the interface is down. `nc -zv host port` produces one of the three in a second, and the **Build It** script produces all three on purpose.

The server-side counterpart is `EADDRINUSE` at bind time: the port is held by the previous copy still shutting down, a child that inherited the listening socket and outlived its parent (lesson 10), or another service. `ss -tlnp` names the holder. `SO_REUSEADDR`, which every server sets and lesson 09's Phase 2 echo server set, allows a bind while old connections sit in `TIME-WAIT`; it does not allow two listeners.

### dig: the name, and where the answer came from

Before any packet, the name has to become an address. The order is in `/etc/nsswitch.conf` (`hosts: files dns`): `/etc/hosts` first, then the resolvers in `/etc/resolv.conf`, over UDP port 53. `getent hosts NAME` follows that whole path, which is what your program does; `dig NAME` asks DNS directly and shows the record, the TTL, and which server answered; `dig +short` gives just the addresses, `dig -x ADDR` reverses, `dig @1.1.1.1 NAME` asks a different resolver to tell your resolver's fault from the record's. When `getent` and `dig` disagree, `/etc/hosts` has an override. Inside a container, `resolv.conf` points at Docker's embedded resolver (`127.0.0.11`), which is the second `LISTEN` row you have seen in every `ss` since lesson 02. Phase 2 lesson 06 builds the protocol; this is enough to diagnose it.

### nc and tcpdump: talk raw, and watch the wire

`nc` (netcat) is a socket with stdin and stdout attached (lesson 07): `nc -zv host port` probes, `nc host port` connects and lets you type the protocol by hand, `nc -l port` listens. Typing an HTTP request into `nc` is how you learn what `curl` really sends, and how you test a server when you suspect the client library. `tcpdump` is the other direction: it shows the packets themselves. `-i any` or `-i eth0` picks the interface, `-nn` skips name lookups, `-c N` stops after N packets, an expression like `tcp port 8082` or `host 10.0.0.5` filters, `-w file` saves a capture for Wireshark and `-r file` reads it back, `-A` prints payloads as text. A handshake and an HTTP request on loopback:

```console
$ tcpdump -i lo -nn -c 6 'tcp port 8082'
05:04:13.091109 IP 127.0.0.1.43958 > 127.0.0.1.8082: Flags [S], seq 3944020579, win 65495, ...
05:04:13.091127 IP 127.0.0.1.8082 > 127.0.0.1.43958: Flags [S.], seq 3049161847, ack 3944020580, ...
05:04:13.091134 IP 127.0.0.1.43958 > 127.0.0.1.8082: Flags [.], ack 1, win 64, ...
05:04:13.091188 IP 127.0.0.1.43958 > 127.0.0.1.8082: Flags [P.], seq 1:79, ack 1, ..., length 78
05:04:13.091190 IP 127.0.0.1.8082 > 127.0.0.1.43958: Flags [.], ack 79, ...
05:04:13.093127 IP 127.0.0.1.8082 > 127.0.0.1.43958: Flags [P.], seq 1:158, ack 79, ..., length 157
```

`[S]`, `[S.]`, `[.]`: `SYN`, `SYN-ACK`, `ACK`, 17 µs apart. Then 78 bytes of request (`[P.]`, push), an acknowledgement, and 157 bytes of response. When the layers disagree, this is the arbiter: a `SYN` that leaves with nothing returning is a drop; a `SYN` answered by `RST` is refused on the far side; a completed handshake followed by silence is an application that accepted and stalled.

### The firewall: drop versus reject

The kernel's packet filter is **netfilter**, configured today with `nftables` (`nft`), historically with `iptables`, and on Ubuntu usually through `ufw`, which writes the same rules with friendlier commands. A rule can `drop` a packet (silence: the client times out) or `reject` it (an `RST` or an ICMP error: the client is refused). On the booted `systemd` box from lesson 11, which has the capability to change rules, the same port under the two verbs:

```console
$ nft add table inet filter
$ nft add chain inet filter input '{ type filter hook input priority 0; policy accept; }'
$ nft add rule inet filter input tcp dport 9999 drop;  nft list ruleset
table inet filter {
        chain input {
                type filter hook input priority filter; policy accept;
                tcp dport 9999 drop
        }
}
$ nc -zv -w 2 127.0.0.1 9999
nc: connect to 127.0.0.1 port 9999 (tcp) timed out: Operation now in progress
$ nft flush chain inet filter input;  nft add rule inet filter input tcp dport 9999 reject;  nc -zv -w 2 127.0.0.1 9999
nc: connect to 127.0.0.1 port 9999 (tcp) failed: Connection refused
$ nft delete table inet filter;  nc -zv -w 2 127.0.0.1 9999
Connection to 127.0.0.1 9999 port [tcp/*] succeeded!
```

The service listened the whole time. Only the rule changed, and the client's error changed with it, from timeout to refused to success: that is why the firewall is layer 5 of the ladder and why its two verbs impersonate layers 3 and 4. The `ufw` form of a typical server policy is four lines: `ufw default deny incoming; ufw allow 22/tcp; ufw allow 80,443/tcp; ufw enable`, and the capstone (lesson 18) applies it. Cloud security groups are the same rules kept outside the box, checked in a different console, and almost always `drop`.

## Build It

The script for this lesson is [`code/netshell.py`](../code/netshell.py). It reads the tables the tools read, opens the sockets the tools open, and, in the sandbox where it is root, captures three packets off the loopback with a raw socket and decodes them by hand. On macOS the `/proc` sections say what they would read; the socket sections run everywhere:

```bash
python3 phases/01-linux-and-the-command-line/14-networking-from-the-shell/code/netshell.py
make shell   # then the same: all seven sections
```

**`ip route` from `/proc/net/route`**, where every address is little-endian hex, the same encoding lesson 02 met in `/proc/net/tcp`:

```python
def hex_ip(h):
    return socket.inet_ntoa(struct.pack("<I", int(h, 16)))    # little-endian hex -> dotted quad

for line in open("/proc/net/route").readlines()[1:]:
    f = line.split()
    iface, dest, gw, mask = f[0], f[1], f[2], f[7]
    out.append((hex_ip(dest), hex_ip(mask), hex_ip(gw), iface))
```

**`ss -p`** is lesson 02's `/proc/net/tcp` decoder plus one more idea: the socket's inode, matched against every process's descriptors, which is exactly why `ss -p` needs root to see other users' processes:

```python
def pid_for_socket_inode(inode):
    for pid in os.listdir("/proc"):
        if not pid.isdigit(): continue
        for fd in os.listdir(f"/proc/{pid}/fd"):
            if os.readlink(f"/proc/{pid}/fd/{fd}") == f"socket:[{inode}]":
                return int(pid)
```

**The port check** is a connect with a timeout and three `except` clauses, and it reproduces the three answers with three targets: our own listener, port 1 where nothing listens, and a documentation address that black-holes:

```console
   127.0.0.1:40761 (we listen)      -> open (0.2 ms to handshake)
   127.0.0.1:1 (nobody listens)      -> closed: connection refused (a host answered with RST: nothing is listening there)
   203.0.113.1:80 (a black hole)     -> filtered: timed out (no answer at all: a firewall dropped it, or the host is down)
```

**`EADDRINUSE` and `ECONNREFUSED`** are produced by binding the same port twice and by connecting after the listener closes: errno 98 and 111 on Linux, 48 and 61 on macOS, the same words. **The sniffer** opens an `AF_PACKET` socket bound to `lo`, skips the outgoing copy of each packet (loopback shows every packet twice), parses the Ethernet type, the IP header length and protocol, and the TCP ports, sequence numbers and flags:

```python
sport, dport, seq, ack, off_flags = struct.unpack("!HHIIH", tcp[:14])
flags = off_flags & 0x01FF
names = [n for bit, n in ((0x02, "SYN"), (0x10, "ACK"), (0x08, "PSH"), (0x01, "FIN"), (0x04, "RST")) if flags & bit]
```

```console
   127.0.0.1:40740 -> 127.0.0.1:44283  [SYN]  seq=4171967469  ack=0  len=0
   127.0.0.1:44283 -> 127.0.0.1:40740  [SYN,ACK]  seq=2877051061  ack=4171967470  len=0
   127.0.0.1:40740 -> 127.0.0.1:44283  [ACK]  seq=4171967470  ack=2877051062  len=0
```

The acknowledgement number is the other side's sequence number plus one, the handshake from Phase 2 lesson 05 read off the wire by forty lines of Python. `tcpdump` prints these same fields, with the header-decoding done by `libpcap` and RFC 791 and RFC 9293 for the layouts.

## Use It

The real tools inside `make shell`, layer by layer. The interface, its counters, and the route a packet would take:

```console
$ ip -s link show eth0 | tail -4
    RX:  bytes packets errors dropped  missed   mcast
           260       2      0       0       0       0
    TX:  bytes packets errors dropped carrier collsns
            42       1      0       0       0       0
$ ip route get 1.1.1.1
1.1.1.1 via 192.168.97.1 dev eth0 src 192.168.97.2 uid 0
```

A listener, a connection to it, the two `ss` rows for one connection, and the port held against a second bind:

```console
$ ss -tlnp
State  Recv-Q Send-Q Local Address:Port  Peer Address:Port Process
LISTEN 0      5            0.0.0.0:8080       0.0.0.0:*     users:(("python3",pid=13,fd=3))
LISTEN 0      4096      127.0.0.11:33833      0.0.0.0:*
$ ss -tan | grep 8080                              # while nc holds a connection open
LISTEN 1      5            0.0.0.0:8080       0.0.0.0:*
ESTAB  0      0          127.0.0.1:53180    127.0.0.1:8080
ESTAB  0      0          127.0.0.1:8080     127.0.0.1:53180
$ python3 -c 'import socket; socket.socket().bind(("0.0.0.0", 8081))'      # while another process listens on 8081
OSError: [Errno 98] Address already in use
$ ss -tlnp | grep 8081
LISTEN 0      5            0.0.0.0:8081       0.0.0.0:*     users:(("python3",pid=28,fd=3))
```

Note the `Recv-Q 1` on the `LISTEN` row while the connection waits: one completed handshake not yet accepted. Reachability and the path, then the name three ways, and where the resolver lives:

```console
$ ping -c 2 -W 1 deb.debian.org | tail -1
rtt min/avg/max/mdev = 57.901/64.589/71.278/6.688 ms
$ traceroute -n -m 4 -w 1 -q 1 deb.debian.org
 1  192.168.97.1  0.499 ms
 2  192.168.139.1  0.482 ms
 3  192.168.0.1  3.135 ms
 4  172.25.11.129  13.831 ms
$ grep '^hosts' /etc/nsswitch.conf;  grep nameserver /etc/resolv.conf
hosts:          files dns
nameserver 127.0.0.11
$ getent hosts deb.debian.org | head -1;  dig +short deb.debian.org | head -2
2a04:4e42::644  debian.map.fastlydns.net deb.debian.org
debian.map.fastlydns.net.
151.101.194.132
$ dig deb.debian.org A | grep -E 'IN\s+A' | head -2
debian.map.fastlydns.net. 67    IN      A       151.101.194.132
debian.map.fastlydns.net. 67    IN      A       151.101.2.132
```

`getent` returned the IPv6 address first (the box has a v6 route), `dig` shows the name is an alias (`CNAME`) resolved through a CDN, and the `67` is the TTL: how long the answer may be cached. `nc` as a client, as a probe, and as a raw HTTP client:

```console
$ nc -zv localhost 22
nc: connect to localhost (127.0.0.1) port 22 (tcp) failed: Connection refused
$ nc -zv localhost 9000                            # a Python server is listening
Connection to localhost (127.0.0.1) 9000 port [tcp/*] succeeded!
$ printf 'GET / HTTP/1.1\r\nHost: deb.debian.org\r\nConnection: close\r\n\r\n' | nc -w 3 deb.debian.org 80 | head -3
HTTP/1.1 200 OK
Connection: close
Content-Length: 1876
```

A capture written to a file and read back with the payload as text, the interface and TCP counters, and `curl` producing the three failure words of the ladder (lessons 15 and 16 own `curl`):

```console
$ tcpdump -i lo -nn -c 4 -w /tmp/cap.pcap 'tcp port 8082' &  curl -s -o /dev/null http://127.0.0.1:8082/;  wait
$ tcpdump -nn -r /tmp/cap.pcap -A | grep -aE 'GET /|Host:'
GET / HTTP/1.1
Host: 127.0.0.1:8082
$ nstat -az | grep -E 'TcpActiveOpens|TcpPassiveOpens|TcpRetransSegs|ListenOverflows|ListenDrops'
TcpActiveOpens                  2                  0.0
TcpPassiveOpens                 2                  0.0
TcpRetransSegs                  0                  0.0
TcpExtListenOverflows           0                  0.0
TcpExtListenDrops               0                  0.0
$ curl -sS -o /dev/null -w 'http %{http_code} in %{time_total}s via %{remote_ip}\n' http://deb.debian.org/
http 200 in 0.172553s via 151.101.66.132
$ curl -sS -o /dev/null http://127.0.0.1:1/;  curl -sS -m 2 -o /dev/null http://203.0.113.1/
curl: (7) Failed to connect to 127.0.0.1 port 1 after 0 ms: Could not connect to server
curl: (28) Connection timed out after 2007 milliseconds
```

Two active opens, two passive opens, zero retransmits, zero listen drops: a quiet box. On a busy one, `TcpRetransSegs` climbing is loss on the path and `ListenOverflows` climbing is the accept queue from the second diagram. The firewall demo lives on the `systemd` box, above.

## Ship It

The artifact for this lesson is a runbook: [`outputs/runbook-cannot-connect.md`](../outputs/runbook-cannot-connect.md). It starts by mapping the literal error to a layer, then walks the ladder with the command at each rung and what each answer means: the name (`getent` versus `dig`, `nsswitch`, a dead resolver, IPv6 fallback), the route (`ip route get`, the interface), reachability (`ping`, `traceroute`, and the `nc` probe whose three answers decide the next step), the port from the server's side (`ss -tlnp`, loopback-only binds, `EADDRINUSE`, a full accept queue), the firewall at both ends and in between (drop versus reject, the cloud console), the protocol (`curl -v`, `openssl s_client`, `--resolve`), and `tcpdump` as the arbiter when layers disagree. It ends with how to write the answer: a layer and a fact.

## Think about it

1. A client reports `Connection timed out` to your API. From the API box, `ss -tlnp` shows it listening on `0.0.0.0:8443` and `nc -zv 127.0.0.1 8443` succeeds. Name the two most likely layers, the command for each, and why the error word rules out "the service is down."
2. `getent hosts db.internal` returns `10.0.0.5` but `dig +short db.internal` returns `10.0.0.9`. What is happening, which file, and which of the two does your application use?
3. After a deploy, the new copy of a service fails to start with `EADDRINUSE`, yet `systemctl status` says the old copy is stopped. Give two explanations from lesson 10 and the `ss` flag that distinguishes them.
4. `tcpdump` on the client shows `SYN`, `SYN-ACK`, `ACK`, then a `GET`, then nothing for 30 seconds, then the client's `FIN`. Which layer of the ladder is fine, which is not, and which lesson-12 questions do you ask on the server?

## Key takeaways

- A connection passes **five layers** in order: name, route, reachability, port, firewall, then the protocol. The error names the first that said no; ask them in that order.
- `ip -br addr`, `ip -s link`, `ip route`, **`ip route get ADDR`** read `/sys/class/net` and `/proc/net/route`. No route means `unreachable` before any packet leaves.
- **`ss -tlnp`** reads `/proc/net/tcp` and finds the PID through `/proc/*/fd`. On a `LISTEN` row `Recv-Q` is the accept backlog in use and `Send-Q` its capacity; on an `ESTAB` row they are unread and unacknowledged bytes. A `127.0.0.1` bind is invisible from outside.
- **Refused** (`RST`) means a host is there and nothing listens, or a `reject` rule; **timed out** means nothing answered, a down host or a `drop` rule; **unreachable** means no route. **`nc -zv`** tells them apart in a second.
- `getent hosts` follows `nsswitch.conf` (`/etc/hosts`, then the resolvers in `resolv.conf`); `dig` asks DNS directly and shows the record and TTL; when they disagree, `/etc/hosts` is why.
- **`nc`** talks any TCP protocol by hand; **`tcpdump -i any -nn 'port N'`** shows the packets, and a `SYN` with no answer, a `SYN` met by `RST`, or a handshake followed by silence each settle a different argument.
- The firewall (**`nft`**, `ufw`, cloud security groups) impersonates layers 3 and 4 depending on `drop` or `reject`; test from inside the box, then the subnet, then outside, and check `nstat` for retransmits and listen drops.

Next: [curl, Part 1: Requests, Headers, Bodies, Auth, Files & Cookies](../15-curl-part-1-requests/). The connection works. Now the tool you will use every day to talk HTTP by hand, a mini `curl` built on `http.client` that prints what really goes on the wire, and the thirty options that cover most of what you need.
