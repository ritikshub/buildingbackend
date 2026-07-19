"""Connection & resource pooling, built from scratch.

Builds a generic ResourcePool (bounded, LIFO free list, FIFO waiter queue,
checkout timeout, jittered max-lifetime, idle reaping, leak tracking) and then
measures the four things that matter: reuse vs reconnect, the sizing curve,
checkout timeouts under exhaustion, and the async trap.
Companion to docs/en.md (Phase 8, Lesson 12). Standard library only.
Little's Law (L = lambda * W) is Little, Operations Research 9(3), 1961.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import statistics
import sys
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Optional

random.seed(7)


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def pct(values, q: float) -> float:
    """Nearest-rank percentile, same units as `values`."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(q * len(ordered) + 0.9999) - 1))
    return ordered[idx]


def banner(text: str) -> None:
    print(f"\n== {text} ==")


# --------------------------------------------------------------------------
# THE POOL
# --------------------------------------------------------------------------


class PoolTimeout(RuntimeError):
    """No permit became available before the checkout deadline."""


class PoolClosed(RuntimeError):
    """Acquire against a pool that has been shut down."""


@dataclass
class _Entry:
    """One pooled resource plus the bookkeeping the pool keeps about it."""

    resource: Any
    created_at: float
    expires_at: float          # jittered max-lifetime deadline
    returned_at: float = 0.0   # when it last landed on the free list
    uses: int = 0


@dataclass
class Checkout:
    """A resource somebody is holding right now. This is the leak detector."""

    resource: Any
    holder: str
    acquired_at: float
    stack: str = ""

    def age(self) -> float:
        return time.perf_counter() - self.acquired_at


class _Waiter:
    """One parked requester. Direct hand-off is what makes the queue FIFO."""

    __slots__ = ("event", "entry", "granted", "fresh")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.entry: Optional[_Entry] = None
        self.granted = False
        self.fresh = False     # granted an empty slot: build the resource yourself


_NEW = object()   # sentinel from _take_locked(): "you own a free slot"


