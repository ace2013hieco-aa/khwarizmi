"""Repository tests — verifying the domain/SQL boundary (Phase 1 req §18, §19)."""
from __future__ import annotations

import sqlite3

import pytest

from hermes.core.lifecycle import LifecycleState, TransitionError
from hermes.core.modes import ModeTransitionError, OperationalMode
from hermes.core.node import NodeContract, NodeType
from hermes.core.task_status import TaskStatus, TaskTransitionError
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    EventRepository,
    NotFoundError,
    ProjectRepository,
    TaskRepository,
)


@pytest.fixture
def conn():
    c = connect(":memory:")
    migrate_to_latest(c)
    yield c
    c.close()


@pytest.fixture
def proj_repo(conn):
    return ProjectRepository(conn)


@pytest.fixture
def task_repo(conn):
    return TaskRepository(conn)


@pytest.fixture
def event_repo(conn):
    return EventRepository(conn)


@pytest.fixture
def project_id(proj_repo):
    p = proj_repo.create("proj-001", "Test Project")
    return p["project_id"]


# ── Project Repository ──

class TestProjectRepository:
    def test_create_project(self, proj_repo):
        p = proj_repo.create("proj-001", "Test Project")
        assert p["project_id"] == "proj-001"
        assert p["name"] == "Test Project"
        assert p["lifecycle_state"] == "CREATED"
        assert p["operational_mode"] == "ACTIVE"
        assert p["iteration"] == 1

    def test_get_lifecycle(self, proj_repo, project_id):
        assert proj_repo.get_lifecycle(project_id) == LifecycleState.CREATED

    def test_get_mode(self, proj_repo, project_id):
        assert proj_repo.get_mode(project_id) == OperationalMode.ACTIVE

    def test_get_nonexistent_raises(self, proj_repo):
        with pytest.raises(NotFoundError):
            proj_repo.get("nonexistent")

    def test_transition_lifecycle_valid(self, proj_repo, project_id):
        p = proj_repo.transition_lifecycle(project_id, LifecycleState.SCOPING)
        assert p["lifecycle_state"] == "SCOPING"
        assert proj_repo.get_lifecycle(project_id) == LifecycleState.SCOPING

    def test_transition_lifecycle_invalid_raises(self, proj_repo, project_id):
        with pytest.raises(TransitionError):
            proj_repo.transition_lifecycle(project_id, LifecycleState.COMPLETED)

    def test_transition_lifecycle_invalid_db_unchanged(self, proj_repo, project_id):
        """No-direct-mutation regression: illegal transition → DB unchanged."""
        state_before = proj_repo.get_lifecycle(project_id)
        with pytest.raises(TransitionError):
            proj_repo.transition_lifecycle(project_id, LifecycleState.COMPLETED)
        state_after = proj_repo.get_lifecycle(project_id)
        assert state_before == state_after  # must be identical

    def test_transition_mode_valid(self, proj_repo, project_id):
        p = proj_repo.transition_mode(project_id, OperationalMode.PAUSED)
        assert p["operational_mode"] == "PAUSED"
        assert proj_repo.get_mode(project_id) == OperationalMode.PAUSED

    def test_transition_mode_to_same_raises(self, proj_repo, project_id):
        with pytest.raises(ModeTransitionError):
            proj_repo.transition_mode(project_id, OperationalMode.ACTIVE)

    def test_advance_iteration(self, proj_repo, project_id):
        new_iter = proj_repo.advance_iteration(project_id)
        assert new_iter == 2
        assert proj_repo.get(project_id)["iteration"] == 2

    def test_list_all(self, proj_repo):
        proj_repo.create("p1", "A")
        proj_repo.create("p2", "B")
        all_projects = proj_repo.list_all()
        assert len(all_projects) == 2


# ── Task Repository ──

