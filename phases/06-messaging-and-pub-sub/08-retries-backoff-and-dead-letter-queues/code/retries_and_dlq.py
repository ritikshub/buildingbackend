#!/usr/bin/env python3
"""
Retries, backoff, dead-letter queues and poison messages - measured, not asserted.

Companion to docs/en.md (Phase 6, Lesson 08 - Retries, Backoff, Dead-Letter
Queues & Poison Messages). Six experiments on a virtual clock: classification
(transient vs permanent), five backoff strategies against a thundering herd,
retry budgets and a circuit breaker, delivery counting into a DLQ record,
poison-message head-of-line blocking, and a redrive whose safety depends
entirely on the dedup window of Lesson 06.

Backoff formulations are the standard ones: exponential base*2^(n-1), full
jitter random(0,b), equal jitter b/2+random(0,b/2), decorrelated jitter
min(cap, random(base, 3*prev)). Message identity follows RFC 4122 UUID
semantics: an opaque, stable, unique name for one unit of work.

Nothing sleeps and nothing is random between runs.
Standard library only:  python retries_and_dlq.py
"""

from __future__ import annotations

import heapq
import json
import random
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

SEED = 4711
BASE_TS = 1_700_000_000.0        # fixed epoch so timestamps never drift

# --- the fleet experiment (sections 2 and 3) --------------------------------
N_CLIENTS = 200                  # consumers holding a message for a sick dependency
INITIAL_SPREAD = 2.0             # they all fail together when it dies: a synchronised herd
RECOVER_AT = 45.0                # the dependency comes back at t=45s
CAP_RPS = 60                     # ...and can absorb 60 requests/second, no more
MAX_DELIVERY = 12                # attempts before the message is dead-lettered
BASE, CAP, MIN_DELAY = 2.0, 32.0, 0.5     # backoff base, ceiling and floor, seconds
FIXED_DELAY = 5.0
HORIZON = 400.0
FLEET_TIERS = [5.0, 30.0, 120.0]          # delay tiers a parked message walks down
BUDGET_RPS, BUDGET_BURST = 10.0, 10.0     # 10% of a 100 req/s consumer group
BREAKER_FAILS, BREAKER_COOLDOWN = 5, 5.0

# --- the ordered-partition experiment (section 5) ---------------------------
PROC_S = 0.02                    # 20 ms to process one message
PUBLISH_S = 0.005                # 5 ms to republish to a retry topic
PARTITION_LEN = 40
POISON_INDEX = 12
P_BASE, P_CAP = 1.0, 30.0        # the in-place retry backoff for the poison message
RETRY_TIERS = [5.0, 60.0, 600.0]  # retry-5s -> retry-1m -> retry-10m -> DLQ
WATCH_S = 300.0                  # how long we watch the halted partition


