#!/usr/bin/env python3
"""
A mini document database: JSON documents in a collection, queryable by field.

Companion to docs/en.md (Phase 04, Lesson 03 - Document Databases). Unlike a
key-value store, the value here is NOT opaque: each document is a JSON tree the
database can look *inside* to match queries on any field, including nested paths
(dot notation) and operators ($gt/$lt/$in). A secondary index turns an
equality lookup from an O(n) scan into an O(1) hash hit -- the same trade the
B-tree made for relational tables (Phase 03, Lesson 09), here on schemaless docs.

Runs standalone on the Python standard library only:  python docdb.py
"""

from __future__ import annotations
import json
import os
from itertools import count

_MISSING = object()   # sentinel: a path that doesn't exist is different from a stored null


def resolve_path(doc: dict, path: str):
    """Walk a dotted path like 'address.city' into a nested document.
    Returns _MISSING if any segment is absent -- so a query never matches a field
    that isn't there (rather than crashing or matching null)."""
    cur = doc
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return _MISSING
    return cur


def matches(doc: dict, query: dict) -> bool:
    """A document matches if EVERY field condition holds (implicit AND).
    A condition is either an equality value or an operator dict like {'$gt': 100}."""
    for path, condition in query.items():
        actual = resolve_path(doc, path)
        if isinstance(condition, dict) and any(k.startswith("$") for k in condition):
            for op, operand in condition.items():
                if op == "$eq" and not (actual is not _MISSING and actual == operand):
                    return False
                if op == "$gt" and not (actual is not _MISSING and actual > operand):
                    return False
                if op == "$lt" and not (actual is not _MISSING and actual < operand):
                    return False
                if op == "$in" and not (actual is not _MISSING and actual in operand):
                    return False
        else:
            if actual is _MISSING or actual != condition:
                return False
    return True


class Collection:
    def __init__(self):
        self.docs: dict[str, dict] = {}                 # _id -> document
        self.indexes: dict[str, dict] = {}              # field path -> {value -> set(_id)}
        self._ids = count(1)
        self.scans_last_find = 0                         # instrumentation: docs examined

    def insert(self, doc: dict) -> str:
        doc = dict(doc)
        _id = doc.get("_id") or f"doc:{next(self._ids)}"
        doc["_id"] = _id
        self.docs[_id] = doc
        for field, idx in self.indexes.items():          # keep every index current
            val = resolve_path(doc, field)
            if val is not _MISSING:
                idx.setdefault(_freeze(val), set()).add(_id)
        return _id

    def create_index(self, field: str) -> None:
        """Build a secondary index: value -> set of doc ids, for O(1) equality lookups."""
        idx: dict = {}
        for _id, doc in self.docs.items():
            val = resolve_path(doc, field)
            if val is not _MISSING:
                idx.setdefault(_freeze(val), set()).add(_id)
        self.indexes[field] = idx

    def find(self, query: dict | None = None, projection: list[str] | None = None) -> list[dict]:
        query = query or {}
        self.scans_last_find = 0

        # Fast path: if a single equality field in the query is indexed, use the index
        # to fetch only the candidate ids instead of scanning the whole collection.
        candidates = None
        for field, condition in query.items():
            if field in self.indexes and not isinstance(condition, dict):
                candidates = self.indexes[field].get(_freeze(condition), set())
                break
        source = (self.docs[i] for i in candidates) if candidates is not None else self.docs.values()

        results = []
        for doc in source:
            self.scans_last_find += 1
            if matches(doc, query):
                results.append(_project(doc, projection))
        return results


def _freeze(v):
    """Make a value hashable so it can key an index (lists -> tuples)."""
    return tuple(v) if isinstance(v, list) else v


def _project(doc: dict, projection: list[str] | None) -> dict:
    if projection is None:
        return dict(doc)
    keep = set(projection) | {"_id"}
    return {k: v for k, v in doc.items() if k in keep}


class DocumentDB:
    """A tiny document store: named collections, persisted to one JSON file."""
    def __init__(self, path: str | None = None):
        self.path = path
        self.collections: dict[str, Collection] = {}

    def collection(self, name: str) -> Collection:
        return self.collections.setdefault(name, Collection())

    def save(self) -> None:
        if not self.path:
            return
        data = {name: list(c.docs.values()) for name, c in self.collections.items()}
        with open(self.path, "w") as f:
            json.dump(data, f)

    def load(self) -> None:
        if not self.path or not os.path.exists(self.path):
            return
        with open(self.path) as f:
            data = json.load(f)
        for name, docs in data.items():
            c = self.collection(name)
            for doc in docs:
                c.insert(doc)


def _demo():
    db = DocumentDB()
    products = db.collection("products")

    # Heterogeneous documents -- a book and a laptop have DIFFERENT fields, no schema needed.
    products.insert({"_id": "p:1", "type": "book", "title": "SICP",
                     "author": "Abelson", "price": 42, "tags": ["cs", "classic"]})
    products.insert({"_id": "p:2", "type": "laptop", "title": "ThinkPad X1",
                     "specs": {"ram_gb": 32, "cpu": "i7"}, "price": 1600})
    products.insert({"_id": "p:3", "type": "book", "title": "SQL for Smarties",
                     "author": "Celko", "price": 55, "tags": ["cs", "sql"]})

    print("== Query by a top-level field ==")
    for d in products.find({"type": "book"}, projection=["title", "author"]):
        print(" ", d)

    print("\n== Query a NESTED field with dot notation ==")
    for d in products.find({"specs.ram_gb": {"$gt": 16}}, projection=["title", "specs"]):
        print(" ", d)

    print("\n== Operator query ($lt) ==")
    print("  books/products under $50:",
          [d["title"] for d in products.find({"price": {"$lt": 50}})])

    print("\n== Index: turn an O(n) scan into an O(1) lookup ==")
    for i in range(4, 10004):                          # bulk-load 10k docs
        products.insert({"_id": f"p:{i}", "type": "widget", "sku": f"SKU-{i}", "price": i})
    products.find({"sku": "SKU-9999"})
    print(f"  without index: examined {products.scans_last_find} docs")
    products.create_index("sku")
    products.find({"sku": "SKU-9999"})
    print(f"  with index:    examined {products.scans_last_find} docs")


if __name__ == "__main__":
    _demo()
