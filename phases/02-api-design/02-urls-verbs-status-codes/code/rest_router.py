"""
Build It — a resource-oriented HTTP router on the standard library.

Implements CRUD on /orders using the method x status conventions from this lesson,
with no web framework — just http.server, routing the (method, resource) grid by
hand so the FastAPI version stops being magic:

  POST   /orders        -> 201 + Location + full body     (create, non-idempotent)
  GET    /orders        -> 200 list
  GET    /orders/{id}   -> 200 / 404
  PUT    /orders/{id}   -> 200 replace whole resource      (idempotent)
  PATCH  /orders/{id}   -> 200 merge-patch, null deletes    (RFC 7396)
  DELETE /orders/{id}   -> 204, second call -> 404          (idempotent in effect)
  wrong method          -> 405 + Allow
  bad JSON body         -> 400

Self-terminating: runs the server on a thread, drives it with a scripted set of
client requests, prints method/path/status of each, shuts down, exits 0.

Docs: phases/02-api-design/02-urls-verbs-status-codes/docs/en.md
Spec: RFC 9110 (HTTP semantics: methods, safe/idempotent, status codes),
      RFC 7396 (JSON Merge Patch)

Run:
    python rest_router.py
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from uuid import uuid4

HOST, PORT = "127.0.0.1", 54_320

# In-memory store: order_id -> order dict. Stands in for a database table.
ORDERS: dict[str, dict] = {}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_order(body: dict) -> dict:
    """Server owns id/status/created_at — the client never sends them."""
    oid = "ord_" + uuid4().hex[:12]
    order = {
        "id": oid,
        "status": "pending",
        "customer_id": body.get("customer_id"),
        "items": body.get("items", []),
        "created_at": now_iso(),
    }
    ORDERS[oid] = order
    return order


class OrdersHandler(BaseHTTPRequestHandler):
    # Which methods each kind of resource allows. This table *is* the 405 + Allow
    # contract: a request outside it is answered "405" with the allowed set.
    COLLECTION_METHODS = ("GET", "POST")
    MEMBER_METHODS = ("GET", "PUT", "PATCH", "DELETE")

    # ---- tiny response/parse helpers ---------------------------------------
    def _send(self, status: int, payload=None, headers=None) -> None:
        body = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        if body:
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        return json.loads(raw) if raw else {}  # raises JSONDecodeError on bad input

    def _resource(self):
        """Classify the path: a collection, a member (with id), or unknown."""
        parts = [p for p in self.path.split("?")[0].split("/") if p]
        if parts == ["orders"]:
            return "collection", None
        if len(parts) == 2 and parts[0] == "orders":
            return "member", parts[1]
        return "unknown", None

    def log_message(self, *args) -> None:
        pass  # silence the default stderr access log so the demo output is clean

    # ---- one entry point per method, all funnel into _route ----------------
    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_PUT(self):
        self._route("PUT")

    def do_PATCH(self):
        self._route("PATCH")

    def do_DELETE(self):
        self._route("DELETE")

    def _route(self, method: str) -> None:
        kind, oid = self._resource()

        if kind == "unknown":
            return self._send(404, {"code": "not_found", "message": "no such resource"})

        allowed = self.COLLECTION_METHODS if kind == "collection" else self.MEMBER_METHODS
        if method not in allowed:
            # 405 MUST carry Allow (RFC 9110 §15.5.6) so the client learns the verbs.
            return self._send(
                405,
                {"code": "method_not_allowed", "message": method + " not allowed here"},
                headers={"Allow": ", ".join(allowed)},
            )

        try:
            body = self._read_json() if method in ("POST", "PUT", "PATCH") else {}
        except json.JSONDecodeError:
            return self._send(400, {"code": "bad_request", "message": "body is not valid JSON"})

        if kind == "collection":
            if method == "GET":
                return self._send(200, {"data": list(ORDERS.values()), "count": len(ORDERS)})
            # POST: create, then advertise the new URL in Location. 201, not 200.
            order = create_order(body)
            return self._send(201, order, headers={"Location": "/orders/" + order["id"]})

        # --- member (/orders/{id}) ---
        if oid not in ORDERS:
            return self._send(404, {"code": "not_found", "message": "order " + str(oid) + " not found"})
        order = ORDERS[oid]

        if method == "GET":
            return self._send(200, order)

        if method == "PUT":
            # Replace the whole resource. Omitted client fields are reset to defaults
            # (that is the PUT contract); server-owned id/created_at are preserved.
            replaced = {
                "id": order["id"],
                "created_at": order["created_at"],
                "status": body.get("status", "pending"),
                "customer_id": body.get("customer_id"),
                "items": body.get("items", []),
            }
            ORDERS[oid] = replaced
            return self._send(200, replaced)

        if method == "PATCH":
            # RFC 7396 JSON Merge Patch: present key -> set; key set to null -> delete.
            for key, value in body.items():
                if key in ("id", "created_at"):
                    continue  # immutable, server-owned
                if value is None:
                    order.pop(key, None)
                else:
                    order[key] = value
            return self._send(200, order)

        # DELETE
        del ORDERS[oid]
        return self._send(204)  # 204 No Content — success with an empty body


# ---- client driver: exercise every branch, print what came back -----------
def call(method: str, path: str, body=None):
    url = "http://{}:{}{}".format(HOST, PORT, path)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if isinstance(body, str):  # allow raw (possibly malformed) bodies
        data = body.encode()
        req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return resp.status, dict(resp.headers), (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, dict(exc.headers), (json.loads(raw) if raw else None)


def show(label: str, method: str, path: str, body=None) -> tuple:
    status, headers, payload = call(method, path, body)
    extra = ""
    if headers.get("Location"):
        extra = "  Location: " + headers["Location"]
    if headers.get("Allow"):
        extra = "  Allow: " + headers["Allow"]
    print("{:<40} {:<7} {:<16} -> {}{}".format(label, method, path, status, extra))
    return status, headers, payload


def main() -> None:
    server = HTTPServer((HOST, PORT), OrdersHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        print("method x resource grid, by hand:\n")
        _, headers, created = show(
            "create -> 201 + Location", "POST", "/orders",
            {"customer_id": "cus_8xkP2m", "items": [{"menu_item_id": "mi_551", "quantity": 2}]},
        )
        oid = created["id"]
        member = "/orders/" + oid

        show("list", "GET", "/orders")
        show("fetch one", "GET", member)
        show("replace whole (PUT, idempotent)", "PUT", member, {"customer_id": "cus_new", "status": "confirmed"})
        show("merge-patch: set a field", "PATCH", member, {"status": "preparing"})
        show("merge-patch: null DELETES a field", "PATCH", member, {"customer_id": None})
        show("wrong verb -> 405 + Allow", "DELETE", "/orders")          # DELETE on a collection
        show("bad JSON -> 400", "POST", "/orders", "{not json")
        show("missing resource -> 404", "GET", "/orders/ord_doesnotexist")
        show("delete -> 204", "DELETE", member)
        show("delete again -> 404 (idempotent effect)", "DELETE", member)

        print("\nFinal store:", json.dumps(list(ORDERS.values()), indent=2))
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
