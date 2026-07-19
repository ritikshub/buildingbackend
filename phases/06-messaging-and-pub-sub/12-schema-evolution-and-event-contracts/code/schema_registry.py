#!/usr/bin/env python3
"""
Schema evolution: a registry, a compatibility checker, and an upcaster chain.

Companion to docs/en.md (Phase 6, Lesson 12 - Schema Evolution & Event
Contracts). Builds what a schema registry actually does: a schema model with
field tags and defaults, writer's-schema/reader's-schema resolution, the six
compatibility modes, a matrix of 13 proposed changes scored against all six,
the silent corruption a rename causes, an upcaster chain that replays three
schema generations, the schema-id wire envelope, and the enum hazard.

Sources: Apache Avro 1.11 specification (schema resolution), Protocol Buffers
language specification (field numbers, reserved), CloudEvents 1.0 (dataschema).
Standard library only, seeded, deterministic:  python schema_registry.py
"""

from __future__ import annotations

import json
import random
import struct
from dataclasses import dataclass, replace
from typing import Any, Callable

SEED = 20260718
N_CORRUPTION = 5_000          # events written under v1, read by a v3 consumer
DAYS_RETAINED = 90            # the log's retention window (lesson 05)
PER_DAY = 100                 # events per day in the replay corpus
N_ENUM = 4_000                # events in the enum-hazard stream
NEW_ENUM_SHARE = 0.08         # share of them carrying the newly added symbol

NO_DEFAULT = object()         # a field with no default is a REQUIRED field


# ─── the schema model ────────────────────────────────────────────────────────
#
# A schema is an ordered set of fields. Every field carries four things that
# matter for evolution: a TAG (its permanent identity on the wire, Protobuf's
# field number), a NAME, a TYPE, and a DEFAULT. "Optional" is not a separate
# property of the wire format - it is exactly "has a default", which is why
# Avro requires defaults on any field you want to evolve past.
# SEMANTICS is declared here and checked nowhere: see section 2, row 8.

@dataclass(frozen=True)
class Field:
    tag: int
    name: str
    type: str
    optional: bool = False
    default: Any = NO_DEFAULT
    semantics: str = ""

    @property
    def has_default(self) -> bool:
        return self.default is not NO_DEFAULT


# Avro's type promotion rules: a value written as X can be read as any of
# PROMOTIONS[X]. Promotion is one-directional, which is the entire reason
# widening and narrowing land in different compatibility modes.
PROMOTIONS: dict[str, set[str]] = {
    "int32": {"int32", "int64", "float", "double"},
    "int64": {"int64", "float", "double"},
    "float": {"float", "double"},
    "double": {"double"},
    "string": {"string", "bytes"},
    "bytes": {"bytes", "string"},
    "bool": {"bool"},
}


def readable_as(writer_type: str, reader_type: str) -> bool:
    if writer_type == reader_type:
        return True
    return reader_type in PROMOTIONS.get(writer_type, set())


class Schema:
    """An ordered field set plus its enum symbol tables and retired tags."""

    def __init__(self, name: str, fields: list[Field],
                 enums: dict[str, tuple[str, ...]] | None = None,
                 reserved: frozenset[int] = frozenset()) -> None:
        self.name = name
        self.order = [f.name for f in fields]                 # declaration order
        self.fields = {f.name: f for f in fields}
        self.by_tag = {f.tag: f for f in fields}
        self.enums = dict(enums or {})
        self.reserved = frozenset(reserved)
        assert len(self.by_tag) == len(fields), "duplicate tag in one schema"
        for f in fields:
            assert not f.optional or f.has_default, f"optional field {f.name} needs a default"

    def evolve(self, add: list[Field] = (), drop: list[str] = (),
               retype: dict[str, str] | None = None,
               resemantic: dict[str, str] | None = None,
               enums: dict[str, tuple[str, ...]] | None = None,
               reserve: set[int] = frozenset(), reorder: bool = False) -> "Schema":
        """Produce a candidate next version. Every matrix row is one call."""
        fields = [self.fields[n] for n in self.order if n not in drop]
        if retype:
            fields = [replace(f, type=retype[f.name]) if f.name in retype else f for f in fields]
        if resemantic:
            fields = [replace(f, semantics=resemantic[f.name]) if f.name in resemantic else f
                      for f in fields]
        fields = fields + list(add)
        if reorder:
            fields = list(reversed(fields))
        return Schema(self.name, fields, {**self.enums, **(enums or {})},
                      self.reserved | frozenset(reserve))

    def to_dict(self) -> dict:
        """The .avsc-shaped document a registry would store and serve."""
        return {
            "type": "record", "name": self.name,
            "fields": [
                {"tag": f.tag, "name": f.name, "type": f.type,
                 **({"default": f.default} if f.has_default else {}),
                 **({"doc": f.semantics} if f.semantics else {})}
                for f in (self.fields[n] for n in self.order)
            ],
            "enums": {k: list(v) for k, v in self.enums.items()},
            "reserved": sorted(self.reserved),
        }

    def json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True)


