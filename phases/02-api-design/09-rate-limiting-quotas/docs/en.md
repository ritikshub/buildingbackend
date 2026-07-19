# Rate Limiting & Quotas

> A rate limit turns "everyone gets slow, then everyone gets errors" into "one client gets 429s, everyone else is fine." Resilience is a negotiated protocol between client and server.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Idempotency & Safe Retries](../07-idempotency-safe-retries/)
**Time:** ~60 minutes

## The Problem

Every API that survives production needs a way to say "no" politely when demand
exceeds capacity. There are four distinct motivations, each shaping the design:

1. **Protecting capacity** — one misbehaving client (often a retry loop with no
   backoff) can consume your whole CPU/DB/memory budget.
2. **Fairness between tenants** — tenant A's bulk export must not starve tenant B's
   checkout.
3. **Abuse defense** — 5 login attempts/minute/account makes brute-forcing hopeless.
4. **Downstream cost control** — if each request fans out to a metered downstream (SMS, payments, geocoding), a
   traffic spike is a billing spike.

A real API layers all four: a tight abuse limit on `/login`, a per-tenant fairness
limit everywhere, a global capacity limit at the edge.

## The Concept

### The classic algorithms

All limiters answer "has this key exceeded N ops per window T?" — they differ in how
they account for time.

| Algorithm | State/key | Accuracy | Boundary burst? | Best fit |
|---|---|---|---|---|
| Fixed window counter | 1 counter | Coarse | **Yes — up to 2× limit** | Cheap coarse limits, quotas |
| Sliding window log | Up to N timestamps | Exact | No | Low-limit, high-stakes (login) |
| Sliding window counter | 2 counters | Approximate (close) | Bounded, small | **General-purpose default** |
| Token bucket | Tokens + timestamp | Exact to its model | No | Bursty clients; weighted costs |
| Leaky bucket (queue) | Level + timestamp | Exact | No — smooths | Strict-rate downstreams |

The **fixed window's boundary-burst problem**: windows align to the clock, not the
client. 100 requests at 11:59:59 and 100 at 12:00:01 = 200 in two seconds, all
allowed, because they land in different windows. Effective worst-case is 2× the
limit. The **sliding window counter** (weight the previous window's count by its
remaining overlap) fixes this with just two counters — Cloudflare's edge choice.

### Token bucket (bursts + sustained rate)

The most useful for public APIs. A bucket holds up to `capacity` tokens dripping in
at `rate`/sec; each request consumes one (or `cost` for expensive ops):

```python
import time
from dataclasses import dataclass, field

@dataclass
class TokenBucket:
    rate: float                 # sustained tokens/second
    capacity: float             # max burst
    tokens: float = 0.0
    last: float = field(default_factory=time.monotonic)

    def allow(self, cost: float = 1.0) -> bool:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
        self.last = now
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False
```

`rate` is the long-run average you tolerate; `capacity` is how much burst you
forgive. Note the lazy refill — no background timer; tokens are computed from
elapsed time on each check. AWS API Gateway throttling is expressed in exactly these
terms.

### Distributed limiting: the replica trap

In-process counters silently multiply your limit by the replica count — two replicas
each enforce the full limit, so the effective limit becomes `limit × replicas` and
drifts with autoscaling. The fix is shared state in Redis. `INCR` is atomic, but the
`INCR`/`EXPIRE` gap can leak a never-expiring key on a crash — make the pair atomic
with a Lua script (Redis runs scripts atomically):

```lua
-- KEYS[1]=counter key, ARGV[1]=limit, ARGV[2]=window seconds
local current = redis.call("INCR", KEYS[1])
if current == 1 then redis.call("EXPIRE", KEYS[1], ARGV[2]) end
if current > tonumber(ARGV[1]) then return 0 end
return 1
```

**Decide the failure mode explicitly:** if Redis is unreachable, do you fail-open
(availability over protection — right for fairness limits) or fail-closed (right for
`/login` abuse limits)? An accidental fail-closed on a Redis blip turns a cache
hiccup into a full outage.

### Scoping: what's the key?

Per API key/tenant for authenticated traffic; **per IP only for anonymous traffic**
— and mind the pitfalls: NAT means an office or campus shares one public IP (a
per-IP limit locks out thousands at once), and `X-Forwarded-For` is client-forgeable
(only trust the entry your own edge appends).

