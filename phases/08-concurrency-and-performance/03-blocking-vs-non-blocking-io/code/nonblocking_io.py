"""Blocking vs non-blocking I/O, measured from the syscall up.

Builds: a blocking server that visibly queues clients, a bare EAGAIN busy loop
priced in CPU seconds, a one-thread `selectors` server with real read buffers
and write queues, a scaling measurement of select() vs epoll/kqueue, and a
level-triggered/edge-triggered demonstration.
Companion to docs/en.md (Phase 8, Lesson 03). Stdlib only, self-terminating.
Non-blocking semantics: POSIX.1-2017 (IEEE Std 1003.1) O_NONBLOCK / EAGAIN;
readiness notification: select(2), poll(2), epoll(7), kqueue(2).
"""

from __future__ import annotations

import errno
import os
import resource
import select
import selectors
import socket
import threading
import time

HOST = "127.0.0.1"


def _selector_name() -> str:
    sel = selectors.DefaultSelector()
    name = type(sel).__name__
    sel.close()
    return name


SELECTOR_NAME = _selector_name()   # EpollSelector on Linux, KqueueSelector on BSD/macOS


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def banner(text: str) -> None:
    print(f"\n== {text} ==")


def read_proc_kib(field: str) -> int:
    """VmRSS / VmSize in KiB from /proc/self/status; 0 if unavailable."""
    try:
        with open("/proc/self/status", "r", encoding="ascii") as fh:
            for line in fh:
                if line.startswith(field + ":"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0


def human_bytes(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024.0 or unit == "TiB":
            return f"{n:,.1f} {unit}"
        n /= 1024.0
    return f"{n:,.1f} TiB"


def recv_line(sock: socket.socket) -> bytes:
    """Blocking read until a newline. The client side of every demo."""
    chunks: list[bytes] = []
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        if chunk.endswith(b"\n"):
            return b"".join(chunks)


# ---------------------------------------------------------------------------
# 1 · a blocking server serves one client at a time
# ---------------------------------------------------------------------------

SERVICE_SECONDS = 0.30


def demo_blocking_server() -> None:
    banner("1 · A BLOCKING SERVER SERVES ONE CLIENT AT A TIME")

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((HOST, 0))
    listener.listen(8)
    port = listener.getsockname()[1]

    def server() -> None:
        for _ in range(2):
            conn, _addr = listener.accept()          # blocks until a client arrives
            with conn:
                conn.recv(4096)                      # blocks until the request lands
                time.sleep(SERVICE_SECONDS)          # the "work": 300 ms of it
                conn.sendall(b"ok\n")

    results: dict[str, float] = {}
    ready = threading.Barrier(3)

    def client(name: str) -> None:
        sock = socket.create_connection((HOST, port))
        ready.wait()                                 # both clients start together
        t0 = time.perf_counter()
        sock.sendall(b"GET\n")
        recv_line(sock)
        results[name] = time.perf_counter() - t0
        sock.close()

    srv = threading.Thread(target=server, daemon=True)
    srv.start()
    threads = [threading.Thread(target=client, args=(n,)) for n in ("A", "B")]
    for t in threads:
        t.start()
    ready.wait()
    for t in threads:
        t.join()
    srv.join(timeout=5)
    listener.close()

    first, second = sorted(results.values())
    print(f"  server work per request      = {SERVICE_SECONDS * 1000:7.1f} ms")
    print(f"  fastest client saw           = {first * 1000:7.1f} ms")
    print(f"  slowest client saw           = {second * 1000:7.1f} ms")
    print(f"  measured stall (queueing)    = {(second - first) * 1000:7.1f} ms"
          f"   <- time spent waiting in line, not being served")
    print(f"  the second client paid {second / first:.2f}x for identical work")


# ---------------------------------------------------------------------------
# 2 · EAGAIN, and the busy loop that is NOT the fix
# ---------------------------------------------------------------------------

IDLE_SECONDS = 0.25


def demo_eagain() -> None:
    banner("2 · EAGAIN IN THE FLESH, AND WHAT A BUSY LOOP COSTS")

    a, b = socket.socketpair()
    a.setblocking(False)
    try:
        a.recv(1024)
        print("  unexpected: recv() returned data")
    except BlockingIOError as exc:
        name = errno.errorcode.get(exc.errno, "?")
        print(f"  sock.setblocking(False); sock.recv() with an empty buffer")
        print(f"    -> BlockingIOError errno={exc.errno} ({name}): {os.strerror(exc.errno)}")
        print(f"       EAGAIN == EWOULDBLOCK: {errno.EAGAIN == errno.EWOULDBLOCK}")
    a.close()
    b.close()

    # (a) the busy loop: spin on a non-blocking recv until the peer speaks.
    a, b = socket.socketpair()
    a.setblocking(False)
    timer = threading.Timer(IDLE_SECONDS, lambda: b.sendall(b"hello\n"))
    timer.start()
    attempts = 0
    cpu0, wall0 = time.process_time(), time.perf_counter()
    while True:
        try:
            a.recv(1024)
            break
        except BlockingIOError:
            attempts += 1
    spin_cpu = time.process_time() - cpu0
    spin_wall = time.perf_counter() - wall0
    timer.join()
    a.close()
    b.close()

    # (b) the same wait, parked in the kernel by a blocking recv.
    a, b = socket.socketpair()
    timer = threading.Timer(IDLE_SECONDS, lambda: b.sendall(b"hello\n"))
    timer.start()
    cpu0, wall0 = time.process_time(), time.perf_counter()
    a.recv(1024)
    park_cpu = time.process_time() - cpu0
    park_wall = time.perf_counter() - wall0
    timer.join()
    a.close()
    b.close()

    print(f"\n  receiving ONE message that arrives {IDLE_SECONDS * 1000:.0f} ms from now:")
    print(f"    busy loop   wall={spin_wall * 1000:7.1f} ms   cpu={spin_cpu * 1000:7.1f} ms"
          f"   failed recv() syscalls = {attempts:,}")
    print(f"    blocking    wall={park_wall * 1000:7.1f} ms   cpu={park_cpu * 1000:7.1f} ms"
          f"   failed recv() syscalls = 0")
    # NB: no ratio here -- the blocking CPU time rounds to zero, so any ratio is
    # an artifact of the clock's resolution. Utilisation is the honest statistic.
    print(f"    CPU utilisation while waiting: busy loop {spin_cpu / spin_wall * 100:5.1f}%"
          f"   vs blocking {park_cpu / park_wall * 100:5.1f}%")
    print(f"    the busy loop costs {spin_cpu / spin_wall:.2f} CPU-seconds per idle"
          f" second, PER CONNECTION")
    print(f"    -> 10,000 idle connections would need {spin_cpu / spin_wall * 10000:,.0f}"
          f" cores to do nothing")
    print(f"    {attempts / spin_wall / 1000:,.0f}k syscalls/sec returning"
          f" 'nothing to do' -> a whole core, producing nothing")


# ---------------------------------------------------------------------------
# 3 · one thread, many connections
# ---------------------------------------------------------------------------

N_CLIENTS = 150
REQUESTS_PER_CLIENT = 4
REQUEST_BYTES = 12288     # bigger than one recv() -> messages arrive in fragments
RESPONSE_BYTES = 16384
SNDBUF = 2048             # deliberately small, to force partial writes
RCVBUF = 2048             # ... and a slow reader on the other end, to keep them coming


class Connection:
    """Per-connection state. In a blocking server this lives on the call stack;
    with one thread for everything, you have to write it down yourself."""

    __slots__ = ("sock", "inbuf", "outq", "requests")

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.inbuf = bytearray()      # bytes received but not yet a whole message
        self.outq = bytearray()       # bytes owed to the peer but not yet accepted
        self.requests = 0


def make_listener() -> tuple[socket.socket, int]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((HOST, 0))
    listener.listen(512)
    return listener, listener.getsockname()[1]


def spawn_clients(port: int, n: int) -> threading.Barrier:
    """n client threads, each doing REQUESTS_PER_CLIENT round trips."""
    gate = threading.Barrier(n + 1)

    def client(idx: int) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # a small receive buffer, set BEFORE connect, makes this a slow reader --
        # which is exactly what forces the server's send() to come up short.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, RCVBUF)
        sock.connect((HOST, port))
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        gate.wait()
        for seq in range(REQUESTS_PER_CLIENT):
            body = f"req {idx}:{seq} ".encode().ljust(REQUEST_BYTES - 1, b"-")
            sock.sendall(body + b"\n")
            recv_line(sock)
        sock.close()

    for i in range(n):
        threading.Thread(target=client, args=(i,), daemon=True).start()
    return gate


def run_selector_server(port: int, listener: socket.socket, total_requests: int) -> dict:
    """ONE thread. Every connection is a dict entry, not a stack frame."""
    sel = selectors.DefaultSelector()
    listener.setblocking(False)
    sel.register(listener, selectors.EVENT_READ, None)

    conns: dict[int, Connection] = {}
    served = 0
    peak = 0
    partial_writes = 0
    partial_reads = 0
    t0 = time.perf_counter()

    while served < total_requests:
        for key, mask in sel.select(timeout=5.0):
            if key.data is None:                              # the listener
                while True:
                    try:
                        sock, _ = listener.accept()
                    except BlockingIOError:                   # accept queue drained
                        break
                    sock.setblocking(False)
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, SNDBUF)
                    conn = Connection(sock)
                    conns[sock.fileno()] = conn
                    sel.register(sock, selectors.EVENT_READ, conn)
                    peak = max(peak, len(conns))
                continue

            conn: Connection = key.data
            if mask & selectors.EVENT_READ:
                try:
                    chunk = conn.sock.recv(4096)
                except BlockingIOError:                       # spurious wakeup
                    continue
                if not chunk:
                    sel.unregister(conn.sock)
                    conns.pop(conn.sock.fileno(), None)
                    conn.sock.close()
                    continue
                conn.inbuf += chunk
                if b"\n" not in conn.inbuf:
                    partial_reads += 1                        # a fragment, not a message
                while b"\n" in conn.inbuf:                    # framing: one message per line
                    line, _, rest = conn.inbuf.partition(b"\n")
                    conn.inbuf = bytearray(rest)
                    conn.outq += line.upper().ljust(RESPONSE_BYTES - 1, b".") + b"\n"
                    conn.requests += 1
                    served += 1
                if conn.outq:
                    sel.modify(conn.sock, selectors.EVENT_READ | selectors.EVENT_WRITE, conn)

            if mask & selectors.EVENT_WRITE and conn.outq:
                try:
                    sent = conn.sock.send(conn.outq)
                except BlockingIOError:
                    sent = 0
                if sent < len(conn.outq):
                    partial_writes += 1                       # the kernel took only some
                del conn.outq[:sent]
                if not conn.outq:
                    sel.modify(conn.sock, selectors.EVENT_READ, conn)

    elapsed = time.perf_counter() - t0
    for conn in list(conns.values()):
        try:
            sel.unregister(conn.sock)
        except (KeyError, ValueError):
            pass
        conn.sock.close()
    sel.unregister(listener)
    sel.close()
    return {
        "elapsed": elapsed, "served": served, "peak": peak,
        "partial_writes": partial_writes, "partial_reads": partial_reads,
        "threads": 1,
    }


def run_thread_per_connection(port: int, listener: socket.socket, n: int) -> dict:
    """The obvious design: one blocking thread per connection."""
    workers: list[threading.Thread] = []
    served = 0
    lock = threading.Lock()
    t0 = time.perf_counter()

    def handle(sock: socket.socket) -> None:
        nonlocal served
        with sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, SNDBUF)
            buf = bytearray()
            while True:
                chunk = sock.recv(4096)               # this thread parks here
                if not chunk:
                    return
                buf += chunk
                while b"\n" in buf:
                    line, _, rest = buf.partition(b"\n")
                    buf = bytearray(rest)
                    sock.sendall(line.upper().ljust(RESPONSE_BYTES - 1, b".") + b"\n")
                    with lock:
                        served += 1

    for _ in range(n):
        sock, _addr = listener.accept()
        t = threading.Thread(target=handle, args=(sock,), daemon=True)
        t.start()
        workers.append(t)
    for t in workers:
        t.join(timeout=15)
    elapsed = time.perf_counter() - t0
    return {"elapsed": elapsed, "served": served, "threads": len(workers)}


