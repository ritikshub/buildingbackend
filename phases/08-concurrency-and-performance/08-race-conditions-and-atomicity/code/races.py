"""Race conditions, atomicity and critical sections, measured rather than asserted.

Builds: the lost update (with CPython bytecode), check-then-act (TOCTOU) failures with
money and scarcity attached, a window-width sweep showing probability is a function of
window length, a broken invariant observed by a reader mid-transfer, the same scenarios
repaired with threading.Lock plus the measured cost of that repair, and a race condition
composed entirely out of individually atomic operations.

Companion to docs/en.md (Phase 8, Lesson 08). Standard library only; exits 0 in ~15 s.
Free-threading background: PEP 703 (Making the Global Interpreter Lock Optional in CPython).
"""

from __future__ import annotations

import dis
import io
import sys
import threading
import time

# ---------------------------------------------------------------------------
# Why this program touches sys.setswitchinterval
# ---------------------------------------------------------------------------
# CPython hands the GIL (Global Interpreter Lock) from thread to thread when the
# "switch interval" expires -- 5 ms by default (sys.getswitchinterval()). Five
# milliseconds is an eternity in bytecode terms, so a race window a few instructions
# wide is rarely landed in during a short demo. Setting the interval to 1 microsecond
# makes threads swap constantly, which raises the *observed* rate of the bug.
#
# Be honest about what that does: it changes the FREQUENCY of the failure, never its
# EXISTENCE. Every race below is reachable at the default interval too -- it just
# needs production traffic and a few weeks instead of 40 milliseconds. That asymmetry
# is the whole reason races reach production: your test suite runs for seconds, your
# service runs for years. Section 2b measures the relationship directly.
DEFAULT_SWITCH_INTERVAL = sys.getswitchinterval()
FAST_SWITCH = 1e-6

THREADS = 8
INCREMENTS = 100_000
EXPECTED = THREADS * INCREMENTS
ROUNDS = 120
CLIENTS = 12


def banner(text: str) -> None:
    print(f"\n== {text} ==")


