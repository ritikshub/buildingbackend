"""
Build It — offset vs cursor pagination, and why the choice matters.

Both page the same in-memory collection sorted by (created_at, id) DESC. The demo's
whole point is the failure the concept section describes: insert one row between two
page fetches and

  * OFFSET pagination duplicates a row (offsets address positions, not rows),
  * CURSOR/keyset pagination stays stable (the cursor pins a spot in key space).

Also shows a sort whitelist (unknown field -> 400, not a silent full-table sort) and
an opaque base64 cursor built from the last row's sort keys.

Self-terminating: runs the two paging demos and the whitelist demo, prints results,
exits 0.

Docs: phases/02-api-design/04-pagination-filtering-sorting/docs/en.md
Spec: RFC 4648 (base64url). Keyset pagination is a standard SQL seek pattern.

Run:
    python pagination.py
"""

from __future__ import annotations

import base64
import json

SORTABLE = ("created_at", "total_amount")  # the whitelist — nothing else is sortable


def make_rows(n: int) -> list:
    """ord_01 .. ord_0n, each a minute newer than the last (ord_0n is newest)."""
    rows = []
    for i in range(1, n + 1):
        rows.append({
            "id": "ord_{:02d}".format(i),
            "created_at": "2026-07-10T08:{:02d}:00Z".format(i),
            "status": "pending" if i % 2 else "confirmed",
            "total_amount": i * 1000,
        })
    return rows


def newest_row(oid: str) -> dict:
    """A brand-new order that sorts to the very top."""
    return {"id": oid, "created_at": "2026-07-10T09:00:00Z", "status": "pending", "total_amount": 9999}


def sort_desc(rows: list) -> list:
    return sorted(rows, key=lambda r: (r["created_at"], r["id"]), reverse=True)


# ---- offset/limit: a window by POSITION -----------------------------------
def offset_page(rows: list, limit: int, offset: int) -> dict:
    ordered = sort_desc(rows)
    window = ordered[offset:offset + limit]
    return {
        "data": [r["id"] for r in window],
        "total": len(ordered),          # a count comes "for free" — one of offset's perks
        "limit": limit,
        "offset": offset,
    }


# ---- cursor/keyset: "rows after this row" by KEY ---------------------------
def encode_cursor(row: dict) -> str:
    raw = json.dumps({"created_at": row["created_at"], "id": row["id"]}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple:
    data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    return (data["created_at"], data["id"])


def cursor_page(rows: list, limit: int, cursor=None) -> dict:
    ordered = sort_desc(rows)
    if cursor is not None:
        key = decode_cursor(cursor)
        # Strict seek: keep only rows that sort strictly AFTER the cursor row.
        # (created_at, id) is unique + immutable, so no boundary row is skipped/repeated.
        ordered = [r for r in ordered if (r["created_at"], r["id"]) < key]
    window = ordered[:limit + 1]        # fetch one extra to learn has_more without a COUNT
    has_more = len(window) > limit
    page = window[:limit]
    next_cursor = encode_cursor(page[-1]) if (has_more and page) else None
    return {"data": [r["id"] for r in page], "has_more": has_more, "next_cursor": next_cursor}


# ---- filtering + sorting with a whitelist ---------------------------------
def list_orders(rows: list, status=None, sort: str = "-created_at") -> list:
    field = sort[1:] if sort.startswith("-") else sort
    if field not in SORTABLE:
        # Unknown sort field fails LOUDLY. Silently sorting the whole table (or
        # ignoring the param) is how a "?staus=" typo leaks the full collection.
        raise ValueError("400 cannot sort by {!r}; allowed: {}".format(field, ", ".join(SORTABLE)))
    result = [r for r in rows if status is None or r["status"] == status]
    return sorted(result, key=lambda r: r[field], reverse=sort.startswith("-"))


def main() -> None:
    print("=== offset pagination: a row inserted between pages DUPLICATES ===")
    rows = make_rows(5)
    p1 = offset_page(rows, limit=2, offset=0)
    print("  page1 (offset 0):", p1["data"], " total:", p1["total"])
    rows.append(newest_row("ord_06"))
    print("  --- ord_06 inserted at the top (a concurrent write) ---")
    p2 = offset_page(rows, limit=2, offset=2)
    print("  page2 (offset 2):", p2["data"], "  <-- ord_04 already appeared on page1 (duplicate)")

    print("\n=== cursor pagination: same insert, STABLE ===")
    rows = make_rows(5)
    c1 = cursor_page(rows, limit=2)
    print("  page1:", c1["data"], " next_cursor:", c1["next_cursor"])
    rows.append(newest_row("ord_06"))
    print("  --- ord_06 inserted at the top (a concurrent write) ---")
    c2 = cursor_page(rows, limit=2, cursor=c1["next_cursor"])
    print("  page2:", c2["data"], "  <-- no duplicate, no skip; has_more:", c2["has_more"])

    print("\n=== sort whitelist ===")
    print("  sort=-total_amount:", [r["id"] for r in list_orders(make_rows(5), sort="-total_amount")])
    try:
        list_orders(make_rows(5), sort="password")
    except ValueError as exc:
        print("  sort=password ->", exc)


if __name__ == "__main__":
    main()