class ResourcePool:
    """A semaphore over a bag of reusable objects.

    `max_size` permits exist. acquire() takes a permit and hands you an object;
    release() gives back both. Every other feature here — validation, reset,
    recycling, reaping, timeouts, leak tracking — is a rule about what may
    happen between those two moments.
    """

    def __init__(
        self,
        factory: Callable[[], Any],
        *,
        max_size: int,
        min_size: int = 0,
        checkout_timeout: float = 5.0,
        validator: Optional[Callable[[Any], bool]] = None,
        reset: Optional[Callable[[Any], None]] = None,
        closer: Optional[Callable[[Any], None]] = None,
        max_lifetime: Optional[float] = None,
        lifetime_jitter: float = 0.25,
        idle_timeout: Optional[float] = None,
        validate_on_checkout: bool = False,
        track_stacks: bool = False,
        reap_interval: float = 0.05,
        name: str = "pool",
    ) -> None:
        self.name = name
        self._factory = factory
        self._max_size = max_size
        self._checkout_timeout = checkout_timeout
        self._validator = validator
        self._reset = reset
        self._closer = closer
        self._max_lifetime = max_lifetime
        self._jitter = lifetime_jitter
        self._idle_timeout = idle_timeout
        self._validate_on_checkout = validate_on_checkout
        self._track_stacks = track_stacks

        self._lock = threading.Lock()
        self._free: list[_Entry] = []             # LIFO: pop() the hottest
        self._waiters: "deque[_Waiter]" = deque()  # FIFO: popleft() the oldest
        self._checkouts: dict[int, Checkout] = {}  # id(resource) -> Checkout
        self._live: dict[int, _Entry] = {}         # id(resource) -> _Entry
        self._pending_close: list[_Entry] = []
        self._total = 0                            # created, not yet destroyed
        self._in_use = 0
        self._closed = False
        self._started = time.perf_counter()

        # metrics
        self.created_total = 0
        self.destroyed_total = 0
        self.checkouts_total = 0
        self.timeouts_total = 0
        self.validation_failures = 0
        self.recycled_total = 0
        self.reaped_idle_total = 0
        self._waits: "deque[float]" = deque(maxlen=20000)

        self._stop = threading.Event()
        self._reaper: Optional[threading.Thread] = None
        if max_lifetime is not None or idle_timeout is not None:
            self._reaper = threading.Thread(
                target=self._reap_loop, args=(reap_interval,),
                name=f"{name}-reaper", daemon=True)
            self._reaper.start()

        for _ in range(min_size):                  # warm start (min/idle size)
            entry = self._build()
            with self._lock:
                self._total += 1
                entry.returned_at = time.perf_counter()
                self._free.append(entry)

    # -- lifecycle hooks ---------------------------------------------------

    def _build(self) -> _Entry:
        """on-create. Jitter the lifetime so they never all expire together."""
        now = time.perf_counter()
        if self._max_lifetime is None:
            expires = float("inf")
        else:
            expires = now + self._max_lifetime * (
                1.0 + random.uniform(-self._jitter, self._jitter))
        resource = self._factory()
        with self._lock:
            self.created_total += 1
        return _Entry(resource=resource, created_at=now, expires_at=expires)

    def _destroy(self, entry: _Entry) -> None:
        with self._lock:
            self.destroyed_total += 1
        if self._closer is not None:
            with contextlib.suppress(Exception):
                self._closer(entry.resource)

    # -- checkout ----------------------------------------------------------

    def acquire(self, timeout: Optional[float] = None) -> Any:
        limit = self._checkout_timeout if timeout is None else timeout
        start = time.perf_counter()
        deadline = start + limit

        for _ in range(self._max_size + 2):        # bounded revalidation retries
            entry = self._checkout_one(deadline, start)
            if self._validate_on_checkout and self._validator is not None:
                if not self._validator(entry.resource):   # on-checkout hook
                    with self._lock:
                        self.validation_failures += 1
                    self._retire(entry)            # dead: free the slot, retry
                    continue
            entry.uses += 1
            self._waits.append((time.perf_counter() - start) * 1000.0)
            with self._lock:
                self.checkouts_total += 1
                self._live[id(entry.resource)] = entry
                self._checkouts[id(entry.resource)] = Checkout(
                    resource=entry.resource,
                    holder=threading.current_thread().name,
                    acquired_at=time.perf_counter(),
                    stack=self._capture_stack() if self._track_stacks else "")
            return entry.resource
        raise PoolTimeout(f"{self.name}: every resource failed validation")

    def _checkout_one(self, deadline: float, start: float) -> _Entry:
        while True:
            with self._lock:
                if self._closed:
                    raise PoolClosed(f"{self.name} is closed")
                slot = self._take_locked()
                if slot is not None:
                    self._in_use += 1
                    if slot is not _NEW:
                        return slot                # type: ignore[return-value]
                    break                          # build outside the lock
                waiter = _Waiter()
                self._waiters.append(waiter)       # FIFO: oldest served first

            waiter.event.wait(max(0.0, deadline - time.perf_counter()))

            with self._lock:
                if not waiter.granted:             # timed out, or being granted
                    with contextlib.suppress(ValueError):
                        self._waiters.remove(waiter)
                if not waiter.granted:
                    self.timeouts_total += 1
                    waited = (time.perf_counter() - start) * 1000.0
                    self._waits.append(waited)
                    raise PoolTimeout(
                        f"{self.name}: no resource after {waited:.0f} ms "
                        f"(size={self._total}/{self._max_size}, "
                        f"in_use={self._in_use}, waiting={len(self._waiters)})")
                if not waiter.fresh:
                    return waiter.entry            # type: ignore[return-value]
            break                                  # granted an empty slot

        try:
            return self._build()
        except Exception:
            with self._lock:                       # never leak the slot
                self._total -= 1
                self._in_use -= 1
                self._grant_locked()
            raise

    def _take_locked(self):
        """Free list first (LIFO, warm), then spare capacity. None => wait."""
        now = time.perf_counter()
        while self._free:
            entry = self._free.pop()               # LIFO: newest, warmest
            if entry.expires_at <= now:            # max-lifetime recycling
                self.recycled_total += 1
                self._total -= 1
                self._pending_close.append(entry)
                continue
            return entry
        if self._total < self._max_size:
            self._total += 1
            return _NEW
        return None

    # -- return ------------------------------------------------------------

    def release(self, resource: Any, discard: bool = False) -> None:
        with self._lock:
            self._checkouts.pop(id(resource), None)
            entry = self._live.pop(id(resource), None)
        if entry is None:                          # double release, or not ours
            return
        if not discard and self._reset is not None:
            try:
                self._reset(entry.resource)        # on-return hook
            except Exception:
                discard = True
        now = time.perf_counter()
        if not discard and entry.expires_at <= now:
            discard = True
            with self._lock:
                self.recycled_total += 1
        if discard:
            self._retire(entry)
            return
        entry.returned_at = now
        with self._lock:
            self._in_use -= 1
            self._free.append(entry)               # LIFO push
            self._grant_locked()

    def _retire(self, entry: _Entry) -> None:
        with self._lock:
            self._total -= 1
            self._in_use -= 1
            self._grant_locked()
        self._destroy(entry)

    def _grant_locked(self) -> None:
        """Hand resources straight to the head of the wait queue: strict FIFO."""
        while self._waiters:
            slot = self._take_locked()
            if slot is None:
                return
            waiter = self._waiters.popleft()
            self._in_use += 1
            waiter.granted = True
            if slot is _NEW:
                waiter.fresh = True
            else:
                waiter.entry = slot
            waiter.event.set()

    # -- reaping -----------------------------------------------------------

    def _reap_loop(self, interval: float) -> None:
        while not self._stop.wait(interval):
            self.reap()

    def reap(self) -> int:
        """Evict expired and long-idle resources from the free list."""
        now = time.perf_counter()
        doomed: list[_Entry] = []
        with self._lock:
            keep: list[_Entry] = []
            for entry in self._free:
                expired = entry.expires_at <= now
                idle_out = (self._idle_timeout is not None
                            and now - entry.returned_at > self._idle_timeout)
                if expired or idle_out:
                    self._total -= 1
                    self.recycled_total += int(expired)
                    self.reaped_idle_total += int(idle_out and not expired)
                    doomed.append(entry)
                else:
                    keep.append(entry)
            self._free = keep
            doomed.extend(self._pending_close)
            self._pending_close.clear()
        for entry in doomed:
            self._destroy(entry)
        return len(doomed)

    # -- observability -----------------------------------------------------

    def leaked(self, older_than: float) -> list[Checkout]:
        """Checkouts older than any sane request. Monotonic growth == a leak."""
        with self._lock:
            return sorted((c for c in self._checkouts.values()
                           if c.age() > older_than),
                          key=lambda c: c.acquired_at)

    def stats(self) -> dict:
        with self._lock:
            elapsed = max(1e-9, time.perf_counter() - self._started)
            waits = list(self._waits)
            return {
                "size": self._total,
                "max_size": self._max_size,
                "in_use": self._in_use,
                "idle": len(self._free),
                "waiting": len(self._waiters),
                "utilization": self._in_use / self._max_size,
                "checkouts_total": self.checkouts_total,
                "timeouts_total": self.timeouts_total,
                "created_total": self.created_total,
                "created_per_sec": self.created_total / elapsed,
                "recycled_total": self.recycled_total,
                "reaped_idle_total": self.reaped_idle_total,
                "validation_failures": self.validation_failures,
                "wait_p50_ms": pct(waits, 0.50),
                "wait_p99_ms": pct(waits, 0.99),
            }

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            self._closed = True
            doomed, self._free = self._free, []
            doomed.extend(self._pending_close)
            self._pending_close.clear()
            self._total -= len(doomed)
            for waiter in self._waiters:
                waiter.event.set()
            self._waiters.clear()
        for entry in doomed:
            self._destroy(entry)

    @contextlib.contextmanager
    def connection(self, timeout: Optional[float] = None):
        """The only safe way to use a pool: release lives in a `finally`."""
        resource = self.acquire(timeout)
        try:
            yield resource
        except BaseException:
            # An exception may have left the resource mid-protocol. Returning it
            # poisons whoever checks it out next, so throw it away instead.
            self.release(resource, discard=True)
            raise
        else:
            self.release(resource)

    @staticmethod
    def _capture_stack() -> str:
        frames = traceback.extract_stack()[:-2]    # drop acquire + this helper
        tail = frames[-2:]
        return " <- ".join(f"{f.name}():{f.lineno}" for f in reversed(tail))


