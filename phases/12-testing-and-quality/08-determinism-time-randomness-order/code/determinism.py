#!/usr/bin/env python3
"""
Determinism measured rather than asserted: the hidden inputs a backend test
reads without ever setting, why a frozen clock cannot test a timeout, the
timezone/DST/leap-year matrix a local-time renewal implementation gets wrong,
a shared seed under parallel workers, UUID ordering inversions, hash-seed and
ORDER BY-less iteration instability, the detection power of a shuffled suite,
the float tolerance that is really a policy about money, and the scheduler.

Companion to docs/en.md (Phase 12, Lesson 08). Standard library only, every RNG
seeded from SEED below, no wall-clock value is ever printed, self-terminating in
well under 30 seconds. Sources: RFC 9562 (Universally Unique IDentifiers), 2024;
RFC 3339 (Date and Time on the Internet: Timestamps), 2002; IEEE 754-2019;
PEP 456 (Secure and Interchangeable Hash Algorithm), 2013; Directive 2000/84/EC
(EU summer-time arrangements); the SQLite "SELECT ... ORDER BY" documentation.

Run:  python3 determinism.py
"""

from __future__ import annotations

import datetime as dt
import decimal
import itertools
import math
import os
import random
import sqlite3
import subprocess
import sys
from decimal import Decimal
from typing import Callable, Iterator

SEED = 20260718
UTC = dt.timezone.utc


def banner(n: int, title: str) -> None:
    print(f"\n== {n} · {title} ==")


def note(text: str) -> None:
    for line in text.strip("\n").split("\n"):
        print(f"  {line}")


# ══ 1 ═══════════════════════════════════════════════════════════════════════════
# Determinism is a property of INPUTS, not of code: a function is deterministic
# when its result is a function of the arguments you passed it. Everything else
# it reads is a hidden input — an argument the test did not set and cannot see.


class Ambient:
    """One "world" a process might find itself in. Nothing here is set by a test;
    every accessor is counted, so the hidden inputs can be tallied rather than
    guessed at."""

    def __init__(self, wall: dt.datetime, env: dict[str, str], rng_seed: int,
                 tag_order: tuple[str, ...], counter_start: int) -> None:
        self.wall, self.env, self.tag_order = wall, env, tag_order
        self.rng, self.counter = random.Random(rng_seed), counter_start
        self.reads: dict[str, int] = {}

    def _hit(self, name: str) -> None:
        self.reads[name] = self.reads.get(name, 0) + 1

    def now(self) -> dt.datetime:
        self._hit("clock"); return self.wall

    def getenv(self, key: str, default: str) -> str:
        self._hit("environment"); return self.env.get(key, default)

    def random_id(self) -> str:
        self._hit("RNG"); return f"{self.rng.getrandbits(32):08x}"

    def tags(self) -> tuple[str, ...]:
        self._hit("iteration order"); return self.tag_order

    def next_seq(self) -> int:
        self._hit("process-global counter"); self.counter += 1; return self.counter


def price_order_hidden(amb: Ambient, cents: int) -> str:
    """The function everybody writes. Five of its inputs are invisible."""
    now = amb.now()
    promo = Decimal(amb.getenv("PROMO_RATE", "0.00"))
    total = (Decimal(cents) * (Decimal(1) - promo)).quantize(Decimal("1"))
    return (f"id={amb.random_id()} seq={amb.next_seq()} "
            f"day={now.date().isoformat()} total={int(total)} tags={','.join(amb.tags())}")


def price_order_injected(*, now: dt.datetime, promo: Decimal, order_id: str,
                         seq: int, tags: tuple[str, ...], cents: int) -> str:
    """The same arithmetic with every hidden input promoted to an argument."""
    total = (Decimal(cents) * (Decimal(1) - promo)).quantize(Decimal("1"))
    return (f"id={order_id} seq={seq} day={now.date().isoformat()} "
            f"total={int(total)} tags={','.join(sorted(tags))}")


def worlds() -> list[Ambient]:
    """Six ordinary machines: two times of day, two promo settings, two hash seeds."""
    base = dt.datetime(2026, 7, 18, 21, 40, tzinfo=UTC)
    return [
        Ambient(base, {}, 1, ("beta", "alpha", "gamma"), 0),
        Ambient(base + dt.timedelta(hours=3), {}, 2, ("alpha", "gamma", "beta"), 41),
        Ambient(base, {"PROMO_RATE": "0.10"}, 3, ("gamma", "beta", "alpha"), 7),
        Ambient(base + dt.timedelta(days=1), {}, 4, ("alpha", "beta", "gamma"), 900),
        Ambient(base, {}, 5, ("gamma", "alpha", "beta"), 12),
        Ambient(base + dt.timedelta(hours=3), {"PROMO_RATE": "0.10"}, 6,
                ("beta", "gamma", "alpha"), 3),
    ]


def section1() -> None:
    banner(1, "HIDDEN INPUTS: THE ARGUMENTS YOUR TEST NEVER PASSED")
    ws = worlds()
    hidden = [price_order_hidden(w, 1999) for w in ws]
    inj = [price_order_injected(now=dt.datetime(2026, 7, 18, 21, 40, tzinfo=UTC),
                                promo=Decimal("0.00"), order_id="0000002a", seq=1,
                                tags=("alpha", "beta", "gamma"), cents=1999)
           for _ in ws]

    print("  one 6-line pricing function, run in 6 ordinary machine states")
    print("  (different times of day, PROMO_RATE set or not, different hash seeds)")
    print()
    print("    hidden input           reads/call   what it makes non-reproducible")
    rows = [("clock", "the date rolls over at midnight, in SOME timezone"),
            ("environment", "a variable set on the runner and not on your laptop"),
            ("RNG", "a fresh value per call; assertions cannot name it"),
            ("iteration order", "set iteration order, which the hash seed decides"),
            ("process-global counter", "depends on how many tests ran before this one")]
    for name, why in rows:
        print(f"    {name:<22} {ws[0].reads.get(name, 0):>6}       {why}")
    print(f"    {'TOTAL':<22} {sum(ws[0].reads.values()):>6}")
    print()
    print(f"  distinct results across the 6 worlds, hidden inputs:   {len(set(hidden))} of {len(ws)}")
    print(f"  distinct results across the 6 worlds, inputs injected: {len(set(inj))} of {len(ws)}")
    note("""
example of the same call in two of those worlds:
  world 1: %s
  world 2: %s
determinism is not a property of the code. It is a property of how much of the
world the code is allowed to read. Injection did not make the function correct;
it made the output a function of the arguments, which is the only thing an
assertion can talk about.
""" % (hidden[0], hidden[1]))


