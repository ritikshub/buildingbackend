#!/usr/bin/env python3
"""
Single-table design from scratch: serve many access patterns with key lookups.

Companion to docs/en.md (Phase 04, Lesson 07 - Data Modeling by Access Pattern).
NoSQL stores have no joins: you can only fetch efficiently by key. So you invert
the relational habit -- instead of modeling clean normalized data and querying it
however you like later, you LIST THE QUERIES FIRST and design the keys so each
query is a single, cheap partition lookup.

This models the sharpest expression of that discipline -- DynamoDB-style
SINGLE-TABLE DESIGN: different entity types (customers, orders, order items) live
in ONE table, co-located by partition key so a parent and its children come back
together in one query (an "item collection"). A global secondary index (GSI),
built by hand here, adds an access pattern you didn't key the base table for.

Each query prints how many items it examined, to show it's a targeted lookup --
not the full-table scan() that signals an access pattern you forgot to model.

Runs standalone on the Python standard library only:  python single_table.py
"""

from __future__ import annotations


class GSI:
    """A Global Secondary Index: a second copy of the items, keyed differently,
    kept current on every put. This is 'duplicate on write to serve a read',
    automated -- the same trade wide-column stores make by hand (Lesson 4)."""

    def __init__(self, name, pk_attr, sk_attr):
        self.name = name
        self.pk_attr = pk_attr                 # which attribute becomes the index's partition key
        self.sk_attr = sk_attr                 # which attribute becomes the index's sort key
        self.data: dict = {}                    # gsi_pk -> { (gsi_sk, PK, SK) -> item }

    def index(self, item):
        if self.pk_attr in item and self.sk_attr in item:
            bucket = self.data.setdefault(item[self.pk_attr], {})
            bucket[(item[self.sk_attr], item["PK"], item["SK"])] = dict(item)

    def query(self, gsi_pk, reverse=False):
        bucket = self.data.get(gsi_pk, {})
        keys = sorted(bucket, reverse=reverse)        # ordered by the GSI sort key
        return [bucket[k] for k in keys], len(keys)


class Table:
    """A single table addressed by a composite key: (PK, SK).
    PK (partition key) groups items; SK (sort key) orders them within a partition
    and lets you slice a range -- 'items in this partition whose SK begins with X'."""

    def __init__(self, name):
        self.name = name
        self.items: dict = {}                   # PK -> { SK -> item }
        self.gsis: dict = {}                     # name -> GSI
        self.reads_last = 0                      # items examined by the most recent read

    def create_gsi(self, name, pk_attr, sk_attr):
        gsi = self.gsis[name] = GSI(name, pk_attr, sk_attr)
        for partition in self.items.values():
            for item in partition.values():
                gsi.index(item)
        return gsi

    def put(self, item):
        self.items.setdefault(item["PK"], {})[item["SK"]] = dict(item)
        for gsi in self.gsis.values():
            gsi.index(item)

    def get(self, pk, sk):
        self.reads_last = 1                     # a point lookup: exactly one item
        return self.items.get(pk, {}).get(sk)

    def query(self, pk, begins_with=None, reverse=False):
        """Read one partition, optionally sliced to the SKs that begin with a
        prefix, returned in sort-key order. Touches only that partition's items --
        the whole point: a targeted lookup, never a table scan."""
        partition = self.items.get(pk, {})
        keys = sorted(partition)
        if begins_with is not None:
            keys = [k for k in keys if k.startswith(begins_with)]
        if reverse:
            keys.reverse()
        self.reads_last = len(keys)
        return [partition[k] for k in keys]

    def query_gsi(self, name, gsi_pk, reverse=False):
        results, examined = self.gsis[name].query(gsi_pk, reverse=reverse)
        self.reads_last = examined
        return results

    def scan(self):
        """The anti-pattern: walk EVERY item in the table. In production a Scan
        means you have an access pattern you never modeled a key for."""
        all_items = [it for part in self.items.values() for it in part.values()]
        self.reads_last = len(all_items)
        return all_items

    def total_items(self):
        return sum(len(p) for p in self.items.values())


