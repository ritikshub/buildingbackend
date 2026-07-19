# Request Validation & Error Contracts

> A client should be able to write one error handler for your whole API. That only works if every error shares one envelope with a frozen machine-readable code.

**Type:** Build
**Languages:** Python
**Prerequisites:** [URLs, Verbs & Status Codes](../02-urls-verbs-status-codes/)
**Time:** ~75 minutes

## The Problem

Clients need three things from an error: an HTTP status for coarse routing (retry?
re-auth? give up?), a machine-readable code for precise handling, and a
human-readable message for logs. If every endpoint invents its own error shape,
every consumer writes bespoke parsing and something always slips through. Design
**one** envelope and use it for *every* error your API can emit.

## The Concept

### Status code selection

The coarse routing signal. Two that trip people up: **400** is for malformed
syntax/shape; **422 Unprocessable Content** is for well-formed-but-semantically-invalid
input (what FastAPI and GitHub use for validation failures). The 400-vs-422 split
is convention, not law — consistency within your API is what matters.

### Problem Details: RFC 9457 (formerly RFC 7807)

Don't invent an envelope — use the one the IETF standardized. Media type
`application/problem+json`, five standard members (`type`, `title`, `status`,
`detail`, `instance`) plus arbitrary extension members for your domain:

```http
HTTP/1.1 422 Unprocessable Content
Content-Type: application/problem+json

{
  "type": "https://api.example.com/errors/validation-error",
  "title": "Request validation failed",
  "status": 422,
  "detail": "2 fields failed validation.",
  "instance": "/v1/orders",
  "code": "validation_error",
  "errors": [
    {"field": "items[0].quantity", "code": "min_value", "message": "quantity must be >= 1"},
    {"field": "customer_id",       "code": "required",  "message": "customer_id is required"}
  ]
}
```

Design notes baked in:

- **`code` is the machine contract.** Clients branch on `code == "validation_error"`,
  **never** on the English `detail` string — messages change freely, codes are frozen
  forever. (Stripe's `{"error": {"type", "code", "message", "param"}}` follows the
  same principle.)
- **Field-level errors are a list of `{field, code, message}`** using a path syntax
  (`items[0].quantity`) that clients can map back onto form inputs. Return **all**
  failures at once — nobody enjoys fix-one-resubmit-discover-the-next loops.
- **`type` URIs should resolve to docs** but be treated as opaque identifiers.

One hard rule: error responses must **never leak internals** — no stack traces, no
SQL, no hostnames. Log the detail server-side keyed by a request ID you *do* return
(the `instance` URI or an `X-Request-Id` echo) so support can correlate.

## Build It

