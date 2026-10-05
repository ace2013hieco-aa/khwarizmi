"""Operational modes (v4 §6.2) — orthogonal to lifecycle state.

Three modes, separate from the lifecycle machine:
  ACTIVE | AWAITING_HUMAN | PAUSED

A project can be in lifecycle=IMPLEMENTATION, mode=PAUSED without
corrupting the scientific lifecycle. Modes apply only to non-terminal
lifecycle states (v4 §6.2).
"""
from __future__ import annotations

from enum import Enum


class OperationalMode(str, Enum):
    """v4 §6.2 operational modes (orthogonal to lifecycle)."""

    ACTIVE = "ACTIVE"
    AWAITING_HUMAN = "AWAITING_HUMAN"
    PAUSED = "PAUSED"

    @classmethod
    def all_values(cls) -> frozenset[str]:
        return frozenset(member.value for member in cls)


# ── v4 §6.2 mode transition table ──

_MODE_TRANSITIONS: dict[OperationalMode, frozenset[OperationalMode]] = {
    OperationalMode.ACTIVE: frozenset({
        OperationalMode.AWAITING_HUMAN,
        OperationalMode.PAUSED,
    }),
    OperationalMode.AWAITING_HUMAN: frozenset({
        OperationalMode.ACTIVE,
        OperationalMode.PAUSED,
    }),
    OperationalMode.PAUSED: frozenset({
        OperationalMode.ACTIVE,
        OperationalMode.AWAITING_HUMAN,
    }),
}


class ModeTransitionError(Exception):
    """Raised when a mode transition is not in the v4 §6.2 table."""

    def __init__(self, from_mode: OperationalMode, to_mode: OperationalMode):
        self.from_mode = from_mode
        self.to_mode = to_mode
        super().__init__(
            f"Invalid mode transition: {from_mode.value} → {to_mode.value}"
        )


def is_valid_mode_transition(from_mode: OperationalMode, to_mode: OperationalMode) -> bool:
    if not isinstance(to_mode, OperationalMode):
        return False
    return to_mode in _MODE_TRANSITIONS.get(from_mode, frozenset())


def validate_mode_transition(from_mode: OperationalMode, to_mode: OperationalMode) -> None:
    if not is_valid_mode_transition(from_mode, to_mode):
        raise ModeTransitionError(from_mode, to_mode)


def allowed_mode_transitions(mode: OperationalMode) -> frozenset[OperationalMode]:
    return _MODE_TRANSITIONS.get(mode, frozenset())


def all_mode_values() -> list[str]:
    return [member.value for member in OperationalMode]
