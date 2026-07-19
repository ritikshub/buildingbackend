# Idempotency & Safe Retries

> On a timeout, the client can't tell whether the request failed or succeeded with the response lost. A blind retry double-charges. Idempotency keys are the fix.

**Type:** Build
**Languages:** Python
**Prerequisites:** [URLs, Verbs & Status Codes](../02-urls-verbs-status-codes/)
**Time:** ~60 minutes

## The Problem

A client sends `POST /v1/payments` and the connection drops before the response
arrives. The client cannot distinguish three worlds: (a) the request never reached
the server, (b) it reached and failed, (c) **it succeeded and the response was
lost**. The only safe behavior on timeout is to retry — but a blind retry in world
(c) charges the customer twice. GET/PUT/DELETE are idempotent by definition, so
retries are safe; POST creates, so each retry can create *again*. This isn't a rare
edge case — mobile networks, load-balancer failovers, and deploy-time connection
resets make world (c) a weekly event at any real volume.

## The Concept

### The Idempotency-Key header

The client attaches a unique key to the request, and the server guarantees that all
requests bearing the same key execute the operation **at most once**, replaying the
original response for duplicates. Stripe pioneered the convention:

```bash
curl -s https://api.stripe.com/v1/payment_intents \
  -u "$STRIPE_KEY:" \
  -H "Idempotency-Key: 8b2e5a70-4f0e-4c9c-9d3a-2f1b7c6d5e4f" \
  -d amount=90000 -d currency=inr
```

The reference design:

- The key is any client-chosen unique string (a UUID v4 is the norm), scoped per account.
- On first use, the server executes the request and **stores the key with the
  response** (status + body).
- A retry with the same key returns the stored response verbatim, without re-executing.
- Reusing a key with a **different payload** is an error — "same key, different
  request" is a client bug, not a retry.
- Keys are retained for a bounded window (Stripe: 24 hours).

The client's job: generate the key **once per logical operation** (when the user
taps "Pay"), persist it, and reuse the *same* key across every retry. A fresh key
per retry defeats the entire mechanism.

## Build It

Storage — a table keyed by `(tenant, idempotency_key)`:

```sql
CREATE TABLE idempotency_records (
    tenant_id        uuid        NOT NULL,
    idempotency_key  text        NOT NULL,
    request_hash     text        NOT NULL,   -- SHA-256 of method + path + body
    response_status  int,                     -- NULL while in flight
    response_body    jsonb,
    created_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, idempotency_key)
);
```

Flow, with the concurrency traps handled:

```python
import hashlib, json
from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse

def fingerprint(method: str, path: str, body: bytes) -> str:
    return hashlib.sha256(method.encode() + path.encode() + body).hexdigest()

@router.post("/payments", status_code=201)
async def create_payment(request: Request, idempotency_key: str = Header(alias="Idempotency-Key")):
    body = await request.body()
    fp = fingerprint("POST", "/payments", body)

    # 1. Atomically claim the key: INSERT ... ON CONFLICT DO NOTHING RETURNING *
    record = await try_insert_record(tenant_id, idempotency_key, fp)

    if record is None:                        # key already exists
        existing = await get_record(tenant_id, idempotency_key)
        if existing.request_hash != fp:       # same key, different payload -> client bug
            raise HTTPException(422, detail="Idempotency-Key reused with a different request body")
        if existing.response_status is None:  # original still executing
            raise HTTPException(409, detail="A request with this Idempotency-Key is in progress",
                                headers={"Retry-After": "2"})
        return JSONResponse(status_code=existing.response_status,   # replay stored response
                            content=existing.response_body)

    # 2. First execution: do the work, then persist the outcome.
    result = await payments_service.create(json.loads(body))
    await save_response(tenant_id, idempotency_key, status=201, body=result)
    return result
```

The design points that make it correct:

