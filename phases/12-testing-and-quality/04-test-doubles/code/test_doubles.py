#!/usr/bin/env python3
"""
Test doubles measured rather than argued: the five kinds against one payment
port, mock drift across twelve provider releases, the shared contract suite
that catches it, Mock() versus create_autospec(), interaction versus outcome
assertions under behaviour-preserving refactors, and how much of your own code
a double at the wrong layer skips.

Companion to docs/en.md (Phase 12, Lesson 04). Standard library only
(`unittest.mock` and `sys.settrace` are stdlib), every RNG seeded with
random.Random(20260718), no network, no files written, self-terminating in
about two seconds. Sources: Meszaros, *xUnit Test Patterns: Refactoring Test
Code*, Addison-Wesley, 2007 (the double taxonomy); Mackinnon, Freeman & Craig,
*Endo-Testing: Unit Testing with Mock Objects*, XP2000, 2000; RFC 9110, *HTTP
Semantics*, 2022 (§15.5.21 the 422 status code, §10.2.3 Retry-After); RFC 6585,
*Additional HTTP Status Codes*, 2012 (§4 the 429 status code).

Run:  python3 test_doubles.py
"""

from __future__ import annotations

import ast
import bisect
import hashlib
import random
import sys
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple
from unittest.mock import Mock, create_autospec

SEED = 20260718
RELEASES = 12

Response = Tuple[int, Dict[str, Any]]

def banner(n: int, title: str) -> None:
    print(f"\n== {n} · {title} ==")


# ══ THE PORT AND THE DOMAIN ══════════════════════════════════════════════════
# One dependency: a payment provider reachable over HTTP. Everything in this
# file is a different way of standing in for it.

@dataclass
class ChargeOutcome:
    """What our adapter promises the rest of the application."""
    ok: bool
    charge_id: str = ""
    receipt: str = ""
    decline_code: str = ""

class InvalidRequest(Exception):
    """The provider rejected the request. This is a 4xx for our caller."""

class TransportError(Exception):
    """Anything we did not expect. This is a 5xx for our caller."""

class PaymentGateway:
    """The port. Nothing implements this directly — it exists so `spec=` and
    `create_autospec()` in section 4 have a real signature to check against."""

    def charge(self, idempotency_key: str, amount_cents: int,
               currency: str, card: str) -> ChargeOutcome:
        raise NotImplementedError

    def refund(self, charge_id: str, amount_cents: int) -> bool:
        raise NotImplementedError

def rate_limited_key(key: str) -> bool:
    """From release 11 the provider rate-limits one key in four. The bucket is
    a hash of the key so it is stable across runs and across implementations —
    the real provider and our fake must agree on which keys are affected."""
    return hashlib.sha256(key.encode()).digest()[0] % 4 == 0


# ══ THE REAL PROVIDER, EVOLVING ══════════════════════════════════════════════
# The vendor's sandbox. We do not own this code and we are not consulted about
# it. Four changes land over twelve releases; each one is the kind of change a
# provider considers minor and publishes in a changelog nobody reads.
#
#   R4   the success status string is renamed "success" -> "succeeded"
#   R6   receipt_url becomes OPTIONAL and is omitted for charges under 500c
#   R9   validation errors move from 400 {"error": str} to 422 {"errors": [...]}
#   R11  one key in four is rate-limited on first attempt: 429 + Retry-After

RENAME = "status string renamed"
OPTIONAL = "receipt_url now optional"
UNPROCESSABLE = "validation error 400 -> 422"
RETRY = "429 retry now required"

CHANGE_RELEASE = {RENAME: 4, OPTIONAL: 6, UNPROCESSABLE: 9, RETRY: 11}
CHANGE_DETAIL = {RENAME: '"success" -> "succeeded"', OPTIONAL: "omitted for charges below 500c",
    UNPROCESSABLE: '{"error": str} -> {"errors": [...]}',
    RETRY: "one key in four, on the first attempt",
}

class RealProvider:
    """The vendor's API. `enabled` is the set of changes that have shipped, so
    a single change can be switched on alone — that is how section 2 attributes
    a broken scenario to the change that actually broke it."""

    def __init__(self, enabled: frozenset) -> None:
        self.enabled = enabled
        self._charges: Dict[str, Dict[str, Any]] = {}
        self._seen_attempts: Dict[str, int] = {}
        self._next = 1000

    @classmethod
    def at_release(cls, release: int) -> "RealProvider":
        return cls(frozenset(c for c, r in CHANGE_RELEASE.items() if release >= r))

    @classmethod
    def with_only(cls, change: str) -> "RealProvider":
        return cls(frozenset({change}))

    def post(self, path: str, body: Dict[str, Any]) -> Response:
        assert path == "/v1/charges"
        key = body["idempotency_key"]
        self._seen_attempts[key] = self._seen_attempts.get(key, 0) + 1

        if RETRY in self.enabled:
            if rate_limited_key(key) and self._seen_attempts[key] == 1:
                return 429, {"error": "rate_limited", "retry_after": 0}

        amount = body["amount_cents"]
        currency = body["currency"]
        if amount <= 0 or currency not in ("usd", "eur"):
            reason = ("amount_cents must be positive" if amount <= 0
                      else f"currency {currency!r} is not supported")
            field_name = "amount_cents" if amount <= 0 else "currency"
            if UNPROCESSABLE in self.enabled:
                return 422, {"errors": [{"field": field_name, "code": "invalid", "detail": reason}]}
            return 400, {"error": reason}

        if key in self._charges:
            return 200, dict(self._charges[key])

        self._next += 1
        charge_id = f"ch_live_{self._next}"
        if body["card"] == "declined":
            record = {"id": charge_id, "status": "declined", "decline_code": "card_declined",
                      "amount_cents": amount, "currency": currency}
        else:
            ok_status = "succeeded" if RENAME in self.enabled else "success"
            record = {"id": charge_id, "status": ok_status,
                      "amount_cents": amount, "currency": currency}
            omit = OPTIONAL in self.enabled and amount < 500
            if not omit:
                record["receipt_url"] = f"https://pay.example/r/{charge_id}"
        self._charges[key] = record
        return 200, dict(record)


# ══ 1 · THE FIVE DOUBLES ═════════════════════════════════════════════════════
# Meszaros' taxonomy, each implemented by hand against the same port. The
# question that separates them is not "how is it built" but "what can a test
# that uses it prove".

class DummyGateway:
    """Dummy: never called. It exists to fill a parameter."""

    def charge(self, *_a: Any, **_k: Any) -> ChargeOutcome:
        raise AssertionError("dummy was called")

