---
name: runbook-slow-or-failing-request
description: Diagnosing one HTTP request with curl alone — the -w timing variables and which of the five steps (DNS, TCP, TLS, server, transfer) is eating the time, --trace for the bytes, --resolve to take DNS and the load balancer out of the picture, the TLS error codes and what each means, and the timeout and retry flags a script must have
phase: 01
lesson: 16
---

# One request: slow, or failing

curl can measure every step of a request and show every byte of it. This
runbook is the order to use those powers in. Section 1 for "slow",
section 2 for "failing", section 3 for "it depends where I run it",
section 4 for TLS, section 5 for scripts.

## 1 · Slow: which of the five steps?

```bash
W='dns %{time_namelookup}  tcp %{time_connect}  tls %{time_appconnect}  ttfb %{time_starttransfer}  total %{time_total}  status %{http_code}  size %{size_download}\n'
curl -s -o /dev/null -w "$W" https://api.example.com/health
for i in 1 2 3 4 5; do curl -s -o /dev/null -w "$W" https://api.example.com/health; done   # five samples: one is noise
```

The variables are cumulative stopwatch readings from the start. Subtract neighbours to get the step:

| step | how long it took | slow means |
|---|---|---|
| DNS | `time_namelookup` | the resolver: a dead server in `resolv.conf`, a slow upstream, a name with many records; `dig +stats` and lesson 14. Usually 0 on the second request in a process (cached) |
| TCP | `time_connect` − `time_namelookup` | distance and packet loss: one round trip. 0.2 ms on loopback, 1 ms in a data centre, 60 ms across a continent, 300+ across the world or over a VPN. Much more than the ping time means retransmits (`nstat`, lesson 14) |
| TLS | `time_appconnect` − `time_connect` | one to two more round trips plus crypto. Large on a slow link; enormous when the server does an OCSP fetch or the client has a huge CA bundle; zero on a reused connection (HTTP/2, keep-alive; Phase 2 lesson 14) |
| server | `time_starttransfer` − `time_pretransfer` | **the application**: the time from the last request byte to the first response byte. This is the one you own: the database query, the downstream call, the lock. Lesson 12 on the server |
| transfer | `time_total` − `time_starttransfer` | body size over bandwidth; `--compressed` if the server supports it; pagination or ranges if it does not |

- [ ] Compare with `ping` to the same host: TCP should be about one ping; TLS about two. Anything bigger is loss or a slow endpoint.
- [ ] `%{num_connects}` and `%{num_redirects}`: a redirect chain doubles everything; a new connection per request pays DNS, TCP and TLS every time (keep-alive is Phase 2 lesson 14).
- [ ] `--trace-time -v` timestamps every line, which shows a stall *inside* the exchange (headers sent, then a gap, then the response).
- [ ] Slow only from one place: section 3.

## 2 · Failing: read the exit code first