# ─── writer's schema vs reader's schema: the one primitive everything uses ───

def can_read(reader: Schema, writer: Schema, strict: bool = False) -> list[str]:
    """Can code holding `reader` decode a record written with `writer`?

    This is Avro's schema-resolution question, and every compatibility mode is
    just this function called with the arguments in a particular order.
    `strict=True` models a validator that rejects unknown fields - Postel's
    principle violated, and the direct cause of failure one in the lesson.
    """
    problems: list[str] = []

    for tag in sorted(set(reader.by_tag) & set(writer.by_tag)):
        rf, wf = reader.by_tag[tag], writer.by_tag[tag]
        if rf.name != wf.name:
            problems.append(
                f"tag {tag} carries '{wf.name}' on the wire but means '{rf.name}' to the reader")

    for name in reader.order:
        rf = reader.fields[name]
        wf = writer.fields.get(name)
        if wf is None:
            if not rf.has_default:
                problems.append(
                    f"reader needs '{name}', the writer never emits it, and it has no default")
            continue
        if not readable_as(wf.type, rf.type):
            problems.append(
                f"'{name}' is {wf.type} on the wire, {rf.type} in the reader: no legal promotion")
            continue
        if wf.type.startswith("enum:"):
            unknown = [s for s in writer.enums[wf.type[5:]] if s not in reader.enums[rf.type[5:]]]
            if unknown and not rf.has_default:
                problems.append(
                    f"'{name}' may carry enum symbol {unknown[0]!r}, unknown to the reader")

    if strict:
        for name in writer.order:
            if name not in reader.fields:
                problems.append(f"strict validator rejects unknown field '{name}'")

    return problems


# ─── the six compatibility modes ─────────────────────────────────────────────

MODES = ["BACKWARD", "BACKWARD_T", "FORWARD", "FORWARD_T", "FULL", "FULL_T"]
_SPEC = {                       # (checks backward?, checks forward?, transitive?)
    "BACKWARD":   (True, False, False),
    "BACKWARD_T": (True, False, True),
    "FORWARD":    (False, True, False),
    "FORWARD_T":  (False, True, True),
    "FULL":       (True, True, False),
    "FULL_T":     (True, True, True),
}


def check_mode(mode: str, candidate: Schema, history: list[Schema],
               strict: bool = False) -> list[str]:
    """Score a candidate against a subject's version history. [] means accept."""
    backward, forward, transitive = _SPEC[mode]
    targets = list(enumerate(history, 1)) if transitive else [(len(history), history[-1])]
    problems: list[str] = []
    for version, old in targets:
        if backward:                      # new code reads old data
            problems += [f"v{version}: {p}" for p in can_read(candidate, old, strict)]
        if forward:                       # old code reads new data
            problems += [f"v{version}: {p}" for p in can_read(old, candidate, strict)]
    return problems


class IncompatibleSchema(Exception):
    pass