# --------------------------------------------------------------------------
# The things behind the pool
# --------------------------------------------------------------------------

CONNECT_TCP_MS = 1.5      # one round trip
CONNECT_TLS_MS = 3.0      # two round trips
CONNECT_AUTH_MS = 1.5     # one round trip, plus the server forking a backend
CONNECT_TOTAL_MS = CONNECT_TCP_MS + CONNECT_TLS_MS + CONNECT_AUTH_MS


class Connection:
    """A pretend database connection: expensive to make, cheap to reuse."""

    _seq = 0
    _seq_lock = threading.Lock()

    def __init__(self, setup_ms: float = CONNECT_TOTAL_MS):
        with Connection._seq_lock:
            Connection._seq += 1
            self.cid = Connection._seq
        self.alive = True
        time.sleep(setup_ms / 1000.0)

    def query(self, work_ms: float) -> None:
        if not self.alive:
            raise ConnectionError(f"conn#{self.cid}: server closed the connection")
        time.sleep(work_ms / 1000.0)

    def ping(self) -> bool:
        time.sleep(0.4 / 1000.0)          # SELECT 1 — one extra round trip
        return self.alive

    def close(self) -> None:
        self.alive = False


class SimulatedDownstream:
    """A database with a real capacity limit.

    Up to `cores` concurrent queries run at full speed. Past that each query
    slows proportionally (they are sharing cores) AND superlinearly (lock
    contention, context switching, cache thrash). Modelled contention — not a
    constant delay bolted on.
    """

    def __init__(self, cores: int = 8, service_ms: float = 4.0,
                 thrash: float = 0.06):
        self.cores = cores
        self.service_ms = service_ms
        self.thrash = thrash
        self._lock = threading.Lock()
        self._inflight = 0
        self._samples: list[int] = []

    def execute(self) -> None:
        with self._lock:
            self._inflight += 1
            n = self._inflight
            self._samples.append(n)
        over = max(1.0, n / self.cores)
        elapsed = self.service_ms * over * (1.0 + self.thrash * (over - 1.0))
        time.sleep(elapsed / 1000.0)
        with self._lock:
            self._inflight -= 1

    def mean_inflight(self) -> float:
        return statistics.fmean(self._samples) if self._samples else 0.0


