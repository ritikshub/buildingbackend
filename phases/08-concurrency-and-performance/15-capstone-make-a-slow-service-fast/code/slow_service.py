"""
The inherited service: correct, ~12 requests/second, and seven flaws.

Builds ONE request handler whose every pathology sits behind a Stage flag, so the
same load harness can measure every version of the service without the code
drifting between runs.  Companion to docs/en.md (Phase 8, Lesson 15).

All "I/O" is time.sleep, so the whole investigation runs anywhere with no network
dependency.  The lost-update race in Stage 3 has a DELIBERATELY WIDENED window
(RACE_WINDOW_S below) so it reproduces on every run instead of once a fortnight.
"""

from __future__ import annotations

import queue
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field

perf = time.perf_counter

# --------------------------------------------------------------------------- #
# Simulated upstream costs, in milliseconds.  These are the numbers a real
# profile of this service would have shown; everything else is derived.
# --------------------------------------------------------------------------- #
CONNECT_MS = 3.0      # TCP + TLS + auth handshake, paid per connection
PROFILE_MS = 5.0      # GET /profile
SETTINGS_MS = 4.0     # GET /settings
LIST_MS = 6.0         # GET /items  -> returns N_ITEMS ids
ITEM_MS = 2.2         # GET /item/{id}   <- the N+1
BATCH_MS = 4.0        # POST /items:batch -> all N_ITEMS at once
N_ITEMS = 8
CPU_ROUNDS = 4000     # pure-Python scoring work; ~3.2 ms per request

# The read-modify-write window in CallStats.record().  A real one is ~50 ns wide
# and loses an update maybe once a day.  time.sleep(0) forces the interpreter to
# hand the GIL to another thread mid-update, so it loses one on every run.
RACE_WINDOW_S = 0.0

# The service level objective the whole investigation optimises toward.
SLO_RATE = 40.0       # requests/second the product actually receives
SLO_MS = 250.0        # 99% of them must finish inside this
SLO_ERR_PCT = 1.0     # ...with this error budget

WATCHED: set[int] = set()   # thread idents the sampling profiler should look at


# --------------------------------------------------------------------------- #
# 1 · The primitives.  Every one of these is named so a sampling profiler can
#     attribute a stack to it (see profiler.py's LABELS).
# --------------------------------------------------------------------------- #
def _sleep_io(seconds: float, abort: threading.Event | None = None) -> None:
    """The ONLY place simulated I/O time passes. Blocked stacks bottom out here."""
    if abort is not None and abort.is_set():
        return                       # harness pulled the plug: unwind immediately
    time.sleep(seconds)


def _widen() -> None:
    """Force a GIL hand-off inside a read-modify-write, so the lost update is
    reproducible instead of lucky. A real window is a few nanoseconds wide and
    a real system hits it a few times a day."""
    time.sleep(RACE_WINDOW_S)


def _queue_get(q: queue.Queue):
    """Named wrapper so 'blocked waiting for work' is distinguishable from 'busy'."""
    return q.get()


def _acquire_global(lock: threading.Lock, samples: list, slock: threading.Lock) -> None:
    """Acquire the one global lock, recording how long we queued for it."""
    t0 = perf()
    lock.acquire()
    waited = perf() - t0
    with slock:
        samples.append(waited)


def score_items(payload, rounds: int = CPU_ROUNDS) -> int:
    """The one genuinely CPU-bound step on the request path: an FNV-style score.

    Pure Python on purpose — it holds the GIL (Global Interpreter Lock, the mutex
    that lets only one thread execute Python bytecode at a time), so no number of
    threads makes it parallel.
    """
    h = 0x811C9DC5
    for _ in range(rounds):
        for b in payload:
            h = ((h ^ b) * 16777619) & 0xFFFFFFFF
    return h


# --------------------------------------------------------------------------- #
# 2 · The simulated dependency.  Its per-call latency degrades past a knee, the
#     way a real database does when you point too many connections at it.  This
#     is what makes "just raise the pool size" a measurable mistake.
# --------------------------------------------------------------------------- #
class Upstream:
    """Past KNEE concurrent calls its latency grows in proportion to the load,
    which is what a saturated server does: its throughput is pinned at
    KNEE/service_time and every extra caller only adds queue time. Point more
    concurrency at it and you buy latency, for yourself and for everyone else
    who uses it."""

    KNEE = 32          # concurrent calls it serves at full speed

    def __init__(self) -> None:
        self.inflight = 0
        self.peak = 0
        self._lock = threading.Lock()

    def call(self, ms: float, abort: threading.Event | None) -> None:
        with self._lock:
            self.inflight += 1
            n = self.inflight
            if n > self.peak:
                self.peak = n
        try:
            factor = max(1.0, n / self.KNEE)
            _sleep_io(ms / 1000.0 * factor, abort)
        finally:
            with self._lock:
                self.inflight -= 1


class Conn:
    __slots__ = ("cid",)

    def __init__(self, cid: int) -> None:
        self.cid = cid


def connect_upstream(abort) -> Conn:
    """No pool: pay the whole handshake on every single call."""
    _sleep_io(CONNECT_MS / 1000.0, abort)
    return Conn(-1)