class Registry:
    """Subjects -> version history, plus one globally unique id per schema."""

    def __init__(self, mode: str = "FULL_T") -> None:
        self.mode = mode
        self.subjects: dict[str, list[Schema]] = {}
        self.by_id: dict[int, Schema] = {}
        self.ids: dict[str, int] = {}          # schema json -> id
        self._next_id = 1

    def register(self, subject: str, schema: Schema) -> tuple[int, int]:
        """Returns (version, schema_id) or raises. This is the CI gate."""
        history = self.subjects.setdefault(subject, [])
        for tag in schema.by_tag:
            for v, old in enumerate(history, 1):
                if tag in old.reserved:
                    raise IncompatibleSchema(f"tag {tag} was reserved by v{v} and may never return")
        if history:
            problems = check_mode(self.mode, schema, history)
            if problems:
                raise IncompatibleSchema(problems[0])
        key = schema.json()
        if key not in self.ids:
            self.ids[key] = self._next_id
            self.by_id[self._next_id] = schema
            self._next_id += 1
        history.append(schema)
        return len(history), self.ids[key]


def semantic_drift(a: Schema, b: Schema) -> list[str]:
    """Fields whose NAME and TYPE are identical but whose MEANING changed.

    No structural checker sees this. Not Avro, not Protobuf, not JSON Schema.
    It is detected here only because this model records semantics explicitly -
    a luxury real wire formats do not give you.
    """
    out = []
    for name in a.order:
        fa, fb = a.fields[name], b.fields.get(name)
        if fb and fa.type == fb.type and fa.semantics and fb.semantics != fa.semantics:
            out.append(f"'{name}': {fa.semantics!r} -> {fb.semantics!r}")
    return out


# ─── the subject: orders.OrderPlaced, three registered versions ──────────────

ORDER_STATUS_V1 = ("placed", "paid", "shipped")

V1 = Schema("orders.OrderPlaced", [
    Field(1, "order_id", "string"),
    Field(2, "customer_id", "string"),
    Field(3, "total_cents", "int64", semantics="integer minor units (cents)"),
    Field(4, "status", "enum:order_status"),
    Field(5, "item_count", "int32"),
    Field(7, "gift_message", "string", optional=True, default=""),
    Field(8, "promo_code", "string", optional=True, default=""),
], enums={"order_status": ORDER_STATUS_V1})

# v2 adds a currency field and retires gift_message -- WITHOUT reserving tag 7.
V2 = V1.evolve(add=[Field(6, "currency", "string", optional=True, default="EUR")],
               drop=["gift_message"])
# v3 retires promo_code and adds the acquisition channel.
V3 = V2.evolve(add=[Field(9, "channel", "string", optional=True, default="web")],
               drop=["promo_code"])

HISTORY = [V1, V2, V3]


def candidates() -> list[tuple[str, Schema, str]]:
    """13 proposed v4 changes, each with the migration that ships it safely."""
    return [
        ("add optional field, with default",
         V3.evolve(add=[Field(10, "coupon_code", "string", optional=True, default="")]),
         "ship it - the only free change on this list"),
        ("add required field, no default",
         V3.evolve(add=[Field(10, "warehouse_code", "string")]),
         "give it a default; require it in a later version"),
        ("remove optional field (has default)",
         V3.evolve(drop=["channel"]),
         "deprecate: announce, watch usage, then drop"),
        ("remove required field",
         V3.evolve(drop=["customer_id"]),
         "add a default in v+1, remove the field in v+2"),
        ("rename required field (drop + add)",
         V3.evolve(drop=["total_cents"], add=[Field(10, "total_amount", "int64")]),
         "dual-write both names, migrate, upcast forever"),
        ("widen int32 -> int64 (item_count)",
         V3.evolve(retype={"item_count": "int64"}),
         "consumers first: upgrade every reader, then widen"),
        ("narrow int64 -> int32 (total_cents)",
         V3.evolve(retype={"total_cents": "int32"}),
         "do not narrow - add a new field instead"),
        ("change UNITS, same name and type",
         V3.evolve(resemantic={"total_cents": "decimal major units (euros)"}),
         "NEVER redefine. add total_eur, keep total_cents"),
        ("add enum symbol 'refunded'",
         V3.evolve(enums={"order_status": ORDER_STATUS_V1 + ("refunded",)}),
         "ship tolerant readers first, then emit the symbol"),
        ("reorder field declarations",
         V3.evolve(reorder=True),
         "ship it - tag and name are identity, order is not"),
        ("reuse retired tag 7 for a new field",
         V3.evolve(add=[Field(7, "warehouse_id", "string", optional=True, default="")]),
         "never reuse a tag. reserve 7, take the next one"),
        ("re-add retired NAME with a new type",
         V3.evolve(add=[Field(10, "promo_code", "int64", optional=True, default=0)]),
         "pick a new name: promo_code_id, not promo_code"),
        ("change cardinality: string -> array",
         V3.evolve(retype={"currency": "array<string>"}),
         "add currencies[]; upcast old value to a 1-item list"),
    ]