# --------------------------------------------------------------------------
# 2 · WHY POOL AT ALL
# --------------------------------------------------------------------------


def demo_why_pool() -> None:
    banner("2 · WHY POOL AT ALL: THE HANDSHAKE COSTS MORE THAN THE QUERY")
    n_ops, work_ms = 100, 1.0

    t0 = time.perf_counter()
    for _ in range(n_ops):
        conn = Connection()
        conn.query(work_ms)
        conn.close()
    cold = (time.perf_counter() - t0) * 1000.0

    pool = ResourcePool(Connection, max_size=1, min_size=1, name="warm")
    t0 = time.perf_counter()
    for _ in range(n_ops):
        with pool.connection() as conn:
            conn.query(work_ms)
    warm = (time.perf_counter() - t0) * 1000.0
    pool.close()

    print(f"  handshake budget : TCP {CONNECT_TCP_MS} + TLS {CONNECT_TLS_MS} + "
          f"auth {CONNECT_AUTH_MS} = {CONNECT_TOTAL_MS} ms per connect")
    print(f"  the query itself : {work_ms} ms")
    print(f"  {n_ops} ops, reconnect each time : {cold:8.1f} ms "
          f"({cold / n_ops:5.2f} ms/op)")
    print(f"  {n_ops} ops, pooled (1 connect)  : {warm:8.1f} ms "
          f"({warm / n_ops:5.2f} ms/op)")
    print(f"  speedup                          : {cold / warm:8.2f}x   "
          f"{(1 - warm / cold) * 100:.1f}% of the wall clock was handshake")
    print("  server side, unpooled: a fresh backend process per connect, "
          "~5-10 MB each,")
    print("  born and killed around 1 ms of useful work.")


# --------------------------------------------------------------------------
# 3 · THE SIZING CURVE
# --------------------------------------------------------------------------


def drive_closed_loop(pool: ResourcePool, db: SimulatedDownstream,
                      clients: int, duration_s: float):
    """`clients` threads looping request -> response for `duration_s`."""
    stop_at = time.perf_counter() + duration_s
    e2e: list[float] = []
    inside: list[float] = []
    lock = threading.Lock()

    def worker() -> None:
        mine_e: list[float] = []
        mine_i: list[float] = []
        while time.perf_counter() < stop_at:
            t0 = time.perf_counter()
            with pool.connection(timeout=30.0):
                t1 = time.perf_counter()
                db.execute()
                t2 = time.perf_counter()
            mine_e.append((t2 - t0) * 1000.0)
            mine_i.append((t2 - t1) * 1000.0)
        with lock:
            e2e.extend(mine_e)
            inside.extend(mine_i)

    threads = [threading.Thread(target=worker, name=f"client-{i}")
               for i in range(clients)]
    t_start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return e2e, inside, time.perf_counter() - t_start


