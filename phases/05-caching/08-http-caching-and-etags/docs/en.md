# HTTP Caching & ETags

> Browsers and CDNs cache billions of responses without any custom code — because the answer travels *with* the answer. A handful of HTTP headers tell every cache in the chain whether it may store a response, for how long, and how to check — for free — whether its copy is still good. This is the protocol lesson 7 was quietly built on.

**Type:** Build
**Languages:** Python
**Prerequisites:** [CDNs & Edge Caching](../07-cdns-and-edge-caching/), [HTTP Server from a TCP Socket](../../01-networking-and-protocols/09-http-server-from-tcp/)
**Time:** ~60 minutes

## The Problem

The browser cache and the CDN from lesson 7 are only useful if they know the rules: *Can
I store this response? For how long? And when it gets old, do I really have to download
the whole thing again to find out it didn't change?*

None of that can be guessed. A cache can't tell whether `/account` is safe to reuse for
five minutes or is different for every user; it can't know whether the 2 MB image it
downloaded an hour ago is still current. So HTTP builds the rules **into the protocol
itself**: the server attaches caching instructions to each response, and every compliant
cache — browser, proxy, CDN — obeys them. Standardized in **RFC 9111 (HTTP Caching)**,
this is the most widely deployed caching system on earth, and it runs on maybe six
headers. This lesson is those headers, and the clever trick — the **conditional request**
— that lets a cache revalidate a 2 MB response with a few hundred bytes.

## The Concept

### Two questions every cache asks

When a cache holds a copy and a request comes in, it answers two questions in order:

1. **Is my copy still _fresh_?** If yes, serve it immediately — **zero** network. This is
   governed by *freshness* headers.
