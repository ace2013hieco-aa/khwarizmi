"""Database connection management (v4 §16.4) — SQLite WAL, single-writer lock.

Configures SQLite deliberately for Hermes' workload:
  - WAL mode (concurrent readers, single writer)
  - Foreign keys enabled (FK enforcement)
  - busy_timeout (graceful lock contention handling)
  - Advisory lock table (single-writer controller discipline, v4 §8)

All domain objects go through repositories (Phase 1 req §18) — no raw SQL
outside this module and ``migrations.py``.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from hermes.core import Clock, utc_now


class SchemaVersionError(Exception):
    """Raised when the database schema version is not supported.

    - schema > supported → refuse to start (unknown future schema)
    - schema < supported → should have been migrated by migrations.py
    """
    def __init__(self, current: int, supported: int):
        self.current = current
        self.supported = supported
        super().__init__(
            f"Database schema version {current} is not supported "
            f"(supported: {supported}). "
            f"{'Run migrations first.' if current < supported else 'Refusing to operate against unknown future schema.'}"
        )


class DatabaseLockError(Exception):
    """The single-writer advisory lock cannot be acquired, or a release was
    refused because the connection's open transaction is not the caller's
    writer-lock acquisition transaction (C-F-08)."""


def _configure_pragmas(conn: sqlite3.Connection) -> None:
    """Apply Hermes-standard PRAGMAs to a connection."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")  # 5 seconds (IDR-015)


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection configured for Hermes (WAL + FK + busy_timeout).

    Args:
        db_path: Path to the SQLite database file. Use ":memory:" for tests.

    Returns:
        A configured ``sqlite3.Connection`` with ``row_factory = Row``.
    """
    # check_same_thread=False (C2): the controller's mid-execution heartbeat
    # refresher shares this connection from its daemon thread — the lease
    # holder is the only writer, SQLite + busy_timeout serialize, and the
    # fenced write check still guards every statement.
    conn = sqlite3.connect(
        str(db_path), isolation_level=None,
        check_same_thread=False)  # autocommit
    conn.row_factory = sqlite3.Row
    _configure_pragmas(conn)
    return conn


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Return the current schema version (0 if the table doesn't exist yet).

    Returns the MAX version from schema_version (not the first row),
    so multiple migration records don't cause a stale read.
    """
    try:
        row = conn.execute("SELECT MAX(version) as v FROM schema_version").fetchone()
        return row["v"] if row and row["v"] is not None else 0
    except sqlite3.OperationalError:
        # schema_version table doesn't exist → version 0 (clean database)
        return 0


def assert_schema_version(conn: sqlite3.Connection, supported: int) -> None:
    """Raise ``SchemaVersionError`` if the DB schema != supported.

    - version == supported → proceed
    - version < supported  → raise (migrations should have run first)
    - version > supported  → raise (unknown future schema)
    """
    current = get_schema_version(conn)
    if current != supported:
        raise SchemaVersionError(current, supported)


def acquire_writer_lock(conn: sqlite3.Connection, owner_id: str = "default",
                         clock: Clock | None = None) -> bool:
    """Acquire the single-writer advisory lock (v4 §8).

    F-02: The lock is a single-row advisory lock that tracks the owner and
    timestamp. A second owner fails to acquire and returns False. The lock
    is released by ``release_writer_lock`` which DELETEs the row, allowing
    re-acquisition.

    Stale-owner behavior: if the lock row exists but the owner is known to
    be stale (caller responsibility — e.g. lease expiry or crash detection),
    the caller calls ``release_writer_lock`` on a fresh connection to
    clear it, then acquires.

    Uses ``BEGIN IMMEDIATE`` so a second writer blocks (busy_timeout) then
    fails rather than silently proceeding.

    C-F-08: a successful acquire opens the caller-owned transaction whose
    lock row is visible only on this connection. The matching
    ``release_writer_lock`` therefore requires the caller to pass the same
    ``owner_id`` it acquired under — the release verifies it is committing
    ITS OWN acquisition transaction, never a foreign one.
    """
    ts = (clock or utc_now)()
    begun = False
    try:
        conn.execute("BEGIN IMMEDIATE")
        begun = True
        row = conn.execute("SELECT COUNT(*) as n FROM scheduler_lock").fetchone()
        if row["n"] == 0:
            conn.execute(
                "INSERT INTO scheduler_lock (id, owner, locked_at) VALUES (0, ?, ?)",
                (owner_id, ts),
            )
            # Don't commit yet — the caller holds the lock until they COMMIT/ROLLBACK
            return True
        # Already locked — fall through to the shared refusal path below.
    except sqlite3.OperationalError:
        # BEGIN IMMEDIATE failed (another writer holds the lock), or the
        # scheduler_lock table is missing — refuse. Fall through to the
        # shared refusal path below.
        pass
    # FIX-FENCE-CLASSIFIER (IMPROVE-B B-F-04): a REFUSED acquire must never
    # leave an open transaction behind — pre-fix, a failed post-BEGIN
    # statement (e.g. the scheduler_lock table is missing) returned False
    # with in_transaction=True, and the next BEGIN then failed with "cannot
    # start a transaction within a transaction". A SUCCESSFUL acquire still
    # leaves its transaction open (the caller-owned contract documented
    # above); only the refusal path rolls back, and only when BEGIN actually
    # started a transaction.
    if begun:
        conn.execute("ROLLBACK")
    return False