def demo_sizing_curve() -> dict:
    banner("3 · THE SIZING CURVE: BIGGER IS NOT BETTER, AND IT IS NOT CLOSE")
    cores, spindles, clients = 8, 2, 64
    sizes = [1, 2, 4, 8, 12, 16, 24, 32, 48, 64]
    rows = []
    print(f"  downstream   : {cores} cores, 4.0 ms of work per query, "
          f"superlinear contention past {cores} concurrent")
    print(f"  offered load : {clients} client threads, always trying "
          "(closed loop)\n")
    print("  pool  throughput   e2e p50   e2e p99    db p50    db p99   "
          "mean db   pool wait")
    print("  size      ops/s        ms        ms        ms        ms  "
          "inflight     p99 ms")
    for size in sizes:
        # Two reps, keep the better. Interference from a busy host only ever
        # slows a rep down, so max-of-2 removes downward outliers and keeps the
        # knee stable across runs.
        reps = []
        for _ in range(2):
            db = SimulatedDownstream(cores=cores, service_ms=4.0, thrash=0.06)
            pool = ResourcePool(lambda: Connection(setup_ms=0.2), max_size=size,
                                min_size=size, checkout_timeout=30.0,
                                name=f"sweep{size}")
            e2e, inside, wall = drive_closed_loop(pool, db, clients, 0.55)
            st = pool.stats()
            pool.close()
            reps.append({"size": size, "tput": len(e2e) / wall,
                         "e2e_p50": pct(e2e, 0.50), "e2e_p99": pct(e2e, 0.99),
                         "db_p50": pct(inside, 0.50), "db_p99": pct(inside, 0.99),
                         "inflight": db.mean_inflight(),
                         "wait_p99": st["wait_p99_ms"]})
        row = max(reps, key=lambda r: r["tput"])
        rows.append(row)
        print(f"  {size:4d}  {row['tput']:9.0f}  {row['e2e_p50']:8.1f}  "
              f"{row['e2e_p99']:8.1f}  {row['db_p50']:8.2f}  "
              f"{row['db_p99']:8.2f}  {row['inflight']:8.1f}  "
              f"{row['wait_p99']:10.1f}")

    best = max(rows, key=lambda r: r["tput"])
    # the knee: the SMALLEST pool that already reaches 97% of peak throughput.
    # That is the engineering answer — anything wider is pure latency debt.
    knee = min((r for r in rows if r["tput"] >= 0.97 * best["tput"]),
               key=lambda r: r["size"])
    widest = rows[-1]
    heuristic = cores * 2 + spindles
    print()
    print(f"  peak throughput        : pool={best['size']:<3d} "
          f"{best['tput']:.0f} ops/s")
    print(f"  measured knee (>=97%)  : pool={knee['size']:<3d} "
          f"{knee['tput']:.0f} ops/s, db p99 {knee['db_p99']:.1f} ms "
          "<- the answer")
    print(f"  heuristic (cores*2+sp) : pool={heuristic:<3d} "
          f"= ({cores} x 2) + {spindles}  <- a starting point, not an answer")
    print(f"  widest pool tested     : pool={widest['size']:<3d} "
          f"{widest['tput']:.0f} ops/s, db p99 {widest['db_p99']:.1f} ms")
    print(f"  {widest['size'] // knee['size']}x the knee bought "
          f"{(widest['tput'] / knee['tput'] - 1) * 100:+.0f}% throughput and "
          f"{widest['db_p99'] / knee['db_p99']:.1f}x the database-side p99")
    print("  Little's Law: L = lambda x W. At the optimum the queue sits in "
          "YOUR process,")
    print("  where it is free. Past it the queue moves inside the database, "
          "where it is not.")
    return {"best": best, "knee": knee, "widest": widest, "rows": rows,
            "heuristic": heuristic}


# --------------------------------------------------------------------------
# 4 · EXHAUSTION AND THE CHECKOUT TIMEOUT
# --------------------------------------------------------------------------


def demo_exhaustion() -> dict:
    banner("4 · EXHAUSTION: UNBOUNDED WAIT HANGS, BOUNDED WAIT SHEDS")
    size, work_ms = 4, 25.0
    rate, n, deadline_ms = 400.0, 240, 250.0     # open loop: arrivals do not
    capacity = size / work_ms * 1000.0           # wait for the previous reply

    def run(timeout: float) -> dict:
        pool = ResourcePool(lambda: Connection(setup_ms=0.2), max_size=size,
                            min_size=size, checkout_timeout=timeout, name="exh")
        oks: list[float] = []
        errs: list[float] = []
        lock = threading.Lock()

        def one() -> None:
            t0 = time.perf_counter()
            try:
                with pool.connection() as conn:
                    conn.query(work_ms)
                dt = (time.perf_counter() - t0) * 1000.0
                with lock:
                    oks.append(dt)
            except PoolTimeout:
                dt = (time.perf_counter() - t0) * 1000.0
                with lock:
                    errs.append(dt)

        threads: list[threading.Thread] = []
        start = time.perf_counter()
        for i in range(n):                        # pace the arrivals
            due = start + i / rate
            gap = due - time.perf_counter()
            if gap > 0:
                time.sleep(gap)
            th = threading.Thread(target=one, name=f"req-{i}")
            th.start()
            threads.append(th)
        for th in threads:
            th.join()
        wall = (time.perf_counter() - start) * 1000.0
        pool.close()
        return {"ok": len(oks), "err": len(errs), "wall": wall,
                "p50": pct(oks, 0.5), "p99": pct(oks, 0.99),
                "err_p99": pct(errs, 0.99),
                "goodput": len([d for d in oks if d <= deadline_ms])}

    unbounded = run(30.0)
    bounded = run(0.100)
    print(f"  {n} requests arriving at {rate:.0f} req/s (open loop) into a pool "
          f"of {size} doing {work_ms:.0f} ms of work each")
    print(f"  pool capacity = {size}/{work_ms:.0f}ms = {capacity:.0f} req/s. "
          f"Offered load is {rate / capacity:.1f}x capacity.")
    print(f"  client gives up at {deadline_ms:.0f} ms; anything slower is "
          "wasted work (Lesson 11's goodput)\n")
    print("                     served  shed   p50 ms   p99 ms   shed p99"
          "   wall ms   goodput")
    for label, r in (("unbounded wait ", unbounded),
                     ("100 ms timeout ", bounded)):
        shed_p99 = "        —" if r["err"] == 0 else f"{r['err_p99']:9.1f}"
        print(f"  {label} {r['ok']:8d} {r['err']:5d} {r['p50']:8.1f} "
              f"{r['p99']:8.1f} {shed_p99} {r['wall']:9.1f} "
              f"{r['goodput']:9d}")
    print()
    print(f"  unbounded: all {unbounded['ok']} 'succeeded', but p99 = "
          f"{unbounded['p99']:.0f} ms for {work_ms:.0f} ms of work, and the "
          f"queue drained {unbounded['wall'] - n / rate * 1000:.0f} ms")
    print("             after the last arrival. The longer the overload lasts, "
          "the worse that gets — without bound.")
    print(f"  bounded  : {bounded['err']} requests shed in "
          f"{bounded['err_p99']:.0f} ms — fast, visible, alertable, retryable")
    print(f"  GOODPUT inside the {deadline_ms:.0f} ms deadline: "
          f"{unbounded['goodput']}/{n} unbounded vs {bounded['goodput']}/{n} "
          f"bounded  ({bounded['goodput'] / max(1, unbounded['goodput']):.1f}x)")
    return {"unbounded": unbounded, "bounded": bounded}


