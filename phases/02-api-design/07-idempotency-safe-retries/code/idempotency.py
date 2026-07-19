"""
Build It — an idempotency layer that survives concurrent duplicates.

The reliability core of Stripe-style Idempotency-Key handling, stdlib-only:

  * claim-then-execute — atomically insert the key row BEFORE doing the work, so two
    simultaneous duplicates can't both execute (the loser sees the row),
  * fingerprint the request — same key + different body is a client bug (422),
  * in-flight duplicates get 409, completed ones REPLAY the stored response,
  * the operation (charging a card) runs AT MOST ONCE per key.

A threading.Lock stands in for the database's atomic `INSERT ... ON CONFLICT DO
NOTHING`. The demo fires 5 concurrent requests with one key and asserts the card was
charged exactly once.

Self-terminating: runs the concurrency test + a retry + a key-reuse test, exits 0.

Docs: phases/02-api-design/07-idempotency-safe-retries/docs/en.md
Spec: draft-ietf-httpapi-idempotency-key-header; the pattern Stripe documents.

Run:
    python idempotency.py
"""

from __future__ import annotations

import hashlib
import json
import threading
import time

# ---- the thing we must never do twice -------------------------------------


class Charger:
    """A metered side effect. Counts how many times it actually ran."""

    def __init__(self) -> None:
        self.charges = 0
        self._lock = threading.Lock()

    def charge(self, amount: int, currency: str) -> dict:
        time.sleep(0.05)  # make the network/DB window wide enough for overlap
        with self._lock:
            self.charges += 1
            charge_id = "ch_{:04d}".format(self.charges)
        return {"id": charge_id, "amount": amount, "currency": currency, "status": "succeeded"}


# ---- the idempotency store -------------------------------------------------


def fingerprint(method: str, path: str, body: bytes) -> str:
    return hashlib.sha256(method.encode() + b" " + path.encode() + b" " + body).hexdigest()


class IdempotencyStore:
    def __init__(self) -> None:
        self._records: dict = {}       # (tenant, key) -> {"hash", "status", "body"}
        self._lock = threading.Lock()  # guards the atomic "claim"

    def handle(self, tenant: str, key: str, method: str, path: str, body: bytes, work):
        fp = fingerprint(method, path, body)
        k = (tenant, key)

        # 1. Atomically CLAIM the key (this is the ON CONFLICT DO NOTHING moment).
        with self._lock:
            record = self._records.get(k)
            if record is None:
                record = {"hash": fp, "status": None, "body": None}  # status None == in flight
                self._records[k] = record
                claimed = True
            else:
                claimed = False

        # 2a. We lost the race (or this is a later retry): inspect the existing row.
        if not claimed:
            if record["hash"] != fp:
                return 422, {"code": "idempotency_key_reuse",
                             "message": "Idempotency-Key reused with a different request body"}, "reject-422"
            if record["status"] is None:
                return 409, {"code": "request_in_progress",
                             "message": "A request with this Idempotency-Key is in progress"}, "in-flight-409"
            return record["status"], record["body"], "replayed"

        # 2b. We won the claim: do the work exactly once, then persist the response.
        result = work()
        record["status"], record["body"] = 201, result
        return 201, result, "executed"


# ---- demos ----------------------------------------------------------------


def concurrent_duplicates() -> None:
    print("=== 5 concurrent requests, one Idempotency-Key ===")
    charger = Charger()
    store = IdempotencyStore()
    body = json.dumps({"amount": 90000, "currency": "inr"}).encode()
    outcomes: list = []

    def worker() -> None:
        status, _, tag = store.handle(
            "tenant_1", "key-abc", "POST", "/v1/payments", body,
            work=lambda: charger.charge(90000, "inr"),
        )
        outcomes.append((status, tag))

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    tally: dict = {}
    for status, tag in outcomes:
        tally[tag] = tally.get(tag, 0) + 1
    print("  outcomes:", tally)
    print("  card charged:", charger.charges, "time(s)  <-- at-most-once holds")
    assert charger.charges == 1, "idempotency broken: charged more than once!"


def retry_after_success() -> None:
    print("\n=== later retry with the same key -> replay, no new charge ===")
    charger = Charger()
    store = IdempotencyStore()
    body = json.dumps({"amount": 5000, "currency": "inr"}).encode()
    work = lambda: charger.charge(5000, "inr")  # noqa: E731

    s1, b1, t1 = store.handle("tenant_1", "key-xyz", "POST", "/v1/payments", body, work)
    s2, b2, t2 = store.handle("tenant_1", "key-xyz", "POST", "/v1/payments", body, work)
    print("  1st:", s1, t1, "->", b1["id"])
    print("  2nd:", s2, t2, "->", b2["id"], " (same charge id)")
    print("  card charged:", charger.charges, "time(s)")
    assert charger.charges == 1 and b1 == b2


def key_reused_different_body() -> None:
    print("\n=== same key, DIFFERENT body -> 422 (client bug, not a retry) ===")
    charger = Charger()
    store = IdempotencyStore()
    store.handle("tenant_1", "key-9", "POST", "/v1/payments",
                 json.dumps({"amount": 100}).encode(), lambda: charger.charge(100, "inr"))
    status, resp, tag = store.handle("tenant_1", "key-9", "POST", "/v1/payments",
                                     json.dumps({"amount": 999999}).encode(),
                                     lambda: charger.charge(999999, "inr"))
    print("  ->", status, tag, "-", resp["message"])
    assert status == 422 and charger.charges == 1


def main() -> None:
    concurrent_duplicates()
    retry_after_success()
    key_reused_different_body()
    print("\nAll invariants held: the operation ran at most once per key.")


if __name__ == "__main__":
    main()
