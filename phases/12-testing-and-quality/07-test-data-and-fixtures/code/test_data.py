"""Test data and fixtures: shared seeds, factories, and what each one costs.

Companion program for phases/12-testing-and-quality/
07-test-data-and-fixtures/docs/en.md (Phase 12, Lesson 07).
Sources: Feller, "An Introduction to Probability Theory and Its Applications",
Vol. 1, 3rd ed., 1968, sec. II.3 (the birthday problem); Sweeney, "k-Anonymity:
A Model for Protecting Privacy", IJUFKS 10(5), 2002; RFC 9562 "Universally
Unique IDentifiers (UUIDs)", 2024, sec. 5.4 (UUIDv4 entropy).
Standard library only. Seeded with random.Random(1207). Exits 0 in ~5 s.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import math
import random
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

SEED = 1207
START = time.perf_counter()


def banner(text: str) -> None:
    print(f"\n== {text} ==")


def source_block_lines(name: str) -> int:
    """Non-blank source lines of this file between two markers, so that
    "lines of fixture code" is measured rather than typed into the prose."""
    src = Path(__file__).read_text(encoding="utf-8").splitlines()
    start = next(i for i, l in enumerate(src) if l.strip() == f"# >>> {name}")
    end = next(i for i, l in enumerate(src) if l.strip() == f"# <<< {name}")
    return len([l for l in src[start + 1:end] if l.strip()])


def ranked(counter: Counter) -> list:
    """most_common() with an explicit tie-break. Counter breaks ties by
    insertion order, and this program inserts while iterating frozensets,
    whose order follows PYTHONHASHSEED. Sorting by (-count, key) makes the
    ranking a property of the data. That bug is lesson 08's subject and this
    program is not exempt from it."""
    return sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))


# ----------------------------------------------------------------------------
# 0 · THE DOMAIN — one order service that every section below runs against.
# ----------------------------------------------------------------------------

CITIES = ("Aachen", "Bristol", "Cork", "Dresden", "Eindhoven", "Faro", "Genoa",
          "Hull", "Iasi", "Jena", "Kiel", "Lyon", "Malmo", "Nantes", "Oulu",
          "Porto", "Quimper", "Reims", "Siena", "Turku")
CITY_COUNTRY = ("DE", "GB", "IE", "DE", "NL", "PT", "IT", "GB", "RO", "DE",
                "DE", "FR", "SE", "FR", "FI", "PT", "FR", "FR", "IT", "FI")
ROLES = ("admin", "member", "viewer")
USER_STATES = ("active", "suspended", "pending")
ORDER_STATES = ("paid", "pending", "refunded", "cancelled")
VAT = {"DE": 19.0, "GB": 20.0, "IE": 23.0, "NL": 21.0, "PT": 23.0, "IT": 22.0,
       "RO": 19.0, "FR": 20.0, "SE": 25.0, "FI": 24.0}

# The 22 columns a real `users` row has. An object mother sets every one;
# a factory shows you only what you overrode. Section 4 prices the difference.
USER_FIELDS = ("id", "email", "username", "role", "status", "country", "city",
               "credit_limit_cents", "currency", "locale", "timezone",
               "marketing_opt_in", "created_day", "updated_day",
               "last_login_day", "failed_logins", "mfa_enabled", "plan",
               "referral_code", "billing_day", "deleted", "notes")

N_USERS = 300
N_PRODUCTS = 140
N_TESTS = 240


def make_user(uid: int, rng: random.Random) -> dict:
    ci = rng.randrange(len(CITIES))
    return {
        "id": uid, "email": f"user{uid}@example.com", "username": f"user{uid}",
        "role": rng.choices(ROLES, weights=(1, 8, 2))[0],
        "status": rng.choices(USER_STATES, weights=(8, 1, 1))[0],
        "country": CITY_COUNTRY[ci], "city": CITIES[ci],
        "credit_limit_cents": rng.choice((0, 0, 50_000, 100_000, 250_000)),
        "currency": "EUR", "locale": "en_GB", "timezone": "Europe/Berlin",
        "marketing_opt_in": rng.choice((0, 1)),
        "created_day": 19_000 + rng.randrange(400),
        "updated_day": 19_400 + rng.randrange(60),
        "last_login_day": 19_400 + rng.randrange(60),
        "failed_logins": rng.choice((0, 0, 0, 1, 3)),
        "mfa_enabled": rng.choice((0, 1)),
        "plan": rng.choice(("free", "pro", "team")),
        "referral_code": f"REF{uid:05d}", "billing_day": 1 + rng.randrange(28),
        "deleted": 0, "notes": "",
    }


def build_world(rng: random.Random) -> dict:
    """The three-year-old shared seed, generated. User 1 is the god fixture:
    every real seed.sql has one row that satisfied every precondition anyone
    ever needed, which is exactly why everyone used it."""
    users = [make_user(uid, rng) for uid in range(1, N_USERS + 1)]
    users[0].update(role="admin", status="active", country="DE", city="Dresden",
                    credit_limit_cents=250_000, email="admin@example.com",
                    username="admin", mfa_enabled=1, plan="team",
                    marketing_opt_in=1, failed_logins=0)
    products = [{"id": p, "sku": f"SKU-{p:04d}", "price_cents": 500 + 50 * p,
                 "vat_country": "DE", "active": 1}
                for p in range(1, N_PRODUCTS + 1)]
    addresses = [{"id": u["id"], "user_id": u["id"], "city": u["city"],
                  "country": u["country"], "postcode": f"{10000 + u['id']}"}
                 for u in users]
    orders: list[dict] = []
    items: list[dict] = []
    payments: list[dict] = []
    for u in users:
        n = 2 if u["id"] == 1 else rng.choices(
            (0, 1, 2, 3, 4, 5, 6, 7), weights=(4, 7, 9, 9, 7, 5, 3, 2))[0]
        for k in range(n):
            oid, total = len(orders) + 1, 0
            for _ in range(rng.randrange(1, 5)):
                prod = products[rng.randrange(N_PRODUCTS)]
                qty = rng.randrange(1, 4)
                total += prod["price_cents"] * qty
                items.append({"id": len(items) + 1, "order_id": oid,
                              "product_id": prod["id"], "qty": qty,
                              "unit_price_cents": prod["price_cents"]})
            orders.append({"id": oid, "user_id": u["id"],
                           "status": "paid" if u["id"] == 1
                                     else ORDER_STATES[k % 4],
                           "total_cents": total,
                           "created_day": 19_100 + rng.randrange(300)})
            if rng.random() < 0.31:
                payments.append({"id": len(payments) + 1, "order_id": oid,
                                 "amount_cents": total, "method": "card"})
    return {"users": users, "products": products, "addresses": addresses,
            "orders": orders, "items": items, "payments": payments,
            "vat": dict(VAT), "grown": 0}


TABLES = (("products", "products"), ("users", "users"),
          ("addresses", "addresses"), ("orders", "orders"),
          ("order_items", "items"), ("payments", "payments"))


def seed_row_count(world: dict) -> int:
    return sum(len(world[k]) for _, k in TABLES)


def write_seed_sql(world: dict, path: Path) -> int:
    """Emit the shared seed as one INSERT per row; return the line count."""
    lines = ["-- fixtures/seed.sql — the shared world every test depends on.",
             "-- Generated once, three years ago. Nobody knows what needs what.",
             "BEGIN;"]
    for table, key in TABLES:
        rows = world[key]
        lines.append(f"-- {table}: {len(rows)} rows")
        cols = ", ".join(rows[0].keys())
        for r in rows:
            vals = ", ".join(repr(v) if isinstance(v, str) else str(v)
                             for v in r.values())
            lines.append(f"INSERT INTO {table} ({cols}) VALUES ({vals});")
    lines.append(f"-- vat_rates: {len(world['vat'])} rows")
    for country, rate in world["vat"].items():
        lines.append(f"INSERT INTO vat_rates (country, rate) "
                     f"VALUES ('{country}', {rate});")
    lines.append("COMMIT;")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


# ----------------------------------------------------------------------------
# 1 · THE SHARED-FIXTURE TRAP: BLAST RADIUS OF ONE CHANGED FIELD
# ----------------------------------------------------------------------------
# A test declares two different things: what the data must satisfy for it to
# run at all (`needs`), and what its assertion reads (`reads`). The gap
# between those two sets is where the trap lives.

@dataclass(frozen=True)
class Archetype:
    name: str
    needs: tuple[str, ...]
    reads: tuple[str, ...]
    weight: int
    mutates: bool = False


ARCHETYPES: tuple[Archetype, ...] = (
    Archetype("test_admin_can_delete_any_order", ("role=admin", "status=active"),
              ("user.role",), 6),
    Archetype("test_admin_dashboard_totals", ("role=admin",),
              ("user.role", "orders.sum_total"), 4),
    Archetype("test_orders_page_two_is_empty", ("orders>=2",),
              ("orders.count",), 5),
    Archetype("test_order_list_is_newest_first", ("orders>=2",),
              ("orders.list",), 4),
    Archetype("test_invoice_total_matches_orders", ("orders>=1",),
              ("orders.sum_total",), 5),
    Archetype("test_first_order_gets_welcome_discount", ("orders>=1",),
              ("orders.first_id",), 3),
    Archetype("test_suspended_user_cannot_checkout", ("status=suspended",),
              ("user.status",), 4, mutates=True),
    Archetype("test_email_is_normalised_on_login", (), ("user.email",), 4),
    Archetype("test_credit_limit_blocks_large_order", ("credit>0",),
              ("user.credit_limit_cents",), 4, mutates=True),
    Archetype("test_vat_applied_for_eu_country", ("country=DE",),
              ("user.country", "vat.rate"), 4),
    Archetype("test_shipping_quote_uses_address_city", ("has_address",),
              ("address.city",), 3),
    Archetype("test_price_shown_includes_tax", (),
              ("product.price", "vat.rate"), 4),
    Archetype("test_viewer_cannot_edit_catalogue", ("role=viewer",),
              ("user.role",), 3),
    Archetype("test_refund_restores_credit", ("orders>=1", "credit>0"),
              ("orders.sum_total", "user.credit_limit_cents"), 3, mutates=True),
)

# Incidental preconditions a real test piles on top of its archetype: "an
# admin who is also on the team plan with MFA on". These are what make an
# object mother's method count explode (section 3).
EXTRA_AXES = ("plan=pro", "plan=team", "mfa=1", "mfa=0", "marketing=1",
              "country=DE", "credit>0", "status=active", "clean_logins")

# What each precondition pins down, so section 4 can ask whether a test's
# assertion depends on something the test never stated.
NEED_COVERS = {
    "role=admin": ("user.role",), "role=viewer": ("user.role",),
    "role=member": ("user.role",), "status=suspended": ("user.status",),
    "status=active": ("user.status",), "country=DE": ("user.country",),
    "credit>0": ("user.credit_limit_cents",), "has_address": ("address.city",),
    "orders>=1": ("orders.count", "orders.list", "orders.sum_total",
                  "orders.first_id"),
    "orders>=2": ("orders.count", "orders.list", "orders.sum_total",
                  "orders.first_id"),
    "plan=pro": ("user.plan",), "plan=team": ("user.plan",),
    "mfa=1": ("user.mfa_enabled",), "mfa=0": ("user.mfa_enabled",),
    "marketing=1": ("user.marketing_opt_in",),
    "clean_logins": ("user.failed_logins",),
}


def order_count(world: dict, uid: int) -> int:
    return sum(1 for o in world["orders"] if o["user_id"] == uid)


def satisfies(u: dict, world: dict, need: str) -> bool:
    if need.startswith(("role=", "status=", "country=", "plan=")):
        field, _, want = need.partition("=")
        return u[field] == want
    if need.startswith("mfa="):
        return u["mfa_enabled"] == int(need[4:])
    if need == "marketing=1":
        return u["marketing_opt_in"] == 1
    if need == "clean_logins":
        return u["failed_logins"] == 0
    if need == "credit>0":
        return u["credit_limit_cents"] > 0
    if need == "has_address":
        return True
    if need.startswith("orders>="):
        return order_count(world, u["id"]) >= int(need[8:])
    raise ValueError(need)


@dataclass
class Test:
    name: str
    arch: Archetype
    needs: tuple[str, ...]
    user_id: int
    product_id: int
    reads: frozenset


def sample_suite(rng: random.Random, n: int) -> list[tuple[Archetype, tuple]]:
    """One test = an archetype plus 0-3 incidental preconditions."""
    out = []
    for _ in range(n):
        arch = rng.choices(ARCHETYPES, weights=[a.weight for a in ARCHETYPES])[0]
        k = rng.choices((0, 1, 2, 3), weights=(30, 36, 22, 12))[0]
        extras = tuple(sorted(rng.sample(EXTRA_AXES, k)))
        out.append((arch, tuple(sorted(set(arch.needs) | set(extras)))))
    return out


def read_set(arch: Archetype, uid: int, pid: int) -> frozenset:
    out = set()
    for r in arch.reads:
        if r.startswith("user."):
            out.add(("user", uid, r.split(".", 1)[1]))
        elif r.startswith("orders."):
            out.add(("user", uid, r))
        elif r.startswith("address."):
            out.add(("address", uid, r.split(".", 1)[1]))
        elif r.startswith("product."):
            out.add(("product", pid, "price"))
        elif r == "vat.rate":
            out.add(("vat", "DE", "rate"))
    return frozenset(out)


def grow_seed(world: dict, needs: tuple[str, ...], rng: random.Random) -> int:
    """No existing row satisfies these preconditions, so someone appends one.
    This is how a seed file reaches 4,000 lines: one row at a time, forever."""
    uid = len(world["users"]) + 1
    u = make_user(uid, rng)
    for nd in needs:
        field, _, want = nd.partition("=")
        if field in ("role", "status", "plan"):
            u[field] = want
        elif field == "mfa":
            u["mfa_enabled"] = int(want)
        elif nd == "marketing=1":
            u["marketing_opt_in"] = 1
        elif nd == "clean_logins":
            u["failed_logins"] = 0
        elif nd == "credit>0":
            u["credit_limit_cents"] = 50_000
        elif field == "country":
            u["country"] = want
            u["city"] = CITIES[CITY_COUNTRY.index(want)]
    world["users"].append(u)
    world["addresses"].append({"id": uid, "user_id": uid, "city": u["city"],
                               "country": u["country"],
                               "postcode": f"{10000 + uid}"})
    for nd in needs:
        if nd.startswith("orders>="):
            for k in range(int(nd[8:])):
                oid = len(world["orders"]) + 1
                world["orders"].append(
                    {"id": oid, "user_id": uid, "status": "paid",
                     "total_cents": 1500 + 100 * k, "created_day": 19_300 + k})
                world["items"].append(
                    {"id": len(world["items"]) + 1, "order_id": oid,
                     "product_id": 1, "qty": 1, "unit_price_cents": 550})
    world["grown"] += 1
    return uid


def bind_shared(suite, world: dict, rng: random.Random) -> list[Test]:
    """How a test finds data in a shared seed: grep the file and take the
    first row that works. Four times in five that is the lowest id."""
    cache: dict[tuple[str, ...], list[int]] = {}
    tests = []
    for i, (arch, needs) in enumerate(suite):
        if needs not in cache:
            cache[needs] = [u["id"] for u in world["users"]
                            if all(satisfies(u, world, nd) for nd in needs)]
        matches = cache[needs]
        if not matches:
            matches = cache[needs] = [grow_seed(world, needs, rng)]
        uid = matches[0] if rng.random() < 0.80 else rng.choice(matches[:5])
        pid = 1 if rng.random() < 0.85 else rng.randrange(1, 6)
        tests.append(Test(f"{arch.name}_{i}", arch, needs, uid, pid,
                          read_set(arch, uid, pid)))
    return tests


def bind_factory(suite) -> list[Test]:
    """How a test finds data with factories: it builds exactly what it needs,
    with ids from a sequence, so no two tests can collide."""
    return [Test(f"{arch.name}_{i}", arch, needs, 10_001 + i, 20_001 + i,
                 read_set(arch, 10_001 + i, 20_001 + i))
            for i, (arch, needs) in enumerate(suite)]


CHANGES: tuple[tuple[str, frozenset, tuple[str, ...]], ...] = (
    ("user 1 role: admin -> member",
     frozenset({("user", 1, "role")}), ("role=admin",)),
    ("add a 3rd order to user 1 (to test pagination)",
     frozenset({("user", 1, "orders.count"), ("user", 1, "orders.sum_total"),
                ("user", 1, "orders.list")}), ()),
    ("product 1 price: 550 -> 590 cents",
     frozenset({("product", 1, "price")}), ()),
    ("DE VAT rate: 19.0 -> 20.0 (reference data)",
     frozenset({("vat", "DE", "rate")}), ()),
)


def failures(tests: list[Test], changed: frozenset,
             invalidated: tuple[str, ...]) -> int:
    n = 0
    for t in tests:
        broke = bool(t.reads & changed)
        if not broke and invalidated:
            # The change also destroyed a precondition this test declared.
            broke = t.user_id == 1 and any(nd in t.needs for nd in invalidated)
        n += broke
    return n


def section_1(world: dict, tmp: Path) -> dict:
    banner("1 · THE SHARED-FIXTURE TRAP: BLAST RADIUS OF ONE FIELD")
    suite = sample_suite(random.Random(SEED + 2), N_TESTS)
    shared = bind_shared(suite, world, random.Random(SEED + 1))
    factory = bind_factory(suite)
    seed_path = tmp / "seed.sql"
    seed_lines = write_seed_sql(world, seed_path)
    rows = seed_row_count(world)
    factory_lines = source_block_lines("FACTORY-DEFS")
    on_user_1 = sum(1 for t in shared if t.user_id == 1)
    distinct = len({t.user_id for t in shared})

    print(f"  shared seed : {seed_lines:,} lines, {rows:,} rows, "
          f"{seed_path.stat().st_size / 1024:.0f} KiB — of which "
          f"{world['grown']} users were")
    print("                appended by this suite, because no existing row fit")
    print(f"  factory code: {factory_lines} lines of definitions, measured "
          f"from this file; 0 rows until asked")
    print(f"  suite       : {N_TESTS} tests, {len(ARCHETYPES)} archetypes, "
          f"identical in both worlds")
    print(f"  binding     : shared -> {on_user_1} tests "
          f"({on_user_1 / N_TESTS:.1%}) on user 1, {distinct} distinct users; "
          f"factory -> {len(factory)}, 0 shared\n")

    print(f"  {'one change to the fixture':<46}{'shared':>8}{'factory':>9}")
    out = {}
    for label, changed, invalid in CHANGES:
        fs, ff = (failures(shared, changed, invalid),
                  failures(factory, changed, invalid))
        print(f"  {label:<46}{fs:>8}{ff:>9}")
        out[label] = (fs, ff)
    worst = max(out.values(), key=lambda v: v[0])[0]
    print(f"\n  worst single-field change: {worst} of {N_TESTS} tests "
          f"({worst / N_TESTS:.1%}) in the shared world, 0 in")
    print("  the factory world, and the code under test did not move. Now read")
    print("  the last row: DE's VAT rate is reference data, no factory invents")
    print("  a country, so it breaks both worlds equally. Factories do not")
    print("  abolish shared state — they shrink it to the genuinely global")
    print("  rows, and those are few enough to list.")
    return {"seed_lines": seed_lines, "rows": rows, "shared": shared,
            "factory": factory, "suite": suite, "on_user_1": on_user_1,
            "distinct": distinct, "changes": out, "grown": world["grown"],
            "world": world, "factory_lines": factory_lines, "worst": worst,
            "kib": seed_path.stat().st_size / 1024}


# ----------------------------------------------------------------------------
# 2 · THE COUPLING MATRIX: THE CELLS NOBODY CAN EVER CHANGE
# ----------------------------------------------------------------------------
# For every cell of the shared seed, how many tests read it? The answer is a
# power law, and the head of it is a list of columns that are now frozen.

def section_2(state: dict) -> dict:
    banner("2 · THE COUPLING MATRIX: WHICH CELLS ARE NOW FROZEN")

    def matrix(tests: list[Test]) -> Counter:
        c: Counter = Counter()
        for t in tests:
            for r in t.reads:
                c[r] += 1
        return c

    ms, mf = matrix(state["shared"]), matrix(state["factory"])
    seed_cells = [(k, v) for k, v in ranked(ms) if k[0] != "vat"]
    f_seed = [(k, v) for k, v in mf.items() if k[0] != "vat"]
    vat_reads = ms[("vat", "DE", "rate")]
    top1, head = seed_cells[0], sum(n for _, n in seed_cells[:5])
    total_reads = sum(ms.values())

    print(f"  a cell is one (entity, id, field). Every cell in seed.sql that "
          f"the {N_TESTS}")
    print("  tests' assertions depend on, ranked:\n")
    print(f"  {'#':>3}  {'cell in the shared seed':<32}{'tests':>7}"
          f"{'% of suite':>12}   verdict")
    for i, ((ent, ident, fld), n) in enumerate(seed_cells[:10], 1):
        verdict = ("frozen — you cannot change it" if n >= 24 else
                   "read all 10+ tests first" if n >= 10 else "survivable")
        print(f"  {i:>3}  {f'{ent}[{ident}].{fld}':<32}{n:>7}"
              f"{n / N_TESTS:>11.1%}   {verdict}")

    print(f"\n  {'':<5}{'distribution':<32}{'shared':>10}{'factory':>10}")
    for label, a, b in [
            ("distinct cells the suite reads", len(ms), len(mf)),
            ("total reads across the suite", total_reads, sum(mf.values())),
            ("most tests reading one SEED cell", top1[1],
             max(v for _, v in f_seed)),
            ("seed cells read by 2+ tests",
             sum(1 for k, v in ms.items() if k[0] != "vat" and v > 1),
             sum(1 for _, v in f_seed if v > 1)),
            ("seed cells read by 10+ tests",
             sum(1 for k, v in ms.items() if k[0] != "vat" and v > 10),
             sum(1 for _, v in f_seed if v > 10)),
            ("reads of the one reference cell", vat_reads, vat_reads)]:
        print(f"  {'':<5}{label:<32}{a:>10,}{b:>10,}")

    seed_rows = state["rows"]
    load_bearing = len({(e, i) for (e, i, _) in ms if e != "vat"})
    print(f"\n  the top 5 seed cells carry {head}/{total_reads} = "
          f"{head / total_reads:.1%} of every read. {load_bearing} of")
    print(f"  {seed_rows:,} seeded rows ({load_bearing / seed_rows:.2%}) are "
          f"load-bearing; the other {seed_rows - load_bearing:,} exist to")
    print("  make the file look like a database. The ballast is free. The head")
    print(f"  is not: {top1[0][0]}[{top1[0][1]}].{top1[0][2]} is read by "
          f"{top1[1]} tests ({top1[1] / N_TESTS:.1%}) and no test says so.")
    print(f"  the factory world reads {len(mf)} cells, of which exactly "
          f"{sum(1 for v in mf.values() if v > 1)} is shared: vat[DE].rate,")
    print(f"  read by {vat_reads} tests in BOTH worlds. That is the "
          f"irreducible core — reference")
    print("  data a factory has no business inventing. Everything above it in")
    print("  the shared ranking is coupling you chose.")
    return {"ms": ms, "mf": mf, "top1": top1, "load_bearing": load_bearing,
            "head_share": head / total_reads, "total_reads": total_reads,
            "vat_reads": vat_reads}


# ----------------------------------------------------------------------------
# 3 · OBJECT MOTHERS vs BUILDERS vs FACTORIES
# ----------------------------------------------------------------------------
# Three patterns for the same job, all three implemented below. The
# measurement is what each does as the suite grows and the schema moves.

# >>> MOTHER-DEFS
def admin_user() -> dict:
    """An object mother: a named, fully-formed specimen. One per scenario."""
    return {"id": 1, "email": "admin@example.com", "username": "admin",
            "role": "admin", "status": "active", "country": "DE",
            "city": "Dresden", "credit_limit_cents": 250_000,
            "currency": "EUR", "locale": "en_GB", "timezone": "Europe/Berlin",
            "marketing_opt_in": 1, "created_day": 19_000,
            "updated_day": 19_400, "last_login_day": 19_400,
            "failed_logins": 0, "mfa_enabled": 1, "plan": "team",
            "referral_code": "REF00001", "billing_day": 1, "deleted": 0,
            "notes": ""}


def suspended_user() -> dict:
    row = admin_user()
    row.update(id=2, email="susp@example.com", username="susp", role="member",
               status="suspended", plan="free", credit_limit_cents=0,
               mfa_enabled=0, referral_code="REF00002")
    return row


def admin_user_on_pro_with_mfa() -> dict:
    row = admin_user()
    row.update(id=3, email="adminpro@example.com", username="adminpro",
               plan="pro", referral_code="REF00003")
    return row
# <<< MOTHER-DEFS


# >>> FACTORY-DEFS
DEFAULT_USER = {
    "email": None, "username": None, "role": "member", "status": "active",
    "country": "DE", "city": "Dresden", "credit_limit_cents": 0,
    "currency": "EUR", "locale": "en_GB", "timezone": "Europe/Berlin",
    "marketing_opt_in": 0, "created_day": 19_000, "updated_day": 19_400,
    "last_login_day": 19_400, "failed_logins": 0, "mfa_enabled": 0,
    "plan": "free", "referral_code": None, "billing_day": 1,
    "deleted": 0, "notes": "",
}


class Sequence:
    """factory_boy's Sequence: a counter owned by the factory. A sequence is
    why a factory cannot emit a duplicate. Section 6 prices the alternative."""

    def __init__(self, start: int = 1) -> None:
        self.n = start - 1

    def __call__(self) -> int:
        self.n += 1
        return self.n


class UserFactory:
    """Sensible defaults plus explicit overrides. The override list is the
    test's own statement of what its assertion depends on."""

    def __init__(self) -> None:
        self.seq = Sequence()
        self.built: list[dict] = []

    def build(self, **overrides: object) -> dict:
        n = self.seq()
        row = dict(DEFAULT_USER)
        row["id"] = 10_000 + n
        row["email"] = f"user-{n}@test.invalid"        # sequence, not random
        row["username"] = f"user-{n}"
        row["referral_code"] = f"REF{n:05d}"
        row.update(overrides)
        if "city" in overrides and "country" not in overrides:
            row["country"] = CITY_COUNTRY[CITIES.index(str(row["city"]))]
        self.built.append(row)
        return row