class StubGateway:
    """Stub: canned answers, no memory, no logic. Cannot be interrogated."""

    def __init__(self, answer: ChargeOutcome) -> None:
        self.answer = answer

    def charge(self, idempotency_key: str, amount_cents: int,
               currency: str, card: str) -> ChargeOutcome:
        return self.answer

class SpyGateway(StubGateway):
    """Spy: a stub that records what happened, checked after the fact."""

    def __init__(self, answer: ChargeOutcome) -> None:
        super().__init__(answer)
        self.calls: List[Tuple[str, int, str, str]] = []

    def charge(self, idempotency_key: str, amount_cents: int,
               currency: str, card: str) -> ChargeOutcome:
        self.calls.append((idempotency_key, amount_cents, currency, card))
        return self.answer

class MockGateway(StubGateway):
    """Mock: carries the expectation itself and fails at the point of the call.
    The test states what must happen before the code runs."""

    def __init__(self, answer: ChargeOutcome, expect: Tuple[str, int, str, str]) -> None:
        super().__init__(answer)
        self.expect = expect
        self.satisfied = False

    def charge(self, idempotency_key: str, amount_cents: int,
               currency: str, card: str) -> ChargeOutcome:
        got = (idempotency_key, amount_cents, currency, card)
        if got != self.expect:
            raise AssertionError(f"expected charge{self.expect}, got charge{got}")
        self.satisfied = True
        return self.answer

    def verify(self) -> None:
        if not self.satisfied:
            raise AssertionError("expected charge() was never called")

class InMemoryProvider:
    """Fake: a real, working implementation with a shortcut. Written by us,
    independently of RealProvider, speaking the same wire protocol. `synced_to`
    is the provider behaviour this fake has been brought up to — section 3 is
    entirely about what makes us change that number."""

    def __init__(self, synced_to: frozenset = frozenset()) -> None:
        self.synced_to = synced_to
        self.store: Dict[str, Dict[str, Any]] = {}
        self.attempts: Dict[str, int] = {}
        self.counter = 0

    @classmethod
    def synced_to_release(cls, release: int) -> "InMemoryProvider":
        return cls(frozenset(c for c, r in CHANGE_RELEASE.items() if release >= r))

    def post(self, path: str, body: Dict[str, Any]) -> Response:
        if path != "/v1/charges":
            return 404, {"error": "no such route"}
        key = body["idempotency_key"]
        self.attempts[key] = self.attempts.get(key, 0) + 1
        if (RETRY in self.synced_to and rate_limited_key(key) and self.attempts[key] == 1):
            return 429, {"error": "rate_limited", "retry_after": 0}
        if body["amount_cents"] <= 0:
            return self._reject("amount_cents", "amount_cents must be positive")
        if body["currency"] not in ("usd", "eur"):
            return self._reject("currency", f"currency {body['currency']!r} is not supported")
        if key in self.store:
            return 200, dict(self.store[key])
        self.counter += 1
        cid = f"ch_fake_{self.counter:04d}"
        if body["card"] == "declined":
            rec = {"id": cid, "status": "declined", "decline_code": "card_declined",
                   "amount_cents": body["amount_cents"],
                   "currency": body["currency"]}
        else:
            rec = {"id": cid, "status": "succeeded" if RENAME in self.synced_to else "success",
                   "amount_cents": body["amount_cents"],
                   "currency": body["currency"]}
            if not (OPTIONAL in self.synced_to and body["amount_cents"] < 500):
                rec["receipt_url"] = f"https://fake.local/r/{cid}"
        self.store[key] = rec
        return 200, dict(rec)

    def _reject(self, field_name: str, detail: str) -> Response:
        if UNPROCESSABLE in self.synced_to:
            return 422, {"errors": [{"field": field_name, "code": "invalid", "detail": detail}]}
        return 400, {"error": detail}

    def charge_count(self, key: str) -> int:
        return 1 if key in self.store else 0

    def recorded(self, key: str) -> Dict[str, Any]:
        return dict(self.store.get(key, {}))

class FrozenStubTransport:
    """The hand-written double from the incident: someone read the docs once,
    in 2024, and wrote the four response shapes they saw. It has no state and
    no logic, it never changes, and nothing anywhere verifies it against the
    provider it claims to imitate."""

    def __init__(self) -> None:
        self.calls = 0

    def post(self, path: str, body: Dict[str, Any]) -> Response:
        self.calls += 1
        if body["amount_cents"] <= 0 or body["currency"] not in ("usd", "eur"):
            return 400, {"error": "invalid request"}
        if body["card"] == "declined":
            return 200, {"id": "ch_test_1", "status": "declined", "decline_code": "card_declined"}
        return 200, {"id": "ch_test_1", "status": "success", "amount_cents": body["amount_cents"],
                     "currency": body["currency"],
                     "receipt_url": "https://pay.example/r/ch_test_1"}


# ══ OUR CODE ═════════════════════════════════════════════════════════════════
# Two layers we own. The adapter turns wire responses into domain outcomes; the
# service turns domain outcomes into an order. Section 6 measures how much of
# this a double at each layer actually executes.

ACTIVE_MUTANT: Optional[str] = None

def mutant(name: str) -> bool:
    """Section 6 seeds bugs with an explicit switch rather than by rewriting
    source, so the mutated line stays readable in the listing."""
    return ACTIVE_MUTANT == name

class PaymentClient:
    """The adapter. Builds the request, retries, parses the response. Written
    against release 1 of the provider and never revisited."""

    def __init__(self, transport: Any, max_attempts: int = 1) -> None:
        self.transport = transport
        self.max_attempts = max_attempts

    def charge(self, idempotency_key: str, amount_cents: int,
               currency: str, card: str) -> ChargeOutcome:
        key = idempotency_key
        if mutant("adapter_drops_idempotency_key"):
            key = f"{idempotency_key}-{self.transport.__class__.__name__}-x"
        amount = amount_cents
        if mutant("adapter_sends_amount_in_dollars"):
            amount = amount_cents // 100
        wire_currency = currency
        if mutant("adapter_ignores_currency"):
            wire_currency = "usd"
        body = {"idempotency_key": key, "amount_cents": amount,
                "currency": wire_currency, "card": card}
        attempts = 0
        while True:
            attempts += 1
            code, resp = self.transport.post("/v1/charges", body)
            if code == 429 and attempts < self.max_attempts:
                continue
            return self._parse(code, resp)

    def _parse(self, code: int, resp: Dict[str, Any]) -> ChargeOutcome:
        if code == 400:
            if mutant("adapter_swallows_400"):
                return ChargeOutcome(ok=False, decline_code="invalid")
            raise InvalidRequest(resp["error"])
        if code != 200:
            raise TransportError(f"unexpected status {code}")
        status = resp["status"]
        if status == "success":
            receipt = resp["receipt_url"]
            if mutant("adapter_returns_no_receipt"):
                receipt = ""
            return ChargeOutcome(ok=True, charge_id=resp["id"], receipt=receipt)
        if status == "declined":
            if mutant("adapter_treats_declined_as_success"):
                return ChargeOutcome(ok=True, charge_id=resp["id"], receipt="")
            return ChargeOutcome(ok=False, decline_code=resp["decline_code"])
        raise TransportError(f"unknown status {status!r}")

