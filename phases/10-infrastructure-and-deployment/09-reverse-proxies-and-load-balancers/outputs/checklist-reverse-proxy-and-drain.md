---
name: checklist-reverse-proxy-and-drain
description: Put a proxy in front of a service without breaking client IPs, timeouts or deploys — trust boundaries for X-Forwarded-For, a nested timeout ladder, and the drain sequence that takes dropped requests from 15 to 0.
phase: 10
lesson: 09
---

# Reverse proxy & drain — pre-ship checklist

Run this the day you put a proxy in front of a service, and again every time a hop is added
or removed. Every item exists because skipping it caused a real outage or a real bypass.

## 1 · Decide the layer before anything else

- [ ] Written down: **L4 or L7**, and why. L4 = transport, moves bytes, can route only on the
      port you connected to. L7 = application, parses HTTP, can route on anything in it.
- [ ] If you need path routing, header routing, per-route timeouts, retries or
      `X-Forwarded-For`, you need **L7**, which means you must **terminate TLS**.
- [ ] If the backend must see the client's TLS certificate (mTLS), you need **passthrough**,
      which means you do **not** get any of the above. These are mutually exclusive.
- [ ] TLS arrangement chosen deliberately: **terminate** (default) / **passthrough** (backend
      needs the client cert or you may not hold the key) / **re-encrypt** (internal network
      not trusted).

## 2 · The client IP — the security item

- [ ] The application reads the client address from **`X-Forwarded-For` parsed by trusted hop
      count**, never `remote_addr` and never `xff.split(",")[0]`.
- [ ] `trusted_hops` equals the number of proxies **you operate**, as an explicit constant.
- [ ] Framework setting matches: Express `app.set('trust proxy', N)`, Werkzeug
      `ProxyFix(x_for=N)`, ASP.NET `ForwardedHeadersOptions.ForwardLimit`. **A hop count, not
      `true`.** `true` is the spoofable parser with extra steps.
- [ ] Your **outermost** proxy **overwrites** client-supplied `X-Forwarded-For` rather than
      appending (nginx: `proxy_set_header X-Forwarded-For $remote_addr;` at the edge,
      `$proxy_add_x_forwarded_for` on inner hops only).
- [ ] `set_real_ip_from` / `xff_num_trusted_hops` / equivalent names the **CIDR ranges** that
      may set the header. Unset = trust the internet.
- [ ] Everything derived from a client IP audited against the above: rate limits, IP
      allowlists, geo rules, fraud signals, audit logs, abuse blocking.
- [ ] `X-Forwarded-Proto` is set and the app uses it for redirects and `Secure` cookies —
      after termination the app sees plain HTTP and will otherwise redirect-loop.
- [ ] Adding or removing a hop (a CDN, a second LB) is on a change checklist that includes
      updating the hop count. Nothing fails loudly when this is wrong.
- [ ] Access logs record **both** the resolved client IP and the full chain, so an incident can
      distinguish a spoof from a topology change.

## 3 · The timeout ladder

Write the whole ladder down, one line, and check that it strictly decreases:

```text
client deadline  >  edge proxy  >  ingress proxy  >  app request  >  DB query
   10 s          >     5 s      >      3 s        >     2 s       >    1 s
```

- [ ] **Every inner timeout is strictly shorter than the one outside it.** Whoever gives up
      first should be whoever can still say something useful about why.
- [ ] `proxy_read_timeout` (nginx) is set explicitly. **The default is 60 s**, which is not a
      timeout, it is a hope.
- [ ] `proxy_connect_timeout` is small (1–2 s on a LAN); a slow *connect* usually means a dead
      host, not a slow one.
- [ ] The proxy's **keep-alive idle timeout is shorter than the backend's**, or the backend
      will close a pooled connection just as the proxy writes a request into it.
- [ ] Retries are bounded (`proxy_next_upstream_tries 2`, Envoy `num_retries`) and only for
      idempotent requests. A proxy that retries a `POST` on timeout will double-charge somebody.
- [ ] Retries exist at **exactly one layer**. SDK + mesh + gateway each retrying 3× is 27
      requests at the bottom.
- [ ] You have accepted, in writing, that **a timeout does not cancel backend work** — the
      backend finishes and you pay for it. If that cost matters, propagate a deadline the
      backend itself enforces.

