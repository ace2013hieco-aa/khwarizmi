"""Tests for the task status machine (v3 §6.3) — independent from lifecycle."""
from __future__ import annotations

import pytest

from hermes.core.task_status import (
    TaskStatus,
    TaskTransitionError,
    all_task_status_values,
    allowed_task_transitions,
    is_valid_task_transition,
    validate_task_transition,
)


class TestTaskStatuses:
    def test_twelve_statuses(self):
        assert len(list(TaskStatus)) == 12

    def test_status_values(self):
        assert TaskStatus.PENDING.value == "PENDING"
        assert TaskStatus.RUNNING.value == "RUNNING"
        assert TaskStatus.SUCCEEDED.value == "SUCCEEDED"
        assert TaskStatus.INVALIDATED.value == "INVALIDATED"

    def test_all_task_status_values(self):
        vals = all_task_status_values()
        assert len(vals) == 12
        assert "PENDING" in vals
        assert "INVALIDATED" in vals


class TestValidTaskTransitions:
    @pytest.mark.parametrize("from_status,to_status", [
        (TaskStatus.PENDING, TaskStatus.READY),
        (TaskStatus.PENDING, TaskStatus.CANCELLED),
        (TaskStatus.PENDING, TaskStatus.SKIPPED),
        (TaskStatus.READY, TaskStatus.RUNNING),
        (TaskStatus.READY, TaskStatus.CANCELLED),
        (TaskStatus.READY, TaskStatus.SKIPPED),
        (TaskStatus.READY, TaskStatus.INVALIDATED),
        (TaskStatus.RUNNING, TaskStatus.SUCCEEDED),
        (TaskStatus.RUNNING, TaskStatus.FAILED),
        (TaskStatus.RUNNING, TaskStatus.NO_SIGNAL),
        (TaskStatus.RUNNING, TaskStatus.WAITING_HUMAN),
        (TaskStatus.RUNNING, TaskStatus.WAITING_EXTERNAL),
        (TaskStatus.RUNNING, TaskStatus.CANCELLED),
        (TaskStatus.NO_SIGNAL, TaskStatus.RUNNING),
        (TaskStatus.NO_SIGNAL, TaskStatus.FAILED),
        (TaskStatus.WAITING_HUMAN, TaskStatus.RUNNING),
        (TaskStatus.WAITING_EXTERNAL, TaskStatus.RUNNING),
        (TaskStatus.WAITING_EXTERNAL, TaskStatus.FAILED),
        (TaskStatus.FAILED, TaskStatus.RETRYING),
        (TaskStatus.FAILED, TaskStatus.CANCELLED),
        (TaskStatus.RETRYING, TaskStatus.RUNNING),
        (TaskStatus.SUCCEEDED, TaskStatus.INVALIDATED),  # can be invalidated after success
    ])
    def test_valid_transition(self, from_status, to_status):
        assert is_valid_task_transition(from_status, to_status)
        validate_task_transition(from_status, to_status)  # should not raise


class TestInvalidTaskTransitions:
    @pytest.mark.parametrize("from_status,to_status", [
        (TaskStatus.PENDING, TaskStatus.RUNNING),       # must go through READY
        (TaskStatus.PENDING, TaskStatus.SUCCEEDED),     # too far
        (TaskStatus.READY, TaskStatus.SUCCEEDED),       # must run first
        (TaskStatus.SUCCEEDED, TaskStatus.RUNNING),     # terminal (except INVALIDATED)
        (TaskStatus.CANCELLED, TaskStatus.RUNNING),      # terminal
        (TaskStatus.SKIPPED, TaskStatus.RUNNING),         # terminal
        (TaskStatus.INVALIDATED, TaskStatus.RUNNING),    # terminal
    ])
    def test_invalid_transition_raises(self, from_status, to_status):
        assert not is_valid_task_transition(from_status, to_status)
        with pytest.raises(TaskTransitionError):
            validate_task_transition(from_status, to_status)

    def test_error_has_from_and_to(self):
        try:
            validate_task_transition(TaskStatus.PENDING, TaskStatus.RUNNING)
            raise AssertionError()
        except TaskTransitionError as e:
            assert e.from_status == TaskStatus.PENDING
            assert e.to_status == TaskStatus.RUNNING


class TestTerminalStatuses:
    def test_four_terminal_statuses(self):
        terminals = TaskStatus.terminal_statuses()
        assert len(terminals) == 4
        assert TaskStatus.SUCCEEDED in terminals
        assert TaskStatus.CANCELLED in terminals
        assert TaskStatus.SKIPPED in terminals
        assert TaskStatus.INVALIDATED in terminals

    @pytest.mark.parametrize("terminal", [
        TaskStatus.CANCELLED,
        TaskStatus.SKIPPED,
        TaskStatus.INVALIDATED,
    ])
    def test_terminal_no_outgoing(self, terminal):
        assert allowed_task_transitions(terminal) == frozenset()

    def test_succeeded_can_be_invalidated(self):
        """SUCCEEDED is quasi-terminal — it can transition to INVALIDATED."""
        allowed = allowed_task_transitions(TaskStatus.SUCCEEDED)
        assert TaskStatus.INVALIDATED in allowed
