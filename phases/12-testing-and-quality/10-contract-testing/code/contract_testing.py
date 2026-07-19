#!/usr/bin/env python3
"""
Contract testing at the seam between two services, measured rather than
asserted: the integration matrix's combinatorics against contract testing's
linear cost, a working consumer-driven contract recorder and provider verifier,
three gates run over six real cross-service defects, a compatibility checker
whose verdicts are confirmed by round-tripping data, the deploy order each
change forces, and the tolerant reader that defers breakage into corruption.

Companion to docs/en.md (Phase 12, Lesson 10). Standard library only, one seed
(SEED = 20260718), self-terminating in about one second, no network, no files
outside a TemporaryDirectory. Sources: Postel, RFC 761 sec 2.10 (1980);
Thomson & Pauly, RFC 9413 "Maintaining Robust Protocols" (2023); the Pact
Specification v3 (matching rules, provider states); OpenAPI Specification 3.1.0.

Run:  python3 contract_testing.py
"""

from __future__ import annotations

import json
import os
import random
import tempfile
import re
from dataclasses import dataclass, replace
from typing import Any, Callable

SEED = 20260718
MEASURED: dict[str, float] = {}


def banner(n: int, title: str) -> None:
    print(f"\n== {n} · {title} ==")


def type_name(v: Any) -> str:
    if isinstance(v, bool):
        return "boolean"
    for typ, name in ((int, "integer"), (float, "number"), (str, "string"),
                      (list, "array"), (dict, "object")):
        if isinstance(v, typ):
            return name
    return "null"


def big(v: float) -> str:
    return f"{v:,.0f}" if v < 1e6 else f"{v:.2e}"


# ══ 1 ═══════════════════════════════════════════════════════════════════════════
# The integration matrix. "Does this system work?" is a question about a
# COMBINATION of versions, and combinations multiply. Contract testing asks a
# question per dependency EDGE, and edges add. Then the measurement that
# explains why nobody reads the shared environment: it answers only on the days
# when every service in it is green, and that is a product over its members.


def dep_edges(n: int) -> list[tuple[int, int]]:
    """Service i calls i+1 and i+2 — no RNG, so E is checkable by hand."""
    return [(i, j) for i in range(n) for j in (i + 1, i + 2) if j < n]


def env_availability(n: int, p_break: float, p_fix: float, days: int,
                     rng: random.Random) -> tuple[float, int]:
    broken = [False] * n
    green = longest = run = 0
    for _ in range(days):
        for i in range(n):
            if broken[i]:
                broken[i] = rng.random() >= p_fix
            else:
                broken[i] = rng.random() < p_break
        if any(broken):
            run += 1
            longest = max(longest, run)
        else:
            green, run = green + 1, 0
    return green / days, longest


def section1() -> None:
    banner(1, "THE INTEGRATION MATRIX: WHY A SHARED ENVIRONMENT STOPS SCALING")
    m = 3
    print(f"  M = {m} live versions per service (production, staging, the branch in review)")
    print("  dependency graph: service i calls i+1 and i+2, so E edges = one contract each\n")
    print("    services   edges   version combinations   pairwise pairs   contract verifications"
          "   matrix/contract")
    for n in (3, 5, 11, 30):
        e, combos = len(dep_edges(n)), float(m) ** n
        print(f"    {n:8d}   {e:5d}   {big(combos):>20}   {e * m * m:14d}   {e:22d}"
              f"   {big(combos / e):>15}")
    print("  M^N grows with the SYSTEM; E grows with the WIRING. At 11 services that is")
    print(f"  {big(3.0 ** 11)} combinations against {len(dep_edges(11))} contracts, and a shared environment")
    print("  holds exactly ONE of those combinations at a time.")
    print(f"  lockstep: 11 services x 5 deploys/week = {11 * 5}/week independently, or {5}/week as one")
    print(f"  release train — an {11 * 5 / 5:.0f}x difference in how often anything reaches a user.")

    print("\n  the environment's own availability — each service breaks it with p=0.02/day,")
    print("  repaired with p=0.25/day (mean repair 4 days); 20,000 simulated days:")
    print("    services   simulated green   closed form   longest unbroken red streak")
    g = 0.25 / (0.25 + 0.02)
    for n in (3, 5, 11, 30):
        sim, streak = env_availability(n, 0.02, 0.25, 20_000, random.Random(SEED + 31 * n))
        print(f"    {n:8d}   {sim:14.1%}   {g ** n:11.1%}   {streak:22d} days")
        if n == 11:
            MEASURED["green"], MEASURED["streak"] = sim, float(streak)
    print("  simulation and closed form agree: availability is a PRODUCT over members, so it")
    print(f"  decays exponentially while every member stays healthy. At 11 services the gate")
    print(f"  answers on {MEASURED['green']:.1%} of days; its longest red stretch was {int(MEASURED['streak'])} days.")


# ══ 2 ═══════════════════════════════════════════════════════════════════════════
# A minimal consumer-driven contract system: matchers, a mock provider the
# consumer's REAL code runs against, a JSON contract file, and a verifier that
# replays every interaction against the real provider. The shape follows the
# Pact Specification v3 — an example body plus matching rules by JSON path.


@dataclass(frozen=True)
class Matcher:
    kind: str                 # "type" | "regex" | "eachLike"
    example: Any
    regex: str = ""
    min_items: int = 1


def like(example: Any) -> Matcher:
    """Match the TYPE, not the value — the provider may return any integer."""
    return Matcher("type", example)


def term(regex: str, example: str) -> Matcher:
    return Matcher("regex", example, regex)


def each_like(template: Any, min_items: int = 1) -> Matcher:
    return Matcher("eachLike", template, min_items=min_items)


def compile_expectation(node: Any, path: str, rules: dict[str, dict]) -> Any:
    """Split an expectation into (example body, matching rules by JSON path)."""
    if isinstance(node, Matcher):
        if node.kind == "type":
            rules[path] = {"match": "type"}
            return compile_expectation(node.example, path, rules)
        if node.kind == "regex":
            rules[path] = {"match": "regex", "regex": node.regex}
            return node.example
        rules[path] = {"match": "type", "min": node.min_items}
        return [compile_expectation(node.example, path + "[*]", rules)]
    if isinstance(node, dict):
        return {k: compile_expectation(v, f"{path}.{k}", rules) for k, v in node.items()}
    if isinstance(node, list):
        return [compile_expectation(v, f"{path}[{i}]", rules) for i, v in enumerate(node)]
    return node