## 4 · Health checks the proxy acts on

- [ ] The check is an **HTTP request to a real endpoint**, not a TCP connect. A deadlocked
      process completes the TCP handshake forever.
- [ ] It targets **readiness**, not liveness. The proxy's question is "route here?", not
      "is this process broken?".
- [ ] Active checking (interval + thresholds) **and** passive ejection (`outlier_detection`,
      `max_fails`/`fail_timeout`) are both configured.
- [ ] Ejection is capped (`max_ejection_percent: 50` or equivalent) so a **global** fault
      cannot empty the pool and turn a degradation into an outage.
- [ ] Coming back into rotation is harder than leaving (higher healthy threshold), so an
      instance cannot flap.

## 5 · The drain sequence — three steps, and step 2 is the point

Measured on an identical 45-request schedule with 3 requests in flight at removal:
**kill = 15 dropped · remove-then-kill = 3 dropped · drain = 0 dropped**, for ~400 ms of waiting.

- [ ] **1.** Mark the instance **not routable** — fail readiness, deregister from the target
      group — so it receives no *new* requests.
- [ ] **2.** **Wait**, while still serving, long enough for that decision to reach every proxy
      *and* for in-flight work to finish. Track an in-flight counter; do not guess.
- [ ] **3.** Only then stop the process.
- [ ] The wait has a **deadline**, and what happens to a request still running at the deadline
      is decided in advance (and is safe, because the operation is idempotent).
- [ ] `terminationGracePeriodSeconds` ≥ preStop wait + longest request + flush, with headroom.
- [ ] The load balancer's **deregistration delay** (AWS default: **300 s**) is no larger than
      the grace period — otherwise the orchestrator kills a pod the LB still thinks is draining.
- [ ] Responses during the drain carry `Connection: close`, so keep-alive clients holding a
      pooled socket reconnect elsewhere instead of sending their next request into a closing one.
- [ ] Config reloads drain too (`nginx -s reload` finishes in-flight requests in the old
      workers). Verify yours does.
- [ ] Verified by watching a real deploy: **zero connection resets, zero 502s** attributable to it.

## 6 · Certificates and config

- [ ] Certificate issuance and renewal are **automated** (ACME / cert-manager / managed certs).
      A 90-day certificate is a scheduled outage if renewal is manual.
- [ ] Expiry is monitored independently of the renewal system, with an alert at 21 days.
- [ ] Hop-by-hop headers (`Connection`, `Keep-Alive`, `TE`, `Trailer`, `Transfer-Encoding`,
      `Upgrade`, `Proxy-Authenticate`, `Proxy-Authorization`) are **not** forwarded upstream.
- [ ] `Host` handling is deliberate: preserved, or rewritten with `X-Forwarded-Host` set.
- [ ] Controller-specific ingress **annotations** are inventoried — they are the part that does
      not port to another controller. Prefer the Gateway API where it is available.
- [ ] Sticky sessions are absent, or there is a written reason and a plan to remove them.

## 7 · Anti-patterns to grep for

- [ ] `split(",")[0]` anywhere near a forwarded header. **The** classic bypass.
- [ ] `trust proxy: true` / trust-all forwarded headers.
- [ ] `remote_addr` used as "the client IP" in an app that sits behind a proxy.
- [ ] Any `proxy_read_timeout` left at the default.
- [ ] A `tcpSocket` health check on an HTTP backend.
- [ ] A deploy script that stops a container without deregistering it first.
- [ ] A deploy script that deregisters and then stops **immediately** — that is 3 dropped
      requests, and they are the oldest and most side-effecting ones.
- [ ] Retries enabled on non-idempotent routes.

> ## Decision shortcut
>
> **"Where does this request's information come from, and who could have written it?"**
> Socket peer → the last hop, always true, usually useless.
> Right-most `X-Forwarded-For` entry → your last proxy, trustworthy.
> Left-most entry → **whoever spoke first**, which may be an attacker.
>
> **"What happens to the requests already inside it?"**
> Ask this of every removal, every deploy, every reload. If the answer is "they finish",
> you are draining. If the answer is anything else, you are dropping requests and calling it
> a rollout.
