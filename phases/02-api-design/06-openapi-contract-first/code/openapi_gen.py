"""
Build It — generate an OpenAPI 3.1 document from Python types, by hand.

This is the engine a framework hides: introspect dataclasses + type hints, turn each
into a JSON Schema (`$ref`-ing nested models so they're defined once), wire them into
paths, and emit the spec. Because the schema is DERIVED from the same types the code
uses, docs and behavior can't drift — the whole promise of code-first OpenAPI.

Includes a tiny "Spectral-style" linter (every operation must document a 4xx) to show
how house rules get enforced in CI.

Self-terminating: builds the spec, lints it, prints both, exits 0.

Docs: phases/02-api-design/06-openapi-contract-first/docs/en.md
Spec: OpenAPI Specification 3.1.0; JSON Schema 2020-12

Run:
    python openapi_gen.py
"""

from __future__ import annotations

import json
from dataclasses import MISSING, dataclass, fields, is_dataclass
from typing import List, Literal, Optional, Union, get_args, get_origin, get_type_hints

# ---- the domain models: plain dataclasses, the single source of truth ------


@dataclass
class LineItem:
    menu_item_id: str
    quantity: int


@dataclass
class Order:
    id: str
    status: Literal["pending", "confirmed", "cancelled"]
    total_amount: int          # minor units (paise/cents)
    currency: str
    items: List[LineItem]      # nested model -> becomes a $ref
    created_at: str
    delivery_notes: Optional[str] = None   # optional -> nullable, not required


@dataclass
class Problem:
    type: str
    title: str
    status: int
    detail: Optional[str] = None
    code: Optional[str] = None


# ---- type hint -> JSON Schema ---------------------------------------------

PRIMITIVES = {str: "string", int: "integer", float: "number", bool: "boolean"}


def schema_for(tp, registry: dict) -> dict:
    """Map one Python type to a JSON Schema fragment, registering nested models."""
    origin = get_origin(tp)

    if origin is Literal:                       # Literal["a","b"] -> string enum
        return {"type": "string", "enum": list(get_args(tp))}

    if origin in (list, List):                  # list[X] -> array of schema(X)
        inner = (get_args(tp) or (str,))[0]
        return {"type": "array", "items": schema_for(inner, registry)}

    if origin is Union:                         # Optional[X] == Union[X, None]
        non_null = [a for a in get_args(tp) if a is not type(None)]
        frag = dict(schema_for(non_null[0], registry))
        frag["nullable"] = True
        return frag

    if is_dataclass(tp):                        # nested model -> define once, reference
        register(tp, registry)
        return {"$ref": "#/components/schemas/" + tp.__name__}

    return {"type": PRIMITIVES.get(tp, "string")}


def register(cls, registry: dict) -> None:
    """Add cls (and anything it references) to the components registry."""
    if cls.__name__ in registry:
        return
    registry[cls.__name__] = {}                 # placeholder guards against recursion
    hints = get_type_hints(cls)
    defaults = {f.name: f.default for f in fields(cls)}
    props, required = {}, []
    for name, tp in hints.items():
        props[name] = schema_for(tp, registry)
        if defaults.get(name, MISSING) is MISSING:   # no default -> required
            required.append(name)
    obj = {"type": "object", "properties": props}
    if required:
        obj["required"] = required
    registry[cls.__name__] = obj


# ---- assemble the whole document ------------------------------------------


def build_spec() -> dict:
    registry: dict = {}
    register(Order, registry)
    register(Problem, registry)
    return {
        "openapi": "3.1.0",
        "info": {"title": "Orders API", "version": "1.0.0"},
        "paths": {
            "/v1/orders/{order_id}": {
                "get": {
                    "operationId": "getOrder",
                    "parameters": [
                        {"name": "order_id", "in": "path", "required": True,
                         "schema": {"type": "string"}},
                    ],
                    "responses": {
                        "200": {
                            "description": "The order",
                            "content": {"application/json":
                                        {"schema": {"$ref": "#/components/schemas/Order"}}},
                        },
                        "404": {
                            "description": "Order not found",
                            "content": {"application/problem+json":
                                        {"schema": {"$ref": "#/components/schemas/Problem"}}},
                        },
                    },
                }
            }
        },
        "components": {"schemas": registry},
    }


# ---- a mini linter: the kind of rule CI would enforce ----------------------


def lint(spec: dict) -> list:
    violations = []
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            codes = op.get("responses", {})
            if not any(str(c).startswith("4") for c in codes):
                violations.append("{} {}: no documented 4xx response".format(method.upper(), path))
    return violations


def main() -> None:
    spec = build_spec()
    print("=== generated OpenAPI 3.1 (from the dataclasses above) ===\n")
    print(json.dumps(spec, indent=2))

    print("\n=== lint: every operation must document a 4xx ===")
    violations = lint(spec)
    print("PASS — no violations" if not violations else "\n".join(violations))
    print("\nComponents generated:", ", ".join(sorted(spec["components"]["schemas"])))


if __name__ == "__main__":
    main()
