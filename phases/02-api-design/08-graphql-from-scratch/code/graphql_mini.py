"""
Build It — a mini GraphQL engine from scratch (parser + resolver executor).

Strips GraphQL down to its two load-bearing ideas:

  1. A query is a SELECTION TREE — parse `{ products { name reviews { rating } } }`
     into nested fields.
  2. Execution walks that tree calling ONE RESOLVER PER FIELD; a resolver's return
     value becomes the parent for its sub-selection. Resolvers are lazy (a field
     unasked-for costs nothing) and naive (each knows only its own parent) — which is
     exactly why N+1 happens.

Then it shows the fix (a DataLoader-style batch) and the `data` + `errors` channels
(a failing resolver nulls its field and appends to `errors`; the rest still returns).

Self-terminating: runs the N+1 query naively, then batched, then a partial-failure
query; prints query counts and responses; exits 0.

Docs: phases/02-api-design/08-graphql-from-scratch/docs/en.md
Spec: GraphQL Specification (graphql.org/learn/execution) — execution & error handling.

Run:
    python graphql_mini.py
"""

from __future__ import annotations

import json
import re

# ---- the data (stands in for a database) ----------------------------------

PRODUCTS = {
    "p1": {"id": "p1", "name": "Cold Brew", "price_cents": 45000},
    "p2": {"id": "p2", "name": "Espresso", "price_cents": 30000},
    "p3": {"id": "p3", "name": "Latte", "price_cents": 38000},
}
REVIEWS = {
    "p1": [{"id": "r1", "rating": 5}, {"id": "r2", "rating": 4}],
    "p2": [{"id": "r3", "rating": 3}],
    "p3": [{"id": "r4", "rating": 5}, {"id": "r5", "rating": 2}],
}


class DB:
    """Every access bumps a counter so we can SEE the N+1 problem."""

    def __init__(self) -> None:
        self.queries = 0

    def all_products(self) -> list:
        self.queries += 1
        return list(PRODUCTS.values())

    def reviews_for(self, product_id: str) -> list:
        self.queries += 1                         # one query PER product == N+1
        return REVIEWS.get(product_id, [])

    def reviews_for_many(self, product_ids: list) -> dict:
        self.queries += 1                         # one query for ALL products
        return {pid: REVIEWS.get(pid, []) for pid in product_ids}


# ---- parser: source text -> selection tree --------------------------------


class Field:
    def __init__(self, name: str) -> None:
        self.name = name
        self.children: list = []


def parse(source: str) -> list:
    tokens = re.findall(r"[{}]|[A-Za-z_][A-Za-z0-9_]*", source)
    pos = 0

    def selection_set() -> list:
        nonlocal pos
        assert tokens[pos] == "{", "expected '{'"
        pos += 1
        fields = []
        while tokens[pos] != "}":
            field = Field(tokens[pos])
            pos += 1
            if pos < len(tokens) and tokens[pos] == "{":
                field.children = selection_set()
            fields.append(field)
        pos += 1  # consume '}'
        return fields

    return selection_set()


# ---- executor: walk the tree, one resolver per field ----------------------


def execute(selection: list, parent, ctx: dict, path: list, errors: list) -> dict:
    result = {}
    for field in selection:
        try:
            value = ctx["resolve"](parent, field, ctx)
        except Exception as exc:  # noqa: BLE001 - a failing resolver nulls its field
            errors.append({"message": str(exc), "path": path + [field.name]})
            result[field.name] = None
            continue

        if not field.children:
            result[field.name] = value
        elif isinstance(value, list):
            result[field.name] = [
                execute(field.children, item, ctx, path + [field.name, i], errors)
                for i, item in enumerate(value)
            ]
        elif value is None:
            result[field.name] = None
        else:
            result[field.name] = execute(field.children, value, ctx, path + [field.name], errors)
    return result


def run(query: str, ctx: dict) -> dict:
    errors: list = []
    data = execute(parse(query), None, ctx, [], errors)
    response = {"data": data}
    if errors:
        response["errors"] = errors      # data and errors coexist, HTTP stays 200
    return response


# ---- a DataLoader-style batch loader --------------------------------------


class DataLoader:
    def __init__(self, batch_fn) -> None:
        self._batch_fn = batch_fn
        self._cache: dict = {}

    def prime_many(self, keys: list) -> None:
        missing = [k for k in keys if k not in self._cache]
        if missing:
            for key, value in self._batch_fn(missing).items():  # ONE batched query
                self._cache[key] = value

    def load(self, key: str):
        if key not in self._cache:
            self.prime_many([key])
        return self._cache[key]


# ---- resolvers: the ONLY thing that differs between naive and batched ------


def resolve_default(parent, field, ctx):
    """One resolver per field. Root fields ignore parent; leaf fields read it."""
    if field.name == "products":
        return ctx["products"]()
    if field.name == "reviews":
        return ctx["reviews"](parent)
    return parent.get(field.name)  # scalar leaf: name, rating, price_cents, id


QUERY = "{ products { name reviews { rating } } }"


def main() -> None:
    # --- naive: 1 query for products + 1 per product for reviews (N+1) ---
    db = DB()
    naive_ctx = {
        "resolve": resolve_default,
        "products": db.all_products,
        "reviews": lambda parent: db.reviews_for(parent["id"]),
    }
    naive = run(QUERY, naive_ctx)
    print("=== naive resolvers ===")
    print(json.dumps(naive, indent=2))
    print("DB queries:", db.queries, "(1 products + {} reviews = N+1)\n".format(len(PRODUCTS)))

    # --- batched: prime a DataLoader from the product list in ONE query ---
    db = DB()
    loader = DataLoader(db.reviews_for_many)

    def products_and_prime():
        products = db.all_products()
        loader.prime_many([p["id"] for p in products])   # single batched review query
        return products

    batched_ctx = {
        "resolve": resolve_default,
        "products": products_and_prime,
        "reviews": lambda parent: loader.load(parent["id"]),
    }
    batched = run(QUERY, batched_ctx)
    print("=== batched with a DataLoader ===")
    print("DB queries:", db.queries, "(1 products + 1 batched reviews) — N+1 -> 2\n")
    assert batched["data"] == naive["data"], "batching must not change the result"

    # --- partial failure: one resolver throws; data + errors coexist ---
    db = DB()

    def flaky_reviews(parent):
        if parent["id"] == "p2":
            raise RuntimeError("reviews service unavailable for p2")
        return db.reviews_for(parent["id"])

    flaky_ctx = {"resolve": resolve_default, "products": db.all_products, "reviews": flaky_reviews}
    partial = run(QUERY, flaky_ctx)
    print("=== partial failure (HTTP would still be 200) ===")
    print(json.dumps(partial, indent=2))
    print("\np2.reviews is null, an error carries its path, and p1/p3 still returned.")


if __name__ == "__main__":
    main()