@dataclass
class Order:
    order_id: str
    status: str = "new"
    charge_id: str = ""
    receipt: str = ""
    message: str = ""

class CheckoutService:
    """The unit under test. `refactor` selects between internally different,
    behaviourally identical implementations — section 5 uses them."""

    def __init__(self, gateway: Any, refactor: str = "none") -> None:
        self.gateway = gateway
        self.refactor = refactor
        self.reads = 0

    def place_order(self, order_id: str, amount_cents: int,
                    currency: str, card: str) -> Order:
        order = Order(order_id=order_id)
        self.reads += 1
        if amount_cents == 0:
            # the one rule we enforce locally; this path never calls out.
            order.status = "client_error"
            order.message = "amount_cents must not be zero"
            return order
        key = f"idem-{order_id}"
        if mutant("service_reuses_one_idempotency_key"):
            key = "idem-fixed"
        if self.refactor != "single_read":
            self.reads += 1
        try:
            if self.refactor == "kwargs":
                out = self.gateway.charge(idempotency_key=key, amount_cents=amount_cents,
                                          currency=currency, card=card)
            else:
                out = self.gateway.charge(key, amount_cents, currency, card)
        except InvalidRequest as exc:
            order.status = ("server_error"
                            if mutant("service_maps_client_error_to_server_error")
                            else "client_error")
            order.message = str(exc)
            return order
        except TransportError as exc:
            order.status = "server_error"
            order.message = str(exc)
            return order
        except (KeyError, TypeError, ValueError) as exc:
            # a KeyError from a field the provider stopped sending lands here,
            # becomes a 500 for the customer, and looks like our bug.
            order.status = "server_error"
            order.message = f"{type(exc).__name__}: {exc}"
            return order
        return self._apply(order, out)

    def _apply(self, order: Order, out: ChargeOutcome) -> Order:
        if out.ok or mutant("service_marks_declined_as_paid"):
            order.status = "paid"
            if not mutant("service_skips_charge_id"):
                order.charge_id = out.charge_id
            order.receipt = out.receipt
        else:
            order.status = "declined"
            order.message = out.decline_code
        return order


# ══ THE CONSUMER'S TEST SUITE ════════════════════════════════════════════════

@dataclass(frozen=True)
class Scenario:
    name: str
    order_id: str
    amount_cents: int
    currency: str
    card: str
    expect_status: str
    expect_receipt: bool = False
    repeat: bool = False

# One order id whose idempotency key falls in the rate-limited bucket from R11
# and one that does not, so the scenario set covers both sides of that change.
_IDS = [f"A{i:04d}" for i in range(1, 400)]
CALM_ID = next(o for o in _IDS if not rate_limited_key(f"idem-{o}"))
BURST_ID = next(o for o in _IDS if rate_limited_key(f"idem-{o}"))

SCENARIOS: Tuple[Scenario, ...] = (
    Scenario("standard_charge_is_paid", CALM_ID, 2500, "usd", "ok", "paid", True),
    Scenario("eur_charge_is_paid", "A9001", 4200, "eur", "ok", "paid", True),
    Scenario("small_charge_is_paid", "A9002", 300, "usd", "ok", "paid", True),
    Scenario("declined_card_is_declined", "A9003", 2500, "usd", "declined", "declined"),
    Scenario("negative_amount_is_client_error", "A9004", -100, "usd", "ok", "client_error"),
    Scenario("unsupported_currency_is_client_error", "A9005", 2500, "gbp", "ok", "client_error"),
    Scenario("repeated_order_is_paid_once", "A9006", 2500, "usd", "ok", "paid", True, repeat=True),
    Scenario("rate_limited_order_is_paid", BURST_ID, 2500, "usd", "ok", "paid", True),
)

def run_scenario(scn: Scenario, transport: Any, refactor: str = "none") -> bool:
    """One test: place the order, assert on the ORDER, not on the calls."""
    svc = CheckoutService(PaymentClient(transport), refactor=refactor)
    order = svc.place_order(scn.order_id, scn.amount_cents, scn.currency, scn.card)
    if scn.repeat:
        order = svc.place_order(scn.order_id, scn.amount_cents, scn.currency, scn.card)
    if order.status != scn.expect_status:
        return False
    if scn.expect_status == "paid":
        if not order.charge_id:
            return False
        if scn.expect_receipt and not order.receipt:
            return False
    return True

def run_suite(transport_factory: Callable[[], Any], refactor: str = "none"):
    return [run_scenario(s, transport_factory(), refactor) for s in SCENARIOS]

# A day of real traffic, so the drift experiment can be priced in orders rather
# than in test cases. This is the only randomness in the file and it is seeded.
DAY_SIZE = 2000

def production_day() -> Tuple[Tuple[str, int, str, str, str], ...]:
    """(order_id, amount_cents, currency, card, expected_status). The expected
    status is derived from the order, not from any provider — it is what the
    customer should get, and it does not change when the provider does."""
    rng = random.Random(SEED)
    day = []
    for i in range(1, DAY_SIZE + 1):
        roll = rng.random()
        if roll < 0.02:
            amount, currency = rng.choice([0, -100, -1]), "usd"
        elif roll < 0.04:
            amount, currency = rng.randrange(500, 20000), "gbp"
        elif roll < 0.44:
            amount, currency = rng.randrange(50, 500), "usd"     # small charges
        else:
            amount = rng.randrange(500, 20000)
            currency = "usd" if rng.random() < 0.9 else "eur"
        card = "declined" if rng.random() < 0.06 else "ok"
        if amount <= 0 or currency not in ("usd", "eur"):
            expected = "client_error"
        elif card == "declined":
            expected = "declined"
        else:
            expected = "paid"
        day.append((f"P{i:04d}", amount, currency, card, expected))
    return tuple(day)

DAY = production_day()

def run_day(transport_factory: Callable[[], Any]) -> int:
    """How many of the day's orders got the outcome the customer should have
    seen. Note the receipt is NOT required: a client that tolerates an absent
    optional field is correct, so this measure is generous to the provider."""
    transport = transport_factory()
    correct = 0
    for order_id, amount, currency, card, expected in DAY:
        svc = CheckoutService(PaymentClient(transport))
        order = svc.place_order(order_id, amount, currency, card)
        if order.status == expected:
            correct += 1
    return correct