def match_node(expected: Any, actual: Any, rules: dict[str, dict], path: str) -> list[str]:
    """The verifier's core. Extra keys in `actual` are ALLOWED — that is the whole
    design: the provider may add anything and must not remove what is recorded."""
    rule = rules.get(path, {})
    if rule.get("match") == "regex":
        if not isinstance(actual, str) or not re.fullmatch(rule["regex"], actual):
            return [f"{path}: {actual!r} does not match /{rule['regex']}/"]
        return []
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}: expected an object, got {type_name(actual)}"]
        out: list[str] = []
        for k in sorted(expected):
            if k not in actual:
                out.append(f"{path}.{k}: MISSING from the provider response")
            else:
                out += match_node(expected[k], actual[k], rules, f"{path}.{k}")
        return out
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return [f"{path}: expected an array, got {type_name(actual)}"]
        if rule.get("match") == "type":
            if len(actual) < int(rule.get("min", 1)):
                return [f"{path}: expected at least {rule.get('min', 1)} element(s), "
                        f"got {len(actual)}"]
            seen: list[str] = []
            for item in actual:
                for d in match_node(expected[0], item, rules, path + "[*]"):
                    if d not in seen:
                        seen.append(d)
            return seen
        if len(expected) != len(actual):
            return [f"{path}: expected {len(expected)} element(s), got {len(actual)}"]
        out = []
        for i, (e, a) in enumerate(zip(expected, actual)):
            out += match_node(e, a, rules, f"{path}[{i}]")
        return out
    if rule.get("match") == "type":
        if type_name(expected) != type_name(actual):
            return [f"{path}: expected {type_name(expected)}, got {type_name(actual)} ({actual!r})"]
        return []
    return [] if expected == actual else [f"{path}: expected {expected!r}, got {actual!r}"]


@dataclass
class Interaction:
    description: str
    provider_state: str
    request: dict[str, Any]
    status: int
    body: Any
    rules: dict[str, dict]
    used: bool = False


class HttpClient:
    def __init__(self, handler: Callable[[dict], dict]) -> None:
        self._h = handler

    def get(self, path: str) -> dict[str, Any]:
        return self._h({"method": "GET", "path": path})


class ConsumerContract:
    """Recorded by the consumer's own test run, against a mock it controls."""

    def __init__(self, consumer: str, provider: str) -> None:
        self.consumer, self.provider = consumer, provider
        self.interactions: list[Interaction] = []
        self._p: dict[str, Any] = {}

    def given(self, state: str) -> "ConsumerContract":
        self._p = {"state": state}
        return self

    def upon_receiving(self, desc: str) -> "ConsumerContract":
        self._p["desc"] = desc
        return self

    def with_request(self, method: str, path: str) -> "ConsumerContract":
        self._p["request"] = {"method": method, "path": path}
        return self

    def will_respond_with(self, status: int, body: Any) -> "ConsumerContract":
        rules: dict[str, dict] = {}
        example = compile_expectation(body, "$", rules)
        self.interactions.append(Interaction(self._p["desc"], self._p["state"],
                                             self._p["request"], status, example, rules))
        self._p = {}
        return self

    def mock_client(self) -> HttpClient:
        def handler(req: dict[str, Any]) -> dict[str, Any]:
            for ix in self.interactions:
                if (ix.request["method"], ix.request["path"]) == (req["method"], req["path"]):
                    ix.used = True
                    return {"status": ix.status, "body": json.loads(json.dumps(ix.body))}
            raise AssertionError(f"consumer made an unrecorded request: {req}")
        return HttpClient(handler)

    def to_json(self) -> str:
        return json.dumps({
            "consumer": {"name": self.consumer}, "provider": {"name": self.provider},
            "interactions": [{"description": ix.description,
                              "providerState": ix.provider_state, "request": ix.request,
                              "response": {"status": ix.status, "body": ix.body,
                                           "matchingRules": ix.rules}}
                             for ix in self.interactions]}, indent=2, sort_keys=True)


class OrderNotFound(Exception):
    pass


class NotBillable(Exception):
    pass


def build_receipt(client: HttpClient, order_id: str) -> dict[str, Any]:
    """THE CONSUMER'S REAL CODE — the same function runs against the mock in the
    consumer test and against the live provider in production."""
    resp = client.get(f"/orders/{order_id}")
    if resp["status"] == 404:
        raise OrderNotFound(order_id)
    body = resp["body"]
    if body["status"] not in ("confirmed", "shipped"):
        raise NotBillable(body["status"])
    return {"order_id": body["id"], "amount_due_cents": body["total_cents"],
            "currency": body["currency"]}


ORDER_V1: dict[str, Any] = {
    "id": "ord_7hQ2df", "status": "confirmed", "total_cents": 129900, "currency": "INR",
    "created_at": "2026-07-14T09:12:04Z", "customer_id": "cus_4Kd91", "channel": "web",
    "shipping_cents": 4900, "tax_cents": 19821, "warehouse": "BLR-2",
    "lines": [{"sku": "KB-88", "qty": 1, "unit_cents": 105179}],
}

STATES = {"an order ord_7hQ2df exists and is confirmed": ("ord_7hQ2df", "confirmed"),
          "an order ord_3Xb10p exists and is cancelled": ("ord_3Xb10p", "cancelled"),
          "no order ord_GONE99 exists": None}


class OrdersProvider:
    """The real provider. `variant` selects a released build; `set_state` is the
    provider-state hook the verifier calls before replaying an interaction."""

    def __init__(self, variant: str = "v1") -> None:
        self.variant, self.store, self.states_seen = variant, {}, []

    def set_state(self, state: str) -> bool:
        self.store, seeded = {}, STATES.get(state, "?")
        self.states_seen.append(state)
        if seeded == "?":
            return False
        if seeded:
            oid, status = seeded
            self.store[oid] = dict(ORDER_V1, id=oid, status=status)
        return True

    def handle(self, req: dict[str, Any]) -> dict[str, Any]:
        oid = req["path"].split("/")[-1]
        if oid not in self.store:
            return {"status": 404, "body": {"error": {"code": "order_not_found",
                                                      "order_id": oid}}}
        b = json.loads(json.dumps(self.store[oid]))
        if self.variant == "v2_rename":
            b["amount_cents"] = b.pop("total_cents")
        elif self.variant == "v3_additive":
            b.update(discount_cents=0, promised_at="2026-07-18T00:00:00Z",
                     warehouse_region="in-south")
        elif self.variant == "v4_stringly":
            b["total_cents"] = str(b["total_cents"])
        return {"status": 200, "body": b}


