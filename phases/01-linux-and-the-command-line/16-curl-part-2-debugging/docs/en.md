# curl, Part 2: Debugging with -v, --trace, -w Timing, --resolve, TLS & Retries

> One HTTP request is five waits in a row: resolve the name, shake hands with TCP, shake hands with TLS, wait for the server's first byte, receive the rest. `curl -w` reads a stopwatch at each boundary, and this lesson rebuilds that stopwatch with a raw socket so the numbers stop being magic: against a real site, DNS **1.3 ms**, TCP **44 ms**, TLS **51 ms**, the server **90 ms**, the transfer **0.1 ms**. Then the tools for when a request is slow or wrong: `--trace-ascii` for the bytes, `--resolve` to reach a server DNS does not know, the meaning of exit **60**, **51**, **35** and **28**, `--compressed`, and the timeout and retry flags without which a script can hang forever and report success.

## The Problem

Lesson 15 made curl send anything. This lesson is about what comes back, and how long it took, and why. "The API is slow" is not a diagnosis; "the server took 400 ms to send its first byte" is, and so is "TLS is costing 125 ms on every request because nothing reuses the connection." "It fails with a certificate error" is not a diagnosis either; exit 60 (this box does not trust the CA) and exit 51 (the name does not match) have different fixes. And a script that calls an API needs to bound its waiting, retry the right failures, and fail honestly, which takes four flags most scripts do not have.

curl can answer all of that alone, without a browser, without an APM tool, from the box where the problem is. It has stopwatches, a byte-level trace, a way to dial any address while keeping the hostname, and a verified TLS stack that tells you exactly why it refused. This lesson is those four powers, in the order you reach for them.

## The Concept

### The five waits, and the stopwatch at each