# ─── Demo: an e-commerce backend in ONE table ────────────────────────────────

def _key(item):
    return f'{item["PK"]:<16} | {item["SK"]:<26} | {item["entity"]}'

def _demo():
    t = Table("shop")

    # Customers (profile lives at SK '#PROFILE' so it sorts before the orders).
    t.put({"PK": "CUSTOMER#c-1", "SK": "#PROFILE", "entity": "customer",
           "name": "Ada", "tier": "gold"})
    t.put({"PK": "CUSTOMER#c-2", "SK": "#PROFILE", "entity": "customer",
           "name": "Bob", "tier": "silver"})

    # An order is written TWICE (denormalized on purpose):
    #   1) as a reference in the customer's partition -> "a customer's orders"
    #   2) as its own partition head (#META) with its line items -> "order + items"
    def place_order(cust, oid, date, status, items):
        t.put({"PK": f"CUSTOMER#{cust}", "SK": f"ORDER#{date}#{oid}", "entity": "order_ref",
               "order_id": oid, "status": status, "order_date": date})
        # Only the canonical #META order carries the GSI keys (gsi1pk/gsi1sk), so
        # each order is indexed exactly once. Overloaded GSI attributes like these
        # are how single-table design controls what lands in an index.
        t.put({"PK": f"ORDER#{oid}", "SK": "#META", "entity": "order",
               "order_id": oid, "customer": cust, "status": status, "order_date": date,
               "gsi1pk": status, "gsi1sk": f"{date}#{oid}"})
        for i, (sku, qty) in enumerate(items, 1):
            t.put({"PK": f"ORDER#{oid}", "SK": f"ITEM#{i:02d}", "entity": "order_item",
                   "sku": sku, "qty": qty})

    place_order("c-1", "o-500", "2024-05-02", "PAID",    [("BOOK-1", 1)])
    place_order("c-1", "o-620", "2024-06-11", "SHIPPED", [("LAPTOP-9", 1), ("MOUSE-3", 2)])
    place_order("c-2", "o-700", "2024-06-01", "SHIPPED", [("BOOK-1", 3)])

    print(f"== One table, {t.total_items()} items, three entity types co-located by key ==")
    for it in t.scan():
        print("   ", _key(it))

    print("\n== Access pattern 1: get a customer's profile (point lookup) ==")
    p = t.get("CUSTOMER#c-1", "#PROFILE")
    print(f"   {p['name']} ({p['tier']})   examined {t.reads_last} item")

    print("\n== Access pattern 2: a customer's orders, newest first ==")
    orders = t.query("CUSTOMER#c-1", begins_with="ORDER#", reverse=True)
    for o in orders:
        print(f"   {o['order_id']}  {o['order_date']}  {o['status']}")
    print(f"   examined {t.reads_last} items (only Ada's partition, not the table)")

    print("\n== Access pattern 3: a customer + all their orders in ONE query (item collection) ==")
    everything = t.query("CUSTOMER#c-1")
    print(f"   returned {len(everything)} items: "
          f"{[e['entity'] for e in everything]}   examined {t.reads_last}")

    print("\n== Access pattern 4: an order with its line items (one partition) ==")
    order = t.query("ORDER#o-620")
    for row in order:
        label = row.get("sku") or f"order {row['order_id']} ({row['status']})"
        print(f"   {row['SK']:<8} {label}")
    print(f"   examined {t.reads_last} items")

    print("\n== Access pattern 5: orders by status -- needs a GSI (a non-key attribute) ==")
    t.create_gsi("orders_by_status", pk_attr="gsi1pk", sk_attr="gsi1sk")
    shipped = t.query_gsi("orders_by_status", "SHIPPED")
    print(f"   SHIPPED orders: {[o['order_id'] for o in shipped]}   "
          f"examined {t.reads_last} items via the GSI")
    t.scan()
    print(f"   (without the GSI, the same answer needs a full scan: "
          f"{t.reads_last} items examined)")


if __name__ == "__main__":
    _demo()