def measure_thread_cost(n: int = 200) -> dict:
    """What one parked thread costs in memory, and one context switch in time."""
    stack_limit = resource.getrlimit(resource.RLIMIT_STACK)[0]
    reserved = stack_limit if stack_limit > 0 else 8 * 1024 * 1024

    stop = threading.Event()
    rss0, vsz0 = read_proc_kib("VmRSS"), read_proc_kib("VmSize")
    parked = [threading.Thread(target=stop.wait, daemon=True) for _ in range(n)]
    for t in parked:
        t.start()
    time.sleep(0.4)                                   # let every stack fault in
    rss1, vsz1 = read_proc_kib("VmRSS"), read_proc_kib("VmSize")
    stop.set()
    for t in parked:
        t.join(timeout=5)

    rss_per_thread = max(rss1 - rss0, 0) * 1024 / n
    vsz_per_thread = max(vsz1 - vsz0, 0) * 1024 / n

    # Ping-pong over a socketpair: each round trip is exactly two thread wakeups.
    # Timing microbenchmarks are contaminated upwards by any other load on the
    # box, never downwards, so we take the BEST of three trials.
    rounds = 10000
    trials = 3
    rt = float("inf")
    switches = 0
    for _ in range(trials):
        a, b = socket.socketpair()

        def echo(sock: socket.socket = b) -> None:
            for _ in range(rounds):
                data = sock.recv(1)
                if not data:
                    return
                sock.sendall(data)

        peer = threading.Thread(target=echo, daemon=True)
        peer.start()
        sw0 = resource.getrusage(resource.RUSAGE_SELF).ru_nvcsw
        t0 = time.perf_counter()
        for _ in range(rounds):
            a.sendall(b"x")
            a.recv(1)
        elapsed = (time.perf_counter() - t0) / rounds
        if elapsed < rt:
            rt = elapsed
            switches = resource.getrusage(resource.RUSAGE_SELF).ru_nvcsw - sw0
        peer.join(timeout=5)
        a.close()
        b.close()

    return {
        "reserved": reserved,
        "rss_per_thread": rss_per_thread,
        "vsz_per_thread": vsz_per_thread,
        "roundtrip_us": rt * 1e6,
        "switch_us": rt * 1e6 / 2,
        "voluntary_switches": switches,
        "rounds": rounds,
        "sampled": n,
    }