# ══ 2 ═══════════════════════════════════════════════════════════════════════════
# The clock. A frozen clock answers "what time is it" with a constant, so any
# behaviour that depends on time PASSING inside one call is unreachable under it.


class Clock:
    """The port: now() and sleep(). That is the whole abstraction, and it is the
    only thing the code under test is allowed to know about time."""

    def now(self) -> float:
        return self.t                                            # type: ignore[attr-defined]

    def sleep(self, seconds: float) -> None:
        raise NotImplementedError


class RealClock(Clock):
    """time.monotonic() + time.sleep(). The waits are ACCOUNTED here, never paid,
    so the program keeps its runtime budget; the bill is the point, not the nap."""

    def __init__(self) -> None:
        self.t = self.slept = 0.0

    def sleep(self, seconds: float) -> None:
        self.t += seconds
        self.slept += seconds


class FrozenClock(Clock):
    """freezegun / time-machine with no tick: now() is a constant. Re-freezing
    between calls is allowed; advancing DURING a call is not possible."""

    def __init__(self, t: float = 1_000_000.0) -> None:
        self.t = t

    def sleep(self, seconds: float) -> None:
        return                      # the wait is swallowed; the clock does not move


class ControllableClock(Clock):
    """The one you want: the test owns the time axis and moves it explicitly."""

    def __init__(self, t: float = 1_000_000.0) -> None:
        self.t = t

    def sleep(self, seconds: float) -> None:
        self.t += seconds

    advance = sleep


class TtlCache:
    """The system under test. It asks the clock; it does not read one."""

    def __init__(self, clock: Clock, ttl: float) -> None:
        self.clock, self.ttl, self.store = clock, ttl, {}

    def put(self, k: str, v: str) -> None:
        self.store[k] = (v, self.clock.now())

    def get(self, k: str) -> str | None:
        hit = self.store.get(k)
        if hit is None:
            return None
        v, at = hit
        return None if self.clock.now() - at >= self.ttl else v


def retry_with_backoff(clock: Clock, attempts: int, base: float) -> list[float]:
    """The offset of each attempt. Time must pass INSIDE this one call."""
    start, seen = clock.now(), []
    for i in range(attempts):
        seen.append(round(clock.now() - start, 3))
        if i < attempts - 1:
            clock.sleep(base * (2 ** i))
    return seen


def wait_for(clock: Clock, ready_at: float, timeout: float,
             interval: float) -> tuple[bool, float]:
    """Poll until a deadline. Returns (ready, seconds the clock actually moved).
    A frozen clock returns (False, 0.0) — it never reached the deadline, it
    simply ran out of iterations, which proves nothing about the timeout."""
    start = clock.now()
    deadline = start + timeout
    for _ in range(10_000):
        if clock.now() >= ready_at:
            return True, clock.now() - start
        if clock.now() >= deadline:
            return False, clock.now() - start
        clock.sleep(interval)
    return False, clock.now() - start


def section2() -> None:
    banner(2, "THE CLOCK: FREEZING IS NOT CONTROLLING")
    ttl = 300.0
    behaviours = ["B1 fresh key is a hit", "B2 hit 1 s before expiry",
                  "B3 miss exactly AT the ttl boundary", "B4 miss 1 s after expiry",
                  "B5 retry backoff emits 0/1/3/7 s", "B6 wait_for times out after 30 s"]

    def exercise(make: Callable[[], Clock],
                 jump: Callable[[Clock, float], None]) -> list[str]:
        out = []
        c = make()
        cache = TtlCache(c, ttl)
        cache.put("k", "v")
        out.append("pass" if cache.get("k") == "v" else "FAIL")
        for delta, want in ((ttl - 1, "v"), (ttl, None), (ttl + 1, None)):
            c2 = make()
            cache2 = TtlCache(c2, ttl)
            cache2.put("k", "v")
            jump(c2, delta)          # re-freezing at another instant is allowed
            out.append("pass" if cache2.get("k") == want else "FAIL")
        c3 = make()
        out.append("pass" if retry_with_backoff(c3, 4, 1.0) == [0.0, 1.0, 3.0, 7.0]
                   else "unreachable")
        c4 = make()
        ready, moved = wait_for(c4, ready_at=c4.now() + 10_000, timeout=30.0,
                                interval=0.5)
        out.append("pass" if ready is False and moved >= 30.0 else "unreachable")
        return out

    real = exercise(RealClock, lambda c, d: c.sleep(d))
    frozen = exercise(FrozenClock, lambda c, d: setattr(c, "t", c.t + d))
    ctrl = exercise(ControllableClock, lambda c, d: c.advance(d))

    # the real clock's bill: every wait actually paid, in seconds
    paid = (ttl - 1) + ttl + (ttl + 1) + (1 + 2 + 4) + 30
    print("  a 300 s TTL cache + a 4-attempt backoff + a 30 s timeout, 6 behaviours")
    print()
    print(f"    {'behaviour':<38}{'real clock':<13}{'frozen':<13}{'controllable'}")
    for i, b in enumerate(behaviours):
        print(f"    {b:<38}{real[i]:<13}{frozen[i]:<13}{ctrl[i]}")
    print()
    reach = {}
    for label, res, cost in (("real clock (actually sleeps)", real, paid),
                             ("frozen (freezegun, no tick)", frozen, 0.0),
                             ("controllable (test owns time)", ctrl, 0.0)):
        ok = sum(1 for r in res if r == "pass")
        reach[label.split()[0]] = ok
        print(f"    {label:<38}{ok}/6 reachable    wall cost {cost:>6.0f} s")
    note("""
the frozen clock reaches %d of 6. It can be RE-frozen at any instant, so every
"what is true at time T" assertion is available. What it cannot do is let time
pass INSIDE one call, so B5 (a backoff schedule read from within the retry loop)
and B6 (a timeout) are not slow under a frozen clock — they are unreachable.
wait_for() under it exhausts its iteration guard having advanced 0.0 s: it
returned False without reaching a deadline, which is the right answer for the
wrong reason. The real clock reaches 6/6 and bills %d s = %.1f min of sleeping
for six assertions; the controllable clock reaches 6/6 for 0 s.
""" % (reach["frozen"], paid, paid / 60))