### Rate limits vs quotas

Different instruments, usually both present:

| | Rate limit | Quota |
|---|---|---|
| Window | Seconds–minutes | Day/month |
| Purpose | Protect capacity | Meter plan tiers |
| Example | 100/minute | 50,000/month on Free |

### Communicating limits

Rejecting silently trains clients to hammer harder. Use the HTTP vocabulary:
**`429 Too Many Requests`** (RFC 6585) with **`Retry-After`** (RFC 9110, seconds or
an HTTP-date), plus the de facto **`X-RateLimit-Limit`/`-Remaining`/`-Reset`** trio.
GitHub and Stripe are the reference implementations of the contract: *the server
tells the client whether and when retrying makes sense, and the official clients obey.*

Client side, retry with **exponential backoff and full jitter** — plain exponential
backoff makes 1,000 clients that failed together return in synchronized waves (a
thundering herd); jitter (sleep uniformly random in `[0, cap]`) decorrelates them.
Always **honor `Retry-After`** over your own guess, and classify before retrying (a
`400`/`422` is your bug — retrying it is pure waste).

> The deeper resilience patterns that build on this — timeouts, circuit breakers,
> bulkheads, load shedding, backpressure — live in **Phase 11 · Scalability & Reliability**.

## Build It

`code/rate_limiters.py` implements all three algorithms against a *fake clock*, so the
boundary-burst bug is reproducible rather than a race you have to take on faith. The
token bucket is the mental model worth keeping:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 612" width="100%" style="max-width:880px" role="img" aria-label="The token bucket algorithm drawn as a real bucket. Tokens drip in at rate equals 10 tokens per second, and the bucket's rim is its capacity of 10 tokens, so it can never hold more than 10; the drawing shows it full with 10 countable tokens. A request arrives costing cost tokens, one by default, though an expensive operation can charge more. One decision is asked: are there at least cost tokens, counted after the lazy refill? On the yes branch the request is allowed, the tokens are spent, and the response is 200 OK carrying X-RateLimit-Remaining 9. On the no branch it is rejected with 429 Too Many Requests from RFC 6585, a Retry-After header from RFC 9110, and the de facto trio X-RateLimit-Limit 10, X-RateLimit-Remaining 0 and X-RateLimit-Reset; rejecting silently instead trains clients to hammer harder, and GitHub and Stripe are the reference implementations of that contract. There is no background timer: tokens are recomputed lazily on every check as tokens equals min of capacity and tokens plus elapsed time times rate, which is exactly what lets the Redis version be a single atomic script. The bottom timeline replays the lesson's own run with rate 10 per second and capacity 10. At t equals 0.0, 15 requests arrive at one instant; the first 10 are allowed because the bucket held 10, and 5 are denied, leaving the bucket empty. One second of drip refills 10 tokens, capped at capacity. At t equals 1.0 the same 15 requests again get 10 allowed and 5 denied, so sustained throughput settles at the rate while capacity alone paid for the burst.">
  <defs>
    <marker id="p2l09a-arb" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
    <marker id="p2l09a-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p2l09a-arm" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
    <marker id="p2l09a-arp" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#7c5cff"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Token bucket: capacity forgives the burst, rate sets the ceiling you sustain</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g fill="none" stroke-linejoin="round" stroke-width="1.7">
      <rect x="16" y="44" width="356" height="290" rx="12" fill="#7c5cff" fill-opacity="0.05" stroke="#7c5cff" stroke-opacity="0.45"/>
    </g>
    <g text-anchor="middle" fill="currentColor">
      <text x="194" y="66" font-size="11" font-weight="700" fill="#7c5cff">THE BUCKET — the whole state</text>
      <text x="194" y="80" font-size="8" opacity="0.75">tokens + one timestamp, per key</text>
      <text x="194" y="100" font-size="9.5" font-weight="700" fill="#0fa07f">drip · rate = 10 tokens/sec</text>
      <text x="194" y="112" font-size="7.5" opacity="0.75">the long-run average you tolerate</text>
    </g>

    <g fill="none" stroke="#0fa07f" stroke-width="1.6" stroke-dasharray="3 4" stroke-opacity="0.8">
      <path d="M194 118 L194 156" marker-end="url(#p2l09a-arg)"/>
    </g>
    <g fill="#0fa07f">
      <circle cx="194" cy="122" r="4.2"/><circle cx="194" cy="135" r="3.4"/><circle cx="194" cy="147" r="2.6"/>
    </g>

    <path d="M118 162 L270 162 L254 272 L134 272 Z" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff" stroke-width="2.2" stroke-linejoin="round"/>
    <path d="M112 162 L276 162" fill="none" stroke="#7c5cff" stroke-width="3.4" stroke-linecap="round"/>
    <path d="M34 162 L108 162" fill="none" stroke="#7c5cff" stroke-width="1.2" stroke-dasharray="4 4" stroke-opacity="0.65"/>
    <text x="34" y="143" font-size="9" font-weight="700" fill="#7c5cff">capacity = 10</text>
    <text x="34" y="155" font-size="7.5" fill="currentColor" opacity="0.8">holds ≤ capacity</text>

    <g fill="#0fa07f" fill-opacity="0.75" stroke="#0fa07f" stroke-width="1.2">
      <circle cx="152" cy="254" r="6.5"/><circle cx="182" cy="254" r="6.5"/><circle cx="212" cy="254" r="6.5"/><circle cx="242" cy="254" r="6.5"/>
      <circle cx="152" cy="238" r="6.5"/><circle cx="182" cy="238" r="6.5"/><circle cx="212" cy="238" r="6.5"/><circle cx="242" cy="238" r="6.5"/>
      <circle cx="182" cy="222" r="6.5"/><circle cx="212" cy="222" r="6.5"/>
    </g>

    <g text-anchor="middle" fill="currentColor">
      <text x="194" y="290" font-size="9" font-weight="700" fill="#0fa07f">10 of 10 tokens — full</text>
      <text x="194" y="306" font-size="8" opacity="0.9">the rim = capacity (burst) · the drip = rate</text>
      <text x="194" y="322" font-size="7.5" opacity="0.7">AWS API Gateway throttling is expressed in exactly these terms.</text>
    </g>

    <g fill="none" stroke-linejoin="round" stroke-width="2">
      <rect x="400" y="52" width="214" height="54" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <path d="M507 122 L614 176 L507 230 L400 176 Z" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.6"/>
    </g>
    <g text-anchor="middle" fill="currentColor">
      <text x="507" y="73" font-size="11" font-weight="700" fill="#3553ff">REQUEST arrives</text>
      <text x="507" y="88" font-size="8.5">it costs `cost` tokens — default 1</text>
      <text x="507" y="100" font-size="7.5" opacity="0.75">an expensive op can charge more</text>
      <text x="507" y="172" font-size="11" font-weight="700">tokens ≥ cost?</text>
      <text x="507" y="187" font-size="7.5" opacity="0.8">asked AFTER the lazy refill</text>
      <text x="390" y="192" font-size="7.5" opacity="0.7" fill="#7c5cff">tokens</text>
      <text x="507" y="266" font-size="8.5" font-weight="700" opacity="0.85">one bucket per key</text>
      <text x="507" y="280" font-size="8" opacity="0.7">API key or tenant — IP only for anonymous</text>
    </g>

    <g fill="none" stroke="#3553ff" stroke-width="1.8">
      <path d="M507 106 L507 118" marker-end="url(#p2l09a-arb)"/>
    </g>
    <g fill="none" stroke="#7c5cff" stroke-width="1.8">
      <path d="M376 176 L396 176" marker-end="url(#p2l09a-arp)"/>
    </g>
    <g fill="none" stroke="#0fa07f" stroke-width="1.8">
      <path d="M616 176 L632 176 L632 108 L646 108" marker-end="url(#p2l09a-arg)"/>
    </g>
    <g fill="none" stroke="#e0930f" stroke-width="1.8">
      <path d="M616 176 L632 176 L632 244 L646 244" marker-end="url(#p2l09a-arm)"/>
    </g>
    <g text-anchor="end">
      <text x="628" y="136" font-size="9" font-weight="700" fill="#0fa07f">yes</text>
      <text x="628" y="148" font-size="7" fill="#0fa07f" opacity="0.85">tokens -= cost</text>
      <text x="628" y="212" font-size="9" font-weight="700" fill="#e0930f">no</text>
      <text x="628" y="224" font-size="7" fill="#e0930f" opacity="0.85">no tokens spent</text>
    </g>

    <g fill="none" stroke-linejoin="round" stroke-width="2">
      <rect x="650" y="48" width="234" height="96" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="650" y="156" width="234" height="178" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
    </g>
    <g fill="currentColor">
      <text x="666" y="70" font-size="11" font-weight="700" fill="#0fa07f">ALLOW</text>
      <text x="868" y="70" font-size="9.5" font-weight="700" text-anchor="end" fill="#0fa07f">200 OK</text>
      <text x="666" y="90" font-size="8.5">tokens -= cost → 10 becomes 9</text>
      <text x="666" y="108" font-size="9">X-RateLimit-Remaining: 9</text>
      <text x="666" y="126" font-size="7.5" opacity="0.75">limit headers ride the success path too</text>

      <text x="666" y="178" font-size="11" font-weight="700" fill="#e0930f">REJECT</text>
      <text x="868" y="178" font-size="7.5" text-anchor="end" opacity="0.7">4xx = the client's fault</text>
      <text x="666" y="198" font-size="9.5" font-weight="700" fill="#e0930f">429 Too Many Requests</text>
      <text x="868" y="198" font-size="7" text-anchor="end" opacity="0.65">RFC 6585</text>
      <text x="666" y="216" font-size="9">Retry-After: 1</text>
      <text x="868" y="216" font-size="7" text-anchor="end" opacity="0.65">RFC 9110</text>
      <text x="666" y="234" font-size="9">X-RateLimit-Limit: 10</text>
      <text x="666" y="252" font-size="9">X-RateLimit-Remaining: 0</text>
      <text x="868" y="252" font-size="7" text-anchor="end" opacity="0.65">de facto trio</text>
      <text x="666" y="270" font-size="9">X-RateLimit-Reset: (epoch)</text>
      <text x="666" y="292" font-size="7.5" opacity="0.8">silence trains clients to hammer harder</text>
      <text x="666" y="306" font-size="7.5" opacity="0.8">GitHub and Stripe are the reference here</text>
      <text x="666" y="320" font-size="7.5" opacity="0.8">clients honor Retry-After + full jitter</text>
    </g>

    <g fill="none" stroke-linejoin="round" stroke-width="1.6">
      <rect x="16" y="348" width="868" height="56" rx="10" fill="#7c5cff" fill-opacity="0.06" stroke="#7c5cff" stroke-opacity="0.5"/>
    </g>
    <g fill="currentColor">
      <text x="32" y="370" font-size="10.5" font-weight="700" fill="#7c5cff">LAZY REFILL — there is no background timer</text>
      <text x="868" y="370" font-size="8" text-anchor="end" opacity="0.75">which is what makes the Redis version a single atomic script</text>
      <text x="32" y="390" font-size="9.5">tokens = min(capacity, tokens + (now - last) * rate)</text>
      <text x="352" y="390" font-size="8" opacity="0.8">— recomputed on each check, from elapsed time; nothing runs between requests</text>
    </g>

    <text x="450" y="428" text-anchor="middle" font-size="10.5" font-weight="700" fill="currentColor">The lesson's own run — rate = 10/sec, capacity = 10, 15 requests fired twice</text>
    <g fill="none" stroke-linejoin="round" stroke-width="1.5">
      <rect x="16" y="440" width="380" height="118" rx="10" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.28"/>
      <rect x="504" y="440" width="380" height="118" rx="10" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.28"/>
    </g>
    <g fill="currentColor">
      <text x="32" y="464" font-size="10.5" font-weight="700">t = 0.0</text>
      <text x="380" y="464" font-size="8.5" text-anchor="end" fill="#0fa07f">bucket held 10 tokens</text>
      <text x="520" y="464" font-size="10.5" font-weight="700">t = 1.0</text>
      <text x="868" y="464" font-size="8.5" text-anchor="end" fill="#0fa07f">1s refilled 10 tokens</text>
    </g>
    <g stroke-width="1.2" rx="3">
      <rect x="34" y="474" width="18" height="16" rx="3" fill="#0fa07f" fill-opacity="0.75" stroke="#0fa07f"/>
      <rect x="56" y="474" width="18" height="16" rx="3" fill="#0fa07f" fill-opacity="0.75" stroke="#0fa07f"/>
      <rect x="78" y="474" width="18" height="16" rx="3" fill="#0fa07f" fill-opacity="0.75" stroke="#0fa07f"/>
      <rect x="100" y="474" width="18" height="16" rx="3" fill="#0fa07f" fill-opacity="0.75" stroke="#0fa07f"/>
      <rect x="122" y="474" width="18" height="16" rx="3" fill="#0fa07f" fill-opacity="0.75" stroke="#0fa07f"/>
      <rect x="144" y="474" width="18" height="16" rx="3" fill="#0fa07f" fill-opacity="0.75" stroke="#0fa07f"/>
      <rect x="166" y="474" width="18" height="16" rx="3" fill="#0fa07f" fill-opacity="0.75" stroke="#0fa07f"/>
      <rect x="188" y="474" width="18" height="16" rx="3" fill="#0fa07f" fill-opacity="0.75" stroke="#0fa07f"/>
      <rect x="210" y="474" width="18" height="16" rx="3" fill="#0fa07f" fill-opacity="0.75" stroke="#0fa07f"/>
      <rect x="232" y="474" width="18" height="16" rx="3" fill="#0fa07f" fill-opacity="0.75" stroke="#0fa07f"/>
      <rect x="254" y="474" width="18" height="16" rx="3" fill="#e0930f" fill-opacity="0.65" stroke="#e0930f"/>
      <rect x="276" y="474" width="18" height="16" rx="3" fill="#e0930f" fill-opacity="0.65" stroke="#e0930f"/>
      <rect x="298" y="474" width="18" height="16" rx="3" fill="#e0930f" fill-opacity="0.65" stroke="#e0930f"/>
      <rect x="320" y="474" width="18" height="16" rx="3" fill="#e0930f" fill-opacity="0.65" stroke="#e0930f"/>
      <rect x="342" y="474" width="18" height="16" rx="3" fill="#e0930f" fill-opacity="0.65" stroke="#e0930f"/>
      <rect x="522" y="474" width="18" height="16" rx="3" fill="#0fa07f" fill-opacity="0.75" stroke="#0fa07f"/>
      <rect x="544" y="474" width="18" height="16" rx="3" fill="#0fa07f" fill-opacity="0.75" stroke="#0fa07f"/>
      <rect x="566" y="474" width="18" height="16" rx="3" fill="#0fa07f" fill-opacity="0.75" stroke="#0fa07f"/>
      <rect x="588" y="474" width="18" height="16" rx="3" fill="#0fa07f" fill-opacity="0.75" stroke="#0fa07f"/>
      <rect x="610" y="474" width="18" height="16" rx="3" fill="#0fa07f" fill-opacity="0.75" stroke="#0fa07f"/>
      <rect x="632" y="474" width="18" height="16" rx="3" fill="#0fa07f" fill-opacity="0.75" stroke="#0fa07f"/>
      <rect x="654" y="474" width="18" height="16" rx="3" fill="#0fa07f" fill-opacity="0.75" stroke="#0fa07f"/>
      <rect x="676" y="474" width="18" height="16" rx="3" fill="#0fa07f" fill-opacity="0.75" stroke="#0fa07f"/>
      <rect x="698" y="474" width="18" height="16" rx="3" fill="#0fa07f" fill-opacity="0.75" stroke="#0fa07f"/>
      <rect x="720" y="474" width="18" height="16" rx="3" fill="#0fa07f" fill-opacity="0.75" stroke="#0fa07f"/>
      <rect x="742" y="474" width="18" height="16" rx="3" fill="#e0930f" fill-opacity="0.65" stroke="#e0930f"/>
      <rect x="764" y="474" width="18" height="16" rx="3" fill="#e0930f" fill-opacity="0.65" stroke="#e0930f"/>
      <rect x="786" y="474" width="18" height="16" rx="3" fill="#e0930f" fill-opacity="0.65" stroke="#e0930f"/>
      <rect x="808" y="474" width="18" height="16" rx="3" fill="#e0930f" fill-opacity="0.65" stroke="#e0930f"/>
      <rect x="830" y="474" width="18" height="16" rx="3" fill="#e0930f" fill-opacity="0.65" stroke="#e0930f"/>
    </g>
    <g text-anchor="middle" font-size="9" font-weight="700">
      <text x="142" y="508" fill="#0fa07f">10 allowed</text>
      <text x="307" y="508" fill="#e0930f">5 denied</text>
      <text x="630" y="508" fill="#0fa07f">10 allowed</text>
      <text x="795" y="508" fill="#e0930f">5 denied</text>
    </g>
    <g fill="currentColor" font-size="8" opacity="0.85">
      <text x="34" y="526">15 requests at one instant — the burst capacity forgives</text>
      <text x="34" y="540">bucket 10 → 0 · the 11th request finds it empty</text>
      <text x="522" y="526">the same 15 again — only the refilled 10 get in</text>
      <text x="522" y="540">sustained throughput settles at rate = 10/sec</text>
    </g>
    <g fill="none" stroke="#0fa07f" stroke-width="1.8">
      <path d="M404 492 L496 492" marker-end="url(#p2l09a-arg)"/>
    </g>
    <g text-anchor="middle">
      <text x="450" y="470" font-size="8.5" font-weight="700" fill="#0fa07f">+10 tokens</text>
      <text x="450" y="482" font-size="7" fill="currentColor" opacity="0.75">1.0s × rate</text>
      <text x="450" y="508" font-size="7" fill="currentColor" opacity="0.7">capped at capacity</text>
    </g>
  </g>
  <text x="450" y="580" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">The whole limiter is two numbers per key — tokens and a timestamp — which is why one Redis script can do it atomically.</text>
  <text x="450" y="598" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.75">A silent reject trains clients to hammer harder: 429 + Retry-After tells them whether and when retrying makes sense.</text>
