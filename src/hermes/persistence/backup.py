"""Database backup and restore (v4 §16.4, IDR-014).

Uses the SQLite Online Backup API (``sqlite3.Connection.backup()``) — safe
to run while the database is in use (WAL mode allows concurrent readers).

Procedure:
  1. Open a destination connection.
  2. ``source.backup(dest)`` — copies all pages.
  3. Close destination.
  4. ``PRAGMA integrity_check`` on the destination.
  5. If clean: log and return metadata. If corrupt: delete, raise.

Restore (B6 — atomic and store-consistent):
  1. Verify backup integrity.
  2. Copy the backup to a TEMP file in the live DB's directory, fsync, then
     ``os.replace`` over the live path — the swap is atomic on the same
     filesystem, so a crash mid-restore can never corrupt the live DB (it
     is untouched until the rename).
  3. Delete -wal/-shm (F-06: no post-backup WAL replay).
  4. Reopen; verify integrity; restore the artifact-store snapshot when one
     was taken (content-addressed immutable files merge in crash-safely).
"""
from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from hermes.core import Clock, utc_now
from hermes.persistence.database import integrity_check


class BackupResult:
    """Metadata about a completed backup."""

    def __init__(self, backup_path: str, integrity_ok: bool, timestamp: str,
                 artifact_store_path: str = ""):
        self.backup_path = backup_path
        self.integrity_ok = integrity_ok
        self.timestamp = timestamp
        self.artifact_store_path = artifact_store_path

    def __repr__(self) -> str:
        return (f"BackupResult(path={self.backup_path}, "
                f"integrity={self.integrity_ok}, ts={self.timestamp}, "
                f"store={self.artifact_store_path!r})")


def create_backup(
    source_conn: sqlite3.Connection,
    backup_dir: str | Path,
    clock: Clock | None = None,
    artifact_root: str | Path | None = None,
) -> BackupResult:
    """Create a snapshot of the database using the Online Backup API.

    Args:
        source_conn: An open connection to the live database.
        backup_dir: Directory to write the backup file into.
        clock: Optional clock for deterministic timestamps.
        artifact_root: When given, ALSO snapshot the artifact store (a
            content-addressed copy of the store root beside the backup) so
            a later restore can bring DB + store back to the SAME point —
            the red-team B6 consistency gap (restore rolled the DB back but
            left the store at a newer state).

    Returns:
        BackupResult with the backup path and integrity check result.
    """
    ts = (clock or utc_now)()
    safe_ts = ts.replace(":", "-").replace("+", "Z")
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"hermes_backup_{safe_ts}.db"

    # Online backup
    dest_conn = sqlite3.connect(str(backup_path))
    try:
        source_conn.backup(dest_conn)
    finally:
        dest_conn.close()

    # Integrity check on the backup
    check_conn = sqlite3.connect(str(backup_path))
    try:
        ok = integrity_check(check_conn)
    finally:
        check_conn.close()

    if not ok:
        backup_path.unlink(missing_ok=True)
        raise RuntimeError(f"Backup integrity check failed: {backup_path}")

    store_path = ""
    if artifact_root is not None:
        src_root = Path(artifact_root)
        if src_root.exists() and any(src_root.iterdir()):
            store_path = str(backup_dir / f"hermes_store_{safe_ts}")
            shutil.copytree(
                src_root, store_path,
                ignore=shutil.ignore_patterns("*.tmp-*"))

    return BackupResult(str(backup_path), ok, ts, store_path)


def _assert_no_live_lease(live_db_path: Path, lease_seconds: int) -> None:
    """F16 — refuse to restore onto a DB whose scheduler lease is LIVE.

    Restoring while a controller holds the scheduler lock would let a
    post-backup write land in the rolled-back snapshot (the fence-check to
    write statement window is a file swap, not a SQLite transaction). The
    meaningful part of the documented "all connections closed" precondition
    is: no live lease. A stale (dead-owner) lock does not block restore —
    the owner is gone, the swap is safe. A pre-lease schema (no
    scheduler_lock table) passes through — there is no lease machinery to
    protect.
    """
    conn = sqlite3.connect(str(live_db_path))
    try:
        row = conn.execute(
            "SELECT owner, locked_at FROM scheduler_lock WHERE id = 0"
        ).fetchone()
    except sqlite3.OperationalError:
        return  # pre-lease schema: nothing to protect
    finally:
        conn.close()
    if row is None or row[0] is None or row[1] is None:
        return
    try:
        ts = datetime.fromisoformat(row[1])
        age = (datetime.fromisoformat(utc_now()) - ts).total_seconds()
    except ValueError:
        return  # unparseable lock row — let the swap itself fail closed
    if age < lease_seconds:
        raise RuntimeError(
            f"refusing restore: live scheduler lease held by {row[0]!r} "
            f"({age:.0f}s old < {lease_seconds}s lease) — stop the running "
            f"controller before restoring")

