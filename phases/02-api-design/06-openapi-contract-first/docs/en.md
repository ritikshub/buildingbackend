# OpenAPI & Contract-First Design

> When the spec is generated from the same models that validate requests at runtime, your docs and your behavior can't drift.

**Type:** Build
**Languages:** Python
**Prerequisites:** [URLs, Verbs & Status Codes](../02-urls-verbs-status-codes/)
**Time:** ~75 minutes

## The Problem

Hand-maintained API docs rot. The moment the code and the docs live in separate
places, they drift, and consumers build against a fiction. OpenAPI is the
machine-readable description of an HTTP API — every path, method, parameter,
schema, and auth scheme in one document — that tooling turns into typed clients,
server stubs, mocks, and contract tests.

## The Concept

A minimal spec for one endpoint:

```yaml
openapi: 3.1.0
info: {title: Orders API, version: 1.0.0}
paths:
  /v1/orders/{order_id}:
    get:
      operationId: getOrder
      parameters:
        - {name: order_id, in: path, required: true, schema: {type: string}}
      responses:
        "200":
          description: The order
          content:
            application/json:
              schema: {$ref: "#/components/schemas/Order"}
        "404":
          description: Order not found
          content:
            application/problem+json:
              schema: {$ref: "#/components/schemas/Problem"}
components:
  schemas:
    Order:
      type: object
      required: [id, status, total_amount, currency, created_at]
      properties:
        id: {type: string, example: ord_7hQ2df}
        status: {type: string, enum: [pending, confirmed, cancelled]}
        total_amount: {type: integer, description: Minor units}
        currency: {type: string, example: INR}
        created_at: {type: string, format: date-time}
```