</svg>
```

Fire 100 requests just before `t=60` and 100 just after: the fixed window lets all
200 through — two aligned windows ~0.02s apart — while the sliding-window counter,
weighting the previous window, holds the burst near the true limit:

```console
$ python rate_limiters.py
=== the boundary burst: 100 req just before, 100 just after t=60 ===
  FixedWindow          allowed: 100 + 100 = 200  <-- ~2x the limit in ~0.02s
  SlidingWindowCounter allowed: 100 + 1   = 101  <-- burst stays near the limit

=== token bucket: burst up to capacity, then throttle to rate ===
  t=0.0  15 requests -> 10 allowed (bucket held 10), 5 denied
  t=1.0  15 requests -> 10 allowed (1s refilled 10 tokens)
```

The token bucket's two knobs are why it's the public-API favorite: `capacity` forgives
a burst (the 10 at `t=0`), `rate` sets the sustained ceiling (10/sec after). Note the
**lazy refill** — no background timer; tokens are recomputed from elapsed time on each
call, which is exactly what makes the Redis version a single script.

## Use It

Enforce in FastAPI middleware, which sees the authenticated principal and route:

```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import time

app = FastAPI()

@app.middleware("http")
async def rate_limit(request: Request, call_next):
    api_key = request.headers.get("X-API-Key", request.client.host)
    allowed, remaining, reset = await check_limit(f"rl:{api_key}")  # Redis Lua call
    if not allowed:
        return JSONResponse(
            status_code=429,
            content={"error": {"code": "rate_limited", "message": "Too many requests."}},
            headers={
                "Retry-After": str(max(1, reset - int(time.time()))),
                "X-RateLimit-Limit": "100",
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(reset),
            },
        )
    response = await call_next(request)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    return response
```

Duplicate the machine-readable retry hint into the body — some HTTP clients make
response headers awkward to reach from error-handling paths.

## Key takeaways

- Rate limiting serves four goals (capacity, fairness, abuse, cost) — layer limits
  at different scopes.
- Fixed window is cheapest but allows 2× at boundaries; **sliding window counter** is
  the practical default; **token bucket** separates sustained rate from burst.
- In-process counters multiply your limit by replica count; distributed limiting needs
  shared state (Redis `INCR`+`EXPIRE` made atomic with **Lua**) and an explicit
  **fail-open/fail-closed** decision.
- Communicate with `429` + `Retry-After` + `X-RateLimit-*`; clients retry with
  **backoff + full jitter** and honor `Retry-After`.