class UserBuilder:
    """Fluent builder: the same power, more ceremony, and every transition
    gets a name you can grep for."""

    def __init__(self, factory: UserFactory) -> None:
        self._f = factory
        self._over: dict[str, object] = {}

    def admin(self) -> "UserBuilder":
        self._over["role"] = "admin"
        return self

    def suspended(self) -> "UserBuilder":
        self._over["status"] = "suspended"
        return self

    def on_plan(self, plan: str) -> "UserBuilder":
        self._over["plan"] = plan
        return self

    def with_credit(self, cents: int) -> "UserBuilder":
        self._over["credit_limit_cents"] = cents
        return self

    def build(self) -> dict:
        return self._f.build(**self._over)
# <<< FACTORY-DEFS


def section_3(state: dict) -> dict:
    banner("3 · OBJECT MOTHERS vs BUILDERS vs FACTORIES")
    suite = state["suite"]
    print("  object mother: a named specimen —  admin_user_on_pro_with_mfa()")
    print("  builder      : a fluent chain    —  UserBuilder().admin()"
          ".on_plan('pro')")
    print("  factory      : defaults+overrides—  user(role='admin', "
          "plan='pro')\n")
    print("  a mother's NAME is its precondition set, so a suite needs one")
    print("  mother per distinct set. Count them as tests accumulate:\n")

    growth, seen = [], set()
    for i, (_arch, needs) in enumerate(suite, 1):
        seen.add(needs)
        if i in (30, 60, 120, 240):
            growth.append((i, len(seen)))
    print(f"  {'tests written':>14}{'mothers required':>19}"
          f"{'tests per mother':>19}")
    for n, m in growth:
        print(f"  {n:>14}{m:>19}{n / m:>19.1f}")
    axes = sorted({nd for a in ARCHETYPES for nd in a.needs} | set(EXTRA_AXES))
    print(f"  {'ceiling':>14}{2 ** len(axes):>19}{'—':>19}   "
          f"(2^{len(axes)} independent preconditions)")

    mothers = len(seen)
    per_mother = source_block_lines("MOTHER-DEFS") / 3
    factory_lines = source_block_lines("FACTORY-DEFS")
    builder_calls = sum(1 + len(nd) for _a, nd in suite)
    print(f"\n  {'pattern':<16}{'definition':>12}{'call lines':>13}"
          f"{'edits to add':>15}{'a new':>16}")
    print(f"  {'':<16}{'lines':>12}{'in the suite':>13}{'one column':>15}"
          f"{'scenario costs':>16}")
    print(f"  {'object mother':<16}{int(per_mother * mothers):>12,}"
          f"{N_TESTS:>13}{mothers:>15}{'a new method':>16}")
    print(f"  {'builder':<16}{factory_lines:>12}{builder_calls:>13,}{1:>15}"
          f"{'nothing':>16}")
    print(f"  {'factory':<16}{factory_lines:>12}{N_TESTS:>13}{1:>15}"
          f"{'nothing':>16}")
    print(f"\n  {mothers} mothers at {per_mother:.1f} lines each is "
          f"{int(per_mother * mothers):,} lines of fixture code against")
    print(f"  {factory_lines} for the factory — "
          f"{per_mother * mothers / factory_lines:.0f}x. One new required "
          f"column costs {mothers} edits or 1,")
    print(f"  and {mothers} is not a constant: it is the mother count, which "
          f"only goes up.")
    print(f"  the builder costs more at the call site ({builder_calls:,} lines "
          f"vs {N_TESTS}) and buys")
    print("  one thing for it: every precondition has a name you can grep.")
    return {"mothers": mothers, "axes": len(axes), "per_mother": per_mother,
            "mother_total": int(per_mother * mothers),
            "factory_lines": factory_lines, "builder_calls": builder_calls,
            "growth": growth}


