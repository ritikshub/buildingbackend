#!/usr/bin/env python3
"""
An event loop (reactor) from scratch: selector + timer heap + ready queue.

Companion to docs/en.md (Phase 8, Lesson 04). Builds an EventLoop with
call_soon, call_later/call_at (cancellable handles), add_reader/add_writer,
call_soon_threadsafe over a socketpair self-pipe, run_forever/stop and
run_until_complete -- the same anatomy as asyncio's BaseEventLoop. Then runs a
real non-blocking HTTP server on it and MEASURES what a single blocking 500 ms
handler does to every other connection's p99. Standard library only.

Run:  python3 event_loop.py      (self-terminating, ~10 s, exits 0)
"""

from __future__ import annotations

import heapq
import inspect
import itertools
import math
import re
import selectors
import socket
import threading
import time
from collections import deque


# ─── Handles: a scheduled callback you can cancel ────────────────────────────

class Handle:
    """One scheduled callback. Cancelling flips a flag; the loop skips it."""

    __slots__ = ("_fn", "_args", "_loop", "_cancelled", "when")

    def __init__(self, fn, args, loop, when=None):
        self._fn, self._args, self._loop = fn, args, loop
        self._cancelled = False
        self.when = when            # None for call_soon, a deadline for timers

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True

    def _run(self) -> None:
        try:
            self._fn(*self._args)
        except Exception as exc:                     # noqa: BLE001 - the loop is the top frame
            # There is no caller to propagate to: the loop IS the stack.
            self._loop.handle_exception(exc, self._fn)


class Completion:
    """A one-shot result slot -- the seed of a Future. run_until_complete waits on it."""

    def __init__(self):
        self.done = False
        self.result = None
        self._callbacks = []

    def add_done_callback(self, fn):
        if self.done:
            fn(self)
        else:
            self._callbacks.append(fn)

    def set_result(self, value=None):
        if self.done:
            return
        self.done, self.result = True, value
        for fn in self._callbacks:
            fn(self)


# ─── The loop ────────────────────────────────────────────────────────────────