Validation is your first line of defense: reject bad shapes at the **edge**, before
any business logic runs. `code/validation.py` builds a schema-free validator and the
one envelope by hand.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 886" width="100%" style="max-width:880px" role="img" aria-label="How one request body becomes one error envelope. A POST to /v1/orders reaches a validator at the edge, before any business logic runs. The validator collects ALL errors rather than returning on the first one. On the clean branch the business logic runs and returns 200 or 201. On the errors branch the API returns 422 Unprocessable Content carrying one application/problem+json envelope. A side note contrasts 400, which is for malformed syntax or shape, with 422, which is for well-formed but semantically invalid input; the split is convention, not law, and consistency within your API is what matters. The middle band shows the accumulator: the helper bad(field, code, message) appends to a list, and one bad payload yields four entries at once: customer_id with code required, currency with code enum, items[0].quantity with code min_value, and items[1].menu_item_id with code required. Beside it, the fail-fast alternative is shown costing four round trips for the same payload instead of one. The third band decomposes the RFC 9457 envelope sent with media type application/problem+json: the five standard members type, title, status, detail and instance, plus the extension members code and errors. The members are tagged: status, type, code and each errors entry's code are FROZEN, the machine contract clients branch on; title, detail and each errors entry's message are disposable prose that may be rewritten freely and must never be branched on. The bottom band draws the 500 path as a real trust boundary: the server side holds the log line with the request_id, the full traceback, the failing SQL, hostnames and file paths, and none of it ever leaves the server; the client side receives only HTTP 500 with a generic message and the request_id. Two arrows cross the boundary, the response carrying 500 plus the request_id outward, and the same id quoted back inward so support can find that exact log line.">
  <defs>
    <marker id="p2l03a-arb" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
    <marker id="p2l03a-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p2l03a-arm" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
    <marker id="p2l03a-arr" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">One envelope for every error: collect ALL failures, freeze the code, leak nothing else</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g fill="none" stroke-linejoin="round" stroke-width="2">
      <rect x="16" y="78" width="132" height="58" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <path d="M282 55 L380 107 L282 159 L184 107 Z" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.6"/>
      <rect x="442" y="58" width="176" height="48" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="442" y="146" width="262" height="54" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
      <rect x="712" y="58" width="170" height="48" rx="10" fill="#d64545" fill-opacity="0.10" stroke="#d64545"/>
      <rect x="16" y="162" width="252" height="56" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="#7f7f7f" stroke-width="1.4"/>
    </g>

    <g text-anchor="middle" fill="currentColor">
      <text x="82" y="102" font-size="10.5" font-weight="700" fill="#3553ff">request body</text>
      <text x="82" y="117" font-size="8.5">POST /v1/orders</text>
      <text x="82" y="130" font-size="8.5" opacity="0.8">application/json</text>

      <text x="282" y="98" font-size="10.5" font-weight="700">validate at the EDGE</text>
      <text x="282" y="113" font-size="9">collect ALL errors</text>
      <text x="282" y="129" font-size="8" opacity="0.75">before business logic</text>

      <text x="530" y="78" font-size="10.5" font-weight="700" fill="#0fa07f">business logic runs</text>
      <text x="530" y="94" font-size="8.5">200 / 201 · normal response</text>

      <text x="573" y="165" font-size="10.5" font-weight="700" fill="#e0930f">422 Unprocessable Content</text>
      <text x="573" y="180" font-size="8.5">ONE problem+json envelope</text>
      <text x="573" y="193" font-size="8" opacity="0.8">status · code · detail · errors[]</text>

      <text x="797" y="78" font-size="10" font-weight="700" fill="#d64545">500 Internal Server Error</text>
      <text x="797" y="94" font-size="8.5">request_id ONLY on the wire</text>
    </g>

    <g fill="none" stroke="#3553ff" stroke-width="1.8"><path d="M150 107 L180 107" marker-end="url(#p2l03a-arb)"/></g>
    <g fill="none" stroke="currentColor" stroke-width="1.7" stroke-opacity="0.6"><path d="M382 107 L412 107"/></g>
    <g fill="none" stroke="#0fa07f" stroke-width="1.8"><path d="M412 107 L412 82 L440 82" marker-end="url(#p2l03a-arg)"/></g>
    <g fill="none" stroke="#e0930f" stroke-width="1.8"><path d="M412 107 L412 173 L440 173" marker-end="url(#p2l03a-arm)"/></g>
    <g fill="none" stroke="#d64545" stroke-width="1.7" stroke-dasharray="5 4"><path d="M621 82 L706 82" marker-end="url(#p2l03a-arr)"/></g>

    <g text-anchor="middle" font-weight="700">
      <text x="426" y="76" font-size="8.5" fill="#0fa07f">clean</text>
      <text x="424" y="188" font-size="8.5" fill="#e0930f">errors</text>
      <text x="665" y="74" font-size="7.5" fill="#d64545">unexpected crash</text>
    </g>

    <text x="28" y="180" font-size="8.5" font-weight="700" fill="currentColor">400 = malformed syntax or shape</text>
    <text x="28" y="194" font-size="8.5" font-weight="700" fill="currentColor">422 = well-formed, invalid meaning</text>
    <text x="28" y="209" font-size="7.5" fill="currentColor" opacity="0.75">the split is convention, not law — be consistent</text>

    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="16" y="230" width="496" height="176" rx="11" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f"/>
      <rect x="524" y="230" width="358" height="176" rx="11" fill="#7f7f7f" fill-opacity="0.08" stroke="#7f7f7f"/>
    </g>

    <text x="34" y="250" font-size="10.5" font-weight="700" fill="#e0930f">COLLECT — append every failure, never return on the first</text>
    <text x="34" y="270" font-size="8.5" fill="currentColor">def bad(field, code, message):</text>
    <text x="56" y="283" font-size="8.5" fill="currentColor">errors.append({"field": field, "code": code, "message": message})</text>

    <g font-size="8" font-weight="700" fill="currentColor" opacity="0.65">
      <text x="58" y="304">field</text><text x="200" y="304">code</text><text x="280" y="304">message</text>
    </g>
    <g stroke="currentColor" stroke-opacity="0.18" stroke-width="1"><path d="M34 310 L500 310"/></g>

    <g font-size="8.5" fill="currentColor">
      <text x="34" y="328" font-weight="700" fill="#e0930f">1 ·</text>
      <text x="58" y="328">customer_id</text><text x="200" y="328">required</text><text x="280" y="328">customer_id is required</text>
      <text x="34" y="346" font-weight="700" fill="#e0930f">2 ·</text>
      <text x="58" y="346">currency</text><text x="200" y="346">enum</text><text x="280" y="346">currency must be one of INR, USD, EUR</text>
      <text x="34" y="364" font-weight="700" fill="#e0930f">3 ·</text>
      <text x="58" y="364">items[0].quantity</text><text x="200" y="364">min_value</text><text x="280" y="364">quantity must be &gt;= 1</text>
      <text x="34" y="382" font-weight="700" fill="#e0930f">4 ·</text>
      <text x="58" y="382">items[1].menu_item_id</text><text x="200" y="382">required</text><text x="280" y="382">menu_item_id is required</text>
    </g>
    <text x="34" y="398" font-size="8" fill="currentColor" opacity="0.78">each entry is {field, code, message} — items[0].quantity maps onto a form input</text>
    <g fill="none" stroke="#e0930f" stroke-width="1.6"><path d="M25 318 L25 390" marker-end="url(#p2l03a-arm)"/></g>

    <text x="540" y="250" font-size="10" font-weight="700" fill="#d64545">✗ THE ALTERNATIVE — fail-fast</text>
    <text x="540" y="270" font-size="8.5" fill="currentColor">return on the FIRST failure and the</text>
    <text x="540" y="283" font-size="8.5" fill="currentColor">client climbs a staircase of retries:</text>
    <g font-size="8.5" fill="currentColor" opacity="0.9">
      <text x="548" y="304">1 · fix customer_id → resubmit</text>
      <text x="548" y="320">2 · fix currency → resubmit</text>
      <text x="548" y="336">3 · fix items[0].quantity → resubmit</text>
      <text x="548" y="352">4 · fix items[1].menu_item_id</text>
    </g>
    <text x="540" y="372" font-size="9" font-weight="700" fill="#d64545">4 round trips for 1 bad payload</text>
    <text x="540" y="390" font-size="8" fill="currentColor" opacity="0.8">collecting all four costs exactly one</text>

    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="16" y="416" width="866" height="236" rx="11" fill="#7f7f7f" fill-opacity="0.06" stroke="#7f7f7f"/>
    </g>
    <text x="38" y="438" font-size="9.5" font-weight="700" fill="#e0930f">HTTP/1.1 422 Unprocessable Content</text>
    <text x="38" y="454" font-size="9" fill="currentColor">Content-Type: application/problem+json</text>
    <text x="264" y="454" font-size="8" fill="currentColor" opacity="0.75">← the media type RFC 9457 (formerly RFC 7807) defines</text>
    <g stroke="currentColor" stroke-opacity="0.18" stroke-width="1"><path d="M38 466 L560 466"/></g>

    <text x="38" y="478" font-size="8.5" fill="currentColor">{</text>
    <text x="52" y="478" font-size="7.5" fill="currentColor" opacity="0.7">— the five standard RFC 9457 members —</text>

    <g font-size="8.5" fill="currentColor">
      <text x="58" y="495">"type":</text><text x="130" y="495">"https://api.example.com/errors/validation-error",</text>
      <text x="58" y="512">"title":</text><text x="130" y="512">"Request validation failed",</text>
      <text x="58" y="529">"status":</text><text x="130" y="529">422,</text>
      <text x="58" y="546">"detail":</text><text x="130" y="546">"4 field(s) failed validation.",</text>
      <text x="58" y="563">"instance":</text><text x="130" y="563">"/v1/orders",</text>
      <text x="58" y="597" fill="#0fa07f" font-weight="700">"code":</text><text x="130" y="597" fill="#0fa07f" font-weight="700">"validation_error",</text>
      <text x="58" y="614" fill="#e0930f" font-weight="700">"errors":</text><text x="130" y="614" fill="#e0930f">[ the 4 entries collected above ]</text>
    </g>
    <text x="38" y="580" font-size="7.5" fill="currentColor" opacity="0.7">— extension members: yours, alongside the standard five —</text>
    <text x="38" y="631" font-size="8.5" fill="currentColor">}</text>

    <g font-size="8">
      <text x="408" y="495" fill="#0fa07f">FROZEN · opaque id, resolves to docs</text>
      <text x="408" y="512" fill="#e0930f">PROSE · may change freely</text>
      <text x="408" y="529" fill="#0fa07f" font-size="7.5">FROZEN · coarse routing: retry? re-auth?</text>
      <text x="408" y="546" fill="#e0930f">PROSE · rewritten freely, never branch</text>
      <text x="408" y="563" fill="currentColor" opacity="0.8">which request this is about</text>
      <text x="408" y="597" fill="#0fa07f" font-weight="700">FROZEN FOREVER — clients branch here</text>
      <text x="408" y="614" fill="#0fa07f">field + code FROZEN</text><text x="506" y="614" fill="#e0930f">· message is PROSE</text>
    </g>
    <g fill="none" stroke="#e0930f" stroke-width="1.6"><path d="M25 406 L25 614 L46 614" marker-end="url(#p2l03a-arm)"/></g>

    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="604" y="474" width="272" height="74" rx="9" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f"/>
      <rect x="604" y="558" width="272" height="76" rx="9" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f"/>
    </g>
    <text x="616" y="492" font-size="9" font-weight="700" fill="#0fa07f">FROZEN — the machine contract</text>
    <text x="616" y="508" font-size="8" fill="currentColor">status · type · code · errors[].code</text>
    <text x="616" y="522" font-size="8" fill="currentColor">clients branch on code == "validation_error"</text>
    <text x="616" y="538" font-size="8" fill="currentColor" opacity="0.8">frozen forever; changing one breaks clients</text>
    <text x="616" y="576" font-size="9" font-weight="700" fill="#e0930f">DISPOSABLE PROSE — humans only</text>
    <text x="616" y="592" font-size="8" fill="currentColor">title · detail · errors[].message</text>
    <text x="616" y="606" font-size="8" fill="currentColor">reworded, re-counted or localised at</text>
    <text x="616" y="620" font-size="8" fill="currentColor">any time — never parse or branch on it</text>

    <text x="450" y="666" text-anchor="middle" font-size="11" font-weight="700" fill="#d64545">The 500 path is a boundary, not a dotted line — only the request_id crosses it</text>

    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="16" y="676" width="866" height="54" rx="11" fill="#7f7f7f" fill-opacity="0.08" stroke="#7f7f7f"/>
      <rect x="16" y="764" width="866" height="54" rx="11" fill="#d64545" fill-opacity="0.07" stroke="#d64545"/>
    </g>
    <text x="34" y="694" font-size="9.5" font-weight="700" fill="currentColor">SERVER SIDE — the log line, keyed by request_id</text>
    <text x="34" y="710" font-size="8.5" fill="currentColor">full traceback · the failing SQL · hostnames · file paths · internal params</text>
    <text x="34" y="723" font-size="8" fill="currentColor" opacity="0.75">safe_call() logs the exception here — none of this ever leaves the server</text>

    <g fill="none" stroke="currentColor" stroke-width="2" stroke-dasharray="6 5" stroke-opacity="0.5">
      <path d="M16 746 L190 746"/><path d="M214 746 L882 746"/>
    </g>
    <text x="34" y="740" font-size="8.5" font-weight="700" fill="currentColor" opacity="0.8">TRUST BOUNDARY</text>
    <text x="202" y="751" text-anchor="middle" font-size="13" font-weight="700" fill="#d64545">✗</text>
    <g fill="none" stroke="#d64545" stroke-width="1.7"><path d="M202 730 L202 740" marker-end="url(#p2l03a-arr)"/></g>
    <text x="224" y="759" font-size="8.5" font-weight="700" fill="#d64545">traceback · SQL · hostnames stop here</text>

    <g fill="none" stroke="#d64545" stroke-width="1.7"><path d="M470 732 L470 762" marker-end="url(#p2l03a-arr)"/></g>
    <text x="480" y="740" font-size="8.5" font-weight="700" fill="#d64545">500 + request_id</text>
    <g fill="none" stroke="#3553ff" stroke-width="1.7"><path d="M700 762 L700 732" marker-end="url(#p2l03a-arb)"/></g>
    <text x="710" y="740" font-size="8.5" font-weight="700" fill="#3553ff">the same id, quoted back</text>

    <text x="34" y="782" font-size="9.5" font-weight="700" fill="#d64545">CLIENT SIDE — the whole response</text>
    <text x="34" y="798" font-size="8.5" fill="currentColor">HTTP 500 · application/problem+json · a generic message + the request_id</text>
    <text x="34" y="811" font-size="8" fill="currentColor" opacity="0.75">no traceback · no SQL · no hostnames — the id is what support quotes back to find that exact log line</text>
  </g>
  <text x="450" y="840" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">The status routes coarsely, the code routes precisely, the detail is only ever for the human reading it.</text>
  <text x="450" y="858" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Collecting all four failures costs one round trip; failing fast costs four — and the traceback never crosses.</text>
  <text x="450" y="876" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.72">Write this envelope once, use it for every error your API can emit, and a client writes exactly one handler.</text>