class TestTaskRepository:
    def _make_node(self, project_id, task_id="task-001", idempotency_key="hash-001"):
        return NodeContract(
            task_id=task_id,
            project_id=project_id,
            task_type=NodeType.TOOL_TASK.value,
            idempotency_key=idempotency_key,
        )

    def test_create_task(self, task_repo, project_id):
        node = self._make_node(project_id)
        t = task_repo.create(node)
        assert t["task_id"] == "task-001"
        assert t["status"] == TaskStatus.PENDING.value
        assert t["task_type"] == "TOOL_TASK"
        assert t["attempt"] == 1

    def test_get_status(self, task_repo, project_id):
        task_repo.create(self._make_node(project_id))
        assert task_repo.get_status("task-001") == TaskStatus.PENDING

    def test_transition_status_valid(self, task_repo, project_id):
        task_repo.create(self._make_node(project_id))
        t = task_repo.transition_status("task-001", TaskStatus.READY)
        assert t["status"] == TaskStatus.READY.value
        t = task_repo.transition_status("task-001", TaskStatus.RUNNING)
        assert t["status"] == TaskStatus.RUNNING.value
        t = task_repo.transition_status("task-001", TaskStatus.SUCCEEDED)
        assert t["status"] == TaskStatus.SUCCEEDED.value
        assert t["completed_at"] is not None

    def test_transition_status_invalid_raises(self, task_repo, project_id):
        task_repo.create(self._make_node(project_id))
        with pytest.raises(TaskTransitionError):
            task_repo.transition_status("task-001", TaskStatus.SUCCEEDED)  # PENDING → SUCCEEDED is illegal

    def test_invalid_status_transition_db_unchanged(self, task_repo, project_id):
        """No-direct-mutation: illegal task transition → DB unchanged."""
        task_repo.create(self._make_node(project_id))
        status_before = task_repo.get_status("task-001")
        with pytest.raises(TaskTransitionError):
            task_repo.transition_status("task-001", TaskStatus.SUCCEEDED)
        status_after = task_repo.get_status("task-001")
        assert status_before == status_after

    def test_idempotency_key_uniqueness(self, task_repo, project_id):
        """Same idempotency_key + same attempt must fail."""
        node1 = self._make_node(project_id, task_id="t1", idempotency_key="dup-hash")
        task_repo.create(node1)
        node2 = NodeContract(
            task_id="t2", project_id=project_id,
            task_type=NodeType.TOOL_TASK.value,
            idempotency_key="dup-hash",  # same key
        )
        with pytest.raises(sqlite3.IntegrityError):
            task_repo.create(node2)

    def test_invalidate_succeeded_task(self, task_repo, project_id):
        """v3 §7 rule 4: SUCCEEDED → INVALIDATED is allowed."""
        task_repo.create(self._make_node(project_id))
        task_repo.transition_status("task-001", TaskStatus.READY)
        task_repo.transition_status("task-001", TaskStatus.RUNNING)
        task_repo.transition_status("task-001", TaskStatus.SUCCEEDED)
        t = task_repo.invalidate("task-001", reason="upstream changed")
        assert t["status"] == TaskStatus.INVALIDATED.value

    def test_invalidate_non_succeeded_raises(self, task_repo, project_id):
        """Cannot invalidate a task that hasn't succeeded."""
        task_repo.create(self._make_node(project_id))
        with pytest.raises(TaskTransitionError):
            task_repo.invalidate("task-001")

    def test_dependencies_persisted(self, task_repo, project_id):
        """Task dependencies are stored in task_dependencies table."""
        # Create two independent tasks
        task_repo.create(self._make_node(project_id, task_id="dep-1", idempotency_key="hash-d1"))
        task_repo.create(NodeContract(
            task_id="dep-2", project_id=project_id,
            task_type=NodeType.TOOL_TASK.value,
            idempotency_key="hash-d2",
        ))
        # Create a task that depends on both
        node = NodeContract(
            task_id="main-task", project_id=project_id,
            task_type=NodeType.AGENT_TASK.value,
            idempotency_key="hash-main",
            dependencies=["dep-1", "dep-2"],
        )
        task_repo.create(node)
        deps = task_repo.get_dependencies("main-task")
        assert set(deps) == {"dep-1", "dep-2"}

    def test_list_for_project(self, task_repo, project_id):
        task_repo.create(self._make_node(project_id, task_id="t1", idempotency_key="h1"))
        task_repo.create(self._make_node(project_id, task_id="t2", idempotency_key="h2"))
        tasks = task_repo.list_for_project(project_id)
        assert len(tasks) == 2

    def test_list_for_project_by_iteration(self, task_repo, project_id):
        task_repo.create(self._make_node(project_id, task_id="t1", idempotency_key="h1"))
        task_repo.create(NodeContract(
            task_id="t2", project_id=project_id,
            task_type=NodeType.TOOL_TASK.value,
            idempotency_key="h2",
            iteration=2,
        ))
        iter1 = task_repo.list_for_project(project_id, iteration=1)
        iter2 = task_repo.list_for_project(project_id, iteration=2)
        assert len(iter1) == 1
        assert len(iter2) == 1
        assert iter1[0]["task_id"] == "t1"
        assert iter2[0]["task_id"] == "t2"


