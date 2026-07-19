"""
Build It — validate at the edge, and speak ONE error envelope.

Two jobs, both stdlib-only:

  1. validate_order()  — reject a bad request shape, collecting EVERY field error
     at once (never fail-fast) with a path syntax clients can map to form inputs.
  2. problem()         — wrap those errors in an RFC 9457 `application/problem+json`
     envelope: a frozen machine `code`, a human `detail`, a field-level `errors[]`,
     and a request id for correlation — with no server internals ever leaked.

A `safe_call()` wrapper shows the other half of "never leak internals": an
unexpected exception is logged server-side (with traceback) but returns a generic
500 problem carrying only the request id.

Self-terminating: validates one bad payload, one good payload, and one crashing
handler, prints each envelope, exits 0.

Docs: phases/02-api-design/03-request-validation-error-contracts/docs/en.md
Spec: RFC 9457 (Problem Details for HTTP APIs), RFC 9110 (status codes)

Run:
    python validation.py
"""

from __future__ import annotations

import json
import sys
import traceback
from uuid import uuid4

CURRENCIES = ("INR", "USD", "EUR")


def validate_order(payload: dict) -> list:
    """Return a list of {field, code, message}. Empty list == valid.

    Collect ALL failures — a client should fix everything in one round trip, not
    discover errors one resubmit at a time.
    """
    errors: list = []

    def bad(field: str, code: str, message: str) -> None:
        errors.append({"field": field, "code": code, "message": message})

    # customer_id: required string
    cid = payload.get("customer_id")
    if cid is None:
        bad("customer_id", "required", "customer_id is required")
    elif not isinstance(cid, str):
        bad("customer_id", "type", "customer_id must be a string")

    # currency: required enum
    currency = payload.get("currency")
    if currency is None:
        bad("currency", "required", "currency is required")
    elif currency not in CURRENCIES:
        bad("currency", "enum", "currency must be one of " + ", ".join(CURRENCIES))

    # items: required, non-empty list of {menu_item_id, quantity>=1}
    items = payload.get("items")
    if items is None:
        bad("items", "required", "items is required")
    elif not isinstance(items, list):
        bad("items", "type", "items must be a list")
    elif not items:
        bad("items", "min_length", "items must contain at least 1 item")
    else:
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                bad("items[{}]".format(i), "type", "item must be an object")
                continue
            if "menu_item_id" not in item:
                bad("items[{}].menu_item_id".format(i), "required", "menu_item_id is required")
            qty = item.get("quantity")
            # bool is a subclass of int, so exclude it explicitly.
            if qty is None:
                bad("items[{}].quantity".format(i), "required", "quantity is required")
            elif isinstance(qty, bool) or not isinstance(qty, int):
                bad("items[{}].quantity".format(i), "type", "quantity must be an integer")
            elif qty < 1:
                bad("items[{}].quantity".format(i), "min_value", "quantity must be >= 1")

    return errors


def problem(status: int, code: str, title: str, errors: list, instance: str, request_id: str) -> dict:
    """One envelope for every error the API can emit (RFC 9457)."""
    body = {
        "type": "https://api.example.com/errors/" + code.replace("_", "-"),
        "title": title,
        "status": status,
        "detail": "{} field(s) failed validation.".format(len(errors)) if errors else title,
        "instance": instance,
        "code": code,           # the machine contract — clients branch on THIS, never `detail`
        "request_id": request_id,
    }
    if errors:
        body["errors"] = errors
    return body


def safe_call(handler, instance: str):
    """Run a handler; turn any uncaught exception into a leak-free 500.

    The real error + traceback goes to the server log; the client gets only a
    request id it can quote to support.
    """
    request_id = "req_" + uuid4().hex[:12]
    try:
        return 201, handler()
    except Exception:  # noqa: BLE001 - top-level API boundary, deliberately broad
        print("SERVER LOG  request_id=%s\n%s" % (request_id, traceback.format_exc()),
              file=sys.stderr, end="")
        return 500, problem(500, "internal_error", "Internal server error", [], instance, request_id)


def render(status: int, body: dict) -> None:
    print("HTTP {}  Content-Type: application/problem+json".format(status))
    print(json.dumps(body, indent=2))
    print()


def main() -> None:
    instance = "/v1/orders"

    print("=== 1. malformed payload: every error at once ===\n")
    bad_payload = {
        # customer_id missing
        "currency": "GBP",                                  # not in enum
        "items": [
            {"menu_item_id": "mi_551", "quantity": 0},      # quantity < 1
            {"quantity": 2},                                # menu_item_id missing
        ],
    }
    errors = validate_order(bad_payload)
    render(422, problem(422, "validation_error", "Request validation failed", errors,
                        instance, "req_" + uuid4().hex[:12]))

    print("=== 2. valid payload: passes, no envelope ===\n")
    good_payload = {
        "customer_id": "cus_8xkP2m",
        "currency": "INR",
        "items": [{"menu_item_id": "mi_551", "quantity": 2}],
    }
    errors = validate_order(good_payload)
    print("errors:", errors, "-> would proceed to create the order (201)\n")

    print("=== 3. handler crashes: 500 with a request id, no traceback leaked ===\n")

    def crashing_handler():
        totals = {}
        return totals["missing_key"]  # KeyError

    status, body = safe_call(crashing_handler, instance)
    render(status, body)


if __name__ == "__main__":
    main()