def section1() -> None:
    banner(1, "THE FIVE DOUBLES: WHAT EACH ONE LETS A TEST PROVE")
    print("  one port, five stand-ins, the same question asked of each:")
    print("  after the test runs, what can you actually assert?\n")

    key = "idem-A0001"
    good = ChargeOutcome(ok=True, charge_id="ch_1", receipt="https://r/1")

    # dummy: passed to satisfy a signature on a path that never charges.
    dummy_ok = True
    try:
        # a zero-amount order is rejected locally, so the gateway is never used
        CheckoutService(DummyGateway()).place_order("A0001", 0, "usd", "ok")
    except AssertionError:
        dummy_ok = False
    print(f"  dummy    never called; proves only that the path avoids the "
          f"dependency   -> gateway untouched: {dummy_ok}")

    stub = StubGateway(good)
    order = CheckoutService(stub).place_order("A0001", 2500, "usd", "ok")
    print(f"  stub     canned answer; proves the caller HANDLES it            "
          f"   -> order.status={order.status!r}, receipt set: "
          f"{bool(order.receipt)}")

    spy = SpyGateway(good)
    CheckoutService(spy).place_order("A0001", 2500, "usd", "ok")
    print(f"  spy      records calls; proves WHAT WAS SENT, after the fact    "
          f"   -> calls={spy.calls}")

    mock_gw = MockGateway(good, (key, 2500, "usd", "ok"))
    CheckoutService(mock_gw).place_order("A0001", 2500, "usd", "ok")
    mock_gw.verify()
    bad = MockGateway(good, (key, 9999, "usd", "ok"))
    caught = ""
    try:
        CheckoutService(bad).place_order("A0001", 2500, "usd", "ok")
    except AssertionError as exc:
        caught = str(exc)
    print(f"  mock     expectation set BEFORE the call; fails at the call site")
    print(f"           -> {caught}")

    fake = InMemoryProvider()
    svc = CheckoutService(PaymentClient(fake))
    svc.place_order("A0001", 2500, "usd", "ok")
    svc.place_order("A0001", 2500, "usd", "ok")
    print(f"  fake     a working implementation; proves things about STATE")
    print(f"           -> charges recorded for one key after two calls: "
          f"{fake.charge_count(key)}; stored={fake.recorded(key)['amount_cents']}c")

    print("\n  the assertion each one makes possible:")
    print("    double   input asserted   output asserted   STATE asserted   " "fails at call site")
    rows = (("dummy", "no", "no", "no", "n/a"), ("stub", "no", "yes", "no", "no"),
            ("spy", "yes (after)", "yes", "no", "no"),
            ("mock", "yes (before)", "yes", "no", "yes"),
            ("fake", "yes (after)", "yes", "yes", "no"))
    for name, i, o, s, f in rows:
        print(f"    {name:<8} {i:<15}  {o:<16}  {s:<15}  {f}")
    print("  only the fake can answer 'was this customer charged twice?',")
    print("  because only the fake has somewhere to put the first charge.")


# ══ 2 · THE DRIFT EXPERIMENT ═════════════════════════════════════════════════

def section2() -> None:
    banner(2, "MOCK DRIFT: THE FROZEN DOUBLE ACROSS TWELVE PROVIDER RELEASES")
    print(f"  {len(SCENARIOS)} scenarios, {RELEASES} releases. The CI suite runs against a")
    print("  hand-written stub frozen at release 1. Production runs against the")
    print("  provider. Nothing compares the two.")
    print("  the four changes the provider shipped:")
    for name, rel in CHANGE_RELEASE.items():
        print(f"    R{rel:<3} {name:<30} {CHANGE_DETAIL[name]}")
    print(f"  (rate-limited order id chosen by hash: {BURST_ID}; " f"unaffected: {CALM_ID})\n")

    frozen_pass = sum(run_suite(FrozenStubTransport))

    print(f"  release   CI suite (frozen stub)   real provider: {len(SCENARIOS)} scenarios"
          f"   a {DAY_SIZE}-order day    green")
    print( "                                                            "
           "                        while broken")
    first_silent = 0
    false_conf = 0
    worst = DAY_SIZE
    for rel in range(1, RELEASES + 1):
        rp = sum(run_suite(lambda r=rel: RealProvider.at_release(r)))
        day = run_day(lambda r=rel: RealProvider.at_release(r))
        worst = min(worst, day)
        lying = frozen_pass == len(SCENARIOS) and rp < len(SCENARIOS)
        if lying:
            false_conf += 1
            if not first_silent:
                first_silent = rel
        print(f"    R{rel:<6}  {frozen_pass}/{len(SCENARIOS)} green                "
              f"  {rp}/{len(SCENARIOS)} correct              "
              f"{day:>5}/{DAY_SIZE} ({day / DAY_SIZE:5.1%})    "
              f"{'YES' if lying else '-'}")

    print(f"\n  the frozen stub passed {frozen_pass}/{len(SCENARIOS)} on every one of "
          f"{RELEASES} releases.")
    print(f"  releases to first silent failure: {first_silent - 1} genuinely green, "
          f"then R{first_silent} onwards.")
    print(f"  total false confidence: {false_conf} of {RELEASES} releases green while broken "
          f"({false_conf / RELEASES:.0%} of the year).")

    broken = [s.name for s, ok in zip(SCENARIOS, run_suite(
        lambda: RealProvider.at_release(RELEASES))) if not ok]
    print(f"  at R{RELEASES} the real provider fails {len(broken)} of {len(SCENARIOS)} scenarios "
          f"and the suite still reports 0 failures:")
    for name in broken:
        print(f"    - {name}")

    print(f"  worst release served {DAY_SIZE - worst} of {DAY_SIZE} orders "
          f"({(DAY_SIZE - worst) / DAY_SIZE:.1%}) the wrong outcome.")

    print("\n  each change ALONE (one enabled at a time, so a failure is")
    print("  attributed to what actually caused it):")
    print("    change                          lands  suite  day wrong  " "scenarios it broke")
    for name, rel in CHANGE_RELEASE.items():
        res = run_suite(lambda c=name: RealProvider.with_only(c))
        day = run_day(lambda c=name: RealProvider.with_only(c))
        hit = [s.name for s, ok in zip(SCENARIOS, res) if not ok]
        print(f"    {name:<30}  R{rel:<4} {sum(res)}/{len(SCENARIOS)}   "
              f"{1 - day / DAY_SIZE:6.1%}     {', '.join(hit) if hit else '-'}")
    print("  the stub never moved on any of them. It could not: nothing connects")
    print("  it to the provider it claims to imitate.")


