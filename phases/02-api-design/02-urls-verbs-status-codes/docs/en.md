# URLs, Verbs & Status Codes

> The method + URI pair replaces an infinite vocabulary of RPC function names with a small grammar everything already understands.

**Type:** Build
**Languages:** Python
**Prerequisites:** [REST Principles & Resource Modeling](../01-rest-principles-resource-modeling/)
**Time:** ~60 minutes

## The Problem

Once resources are nouns, the verbs come from HTTP. But which method creates vs.
replaces vs. patches? What's the difference between *safe* and *idempotent*, and
why do proxies care? And which status code do you actually return? Getting these
right is what moves an API from Richardson level 1 to level 2.

## The Concept

### Mapping CRUD onto HTTP

| Method | On `/orders` | On `/orders/{id}` | Safe | Idempotent | Success |
|---|---|---|---|---|---|
| GET | List | Fetch one | Yes | Yes | 200 |
| POST | Create | (sub-actions) | No | **No** | 201 + `Location` |
| PUT | (rare) | Replace entirely | No | Yes | 200 / 204 |
| PATCH | — | Partial update | No | No (by default) | 200 |
| DELETE | (dangerous) | Delete | No | Yes | 204 |

*Safe* = no state change. *Idempotent* = N identical requests have the same effect
as one. These are defined in RFC 9110 and matter operationally: proxies and
clients may auto-retry idempotent requests, and caches only ever cache safe ones.

### Create — POST

```http
POST /v1/orders HTTP/1.1
Content-Type: application/json

{"customer_id": "cus_8xkP2m", "items": [{"menu_item_id": "mi_551", "quantity": 2}]}
```
```http
HTTP/1.1 201 Created
Location: /v1/orders/ord_7hQ2df

{"id": "ord_7hQ2df", "status": "pending", "total_amount": 90000, "currency": "INR",
 "created_at": "2026-07-11T08:30:00Z"}
```

Conventions worth copying: **`201 Created`** (not 200), a **`Location`** header
pointing at the new resource, and the **full created representation** in the body
so the client needs no follow-up GET. Server-generated fields (`id`, `created_at`)
appear even though the client never sent them.

### Read — GET

GET must **never mutate state** — no `GET /orders/7/cancel`. Crawlers, prefetchers,
and cache-warming proxies issue GETs freely on the assumption they're safe.

### Replace vs partial update — PUT vs PATCH

**PUT replaces the entire resource.** Omitted fields are removed — that's the
contract. Idempotent: sending the same document five times = once.

**PATCH applies a partial modification.** Two standardized formats:

- **JSON Merge Patch (RFC 7396)**, `application/merge-patch+json`: a document
  shaped like the target; present fields are set, fields set to `null` are
  **removed**. Sharp edge: you can't distinguish "set to null" from "delete," and
  arrays are replaced wholesale.
- **JSON Patch (RFC 6902)**, `application/json-patch+json`: an ordered op list
  (`add`/`remove`/`replace`/`move`/`copy`/`test`) addressed by JSON Pointer. The
  `test` op makes a patch conditional (optimistic concurrency). More power, more
  complexity — reach for it only when clients need surgical array edits.

### Delete — DELETE

`DELETE /orders/7` → `204 No Content`. Idempotent in *effect* (the resource ends
up gone), but the second call may legitimately return `404` — idempotency is about
server state, not identical status codes. Many domains prefer soft deletion
(a `deleted_at` timestamp) returning `404`/`410 Gone` while the row survives for audit.

### Status codes that matter

| Situation | Code |
|---|---|
| Malformed request (bad JSON/types) | 400 Bad Request |
| Missing/invalid credentials | 401 Unauthorized (send `WWW-Authenticate`) |
| Authenticated but not allowed | 403 Forbidden |
| Resource doesn't exist (or is hidden from you) | 404 Not Found |
| Method not supported here | 405 (include `Allow`) |
| State conflict (collision, duplicate, illegal transition) | 409 Conflict |
| Well-formed but semantically invalid | 422 Unprocessable Content |
| Rate limited | 429 (send `Retry-After`) |
| Server bug | 500 (never leak stack traces) |
| Upstream failed / overloaded | 502 / 503 |