- **Claim-then-execute.** Inserting the key row *before* doing the work (atomically,
  via the primary-key constraint) is what makes two simultaneous duplicates safe: one
  INSERT wins, the loser sees the row and waits/replays. Checking "does the key
  exist?" and *then* inserting is a race.
- **Fingerprint the request** so a reused key with a different body is rejected, not
  silently answered with an unrelated stored response.
- **In-flight duplicates get `409` + `Retry-After`**, not a second execution.
- **Failures need a policy.** A 5xx should generally let the retry *re-execute* (clear
  the row) rather than replay the failure forever; deterministic 4xx failures can be
  replayed safely.
- **Expire rows** (a cron deleting rows older than 24h) so the table doesn't grow forever.

### Proving it: concurrent duplicates run once

`code/idempotency.py` implements this flow with the standard library — a
`threading.Lock` playing the role of the atomic `INSERT ... ON CONFLICT DO NOTHING`.
The claim is what serializes the race:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 650" width="100%" style="max-width:880px" role="img" aria-label="A sequence diagram of two concurrent requests carrying the same Idempotency-Key, drawn against three lifelines: Request A on the left, the idempotency store in the middle, and the duplicate Request B on the right. Request A claims key-abc with an atomic INSERT ON CONFLICT DO NOTHING RETURNING statement, and Request B sends the identical claim concurrently. A note over the store explains that only one INSERT wins, because the primary key of tenant id plus idempotency key serializes the race: claim-then-execute, not check-then-insert. The store replies to A that the claim succeeded so A executes, and replies to B with 409, the key exists and is already in flight, plus Retry-After 2, so B waits without executing. A then charges the card once, drawn as a self-directed call on its own lifeline, and saves the 201 response and body as charge ch_0001. A final note over B says a later retry with the same key replays the stored 201 and returns ch_0001 again with no new charge. The lesson's run of 5 concurrent requests with one key produces one executed request and four in-flight 409s, the card is charged exactly once, and reusing the same key with a different body is rejected with 422 because the request fingerprint, a SHA-256 of method plus path plus body, differs.">
  <defs>
    <marker id="p2l07a-arb" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
    <marker id="p2l07a-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p2l07a-ara" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Claim the key BEFORE you execute — that is what makes two duplicates safe</text>
  <text x="450" y="45" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9" fill="currentColor" opacity="0.78">The client mints one Idempotency-Key per logical operation (the 'Pay' tap), persists it, and reuses it on every retry</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <!-- actor headers -->
    <g fill="none" stroke-width="1.7" stroke-linejoin="round">
      <rect x="36" y="58" width="208" height="44" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="326" y="58" width="248" height="44" rx="8" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
      <rect x="652" y="58" width="216" height="44" rx="8" fill="#3553ff" fill-opacity="0.06" stroke="#3553ff" stroke-opacity="0.75" stroke-dasharray="5 4"/>
    </g>
    <g text-anchor="middle">
      <text x="140" y="78" font-size="11.5" font-weight="700" fill="#3553ff">Request A</text>
      <text x="140" y="93" font-size="8" fill="currentColor" opacity="0.8">POST /v1/payments · key-abc</text>
      <text x="450" y="78" font-size="11.5" font-weight="700" fill="#7c5cff">Idempotency store</text>
      <text x="450" y="93" font-size="8" fill="currentColor" opacity="0.8">PRIMARY KEY (tenant_id, idempotency_key)</text>
      <text x="760" y="78" font-size="11.5" font-weight="700" fill="#3553ff">Request B (duplicate)</text>
      <text x="760" y="93" font-size="8" fill="currentColor" opacity="0.8">same key-abc · 4 of 5 concurrent</text>
    </g>

    <!-- lifelines, broken where a note band sits over them -->
    <g stroke="currentColor" stroke-opacity="0.25" stroke-width="1.3" stroke-dasharray="4 5">
      <path d="M140 102 L140 512"/>
      <path d="M450 102 L450 200"/>
      <path d="M450 256 L450 512"/>
      <path d="M760 102 L760 448"/>
      <path d="M760 504 L760 512"/>
    </g>

    <!-- 1 · A claims the key -->
    <path d="M148 132 L442 132" fill="none" stroke="#3553ff" stroke-width="1.7" marker-end="url(#p2l07a-arb)"/>
    <text x="295" y="126" text-anchor="middle" font-size="10" font-weight="700" fill="#3553ff">1&#8195;·&#8195;claim key-abc</text>
    <text x="295" y="146" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">INSERT ... ON CONFLICT DO NOTHING RETURNING *</text>

    <!-- 2 · B claims the same key -->
    <path d="M752 176 L458 176" fill="none" stroke="#3553ff" stroke-width="1.7" marker-end="url(#p2l07a-arb)"/>
    <text x="605" y="170" text-anchor="middle" font-size="10" font-weight="700" fill="#3553ff">2&#8195;·&#8195;claim key-abc</text>
    <text x="605" y="190" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">same key, same body, arriving concurrently</text>

    <!-- note over the store -->
    <rect x="250" y="204" width="400" height="48" rx="6" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-opacity="0.55" stroke-width="1"/>
    <g text-anchor="middle">
      <text x="450" y="221" font-size="10" font-weight="700" fill="#7c5cff">Only one INSERT wins</text>
      <text x="450" y="235" font-size="8.5" fill="currentColor" opacity="0.9">claim-then-execute — NOT check-then-insert</text>
      <text x="450" y="248" font-size="8" fill="currentColor" opacity="0.75">checking 'does the key exist?' then inserting is a race</text>
    </g>

    <!-- 3 · the store tells A it won -->
    <path d="M442 280 L148 280" fill="none" stroke="#0fa07f" stroke-width="1.7" stroke-dasharray="6 4" marker-end="url(#p2l07a-arg)"/>
    <text x="295" y="274" text-anchor="middle" font-size="10" font-weight="700" fill="#0fa07f">3&#8195;·&#8195;claimed — you execute</text>
    <text x="295" y="294" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">row inserted, response_status = NULL (in flight)</text>

    <!-- 4 · the store tells B to wait -->
    <path d="M458 324 L752 324" fill="none" stroke="#e0930f" stroke-width="1.7" stroke-dasharray="6 4" marker-end="url(#p2l07a-ara)"/>
    <text x="605" y="318" text-anchor="middle" font-size="10" font-weight="700" fill="#e0930f">4&#8195;·&#8195;409 — exists, already in flight</text>
    <text x="605" y="338" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">Retry-After: 2 — wait, do not execute</text>

    <!-- B's waiting bar -->
    <rect x="756" y="332" width="8" height="114" rx="3" fill="#e0930f" fill-opacity="0.2" stroke="#e0930f" stroke-opacity="0.6" stroke-width="1"/>
    <g text-anchor="end">
      <text x="744" y="384" font-size="8.5" font-weight="700" fill="#e0930f">B is told to wait</text>
      <text x="744" y="397" font-size="8" fill="currentColor" opacity="0.75">Retry-After: 2 — it must not execute</text>
    </g>

    <!-- 5 · A charges the card, a self-call on its own lifeline -->
    <path d="M148 362 L224 362 L224 392 L150 392" fill="none" stroke="#0fa07f" stroke-width="1.7" stroke-linejoin="round" marker-end="url(#p2l07a-arg)"/>
    <text x="236" y="368" font-size="10" font-weight="700" fill="#0fa07f">5&#8195;·&#8195;charge the card once</text>
    <text x="236" y="384" font-size="8.5" fill="currentColor" opacity="0.85">at-most-once: card charged 1 time</text>
    <text x="236" y="399" font-size="8" fill="currentColor" opacity="0.75">the work runs only after the claim</text>

    <!-- 6 · A saves the response -->
    <path d="M148 428 L442 428" fill="none" stroke="#0fa07f" stroke-width="1.7" marker-end="url(#p2l07a-arg)"/>
    <text x="295" y="422" text-anchor="middle" font-size="10" font-weight="700" fill="#0fa07f">6&#8195;·&#8195;save 201 + body → ch_0001</text>
    <text x="295" y="442" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">response_status = 201, body stored</text>

    <!-- note over B -->
    <rect x="536" y="452" width="348" height="48" rx="6" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-opacity="0.55" stroke-width="1"/>
    <g text-anchor="middle">
      <text x="710" y="469" font-size="10" font-weight="700" fill="#0fa07f">A later retry now REPLAYS the saved 201</text>
      <text x="710" y="483" font-size="8.5" fill="currentColor" opacity="0.9">2nd: 201 replayed → ch_0001 (same charge id)</text>
      <text x="710" y="496" font-size="8" fill="currentColor" opacity="0.75">no new charge — the stored response is returned verbatim</text>
    </g>

    <!-- outcomes strip -->
    <text x="450" y="534" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">The three outcomes from the lesson's run — 5 concurrent requests, one Idempotency-Key</text>
    <g fill="none" stroke-width="1.6" stroke-linejoin="round">
      <rect x="40" y="542" width="264" height="56" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="318" y="542" width="264" height="56" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
      <rect x="596" y="542" width="264" height="56" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
    </g>
    <g text-anchor="middle">
      <text x="172" y="561" font-size="9.5" font-weight="700" fill="#0fa07f">executed: 1</text>
      <text x="172" y="575" font-size="8.5" fill="currentColor" opacity="0.9">201 Created → ch_0001</text>
      <text x="172" y="588" font-size="8" fill="currentColor" opacity="0.75">the card is charged exactly once</text>
      <text x="450" y="561" font-size="9.5" font-weight="700" fill="#e0930f">in-flight-409: 4</text>
      <text x="450" y="575" font-size="8.5" fill="currentColor" opacity="0.9">409 + Retry-After: 2</text>
      <text x="450" y="588" font-size="8" fill="currentColor" opacity="0.75">in progress — retry, never re-execute</text>
      <text x="728" y="561" font-size="9.5" font-weight="700" fill="#e0930f">422 — same key, different body</text>
      <text x="728" y="575" font-size="8.5" fill="currentColor" opacity="0.9">request fingerprint differs</text>
      <text x="728" y="588" font-size="8" fill="currentColor" opacity="0.75">SHA-256 of method + path + body</text>
    </g>

    <!-- takeaway -->
    <text x="450" y="620" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.85">Idempotency keys are for POST — GET, PUT and DELETE are already idempotent by contract; rows expire after ~24h.</text>
    <text x="450" y="635" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.75">A fresh key per retry defeats the entire mechanism: one logical operation, one key, every attempt.</text>
  </g>
</svg>
```

Fire five concurrent requests with one key and the card is charged exactly once; the
losers are told "in progress," and a later retry replays the stored response:

```console
$ python idempotency.py
=== 5 concurrent requests, one Idempotency-Key ===
  outcomes: {'in-flight-409': 4, 'executed': 1}
  card charged: 1 time(s)  <-- at-most-once holds
=== later retry with the same key -> replay, no new charge ===
  2nd: 201 replayed -> ch_0001  (same charge id)
=== same key, DIFFERENT body -> 422 (client bug, not a retry) ===
  -> 422 - Idempotency-Key reused with a different request body
```

Idempotency keys are for **POST**. Don't bother on GET/PUT/DELETE — they're already
idempotent by contract.

## Key takeaways

- POST retries are ambiguous because the success response can be lost; retrying blind
  double-acts.
- Accept an **`Idempotency-Key`**: atomically **claim the key, store the response,
  replay on duplicates**, reject same-key-different-body, expire after ~24h.
- Claim-then-execute (not check-then-insert) is what makes concurrent duplicates safe.
- Idempotency is *the* single most important reliability concept in API engineering —
  it reappears in rate limiting, webhooks, and event delivery.