class ConnPool:
    """Fixed-size pool of pre-warmed connections. Blocks when all are checked out."""

    def __init__(self, size: int) -> None:
        self.size = size
        self._free: queue.LifoQueue = queue.LifoQueue()
        for i in range(size):
            self._free.put(Conn(i))
        self.waits: list[float] = []
        self._wl = threading.Lock()

    @contextmanager
    def lease(self, abort):
        t0 = perf()
        conn = self._free.get()
        waited = perf() - t0
        with self._wl:
            self.waits.append(waited)
        try:
            yield conn
        finally:
            self._free.put(conn)


# --------------------------------------------------------------------------- #
# 3 · The two pieces of shared mutable state, and the race that lives in one.
# --------------------------------------------------------------------------- #
class CallStats:
    """Counts upstream calls. Read-modify-write, unguarded unless safe=True.

    In the baseline this is safe by ACCIDENT: the global request lock means only
    one thread is ever inside it. Stage 3 removes that accident.
    """

    def __init__(self, safe: bool) -> None:
        self.safe = safe
        self.calls = 0
        self.bytes = 0
        self.true_calls = 0          # ground truth, always guarded
        self._lock = threading.Lock()
        self._truth = threading.Lock()

    def record(self, nbytes: int) -> None:
        with self._truth:
            self.true_calls += 1
        if self.safe:
            with self._lock:            # the fix: make the RMW atomic
                tmp = self.calls
                _widen()
                self.calls = tmp + 1
                self.bytes += nbytes
        else:
            tmp = self.calls            # read  ─┐
            _widen()                    #        ├─ another thread can land here
            self.calls = tmp + 1        # write ─┘  and its increment is lost
            self.bytes += nbytes


class Index:
    """The hot in-memory index every request touches, sharded into `stripes` maps.

    stripes=1 is the original: one map, one lock, everybody queues.
    """

    def __init__(self, stripes: int) -> None:
        self.stripes = stripes
        self._locks = [threading.Lock() for _ in range(stripes)]
        self._maps: list[dict] = [{} for _ in range(stripes)]
        self._counts = [0] * stripes

    def record(self, key: int, score: int) -> None:
        s = key % self.stripes
        with self._locks[s]:
            self._maps[s][key] = score
            self._counts[s] += 1

    def total(self) -> int:
        return sum(self._counts)


# --------------------------------------------------------------------------- #
# 4 · The CPU offload (a process pool dodges the GIL; a thread pool cannot).
# --------------------------------------------------------------------------- #
_CPU_POOL: ProcessPoolExecutor | None = None
_CPU_POOL_LOCK = threading.Lock()


def cpu_pool(workers: int = 4) -> ProcessPoolExecutor:
    global _CPU_POOL
    with _CPU_POOL_LOCK:
        if _CPU_POOL is None:
            _CPU_POOL = ProcessPoolExecutor(max_workers=workers)
            list(_CPU_POOL.map(score_items, [(1,)] * workers))   # fork + warm
    return _CPU_POOL


def shutdown_cpu_pool() -> None:
    global _CPU_POOL
    with _CPU_POOL_LOCK:
        if _CPU_POOL is not None:
            _CPU_POOL.shutdown(wait=True)
            _CPU_POOL = None


# --------------------------------------------------------------------------- #
# 5 · The stage flags and the request.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Stage:
    name: str
    batch: bool = False          # 2: one call for all items instead of N+1
    concurrent: bool = False     # 3: overlap the three independent calls
    race_fixed: bool = False     # 3b: make CallStats.record atomic
    narrow_lock: bool = False    # 4: shrink + shard the critical section
    pool_size: int = 0           # 5: 0 = connect per call
    offload_cpu: bool = False    # 6: score_items -> process pool
    workers: int = 24
    bounded: bool = False        # 8: bounded queue + deadline-aware shedding
    queue_max: int = 96
    deadline_ms: float = SLO_MS

    def calls_per_request(self) -> int:
        return 4 if self.batch else 3 + N_ITEMS


@dataclass
class Request:
    i: int
    key: int
    ids: tuple
    intended: float = 0.0
    work_start: float = 0.0     # set once the handler owns the global lock


@dataclass
class Sample:
    latency_ms: float      # from INTENDED arrival — the number the user feels
    service_ms: float      # from lock-acquired to done — what a naive timer sees
    done_at: float = 0.0   # absolute completion time, for goodput-over-time


