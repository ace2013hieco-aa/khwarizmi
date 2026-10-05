"""Tests for the event journal (v3 §8.1) and graph queries (v3 §7)."""
from __future__ import annotations

import pytest

from hermes.core.graph import ReadinessResult, compute_subgraph_for_iteration, is_ready
from hermes.core.lifecycle import LifecycleState
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    EventRepository,
    ProjectRepository,
    TaskRepository,
)


@pytest.fixture
def repos():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    yield (
        ProjectRepository(conn),
        TaskRepository(conn),
        EventRepository(conn),
    )
    conn.close()


class TestEventAppendOnly:
    """Events can only be appended, never updated or deleted."""

    def test_no_delete_method(self):
        """EventRepository must not expose a delete method."""
        assert not hasattr(EventRepository, "delete")
        assert not hasattr(EventRepository, "remove")

    def test_no_update_method(self):
        """EventRepository must not expose an update method."""
        assert not hasattr(EventRepository, "update")

    def test_events_only_grow(self, repos):
        proj_repo, _task_repo, event_repo = repos
        proj_repo.create("p1", "Test")
        count_1 = event_repo.count()
        proj_repo.transition_lifecycle("p1", LifecycleState.SCOPING)
        count_2 = event_repo.count()
        assert count_2 > count_1  # grew
        proj_repo.transition_lifecycle("p1", LifecycleState.LITERATURE_REVIEW)
        count_3 = event_repo.count()
        assert count_3 > count_2  # grew again

    def test_list_all_returns_in_order(self, repos):
        proj_repo, _, event_repo = repos
        proj_repo.create("p1", "A")
        proj_repo.create("p2", "B")
        all_events = event_repo.list_all()
        ids = [e["event_id"] for e in all_events]
        assert ids == sorted(ids)


class TestEventCorrelation:
    def test_correlation_ids_are_unique_per_transition(self, repos):
        proj_repo, _, event_repo = repos
        proj_repo.create("p1", "Test")
        proj_repo.transition_lifecycle("p1", LifecycleState.SCOPING)
        proj_repo.transition_lifecycle("p1", LifecycleState.LITERATURE_REVIEW)
        events = [e for e in event_repo.list_for_project("p1")
                    if e["event_type"] == "LifecycleTransition"]
        assert len(events) == 2
        assert events[0]["correlation_id"] != events[1]["correlation_id"]

    def test_created_event_has_correlation_id(self, repos):
        proj_repo, _, event_repo = repos
        proj_repo.create("p1", "Test")
        events = event_repo.list_for_project("p1")
        assert len(events) == 1
        assert events[0]["correlation_id"]  # not empty


class TestEventReplay:
    def test_replay_lifecycle_transitions(self, repos):
        proj_repo, _, event_repo = repos
        proj_repo.create("p1", "Test")
        for target in [LifecycleState.SCOPING, LifecycleState.LITERATURE_REVIEW,
                       LifecycleState.HYPOTHESIS_FORMULATION]:
            proj_repo.transition_lifecycle("p1", target)

        events = event_repo.list_for_project("p1")
        transitions = [e for e in events if e["event_type"] == "LifecycleTransition"]
        assert len(transitions) == 3

        # Verify chain: each from_state == previous to_state
        assert transitions[0]["from_state"] == "CREATED"
        assert transitions[0]["to_state"] == "SCOPING"
        assert transitions[1]["from_state"] == "SCOPING"
        assert transitions[1]["to_state"] == "LITERATURE_REVIEW"
        assert transitions[2]["from_state"] == "LITERATURE_REVIEW"
        assert transitions[2]["to_state"] == "HYPOTHESIS_FORMULATION"

        # Final event's to_state matches persisted lifecycle
        assert transitions[-1]["to_state"] == proj_repo.get_lifecycle("p1").value


