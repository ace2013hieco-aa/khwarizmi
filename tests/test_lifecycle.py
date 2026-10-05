"""Tests for the lifecycle state machine (v3 §6.1).

Verifies valid transitions, invalid transitions, terminal states, and
the full §6.1 transition table.
"""
from __future__ import annotations

import pytest

from hermes.core.lifecycle import (
    LifecycleState,
    TransitionError,
    all_lifecycle_states,
    allowed_transitions,
    is_valid_transition,
    validate_transition,
)


class TestLifecycleStates:
    def test_initial_state_is_created(self):
        assert LifecycleState.initial_state() == LifecycleState.CREATED

    def test_all_17_states_present(self):
        assert len(list(LifecycleState)) == 17

    def test_state_values_are_strings(self):
        for s in LifecycleState:
            assert isinstance(s.value, str)

    def test_all_values_returns_frozenset(self):
        vals = LifecycleState.all_values()
        assert isinstance(vals, frozenset)
        assert len(vals) == 17

    def test_all_lifecycle_states_returns_list(self):
        vals = all_lifecycle_states()
        assert isinstance(vals, list)
        assert len(vals) == 17
        assert "CREATED" in vals


class TestValidTransitions:
    """Spot-check valid transition edges from the v3 §6.1 table."""

    @pytest.mark.parametrize("from_state,to_state", [
        (LifecycleState.CREATED, LifecycleState.SCOPING),
        (LifecycleState.SCOPING, LifecycleState.LITERATURE_REVIEW),
        (LifecycleState.LITERATURE_REVIEW, LifecycleState.HYPOTHESIS_FORMULATION),
        (LifecycleState.HYPOTHESIS_FORMULATION, LifecycleState.EXPERIMENT_DESIGN),
        (LifecycleState.HYPOTHESIS_FORMULATION, LifecycleState.HYPOTHESIS_FORMULATION),  # revision loop
        (LifecycleState.EXPERIMENT_DESIGN, LifecycleState.DATA_ACQUISITION),
        (LifecycleState.DATA_ACQUISITION, LifecycleState.DATA_VALIDATION),
        (LifecycleState.DATA_VALIDATION, LifecycleState.IMPLEMENTATION),
        (LifecycleState.DATA_VALIDATION, LifecycleState.DATA_ACQUISITION),  # data gate failed
        (LifecycleState.IMPLEMENTATION, LifecycleState.EXPERIMENTATION),
        (LifecycleState.IMPLEMENTATION, LifecycleState.IMPLEMENTATION),  # pre-compute gate rejected
        (LifecycleState.EXPERIMENTATION, LifecycleState.ANALYSIS),
        (LifecycleState.ANALYSIS, LifecycleState.VALIDATION),
        (LifecycleState.VALIDATION, LifecycleState.ADVERSARIAL_REVIEW),
        (LifecycleState.ADVERSARIAL_REVIEW, LifecycleState.REPLICATION),
        (LifecycleState.ADVERSARIAL_REVIEW, LifecycleState.EXPERIMENT_DESIGN),  # fixable flaw
        (LifecycleState.ADVERSARIAL_REVIEW, LifecycleState.HYPOTHESIS_FORMULATION),  # refuted
        (LifecycleState.REPLICATION, LifecycleState.REPORTING),
        (LifecycleState.REPLICATION, LifecycleState.ANALYSIS),  # replication disagrees
        (LifecycleState.REPLICATION, LifecycleState.REPLICATION),  # pre-live gate rejected
        (LifecycleState.REPORTING, LifecycleState.COMPLETED),
    ])
    def test_valid_transition(self, from_state, to_state):
        assert is_valid_transition(from_state, to_state)

    def test_validate_transition_does_not_raise_for_valid(self):
        validate_transition(LifecycleState.CREATED, LifecycleState.SCOPING)
        validate_transition(LifecycleState.REPORTING, LifecycleState.COMPLETED)

    def test_allowed_transitions_returns_frozenset(self):
        allowed = allowed_transitions(LifecycleState.CREATED)
        assert isinstance(allowed, frozenset)
        assert LifecycleState.SCOPING in allowed