class EventLoop:
    """A reactor: demultiplex fd readiness + timers, dispatch to handlers.

    One thread. One selector. One heap of timers. One ready queue.
    """

    def __init__(self):
        self._selector = selectors.DefaultSelector()
        self._ready: deque[Handle] = deque()          # callbacks to run this/next iteration
        self._timers: list[tuple[float, int, Handle]] = []   # min-heap on deadline
        self._seq = itertools.count()                 # tie-breaker: FIFO among equal deadlines
        self._running = False
        self._stopping = False

        # Cross-thread wakeup: the self-pipe trick, done with a socketpair so it
        # works identically on every platform the selector supports.
        self._wake_r, self._wake_w = socket.socketpair()
        self._wake_r.setblocking(False)
        self._wake_w.setblocking(False)
        self._ts_lock = threading.Lock()
        self._threadsafe: list[Handle] = []
        self.add_reader(self._wake_r.fileno(), self._drain_wakeup)

        # Instrumentation -- this is where "loop lag" comes from in production.
        self.iterations = 0
        self.callbacks_run = 0
        self.select_calls = 0
        self.time_in_select = 0.0
        self.longest_select = 0.0
        self.longest_drain = 0.0      # longest single ready-queue drain == worst loop lag
        self.exceptions = []

    # -- clock ---------------------------------------------------------------

    def time(self) -> float:
        """MONOTONIC, never wall clock. An NTP step must not move a deadline."""
        return time.monotonic()

    # -- scheduling ----------------------------------------------------------

    def call_soon(self, fn, *args) -> Handle:
        """Run fn on the NEXT drain. Never inline -- that is what bounds recursion."""
        h = Handle(fn, args, self)
        self._ready.append(h)
        return h

    def call_at(self, when: float, fn, *args) -> Handle:
        h = Handle(fn, args, self, when=when)
        heapq.heappush(self._timers, (when, next(self._seq), h))
        return h

    def call_later(self, delay: float, fn, *args) -> Handle:
        return self.call_at(self.time() + delay, fn, *args)

    def call_soon_threadsafe(self, fn, *args) -> Handle:
        """The ONLY loop method another thread may call. Queue, then wake the select."""
        h = Handle(fn, args, self)
        with self._ts_lock:
            self._threadsafe.append(h)
        try:
            self._wake_w.send(b"\x01")     # forces select() to return right now
        except (BlockingIOError, OSError):
            pass                           # pipe full == a wakeup is already pending
        return h

    # -- I/O registration ----------------------------------------------------

    def add_reader(self, fd: int, fn, *args) -> None:
        self._add_fd(fd, selectors.EVENT_READ, fn, args)

    def add_writer(self, fd: int, fn, *args) -> None:
        self._add_fd(fd, selectors.EVENT_WRITE, fn, args)

    def remove_reader(self, fd: int) -> bool:
        return self._remove_fd(fd, selectors.EVENT_READ)

    def remove_writer(self, fd: int) -> bool:
        return self._remove_fd(fd, selectors.EVENT_WRITE)

    def _add_fd(self, fd, event, fn, args):
        try:
            key = self._selector.get_key(fd)
        except KeyError:
            self._selector.register(fd, event, {event: (fn, args)})
        else:
            data = dict(key.data)
            data[event] = (fn, args)
            self._selector.modify(fd, key.events | event, data)

    def _remove_fd(self, fd, event) -> bool:
        try:
            key = self._selector.get_key(fd)
        except KeyError:
            return False
        mask = key.events & ~event
        data = dict(key.data)
        data.pop(event, None)
        if not mask:
            self._selector.unregister(fd)
        else:
            self._selector.modify(fd, mask, data)
        return True

    def _drain_wakeup(self):
        while True:
            try:
                if not self._wake_r.recv(4096):
                    return
            except BlockingIOError:
                return
            except OSError:
                return

    # -- the iteration -------------------------------------------------------

    def _run_once(self) -> None:
        # (1) How long may we sleep? Zero if work is already queued; otherwise
        #     until the nearest deadline; otherwise forever (the socketpair can
        #     always wake us).
        if self._ready:
            timeout = 0.0
        elif self._timers:
            timeout = max(0.0, self._timers[0][0] - self.time())
        else:
            timeout = None

        # (2) The one blocking call in the whole program.
        t0 = self.time()
        events = self._selector.select(timeout)
        waited = self.time() - t0
        self.select_calls += 1
        self.time_in_select += waited
        self.longest_select = max(self.longest_select, waited)

        # (3) I/O callbacks for ready file descriptors.
        for key, mask in events:
            for event in (selectors.EVENT_READ, selectors.EVENT_WRITE):
                if mask & event:
                    entry = key.data.get(event)
                    if entry is not None:
                        self._ready.append(Handle(entry[0], entry[1], self))

        # (3b) Cross-thread callbacks are a third event source.
        if self._threadsafe:
            with self._ts_lock:
                pending, self._threadsafe = self._threadsafe, []
            self._ready.extend(pending)

        # (4) Expired timers.
        now = self.time()
        while self._timers and self._timers[0][0] <= now:
            _, _, handle = heapq.heappop(self._timers)
            if not handle.cancelled:
                self._ready.append(handle)

        # (5) Drain a SNAPSHOT of the ready queue. A callback that calls
        #     call_soon() appends behind the snapshot, so it runs next iteration
        #     and cannot starve I/O this one.
        n = len(self._ready)
        d0 = self.time()
        for _ in range(n):
            handle = self._ready.popleft()
            if not handle.cancelled:
                self.callbacks_run += 1
                handle._run()
        self.longest_drain = max(self.longest_drain, self.time() - d0)
        self.iterations += 1

    # -- driving -------------------------------------------------------------

    def run_forever(self) -> None:
        self._running, self._stopping = True, False
        try:
            while not self._stopping:
                self._run_once()
        finally:
            self._running = False

    def stop(self) -> None:
        """Stop after the current iteration finishes -- never mid-drain."""
        self._stopping = True

    def run_until_complete(self, completion: Completion):
        completion.add_done_callback(lambda _c: self.stop())
        self.run_forever()
        return completion.result

    def close(self) -> None:
        self.remove_reader(self._wake_r.fileno())
        self._wake_r.close()
        self._wake_w.close()
        self._selector.close()

    def handle_exception(self, exc, fn) -> None:
        self.exceptions.append((type(exc).__name__, str(exc), getattr(fn, "__name__", repr(fn))))


# ─── A non-blocking HTTP server that lives entirely on the loop ──────────────

BODY = b"x" * 16384      # big enough that a small SO_SNDBUF forces partial writes


class Conn:
    __slots__ = ("sock", "fd", "inbuf", "outbuf")

    def __init__(self, sock):
        self.sock, self.fd = sock, sock.fileno()
        self.inbuf, self.outbuf = b"", b""