2. **If it's stale, is my copy still _valid_ (unchanged)?** Rather than blindly
   re-download, *ask the server* "has it changed?" This is *validation*, and if the answer
   is "no," the cache reuses what it already has.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 860 604" width="100%" style="max-width:840px" role="img" aria-label="The two questions a cache asks, drawn as a flowchart with two decision diamonds. A request arrives at the cache. First question, freshness: is the copy still within its max-age? If yes, the cache serves the stored copy immediately and zero bytes cross the network — the server is never contacted. If no, the copy is stale, and stale does not mean re-download: the cache sends a conditional request, GET slash img with the header If-None-Match set to the stored ETag a1b2c3, about three hundred bytes of headers with no body. Second question, validation: did the content actually change on the server? If it did not, the server answers 304 Not Modified with no body at all, the cache reuses the two megabytes it already holds, and the whole exchange costs roughly four hundred and fifty bytes. Only if the content really changed does the server send 200 OK with the full new body, and the cache replaces its copy and stores the new ETag, paying the full two megabytes.">
  <defs>
    <marker id="p5l8a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p5l8a-arg" markerUnits="userSpaceOnUse" markerWidth="12" markerHeight="11" refX="11" refY="5" orient="auto"><path d="M0,0 L11,5 L0,10 Z" fill="#0fa07f"/></marker>
    <marker id="p5l8a-arw" markerUnits="userSpaceOnUse" markerWidth="12" markerHeight="11" refX="11" refY="5" orient="auto"><path d="M0,0 L11,5 L0,10 Z" fill="#e0930f"/></marker>
  </defs>
  <text x="430" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Stale does not mean re-download — it means go ask</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- arrows -->
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M430 92 L430 122" marker-end="url(#p5l8a-ar)"/>
    </g>
    <g fill="none" stroke="#0fa07f" stroke-width="1.6" stroke-linejoin="round">
      <path d="M535 172 L616 172" marker-end="url(#p5l8a-arg)"/>
      <path d="M330 396 L170 396 L170 464" marker-end="url(#p5l8a-arg)"/>
    </g>
    <g fill="none" stroke="#e0930f" stroke-linejoin="round">
      <path d="M430 218 L430 248" stroke-width="1.6" marker-end="url(#p5l8a-arw)"/>
      <path d="M430 312 L430 346" stroke-width="1.6" marker-end="url(#p5l8a-arw)"/>
      <path d="M530 396 L690 396 L690 464" stroke-width="2.8" marker-end="url(#p5l8a-arw)"/>
    </g>

    <!-- process boxes -->
    <g stroke-width="1.8" stroke-linejoin="round">
      <rect x="320" y="48" width="220" height="44" rx="10" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
      <rect x="620" y="140" width="220" height="64" rx="10" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="280" y="252" width="300" height="60" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
      <rect x="40" y="468" width="260" height="82" rx="10" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="560" y="468" width="260" height="82" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
    </g>

    <!-- decision diamonds -->
    <g stroke-width="1.8" stroke-linejoin="round" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f">
      <path d="M430 126 L535 172 L430 218 L325 172 Z"/>
      <path d="M430 350 L530 396 L430 442 L330 396 Z"/>
    </g>

    <!-- stage labels -->
    <g font-size="9.5" font-weight="700" fill="currentColor" opacity="0.6" text-anchor="end">
      <text x="315" y="176">1 · FRESHNESS</text>
      <text x="270" y="286">2 · VALIDATION</text>
    </g>

    <!-- branch labels -->
    <g font-size="9.5" font-weight="700">
      <text x="575" y="166" text-anchor="middle" fill="#0fa07f">yes</text>
      <text x="440" y="238" text-anchor="start" fill="#e0930f">no (stale)</text>
      <text x="250" y="388" text-anchor="middle" fill="#0fa07f">no — unchanged</text>
      <text x="610" y="388" text-anchor="middle" fill="#e0930f">yes — changed</text>
    </g>

    <!-- diamond text -->
    <g text-anchor="middle" font-size="10" font-weight="700" fill="currentColor">
      <text x="430" y="168">Copy still fresh?</text>
      <text x="430" y="182">(within max-age)</text>
      <text x="430" y="392">Changed on</text>
      <text x="430" y="406">the server?</text>
    </g>

    <!-- box text -->
    <g text-anchor="middle" fill="currentColor">
      <text x="430" y="66" font-size="10.5">A request arrives at the cache</text>
      <text x="430" y="80" font-size="10.5">(browser, proxy or CDN)</text>

      <text x="730" y="160" font-size="10.5" font-weight="700" fill="#0fa07f">Serve the cached copy</text>
      <text x="730" y="176" font-size="10">0 bytes over the network</text>
      <text x="730" y="192" font-size="9" opacity="0.75">the server is never contacted</text>

      <text x="430" y="272" font-size="10.5" font-weight="700" fill="#e0930f">Don't re-download — go ASK</text>
      <text x="430" y="288" font-size="10">GET /img&#8195;If-None-Match: "a1b2c3"</text>
      <text x="430" y="303" font-size="9" opacity="0.75">a conditional request: ~300 bytes of headers</text>

      <text x="170" y="490" font-size="11" font-weight="700" fill="#0fa07f">304 Not Modified</text>
      <text x="170" y="507" font-size="10">no body at all</text>
      <text x="170" y="523" font-size="10">reuse the 2 MB you have</text>
      <text x="170" y="539" font-size="9" opacity="0.75">total cost ≈ 450 bytes</text>

      <text x="690" y="490" font-size="11" font-weight="700" fill="#e0930f">200 OK + new body</text>
      <text x="690" y="507" font-size="10">replace the copy and</text>
      <text x="690" y="523" font-size="10">store the new ETag</text>
      <text x="690" y="539" font-size="9" opacity="0.75">total cost = the full 2 MB</text>
    </g>

    <!-- takeaway -->
    <text x="430" y="576" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">Freshness skips the network entirely; validation skips only the payload.</text>
    <text x="430" y="594" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.75">Both green paths are nearly free — and for most stale copies, the answer really is 304.</text>
  </g>
</svg>
```

Freshness avoids the network entirely; validation avoids the *payload*. Together they
turn most repeat requests into either nothing or almost nothing.

### Freshness: Cache-Control

`Cache-Control` is the master switch, and its directives compose. The ones that earn
their keep:

| Directive | Meaning |
|---|---|
| `max-age=N` | Fresh for N seconds, in any cache |
| `s-maxage=N` | Fresh for N seconds in **shared** caches (CDN/proxy); overrides `max-age` there |
| `public` | Any cache may store it |
| `private` | Only the user's **browser** may store it — never a shared cache |
| `no-cache` | May store, but **must revalidate** before every reuse (not "don't cache"!) |
| `no-store` | Never store at all — for secrets and truly per-request data |
| `immutable` | Won't change while fresh — don't even revalidate on a reload |
| `stale-while-revalidate=N` | Serve stale up to N s while refreshing in the **background** |
| `stale-if-error=N` | Serve stale up to N s if the origin is erroring |

The two most-misunderstood: `no-cache` does **not** mean "don't cache" — it means "cache,
but check with me before each reuse." The one that means don't-cache is `no-store`. And
`s-maxage` is how you tell a CDN to cache for an hour while telling browsers (`max-age`) to
cache for a minute — the shared/private split from lesson 7, expressed in one header. Note
`stale-while-revalidate` is exactly the serve-stale-and-refresh stampede defense of lesson
6, standardized as an HTTP directive.

### Validation: ETags and the 304

When a fresh lifetime runs out, the copy is *probably* still correct — most things don't
change every `max-age` window. Re-downloading 2 MB to confirm "yep, identical" is pure
waste. **Validators** fix this. The server tags each response with a version marker; the
cache echoes it back on revalidation; the server compares and, if nothing changed,
answers **`304 Not Modified`** — a tiny, bodyless response that says "reuse what you have."

Two validators exist:

- **`ETag`** (Entity Tag) — an opaque version id, usually a hash of the content, e.g.
  `ETag: "a1b2c3"`. The cache stores it and later sends **`If-None-Match: "a1b2c3"`**.
  Match → `304`. This is the strong, precise validator: any byte change flips the hash.
  A `W/"..."` prefix marks a **weak** ETag ("semantically equivalent, not byte-identical" —
  fine for revalidation, not for byte-range requests).
- **`Last-Modified`** — a timestamp; the cache sends **`If-Modified-Since:`** that date.
  Cheaper to produce but coarse (one-second resolution) and fragile (a file touched
  without content change looks modified). Prefer `ETag` when you can compute one; send both
  and caches use the stronger.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 860 528" width="100%" style="max-width:840px" role="img" aria-label="The revalidation exchange drawn as a sequence between two actors, a Cache and a Server. The cache already holds a two megabyte copy of slash img whose max-age has expired, and it stored the validator ETag a1b2c3 alongside it. The cache sends one conditional request to the server: GET slash img with the header If-None-Match set to a1b2c3 — headers only, about three hundred bytes, no body. The server then takes one of two branches. In the unchanged branch, the server's hash is still a1b2c3, so it replies 304 Not Modified with no body, roughly one hundred and fifty bytes of status line and headers, and the cache reuses the two megabytes it already has — nothing is re-downloaded. In the changed branch, the content genuinely moved, so the server replies 200 OK with the full new body and a new ETag d4e5f6, drawn as a much thicker arrow because it carries the whole two megabytes, and the cache replaces its copy and stores the new validator. The asymmetry is the point: a small question can avoid a very large answer.">
  <defs>
    <marker id="p5l8b-ar" markerUnits="userSpaceOnUse" markerWidth="12" markerHeight="11" refX="11" refY="5" orient="auto"><path d="M0,0 L11,5 L0,10 Z" fill="currentColor"/></marker>
    <marker id="p5l8b-arg" markerUnits="userSpaceOnUse" markerWidth="12" markerHeight="11" refX="11" refY="5" orient="auto"><path d="M0,0 L11,5 L0,10 Z" fill="#0fa07f"/></marker>
    <marker id="p5l8b-arw" markerUnits="userSpaceOnUse" markerWidth="17" markerHeight="15" refX="15" refY="7" orient="auto"><path d="M0,0 L15,7 L0,14 Z" fill="#e0930f"/></marker>
  </defs>
  <text x="430" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">One small question decides whether 2 MB has to move</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- alt section backgrounds -->
    <rect x="56" y="200" width="748" height="142" rx="10" fill="#0fa07f" fill-opacity="0.05"/>
    <rect x="56" y="356" width="748" height="118" rx="10" fill="#e0930f" fill-opacity="0.06"/>

    <!-- actor headers -->
    <g stroke-width="1.7" stroke-linejoin="round">
      <rect x="140" y="44" width="140" height="30" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="580" y="44" width="140" height="30" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    </g>
    <text x="210" y="63" text-anchor="middle" font-size="11.5" font-weight="700" fill="#0fa07f">Cache</text>
    <text x="650" y="63" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">Server</text>

    <!-- lifelines -->
    <g stroke="currentColor" stroke-opacity="0.25" stroke-width="1.3" stroke-dasharray="4 5">
      <path d="M210 74 L210 474"/>
      <path d="M650 74 L650 474"/>
    </g>

    <!-- Note over Cache: what it already holds -->
    <rect x="52" y="84" width="316" height="40" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-opacity="0.6" stroke-width="1"/>
    <g text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.9">
      <text x="210" y="100">holds /img — 2 MB — max-age has expired</text>
      <text x="210" y="115">stored validator:  ETag "a1b2c3"</text>
    </g>

    <!-- the conditional request -->
    <g fill="none" stroke="currentColor" stroke-width="1.7">
      <path d="M216 166 L644 166" marker-end="url(#p5l8b-ar)"/>
    </g>
    <text x="430" y="159" text-anchor="middle" font-size="10.5" fill="currentColor">GET /img&#8195;If-None-Match: "a1b2c3"</text>
    <text x="430" y="182" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.75">a conditional request — headers only, ~300 bytes, no body</text>

    <!-- alt: unchanged -->
    <rect x="72" y="206" width="716" height="22" rx="6" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-opacity="0.6" stroke-width="1"/>
    <text x="430" y="221" text-anchor="middle" font-size="9.5" font-weight="700" fill="currentColor" opacity="0.9">alt · UNCHANGED — the server's hash is still a1b2c3</text>
    <g fill="none" stroke="#0fa07f" stroke-width="1.6">
      <path d="M644 268 L216 268" marker-end="url(#p5l8b-arg)"/>
    </g>
    <text x="430" y="261" text-anchor="middle" font-size="10.5" font-weight="700" fill="#0fa07f">304 Not Modified — no body</text>
    <text x="430" y="285" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.75">~150 bytes: a status line and a few headers</text>
    <rect x="52" y="296" width="316" height="38" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-opacity="0.6" stroke-width="1"/>
    <g text-anchor="middle" font-size="9.5" fill="currentColor">
      <text x="210" y="312" opacity="0.9">reuse the 2 MB it already has</text>
      <text x="210" y="327" opacity="0.75">nothing was re-downloaded</text>
    </g>

    <!-- else: changed -->
    <rect x="72" y="362" width="716" height="22" rx="6" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f" stroke-opacity="0.6" stroke-width="1"/>
    <text x="430" y="377" text-anchor="middle" font-size="9.5" font-weight="700" fill="currentColor" opacity="0.9">else · CHANGED — the content really moved</text>
    <g fill="none" stroke="#e0930f" stroke-width="3">
      <path d="M644 414 L216 414" marker-end="url(#p5l8b-arw)"/>
    </g>
    <text x="430" y="404" text-anchor="middle" font-size="10.5" font-weight="700" fill="#e0930f">200 OK — full new body + new ETag "d4e5f6"</text>
    <text x="430" y="433" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.75">the whole 2 MB — paid only when it genuinely changed</text>
    <rect x="52" y="440" width="316" height="26" rx="6" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f" stroke-opacity="0.6" stroke-width="1"/>
    <text x="210" y="457" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.9">replace the copy, store the new ETag</text>

    <!-- takeaway -->
    <text x="430" y="496" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">The question costs ~300 bytes; the "nothing changed" answer costs ~150.</text>
    <text x="430" y="513" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.75">Together that is ~0.02% of the 2 MB they just avoided moving — revalidation ships headers, not payloads.</text>
  </g>
</svg>
```

The payoff is dramatic: a revalidation of a large-but-unchanged resource costs a few
hundred bytes of headers instead of the whole payload. Multiply across every image, font,
and script on every page load, for every returning visitor.

### Vary: keying the cache correctly

One response URL can have several representations — gzip vs. brotli, English vs. French.
`Vary` lists the **request** headers that change the response, so a cache stores and
matches them separately: `Vary: Accept-Encoding` keeps the gzip and brotli copies
distinct. This is the same cache-key concern from lesson 7 — and the same trap: `Vary:
User-Agent` explodes into thousands of near-duplicate entries and destroys the hit ratio.
Vary on the *fewest* headers that genuinely change the bytes.

## Build It

An HTTP server in Python that sets `Cache-Control` and a content-hash `ETag`, and correctly
answers a conditional request with `304` when the client's copy is still current — the
whole freshness-plus-validation contract in one handler. Standard library only
(`http.server` to serve, `http.client` to drive it).

```python
# HTTP caching: Cache-Control freshness + ETag validation with 304 Not Modified.
# Ref: phases/05-caching/08-http-caching-and-etags/docs/en.md
# Spec: RFC 9111 (HTTP Caching), RFC 9110 §8.8 (validators / ETag).
import hashlib
import http.client
import http.server
import socketserver
import threading

BODY = b'{"id":42,"name":"Ada"}'  # the resource representation

def etag_of(body: bytes) -> str:   # strong, quoted ETag — any byte change flips the hash
    return '"' + hashlib.sha256(body).hexdigest()[:16] + '"'

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        etag = etag_of(BODY)
        # Conditional request: the cache already holds a version — is it current?
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)                       # reuse your copy, send NO body
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "public, max-age=60")
            self.end_headers()
            return
        self.send_response(200)                           # full payload
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "public, max-age=60")  # fresh 60s, any cache
        self.send_header("ETag", etag)                    # version id for revalidation
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)

    def log_message(self, *args):                          # silence per-request logging
        pass

def fetch(host, port, headers=None):
    conn = http.client.HTTPConnection(host, port)          # http.client does NOT raise on 304
    conn.request("GET", "/", headers=headers or {})
    resp = conn.getresponse()
    status, etag, nbytes = resp.status, resp.getheader("ETag"), len(resp.read())
    conn.close()
    return status, etag, nbytes

def main():
    srv = socketserver.TCPServer(("127.0.0.1", 0), Handler)  # real server, ephemeral port
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    host, port = srv.server_address

    # 1) Cold request: no validator yet -> 200 with the full body + an ETag.
    status, etag, n = fetch(host, port)
    print(f"GET                 → {status}  ETag={etag}  body={n} bytes")

    # 2) Revalidation: echo the ETag back; unchanged -> 304 with an empty body.
    status, _, n = fetch(host, port, {"If-None-Match": etag})
    print(f"GET (If-None-Match) → {status}  body={n} bytes (payload skipped)")

    srv.shutdown()

if __name__ == "__main__":
    main()
```

Run `python main.py`:

```console
GET                 → 200  ETag="60ee12d6d5078508"  body=22 bytes
GET (If-None-Match) → 304  body=0 bytes (payload skipped)
```

The second request carried the ETag, the server saw it matched, and replied `304` with an
empty body. On a real 2 MB asset that second exchange is a few hundred bytes instead of
two megabytes — and your handler never had to serialize or send the payload.

## Use It

You rarely write this by hand. Static file servers (nginx, Python's `http.server`,
Starlette/FastAPI's `StaticFiles`, WhiteNoise) generate `ETag` and `Last-Modified` from the
file's content/mtime and answer conditional requests automatically. Your job is to declare
the **policy** per response type. The battle-tested recipes:

```http
# Fingerprinted static asset (app.9f8c2a.js) — never changes under this URL.
Cache-Control: public, max-age=31536000, immutable

# HTML shell — must always reflect the latest deploy, but revalidate cheaply.
Cache-Control: no-cache
ETag: "build-1a2b3c"

# Cacheable API response, longer at the CDN than in the browser, herd-safe.
Cache-Control: public, max-age=10, s-maxage=60, stale-while-revalidate=30

# Anything personalized or secret — never in a shared cache, never stored.
Cache-Control: private, no-store
```

The mental model that ties the phase together:

- **`immutable` + a fingerprinted URL** is the gold standard for static assets — cache
  forever, change the URL to change the content (lesson 7's cache-busting, enforced by a
  header).
- **`no-cache` + `ETag`** for HTML/JSON that must be current but rarely changes: the cache
  revalidates every time, but pays only a `304` when nothing moved.
- **`s-maxage` + `stale-while-revalidate`** pushes work to the CDN and applies the
  serve-stale stampede defense (lesson 6) at the edge (lesson 7) — one line of headers
  standing in for a lot of the machinery you built by hand this phase.
- **`private, no-store`** for authenticated data — the guardrail against the shared-cache
  data-leak from lesson 7.

That closes the loop: the in-process LRU, Redis, cache-aside, TTLs, single-flight, CDNs,
and now the HTTP headers are all the same idea — *keep a copy of the answer close, and be
disciplined about when it stops being true* — applied at every layer from a CPU cache line
to a continent.

## Key takeaways

- HTTP bakes caching into the protocol (**RFC 9111**): the server attaches instructions to
  each response and every browser, proxy, and CDN obeys them — the most widely deployed
  caching system in existence.
- Caches answer two questions: **freshness** (`Cache-Control: max-age`/`s-maxage` — serve
  with zero network) and **validation** (revalidate a stale copy without re-downloading).
- **ETags** (content-hash version ids via `If-None-Match`) and **Last-Modified** (via
  `If-Modified-Since`) enable the **`304 Not Modified`** exchange — reuse a large unchanged
  response for the cost of a few header bytes.
- Know the traps: `no-cache` means *revalidate*, not *don't store* (that's `no-store`);
  `s-maxage` is the CDN-only TTL; `Vary` on too many headers shatters the hit ratio.
- Reach for the recipes: **`immutable` + fingerprinted URL** for static assets, **`no-cache`
  + `ETag`** for must-be-current HTML, **`s-maxage` + `stale-while-revalidate`** for
  CDN-cacheable APIs, **`private, no-store`** for anything authenticated.

**Phase complete.** You've built caching from the CPU line to the edge: why and where to
cache, an O(1) LRU, Redis and its protocol, the aside/through/behind strategies,
invalidation and TTLs, stampede defenses, CDNs, and the HTTP headers that govern it all.
The fastest query really is the one you never run — and now you know how to never run it.