Reserve **5xx strictly for "the server is at fault"** — alerting and client retry
logic key off that boundary.

## Build It

`code/rest_router.py` implements this whole grid on `http.server` — no framework, so
every decision is visible. The core is a dispatch table: a path is either a
*collection* (`/orders`) or a *member* (`/orders/{id}`), and each kind allows a fixed
set of methods. That table *is* the `405 + Allow` contract.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 612" width="100%" style="max-width:880px" role="img" aria-label="How the router turns one request into one status code. A request carrying a method and a path enters a single decision: what shape is the path? Three branches leave it. If the path is /orders it is the collection, which allows GET and POST. If the path is /orders/{id} it is one member of that collection, which allows GET, PUT, PATCH and DELETE. Anything else returns 404 not_found immediately. Inside the collection lane, a method in the allowed set succeeds: GET returns 200 with the list, and POST returns 201 with a Location header pointing at the new order, plus the full created representation so the client needs no follow-up GET. A method not in the set returns 405 Method Not Allowed with the header Allow: GET, POST. Inside the member lane there are three branches. If the id names no order that exists, the answer is 404 not_found, checked before the method. If the method is in the allowed set, GET returns 200, PUT returns 200 after replacing the whole resource, PATCH returns 200 after merging, and DELETE returns 204. Deleting the same order twice returns 404 the second time, which is idempotency in effect, because the resource ends up gone either way. A method not in the set returns 405 with the header Allow: GET, PUT, PATCH, DELETE. Every success terminal is drawn green and every 4xx terminal amber, because a 4xx means the client is at fault. A strip at the bottom records the RFC 9110 properties of each method: GET is safe and idempotent; POST is neither; PUT is idempotent but not safe; PATCH is neither by default; DELETE is idempotent but not safe. That matters because proxies and clients may auto-retry idempotent requests, and caches only ever cache safe ones.">
  <defs>
    <marker id="p2l02a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p2l02a-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p2l02a-arm" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">A path is either a collection or one member of it — and that shape is the contract</text>
  <text x="450" y="44" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.8">The dispatch table in rest_router.py is exactly this decision — and 405 + Allow is that table, reported back</text>

  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g fill="none" stroke-linejoin="round" stroke-width="2">
      <rect x="320" y="56" width="260" height="42" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <path d="M450 112 L554 150 L450 188 L346 150 Z" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.6"/>
      <rect x="390" y="240" width="120" height="60" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
    </g>

    <g text-anchor="middle" fill="currentColor">
      <text x="450" y="76" font-size="11" font-weight="700" fill="#3553ff">request: method + path</text>
      <text x="450" y="91" font-size="7.5" opacity="0.8">e.g. POST /orders · DELETE /orders/ord_7hQ2df</text>
      <text x="450" y="146" font-size="12" font-weight="700">path shape?</text>
      <text x="450" y="161" font-size="7.5" opacity="0.75">one dispatch table lookup</text>
      <text x="450" y="268" font-size="15" font-weight="700" fill="#e0930f">404</text>
      <text x="450" y="286" font-size="8.5" fill="#e0930f">not_found</text>
      <text x="450" y="316" font-size="7.5" opacity="0.7">the path matches</text>
      <text x="450" y="327" font-size="7.5" opacity="0.7">neither shape</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.7">
      <path d="M450 98 L450 108" marker-end="url(#p2l02a-ar)"/>
      <path d="M344 150 L196 150 L196 199" marker-end="url(#p2l02a-ar)"/>
      <path d="M556 150 L704 150 L704 199" marker-end="url(#p2l02a-ar)"/>
    </g>
    <g fill="none" stroke="#e0930f" stroke-width="1.7">
      <path d="M450 190 L450 233" marker-end="url(#p2l02a-arm)"/>
    </g>
    <g font-size="9" font-weight="700">
      <text x="270" y="143" text-anchor="middle" fill="#3553ff">/orders</text>
      <text x="630" y="143" text-anchor="middle" fill="#3553ff">/orders/{id}</text>
      <text x="458" y="206" font-size="8" fill="#e0930f">anything</text>
      <text x="458" y="217" font-size="8" fill="#e0930f">else</text>
    </g>

    <g fill="none" stroke-linejoin="round" stroke-width="1.6">
      <rect x="18" y="206" width="356" height="264" rx="12" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.35"/>
      <rect x="526" y="206" width="356" height="264" rx="12" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.35"/>
    </g>

    <g>
      <rect x="30" y="217" width="40" height="7" rx="2" fill="#3553ff" fill-opacity="0.5"/>
      <rect x="30" y="228" width="40" height="7" rx="2" fill="#3553ff" fill-opacity="0.5"/>
      <rect x="30" y="239" width="40" height="7" rx="2" fill="#3553ff" fill-opacity="0.5"/>
      <rect x="538" y="217" width="40" height="7" rx="2" fill="none" stroke="#3553ff" stroke-opacity="0.45" stroke-width="1"/>
      <rect x="538" y="228" width="40" height="7" rx="2" fill="#3553ff" fill-opacity="0.5"/>
      <rect x="538" y="239" width="40" height="7" rx="2" fill="none" stroke="#3553ff" stroke-opacity="0.45" stroke-width="1"/>
    </g>

    <g fill="currentColor">
      <text x="84" y="226" font-size="11.5" font-weight="700">COLLECTION</text>
      <text x="84" y="241" font-size="11.5" font-weight="700" fill="#3553ff">/orders</text>
      <text x="84" y="256" font-size="8" opacity="0.8">the set of all orders</text>
      <text x="592" y="226" font-size="11.5" font-weight="700">MEMBER</text>
      <text x="592" y="241" font-size="11.5" font-weight="700" fill="#3553ff">/orders/{id}</text>
      <text x="592" y="256" font-size="8" opacity="0.8">one order in that set — /orders/ord_7hQ2df</text>
    </g>

    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="76" y="270" width="240" height="42" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
      <rect x="584" y="270" width="240" height="42" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
    </g>
    <g text-anchor="middle" fill="currentColor">
      <text x="196" y="289" font-size="11" font-weight="700">allows: GET, POST</text>
      <text x="196" y="304" font-size="8" opacity="0.8">list the set · create in it</text>
      <text x="704" y="289" font-size="10" font-weight="700">allows: GET, PUT, PATCH, DELETE</text>
      <text x="704" y="304" font-size="8" opacity="0.8">fetch · replace · merge · delete</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-opacity="0.5" stroke-width="1.5">
      <path d="M196 312 L196 332"/>
      <path d="M704 312 L704 332"/>
    </g>
    <g fill="none" stroke="#0fa07f" stroke-width="1.7">
      <path d="M196 332 L128 332 L128 355" marker-end="url(#p2l02a-arg)"/>
      <path d="M704 332 L704 355" marker-end="url(#p2l02a-arg)"/>
    </g>
    <g fill="none" stroke="#e0930f" stroke-width="1.7">
      <path d="M196 332 L299 332 L299 355" marker-end="url(#p2l02a-arm)"/>
      <path d="M704 332 L582 332 L582 355" marker-end="url(#p2l02a-arm)"/>
      <path d="M704 332 L826 332 L826 355" marker-end="url(#p2l02a-arm)"/>
    </g>
    <g font-size="8" font-weight="700">
      <text x="162" y="327" text-anchor="middle" fill="#0fa07f">method in set</text>
      <text x="248" y="327" text-anchor="middle" fill="#e0930f">method not in set</text>
      <text x="643" y="327" text-anchor="middle" fill="#e0930f">id missing</text>
      <text x="765" y="327" text-anchor="middle" fill="#e0930f">method not in set</text>
      <text x="712" y="349" fill="#0fa07f">method in set</text>
    </g>

    <g fill="none" stroke-linejoin="round" stroke-width="1.9">
      <rect x="30" y="360" width="196" height="96" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="236" y="360" width="126" height="96" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
      <rect x="538" y="360" width="88" height="96" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
      <rect x="636" y="360" width="136" height="96" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="782" y="360" width="88" height="96" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
    </g>

    <g text-anchor="middle" fill="currentColor">
      <text x="128" y="381" font-size="9.5" font-weight="700" fill="#0fa07f">GET → 200 list</text>
      <text x="128" y="397" font-size="9.5" font-weight="700" fill="#0fa07f">POST → 201 + Location</text>
      <text x="128" y="417" font-size="7.5" opacity="0.85">Location: /v1/orders/ord_7hQ2df</text>
      <text x="128" y="430" font-size="7.5" opacity="0.85">plus the full created body</text>
      <text x="128" y="443" font-size="7.5" opacity="0.85">so no follow-up GET is needed</text>

      <text x="299" y="383" font-size="14" font-weight="700" fill="#e0930f">405</text>
      <text x="299" y="399" font-size="7.5" opacity="0.9">Method Not Allowed</text>
      <text x="299" y="419" font-size="8.5" font-weight="700" fill="#e0930f">Allow: GET, POST</text>
      <text x="299" y="435" font-size="7" opacity="0.8">the Allow header is</text>
      <text x="299" y="446" font-size="7" opacity="0.8">required, not optional</text>

      <text x="582" y="385" font-size="14" font-weight="700" fill="#e0930f">404</text>
      <text x="582" y="401" font-size="7.5" opacity="0.9">not_found</text>
      <text x="582" y="422" font-size="7" opacity="0.8">no order with</text>
      <text x="582" y="433" font-size="7" opacity="0.8">that id exists</text>
      <text x="582" y="446" font-size="7" opacity="0.8">checked first</text>

      <text x="704" y="437" font-size="7" fill="#e0930f">DELETE again → 404:</text>
      <text x="704" y="448" font-size="7" fill="#e0930f">idempotent in effect</text>

      <text x="826" y="385" font-size="14" font-weight="700" fill="#e0930f">405</text>
      <text x="826" y="401" font-size="7.5" opacity="0.9">Method Not</text>
      <text x="826" y="412" font-size="7.5" opacity="0.9">Allowed</text>
      <text x="826" y="428" font-size="7.5" font-weight="700" fill="#e0930f">Allow:</text>
      <text x="826" y="439" font-size="7.5" font-weight="700" fill="#e0930f">GET, PUT,</text>
      <text x="826" y="450" font-size="7.5" font-weight="700" fill="#e0930f">PATCH, DELETE</text>
    </g>

    <g font-size="8" font-weight="700" fill="#0fa07f">
      <text x="646" y="379">GET</text><text x="684" y="379">→ 200</text>
      <text x="646" y="393">PUT</text><text x="684" y="393">→ 200 replace</text>
      <text x="646" y="407">PATCH</text><text x="684" y="407">→ 200 merge</text>
      <text x="646" y="421">DELETE</text><text x="684" y="421">→ 204</text>
    </g>

    <g fill="none" stroke-linejoin="round" stroke-width="1.4">
      <rect x="18" y="476" width="864" height="64" rx="10" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.3"/>
    </g>
    <g stroke="currentColor" stroke-opacity="0.15" stroke-width="1">
      <path d="M178 484 L178 532"/><path d="M326 484 L326 532"/><path d="M462 484 L462 532"/>
      <path d="M598 484 L598 532"/><path d="M734 484 L734 532"/>
    </g>
    <g fill="currentColor">
      <text x="30" y="496" font-size="8.5" font-weight="700" opacity="0.9">RFC 9110 properties</text>
      <text x="30" y="514" font-size="8" opacity="0.85">safe — changes no state</text>
      <text x="30" y="531" font-size="8" opacity="0.85">idempotent — N calls = 1</text>
    </g>
    <g text-anchor="middle" fill="currentColor">
      <text x="258" y="496" font-size="10" font-weight="700">GET</text>
      <text x="394" y="496" font-size="10" font-weight="700">POST</text>
      <text x="530" y="496" font-size="10" font-weight="700">PUT</text>
      <text x="666" y="496" font-size="10" font-weight="700">PATCH</text>
      <text x="802" y="496" font-size="10" font-weight="700">DELETE</text>

      <text x="258" y="514" font-size="9" font-weight="700" fill="#0fa07f">yes</text>
      <text x="394" y="514" font-size="9" opacity="0.55">no</text>
      <text x="530" y="514" font-size="9" opacity="0.55">no</text>
      <text x="666" y="514" font-size="9" opacity="0.55">no</text>
      <text x="802" y="514" font-size="9" opacity="0.55">no</text>

      <text x="258" y="531" font-size="9" font-weight="700" fill="#0fa07f">yes</text>
      <text x="394" y="531" font-size="9" opacity="0.55">no</text>
      <text x="530" y="531" font-size="9" font-weight="700" fill="#0fa07f">yes</text>
      <text x="666" y="531" font-size="9" opacity="0.55">no (by default)</text>
      <text x="802" y="531" font-size="9" font-weight="700" fill="#0fa07f">yes</text>
    </g>
  </g>
  <text x="450" y="558" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9" fill="currentColor" opacity="0.85">Proxies and clients may auto-retry idempotent requests; caches only ever cache safe ones — that is the operational payoff.</text>
  <text x="450" y="582" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">One dispatch table decides everything: the path shape picks the allowed set, and a 405 must name that set in Allow.</text>
  <text x="450" y="600" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.75">Colour rule for the whole phase: 2xx green, 4xx amber — a 4xx says the client got it wrong, never the server.</text>