class LoopHTTPServer:
    """HTTP/1.1 keep-alive, one thread, driven by add_reader/add_writer."""

    def __init__(self, loop: EventLoop, slow_path: str | None = None, slow_seconds: float = 0.5):
        self.loop = loop
        self.slow_path, self.slow_seconds = slow_path, slow_seconds
        self.requests = 0
        self.partial_writes = 0
        self.conns: dict[int, Conn] = {}
        self.lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.lsock.bind(("127.0.0.1", 0))       # ephemeral port: never collides
        self.lsock.listen(128)
        self.lsock.setblocking(False)
        self.addr = self.lsock.getsockname()
        loop.add_reader(self.lsock.fileno(), self._on_accept)

    def _on_accept(self):
        while True:                              # drain the backlog: one readiness
            try:                                 # notification can mean many sockets
                sock, _ = self.lsock.accept()
            except (BlockingIOError, OSError):
                return
            sock.setblocking(False)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 2048)
            conn = Conn(sock)
            self.conns[conn.fd] = conn
            self.loop.add_reader(conn.fd, self._on_readable, conn.fd)

    def _on_readable(self, fd):
        conn = self.conns.get(fd)
        if conn is None:
            return
        try:
            chunk = conn.sock.recv(65536)
        except BlockingIOError:
            return
        except OSError:
            return self._close(fd)
        if not chunk:
            return self._close(fd)
        conn.inbuf += chunk
        while b"\r\n\r\n" in conn.inbuf:                  # PARTIAL READ handling:
            head, _, conn.inbuf = conn.inbuf.partition(b"\r\n\r\n")   # a recv is not
            path = head.split(b" ")[1].decode() if b" " in head else "/"  # a message
            self.requests += 1
            if self.slow_path is not None and path == self.slow_path:
                time.sleep(self.slow_seconds)             # THE CARDINAL SIN
            conn.outbuf += (
                b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n"
                b"Content-Length: " + str(len(BODY)).encode() + b"\r\n\r\n" + BODY
            )
        if conn.outbuf:
            self._flush(fd)

    def _flush(self, fd):
        conn = self.conns.get(fd)
        if conn is None:
            return
        while conn.outbuf:
            try:
                sent = conn.sock.send(conn.outbuf)
            except BlockingIOError:
                sent = 0
            except OSError:
                return self._close(fd)
            if sent == 0:
                break
            conn.outbuf = conn.outbuf[sent:]
        if conn.outbuf:                       # PARTIAL WRITE: kernel buffer is full.
            self.partial_writes += 1          # Ask to be told when it drains.
            self.loop.add_writer(fd, self._flush, fd)
        else:
            self.loop.remove_writer(fd)       # Nothing to send: stop asking, or the
                                              # loop spins at 100% CPU on writability.

    def _close(self, fd):
        conn = self.conns.pop(fd, None)
        if conn is None:
            return
        self.loop.remove_reader(fd)
        self.loop.remove_writer(fd)
        conn.sock.close()

    def close(self):
        for fd in list(self.conns):
            self._close(fd)
        self.loop.remove_reader(self.lsock.fileno())
        self.lsock.close()


# ─── Thread-based client harness (the load generator, not the server) ────────

class ClientConn:
    def __init__(self, addr):
        self.sock = socket.create_connection(addr, timeout=15)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buf = b""

    def request(self, path: str) -> float:
        t0 = time.monotonic()
        self.sock.sendall(b"GET " + path.encode() + b" HTTP/1.1\r\nHost: bench\r\n\r\n")
        while True:
            i = self.buf.find(b"\r\n\r\n")
            if i != -1:
                n = int(re.search(rb"Content-Length: (\d+)", self.buf[:i]).group(1))
                if len(self.buf) >= i + 4 + n:
                    self.buf = self.buf[i + 4 + n:]
                    return (time.monotonic() - t0) * 1000.0
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("server closed")
            self.buf += chunk

    def close(self):
        self.sock.close()


def pct(values, q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, math.ceil(q / 100.0 * len(s)) - 1))
    return s[k]