def release_writer_lock(conn: sqlite3.Connection,
                         owner_id: str | None = None) -> None:
    """Release the single-writer lock by deleting the lock row.

    F-02: The lock can be released and then re-acquired (unlike the old
    code which INSERTed but never DELETEd, bricking the lock after one use).

    Ownership of the ROW stays the caller's responsibility: on a fresh
    recovery connection (no open transaction) this deletes the row
    unconditionally — the documented stale-owner recovery surface — after
    confirming the previous owner is dead (e.g. via lease expiry or crash
    detection).

    C-F-08: this function NEVER COMMITs a transaction it did not open. When
    a transaction is already active (the documented acquire -> release
    chain keeps the acquire's transaction open), the caller MUST assert the
    owner it acquired under and the lock row visible inside that
    transaction must carry that owner — otherwise ``DatabaseLockError`` is
    raised and the foreign transaction is left exactly as it was (nothing
    deleted, nothing committed). An open transaction that carries no
    matching acquisition row is refused.

    Opens its own ``BEGIN IMMEDIATE`` transaction so it works on a fresh
    recovery connection (autocommit mode, no active transaction).
    """
    # F-02 fix: Open our own transaction so this works on a fresh recovery
    # connection (autocommit mode, no active transaction). The old code
    # called DELETE then COMMIT unconditionally; on a recovery connection
    # the spurious COMMIT raised OperationalError.
    begun = False
    try:
        conn.execute("BEGIN IMMEDIATE")
        begun = True
    except sqlite3.OperationalError as e:
        # Only swallow "cannot start a transaction within a transaction"
        # (a transaction is already active on this connection). Let other
        # OperationalErrors (e.g. "database is locked" after busy_timeout)
        # propagate so the caller knows contention occurred.
        if "cannot start a transaction" not in str(e):
            raise
        # C-F-08 — a transaction is already open and THIS call did not open
        # it. COMMITing it would flush work the writer-lock API does not own
        # (probe: an unrelated insert was made durable this way). The only
        # legitimate open-transaction caller is the acquire -> release
        # chain: prove ownership first — the caller's assertion plus the
        # lock row the acquisition inserted into this same transaction —
        # and refuse otherwise, leaving the foreign transaction untouched.
        if owner_id is None:
            raise DatabaseLockError(
                "release_writer_lock refused: a transaction this call did not "
                "open is active on the connection — pass owner_id=<the owner "
                "you acquired under> only for the writer-lock acquisition "
                "transaction; COMMIT or ROLLBACK the caller-owned transaction "
                "first otherwise (C-F-08)") from None
        row = conn.execute(
            "SELECT owner FROM scheduler_lock WHERE id = 0").fetchone()
        row_owner = row[0] if row is not None else None
        if row_owner != owner_id:
            raise DatabaseLockError(
                f"release_writer_lock refused: the open transaction does not "
                f"carry the writer-lock acquisition row for owner "
                f"{owner_id!r} (found {row_owner!r}) — refusing to DELETE or "
                f"COMMIT a foreign transaction (C-F-08)") from None
    if begun:
        # Self-owned transaction (fresh/recovery connection): the
        # documented unconditional stale-owner DELETE is unchanged.
        conn.execute("DELETE FROM scheduler_lock WHERE id = 0")
    else:
        # Caller-owned acquisition transaction, ownership verified above:
        # delete only the row this acquisition created, then commit it.
        conn.execute(
            "DELETE FROM scheduler_lock WHERE id = 0 AND owner = ?",
            (owner_id,),
        )
    conn.execute("COMMIT")


def get_lock_owner(conn: sqlite3.Connection) -> str | None:
    """Return the current lock owner, or None if not locked."""
    row = conn.execute("SELECT owner FROM scheduler_lock WHERE id = 0").fetchone()
    return row["owner"] if row else None


def integrity_check(conn: sqlite3.Connection) -> bool:
    """Run ``PRAGMA integrity_check`` and return True if the database is clean."""
    row = conn.execute("PRAGMA integrity_check").fetchone()
    return row is not None and row[0] == "ok"


def foreign_key_check(conn: sqlite3.Connection) -> bool:
    """Run ``PRAGMA foreign_key_check`` and return True if no violations."""
    rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    return len(rows) == 0