A request over HTTPS pays five costs in sequence, and every tool that measures HTTP, curl included, reads a clock at the boundary between each:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 430" width="100%" style="max-width:880px" font-family="'JetBrains Mono', ui-monospace, monospace" role="img" aria-label="A timeline of one HTTPS request from left to right with five segments and the curl -w stopwatch variable at each boundary. Segment one, DNS: from the start to time_namelookup; the resolver answers; 1.3 milliseconds here, 0 when cached or when --resolve supplies the address. Segment two, TCP: to time_connect; SYN, SYN-ACK, ACK, one round trip; 44 milliseconds here, so the round trip to this server is about 44 milliseconds. Segment three, TLS: to time_appconnect; ClientHello, ServerHello, certificate, keys, one to two round trips plus crypto; 51 milliseconds here; zero on a reused connection. A marker, time_pretransfer, when the request bytes have been written. Segment four, the server: to time_starttransfer, the first byte of the response; 90 milliseconds here; this is the application's think time, the part you own. Segment five, transfer: to time_total; the body over the bandwidth; 0.1 milliseconds for 2.5 kilobytes. Below: the variables are cumulative, subtract neighbours to get a step; compare TCP with ping and TLS with two pings; the server segment is what lesson 12 diagnoses on the far box.">
  <defs>
    <marker id="p1l16a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">One HTTPS request as five waits, with curl's stopwatch reading at each boundary</text>
  <path d="M40 120 L860 120" fill="none" stroke="currentColor" stroke-width="2" marker-end="url(#p1l16a-ar)"/>
  <g stroke-linejoin="round" stroke-width="1.5">
    <rect x="40"  y="96" width="60"  height="48" rx="6" fill="#7c5cff" fill-opacity="0.25" stroke="#7c5cff"/>
    <rect x="100" y="96" width="150" height="48" rx="6" fill="#7f7f7f" fill-opacity="0.22" stroke="#7f7f7f"/>
    <rect x="250" y="96" width="170" height="48" rx="6" fill="#e0930f" fill-opacity="0.22" stroke="#e0930f"/>
    <rect x="420" y="96" width="300" height="48" rx="6" fill="#c94a12" fill-opacity="0.22" stroke="#c94a12"/>
    <rect x="720" y="96" width="120" height="48" rx="6" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f"/>
  </g>
  <g text-anchor="middle" font-size="9" font-weight="700" fill="currentColor">
    <text x="70" y="124">DNS</text>
    <text x="175" y="124">TCP handshake</text>
    <text x="335" y="124">TLS handshake</text>
    <text x="570" y="124">the server thinks</text>
    <text x="780" y="124">transfer</text>
  </g>
  <g font-size="8" fill="currentColor" text-anchor="middle">
    <text x="70" y="160">1.3 ms</text>
    <text x="175" y="160">44 ms · one round trip</text>
    <text x="335" y="160">51 ms · 1 to 2 round trips + crypto</text>
    <text x="570" y="160">90 ms · request in, first byte out</text>
    <text x="780" y="160">0.1 ms · 2.5 KB</text>
  </g>
  <!-- boundary labels -->
  <g font-size="8.5" fill="currentColor">
    <text x="100" y="82" text-anchor="middle">time_namelookup</text>
    <text x="250" y="82" text-anchor="middle">time_connect</text>
    <text x="420" y="82" text-anchor="middle">time_appconnect</text>
    <text x="428" y="66" text-anchor="middle" opacity="0.7">time_pretransfer (request written)</text>
    <text x="720" y="82" text-anchor="middle">time_starttransfer</text>
    <text x="840" y="82" text-anchor="middle">time_total</text>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.2" stroke-dasharray="3 3">
    <path d="M100 86 L100 96"/><path d="M250 86 L250 96"/><path d="M420 86 L420 96"/><path d="M720 86 L720 96"/><path d="M840 86 L840 96"/>
  </g>
  <g stroke-linejoin="round" stroke-width="1.5">
    <rect x="40"  y="190" width="160" height="110" rx="9" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff"/>
    <rect x="215" y="190" width="160" height="110" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f"/>
    <rect x="390" y="190" width="160" height="110" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
    <rect x="565" y="190" width="160" height="110" rx="9" fill="#c94a12" fill-opacity="0.10" stroke="#c94a12"/>
    <rect x="740" y="190" width="120" height="110" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
  </g>
  <g font-size="8" fill="currentColor" text-anchor="middle">
    <text x="120" y="208" font-weight="700">slow DNS means</text>
    <text x="120" y="224">a dead or far resolver,</text>
    <text x="120" y="238">many records, no cache</text>
    <text x="120" y="256">0 when --resolve</text>
    <text x="120" y="270">supplies the address, or</text>
    <text x="120" y="284">on the 2nd request (cached)</text>
    <text x="295" y="208" font-weight="700">slow TCP means</text>
    <text x="295" y="224">distance (compare ping)</text>
    <text x="295" y="238">or loss: retransmits</text>
    <text x="295" y="256">0.1 ms loopback</text>
    <text x="295" y="270">1 ms a data centre</text>
    <text x="295" y="284">60+ ms a continent</text>
    <text x="470" y="208" font-weight="700">slow TLS means</text>
    <text x="470" y="224">distance ×2, slow crypto,</text>
    <text x="470" y="238">an OCSP fetch, a huge chain</text>
    <text x="470" y="256">0 on a reused connection</text>
    <text x="470" y="270">(keep-alive, HTTP/2):</text>
    <text x="470" y="284">Phase 2, lesson 14</text>
    <text x="645" y="208" font-weight="700">slow server means</text>
    <text x="645" y="224">the application: a query,</text>
    <text x="645" y="238">a downstream call, a lock</text>
    <text x="645" y="256">the part you own;</text>
    <text x="645" y="270">lesson 12 on that box,</text>
    <text x="645" y="284">Phase 9 for the profiling</text>
    <text x="800" y="208" font-weight="700">slow transfer</text>
    <text x="800" y="224">body / bandwidth</text>
    <text x="800" y="238">--compressed,</text>
    <text x="800" y="256">smaller responses,</text>
    <text x="800" y="270">pagination</text>
    <text x="800" y="284">(Phase 3)</text>
  </g>
  <text x="450" y="336" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">The -w variables are cumulative from the start: subtract neighbours to get one step. That subtraction is the whole diagnosis.</text>
  <text x="450" y="356" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">TCP ≈ one ping. TLS ≈ two. Anything much bigger is loss (nstat, lesson 14) or an endpoint doing something slow.</text>
  <text x="450" y="386" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">A request that skips steps, because a connection is reused, pays only the server and transfer segments: that is why connection pooling exists.</text>
  <text x="450" y="410" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">Measured here with a raw socket in Python and with curl -w on the same host; the two agree to within a millisecond.</text>