| exit | curl says | it means | next |
|---|---|---|---|
| 6 | Could not resolve host | DNS | lesson 14, layer 1 |
| 7 | Failed to connect | refused, or unreachable | lesson 14, layers 2 to 5 |
| 28 | Operation timed out | `--max-time`/`--connect-timeout` hit; nothing answered, or the server is slow | section 1; lesson 14 layer 3 or 5 |
| 35 | SSL connect error | the TLS handshake failed: protocol or cipher mismatch, or a plain-HTTP port | section 4 |
| 51 | SSL: no alternative certificate subject name matches | the certificate is for a different name (you dialled by IP, or the wrong hostname) | section 4 |
| 52 | Empty reply from server | it accepted and closed without a response: crashed mid-request, or expects TLS on that port | server logs; try `https://` |
| 55 / 56 | Failed sending / receiving | the connection was reset mid-transfer: a proxy or LB timeout, or the server died | `--trace-time`; the LB's idle timeout |
| 60 | SSL certificate problem: unable to get local issuer / self-signed | the CA is not trusted here | section 4 |
| 22 | The requested URL returned error: NNN | `-f` and a 4xx/5xx | the status code; the body without `-f` |
| 18 | transfer closed with N bytes remaining | `Content-Length` promised more than arrived | the server (Phase 2 lesson 09's bug) |

- [ ] `-sS` so the message is printed, `-v` for the step it died at, `--trace-ascii -` when the message is not enough.
- [ ] A `4xx`/`5xx` is not a curl failure unless `-f`: read the body (`curl -i`), the `WWW-Authenticate` on 401, the `Allow` on 405, the `Retry-After` on 429 and 503.

## 3 · It depends where I run it: take pieces out of the path

```bash
curl --resolve api.example.com:443:10.0.0.7 https://api.example.com/health   # this backend, by address, correct Host and SNI
curl --connect-to api.example.com:443:canary.internal:8443 https://api.example.com/health   # a different host and port, same name
curl -H 'Host: api.example.com' http://10.0.0.7/health                        # plain HTTP: the header is enough
curl -4 / curl -6 https://api.example.com/health                              # force an address family
curl --interface eth1 https://api.example.com/health                          # force the source interface
curl --noproxy '*' https://api.example.com/health                             # ignore http_proxy / https_proxy
curl -x http://proxy.internal:3128 https://api.example.com/health             # or use one explicitly
```

- [ ] Works with `--resolve` to one backend and fails through the name: the load balancer, DNS, or another backend. Try each backend's address in turn.
- [ ] Works from the server (`127.0.0.1`) and not from outside: lesson 14, layers 4 and 5.
- [ ] Works with `-4` and not by default: IPv6 is configured but not routed (or the reverse).
- [ ] `env | grep -i proxy`: a proxy variable in the environment changes every request silently; `--noproxy '*'` proves it.

## 4 · TLS

```bash
curl -v https://api.example.com/ -o /dev/null 2>&1 | grep -E 'SSL connection|subject:|issuer:|expire|subjectAltName'
openssl s_client -connect api.example.com:443 -servername api.example.com </dev/null 2>/dev/null | openssl x509 -noout -subject -issuer -dates -ext subjectAltName
curl --cacert internal-ca.pem https://api.internal/                          # trust a private CA for this call
curl -k https://api.internal/                                                # skip verification: diagnosis only, never in a script
curl --tlsv1.2 --tls-max 1.2 https://api.example.com/                        # pin a version to test a mismatch
curl --cert client.pem --key client-key.pem https://api.example.com/         # mutual TLS (Phase 2 lesson 10)
```

- [ ] **60** (unable to get local issuer certificate, or self-signed): the chain does not end in a CA this box trusts. Internal CA: `--cacert` for now, and install it into the system store (`/usr/local/share/ca-certificates/` then `update-ca-certificates` on Debian; `/etc/pki/ca-trust/source/anchors/` then `update-ca-trust` on Red Hat) for good. A public site: the server is sending an incomplete chain (missing intermediate), which browsers paper over and curl does not.
- [ ] **51** (no alternative certificate subject name matches): you connected by IP, or the name is not in the certificate's SAN list. `--resolve` keeps the name; `-k` hides the problem.
- [ ] **expired**: `expire date` in the past. Renew; check who was supposed to.
- [ ] **35**: the handshake itself failed: TLS 1.0/1.1 only on one side, a cipher mismatch, or you spoke TLS to a plain-HTTP port (or the reverse: exit 52 or a `400 Bad Request` with binary in it).
- [ ] The clock: a box whose clock is wrong by more than the certificate's validity window rejects every certificate. `date`, `timedatectl`.
- [ ] `-k` is for finding out what the certificate *is*; a script with `-k` has no TLS.

## 5 · In a script: bound it, retry it, fail honestly

```bash
curl -sSf \
  --connect-timeout 5 --max-time 30 \
  --retry 3 --retry-delay 2 --retry-max-time 60 \
  -o "$out" -w '%{http_code}\n' "$url"
```

- [ ] `--connect-timeout`: how long to wait for the TCP/TLS connection; `--max-time`: the whole request. Without both, a hung server hangs your script forever.
- [ ] `--retry N`: retries transient failures (connect errors, timeouts, 408/429/500/502/503/504) with delays that double from `--retry-delay`; `--retry-all-errors` retries everything (dangerous with non-idempotent requests, Phase 3 lesson 07); `--retry-max-time` caps the total. `%{num_retries}` tells you it happened.
- [ ] `-f`: a final 4xx/5xx is exit 22, not a saved error page. `--fail-with-body` keeps the body for the log.
- [ ] Idempotency: retrying a `POST` that half-succeeded creates two orders. Retry `GET`, `PUT`, `DELETE` freely; retry `POST` only with an idempotency key (Phase 3 lesson 07).
- [ ] Log the `-w` line on failure, with the timestamp: the five numbers are the incident's first evidence.