# --------------------------------------------------------------------------- #
# 6 · The service.
# --------------------------------------------------------------------------- #
class Service:
    def __init__(self, stage: Stage) -> None:
        self.stage = stage
        self.q: queue.Queue = queue.Queue(maxsize=stage.queue_max if stage.bounded else 0)
        self.up = Upstream()
        self.index = Index(16 if stage.narrow_lock else 1)
        self.stats = CallStats(safe=stage.race_fixed)
        self.pool = ConnPool(stage.pool_size) if stage.pool_size else None
        self.fan = None
        if stage.concurrent:
            self.fan = ThreadPoolExecutor(
                max_workers=max(12, stage.workers * 3),
                thread_name_prefix="fan",
                initializer=lambda: WATCHED.add(threading.get_ident()),
            )
        self.glock = threading.Lock()
        self.lock_waits: list[float] = []
        self._lw = threading.Lock()
        self.abort = threading.Event()
        self.count_calls = False
        self.call_counts: dict[str, int] = {}
        self._cc = threading.Lock()

        self.samples: list[Sample] = []
        self.shed = 0
        self.expired = 0
        self.inflight = 0
        self.inflight_peak = 0
        self.aborted = 0
        self.finished = 0
        self._rl = threading.Lock()
        self.threads: list[threading.Thread] = []

    # -- one upstream call -------------------------------------------------- #
    def _upstream(self, ms: float, label: str):
        self.stats.record(64)            # count it on the way IN, like real code
        if self.pool is not None:
            with self.pool.lease(self.abort):
                self.up.call(ms, self.abort)
        else:
            connect_upstream(self.abort)
            self.up.call(ms, self.abort)
        if self.count_calls:
            with self._cc:
                self.call_counts[label] = self.call_counts.get(label, 0) + 1
                self.call_counts["connect"] = self.call_counts.get("connect", 0) + (
                    0 if self.pool is not None else 1
                )
        return label

    # Named wrappers: a sampling profiler attributes stacks by function name.
    def fetch_profile(self):
        return self._upstream(PROFILE_MS, "GET /profile")

    def fetch_settings(self):
        return self._upstream(SETTINGS_MS, "GET /settings")

    def fetch_list(self):
        return self._upstream(LIST_MS, "GET /items")

    def fetch_item(self, item_id):
        return self._upstream(ITEM_MS, "GET /item/{id}")

    def fetch_items_batch(self, ids):
        return self._upstream(BATCH_MS, "POST /items:batch")

    # -- the handler -------------------------------------------------------- #
    def handle(self, req: Request) -> int:
        st = self.stage
        if not st.narrow_lock:
            _acquire_global(self.glock, self.lock_waits, self._lw)
        req.work_start = perf()      # a naive in-service timer starts HERE
        try:
            if st.concurrent:
                futs = (
                    self.fan.submit(self.fetch_profile),
                    self.fan.submit(self.fetch_settings),
                    self.fan.submit(self.fetch_list),
                )
                for f in futs:
                    f.result()
            else:
                self.fetch_profile()
                self.fetch_settings()
                self.fetch_list()

            if st.batch:
                self.fetch_items_batch(req.ids)
            else:
                for item_id in req.ids:          # <- N+1: one call per item
                    self.fetch_item(item_id)

            if st.bounded and perf() - req.intended > st.deadline_ms / 1000.0:
                raise Expired()                  # deadline check before CPU work

            if st.offload_cpu:
                score = cpu_pool().submit(score_items, req.ids).result()
            else:
                score = score_items(req.ids)

            self.index.record(req.key, score)
        finally:
            if not st.narrow_lock:
                self.glock.release()
        return score

    # -- worker loop -------------------------------------------------------- #
    def _worker(self) -> None:
        WATCHED.add(threading.get_ident())
        while True:
            req = _queue_get(self.q)
            if req is None:
                return
            deq = perf()
            st = self.stage
            with self._rl:
                self.inflight += 1
                if self.inflight > self.inflight_peak:
                    self.inflight_peak = self.inflight
            try:
                if st.bounded and deq - req.intended > st.deadline_ms / 1000.0:
                    raise Expired()              # already too late: don't do the work
                self.handle(req)
                done = perf()
                if self.abort.is_set():
                    self._bump("aborted")
                else:
                    with self._rl:
                        self.samples.append(
                            Sample((done - req.intended) * 1000.0,
                               (done - req.work_start) * 1000.0, done)
                        )
                        self.finished += 1
            except Expired:
                self._bump("expired")
            except Exception:
                self._bump("aborted")
            finally:
                with self._rl:
                    self.inflight -= 1

    def _bump(self, what: str) -> None:
        with self._rl:
            setattr(self, what, getattr(self, what) + 1)
            self.finished += 1

    # -- lifecycle ---------------------------------------------------------- #
    def start(self) -> None:
        for i in range(self.stage.workers):
            t = threading.Thread(target=self._worker, name=f"svc-{i}", daemon=True)
            t.start()
            self.threads.append(t)

    def drain(self, expected: int, budget: float) -> bool:
        end = perf() + budget
        while perf() < end:
            with self._rl:
                if self.finished >= expected:
                    return True
            time.sleep(0.002)
        self.abort.set()                    # unwind everything still in flight
        end2 = perf() + 1.5
        while perf() < end2:
            with self._rl:
                if self.finished >= expected:
                    break
            time.sleep(0.002)
        return False

    def stop(self) -> None:
        for _ in self.threads:
            self.q.put(None)
        for t in self.threads:
            t.join(timeout=1.0)
        if self.fan is not None:
            self.fan.shutdown(wait=False, cancel_futures=True)


class Expired(Exception):
    """Request abandoned because its deadline had already passed."""