# ----------------------------------------------------------------------------
# 4 · DEFAULTS, OVERRIDES AND THE RELEVANCE PRINCIPLE
# ----------------------------------------------------------------------------
# A test should state, in its own body, exactly the data its assertion depends
# on — and nothing else. That is two measurements: how much of what the test
# shows you matters, and how much of what matters it never showed you.

def section_4(state: dict) -> dict:
    banner("4 · THE RELEVANCE PRINCIPLE, MEASURED")
    suite, shared, world = state["suite"], state["shared"], state["world"]
    print("  one question asked three ways: to know what a test depends on,")
    print("  how much must you read elsewhere, how much does it state itself,")
    print("  and what does its assertion read that it never mentioned?\n")

    n_fields = len(USER_FIELDS)
    styles = ("shared seed", "object mother", "factory")
    elsewhere = dict.fromkeys(styles, 0.0)
    in_body = dict.fromkeys(styles, 0.0)
    stated = dict.fromkeys(styles, 0.0)
    unstated = dict.fromkeys(styles, 0)
    deps_total = 0.0
    for t, (arch, needs) in zip(shared, suite):
        deps = set(arch.reads)
        deps_total += len(deps)
        covered = {c for nd in needs for c in NEED_COVERS.get(nd, ())}
        n_orders = max([int(nd[8:]) for nd in needs
                        if nd.startswith("orders>=")] or [0])
        # user row + address row + the product row + this user's orders
        elsewhere["shared seed"] += 3 + order_count(world, t.user_id)
        elsewhere["object mother"] += n_fields + 6 * n_orders
        in_body["object mother"] += 1                  # just the name
        in_body["factory"] += len(needs)
        stated["factory"] += len(deps & covered)
        unstated["shared seed"] += 1
        unstated["object mother"] += 1
        unstated["factory"] += bool(deps - covered)

    print(f"  {'style':<16}{'data rows to':>14}{'values stated':>15}"
          f"{'of the deps,':>14}{'tests with an':>16}")
    print(f"  {'':<16}{'read ELSEWHERE':>14}{'in the body':>15}"
          f"{'stated':>14}{'unstated dep':>16}")
    out = {}
    for style in styles:
        els, body = elsewhere[style] / N_TESTS, in_body[style] / N_TESTS
        frac = stated[style] / deps_total
        print(f"  {style:<16}{els:>14.1f}{body:>15.1f}{frac:>13.1%}"
              f"{unstated[style]:>16}")
        out[style] = (els, body, frac, unstated[style])

    els = elsewhere["shared seed"] / N_TESTS
    print(f"\n  the shared-seed row is the lesson. Its assertion depends on "
          f"{deps_total / N_TESTS:.2f} things,")
    print(f"  states none, and the only route to them is {els:.1f} rows "
          f"somewhere inside a")
    print(f"  {state['seed_lines']:,}-line file, with nothing to say which "
          f"{els:.1f}.")
    print("  the object mother is no better here: `admin_user()` is a name,")
    print(f"  not data — {n_fields} fields one hop away, still nothing in the "
          f"body.")
    print(f"  the factory states {out['factory'][2]:.1%} of what its "
          f"assertions read, at {out['factory'][1]:.1f} values per test —")
    print(f"  MORE than the {deps_total / N_TESTS:.2f} it reads, because a "
          f"test states its preconditions as")
    print("  well as its dependencies. That is the shape you want.")
    print(f"  the honest residual: {unstated['factory']} of {N_TESTS} factory "
          f"tests ({unstated['factory'] / N_TESTS:.1%}) still assert on a")
    print("  value they never stated — a default, or reference data. Defaults")
    print("  are shared state with better manners. The fix is not fewer")
    print("  defaults; it is to restate every value the assertion names, even")
    print("  when the default already has it right.")
    return out