# ══ 3 ═══════════════════════════════════════════════════════════════════════════
# Timezones, DST and leap years. Europe/Berlin is UTC+1 in winter and UTC+2 in
# summer; the EU transitions happen at a single instant, 01:00 UTC on the last
# Sunday of March and of October (Directive 2000/84/EC). Implemented by hand so
# the program needs no tzdata and the rule is visible rather than magic.


def last_sunday(year: int, month: int) -> dt.date:
    d = dt.date(year, month, 31 if month in (1, 3, 5, 7, 8, 10, 12) else 30)
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


def berlin_transitions(year: int) -> tuple[dt.datetime, dt.datetime]:
    """(CET->CEST, CEST->CET) as UTC instants."""
    start = dt.datetime.combine(last_sunday(year, 3), dt.time(1), tzinfo=UTC)
    end = dt.datetime.combine(last_sunday(year, 10), dt.time(1), tzinfo=UTC)
    return start, end


def berlin_offset(when: dt.datetime) -> dt.timedelta:
    start, end = berlin_transitions(when.year)
    return dt.timedelta(hours=2 if start <= when < end else 1)


def to_wall(when: dt.datetime) -> dt.datetime:
    """The naive wall-clock reading on a Berlin server. No offset attached."""
    return (when + berlin_offset(when)).replace(tzinfo=None)


def from_wall(wall: dt.datetime) -> list[dt.datetime]:
    """Every UTC instant that displays as this wall time, earliest first. 0 = the
    spring gap, 2 = the autumn fold, 1 = an ordinary hour. Picking [0] is what
    PEP 495's fold=0 means: when the hour repeats, take the first occurrence."""
    out = [c for h in (1, 2)
           if berlin_offset(c := wall.replace(tzinfo=UTC) - dt.timedelta(hours=h))
           == dt.timedelta(hours=h)]
    return sorted(out)


def add_month_clamped(d: dt.date, months: int) -> dt.date:
    """Calendar-month arithmetic with the clamp everyone forgets: Jan 31 + 1
    month is Feb 28, or Feb 29 in a leap year."""
    total = (d.year * 12 + d.month - 1) + months
    y, m = divmod(total, 12)
    m += 1
    last = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return dt.date(y, m, min(d.day, last))


def renew_utc(start: dt.datetime, months: int = 1) -> dt.datetime:
    """Correct: one calendar month on the UTC calendar, same UTC time of day."""
    return dt.datetime.combine(add_month_clamped(start.date(), months),
                               start.timetz())


def renew_wall(start: dt.datetime, months: int = 1) -> dt.datetime | None:
    """What datetime.now() + local dates gives you. Returns None when the
    resulting wall time does not exist (the hour the clocks skip)."""
    wall = to_wall(start)
    target = dt.datetime.combine(add_month_clamped(wall.date(), months), wall.time())
    cands = from_wall(target)
    return cands[0] if cands else None