def demo_one_thread_many_connections() -> None:
    banner("3 · ONE THREAD, MANY CONNECTIONS")

    total = N_CLIENTS * REQUESTS_PER_CLIENT
    trials = 3

    sel_stats = None
    for _ in range(trials):                      # best of 3: see the note above
        listener, port = make_listener()
        gate = spawn_clients(port, N_CLIENTS)
        gate.wait()
        run = run_selector_server(port, listener, total)
        listener.close()
        if sel_stats is None or run["elapsed"] < sel_stats["elapsed"]:
            sel_stats = run

    tpc_stats = None
    for _ in range(trials):
        listener, port = make_listener()
        gate = spawn_clients(port, N_CLIENTS)
        gate.wait()
        run = run_thread_per_connection(port, listener, N_CLIENTS)
        listener.close()
        if tpc_stats is None or run["elapsed"] < tpc_stats["elapsed"]:
            tpc_stats = run

    cost = measure_thread_cost()

    print(f"  workload: {N_CLIENTS} concurrent clients x {REQUESTS_PER_CLIENT} requests"
          f" = {total} requests")
    print(f"            {REQUEST_BYTES // 1024} KiB request, {RESPONSE_BYTES // 1024} KiB"
          f" response, small SO_SNDBUF/SO_RCVBUF")
    print(f"            so that fragmentation is guaranteed, not hoped for\n")
    print(f"  (each server is run {trials}x; the best wall time is reported, because")
    print(f"   background load can only ever make a timing worse, never better)\n")
    print(f"  selectors ({SELECTOR_NAME}), ONE thread:")
    print(f"    wall time            = {sel_stats['elapsed'] * 1000:8.1f} ms"
          f"   ({sel_stats['served'] / sel_stats['elapsed']:,.0f} req/s)")
    print(f"    requests served      = {sel_stats['served']}")
    print(f"    peak concurrent conns= {sel_stats['peak']}")
    print(f"    OS threads used      = {sel_stats['threads']}")
    print(f"    partial writes hit   = {sel_stats['partial_writes']:,}"
          f"   <- send() took less than we gave it, this often")
    print(f"    partial reads hit    = {sel_stats['partial_reads']:,}"
          f"   <- recv() returned less than one message")
    print(f"\n  thread-per-connection, same workload:")
    print(f"    wall time            = {tpc_stats['elapsed'] * 1000:8.1f} ms"
          f"   ({tpc_stats['served'] / tpc_stats['elapsed']:,.0f} req/s)")
    print(f"    requests served      = {tpc_stats['served']}")
    print(f"    OS threads created   = {tpc_stats['threads']}")

    print(f"\n  what one parked thread costs (measured over {cost['sampled']} threads):")
    print(f"    stack RESERVED (RLIMIT_STACK) = {human_bytes(cost['reserved'])} of address space")
    print(f"    virtual size per thread       = {human_bytes(cost['vsz_per_thread'])}")
    print(f"    RESIDENT per thread           = {human_bytes(cost['rss_per_thread'])}")
    print(f"    thread ping-pong round trip   = {cost['roundtrip_us']:.2f} us"
          f"  -> ~{cost['switch_us']:.2f} us per wakeup")
    print(f"    voluntary context switches    = {cost['voluntary_switches']:,}"
          f" over {cost['rounds']:,} round trips (2.0 each)")

    print(f"\n  extrapolate to 10,000 mostly-idle connections:")
    print(f"    thread-per-connection, resident = {human_bytes(cost['rss_per_thread'] * 10000)}")
    print(f"    thread-per-connection, reserved = {human_bytes(cost['reserved'] * 10000)}"
          f"  of virtual address space")
    print(f"    one wakeup each                 = {cost['switch_us'] * 10000 / 1000:,.1f} ms"
          f" of pure scheduler work per round")
    print(f"    selector loop, resident         = {human_bytes(cost['rss_per_thread'])}"
          f"  (1 thread) + ~{human_bytes(400 * 10000)} of connection state")


