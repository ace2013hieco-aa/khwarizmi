"""Tests for the database layer, migrations, backup/restore, and integrity (v3 §16.4)."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from hermes.core import frozen_clock
from hermes.persistence.backup import create_backup, restore_backup, retain_last_n
from hermes.persistence.database import (
    SchemaVersionError,
    assert_schema_version,
    connect,
    foreign_key_check,
    get_schema_version,
    integrity_check,
)
from hermes.persistence.migrations import SUPPORTED_VERSION, migrate_to_latest


@pytest.fixture
def mem_conn():
    """In-memory SQLite connection with migrations applied."""
    conn = connect(":memory:")
    migrate_to_latest(conn)
    yield conn
    conn.close()


@pytest.fixture
def tmp_db(tmp_path):
    """File-based SQLite DB in a temp directory."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))
    migrate_to_latest(conn)
    conn.close()
    return str(db_path)


class TestMigrations:
    def test_clean_db_migrates_to_supported_version(self, mem_conn):
        version = get_schema_version(mem_conn)
        assert version == SUPPORTED_VERSION

    def test_supported_version_is_latest(self):
        # IDR-018: version 4 adds the research_programs table (ResearchProgram
        # artifact, approved Part 2 architecture).
        # IDR-026: version 5 adds the ResearchClaim/ResearchAssumption
        # substrate persistence (P7 write path).
        # ADV-02: version 8 adds scheduler-lease generation fencing.
        # audit F9: version 12 adds the schema-level one-verdict index
        # on events (event_type, correlation_id).
        # M1/HR-02: version 13 adds validation_verdicts (content-validation
        # verdicts gate the ladder).
        # M4/HR-05: version 14 adds research_claims.support_state (the
        # closed claim support-state vocabulary).
        # Step 7: version 15 adds the curated knowledge registry
        # (curated_knowledge_entries / retraction_basis / supersession).
        # CHG-1/CHG-2: version 16 adds contradictions +
        # provider_interactions (derived working state; no rewrites).
        # P4 closure: version 17 adds provider_interactions.content_type
        # (remediation for certified-v16 databases missing the column).
        # Step 3 FIX 1: version 18 adds research_claims.related_claim_ids_json
        # (advisory cross-ref data, never a gate input).
        assert SUPPORTED_VERSION == 20

    def test_migration_17_adds_content_type(self):
        """P4 closure remediation matrix, all four cases."""
        from hermes.persistence.repositories import ProjectRepository
        # 1. Fresh database receives the column at latest.
        fresh = connect(":memory:")
        migrate_to_latest(fresh)
        cols = {r["name"] for r in fresh.execute(
            "SELECT name FROM pragma_table_info("
            "'provider_interactions')").fetchall()}
        assert "content_type" in cols
        fresh.close()
        # 2/3/4. Simulated certified-v16 database (exact v16 schema
        # minus the column), empty and historically populated.
        for populated in (False, True):
            conn = connect(":memory:")
            migrate_to_latest(conn)
            conn.execute(
                "ALTER TABLE provider_interactions DROP COLUMN content_type")
            # claim-ground G13 added version 20: rewind it too so the simulated
            # state is a genuine v16 database.
            conn.execute("DELETE FROM schema_version WHERE version IN (17, 18, 19, 20)")
            assert conn.execute(
                "SELECT MAX(version) v FROM schema_version").fetchone()["v"] \
                == 16
            if populated:
                ProjectRepository(conn).create("p1", "Test")
                conn.execute(
                    "INSERT INTO provider_interactions "
                    "(interaction_id, project_id, provider_id, "
                    "adapter_version, parser_version, "
                    "normalized_request_hash, request_json, "
                    "response_status_class, outcome_kind, retrieved_at, "
                    "source_url_redacted, created_at) "
                    "VALUES ('fx-old', 'p1', 'openalex', '1', '1', 'h', "
                    "'{}', 'HTTP_200', 'RECORDED_SUCCESS', 't', 'u', 't')")
            assert migrate_to_latest(conn) == 20
            cols = {r["name"] for r in conn.execute(
                "SELECT name FROM pragma_table_info("
                "'provider_interactions')").fetchall()}
            assert "content_type" in cols
            if populated:
                row = conn.execute(
                    "SELECT * FROM provider_interactions "
                    "WHERE interaction_id = 'fx-old'").fetchone()
                assert row["content_type"] is None
                assert row["provider_id"] == "openalex"
            # Idempotent re-run: no error, still v20.
            assert migrate_to_latest(conn) == 20
            conn.close()

    def test_migrate_to_latest_returns_version(self):
        conn = connect(":memory:")
        version = migrate_to_latest(conn)
        assert version == SUPPORTED_VERSION
        conn.close()

    def test_running_migration_twice_is_idempotent(self, mem_conn):
        # Migrating an already-migrated DB should be a no-op
        version = migrate_to_latest(mem_conn)
        assert version == SUPPORTED_VERSION

    def test_schema_version_too_high_raises(self, mem_conn):
        # Inject a future version (replace all rows with a single future version)
        mem_conn.execute("DELETE FROM schema_version")
        mem_conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (999, '2026-01-01')")
        with pytest.raises(SchemaVersionError) as exc_info:
            assert_schema_version(mem_conn, SUPPORTED_VERSION)
        assert exc_info.value.current == 999
        assert exc_info.value.supported == SUPPORTED_VERSION

    def test_schema_version_with_deterministic_clock(self):
        conn = connect(":memory:")
        clock = frozen_clock("2026-01-01T00:00:00.000000+00:00")
        migrate_to_latest(conn, clock=clock)
        row = conn.execute("SELECT applied_at FROM schema_version").fetchone()
        assert row["applied_at"] == "2026-01-01T00:00:00.000000+00:00"
        conn.close()

    def test_v2_to_v3_migration_patches_weak_check(self):
        """F-04 regression: A v2 database with the old char-counted CHECK
        is migrated to v3 with the byte-accurate CHECK.

        After migration, an 8 KiB multibyte payload that passed the old
        char-counted CHECK must be rejected by the new byte-accurate CHECK.
        """
        from hermes.core import frozen_clock

        conn = connect(":memory:")
        conn.row_factory = sqlite3.Row

        # Build a v2 schema manually with the OLD weak CHECK
        conn.execute("BEGIN")
        conn.execute("""
            CREATE TABLE schema_version (
                version     INTEGER PRIMARY KEY,
                applied_at  TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE scheduler_lock (
                id          INTEGER PRIMARY KEY CHECK (id = 0),
                owner       TEXT NOT NULL,
                locked_at   TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE projects (
                project_id          TEXT PRIMARY KEY,
                name                TEXT NOT NULL,
                lifecycle_state     TEXT NOT NULL,
                operational_mode    TEXT NOT NULL DEFAULT 'ACTIVE',
                iteration           INTEGER NOT NULL DEFAULT 1,
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE tasks (
                task_id             TEXT PRIMARY KEY,
                project_id          TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
                task_type           TEXT NOT NULL,
                profile             TEXT,
                idempotency_key     TEXT NOT NULL,
                attempt             INTEGER NOT NULL DEFAULT 1,
                status              TEXT NOT NULL DEFAULT 'PENDING',
                iteration           INTEGER NOT NULL DEFAULT 1,
                parent_task_id      TEXT,
                spec_json           TEXT NOT NULL DEFAULT '{}',
                inputs_json         TEXT,
                outputs_json        TEXT,
                provenance_json     TEXT,
                cost_class          TEXT,
                concurrency_group   TEXT,
                max_retries         INTEGER NOT NULL DEFAULT 3,
                created_at          TEXT NOT NULL,
                started_at          TEXT,
                completed_at        TEXT,
                last_heartbeat      TEXT,
                UNIQUE (idempotency_key, attempt)
            )
        """)
        conn.execute("""
            CREATE TABLE events (
                event_id            INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type          TEXT NOT NULL,
                project_id          TEXT REFERENCES projects(project_id),
                task_id             TEXT REFERENCES tasks(task_id),
                from_state          TEXT,
                to_state            TEXT,
                correlation_id      TEXT NOT NULL DEFAULT '',
                caused_by           TEXT,
                reason              TEXT,
                artifact_ids_json   TEXT,
                payload_json        TEXT,
                created_at          TEXT NOT NULL,
                CHECK (length(payload_json) <= 4096)
            )
        """)
        conn.execute("CREATE INDEX idx_events_project ON events(project_id)")
        conn.execute("CREATE INDEX idx_events_task ON events(task_id)")
        conn.execute("""
            CREATE TABLE artifacts (
                artifact_id         TEXT PRIMARY KEY,
                project_id          TEXT REFERENCES projects(project_id),
                task_id             TEXT REFERENCES tasks(task_id),
                artifact_type       TEXT NOT NULL,
                content_hash        TEXT NOT NULL UNIQUE,
                size_bytes          INTEGER NOT NULL,
                storage_path        TEXT NOT NULL,
                producer            TEXT NOT NULL,
                metadata_json       TEXT,
                created_at          TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX idx_artifacts_hash ON artifacts(content_hash)")
        conn.execute("""
            CREATE TABLE task_dependencies (
                dependency_id       INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id             TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                depends_on_task_id  TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                created_at          TEXT NOT NULL,
                UNIQUE (task_id, depends_on_task_id),
                CHECK (task_id != depends_on_task_id)
            )
        """)
        # Mark as v2
        conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (2, '2026-01-01')")
        conn.execute("COMMIT")
        assert get_schema_version(conn) == 2

        # Verify old CHECK is char-counted: 2048 emoji (8192 bytes) passes
        conn.execute("INSERT INTO projects (project_id, name, lifecycle_state, "
                     "operational_mode, iteration, created_at, updated_at) VALUES "
                     "('p1', 'test', 'CREATED', 'ACTIVE', 1, '2026-01-01', '2026-01-01')")
        emoji_payload = "😀" * 2048  # 2048 chars, 8192 bytes
        conn.execute("INSERT INTO events (event_type, project_id, payload_json, created_at) "
                     "VALUES ('TestEvent', 'p1', ?, '2026-01-01')", (emoji_payload,))
        # Old v2 CHECK accepts this (char count 2048 <= 4096) — confirmed weak

        # Clean up the invalid row before migration (can't copy it into new table)
        conn.execute("DELETE FROM events WHERE event_type = 'TestEvent'")

        # Now run migration to v3
        from hermes.persistence.migrations import _migrate_2_to_3
        conn.execute("BEGIN")
        _migrate_2_to_3(conn, frozen_clock("2026-01-01T00:00:00.000000+00:00"))
        conn.execute("COMMIT")
        assert get_schema_version(conn) == 3

        # After migration, the same 8 KiB payload must be REJECTED
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO events (event_type, project_id, payload_json, created_at) "
                         "VALUES ('TestEvent', 'p1', ?, '2026-01-01')", (emoji_payload,))

        # A small multibyte payload (under 4096 bytes) should still pass
        small_emoji = "😀" * 500  # 500 chars, 2000 bytes
        conn.execute("INSERT INTO events (event_type, project_id, payload_json, created_at) "
                     "VALUES ('TestEvent', 'p1', ?, '2026-01-01')", (small_emoji,))
        conn.close()


class TestPragmas:
    def test_wal_mode_enabled(self, mem_conn):
        mode = mem_conn.execute("PRAGMA journal_mode").fetchone()[0]
        # WAL returns 'wal' on disk; in-memory returns 'memory'
        assert mode in ("wal", "memory")

    def test_foreign_keys_enabled(self, mem_conn):
        fk = mem_conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1  # FK is on

    def test_busy_timeout_set(self, mem_conn):
        bt = mem_conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert bt == 5000  # 5 seconds per IDR-015


class TestIntegrity:
    def test_integrity_check_passes_on_clean_db(self, mem_conn):
        assert integrity_check(mem_conn) is True

    def test_foreign_key_check_passes_on_clean_db(self, mem_conn):
        assert foreign_key_check(mem_conn) is True


class TestRestart:
    def test_data_persists_across_restart(self, tmp_db):
        """Close and reopen a DB file, verify data persists."""
        conn = connect(tmp_db)
        conn.execute("INSERT INTO projects (project_id, name, lifecycle_state, operational_mode, iteration, created_at, updated_at) VALUES ('p1', 'Test', 'CREATED', 'ACTIVE', 1, '2026-01-01', '2026-01-01')")
        conn.close()

        # Reopen
        conn2 = connect(tmp_db)
        row = conn2.execute("SELECT * FROM projects WHERE project_id = 'p1'").fetchone()
        assert row is not None
        assert row["name"] == "Test"
        assert row["lifecycle_state"] == "CREATED"
        conn2.close()


class TestBackupRestore:
    def test_backup_creates_valid_file(self, tmp_db, tmp_path):
        """Create a backup, verify it's a valid SQLite file."""
        conn = connect(tmp_db)
        conn.execute("INSERT INTO projects (project_id, name, lifecycle_state, operational_mode, iteration, created_at, updated_at) VALUES ('p1', 'Test', 'CREATED', 'ACTIVE', 1, '2026-01-01', '2026-01-01')")
        conn.close()

        conn = connect(tmp_db)
        backup_dir = tmp_path / "backups"
        result = create_backup(conn, backup_dir)
        conn.close()

        assert result.integrity_ok is True
        assert os.path.exists(result.backup_path)

    def test_restore_recovers_data(self, tmp_db, tmp_path):
        """Backup, modify, restore — verify original state is recovered."""
        conn = connect(tmp_db)
        conn.execute("INSERT INTO projects (project_id, name, lifecycle_state, operational_mode, iteration, created_at, updated_at) VALUES ('p1', 'Original', 'CREATED', 'ACTIVE', 1, '2026-01-01', '2026-01-01')")
        conn.close()

        # Create backup
        conn = connect(tmp_db)
        backup_dir = tmp_path / "backups"
        result = create_backup(conn, backup_dir)
        conn.close()

        # Modify the database after backup
        conn = connect(tmp_db)
        conn.execute("INSERT INTO projects (project_id, name, lifecycle_state, operational_mode, iteration, created_at, updated_at) VALUES ('p2', 'Added Later', 'CREATED', 'ACTIVE', 1, '2026-01-01', '2026-01-01')")
        conn.close()

        # Restore
        restored_path = restore_backup(result.backup_path, tmp_db)
        assert restored_path == tmp_db

        # Verify only the original data exists
        conn = connect(tmp_db)
        rows = conn.execute("SELECT * FROM projects").fetchall()
        assert len(rows) == 1
        assert rows[0]["project_id"] == "p1"
        assert rows[0]["name"] == "Original"
        conn.close()

    def test_retain_last_n_deletes_older_backups(self, tmp_db, tmp_path):
        """retain_last_n keeps only the N most recent backups."""
        conn = connect(tmp_db)
        backup_dir = tmp_path / "backups"
        # Create 3 backups with slightly different names using different clocks
        for i in range(3):
            clock = frozen_clock(f"2026-01-0{i+1}T00:00:00.000000+00:00")
            create_backup(conn, backup_dir, clock=clock)
        conn.close()

        # There should be 3 backups (different filenames due to different timestamps)
        backups = list(backup_dir.glob("hermes_backup_*.db"))
        assert len(backups) == 3

        deleted = retain_last_n(backup_dir, n=1)
        assert len(deleted) == 2
        remaining = list(backup_dir.glob("hermes_backup_*.db"))
        assert len(remaining) == 1


class TestAtomicRestoreAndStoreSnapshot:
    """B6 hardening: restore swaps the backup in atomically (temp + rename,
    never a truncating copy2), and a backup taken with artifact_root brings
    the store back to the SAME point as the DB."""

    def test_restore_never_leaves_temp_files(self, tmp_db, tmp_path):
        conn = connect(tmp_db)
        conn.execute("INSERT INTO projects (project_id, name, lifecycle_state, operational_mode, iteration, created_at, updated_at) VALUES ('p1', 'X', 'CREATED', 'ACTIVE', 1, '2026-01-01', '2026-01-01')")
        conn.close()
        conn = connect(tmp_db)
        backup_dir = tmp_path / "backups"
        result = create_backup(conn, backup_dir)
        conn.close()
        conn = connect(tmp_db)
        conn.execute("INSERT INTO projects (project_id, name, lifecycle_state, operational_mode, iteration, created_at, updated_at) VALUES ('p2', 'Y', 'CREATED', 'ACTIVE', 1, '2026-01-01', '2026-01-01')")
        conn.close()

        restore_backup(result.backup_path, tmp_db)
        leftovers = list(Path(tmp_db).parent.glob(".*restore-*"))
        assert leftovers == []
        conn = connect(tmp_db)
        try:
            rows = conn.execute("SELECT project_id FROM projects").fetchall()
            assert [r[0] for r in rows] == ["p1"]
        finally:
            conn.close()

    def test_store_snapshot_round_trip(self, tmp_db, tmp_path):
        """Backup with artifact_root snapshots the store; a post-backup store
        mutation is rolled back WITH the DB on restore — the store and DB
        come back to the same point (no stale derefs, no surprise files)."""
        store_root = tmp_path / "artifacts"
        (store_root / "ab").mkdir(parents=True)
        (store_root / "ab" / "old.bin").write_bytes(b"OLD")

        conn = connect(tmp_db)
        conn.execute("INSERT INTO projects (project_id, name, lifecycle_state, operational_mode, iteration, created_at, updated_at) VALUES ('p1', 'Original', 'CREATED', 'ACTIVE', 1, '2026-01-01', '2026-01-01')")
        conn.close()

        conn = connect(tmp_db)
        backup_dir = tmp_path / "backups"
        result = create_backup(conn, backup_dir, artifact_root=store_root)
        conn.close()
        assert result.artifact_store_path  # snapshot was taken
        assert os.path.isdir(result.artifact_store_path)

        # post-backup: DB gains p2 AND the store gains a new file
        conn = connect(tmp_db)
        conn.execute("INSERT INTO projects (project_id, name, lifecycle_state, operational_mode, iteration, created_at, updated_at) VALUES ('p2', 'Later', 'CREATED', 'ACTIVE', 1, '2026-01-01', '2026-01-01')")
        conn.close()
        (store_root / "ab" / "new.bin").write_bytes(b"NEW")

        restore_backup(result.backup_path, tmp_db,
                       live_artifact_root=store_root)
        # DB rolled back to p1 only
        conn = connect(tmp_db)
        try:
            rows = conn.execute("SELECT project_id FROM projects").fetchall()
            assert [r[0] for r in rows] == ["p1"]
        finally:
            conn.close()
        # store still holds the backup-point file (snapshot merged back)
        assert (store_root / "ab" / "old.bin").read_bytes() == b"OLD"
        # and a second restore is idempotent (crash-safe merge)
        restore_backup(result.backup_path, tmp_db,
                       live_artifact_root=store_root)
        assert (store_root / "ab" / "old.bin").read_bytes() == b"OLD"


    def test_restore_refused_under_live_lease(self, tmp_db, tmp_path):
        """F16 — restore refuses when the scheduler lease is LIVE (a live
        controller could write into the rolled-back snapshot), and passes
        when the lease is stale (dead owner) or absent."""
        conn = connect(tmp_db)
        conn.execute(
            "INSERT INTO projects (project_id, name, lifecycle_state, "
            "operational_mode, iteration, created_at, updated_at) "
            "VALUES ('p1', 'Original', 'CREATED', 'ACTIVE', 1, "
            "'2026-01-01', '2026-01-01')")
        conn.close()

        conn = connect(tmp_db)
        backup_dir = tmp_path / "backups"
        result = create_backup(conn, backup_dir)
        conn.close()

        # LIVE lease (fresh locked_at) -> refused, live DB untouched.
        from hermes.core import utc_now as _utc_now
        conn = connect(tmp_db)
        conn.execute(
            "INSERT OR REPLACE INTO scheduler_lock "
            "(id, owner, locked_at, generation) VALUES (0, 'controller-x', "
            "?, 0)", (_utc_now(),))
        conn.close()
        import pytest as _pytest

        from hermes.persistence.backup import restore_backup as _restore
        with _pytest.raises(RuntimeError, match="live scheduler lease"):
            _restore(result.backup_path, tmp_db)
        conn = connect(tmp_db)
        row = conn.execute(
            "SELECT name FROM projects WHERE project_id = 'p1'").fetchone()
        assert row["name"] == "Original"  # nothing was swapped
        conn.close()

        # STALE lease (dead owner) -> restore proceeds.
        conn = connect(tmp_db)
        conn.execute(
            "UPDATE scheduler_lock SET locked_at = '2025-01-01T00:00:00.000000+00:00'")
        conn.close()
        restored = _restore(result.backup_path, tmp_db,
                            lease_seconds=60)
        assert restored == tmp_db

    def test_retain_last_n_zero_never_deletes(self, tmp_db, tmp_path):
        """B4 — retain_last_n = 0 must never delete backups (the fresh one
        included): refuse to prune instead of destroying every copy."""
        conn = connect(tmp_db)
        backup_dir = tmp_path / "backups"
        r1 = create_backup(conn, backup_dir)
        r2 = create_backup(conn, backup_dir)
        conn.close()

        deleted = retain_last_n(backup_dir, 0)
        assert deleted == []
        assert os.path.exists(r1.backup_path)
        assert os.path.exists(r2.backup_path)

    def test_retain_last_n_removes_store_snapshots(self, tmp_db, tmp_path):
        store_root = tmp_path / "artifacts"
        (store_root / "ab").mkdir(parents=True)
        (store_root / "ab" / "x.bin").write_bytes(b"X")
        conn = connect(tmp_db)
        backup_dir = tmp_path / "backups"
        for i in range(2):
            clock = frozen_clock(f"2026-01-0{i+1}T00:00:00.000000+00:00")
            create_backup(conn, backup_dir, clock=clock,
                          artifact_root=store_root)
        conn.close()
        snaps = list(backup_dir.glob("hermes_store_*"))
        assert len(snaps) == 2
        retain_last_n(backup_dir, n=1)
        assert len(list(backup_dir.glob("hermes_backup_*.db"))) == 1
        assert len(list(backup_dir.glob("hermes_store_*"))) == 1