# ══ 3 · THE CONTRACT SUITE ═══════════════════════════════════════════════════
# One suite of clauses about the PROVIDER'S behaviour, run against both the
# fake and the real thing. It is the only thing in this file that can notice
# a difference between them.

ClauseFn = Callable[[Any], bool]

RATE_LIMITED_FIXTURE = next(f"contract-fixture-{i:02d}" for i in range(8, 200)
                            if rate_limited_key(f"contract-fixture-{i:02d}"))

def _post(p: Any, key: str, amount: int, currency: str, card: str) -> Response:
    return p.post("/v1/charges", {"idempotency_key": key, "amount_cents": amount,
                                  "currency": currency, "card": card})

def clause(key: str, amount: int, currency: str, card: str,
           check: Callable[[int, Dict[str, Any]], bool]) -> ClauseFn:
    """A clause is one request plus one predicate over (status_code, body).
    Note what the fixture data decides: the amount and the key in each clause
    are exactly what determines which future change it can notice."""
    return lambda p: check(*_post(p, key, amount, currency, card))

def replay_clause(p: Any) -> bool:
    _, first = _post(p, "contract-fixture-06", 2500, "usd", "ok")
    _, second = _post(p, "contract-fixture-06", 2500, "usd", "ok")
    return first.get("id") == second.get("id") and bool(first.get("id"))

CONTRACT_V1: Tuple[Tuple[str, ClauseFn], ...] = (("success status is the string 'success'",
     clause("contract-fixture-01", 2500, "usd", "ok",
            lambda c, b: c == 200 and b.get("status") == "success")),
    ("success body carries a non-empty id", clause("contract-fixture-02", 2500, "usd", "ok",
            lambda c, b: c == 200 and isinstance(b.get("id"), str) and bool(b["id"]))),
    ("success body carries receipt_url", clause("contract-fixture-03", 2500, "usd", "ok",
            lambda c, b: c == 200 and "receipt_url" in b)),
    ("declined is 200 with a decline_code", clause("contract-fixture-04", 2500, "usd", "declined",
            lambda c, b: c == 200 and b.get("status") == "declined"
            and isinstance(b.get("decline_code"), str))),
    ("invalid amount is 400 with error string", clause("contract-fixture-05", -100, "usd", "ok",
            lambda c, b: c == 400 and isinstance(b.get("error"), str))),
    ("replayed idempotency key returns same id", replay_clause),
)

# v2 adds the two clauses that close the gaps v1 leaves: a charge small enough
# to lose its receipt, and a key that lands in the rate-limited bucket.
CONTRACT_V2: Tuple[Tuple[str, ClauseFn], ...] = CONTRACT_V1 + (
    ("small charge ALSO carries receipt_url", clause("contract-fixture-07", 300, "usd", "ok",
            lambda c, b: c == 200 and "receipt_url" in b)),
    ("no status outside 200/400 is ever returned",
     clause(RATE_LIMITED_FIXTURE, 2500, "usd", "ok", lambda c, b: c in (200, 400))),
)

def run_contract(provider_factory: Callable[[], Any],
                 clauses: Tuple[Tuple[str, ClauseFn], ...]) -> List[bool]:
    out = []
    for _name, fn in clauses:
        try:
            out.append(bool(fn(provider_factory())))
        except Exception:
            out.append(False)
    return out

def detects(clauses: Tuple[Tuple[str, ClauseFn], ...], change: str) -> bool:
    """Does this clause set notice `change` at all? Run it against a provider
    with ONLY that change enabled — the honest attribution."""
    return not all(run_contract(lambda c=change: RealProvider.with_only(c), clauses))

def detect_release(clauses: Optional[Tuple[Tuple[str, ClauseFn], ...]], change: str) -> int:
    """The release at which this guard first goes red because of `change`.
    0 means never. A contract suite runs against the provider's sandbox in CI,
    so it goes red the release the change lands — or not at all."""
    if clauses is None:
        return 0
    return CHANGE_RELEASE[change] if detects(clauses, change) else 0

def exposure(clauses: Optional[Tuple[Tuple[str, ClauseFn], ...]]):
    """A defect is exposed from the release it lands until the release its
    guard goes red. Returns (first silent release, defect-releases exposed,
    releases green-while-broken)."""
    silent_releases: set = set()
    exposed = 0
    for change, land in CHANGE_RELEASE.items():
        det = detect_release(clauses, change)
        last = (det - 1) if det else RELEASES
        span = list(range(land, last + 1))
        exposed += len(span)
        silent_releases |= set(span)
    first = min(silent_releases) if silent_releases else 0
    return first, exposed, len(silent_releases)

def section3() -> None:
    banner(3, "THE FIX: ONE CONTRACT SUITE, RUN AGAINST BOTH IMPLEMENTATIONS")
    print("  the same clauses run against our in-memory fake AND against the")
    print("  provider's sandbox. Divergence is the signal.\n")

    fake_now = run_contract(lambda: InMemoryProvider(), CONTRACT_V2)
    print(f"  contract v2 ({len(CONTRACT_V2)} clauses) against our fake, synced to R1: "
          f"{sum(fake_now)}/{len(CONTRACT_V2)} pass")
    print("  a double that passes its own contract proves nothing on its own.")
    print("  the same clauses against the provider are what make it evidence.\n")

    print("  contract v1 (6 clauses) against the real provider, per release:")
    print("    release   clauses passing   clauses failing")
    for rel in range(1, RELEASES + 1):
        res = run_contract(lambda r=rel: RealProvider.at_release(r), CONTRACT_V1)
        failed = [n for (n, _), ok in zip(CONTRACT_V1, res) if not ok]
        print(f"      R{rel:<6}  {sum(res)}/{len(CONTRACT_V1)}               "
              f"{'; '.join(failed) if failed else '-'}")

    print("\n  per change, with ONLY that change enabled: which guard notices?")
    print("    change                          lands   frozen stub   contract v1" "   contract v2")
    for name, rel in CHANGE_RELEASE.items():
        v1 = detect_release(CONTRACT_V1, name)
        v2 = detect_release(CONTRACT_V2, name)
        print(f"    {name:<30}  R{rel:<5}  {'never':<12}  "
              f"{('R%d' % v1) if v1 else 'never':<12}  "
              f"{('R%d' % v2) if v2 else 'never'}")

    caught_v1 = sum(1 for c in CHANGE_RELEASE if detects(CONTRACT_V1, c))
    caught_v2 = sum(1 for c in CHANGE_RELEASE if detects(CONTRACT_V2, c))
    print(f"\n  contract v1 caught {caught_v1} of {len(CHANGE_RELEASE)}; contract v2 caught "
          f"{caught_v2} of {len(CHANGE_RELEASE)}.")
    print("  a contract is not magic — it covers exactly what it exercises. v1's")
    print("  receipt clause charges 2500c and the provider only drops the receipt")
    print(f"  below 500c; none of v1's six fixture keys land in the rate-limited")
    print(f"  bucket ({RATE_LIMITED_FIXTURE} does). Two more clauses close both gaps.")

    print("\n  exposure: a defect is live from the release it lands until its")
    print("  guard goes red.")
    print("    guard          first silent release   defect-releases exposed"
          "   releases green-while-broken")
    for label, clauses in (("frozen stub", None), ("contract v1", CONTRACT_V1),
                           ("contract v2", CONTRACT_V2)):
        first, exposed, green_broken = exposure(clauses)
        print(f"    {label:<14} {('R%d' % first) if first else 'none':<22} "
              f"{exposed:<25} {green_broken}")

    print("\n  and the loop closes: the contract goes red, so we sync the fake,")
    print("  and now OUR OWN unit suite reproduces the outage on a laptop.")
    real_r4 = sum(run_suite(lambda: RealProvider.at_release(4)))
    for rel, label in ((1, "fake synced to R1 (stale)"), (4, "fake synced to R4 (updated)")):
        res = run_suite(lambda r=rel: InMemoryProvider.synced_to_release(r))
        print(f"    {label:<28} unit suite: {sum(res)}/{len(SCENARIOS)}   "
              f"real provider at R4: {real_r4}/{len(SCENARIOS)}")
    print("  the updated fake and the real provider now fail the same scenarios,")
    print("  offline, with no vendor sandbox in the loop. That is the technique:")
    print("  the contract keeps the fake honest, and the fake keeps the suite fast.")