# ── Event Repository (append-only) ──

class TestEventRepository:
    def test_events_appended_on_project_creation(self, event_repo, proj_repo):
        """Creating a project appends exactly one ResearchCreated event."""
        proj_repo.create("proj-001", "Test")
        events = event_repo.list_for_project("proj-001")
        assert len(events) == 1
        assert events[0]["event_type"] == "ResearchCreated"
        assert events[0]["to_state"] == "CREATED"

    def test_events_appended_on_lifecycle_transition(self, event_repo, proj_repo):
        """A lifecycle transition appends exactly one event."""
        proj_repo.create("proj-001", "Test")
        proj_repo.transition_lifecycle("proj-001", LifecycleState.SCOPING)
        events = event_repo.list_for_project("proj-001")
        assert len(events) == 2  # ResearchCreated + LifecycleTransition
        transition_event = events[1]
        assert transition_event["event_type"] == "LifecycleTransition"
        assert transition_event["from_state"] == "CREATED"
        assert transition_event["to_state"] == "SCOPING"

    def test_events_ordered_by_event_id(self, event_repo, proj_repo):
        proj_repo.create("proj-001", "Test")
        proj_repo.transition_lifecycle("proj-001", LifecycleState.SCOPING)
        proj_repo.transition_lifecycle("proj-001", LifecycleState.LITERATURE_REVIEW)
        events = event_repo.list_for_project("proj-001")
        ids = [e["event_id"] for e in events]
        assert ids == sorted(ids)  # monotonic

    def test_events_for_task(self, event_repo, proj_repo, task_repo):
        proj_repo.create("proj-001", "Test")
        task_repo.create(NodeContract(
            task_id="t1", project_id="proj-001",
            task_type=NodeType.TOOL_TASK.value,
            idempotency_key="h1",
        ))
        events = event_repo.list_for_task("t1")
        assert len(events) == 1
        assert events[0]["event_type"] == "TaskCreated"

    def test_event_count(self, event_repo, proj_repo):
        proj_repo.create("p1", "A")
        proj_repo.create("p2", "B")
        assert event_repo.count() == 2

    def test_correlation_id_not_empty(self, event_repo, proj_repo):
        """Every transition event has a non-empty correlation ID."""
        proj_repo.create("proj-001", "Test")
        proj_repo.transition_lifecycle("proj-001", LifecycleState.SCOPING)
        events = event_repo.list_for_project("proj-001")
        for e in events:
            assert e["correlation_id"]  # not empty


# ── Transaction + Event Atomicity (IDR-013, Phase 1 req §19) ──

class TestAtomicity:
    def test_legal_transition_produces_exactly_one_event(self, event_repo, proj_repo):
        """Legal transition → state changed → exactly one corresponding event."""
        proj_repo.create("proj-001", "Test")
        event_count_before = event_repo.count()
        proj_repo.transition_lifecycle("proj-001", LifecycleState.SCOPING)
        event_count_after = event_repo.count()
        delta = event_count_after - event_count_before
        assert delta == 1  # exactly one event per transition

    def test_illegal_transition_no_event_appended(self, event_repo, proj_repo):
        """Illegal transition → no event appended, DB unchanged."""
        proj_repo.create("proj-001", "Test")
        event_count_before = event_repo.count()
        with pytest.raises(TransitionError):
            proj_repo.transition_lifecycle("proj-001", LifecycleState.COMPLETED)
        event_count_after = event_repo.count()
        assert event_count_after == event_count_before  # no event


# ── Event replay / reconstruction (Phase 1 req §20) ──

class TestEventReplay:
    def test_final_event_state_matches_persisted_lifecycle(self, event_repo, proj_repo):
        """The last LifecycleTransition event's to_state matches the persisted lifecycle."""
        proj_repo.create("proj-001", "Test")
        proj_repo.transition_lifecycle("proj-001", LifecycleState.SCOPING)
        proj_repo.transition_lifecycle("proj-001", LifecycleState.LITERATURE_REVIEW)
        proj_repo.transition_lifecycle("proj-001", LifecycleState.HYPOTHESIS_FORMULATION)

        # Read persisted state
        persisted = proj_repo.get_lifecycle("proj-001")

        # Replay events
        events = event_repo.list_for_project("proj-001")
        lifecycle_events = [e for e in events if e["event_type"] == "LifecycleTransition"]
        assert len(lifecycle_events) >= 1
        final = lifecycle_events[-1]["to_state"]

        assert persisted.value == final