# ----------------------------------------------------------------------------
# 5 · REFERENTIAL INTEGRITY FOR FREE — AND THE CYCLE
# ----------------------------------------------------------------------------
# A SubFactory creates the parent a child needs. That is the feature. It is
# also how one requested row becomes nine written rows, and how a schema with
# a mutual foreign key becomes unbounded recursion.

SCHEMA_PARENTS = {
    "order_item": ("order", "product"), "order": ("user", "shipping_address"),
    "shipping_address": ("user",), "user": ("account",), "account": (),
    "product": ("catalogue",), "catalogue": (),
}
CYCLIC = {"user": ("default_address",), "default_address": ("user",)}


def create(entity: str, counts: Counter, reuse: set | None = None,
           top: bool = True) -> None:
    """Recursive SubFactory creation. `reuse` models passing an existing
    parent in instead of letting the factory make another one."""
    if not top and reuse is not None and entity in reuse:
        return
    counts[entity] += 1
    if reuse is not None:
        reuse.add(entity)
    for parent in SCHEMA_PARENTS[entity]:
        create(parent, counts, reuse, top=False)


def create_cyclic(entity: str, counts: Counter, depth: int, limit: int) -> int:
    """Naive SubFactory recursion across a mutual FK. There is no base case;
    `limit` exists only so this program terminates."""
    if depth >= limit:
        return depth
    counts[entity] += 1
    best = depth
    for parent in CYCLIC[entity]:
        best = max(best, create_cyclic(parent, counts, depth + 1, limit))
    return best