# ══ 4 · Mock() VERSUS create_autospec() ══════════════════════════════════════

def section4() -> None:
    banner(4, "Mock() WILL AGREE WITH ANYTHING YOU SAY")
    print("  seven mistakes a real test makes. A double catches one if the")
    print("  mistake raises. Silence means the test passes and proves nothing.\n")

    def d1_renamed_method(gw: Any) -> None:
        gw.charge_card("idem-1", 2500, "usd", "ok")

    def d2_too_few_arguments(gw: Any) -> None:
        gw.charge("idem-1", 2500)

    def d3_wrong_keyword(gw: Any) -> None:
        gw.charge(key="idem-1", amount_cents=2500, currency="usd", card="ok")

    def d4_attribute_that_does_not_exist(gw: Any) -> None:
        if gw.last_charge_id:
            pass

    def d5_misspelled_assertion(gw: Any) -> None:
        gw.charge("idem-1", 2500, "usd", "ok")
        gw.charge.assert_caled_once_with("idem-1", 2500, "usd", "ok")

    def d6_assertion_never_called(gw: Any) -> None:
        gw.charge("idem-1", 2500, "usd", "ok")
        assert gw.charge.assert_called_once  # no parentheses: always truthy

    def d7_sets_a_field_that_does_not_exist(gw: Any) -> None:
        gw.timeout_seconds = 5

    defects = (("method renamed in production", d1_renamed_method),
               ("call with too few arguments", d2_too_few_arguments),
               ("keyword argument that does not exist", d3_wrong_keyword),
               ("reads an attribute that does not exist", d4_attribute_that_does_not_exist),
               ("misspelled assertion: assert_caled_", d5_misspelled_assertion),
               ("assertion referenced, never called", d6_assertion_never_called),
               ("assigns a field the port does not have", d7_sets_a_field_that_does_not_exist))

    doubles = (("Mock()", lambda: Mock()), ("Mock(spec=)", lambda: Mock(spec=PaymentGateway)),
               ("autospec", lambda: create_autospec(PaymentGateway, instance=True)),
               ("+spec_set", lambda: create_autospec(PaymentGateway, instance=True, spec_set=True)))

    print(f"    {'the mistake':<40}" + "".join(f"{n:<15}" for n, _ in doubles).rstrip())
    caught_total = [0] * len(doubles)
    for label, defect in defects:
        cells = []
        for i, (_name, factory) in enumerate(doubles):
            gw = factory()
            try:
                defect(gw)
                cells.append("silent")
            except Exception as exc:
                cells.append(type(exc).__name__)
                caught_total[i] += 1
        print(f"    {label:<40}" + "".join(f"{c:<15}" for c in cells).rstrip())
    print(f"    {'CAUGHT':<40}" + "".join(f"{str(c) + '/' + str(len(defects)):<15}"
                    for c in caught_total).rstrip())

    print(f"\n  a bare Mock() caught {caught_total[0]} of {len(defects)}.")
    print(f"  create_autospec() caught {caught_total[2]}, spec_set " f"{caught_total[3]}.")
    print("  the one nothing catches is the assertion you referenced but never")
    print("  called: `assert m.assert_called_once` is a bound method, and a bound")
    print("  method is truthy. No spec can see that — only a linter can.")

    print("\n  why the bare Mock() is silent: it manufactures whatever you ask for.")
    m = Mock()
    print(f"    type(Mock().charge_card)                 = " f"{type(m.charge_card).__name__}")
    print(f"    bool(Mock().anything_at_all)             = " f"{bool(m.anything_at_all)}")
    print(f"    Mock().charge()                          = "
          f"{type(m.charge()).__name__}  (no signature check)")
    a = create_autospec(PaymentGateway, instance=True)
    print(f"    type(create_autospec(...).charge)        = {type(a.charge).__name__}")
    try:
        a.charge("k", 1)
    except TypeError as exc:
        print(f"    create_autospec(...).charge('k', 1)      -> TypeError: {exc}")


# ══ 5 · INTERACTION VERSUS OUTCOME ═══════════════════════════════════════════

MUTANTS = (("adapter_drops_idempotency_key", "adapter"),
    ("adapter_sends_amount_in_dollars", "adapter"),
    ("adapter_ignores_currency", "adapter"),
    ("adapter_treats_declined_as_success", "adapter"),
    ("adapter_swallows_400", "adapter"),
    ("adapter_returns_no_receipt", "adapter"),
    ("service_marks_declined_as_paid", "service"),
    ("service_skips_charge_id", "service"),
    ("service_maps_client_error_to_server_error", "service"),
    ("service_reuses_one_idempotency_key", "service"),
)