def restore_backup(
    backup_path: str | Path,
    live_db_path: str | Path,
    live_artifact_root: str | Path | None = None,
    lease_seconds: int = 60,
) -> str:
    """Restore a backup file to the live database path.

    F-06: WAL-safe restore. After copying the backup file, the WAL and shared
    memory files (-wal, -shm) MUST be removed. If they are left in place,
    SQLite will replay the WAL on next open, resurrecting newer state that
    was written after the backup was taken.

    The restore procedure is:
      1. Verify backup integrity before restoring.
      2. Copy backup to the live DB path (overwriting the .db file).
      3. Delete -wal and -shm files to prevent WAL replay.
      4. Reopen and verify integrity.

    Precondition: all connections to the live DB must be closed by the caller
    before calling this function.
    """
    backup_path = Path(backup_path)
    live_db_path = Path(live_db_path)

    if not backup_path.exists():
        raise FileNotFoundError(f"Backup not found: {backup_path}")

    # Verify the backup integrity before restoring
    check_conn = sqlite3.connect(str(backup_path))
    try:
        ok = integrity_check(check_conn)
    finally:
        check_conn.close()
    if not ok:
        raise RuntimeError(f"Backup integrity check failed: {backup_path}")

    # F16: never swap under a live lease (the file swap is not a SQLite
    # transaction — a stale controller could write into the rolled-back DB).
    _assert_no_live_lease(live_db_path, lease_seconds)

    # B6: ATOMIC restore — the backup lands in a temp file in the live DB's
    # own directory (same filesystem), fsynced, then os.replace swaps it in.
    # A crash at any point before the rename leaves the live DB untouched;
    # the old shutil.copy2 could truncate the live file mid-copy.
    live_dir = live_db_path.parent
    live_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = live_dir / (
        f".{live_db_path.name}.restore-{os.getpid()}-{os.urandom(4).hex()}")
    try:
        with open(tmp_path, "wb") as fh:
            with open(str(backup_path), "rb") as src:
                shutil.copyfileobj(src, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, live_db_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    # F-06: Delete WAL and SHM files to prevent newer state from reappearing.
    # These files are safe to delete — SQLite recreates them automatically on
    # next open. Leaving them in place means SQLite would replay the WAL
    # journal, which contains post-backup transactions that should not exist
    # in the restored snapshot.
    wal_path = Path(str(live_db_path) + "-wal")
    shm_path = Path(str(live_db_path) + "-shm")
    wal_path.unlink(missing_ok=True)
    shm_path.unlink(missing_ok=True)

    # Verify the restored DB
    verify_conn = sqlite3.connect(str(live_db_path))
    try:
        ok = integrity_check(verify_conn)
    finally:
        verify_conn.close()
    if not ok:
        raise RuntimeError(f"Restored database integrity check failed: {live_db_path}")

    # B6: restore the artifact-store snapshot taken with this backup, so the
    # DB and the store come back to the SAME point. Artifact files are
    # immutable and content-addressed, so copying the snapshot INTO the live
    # root merges crash-safely (a re-run completes the restore); orphans
    # written after the backup remain but are unreferenced by the restored
    # DB — never a stale deref.
    if live_artifact_root is not None:
        snapshot_dir = backup_path.parent / (
            "hermes_store_"
            + backup_path.name[len("hermes_backup_"):-len(".db")])
        if snapshot_dir.is_dir():
            shutil.copytree(
                snapshot_dir, Path(live_artifact_root),
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("*.tmp-*"))

    return str(live_db_path)


def retain_last_n(backup_dir: str | Path, n: int) -> list[str]:
    """Keep only the N most recent backups; delete older ones.

    Returns the list of deleted backup paths.
    """
    backup_dir = Path(backup_dir)
    if n < 1:
        # B4 — retain 0 must not delete (the backup just created included):
        # refuse to prune rather than silently destroy the only copy.
        return []
    if not backup_dir.exists():
        return []

    backups = sorted(
        backup_dir.glob("hermes_backup_*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    deleted = []
    for old in backups[n:]:
        old.unlink(missing_ok=True)
        deleted.append(str(old))
        # the artifact-store snapshot paired with this backup (B6)
        snap = backup_dir / (
            "hermes_store_"
            + old.name[len("hermes_backup_"):-len(".db")])
        if snap.is_dir():
            shutil.rmtree(snap, ignore_errors=True)
    return deleted
