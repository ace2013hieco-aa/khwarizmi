"""Failure injection tests (Phase 1 req §22).

If a state transition succeeds but the event append fails, the transaction
must roll back — no partial state. If an artifact write succeeds but the DB
commit fails, no DB record should exist (orphaned but safe).
"""
from __future__ import annotations

import sqlite3

import pytest

from hermes.artifacts.store import ArtifactStore, compute_content_hash
from hermes.core.lifecycle import LifecycleState
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    ArtifactRepository,
    EventRepository,
    ProjectRepository,
)


class _FailingConnection:
    """Proxy that wraps a real sqlite3.Connection and injects failures
    for specific SQL patterns. sqlite3.Connection.execute is read-only,
    so we wrap it with a proxy instead of monkeypatching."""

    def __init__(self, real_conn, fail_pattern: str):
        self._real = real_conn
        self._fail_pattern = fail_pattern

    def execute(self, sql, params=()):
        if self._fail_pattern and self._fail_pattern in sql:
            raise sqlite3.OperationalError(
                f"injected failure: pattern '{self._fail_pattern}' matched"
            )
        return self._real.execute(sql, params)

    def close(self):
        self._real.close()

    def __getattr__(self, name):
        return getattr(self._real, name)


@pytest.fixture
def conn():
    c = connect(":memory:")
    migrate_to_latest(c)
    yield c
    c.close()


class TestTransitionEventAtomicity:
    def test_event_append_failure_rolls_back_state(self, conn):
        """If the event INSERT fails, the state update must roll back."""
        proj_repo = ProjectRepository(conn)
        proj_repo.create("p1", "Test")
        initial_state = proj_repo.get_lifecycle("p1")
        assert initial_state == LifecycleState.CREATED

        event_repo = EventRepository(conn)
        events_before = event_repo.count()

        # Wrap the connection to inject failure on event INSERT
        failing_conn = _FailingConnection(conn, "INSERT INTO events")
        failing_repo = ProjectRepository(failing_conn)

        with pytest.raises(sqlite3.OperationalError, match="injected failure"):
            failing_repo.transition_lifecycle("p1", LifecycleState.SCOPING)

        # Verify state was rolled back (transaction ROLLBACK fired)
        assert proj_repo.get_lifecycle("p1") == initial_state  # still CREATED

        # Verify no event was appended
        assert event_repo.count() == events_before

    def test_rollback_does_not_leave_partial_state(self, conn):
        """After a failed transition, the DB is consistent: state + events match."""
        proj_repo = ProjectRepository(conn)
        proj_repo.create("p1", "Test")
        event_repo = EventRepository(conn)
        events_before = event_repo.count()
        state_before = proj_repo.get_lifecycle("p1")

        failing_conn = _FailingConnection(conn, "INSERT INTO events")
        failing_repo = ProjectRepository(failing_conn)

        with pytest.raises(sqlite3.OperationalError):
            failing_repo.transition_lifecycle("p1", LifecycleState.SCOPING)

        assert proj_repo.get_lifecycle("p1") == state_before
        assert event_repo.count() == events_before

    def test_legal_transition_after_failed_one_still_works(self, conn):
        """After a failed transition, the next legal transition succeeds normally."""
        proj_repo = ProjectRepository(conn)
        proj_repo.create("p1", "Test")

        # Failed transition (injected)
        failing_conn = _FailingConnection(conn, "INSERT INTO events")
        failing_repo = ProjectRepository(failing_conn)
        with pytest.raises(sqlite3.OperationalError):
            failing_repo.transition_lifecycle("p1", LifecycleState.SCOPING)

        # Now a legal transition with the real connection should work
        proj_repo.transition_lifecycle("p1", LifecycleState.SCOPING)
        assert proj_repo.get_lifecycle("p1") == LifecycleState.SCOPING


class TestArtifactDbFailure:
    def test_artifact_write_succeeds_db_fails_no_record(self, conn, tmp_path):
        """Artifact content is written to filesystem, but DB record fails.

        The artifact content is orphaned (safe), but no DB record exists.
        No false claim that the artifact is authoritative.
        """
        artifact_root = tmp_path / "artifacts"
        artifact_root.mkdir()
        repo = ArtifactRepository(conn)

        # Monkeypatch repo.record to raise after the content is written
        def failing_record(*args, **kwargs):
            raise sqlite3.OperationalError("injected: DB write failed")

        repo.record = failing_record

        store = ArtifactStore(artifact_root, repo)

        data = b"orphaned content"
        with pytest.raises(sqlite3.OperationalError, match="injected"):
            store.write(data, "TestType", "producer-1")

        # Verify: no DB record exists (cannot be cited as authoritative)
        assert repo.get_by_hash(compute_content_hash(data)) is None

        # Verify: the content IS on disk (orphaned but safe)
        content_hash = compute_content_hash(data)
        sharded = artifact_root / content_hash[:2] / content_hash[2:4] / content_hash
        assert sharded.exists(), "Orphaned content should still be on disk"
        assert sharded.read_bytes() == data

    def test_orphaned_artifact_can_be_reclaimed(self, conn, tmp_path):
        """An orphaned artifact (content on disk, no DB record) can be reclaimed."""
        artifact_root = tmp_path / "artifacts"
        repo = ArtifactRepository(conn)
        store = ArtifactStore(artifact_root, repo)

        data = b"reclaimable content"
        content_hash = compute_content_hash(data)
        sharded = artifact_root / content_hash[:2] / content_hash[2:4] / content_hash
        sharded.parent.mkdir(parents=True, exist_ok=True)
        sharded.write_bytes(data)

        # Write through the store — should detect existing content
        meta = store.write(data, "TestType", "producer-1")
        assert meta is not None
        assert meta["content_hash"] == content_hash
        assert repo.get_by_hash(content_hash) is not None
