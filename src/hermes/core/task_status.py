"""Task status machine (v4 §6.3) — per-node operational status.

Independent from lifecycle state (§6.1) and operational mode (§6.2).
The three axes are never conflated (v3 §6).

```
PENDING → READY → RUNNING → SUCCEEDED
              │         ├→ NO_SIGNAL → FAILED (second conclusive miss)
              │         └→ WAITING_HUMAN | WAITING_EXTERNAL → RUNNING
              ├→ CANCELLED | SKIPPED (optional branches only)
              └→ INVALIDATED
FAILED → RETRYING → RUNNING
```
"""
from __future__ import annotations

from enum import Enum


class TaskStatus(str, Enum):
    """v4 §6.3 task statuses (per node)."""

    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    NO_SIGNAL = "NO_SIGNAL"
    WAITING_HUMAN = "WAITING_HUMAN"
    WAITING_EXTERNAL = "WAITING_EXTERNAL"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"
    INVALIDATED = "INVALIDATED"

    @classmethod
    def all_values(cls) -> frozenset[str]:
        return frozenset(member.value for member in cls)

    @classmethod
    def terminal_statuses(cls) -> frozenset["TaskStatus"]:
        """Statuses from which no further transition is possible."""
        return frozenset({
            cls.SUCCEEDED,
            cls.CANCELLED,
            cls.SKIPPED,
            cls.INVALIDATED,
        })


class TaskTransitionError(Exception):
    """Raised when a task status transition is illegal."""

    def __init__(self, from_status: TaskStatus, to_status: TaskStatus, reason: str = ""):
        self.from_status = from_status
        self.to_status = to_status
        self.reason = reason
        super().__init__(
            f"Invalid task status transition: {from_status.value} → {to_status.value}"
            + (f" — {reason}" if reason else "")
        )


# ── v4 §6.3 task status transition table ──

_TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset({TaskStatus.READY, TaskStatus.CANCELLED, TaskStatus.SKIPPED}),
    TaskStatus.READY: frozenset({
        TaskStatus.RUNNING,
        TaskStatus.CANCELLED,
        TaskStatus.SKIPPED,
        TaskStatus.INVALIDATED,
    }),
    TaskStatus.RUNNING: frozenset({
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.NO_SIGNAL,
        TaskStatus.WAITING_HUMAN,
        TaskStatus.WAITING_EXTERNAL,
        TaskStatus.CANCELLED,
    }),
    TaskStatus.NO_SIGNAL: frozenset({
        TaskStatus.RUNNING,    # fresh heartbeat before second check → revert
        TaskStatus.FAILED,     # second consecutive miss → confirmed dead
    }),
    TaskStatus.WAITING_HUMAN: frozenset({TaskStatus.RUNNING}),
    TaskStatus.WAITING_EXTERNAL: frozenset({TaskStatus.RUNNING, TaskStatus.FAILED}),
    TaskStatus.FAILED: frozenset({TaskStatus.RETRYING, TaskStatus.CANCELLED}),
    TaskStatus.RETRYING: frozenset({TaskStatus.RUNNING}),
    # Terminal statuses
    TaskStatus.SUCCEEDED: frozenset({TaskStatus.INVALIDATED}),  # can be invalidated after success
    TaskStatus.CANCELLED: frozenset(),
    TaskStatus.SKIPPED: frozenset(),
    TaskStatus.INVALIDATED: frozenset(),
}


def is_valid_task_transition(from_status: TaskStatus, to_status: TaskStatus) -> bool:
    if not isinstance(to_status, TaskStatus):
        return False
    return to_status in _TASK_TRANSITIONS.get(from_status, frozenset())


def validate_task_transition(from_status: TaskStatus, to_status: TaskStatus) -> None:
    if not is_valid_task_transition(from_status, to_status):
        raise TaskTransitionError(from_status, to_status)


def allowed_task_transitions(status: TaskStatus) -> frozenset[TaskStatus]:
    return _TASK_TRANSITIONS.get(status, frozenset())


def all_task_status_values() -> list[str]:
    return [member.value for member in TaskStatus]