# ─── the corpus: orders written under three schema generations ───────────────

CUSTOMERS = ["c_%04d" % i for i in range(400)]
CHANNELS = ["web", "ios", "android", "partner-api"]
CURRENCIES = ["EUR", "USD", "GBP"]


def make_order(rnd: random.Random, seq: int, version: int) -> dict:
    """A payload shaped exactly like the schema in force on that day."""
    rec = {
        "order_id": "o_%05d" % seq,
        "customer_id": rnd.choice(CUSTOMERS),
        "total_cents": rnd.randrange(499, 49_999),
        "status": rnd.choice(ORDER_STATUS_V1),
        "item_count": rnd.randrange(1, 9),
    }
    if version == 1:
        rec["gift_message"] = "" if rnd.random() < 0.9 else "happy birthday"
        rec["promo_code"] = "" if rnd.random() < 0.8 else "SPRING10"
    elif version == 2:
        rec["currency"] = rnd.choice(CURRENCIES)
        rec["promo_code"] = "" if rnd.random() < 0.8 else "SPRING10"
    else:
        rec["currency"] = rnd.choice(CURRENCIES)
        rec["channel"] = rnd.choice(CHANNELS)
    return rec


def version_on_day(day: int) -> int:
    """The producer deployed v2 on day 25 and v3 on day 53. The log remembers."""
    return 1 if day < 25 else 2 if day < 53 else 3


def build_log(rnd: random.Random) -> list[dict]:
    """A retained log: DAYS_RETAINED days of events, three schema generations."""
    log, seq = [], 0
    for day in range(1, DAYS_RETAINED + 1):
        version = version_on_day(day)
        for _ in range(PER_DAY):
            log.append({"day": day, "version": version,
                        "payload": make_order(rnd, seq, version)})
            seq += 1
    return log


# ─── upcasters: pure functions that carry old records forward ────────────────
#
# The consumer understands exactly ONE shape - the newest. Everything older is
# lifted to it at read time by a chain of small, pure, individually testable
# functions. This is what makes a long-retention log replayable.

def up_1_to_2(r: dict) -> dict:
    out = {k: v for k, v in r.items() if k != "gift_message"}
    out["currency"] = "EUR"        # v1 predates multi-currency: EUR is historically correct
    return out


def up_2_to_3(r: dict) -> dict:
    out = {k: v for k, v in r.items() if k != "promo_code"}
    out["channel"] = "web"         # v2 predates the mobile apps
    return out


def up_3_to_4(r: dict) -> dict:
    out = dict(r)
    out["total_amount"] = out.pop("total_cents")     # the rename, made survivable
    return out


UPCASTERS: dict[int, Callable[[dict], dict]] = {1: up_1_to_2, 2: up_2_to_3, 3: up_3_to_4}
TARGET_VERSION = 4
V4_REQUIRED = ("order_id", "customer_id", "total_amount", "currency", "channel",
               "status", "item_count")


def upcast(record: dict, from_version: int, to_version: int = TARGET_VERSION) -> dict:
    for v in range(from_version, to_version):
        record = UPCASTERS[v](record)
    return record


