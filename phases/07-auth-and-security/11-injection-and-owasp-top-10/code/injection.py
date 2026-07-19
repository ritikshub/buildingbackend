#!/usr/bin/env python3
"""
Injection, run for real — SQL injection, command injection, path traversal, SSRF
— and the one durable fix: separate code from data.

Companion to docs/en.md (Phase 07, Lesson 11). What it makes concrete:

  * SQL injection against a REAL sqlite3 database: string concatenation lets the
    input become SQL; a parameterized query binds it as data, so it can't.
  * Command injection dies when you drop the shell (argument list, shell=False),
    demonstrated harmlessly with `echo`.
  * Path traversal is stopped by confining the resolved path to a base directory.
  * SSRF is stopped by an allowlist plus blocking loopback/private/link-local
    ranges (the cloud metadata endpoint 169.254.169.254 is link-local).

Stdlib only:  python3 injection.py
"""

from __future__ import annotations

import ipaddress
import os
import socket
import sqlite3
import subprocess
import urllib.parse


# ── 1 · SQL injection (real sqlite3) ─────────────────────────────────────────

def demo_sql() -> None:
    print("== 1 · SQL INJECTION (real sqlite3) ==")
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE users (name TEXT, email TEXT)")
    db.executemany("INSERT INTO users VALUES (?, ?)",
                   [("alice", "alice@acme.com"), ("bob", "bob@acme.com"), ("carol", "carol@acme.com")])
    print("  users table has 3 rows (alice, bob, carol)")

    rows = db.execute("SELECT name, email FROM users WHERE name = '" + "alice" + "'").fetchall()
    print(f"  search 'alice'         -> {len(rows)} row   {rows}")

    attack = "' OR '1'='1"
    vuln = db.execute("SELECT name, email FROM users WHERE name = '" + attack + "'").fetchall()
    print(f"""  VULNERABLE  name="{attack}"  -> {len(vuln)} rows   ✗ dumped the whole table""")

    safe = db.execute("SELECT name, email FROM users WHERE name = ?", (attack,)).fetchall()
    print(f"""  PARAMETERIZED name="{attack}" -> {len(safe)} rows   ✓ treated as a literal name""")


# ── 2 · Command injection (drop the shell) ───────────────────────────────────

def demo_command() -> None:
    print("\n== 2 · COMMAND INJECTION (drop the shell) ==")
    payload = "8.8.8.8; echo PWNED"
    print(f'  host="{payload}"  (using echo instead of ping — harmless demo)')
    # shell=True: the shell parses ';' and runs a SECOND command -> injection
    out = subprocess.run(f"echo pinging {payload}", shell=True, capture_output=True, text=True).stdout.strip()
    print(f"  shell=True  -> output: {out!r}   ✗ (the injected 'echo PWNED' ran)")
    # shell=False: the payload is a single argument, never parsed as shell syntax
    out2 = subprocess.run(["echo", "pinging", payload], capture_output=True, text=True).stdout.strip()
    print(f"  shell=False -> output: {out2!r}   ✓ (one literal argument)")


# ── 3 · Path traversal (confine to a base dir) ───────────────────────────────

def safe_path(base: str, name: str) -> str | None:
    full = os.path.realpath(os.path.join(base, name))            # resolve .. and symlinks
    root = os.path.realpath(base)
    return full if full == root or full.startswith(root + os.sep) else None


def demo_path() -> None:
    print("\n== 3 · PATH TRAVERSAL (confine to a base dir) ==")
    base = "/srv/uploads"
    for name in ("report.pdf", "../../etc/passwd"):
        p = safe_path(base, name)
        verdict = f"{p}   ✓ allowed" if p else "blocked (escapes base)     ✓"
        print(f'  base={base}   name="{name}"'.ljust(48) + f"-> {verdict}")


# ── 4 · SSRF (allowlist + block internal ranges) ─────────────────────────────

ALLOWED_HOSTS = {"api.partner.com"}


def _resolve(host: str):
    try:
        return ipaddress.ip_address(host)                        # already a literal IP
    except ValueError:
        try:
            return ipaddress.ip_address(socket.gethostbyname(host))
        except OSError:
            return None                                          # unresolvable (offline) → treat as non-internal


def ssrf_check(url: str) -> tuple[bool, str]:
    host = urllib.parse.urlparse(url).hostname or ""
    if host in ALLOWED_HOSTS:                                    # allowlist is the positive gate
        return True, "allowed (public, allowlisted)"            # (prod also re-resolves: DNS rebinding)
    ip = _resolve(host)
    if ip is not None and (ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved):
        kind = "loopback" if ip.is_loopback else "link-local" if ip.is_link_local else "private"
        return False, f"blocked ({kind}: internal)"
    return False, "blocked (not on allowlist)"


def demo_ssrf() -> None:
    print("\n== 4 · SSRF (allowlist / block internal ranges) ==")
    for url in ("https://api.partner.com/hook", "http://169.254.169.254/latest/meta-data/",
                "http://localhost:6379/"):
        ok, why = ssrf_check(url)
        print(f"  {url:44s} -> {why}   ✓")


def main() -> None:
    demo_sql()
    demo_command()
    demo_path()
    demo_ssrf()


if __name__ == "__main__":
    main()
