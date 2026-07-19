#!/usr/bin/env python3
"""
Consumer lag, backpressure and flow control - measured on a virtual clock.

Companion to docs/en.md (Phase 6, Lesson 09 - Backpressure, Consumer Lag &
Flow Control). Little's Law (L = lambda*W, Little, Operations Research 9(3),
1961) is the arithmetic behind every conversion between count lag and time lag.

The broker is a FLUID queue: a FIFO of per-tick buckets whose message counts are
real numbers, which is exactly how capacity-planning arithmetic works and makes
every printed figure reproducible to the digit. The prefetch sweep, by contrast,
is a discrete-event simulation because fairness is a whole-message property.

Deterministic and self-terminating:  python backpressure_and_lag.py
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

TICK = 0.25                     # virtual seconds per simulation step
POLL = 1.0                      # consumers fetch in batches once a second
RAMP = " .:-=+*#%@"             # ASCII density ramp for the time-series plots
RETENTION_H = 6.0               # broker retention window used in the projections


def poll_due(now: float) -> bool:
    """Consumers do not sip continuously; they poll. This is why a healthy
    system still has a standing backlog of one poll cycle of arrivals."""
    return abs((now / POLL) - round(now / POLL)) < 1e-9


def slope(xs: list[float], ys: list[float]) -> float:
    """Least-squares gradient - robust to the sawtooth a poll cycle creates."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    d = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / d if d else 0.0


# --- the broker: a FIFO backlog that knows both kinds of lag -----------------

class Broker:
    """A partition's backlog. Tracks count lag, time lag, and retention loss.

    Messages are held in arrival-ordered buckets [ts, n_high, n_low]. The head
    bucket's timestamp is the age of the oldest unprocessed message, which is
    the only lag number that is directly comparable to an SLA or a retention
    window.
    """

    def __init__(self, retention_s: float | None = None) -> None:
        self.q: deque[list[float]] = deque()
        self.retention = retention_s
        self._nh = self._nl = 0.0
        self.published = {"high": 0.0, "low": 0.0}
        self.consumed = {"high": 0.0, "low": 0.0}
        self.expired = {"high": 0.0, "low": 0.0}
        self.shed = {"high": 0.0, "low": 0.0}

    def publish(self, ts: float, high: float = 0.0, low: float = 0.0) -> None:
        if high <= 0 and low <= 0:
            return
        if self.q and self.q[-1][0] == ts:
            self.q[-1][1] += high
            self.q[-1][2] += low
        else:
            self.q.append([ts, high, low])
        self._nh += high
        self._nl += low
        self.published["high"] += high
        self.published["low"] += low

    @property
    def count_lag(self) -> float:
        return self._nh + self._nl

    @property
    def high_lag(self) -> float:
        return self._nh

    def time_lag(self, now: float) -> float:
        return (now - self.q[0][0]) if self.q else 0.0

    def high_time_lag(self, now: float) -> float:
        """Age of the oldest unprocessed HIGH-priority message."""
        for ts, h, _ in self.q:
            if h > 1e-9:
                return now - ts
        return 0.0

    def expire(self, now: float) -> None:
        """Retention deletes the head of the log. Nobody gets an error."""
        if self.retention is None:
            return
        cut = now - self.retention
        while self.q and self.q[0][0] < cut:
            _, h, l = self.q.popleft()
            self.expired["high"] += h
            self.expired["low"] += l
            self._nh -= h
            self._nl -= l

    def consume(self, n: float) -> dict[str, float]:
        """Drain up to n messages from the head, FIFO, pro rata by class."""
        got = {"high": 0.0, "low": 0.0}
        while n > 1e-9 and self.q:
            ts, h, l = self.q[0]
            tot = h + l
            if tot <= n + 1e-9:
                got["high"] += h
                got["low"] += l
                n -= tot
                self.q.popleft()
                self._nh -= h
                self._nl -= l
            else:
                f = n / tot
                self.q[0][1] -= h * f
                self.q[0][2] -= l * f
                self._nh -= h * f
                self._nl -= l * f
                got["high"] += h * f
                got["low"] += l * f
                n = 0.0
        self.consumed["high"] += got["high"]
        self.consumed["low"] += got["low"]
        return got


# --- the consumer group: capacity, and the cost of changing its size ---------

@dataclass
class Group:
    """A consumer group. Resizing costs a stop-the-world rebalance pause."""

    n: int
    per: float                       # messages/second per consumer
    partitions: int | None = None    # the hard ceiling on useful consumers
    rebalance_s: float = 5.0
    pause_until: float = -1.0
    events: int = 0
    paused: float = 0.0

    @property
    def assigned(self) -> int:
        return self.n if self.partitions is None else min(self.n, self.partitions)

    @property
    def idle(self) -> int:
        return self.n - self.assigned

    def capacity(self, now: float) -> float:
        if now < self.pause_until:
            self.paused += TICK
            return 0.0
        return self.assigned * self.per

    def resize(self, n: int, now: float) -> None:
        if n == self.n:
            return
        self.n = n
        self.events += 1
        self.pause_until = now + self.rebalance_s