def consume_v4(record: dict) -> int:
    """The only consumer code that exists. It knows v4 and nothing else."""
    missing = [f for f in V4_REQUIRED if f not in record]
    if missing:
        raise KeyError(f"missing required field {missing[0]!r}")
    return record["total_amount"]


# ─── the wire envelope: schema id vs the whole schema ────────────────────────

def encode_with_id(payload: dict, schema_id: int) -> bytes:
    """Confluent's wire format: magic byte 0x00, 4-byte big-endian id, payload."""
    return b"\x00" + struct.pack(">I", schema_id) + json.dumps(
        payload, separators=(",", ":"), sort_keys=True).encode()


def encode_with_schema(payload: dict, schema: Schema) -> bytes:
    """The naive alternative: ship the contract with every single message."""
    return json.dumps({"schema": schema.to_dict(), "data": payload},
                      separators=(",", ":"), sort_keys=True).encode()


# ─── the enum hazard ─────────────────────────────────────────────────────────

def exhaustive_consumer(status: str) -> str:
    """A match statement with no default arm. Idiomatic, strict, and a landmine."""
    if status == "placed":
        return "await_payment"
    if status == "paid":
        return "pick_and_pack"
    if status == "shipped":
        return "notify_customer"
    raise ValueError(f"unhandled status {status!r}")


def tolerant_consumer(status: str) -> str:
    """Same logic, one extra arm: unknown means 'not mine', not 'crash'."""
    known = {"placed": "await_payment", "paid": "pick_and_pack", "shipped": "notify_customer"}
    return known.get(status, "ignore_unknown_status")


# ─── report ──────────────────────────────────────────────────────────────────

def money(cents: int) -> str:
    return f"EUR {cents / 100:,.2f}"