def section3() -> None:
    banner(3, "TIMEZONES, DST AND LEAP YEARS: A YEAR OF DATE BOUNDARIES")
    print("  server in Europe/Berlin (UTC+1 winter, UTC+2 summer, EU transition rule)")
    print("  every hour of the year is a subscription start; renew it by one month")
    print()
    print(f"    {'year':<7}{'instants':<11}{'wrong':<9}{'':<7}{'1 h off':<10}"
          f"{'>=1 day off':<13}{'ambiguous'}")
    detail: dict[int, dict[str, int]] = {}
    samples: dict[str, dt.datetime] = {}
    by_hour: dict[int, int] = {}
    for year in (2024, 2025):
        c = dict.fromkeys(("total", "wrong", "hour_off", "day_off", "fold", "dom"), 0)
        cur, stop = dt.datetime(year, 1, 1, tzinfo=UTC), dt.datetime(year + 1, 1, 1, tzinfo=UTC)
        while cur < stop:
            c["total"] += 1
            good, bad = renew_utc(cur), renew_wall(cur)
            if bad is None or to_wall(bad).day != cur.day:      # the day-of-month property
                c["dom"] += 1
                if year == 2024:
                    by_hour[cur.hour] = by_hour.get(cur.hour, 0) + 1
            if bad is not None and len(from_wall(to_wall(bad))) == 2:
                c["fold"] += 1
            if bad != good:
                c["wrong"] += 1
                if abs((bad - good).total_seconds()) <= 3600:
                    c["hour_off"] += 1
                    samples.setdefault("renewal crosses a DST change", cur)
                else:
                    c["day_off"] += 1
                    samples.setdefault("the two calendars clamp differently", cur)
            cur += dt.timedelta(hours=1)
        detail[year] = c
        print(f"    {year:<7}{c['total']:<11}{c['wrong']:<9}{c['wrong']/c['total']:>6.1%} "
              f"{c['hour_off']:<10}{c['day_off']:<13}{c['fold']}")

    print("\n  the first instance of each failure mode, in full:")
    for label, start in samples.items():
        good, bad = renew_utc(start), renew_wall(start)
        drift = f"off by {(bad - good).total_seconds() / 3600:+.0f} h" if bad else "n/a"
        print(f"    {label:<44} start   {start:%Y-%m-%d %H:%MZ} = Berlin wall {to_wall(start):%Y-%m-%d %H:%M}")
        print(f"    {'':<44} utc-ok  {good:%Y-%m-%d %H:%MZ}   wall-based {bad:%Y-%m-%d %H:%MZ}  {drift}")

    print("\n  and the two wall-clock times that are not instants at all:")
    for wall, what in ((dt.datetime(2024, 3, 31, 2, 30), "spring forward"),
                       (dt.datetime(2024, 10, 27, 2, 30), "autumn back")):
        cands = from_wall(wall)
        shown = ", ".join(format(x, "%H:%MZ") for x in cands) or "nothing — this wall time never happens"
        print(f"    Berlin {wall:%Y-%m-%d %H:%M} ({what:<14}) -> {len(cands)} UTC instant(s): {shown}")

    print("\n  test_renewal_lands_on_the_same_day_of_month(), run at each hour of the year:")
    for year in (2024, 2025):
        c = detail[year]
        print(f"    {year}: fails at {c['dom']:>4} of {c['total']} hours ({c['dom']/c['total']:.1%})")
    late = by_hour.get(22, 0) + by_hour.get(23, 0)
    fails = {y: detail[y]["dom"] for y in detail}
    print(f"    2024 by UTC hour: 23:00 fails {by_hour.get(23,0)}x, 22:00 fails "
          f"{by_hour.get(22,0)}x, all 22 other hours {fails[2024]-late}x combined")
    feb29 = renew_utc(dt.datetime(2024, 2, 29, 9, tzinfo=UTC), 12)
    note("""
a monthly-renewal test written against datetime.now() is not one test. It is
%d different tests, one per hour, and CI picks which one to run. %.1f%% of them
compute the wrong renewal instant: %d land an hour out because the renewal
crosses a DST change, and %d land on the wrong DAY because the two calendars
clamp a short month differently. The day-of-month property fails %d times, and
%d of those %d are at 22:00 and 23:00 UTC — the hours at which Berlin's calendar
has already rolled over to tomorrow. That is the "it only fails at 23:00"
report, and it is not a coincidence; it is an offset. An annual renewal started
on 2024-02-29 is due %s — the clamp is a decision, and if your code does not
make it, ValueError makes it for you on 28 February.
""" % (detail[2024]["total"], 100 * detail[2024]["wrong"] / detail[2024]["total"],
       detail[2024]["hour_off"], detail[2024]["day_off"], fails[2024], late,
       fails[2024], feb29.date().isoformat()))


# ══ 4 ═══════════════════════════════════════════════════════════════════════════
# Randomness. Seeding is necessary, not sufficient: N workers seeding from one
# constant replay one stream, so "random" data collides by construction.


def section4() -> None:
    banner(4, "SEEDS UNDER PARALLEL WORKERS: THE STREAM YOU SHARE")
    workers, per_worker, space = 8, 500, 10 ** 6
    n = workers * per_worker

    def run(seed_for: Callable[[int], int], namespaced: bool) -> tuple[int, int]:
        seen: list[str] = []
        for w in range(workers):
            rng = random.Random(seed_for(w))
            for i in range(per_worker):
                seen.append(f"u{w}-{i}@test" if namespaced
                            else f"u{rng.randrange(space)}@test")
        return len(seen), len(set(seen))

    strategies = [
        ("one global seed, all workers", lambda w: SEED, False),
        ("per-worker seed (SEED ^ worker)", lambda w: SEED ^ (w * 7919), False),
        ("per-worker namespaced sequence", lambda w: SEED, True),
    ]
    print(f"  {workers} workers x {per_worker} generated emails, random.randrange(0, {space:,})")
    print()
    print(f"    {'strategy':<34}{'generated':<12}{'unique':<10}{'duplicates':<13}{'dup rate'}")
    for label, fn, ns in strategies:
        total, uniq = run(fn, ns)
        print(f"    {label:<34}{total:<12}{uniq:<10}{total-uniq:<13}{(total-uniq)/total:.2%}")

    # the birthday arithmetic, computed and simulated, for the honest strategy
    expected_collisions = n - space * (1 - (1 - 1 / space) ** n)
    p_any = 1 - math.exp(-n * (n - 1) / (2 * space))
    print()
    print(f"    birthday model for {n:,} draws from {space:,} values:")
    print(f"      expected collisions      {expected_collisions:.2f}")
    print(f"      P(at least one)          {p_any:.4%}")
    note("""
sharing one seed is not a small mistake: every worker replays the identical
stream, so 7 of every 8 rows are duplicates by construction, and a UNIQUE
constraint turns that into a failure whose stack trace points at your factory
rather than your configuration. Per-worker seeding fixes duplication and does
NOT fix collisions — the birthday model says %.2f%% of runs still hit at least
one. Only a per-worker namespace makes uniqueness a property of the design.
""" % (100 * p_any,))


# ══ 5 ═══════════════════════════════════════════════════════════════════════════
# Identifiers. Sorting by id and sorting by creation time are the same operation
# only if the id encodes the time. UUIDv4 is 122 random bits (RFC 9562 §5.4) and
# encodes nothing; UUIDv7 puts a 48-bit millisecond timestamp first (§5.7).


def uuid4_int(rng: random.Random) -> int:
    v = rng.getrandbits(128)
    v &= ~(0xF << 76)
    v |= 0x4 << 76                      # version 4
    v &= ~(0x3 << 62)
    v |= 0x2 << 62                      # variant 10
    return v


def uuid7_int(ms: int, rng: random.Random, counter: int | None = None) -> int:
    rand_a = counter & 0xFFF if counter is not None else rng.getrandbits(12)
    v = (ms & 0xFFFFFFFFFFFF) << 80
    v |= 0x7 << 76                      # version 7
    v |= rand_a << 64
    v |= 0x2 << 62                      # variant 10
    v |= rng.getrandbits(62)
    return v


