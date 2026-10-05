"""Lifecycle state machine (v4 §6.1) — authoritative desired-state declaration.

The lifecycle state machine is one of three orthogonal axes (v4 §6):
  - Axis 1: Lifecycle (project-level, coarse) — THIS MODULE
  - Axis 2: Operational mode (§6.2) — core/modes.py
  - Axis 3: Task status (§6.3, per-node) — core/task_status.py

Illegal transitions are impossible through the public API. There is no
public setter for lifecycle state. The only mutation path is
``request_transition()`` which validates against the v4 §6.1 table and
returns a ``(from_state, to_state)`` pair — the caller (repository) is
responsible for the atomic DB write + event append within a single
transaction (IDR-013).

v4 §6.1 adds two edges missing from v3: any non-terminal state may
transition to FAILED (unrecoverable failure) or ABANDONED (human-approved
ResearchDecision). These are abnormal-termination paths that make FAILED
and ABANDONED reachable — they were unreachable in v3, which was a defect.
"""
from __future__ import annotations

from enum import Enum


class LifecycleState(str, Enum):
    """v4 §6.1 lifecycle states (project-level)."""

    CREATED = "CREATED"
    SCOPING = "SCOPING"
    LITERATURE_REVIEW = "LITERATURE_REVIEW"
    HYPOTHESIS_FORMULATION = "HYPOTHESIS_FORMULATION"
    EXPERIMENT_DESIGN = "EXPERIMENT_DESIGN"
    DATA_ACQUISITION = "DATA_ACQUISITION"
    DATA_VALIDATION = "DATA_VALIDATION"
    IMPLEMENTATION = "IMPLEMENTATION"
    EXPERIMENTATION = "EXPERIMENTATION"
    ANALYSIS = "ANALYSIS"
    VALIDATION = "VALIDATION"
    ADVERSARIAL_REVIEW = "ADVERSARIAL_REVIEW"
    REPLICATION = "REPLICATION"
    REPORTING = "REPORTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"

    @classmethod
    def all_values(cls) -> frozenset[str]:
        return frozenset(member.value for member in cls)

    @classmethod
    def terminal_states(cls) -> frozenset["LifecycleState"]:
        return frozenset({cls.COMPLETED, cls.FAILED, cls.ABANDONED})

    @classmethod
    def initial_state(cls) -> "LifecycleState":
        return cls.CREATED


class TransitionError(Exception):
    """Raised when a lifecycle transition is not in the v4 §6.1 table."""

    def __init__(self, from_state: LifecycleState, to_state: LifecycleState, reason: str = ""):
        self.from_state = from_state
        self.to_state = to_state
        self.reason = reason
        super().__init__(f"Invalid transition: {from_state.value} → {to_state.value}" +
                         (f" — {reason}" if reason else ""))


# ── v4 §6.1 transition table ──
# Format: { from_state: { allowed_to_states } }
# Terminal states (COMPLETED, FAILED, ABANDONED) have no outgoing transitions.
#
# F-03: Every non-terminal state can transition to FAILED (unrecoverable
# failure after retries and human escalation) and ABANDONED (human-approved
# ResearchDecision; human-approved if the hypothesis was pre-registered).
# In v3 these edges were missing, making FAILED/ABANDONED unreachable.

# All non-terminal states share these abnormal-termination targets.
_ABNORMAL = frozenset({LifecycleState.FAILED, LifecycleState.ABANDONED})