def record_contract() -> ConsumerContract:
    """The consumer test. Every expectation is a field the consumer's own code
    reads — the contract is a projection of USAGE, not of the provider's schema."""
    pact = ConsumerContract("receipts", "orders")
    for oid, status in (("ord_7hQ2df", "confirmed"), ("ord_3Xb10p", "cancelled")):
        (pact.given(f"an order {oid} exists and is {status}")
             .upon_receiving(f"a request for a {status} order")
             .with_request("GET", f"/orders/{oid}")
             .will_respond_with(200, {"id": like(oid), "status": status,
                                      "total_cents": like(129900),
                                      "currency": term(r"[A-Z]{3}", "INR")}))
    (pact.given("no order ord_GONE99 exists")
         .upon_receiving("a request for an order that does not exist")
         .with_request("GET", "/orders/ord_GONE99")
         .will_respond_with(404, {"error": {"code": "order_not_found"}}))

    client = pact.mock_client()
    assert build_receipt(client, "ord_7hQ2df")["amount_due_cents"] == 129900
    for oid, exc in (("ord_3Xb10p", NotBillable), ("ord_GONE99", OrderNotFound)):
        try:
            build_receipt(client, oid)
            raise AssertionError(f"expected {exc.__name__}")
        except exc:
            pass
    return pact


def other_contract(name: str, body: dict, check: Callable[[HttpClient], None]) -> ConsumerContract:
    """Two more consumers reading different slices of the same response."""
    pact = ConsumerContract(name, "orders")
    (pact.given("an order ord_7hQ2df exists and is confirmed")
         .upon_receiving(f"a request from {name}")
         .with_request("GET", "/orders/ord_7hQ2df").will_respond_with(200, body))
    check(pact.mock_client())
    return pact


def shipping_contract() -> ConsumerContract:
    def plan(client: HttpClient) -> None:
        b = client.get("/orders/ord_7hQ2df")["body"]
        assert b["warehouse"] and sum(ln["qty"] for ln in b["lines"]) == 1
    return other_contract("shipping", {"id": like("ord_7hQ2df"), "warehouse": like("BLR-2"),
                                       "lines": each_like({"sku": like("KB-88"),
                                                           "qty": like(1)})}, plan)


def analytics_contract() -> ConsumerContract:
    def rollup(client: HttpClient) -> None:
        b = client.get("/orders/ord_7hQ2df")["body"]
        assert b["created_at"][:10] == "2026-07-14" and b["channel"] == "web"
    return other_contract("analytics", {"id": like("ord_7hQ2df"), "channel": like("web"),
                                        "created_at": term(r"\d{4}-\d{2}-\d{2}T.*",
                                                           "2026-07-14T09:12:04Z")}, rollup)


def verify_contract(doc: dict, provider: OrdersProvider) -> list[tuple[str, list[str]]]:
    """The provider-side verifier: replay each interaction against the real
    provider, after putting it into the state the consumer's example assumed."""
    results = []
    for ix in doc["interactions"]:
        if not provider.set_state(ix["providerState"]):
            results.append((ix["description"],
                            [f"provider state not implemented: {ix['providerState']!r}"]))
            continue
        actual = provider.handle(ix["request"])
        if actual["status"] != ix["response"]["status"]:
            diffs = [f"$.status: expected HTTP {ix['response']['status']}, "
                     f"got {actual['status']}"]
        else:
            diffs = match_node(ix["response"]["body"], actual["body"],
                               ix["response"]["matchingRules"], "$")
        results.append((ix["description"], diffs))
    return results