def inversions(seq: list[int]) -> int:
    """Pairs out of order, counted with a Fenwick tree. O(n log n)."""
    n = len(seq)
    tree = [0] * (n + 1)
    total = 0
    for pos, val in enumerate(seq):
        i = val + 1
        seen = 0
        while i > 0:
            seen += tree[i]
            i -= i & -i
        total += pos - seen
        i = val + 1
        while i <= n:
            tree[i] += 1
            i += i & -i
    return total


def section5() -> None:
    banner(5, "IDENTIFIERS: SORTING BY ID IS NOT SORTING BY TIME")
    n = 10_000
    pairs = n * (n - 1) // 2
    print(f"  {n:,} ids generated in creation order, sorted by VALUE, inverted pairs counted")
    print(f"  ({pairs:,} pairs; a value-sort that ignores time inverts ~50% of them)")
    print()
    print(f"    {'scheme':<44}{'rate':<14}{'inversions':<14}{'% of pairs'}")

    rng = random.Random(SEED)
    order = sorted(range(n), key=lambda i: uuid4_int(random.Random(SEED + i)))
    inv4 = inversions(order)
    print(f"    {'UUIDv4 (122 random bits)':<44}{'any':<14}{inv4:<14}{inv4/pairs:.2%}")

    v7_rows = []
    for per_ms in (1, 10, 100, 1000):
        ids = []
        for i in range(n):
            ids.append((uuid7_int(1_750_000_000_000 + i // per_ms,
                                  random.Random(SEED * 31 + i)), i))
        seq = [i for _, i in sorted(ids)]
        inv = inversions(seq)
        v7_rows.append((per_ms, inv))
        print(f"    {'UUIDv7 (48-bit ms + 74 random bits)':<44}"
              f"{f'{per_ms}/ms':<14}{inv:<14}{inv/pairs:.4%}")

    ids = []
    for i in range(n):
        ids.append((uuid7_int(1_750_000_000_000 + i // 1000, random.Random(SEED + i),
                              counter=i % 1000), i))
    inv7m = inversions([i for _, i in sorted(ids)])
    print(f"    {'UUIDv7 + monotonic counter (RFC 9562 6.2)':<44}"
          f"{'1000/ms':<14}{inv7m:<14}{inv7m/pairs:.4%}")

    # the assertion that actually appears in suites
    trials = 10_000
    fails4 = sum(1 for i in range(trials)
                 if uuid4_int(random.Random(SEED + 2 * i))
                 > uuid4_int(random.Random(SEED + 2 * i + 1)))
    fails7 = sum(1 for i in range(trials)
                 if uuid7_int(1_750_000_000_000 + i, random.Random(SEED + 2 * i))
                 > uuid7_int(1_750_000_000_000 + i, random.Random(SEED + 2 * i + 1)))
    print()
    print(f"    assert first.id < second.id, over {trials:,} freshly created pairs:")
    print(f"      UUIDv4                 fails {fails4:>5} times  ({fails4/trials:.2%})")
    print(f"      UUIDv7, same millisec  fails {fails7:>5} times  ({fails7/trials:.2%})")

    # sequence gaps: the same assertion, two schemas
    gaps = {}
    for autoinc in (False, True):
        con = sqlite3.connect(":memory:")
        kind = "INTEGER PRIMARY KEY AUTOINCREMENT" if autoinc else "INTEGER PRIMARY KEY"
        con.execute(f"CREATE TABLE orders (id {kind}, sku TEXT)")
        con.executemany("INSERT INTO orders (sku) VALUES (?)",
                        [("a",), ("b",), ("c",)])          # a previous test
        con.execute("DELETE FROM orders")                   # its cleanup
        con.execute("INSERT INTO orders (sku) VALUES ('mine')")
        gaps[autoinc] = con.execute("SELECT id FROM orders").fetchone()[0]
        con.close()
    print()
    print(f"    assert order.id == 1 after a previous test inserted 3 rows and cleaned up:")
    print(f"      INTEGER PRIMARY KEY                 id = {gaps[False]}  -> passes")
    print(f"      INTEGER PRIMARY KEY AUTOINCREMENT   id = {gaps[True]}  -> fails")
    note("""
UUIDv4 inverts %.1f%% of pairs — a coin flip, which is what "sorted by a random
number" means. UUIDv7 keeps creation order to within one millisecond, so its
inversions are exactly the ties inside a millisecond: %d at 1000 ids/ms, %d at
1/ms, and the monotonic-counter variant reaches %d. And note the last block:
the SAME assertion passes or fails on a keyword in a CREATE TABLE nobody read,
because an id is a fact about the database's history, not about your test.
""" % (100 * inv4 / pairs, v7_rows[3][1], v7_rows[0][1], inv7m))


# ══ 6 ═══════════════════════════════════════════════════════════════════════════
# Iteration order. CPython randomises str/bytes hashing per process (PEP 456,
# SipHash) unless PYTHONHASHSEED is fixed, so set order is a hidden input. Shown
# twice: with a seed we control, then with real subprocesses at pinned seeds.


class SeededSet:
    """An open-addressed set whose hash is keyed, exactly like CPython's. The
    seed enters the hash, the hash picks the slot, the slot order IS the
    iteration order. Nothing else about the container changed."""

    MASK = (1 << 64) - 1

    def __init__(self, seed: int, capacity: int = 32) -> None:
        self.seed, self.slots = seed, [None] * capacity

    def _hash(self, s: str) -> int:
        h = (0xCBF29CE484222325 ^ self.seed) & self.MASK       # seeded FNV-1a
        for b in s.encode():
            h = ((h ^ b) * 0x100000001B3) & self.MASK
        h ^= h >> 33                                          # avalanche, so the
        h = (h * 0xFF51AFD7ED558CCD) & self.MASK               # seed reaches every
        h ^= h >> 33                                          # bit of the result
        return h

    def add(self, s: str) -> None:
        i = self._hash(s) % len(self.slots)
        while self.slots[i] is not None:
            if self.slots[i] == s:
                return
            i = (i + 1) % len(self.slots)
        self.slots[i] = s

    def __iter__(self) -> Iterator[str]:
        return (s for s in self.slots if s is not None)