def section_5() -> dict:
    banner("5 · REFERENTIAL INTEGRITY FOR FREE, AND WHAT IT COSTS")
    one: Counter = Counter()
    create("order_item", one)
    per_item = sum(one.values())
    print("  a test asks the factory for ONE order_item. The SubFactory chain")
    print("  walks every foreign key and writes:")
    print("      " + "  ".join(f"{e}={n}" for e, n in sorted(one.items())))
    print(f"      TOTAL {per_item} rows for 1 requested row — and note user=2, "
          f"account=2:")
    print("      the order made a user, its shipping_address made another.\n")

    fan: Counter = Counter()
    shared: Counter = Counter()
    reuse: set = set()
    for _ in range(10):
        create("order_item", fan)
        create("order_item", shared, reuse)
    fan_rows, reuse_rows = sum(fan.values()), sum(shared.values())
    print("  now the test wants ONE order with 10 line items.")
    print(f"    each item builds its own parents : {fan_rows:>4} rows, "
          f"{fan['order']} orders, {fan['user']} users")
    print(f"    parents created once and passed  : {reuse_rows:>4} rows, "
          f"{shared['order']} order,   {shared['user']} user")
    print(f"    ratio {fan_rows / reuse_rows:.1f}x — and the first version "
          f"tests 10 orders of one item")
    print("    each, which is not what the author meant.\n")

    cyc: Counter = Counter()
    reached = create_cyclic("user", cyc, 0, 50)
    print("  the cycle: users.default_address_id -> addresses.id and")
    print("  addresses.user_id -> users.id. Two SubFactories pointing at each")
    print(f"  other have no base case: depth {reached} and "
          f"{sum(cyc.values())} rows written before an")
    print("  artificial limit stopped it (in factory_boy, a RecursionError).")
    print("  the fix is two statements: create with the nullable side NULL,")
    print("  then fill it in with a post_generation hook. Rows: 2. Always 2.")
    print(f"\n  at suite scale: {N_TESTS} x {per_item} = "
          f"{N_TESTS * per_item:,} rows written for {N_TESTS} asked for — the")
    print("  honest price of referential integrity for free, and why section 7")
    print("  exists.")
    return {"per_item": per_item, "fan": fan_rows, "reuse": reuse_rows,
            "ratio": fan_rows / reuse_rows, "depth": reached,
            "cyc_rows": sum(cyc.values()), "suite_cost": N_TESTS * per_item}


