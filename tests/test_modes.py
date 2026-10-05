"""Tests for operational modes (v3 §6.2) — orthogonal to lifecycle state."""
from __future__ import annotations

import pytest

from hermes.core.modes import (
    ModeTransitionError,
    OperationalMode,
    all_mode_values,
    allowed_mode_transitions,
    is_valid_mode_transition,
    validate_mode_transition,
)


class TestOperationalModes:
    def test_three_modes(self):
        assert len(list(OperationalMode)) == 3

    def test_mode_values(self):
        assert OperationalMode.ACTIVE.value == "ACTIVE"
        assert OperationalMode.PAUSED.value == "PAUSED"
        assert OperationalMode.AWAITING_HUMAN.value == "AWAITING_HUMAN"

    def test_all_mode_values(self):
        vals = all_mode_values()
        assert set(vals) == {"ACTIVE", "PAUSED", "AWAITING_HUMAN"}


class TestValidModeTransitions:
    @pytest.mark.parametrize("from_mode,to_mode", [
        (OperationalMode.ACTIVE, OperationalMode.PAUSED),
        (OperationalMode.ACTIVE, OperationalMode.AWAITING_HUMAN),
        (OperationalMode.PAUSED, OperationalMode.ACTIVE),
        (OperationalMode.PAUSED, OperationalMode.AWAITING_HUMAN),
        (OperationalMode.AWAITING_HUMAN, OperationalMode.ACTIVE),
        (OperationalMode.AWAITING_HUMAN, OperationalMode.PAUSED),
    ])
    def test_valid_mode_transition(self, from_mode, to_mode):
        assert is_valid_mode_transition(from_mode, to_mode)
        validate_mode_transition(from_mode, to_mode)  # should not raise

    def test_all_modes_connect_to_all_others(self):
        """v3 §6.2: every mode can transition to every other mode."""
        for from_m in OperationalMode:
            allowed = allowed_mode_transitions(from_m)
            assert len(allowed) == 2  # each mode can go to the other two


class TestInvalidModeTransitions:
    def test_same_mode_is_invalid(self):
        assert not is_valid_mode_transition(OperationalMode.ACTIVE, OperationalMode.ACTIVE)
        assert not is_valid_mode_transition(OperationalMode.PAUSED, OperationalMode.PAUSED)

    def test_invalid_transition_raises(self):
        with pytest.raises(ModeTransitionError):
            validate_mode_transition(OperationalMode.ACTIVE, OperationalMode.ACTIVE)

    def test_error_has_from_and_to(self):
        try:
            validate_mode_transition(OperationalMode.ACTIVE, OperationalMode.ACTIVE)
            raise AssertionError()
        except ModeTransitionError as e:
            assert e.from_mode == OperationalMode.ACTIVE
            assert e.to_mode == OperationalMode.ACTIVE