def section6() -> None:
    banner(6, "ITERATION ORDER: HASH SEEDS AND THE QUERY WITH NO ORDER BY")
    tags = ("billing", "auth", "search", "reports")
    seeds = 512
    orders = []
    for s in range(seeds):
        st = SeededSet(s)
        for t in tags:
            st.add(t)
        orders.append(",".join(st))
    laptop = orders[0]
    matches = orders.count(laptop)
    print(f"  4 tags in a set, {seeds} hash seeds, result serialised with ','.join()")
    print(f"    distinct orders observed        {len(set(orders))} of {math.factorial(4)} possible")
    print(f"    the order YOUR machine showed   {laptop}")
    print(f"    seeds that reproduce it         {matches} of {seeds}  ({matches/seeds:.2%})")
    print(f"    a hard-coded assertion on it passes on {matches/seeds:.1%} of processes")

    print()
    print("  the same thing in real CPython, PYTHONHASHSEED pinned per subprocess:")
    snippet = ("import sys;print(','.join({'billing','auth','search','reports'}),"
               "','.join(str(x) for x in {40,10,30,20}))")
    seen = []
    for hs in ("0", "1", "2", "3", "4"):
        env = dict(os.environ, PYTHONHASHSEED=hs)
        try:
            out = subprocess.run([sys.executable, "-c", snippet], env=env,
                                 capture_output=True, text=True, timeout=30).stdout.strip()
        except Exception:                              # pragma: no cover - defensive
            out = "(subprocess unavailable)"
        strs, ints = (out.split(" ") + [""])[:2]
        seen.append(strs)
        print(f"    PYTHONHASHSEED={hs}   set of str -> {strs:<34} set of int -> {ints}")
    print(f"    {len(set(seen))} distinct string orders across 5 seeds; the int order never "
          f"moves — CPython does not randomise hash(int).")
    # A pinned PYTHONHASHSEED makes string hashing deterministic for ONE CPython
    # build, not across builds — the siphash seeding has changed between versions.
    # So the orderings above are a property of this interpreter; only the pattern
    # (strings move, ints never do) reproduces everywhere. Saying so in the output
    # keeps any doc that quotes this block truthful on someone else's machine.
    print(f"    NOTE: the orderings above are specific to CPython "
          f"{sys.version_info.major}.{sys.version_info.minor} on this machine and will")
    print( "          differ on another build. What reproduces everywhere is the pattern:")
    print( "          pinning the seed fixes the order, strings reorder across seeds, ints never do.")

    print()
    print("  SELECT with no ORDER BY, in sqlite3 — same query, same rows, two answers:")
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, tenant TEXT, seq INTEGER)")
    rows = [("acme", 50), ("acme", 40), ("acme", 30), ("acme", 20), ("acme", 10)]
    con.executemany("INSERT INTO events (tenant, seq) VALUES (?, ?)", rows)
    q = "SELECT seq FROM events WHERE tenant = 'acme'"

    def answer() -> tuple[list[int], str]:
        plan = con.execute("EXPLAIN QUERY PLAN " + q).fetchone()[3]
        kind = "index scan" if "INDEX" in plan.upper() else "full table scan"
        return [r[0] for r in con.execute(q)], kind

    before, k1 = answer()
    con.execute("CREATE INDEX ix_events_tenant_seq ON events (tenant, seq)")
    after, k2 = answer()
    print(f"    before the migration ({k1:<16}) -> {before}")
    print(f"    after  the migration ({k2:<16}) -> {after}")
    print(f"    identical? {before == after}. The only change was CREATE INDEX.")

    con.execute("DROP INDEX ix_events_tenant_seq")
    con.execute("DELETE FROM events WHERE seq = 30")
    con.execute("INSERT INTO events (tenant, seq) VALUES ('acme', 30)")
    redone, _ = answer()
    print(f"    after DELETE seq=30 + re-INSERT the same row  -> {redone}")
    print(f"    identical to before? {redone == before}. A fixture that re-creates a row moves it.")
    con.close()
    note("""
An assertion on collection order is an assertion about a hash seed you did not
choose, a query plan you did not write and a row's insertion history. The
sqlite3 rows never changed value: an index moved them, and a delete-then-
reinsert of the same logical row moved them again. dict is the exception —
insertion order is a language guarantee since 3.7 — which is exactly why the
habit of reaching for a set instead hides so well.
""")


# ══ 7 ═══════════════════════════════════════════════════════════════════════════
# Test execution order. Independence is a property, and the only way to know you
# have it is to violate the file order on purpose. 200 tests, 3 dependencies.

SHUFFLES = 4_000
LEAKERS = 39


class World:
    """Module-level state shared by the whole suite. There is no reset between
    tests — which is the entire point."""

    def __init__(self) -> None:
        self.config = {"currency": "USD"}
        self.rows: list[str] = []
        self.cache: list[str] = []