# ----------------------------------------------------------------------------
# 6 · UNIQUENESS: THE BIRTHDAY PROBLEM IS YOUR FLAKE RATE
# ----------------------------------------------------------------------------
# `email = f"user{random.randint(1, 10**6)}@test.com"` looks unique. It is a
# birthday-problem draw (Feller 1968, sec. II.3). Compute it exactly, simulate
# it, and check the two agree.

SUITE_SIZE = 5_000
SPACE = 10 ** 6


def birthday_p(n: int, m: int) -> float:
    """P(at least one collision) drawing n values uniformly from m, exactly."""
    if n > m:
        return 1.0
    return -math.expm1(sum(math.log1p(-i / m) for i in range(n)))


def simulate_collisions(n: int, m: int, trials: int, seed: int) -> int:
    rng = random.Random(seed)
    hits = 0
    for _ in range(trials):
        seen: set[int] = set()
        for _ in range(n):
            v = rng.randrange(m)
            if v in seen:
                hits += 1
                break
            seen.add(v)
    return hits


def section_6() -> dict:
    banner("6 · UNIQUENESS: A RANDOM 'UNIQUE' FIELD IS A FLAKE RATE")
    print('  the line under test:  email = f"user{randint(1, 10**6)}@test.com"')
    print(f"  a {SUITE_SIZE:,}-test suite draws {SUITE_SIZE:,} of them from "
          f"{SPACE:,} slots.\n")
    print(f"  {'suite size':>11}{'analytic':>12}{'simulated':>12}{'trials':>9}"
          f"{'expected dup pairs':>20}")
    for n, trials in ((100, 20_000), (250, 8_000), (500, 4_000),
                      (1_000, 2_000), (2_000, 1_000), (5_000, 400)):
        emp = simulate_collisions(n, SPACE, trials, SEED + n) / trials
        print(f"  {n:>11,}{birthday_p(n, SPACE):>11.4%}{emp:>12.4%}"
              f"{trials:>9,}{n * (n - 1) / 2 / SPACE:>20.3f}")

    p5000 = birthday_p(SUITE_SIZE, SPACE)
    lo, hi = 2, SUITE_SIZE
    while lo < hi:                       # smallest suite with P >= 1%
        mid = (lo + hi) // 2
        lo, hi = (mid + 1, hi) if birthday_p(mid, SPACE) < 0.01 else (lo, mid)
    print("\n  analytic and simulated agree at every size, so the closed form")
    print(f"  can be trusted where simulating is pointless. At {SUITE_SIZE:,} "
          f"tests, P(collision)")
    print(f"  = {p5000:.6%}: not a flaky suite, a broken one that passes "
          f"{1 - p5000:.6%} of the time,")
    print(f"  with {SUITE_SIZE * (SUITE_SIZE - 1) / 2 / SPACE:.1f} expected "
          f"duplicate pairs per run. And the threshold nobody")
    print("  thinks they are near — a 1% chance of a red build per run, for")
    print(f"  this reason alone — arrives at {lo} tests. Not 5,000. {lo}.\n")

    print(f"  {'strategy for a unique field':<38}{'distinct values':>22}"
          f"{'P(collide) @5,000':>19}")
    for label, m in (("randint(1, 10**6)", SPACE),
                     ("randint(1, 10**12)", 10 ** 12),
                     ("random 8-hex suffix (16**8)", 16 ** 8),
                     ("uuid4 — 122 random bits (RFC 9562)", 2 ** 122)):
        p = birthday_p(SUITE_SIZE, m)
        print(f"  {label:<38}{f'{m:,}' if m < 10 ** 15 else f'{m:.3e}':>22}"
              f"{f'{p:.6%}' if p > 0.01 else f'{p:.3e}':>19}")
    print(f"  {'factory Sequence / itertools.count':<38}{'unbounded':>22}"
          f"{'0 by construction':>19}")
    print("\n  a sequence is not 'less random'. It is a different guarantee —")
    print("  uniqueness proved rather than probable, for one integer of state.")
    print("  UUID4 works too, at 36 bytes and an unreadable assertion message.")
    print("  Both beat randint by so much that the only reason anyone writes")
    print("  randint is that it looks obviously fine.")
    return {"p5000": p5000, "n_1pct": lo,
            "pairs": SUITE_SIZE * (SUITE_SIZE - 1) / 2 / SPACE,
            "p_uuid": birthday_p(SUITE_SIZE, 2 ** 122),
            "p_hex": birthday_p(SUITE_SIZE, 16 ** 8)}


# ----------------------------------------------------------------------------
# 7 · VOLUME: WHEN THE FIXTURE IS THE SUITE'S RUN TIME
# ----------------------------------------------------------------------------
# Three ways to put a corpus in front of 300 tests, against real sqlite3. Wall
# clock is not reproducible, so the currency is rows written and statements
# executed — which is what the wall clock is proportional to.

VOL_TESTS = 300
VOL_CORPUS = 1_000
INSERT = "INSERT INTO events VALUES (?,?,?,?)"
PROBE = "SELECT count(*) FROM events WHERE user_id = 7"


def make_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA journal_mode = MEMORY")
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, user_id INT, "
                 "kind TEXT, amount_cents INT)")
    conn.execute("CREATE INDEX ix_events_user ON events (user_id)")
    return conn


def corpus_rows(n: int, offset: int = 0) -> list[tuple]:
    return [(offset + i, i % 97, "click" if i % 3 else "purchase",
             100 + (i % 500)) for i in range(1, n + 1)]


