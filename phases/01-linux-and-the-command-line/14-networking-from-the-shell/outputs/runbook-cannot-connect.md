---
name: runbook-cannot-connect
description: The layered diagnosis for "it cannot connect" or "nothing can connect to it" — name, route, reachability, port, firewall, then the protocol — with the command at each layer, what each answer means (refused versus timed out versus unreachable), and the same ladder run from the server's side
phase: 01
lesson: 14
---

# Cannot connect

Two directions, one ladder. **Outbound**: this box cannot reach
something. **Inbound**: something cannot reach this box. Each layer has
one command and three possible answers, and the answer tells you which
layer to look at next. Do not skip layers; "DNS was fine yesterday" is
how an hour disappears.

## 0 · Get the exact failure

- [ ] The literal error, from the client that fails: `Connection refused`, `Connection timed out`, `No route to host`, `Name or service not known`, `Network is unreachable`, `SSL ...`, `HTTP 502`. Each is a different layer.
- [ ] The exact target: hostname, IP, port, protocol. "The API" is not a target; `api.internal:8443` is.
- [ ] From where: this box, a container on it, another box, a laptop on VPN. The path differs.

| the error says | the layer | go to |
|---|---|---|
| `Name or service not known`, `Temporary failure in name resolution`, `NXDOMAIN` | DNS | 1 |
| `Network is unreachable`, `No route to host` | routing / the interface | 2 |
| hangs, then `Connection timed out` | reachability or a firewall that drops | 3, 5 |
| `Connection refused` | reached a host; nothing listens on that port (or a firewall that rejects) | 4, 5 |
| connects, then hangs or resets | the service, TLS, or a middlebox | 6 |
| `EADDRINUSE` on the server | the port is held by another process | 4 (inbound) |

## 1 · The name

```bash
getent hosts api.internal            # what the box actually resolves to (hosts file first, then DNS, per nsswitch.conf)
dig +short api.internal              # what DNS alone says; dig api.internal A for the full answer and which server answered
cat /etc/resolv.conf                 # which resolvers; nameserver 127.0.0.53 means systemd-resolved: resolvectl status
grep api /etc/hosts                  # an override someone left behind
dig @1.1.1.1 +short api.internal     # ask a different resolver: is it your resolver, or the record?
```

