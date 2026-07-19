"""
Keep-Alive & Connection Pooling — a thread-safe TCP connection pool, by hand.

Runs N requests against a local echo server two ways: opening a fresh socket per
request (a new TCP handshake every time) versus borrowing from a bounded pool of
reused, kept-alive connections. Both are timed with time.perf_counter to show the
reuse win. Stdlib only (socket, threading, time, queue); localhost only; exits 0.

Docs: phases/01-networking-and-protocols/14-keep-alive-pooling-timeouts/docs/en.md
Spec: RFC 9112 §9 (HTTP/1.1 persistent connections / keep-alive)

Run:
    python3 connection_pool.py
It starts a server, runs both scenarios, prints the comparison, and exits 0.
"""

from __future__ import annotations

import queue
import socket
import threading
import time

HOST = "127.0.0.1"
N_REQUESTS = 24        # how many requests each scenario performs
POOL_SIZE = 4          # max open connections the pool is allowed to hold
CONCURRENT_WORKERS = 8  # threads sharing the bounded pool in the safety demo

# A stand-in for the real cost of opening a connection. On localhost a TCP
# handshake is near-instant, which hides the whole point; over a real network
# every new connection costs at least one round-trip (and a TLS handshake adds
# more on top for HTTPS). We add this fixed delay to each *new* connection so the
# demo reflects the reality that pooling is built to avoid.
CONNECT_COST_S = 0.005  # 5 ms of modeled handshake latency per new connection


class EchoServer:
    """A tiny keep-alive TCP echo server on a background thread.

    Each accepted connection is handled in its own thread that loops on recv():
    the socket stays open and serves many requests until the client closes it.
    That persistence is exactly what keep-alive means (RFC 9112 §9)."""

    def __init__(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((HOST, 0))            # port 0 => OS picks a free port
        self.port = self._sock.getsockname()[1]
        self._sock.listen(128)

    def serve_forever(self) -> None:
        while True:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return                        # listener closed -> stop
            threading.Thread(
                target=self._handle, args=(conn,), daemon=True
            ).start()

    def _handle(self, conn: socket.socket) -> None:
        with conn:
            while True:
                data = conn.recv(1024)
                if not data:                  # client closed -> connection done
                    return
                conn.sendall(data)            # echo the request straight back

    def close(self) -> None:
        self._sock.close()


def open_connection(host: str, port: int) -> socket.socket:
    """Open one TCP connection, paying the modeled handshake cost once."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))                # SYN / SYN-ACK / ACK happens here
    time.sleep(CONNECT_COST_S)                # models handshake (+TLS) round-trip
    return sock


class ConnectionPool:
    """A bounded, thread-safe pool of reusable TCP connections.

    acquire() hands out an idle connection, opening a new one only while the
    pool is below max_size; once at capacity, callers block until someone
    release()s one back. This is the same acquire/release contract every HTTP
    client library and database driver exposes."""

    def __init__(self, host: str, port: int, max_size: int) -> None:
        self._host = host
        self._port = port
        self._max_size = max_size
        self._idle: queue.LifoQueue = queue.LifoQueue()  # idle, ready-to-reuse
        self._lock = threading.Lock()
        self.opened = 0                       # total connections ever opened

    def acquire(self, timeout: float = 5.0) -> socket.socket:
        # Fast path: reuse an already-open, idle connection.
        try:
            return self._idle.get_nowait()
        except queue.Empty:
            pass
        # No idle connection. Open a new one only if under the size limit.
        with self._lock:
            may_open = self.opened < self._max_size
            if may_open:
                self.opened += 1
        if may_open:
            return open_connection(self._host, self._port)
        # At capacity: wait for another caller to release one back.
        return self._idle.get(timeout=timeout)

    def release(self, conn: socket.socket) -> None:
        self._idle.put(conn)                  # return it for the next caller

    def close(self) -> None:
        while True:
            try:
                self._idle.get_nowait().close()
            except queue.Empty:
                return


def one_request(conn: socket.socket, payload: bytes) -> bytes:
    conn.sendall(payload)
    return conn.recv(1024)


def without_pool(host: str, port: int) -> float:
    """N requests, each on a brand-new connection (no reuse). Returns seconds."""
    start = time.perf_counter()
    for i in range(N_REQUESTS):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((host, port))
            time.sleep(CONNECT_COST_S)        # same modeled handshake cost, paid
            one_request(sock, f"request {i}".encode())  # ...every single time
    return time.perf_counter() - start


def with_pool(pool: ConnectionPool) -> float:
    """N requests, each borrowing a reused connection from the pool. Seconds."""
    start = time.perf_counter()
    for i in range(N_REQUESTS):
        conn = pool.acquire()
        try:
            one_request(conn, f"request {i}".encode())
        finally:
            pool.release(conn)                # hand it back for reuse
    return time.perf_counter() - start


def concurrency_safety_demo(pool: ConnectionPool) -> None:
    """Prove the pool is thread-safe: more workers than connections, all sharing
    the bounded set, never exceeding max_size open sockets and never erroring."""
    errors: list = []
    barrier = threading.Barrier(CONCURRENT_WORKERS)

    def worker() -> None:
        barrier.wait()                        # start together to force contention
        try:
            for i in range(N_REQUESTS):
                conn = pool.acquire()
                try:
                    echo = one_request(conn, f"w{i}".encode())
                    assert echo == f"w{i}".encode()
                finally:
                    pool.release(conn)
        except Exception as exc:              # noqa: BLE001 - report, don't crash
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(CONCURRENT_WORKERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    print(f"[safety] {CONCURRENT_WORKERS} threads x {N_REQUESTS} requests shared "
          f"the pool with {errors and 'ERRORS' or 'no errors'}")
    print(f"[safety] connections ever opened: {pool.opened} "
          f"(capped at max_size={POOL_SIZE})")
    assert not errors, f"pool was not thread-safe: {errors}"
    assert pool.opened <= POOL_SIZE, "pool exceeded its size limit"


def main() -> None:
    server = EchoServer()
    threading.Thread(target=server.serve_forever, daemon=True).start()

    # Scenario 1: a fresh connection per request.
    no_pool_s = without_pool(HOST, server.port)
    print(f"[no pool] {N_REQUESTS} requests, {N_REQUESTS} new connections "
          f"(handshakes) -> {no_pool_s * 1000:6.1f} ms")

    # Scenario 2: a bounded pool of reused, kept-alive connections.
    pool = ConnectionPool(HOST, server.port, max_size=POOL_SIZE)
    pooled_s = with_pool(pool)
    print(f"[pool]    {N_REQUESTS} requests, {pool.opened} new connection(s) "
          f"reused -> {pooled_s * 1000:6.1f} ms")

    speedup = no_pool_s / pooled_s if pooled_s else float("inf")
    print(f"[result]  pooling reused connections and ran {speedup:.1f}x faster, "
          f"opening {pool.opened} connection(s) instead of {N_REQUESTS}")

    # Scenario 3: the same pool under concurrent load, proving thread-safety.
    concurrency_safety_demo(pool)

    pool.close()
    server.close()
    print("[done] keep-alive + pooling reused connections and skipped the "
          "per-request handshake.")


if __name__ == "__main__":
    main()