def section_7() -> dict:
    banner("7 · VOLUME: 300 TESTS THAT EACH NEED A 1,000-ROW CORPUS")
    vol_suite = sample_suite(random.Random(SEED + 8), VOL_TESTS)
    mutators = sum(1 for a, _ in vol_suite if a.mutates)
    rows = corpus_rows(VOL_CORPUS)
    print(f"  {VOL_TESTS} tests, {VOL_CORPUS:,} rows each, real sqlite3 in a "
          f"temp dir, each test isolated")
    print(f"  by BEGIN/ROLLBACK (lesson 06's technique). {mutators} of the "
          f"{VOL_TESTS} tests ({mutators / VOL_TESTS:.1%}) WRITE")
    print("  to the corpus — counted from the same archetypes, not assumed.\n")

    results = []
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        conn = make_db(tmp / "a.db")                    # per-test, row by row
        for _ in range(VOL_TESTS):
            conn.execute("BEGIN")
            for r in rows:
                conn.execute(INSERT, r)
            conn.execute(PROBE)
            conn.execute("ROLLBACK")
        results.append(["per-test, row by row", conn.total_changes,
                        VOL_TESTS * (VOL_CORPUS + 3), VOL_TESTS])
        conn.close()

        conn = make_db(tmp / "b.db")                    # per-test, one batch
        for _ in range(VOL_TESTS):
            conn.execute("BEGIN")
            conn.executemany(INSERT, rows)
            conn.execute(PROBE)
            conn.execute("ROLLBACK")
        results.append(["per-test, one batch (COPY-shaped)", conn.total_changes,
                        VOL_TESTS * 4, VOL_TESTS])
        conn.close()

        conn = make_db(tmp / "c.db")                    # session-scoped corpus
        conn.execute("BEGIN")
        conn.executemany(INSERT, rows)
        conn.execute("COMMIT")
        stmts, builds = 3, 1
        for arch, _ in vol_suite:
            if arch.mutates:
                conn.execute("BEGIN")
                conn.executemany(INSERT, corpus_rows(VOL_CORPUS, VOL_CORPUS))
                conn.execute(PROBE)
                conn.execute("ROLLBACK")
                stmts, builds = stmts + 4, builds + 1
            else:
                conn.execute(PROBE)
                stmts += 1
        results.append(["session corpus + per-test writers", conn.total_changes,
                        stmts, builds])
        conn.close()

    print(f"  {'strategy':<36}{'rows written':>14}{'statements':>12}"
          f"{'corpus builds':>15}")
    for label, changed, stmts, builds in results:
        print(f"  {label:<36}{changed:>14,}{stmts:>12,}{builds:>15,}")
    base = results[0][1]
    print(f"\n  {'strategy':<36}{'rows':>8}{'stmts':>8}   isolation")
    for (label, changed, stmts, _), note in zip(results, (
            "every test gets a pristine corpus",
            "every test gets a pristine corpus",
            "readers share it; writers build their own")):
        print(f"  {label:<36}{base / max(changed, 1):>7.1f}x"
              f"{results[0][2] / stmts:>7.0f}x   {note}")

    ceiling, actual = base / VOL_CORPUS, base / results[2][1]
    print(f"\n  the batch writes exactly the same {results[1][1]:,} rows as "
          f"the row-by-row version,")
    print(f"  in {results[1][2]:,} statements instead of {results[0][2]:,} — a "
          f"{results[0][2] / results[1][2]:.0f}x cut in round trips and 0x")
    print("  in rows. Rows are the floor you cannot batch away; only sharing")
    print(f"  removes them. And sharing under-delivers: a "
          f"{ceiling:.0f}x-looking win returns {actual:.1f}x,")
    print(f"  because {mutators} of {VOL_TESTS} tests write and must build "
          f"their own. The gap between")
    print("  those two numbers is the design problem in one line: you cannot")
    print("  share a corpus with a test that changes it.")
    return {"rows_a": results[0][1], "stmts_a": results[0][2],
            "rows_b": results[1][1], "stmts_b": results[1][2],
            "rows_c": results[2][1], "stmts_c": results[2][2],
            "mutators": mutators, "ceiling": ceiling, "actual": actual,
            "builds_c": results[2][3],
            "stmt_ratio": results[0][2] / results[1][2]}


# ----------------------------------------------------------------------------
# 8 · PRODUCTION DATA IS NOT TEST DATA
# ----------------------------------------------------------------------------
# Two attacks on "we anonymised it", both measured: a consistent hash is one
# dictionary away from plaintext, and the columns you left alone re-identify
# people by themselves (Sweeney, k-Anonymity, IJUFKS 10(5), 2002). Then the
# fix that is worse: shuffling a column preserves every marginal distribution
# and destroys every join.

PROD_ROWS = 20_000
SYL_A = ("an", "be", "ca", "da", "el", "fi", "gi", "hu", "in", "jo",
         "ka", "le", "mo", "ni", "or", "pi", "ra", "sa", "to", "um")
SYL_B = ("a", "el", "in", "ka", "na", "os", "ra", "us", "ya", "ir")
SYL_C = ("ad", "bo", "cr", "du", "ea", "fr", "ga", "ho", "iv", "ju",
         "ke", "la", "mo", "no", "oa", "pi", "qu", "ro", "sh", "ta")
SYL_D = ("ler", "yd", "ane", "nn", "ton", "ost", "le", "lt", "es", "ng",
         "rr", "mb", "tt", "vak", "kes")
DOMAIN = "acme-corp.example"


def section_8(state: dict) -> dict:
    banner("8 · ANONYMISATION: TWO WAYS IT DOES NOT WORK")
    rng = random.Random(SEED + 9)
    first_pool = [a + b for a in SYL_A for b in SYL_B]          # 200
    last_pool = [c + d for c in SYL_C for d in SYL_D]           # 300
    candidates = len(first_pool) * len(last_pool)
    people = []
    for f, l in rng.sample([(f, l) for f in first_pool for l in last_pool],
                           PROD_ROWS):
        ci = rng.randrange(len(CITIES))
        people.append({"email": f"{f}.{l}@{DOMAIN}", "city": CITIES[ci],
                       "postcode": f"{10_000 + rng.randrange(400)}",
                       "birth_year": 1955 + rng.randrange(50),
                       "birth_day": rng.randrange(365),
                       "gender": rng.choice(("f", "m", "x"))})
    masked = [{"email_hash": hashlib.sha256(p["email"].encode()).hexdigest(),
               **{k: v for k, v in p.items() if k != "email"}} for p in people]

    print(f"  a {PROD_ROWS:,}-row production dump, anonymised the usual way: "
          f"email -> sha256(email),")
    print("  everything else kept 'because the tests need realistic data'.\n")
    index = {m["email_hash"] for m in masked}
    recovered = sum(1 for f in first_pool for l in last_pool
                    if hashlib.sha256(f"{f}.{l}@{DOMAIN}".encode()).hexdigest()
                    in index)
    print("  ATTACK 1 — dictionary attack on the unsalted consistent hash. The")
    print(f"  address format is public (first.last@{DOMAIN}) and the")
    print("  attacker does not know who is in the dump, so they enumerate the")
    print(f"  whole name space: {len(first_pool)} x {len(last_pool)} = "
          f"{candidates:,} candidates hashed.")
    print(f"  rows re-identified: {recovered:,} of {PROD_ROWS:,} "
          f"({recovered / PROD_ROWS:.1%}). The hash column survived;")
    print("  every row behind it did not. A consistent hash is not encryption,")
    print("  it is an equality check over a domain the attacker can enumerate.")

    print("\n  ATTACK 2 — a join on the columns you did NOT mask. A row is")
    print("  re-identified when its quasi-identifier is unique in the dump, so")
    print("  any public list with the same columns names it (Sweeney 2002).\n")
    print(f"  {'quasi-identifier joined on':<42}{'cells':>9}{'k=1 rows':>10}"
          f"{'share':>9}")
    qi = {}
    for label, keyf in (
            ("(city, birth_year, gender)",
             lambda m: (m["city"], m["birth_year"], m["gender"])),
            ("(postcode, birth_year, gender)",
             lambda m: (m["postcode"], m["birth_year"], m["gender"])),
            ("(postcode, birth_year, birth_day, gender)",
             lambda m: (m["postcode"], m["birth_year"], m["birth_day"],
                        m["gender"]))):
        groups = Counter(keyf(m) for m in masked)
        uniq = sum(1 for g in groups.values() if g == 1)
        qi[label] = (len(groups), uniq, uniq / PROD_ROWS)
        print(f"  {label:<42}{len(groups):>9,}{uniq:>10,}"
              f"{uniq / PROD_ROWS:>8.1%}")
    fine = qi["(postcode, birth_year, birth_day, gender)"][2]
    coarse = qi["(city, birth_year, gender)"][2]
    print(f"\n  the third row is a date of birth, kept by every 'anonymised' "
          f"dump because")
    print(f"  the tests 'need realistic ages'. It leaves {fine:.1%} of the "
          f"dump uniquely")
    print("  identifiable from three public facts. Generalising the")
    print(f"  quasi-identifier is the fix, and row one is its price: "
          f"{coarse:.1%} unique, bought")
    print("  with exactly the realism you took the production dump for.\n")

    cities = [p["city"] for p in people]
    shuffled = list(cities)
    random.Random(SEED + 10).shuffle(shuffled)
    consistent = sum(1 for a, b in zip(cities, shuffled) if a == b)
    country_ok = sum(1 for p, c in zip(people, shuffled)
                     if CITY_COUNTRY[CITIES.index(c)]
                     == CITY_COUNTRY[CITIES.index(p["city"])])
    cross = sum(1 for t in state["shared"] if any(
        r[0] in ("address", "vat") or (r[0] == "user" and r[2] == "country")
        for r in t.reads))
    print("  THE 'FIX' — shuffle the city column so no row is a real person.")
    print(f"  {'marginal distribution preserved exactly':<48}"
          f"{str(Counter(cities) == Counter(shuffled)):>10}")
    print(f"  {'rows whose city still matches their address':<48}"
          f"{consistent:>10,}  {consistent / PROD_ROWS:.2%}")
    print(f"  {'rows whose country still matches their city':<48}"
          f"{country_ok:>10,}  {country_ok / PROD_ROWS:.2%}")
    print(f"  {'tests asserting a cross-table invariant':<48}"
          f"{cross:>10}  {cross / N_TESTS:.1%} of the suite")
    print("\n  every one of those tests now fails, and not because of a bug.")
    print("  shuffling preserves every marginal and destroys every joint")
    print("  distribution: the histograms are perfect and the joins are")
    print("  fiction. That is the worst of both — the data looks real enough")
    print("  that nobody checks it, and no invariant in it holds.")
    return {"recovered": recovered, "candidates": candidates, "qi": qi,
            "consistent": consistent, "consistent_pct": consistent / PROD_ROWS,
            "country_pct": country_ok / PROD_ROWS, "cross": cross,
            "fine": fine, "coarse": coarse}