def main() -> None:
    rnd = random.Random(SEED)

    print("== 1. THE REGISTRY: subjects, versions, and one id per schema ==")
    reg = Registry(mode="FULL_T")
    for schema in HISTORY:
        version, sid = reg.register("orders.OrderPlaced", schema)
        print(f"  registered v{version}  schema_id={sid:<3} "
              f"fields={len(schema.fields)}  {len(schema.json()):,} B of schema text")
    print(f"  compatibility mode enforced on every register(): {reg.mode}")
    try:
        reg.register("orders.OrderPlaced", candidates()[4][1])   # the rename
    except IncompatibleSchema as e:
        print(f"  register(v4 = rename total_cents -> total_amount) REJECTED")
        print(f"    reason: {e}")
    print("  the rename never reaches the log. That is the entire point of the gate.")

    print("\n== 2. COMPATIBILITY MATRIX: 13 proposed changes x 6 modes ==")
    print(f"  subject 'orders.OrderPlaced'   history v1..v{len(HISTORY)}"
          f"   ACC = accept, REJ = reject")
    print(f"  _T = transitive: checked against EVERY registered version, not just the latest")
    print(f"  {'#':>3}  {'proposed change':<35} " + " ".join(f"{m:>10}" for m in MODES))
    flips = accepted = 0
    for i, (label, cand, _) in enumerate(candidates(), 1):
        verdicts, reason = [], ""
        for mode in MODES:
            problems = check_mode(mode, cand, HISTORY)
            verdicts.append("REJ" if problems else "ACC")
            if problems and not reason:
                reason = problems[0]
        print(f"  {i:>3}  {label:<35} " + " ".join(f"{v:>10}" for v in verdicts))
        drift = semantic_drift(V3, cand)
        if drift:
            print(f"       -> UNDETECTABLE: {drift[0]}")
            print(f"          no mode rejects it; no structural checker ever could")
        else:
            print(f"       -> {reason or 'compatible with every registered version'}")
        for mode in ("BACKWARD", "FORWARD"):
            if not check_mode(mode, cand, HISTORY):
                accepted += 1
                if check_mode(mode, cand, HISTORY, strict=True):
                    flips += 1
    print(f"  swap the tolerant reader for a strict one and {flips} of those {accepted}"
          f" BACKWARD/FORWARD accepts become rejects")
    guarded = V2.evolve(reserve={7})
    reg2 = Registry("BACKWARD")
    reg2.register("guarded", V1)
    reg2.register("guarded", guarded)
    try:
        reg2.register("guarded", guarded.evolve(
            add=[Field(7, "warehouse_id", "string", optional=True, default="")]))
        print("  reserved-tag guard FAILED")
    except IncompatibleSchema as e:
        print(f"  row 11 under non-transitive BACKWARD is ACC -- unless v2 said 'reserved 7':")
        print(f"    {e}")

    print("\n== 3. SILENT CORRUPTION: the rename that raised nothing ==")
    corr_rnd = random.Random(SEED + 1)
    v1_events = [make_order(corr_rnd, i, 1) for i in range(N_CORRUPTION)]
    truth = sum(e["total_cents"] for e in v1_events)
    naive = sum(e.get("total_amount", 0) for e in v1_events)      # v3 code, zero default
    print(f"  producer wrote {N_CORRUPTION:,} OrderPlaced events under v1 (field 'total_cents')")
    print(f"  ground truth            sum(total_cents)  = {truth:>12,} cents  {money(truth)}")
    print(f"  v3 analytics consumer   sum(total_amount) = {naive:>12,} cents  {money(naive)}")
    print(f"  exceptions raised {0}   log lines written {0}   alerts fired {0}"
          f"   records skipped {0}")
    strict_err, strict_at = None, None
    for i, e in enumerate(v1_events):
        try:
            consume_v4(e)
        except KeyError as exc:
            strict_err, strict_at = exc, i + 1
            break
    print(f"  same data, strict validator: HALTED at record {strict_at:,} of {N_CORRUPTION:,}"
          f" - {strict_err}")
    print(f"  the loud failure costs one page. The quiet one costs {money(truth)} of wrong numbers.")

    print("\n== 4. UPCASTERS: replaying 90 days across three schema generations ==")
    log = build_log(random.Random(SEED + 2))
    counts = {v: sum(1 for r in log if r["version"] == v) for v in (1, 2, 3)}
    expected = sum(r["payload"]["total_cents"] for r in log)
    print(f"  log: {len(log):,} events over {DAYS_RETAINED} days"
          f"   producer deployed v2 on day 25, v3 on day 53")
    for v in (1, 2, 3):
        print(f"    v{v}: {counts[v]:>6,} events ({100 * counts[v] / len(log):4.1f}%)"
              f"   days {min(d['day'] for d in log if d['version'] == v):>2}"
              f"-{max(d['day'] for d in log if d['version'] == v):<2}")
    ok = failed = 0
    for r in log:
        try:
            consume_v4(r["payload"])
            ok += 1
        except KeyError:
            failed += 1
    print(f"  v4 consumer, NO upcasters:  processed {ok:,} of {len(log):,}"
          f" ({100 * ok / len(log):.1f}%)   failed {failed:,}   <- the replay is impossible")
    total, ok, per_version = 0, 0, {1: 0, 2: 0, 3: 0}
    for r in log:
        rec = upcast(r["payload"], r["version"])
        total += consume_v4(rec)
        ok += 1
        per_version[r["version"]] += 1
    print(f"  v4 consumer, WITH upcasters: processed {ok:,} of {len(log):,}"
          f" ({100 * ok / len(log):.1f}%)   failed 0")
    print(f"    upcast hops applied: v1->v4 x{per_version[1]:,} (3 hops each), "
          f"v2->v4 x{per_version[2]:,} (2), v3->v4 x{per_version[3]:,} (1)")
    print(f"    aggregate sum(total_amount) = {total:,} cents  {money(total)}")
    print(f"    expected                    = {expected:,} cents  {money(expected)}"
          f"   match: {total == expected}")

    print("\n== 5. THE ENVELOPE: a 5-byte schema id vs the whole schema ==")
    schema_ids = {1: reg.ids[V1.json()], 2: reg.ids[V2.json()], 3: reg.ids[V3.json()]}
    schemas = {1: V1, 2: V2, 3: V3}
    id_bytes = sum(len(encode_with_id(r["payload"], schema_ids[r["version"]])) for r in log)
    full_bytes = sum(len(encode_with_schema(r["payload"], schemas[r["version"]])) for r in log)
    payload_bytes = sum(
        len(json.dumps(r["payload"], separators=(",", ":"), sort_keys=True)) for r in log)
    print(f"  corpus {len(log):,} events   payload alone {payload_bytes:>10,} B"
          f"   ({payload_bytes / len(log):.0f} B/event)")
    print(f"  schema embedded in every message  {full_bytes:>10,} B"
          f"   ({full_bytes / len(log):.0f} B/event)   overhead"
          f" {100 * (full_bytes - payload_bytes) / payload_bytes:,.0f}%")
    print(f"  magic byte + 4-byte schema id     {id_bytes:>10,} B"
          f"   ({id_bytes / len(log):.0f} B/event)   overhead"
          f" {100 * (id_bytes - payload_bytes) / payload_bytes:,.1f}%")
    print(f"  saved {full_bytes - id_bytes:,} B on this corpus:"
          f" the wire is {full_bytes / id_bytes:.1f}x smaller")
    print(f"  ...and the writer's schema is still recoverable for every record:"
          f" by_id[{schema_ids[1]}] -> v1, by_id[{schema_ids[3]}] -> v3")
    at_scale = (full_bytes - id_bytes) / len(log) * 5_000 * 86_400 / 1024 ** 3
    print(f"  at 5,000 events/s that difference is {at_scale:,.0f} GB/day of pure schema text")

    print("\n== 6. THE ENUM HAZARD: exhaustive matching meets a new symbol ==")
    erd = random.Random(SEED + 3)
    stream = ["refunded" if erd.random() < NEW_ENUM_SHARE else erd.choice(ORDER_STATUS_V1)
              for _ in range(N_ENUM)]
    new_symbols = sum(1 for s in stream if s == "refunded")
    processed, halt_at, halt_err = 0, None, None
    for i, s in enumerate(stream):
        try:
            exhaustive_consumer(s)
            processed += 1
        except ValueError as exc:
            halt_at, halt_err = i, exc
            break
    routes: dict[str, int] = {}
    for s in stream:
        routes[tolerant_consumer(s)] = routes.get(tolerant_consumer(s), 0) + 1
    print(f"  producer added one enum symbol; {new_symbols:,} of {N_ENUM:,}"
          f" events ({100 * new_symbols / N_ENUM:.1f}%) now carry it")
    print(f"  exhaustive consumer: HALTED at offset {halt_at:,} - {halt_err}")
    print(f"    processed {processed:,} of {N_ENUM:,} ({100 * processed / N_ENUM:.1f}%),"
          f" partition blocked, {N_ENUM - processed:,} events stuck behind it")
    tol_total = sum(routes.values())
    print(f"  tolerant consumer:   processed {tol_total:,} of {N_ENUM:,}"
          f" ({100 * tol_total / N_ENUM:.1f}%), 0 halts")
    for route in sorted(routes):
        print(f"    {route:<22} {routes[route]:>6,}")
    print(f"  adding an enum value is BACKWARD compatible and FORWARD INCOMPATIBLE.")
    print(f"  row 9 of the table said so. This is what the table was measuring.")

    print("\n== 7. SUMMARY: FULL_TRANSITIVE verdict, and the safe path anyway ==")
    print(f"  {'change':<35} {'FULL_T':>7}  {'deploy order':<10} safe migration path")
    for label, cand, path in candidates():
        bwd = not check_mode("BACKWARD_T", cand, HISTORY)
        fwd = not check_mode("FORWARD_T", cand, HISTORY)
        order = ("either" if bwd and fwd else "cons-first" if bwd
                 else "prod-first" if fwd else "NEITHER")
        verdict = "ACC" if bwd and fwd else "REJ"
        print(f"  {label:<35} {verdict:>7}  {order:<10} {path}")
    print(f"  default for a retained, replayable log: FULL_TRANSITIVE."
          f" Anything weaker is a promise you cannot keep.")


if __name__ == "__main__":
    main()