# --------------------------------------------------------------------------
# 5 · THE ASYNC TRAP
# --------------------------------------------------------------------------


class AsyncResourcePool:
    """The same idea on one event loop, in 20 lines: a semaphore over a bag."""

    def __init__(self, factory, max_size: int):
        self._factory = factory
        self._sem = asyncio.Semaphore(max_size)
        self._free: list[Any] = []
        self.hold_times: list[float] = []

    @contextlib.asynccontextmanager
    async def connection(self):
        await self._sem.acquire()                          # the permit
        resource = self._free.pop() if self._free else self._factory()  # LIFO
        t0 = time.perf_counter()
        try:
            yield resource
        finally:
            self.hold_times.append((time.perf_counter() - t0) * 1000.0)
            self._free.append(resource)
            self._sem.release()


HTTP_MS, QUERY_MS = 50.0, 5.0


async def _async_trap(pool_size: int, ops: int, concurrency: int,
                      inside: bool) -> dict:
    pool = AsyncResourcePool(lambda: object(), pool_size)
    gate = asyncio.Semaphore(concurrency)

    async def op() -> None:
        async with gate:
            if inside:
                async with pool.connection():
                    await asyncio.sleep(HTTP_MS / 1000.0)   # unrelated I/O!
                    await asyncio.sleep(QUERY_MS / 1000.0)  # the actual query
            else:
                await asyncio.sleep(HTTP_MS / 1000.0)       # do it first
                async with pool.connection():
                    await asyncio.sleep(QUERY_MS / 1000.0)

    t0 = time.perf_counter()
    await asyncio.gather(*(op() for _ in range(ops)))
    wall = time.perf_counter() - t0
    return {"wall_ms": wall * 1000.0, "tput": ops / wall,
            "hold_mean": statistics.fmean(pool.hold_times)}


def demo_async_trap() -> dict:
    banner("5 · THE ASYNC TRAP: AN UNRELATED await INSIDE THE CHECKOUT")
    ops, concurrency, size, target = 160, 80, 8, 1000.0
    bad = asyncio.run(_async_trap(size, ops, concurrency, inside=True))
    good = asyncio.run(_async_trap(size, ops, concurrency, inside=False))
    print(f"  identical work: a {HTTP_MS:.0f} ms HTTP call + a "
          f"{QUERY_MS:.0f} ms query, {ops} ops, {concurrency} concurrent, "
          f"pool_size={size}\n")
    print("                                  hold ms    ops/s   wall ms   "
          "permits for 1000 ops/s")
    print(f"  HTTP call INSIDE the checkout  {bad['hold_mean']:8.1f} "
          f"{bad['tput']:8.0f}  {bad['wall_ms']:8.0f}   "
          f"{target * bad['hold_mean'] / 1000:12.0f}")
    print(f"  HTTP call BEFORE the checkout  {good['hold_mean']:8.1f} "
          f"{good['tput']:8.0f}  {good['wall_ms']:8.0f}   "
          f"{target * good['hold_mean'] / 1000:12.0f}")
    mult = bad["hold_mean"] / good["hold_mean"]
    print()
    print(f"  hold-time multiple {mult:.1f}x   throughput multiple "
          f"{good['tput'] / bad['tput']:.1f}x")
    print("  The await did not make the query slower. It made you hold the "
          f"permit {mult:.0f}x longer,")
    print("  and by Little's Law permits = throughput x hold time.")
    return {"bad": bad, "good": good, "mult": mult}