# ----------------------------------------------------------------------------
# 9 · GOLDEN FILES: WHEN THE FIXTURE IS THE ASSERTION
# ----------------------------------------------------------------------------
# A golden (approval) file is a fixture that is also the expected output. It is
# reviewed as a diff, so its format decides whether the review is real.

N_GOLDEN = 60


def api_response(i: int, rng: random.Random, currency: bool = False,
                 volatile: bool = False, bug: bool = False) -> dict:
    total = 1000 + 37 * i
    body = {
        "order_id": 5000 + i, "status": "paid",
        "customer": {"id": 900 + i, "email": f"user{i}@example.com",
                     "country": "DE"},
        "lines": [{"sku": f"SKU-{(i * 7 + k) % 120:04d}", "qty": 1 + k,
                   "unit_price_cents": 500 + 50 * ((i + k) % 40)}
                  for k in range(3)],
        "total_cents": total, "vat_cents": total * (20 if bug else 19) // 100,
    }
    if currency:
        body["currency"] = "EUR"
    if volatile:
        body["generated_at"] = (f"2026-07-18T09:{i % 60:02d}:"
                                f"{rng.randrange(60):02d}Z")
    return body


def diff_size(old: str, new: str) -> tuple[int, int]:
    d = list(difflib.unified_diff(old.splitlines(), new.splitlines(), n=0))
    changed = [l for l in d if l[:1] in "+-" and l[:3] not in ("+++", "---")]
    return len(changed), sum(len(l) for l in changed)


def section_9() -> dict:
    banner("9 · GOLDEN FILES: THE FORMAT IS THE REVIEW")
    rng = random.Random(SEED + 11)
    base = [api_response(i, rng) for i in range(N_GOLDEN)]
    after = [api_response(i, rng, currency=True) for i in range(N_GOLDEN)]
    formats = (("json.dumps(obj)  — one line, no spaces", json.dumps),
               ("json.dumps(obj, indent=2, sort_keys=True)",
                lambda o: json.dumps(o, indent=2, sort_keys=True)))

    print(f"  {N_GOLDEN} golden files, one API response each. One benign "
          f"change: a `currency`")
    print("  field is added to every response.\n")
    print(f"  {'golden file format':<44}{'files':>7}{'diff lines':>12}"
          f"{'diff chars':>12}{'chars/file':>12}")
    out = {}
    for label, fmt in formats:
        sizes = [diff_size(fmt(b), fmt(a)) for b, a in zip(base, after)]
        lines, chars = sum(s[0] for s in sizes), sum(s[1] for s in sizes)
        print(f"  {label:<44}{N_GOLDEN:>7}{lines:>12,}{chars:>12,}"
              f"{chars / N_GOLDEN:>12,.0f}")
        out[label] = (lines, chars)
    ratio = out[formats[0][0]][1] / out[formats[1][0]][1]
    print(f"\n  same change, same {N_GOLDEN} files, {ratio:.0f}x the "
          f"characters to read. The reviewer of")
    print("  the pretty diff sees 60 identical one-line additions and can")
    print("  actually approve them; the reviewer of the one-line diff sees 60")
    print("  walls of JSON and approves faster, having read none of it.\n")

    pretty = formats[1][1]
    vol_a = [api_response(i, random.Random(SEED + 20), volatile=True)
             for i in range(N_GOLDEN)]
    vol_b = [api_response(i, random.Random(SEED + 21), volatile=True,
                          bug=(i == 17)) for i in range(N_GOLDEN)]
    churned = sum(1 for a, b in zip(vol_a, vol_b) if pretty(a) != pretty(b))
    real = sum(1 for a, b in zip(vol_a, vol_b)
               if a["vat_cents"] != b["vat_cents"])
    noise = sum(diff_size(pretty(a), pretty(b))[0] for a, b in zip(vol_a, vol_b))
    signal = sum(diff_size(pretty(a), pretty(b))[0]
                 for a, b in zip(vol_a, vol_b)
                 if a["vat_cents"] != b["vat_cents"])
    print("  now put ONE unstable field in the golden (`generated_at`) and one")
    print("  REAL regression (VAT at 20% not 19% on a single response):\n")
    print(f"  {'goldens that changed this run':<46}{churned:>5} of {N_GOLDEN}")
    print(f"  {'goldens with a real behaviour change':<46}{real:>5} of "
          f"{N_GOLDEN}")
    print(f"  {'diff lines the reviewer must read':<46}{noise:>5}")
    print(f"  {'diff lines that mean anything':<46}{signal:>5}")
    print(f"  {'signal ratio':<46}{signal / noise:>5.1%}")
    print(f"\n  a reviewer facing {churned} changed goldens does not review "
          f"them; they run the")
    print("  accept-all command and approve the one real regression with the")
    print("  noise. Determinism is not a nicety for a golden file — it is the")
    print("  precondition for the review existing. Lesson 08 removes exactly")
    print("  this class of input.")
    return {"one_line_chars": out[formats[0][0]][1],
            "pretty_chars": out[formats[1][0]][1],
            "one_line_lines": out[formats[0][0]][0],
            "pretty_lines": out[formats[1][0]][0], "ratio": ratio,
            "churned": churned, "noise": noise, "signal": signal,
            "signal_ratio": signal / noise}


def main() -> None:
    print("TEST DATA & FIXTURES — measured")
    print(f"Phase 12 · Lesson 07 · seed={SEED} · stdlib only")
    with tempfile.TemporaryDirectory() as td:
        state = section_1(build_world(random.Random(SEED)), Path(td))
    state.update(section_2(state))
    section_3(state)
    section_4(state)
    section_5()
    section_6()
    section_7()
    section_8(state)
    section_9()
    # Every number above is a count, not a duration, so stdout is
    # bit-reproducible. The one value that cannot be goes to stderr, which
    # keeps `python3 test_data.py > a.txt` diffable byte for byte while the
    # reader still sees how long it took.
    print("\n  (elapsed on stderr; stdout is identical run to run)")
    print(f"total wall time {time.perf_counter() - START:.2f} s",
          file=sys.stderr)


if __name__ == "__main__":
    main()