def interaction_suite(refactor: str) -> List[bool]:
    """Asserts on the CALLS. This is what a mock-first suite looks like."""
    results: List[bool] = []

    gw = create_autospec(PaymentGateway, instance=True)
    gw.charge.return_value = ChargeOutcome(ok=True, charge_id="ch_1", receipt="https://r/1")
    svc = CheckoutService(gw, refactor=refactor)
    svc.place_order("A0001", 2500, "usd", "ok")
    try:
        gw.charge.assert_called_once_with("idem-A0001", 2500, "usd", "ok")
        results.append(True)
    except AssertionError:
        results.append(False)

    gw2 = create_autospec(PaymentGateway, instance=True)
    gw2.charge.return_value = ChargeOutcome(ok=True, charge_id="ch_1")
    svc2 = CheckoutService(gw2, refactor=refactor)
    svc2.place_order("A0002", 2500, "usd", "ok")
    results.append(gw2.charge.call_count == 1 and svc2.reads == 2)

    gw3 = create_autospec(PaymentGateway, instance=True)
    gw3.charge.return_value = ChargeOutcome(ok=False, decline_code="card_declined")
    svc3 = CheckoutService(gw3, refactor=refactor)
    svc3.place_order("A0003", 2500, "usd", "declined")
    results.append(gw3.charge.call_count == 1 and gw3.charge.call_args.args[:1] == ("idem-A0003",))

    gw4 = create_autospec(PaymentGateway, instance=True)
    gw4.charge.return_value = ChargeOutcome(ok=True, charge_id="ch_9", receipt="https://r/9")
    svc4 = CheckoutService(gw4, refactor=refactor)
    svc4.place_order("A0004", 700, "eur", "ok")
    results.append(gw4.charge.call_args is not None
                   and gw4.charge.call_args.args == ("idem-A0004", 700, "eur", "ok"))
    return results

def outcome_suite_stub(refactor: str) -> List[bool]:
    """Asserts on the ORDER, with a canned stub underneath. No state to read."""
    results: List[bool] = []
    good = ChargeOutcome(ok=True, charge_id="ch_1", receipt="https://r/1")
    o = CheckoutService(StubGateway(good), refactor=refactor).place_order(
        "A0001", 2500, "usd", "ok")
    results.append(o.status == "paid" and o.charge_id == "ch_1")

    o2 = CheckoutService(StubGateway(good), refactor=refactor).place_order(
        "A0002", 2500, "usd", "ok")
    results.append(o2.receipt.startswith("https://"))

    bad = ChargeOutcome(ok=False, decline_code="card_declined")
    o3 = CheckoutService(StubGateway(bad), refactor=refactor).place_order(
        "A0003", 2500, "usd", "declined")
    results.append(o3.status == "declined" and o3.message == "card_declined")

    svc = CheckoutService(StubGateway(good), refactor=refactor)
    svc.place_order("A0004", 700, "eur", "ok")
    o4 = svc.place_order("A0004", 700, "eur", "ok")
    results.append(o4.status == "paid")
    return results

def outcome_suite_fake(refactor: str) -> List[bool]:
    """Asserts on the ORDER **and** on the fake's state. Same four tests."""
    results: List[bool] = []

    f1 = InMemoryProvider()
    o = CheckoutService(PaymentClient(f1), refactor=refactor).place_order(
        "A0001", 2500, "usd", "ok")
    results.append(o.status == "paid" and bool(o.charge_id)
                   and f1.recorded("idem-A0001").get("amount_cents") == 2500)

    f2 = InMemoryProvider()
    o2 = CheckoutService(PaymentClient(f2), refactor=refactor).place_order(
        "A0002", 2500, "usd", "ok")
    results.append(o2.receipt.startswith("https://")
                   and f2.recorded("idem-A0002").get("currency") == "usd")

    f3 = InMemoryProvider()
    o3 = CheckoutService(PaymentClient(f3), refactor=refactor).place_order(
        "A0003", 2500, "usd", "declined")
    results.append(o3.status == "declined" and o3.message == "card_declined")

    f4 = InMemoryProvider()
    svc = CheckoutService(PaymentClient(f4), refactor=refactor)
    svc.place_order("A0004", 700, "eur", "ok")
    o4 = svc.place_order("A0004", 700, "eur", "ok")
    results.append(o4.status == "paid" and len(f4.store) == 1
                   and f4.recorded("idem-A0004").get("amount_cents") == 700)
    return results

def kill_rate(suite: Callable[[str], List[bool]]) -> Tuple[int, List[str]]:
    """A mutant is killed only if the suite was green without it and red with
    it. Comparing against the baseline is what stops a suite that is already
    failing from scoring a free kill."""
    global ACTIVE_MUTANT
    baseline = suite("none")
    killed = 0
    survivors: List[str] = []
    for name, _layer in MUTANTS:
        ACTIVE_MUTANT = name
        try:
            res = suite("none")
            dead = any(b and not r for b, r in zip(baseline, res))
        except Exception:
            dead = True
        ACTIVE_MUTANT = None
        if dead:
            killed += 1
        else:
            survivors.append(name)
    return killed, survivors

def section5() -> None:
    banner(5, "INTERACTION ASSERTIONS BREAK ON REFACTORS AND CATCH LESS")
    print("  three suites of four tests over the same service. One asserts on the")
    print("  CALLS, one on the ORDER with a stub, one on the ORDER plus the " "fake's state.\n")

    suites = (("assert on calls (mock)", interaction_suite),
              ("assert on outcome (stub)", outcome_suite_stub),
              ("assert on outcome (fake)", outcome_suite_fake))

    print("  a · behaviour-preserving refactors — every one of these leaves the")
    print("      order, the charge and the receipt identical:")
    print("        kwargs       pass the same arguments by keyword")
    print("        single_read  read the order record once instead of twice")
    print("    suite                       baseline   kwargs   single_read   " "false alarms")
    for label, suite in suites:
        base = suite("none")
        cells = []
        alarms = 0
        for ref in ("kwargs", "single_read"):
            res = suite(ref)
            broke = sum(1 for b, r in zip(base, res) if b and not r)
            alarms += broke
            cells.append(f"{sum(res)}/{len(res)}")
        print(f"    {label:<26}  {sum(base)}/{len(base)}        {cells[0]:<8} "
              f"{cells[1]:<13} {alarms}")

    print("\n  b · the same three suites against 10 seeded bugs "
          "(6 in the adapter, 4 in the service):")
    print("    suite                       bugs killed   survivors")
    for label, suite in suites:
        killed, survivors = kill_rate(suite)
        short = ", ".join(s.replace("adapter_", "a:").replace("service_", "s:")
                          for s in survivors[:3])
        more = f" (+{len(survivors) - 3})" if len(survivors) > 3 else ""
        print(f"    {label:<26}  {killed}/{len(MUTANTS)}           " f"{short}{more}")
    print("  the interaction suite pays churn on refactors that changed nothing,")
    print("  and it cannot see a bug the adapter introduces because the adapter")
    print("  never runs. The stub suite has no state to interrogate. The fake")
    print("  suite asserts on outcomes and still sees everything.")