class TestInvalidTransitions:
    """Illegal transitions must raise TransitionError."""

    @pytest.mark.parametrize("from_state,to_state", [
        (LifecycleState.CREATED, LifecycleState.COMPLETED),
        (LifecycleState.CREATED, LifecycleState.EXPERIMENTATION),
        (LifecycleState.SCOPING, LifecycleState.COMPLETED),
        (LifecycleState.LITERATURE_REVIEW, LifecycleState.IMPLEMENTATION),
        (LifecycleState.EXPERIMENT_DESIGN, LifecycleState.COMPLETED),
        (LifecycleState.EXPERIMENTATION, LifecycleState.CREATED),
        (LifecycleState.ANALYSIS, LifecycleState.SCOPING),
        (LifecycleState.VALIDATION, LifecycleState.COMPLETED),
        (LifecycleState.ADVERSARIAL_REVIEW, LifecycleState.COMPLETED),
        (LifecycleState.REPORTING, LifecycleState.SCOPING),
    ])
    def test_invalid_transition_raises(self, from_state, to_state):
        with pytest.raises(TransitionError):
            validate_transition(from_state, to_state)

    def test_invalid_transition_error_has_from_and_to(self):
        try:
            validate_transition(LifecycleState.CREATED, LifecycleState.COMPLETED)
            raise AssertionError("should have raised")
        except TransitionError as e:
            assert e.from_state == LifecycleState.CREATED
            assert e.to_state == LifecycleState.COMPLETED

    def test_is_valid_transition_returns_false_for_invalid(self):
        # CREATED → COMPLETED is still invalid (COMPLETED only from REPORTING)
        assert not is_valid_transition(LifecycleState.CREATED, LifecycleState.COMPLETED)
        # SCOPING → COMPLETED is still invalid
        assert not is_valid_transition(LifecycleState.SCOPING, LifecycleState.COMPLETED)


class TestTerminalStates:
    """Terminal states have no outgoing transitions."""

    @pytest.mark.parametrize("terminal", [
        LifecycleState.COMPLETED,
        LifecycleState.FAILED,
        LifecycleState.ABANDONED,
    ])
    def test_terminal_state_has_no_outgoing(self, terminal):
        assert allowed_transitions(terminal) == frozenset()

    @pytest.mark.parametrize("terminal", [
        LifecycleState.COMPLETED,
        LifecycleState.FAILED,
        LifecycleState.ABANDONED,
    ])
    def test_terminal_state_in_terminal_set(self, terminal):
        assert terminal in LifecycleState.terminal_states()

    @pytest.mark.parametrize("terminal", [
        LifecycleState.COMPLETED,
        LifecycleState.FAILED,
        LifecycleState.ABANDONED,
    ])
    def test_any_transition_from_terminal_raises(self, terminal):
        for target in [LifecycleState.SCOPING, LifecycleState.CREATED, LifecycleState.COMPLETED]:
            with pytest.raises(TransitionError):
                validate_transition(terminal, target)

    def test_non_terminal_states_not_in_terminal_set(self):
        assert LifecycleState.CREATED not in LifecycleState.terminal_states()
        assert LifecycleState.REPORTING not in LifecycleState.terminal_states()


class TestAbnormalTermination:
    """F-03: Every non-terminal state can reach FAILED and ABANDONED (v4 §6.1)."""

    NON_TERMINAL = [
        LifecycleState.CREATED,
        LifecycleState.SCOPING,
        LifecycleState.LITERATURE_REVIEW,
        LifecycleState.HYPOTHESIS_FORMULATION,
        LifecycleState.EXPERIMENT_DESIGN,
        LifecycleState.DATA_ACQUISITION,
        LifecycleState.DATA_VALIDATION,
        LifecycleState.IMPLEMENTATION,
        LifecycleState.EXPERIMENTATION,
        LifecycleState.ANALYSIS,
        LifecycleState.VALIDATION,
        LifecycleState.ADVERSARIAL_REVIEW,
        LifecycleState.REPLICATION,
        LifecycleState.REPORTING,
    ]

    @pytest.mark.parametrize("state", NON_TERMINAL)
    def test_any_non_terminal_can_reach_failed(self, state):
        """v4 §6.1: any non-terminal → FAILED (unrecoverable failure)."""
        assert is_valid_transition(state, LifecycleState.FAILED), \
            f"{state.value} should be able to transition to FAILED"

    @pytest.mark.parametrize("state", NON_TERMINAL)
    def test_any_non_terminal_can_reach_abandoned(self, state):
        """v4 §6.1: any non-terminal → ABANDONED (human-approved ResearchDecision)."""
        assert is_valid_transition(state, LifecycleState.ABANDONED), \
            f"{state.value} should be able to transition to ABANDONED"

    def test_failed_is_terminal_no_outgoing(self):
        """FAILED is terminal — no transitions out."""
        assert allowed_transitions(LifecycleState.FAILED) == frozenset()

    def test_abandoned_is_terminal_no_outgoing(self):
        """ABANDONED is terminal — no transitions out."""
        assert allowed_transitions(LifecycleState.ABANDONED) == frozenset()

    def test_validate_transition_to_failed_does_not_raise(self):
        """Representative non-terminal states can reach FAILED without error."""
        for state in [LifecycleState.CREATED, LifecycleState.EXPERIMENTATION,
                      LifecycleState.REPORTING]:
            validate_transition(state, LifecycleState.FAILED)

    def test_validate_transition_to_abandoned_does_not_raise(self):
        """Representative non-terminal states can reach ABANDONED without error."""
        for state in [LifecycleState.SCOPING, LifecycleState.ANALYSIS,
                      LifecycleState.REPLICATION]:
            validate_transition(state, LifecycleState.ABANDONED)
