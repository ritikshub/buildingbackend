#!/usr/bin/env python3
"""
A pub/sub broker: topics, subscriptions, wildcard subjects and fan-out.

Companion to docs/en.md (Phase 6, Lesson 04 - Pub/Sub: Topics, Subscriptions &
Fan-Out). A queue hands each message to ONE consumer; a topic hands EVERY
message to EVERY subscription. This builds the second shape and measures it:
wildcard subject matching ('*' one token; '#' zero or more per AMQP 0-9-1;
'>' one or more and terminal per NATS), attribute filters in the shape of an
SNS filter policy evaluated against the ENVELOPE only, per-subscription durable
queues with the lease/ack machinery of Lesson 03, three competing consumers
inside one subscription (the two shapes compose), a subscriber that disconnects
mid-run, and the fan-out amplification one publish actually costs.

Deterministic: every RNG is seeded and the clock is virtual, so two runs print
identical output.  Standard library only:  python pubsub_broker.py
"""

from __future__ import annotations

import json
import random
from collections import deque
from dataclasses import dataclass, field

SEED = 4111
BASE_TS = 1_700_000_000.0
TICK = 0.005          # virtual clock granularity, seconds
LEASE = 0.120         # a delivered message is invisible this long before redelivery


# ─── the message: an envelope the broker reads, a payload it does not ────────

@dataclass
class Message:
    message_id: str
    subject: str
    headers: dict[str, str]      # the envelope. Filters see ONLY this.
    payload: str                 # opaque body. The broker never parses it.
    ts: float

    def __post_init__(self) -> None:
        self.header_bytes = len(json.dumps(self.headers, separators=(",", ":")))
        self.payload_bytes = len(self.payload)
        self.size = self.header_bytes + self.payload_bytes + len(self.subject) + len(self.message_id)


REGIONS = ["eu-west-1", "eu-central-1", "us-east-1", "ap-south-1"]
EVENTS = ["created", "created", "created", "cancelled", "amended"]
TIERS = ["free", "free", "silver", "gold"]
AMOUNTS = [320, 1299, 4999, 8250, 62_000, 145_000]


def make_message(i: int, rnd: random.Random, ts: float) -> Message:
    """One OrderPlaced-shaped event: a small envelope and a fat payload."""
    region, kind = rnd.choice(REGIONS), rnd.choice(EVENTS)
    tier, amount = rnd.choice(TIERS), rnd.choice(AMOUNTS)
    payload = json.dumps({
        "order_id": f"ord_{i:05d}",
        "customer_id": f"cus_{rnd.randrange(90_000):05d}",
        "lines": [{"sku": f"SKU-{rnd.randrange(9999):04d}",
                   "qty": rnd.randrange(1, 5),
                   "unit_cents": rnd.randrange(199, 9999)} for _ in range(rnd.randrange(1, 4))],
        "total_cents": amount,
        "currency": "EUR" if region.startswith("eu-") else "USD",
        "ship_to": {"country": region.split("-")[0].upper(), "postcode": f"{rnd.randrange(99999):05d}"},
        "placed_at": round(BASE_TS + ts, 3),
    }, separators=(",", ":"))
    headers = {"event_type": f"Order{kind.capitalize()}", "region": region, "tier": tier,
               "amount_cents": str(amount), "source": "checkout-api", "schema_version": "3"}
    return Message(f"msg-{i:05d}", f"order.{region}.{kind}", headers, payload, ts)


# ─── subject matching: '*' one token, '#' zero or more, '>' one or more ──────

MULTI = {"#": 0, ">": 1}          # multi-segment wildcard -> tokens it must consume


def subject_matches(pattern: str, subject: str) -> bool:
    """Match a dot-separated subject against a pattern.

    '*' matches exactly one token and never crosses a dot.
    '#' matches zero or more tokens   (AMQP 0-9-1 topic exchange).
    '>' matches one or more tokens    (NATS) and must be the final token.
    """
    p = pattern.split(".")
    if ">" in p and p.index(">") != len(p) - 1:
        raise ValueError(f"'>' must be the final token: {pattern!r}")
    return _match(p, 0, subject.split("."), 0)