# --------------------------------------------------------------------------
# 6 · LEAKS
# --------------------------------------------------------------------------


def demo_leaks() -> dict:
    banner("6 · LEAKS: THE CHECKOUT THAT NEVER CAME BACK")
    size = 4
    pool = ResourcePool(lambda: Connection(setup_ms=0.2), max_size=size,
                        min_size=size, checkout_timeout=0.15,
                        track_stacks=True, name="leaky")

    def leaky_request(i: int) -> None:
        conn = pool.acquire()                  # no `with`, no `finally`
        conn.query(1.0)
        if i % 2 == 0:
            raise ValueError("row not found")  # early exit: conn never returns
        pool.release(conn)

    leaked_n = timeouts_seen = 0
    for i in range(10):
        try:
            leaky_request(i)
        except ValueError:
            leaked_n += 1
        except PoolTimeout as exc:
            timeouts_seen += 1
            if timeouts_seen == 1:
                print(f"  request {i}: PoolTimeout — {exc}")
    print(f"  {leaked_n} of 10 requests raised between acquire() and release(); "
          f"the next {timeouts_seen} could not get a connection at all")
    st = pool.stats()
    print(f"  pool now: in_use={st['in_use']}/{st['max_size']}  "
          f"idle={st['idle']}  checkout timeouts={st['timeouts_total']}  "
          f"utilization={st['utilization']:.0%}")
    print("  this looks exactly like a pool that is too small — "
          "except it never recovers")
    time.sleep(0.06)
    print("\n  leak detector (checkouts held longer than 50 ms):")
    for c in pool.leaked(0.050):
        print(f"    conn#{c.resource.cid}  held {c.age() * 1000:7.1f} ms  by "
              f"{c.holder:<12s} acquired at {c.stack}")
    pool.close()

    fixed = ResourcePool(lambda: Connection(setup_ms=0.2), max_size=size,
                         min_size=size, checkout_timeout=0.15, name="fixed")

    def safe_request(i: int) -> None:
        with fixed.connection() as conn:        # release lives in `finally`
            conn.query(1.0)
            if i % 2 == 0:
                raise ValueError("row not found")

    errors = 0
    for i in range(10):
        try:
            safe_request(i)
        except ValueError:
            errors += 1
    st2 = fixed.stats()
    print(f"\n  same workload with `with`: {errors} exceptions raised, "
          f"in_use={st2['in_use']}, idle={st2['idle']}, "
          f"timeouts={st2['timeouts_total']}")
    print(f"  created={st2['created_total']}, destroyed={fixed.destroyed_total} "
          "— the context manager discards a connection an exception may have")
    print("  left mid-protocol, and the pool rebuilds it on demand.")
    fixed.close()
    return {"leaked": leaked_n, "timeouts": st["timeouts_total"]}


# --------------------------------------------------------------------------
# 7 · STALENESS, VALIDATION AND JITTERED RECYCLING
# --------------------------------------------------------------------------