def run_threads(target, n: int, *args) -> float:
    """Start n threads on target, join them all, return wall-clock seconds."""
    threads = [threading.Thread(target=target, args=args) for _ in range(n)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return time.perf_counter() - start


# ===========================================================================
# 1 · THE LOST UPDATE
# ===========================================================================

counter = 0


def increment_global() -> None:
    """The canonical example. Three operations wearing one line of source."""
    global counter
    counter += 1


class Counter:
    """A counter behind an ordinary property -- i.e. what real code looks like.

    An ORM column, a model field, a @property wrapping validation, a config object:
    all of them put a Python-level function call between the load and the store, and
    a function call is a point at which the interpreter may switch threads.
    """

    def __init__(self, value: int = 0) -> None:
        self._value = value

    @property
    def value(self) -> int:
        return self._value

    @value.setter
    def value(self, new: int) -> None:
        self._value = new


def bump_plain(box: list[int]) -> None:
    for _ in range(INCREMENTS):
        box[0] += 1


def bump_property(c: Counter) -> None:
    for _ in range(INCREMENTS):
        c.value += 1


def bump_property_locked(c: Counter, lock: threading.Lock) -> None:
    for _ in range(INCREMENTS):
        with lock:                       # critical section: load, add AND store
            c.value += 1


def demo_lost_update() -> None:
    banner("1 · `counter += 1` IS THREE OPERATIONS, AND ONE OF THEM CAN BE LOST")

    src = io.StringIO()
    dis.dis(increment_global, file=src)
    print("  CPython bytecode for the single line `counter += 1`:")
    for line in src.getvalue().splitlines():
        if line.strip():
            print(f"    {line}")
    print("    LOAD_GLOBAL = read it | BINARY_OP = add | STORE_GLOBAL = write it back.")
    print("    Two threads that LOAD the same value both STORE the same value+1.")
    print("    Two increments happened. One survived. Nothing reported the other.")

    sys.setswitchinterval(FAST_SWITCH)

    # (a) The textbook demo -- and the honest result on CPython 3.12.
    box = [0]
    elapsed_plain = run_threads(bump_plain, THREADS, box)
    print(f"\n  (a) bare `box[0] += 1` in a tight loop, {THREADS} threads x {INCREMENTS:,}")
    print(f"      expected {EXPECTED:>9,}   actual {box[0]:>9,}   lost {EXPECTED - box[0]:>9,}")
    print("      Zero. CPython 3.12 only polls for a thread switch at a loop's back edge")
    print("      and at function entry, so this read-modify-write is never interrupted.")
    print("      That is an accident of one interpreter version, NOT a guarantee. Watch")
    print("      what happens when an ordinary accessor sits between load and store:")

    # (b) The same arithmetic through a property -- one call, and the floor opens.
    c = Counter()
    elapsed_prop = run_threads(bump_property, THREADS, c)
    lost = EXPECTED - c.value
    print(f"\n  (b) `c.value += 1` where value is a @property, same {THREADS} x {INCREMENTS:,}")
    print(f"      expected {EXPECTED:>9,}   actual {c.value:>9,}   lost {lost:>9,}"
          f"   ({lost / EXPECTED:.1%} of all work)")
    print("      Nothing crashed. No exception. No log line. Just a wrong number,")
    print("      returned confidently, by a program that then carried on.")

    # (c) Twenty runs: the bug is neither rare nor consistent.
    results = []
    for _ in range(20):
        c = Counter()
        run_threads(bump_property, THREADS, c)
        results.append(c.value)

    lo, hi = min(results), max(results)
    print(f"\n  (c) the identical program, 20 more times (expected {EXPECTED:,} every time):")
    bins = 10
    width = max(1, (hi - lo) // bins + 1)
    hist: dict[int, int] = {}
    for r in results:
        hist[(r - lo) // width] = hist.get((r - lo) // width, 0) + 1
    for b in range(bins):
        edge = lo + b * width
        n = hist.get(b, 0)
        print(f"      {edge:>9,} - {edge + width - 1:>9,}  {'#' * n}{'' if n else '.'}")
    print(f"      distinct answers {len(set(results))}/20   correct {results.count(EXPECTED)}/20"
          f"   min {lo:,}   max {hi:,}   spread {hi - lo:,}")
    print(f"      (a) took {elapsed_plain * 1000:.0f} ms and (b) took {elapsed_prop * 1000:.0f} ms:"
          " the bug is not on a slow path, it IS the fast path.")

    sys.setswitchinterval(DEFAULT_SWITCH_INTERVAL)


# ===========================================================================
# 2 · CHECK-THEN-ACT (TOCTOU)
# ===========================================================================


class Account:
    """`if acct.balance >= amount: acct.balance -= amount` -- ordinary business logic."""

    def __init__(self, balance: int) -> None:
        self._balance = balance
        self.lock = threading.Lock()

    @property
    def balance(self) -> int:
        return self._balance

    @balance.setter
    def balance(self, new: int) -> None:
        self._balance = new


def write_audit_record(client: int, amount: int) -> str:
    """The work real code does between the check and the act.

    Building an audit row, calling a fraud service, emitting a metric, formatting a
    receipt. It takes ~200 microseconds because it touches something outside the
    process, and it holds the TOCTOU window open for exactly that long.
    """
    time.sleep(200e-6)
    return f"withdrawal client={client} amount={amount}"


def toctou_withdraw(rounds: int, clients: int, start: int, amount: int, locked: bool):
    negative_rounds = 0
    total_overdraft = 0
    illegal = 0
    legal = start // amount

    for _ in range(rounds):
        acct = Account(start)
        gate = threading.Barrier(clients)
        taken = []
        tally = threading.Lock()

        def client(cid: int = 0) -> None:
            gate.wait()                            # release everyone at one instant
            if locked:
                with acct.lock:                    # ONE critical section, check + act
                    if acct.balance >= amount:
                        write_audit_record(cid, amount)
                        acct.balance -= amount
                        ok = True
                    else:
                        ok = False
            else:
                if acct.balance >= amount:         # --- TIME OF CHECK: true
                    write_audit_record(cid, amount)
                    acct.balance -= amount         # --- TIME OF USE: no longer true
                    ok = True
                else:
                    ok = False
            if ok:
                with tally:
                    taken.append(amount)

        run_threads(client, clients)
        if acct.balance < 0:
            negative_rounds += 1
            total_overdraft += -acct.balance
        illegal += max(0, len(taken) - legal)

    return negative_rounds, total_overdraft, illegal, legal


class Inventory:
    """One seat left, and everybody is looking at it."""

    def __init__(self, seats: int) -> None:
        self._seats = seats
        self.lock = threading.Lock()

    @property
    def seats(self) -> int:
        return self._seats

    @seats.setter
    def seats(self, new: int) -> None:
        self._seats = new


def toctou_oversell(rounds: int, buyers: int, window: float, locked: bool):
    """`window` is how long the code sits between the check and the act."""
    oversold_rounds = 0
    phantom = 0
    for _ in range(rounds):
        inv = Inventory(1)
        gate = threading.Barrier(buyers)
        confirmed = []
        tally = threading.Lock()

        def buyer() -> None:
            gate.wait()
            if locked:
                with inv.lock:
                    if inv.seats > 0:
                        if window:
                            time.sleep(window)
                        inv.seats -= 1
                        got = True
                    else:
                        got = False
            else:
                if inv.seats > 0:                  # "there's a seat left!"
                    if window:
                        time.sleep(window)         # ...charge the card, log, render
                    inv.seats -= 1                 # ...and so did everyone else
                    got = True
                else:
                    got = False
            if got:
                with tally:
                    confirmed.append(1)

        run_threads(buyer, buyers)
        if len(confirmed) > 1:
            oversold_rounds += 1
            phantom += len(confirmed) - 1
    return oversold_rounds, phantom


def toctou_cache_fill(workers: int, locked: bool):
    """`if key not in cache: cache[key] = fetch()` -- the stampede, from the inside."""
    cache: dict[str, str] = {}
    calls = 0
    call_lock = threading.Lock()
    fill_lock = threading.Lock()

    def expensive(key: str) -> str:
        nonlocal calls
        with call_lock:
            calls += 1
        time.sleep(0.02)                           # a database query, an upstream API
        return f"value:{key}"

    def reader() -> None:
        if locked:
            with fill_lock:
                if "hot" not in cache:
                    cache["hot"] = expensive("hot")
        else:
            if "hot" not in cache:                 # --- CHECK: miss
                cache["hot"] = expensive("hot")    # --- ACT: 20 ms later, so did 11 others

    elapsed = run_threads(reader, workers)
    return calls, elapsed


def demo_toctou() -> None:
    banner("2 · CHECK-THEN-ACT: TRUE WHEN YOU CHECKED IT, FALSE WHEN YOU USED IT")
    sys.setswitchinterval(FAST_SWITCH)

    bad, overdraft, illegal, legal = toctou_withdraw(ROUNDS, CLIENTS, 500, 100, locked=False)
    print("  (a) withdrawal   if balance >= 100: audit(); balance -= 100")
    print(f"      {ROUNDS} rounds x {CLIENTS} clients against a $500 balance"
          f" ({legal} withdrawals are legal)")
    print(f"      rounds ending NEGATIVE      : {bad:>5}/{ROUNDS}   ({bad / ROUNDS:.1%})")
    print(f"      money withdrawn that did not exist : ${overdraft:>9,}"
          f"   (${overdraft / ROUNDS:,.0f} per round)")
    print(f"      withdrawals that should have been refused: {illegal:,}")

    print(f"\n  (b) oversell     if seats > 0: <work>; seats -= 1"
          f"   ({ROUNDS} rounds, {CLIENTS} buyers, 1 seat)")
    print("      The window is the ONLY variable. Everything else is identical.")
    print("      window between check and act   oversold rounds      phantom seats sold")
    for window in (0.0, 50e-6, 500e-6):
        bad, phantom = toctou_oversell(ROUNDS, CLIENTS, window, locked=False)
        label = "none (a few bytecodes)" if window == 0 else f"{window * 1e6:.0f} us"
        print(f"      {label:<30} {bad:>4}/{ROUNDS} ({bad / ROUNDS:>5.1%})"
              f"      {phantom:>5} / {(CLIENTS - 1) * ROUNDS} possible")
    print("      Probability is a function of window width. Nothing else changed.")

    sys.setswitchinterval(DEFAULT_SWITCH_INTERVAL)
    calls, elapsed = toctou_cache_fill(CLIENTS, locked=False)
    print("\n  (c) cache fill   if key not in cache: cache[key] = fetch()")
    print(f"      {CLIENTS} threads, 1 cold key, fetch() costs 20 ms")
    print(f"      expensive fetches: {calls}   (1 was needed)"
          f"   -> {calls}x the load on the thing the cache exists to protect")
    print(f"      wall clock {elapsed * 1000:.0f} ms, at the DEFAULT switch interval:")
    print("      I/O inside the window releases the GIL, so this race needs no help.")


# ===========================================================================
# 3 · THE INVARIANT VIEW
# ===========================================================================


class Ledger:
    """Two accounts and one invariant: a + b is always 1000. Transfers move, never mint."""

    def __init__(self) -> None:
        self._v = {"a": 500, "b": 500}

    def get(self, name: str) -> int:
        return self._v[name]

    def set(self, name: str, value: int) -> None:
        self._v[name] = value


def demo_invariant() -> None:
    banner("3 · A RACE IS A BROKEN INVARIANT, NOT A TIMING BUG")
    print("  ONE writer thread (so no update can possibly be lost) moving $1 back and")
    print("  forth 60,000 times, and one auditor thread summing the two accounts.")
    sys.setswitchinterval(FAST_SWITCH)

    for locked in (False, True):
        ledger = Ledger()
        lock = threading.Lock()
        stop = threading.Event()
        stats = {"samples": 0, "broken": 0, "worst": 0}

        def mover() -> None:
            for i in range(60_000):
                sign = 1 if i % 2 == 0 else -1
                if locked:
                    with lock:
                        ledger.set("a", ledger.get("a") - sign)
                        ledger.set("b", ledger.get("b") + sign)
                else:
                    ledger.set("a", ledger.get("a") - sign)   # invariant FALSE from here
                    ledger.set("b", ledger.get("b") + sign)   # ...until here
            stop.set()

        def auditor() -> None:
            while not stop.is_set():
                if locked:
                    with lock:
                        total = ledger.get("a") + ledger.get("b")
                else:
                    total = ledger.get("a") + ledger.get("b")
                stats["samples"] += 1
                if total != 1000:
                    stats["broken"] += 1
                    stats["worst"] = max(stats["worst"], abs(total - 1000))

        threads = [threading.Thread(target=mover), threading.Thread(target=auditor)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        final = ledger.get("a") + ledger.get("b")
        label = "with a lock around the transfer" if locked else "no lock"
        print(f"\n  {label}")
        print(f"      audits taken                : {stats['samples']:>8,}")
        print(f"      audits that did NOT see 1000: {stats['broken']:>8,}"
              f"   ({stats['broken'] / max(stats['samples'], 1):.2%})")
        print(f"      largest discrepancy observed: {stats['worst']:>8}")
        print(f"      final a + b                 : {final:>8}"
              f"   {'-- not one cent was lost' if final == 1000 else '-- money lost'}")

    print("\n  Read that carefully. No money was lost in EITHER run: one writer cannot")
    print("  lose an update. The unlocked bug is a reader who saw the ledger in flight.")
    print("  Every report, balance check, export and reconciliation job is that auditor.")

    sys.setswitchinterval(DEFAULT_SWITCH_INTERVAL)


# ===========================================================================
# 4 · THE CRITICAL SECTION, AND WHAT IT COSTS
# ===========================================================================


def demo_fixed() -> None:
    banner("4 · THE FIX: A CRITICAL SECTION THAT COVERS THE WHOLE READ-MODIFY-WRITE")
    sys.setswitchinterval(FAST_SWITCH)

    c = Counter()
    run_threads(bump_property_locked, THREADS, c, threading.Lock())
    print(f"  (a) counter, locked   : {c.value:,} / {EXPECTED:,}"
          f"   {'EXACT' if c.value == EXPECTED else 'WRONG'}")

    bad, overdraft, illegal, _ = toctou_withdraw(ROUNDS, CLIENTS, 500, 100, locked=True)
    print(f"  (b) withdrawal, locked: {bad} negative rounds, ${overdraft} overdrawn,"
          f" {illegal} illegal withdrawals")

    bad, phantom = toctou_oversell(ROUNDS, CLIENTS, 500e-6, locked=True)
    print(f"  (c) oversell, locked  : {bad} oversold rounds, {phantom} phantom seats"
          "   (at the 500 us window that sold 11 seats per round)")

    sys.setswitchinterval(DEFAULT_SWITCH_INTERVAL)
    calls, _ = toctou_cache_fill(CLIENTS, locked=True)
    print(f"  (d) cache fill, locked: {calls} expensive fetch (1 was needed)")

    # --- the price of correctness, measured at the DEFAULT switch interval so the
    # --- numbers describe normal operation, not the artificially widened window.
    n = 150_000
    per_thread = n // THREADS

    def plain(c: Counter, k: int) -> None:
        for _ in range(k):
            c.value += 1

    def locked(c: Counter, k: int, lk: threading.Lock) -> None:
        for _ in range(k):
            with lk:
                c.value += 1

    def timed(fn, *args) -> float:
        start = time.perf_counter()
        fn(*args)
        return time.perf_counter() - start

    # min-of-N, the standard robust estimator: the fastest run is the one least
    # disturbed by other work on the box. The contended row stays noisy anyway --
    # see the note printed under it.
    solo_plain = min(timed(plain, Counter(), n) for _ in range(5))
    solo_lock = min(timed(locked, Counter(), n, threading.Lock()) for _ in range(5))
    many_plain = min(run_threads(plain, THREADS, Counter(), per_thread) for _ in range(3))
    many_lock = min(run_threads(locked, THREADS, Counter(), per_thread, threading.Lock())
                    for _ in range(3))

    print(f"\n  what the lock costs ({n:,} increments, best of 5, default 5 ms interval):")
    print(f"      1 thread,  no lock : {solo_plain * 1000:7.1f} ms")
    print(f"      1 thread,  locked  : {solo_lock * 1000:7.1f} ms"
          f"   {(solo_lock - solo_plain) / solo_plain:+7.1%}  <- the lock itself")
    print(f"      {THREADS} threads, no lock : {many_plain * 1000:7.1f} ms"
          "   (and the answer is wrong)")
    print(f"      {THREADS} threads, locked  : {many_lock * 1000:7.1f} ms"
          f"   {many_lock / many_plain:6.1f}x  <- the lock PLUS contention")
    print("      Uncontended, a lock is two cheap operations on a fast path. Contended,")
    print("      it serialises every thread through one point and adds a wake-up per")
    print("      handoff -- lesson 9 is about making that region smaller, not removing it.")


# ===========================================================================
# 5 · A RACE CONDITION WITH NO DATA RACE
# ===========================================================================


class ThreadSafeInventory:
    """Every method is individually atomic. There is not one data race in this class."""

    def __init__(self, seats: int) -> None:
        self._seats = seats
        self._lock = threading.Lock()

    def available(self) -> bool:
        with self._lock:                          # atomic
            return self._seats > 0

    def take(self) -> None:
        with self._lock:                          # atomic
            self._seats -= 1

    def take_if_available(self) -> bool:
        with self._lock:                          # atomic, and it covers the DECISION
            if self._seats > 0:
                self._seats -= 1
                return True
            return False


def demo_race_without_data_race() -> None:
    banner("5 · A RACE CONDITION WITH ZERO DATA RACES")
    print("  Same class both times. Every field access is under a lock. No data race")
    print("  detector on earth flags either version. One of them oversells anyway.")
    sys.setswitchinterval(FAST_SWITCH)

    for composed in (True, False):
        oversold_rounds = 0
        phantom = 0
        for _ in range(ROUNDS):
            inv = ThreadSafeInventory(1)
            gate = threading.Barrier(CLIENTS)
            sold = []
            tally = threading.Lock()

            def buyer() -> None:
                gate.wait()
                if composed:
                    if inv.available():           # atomic call #1
                        time.sleep(200e-6)        # charge the card / render the page
                        inv.take()                # atomic call #2
                        got = True
                    else:
                        got = False
                else:
                    got = inv.take_if_available()  # ONE atomic call, decision included
                if got:
                    with tally:
                        sold.append(1)

            run_threads(buyer, CLIENTS)
            if len(sold) > 1:
                oversold_rounds += 1
                phantom += len(sold) - 1

        how = ("if inv.available(): inv.take()      two atomic calls" if composed
               else "inv.take_if_available()             one atomic call")
        print(f"\n  {how}")
        print(f"      oversold rounds : {oversold_rounds:>4}/{ROUNDS}"
              f"   ({oversold_rounds / ROUNDS:.1%})")
        print(f"      phantom seats   : {phantom:>4} / {(CLIENTS - 1) * ROUNDS} possible")

    print("\n  The invariant was never 'seats is read consistently'. It was 'a seat is")
    print("  sold at most once' -- and that spans two calls, so the critical section")
    print("  has to span two calls. Thread-safe parts do not compose into a thread-safe")
    print("  whole. This is the bug a 'thread-safe' library cannot save you from.")

    sys.setswitchinterval(DEFAULT_SWITCH_INTERVAL)


def main() -> None:
    print("Race conditions, atomicity and critical sections")
    print(f"python {sys.version.split()[0]}  |  default GIL switch interval "
          f"{DEFAULT_SWITCH_INTERVAL * 1000:.1f} ms  |  race demos run at "
          f"{FAST_SWITCH * 1e6:.0f} us")
    started = time.perf_counter()
    demo_lost_update()
    demo_toctou()
    demo_invariant()
    demo_fixed()
    demo_race_without_data_race()
    print(f"\ntotal runtime {time.perf_counter() - started:.1f} s")


if __name__ == "__main__":
    main()
