#!/usr/bin/env python3
"""
Deadlock, livelock and starvation — reproduced, diagnosed and fixed, by hand.

Companion to docs/en.md (Phase 8, Lesson 10). Reproduces an ABBA deadlock
deterministically and dumps the stuck threads' stacks; fixes it with a total lock
order and measures the cost; builds a wait-for graph deadlock detector with DFS
cycle detection (a miniature of the detector in PostgreSQL/InnoDB); runs the
dining philosophers four ways, each fix breaking a different one of the four
Coffman conditions (Coffman, Elphick & Shoshani, "System Deadlocks", ACM
Computing Surveys 3(2), 1971); demonstrates livelock and its cure, randomised
backoff; and measures lock unfairness against a FIFO ticket lock.

EVERY hanging demo runs in daemon threads behind a watchdog. This program always
terminates and always exits 0.  Run:  python3 deadlock.py
"""

from __future__ import annotations

import os
import random
import sys
import threading
import time
import traceback

SEED = 20260718
DEADLOCK_COST: dict[str, float] = {"cpu": 0.0, "wall": 0.0}   # filled in by section 1


# ─── Small helpers shared by every section ────────────────────────────────────

def banner(text: str) -> None:
    print(f"\n== {text} ==")


def spin(seconds: float) -> None:
    """Burn CPU for `seconds`. Unlike sleep(), this shows up as CPU time."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pass


def dump_thread_stacks(threads, depth: int = 2) -> None:
    """Print where each thread is stuck — exactly what a production thread dump gives you.

    sys._current_frames() maps thread id -> its current frame. A thread blocked in
    lock.acquire() is inside a C call, so its innermost *Python* frame is the very
    line that asked for the lock. That line is the diagnosis.
    """
    frames = sys._current_frames()
    for th in threads:
        frame = frames.get(th.ident)
        if frame is None:
            continue
        print(f"    Thread {th.name!r} — alive={th.is_alive()}, using no CPU:")
        for fr in traceback.extract_stack(frame)[-depth:]:
            where = f"{os.path.basename(fr.filename)}:{fr.lineno} in {fr.name}()"
            print(f"      {where}")
            print(f"          {(fr.line or '').strip()}")


class Account:
    """A bank account guarded by its own lock — the finer-grained locking of Lesson 9."""

    def __init__(self, oid: int, name: str, balance: int) -> None:
        self.oid = oid
        self.name = name
        self.balance = balance
        self.lock = threading.Lock()

    def __repr__(self) -> str:
        return f"Account({self.name})"


# ─── 1 · ABBA: two threads, two locks, opposite order ─────────────────────────

def transfer_naive(src: Account, dst: Account, amount: int, hold: float) -> None:
    """Lock the source, then the destination. Reads correctly. Deadlocks in pairs."""
    with src.lock:
        time.sleep(hold)              # any real work here; the sleep just makes it certain
        with dst.lock:                # <- both threads park here, forever
            src.balance -= amount
            dst.balance += amount


def demo_abba_deadlock() -> float:
    banner("1 · ABBA DEADLOCK: THE SAME CODE, TWO DIRECTIONS, NO ERROR")
    a = Account(1, "acct-A", 1000)
    b = Account(2, "acct-B", 1000)

    t1 = threading.Thread(target=transfer_naive, args=(a, b, 100, 0.05),
                          name="transfer-A->B", daemon=True)
    t2 = threading.Thread(target=transfer_naive, args=(b, a, 100, 0.05),
                          name="transfer-B->A", daemon=True)

    started, cpu0 = time.monotonic(), time.process_time()
    t1.start()
    t2.start()
    WATCHDOG = 1.0
    t1.join(timeout=WATCHDOG)
    t2.join(timeout=0.05)
    elapsed = time.monotonic() - started
    DEADLOCK_COST["cpu"] = time.process_time() - cpu0
    DEADLOCK_COST["wall"] = elapsed

    stuck = [t for t in (t1, t2) if t.is_alive()]
    if not stuck:
        print("  (no deadlock this run — the interleaving did not happen)")
        return elapsed

    print(f"  watchdog fired: still blocked {elapsed:.2f}s after start —"
          f" {len(stuck)}/2 threads never returned (they never will).")
    print("  No exception was raised. No log line was written. Nothing crashed.")
    print("  Balances are unchanged and both transfers are lost:"
          f" {a.name}={a.balance} {b.name}={b.balance}")
    print("  A thread dump is the only evidence that exists:")
    dump_thread_stacks(stuck)
    print("  Read it: both threads are on the SAME line — the second acquisition —")
    print("  and each one holds the lock the other is asking for. That is the cycle.")
    return elapsed


# ─── 2 · The fix: a total order over locks, and what it costs ─────────────────

def transfer_sorted(src: Account, dst: Account, amount: int) -> None:
    """Always take the lower-id lock first. Circular wait is impossible by construction."""
    first, second = sorted((src, dst), key=lambda acct: acct.oid)
    with first.lock:
        with second.lock:
            src.balance -= amount
            dst.balance += amount


def transfer_compared(src: Account, dst: Account, amount: int) -> None:
    """Identical guarantee, one comparison instead of a sort + key lambda."""
    first, second = (src, dst) if src.oid < dst.oid else (dst, src)
    with first.lock:
        with second.lock:
            src.balance -= amount
            dst.balance += amount


def _run_transfer_workload(accounts, n_threads, per_thread, mode: str):
    """`mode`: 'one-way' (deadlock-free by luck), 'sorted', or 'compared'."""
    done = [0] * n_threads

    def worker(idx: int) -> None:
        rng = random.Random(SEED + idx)
        n = len(accounts)
        for _ in range(per_thread):
            i = rng.randrange(n)
            j = rng.randrange(n)
            if i == j:
                continue
            if mode == "sorted":
                transfer_sorted(accounts[i], accounts[j], 1)
            elif mode == "compared":
                transfer_compared(accounts[i], accounts[j], 1)
            else:
                lo, hi = (i, j) if i < j else (j, i)   # never reverses: cannot deadlock
                src, dst = accounts[lo], accounts[hi]
                with src.lock:
                    with dst.lock:
                        src.balance -= 1
                        dst.balance += 1
            done[idx] += 1

    threads = [threading.Thread(target=worker, args=(k,), name=f"w{k}", daemon=True)
               for k in range(n_threads)]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20.0)
    elapsed = time.monotonic() - t0
    return elapsed, sum(done), [t for t in threads if t.is_alive()]


def _bench_ordering(mode: str, iters: int) -> float:
    """Single-threaded cost of one two-lock transfer. No contention, so no scheduler noise."""
    a, b = Account(0, "a", 0), Account(1, "b", 0)
    t0 = time.perf_counter()
    for k in range(iters):
        src, dst = (a, b) if k & 1 else (b, a)     # alternate direction, as real traffic does
        if mode == "unordered":                    # the code from section 1: unsafe
            first, second = src, dst
        elif mode == "sorted":
            first, second = sorted((src, dst), key=lambda acct: acct.oid)
        else:
            first, second = (src, dst) if src.oid < dst.oid else (dst, src)
        with first.lock:
            with second.lock:
                src.balance -= 1
                dst.balance += 1
    return time.perf_counter() - t0


def demo_lock_ordering() -> None:
    banner("2 · LOCK ORDERING: THE FIX, AND WHAT IT COSTS")
    N_ACCTS, N_THREADS, PER_THREAD = 6, 8, 25_000
    total = N_ACCTS * 1000

    accounts = [Account(i, f"acct-{i}", 1000) for i in range(N_ACCTS)]
    el, n, alive = _run_transfer_workload(accounts, N_THREADS, PER_THREAD, "compared")
    conserved = sum(a.balance for a in accounts)
    print(f"  SAFETY  {N_THREADS} threads x {PER_THREAD:,} attempts over {N_ACCTS} accounts,"
          " every direction:")
    print(f"    {n:,} transfers in {el:.2f}s = {n / el:,.0f}/s"
          f"   deadlocks: {len(alive)}   money conserved: {conserved}/{total}"
          f" -> {conserved == total}")

    ITERS, REPS = 250_000, 3
    print(f"  COST    one thread, {ITERS:,} two-lock transfers, best of {REPS}:")
    best = {}
    for _ in range(REPS):
        for mode in ("unordered", "sorted", "compared"):   # interleaved: drift hits all three
            t = _bench_ordering(mode, ITERS)
            best[mode] = min(best.get(mode, float("inf")), t)
    base = best["unordered"]
    labels = {"unordered": "unordered (deadlocks!)", "sorted": "sorted(key=lambda)    ",
              "compared": "one comparison        "}
    for mode in ("unordered", "sorted", "compared"):
        t = best[mode]
        extra = (t - base) / ITERS * 1e9
        tag = "baseline" if mode == "unordered" else f"{extra:+5.0f} ns/transfer ({t / base - 1:+.1%})"
        print(f"    {labels[mode]} {t / ITERS * 1e9:7.0f} ns/transfer   {tag}")
    print("  Ordering is nearly free. sorted() with a key lambda is not — order by comparison.")


# ─── 3 · A wait-for graph deadlock detector (what PostgreSQL does) ────────────

class LockManager:
    """Records who HOLDS each lock and who WAITS for it, so a cycle can be found.

    The wait-for graph has one node per thread and an edge T1 -> T2 meaning
    "T1 is blocked on a lock that T2 currently holds". A cycle in that graph is a
    deadlock — not an analogy for one, the exact condition.
    """

    def __init__(self) -> None:
        self._book = threading.Lock()          # guards the bookkeeping only
        self._locks: dict[str, threading.Lock] = {}
        self.holder: dict[str, str] = {}       # lock name -> thread name
        self.waiter: dict[str, str] = {}       # thread name -> lock name it wants

    def acquire(self, name: str) -> None:
        me = threading.current_thread().name
        with self._book:
            lk = self._locks.setdefault(name, threading.Lock())
            self.waiter[me] = name             # "I am about to block on `name`"
        lk.acquire()
        with self._book:
            self.waiter.pop(me, None)
            self.holder[name] = me

    def release(self, name: str) -> None:
        with self._book:
            self.holder.pop(name, None)
        self._locks[name].release()

    def find_cycle(self):
        """DFS over the wait-for graph. Returns [(thread, lock_it_waits_for)] or None."""
        with self._book:
            waiting, holder = dict(self.waiter), dict(self.holder)

        edges = {}                              # thread -> (lock, thread holding it)
        for th, lk in waiting.items():
            owner = holder.get(lk)
            if owner is not None:
                edges[th] = (lk, owner)         # owner == th means self-deadlock

        for start in edges:
            path, seen, node = [], set(), start
            while node in edges and node not in seen:
                seen.add(node)
                lk, nxt = edges[node]
                path.append((node, lk))
                node = nxt
            if node in seen:                    # we walked back onto the path: a cycle
                head = next(i for i, (t, _) in enumerate(path) if t == node)
                return path[head:]
        return None

    @staticmethod
    def render(cycle) -> str:
        # The holder of each lock is the NEXT thread in the cycle, so the chain closes.
        chain = "".join(f"{th} -> [{lk}] -> " for th, lk in cycle)
        return chain + cycle[0][0]


def demo_wait_for_graph() -> None:
    banner("3 · THE WAIT-FOR GRAPH: FINDING THE CYCLE AUTOMATICALLY")
    lm = LockManager()

    def txn(first: str, second: str) -> None:
        lm.acquire(first)
        time.sleep(0.05)
        lm.acquire(second)
        lm.release(second)
        lm.release(first)

    t1 = threading.Thread(target=txn, args=("acct-A", "acct-B"), name="T1", daemon=True)
    t2 = threading.Thread(target=txn, args=("acct-B", "acct-A"), name="T2", daemon=True)
    t1.start()
    t2.start()
    time.sleep(0.30)                            # let them get stuck (Postgres: deadlock_timeout)

    print("  holders:", dict(sorted(lm.holder.items())))
    print("  waiters:", dict(sorted(lm.waiter.items())))
    cycle = lm.find_cycle()
    if cycle is None:
        print("  no cycle found (threads finished before the detector ran)")
        return
    print(f"  DEADLOCK DETECTED — cycle of length {len(cycle)}:")
    print("    " + LockManager.render(cycle))
    victim = cycle[-1][0]
    print(f"  recovery: abort a victim ({victim}) and let it retry. That is precisely")
    print("  what Postgres reports as: ERROR  deadlock detected / DETAIL Process X waits...")


# ─── 4 · Dining philosophers: one problem, three broken conditions ────────────

def dining(strategy: str, duration: float, n: int = 5):
    """Run `n` philosophers for `duration` seconds. Returns (meals, retries, stalled)."""
    rng_lock = threading.Lock()
    forks = [threading.Lock() for _ in range(n)]
    meals = [0] * n
    retries = [0] * n
    holds_first = [False] * n                   # who is sitting on a fork right now
    stop = threading.Event()
    waiter = threading.Semaphore(n - 1)         # used only by the "waiter" strategy

    def eat(i: int) -> None:
        meals[i] += 1
        time.sleep(0.0005)

    def philosopher(i: int) -> None:
        rng = random.Random(SEED + i)
        left, right = forks[i], forks[(i + 1) % n]
        while not stop.is_set():
            if strategy == "naive":
                left.acquire()
                holds_first[i] = True
                if meals[i] >= 2:
                    time.sleep(0.02)            # the hold that makes the cycle certain
                right.acquire()
                eat(i)
                right.release()
                holds_first[i] = False
                left.release()

            elif strategy == "asymmetric":
                # ONE philosopher reverses: breaks CIRCULAR WAIT.
                first, second = (right, left) if i == n - 1 else (left, right)
                first.acquire()
                if meals[i] >= 2:
                    time.sleep(0.0002)
                second.acquire()
                eat(i)
                second.release()
                first.release()

            elif strategy == "waiter":
                # At most n-1 may reach for forks: breaks HOLD-AND-WAIT.
                waiter.acquire()
                try:
                    left.acquire()
                    right.acquire()
                    eat(i)
                    right.release()
                    left.release()
                finally:
                    waiter.release()

            elif strategy == "backoff":
                # Give up the first fork on timeout: breaks NO-PREEMPTION.
                left.acquire()
                if not right.acquire(timeout=0.002):
                    left.release()
                    retries[i] += 1
                    with rng_lock:
                        pause = rng.uniform(0.0, 0.004)   # jitter, or this becomes livelock
                    time.sleep(pause)
                    continue
                eat(i)
                right.release()
                left.release()

    threads = [threading.Thread(target=philosopher, args=(i,), name=f"phil-{i}", daemon=True)
               for i in range(n)]
    t0 = time.monotonic()
    for t in threads:
        t.start()

    # Watchdog: poll for progress; if nothing moves for 0.25s we have stalled.
    stalled_after = None
    last, still = -1, 0
    while time.monotonic() - t0 < duration:
        time.sleep(0.05)
        now = sum(meals)
        still = still + 1 if now == last else 0
        last = now
        if still >= 5 and stalled_after is None:
            stalled_after = time.monotonic() - t0
            break
    stop.set()
    for t in threads:
        t.join(timeout=0.25)
    alive = sum(1 for t in threads if t.is_alive())
    return sum(meals), sum(retries), stalled_after, alive, sum(holds_first)


def demo_dining_philosophers() -> None:
    banner("4 · DINING PHILOSOPHERS: THREE FIXES, THREE COFFMAN CONDITIONS")
    print("  strategy      breaks               meals   retries  outcome")
    rows = [
        ("naive", "nothing", 1.5),
        ("asymmetric", "circular wait", 0.6),
        ("waiter", "hold-and-wait", 0.6),
        ("backoff", "no-preemption", 0.6),
    ]
    stuck_forks = 0
    for strategy, breaks, dur in rows:
        meals, retries, stalled, alive, forks_held = dining(strategy, dur)
        if stalled is not None:
            outcome = f"STALLED: 0 meals for 0.25s, {alive}/5 threads never returned"
            stuck_forks = forks_held
        else:
            outcome = f"{meals / dur:,.0f} meals/s, no stall"
        print(f"  {strategy:<12}  {breaks:<18}  {meals:6,}  {retries:8,}  {outcome}")
    print(f"  the stalled table: {stuck_forks}/5 philosophers hold their left fork and wait")
    print("  for their right — one 5-node cycle in the wait-for graph, no fork left over.")
    print("  All four run identical philosophers. Only the acquisition discipline differs.")


# ─── 5 · Livelock: running hard, going nowhere ────────────────────────────────

def livelock_run(jitter: bool, cap: int = 15):
    """Two threads, two locks, polite mutual backoff. Returns (attempts, progress, cpu, wall)."""
    lock_a, lock_b = threading.Lock(), threading.Lock()
    PERIOD, HOLD, WASTED_WORK = 0.030, 0.005, 0.006
    t_start = time.monotonic() + 0.05           # one absolute start instant for both threads
    attempts = [0, 0]
    progress = [0, 0]

    def polite(idx: int) -> None:
        rng = random.Random(SEED + idx)
        first, second = (lock_a, lock_b) if idx == 0 else (lock_b, lock_a)
        next_wake = t_start
        time.sleep(max(0.0, t_start - time.monotonic()))
        while attempts[idx] < cap and progress[idx] == 0:
            attempts[idx] += 1
            first.acquire()
            time.sleep(HOLD)                    # do a little work holding just one lock
            if second.acquire(blocking=False):
                progress[idx] += 1              # got both: the whole task completes
                second.release()
                first.release()
                break
            time.sleep(HOLD)                    # decide to give up (still holding `first`)
            first.release()                     # polite: release what I hold and retry
            spin(WASTED_WORK)                   # redo the state we abandoned: real CPU burn
            # A CONSTANT backoff keeps both threads on the same schedule, forever.
            # A RANDOM one makes their schedules drift apart, and one of them wins.
            next_wake += PERIOD + (rng.uniform(0.0, 2 * PERIOD) if jitter else 0.0)
            time.sleep(max(0.0, next_wake - time.monotonic()))

    threads = [threading.Thread(target=polite, args=(i,), name=f"polite-{i}", daemon=True)
               for i in (0, 1)]
    cpu0, wall0 = time.process_time(), time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)
    return sum(attempts), sum(progress), time.process_time() - cpu0, time.monotonic() - wall0


def demo_livelock() -> None:
    banner("5 · LIVELOCK: RUNNING FLAT OUT, GOING NOWHERE — AND THE ONE-LINE CURE")
    a_at, a_pr, a_cpu, a_wall = livelock_run(jitter=False)
    print(f"  fixed backoff   : {a_at:4d} attempts, {a_pr}/2 threads made progress,"
          f" {a_cpu * 1000:6.1f}ms CPU / {a_wall * 1000:5.0f}ms wall"
          f"  = {a_cpu / a_wall * 100:3.0f}% of a core")
    b_at, b_pr, b_cpu, b_wall = livelock_run(jitter=True)
    print(f"  + random jitter : {b_at:4d} attempts, {b_pr}/2 threads made progress,"
          f" {b_cpu * 1000:6.1f}ms CPU / {b_wall * 1000:5.0f}ms wall"
          f"  = {b_cpu / b_wall * 100:3.0f}% of a core")
    print(f"  the fixed pair took and released locks {a_at * 2} times and finished nothing;")
    print(f"  jitter finished the same work in {b_at} attempts."
          " uniform(0, 2*period) is the whole fix.")
    dl_cpu, dl_wall = DEADLOCK_COST["cpu"], DEADLOCK_COST["wall"]
    print(f"  compare section 1's DEADLOCK: {dl_cpu * 1000:.1f}ms CPU over"
          f" {dl_wall * 1000:.0f}ms wall = {dl_cpu / dl_wall * 100:.1f}% of a core.")
    print("  Same symptom (no progress), opposite signal (busy vs idle). Check CPU first.")


# ─── 6 · Starvation: unfair by design, and the price of fairness ──────────────

class TicketLock:
    """FIFO mutex: take a ticket, wait until it is served. Bounded wait, by construction."""

    def __init__(self) -> None:
        self._cv = threading.Condition()
        self._next_ticket = 0
        self._now_serving = 0

    def acquire(self) -> None:
        with self._cv:
            mine = self._next_ticket
            self._next_ticket += 1
            while self._now_serving != mine:
                self._cv.wait()

    def release(self) -> None:
        with self._cv:
            self._now_serving += 1
            self._cv.notify_all()               # O(waiters) wakeups: this is the cost

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()


def hammer(lock, n_threads: int, duration: float, work: float = 0.00005):
    counts = [0] * n_threads
    waits: list[list[float]] = [[] for _ in range(n_threads)]
    deadline = time.monotonic() + duration

    def worker(idx: int) -> None:
        local = waits[idx]
        while time.monotonic() < deadline:
            t0 = time.monotonic()
            lock.acquire()
            local.append(time.monotonic() - t0)
            spin(work)
            counts[idx] += 1
            lock.release()

    threads = [threading.Thread(target=worker, args=(i,), name=f"h{i}", daemon=True)
               for i in range(n_threads)]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=duration + 5.0)
    return counts, waits, time.monotonic() - t0


def _pct(sorted_vals, q: float) -> float:
    if not sorted_vals:
        return 0.0
    return sorted_vals[min(len(sorted_vals) - 1, int(q * len(sorted_vals)))]


def demo_starvation() -> None:
    banner("6 · STARVATION: MOST MUTEXES ARE UNFAIR ON PURPOSE")
    N, DUR = 8, 0.8
    print(f"  {N} threads hammering one lock, 50us critical section, {DUR}s each")
    results = {}
    for label, lock in (("threading.Lock (barging, the default)", threading.Lock()),
                        ("TicketLock (FIFO, hand-built)", TicketLock())):
        counts, waits, el = hammer(lock, N, DUR)
        flat = sorted(w for lst in waits for w in lst)
        total = sum(counts)
        lo, hi = min(counts), max(counts)
        loser = counts.index(lo)
        loser_worst = max(waits[loser]) if waits[loser] else 0.0
        results[label] = (total / el, max(flat))
        print(f"  {label}:  {total / el:,.0f} acq/s")
        print(f"      acquisitions per thread : {sorted(counts)}"
              f"   ({hi / lo if lo else float('inf'):,.0f}x spread)")
        print(f"      unluckiest thread       : {lo:,} acquisitions,"
              f" its worst single wait {loser_worst * 1000:.1f} ms")
        print(f"      wait over ALL samples   : p50 {_pct(flat, 0.50) * 1000:6.3f} ms"
              f"   p99 {_pct(flat, 0.99) * 1000:6.3f} ms"
              f"   max {max(flat) * 1000:7.2f} ms")
    (fast_tp, fast_max), (fair_tp, fair_max) = results.values()
    print(f"  the trade: FIFO costs {(1 - fair_tp / fast_tp) * 100:.0f}% of throughput"
          f" and buys a {fast_max / fair_max:,.0f}x shorter worst-case wait.")
    print("  Note the barging lock's percentiles: the starved thread contributes almost")
    print("  no samples, so it is invisible to p50 and p99. Only the MAX and the")
    print("  per-thread counts show it. Aggregate latency metrics cannot see starvation.")


def main() -> int:
    random.seed(SEED)
    print("Deadlock, livelock & starvation — Phase 8, Lesson 10")
    print(f"python {sys.version.split()[0]}  ·  seed {SEED}  ·  every hang is watchdogged")
    t0 = time.monotonic()
    demo_abba_deadlock()
    demo_lock_ordering()
    demo_wait_for_graph()
    demo_dining_philosophers()
    demo_livelock()
    demo_starvation()
    print(f"\nAll sections complete in {time.monotonic() - t0:.1f}s. "
          "Deadlocked daemon threads are abandoned; the process exits cleanly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