class TestGraphReadiness:
    def test_no_dependencies_ready(self):
        result = is_ready("t1", [], {})
        assert result.ready is True
        assert result.unfulfilled_deps == []
        assert result.invalidated_deps == []

    def test_all_deps_succeeded_ready(self):
        dep_statuses = {"dep1": "SUCCEEDED", "dep2": "SUCCEEDED"}
        result = is_ready("t1", ["dep1", "dep2"], dep_statuses)
        assert result.ready is True

    def test_dep_pending_not_ready(self):
        dep_statuses = {"dep1": "PENDING", "dep2": "SUCCEEDED"}
        result = is_ready("t1", ["dep1", "dep2"], dep_statuses)
        assert result.ready is False
        assert "dep1" in result.unfulfilled_deps
        assert "dep2" not in result.unfulfilled_deps

    def test_dep_invalidated_blocked(self):
        dep_statuses = {"dep1": "INVALIDATED", "dep2": "SUCCEEDED"}
        result = is_ready("t1", ["dep1", "dep2"], dep_statuses)
        assert result.ready is False
        assert result.blocked is True
        assert "dep1" in result.invalidated_deps

    def test_all_deps_invalidated_blocked(self):
        dep_statuses = {"dep1": "INVALIDATED", "dep2": "INVALIDATED"}
        result = is_ready("t1", ["dep1", "dep2"], dep_statuses)
        assert result.ready is False
        assert result.blocked is True
        assert len(result.invalidated_deps) == 2

    def test_missing_dep_treated_as_pending(self):
        """A missing dep (not in dict) is treated as PENDING."""
        result = is_ready("t1", ["dep1"], {})
        assert result.ready is False
        assert "dep1" in result.unfulfilled_deps

    def test_readiness_result_blocked_property(self):
        """The blocked property is True when invalidated_deps is non-empty."""
        r1 = ReadinessResult(task_id="t", ready=False, invalidated_deps=["d"])
        assert r1.blocked is True
        r2 = ReadinessResult(task_id="t", ready=False, unfulfilled_deps=["d"])
        assert r2.blocked is False
        r3 = ReadinessResult(task_id="t", ready=True)
        assert r3.blocked is False


class TestSubgraphIteration:
    def test_filter_by_iteration(self):
        tasks = [
            {"task_id": "t1", "iteration": 1},
            {"task_id": "t2", "iteration": 1},
            {"task_id": "t3", "iteration": 2},
            {"task_id": "t4", "iteration": 2},
            {"task_id": "t5", "iteration": 3},
        ]
        iter1 = compute_subgraph_for_iteration(tasks, 1)
        iter2 = compute_subgraph_for_iteration(tasks, 2)
        iter3 = compute_subgraph_for_iteration(tasks, 3)
        assert len(iter1) == 2
        assert len(iter2) == 2
        assert len(iter3) == 1
        assert all(t["iteration"] == 1 for t in iter1)
        assert all(t["iteration"] == 2 for t in iter2)

    def test_empty_iteration_returns_empty(self):
        tasks = [{"task_id": "t1", "iteration": 1}]
        result = compute_subgraph_for_iteration(tasks, 99)
        assert result == []

    def test_preserves_old_graph_when_new_iteration(self):
        """v3 §7 rule 3: new iteration creates new subgraph, old preserved."""
        all_tasks = [
            {"task_id": "t1", "iteration": 1, "task_type": "AGENT_TASK"},
            {"task_id": "t2", "iteration": 1, "task_type": "GATE"},
        ]
        # Iteration 2 creates new tasks but preserves iteration 1
        all_tasks.extend([
            {"task_id": "t3", "iteration": 2, "task_type": "AGENT_TASK"},
            {"task_id": "t4", "iteration": 2, "task_type": "GATE"},
        ])
        iter1 = compute_subgraph_for_iteration(all_tasks, 1)
        iter2 = compute_subgraph_for_iteration(all_tasks, 2)
        assert len(iter1) == 2  # still there, not mutated
        assert len(iter2) == 2
        assert iter1[0]["task_id"] == "t1"