# ---------------------------------------------------------------------------
# 4 · why epoll won: select() scales with WATCHED, epoll with READY
# ---------------------------------------------------------------------------

def demo_select_scaling() -> None:
    banner("4 · WHY EPOLL WON: SELECT() COSTS O(WATCHED), EPOLL COSTS O(READY)")

    idle_r, idle_w = os.pipe()          # never written to -> never readable
    hot_r, hot_w = os.pipe()
    os.write(hot_w, b"!")               # always readable

    dups: list[int] = []
    print(f"  {'watched':>8}  {'select() us/call':>18}  {SELECTOR_NAME + ' us/call':>22}"
          f"  {'ready':>6}")
    try:
        for target in (10, 100, 500, 1000, 2000):
            while len(dups) < target:
                dups.append(os.dup(idle_r))
            watch = dups[:target] + [hot_r]

            iters, batches = 300, 5
            try:
                for _ in range(50):                       # warm up
                    select.select(watch, [], [], 0)
                best = float("inf")
                for _ in range(batches):                  # best of 5, as above
                    t0 = time.perf_counter()
                    for _ in range(iters):
                        select.select(watch, [], [], 0)
                    best = min(best, (time.perf_counter() - t0) / iters * 1e6)
                select_txt = f"{best:.1f}"
            except (ValueError, OSError):
                select_txt = "FD_SETSIZE EXCEEDED"

            sel = selectors.DefaultSelector()
            for fd in watch:
                sel.register(fd, selectors.EVENT_READ)
            for _ in range(50):
                sel.select(0)
            epoll_us = float("inf")
            ready = 0
            for _ in range(batches):
                t0 = time.perf_counter()
                for _ in range(iters):
                    ready = len(sel.select(0))
                epoll_us = min(epoll_us, (time.perf_counter() - t0) / iters * 1e6)
            sel.close()

            print(f"  {target + 1:8,}  {select_txt:>18}  {epoll_us:22.1f}  {ready:6,}")
    finally:
        for fd in dups:
            os.close(fd)
        for fd in (idle_r, idle_w, hot_r, hot_w):
            os.close(fd)

    print(f"\n  select() re-copies and re-scans the whole fd_set on EVERY call, in both")
    print(f"  directions, so its cost tracks the number of fds you are WATCHING.")
    print(f"  {SELECTOR_NAME} keeps the registration in the kernel and returns a ready")
    print(f"  list, so its cost tracks the number of fds that are READY -- here, always 1.")
    try:
        select.select([2000], [], [], 0)
    except (ValueError, OSError) as exc:
        print(f"  select() on fd 2000 -> {type(exc).__name__}: {exc}")
        print(f"  That is FD_SETSIZE (1024 on glibc). It is a compile-time constant in libc,")
        print(f"  not a tunable: the fd_set bitmap has exactly that many bits. THAT is the wall.")


