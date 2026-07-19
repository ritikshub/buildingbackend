#!/usr/bin/env python3
"""
A migration runner: versioned, idempotent, ordered schema evolution.

Companion to docs/en.md (Phase 03, Lesson 15 - Migrations & Schema Evolution). The runner
records applied versions in a schema_migrations table and applies only the PENDING ones,
in order, each in a transaction - so running it twice is a no-op. Migration 4 shows the
EXPAND step of expand-contract: add a nullable column, then backfill it in batches.

Runs standalone on the Python standard library only:  python migrate.py
"""
import os
import sqlite3
import tempfile
from typing import Callable, NamedTuple


class Migration(NamedTuple):
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]

    def __lt__(self, other):            # sort by version
        return self.version < other.version


def ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  version INTEGER PRIMARY KEY,"
        "  name TEXT NOT NULL"
        ")"
    )
    conn.commit()


def migrate(conn: sqlite3.Connection, migrations: list[Migration]) -> list[int]:
    """Apply every pending migration in order; return the versions applied this run."""
    ensure_migrations_table(conn)
    done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    pending = [m for m in sorted(migrations) if m.version not in done]
    for m in pending:
        m.apply(conn)                                    # the 'up': DDL and/or backfill
        conn.execute(
            "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
            (m.version, m.name),
        )
        conn.commit()                                    # each migration is atomic
    return [m.version for m in pending]


# --- The migrations (in a real project, one file each) --------------------------------

def _create_users(conn):
    conn.execute(
        "CREATE TABLE users ("
        "  id INTEGER PRIMARY KEY,"
        "  email TEXT NOT NULL UNIQUE,"
        "  name TEXT NOT NULL"
        ")"
    )


def _create_orders(conn):
    conn.execute(
        "CREATE TABLE orders ("
        "  id INTEGER PRIMARY KEY,"
        "  user_id INTEGER NOT NULL REFERENCES users(id),"
        "  total NUMERIC NOT NULL"
        ")"
    )


def _seed_demo_rows(conn):
    conn.executemany(
        "INSERT INTO users (id, email, name) VALUES (?, ?, ?)",
        [(1, "ada@x.org", "Ada"), (2, "grace@y.mil", "Grace")],
    )
    conn.executemany(
        "INSERT INTO orders (id, user_id, total) VALUES (?, ?, ?)",
        [(i, 1 + i % 2, 10 * i) for i in range(1, 8)],
    )


def _expand_add_status(conn):
    """EXPAND step: add a nullable column, then backfill existing rows in batches."""
    conn.execute("ALTER TABLE orders ADD COLUMN status TEXT")   # nullable -> safe, no lock
    # Backfill in small batches instead of one giant UPDATE (which would lock/bloat).
    BATCH = 3
    while True:
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM orders WHERE status IS NULL LIMIT ?", (BATCH,))]
        if not ids:
            break
        conn.executemany("UPDATE orders SET status = 'pending' WHERE id = ?",
                         [(i,) for i in ids])
        conn.commit()


MIGRATIONS_V1_3 = [
    Migration(1, "create_users", _create_users),
    Migration(2, "create_orders", _create_orders),
    Migration(3, "seed_demo_rows", _seed_demo_rows),
]
MIGRATION_V4 = Migration(4, "expand_orders_status", _expand_add_status)


def main() -> None:
    tmp = tempfile.NamedTemporaryFile(prefix="mig_", suffix=".db", delete=False)
    tmp.close()
    path = tmp.name
    try:
        conn = sqlite3.connect(path)

        print("Fresh database. Applying migrations 1-3:")
        applied = migrate(conn, MIGRATIONS_V1_3)
        print(f"  applied: {applied}")

        print("\nRunning the migrator again (nothing changed):")
        applied = migrate(conn, MIGRATIONS_V1_3)
        print(f"  applied: {applied}   <- idempotent, 0 pending")

        print("\nA new migration (4) ships. Applying:")
        applied = migrate(conn, MIGRATIONS_V1_3 + [MIGRATION_V4])
        print(f"  applied: {applied}   <- only the pending one runs")

        # Show the backfill worked and the ledger of what ran.
        statuses = conn.execute(
            "SELECT DISTINCT status FROM orders").fetchall()
        print(f"\norders.status after expand + backfill: {[s[0] for s in statuses]}")
        ledger = conn.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version").fetchall()
        print("schema_migrations ledger:")
        for version, name in ledger:
            print(f"  {version}  {name}")

        # Self-checks so the demo verifies itself and exits non-zero on regression.
        assert migrate(conn, MIGRATIONS_V1_3 + [MIGRATION_V4]) == [], "must be idempotent"
        assert [s[0] for s in statuses] == ["pending"], "backfill must set every row"
        assert [v for v, _ in ledger] == [1, 2, 3, 4], "all four migrations recorded in order"
        none_null = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE status IS NULL").fetchone()[0]
        assert none_null == 0, "no row should be left un-backfilled"
        conn.close()
        print("\nAll self-checks passed.")
    finally:
        os.unlink(path)


if __name__ == "__main__":
    main()