def build_suite(w: World) -> list[tuple[str, Callable[[], None]]]:
    """Returns (name, fn). Ordered so that a run in file order is fully green."""
    tests: list[tuple[str, Callable[[], None]]] = []

    def pure(i: int) -> Callable[[], None]:
        def t() -> None:                       # an honest, independent test
            assert i * 2 == i + i
        return t

    def leak(i: int) -> Callable[[], None]:
        def t() -> None:                       # passes always, leaks always
            w.cache.append(f"entry-{i}")
        return t

    def d1_reader() -> None:                       # must run BEFORE d1_setter
        assert w.config["currency"] == "USD"

    def d1_setter() -> None:
        w.config["currency"] = "EUR"

    def d2_seed() -> None:
        w.rows.extend(["r1", "r2", "r3"])

    def d2_count() -> None:                        # needs seed before, truncate after
        assert len(w.rows) == 3

    def d2_truncate() -> None:
        w.rows.clear()

    def d3_target() -> None:                       # needs <39 leaked entries
        assert len(w.cache) < LEAKERS

    tests.append(("test_reads_default_currency", d1_reader))
    for i in range(20):                            # 20 leakers before the target
        tests.append((f"test_writes_audit_entry_{i:02d}", leak(i)))
    tests.append(("test_cache_stays_small", d3_target))
    tests.append(("test_seeds_three_rows", d2_seed))
    tests.append(("test_counts_three_rows", d2_count))
    for i in range(20, LEAKERS):                   # 19 leakers after it
        tests.append((f"test_writes_audit_entry_{i:02d}", leak(i)))
    tests.append(("test_truncates_rows", d2_truncate))
    tests.append(("test_sets_currency_to_eur", d1_setter))
    while len(tests) < 200:
        tests.append((f"test_arithmetic_{len(tests):03d}", pure(len(tests))))
    return tests


DEPS = {"test_reads_default_currency": "D1 leaked global config",
        "test_counts_three_rows": "D2 shared table + a truncating test",
        "test_cache_stays_small": "D3 39 tests each leaking one entry"}


def run_suite(order: list[int], template: list[tuple[str, Callable[[], None]]],
              world: World) -> set[str]:
    failed: set[str] = set()
    for idx in order:
        name, fn = template[idx]
        try:
            fn()
        except AssertionError:
            failed.add(name)
    return failed


def section7() -> None:
    banner(7, "TEST EXECUTION ORDER: THE DETECTION POWER OF A SHUFFLE")
    n = 200

    def fresh() -> tuple[list[tuple[str, Callable[[], None]]], World]:
        w = World()
        return build_suite(w), w

    tpl, w = fresh()
    file_order = run_suite(list(range(n)), tpl, w)
    tpl, w = fresh()
    reverse = run_suite(list(range(n - 1, -1, -1)), tpl, w)

    print(f"  {n} tests, {len(DEPS)} deliberate order dependencies, no reset between tests")
    print(f"    run in file order      {len(file_order)} failures  -> green, ships")
    print(f"    run in reverse order   {len(reverse)} failures  -> "
          f"{', '.join(sorted(DEPS[x][:2] for x in reverse)) or 'none'}")

    counts = {k: 0 for k in DEPS}
    any_hit = 0
    for s in range(SHUFFLES):
        rng = random.Random(SEED + s)
        order = list(range(n))
        rng.shuffle(order)
        tpl, w = fresh()
        failed = run_suite(order, tpl, w)
        if failed:
            any_hit += 1
        for name in failed:
            counts[name] += 1

    analytic = {"test_reads_default_currency": 0.5,
                "test_counts_three_rows": 2 / 3,
                "test_cache_stays_small": 1 / (LEAKERS + 1)}

    def runs_for(p: float, conf: float) -> int:
        return math.ceil(math.log(1 - conf) / math.log(1 - p)) if p > 0 else -1

    print()
    print(f"  {SHUFFLES:,} shuffled runs (a seeded permutation each, as pytest-randomly does)")
    print()
    print(f"    {'dependency':<42}{'measured':<12}{'analytic':<12}{'runs @95%':<12}{'runs @99%'}")
    for name, label in DEPS.items():
        p = counts[name] / SHUFFLES
        a = analytic[name]
        print(f"    {label:<42}{p:<12.4f}{a:<12.4f}{runs_for(a, 0.95):<12}{runs_for(a, 0.99)}")
    p_any = any_hit / SHUFFLES
    a_any = 1 - math.prod(1 - v for v in analytic.values())
    print(f"    {'ANY dependency detected':<42}{p_any:<12.4f}{a_any:<12.4f}"
          f"{runs_for(a_any, 0.95):<12}{runs_for(a_any, 0.99)}")
    note("""
Read the last two columns, because they are the only actionable numbers here.
"Does this suite have an order dependency at all?" is answered by %d shuffled
runs at 99%% confidence — one afternoon. "Have I found ALL of them?" is governed
by the rarest one, and D3 needs %d shuffled runs for the same confidence, which
at one CI run per merge is weeks. Reverse order caught %d of %d for free and
missed D3 entirely, because D3 is not a precedence dependency — it is a COUNT
dependency, and reversing a green order cannot change how many of the 39
leakers happen to sit before the assertion.
""" % (runs_for(a_any, 0.99), runs_for(analytic["test_cache_stays_small"], 0.99),
       len(reverse), len(DEPS)))


# ══ 8 ═══════════════════════════════════════════════════════════════════════════
# Floating point. IEEE 754 binary64 cannot represent 0.01, so a sum of prices is
# never the price you meant, and the tolerance you pick is the error you ship.


