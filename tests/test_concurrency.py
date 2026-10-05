"""Concurrency tests — local concurrent access (Phase 1 req §17).

Hermes is not a distributed system. No distributed locks. But local
concurrent access must fail deterministically rather than corrupting state.
"""
from __future__ import annotations

import sqlite3
import threading

import pytest

from hermes.core.lifecycle import LifecycleState, TransitionError
from hermes.core.node import NodeContract, NodeType
from hermes.core.task_status import TaskStatus
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ProjectRepository, TaskRepository


@pytest.fixture
def file_db(tmp_path):
    """File-based DB for concurrency tests (in-memory can't be shared across threads reliably)."""
    db_path = tmp_path / "concurrent.db"
    conn = connect(str(db_path))
    migrate_to_latest(conn)
    # Seed a project
    proj_repo = ProjectRepository(conn)
    proj_repo.create("proj-concurrent", "Concurrent Test")
    conn.close()
    return str(db_path)


class TestCompetingTransitions:
    def test_two_writers_same_transition_one_succeeds(self, file_db):
        """Two threads both try the same lifecycle transition.

        One should succeed, the other should fail (either TransitionError
        because the state already moved, or sqlite3.OperationalError for
        lock contention). The system must not corrupt state.
        """
        results = {"success": 0, "fail": 0}
        lock = threading.Lock()
        barrier = threading.Barrier(2)

        def attempt_transition():
            barrier.wait()  # release both threads simultaneously
            conn = connect(file_db)
            repo = ProjectRepository(conn)
            try:
                repo.transition_lifecycle("proj-concurrent", LifecycleState.SCOPING)
                with lock:
                    results["success"] += 1
            except (TransitionError, sqlite3.OperationalError, sqlite3.IntegrityError):
                with lock:
                    results["fail"] += 1
            finally:
                conn.close()

        t1 = threading.Thread(target=attempt_transition)
        t2 = threading.Thread(target=attempt_transition)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Exactly one should succeed
        assert results["success"] == 1, f"Expected 1 success, got {results['success']}"
        assert results["fail"] == 1, f"Expected 1 failure, got {results['fail']}"

        # Verify final state
        conn = connect(file_db)
        repo = ProjectRepository(conn)
        state = repo.get_lifecycle("proj-concurrent")
        assert state == LifecycleState.SCOPING
        conn.close()

    def test_two_writers_different_tasks_both_succeed(self, file_db):
        """Two threads transitioning different tasks should both succeed."""
        # Setup: create a project with two tasks
        conn = connect(file_db)
        task_repo = TaskRepository(conn)
        task_repo.create(NodeContract(
            task_id="task-a", project_id="proj-concurrent",
            task_type=NodeType.TOOL_TASK.value, idempotency_key="hash-a",
        ))
        task_repo.create(NodeContract(
            task_id="task-b", project_id="proj-concurrent",
            task_type=NodeType.TOOL_TASK.value, idempotency_key="hash-b",
        ))
        # Move both to READY first
        task_repo.transition_status("task-a", TaskStatus.READY)
        task_repo.transition_status("task-b", TaskStatus.READY)
        conn.close()

        results = {"success": 0, "fail": 0}
        lock = threading.Lock()
        barrier = threading.Barrier(2)

        def transition_task(task_id):
            barrier.wait()
            conn = connect(file_db)
            repo = TaskRepository(conn)
            try:
                repo.transition_status(task_id, TaskStatus.RUNNING)
                with lock:
                    results["success"] += 1
            except Exception:  # noqa: BLE001 — worker must never die; the outcome is counted
                with lock:
                    results["fail"] += 1
            finally:
                conn.close()

        t1 = threading.Thread(target=transition_task, args=("task-a",))
        t2 = threading.Thread(target=transition_task, args=("task-b",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert results["success"] == 2, f"Expected 2 successes, got {results['success']}"
        assert results["fail"] == 0

        # Verify both tasks are RUNNING
        conn = connect(file_db)
        repo = TaskRepository(conn)
        assert repo.get_status("task-a") == TaskStatus.RUNNING
        assert repo.get_status("task-b") == TaskStatus.RUNNING
        conn.close()


class TestDuplicateIdempotency:
    def test_duplicate_idempotency_key_rejected(self, file_db):
        """Same idempotency_key + attempt must fail on second insert.

        Two threads concurrently try to create a task with the same
        idempotency key. The UNIQUE(idempotency_key, attempt) constraint
        means exactly one succeeds and the other gets IntegrityError.
        """
        results = {"success": 0, "fail": 0}
        lock = threading.Lock()
        barrier = threading.Barrier(2)

        def create_task(task_id):
            barrier.wait()
            conn = connect(file_db)
            task_repo = TaskRepository(conn)
            try:
                task_repo.create(NodeContract(
                    task_id=task_id, project_id="proj-concurrent",
                    task_type=NodeType.TOOL_TASK.value, idempotency_key="dup-key",
                ))
                with lock:
                    results["success"] += 1
            except sqlite3.IntegrityError:
                with lock:
                    results["fail"] += 1
            except sqlite3.OperationalError:
                # Lock contention also qualifies as deterministic failure
                with lock:
                    results["fail"] += 1
            finally:
                conn.close()

        t1 = threading.Thread(target=create_task, args=("t1",))
        t2 = threading.Thread(target=create_task, args=("t2",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Exactly one should succeed (the first to commit), one should fail
        assert results["success"] == 1, f"Expected 1 success, got {results['success']}"
        assert results["fail"] == 1, f"Expected 1 failure, got {results['fail']}"
    def test_concurrent_event_append_succeeds(self, file_db):
        """Concurrent event appends to different projects don't corrupt state."""

        # Create 5 projects first
        conn = connect(file_db)
        proj_repo = ProjectRepository(conn)
        for i in range(5):
            proj_repo.create(f"proj-{i}", f"Project {i}")
        conn.close()

        results = {"success": 0, "fail": 0}
        lock = threading.Lock()
        barrier = threading.Barrier(5)

        def transition(i):
            barrier.wait()
            conn = connect(file_db)
            repo = ProjectRepository(conn)
            try:
                repo.transition_lifecycle(f"proj-{i}", LifecycleState.SCOPING)
                with lock:
                    results["success"] += 1
            except Exception:  # noqa: BLE001 — worker must never die; the outcome is counted
                with lock:
                    results["fail"] += 1
            finally:
                conn.close()

        threads = [threading.Thread(target=transition, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results["success"] == 5
        assert results["fail"] == 0