def demo_staleness() -> dict:
    banner("7 · STALENESS: THE POOL WILL HAND YOU A CORPSE")
    size, n = 6, 60

    def run(validate: bool) -> dict:
        pool = ResourcePool(lambda: Connection(setup_ms=0.2), max_size=size,
                            min_size=size, validator=lambda c: c.ping(),
                            validate_on_checkout=validate,
                            checkout_timeout=1.0, name="stale")
        with pool._lock:      # a NAT/firewall/failover kills every idle conn
            for entry in pool._free:
                entry.resource.alive = False
        fails, lat = 0, []
        for _ in range(n):
            t0 = time.perf_counter()
            try:
                with pool.connection() as conn:
                    conn.query(1.0)
            except ConnectionError:
                fails += 1
            lat.append((time.perf_counter() - t0) * 1000.0)
        st = pool.stats()
        pool.close()
        return {"fails": fails, "mean_ms": statistics.fmean(lat),
                "vfail": st["validation_failures"],
                "created": st["created_total"],
                "created_per_sec": st["created_per_sec"]}

    off = run(False)
    on = run(True)
    print(f"  {size} pooled connections, all killed server-side, "
          f"then {n} requests\n")
    print(f"  validate_on_checkout=False : {off['fails']:2d}/{n} failed with "
          f"ConnectionError, mean {off['mean_ms']:.2f} ms/req")
    print(f"  validate_on_checkout=True  : {on['fails']:2d}/{n} failed, "
          f"mean {on['mean_ms']:.2f} ms/req, "
          f"{on['vfail']} corpses detected and replaced")
    print(f"  cost of SELECT 1           : "
          f"{on['mean_ms'] - off['mean_ms']:+.2f} ms per request "
          f"({(on['mean_ms'] / off['mean_ms'] - 1) * 100:+.0f}%) — "
          "one extra round trip, every checkout")
    print(f"  connections created        : {off['created']} either way — "
          "validation does not create more connections, it just replaces the")
    print("                               dead ones before a user request "
          "touches them")
    print("  (watch connections-created/s in production: a sustained high rate "
          "means you are churning, not pooling)")

    jitter = ResourcePool(lambda: Connection(setup_ms=0.2), max_size=8,
                          min_size=8, max_lifetime=1.0, lifetime_jitter=0.25,
                          idle_timeout=0.2, name="jit")
    with jitter._lock:
        base = min(e.created_at for e in jitter._free)
        spread = sorted(e.expires_at - base for e in jitter._free)
    print(f"\n  max_lifetime=1.0s jitter=0.25 -> 8 connections expire across "
          f"{spread[0]:.2f}..{spread[-1]:.2f} s")
    print("  without jitter all 8 expire at exactly 1.00 s: a reconnect "
          "stampede one lifetime after every deploy")
    time.sleep(0.4)
    stj = jitter.stats()
    print(f"  idle_timeout=0.2s: the background reaper evicted "
          f"{stj['reaped_idle_total']} idle connections; pool shrank to "
          f"{stj['size']}")
    jitter.close()
    return {"off": off, "on": on}


# --------------------------------------------------------------------------
# 8 · THE MULTIPLICATION
# --------------------------------------------------------------------------


def demo_multiplication() -> None:
    banner("8 · THE MULTIPLICATION NOBODY WRITES DOWN")
    max_connections, reserved = 200, 8
    budget = max_connections - reserved
    print(f"  postgres max_connections = {max_connections}, {reserved} reserved "
          f"for superuser/monitoring -> app budget {budget}\n")
    print("  service                  pool  workers  replicas    total   verdict")
    configs = [
        ("api (steady state)", 20, 4, 8),
        ("api (autoscaled peak)", 20, 4, 20),
        ("async worker fleet", 10, 2, 6),
        ("cron + migrations", 5, 1, 2),
    ]
    for name, pool, workers, replicas in configs:
        total = pool * workers * replicas
        verdict = "fits" if total <= budget else f"OVER by {total - budget}"
        print(f"  {name:<22s} {pool:6d} {workers:8d} {replicas:9d} "
              f"{total:8d}   {verdict}")
    peak = 20 * 4 * 20 + 10 * 2 * 6 + 5 * 1 * 2
    print(f"\n  peak fleet = (20x4x20) + (10x2x6) + (5x1x2) = {peak} "
          f"vs budget {budget}  ->  {peak / budget:.1f}x OVER")
    print("  Nobody typed 1730 anywhere. Every worker process gets its OWN "
          "pool — a pool")
    print("  cannot be shared across processes — and the autoscaler "
          "multiplies it at 3am.")
    fits = budget // (4 * 20)
    print(f"\n  fix A: pool_size <= {fits} per process "
          f"(budget {budget} / (4 workers x 20 peak replicas))")
    print(f"  fix B: PgBouncer in transaction mode — {peak} client connections "
          f"multiplexed onto ~{budget} server backends")


# --------------------------------------------------------------------------


def main() -> int:
    print("Connection & resource pooling — measured, not asserted")

    banner("1 · THE POOL: A SEMAPHORE OVER A BAG OF REUSABLE OBJECTS")
    demo = ResourcePool(lambda: Connection(setup_ms=0.2), max_size=3,
                        min_size=2, checkout_timeout=0.2, name="demo")
    with demo.connection(), demo.connection():
        s = demo.stats()
        print(f"  two checked out : in_use={s['in_use']}/3  idle={s['idle']}  "
              f"utilization={s['utilization']:.0%}")
    s = demo.stats()
    print(f"  both returned   : in_use={s['in_use']}/3  idle={s['idle']}  "
          f"utilization={s['utilization']:.0%}")
    print(f"  stats(): checkouts={s['checkouts_total']} "
          f"created={s['created_total']} timeouts={s['timeouts_total']} "
          f"recycled={s['recycled_total']} "
          f"wait_p50={s['wait_p50_ms']:.2f}ms wait_p99={s['wait_p99_ms']:.2f}ms")
    demo.close()

    demo_why_pool()
    demo_sizing_curve()
    demo_exhaustion()
    demo_async_trap()
    demo_leaks()
    demo_staleness()
    demo_multiplication()
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