# ---------------------------------------------------------------------------
# 5 · level-triggered vs edge-triggered
# ---------------------------------------------------------------------------

PENDING_BYTES = 8192
DRAIN_CHUNK = 1024


class EdgeTriggeredSim:
    """Python's selectors are level-triggered only. This reproduces EPOLLET
    semantics faithfully: an fd is reported once per *transition* into
    readability, and is only re-armed when the reader hits EAGAIN and new data
    subsequently arrives."""

    def __init__(self) -> None:
        self.armed: dict[int, bool] = {}

    def register(self, fd: int) -> None:
        self.armed[fd] = True          # registration itself arms once

    def data_arrived(self, fd: int) -> None:
        if self.armed.get(fd) is None:
            return
        self.armed[fd] = True          # a new arrival is a new edge

    def select(self, fds: list[int]) -> list[int]:
        ready = [fd for fd in fds if self.armed.get(fd)]
        for fd in ready:
            self.armed[fd] = False     # the edge is consumed by reporting it
        return ready

    def hit_eagain(self, fd: int) -> None:
        self.armed[fd] = False         # drained; the next arrival is a fresh edge


def demo_triggering() -> None:
    banner("5 · LEVEL-TRIGGERED VS EDGE-TRIGGERED")

    a, b = socket.socketpair()
    a.setblocking(False)
    b.sendall(b"x" * PENDING_BYTES)
    time.sleep(0.05)

    sel = selectors.DefaultSelector()
    sel.register(a, selectors.EVENT_READ)
    print(f"  {PENDING_BYTES:,} bytes sitting in the receive buffer;"
          f" we read only {DRAIN_CHUNK:,} per wakeup.\n")
    print("  LEVEL-TRIGGERED (what selectors/epoll-default/kqueue give you):")
    drained = 0
    for wait in range(1, 5):
        events = sel.select(0)
        if events:
            got = len(a.recv(DRAIN_CHUNK))
            drained += got
            print(f"    wait {wait}: reported READY -> read {got:,} B"
                  f"   (drained {drained:,}/{PENDING_BYTES:,}, "
                  f"{PENDING_BYTES - drained:,} still buffered)")
        else:
            print(f"    wait {wait}: reported nothing")
    sel.unregister(a)
    sel.close()
    print(f"    -> readiness is re-reported for as long as data REMAINS."
          f" A partial read is safe.\n")

    a.close()
    b.close()

    a, b = socket.socketpair()
    a.setblocking(False)
    b.sendall(b"x" * PENDING_BYTES)
    time.sleep(0.05)
    et = EdgeTriggeredSim()
    et.register(a.fileno())

    print("  EDGE-TRIGGERED, done WRONG (one read per wakeup, as above):")
    drained = 0
    for wait in range(1, 5):
        events = et.select([a.fileno()])
        if events:
            got = len(a.recv(DRAIN_CHUNK))
            drained += got
            print(f"    wait {wait}: reported READY -> read {got:,} B"
                  f"   (drained {drained:,}/{PENDING_BYTES:,}, "
                  f"{PENDING_BYTES - drained:,} still buffered)")
        else:
            print(f"    wait {wait}: reported NOTHING"
                  f" -- {PENDING_BYTES - drained:,} B are still there,"
                  f" and no event will ever come")
    print(f"    -> the connection is now hung forever: the peer waits for a reply,")
    print(f"       we wait for an event, and the bytes we needed sit in the buffer.\n")
    a.close()
    b.close()

    a, b = socket.socketpair()
    a.setblocking(False)
    b.sendall(b"x" * PENDING_BYTES)
    time.sleep(0.05)
    et = EdgeTriggeredSim()
    et.register(a.fileno())

    print("  EDGE-TRIGGERED, done RIGHT (drain until EAGAIN):")
    for wait in range(1, 4):
        if wait == 3:
            b.sendall(b"y" * 512)               # a new arrival = a new edge
            time.sleep(0.05)
            et.data_arrived(a.fileno())
        events = et.select([a.fileno()])
        if not events:
            print(f"    wait {wait}: reported nothing -- correct, the buffer IS empty")
            continue
        drained, reads = 0, 0
        while True:
            try:
                chunk = a.recv(DRAIN_CHUNK)
            except BlockingIOError:
                et.hit_eagain(a.fileno())
                break
            if not chunk:
                break
            drained += len(chunk)
            reads += 1
        plural = "" if reads == 1 else "s"
        print(f"    wait {wait}: reported READY -> looped {reads} recv() call{plural},"
              f" drained {drained:,} B, hit EAGAIN, re-armed")
    a.close()
    b.close()
    print(f"\n  Python's selectors module exposes level-triggered semantics only;"
          f" the ET blocks\n  above are a faithful simulation of EPOLLET"
          f" (epoll(7)) / EV_CLEAR (kqueue(2)).")


# ---------------------------------------------------------------------------

def main() -> None:
    t0 = time.perf_counter()
    demo_blocking_server()
    demo_eagain()
    demo_one_thread_many_connections()
    demo_select_scaling()
    demo_triggering()
    print(f"\n  total runtime {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()