def fmt_ts(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


# ─── 1. Classification: the decision that comes before any retry ─────────────

TRANSIENT = {
    "conn_reset": "TCP connection reset by peer",
    "read_timeout": "read timeout after 2000 ms",
    "http_503": "503 Service Unavailable",
    "http_429": "429 Too Many Requests (Retry-After: 2)",
    "db_deadlock": "40P01 deadlock detected, transaction aborted",
    "http_502": "502 Bad Gateway",
}
PERMANENT = {
    "http_400": "400 Bad Request: field 'amount_cents' is null",
    "schema_invalid": "payload failed schema validation at $.customer.id",
    "http_403": "403 Forbidden: key lacks scope charges:write",
    "http_422": "422 Unprocessable Entity: currency 'XYZ' not supported",
    "hard_decline": "issuer declined: do-not-honour (hard decline)",
}


def classify(code: str) -> str:
    """The single most important line in any consumer's error path."""
    return "transient" if code in TRANSIENT else "permanent"


@dataclass
class Msg:
    mid: str
    key: str
    idem: str
    amount_cents: int
    offset: int
    heals_after: int = 0            # transient failures stop after this many attempts
    fatal: str | None = None        # a permanent error code, or None
    flaky: str = "http_503"
    delivery_count: int = 0
    errors: list[str] = field(default_factory=list)


def make_workload(n: int, seed_off: int = 0) -> list[Msg]:
    rnd = random.Random(SEED + seed_off)
    perm_codes, tran_codes = sorted(PERMANENT), sorted(TRANSIENT)
    out = []
    for i in range(n):
        r = rnd.random()
        heals, fatal = 0, None
        if r < 0.70:
            pass                                    # clean: succeeds on the first try
        elif r < 0.88:
            heals = rnd.randint(1, 3)               # transient: heals on its own
        else:
            fatal = perm_codes[rnd.randrange(len(perm_codes))]
        out.append(Msg(
            mid="%032x" % rnd.getrandbits(128),
            key="order-%05d" % rnd.randrange(20_000),
            idem="%032x" % rnd.getrandbits(128),
            amount_cents=rnd.randrange(500, 25_000),
            offset=182_400 + i,
            heals_after=heals, fatal=fatal,
            flaky=tran_codes[rnd.randrange(len(tran_codes))],
        ))
    return out


def consume(msgs: list[Msg], policy: str, max_attempts: int = 5) -> dict:
    """policy: retry_all | classify | never.  Returns counters and the dead letters."""
    st = {"attempts": 0, "wasted": 0, "ok": 0, "dlq": 0, "recoverable_lost": 0}
    dead: list[Msg] = []
    for m in msgs:
        n = 0
        while True:
            n += 1
            st["attempts"] += 1
            if m.fatal:
                err = m.fatal
            elif n <= m.heals_after:
                err = m.flaky
            else:
                st["ok"] += 1
                break
            kind = classify(err)
            if kind == "permanent" and n > 1:
                st["wasted"] += 1                   # an attempt that could never have worked
            if policy == "retry_all":
                retry = n < max_attempts
            elif policy == "classify":
                retry = kind == "transient" and n < max_attempts
            else:
                retry = False
            if not retry:
                st["dlq"] += 1
                if kind == "transient":
                    st["recoverable_lost"] += 1     # one more retry would have saved it
                m.delivery_count, m.errors = n, [err] * n
                dead.append(m)
                break
    st["dead"] = dead
    return st


# ─── 2. Backoff strategies ───────────────────────────────────────────────────

def s_fixed(rnd, attempt, prev):
    return FIXED_DELAY


def s_exponential(rnd, attempt, prev):
    return min(CAP, BASE * 2 ** (attempt - 1))


def s_full_jitter(rnd, attempt, prev):
    return rnd.uniform(0.0, min(CAP, BASE * 2 ** (attempt - 1)))


def s_equal_jitter(rnd, attempt, prev):
    b = min(CAP, BASE * 2 ** (attempt - 1))
    return b / 2 + rnd.uniform(0.0, b / 2)


def s_decorrelated(rnd, attempt, prev):
    return min(CAP, rnd.uniform(BASE, max(BASE, prev * 3.0)))


STRATEGIES = [
    ("fixed 5s", s_fixed, 10),
    ("exponential", s_exponential, 20),
    ("+ full jitter", s_full_jitter, 30),
    ("+ equal jitter", s_equal_jitter, 40),
    ("+ decorrelated", s_decorrelated, 50),
]


class Breaker:
    """closed -> (N consecutive failures) -> open -> (cooldown) -> half-open -> closed."""

    def __init__(self) -> None:
        self.state, self.fails, self.open_until, self.probes = "closed", 0, 0.0, 0

    def allow(self, now: float) -> bool:
        if self.state == "open":
            if now < self.open_until:
                return False
            self.state = "half-open"                 # the cooldown expired: one probe may pass
        if self.state == "half-open":
            self.probes += 1
        return True

    def record(self, now: float, ok: bool) -> None:
        if ok:
            self.state, self.fails = "closed", 0
        elif self.state == "half-open":
            self.state, self.open_until = "open", now + BREAKER_COOLDOWN
        else:
            self.fails += 1
            if self.fails >= BREAKER_FAILS:
                self.state, self.open_until, self.fails = "open", now + BREAKER_COOLDOWN, 0


def run_fleet(delay_fn, seed_off: int, budget: bool = False, breaker: bool = False) -> dict:
    """N_CLIENTS messages retrying against a dependency that is down, then capacity-limited.

    Requests are served in time order. One fails if the dependency is still down,
    or if more than CAP_RPS requests reached it in the preceding second -- the
    overload cliff that turns a retry storm into a sustained outage.

    Buckets count RETRIES only (attempt > 0): the first delivery is identical for
    every strategy, so including it would hide the thing being measured.
    """
    arrivals = random.Random(SEED + 900)             # identical arrivals for every strategy
    rnd = random.Random(SEED + seed_off)
    pending: list[tuple] = []
    for c in range(N_CLIENTS):
        heapq.heappush(pending, (arrivals.uniform(0.0, INITIAL_SPREAD), c, 0, 0.0, 0, 0))

    window: deque[float] = deque()
    per_bucket: dict[int, int] = defaultdict(int)
    calls = outage_calls = ok = dlq = fastfail = park_events = 0
    tokens, last_refill, drain = BUDGET_BURST, 0.0, 0.0
    br = Breaker() if breaker else None

    while pending:
        t, c, attempt, prev, ff, parks = heapq.heappop(pending)
        if t > HORIZON:
            dlq += 1
            drain = max(drain, HORIZON)
            continue
        if br is not None and not br.allow(t):       # fail fast: no downstream call at all
            fastfail += 1
            if ff >= 60:
                dlq += 1
                drain = max(drain, t)
                continue
            wake = br.open_until + rnd.uniform(0.0, BREAKER_COOLDOWN)
            heapq.heappush(pending, (max(wake, t + MIN_DELAY), c, attempt, prev, ff + 1, parks))
            continue
        if budget and attempt > 0:                   # a retry must buy a token
            tokens = min(BUDGET_BURST, tokens + (t - last_refill) * BUDGET_RPS)
            last_refill = t
            if tokens < 1.0:
                park_events += 1                     # deferred to a retry topic, not discarded
                if parks >= len(FLEET_TIERS):
                    dlq += 1
                    drain = max(drain, t)
                    continue
                tier = FLEET_TIERS[parks]
                heapq.heappush(pending, (t + tier + rnd.uniform(0.0, tier * 0.25),
                                         c, attempt, prev, ff, parks + 1))
                continue
            tokens -= 1.0

        calls += 1
        if attempt > 0:
            per_bucket[int(t)] += 1
        if t < RECOVER_AT:
            outage_calls += 1
        window.append(t)
        while window and window[0] <= t - 1.0:
            window.popleft()
        success = t >= RECOVER_AT and len(window) <= CAP_RPS
        if br is not None:
            br.record(t, success)
        if success:
            ok += 1
            drain = max(drain, t)
            continue
        nxt = attempt + 1
        if nxt >= MAX_DELIVERY:
            dlq += 1
            drain = max(drain, t)
            continue
        d = max(MIN_DELAY, delay_fn(rnd, nxt, prev))
        heapq.heappush(pending, (t + d, c, nxt, d, ff, parks))

    rec_peak = max((v for s, v in per_bucket.items() if s >= RECOVER_AT), default=0)
    return {"calls": calls, "outage": outage_calls, "peak": max(per_bucket.values(), default=0),
            "rec_peak": rec_peak, "ok": ok, "dlq": dlq, "parks": park_events,
            "fastfail": fastfail, "drain": drain, "buckets": dict(per_bucket),
            "probes": br.probes if br else 0}


DENSITY = " .:-=+*#%@"


def sparkline(buckets: dict[int, int], width: int, span: int, top: int) -> str:
    """One character per `width` seconds; density encodes retries in that window."""
    cells = []
    for b in range(0, span, width):
        c = sum(buckets.get(s, 0) for s in range(b, b + width))
        cells.append(DENSITY[0] if c == 0 else DENSITY[max(1, round(9 * c / top))])
    return "".join(cells)


# ─── 4. Delivery counting and the dead-letter record ─────────────────────────

def dlq_record(m: Msg, first_seen: float, now: float, reason: str) -> dict:
    return {
        "dlq_reason": reason,
        "message_id": m.mid,
        "idempotency_key": m.idem,
        "partition_key": m.key,
        "original_topic": "orders.payments.v2",
        "original_partition": 3,
        "original_offset": m.offset,
        "consumer_group": "payments-worker",
        "consumer_version": "2.14.3",
        "delivery_count": m.delivery_count,
        "max_delivery_count": MAX_DELIVERY,
        "first_seen_at": fmt_ts(first_seen),
        "dead_lettered_at": fmt_ts(now),
        "seconds_in_flight": round(now - first_seen, 1),
        "failure_class": classify(m.errors[-1]),
        "last_error_code": m.errors[-1],
        "last_error": PERMANENT.get(m.errors[-1]) or TRANSIENT.get(m.errors[-1]),
        "error_codes_seen": sorted(set(m.errors)),
        "stack_digest": "sha256:9f2c41ab",
        "payload": {"order_id": m.key, "amount_cents": m.amount_cents, "currency": "EUR"},
    }


# ─── 5. Head-of-line blocking in an ordered partition ────────────────────────

def partition_run(mode: str) -> dict:
    """One ordered partition, one poison message at POISON_INDEX.

    halt    -- the broker redelivers forever; nothing behind the poison ever moves
    inplace -- retry in place until max delivery, then DLQ, then carry on
    parked  -- republish to a retry topic on the first failure; never block
    """
    now, done, out_of_order, attempts = 0.0, 0, 0, 0
    state, blocked = "pending", 0
    for i in range(PARTITION_LEN):
        if i == POISON_INDEX:
            if mode == "parked":
                now += PUBLISH_S
                attempts, state = 1, "parked to retry-5s"
                continue
            while True:
                attempts += 1
                now += PROC_S
                if mode == "inplace" and attempts >= MAX_DELIVERY:
                    state = "dead-lettered"
                    break
                if mode == "halt" and now >= WATCH_S:
                    state = "still retrying"
                    break
                now += min(P_CAP, P_BASE * 2 ** (attempts - 1))
            if mode == "halt":                       # the partition never gets past this offset
                now, blocked = WATCH_S, PARTITION_LEN - i - 1
                break
            continue
        now += PROC_S
        done += 1
        if state.startswith("parked"):
            out_of_order += 1
    return {"elapsed": now, "done": done, "attempts": attempts, "state": state,
            "blocked": blocked, "out_of_order": out_of_order,
            "throughput": done / now if now else 0.0}


# ─── 6. Redrive: replaying the DLQ into a consumer that must be idempotent ───

def redrive(records: list[dict], dedup_ttl_h: float, sat_in_dlq_h: float) -> dict:
    """Replay DLQ records. Keys older than the dedup TTL no longer suppress anything."""
    still_deduped = dedup_ttl_h > sat_in_dlq_h
    ok = suppressed = double = cents = 0
    for r in records:
        if not r["_already_applied"]:
            ok += 1
        elif still_deduped:
            suppressed += 1
        else:
            double += 1
            cents += r["payload"]["amount_cents"]
    return {"replayed": len(records), "processed": ok, "suppressed": suppressed,
            "double": double, "cents": cents}


# ─── main ────────────────────────────────────────────────────────────────────

def main() -> None:
    print("== 1. CLASSIFY BEFORE YOU RETRY ==")
    print("  error code        class      action    why")
    rows = ["http_503", "http_429", "read_timeout", "db_deadlock",
            "http_400", "schema_invalid", "http_403", "hard_decline"]
    why = {"transient": ("retry", "the world may be different in 2 seconds"),
           "permanent": ("DLQ now", "no amount of waiting changes the answer")}
    for code in rows:
        k = classify(code)
        print(f"  {code:<16}  {k:<9}  {why[k][0]:<8}  {why[k][1]}")

    probe = make_workload(600)
    n_perm = sum(1 for m in probe if m.fatal)
    n_tran = sum(1 for m in probe if m.heals_after)
    print(f"\n  workload: {len(probe):,} messages  ->  {len(probe) - n_perm - n_tran:,} clean,"
          f"  {n_tran:,} transient (heal in 1-3 attempts),  {n_perm:,} permanently broken")
    print(f"  {'policy':<20}{'attempts':>9}{'wasted':>8}{'succeeded':>11}"
          f"{'dead-lettered':>15}{'recoverable lost':>18}")
    res = {}
    for pol, label in (("retry_all", "retry everything"), ("classify", "classify first"),
                       ("never", "never retry")):
        st = consume(make_workload(600), pol)
        res[pol] = st
        print(f"  {label:<20}{st['attempts']:>9,}{st['wasted']:>8,}{st['ok']:>11,}"
              f"{st['dlq']:>15,}{st['recoverable_lost']:>18,}")
    saved = res["retry_all"]["attempts"] - res["classify"]["attempts"]
    print(f"  classifying first saves {saved:,} attempts"
          f" ({100 * saved / res['retry_all']['attempts']:.1f}% of all work) and costs nothing:"
          f" {res['classify']['ok']:,} messages succeed either way")
    print(f"  never retrying is the mirror-image mistake:"
          f" {res['never']['recoverable_lost']:,} messages dead-lettered that one retry saves")

    print("\n== 2. BACKOFF AND JITTER: 200 clients, a dependency that dies at t=0 ==")
    print(f"  down until t={RECOVER_AT:.0f}s, then serves {CAP_RPS} req/s;"
          f" a second carrying more than that is shed entirely")
    print(f"  base {BASE:.0f}s  cap {CAP:.0f}s  floor {MIN_DELAY:.1f}s"
          f"  max delivery {MAX_DELIVERY}  horizon {HORIZON:.0f}s")
    print(f"  {'strategy':<16}{'calls':>7}{'in outage':>11}{'peak/s':>8}{'peak/s @45s+':>14}"
          f"{'ok':>6}{'DLQ':>6}{'drain':>9}")
    fleet = {}
    for name, fn, off in STRATEGIES:
        r = run_fleet(fn, off)
        fleet[name] = r
        print(f"  {name:<16}{r['calls']:>7,}{r['outage']:>11,}{r['peak']:>8,}"
              f"{r['rec_peak']:>14,}{r['ok']:>6,}{r['dlq']:>6,}{r['drain']:>8.1f}s")

    top = max(max(r["buckets"].get(s, 0) + r["buckets"].get(s + 1, 0) for s in range(0, 160, 2))
              for r in fleet.values())
    print(f"\n  retries per 2s bucket, t=0 to t=160s   scale '{DENSITY.strip()}'"
          f"   blank = 0, @ = {top}")
    print(f"  {'':<16}0s        20        40        60        80        100"
          f"       120       140")
    for name, _, _ in STRATEGIES:
        print(f"  {name:<16}{sparkline(fleet[name]['buckets'], 2, 160, top)}|")
    f_pk, j_pk = fleet["exponential"]["rec_peak"], fleet["+ full jitter"]["rec_peak"]
    print(f"  the dependency recovers 22 characters in, and that is the column that matters:")
    print(f"  peak retries in one second after recovery - exponential {f_pk}/s vs full jitter"
          f" {j_pk}/s, {f_pk / j_pk:.0f}x lower.")
    print(f"  Un-jittered strategies hit the {CAP_RPS} req/s cliff on every wave, so a recovered"
          f" dependency is knocked")
    print(f"  straight back over; the jittered ones arrive under it and get through.")

    print("\n== 3. RETRY BUDGETS AND CIRCUIT BREAKERS (all on full jitter) ==")
    print(f"  budget: retries capped at {BUDGET_RPS:.0f}/s (10% of a 100 req/s group);"
          f" denied retries park to {'/'.join(f'{t:.0f}s' for t in FLEET_TIERS)}")
    print(f"  breaker: {BREAKER_FAILS} consecutive failures -> open {BREAKER_COOLDOWN:.0f}s"
          f" -> half-open probe -> closed")
    print(f"  {'protection':<20}{'calls':>7}{'in outage':>11}{'peak/s':>8}{'peak/s @45s+':>14}"
          f"{'ok':>6}{'parks':>7}{'drain':>9}")
    prot = {}
    for label, kw, off in (("none", {}, 30), ("retry budget", {"budget": True}, 31),
                           ("circuit breaker", {"breaker": True}, 32),
                           ("budget + breaker", {"budget": True, "breaker": True}, 33)):
        r = run_fleet(s_full_jitter, off, **kw)
        prot[label] = r
        print(f"  {label:<20}{r['calls']:>7,}{r['outage']:>11,}{r['peak']:>8,}"
              f"{r['rec_peak']:>14,}{r['ok']:>6,}{r['parks']:>7,}{r['drain']:>8.1f}s")
    b0, bb = prot["none"]["outage"], prot["circuit breaker"]["outage"]
    print(f"  load delivered to the dying dependency: {b0:,} calls unprotected  ->  {bb:,}"
          f" with a breaker ({b0 / max(1, bb):.0f}x less)")
    print(f"  the breaker rejected {prot['circuit breaker']['fastfail']:,} attempts locally and"
          f" spent {prot['circuit breaker']['probes']:,} half-open probes finding out when to"
          f" close again")

    print("\n== 4. DELIVERY COUNT -> DLQ: what a dead-letter record must carry ==")
    outage_batch = make_workload(120, seed_off=5)
    for m in outage_batch:                        # a long payment-API outage exhausted them
        m.delivery_count = MAX_DELIVERY
        m.errors = ["http_503"] * 9 + ["read_timeout"] * 2 + ["http_502"]
    # the retry window is the sum of the backoffs the policy actually waited out
    window_s = sum(min(CAP, BASE * 2 ** (n - 1)) for n in range(1, MAX_DELIVERY))
    dlq_records = [dlq_record(m, BASE_TS, BASE_TS + window_s, "max_delivery_count_exceeded")
                   for m in outage_batch]
    print(f"  {len(dlq_records):,} messages exhausted delivery count {MAX_DELIVERY} during a"
          f" payment-API outage.")
    print(f"  {MAX_DELIVERY} deliveries at base {BASE:.0f}s / cap {CAP:.0f}s ="
          f" {window_s:.0f}s of retry window. One record, in full:")
    for line in json.dumps(dlq_records[0], indent=2).splitlines():
        print("    " + line)
    print("  every field answers a triage question: what, from where, how many times,"
          " since when,")
    print("  why, and - via idempotency_key - whether it is safe to replay")

    print("\n== 5. POISON MESSAGE AND HEAD-OF-LINE BLOCKING ==")
    print(f"  one ordered partition, {PARTITION_LEN} messages for key order-9182,"
          f" #{POISON_INDEX} is poison, {PROC_S * 1000:.0f} ms each")
    print(f"  {'strategy':<32}{'elapsed':>9}{'done':>6}{'blocked':>9}{'msg/s':>8}"
          f"{'attempts':>10}{'out of order':>14}")
    pr = {}
    for label, mode in (("halt: retry in place forever", "halt"),
                        ("in place, max delivery -> DLQ", "inplace"),
                        ("park to retry topic on 1st fail", "parked")):
        p = partition_run(mode)
        pr[mode] = p
        print(f"  {label:<32}{p['elapsed']:>8.1f}s{p['done']:>6}{p['blocked']:>9}"
              f"{p['throughput']:>8.2f}{p['attempts']:>10}{p['out_of_order']:>14}")
    base_tp = 1 / PROC_S
    print(f"  poison message ends: " + ",  ".join(f"{m} = {pr[m]['state']}"
                                                  for m in ("halt", "inplace", "parked")))
    print(f"  a clean partition drains in {PARTITION_LEN * PROC_S:.2f}s at {base_tp:.0f} msg/s."
          f" One malformed message costs"
          f" {base_tp / pr['halt']['throughput']:,.0f}x throughput if you never")
    print(f"  give up, and {base_tp / pr['inplace']['throughput']:,.0f}x if you give up after"
          f" {MAX_DELIVERY} deliveries. Parking costs {base_tp / pr['parked']['throughput']:.2f}x"
          f" throughput - it is")
    print(f"  effectively free - and the bill is paid in ordering instead:"
          f" {pr['parked']['out_of_order']} messages for key order-9182 overtook")
    print(f"  the parked one. The parked copy walks"
          f" {'/'.join(f'{t:.0f}s' for t in RETRY_TIERS)} = {sum(RETRY_TIERS):.0f}s of tiers and"
          f" then DLQs, none of it on the main partition.")

    print("\n== 6. REDRIVE: safe only if the dedup window outlived the DLQ ==")
    rnd = random.Random(SEED + 77)
    for r in dlq_records:
        r["_already_applied"] = rnd.random() < 0.28   # charge landed, the ack did not
    applied = sum(1 for r in dlq_records if r["_already_applied"])
    sat = 6.2
    print(f"  the payment API is healthy again. Redriving {len(dlq_records):,} messages that sat"
          f" {sat} h in the DLQ.")
    print(f"  {applied} of them had already moved money before the ack failed - they are"
          f" duplicates by construction.")
    print(f"  {'dedup TTL':<12}{'replayed':>10}{'processed':>11}{'suppressed':>12}"
          f"{'DOUBLE CHARGED':>16}{'value':>16}")
    for ttl in (24.0, 1.0):
        rr = redrive(dlq_records, ttl, sat)
        print(f"  {ttl:>6.0f} h{'':<5}{rr['replayed']:>10,}{rr['processed']:>11,}"
              f"{rr['suppressed']:>12,}{rr['double']:>16,}"
              f"{'EUR ' + format(rr['cents'] / 100, ',.2f'):>16}")
    print(f"  same code, same messages, same redrive button. The only difference is whether the"
          f" idempotency")
    print(f"  keys were still in the dedup store after {sat} h. Dedup TTL > max time in DLQ is"
          f" not a tuning")
    print(f"  detail; it is the difference between a clean replay and charging customers twice.")

    print("\n== 7. SUMMARY: same 200 messages, seven ways to attempt them ==")
    print(f"  {'strategy':<30}{'calls':>7}{'outage load':>13}{'peak/s @45s+':>14}"
          f"{'DLQ':>6}{'parks':>7}{'ok':>6}{'drain':>9}")
    for name, _, _ in STRATEGIES:
        r = fleet[name]
        print(f"  {name:<30}{r['calls']:>7,}{r['outage']:>13,}{r['rec_peak']:>14,}"
              f"{r['dlq']:>6,}{r['parks']:>7,}{r['ok']:>6,}{r['drain']:>8.1f}s")
    for label in ("retry budget", "circuit breaker", "budget + breaker"):
        r = prot[label]
        print(f"  {'full jitter + ' + label:<30}{r['calls']:>7,}{r['outage']:>13,}"
              f"{r['rec_peak']:>14,}{r['dlq']:>6,}{r['parks']:>7,}{r['ok']:>6,}"
              f"{r['drain']:>8.1f}s")
    print("  every row delivered the same work. What changed is how much damage the attempt did")
    print("  to the dependency, how many messages survived, and how long the queue took to drain.")


if __name__ == "__main__":
    main()