def run_load(server, n_clients, n_requests, think, slow_client=None, slow_at=None):
    """Drive the server from real threads. Returns (normal_latencies, slow_latency)."""
    normal, slow_ms = [], None
    lock = threading.Lock()

    def worker(cid):
        nonlocal slow_ms
        conn = ClientConn(server.addr)
        mine = []
        try:
            for i in range(n_requests):
                is_slow = (cid == slow_client and i == slow_at)
                ms = conn.request("/slow" if is_slow else "/api")
                if is_slow:
                    with lock:
                        slow_ms = ms
                else:
                    mine.append(ms)
                time.sleep(think)
        finally:
            conn.close()
        with lock:
            normal.extend(mine)

    threads = [threading.Thread(target=worker, args=(c,), daemon=True) for c in range(n_clients)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return normal, slow_ms


def bench(slow: bool):
    """One full server run on a fresh loop. Returns a stats dict."""
    loop = EventLoop()
    server = LoopHTTPServer(loop, slow_path="/slow" if slow else None, slow_seconds=0.5)
    done = Completion()
    result = {}

    def harness():
        t0 = time.monotonic()
        normal, slow_ms = run_load(
            server, n_clients=24, n_requests=40, think=0.04,
            slow_client=0 if slow else None, slow_at=20,
        )
        result["normal"], result["slow_ms"] = normal, slow_ms
        result["wall"] = time.monotonic() - t0
        # The harness thread hands its result back into the loop the only legal way.
        loop.call_soon_threadsafe(done.set_result, True)

    threading.Thread(target=harness, daemon=True).start()
    loop.run_until_complete(done)
    result.update(
        served=server.requests, partial_writes=server.partial_writes,
        iterations=loop.iterations, callbacks=loop.callbacks_run,
        longest_drain=loop.longest_drain * 1000.0,
    )
    server.close()
    loop.close()
    return result


# ─── Demos ───────────────────────────────────────────────────────────────────

def partial_write_proof():
    """send() is allowed to accept only part of your buffer. Prove it, and prove
    add_writer/remove_writer is what finishes the job."""
    loop = EventLoop()
    done = Completion()
    payload = b"y" * (4 * 1024 * 1024)
    a, b = socket.socketpair()
    a.setblocking(False)
    b.setblocking(False)
    state = {"unsent": payload, "sends": 0, "writer_calls": 0, "first_send": None,
             "received": 0}

    def try_send():
        while state["unsent"]:
            try:
                n = a.send(state["unsent"])
            except BlockingIOError:
                break                       # kernel buffer full: stop, wait for writability
            state["sends"] += 1
            if state["first_send"] is None:
                state["first_send"] = n
            state["unsent"] = state["unsent"][n:]
            if n == 0:
                break
        if state["unsent"]:
            state["writer_calls"] += 1
            loop.add_writer(a.fileno(), try_send)     # tell me when there is room
        else:
            loop.remove_writer(a.fileno())            # or the loop spins at 100% CPU

    def drain():
        try:
            chunk = b.recv(1 << 16)
        except BlockingIOError:
            return
        state["received"] += len(chunk)
        if state["received"] >= len(payload):
            done.set_result(True)

    loop.add_reader(b.fileno(), drain)
    try_send()
    loop.call_later(10.0, loop.stop)
    loop.run_until_complete(done)
    a.close()
    b.close()
    loop.close()
    return len(payload), state


def section_1():
    print("== 1 · THE LOOP IS A CYCLE: READY QUEUE FIRST, THEN TIMERS ==")
    loop = EventLoop()
    order, t_start = [], loop.time()
    fired = {}

    def mark(name, deadline=None):
        order.append(name)
        if deadline is not None:
            fired[name] = (loop.time() - t_start, deadline)

    loop.call_soon(mark, "soon-A")
    loop.call_soon(mark, "soon-B")
    loop.call_later(0.150, mark, "t+150ms", 0.150)
    loop.call_later(0.050, mark, "t+50ms", 0.050)
    loop.call_later(0.100, mark, "t+100ms", 0.100)
    doomed = loop.call_later(0.075, mark, "t+75ms-CANCELLED", 0.075)
    loop.call_soon(lambda: loop.call_soon(mark, "soon-C (scheduled from a callback)"))
    doomed.cancel()
    loop.call_later(0.200, loop.stop)
    loop.run_forever()

    print(f"  clock: time.monotonic() -- {loop.time():.3f}s since an arbitrary origin,")
    print("         immune to NTP steps, DST and someone running `date -s`")
    print("  firing order:")
    for i, name in enumerate(order, 1):
        print(f"    {i}. {name}")
    print("  timer accuracy (fired - deadline):")
    for name, (actual, deadline) in fired.items():
        print(f"    {name:<10} deadline {deadline*1000:6.1f} ms   fired {actual*1000:7.3f} ms"
              f"   drift {(actual - deadline)*1000:+6.3f} ms")
    print(f"  cancelled timer fired: {'t+75ms-CANCELLED' in order}")
    print(f"  loop iterations: {loop.iterations}   callbacks run: {loop.callbacks_run}   "
          f"select() calls: {loop.select_calls}")
    print(f"  time asleep in select(): {loop.time_in_select*1000:.1f} ms of "
          f"{(loop.time()-t_start)*1000:.1f} ms wall -- the loop is idle by design")
    loop.close()
    print()


def section_2_and_3():
    print("== 2 · A REAL HTTP SERVER ON THE LOOP: ONE THREAD, 24 CONNECTIONS ==")
    fast = bench(slow=False)
    n = len(fast["normal"])
    print(f"  24 concurrent keep-alive clients x 40 requests, {len(BODY)//1024} KiB responses")
    print(f"  requests served      : {fast['served']}  in {fast['wall']:.2f} s "
          f"({fast['served']/fast['wall']:.0f} req/s, single-threaded)")
    print(f"  loop iterations      : {fast['iterations']}   callbacks dispatched: {fast['callbacks']}")
    print(f"  partial writes       : {fast['partial_writes']}  (on loopback the kernel "
          f"swallows a 16 KiB response whole)")
    total, pw = partial_write_proof()
    print(f"  ...so prove the writer path separately: send 4 MiB down one socket")
    print(f"     first send() accepted {pw['first_send']:,} of {total:,} bytes "
          f"({100*pw['first_send']/total:.1f}%) -- a short write, not an error")
    print(f"     completed in {pw['sends']} send() calls, parked on add_writer "
          f"{pw['writer_calls']} times, {pw['received']:,} bytes received")
    print(f"  latency n={n}        : p50 {pct(fast['normal'],50):6.2f} ms   "
          f"p99 {pct(fast['normal'],99):7.2f} ms   max {max(fast['normal']):7.2f} ms")
    print(f"  longest ready-queue drain (loop lag): {fast['longest_drain']:.2f} ms")
    print()

    print("== 3 · THE MEASUREMENT: ONE HANDLER CALLS time.sleep(0.5) ==")
    slow = bench(slow=True)
    m = len(slow["normal"])
    print(f"  identical run, except request #21 on client 0 hits a handler that blocks 500 ms")
    print(f"  that one request took : {slow['slow_ms']:.1f} ms (it asked for it)")
    print(f"  longest ready-queue drain (loop lag): {slow['longest_drain']:.2f} ms")
    print()
    print("  latency of the OTHER 23 clients -- they did nothing wrong:")
    print(f"    {'':<14}{'p50':>9}{'p90':>9}{'p99':>10}{'max':>10}{'>100ms':>9}")
    for label, r in (("no blocking", fast), ("500ms block", slow)):
        vals = r["normal"]
        over = sum(1 for v in vals if v > 100.0)
        print(f"    {label:<14}{pct(vals,50):8.2f}ms{pct(vals,90):8.2f}ms"
              f"{pct(vals,99):9.2f}ms{max(vals):9.2f}ms{over:9d}")
    ratio = pct(slow["normal"], 99) / max(pct(fast["normal"], 99), 1e-9)
    print(f"    p99 got {ratio:.0f}x worse from ONE blocking call in ONE handler.")
    print(f"    p50 barely moved ({pct(fast['normal'],50):.2f} -> {pct(slow['normal'],50):.2f} ms): "
          f"the damage is entirely in the tail,")
    print(f"    spread across {sum(1 for v in slow['normal'] if v > 100.0)} innocent requests "
          f"out of {m}.")
    print()
    return fast, slow


def section_4():
    print("== 4 · WAKING A SLEEPING LOOP FROM ANOTHER THREAD ==")
    loop = EventLoop()
    done = Completion()
    log = {}

    def deliver(value, sent_at):
        log["wake_latency_ms"] = (loop.time() - sent_at) * 1000.0
        log["value"] = value
        done.set_result(value)

    def worker():
        time.sleep(0.30)                       # pretend this is a thread-pool job
        total = sum(i * i for i in range(200_000))
        sent = time.monotonic()
        loop.call_soon_threadsafe(deliver, total, sent)

    # Nothing is scheduled except a far-future safety timer, so select() blocks.
    loop.call_later(5.0, loop.stop)
    threading.Thread(target=worker, daemon=True).start()
    t0 = loop.time()
    loop.run_until_complete(done)
    wall = loop.time() - t0

    print(f"  worker thread slept 300 ms, then computed sum(i*i for i in range(200000))")
    print(f"  result delivered into the loop: {log['value']}")
    print(f"  loop was asleep in a SINGLE select() call for {loop.longest_select*1000:.1f} ms "
          f"of {wall*1000:.1f} ms wall")
    print(f"  select() calls in the whole run: {loop.select_calls} "
          f"(no polling, no spinning, 0% CPU while waiting)")
    print(f"  wakeup latency, socketpair write -> callback ran: "
          f"{log['wake_latency_ms']:.3f} ms")
    print("  without the socketpair the loop would have slept until the 5 s safety timer")
    loop.close()
    print()


def callback_style_flow(loop, sock, done, depths, trace):
    """read request -> "query" -> write response -> log. Three steps, four callbacks."""
    def on_readable(fd):                                           # nesting level 1
        loop.remove_reader(fd)
        depths["read"] = len(inspect.stack())
        request = sock.recv(4096).decode().strip()
        trace.append(f"step 1  read request  : {request!r}")

        def on_query_done(rows):                                   # nesting level 2
            depths["query"] = len(inspect.stack())
            trace.append(f"step 2  query returned: {rows} rows (50 ms later)")

            def on_written(nbytes):                                # nesting level 3
                depths["write"] = len(inspect.stack())
                trace.append(f"step 3  response sent : {nbytes} bytes")

                def on_logged():                                   # nesting level 4
                    depths["log"] = len(inspect.stack())
                    trace.append("step 4  access log written")
                    done.set_result(True)

                loop.call_soon(on_logged)

            body = f"200 OK rows={rows}".encode()
            sock.send(body)
            loop.call_soon(on_written, len(body))

        loop.call_later(0.05, on_query_done, 3)     # a "database call", async-style

    loop.add_reader(sock.fileno(), on_readable, sock.fileno())


def section_5():
    print("== 5 · CALLBACK HELL, MEASURED ==")
    loop = EventLoop()
    done = Completion()
    depths, trace = {}, []

    srv, cli = socket.socketpair()
    srv.setblocking(False)
    cli.setblocking(False)

    callback_style_flow(loop, srv, done, depths, trace)
    cli.send(b"GET /order/42\n")
    loop.call_later(2.0, loop.stop)
    loop.run_until_complete(done)

    for line in trace:
        print("  " + line)
    src = inspect.getsource(callback_style_flow).splitlines()
    indent = max(len(ln) - len(ln.lstrip()) for ln in src if ln.strip())
    print(f"  source shape   : {len([ln for ln in src if ln.lstrip().startswith('def ')])}"
          f" `def`s, max indentation {indent} columns ({indent // 4} levels deep)"
          f" -- for ONE linear request")
    print("  python stack depth when each step ran:")
    for name in ("read", "query", "write", "log"):
        print(f"    {name:<6} {depths[name]} frames")
    print(f"  all four are identical -> every step ran directly off the loop, with NO")
    print(f"    caller between it and _run_once. There is no stack to raise through.")

    # Now prove the error path has nowhere to go.
    loop2 = EventLoop()
    stop2 = Completion()
    a, b = socket.socketpair()
    a.setblocking(False)

    def step_one(fd):
        loop2.remove_reader(fd)
        a.recv(4096)

        def step_two():
            raise ValueError("row 42 is corrupt")   # deep inside the callback chain

        loop2.call_later(0.02, step_two)
        loop2.call_later(0.10, stop2.set_result, None)

    loop2.add_reader(a.fileno(), step_one, a.fileno())
    b.send(b"GET /order/43\n")
    caught_by_caller = None
    try:
        loop2.run_until_complete(stop2)
    except ValueError as exc:                       # this NEVER fires
        caught_by_caller = exc
    print(f"  error path: caller's try/except around run_until_complete caught: "
          f"{caught_by_caller}")
    print(f"              the loop's exception handler caught : {loop2.exceptions}")
    print("              -> the request is abandoned mid-flight; the socket stays open;")
    print("                 no `except` anywhere in the request's own logic can see it.")
    print("  Lesson 5 replaces all of this with `rows = await db.query(...)`: one stack,")
    print("    one try/except, and a real `for` loop over I/O.")
    for s in (srv, cli, a, b):
        s.close()
    loop.close()
    loop2.close()
    print()


def main():
    t0 = time.monotonic()
    section_1()
    fast, slow = section_2_and_3()
    section_4()
    section_5()
    print(f"(total runtime {time.monotonic() - t0:.1f}s)")


if __name__ == "__main__":
    main()