</svg>
```

Two handlers are worth reading closely. **POST returns `201` with `Location`**
pointing at the freshly-minted URL, plus the full representation so the client needs
no follow-up GET — and the server-owned fields (`id`, `status`, `created_at`) appear
even though the client never sent them:

```python
order = create_order(body)
return self._send(201, order, headers={"Location": "/orders/" + order["id"]})
```

**PATCH implements RFC 7396 merge semantics** — a present key sets, a key sent as
`null` *deletes*. The sharp edge from the concept section, made concrete:

```python
for key, value in body.items():
    if key in ("id", "created_at"):
        continue                 # server-owned, immutable
    if value is None:
        order.pop(key, None)     # under merge-patch, null MEANS delete
    else:
        order[key] = value
```

Running it drives one request per branch and prints the status each returns:

```console
$ python rest_router.py
create -> 201 + Location    POST   /orders        -> 201  Location: /orders/ord_afcc4bac34fb
wrong verb -> 405 + Allow   DELETE /orders        -> 405  Allow: GET, POST
bad JSON -> 400             POST   /orders        -> 400
missing resource -> 404     GET    /orders/ord_x  -> 404
delete -> 204               DELETE /orders/ord_…  -> 204
delete again -> 404         DELETE /orders/ord_…  -> 404
```

That last pair is idempotency *in effect*: the resource ends up gone either way, even
though the second DELETE honestly reports `404`.

## Use It

In FastAPI, a merge-patch handler distinguishes "field absent" from "field sent as
null" with `exclude_unset`:

```python
from pydantic import BaseModel

class OrderPatch(BaseModel):
    delivery_notes: str | None = None
    coupon_code: str | None = None

@router.patch("/orders/{order_id}", response_model=OrderOut)
async def patch_order(order_id: str, patch: OrderPatch):
    changes = patch.model_dump(exclude_unset=True)  # only fields the client actually sent
    # {"delivery_notes": "Ring the bell", "coupon_code": None}
    ...
```

`exclude_unset=True` is the whole trick: without it you can't tell "leave
`coupon_code` alone" from "set it to null."

## Key takeaways

- POST creates (`201` + `Location`, non-idempotent); PUT replaces wholly
  (idempotent); PATCH updates partially.
- **Safe** ⇒ cacheable; **idempotent** ⇒ auto-retryable. GET is both; POST is neither.
- Merge Patch (RFC 7396) for simple updates (`null` deletes!); JSON Patch (RFC 6902)
  for surgical/conditional edits.
- One consistent status-code map; **5xx means the server is at fault** — nothing else.