# --- plotting ---------------------------------------------------------------

def spark(series: list[float], width: int = 68) -> str:
    """An ASCII density plot: the shape of a metric over the whole run."""
    if not series:
        return ""
    hi = max(series) or 1.0
    step = len(series) / width
    out = []
    for i in range(width):
        a = int(i * step)
        b = max(a + 1, int((i + 1) * step))
        seg = series[a:b]
        v = sum(seg) / len(seg)
        j = int(round(v / hi * (len(RAMP) - 1)))
        out.append(RAMP[max(0, min(len(RAMP) - 1, j))])
    return "".join(out)


def plot(label: str, series: list[float], unit: str, fmt: str = ",.0f") -> None:
    print(f"  {label:<11}|{spark(series)}|  peak {max(series):{fmt}} {unit}".rstrip())


def hms(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600:d}h{(s % 3600) // 60:02d}m"


def snap(v: float, eps: float = 0.5) -> float:
    """-0 in a report is noise. Round tiny gradients to a clean zero."""
    return 0.0 if abs(v) < eps else v


# --- 1 + 2. the narrative run ------------------------------------------------

def main_arrival(t: float) -> float:
    if t < 60:
        return 800.0            # steady, rho = 0.80
    if t < 63:
        return 8000.0           # a 10x burst, 3 seconds long
    if t < 170:
        return 800.0            # back to normal while the burst drains
    if t < 320:
        return 1200.0           # a mere +20% over capacity, sustained
    return 0.0                  # sawtooth phase: impulses, handled below


def main_capacity(t: float) -> float:
    return 1000.0 if t < 270 else 1600.0     # operator scales out at t=270


def run_narrative(horizon: float = 400.0) -> dict:
    b = Broker()
    ser = {k: [] for k in ("t", "arr", "drain", "clag", "tlag", "by_lam", "by_mu")}
    steps = int(horizon / TICK)
    for i in range(steps):
        now = i * TICK
        if now >= 320.0 and abs(now % 10.0) < 1e-9:
            b.publish(now, high=4000.0)            # a batch producer's dump
        else:
            b.publish(now, high=main_arrival(now) * TICK)
        cap = main_capacity(now)
        ser["t"].append(now)
        ser["arr"].append(main_arrival(now) if now < 320 else 400.0)
        ser["drain"].append(min(cap, b.count_lag / TICK))
        ser["clag"].append(b.count_lag)
        ser["tlag"].append(b.time_lag(now))
        lam = ser["arr"][-1] or 1.0
        ser["by_lam"].append(b.count_lag / lam)             # the correct conversion
        ser["by_mu"].append(b.count_lag / cap)              # the one on your dashboard
        if poll_due(now):
            b.consume(cap * POLL)
    return {"broker": b, "ser": ser}


def at(ser: dict, key: str, t: float) -> float:
    return ser[key][int(t / TICK)]


def section_narrative() -> dict:
    r = run_narrative()
    ser = r["ser"]
    print("== 1. THE RUN: one consumer group, six lag shapes, 400 virtual seconds ==")
    print("  4 consumers x 250 msg/s = 1,000/s capacity (1,600/s after the operator scales out at t=270)")
    print("  each plot cell is ~5.3s; the ramp is ' .:-=+*#%@' from zero to the peak on that row")
    plot("arrival/s", ser["arr"], "msg/s")
    plot("drain/s", ser["drain"], "msg/s")
    plot("COUNT lag", ser["clag"], "msgs")
    plot("TIME lag", ser["tlag"], "s", ".1f")
    print("   phase:    steady          BURST + absorb            +20% OVERLOAD     recov  sawtooth")
    print("   t=            0s         60s                      170s              270s   320s   400s")

    print("\n== 2. READING THE DERIVATIVE: the shape is the diagnosis ==")
    print("  Values are the phase mean; d/dt is the least-squares gradient across the phase.")
    print(f"  {'phase':<22} {'window':<10} {'lam':>6} {'mu':>6} {'count lag':>10} {'d/dt':>8}"
          f" {'time lag':>9} {'d/dt':>7}  shape -> diagnosis")
    rows = [
        ("steady rho=0.80", 10, 59, "flat + nonzero -> HEALTHY"),
        ("10x burst, 3s", 60, 63, "vertical -> a burst arriving"),
        ("absorbing the burst", 63, 169, "rise then fall -> absorbed"),
        ("+20% sustained", 170, 269, "linear rise -> UNDER-CAPACITY"),
        ("scaled out to 1,600/s", 270, 319, "falling -> recovering"),
        ("batch producer", 320, 399, "sawtooth -> batchy input"),
    ]
    for name, t0, t1, shape in rows:
        w = slice(int(t0 / TICK), int(t1 / TICK))
        ts, cl, tl = ser["t"][w], ser["clag"][w], ser["tlag"][w]
        lam = sum(ser["arr"][w]) / len(ts)
        mu = main_capacity(t0)
        print(f"  {name:<22} {f'{t0}-{t1}s':<10} {lam:>6,.0f} {mu:>6,.0f}"
              f" {sum(cl) / len(cl):>10,.0f} {snap(slope(ts, cl)):>+8,.0f}"
              f" {sum(tl) / len(tl):>8,.1f}s {snap(slope(ts, tl), 0.005):>+7.3f}  {shape}")

    win = slice(int(63 / TICK), int(170 / TICK))
    tl = ser["tlag"][win]
    cl = ser["clag"][win]
    it = tl.index(max(tl))
    ic = cl.index(max(cl))
    print("\n  The two lags do NOT peak together. While the burst backlog drains:")
    print(f"    count lag peaks at t={63 + ic * TICK:>5.1f}s  ({max(cl):>9,.0f} msgs)"
          f" and falls monotonically from there")
    print(f"    TIME lag peaks at t={63 + it * TICK:>5.1f}s  ({max(tl):>9.1f}s)"
          f" -- {it * TICK:.1f}s LATER, while count lag was already down to {cl[it]:,.0f}")
    print("    the head is still crawling through densely-packed burst messages: 8,000/s of")
    print("    arrivals are being retired at 1,000/s, so the oldest message ages 0.875s per second.")

    saw = slice(int(320 / TICK), int(400 / TICK))
    print(f"\n  The sawtooth is invisible above because the burst sets the scale."
          f" Zoomed to t=320-400s:")
    plot("COUNT lag", ser["clag"][saw], "msgs")
    print("    A batch producer dumping 4,000 messages every 10s. Mean lag is low, the shape is")
    print("    alarming, and nothing is wrong -- alarm on the trough, not the peak.")

    print("\n  Converting count lag to time lag. The backlog was BUILT by arrivals, so the")
    print("  identity is time_lag = count_lag / lambda (accurate to one sample interval, 0.25s).")
    print("  The conversion on every dashboard is count_lag / mu, which answers a different")
    print("  question -- 'how long to drain if arrivals stopped' -- and arrivals never stop:")
    print(f"    {'':>6} {'':<19} {'measured':>9} {'/ lambda':>10} {'err':>7} {'/ mu':>10} {'err':>8}")
    for label, t in (("steady, rho=0.80", 50.0), ("draining a burst", 84.0),
                     ("sustained overload", 269.0), ("after scaling out", 300.0)):
        m = at(ser, "tlag", t)
        a, u = at(ser, "by_lam", t), at(ser, "by_mu", t)
        ea = 100 * (a - m) / m if m > 1e-6 else float("nan")
        eu = 100 * (u - m) / m if m > 1e-6 else float("nan")
        print(f"    t={t:>4.0f}s {label:<19} {m:>8.2f}s {a:>9.2f}s {ea:>+6.0f}%"
              f" {u:>9.2f}s {eu:>+7.0f}%")
    print("    The dashboard estimate is only right when mu = lambda -- that is, only when")
    print("    nothing is wrong. It under-reads while a burst drains and over-reads during")
    print("    overload, and both errors point the wrong way for the decision you are making.")
    return r


# --- 3. burst vs sustained ---------------------------------------------------

def run_rate(arrival, capacity, horizon: float, retention: float | None = None) -> dict:
    b = Broker(retention)
    clag: list[float] = []
    tlag: list[float] = []
    drained_at: float | None = None
    for i in range(int(horizon / TICK)):
        now = i * TICK
        b.publish(now, high=arrival(now) * TICK)
        b.expire(now)
        clag.append(b.count_lag)
        tlag.append(b.time_lag(now))
        if drained_at is None and now > 1 and b.time_lag(now) <= POLL + 1e-9:
            drained_at = now
        elif drained_at is not None and b.time_lag(now) > POLL * 2:
            drained_at = None
        if poll_due(now):
            b.consume(capacity(now) * POLL)
    return {"b": b, "clag": clag, "tlag": tlag, "drained_at": drained_at,
            "peak_c": max(clag), "peak_t": max(tlag), "end_c": clag[-1], "end_t": tlag[-1]}


def section_burst_vs_sustained() -> list[dict]:
    print("\n== 3. BURST vs SUSTAINED: the small one is the dangerous one ==")
    H = 1200.0
    burst = run_rate(lambda t: 8000.0 if 30 <= t < 60 else 800.0, lambda t: 1000.0, H)
    sust = run_rate(lambda t: 1200.0, lambda t: 1000.0, H)
    print(f"  Both runs: capacity mu = 1,000 msg/s, horizon {H:,.0f}s.")
    print("  A: a 10x BURST -- 8,000/s for 30s, then back to 800/s (baseline rho=0.80)")
    print("  B: a mere +20% SUSTAINED overload -- 1,200/s, forever")
    plot("A count lag", burst["clag"], "msgs")
    plot("A time lag", burst["tlag"], "s", ".1f")
    plot("B count lag", sust["clag"], "msgs")
    plot("B time lag", sust["tlag"], "s", ".1f")

    excess = (8000 - 1000) * 30
    headroom = 1000 - 800
    predicted = excess / headroom
    measured = (burst["drained_at"] or H) - 60.0
    print(f"\n  A: excess delivered = (8,000-1,000) x 30s = {excess:,.0f} messages")
    print(f"     Little's Law recovery = excess / headroom = {excess:,.0f} / {headroom} ="
          f" {predicted:,.0f}s")
    print(f"     measured recovery after the burst ends      = {measured:,.0f}s"
          f"   ({100 * abs(measured - predicted) / predicted:.1f}% off)")
    print(f"     peak count lag {burst['peak_c']:>9,.0f}   peak time lag {burst['peak_t']:>6.1f}s"
          f"   state at {H:,.0f}s: RECOVERED (lag {burst['end_c']:,.0f}, {burst['end_t']:.2f}s)")
    print(f"  B: excess delivered = 200/s, with no end. At {H:,.0f}s the 'small' mismatch has")
    print(f"     already put {sust['end_c']:,.0f} messages behind -- more than the 10x burst's peak of"
          f" {burst['peak_c']:,.0f}.")
    print(f"     peak count lag {sust['peak_c']:>9,.0f}   peak time lag {sust['peak_t']:>6.1f}s"
          f"   state at {H:,.0f}s: STILL GROWING")
    cross = burst["peak_c"] / 200.0
    print(f"     B overtakes A's peak backlog after {cross:,.0f}s ({cross / 60:.0f} min) and never stops.")

    print("\n  The 14:00 deploy: a synchronous enrichment call, 4ms -> 16ms per message.")
    dep = run_rate(lambda t: 800.0, lambda t: 250.0, 600.0)
    w = slice(int(60 / TICK), None)
    ts = [i * TICK for i in range(int(60 / TICK), int(600 / TICK))]
    slope_c = slope(ts, dep["clag"][w])
    slope_t = slope(ts, dep["tlag"][w])
    ret_s = RETENTION_H * 3600
    deadline = ret_s / slope_t
    print(f"     lambda = 800/s   mu = 4 x 62.5/s = 250/s")
    print(f"     measured slopes: {slope_c:+,.0f} msg/s of count lag,"
          f" {slope_t:+.4f}s of time lag per second")
    for hours in (1, 3, 5):
        print(f"       +{hours}h ({14 + hours}:00): count lag {slope_c * hours * 3600:>12,.0f}"
              f"   time lag {hms(slope_t * hours * 3600):>7}")
    print(f"     retention is {RETENTION_H:.0f}h. Time lag reaches it at +{hms(deadline)}"
          f" -- {14 + int(deadline // 3600)}:{int(deadline % 3600 // 60):02d}. That is the")
    print(f"     deadline for IRRECOVERABLE loss; past it the broker deletes 800 msg/s")
    print(f"     forever and the lag graph goes FLAT because you are losing, not catching up.")
    backlog = slope_c * 5 * 3600
    print(f"\n     Three options at 19:00 -- backlog {backlog:,.0f},"
          f" time lag {hms(slope_t * 5 * 3600)}:")
    for label, cap in (("revert the deploy", 1000.0),
                       ("revert + double the group", 2000.0),
                       ("revert + 4x the group", 4000.0)):
        head = cap - 800.0
        print(f"       {label:<26} mu={cap:>5,.0f}/s  headroom {head:>5,.0f}/s"
              f"  -> drained in {hms(backlog / head):>7}")
    print(f"     All three beat the deadline: time lag falls the moment mu > lambda. But the")
    print(f"     first leaves every downstream consumer reading stale data until 08:45 tomorrow.")
    print(f"     Doing nothing loses data from +{hms(deadline)} and never stops.")
    return [
        {"name": "10x burst, 30s", "pc": burst["peak_c"], "pt": burst["peak_t"],
         "drain": measured, "shed": 0.0, "lost": 0.0, "end": "recovered"},
        {"name": "+20% sustained", "pc": sust["peak_c"], "pt": sust["peak_t"],
         "drain": float("inf"), "shed": 0.0, "lost": 0.0, "end": "unbounded growth"},
        {"name": "14:00 deploy (mu/4), 5h in", "pc": backlog, "pt": slope_t * 5 * 3600,
         "drain": backlog / 200.0, "shed": 0.0,
         "lost": 0.0, "end": f"deletes from +{hms(deadline)}"},
    ]


# --- 4. the prefetch sweep ---------------------------------------------------

MSG_KB = 16.0
RTT_MS = 2.0
SERVICE_MS = 1.0
HEAP_MB = 256.0


def prefetch_run(prefetch: int, consumers: int = 4, backlog: int = 5000) -> dict:
    """Discrete-event: each consumer fetches up to `prefetch`, then processes.

    A fetch costs one round trip; a message costs SERVICE_MS. A consumer cannot
    fetch again until its current batch is acked, so the round trip is only
    amortised over `prefetch` messages -- which is the whole point of prefetch.
    """
    remaining = backlog
    free = [0.0] * consumers            # when each consumer next asks for work
    got = [0] * consumers
    busy = [0.0] * consumers
    batches = [[] for _ in range(consumers)]     # (t_start_processing, size)
    while remaining > 0:
        c = min(range(consumers), key=lambda i: (free[i], i))
        take = min(prefetch, remaining)
        remaining -= take
        start = free[c] + RTT_MS
        free[c] = start + take * SERVICE_MS
        got[c] += take
        busy[c] += take * SERVICE_MS
        batches[c].append((start, take))
    drain_ms = max(free)
    # Unacked messages decay linearly through a batch, so the time-weighted mean
    # exposure of one batch is size/2 over size*SERVICE_MS. Kill the group at a
    # uniformly random instant and this is how many messages get redelivered.
    integral = sum(size * size * SERVICE_MS / 2.0
                   for c in range(consumers) for _, size in batches[c])
    return {
        "p": prefetch,
        "ms": drain_ms,
        "tput": backlog / (drain_ms / 1000.0),
        "per_consumer_tput": prefetch / (RTT_MS + prefetch * SERVICE_MS) * 1000.0,
        "got": got,
        "imbalance": (max(got) - min(got)) / (backlog / consumers),
        "idle_ms": sum(drain_ms - busy[c] - len(batches[c]) * RTT_MS for c in range(consumers)),
        "mem_mb": prefetch * consumers * MSG_KB / 1024.0,
        "at_risk": integral / drain_ms,
    }


def section_prefetch() -> None:
    print("\n== 4. PREFETCH: credit-based flow control, and both of its failure modes ==")
    print(f"  4 consumers drain a 5,000-message backlog. Fetch round trip {RTT_MS:.0f}ms,"
          f" processing {SERVICE_MS:.0f}ms/msg,")
    print(f"  message {MSG_KB:.0f} KB, container heap {HEAP_MB:.0f} MB.")
    print(f"  {'prefetch':>8} {'tput/consumer':>14} {'group tput':>11} {'drain':>8} {'held':>8}"
          f" {'per-consumer split':<26} {'imbal':>6} {'at risk':>9}")
    rows = []
    for p in (1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1000):
        r = prefetch_run(p)
        rows.append(r)
        split = "/".join(f"{g:,}" for g in r["got"])
        print(f"  {p:>8,} {r['per_consumer_tput']:>11,.0f}/s {r['tput']:>9,.0f}/s"
              f" {r['ms']:>7,.0f}ms {r['mem_mb']:>7.1f}MB {split:<26} {r['imbalance']:>5.0%}"
              f" {r['at_risk']:>6,.0f} msg")
    best = min(rows, key=lambda r: r["ms"])
    p1, p1000 = rows[0], rows[-1]
    print(f"\n  Best group throughput at prefetch {best['p']}: {best['tput']:,.0f} msg/s,"
          f" {best['ms']:,.0f}ms to drain.")
    print(f"  prefetch 1     is {p1['ms'] / best['ms']:.2f}x slower -- the consumer spends"
          f" {RTT_MS / (RTT_MS + SERVICE_MS):.0%} of its life waiting on the network.")
    print(f"  prefetch 1,000 is {p1000['ms'] / best['ms']:.2f}x slower -- per-consumer throughput is"
          f" the HIGHEST on the table")
    print(f"                 ({p1000['per_consumer_tput']:,.0f}/s), and the group is the second"
          f" slowest. One consumer claimed")
    print(f"                 {max(p1000['got']):,} of the {sum(p1000['got']):,} messages while three sat"
          f" idle for {p1000['idle_ms']:,.0f}ms combined.")
    print(f"                 Prefetch is not a buffer. It is a CLAIM on work nobody else may do.")
    print("\n  Sizing from Little's Law: a consumer must hold enough in flight to cover the fetch")
    print(f"  round trip. efficiency = P*s / (RTT + P*s), so P = e/(1-e) * RTT/s"
          f"  with RTT/s = {RTT_MS / SERVICE_MS:.0f}:")
    for e in (0.50, 0.90, 0.95, 0.99):
        p = e / (1 - e) * RTT_MS / SERVICE_MS
        print(f"    {e:>5.0%} of peak throughput needs prefetch {p:>6.0f}")
    print("  Past ~40 you are buying <5% more throughput with linear growth in memory,")
    print("  unfairness and redelivery risk. That is the whole sizing argument.")
    big = prefetch_run(10_000, backlog=60_000)
    print(f"\n  The crash cost. A consumer that dies loses every unacked message it holds, and the")
    print(f"  broker redelivers all of them (at-least-once, Lesson 06 - the duplicates are yours):")
    print(f"    {'prefetch':>8} {'worst case':>11} {'repeat work':>12} {'group memory':>13}")
    for r in (rows[5], p1000, big):
        print(f"    {r['p']:>8,} {r['p']:>7,} msg {r['p'] * SERVICE_MS / 1000:>10.2f}s"
              f" {r['mem_mb']:>10.2f} MB"
              + ("   > the heap. Not a crash - an OOM kill." if r["mem_mb"] > HEAP_MB else ""))
    print(f"    At prefetch 10,000 the group needs {big['mem_mb']:.0f} MB against a"
          f" {HEAP_MB:.0f} MB heap, so every consumer is")
    print("    killed, redelivers its 10,000, refills, and is killed again. The prefetch that")
    print("    looked like throughput tuning was a crash loop with a duplicate-message chaser.")


# --- 5 + 6. autoscaling on lag ----------------------------------------------

class NaiveScaler:
    name = "naive: x2 when lag>10s, /2 when lag<1s, no cooldown"

    def __init__(self, interval: float = 10.0, nmax: int = 32) -> None:
        self.interval, self.nmax, self.last = interval, nmax, -1e9

    def decide(self, now, n, per, clag, tlag, rate):
        if now - self.last < self.interval:
            return n
        self.last = now
        if tlag > 10.0:
            return min(self.nmax, n * 2)
        if tlag < 1.0:
            return max(1, n // 2)
        return n


class DampedScaler:
    name = "damped: capacity target + 15% headroom, cooldown, asymmetric deadband"

    def __init__(self, interval: float = 10.0, up_cooldown: float = 20.0,
                 down_cooldown: float = 60.0, step: int = 6, headroom: float = 1.15,
                 drain_target: float = 60.0, deadband: int = 3, nmax: int = 32) -> None:
        self.interval, self.step, self.nmax = interval, step, nmax
        self.up_cd, self.down_cd = up_cooldown, down_cooldown
        self.headroom, self.drain_target, self.deadband = headroom, drain_target, deadband
        self.last_eval = self.last_change = -1e9
        self.cooldown = up_cooldown
        self.down_votes = 0

    def decide(self, now, n, per, clag, tlag, rate):
        if now - self.last_eval < self.interval:
            return n
        self.last_eval = now
        if now - self.last_change < self.cooldown:
            return n
        # keep up with the input, plus enough headroom to drain the backlog in 60s
        want_cap = rate * self.headroom + clag / self.drain_target
        want = max(1, min(self.nmax, math.ceil(want_cap / per)))
        if want > n:                                        # scale up promptly
            self.down_votes = 0
            new, self.cooldown = min(want, n + self.step), self.up_cd
        elif want <= n - self.deadband:                     # scale down reluctantly
            self.down_votes += 1
            if self.down_votes < 2:                         # and only on a second vote
                return n
            self.down_votes = 0
            new, self.cooldown = max(want, n - self.step), self.down_cd
        else:
            self.down_votes = 0
            return n
        self.last_change = now
        return new


def run_autoscaled(scaler, arrival, horizon: float = 300.0, n0: int = 4,
                   per: float = 250.0, partitions: int | None = None) -> dict:
    b = Broker()
    g = Group(n=n0, per=per, partitions=partitions)
    clag: list[float] = []
    tlag: list[float] = []
    ncon: list[float] = []
    recent: deque[float] = deque(maxlen=int(10 / TICK))
    for i in range(int(horizon / TICK)):
        now = i * TICK
        lam = arrival(now)
        recent.append(lam)
        b.publish(now, high=lam * TICK)
        clag.append(b.count_lag)
        tlag.append(b.time_lag(now))
        ncon.append(g.n)
        g.resize(scaler.decide(now, g.n, per, b.count_lag, b.time_lag(now),
                               sum(recent) / len(recent)), now)
        cap = g.capacity(now)
        if poll_due(now):
            b.consume(cap * POLL)
    return {"clag": clag, "tlag": tlag, "n": ncon, "g": g, "b": b}


def step_arrival(t: float) -> float:
    return 800.0 if t < 30 else 2600.0


def section_autoscaling() -> list[dict]:
    print("\n== 5. AUTOSCALING ON LAG: the control loop is the hazard ==")
    print("  Input steps 800/s -> 2,600/s at t=30 and stays. Each consumer drains 250/s, so the")
    print("  group must reach 11 consumers to keep up and more to drain. Every resize costs a")
    print("  5s stop-the-world rebalance in which the group's drain rate is ZERO.")
    out = []
    for scaler in (NaiveScaler(), DampedScaler()):
        r = run_autoscaled(scaler, step_arrival)
        g = r["g"]
        settle = r["tlag"][int(240 / TICK):]
        print(f"\n  {scaler.name}")
        plot("consumers", r["n"], "", ",.0f")
        plot("TIME lag", r["tlag"], "s", ".1f")
        print(f"    resizes {g.events:>2}   rebalance downtime {g.paused:>5.1f}s"
              f" ({100 * g.paused / 300:.0f}% of the run)   final size {g.n:>2}"
              f"   peak time lag {max(r['tlag']):>6.1f}s")
        print(f"    last 60s: time lag min {min(settle):.2f}s / max {max(settle):.2f}s"
              f"   -> {'CONVERGED' if max(settle) < 5 else 'STILL OSCILLATING'}")
        out.append({"name": f"autoscale, {scaler.name.split(':')[0]}",
                    "pc": max(r["clag"]), "pt": max(r["tlag"]),
                    "drain": float("nan"), "shed": 0.0, "lost": 0.0,
                    "end": f"{g.n} consumers, {'converged' if max(settle) < 5 else 'oscillating'}"})
    print("\n  The naive loop is not slow because it scales wrong; it is slow because it scales")
    print("  OFTEN. Doubling and halving on every evaluation keeps the group inside a rebalance,")
    print("  and a group inside a rebalance drains nothing. Scaling was the outage.")

    print("\n== 6. THE PARTITION CEILING: adding consumers stops helping ==")
    print("  Same damped scaler, but the topic has 12 partitions and the input steps to 5,000/s.")
    print("  12 x 250/s = 3,000/s is the maximum drain rate this topic can ever have (Lesson 07).")
    r = run_autoscaled(DampedScaler(), lambda t: 800.0 if t < 30 else 5000.0, partitions=12)
    g = r["g"]
    plot("consumers", r["n"], "", ",.0f")
    plot("COUNT lag", r["clag"], "msgs")
    plot("TIME lag", r["tlag"], "s", ".1f")
    slope = (r["clag"][-1] - r["clag"][int(200 / TICK)]) / (300 - 200)
    print(f"    scaled to {g.n} consumers, {g.assigned} assigned a partition,"
          f" {g.idle} idle with no work to do")
    print(f"    drain rate is pinned at {g.assigned * g.per:,.0f}/s against 5,000/s of arrivals")
    print(f"    count lag still growing at {slope:+,.0f} msg/s at the end of the run"
          f"   peak time lag {max(r['tlag']):.1f}s")
    print(f"    every one of the last resizes bought 0 throughput and cost a 5s rebalance.")
    print("    The fix is not in this lesson: it is repartitioning, or making each message cheaper.")
    out.append({"name": "partition ceiling (12)", "pc": max(r["clag"]), "pt": max(r["tlag"]),
                "drain": float("inf"), "shed": 0.0, "lost": 0.0,
                "end": f"{g.idle} consumers idle, lag growing"})
    return out


# --- 7. load shedding --------------------------------------------------------

def run_shedding(shed_on: bool, horizon: float = 300.0, retention: float = 60.0,
                 hi_rate: float = 640.0, lo_rate: float = 960.0,
                 mu: float = 1000.0, on_at: float = 20.0, off_at: float = 2.0) -> dict:
    b = Broker(retention_s=retention)
    hi_tlag: list[float] = []
    tlag: list[float] = []
    shedding = False
    shed_ticks = 0
    for i in range(int(horizon / TICK)):
        now = i * TICK
        if shed_on:
            t = b.high_time_lag(now)
            if not shedding and t > on_at:
                shedding = True
            elif shedding and t < off_at:
                shedding = False
        if shedding:
            b.shed["low"] += lo_rate * TICK
            shed_ticks += 1
            b.publish(now, high=hi_rate * TICK)
        else:
            b.publish(now, high=hi_rate * TICK, low=lo_rate * TICK)
        b.expire(now)
        hi_tlag.append(b.high_time_lag(now))
        tlag.append(b.time_lag(now))
        if poll_due(now):
            b.consume(mu * POLL)
    return {"b": b, "hi_tlag": hi_tlag, "tlag": tlag,
            "duty": shed_ticks * TICK / horizon}


def section_shedding() -> list[dict]:
    print("\n== 7. LOAD SHEDDING: choose your loss, or retention chooses it for you ==")
    print("  640/s of payment confirmations (HIGH) + 960/s of recommendation updates (LOW)")
    print("  = 1,600/s against 1,000/s of capacity. Broker retention: 60s. Horizon 300s.")
    ctrl = run_shedding(False)
    shed = run_shedding(True)
    out = []
    for label, r in (("no shedding", ctrl), ("shed LOW above 20s HIGH lag", shed)):
        b = r["b"]
        print(f"\n  {label}")
        plot("HIGH tlag", r["hi_tlag"], "s", ".1f")
        print(f"    processed {b.consumed['high'] + b.consumed['low']:>10,.0f}"
              f"  (high {b.consumed['high']:>9,.0f}   low {b.consumed['low']:>9,.0f})")
        print(f"    shed      {b.shed['high'] + b.shed['low']:>10,.0f}"
              f"  (high {b.shed['high']:>9,.0f}   low {b.shed['low']:>9,.0f})"
              f"   deliberate, counted, low value")
        print(f"    EXPIRED   {b.expired['high'] + b.expired['low']:>10,.0f}"
              f"  (high {b.expired['high']:>9,.0f}   low {b.expired['low']:>9,.0f})"
              f"   silent, uncounted, chosen at random")
        print(f"    peak HIGH time lag {max(r['hi_tlag']):>6.1f}s"
              f"   final HIGH time lag {r['hi_tlag'][-1]:>6.2f}s"
              f"   shedding active {r['duty']:>4.0%} of the run")
        print(f"    HIGH stream: {100 * b.consumed['high'] / b.published['high']:>5.1f}% processed,"
              f" {100 * b.expired['high'] / b.published['high']:>5.1f}% deleted by retention")
        out.append({"name": label, "pc": 0.0, "pt": max(r["hi_tlag"]), "drain": float("nan"),
                    "shed": b.shed["high"] + b.shed["low"],
                    "lost": b.expired["high"] + b.expired["low"],
                    "end": f"HIGH tlag {r['hi_tlag'][-1]:.2f}s"})
    lost_hi = ctrl["b"].expired["high"]
    print(f"\n  Read the EXPIRED row twice. Without shedding, retention deleted"
          f" {lost_hi:,.0f} payment")
    print(f"  confirmations -- {100 * lost_hi / ctrl['b'].published['high']:.1f}% of the high-value"
          f" stream -- with no error, no log line, no metric")
    print(f"  except a lag number that had mysteriously STOPPED GROWING. With shedding,"
          f" {shed['b'].expired['high']:,.0f}.")
    tot_c = ctrl["b"].consumed["high"] + ctrl["b"].consumed["low"]
    tot_s = shed["b"].consumed["high"] + shed["b"].consumed["low"]
    print(f"\n  Now the part that surprises people: TOTAL messages processed is"
          f" {tot_c:,.0f} vs {tot_s:,.0f}")
    print(f"  -- identical, because the consumers were saturated either way. Shedding did not")
    print(f"  cost throughput. It re-aimed it: high-priority processed went from"
          f" {ctrl['b'].consumed['high']:,.0f} to")
    print(f"  {shed['b'].consumed['high']:,.0f}"
          f" (+{100 * (shed['b'].consumed['high'] / ctrl['b'].consumed['high'] - 1):.0f}%), paid for with"
          f" {shed['b'].shed['low']:,.0f} recommendation updates dropped on purpose.")
    print("  You never choose whether to lose messages under sustained overload. You only")
    print("  choose whether YOU pick which ones, or the retention window picks for you.")
    return out


# --- 8. summary --------------------------------------------------------------

def section_summary(rows: list[dict]) -> None:
    print("\n== 8. SUMMARY: every scenario, same columns ==")
    print(f"  {'scenario':<28} {'peak count':>11} {'peak time':>9} {'to drain':>9}"
          f" {'shed':>9} {'lost':>8}  final state")
    for r in rows:
        pc = f"{r['pc']:,.0f}" if r["pc"] else "-"
        dr = ("never" if r["drain"] == float("inf")
              else "-" if r["drain"] != r["drain"] else
              hms(r["drain"]) if r["drain"] > 3600 else f"{r['drain']:,.0f}s")
        pt = hms(r["pt"]) if r["pt"] > 3600 else f"{r['pt']:.1f}s"
        print(f"  {r['name']:<28} {pc:>11} {pt:>9} {dr:>9}"
              f" {r['shed']:>9,.0f} {r['lost']:>8,.0f}  {r['end']}")


def main() -> None:
    section_narrative()
    rows = section_burst_vs_sustained()
    section_prefetch()
    rows += section_autoscaling()
    rows += section_shedding()
    section_summary(rows)


if __name__ == "__main__":
    main()