- [ ] `getent` and `dig` disagree: `/etc/hosts` or `nsswitch.conf` is overriding DNS.
- [ ] `dig` works and the program does not: the program caches (Java, some libc), or uses its own resolver config (a container's `/etc/resolv.conf` is written by Docker).
- [ ] Slow to fail (5 s, 10 s): a dead resolver in `resolv.conf` tried first; `options timeout:1 attempts:1` or fix the list.
- [ ] IPv6: the name has an `AAAA` record and the box has no IPv6 route; the client tries v6, waits, falls back. `curl -4` to confirm.

## 2 · The route

```bash
ip route get 10.20.30.40             # which interface and gateway this box would use for that address
ip route                             # the whole table; is there a default?
ip -br addr                          # interfaces up, and their addresses
ip -s link show eth0                 # errors and drops on the interface
```

- [ ] `ip route get` says `unreachable` or errors: no route. Missing default gateway, a VPN that took the route down, a container network without one.
- [ ] The interface is `DOWN` or has no address: DHCP failed, a cable, a cloud NIC not attached.
- [ ] The route goes out the wrong interface (VPN vs LAN): the more specific route wins; `ip route get` tells you which one.

## 3 · Reachability

```bash
ping -c 3 -W 1 10.20.30.40           # ICMP echo; many hosts and clouds block it, so "no reply" is not proof of down
traceroute -n 10.20.30.40            # where the path stops; mtr -n for a live version
nc -zv -w 3 10.20.30.40 443          # a TCP probe to the actual port: the answer that matters
```

- [ ] `nc`: **succeeded** → the layer below is fine, go to 6. **refused** → a host answered with RST: it is up, nothing listens on that port (or a REJECT firewall rule), go to 4. **timed out** → no answer at all: a DROP firewall rule, a host that is down, or a path that black-holes, go to 5.
- [ ] `traceroute` stops at a hop and never reaches: the path is broken there, or a firewall drops ICMP after it. Combine with `nc`.

## 4 · The port (run on the server side)

```bash
ss -tlnp                             # who listens on what: State LISTEN, Local Address:Port, and the process with -p
ss -tlnp | grep ':8443'              # this port specifically
ss -tlnp | grep '127.0.0.1'          # bound to loopback only? then nothing outside the box can reach it
```

- [ ] **Nothing listens**: the service is not running (`systemctl status`), crashed (lesson 11), or is still starting.
- [ ] **Listens on `127.0.0.1:port`** but clients are remote: bind to `0.0.0.0` (or the interface's address). Docker containers bind inside their own namespace; `-p` publishes.
- [ ] **Listens on a different port** than documented: the config, the environment (`PORT=`), or two copies.
- [ ] **`EADDRINUSE` at start**: `ss -tlnp` shows the holder (the previous copy still stopping, a leaked child holding the socket after the parent died: lesson 10, or another service). `TIME-WAIT` sockets alone do not block a bind with `SO_REUSEADDR`.
- [ ] Listens, but `Recv-Q` on the LISTEN row is at `Send-Q` (the backlog): the server is not calling `accept()` fast enough; connections are dropped; `nstat -az | grep -i listen` counts them (lesson 02, lesson 12).

## 5 · The firewall (both ends, and in between)

```bash
nft list ruleset                     # the kernel's rules (nftables); iptables -L -n -v for the legacy view; ufw status verbose
nft list ruleset | grep -E 'dport (8443|22)'
```

- [ ] A **drop** rule shows as a timeout; a **reject** rule as refused. Both are "the port is fine, the firewall is not."
- [ ] The host firewall (`ufw`, `nftables`, `firewalld`), then the cloud one (security groups, network ACLs), then anything in the path (a corporate proxy, a load balancer's listener, Kubernetes network policy). Each has its own console; each is checked separately.
- [ ] Outbound is filtered too: egress rules and proxies block outbound `443` on some networks. `env | grep -i proxy`.
- [ ] Test from the server itself (`nc -zv 127.0.0.1 8443`), then from the same subnet, then from outside. The layer where it stops working is the layer with the rule.

## 6 · The protocol

```bash
curl -v https://api.internal:8443/health          # the TLS handshake and the HTTP exchange, step by step (lesson 15, 16)
openssl s_client -connect api.internal:8443 -servername api.internal </dev/null | head -20   # the certificate the server presents
curl -sS --resolve api.internal:8443:10.20.30.40 https://api.internal:8443/health   # bypass DNS, keep the Host and SNI
printf 'GET / HTTP/1.1\r\nHost: x\r\n\r\n' | nc api.internal 80  # raw HTTP, when you suspect the client library
```

- [ ] Connects, TLS fails: certificate expired, wrong name (SNI), an untrusted CA, or a TLS version mismatch (Phase 2, lesson 10).
- [ ] Connects, hangs with no response: the server accepted and stalled (a full worker pool, a lock, a slow dependency): the server's own logs and lesson 12 on that box.
- [ ] Connects, `502`/`504`: a proxy in front could not reach *its* upstream: run this ladder again from the proxy toward the upstream.
- [ ] Works with `curl`, fails in the app: the app's timeouts, proxy settings, DNS caching, TLS trust store, or a different address family.

## 7 · Watch the wire when the layers disagree

```bash
tcpdump -i any -nn 'host 10.20.30.40 and port 8443'          # do packets leave? does anything come back?
tcpdump -i eth0 -nn -c 20 'tcp[tcpflags] & (tcp-syn) != 0'    # SYNs only: who is trying to connect to what
tcpdump -i any -nn -w /tmp/case.pcap port 8443 &               # capture for later; open in Wireshark
```

- [ ] SYN leaves, nothing returns: dropped in the path or at the far host (5).
- [ ] SYN leaves, RST returns: refused at the far host (4, on their side).
- [ ] SYN, SYN-ACK, ACK, then nothing: the connection is fine and the *application* is silent (6).
- [ ] No SYN at all: the client never sent it: DNS, route, or the client's own bug (1, 2).

## 8 · Write the answer as the layer

"DNS returned the old IP", "no default route after the VPN reconnected", "security group blocks 8443 from that subnet", "the service bound 127.0.0.1", "the backlog was full". A layer and a fact. The next person can act on that; "networking issue" they cannot.