</svg>
```

`-w` (`--write-out`) prints variables after the transfer: `time_namelookup`, `time_connect`, `time_appconnect`, `time_pretransfer`, `time_starttransfer`, `time_total`, plus `http_code`, `size_download`, `remote_ip`, `http_version`, `num_connects`, `num_redirects`, `num_retries`, and `%{json}` for all of them at once. The times are **cumulative** from the start, so a step is the difference between neighbours, and the step that is large is the answer. Against the local echo server's `/slow?ms=400` route, everything is zero except the server:

```console
$ curl -s -o /dev/null -w 'dns %{time_namelookup}s  tcp %{time_connect}s  tls %{time_appconnect}s  ttfb %{time_starttransfer}s  total %{time_total}s\n' "http://127.0.0.1:8089/slow?ms=400"
dns 0.000008s  tcp 0.000136s  tls 0.000000s  ttfb 0.405481s  total 0.405513s
```

Against a real site over HTTPS, all five cost something, and two requests in one `curl` invocation show what caching and connection reuse remove:

```console
$ curl -s -o /dev/null -w "$W" https://deb.debian.org/
dns 0.064598s  tcp 0.114570s  tls 0.167771s  ttfb 0.266305s  total 0.266341s  status 200  size 1876B  v 2
$ curl -s -o /dev/null -o /dev/null -w "$W" https://deb.debian.org/ https://deb.debian.org/robots.txt
dns 0.001904s  tcp 0.046884s  tls 0.096248s  ttfb 0.185896s  total 0.185936s  status 200  size 1876B  v 2
dns 0.000000s  tcp 0.000000s  tls 0.000000s  ttfb 0.447072s  total 0.447120s  status 404  size 300B   v 2
```

The second URL paid nothing for DNS, TCP or TLS: same connection, reused. That is the entire argument for keep-alive and HTTP/2 (Phase 2 lesson 14), visible in three zeros.

### --trace: the bytes, with timestamps

`-v` shows headers. `--trace-ascii -` shows every byte in both directions, with offsets, including the body, and `--trace-time` stamps each line so that a stall *inside* the exchange is visible:

```console
$ curl -s --trace-ascii - http://127.0.0.1:8089/json | head -12
== Info:   Trying 127.0.0.1:8089...
== Info: Connected to 127.0.0.1 (127.0.0.1) port 8089
=> Send header, 82 bytes (0x52)
0000: GET /json HTTP/1.1
0014: Host: 127.0.0.1:8089
002a: User-Agent: curl/8.14.1
0043: Accept: */*
0050:
== Info: Request completely sent off
<= Recv header, 17 bytes (0x11)
0000: HTTP/1.1 200 OK
```

Eighty-two bytes went out, and you can count them. When a server misbehaves on a request that "looks fine," the trace is the arbiter, exactly as `tcpdump` was in lesson 14 one layer down; `--trace` (without `-ascii`) adds the hex.

### --resolve: dial the address you choose, keep the name

DNS says `api.example.com` is one address; you want to test another: a new server before the record changes, one backend behind a load balancer, a canary. `-H 'Host: ...'` against a raw IP works for plain HTTP, but over HTTPS the TLS handshake also carries the name (**SNI**, RFC 6066) and the certificate must match it, so a raw IP fails the certificate check. `--resolve host:port:address` fixes exactly that: curl dials the address you give and keeps the hostname everywhere it belongs:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 340" width="100%" style="max-width:880px" font-family="'JetBrains Mono', ui-monospace, monospace" role="img" aria-label="Three ways to reach a server other than what DNS says, and what each keeps. Normal: curl resolves api.example.com through DNS and connects wherever that points, with Host and SNI set to api.example.com. --resolve api.example.com colon 443 colon 10.0.0.7: no DNS lookup, connect to 10.0.0.7, Host and SNI still api.example.com, so the certificate check passes; used for testing one backend, a canary, or a server before the DNS change. -H Host: api.example.com against http colon slash slash 10.0.0.7: works for plain HTTP because only the Host header matters; over HTTPS the SNI would be the IP and the certificate would not match, exit 51. --connect-to api.example.com colon 443 colon canary.internal colon 8443: connect to a different host and port entirely, still presenting api.example.com; the most general form. A footnote: the same address with the wrong name fails with exit 60 no alternative certificate subject name matches, which is the certificate doing its job.">
  <defs>
    <marker id="p1l16b-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Reaching a server DNS does not point at, without breaking the name the certificate needs</text>
  <g stroke-linejoin="round" stroke-width="1.6">
    <rect x="30"  y="50" width="270" height="200" rx="10" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
    <rect x="315" y="50" width="270" height="200" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="2"/>
    <rect x="600" y="50" width="270" height="200" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
  </g>
  <g text-anchor="middle" font-size="10" font-weight="700">
    <text x="165" y="72" fill="currentColor">NORMAL</text>
    <text x="450" y="72" fill="#0fa07f">--resolve host:port:addr</text>
    <text x="735" y="72" fill="#e0930f">-H 'Host: ...' against an IP</text>
  </g>
  <g font-size="8.5" fill="currentColor">
    <text x="46" y="98">curl https://api.example.com/</text>
    <text x="46" y="120">DNS   → 203.0.113.10 (whatever it says)</text>
    <text x="46" y="136">TCP   → 203.0.113.10:443</text>
    <text x="46" y="152">SNI   = api.example.com</text>
    <text x="46" y="168">Host: api.example.com</text>
    <text x="46" y="184">cert  must cover api.example.com ✓</text>
    <text x="46" y="212" opacity="0.8">you get whichever backend DNS</text>
    <text x="46" y="226" opacity="0.8">and the load balancer choose</text>
    <text x="331" y="98">curl --resolve api.example.com:443:10.0.0.7 \</text>
    <text x="331" y="110">     https://api.example.com/</text>
    <text x="331" y="130">DNS   → skipped (namelookup 0.0 ms)</text>
    <text x="331" y="146">TCP   → 10.0.0.7:443  (your choice)</text>
    <text x="331" y="162">SNI   = api.example.com</text>
    <text x="331" y="178">Host: api.example.com</text>
    <text x="331" y="194">cert  must cover api.example.com ✓</text>
    <text x="331" y="216" opacity="0.8">one backend, a canary, a new box</text>
    <text x="331" y="230" opacity="0.8">before DNS changes; --connect-to for a</text>
    <text x="331" y="244" opacity="0.8">different host AND port</text>
    <text x="616" y="98">curl -H 'Host: api.example.com' \</text>
    <text x="616" y="110">     http://10.0.0.7/</text>
    <text x="616" y="130">plain HTTP: only the Host header</text>
    <text x="616" y="146">matters, so this works (status 200)</text>
    <text x="616" y="170">over HTTPS it would not:</text>
    <text x="616" y="186">SNI = 10.0.0.7, cert says the name,</text>
    <text x="616" y="202">exit 51: no alternative certificate</text>
    <text x="616" y="218">subject name matches target ipv4</text>
    <text x="616" y="240" opacity="0.8">-k would hide it; --resolve fixes it</text>
  </g>
  <text x="450" y="284" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">The name is sent twice: in the TLS ClientHello (SNI) and in the Host header. --resolve keeps both and changes only where the packets go.</text>
  <text x="450" y="306" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">The same address with the wrong name is refused (exit 60 or 51): the certificate doing its job, and the proof that the check is real.</text>
  <text x="450" y="326" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">"Works with --resolve to backend 3, fails through the name" is a sentence that ends an incident's first hour.</text>
</svg>
```

`--connect-to host:port:otherhost:otherport` is the general form (a different host *and* port, still presenting the original name). The **Build It** script does the same thing by hand: dial an address, wrap the socket with `server_hostname` set to the real name, and the certificate check passes while `time_namelookup` reads zero.

### TLS: what the exit codes mean

curl verifies certificates by default, and its refusals are precise. **60** means the chain does not end in a certificate this box trusts: a self-signed certificate, an internal CA the box has not been told about, or a public server sending an incomplete chain (a missing intermediate, which browsers repair silently and curl does not). `--cacert file.pem` trusts a CA for one call; installing it into the system store (`/usr/local/share/ca-certificates/` and `update-ca-certificates` on Debian) trusts it for every program. **51** means the certificate is valid but not for *this name*: you dialled by IP, or the name is not in the certificate's `subjectAltName` list; `--resolve` keeps the right name, `-k` hides the problem. **35** means the handshake itself failed: a TLS version or cipher one side does not support, or TLS spoken to a plain-HTTP port. **28** is a timeout, which is not TLS at all.

`-k` (`--insecure`) skips verification. It is for finding out what a certificate *is* while you diagnose; a script with `-k` has no TLS, because anyone on the path can present any certificate. `openssl s_client -connect host:443 -servername host` shows the certificate the server presents, its issuer, and the verify result, independent of curl. The **Use It** section builds a self-signed server and produces 60, then 51, then success with `--cacert`.

### Timeouts and retries: the four flags a script must have

curl waits forever by default. `--connect-timeout N` bounds the DNS, TCP and TLS steps; `--max-time N` bounds the whole request; both exit **28**. `--retry N` retries transient failures (connection errors, timeouts, `408`, `429`, `500`, `502`, `503`, `504`) with delays that double from `--retry-delay`; `--retry-all-errors` retries anything, which is unsafe for a `POST` that may have half-succeeded (Phase 3 lesson 07 on idempotency); `--retry-max-time` caps the total; `%{num_retries}` reports what happened. And `-f` turns a final `4xx`/`5xx` into exit 22 (`--fail-with-body` keeps the body for the log). The **Build It** script implements the retry loop so you can see how little it is, and why the exit code at the end matters more than the retries.

### Versions and compression

`%{http_version}` shows `2` against a server that supports HTTP/2 and `1.1` with `--http1.1`; `--http2` and `--http3` force them (Phase 2 lesson 11). `--compressed` sends `Accept-Encoding: gzip, br, zstd` and decodes the answer: the echo server's `/gzip` route is 3,600 bytes plain and 64 bytes on the wire with it, which is the transfer segment shrinking by fifty times for one flag. A proxy is `-x http://proxy:3128` or the `http_proxy`/`https_proxy`/`no_proxy` environment variables, which curl honours silently and which explain many "works for me" mysteries; `--noproxy '*'` proves it.

## Build It

The script for this lesson is [`code/timing.py`](../code/timing.py). It takes the five stopwatch readings with a raw socket, prints them cumulative (as `-w` would) and per step, implements `--resolve` and `--retry`, and needs lesson 15's echo server for the local parts. It runs on macOS and Linux:

```bash
python3 phases/01-linux-and-the-command-line/15-curl-part-1-requests/code/echo_server.py &
python3 phases/01-linux-and-the-command-line/16-curl-part-2-debugging/code/timing.py
```

**The stopwatch** is `time.perf_counter()` read after each syscall that ends a step. There is nothing else to it:

```python
addr = resolve_to or socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
t["namelookup"] = time.perf_counter() - t0                   # DNS done
sock = socket.create_connection((addr, port), timeout=timeout)
t["connect"] = time.perf_counter() - t0                      # TCP handshake done
if u.scheme == "https":
    sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)   # SNI = the hostname
    t["appconnect"] = time.perf_counter() - t0               # TLS handshake done
sock.sendall(req.encode())
t["pretransfer"] = time.perf_counter() - t0                  # request written
first = sock.recv(1)
t["starttransfer"] = time.perf_counter() - t0                # first byte: the server's think time ends here
```

Run in the sandbox, the three local requests put the time in three different places, and the real request shows all five costs:

```console
   GET /slow?ms=400: the server thinks for 400 ms before its first byte
   per step:              DNS 0.0  TCP 0.0  TLS 0.0  server 405.5  transfer 0.0 ms
   the time went to: server (100% of the total)

   GET /big?kb=4096: 4 MiB of body, so the transfer step dominates
   per step:              DNS 0.0  TCP 0.0  TLS 0.0  server 0.8  transfer 8.9 ms
   the time went to: transfer (91% of the total)

   GET https://deb.debian.org/
   HTTP/1.1 200 OK   2,503 bytes   via 151.101.66.132   tls TLSv1.3 TLS_AES_128_GCM_SHA256
   cumulative (curl -w):  namelookup      1.3  connect     45.4  appconnect     96.2  starttransfer    186.4  total    186.5 ms
   per step:              DNS 1.3  TCP 44.2  TLS 50.7  server 90.1  transfer 0.1 ms
```

TCP at 44 ms is one round trip to that server; TLS at 51 ms is one more round trip plus the crypto, which is what TLS 1.3's single-round-trip handshake buys (RFC 8446). **`--resolve`** is the same function with `resolve_to` set, and the certificate check still passes because `server_hostname` carries the real name:

```console
   dialled 151.101.66.132 directly (namelookup 0.0 ms: no DNS at all), SNI/Host still deb.debian.org -> HTTP/1.1 200 OK, TLSv1.3 TLS_AES_128_GCM_SHA256
```

**`--retry`** is a loop with a doubling delay and two exit codes, 7 for "never connected" and 22 for "the server kept saying no":

```console
   against /status/503 (a server that says 'later'):
   attempt 1: HTTP/1.1 503 Service Unavailable; retrying in 0.2s
   attempt 2: HTTP/1.1 503 Service Unavailable; retrying in 0.4s
   attempt 3: HTTP/1.1 503 Service Unavailable; retrying in 0.8s
   attempt 4: HTTP/1.1 503 Service Unavailable  -> giving up: exit 22 (curl -f)
```

## Use It

Real curl, inside `make shell`, with the echo server running. The stopwatch as `-w`, as a format file, and as JSON for `jq`:

```console
$ W='dns %{time_namelookup}s  tcp %{time_connect}s  tls %{time_appconnect}s  ttfb %{time_starttransfer}s  total %{time_total}s  status %{http_code}\n'
$ curl -s -o /dev/null -w "$W" http://127.0.0.1:8089/json
dns 0.000026s  tcp 0.000110s  tls 0.000000s  ttfb 0.000738s  total 0.000760s  status 200
$ curl -s -o /dev/null -w '%{json}' http://127.0.0.1:8089/json | jq '{http_code, time_total, time_starttransfer, num_connects}'
{
  "http_code": 200,
  "time_total": 0.000298,
  "time_starttransfer": 0.000286,
  "num_connects": 1
}
```

`--trace-time` with `-v`, which timestamps the headers as they cross:

```console
$ curl -s --trace-time -v http://127.0.0.1:8089/json -o /dev/null 2>&1 | grep -E '^[0-9:.]+ (\*|>|<)' | head -3
05:14:02.481133 *   Trying 127.0.0.1:8089...
05:14:02.481469 * Connected to 127.0.0.1 (127.0.0.1) port 8089
05:14:02.481533 > GET /json HTTP/1.1
```

`--resolve` to one address of a CDN's many, `--connect-to`, a `Host` header over plain HTTP, and the same address under the wrong name:

```console
$ curl -sv --resolve deb.debian.org:443:167.82.58.132 https://deb.debian.org/ -o /dev/null -w 'via %{remote_ip} status %{http_code}\n' 2>&1 | grep -E 'Added|subjectAltName|^via'
* Added deb.debian.org:443:167.82.58.132 to DNS cache
*  subjectAltName: host "deb.debian.org" matched cert's "deb.debian.org"
via 167.82.58.132 status 200
$ curl -sS --resolve wrong.example.com:443:167.82.58.132 https://wrong.example.com/ -o /dev/null
curl: (60) SSL: no alternative certificate subject name matches target hostname 'wrong.example.com'
$ curl -s -o /dev/null -w 'via %{remote_ip} status %{http_code}\n' --connect-to deb.debian.org:443:151.101.2.132:443 https://deb.debian.org/
via 151.101.2.132 status 200
$ curl -s -H 'Host: deb.debian.org' -o /dev/null -w 'status %{http_code}\n' http://151.101.130.132/
status 200
```

TLS, with a self-signed certificate made on the spot and served by a ten-line Python server: the refusal, the by-name fix, the by-IP refusal, and the bypass:

```console
$ openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -keyout key.pem -out cert.pem -days 1 -subj '/CN=localhost' -addext 'subjectAltName=DNS:localhost'
$ curl -sS https://localhost:8443/ -o /dev/null;  echo "exit $?"
curl: (60) SSL certificate problem: self-signed certificate
More details here: https://curl.se/docs/sslcerts.html
exit 60
$ curl -s --cacert cert.pem https://localhost:8443/ -o /dev/null -w 'with --cacert: status %{http_code}\n'
with --cacert: status 200
$ curl -sS --cacert cert.pem https://127.0.0.1:8443/ -o /dev/null;  echo "exit $?"
curl: (60) SSL: no alternative certificate subject name matches target ipv4 address '127.0.0.1'
exit 60
$ curl -sk https://localhost:8443/ -o /dev/null -w 'with -k: status %{http_code}\n'
with -k: status 200
$ echo | openssl s_client -connect localhost:8443 -servername localhost 2>/dev/null | grep -E 'subject=|issuer=|Verify return|Protocol'
subject=CN=localhost
issuer=CN=localhost
Protocol: TLSv1.3
Verify return code: 18 (self-signed certificate)
$ echo | openssl s_client -connect deb.debian.org:443 -servername deb.debian.org 2>/dev/null | grep -E 'issuer=|Verify return'
issuer=C=US, O=Let's Encrypt, CN=YR2
Verify return code: 0 (ok)
```

Timeouts, both kinds, and retries with the count they report:

```console
$ time curl -s -m 1 'http://127.0.0.1:8089/slow?ms=3000' -o /dev/null;  echo "exit $?"
real    0m1.006s
exit 28
$ time curl -s --connect-timeout 1 http://203.0.113.1/ -o /dev/null;  echo "exit $?"
real    0m1.004s
exit 28
$ curl -s --retry 3 --retry-delay 1 -w 'status %{http_code} attempts %{num_retries}\n' -o /dev/null http://127.0.0.1:8089/status/503
status 503 attempts 3
$ curl -sf --retry 2 --retry-delay 1 -o /dev/null http://127.0.0.1:8089/status/503;  echo "with -f: exit $?"
with -f: exit 22
$ time curl -s --retry 2 --retry-delay 1 --retry-all-errors -o /dev/null http://127.0.0.1:1/;  echo "refused, retried: exit $?"
real    0m2.013s
refused, retried: exit 7
```

Versions and compression, one flag each:

```console
$ curl -s -o /dev/null -w '%{http_version}\n' https://deb.debian.org/;  curl -s --http1.1 -o /dev/null -w '%{http_version}\n' https://deb.debian.org/
2
1.1
$ curl -sv --compressed http://127.0.0.1:8089/gzip -o /dev/null 2>&1 | grep -E '^(> Accept-Encoding|< Content-Encoding|< Content-Length)'
> Accept-Encoding: deflate, gzip, br, zstd
< Content-Length: 64
< Content-Encoding: gzip
$ curl -s http://127.0.0.1:8089/gzip -o /dev/null -w 'without: %{size_download}B\n';  curl -s --compressed http://127.0.0.1:8089/gzip -o /dev/null -w 'with --compressed: %{size_download}B on the wire\n'
without: 3600B
with --compressed: 64B on the wire
```

## Ship It

The artifact for this lesson is a runbook: [`outputs/runbook-slow-or-failing-request.md`](../outputs/runbook-slow-or-failing-request.md). Slow: the `-w` line, the table of the five steps with what each means when it is large, and the comparisons with `ping`. Failing: the exit-code table (6, 7, 28, 35, 51, 52, 55, 60, 22, 18) with the next step for each. Where you run it: `--resolve`, `--connect-to`, `-4`/`-6`, `--interface`, `--noproxy`. TLS: `-v`'s certificate lines, `openssl s_client`, `--cacert`, the meaning of 60 and 51, the clock. And the script form: `-sSf --connect-timeout --max-time --retry --retry-delay --retry-max-time`, with the idempotency warning and the `-w` line to log on failure.

## Think about it

1. A request to a payments API shows `tcp 0.002 tls 0.190 ttfb 0.210 total 0.211` on every call from your service. Which step is expensive, why is it paid every time, and which Phase 2 lesson's mechanism removes it?
2. `curl https://api.internal/` fails with exit 60 from the new server and works from the old one. Both have the same application. List three differences between the boxes that would produce exactly that, and the command on each that confirms it.
3. A deploy script runs `curl -X POST https://api/orders --retry 5 --retry-all-errors`. Describe the incident this causes during a 502 storm at the load balancer, and rewrite the line so it is safe.
4. `--resolve api.example.com:443:10.0.0.7` returns 200 while `curl https://api.example.com/` returns 502 intermittently. What have you learned, what is the next `--resolve` to run, and what would `%{remote_ip}` tell you without any `--resolve`?

## Key takeaways

- One request is **five waits**: DNS, TCP, TLS, server, transfer. `-w`'s `time_*` variables are **cumulative stopwatch readings**; subtract neighbours, and the large step is the diagnosis. TCP is about one ping, TLS about two, the server segment is the application, and a reused connection skips the first three.
- `--trace-ascii -` shows every byte; `--trace-time -v` timestamps the exchange, exposing stalls inside it.
- **`--resolve host:port:addr`** dials an address of your choice while keeping the hostname in both SNI and `Host`, so certificates still verify; `--connect-to` changes host and port; `-H 'Host:'` alone works only for plain HTTP.
- TLS exit codes are precise: **60** untrusted chain (`--cacert`, or install the CA), **51** name mismatch (dial by name, not IP), **35** handshake failure (version, cipher, or the wrong port), **28** a timeout. `-k` is for looking, never for scripts. `openssl s_client` shows the certificate independently.
- A script needs **`--connect-timeout`, `--max-time`, `--retry` with `--retry-delay`, and `-f`**; `--retry-all-errors` is unsafe for non-idempotent requests; `%{num_retries}` and the `-w` line belong in the log.
- `%{http_version}` and `--http1.1`/`--http2` pick the protocol; `--compressed` shrinks the transfer by asking for gzip; proxy environment variables change requests silently and `--noproxy '*'` proves it.

Next: [SSH: Keys, Agents, Tunnels, scp & rsync](../17-ssh-keys-tunnels-and-rsync/). You can debug a request from any box. Now the way you reach the box at all: what SSH protects, shown by building the plaintext remote shell it replaced, then keys, agents, the config file, tunnels to a database, and moving files with `scp` and `rsync`.