</svg>
```

The rule that makes a client's life easy: **collect every failure, don't fail-fast.**
The validator appends to a list and keeps going, so one response reports all four
problems in a bad payload at once, each with a path (`items[0].quantity`) a client
can map straight back onto a form input:

```python
def bad(field, code, message):
    errors.append({"field": field, "code": code, "message": message})
...
elif qty < 1:
    bad("items[{}].quantity".format(i), "min_value", "quantity must be >= 1")
```

Those errors go into the RFC 9457 envelope — where `code` is the frozen machine
contract and `detail` is disposable prose:

```console
$ python validation.py
HTTP 422  Content-Type: application/problem+json
{
  "code": "validation_error",
  "detail": "4 field(s) failed validation.",
  "errors": [
    {"field": "customer_id",           "code": "required",  "message": "customer_id is required"},
    {"field": "currency",              "code": "enum",      "message": "currency must be one of INR, USD, EUR"},
    {"field": "items[0].quantity",     "code": "min_value", "message": "quantity must be >= 1"},
    {"field": "items[1].menu_item_id", "code": "required",  "message": "menu_item_id is required"}
  ]
}
```

The `safe_call()` wrapper closes the loop on **never leak internals**: a handler that
throws is logged server-side *with* its traceback, but the client sees only a generic
`500` carrying a `request_id` — the string support quotes back to find that exact log
line. The same id is on the wire and in the log; nothing else crosses the boundary.

## Use It

FastAPI validates request bodies against Pydantic models automatically, but its
default error shape (`{"detail": [...]}`) isn't Problem-Details-shaped. A global
exception handler re-shapes it into your one envelope:

```python
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    errors = [
        {"field": ".".join(str(p) for p in e["loc"][1:]), "code": e["type"], "message": e["msg"]}
        for e in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        media_type="application/problem+json",
        content={
            "type": "https://api.example.com/errors/validation-error",
            "title": "Request validation failed",
            "status": 422,
            "code": "validation_error",
            "errors": errors,
        },
    )
```

Now every validation failure across every endpoint speaks the same language, and a
client writes exactly one handler.

## Key takeaways

- One error envelope everywhere: correct status + frozen machine `code` + human
  `detail` + field-level `errors[]`.
- Use **RFC 9457 `application/problem+json`** rather than inventing a shape.
- Clients branch on **`code`, never the message**; return **all** validation errors at once.
- **Never leak internals**; return a request ID so server logs can be correlated.
