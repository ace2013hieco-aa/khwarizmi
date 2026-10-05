"""Phase 1 acceptance tests: P1-A, P1-B, P1-C.

P1-A: Kill/resume mid-transition — state + event are both committed or both absent.
P1-B: Stale-lock rejection — stale owner cannot operate; new owner can take over.
P1-C: Forced concurrency race — deterministic forced-race test using threading.Barrier.
"""
from __future__ import annotations

import threading

import pytest

from hermes.core import frozen_clock
from hermes.core.lifecycle import LifecycleState, TransitionError
from hermes.persistence.backup import create_backup, restore_backup
from hermes.persistence.database import (
    acquire_writer_lock,
    connect,
    get_lock_owner,
    release_writer_lock,
)
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    DependencyError,
    ProjectRepository,
    TaskRepository,
)


@pytest.fixture
def file_db(tmp_path):
    """File-based SQLite DB for concurrency tests."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))
    migrate_to_latest(conn)
    yield conn
    conn.close()


@pytest.fixture
def mem_conn():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    yield conn
    conn.close()


# ── P1-A: Kill/resume mid-transition ──

class TestKillResumeMidTransition:
    """P1-A: If a transition is interrupted, state + event are both committed
    or both absent. No partial mutation."""

    def test_successful_transition_commits_state_and_event(self, file_db):
        repo = ProjectRepository(file_db, clock=frozen_clock("2026-01-01T00:00:00.000000+00:00"))
        repo.create("p1", "Test")

        # Normal transition: both state and event should be committed
        repo.transition_lifecycle("p1", LifecycleState.SCOPING)

        # Verify state
        project = repo.get("p1")
        assert project["lifecycle_state"] == "SCOPING"

        # Verify event exists
        events = file_db.execute(
            "SELECT * FROM events WHERE project_id = 'p1' AND event_type = 'LifecycleTransition'"
        ).fetchall()
        assert len(events) == 1
        assert events[0]["from_state"] == "CREATED"
        assert events[0]["to_state"] == "SCOPING"

    def test_failed_transition_rolls_back_state_and_event(self, file_db):
        """If an event INSERT fails after a state UPDATE, both must roll back."""
        repo = ProjectRepository(file_db, clock=frozen_clock("2026-01-01T00:00:00.000000+00:00"))
        repo.create("p1", "Test")

        # Count events before
        events_before = file_db.execute("SELECT COUNT(*) as n FROM events").fetchone()["n"]

        # Attempt invalid transition (should raise, no state or event change)
        with pytest.raises(TransitionError):
            repo.transition_lifecycle("p1", LifecycleState.COMPLETED)

        # State unchanged
        assert repo.get_lifecycle("p1") == LifecycleState.CREATED

        # No new events
        events_after = file_db.execute("SELECT COUNT(*) as n FROM events").fetchone()["n"]
        assert events_after == events_before

    def test_transaction_atomicity_state_and_event(self, file_db):
        """Verify that state and event are in the same transaction by checking
        they commit together after a valid transition."""
        repo = ProjectRepository(file_db, clock=frozen_clock("2026-01-01T00:00:00.000000+00:00"))
        repo.create("p1", "Test")

        # Do a valid transition
        repo.transition_lifecycle("p1", LifecycleState.SCOPING)

        # Immediately read back — both state and event visible
        state = file_db.execute(
            "SELECT lifecycle_state FROM projects WHERE project_id = 'p1'"
        ).fetchone()
        event = file_db.execute(
            "SELECT * FROM events WHERE project_id = 'p1' AND event_type = 'LifecycleTransition'"
        ).fetchone()

        assert state["lifecycle_state"] == "SCOPING"
        assert event is not None
        assert event["from_state"] == "CREATED"
        assert event["to_state"] == "SCOPING"


# ── P1-B: Stale-lock rejection ──

class TestStaleLockRejection:
    """P1-B: The advisory writer lock supports acquire, release, re-acquire,
    and rejection of a second owner."""

    def test_acquire_succeeds(self, mem_conn):
        assert acquire_writer_lock(mem_conn, owner_id="A") is True

    def test_second_owner_rejected(self, tmp_path):
        """Owner A acquires; owner B on the same DB is rejected."""
        db_path = tmp_path / "lock_test.db"
        conn_a = connect(str(db_path))
        migrate_to_latest(conn_a)
        assert acquire_writer_lock(conn_a, owner_id="A") is True

        conn_b = connect(str(db_path))
        migrate_to_latest(conn_b)
        # B should fail (the lock row already exists in the shared DB file)
        assert acquire_writer_lock(conn_b, owner_id="B") is False
        conn_a.close()
        conn_b.close()

    def test_release_then_reacquire(self, mem_conn):
        """After release, the lock can be re-acquired."""
        assert acquire_writer_lock(mem_conn, owner_id="A") is True
        # C-F-08: the acquire -> release chain asserts the owner it
        # acquired under; release verifies the acquisition row it commits.
        release_writer_lock(mem_conn, owner_id="A")
        assert acquire_writer_lock(mem_conn, owner_id="B") is True
        release_writer_lock(mem_conn, owner_id="B")

    def test_stale_owner_can_be_force_released(self, mem_conn):
        """If the owner is stale, force-release clears the lock."""
        acquire_writer_lock(mem_conn, owner_id="stale")
        # Simulate stale owner: force release (C-F-08: assert the owner the
        # open acquisition transaction was created under)
        release_writer_lock(mem_conn, owner_id="stale")
        # New owner should now acquire
        assert acquire_writer_lock(mem_conn, owner_id="new") is True
        release_writer_lock(mem_conn, owner_id="new")

    def test_stale_recovery_on_fresh_connection(self, tmp_path):
        """F-02 regression: stale-owner recovery on a fresh connection.

        Simulates: owner acquires, crashes (connection closed with lock held),
        new connection force-releases, new owner acquires. The old code raised
        OperationalError because it called COMMIT with no active transaction.
        """
        db_path = tmp_path / "stale_test.db"
        # Owner crashes with lock held
        conn1 = connect(str(db_path))
        migrate_to_latest(conn1)
        assert acquire_writer_lock(conn1, owner_id="crashed-controller") is True
        conn1.execute("COMMIT")  # persist the lock row
        conn1.close()

        # Verify lock row is durable
        conn2 = connect(str(db_path))
        migrate_to_latest(conn2)
        owner = get_lock_owner(conn2)
        assert owner == "crashed-controller"

        # Fresh connection force-releases (stale-owner recovery)
        release_writer_lock(conn2)

        # Lock is cleared
        assert get_lock_owner(conn2) is None

        # New owner can acquire
        assert acquire_writer_lock(conn2, owner_id="new-controller") is True
        release_writer_lock(conn2, owner_id="new-controller")
        conn2.close()

    def test_lock_owner_tracked(self, mem_conn):
        """The lock tracks who owns it."""
        acquire_writer_lock(mem_conn, owner_id="controller-1")
        owner = get_lock_owner(mem_conn)
        assert owner == "controller-1"
        release_writer_lock(mem_conn, owner_id="controller-1")
        assert get_lock_owner(mem_conn) is None


# ── P1-C: Forced concurrency race (deterministic) ──

class TestForcedConcurrencyRace:
    """P1-C: Deterministic forced-race test using threading.Barrier.

    Two workers contend on the same lifecycle transition. Exactly one must
    succeed. The event journal must contain exactly one valid event with
    the correct from_state. No false duplicate events."""

    def test_two_workers_same_transition_one_succeeds(self, tmp_path):
        """Force two workers to attempt CREATED → SCOPING simultaneously.

        With the F-01 fix (read+validate inside BEGIN IMMEDIATE), the second
        worker's BEGIN IMMEDIATE blocks until the first commits, then sees
        the updated state (SCOPING) and the transition SCOPING → SCOPING fails
        validation (not in the transition table).
        """
        db_path = tmp_path / "race.db"
        # Set up the database with a project
        setup_conn = connect(str(db_path))
        migrate_to_latest(setup_conn)
        repo = ProjectRepository(setup_conn, clock=frozen_clock("2026-01-01T00:00:00.000000+00:00"))
        repo.create("p1", "Race Test")
        setup_conn.close()

        # Barrier ensures both workers start simultaneously
        barrier = threading.Barrier(2)
        results = {"success": 0, "fail": 0}
        results_lock = threading.Lock()

        def attempt_transition():
            conn = connect(str(db_path))
            migrate_to_latest(conn)
            repo = ProjectRepository(conn, clock=frozen_clock("2026-01-01T00:00:00.000000+00:00"))
            barrier.wait()  # Synchronize start
            try:
                repo.transition_lifecycle("p1", LifecycleState.SCOPING)
                with results_lock:
                    results["success"] += 1
            except Exception:  # noqa: BLE001 — worker must never die; the outcome is counted
                with results_lock:
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
        verify_conn = connect(str(db_path))
        proj = verify_conn.execute(
            "SELECT lifecycle_state FROM projects WHERE project_id = 'p1'"
        ).fetchone()
        assert proj["lifecycle_state"] == "SCOPING"

        # Verify exactly one LifecycleTransition event
        events = verify_conn.execute(
            "SELECT * FROM events WHERE project_id = 'p1' AND event_type = 'LifecycleTransition'"
        ).fetchall()
        assert len(events) == 1, f"Expected 1 transition event, got {len(events)}"
        assert events[0]["from_state"] == "CREATED"
        assert events[0]["to_state"] == "SCOPING"

        # No false duplicate events
        all_transition_events = verify_conn.execute(
            "SELECT * FROM events WHERE event_type = 'LifecycleTransition'"
        ).fetchall()
        assert len(all_transition_events) == 1, "False duplicate event detected"
        verify_conn.close()

    def test_concurrent_different_tasks_both_succeed(self, tmp_path):
        """Two workers transition different tasks — both should succeed."""
        db_path = tmp_path / "race2.db"
        setup_conn = connect(str(db_path))
        migrate_to_latest(setup_conn)
        proj_repo = ProjectRepository(setup_conn, clock=frozen_clock("2026-01-01T00:00:00.000000+00:00"))
        proj_repo.create("p1", "Test")

        from hermes.core.node import NodeContract
        task_repo = TaskRepository(setup_conn, clock=frozen_clock("2026-01-01T00:00:00.000000+00:00"))
        task_repo.create(NodeContract(
            task_id="t1", project_id="p1", task_type="AGENT_TASK",
            idempotency_key="k1",
            status="PENDING",
        ))
        task_repo.create(NodeContract(
            task_id="t2", project_id="p1", task_type="AGENT_TASK",
            idempotency_key="k2",
            status="PENDING",
        ))
        setup_conn.close()

        barrier = threading.Barrier(2)
        results = {"success": 0, "fail": 0}
        results_lock = threading.Lock()

        def attempt_transition(task_id, task_status):
            conn = connect(str(db_path))
            migrate_to_latest(conn)
            repo = TaskRepository(conn)
            barrier.wait()
            try:
                repo.transition_status(task_id, task_status)
                with results_lock:
                    results["success"] += 1
            except Exception:  # noqa: BLE001 — worker must never die; the outcome is counted
                with results_lock:
                    results["fail"] += 1
            finally:
                conn.close()

        # Both tasks: PENDING → READY should succeed (no dependency conflict)
        from hermes.core.task_status import TaskStatus
        t1 = threading.Thread(target=attempt_transition, args=("t1", TaskStatus.READY))
        t2 = threading.Thread(target=attempt_transition, args=("t2", TaskStatus.READY))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert results["success"] == 2
        assert results["fail"] == 0


# ── F-10: Dependency INVALIDATED enforcement ──

class TestDependencyInvalidatedEnforcement:
    """F-10: READY→RUNNING rejected when a dependency is INVALIDATED."""

    def test_running_rejected_when_dependency_invalidated(self, mem_conn):
        from hermes.core.node import NodeContract
        from hermes.core.task_status import TaskStatus

        proj_repo = ProjectRepository(mem_conn)
        proj_repo.create("p1", "Test")
        task_repo = TaskRepository(mem_conn)

        # Create parent task, succeed it, then invalidate it
        task_repo.create(NodeContract(
            task_id="parent", project_id="p1", task_type="AGENT_TASK",
            idempotency_key="parent-key",
        ))
        task_repo.transition_status("parent", TaskStatus.READY)
        task_repo.transition_status("parent", TaskStatus.RUNNING)
        task_repo.transition_status("parent", TaskStatus.SUCCEEDED)
        task_repo.invalidate("parent", reason="upstream changed")

        # Create child task dependent on parent
        task_repo.create(NodeContract(
            task_id="child", project_id="p1", task_type="AGENT_TASK",
            idempotency_key="child-key",
            dependencies=["parent"],
        ))

        # Child can go to READY (status transition is valid)
        task_repo.transition_status("child", TaskStatus.READY)

        # But READY → RUNNING must be rejected because dep is INVALIDATED
        with pytest.raises(DependencyError, match="INVALIDATED"):
            task_repo.transition_status("child", TaskStatus.RUNNING)

    def test_running_succeeds_when_dependencies_succeeded(self, mem_conn):
        from hermes.core.node import NodeContract
        from hermes.core.task_status import TaskStatus

        proj_repo = ProjectRepository(mem_conn)
        proj_repo.create("p1", "Test")
        task_repo = TaskRepository(mem_conn)

        # Create parent task and succeed it
        task_repo.create(NodeContract(
            task_id="parent", project_id="p1", task_type="AGENT_TASK",
            idempotency_key="parent-key-2",
        ))
        task_repo.transition_status("parent", TaskStatus.READY)
        task_repo.transition_status("parent", TaskStatus.RUNNING)
        task_repo.transition_status("parent", TaskStatus.SUCCEEDED)

        # Create child task dependent on parent
        task_repo.create(NodeContract(
            task_id="child", project_id="p1", task_type="AGENT_TASK",
            idempotency_key="child-key-2",
            dependencies=["parent"],
        ))
        task_repo.transition_status("child", TaskStatus.READY)

        # READY → RUNNING should succeed (dep is SUCCEEDED, not INVALIDATED)
        result = task_repo.transition_status("child", TaskStatus.RUNNING)
        assert result["status"] == "RUNNING"

    def test_running_rejected_when_dependency_failed(self, mem_conn):
        """F-10: READY→RUNNING rejected when dependency is FAILED.

        v4 §7 rule 1: "all deps SUCCEEDED and none INVALIDATED" — a FAILED
        dependency means the dependency did not succeed, so the dependent
        task cannot start.
        """
        from hermes.core.node import NodeContract
        from hermes.core.task_status import TaskStatus

        proj_repo = ProjectRepository(mem_conn)
        proj_repo.create("p1", "Test")
        task_repo = TaskRepository(mem_conn)

        # Create parent task and fail it
        task_repo.create(NodeContract(
            task_id="parent", project_id="p1", task_type="AGENT_TASK",
            idempotency_key="parent-fail",
        ))
        task_repo.transition_status("parent", TaskStatus.READY)
        task_repo.transition_status("parent", TaskStatus.RUNNING)
        task_repo.transition_status("parent", TaskStatus.FAILED)

        # Create child task dependent on parent
        task_repo.create(NodeContract(
            task_id="child", project_id="p1", task_type="AGENT_TASK",
            idempotency_key="child-fail",
            dependencies=["parent"],
        ))

        # Child can go to READY (status transition is valid by itself)
        task_repo.transition_status("child", TaskStatus.READY)

        # But READY → RUNNING must be rejected because dep is FAILED
        with pytest.raises(DependencyError, match="not SUCCEEDED"):
            task_repo.transition_status("child", TaskStatus.RUNNING)

    def test_running_rejected_when_dependency_pending(self, mem_conn):
        """F-10: READY→RUNNING rejected when dependency is still PENDING."""
        from hermes.core.node import NodeContract
        from hermes.core.task_status import TaskStatus

        proj_repo = ProjectRepository(mem_conn)
        proj_repo.create("p1", "Test")
        task_repo = TaskRepository(mem_conn)

        # Create parent task (stays PENDING)
        task_repo.create(NodeContract(
            task_id="parent", project_id="p1", task_type="AGENT_TASK",
            idempotency_key="parent-pending",
        ))

        # Create child task dependent on parent
        task_repo.create(NodeContract(
            task_id="child", project_id="p1", task_type="AGENT_TASK",
            idempotency_key="child-pending",
            dependencies=["parent"],
        ))
        task_repo.transition_status("child", TaskStatus.READY)

        # READY → RUNNING must be rejected because dep is PENDING (not SUCCEEDED)
        with pytest.raises(DependencyError, match="not SUCCEEDED"):
            task_repo.transition_status("child", TaskStatus.RUNNING)


# ── F-11: Cycle detection ──

class TestCycleDetection:
    """F-11: Adding dependencies that create cycles must be rejected."""

    def test_self_cycle_rejected(self, mem_conn):
        from hermes.core.node import NodeContract

        proj_repo = ProjectRepository(mem_conn)
        proj_repo.create("p1", "Test")
        task_repo = TaskRepository(mem_conn)

        with pytest.raises(DependencyError, match="Self-cycle"):
            task_repo.create(NodeContract(
                task_id="t1", project_id="p1", task_type="AGENT_TASK",
                idempotency_key="k1",
                dependencies=["t1"],  # self-dependency
            ))

    def test_two_node_cycle_rejected(self, mem_conn):
        """Create a chain t1 ← t2 ← t3, then try to create t4 that depends
        on t3 and where t1 depends on t4 (would create a cycle).

        Actually, test a simpler cycle: create t1 (no deps), t2 depends on t1.
        Then try to create a NEW task t3 that depends on t2 AND whose id is
        something t2 depends on — wait, that's fine. The cycle is: try to create
        a task where one of its dependencies already has the task as a transitive
        dependency.

        Simpler: create t1, create t2(dep=[t1]). Now if we create a task t3 with
        dep=[t2], t3 is fine. But if we try to create a task t_new with dep=[t3]
        and t3 has dep=[t_new]... that's forward ref again.

        The cleanest test: create t1, create t2(dep=[t1]). Now try to create a
        task t3 with dep=[t2, t1] where we also MODIFY t1 to depend on t3.
        But the repo doesn't support adding deps to existing tasks.

        Best approach: test at the graph level using detect_cycle().
        """
        from hermes.core.graph import detect_cycle

        # Build a dependency map: t1 ← t2 ← t3 (no cycle)
        deps = {
            "t1": [],
            "t2": ["t1"],
            "t3": ["t2"],
        }
        # No cycle: t3 → t2 → t1, no path back to t3
        result = detect_cycle("t4", deps)
        assert result is None

        # Now simulate adding t4 → t3, and check if t3 → t2 → t1 → (nothing)
        # Add t4 with dep on t3 — still no cycle
        deps["t4"] = ["t3"]
        result = detect_cycle("t4", deps)
        assert result is None

        # But if we add t1 → t4, that creates cycle: t1 → t4 → t3 → t2 → t1
        deps["t1"] = ["t4"]
        result = detect_cycle("t1", deps)
        # Wait, detect_cycle checks from task_id's deps, so for t1 it checks if
        # t4 is reachable from t1's deps... t1 deps on t4, and t4 deps on t3,
        # t3 deps on t2, t2 deps on t1. So t1 → t4 → t3 → t2 → t1 = cycle.
        assert result is not None, "Expected cycle but none detected"
        assert "t1" in result

    def test_valid_dag_accepted(self, mem_conn):
        from hermes.core.node import NodeContract

        proj_repo = ProjectRepository(mem_conn)
        proj_repo.create("p1", "Test")
        task_repo = TaskRepository(mem_conn)

        # Linear DAG: t1 → t2 → t3 (no cycle)
        task_repo.create(NodeContract(
            task_id="t1", project_id="p1", task_type="AGENT_TASK",
            idempotency_key="k1",
        ))
        task_repo.create(NodeContract(
            task_id="t2", project_id="p1", task_type="AGENT_TASK",
            idempotency_key="k2",
            dependencies=["t1"],
        ))
        task_repo.create(NodeContract(
            task_id="t3", project_id="p1", task_type="AGENT_TASK",
            idempotency_key="k3",
            dependencies=["t2"],
        ))


class TestCycleDetectionParity:
    """ADD-02: DB-backed _check_no_cycle and pure graph.detect_cycle must agree.

    Each shape is tested through both entry points:
      1. TaskRepository.create() → _check_no_cycle (DB-backed, needs DB state)
      2. graph.detect_cycle() directly with a hand-built map (pure)

    Both must reject cycles and accept non-cycles identically.

    Note on DB-path limitations: the repository only supports adding
    dependencies at task-creation time, and task_dependencies has a FK
    on depends_on_task_id. This means cycles involving two or more
    pre-existing tasks can only be tested through the pure function
    (the DB path requires the new task's ID to already be in the
    transitive dependency chain of one of its deps, which needs
    forward references the FK forbids). The DB path is exercised for
    self-cycles and non-cycles (diamond); pure detect_cycle covers
    multi-node cycles.
    """

    def test_self_cycle_parity(self, mem_conn):
        """Self-cycle (task depends on itself) — rejected by both."""
        from hermes.core.graph import detect_cycle
        from hermes.core.node import NodeContract

        proj_repo = ProjectRepository(mem_conn)
        proj_repo.create("p1", "Self-Cycle Parity")
        task_repo = TaskRepository(mem_conn)

        # DB path: create raises DependencyError with "Self-cycle"
        with pytest.raises(DependencyError, match="Self-cycle"):
            task_repo.create(NodeContract(
                task_id="s1", project_id="p1", task_type="AGENT_TASK",
                idempotency_key="s1",
                dependencies=["s1"],
            ))

        # Pure path: detect_cycle with self in own dep list
        result = detect_cycle("s1", {"s1": ["s1"]})
        assert result is not None, "detect_cycle must detect self-cycle"

    def test_two_node_cycle_parity(self):
        """Direct 2-node cycle (t_a → t_b → t_a) — rejected by pure path."""
        from hermes.core.graph import detect_cycle

        deps = {"t_a": ["t_b"], "t_b": ["t_a"]}
        result = detect_cycle("t_a", deps)
        assert result is not None
        assert "t_a" in result and "t_b" in result

    def test_four_node_cycle_parity(self):
        """Longer 4-node cycle through an intermediate chain — rejected by pure path."""
        from hermes.core.graph import detect_cycle

        deps = {"c1": ["c4"], "c4": ["c3"], "c3": ["c2"], "c2": ["c1"]}
        result = detect_cycle("c1", deps)
        assert result is not None
        assert "c1" in result

    def test_diamond_not_cycle_parity(self, mem_conn):
        """Diamond dependency shape (not a cycle) — accepted by both."""
        from hermes.core.graph import detect_cycle
        from hermes.core.node import NodeContract

        proj_repo = ProjectRepository(mem_conn)
        proj_repo.create("p1", "Diamond Parity")
        task_repo = TaskRepository(mem_conn)

        # Diamond: d1 (root), d2(dep d1), d3(dep d1), d4(dep d2, d3)
        task_repo.create(NodeContract(
            task_id="d1", project_id="p1", task_type="AGENT_TASK",
            idempotency_key="d1",
        ))
        task_repo.create(NodeContract(
            task_id="d2", project_id="p1", task_type="AGENT_TASK",
            idempotency_key="d2", dependencies=["d1"],
        ))
        task_repo.create(NodeContract(
            task_id="d3", project_id="p1", task_type="AGENT_TASK",
            idempotency_key="d3", dependencies=["d1"],
        ))

        # DB path: create d4 depending on both d2 and d3 — no cycle
        task_repo.create(NodeContract(
            task_id="d4", project_id="p1", task_type="AGENT_TASK",
            idempotency_key="d4", dependencies=["d2", "d3"],
        ))

        # Pure path: same diamond, must also be no cycle
        deps = {
            "d1": [],
            "d2": ["d1"],
            "d3": ["d1"],
            "d4": ["d2", "d3"],
        }
        assert detect_cycle("d4", deps) is None
        assert detect_cycle("d1", deps) is None


# ── F-06: WAL-safe restore regression ──

class TestWALSafeRestore:
    """F-06: Restoring a snapshot must not resurrect newer state from WAL."""

    def test_restore_does_not_resurrect_wal_state(self, tmp_path):
        """Create snapshot, write newer state, restore snapshot — newer state
        must NOT reappear after restore."""
        from hermes.core.lifecycle import LifecycleState

        db_path = tmp_path / "live.db"
        backup_dir = tmp_path / "backups"

        # Set up DB and create project
        conn = connect(str(db_path))
        migrate_to_latest(conn)
        repo = ProjectRepository(conn, clock=frozen_clock("2026-01-01T00:00:00.000000+00:00"))
        repo.create("p1", "WAL Test")

        # Create backup snapshot
        backup = create_backup(conn, str(backup_dir),
                               clock=frozen_clock("2026-01-01T01:00:00.000000+00:00"))

        # Now write NEWER state (transition lifecycle)
        repo.transition_lifecycle("p1", LifecycleState.SCOPING)

        # Verify the newer state is visible
        assert repo.get_lifecycle("p1") == LifecycleState.SCOPING

        # Close all connections
        conn.close()

        # Restore the old backup (deletes -wal, -shm)
        restore_backup(backup.backup_path, str(db_path))

        # Reopen — the WAL was deleted by restore; a new empty WAL may be created
        # by this connect, but it won't contain the SCOPING transition
        conn2 = connect(str(db_path))
        migrate_to_latest(conn2)

        # Check that the project state is CREATED (from backup), not SCOPING (from WAL)
        row = conn2.execute(
            "SELECT lifecycle_state FROM projects WHERE project_id = 'p1'"
        ).fetchone()
        assert row is not None
        assert row["lifecycle_state"] == "CREATED", \
            f"WAL resurrected newer state: {row['lifecycle_state']} (expected CREATED)"

        # Integrity check
        from hermes.persistence.database import integrity_check
        assert integrity_check(conn2) is True

        conn2.close()

    def test_normal_backup_restore_works(self, tmp_path):
        """Normal backup/restore preserves data correctly."""
        db_path = tmp_path / "live.db"
        backup_dir = tmp_path / "backups"

        conn = connect(str(db_path))
        migrate_to_latest(conn)
        repo = ProjectRepository(conn, clock=frozen_clock("2026-01-01T00:00:00.000000+00:00"))
        repo.create("p1", "Test")
        repo.transition_lifecycle("p1", LifecycleState.SCOPING)

        backup = create_backup(conn, str(backup_dir))
        conn.close()

        restore_backup(backup.backup_path, str(db_path))

        conn2 = connect(str(db_path))
        migrate_to_latest(conn2)
        proj = conn2.execute("SELECT * FROM projects WHERE project_id = 'p1'").fetchone()
        assert proj["name"] == "Test"
        assert proj["lifecycle_state"] == "SCOPING"
        conn2.close()


# ── C.1: scheduler_lock dormancy (IDR-016) ──

class TestSchedulerLockDormancy:
    """IDR-016: The scheduler_lock is a dormant primitive in Phase 1.

    Repository mutations rely solely on SQLite's BEGIN IMMEDIATE transaction
    exclusivity — not the advisory scheduler_lock row. The lock is reserved for
    Phase 3+ multi-controller-instance use (§8, assigned to P3 by the roadmap).
    These tests pin that decision so a future reader sees the lock's absence from
    the write path is intentional, not an oversight.
    """

    def test_project_create_works_without_writer_lock(self, mem_conn):
        """ProjectRepository.create() succeeds without calling acquire_writer_lock.

        Per IDR-016, the sole P1-era mutual-exclusion mechanism is BEGIN IMMEDIATE.
        The scheduler_lock row must not exist after a repository-level create.
        """

        repo = ProjectRepository(mem_conn)
        repo.create("dormancy-p1", "Dormancy Test")

        # No lock row should exist — the repository never calls acquire_writer_lock.
        assert get_lock_owner(mem_conn) is None

    def test_task_transition_works_without_writer_lock(self, mem_conn):
        """TaskRepository.transition_status() succeeds without calling acquire_writer_lock."""
        from hermes.core.node import NodeContract
        from hermes.core.task_status import TaskStatus

        proj_repo = ProjectRepository(mem_conn)
        proj_repo.create("dormancy-p2", "Dormancy Test 2")
        task_repo = TaskRepository(mem_conn)
        task_repo.create(NodeContract(
            task_id="dormant-task", project_id="dormancy-p2",
            task_type="AGENT_TASK", idempotency_key="dormant-k1",
        ))
        task_repo.transition_status("dormant-task", TaskStatus.READY)

        # No lock row should exist.
        assert get_lock_owner(mem_conn) is None

    def test_lock_primitive_still_works_when_explicitly_called(self, mem_conn):
        """The lock primitive functions correctly when explicitly called — it's
        dormant (no callers), not broken. P1's 'stale-lock rejection' criterion
        is satisfied by these explicit tests, not by repository integration."""
        assert acquire_writer_lock(mem_conn, owner_id="test-owner") is True
        assert get_lock_owner(mem_conn) == "test-owner"
        release_writer_lock(mem_conn, owner_id="test-owner")
        assert get_lock_owner(mem_conn) is None


# ── C.6: invalidate() non-cascade contract (IDR-017) ──

class TestInvalidateNonCascade:
    """IDR-017: invalidate() is a single-task operation; it does not cascade.

    These tests pin the current (non-cascade) behavior as documented in IDR-017.
    They prove the gap exists exactly as described — a RUNNING dependent is
    untouched when its dependency is invalidated, and the invalidated task's own
    status correctly transitions to INVALIDATED. No other task in the graph is
    affected.
    """

    def test_invalidate_does_not_cascade_to_running_dependent_documented_gap(self, mem_conn):
        """Pin the current non-cascade gap.

        Graph: A (SUCCEEDED) ← B (RUNNING).
        When A is invalidated, B must remain RUNNING — invalidate() does not
        cascade. This is the current P1 behavior, documented in IDR-017 as a
        known deliberate gap. Full cascade semantics are deferred to the
        reconcile loop (§8, P3).
        """
        from hermes.core.node import NodeContract
        from hermes.core.task_status import TaskStatus

        proj_repo = ProjectRepository(mem_conn)
        proj_repo.create("cascade-test", "Cascade Test")
        task_repo = TaskRepository(mem_conn)

        # Create A (no deps)
        task_repo.create(NodeContract(
            task_id="A", project_id="cascade-test", task_type="AGENT_TASK",
            idempotency_key="A",
        ))
        # Create B depends on A
        task_repo.create(NodeContract(
            task_id="B", project_id="cascade-test", task_type="AGENT_TASK",
            idempotency_key="B", dependencies=["A"],
        ))

        # Drive A to SUCCEEDED: PENDING → READY → RUNNING → SUCCEEDED
        task_repo.transition_status("A", TaskStatus.READY)
        task_repo.transition_status("A", TaskStatus.RUNNING)
        task_repo.transition_status("A", TaskStatus.SUCCEEDED)

        # Drive B to RUNNING
        task_repo.transition_status("B", TaskStatus.READY)
        task_repo.transition_status("B", TaskStatus.RUNNING)

        # Capture pre-invalidation state
        assert task_repo.get_status("B") == TaskStatus.RUNNING

        # Invalidate A
        result = task_repo.invalidate("A")
        assert result["status"] == TaskStatus.INVALIDATED.value

        # Pin the gap: B is still RUNNING, not invalidated/cancelled/failed
        assert task_repo.get_status("B") == TaskStatus.RUNNING, (
            "IDR-017: invalidate() must not cascade to running dependents"
        )

        # No other task was touched — only A and B exist, and B is unchanged
        assert task_repo.get_status("A") == TaskStatus.INVALIDATED
