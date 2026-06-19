"""Shared connection helper for the raw-sqlite3 stores in this package.

The four KV-shaped tables in ``core/session/`` (session_directories,
client_state, pending_messages, session_preferences) all share the
same concurrency story: one BE process, N sessions, potentially N
threads competing for the same file via ``asyncio.to_thread``. They
need three things at every connection:

* **WAL journal mode** — readers don't block writers and vice versa,
  so a session's ``get_dir`` doesn't stall behind another session's
  ``set_dir`` commit on the same file.
* **A real busy-timeout** — without one, sqlite raises
  ``OperationalError: database is locked`` immediately on contention.
  5 s matches what callers do anyway (their per-call latency budget).
* **Explicit close** — sqlite3's context-manager ``with conn:`` only
  commits/rolls back, it does NOT close the connection. Leaking
  Connections under a hot loop manifests as a slow memory creep until
  GC catches them. Always pair ``connect_kv`` with
  ``contextlib.closing``.

The pragmas are idempotent: once WAL is set on a file, future
connections inherit it; the pragma is cheap and safe to re-set.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# 5 s matches the BE's per-RPC budget; if contention exceeds this, the
# DB really is wedged and failing the call is the right outcome.
_BUSY_TIMEOUT_MS = 5_000


def connect_kv(db_path: str | Path) -> sqlite3.Connection:
    """Open a sqlite3 connection configured for safe concurrent use.

    Caller MUST pair this with ``contextlib.closing(...)`` to release
    the file handle promptly — otherwise the connection lingers until
    the next GC pass.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    # WAL → concurrent readers + a single writer; serialised across
    # connections to the same file via the WAL lock. ``PRAGMA`` returns
    # the active mode; we don't strictly need to read it, but ignoring
    # the result is fine.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    return conn