def _match(p: list[str], i: int, s: list[str], j: int) -> bool:
    while i < len(p):
        tok = p[i]
        if tok in MULTI:
            lo = MULTI[tok]
            if i == len(p) - 1:                       # terminal wildcard: swallow the rest
                return len(s) - j >= lo
            for k in range(lo, len(s) - j + 1):       # interior '#': try every split
                if _match(p, i + 1, s, j + k):
                    return True
            return False
        if j >= len(s) or (tok != "*" and tok != s[j]):
            return False
        i += 1
        j += 1
    return j == len(s)


# ─── attribute filters: SNS-filter-policy shaped, envelope only ──────────────

_OPS = {"=": lambda a, b: a == b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
        "<": lambda a, b: a < b, "<=": lambda a, b: a <= b}


def _numeric(value, ops: list) -> bool:
    """Header values arrive as strings on the wire; a numeric rule must parse."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    return all(_OPS[ops[k]](v, float(ops[k + 1])) for k in range(0, len(ops), 2))


class Filter:
    """AND across keys, OR within a key. A missing key fails unless exists:false."""

    def __init__(self, policy: dict[str, list]) -> None:
        self.policy = policy
        self.evaluations = 0

    def matches(self, headers: dict[str, str]) -> bool:
        self.evaluations += 1
        return all(self._key(headers.get(k), rules) for k, rules in self.policy.items())

    @staticmethod
    def _key(value, rules: list) -> bool:
        for rule in rules:
            if isinstance(rule, str):
                if value == rule:
                    return True
            elif "prefix" in rule:
                if isinstance(value, str) and value.startswith(rule["prefix"]):
                    return True
            elif "anything-but" in rule:
                if value is not None and value not in rule["anything-but"]:
                    return True
            elif "exists" in rule:
                if (value is not None) == rule["exists"]:
                    return True
            elif "numeric" in rule:
                if _numeric(value, rule["numeric"]):
                    return True
        return False

    def __str__(self) -> str:
        return json.dumps(self.policy, separators=(",", ":"))


# ─── the subscription: the unit of fan-out, with its own queue and ack state ─

@dataclass
class SubStats:
    """subject_miss/filtered = rejected at publish; stored = fan-out writes;
    delivered = poll() hand-offs; lost = ephemeral drops with nobody listening."""
    subject_miss: int = 0
    filtered: int = 0
    stored: int = 0
    stored_bytes: int = 0
    delivered: int = 0
    redelivered: int = 0
    acked: int = 0
    duplicate_acks: int = 0
    lost: int = 0
    peak_backlog: int = 0


class Subscription:
    """One subscription = one independent copy of the matching message stream.

    durable=True  -> its own queue survives disconnection; lease/ack; at-least-once.
    durable=False -> no retained state; if nobody is attached the message is
                     dropped on the floor; no leases, so at-most-once.
    """

    def __init__(self, name: str, pattern: str, filt: Filter | None = None,
                 durable: bool = True) -> None:
        self.name, self.pattern, self.filt, self.durable = name, pattern, filt, durable
        self.queue: deque[Message] = deque()
        self.inflight: dict[str, tuple[Message, float]] = {}
        self.consumers: list[Consumer] = []
        self.stats = SubStats()
        self.acked_ids: set[str] = set()

    # -- broker side ---------------------------------------------------------

    @property
    def attached(self) -> bool:
        return any(c.online for c in self.consumers)

    def offer(self, msg: Message) -> bool:
        """The fan-out write. Returns True if a copy was stored for this subscription."""
        if not self.durable and not self.attached:
            self.stats.lost += 1                       # Redis PUBLISH with nobody subscribed
            return False
        self.queue.append(msg)
        self.stats.stored += 1
        self.stats.stored_bytes += msg.size
        self.stats.peak_backlog = max(self.stats.peak_backlog, self.backlog)
        return True

    def disconnect(self) -> None:
        if not self.durable:
            # No retained state: the queue evaporates, and an at-most-once consumer
            # loses whatever it was still holding. Nothing is redelivered.
            self.stats.lost += len(self.queue) + sum(len(c.holding) for c in self.consumers)
            self.queue.clear()
        for c in self.consumers:
            c.online = False
            c.holding = []                             # a crashed consumer acks nothing
            c.busy_until = 0.0

    def reconnect(self) -> None:
        for c in self.consumers:
            c.online = True

    # -- consumer side -------------------------------------------------------

    @property
    def backlog(self) -> int:
        return len(self.queue) + len(self.inflight)

    def poll(self, now: float, n: int) -> list[Message]:
        out: list[Message] = []
        while self.queue and len(out) < n:
            msg = self.queue.popleft()
            self.stats.delivered += 1
            if self.durable:
                if msg.message_id in self.inflight:
                    self.stats.redelivered += 1
                self.inflight[msg.message_id] = (msg, now + LEASE)
            out.append(msg)
        return out

    def ack(self, message_id: str) -> None:
        if self.durable:
            if message_id not in self.inflight:
                self.stats.duplicate_acks += 1
                return
            del self.inflight[message_id]
        if message_id in self.acked_ids:
            self.stats.duplicate_acks += 1
            return
        self.acked_ids.add(message_id)
        self.stats.acked += 1

    def expire_leases(self, now: float) -> None:
        if not self.durable:
            return
        for mid in [m for m, (_, dl) in self.inflight.items() if dl <= now]:
            msg, _ = self.inflight.pop(mid)
            self.queue.appendleft(msg)
            self.stats.redelivered += 1


class Consumer:
    """A worker attached to one subscription. Several may compete for the same one."""

    def __init__(self, name: str, sub: Subscription, prefetch: int, service_time: float) -> None:
        self.name, self.sub = name, sub
        self.prefetch, self.service_time = prefetch, service_time
        self.online = True
        self.busy_until = 0.0
        self.holding: list[Message] = []
        self.acked = 0
        sub.consumers.append(self)

    def step(self, now: float) -> None:
        if not self.online or now < self.busy_until:
            return
        for msg in self.holding:                       # the batch finished processing
            before = self.sub.stats.acked
            self.sub.ack(msg.message_id)
            self.acked += self.sub.stats.acked - before
        self.holding = []
        batch = self.sub.poll(now, self.prefetch)
        if batch:
            self.holding = batch
            self.busy_until = round(now + self.service_time * len(batch), 6)


# ─── the topic ───────────────────────────────────────────────────────────────

class Topic:
    def __init__(self, name: str) -> None:
        self.name = name
        self.subscriptions: list[Subscription] = []
        self.published = 0
        self.published_bytes = 0
        self.fanout_writes = 0
        self.fanout_bytes = 0
        self.header_bytes_read = 0
        self.payload_bytes_read = 0                    # stays 0. That is the whole point.

    def subscribe(self, sub: Subscription) -> Subscription:
        self.subscriptions.append(sub)
        return sub

    def publish(self, msg: Message) -> None:
        """One publish; up to len(subscriptions) writes. This is the amplification."""
        self.published += 1
        self.published_bytes += msg.size
        for sub in self.subscriptions:
            if not subject_matches(sub.pattern, msg.subject):
                sub.stats.subject_miss += 1
                continue
            if sub.filt is not None:
                self.header_bytes_read += msg.header_bytes
                if not sub.filt.matches(msg.headers):
                    sub.stats.filtered += 1
                    continue
            if sub.offer(msg):
                self.fanout_writes += 1
                self.fanout_bytes += msg.size


# ─── the virtual clock ───────────────────────────────────────────────────────

def run_clock(topic: Topic, schedule: list[tuple[float, Message]],
              hooks: list[tuple[float, callable]], horizon: float,
              samples: list[float] | None = None) -> tuple[float, list[tuple]]:
    now, si, hi, taken = 0.0, 0, 0, []
    pending_samples = list(samples or [])
    while now <= horizon + 1e-9:
        while hi < len(hooks) and hooks[hi][0] <= now + 1e-9:
            hooks[hi][1]()
            hi += 1
        while si < len(schedule) and schedule[si][0] <= now + 1e-9:
            topic.publish(schedule[si][1])
            si += 1
        for sub in topic.subscriptions:
            sub.expire_leases(now)
        for sub in topic.subscriptions:
            for c in sub.consumers:
                c.step(now)
        if pending_samples and pending_samples[0] <= now + 1e-9:
            pending_samples.pop(0)
            taken.append((now, tuple(s.backlog for s in topic.subscriptions)))
        now = round(now + TICK, 6)
    return now, taken


def drain(topic: Topic, now: float, limit: int = 20_000) -> float:
    for _ in range(limit):
        if not any(s.backlog or any(c.holding for c in s.consumers) for s in topic.subscriptions):
            break
        for sub in topic.subscriptions:
            sub.expire_leases(now)
        for sub in topic.subscriptions:
            for c in sub.consumers:
                c.step(now)
        now = round(now + TICK, 6)
    return now


# ─── report sections ─────────────────────────────────────────────────────────

def section_subjects() -> None:
    print("== 1. SUBJECT MATCHING: '*' is one token, '#' is zero or more, '>' is one or more ==")
    cases = [
        ("order.*.created", "order.eu-west-1.created", True, "'*' fills exactly one token"),
        ("order.*.created", "order.created", False, "'*' cannot match zero tokens"),
        ("order.*.created", "order.eu.west.created", False, "'*' never crosses a dot"),
        ("order.*", "order.eu.created", False, "pattern is shorter than the subject"),
        ("*.eu-west-1.*", "order.eu-west-1.created", True, "wildcards anywhere, not just the tail"),
        ("order.#", "order.eu-west-1.created", True, "'#' swallows the remaining tokens"),
        ("order.#", "order", True, "AMQP '#' matches ZERO tokens -- the classic surprise"),
        ("order.>", "order", False, "NATS '>' needs at least one token. Same shape, different rule"),
        ("order.>", "order.eu-west-1.created", True, "'>' behaves like '#' once there is something to eat"),
        ("order.#.created", "order.eu.west.created", True, "an interior '#' is legal in AMQP"),
        ("order.#.created", "order.created", True, "...and matches zero tokens there too"),
        ("#", "payment.eu-west-1.captured", True, "the firehose subscription"),
        ("order.#", "payment.eu-west-1.captured", False, "a different root never matches"),
        ("Order.#", "order.eu-west-1.created", False, "subjects are case-SENSITIVE"),
        ("order.*.created", "order.eu-west-1.cancelled", False, "literal tokens must match exactly"),
    ]
    print(f"  {'pattern':<18} {'subject':<30} {'expect':<7} {'got':<7} why")
    ok = 0
    for pattern, subject, expect, why in cases:
        got = subject_matches(pattern, subject)
        ok += got == expect
        print(f"  {pattern:<18} {subject:<30} {str(expect):<7} {str(got):<7} {why}")
    print(f"  {ok}/{len(cases)} cases agree with the specification")
    try:
        subject_matches("order.>.created", "order.eu.created")
    except ValueError as exc:
        print(f"  rejected at subscribe time: {exc}")


def section_filters() -> None:
    print("\n== 2. ATTRIBUTE FILTERS: AND across keys, OR within a key, envelope only ==")
    hi = {"event_type": "OrderCreated", "region": "eu-west-1", "tier": "gold",
          "amount_cents": "145000", "source": "checkout-api", "schema_version": "3"}
    lo = {"event_type": "OrderCreated", "region": "us-east-1", "tier": "free",
          "amount_cents": "1299", "source": "batch-importer", "schema_version": "3"}
    bare = {"event_type": "OrderCreated", "source": "checkout-api", "schema_version": "3"}
    print("  three envelopes under test (headers only -- no payload is ever read):")
    print(f"    A  high-value EU order   region=eu-west-1  tier=gold    amount_cents=145000  source=checkout-api")
    print(f"    B  small US order        region=us-east-1  tier=free    amount_cents=1299    source=batch-importer")
    print(f"    C  region/tier headers absent                                                source=checkout-api")
    named = {"A": hi, "B": lo, "C": bare}
    cases = [
        ({"region": ["eu-west-1", "eu-central-1"]}, "an OR list of exact values"),
        ({"amount_cents": [{"numeric": [">=", 50000]}]}, "numeric rule; header string is parsed"),
        ({"amount_cents": [{"numeric": [">=", 1000, "<", 50000]}]}, "a numeric range, both bounds"),
        ({"tier": [{"anything-but": ["free"]}]}, "negation"),
        ({"source": [{"prefix": "checkout-"}]}, "prefix match"),
        ({"region": [{"exists": False}]}, "assert a header is absent"),
        ({"region": [{"prefix": "eu-"}], "tier": ["gold"]}, "two keys -> both must pass"),
    ]
    print(f"  {'policy':<52} " + " ".join(f"{n:<6}" for n in named) + " rule")
    for policy, why in cases:
        f = Filter(policy)
        cells = " ".join(f"{('MATCH' if f.matches(h) else '--'):<6}" for h in named.values())
        print(f"  {str(f):<52} {cells} {why}")
    print("  every decision above read only the envelope; 0 bytes of payload were deserialized")


def section_fanout() -> None:
    print("\n== 3. FAN-OUT + COMPOSITION: 3 subscriptions, one of them load-balanced 3 ways ==")
    rnd = random.Random(SEED)
    topic = Topic("orders")
    warehouse = topic.subscribe(Subscription("warehouse", "order.#"))
    analytics = topic.subscribe(Subscription("analytics", "order.#"))
    email = topic.subscribe(Subscription("email", "order.#"))
    Consumer("warehouse-1", warehouse, prefetch=4, service_time=0.010)
    Consumer("analytics-1", analytics, prefetch=8, service_time=0.004)
    Consumer("email-1", email, prefetch=2, service_time=0.020)
    Consumer("email-2", email, prefetch=2, service_time=0.030)
    Consumer("email-3", email, prefetch=2, service_time=0.015)

    # Publish at 250/s. The email subscription's three consumers together manage
    # 1/.020 + 1/.030 + 1/.015 = 150/s, so all three stay saturated and the split
    # reflects their speed rather than who happened to be idle.
    n = 24
    schedule = [(round(i * 0.004, 6), make_message(i, rnd, i * 0.004)) for i in range(n)]
    now, _ = run_clock(topic, schedule, [], horizon=0.12)
    drain(topic, now)

    print(f"  published {topic.published} messages to topic '{topic.name}'"
          f"  ({topic.published_bytes:,} bytes on the wire, once)")
    print(f"  {'subscription':<14} {'pattern':<10} {'cons':>4} {'stored':>7} {'deliv':>6}"
          f" {'redeliv':>8} {'acked':>6} {'dup':>4} {'unique':>7}")
    for sub in topic.subscriptions:
        s = sub.stats
        print(f"  {sub.name:<14} {sub.pattern:<10} {len(sub.consumers):>4} {s.stored:>7}"
              f" {s.delivered:>6} {s.redelivered:>8} {s.acked:>6} {s.duplicate_acks:>4}"
              f" {len(sub.acked_ids):>7}")
    split = "  ".join(f"{c.name}={c.acked}" for c in email.consumers)
    print(f"  the 'email' subscription's three competing consumers split its {email.stats.acked}"
          f" messages: {split}")
    print(f"  fan-out: {topic.published} publishes -> {topic.fanout_writes} queue writes"
          f"  ({topic.fanout_writes / topic.published:.1f}x)"
          f"   every subscription holds all {n}, no subscription holds any twice")


def section_isolation() -> None:
    print("\n== 4. ISOLATION: one subscriber disconnects (durable vs ephemeral) ==")
    rnd = random.Random(SEED + 1)
    topic = Topic("orders")
    warehouse = topic.subscribe(Subscription("warehouse", "order.#", durable=True))
    analytics = topic.subscribe(Subscription("analytics", "order.#", durable=True))
    dashboard = topic.subscribe(Subscription("live-dashboard", "order.#", durable=False))
    Consumer("warehouse-1", warehouse, prefetch=4, service_time=0.006)
    Consumer("analytics-1", analytics, prefetch=4, service_time=0.006)
    Consumer("dashboard-1", dashboard, prefetch=4, service_time=0.006)

    n = 60
    schedule = [(round(i * 0.010, 6), make_message(i, rnd, i * 0.010)) for i in range(n)]
    off, on = 0.150, 0.450
    hooks = [(off, lambda: (analytics.disconnect(), dashboard.disconnect())),
             (on, lambda: (analytics.reconnect(), dashboard.reconnect()))]
    marks = [0.100, 0.200, 0.300, 0.400, 0.450, 0.500, 0.560]
    now, taken = run_clock(topic, schedule, hooks, horizon=0.60, samples=marks)
    end = drain(topic, now)

    published_while_away = sum(1 for t, _ in schedule if off <= t < on)
    print(f"  published {n} messages over 0.60s; 'analytics' (durable) and 'live-dashboard'"
          f" (ephemeral) were away from t={off:.2f}s to t={on:.2f}s")
    print(f"  {published_while_away} messages were published during that window")
    print(f"  {'t (s)':>7}  {'warehouse':>10}  {'analytics':>10}  {'live-dashboard':>15}   backlog depth")
    for t, depths in taken:
        note = "  <- away" if off <= t < on else ""
        print(f"  {t:>7.3f}  {depths[0]:>10}  {depths[1]:>10}  {depths[2]:>15}{note}")
    print(f"  {'subscription':<16} {'durable':>8} {'stored':>7} {'redeliv':>8} {'acked':>6}"
          f" {'LOST':>5} {'peak backlog':>13}")
    for sub in topic.subscriptions:
        s = sub.stats
        print(f"  {sub.name:<16} {str(sub.durable):>8} {s.stored:>7} {s.redelivered:>8}"
              f" {s.acked:>6} {s.lost:>5} {s.peak_backlog:>13}")
    print(f"  drained at t={end:.3f}s. Durable accounting: {analytics.stats.acked} acked"
          f" + {analytics.stats.lost} lost = {n}. Ephemeral accounting:"
          f" {dashboard.stats.acked} acked + {dashboard.stats.lost} lost = {n}.")
    print(f"  'warehouse' never noticed: peak backlog {warehouse.stats.peak_backlog},"
          f" acked {warehouse.stats.acked}/{n} throughout.")


def section_amplification() -> None:
    print("\n== 5. AMPLIFICATION: what one publish costs, and what a filter saves ==")
    rnd = random.Random(SEED + 2)
    topic = Topic("orders")
    specs = [
        ("audit-archive", "#", None),
        ("search-index", "order.*.created", None),
        ("gdpr-export", "order.#", Filter({"region": [{"prefix": "eu-"}]})),
        ("fraud-review", "order.#", Filter({"amount_cents": [{"numeric": [">=", 50000]}]})),
        ("vip-concierge", "order.#", Filter({"tier": ["gold"],
                                             "amount_cents": [{"numeric": [">=", 50000]}]})),
    ]
    for name, pattern, filt in specs:
        topic.subscribe(Subscription(name, pattern, filt))

    n = 200
    msgs = [make_message(i, rnd, i * 0.001) for i in range(n)]
    for m in msgs:
        topic.publish(m)

    total_bytes = topic.published_bytes
    avg = total_bytes / n
    print(f"  published {n} messages, {total_bytes:,} bytes"
          f"  (avg {avg:.0f} B = {msgs[0].header_bytes} B envelope + ~{avg - msgs[0].header_bytes:.0f} B payload)")
    print(f"  {'subscription':<15} {'pattern':<16} {'subj-match':>10} {'passed':>7} {'select':>7}"
          f" {'stored B':>10}")
    subject_matched = 0
    subject_matched_bytes = 0
    for sub in topic.subscriptions:
        s = sub.stats
        matched = n - s.subject_miss
        subject_matched += matched
        subject_matched_bytes += sum(m.size for m in msgs if subject_matches(sub.pattern, m.subject))
        sel = 100.0 * s.stored / matched if matched else 0.0
        print(f"  {sub.name:<15} {sub.pattern:<16} {matched:>10} {s.stored:>7} {sel:>6.1f}%"
              f" {s.stored_bytes:>10,}")
    print(f"  broker-side filtering : {topic.fanout_writes:>5} deliveries"
          f"   {topic.fanout_bytes:>9,} B   amplification {topic.fanout_bytes / total_bytes:.2f}x")
    print(f"  consumer-side filtering: {subject_matched:>5} deliveries"
          f"   {subject_matched_bytes:>9,} B   amplification {subject_matched_bytes / total_bytes:.2f}x")
    wasted = subject_matched_bytes - topic.fanout_bytes
    print(f"  moving the filter to the broker saved {wasted:,} B"
          f" ({100 * wasted / subject_matched_bytes:.1f}% of delivered bytes)"
          f" and {subject_matched - topic.fanout_writes} deliveries")
    evals = sum(sub.filt.evaluations for sub in topic.subscriptions if sub.filt)
    print(f"  it cost the broker {evals:,} filter evaluations over"
          f" {topic.header_bytes_read:,} B of envelope"
          f" -- and {topic.payload_bytes_read} B of payload, because filters never touch the body")
    worst = min((s for s in topic.subscriptions if s.filt),
                key=lambda s: s.stats.stored / max(1, n - s.stats.subject_miss))
    kept = 100.0 * worst.stats.stored / (n - worst.stats.subject_miss)
    print(f"  selectivity matters: '{worst.name}' keeps {kept:.1f}% of what it subscribes to."
          f" Filtered at the consumer that is {100 - kept:.1f}% wasted network and CPU.")


def main() -> None:
    section_subjects()
    section_filters()
    section_fanout()
    section_isolation()
    section_amplification()


if __name__ == "__main__":
    main()