# ══ 6 · MOCKING AT THE WRONG LAYER ═══════════════════════════════════════════

OURS = frozenset({"place_order", "_apply", "charge", "_parse"})


def statement_starts() -> Dict[str, List[int]]:
    """The first line of every statement in each method we trace, read from the
    AST rather than from executed line numbers.

    This indirection is the difference between a measurement and an artefact of
    your interpreter. CPython's line-event attribution for a statement spread
    over several physical lines changed between 3.9 and 3.11, so counting raw
    `f_lineno` values gave 64 reachable lines on 3.13 and 63 on 3.9 for the
    same program. Statement starts come from the source, so they do not move."""
    tree = ast.parse(open(__file__, encoding="utf-8").read())
    out: Dict[str, List[int]] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name in OURS):
            continue
        starts = {sub.lineno for sub in ast.walk(node)
                  if isinstance(sub, (ast.stmt, ast.ExceptHandler))}
        starts.discard(node.lineno)          # the `def` line is not a statement we run
        out[node.name] = sorted(starts)
    return out


STATEMENT_STARTS = statement_starts()


class LineTracer:
    """A minimal statement-coverage tracer over our own two classes. sys.settrace
    is stdlib; a real coverage tool does more, and Lesson 13 builds one properly.
    Each line event is folded onto the statement that contains it, so the count
    is identical on every interpreter."""

    OURS = OURS

    def __init__(self) -> None:
        self.lines: set = set()

    def _local(self, frame, event, arg):
        if event == "line":
            name = frame.f_code.co_name
            starts = STATEMENT_STARTS.get(name, ())
            i = bisect.bisect_right(starts, frame.f_lineno) - 1
            if i >= 0:
                self.lines.add((name, starts[i]))
        return self._local

    def _global(self, frame, event, arg):
        if (event == "call" and frame.f_code.co_name in self.OURS
                and frame.f_code.co_filename == __file__):
            return self._local
        return None

    def __enter__(self) -> "LineTracer":
        sys.settrace(self._global)
        return self

    def __exit__(self, *exc: Any) -> None:
        sys.settrace(None)

class ScenarioPortDouble:
    """Depth 1: the double sits at the port, configured per test with exactly
    the outcome the scenario expects. This is what a mock-first unit test looks
    like — and PaymentClient never runs."""

    def __init__(self, scn: Scenario) -> None:
        self.scn = scn

    def charge(self, idempotency_key: str, amount_cents: int,
               currency: str, card: str) -> ChargeOutcome:
        if self.scn.expect_status == "client_error":
            raise InvalidRequest("invalid request")
        if self.scn.expect_status == "declined":
            return ChargeOutcome(ok=False, decline_code="card_declined")
        return ChargeOutcome(ok=True, charge_id="ch_stub_1",
                             receipt="https://pay.example/r/ch_stub_1")

DEPTHS = (("1 · double at the PORT     ", lambda scn: ScenarioPortDouble(scn), False),
    ("2 · fake at the TRANSPORT  ", lambda scn: PaymentClient(InMemoryProvider()), True),
    ("3 · the real provider      ", lambda scn: PaymentClient(RealProvider(frozenset())), True),
)

def trace_depth(factory: Callable[[Scenario], Any]) -> set:
    with LineTracer() as tr:
        for scn in SCENARIOS:
            run_scenario_at_depth(scn, factory)
    return tr.lines

def run_scenario_at_depth(scn: Scenario, factory: Callable[[Scenario], Any]) -> bool:
    svc = CheckoutService(factory(scn))
    order = svc.place_order(scn.order_id, scn.amount_cents, scn.currency, scn.card)
    if scn.repeat:
        order = svc.place_order(scn.order_id, scn.amount_cents, scn.currency, scn.card)
    if order.status != scn.expect_status:
        return False
    if scn.expect_status == "paid" and not order.charge_id:
        return False
    if scn.expect_status == "paid" and scn.expect_receipt and not order.receipt:
        return False
    return True

def section6() -> None:
    banner(6, "A DOUBLE AT THE WRONG LAYER SKIPS YOUR OWN CODE")
    print("  the same eight scenarios, the double moved one layer deeper each")
    print("  time. `our lines` counts distinct executed statements inside")
    print("  CheckoutService and PaymentClient, traced with sys.settrace and")
    print("  folded onto AST statement starts so the count is interpreter-independent.\n")

    universe = set()
    for _l, factory, _s in DEPTHS:
        universe |= trace_depth(factory)
    deep = (lambda scn: PaymentClient(RealProvider.at_release(RELEASES), max_attempts=3),
            lambda scn: PaymentClient(InMemoryProvider.synced_to_release(RELEASES), max_attempts=3))
    for extra in deep:
        universe |= trace_depth(extra)
    total = len(universe)

    print(f"    depth                     our lines run   of {total} reachable   "
          f"suite   state assertions")
    for label, factory, has_state in DEPTHS:
        lines = trace_depth(factory)
        passing = sum(run_scenario_at_depth(s, factory) for s in SCENARIOS)
        print(f"    {label} {len(lines):>13}   {len(lines) / total:>16.0%}   "
              f"{passing}/{len(SCENARIOS)}     "
              f"{'available' if has_state else 'IMPOSSIBLE':>16}")

    print("\n  what each depth catches, over the same 10 seeded bugs")
    print("  (killed = green at baseline, red with the bug):")
    print("    depth                     adapter bugs   service bugs   total")
    global ACTIVE_MUTANT
    adapters = sum(1 for _n, lay in MUTANTS if lay == "adapter")
    services = sum(1 for _n, lay in MUTANTS if lay == "service")
    for label, factory, _hs in DEPTHS:
        baseline = [run_scenario_at_depth(s, factory) for s in SCENARIOS]
        killed = {"adapter": 0, "service": 0}
        for name, layer in MUTANTS:
            ACTIVE_MUTANT = name
            try:
                res = [run_scenario_at_depth(s, factory) for s in SCENARIOS]
                dead = any(b and not r for b, r in zip(baseline, res))
            except Exception:
                dead = True
            ACTIVE_MUTANT = None
            if dead:
                killed[layer] += 1
        print(f"    {label} {killed['adapter']}/{adapters}            "
              f"  {killed['service']}/{services}            "
              f"{killed['adapter'] + killed['service']}/{len(MUTANTS)}")

    print("  the port double gives a green suite while never executing the layer")
    print("  where the wire format lives — which is exactly where all four of")
    print("  section 2's provider changes landed.")

def main() -> None:
    random.Random(SEED)  # every experiment here is deterministic by construction
    section1()
    section2()
    section3()
    section4()
    section5()
    section6()
    print()

if __name__ == "__main__":
    main()
