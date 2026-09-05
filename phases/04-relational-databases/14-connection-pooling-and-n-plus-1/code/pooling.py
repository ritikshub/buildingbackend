#!/usr/bin/env python3
"""
Connection pooling and the N+1 query problem: the app-to-database seam.

Companion to docs/en.md (Phase 03, Lesson 14). Part 1 builds a bounded, thread-safe
connection pool and shows it caps and REUSES connections instead of paying the (simulated)
handshake cost per request. Part 2 runs the same author/book query three ways - N+1, a
single JOIN, and a batched IN - and counts the queries each costs.

Runs standalone on the Python standard library only:  python pooling.py
"""
import os
import sqlite3
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager


# --- Part 1: a bounded connection pool ------------------------------------------------

class FakeConnection:
    """Stands in for a real DB connection whose setup cost we want to avoid repeating."""
    def close(self) -> None:
        pass


class ConnectionPool:
    def __init__(self, factory, size: int = 5):
        self._factory = factory
        self._size = size
        self._sem = threading.Semaphore(size)   # caps concurrently checked-out conns
        self._idle: list = []
        self._lock = threading.Lock()
        self.opened = 0                          # how many real connections we created

    def _open(self):
        self.opened += 1
        return self._factory()

    @contextmanager
    def acquire(self, timeout: float = 5.0):
        if not self._sem.acquire(timeout=timeout):
            raise TimeoutError("connection pool exhausted")
        conn = None
        try:
            with self._lock:
                conn = self._idle.pop() if self._idle else self._open()
            yield conn
        finally:
            with self._lock:
                self._idle.append(conn)          # return it for the next borrower
            self._sem.release()


HANDSHAKE = 0.02   # simulated TCP+TLS+auth cost per real connection open
WORKERS = 5        # same concurrency for both runs, so only the handshake count differs


def make_connection() -> FakeConnection:
    time.sleep(HANDSHAKE)
    return FakeConnection()


def run_task(pool: ConnectionPool) -> None:
    with pool.acquire() as conn:      # borrow
        time.sleep(0.002)             # do a little "query" work
        _ = conn                      # ...then the 'with' returns it automatically


def demo_pool() -> None:
    print("== Part 1: connection pooling ==")
    tasks = 40

    # Without a pool: every task opens (and pays the handshake for) its own connection.
    no_pool_opens = 0

    def no_pool_task():
        nonlocal no_pool_opens
        make_connection()             # a fresh handshake every time
        no_pool_opens += 1
        time.sleep(0.002)

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(lambda _: no_pool_task(), range(tasks)))
    no_pool_time = time.perf_counter() - start

    # With a pool of 5 (same concurrency): connections are opened once and reused.
    pool = ConnectionPool(make_connection, size=WORKERS)
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(lambda _: run_task(pool), range(tasks)))
    pool_time = time.perf_counter() - start

    print(f"  {tasks} tasks, no pool : {no_pool_opens} connections opened, "
          f"{no_pool_time * 1000:5.0f} ms  (a handshake every time)")
    print(f"  {tasks} tasks, pooled  : {pool.opened} connections opened, "
          f"{pool_time * 1000:5.0f} ms  <- opened once, reused")
    assert pool.opened <= 5, "the pool must never open more than its size"
    assert no_pool_opens == tasks, "without a pool, every task opens its own connection"


# --- Part 2: the N+1 problem and its fixes --------------------------------------------

class CountingDB:
    """A SQLite wrapper that counts how many queries were executed."""
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.queries = 0

    def query(self, sql: str, params=()):
        self.queries += 1
        return self.conn.execute(sql, params).fetchall()

    def reset(self):
        self.queries = 0


def seed(path: str, n_authors: int = 5, books_each: int = 3) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE author (id INTEGER PRIMARY KEY, name TEXT);"
        "CREATE TABLE book (id INTEGER PRIMARY KEY, author_id INTEGER, title TEXT);"
    )
    for a in range(1, n_authors + 1):
        conn.execute("INSERT INTO author (id, name) VALUES (?, ?)", (a, f"Author {a}"))
        for b in range(books_each):
            conn.execute(
                "INSERT INTO book (author_id, title) VALUES (?, ?)",
                (a, f"Book {a}.{b}"),
            )
    conn.commit()
    conn.close()


def demo_n_plus_1(path: str) -> None:
    print("\n== Part 2: N+1 vs JOIN vs batched ==")
    db = CountingDB(path)
    n = len(db.query("SELECT id FROM author"))
    db.reset()

    # N+1: one query for the list, then one per author for their books.
    authors = db.query("SELECT id, name FROM author")     # 1
    for author_id, _name in authors:
        db.query("SELECT title FROM book WHERE author_id = ?", (author_id,))  # N
    n_plus_1 = db.queries
    print(f"  N+1 pattern : {n_plus_1} queries   (1 + {n} authors)")

    # Fix A - a single JOIN: the database does the combining in one round trip.
    db.reset()
    db.query(
        "SELECT author.name, book.title "
        "FROM author JOIN book ON book.author_id = author.id"
    )
    join = db.queries
    print(f"  JOIN        : {join} query    (all authors + books at once)")

    # Fix B - a batched IN: fetch the list, then all children in one query.
    db.reset()
    authors = db.query("SELECT id FROM author")            # 1
    ids = [row[0] for row in authors]
    placeholders = ",".join("?" * len(ids))
    db.query(f"SELECT author_id, title FROM book WHERE author_id IN ({placeholders})", ids)
    batched = db.queries
    print(f"  batched IN  : {batched} queries   (list + one batched fetch)")

    db.conn.close()
    assert n_plus_1 == 1 + n, "N+1 should cost 1 + N queries"
    assert join == 1, "a JOIN should cost exactly 1 query"
    assert batched == 2, "batching should cost exactly 2 queries"


def main() -> None:
    demo_pool()
    tmp = tempfile.NamedTemporaryFile(prefix="np1_", suffix=".db", delete=False)
    tmp.close()
    try:
        seed(tmp.name)
        demo_n_plus_1(tmp.name)
    finally:
        os.unlink(tmp.name)
    print("\nAll self-checks passed.")


if __name__ == "__main__":
    main()