From a spec like this, tooling generates typed client SDKs (`openapi-generator`
targets many languages), server stubs, contract tests, and mock servers — and linters
like Spectral enforce house rules ("every operation documents a 4xx," "all schemas use
snake_case") in CI.

### Two workflows

- **Contract-first:** write the YAML by hand, review it like code, implement to
  match. Best when multiple teams or external partners consume the API and the
  contract IS the coordination artifact.
- **Code-first:** write the code, generate the spec. Best for fast-moving internal APIs.

## Build It

The "code-first" magic — a spec derived from your models — is a short program once you
strip the framework away. `code/openapi_gen.py` introspects plain dataclasses and
their type hints and emits OpenAPI 3.1:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 600" width="100%" style="max-width:880px" role="img" aria-label="The five-stage code-first pipeline, with one real field carried all the way through it. Stage 1, the source of truth: the plain dataclass Order, whose type hints are the same ones that validate requests at runtime. Its fields are id of type str, status of type Literal of pending, confirmed and cancelled, total_amount of type int in minor units, currency of type str, items of type list of LineItem, created_at of type str, and delivery_notes of type Optional str defaulting to None. Six fields have no default so they become required; the one Optional field becomes nullable. Stage 2, introspect: get_type_hints on Order yields the types and fields on Order yields the defaults. For status the origin is Literal and the default is MISSING, so it maps to an enum and to required. For items the origin is list, its argument is the LineItem dataclass, and its default is MISSING, so it maps to an array of ref and to required; is_dataclass causes register to run, so the model is defined once. Stage 3, JSON Schema: status becomes type string with enum of pending, confirmed and cancelled; items becomes type array whose items is a ref to hash slash components slash schemas slash LineItem, which is the line the lesson console prints verbatim. A nested dataclass becomes a ref and is defined once, never inlined. Stage 4, the assembled OpenAPI 3.1 document: under paths, slash v1 slash orders slash order_id has a get operation with operationId getOrder, whose 200 response refs the Order schema and whose 404 response refs the Problem schema. Under components, schemas holds Order and Problem, registered explicitly, plus LineItem, auto-discovered from the items field, which is why the console reports Components generated as LineItem, Order, Problem. Stage 5, the lint gate: a diamond asking whether every operation documents a 4xx. Because getOrder documents a 404, the rule is satisfied and the linter reports PASS with no violations; an operation carrying only a 200 would fail the build in continuous integration. Alongside sits the choice of workflow: code-first writes the code and generates the spec, which is this pipeline and suits fast-moving internal APIs, while contract-first writes the YAML by hand, reviews it like code and implements to match, which suits multiple teams and external partners.">
  <defs>
    <marker id="p2l06a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p2l06a-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p2l06a-arr" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="450" y="25" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The spec is GENERATED from the types that already validate the request — follow one field through</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="16"  y="46" width="286" height="220" rx="11" fill="#3553ff" fill-opacity="0.07" stroke="#3553ff"/>
      <rect x="336" y="46" width="196" height="220" rx="11" fill="#7c5cff" fill-opacity="0.07" stroke="#7c5cff"/>
      <rect x="566" y="46" width="318" height="220" rx="11" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f"/>
    </g>

    <text x="30" y="67" font-size="10.5" font-weight="700" fill="#3553ff">1 · @dataclass Order</text>
    <text x="30" y="82" font-size="7.5" fill="currentColor" opacity="0.85">the SAME type hints that validate a request</text>
    <text x="30" y="93" font-size="7.5" fill="currentColor" opacity="0.85">at runtime — the single source of truth</text>
    <rect x="38" y="141" width="252" height="27" rx="4" fill="#3553ff" fill-opacity="0.12"/>
    <rect x="38" y="193" width="252" height="14" rx="4" fill="#3553ff" fill-opacity="0.12"/>
    <text x="30" y="112" font-size="8" fill="currentColor" opacity="0.7">@dataclass</text>
    <text x="30" y="125" font-size="8" fill="currentColor">class Order:</text>
    <text x="44" y="138" font-size="8" fill="currentColor">id: str</text>
    <text x="44" y="151" font-size="8" font-weight="700" fill="#3553ff">status: Literal["pending",</text>
    <text x="121" y="164" font-size="8" font-weight="700" fill="#3553ff">"confirmed","cancelled"]</text>
    <text x="44" y="177" font-size="8" fill="currentColor">total_amount: int</text>
    <text x="140" y="177" font-size="7" fill="currentColor" opacity="0.6"># minor units</text>
    <text x="44" y="190" font-size="8" fill="currentColor">currency: str</text>
    <text x="44" y="203" font-size="8" font-weight="700" fill="#3553ff">items: list[LineItem]</text>
    <text x="44" y="216" font-size="8" fill="currentColor">created_at: str</text>
    <text x="44" y="229" font-size="8" fill="currentColor">delivery_notes: Optional[str] = None</text>
    <path d="M30 236 L288 236" fill="none" stroke="#3553ff" stroke-opacity="0.35" stroke-width="1"/>
    <text x="30" y="246" font-size="7" fill="currentColor" opacity="0.8">6 fields have no default → required[]</text>
    <text x="30" y="256" font-size="7" fill="currentColor" opacity="0.8">delivery_notes is Optional → nullable, not required</text>

    <text x="350" y="67" font-size="10.5" font-weight="700" fill="#7c5cff">2 · introspect</text>
    <text x="350" y="83" font-size="7.5" fill="currentColor">get_type_hints(Order)</text>
    <text x="452" y="83" font-size="7.5" fill="currentColor" opacity="0.75">→ types</text>
    <text x="350" y="95" font-size="7.5" fill="currentColor">fields(Order)</text>
    <text x="452" y="95" font-size="7.5" fill="currentColor" opacity="0.75">→ defaults</text>
    <text x="350" y="107" font-size="7" fill="currentColor" opacity="0.7">— all the generator ever sees</text>

    <text x="350" y="129" font-size="8.5" font-weight="700" fill="currentColor">status</text>
    <text x="358" y="143" font-size="7.5" fill="currentColor" opacity="0.7">origin</text>
    <text x="406" y="143" font-size="7.5" fill="currentColor">Literal</text>
    <text x="452" y="143" font-size="7.5" fill="#7c5cff">→ enum</text>
    <text x="358" y="155" font-size="7.5" fill="currentColor" opacity="0.7">default</text>
    <text x="406" y="155" font-size="7.5" fill="currentColor">MISSING</text>
    <text x="452" y="155" font-size="7.5" fill="#7c5cff">→ required</text>

    <text x="350" y="177" font-size="8.5" font-weight="700" fill="currentColor">items</text>
    <text x="358" y="191" font-size="7.5" fill="currentColor" opacity="0.7">origin</text>
    <text x="406" y="191" font-size="7.5" fill="currentColor">list</text>
    <text x="452" y="191" font-size="7.5" fill="#7c5cff">→ array</text>
    <text x="358" y="203" font-size="7.5" fill="currentColor" opacity="0.7">arg</text>
    <text x="406" y="203" font-size="7.5" fill="currentColor">LineItem</text>
    <text x="452" y="203" font-size="7.5" fill="#7c5cff">→ $ref</text>
    <text x="358" y="215" font-size="7.5" fill="currentColor" opacity="0.7">default</text>
    <text x="406" y="215" font-size="7.5" fill="currentColor">MISSING</text>
    <text x="452" y="215" font-size="7.5" fill="#7c5cff">→ required</text>

    <text x="350" y="237" font-size="7" font-weight="700" fill="#7c5cff">is_dataclass(tp) → register()</text>
    <text x="350" y="249" font-size="7" fill="currentColor" opacity="0.8">so the model is defined once</text>

    <text x="580" y="67" font-size="10.5" font-weight="700" fill="#0fa07f">3 · JSON Schema fragment</text>
    <text x="580" y="83" font-size="7.5" fill="currentColor" opacity="0.85">each type hint becomes one fragment;</text>
    <text x="580" y="94" font-size="7.5" fill="currentColor" opacity="0.85">a nested model becomes a $ref</text>

    <text x="580" y="117" font-size="8" font-weight="700" fill="currentColor">status</text>
    <text x="616" y="117" font-size="7" fill="#3553ff">Literal["pending","confirmed","cancelled"]</text>
    <text x="586" y="133" font-size="7.5" fill="#0fa07f">→</text>
    <text x="600" y="133" font-size="7.5" fill="#0fa07f">{"type": "string",</text>
    <text x="612" y="145" font-size="7.5" fill="#0fa07f">"enum": ["pending","confirmed","cancelled"]}</text>

    <text x="580" y="171" font-size="8" font-weight="700" fill="currentColor">items</text>
    <text x="616" y="171" font-size="7" fill="#3553ff">list[LineItem]</text>
    <text x="586" y="187" font-size="7.5" fill="#0fa07f">→</text>
    <text x="600" y="187" font-size="7.5" fill="#0fa07f">{"type": "array",</text>
    <text x="612" y="199" font-size="7.5" fill="#0fa07f">"items": {"$ref": "#/components/schemas/LineItem"}}</text>
    <text x="612" y="210" font-size="6.5" fill="currentColor" opacity="0.7">the line the lesson's console prints verbatim</text>

    <text x="580" y="231" font-size="7.5" font-weight="700" fill="#0fa07f">nested dataclass → $ref: defined ONCE, never inlined</text>
    <text x="580" y="245" font-size="7.5" fill="currentColor" opacity="0.85">no default → required[]</text>
    <text x="700" y="245" font-size="7.5" fill="currentColor" opacity="0.85">Optional[str] → nullable</text>

    <g fill="none" stroke="currentColor" stroke-width="1.6" stroke-opacity="0.8">
      <path d="M306 150 L330 150" marker-end="url(#p2l06a-ar)"/>
      <path d="M536 150 L560 150" marker-end="url(#p2l06a-ar)"/>
      <path d="M725 270 L725 286" marker-end="url(#p2l06a-ar)"/>
      <path d="M112 406 L112 419" marker-end="url(#p2l06a-ar)"/>
    </g>
    <text x="737" y="283" font-size="7" fill="currentColor" opacity="0.8">assemble into one document</text>
    <text x="124" y="417" font-size="7" fill="currentColor" opacity="0.8">lint the document in CI (continuous integration)</text>

    <rect x="16" y="290" width="868" height="112" rx="11" fill="#0fa07f" fill-opacity="0.06" stroke="#0fa07f" stroke-width="1.8" stroke-linejoin="round"/>
    <text x="30" y="311" font-size="10.5" font-weight="700" fill="#0fa07f">4 · OpenAPI 3.1 document — paths + components, assembled</text>
    <path d="M450 322 L450 396" fill="none" stroke="currentColor" stroke-opacity="0.22" stroke-width="1.2"/>

    <text x="30" y="331" font-size="8" fill="currentColor">paths:</text>
    <text x="44" y="343" font-size="8" fill="currentColor">/v1/orders/{order_id}:</text>
    <text x="58" y="355" font-size="8" fill="currentColor">get:</text>
    <text x="96" y="355" font-size="8" fill="currentColor" opacity="0.8">operationId: getOrder</text>
    <text x="72" y="367" font-size="8" fill="currentColor">responses:</text>
    <text x="86" y="379" font-size="8" font-weight="700" fill="#0fa07f">"200"</text>
    <text x="128" y="379" font-size="7.5" fill="currentColor">→ {"$ref": "#/components/schemas/Order"}</text>
    <text x="86" y="391" font-size="8" font-weight="700" fill="#e0930f">"404"</text>
    <text x="128" y="391" font-size="7.5" fill="currentColor">→ {"$ref": "#/components/schemas/Problem"}</text>
    <text x="338" y="391" font-size="7" font-weight="700" fill="#e0930f">← the linter's 4xx</text>

    <text x="470" y="331" font-size="8" fill="currentColor">components:</text>
    <text x="484" y="343" font-size="8" fill="currentColor">schemas:</text>
    <text x="498" y="355" font-size="8" font-weight="700" fill="currentColor">Order</text>
    <text x="580" y="355" font-size="7" fill="currentColor" opacity="0.75">← registered explicitly</text>
    <text x="498" y="367" font-size="8" font-weight="700" fill="#7c5cff">LineItem</text>
    <text x="580" y="367" font-size="7" font-weight="700" fill="#7c5cff">← AUTO-DISCOVERED from items: list[LineItem]</text>
    <text x="498" y="379" font-size="8" font-weight="700" fill="currentColor">Problem</text>
    <text x="580" y="379" font-size="7" fill="currentColor" opacity="0.75">← registered explicitly</text>
    <text x="470" y="393" font-size="7" fill="currentColor" opacity="0.8">console: Components generated: LineItem, Order, Problem</text>

    <path d="M112 424 L208 472 L112 520 L16 472 Z" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="1.8" stroke-linejoin="round"/>
    <text x="112" y="456" text-anchor="middle" font-size="9" font-weight="700" fill="#e0930f">5 · lint gate</text>
    <text x="112" y="472" text-anchor="middle" font-size="8" fill="currentColor">every operation</text>
    <text x="112" y="486" text-anchor="middle" font-size="8" fill="currentColor">documents a 4xx?</text>

    <g fill="none" stroke-width="1.7">
      <path d="M210 462 L242 447" stroke="#0fa07f" marker-end="url(#p2l06a-arg)"/>
      <path d="M210 482 L242 497" stroke="#d64545" marker-end="url(#p2l06a-arr)"/>
    </g>
    <text x="224" y="440" text-anchor="middle" font-size="7" font-weight="700" fill="#0fa07f">yes</text>
    <text x="224" y="512" text-anchor="middle" font-size="7" font-weight="700" fill="#d64545">no</text>

    <g fill="none" stroke-linejoin="round" stroke-width="1.7">
      <rect x="248" y="424" width="280" height="42" rx="9" fill="#0fa07f" fill-opacity="0.09" stroke="#0fa07f"/>
      <rect x="248" y="478" width="280" height="42" rx="9" fill="#d64545" fill-opacity="0.08" stroke="#d64545"/>
      <rect x="548" y="424" width="336" height="96" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.35"/>
    </g>
    <text x="262" y="443" font-size="9.5" font-weight="700" fill="#0fa07f">PASS — no violations</text>
    <text x="262" y="457" font-size="7.5" fill="currentColor" opacity="0.85">getOrder documents "404" → rule satisfied</text>
    <text x="262" y="497" font-size="9.5" font-weight="700" fill="#d64545">FAIL the build</text>
    <text x="262" y="511" font-size="7.5" fill="currentColor" opacity="0.85">an operation with only a "200" is rejected</text>

    <text x="562" y="443" font-size="8" font-weight="700" fill="currentColor">TWO WORKFLOWS — same document, opposite direction</text>
    <text x="562" y="460" font-size="8" font-weight="700" fill="#3553ff">code-first</text>
    <text x="634" y="460" font-size="7.5" fill="currentColor">write the code, generate the spec —</text>
    <text x="634" y="471" font-size="7" fill="currentColor" opacity="0.8">this pipeline. Fast-moving internal APIs.</text>
    <text x="562" y="490" font-size="8" font-weight="700" fill="currentColor">contract-first</text>
    <text x="656" y="490" font-size="7.5" fill="currentColor">write the YAML by hand,</text>
    <text x="656" y="501" font-size="7" fill="currentColor" opacity="0.8">review it like code, implement to match.</text>
    <text x="656" y="512" font-size="7" fill="currentColor" opacity="0.8">Best across teams / external partners.</text>
  </g>
  <text x="450" y="548" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Because the schema falls out of the same types that validate requests at runtime, there is nothing to keep in sync.</text>
  <text x="450" y="566" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">The $ref rule is why LineItem is in the document at all — nobody named it; it fell out of items: list[LineItem].</text>
  <text x="450" y="584" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.75">A linter like Spectral turns a house rule (every operation documents a 4xx; all schemas use snake_case) into a build failure.</text>
</svg>
```

The type mapping is the core — each Python type becomes a schema fragment, and a
nested dataclass becomes a `$ref` so it is defined exactly once:

```python
if origin is Literal:            # Literal["pending","confirmed"] -> string enum
    return {"type": "string", "enum": list(get_args(tp))}
if origin in (list, List):       # list[LineItem] -> array of items
    return {"type": "array", "items": schema_for(get_args(tp)[0], registry)}
if is_dataclass(tp):             # nested model -> reference it, don't inline it
    register(tp, registry)
    return {"$ref": "#/components/schemas/" + tp.__name__}
```

A field with no default becomes `required`; an `Optional[...]` becomes `nullable`.
Running it emits the full document — `Order`, the auto-discovered `LineItem`, and
`Problem` — then runs a one-rule linter, the shape of a Spectral check you'd fail the
build on:

```console
$ python openapi_gen.py
...
"items": {"type": "array", "items": {"$ref": "#/components/schemas/LineItem"}}
...
=== lint: every operation must document a 4xx ===
PASS — no violations
Components generated: LineItem, Order, Problem
```

Because the schema falls out of the same types that validate requests at runtime,
there is nothing to keep in sync — the property hand-maintained YAML can never
guarantee.

## Use It

FastAPI is the code-first path done well — it derives the whole OpenAPI document
from your route signatures and Pydantic models:

```python
from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import Literal

app = FastAPI(title="Orders API", version="1.0.0")

class Order(BaseModel):
    id: str = Field(examples=["ord_7hQ2df"])
    status: Literal["pending", "confirmed", "cancelled"]
    total_amount: int = Field(description="Minor units")
    currency: str
    created_at: str

@app.get("/v1/orders/{order_id}", response_model=Order,
         responses={404: {"description": "Order not found"}})
async def get_order(order_id: str) -> Order:
    ...
```

FastAPI serves the spec at **`/openapi.json`** with two bundled doc UIs: **Swagger
UI at `/docs`** (interactive — "Try it out" fires real requests) and **ReDoc at
`/redoc`** (a clean reference layout). Because the spec is generated from the same
models that perform runtime validation, docs and behavior can't drift — the chronic
failure of hand-maintained docs.

The discipline that remains on you: **`response_model` on every route** (it both
documents and *filters* the response — without it, stray internal fields leak),
examples on fields, and documented error responses. Even code-first teams should
snapshot `/openapi.json` in the repo and **diff it in CI**, so an accidental breaking
change (a renamed field, a narrowed type) fails review loudly instead of shipping.

## Key takeaways

- OpenAPI is the machine-readable contract; it generates SDKs, stubs, mocks, and
  contract tests.
- **Contract-first** for cross-team/partner APIs; **code-first** for fast internal ones.
- FastAPI: spec at `/openapi.json`, Swagger UI at `/docs`, ReDoc at `/redoc`.
- `response_model` also **filters** the payload — without it, internal fields leak.
- **Snapshot and diff the spec in CI** so breaking changes fail loudly.