def section8() -> None:
    banner(8, "FLOATING POINT: THE TOLERANCE IS A POLICY ABOUT MONEY")
    acc = 0.0
    for _ in range(10_000):
        acc += 0.01
    exact = Decimal("0.01") * 10_000
    print(f"  0.01 added 10,000 times")
    print(f"    float   {acc!r}")
    print(f"    Decimal {exact}")
    print(f"    drift   {Decimal(acc) - exact:.2E}  ({abs(acc - float(exact))/float(exact):.2E} relative)")
    print(f"    assert 0.1 + 0.2 == 0.3 -> {0.1 + 0.2 == 0.3}   (0.1 + 0.2 is {0.1 + 0.2!r})")

    magnitudes = [Decimal(x) for x in
                  ("1.00", "100.00", "9999.99", "100000.00", "1000000.00", "50000000.00")]

    def drifted(v: Decimal) -> float:
        """The same total summed the way a basket is summed: 997 line items,
        each an exact number of cents, accumulated left to right as floats."""
        k = 997
        base = (v / k).quantize(Decimal("0.01"), rounding=decimal.ROUND_DOWN)
        items = [base] * (k - 1) + [v - base * (k - 1)]
        acc2 = 0.0
        for item in items:
            acc2 += float(item)
        return acc2

    policies = [
        ("assert a == b", lambda a, b: a == b),
        ("math.isclose default (rel 1e-9)", lambda a, b: math.isclose(a, b)),
        ("pytest.approx default (rel 1e-6)",
         lambda a, b: math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-12)),
        ("isclose(rel_tol=0, abs_tol=0.005)",
         lambda a, b: math.isclose(a, b, rel_tol=0.0, abs_tol=0.005)),
        ("Decimal, quantized to cents",
         lambda a, b: Decimal(a).quantize(Decimal("0.01"), decimal.ROUND_HALF_EVEN)
         == Decimal(b).quantize(Decimal("0.01"), decimal.ROUND_HALF_EVEN)),
    ]
    print()
    print(f"  {len(magnitudes)} basket totals from $1.00 to $50,000,000.00; each judged twice:")
    print(f"    (a) float drift vs the exact total  — saying 'unequal' is a FALSE ALARM")
    print(f"    (b) a real 1-cent bug               — saying 'equal'   is a MISSED BUG")
    print()
    print(f"    {'tolerance policy':<38}{'false alarms':<16}{'missed 1c bugs':<18}{'verdict'}")
    for label, ok in policies:
        alarms = missed = 0
        for v in magnitudes:
            f, e = drifted(v), float(v)
            if not ok(f, e):
                alarms += 1
            if ok(f + 0.01, e):
                missed += 1
        verdict = "ship this" if alarms == 0 and missed == 0 else \
            ("too tight" if alarms else "too loose")
        print(f"    {label:<38}{f'{alarms}/{len(magnitudes)}':<16}"
              f"{f'{missed}/{len(magnitudes)}':<18}{verdict}")

    threshold = 0.01 / 1e-6
    note("""
The two failure modes are not symmetric and no single relative tolerance gets
both. pytest.approx defaults to rel=1e-6, which means it stops being able to see
a one-cent error at a total of $%s — and a reconciliation suite is
exactly where the totals are large. A relative tolerance scales the size of the
bug you accept with the size of the number, which is the opposite of what money
wants: a cent is a cent at every magnitude. For money, either compare in integer
minor units / Decimal, or fix abs_tol at half the smallest unit you care about
and set rel_tol to 0.
""" % f"{threshold:,.0f}")


# ══ 9 ═══════════════════════════════════════════════════════════════════════════
# The scheduler is a hidden input. A read-modify-write across two threads has a
# finite set of interleavings; a real test samples one, which is why races hide.


def run_interleaving(plan: list[str]) -> tuple[int, str]:
    """Execute one schedule of two threads doing counter = counter + 1.
    Returns (final counter, a readable trace)."""
    steps = ("READ", "ADD ", "WRIT")
    regs = {"A": 0, "B": 0}
    idx = {"A": 0, "B": 0}
    shared, trace = 0, []
    for who in plan:
        step = steps[idx[who]]
        idx[who] += 1
        if step == "READ":
            regs[who] = shared
        elif step == "ADD ":
            regs[who] += 1
        else:
            shared = regs[who]
        trace.append(f"{who}:{step.strip()}")
    return shared, " ".join(trace)


def section9() -> None:
    banner(9, "THE SCHEDULER IS A HIDDEN INPUT TOO")
    results = []
    for positions in itertools.combinations(range(6), 3):
        plan = ["B"] * 6
        for p in positions:
            plan[p] = "A"
        results.append(run_interleaving(plan))
    total = len(results)
    good = sum(1 for v, _ in results if v == 2)
    bad = total - good
    print("  two threads, each doing counter = counter + 1 as READ / ADD / WRITE")
    print(f"    distinct interleavings enumerated   {total}")
    print(f"    end with counter == 2 (correct)     {good}   ({good/total:.1%})")
    print(f"    end with counter == 1 (lost update) {bad}  ({bad/total:.1%})")
    print()
    win = next(t for v, t in results if v == 2)
    lose = next(t for v, t in results if v == 1)
    print(f"    correct      {win}   -> 2")
    print(f"    lost update  {lose}   -> 1")

    print()
    print("  a real thread pair does not enumerate; it samples one schedule. If the")
    print("  interpreter switches between two of the six steps with probability q,")
    print("  the race is observable at roughly 2q per operation:")
    print()
    print(f"    {'q (switch per step)':<24}{'P(lost update)':<20}"
          f"{'runs for a 50% chance':<26}{'at 20 CI runs/day'}")
    for q in (1e-2, 1e-3, 1e-4, 1e-5):
        p = 2 * q
        runs = math.ceil(math.log(0.5) / math.log(1 - p))
        print(f"    {q:<24.0e}{p:<20.0e}{runs:<26,}{runs/20:,.0f} days")
    note("""
%.0f%% of the possible schedules lose the update and the test still passes,
because a real run samples one schedule and the vulnerable window is a few
nanoseconds wide. That gap between "almost every schedule is wrong" and "almost
every run is right" is what a race condition IS, and it is why the bug reaches
production: the scheduler is a hidden input whose distribution on your laptop is
nothing like its distribution under a loaded CI runner. Enumerating all %d
interleavings finds the bug with certainty in %d executions. Waiting for the
scheduler to find it takes thousands of runs, and the run that finally does will
be closed as a flake.
""" % (100 * bad / total, total, total))


def main() -> None:
    print("DETERMINISM · Phase 12 Lesson 08 · every RNG seeded from "
          f"SEED = {SEED}; no wall-clock value is printed.")
    section1()
    section2()
    section3()
    section4()
    section5()
    section6()
    section7()
    section8()
    section9()
    print()


if __name__ == "__main__":
    main()