def section2(tmpdir: str) -> dict:
    banner(2, "A CONTRACT, RECORDED BY THE CONSUMER AND VERIFIED BY THE PROVIDER")
    pact = record_contract()
    path = os.path.join(tmpdir, "receipts-orders.json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(pact.to_json())
    doc = json.loads(open(path, encoding="utf-8").read())
    fields, constrained = len(ORDER_V1), len(doc["interactions"][0]["response"]["body"])
    rules = sum(len(ix["response"]["matchingRules"]) for ix in doc["interactions"])
    print(f"  the consumer test drove {len(doc['interactions'])} interactions through its own code and wrote a")
    print(f"  {os.path.getsize(path)}-byte contract. Interactions the consumer actually exercised: "
          f"{sum(1 for i in pact.interactions if i.used)}/{len(pact.interactions)}.")
    print(f"  the provider's 200 response carries {fields} top-level fields; the contract constrains")
    print(f"  {constrained} of them, with {rules} matching rules on type and pattern — never on the value.")

    print("\n    provider build                            fields   verified   failed")
    for label, variant in (("v1  the recorded baseline", "v1"),
                           ("v2  renames total_cents -> amount_cents", "v2_rename"),
                           ("v3  adds 3 fields, changes nothing", "v3_additive"),
                           ("v4  emits total_cents as a string", "v4_stringly")):
        prov = OrdersProvider(variant)
        prov.set_state("an order ord_7hQ2df exists and is confirmed")
        n = len(prov.handle({"method": "GET", "path": "/orders/ord_7hQ2df"})["body"])
        res = verify_contract(doc, OrdersProvider(variant))
        bad = [(d, x) for d, x in res if x]
        print(f"    {label:40s}  {n:5d}    {len(res) - len(bad):3d}/{len(res)}    {len(bad):3d}")
        for d, diffs in bad:
            print(f"          FAIL [{d}]  {diffs[0]}")
    print("  v3 added three fields and stayed green: a contract is a floor, not a schema.")

    greens = 0
    for _ in range(4):
        client = HttpClient(lambda _r: {"status": 200, "body": dict(ORDER_V1)})
        greens += build_receipt(client, "ord_7hQ2df")["amount_due_cents"] == 129900
    print(f"\n  the consumer's own unit suite, over a hand-written mock: {greens}/4 GREEN — including")
    print("  both broken builds. A double is a second implementation of someone else's")
    print("  contract, written from the same reading as the code, verified by nobody.")
    return doc


# ══ 3 ═══════════════════════════════════════════════════════════════════════════
# Three gates over six real defects. Every gate is executed, not assumed: the
# spec differ compares schemas INFERRED from what the service actually returns,
# the contract gate replays section 2's contract, and the end-to-end gate runs
# the consumer over a batch and asserts on the receipts it produced.


DEFECTS = [("d1", "rename total_cents -> amount_cents"),
           ("d2", "remove currency from the response"),
           ("d3", "404 becomes 200 with a null body"),
           ("d4", "total_cents redenominated in DOLLARS"),
           ("d5", "lines[] returned in a different order"),
           ("d6", "shipping_cents removed (no consumer reads it)")]


def defective_provider(defect: str) -> Callable[[dict], dict]:
    """The provider as actually deployed, with one real defect applied."""
    def handler(req: dict[str, Any]) -> dict[str, Any]:
        oid = req["path"].split("/")[-1]
        if oid == "ord_GONE99":
            return ({"status": 200, "body": None} if defect == "d3" else
                    {"status": 404, "body": {"error": {"code": "order_not_found"}}})
        b = json.loads(json.dumps(ORDER_V1))
        b["id"] = oid
        b["lines"] = [{"sku": "KB-88", "qty": 1, "unit_cents": 105179},
                      {"sku": "MS-12", "qty": 2, "unit_cents": 12360}]
        if oid == "ord_3Xb10p":
            b["status"] = "cancelled"
        if defect == "d1":
            b["amount_cents"] = b.pop("total_cents")
        elif defect == "d2":
            b.pop("currency")
        elif defect == "d4":
            b["total_cents"] //= 100
        elif defect == "d5":
            b["lines"] = list(reversed(b["lines"]))
        elif defect == "d6":
            b.pop("shipping_cents")
        return {"status": 200, "body": b}
    return handler


def infer_spec(handler: Callable[[dict], dict]) -> dict[str, Any]:
    """The published API description, derived from what the service returns."""
    ok = handler({"method": "GET", "path": "/orders/ord_7hQ2df"})
    gone = handler({"method": "GET", "path": "/orders/ord_GONE99"})
    return {"props": {k: type_name(v) for k, v in sorted((ok["body"] or {}).items())},
            "codes": sorted({ok["status"], gone["status"]})}


def spec_diff(old: dict, new: dict) -> list[str]:
    """Breaking findings only — what an `oasdiff`-style CI gate reports."""
    out = [f"property removed: {k}" for k in old["props"] if k not in new["props"]]
    out += [f"property {k} changed type" for k in old["props"]
            if k in new["props"] and old["props"][k] != new["props"][k]]
    out += [f"response code {c} removed" for c in old["codes"] if c not in new["codes"]]
    return out


def e2e_fails(handler: Callable[[dict], dict]) -> bool:
    """The end-to-end test: run the consumer over a batch and assert on the VALUES
    it produces. That is the assertion neither of the other gates can make."""
    client = HttpClient(handler)
    try:
        receipts = [build_receipt(client, o) for o in ("ord_7hQ2df", "ord_A1", "ord_B2")]
    except Exception:  # noqa: BLE001 - any escape counts as a caught defect
        return True
    if any(r["amount_due_cents"] != 129900 or r["currency"] != "INR" for r in receipts):
        return True
    body = handler({"method": "GET", "path": "/orders/ord_7hQ2df"})["body"] or {}
    return [ln["sku"] for ln in body.get("lines", [])] != ["KB-88", "MS-12"]


def section3(doc: dict) -> None:
    banner(3, "THREE GATES, SIX DEFECTS: WHAT EACH ONE ACTUALLY PROVES")
    print("  (S) spec diff on the published API description, (C) consumer-driven contract")
    print("  verification, (E) end-to-end against the shared environment.\n")
    print("    id   defect                                             S       C       E")
    base = infer_spec(defective_provider("none"))
    tally = {"S": 0, "C": 0, "E": 0}
    only: dict[str, list[str]] = {"S": [], "C": [], "E": []}
    for did, label in DEFECTS:
        handler = defective_provider(did)
        s_hit = bool(spec_diff(base, infer_spec(handler)))
        c_hit = any(actual["status"] != ix["response"]["status"]
                    or match_node(ix["response"]["body"], actual["body"],
                                  ix["response"]["matchingRules"], "$")
                    for ix in doc["interactions"]
                    for actual in [handler(ix["request"])])
        e_hit = e2e_fails(handler)
        hits = {"S": s_hit, "C": c_hit, "E": e_hit}
        for key, hit in hits.items():
            tally[key] += hit
            if hit and sum(hits.values()) == 1:
                only[key].append(did)
        mark = lambda h: "caught" if h else "  .   "  # noqa: E731
        print(f"    {did}   {label:46s}  {mark(s_hit)}  {mark(c_hit)}  {mark(e_hit)}")
    n = len(DEFECTS)
    print(f"\n    caught: spec diff {tally['S']}/{n}   contract {tally['C']}/{n}   end-to-end {tally['E']}/{n}")
    print(f"    only end-to-end caught {only['E']}: a redenomination and a reordering are")
    print("    changes to MEANING, and meaning is not a statement a schema can carry.")
    print(f"    only the spec diff caught {only['S']}: a field no consumer reads. A breaking-change")
    print("    alarm that breaks nobody is how a spec-diff gate becomes a muted channel.")
    print("    d3 shows the reverse: the contract carries the 404 the happy path never walks.")
    green = MEASURED["green"]
    print(f"    and the end-to-end gate only answers on the {green:.1%} of days the environment is")
    print(f"    green, so its effective rate is {tally['E']}/{n} x {green:.3f} = {tally['E'] * green:.2f}/{n} against the contract")
    print(f"    gate's {tally['C']}/{n}, which runs in the provider's own CI with nothing shared.")


# ══ 4 ═══════════════════════════════════════════════════════════════════════════
# The compatibility checker. Every verdict is produced by round-tripping real
# records through a real reader, never by a lookup table — then compared against
# an independent static classifier, so two methods have to agree.


@dataclass(frozen=True)
class Field:
    name: str
    type: str
    required: bool = True
    enum: tuple[str, ...] | None = None
    default: Any = None
    nullable: bool = False
    unit: str = ""


@dataclass(frozen=True)
class Schema:
    name: str
    fields: tuple[Field, ...]

    def get(self, name: str) -> Field | None:
        return next((f for f in self.fields if f.name == name), None)

    def without(self, name: str) -> "Schema":
        return Schema(self.name, tuple(f for f in self.fields if f.name != name))

    def with_field(self, fld: Field) -> "Schema":
        return Schema(self.name, self.fields + (fld,))

    def edit(self, name: str, **kw: Any) -> "Schema":
        return Schema(self.name, tuple(replace(f, **kw) if f.name == name else f
                                       for f in self.fields))

    def rename(self, old: str, new: str) -> "Schema":
        return Schema(self.name, tuple(replace(f, name=new) if f.name == old else f
                                       for f in self.fields))


class ReadError(Exception):
    pass


RESP_V1 = Schema("OrderResponse", (
    Field("id", "string"),
    Field("status", "string", enum=("pending", "confirmed", "shipped", "cancelled")),
    Field("total_cents", "integer", unit="minor"),
    Field("currency", "string"),
    Field("fx_rate", "number", required=False, default=1.0),
    Field("channel", "string", required=False, default="web")))

REQ_V1 = Schema("OrderRequest", (
    Field("order_id", "string"), Field("channel", "string"),
    Field("include_lines", "boolean", required=False, default=False)))


def write_record(s: Schema, canon: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """Encode canonical values under a schema: its field names, its units, its
    enum symbols. A writer emits exactly what its own schema declares."""
    rec: dict[str, Any] = {}
    for f in s.fields:
        if not f.required and rng.random() < 0.30:
            continue                                    # optional means sometimes absent
        if f.name == "status":
            allowed = f.enum or ("confirmed",)
            v: Any = canon["status"] if canon["status"] in allowed else allowed[0]
        elif f.name in ("total_cents", "amount_cents"):
            v = canon["total_cents"] // 100 if f.unit == "major" else canon["total_cents"]
        elif f.name in canon:
            v = canon[f.name]
        else:
            v = {"number": 1.25, "boolean": True, "integer": 7}.get(
                f.type, f"x{rng.randrange(100, 999)}")
        if f.nullable and rng.random() < 0.4:
            v = None
        elif f.type == "integer" and isinstance(v, float):
            v = int(v)
        elif f.type == "number" and isinstance(v, int) and not isinstance(v, bool):
            v = float(v)                    # a writer declaring `number` emits 129900.0
        rec[f.name] = v
    return rec


def read_record(s: Schema, rec: dict[str, Any]) -> dict[str, Any]:
    """A reader that validates its own slice. Unknown fields are ignored — the one
    piece of tolerance every HTTP client has by default."""
    out: dict[str, Any] = {}
    for f in s.fields:
        if f.name not in rec:
            if f.required:
                raise ReadError(f"required field '{f.name}' is absent")
            out[f.name] = f.default
            continue
        v = rec[f.name]
        if v is None:
            if not f.nullable:
                raise ReadError(f"field '{f.name}' is null; the reader does not allow null")
        elif type_name(v) != f.type and not (f.type == "number" and type_name(v) == "integer"):
            raise ReadError(f"field '{f.name}': expected {f.type}, got {type_name(v)}")
        elif f.enum and v not in f.enum:
            raise ReadError(f"field '{f.name}': unknown enum symbol {v!r}")
        out[f.name] = v
    return out


def canon_stream(k: int, rng: random.Random, statuses: tuple[str, ...]) -> list[dict]:
    return [{"id": f"ord_{i:04d}", "order_id": f"ord_{i:04d}", "currency": "INR",
             "status": statuses[rng.randrange(len(statuses))], "channel": "web",
             "total_cents": rng.randrange(1000, 900_000), "idempotency_key": f"idem_{i:04d}"}
            for i in range(k)]


def round_trip(reader: Schema, writer: Schema, k: int, rng: random.Random) -> tuple[int, str]:
    """Compatibility is not a lookup: it is whether this loop completes."""
    ok, first = 0, ""
    sf = writer.get("status")
    statuses = tuple(sf.enum) if sf and sf.enum else ("confirmed",)
    for canon in canon_stream(k, rng, statuses):
        try:
            read_record(reader, write_record(writer, canon, rng))
            ok += 1
        except ReadError as exc:
            first = first or str(exc)
    return ok, first


CHANGES: list[tuple[str, str, Callable[[Schema], Schema]]] = [
    ("add an optional response field with a default", "response",
     lambda s: s.with_field(Field("promised_at", "string", required=False, default=""))),
    ("remove an optional response field", "response", lambda s: s.without("channel")),
    ("remove a required response field", "response", lambda s: s.without("currency")),
    ("rename a response field", "response", lambda s: s.rename("total_cents", "amount_cents")),
    ("widen a response type  integer -> number", "response",
     lambda s: s.edit("total_cents", type="number")),
    ("narrow a response type  number -> integer", "response",
     lambda s: s.edit("fx_rate", type="integer")),
    ("add a value to a response enum", "response",
     lambda s: s.edit("status", enum=("pending", "confirmed", "shipped", "cancelled",
                                      "partially_shipped"))),
    ("remove a value from a response enum", "response",
     lambda s: s.edit("status", enum=("confirmed", "shipped", "cancelled"))),
    ("make a required response field optional", "response",
     lambda s: s.edit("currency", required=False, default="INR")),
    ("add a required request field", "request",
     lambda q: q.with_field(Field("idempotency_key", "string"))),
    ("make a required request field optional", "request",
     lambda q: q.edit("channel", required=False, default="web")),
    ("redenominate total_cents in DOLLARS (same type)", "response",
     lambda s: s.edit("total_cents", unit="major")),
]


def classify(old: Schema, new: Schema) -> tuple[bool, bool]:
    """An independent static classifier: predicted (backward, forward), no data."""
    back = forw = True
    for f in new.fields:                      # what the NEW reader demands of OLD data
        g = old.get(f.name)
        if g is None:
            back &= not f.required
        else:
            back &= f.type == g.type or (f.type == "number" and g.type == "integer")
            back &= not (f.enum and g.enum and set(g.enum) - set(f.enum))
            back &= not (g.nullable and not f.nullable)
    for g in old.fields:                      # what the OLD reader demands of NEW data
        f = new.get(g.name)
        if f is None:
            forw &= not g.required
        else:
            forw &= g.type == f.type or (g.type == "number" and f.type == "integer")
            forw &= not (g.enum and f.enum and set(f.enum) - set(g.enum))
            forw &= not (f.nullable and not g.nullable)
            forw &= not (g.required and not f.required)
    return bool(back), bool(forw)


def section4() -> list[dict]:
    banner(4, "TWELVE SCHEMA CHANGES, DECIDED BY ROUND-TRIPPING REAL DATA")
    k = 400
    print(f"  each verdict is {k} records written under one schema and read under the other.")
    print("  BACKWARD = new reader reads old data.  FORWARD = old reader reads new data.\n")
    print("     #  change                                            dir   backward   forward"
          "    verdict    static")
    rows: list[dict] = []
    agree = 0
    for i, (label, direction, mod) in enumerate(CHANGES, start=1):
        old = RESP_V1 if direction == "response" else REQ_V1
        new = mod(old)
        b_ok, b_err = round_trip(new, old, k, random.Random(SEED + 600 + i))
        f_ok, f_err = round_trip(old, new, k, random.Random(SEED + 700 + i))
        backward, forward = b_ok == k, f_ok == k
        verdict = ("FULL" if backward and forward else "BACKWARD" if backward
                   else "FORWARD" if forward else "NEITHER")
        same = classify(old, new) == (backward, forward)
        agree += same
        rows.append({"n": i, "label": label, "dir": direction, "backward": backward,
                     "forward": forward, "old": old, "new": new,
                     "b_err": b_err, "f_err": f_err})
        print(f"    {i:2d}  {label:48s}  {direction[:4]}   {b_ok:4d}/{k}  {f_ok:4d}/{k}"
              f"   {verdict:9s}  {'agree' if same else 'DISAGREE'}")
    print(f"\n    an independent static classifier agreed with the measured round-trip on"
          f" {agree}/{len(CHANGES)} rows.")
    for r in rows:
        if not r["backward"]:
            print(f"    row {r['n']:2d} backward: {r['b_err']}")
        if not r["forward"]:
            print(f"    row {r['n']:2d} forward:  {r['f_err']}")
    print("\n  the three rows where the intuition is backwards:")
    print("    row  7  the provider only ADDED an enum value — backward-compatible, and it")
    print("            breaks every consumer with an exhaustive match. Additive is not safe.")
    print("    row  8  removing a value the provider no longer emits breaks the NEW reader,")
    print("            because old providers are still emitting it during the rollout.")
    print("    row  9  RELAXING a response field from required to optional is breaking: the")
    print("            old reader still demands it. Relaxation is safe on requests only.")

    new = RESP_V1.edit("total_cents", unit="major")
    canon = canon_stream(k, random.Random(SEED + 1003), ("confirmed",))
    truth = sum(c["total_cents"] for c in canon)
    seen = sum(read_record(RESP_V1, write_record(new, c, random.Random(SEED + 1004)))["total_cents"]
               for c in canon)
    print("\n  row 12 is the one no checker on earth catches:")
    print(f"    the provider means {truth:,} minor units; the consumer computes {seen:,} —")
    print(f"    a factor of {truth / max(seen, 1):.0f}, with every structural check green in both directions.")
    return rows


# ══ 5 ═══════════════════════════════════════════════════════════════════════════
# Deploy order, derived. During any rolling deploy both versions of both sides
# are live at once. Simulate it, count real failures, and check the outcome
# against section 4's verdicts — two independent routes to the same rule.


def rolling_deploy(row: dict, order: str, requests: int, rng: random.Random) -> tuple[int, int]:
    """Returns (failed requests, requests answered with a wrong amount)."""
    resp = (row["old"], row["new"]) if row["dir"] == "response" else (RESP_V1, RESP_V1)
    req = (row["old"], row["new"]) if row["dir"] == "request" else (REQ_V1, REQ_V1)
    units = row["n"] == 12
    fails = wrong = 0
    for i in range(requests):
        t = i / requests
        lead = min(1.0, max(0.0, (t - 0.05) / 0.35))
        follow = min(1.0, max(0.0, (t - 0.55) / 0.35))
        pc, pp = (lead, follow) if order == "consumer_first" else (follow, lead)
        c_new, p_new = rng.random() < pc, rng.random() < pp
        c_req, p_req = req[c_new], req[p_new]
        c_resp, p_resp = resp[c_new and not units], resp[p_new]
        canon = canon_stream(1, rng, tuple(p_resp.get("status").enum))[0]
        try:
            read_record(p_req, write_record(c_req, canon, rng))
            got = read_record(c_resp, write_record(p_resp, canon, rng))
        except ReadError:
            fails += 1
            continue
        fld = c_resp.get("total_cents") or c_resp.get("amount_cents")
        scale = 100 if fld is not None and fld.unit == "major" else 1
        amount = got.get("total_cents", got.get("amount_cents"))
        wrong += amount is None or int(amount) * scale != canon["total_cents"]
    return fails, wrong


def section5(rows: list[dict]) -> None:
    banner(5, "DEPLOY ORDER, DERIVED: WHOEVER READS THE DATA SHIPS FIRST")
    n_req = 3000
    print(f"  a rolling deploy of {n_req} requests: one side flips instance by instance, then")
    print("  the other. Both versions of both sides are live at once — that is the hazard.\n")
    print("     #  change                                           consumer-first     provider-first"
          "    ship first")
    predicted = 0
    silent: list[int] = []
    for r in rows:
        cf, cf_bad = rolling_deploy(r, "consumer_first", n_req, random.Random(SEED + 1100 + r["n"]))
        pf, pf_bad = rolling_deploy(r, "provider_first", n_req, random.Random(SEED + 1200 + r["n"]))
        # For a RESPONSE the consumer reads, so consumer-first needs BACKWARD.
        # For a REQUEST the provider reads, so the roles swap.
        pred = (r["backward"], r["forward"]) if r["dir"] == "response" \
            else (r["forward"], r["backward"])
        predicted += pred == (cf == 0, pf == 0)
        best = ("either" if cf == 0 and pf == 0 else "consumer" if cf == 0
                else "provider" if pf == 0 else "NEITHER")
        if cf == 0 and pf == 0 and (cf_bad or pf_bad):
            silent.append(r["n"])
            best = "SILENT"
        print(f"    {r['n']:2d}  {r['label']:47s}  {cf:5d}e {cf_bad:5d}w   {pf:5d}e {pf_bad:5d}w"
              f"    {best}")
    print(f"\n    section 4's verdicts predicted {predicted}/{len(rows)} of these outcomes with no simulation.")
    print("    the rule that falls out, and it is the only one worth memorising:")
    print("      the side that READS the changed data must understand both shapes. BACKWARD")
    print("      compatibility lets the READER ship first; FORWARD lets the WRITER ship first.")
    print("      For a RESPONSE the reader is the consumer. For a REQUEST it is the provider.")
    print("      That single flip is the part everybody gets wrong.")
    print(f"    rows that never error in either order and answer wrongly in both: {silent}")
    print("    no deploy-order policy reaches those. Only a value assertion does.")


# ══ 6 ═══════════════════════════════════════════════════════════════════════════
# The tolerant reader. Postel, RFC 761 sec 2.10 (1980): "be conservative in what
# you do, be liberal in what you accept from others." Thomson & Pauly, RFC 9413
# (2023) is the counter-argument; this section turns it into a number.


BILLABLE = ("confirmed", "shipped")


class ContractViolation(Exception):
    pass


def strict_consumer(body: dict) -> tuple[int, str]:
    for k in ("id", "status", "total_cents", "currency", "lines"):
        if k not in body:
            raise ContractViolation(f"missing field {k!r}")
    if body["status"] not in ("pending", "confirmed", "shipped", "cancelled"):
        raise ContractViolation(f"unknown status {body['status']!r}")
    if not isinstance(body["total_cents"], int) or isinstance(body["total_cents"], bool):
        raise ContractViolation(f"total_cents is {type_name(body['total_cents'])}")
    if not isinstance(body["currency"], str):
        raise ContractViolation("currency is not a string")
    if not isinstance(body["lines"], list):
        raise ContractViolation(f"lines is {type_name(body['lines'])}, not array")
    return (body["total_cents"] if body["status"] in BILLABLE else 0), body["currency"]


def tolerant_consumer(body: dict) -> tuple[int, str]:
    try:
        total = int(float(body.get("total_cents", 0)))
    except (TypeError, ValueError):
        total = 0
    status = str(body.get("status", "")).lower()
    return (total if status in BILLABLE else 0), (body.get("currency") or "INR")


def release_body(release: int, canon: dict, rng: random.Random) -> dict:
    """One release, one change, applied to the baseline in ISOLATION — so every
    row of the table prices exactly one thing the provider did."""
    b: dict[str, Any] = {"id": canon["id"], "status": canon["status"],
                         "total_cents": canon["total_cents"], "currency": "INR",
                         "created_at": "2026-07-14T09:12:04Z", "tax_cents": 19821,
                         "shipping_cents": 4900, "lines": [{"sku": "KB-88", "qty": 1}]}
    if release == 1:
        b["promised_at"] = "2026-07-20T00:00:00Z"
    elif release == 2:
        b["discount_cents"] = 0
    elif release == 3:
        b["total_cents"] = str(b["total_cents"])
    elif release == 4 and b["status"] == "confirmed" and rng.random() < 0.60:
        b["status"] = "partially_shipped"
    elif release == 5 and rng.random() < 0.40:
        b["currency"] = None
    elif release == 6:
        b["tax_amount_cents"] = b.pop("tax_cents")
    elif release == 7:
        b.pop("shipping_cents")
    elif release == 8:
        b["total_cents"] //= 100
    elif release == 9:
        b["created_at"] = "2026-07-14T14:42:04+05:30"
    elif release == 10 and b["status"] in BILLABLE:
        b["status"] = b["status"].upper()
    elif release == 11:
        b["lines"] = {"items": b["lines"], "next": None}
    elif release == 12:
        b["amount_cents"] = b.pop("total_cents")
    return b


def truth_of(canon: dict, b: dict) -> tuple[int, str]:
    """What the receipt SHOULD say, given what the provider MEANT — which is the
    one thing no wire format carries."""
    status = str(b.get("status", "")).lower()
    status = "shipped" if status == "partially_shipped" else status
    return (canon["total_cents"] if status in BILLABLE else 0), "INR"


RELEASE_LABELS = ["add promised_at", "add discount_cents", "total_cents sent as a string",
                  "status gains 'partially_shipped'", "currency null for domestic orders",
                  "rename tax_cents -> tax_amount_cents", "drop shipping_cents",
                  "total_cents redenominated in DOLLARS", "created_at gains a +05:30 offset",
                  "status upper-cased", "lines becomes {items:[...]}",
                  "rename total_cents -> amount_cents"]


def section6() -> None:
    banner(6, "THE TOLERANT READER: BREAKAGE DEFERRED, NOT AVOIDED")
    batch = 200
    print(f"  two frozen consumers, {batch} orders per release, 12 releases, each measured in")
    print("  ISOLATION. STRICT validates its slice and raises. TOLERANT ignores unknown")
    print("  fields, coerces types, lower-cases enums and defaults what is missing.\n")
    print("    rel  what the provider shipped                   strict rejects  tolerant wrong"
          "  tolerant raised  outcome")
    buckets: dict[str, list[int]] = {"free": [], "absorbed": [], "DEFERRED": [], "INVISIBLE": []}
    money = records = rejected = 0
    for rel in range(1, 13):
        rng = random.Random(SEED + 2000 + rel)
        canon = canon_stream(batch, random.Random(SEED + 2100 + rel),
                             ("pending", "confirmed", "shipped", "cancelled"))
        s_rej = t_err = t_wrong = delta = 0
        for c in canon:
            b = release_body(rel, c, rng)
            want = truth_of(c, b)
            try:
                strict_consumer(b)
            except ContractViolation:
                s_rej += 1
            try:
                got = tolerant_consumer(b)
                if got != want:
                    t_wrong += 1
                    delta += abs(want[0] - got[0])
            except Exception:  # noqa: BLE001 - counting escapes is the measurement
                t_err += 1
        outcome = ("DEFERRED" if s_rej and t_wrong else "absorbed" if s_rej
                   else "INVISIBLE" if t_wrong else "free")
        buckets[outcome].append(rel)
        rejected += bool(s_rej)
        records += t_wrong
        money += delta
        print(f"    r{rel:02d}  {RELEASE_LABELS[rel - 1]:44s}  {s_rej:8d}/{batch}  {t_wrong:8d}/{batch}"
              f"  {t_err:9d}       {outcome}")
    print(f"\n    free for both consumers:                       {buckets['free']}")
    print(f"    the tolerant reader absorbed CORRECTLY:        {buckets['absorbed']}")
    print(f"    it turned an exception into a wrong number:    {buckets['DEFERRED']}")
    print(f"    NEITHER consumer noticed — pure semantics:     {buckets['INVISIBLE']}")
    print(f"\n    the strict consumer rejected data in {rejected} of 12 releases: loud, immediate, and")
    print("    an outage until somebody ships a fix. That is the honest cost of strictness.")
    print(f"    the tolerant consumer raised 0 exceptions in 12 of 12 releases and issued")
    print(f"    {records} wrong receipts, understating what it billed by {money:,} minor units.")
    print(f"    of the {rejected} changes a strict reader would have rejected, tolerance handled")
    print(f"    {len(buckets['absorbed'])} correctly and turned {len(buckets['DEFERRED'])} into silent corruption — and the {len(buckets['absorbed'])} it handled")
    print(f"    are exactly the evidence that persuaded the provider the other {len(buckets['DEFERRED'])} were safe.")


# ══ 7 ═══════════════════════════════════════════════════════════════════════════
# Provider states and the deployment gate. A contract is verifiable only if the
# provider can be put into the state the consumer's example assumed, and a
# verification result is worth something only if a deploy is gated on it.


CONSUMER_STATES = [("receipts", ["ord_7hQ2df confirmed", "ord_3Xb10p cancelled",
                                 "ord_GONE99 absent"]),
                   ("shipping", ["ord_7hQ2df confirmed", "ord_7hQ2df shipped",
                                 "ord_9Zq44 confirmed", "ord_GONE99 absent"]),
                   ("analytics", ["ord_7hQ2df confirmed", "ord_7hQ2df cancelled"]),
                   ("fraud", ["ord_7hQ2df confirmed", "ord_5Yt02 flagged",
                              "ord_9Zq44 confirmed"])]


def section7(doc: dict) -> None:
    banner(7, "PROVIDER STATES, AND THE GATE THAT MAKES VERIFICATION MEAN SOMETHING")
    blind = OrdersProvider("v1")
    blind.set_state = lambda _s: True                      # type: ignore[assignment]
    res = verify_contract(doc, blind)
    bad = [(d, x) for d, x in res if x]
    print(f"  a provider with no state-setup hook: {len(res) - len(bad)}/{len(res)} interactions verified.")
    for d, diffs in bad:
        print(f"      FAIL [{d}]  {diffs[0]}")
    real = OrdersProvider("v1")
    ok = sum(1 for _d, x in verify_contract(doc, real) if not x)
    print(f"  the same contract with the hook implemented: {ok}/{len(res)} verified, over "
          f"{len(set(real.states_seen))} states:")
    for s in sorted(set(real.states_seen)):
        print(f"      - {s}")

    print("\n  state explosion across the provider's consumer set:")
    print("    consumer      interactions   distinct states   contradiction")
    seen: dict[str, str] = {}
    collisions = 0
    for name, states in CONSUMER_STATES:
        clash = []
        for s in states:
            oid, cond = s.split(" ", 1)
            if oid in seen and seen[oid] != cond:
                clash.append(f"{oid}: {seen[oid]} vs {cond}")
                collisions += 1
            seen.setdefault(oid, cond)
        print(f"    {name:12s}  {len(states):12d}   {len(set(states)):15d}   "
              f"{clash[0] if clash else '-'}")
    total = len({s for _n, ss in CONSUMER_STATES for s in ss})
    print(f"    {len(CONSUMER_STATES)} consumers, {sum(len(s) for _n, s in CONSUMER_STATES)} interactions, "
          f"{total} distinct states, {collisions} contradictory pair(s).")
    print("    no single seeded fixture satisfies both 'ord_7hQ2df is confirmed' and")
    print("    'ord_7hQ2df is cancelled'. Per-state setup, not a shared database, is the fix.")

    print("\n  can-i-deploy: every consumer contract replayed against every provider build")
    contracts = [("receipts@v3", doc), ("shipping@v2", json.loads(shipping_contract().to_json())),
                 ("analytics@v1", json.loads(analytics_contract().to_json()))]
    print("    provider build            " + "".join(f"{n:>15}" for n, _c in contracts)
          + "     deployable")
    for label, variant in (("orders v1", "v1"), ("orders v2 (rename)", "v2_rename"),
                           ("orders v3 (additive)", "v3_additive"),
                           ("orders v4 (stringly)", "v4_stringly")):
        cells, all_ok = [], True
        for _name, cdoc in contracts:
            good = all(not x for _d, x in verify_contract(cdoc, OrdersProvider(variant)))
            all_ok &= good
            cells.append(f"{'pass' if good else 'FAIL':>15}")
        print(f"    {label:22s}" + "".join(cells) + f"     {'yes' if all_ok else 'BLOCKED'}")
    print("    the gate is not 'did my tests pass'. It is 'does every consumer version now in")
    print("    production still verify against the artifact I am about to ship' — a question")
    print("    the provider's own CI answers alone, with no shared environment anywhere.")


def main() -> None:
    print("CONTRACT TESTING: THE SEAM BETWEEN SERVICES")
    print(f"deterministic, standard library only, seed = {SEED}")
    section1()
    with tempfile.TemporaryDirectory() as tmp:
        doc = section2(tmp)
        section3(doc)
        section5(section4())
        section6()
        section7(doc)
    print("\n(every number above was produced by this program on this run)")


if __name__ == "__main__":
    main()