_TRANSITIONS: dict[LifecycleState, frozenset[LifecycleState]] = {
    LifecycleState.CREATED: frozenset({LifecycleState.SCOPING}) | _ABNORMAL,
    LifecycleState.SCOPING: frozenset({LifecycleState.LITERATURE_REVIEW}) | _ABNORMAL,
    LifecycleState.LITERATURE_REVIEW: frozenset({LifecycleState.HYPOTHESIS_FORMULATION}) | _ABNORMAL,
    LifecycleState.HYPOTHESIS_FORMULATION: frozenset({
        LifecycleState.EXPERIMENT_DESIGN,
        LifecycleState.HYPOTHESIS_FORMULATION,  # gate rejected → revision loop
    }) | _ABNORMAL,
    LifecycleState.EXPERIMENT_DESIGN: frozenset({LifecycleState.DATA_ACQUISITION}) | _ABNORMAL,
    LifecycleState.DATA_ACQUISITION: frozenset({LifecycleState.DATA_VALIDATION}) | _ABNORMAL,
    LifecycleState.DATA_VALIDATION: frozenset({
        LifecycleState.IMPLEMENTATION,
        LifecycleState.DATA_ACQUISITION,  # data gate failed → re-acquire
    }) | _ABNORMAL,
    LifecycleState.IMPLEMENTATION: frozenset({
        LifecycleState.EXPERIMENTATION,
        LifecycleState.IMPLEMENTATION,  # pre-compute gate rejected → revision
    }) | _ABNORMAL,
    LifecycleState.EXPERIMENTATION: frozenset({LifecycleState.ANALYSIS}) | _ABNORMAL,
    LifecycleState.ANALYSIS: frozenset({LifecycleState.VALIDATION}) | _ABNORMAL,
    LifecycleState.VALIDATION: frozenset({LifecycleState.ADVERSARIAL_REVIEW}) | _ABNORMAL,
    LifecycleState.ADVERSARIAL_REVIEW: frozenset({
        LifecycleState.REPLICATION,
        LifecycleState.EXPERIMENT_DESIGN,  # fixable experiment-level flaw
        LifecycleState.HYPOTHESIS_FORMULATION,  # hypothesis refuted
    }) | _ABNORMAL,
    LifecycleState.REPLICATION: frozenset({
        LifecycleState.REPORTING,
        LifecycleState.ANALYSIS,  # replication disagrees → UNCERTAIN + routing
        LifecycleState.REPLICATION,  # pre-live gate rejected → revision
    }) | _ABNORMAL,
    LifecycleState.REPORTING: frozenset({LifecycleState.COMPLETED}) | _ABNORMAL,
    # Terminal states — no outgoing transitions
    LifecycleState.COMPLETED: frozenset(),
    LifecycleState.FAILED: frozenset(),
    LifecycleState.ABANDONED: frozenset(),
}


def is_valid_transition(from_state: LifecycleState, to_state: LifecycleState) -> bool:
    """Check whether ``(from → to)`` is in the v4 §6.1 transition table."""
    if not isinstance(to_state, LifecycleState):
        return False
    allowed = _TRANSITIONS.get(from_state, frozenset())
    return to_state in allowed


def validate_transition(from_state: LifecycleState, to_state: LifecycleState) -> None:
    """Raise ``TransitionError`` if the transition is illegal.

    This is the *only* entry point for lifecycle mutation. The repository
    layer calls this inside a ``BEGIN…COMMIT`` transaction (IDR-013).
    """
    if from_state in LifecycleState.terminal_states():
        raise TransitionError(
            from_state, to_state,
            f"{from_state.value} is terminal — no outgoing transitions"
        )
    if not is_valid_transition(from_state, to_state):
        raise TransitionError(
            from_state, to_state,
            f"permitted targets from {from_state.value}: "
            + ", ".join(s.value for s in _TRANSITIONS.get(from_state, frozenset()))
            if _TRANSITIONS.get(from_state)
            else f"{from_state.value} is terminal"
        )


def allowed_transitions(state: LifecycleState) -> frozenset[LifecycleState]:
    """Return the set of states reachable from ``state`` in one transition."""
    return _TRANSITIONS.get(state, frozenset())


def all_lifecycle_states() -> list[str]:
    """Return all lifecycle state names (for CHECK constraints and validation)."""
    return [member.value for member in LifecycleState]
