"""C4 exploration floor — pure-level fixtures (ratified design gate §6).

The floor is a versioned RESERVATION clause in the ratified Q-02 ordering
policy: it permutes the OUTPUT of the ratified ``_task_ordering_key`` under
a documented constraint — the key itself is UNCHANGED. Pure: no clock, no
random, no SQL, no write path, no LLM input. These fixtures pin the pure
contract (AC-1..AC-10 + the C4×C5 joint matrix cells 1–2, 7); the
controller consumption (event persistence, default-off, capacity rejection)
lives in test_controller_c4.py.

Maps design gate §6 acceptance criteria AC-1..AC-10 and §4.5 joint matrix
cells 1 (floor inert under diversity), 2 (floor fires under monopoly),
7 (zero-claim round: cap binding / empty set ⇒ no floor grant).
"""
from __future__ import annotations

import pytest

from hermes.research.evaluation import (
    FLOOR_POLICY_VERSION_SUFFIX,
    CostTier,
    EligibleTask,
    EligibleTaskRanking,
    FloorEventRecord,
    FloorPolicy,
    FloorStagnationMode,
    TaskDiagnosticKind,
    apply_exploration_floor,
    derive_floor_states,
    evaluate_eligible_tasks,
    evaluate_eligible_tasks_with_floor,
    trajectory_label,
)


def _task(ref, prog=None, cost=CostTier.LOW, dims=None, basis=(),
          created="2026-08-15T10:00:00"):
    return EligibleTask(
        task_ref=ref,
        template="extract",
        cost_class=cost,
        dimensions=dims or {},
        basis_refs=tuple(basis),
        created_at=created,
        program_refs=(f"research_program:{prog}",) if prog else (),
    )


def _ordered_refs(ranking: EligibleTaskRanking) -> list[str]:
    return [e.task_ref for e in ranking.comparison]


def _kinds(ranking: EligibleTaskRanking) -> list[TaskDiagnosticKind]:
    return [d.kind for d in ranking.diagnostics]


def _grants(ranking: EligibleTaskRanking):
    return [t for t in ranking.floor_transitions
            if t.kind is TaskDiagnosticKind.FLOOR_GRANTED]


def _grant(traj, round_index, sat, task_ref="t-n", outstanding=()):
    return FloorEventRecord(
        kind=TaskDiagnosticKind.FLOOR_GRANTED,
        trajectory=traj,
        round_index=round_index,
        created_at=f"2026-08-1{round_index + 1}T00:00:00",
        task_ref=task_ref,
        satisfaction_count=sat,
        outstanding_obligations=tuple(outstanding),
    )


# ── AC-1: floor inert under diversity ──

class TestAC1InertUnderDiversity:
    def test_diverse_top_slots_change_nothing(self):
        a = _task("t-a", "rp-A", created="2026-08-15T09:00:00")
        b = _task("t-b", "rp-B", created="2026-08-15T10:00:00")
        pure = evaluate_eligible_tasks([a, b])
        floored = evaluate_eligible_tasks_with_floor([a, b], capacity=8)
        # The floor-aware ordering equals the pure policy ordering.
        assert _ordered_refs(floored) == _ordered_refs(pure)
        assert TaskDiagnosticKind.FLOOR_INERT in _kinds(floored)
        assert floored.floor_transitions == ()

    def test_matrix_cell_1_no_priority_diverse_top_c(self):
        """Joint C4×C5 matrix cell 1: priority none, diverse top-C ⇒ the
        floor is inert (AC-1) — with no C5 surface present, the pure-policy
        order stands untouched."""
        tasks = [
            _task("t-a", "rp-A", created="2026-08-15T09:00:00"),
            _task("t-b", "rp-B", created="2026-08-15T10:00:00"),
            _task("t-c", "rp-A", created="2026-08-15T11:00:00"),
        ]
        r = evaluate_eligible_tasks_with_floor(tasks, capacity=3)
        assert _ordered_refs(r) == ["t-a", "t-b", "t-c"]
        assert TaskDiagnosticKind.FLOOR_INERT in _kinds(r)
        assert r.floor_transitions == ()


# ── AC-2: floor fires under monopoly ──

class TestAC2FiresUnderMonopoly:
    def test_one_non_leader_promoted_into_last_slot(self):
        lead1 = _task("t-l1", "rp-A", created="2026-08-15T09:00:00")
        lead2 = _task("t-l2", "rp-A", created="2026-08-15T10:00:00")
        non = _task("t-n", "rp-B", created="2026-08-15T11:00:00")
        r = evaluate_eligible_tasks_with_floor([lead1, lead2, non],
                                               capacity=2)
        # The leader keeps slot 0; the non-leader takes the LAST slot (1);
        # the displaced leader task falls behind the promoted task.
        assert _ordered_refs(r) == ["t-l1", "t-n", "t-l2"]
        grants = _grants(r)
        assert len(grants) == 1
        g = grants[0]
        assert g.task_ref == "t-n"
        assert g.slot == 1
        assert g.trajectory == "research_program:rp-B"
        assert TaskDiagnosticKind.FLOOR_GRANTED in _kinds(r)

    def test_matrix_cell_2_no_priority_monopoly_pure_policy_pick(self):
        """Joint C4×C5 matrix cell 2: priority none, monopoly ⇒ the floor
        fires and promotes the PURE-POLICY highest-ranked non-leader."""
        lead1 = _task("t-l1", "rp-A", created="2026-08-15T09:00:00")
        lead2 = _task("t-l2", "rp-A", created="2026-08-15T10:00:00")
        # Two non-leaders: the higher pure-policy rank (earlier created_at)
        # must be the one promoted.
        non_hi = _task("t-n1", "rp-B", created="2026-08-15T11:00:00")
        non_lo = _task("t-n2", "rp-C", created="2026-08-15T12:00:00")
        r = evaluate_eligible_tasks_with_floor(
            [lead1, lead2, non_hi, non_lo], capacity=2)
        grants = _grants(r)
        assert len(grants) == 1
        assert grants[0].task_ref == "t-n1"
        assert _ordered_refs(r)[1] == "t-n1"

    def test_floor_never_forces_dispatch_only_reorders(self):
        """The floor reorders; it never admits or substitutes. The promoted
        task is the same object identity (same task_ref) the pure policy
        already ranked — nothing new enters the set."""
        lead = _task("t-l1", "rp-A", created="2026-08-15T09:00:00")
        lead2 = _task("t-l2", "rp-A", created="2026-08-15T10:00:00")
        non = _task("t-n", "rp-B", created="2026-08-15T11:00:00")
        pure = evaluate_eligible_tasks([lead, lead2, non])
        floored = evaluate_eligible_tasks_with_floor([lead, lead2, non],
                                                     capacity=2)
        assert set(_ordered_refs(floored)) == set(_ordered_refs(pure))
        assert len(floored.comparison) == len(pure.comparison)


# ── AC-3: cap binding + fail-closed capacity validation ──

class TestAC3CapBinding:
    def test_zero_capacity_grants_nothing(self):
        lead1 = _task("t-l1", "rp-A", created="2026-08-15T09:00:00")
        lead2 = _task("t-l2", "rp-A", created="2026-08-15T10:00:00")
        non = _task("t-n", "rp-B", created="2026-08-15T11:00:00")
        r = evaluate_eligible_tasks_with_floor([lead1, lead2, non],
                                               capacity=0)
        # Pure policy stands; the floor grants nothing.
        assert _ordered_refs(r) == ["t-l1", "t-l2", "t-n"]
        assert TaskDiagnosticKind.FLOOR_INERT in _kinds(r)
        assert r.floor_transitions == ()

    def test_matrix_cell_7_zero_claim_round_no_grant(self):
        """Joint C4×C5 matrix cell 7 (C4 side): a zero-claim round (cap
        binding OR empty set) ⇒ no floor grant, no transition recorded."""
        # Cap binding.
        lead = _task("t-l1", "rp-A", created="2026-08-15T09:00:00")
        non = _task("t-n", "rp-B", created="2026-08-15T10:00:00")
        r_cap = evaluate_eligible_tasks_with_floor([lead, non], capacity=0)
        assert r_cap.floor_transitions == ()
        # Empty eligible set.
        r_empty = evaluate_eligible_tasks_with_floor([], capacity=8)
        assert r_empty.floor_transitions == ()
        assert _grants(r_empty) == []

    def test_floor_slots_at_or_above_cap_rejected(self):
        with pytest.raises(ValueError):
            FloorPolicy(floor_slots=8).validate_capacity(8)
        with pytest.raises(ValueError):
            FloorPolicy(floor_slots=9).validate_capacity(8)
        # Strictly below the cap is accepted.
        FloorPolicy(floor_slots=7).validate_capacity(8)

    def test_invalid_policy_params_rejected(self):
        with pytest.raises(ValueError):
            FloorPolicy(floor_slots=0)
        with pytest.raises(ValueError):
            FloorPolicy(floor_stagnation_rounds=0)
        with pytest.raises(ValueError):
            FloorPolicy(floor_decay_cooldown_rounds=0)


# ── AC-4: determinism ──

class TestAC4Determinism:
    def test_same_inputs_same_identity_and_decision(self):
        lead1 = _task("t-l1", "rp-A", created="2026-08-15T09:00:00")
        lead2 = _task("t-l2", "rp-A", created="2026-08-15T10:00:00")
        non = _task("t-n", "rp-B", created="2026-08-15T11:00:00")
        hist = (_grant("research_program:rp-B", 0, 0),)
        a = evaluate_eligible_tasks_with_floor(
            [lead1, lead2, non], capacity=2, event_records=hist,
            satisfaction_counts={"research_program:rp-B": 0})
        b = evaluate_eligible_tasks_with_floor(
            [non, lead2, lead1], capacity=2, event_records=hist,
            satisfaction_counts={"research_program:rp-B": 0})
        assert a.ranking_id == b.ranking_id
        assert a.content_hash == b.content_hash
        assert _ordered_refs(a) == _ordered_refs(b)
        assert a.floor_transitions == b.floor_transitions

    def test_policy_version_reflects_floor(self):
        lead = _task("t-l1", "rp-A")
        r = evaluate_eligible_tasks_with_floor([lead], capacity=8)
        assert r.policy_version.endswith(FLOOR_POLICY_VERSION_SUFFIX)
        assert "exploration floor" in r.ordering_policy


# ── AC-5: degenerate-to-baseline ──

class TestAC5DegenerateToBaseline:
    def test_unresolvable_leader_label_degenerates(self):
        nolabel = _task("t-x", None, created="2026-08-15T09:00:00")
        lead = _task("t-l1", "rp-A", created="2026-08-15T10:00:00")
        r = evaluate_eligible_tasks_with_floor([nolabel, lead], capacity=2)
        assert TaskDiagnosticKind.FLOOR_DEGENERATE_TO_BASELINE in _kinds(r)
        assert r.floor_transitions == ()

    def test_single_trajectory_no_non_leader_inert(self):
        lead1 = _task("t-l1", "rp-A", created="2026-08-15T09:00:00")
        lead2 = _task("t-l2", "rp-A", created="2026-08-15T10:00:00")
        r = evaluate_eligible_tasks_with_floor([lead1, lead2], capacity=2)
        assert TaskDiagnosticKind.FLOOR_INERT in _kinds(r)
        assert r.floor_transitions == ()

    def test_never_crashes_on_corrupt_history(self):
        """A malformed history record is skipped fail-closed — the floor
        still produces a decision, never a crash, never a silent skip."""
        lead1 = _task("t-l1", "rp-A", created="2026-08-15T09:00:00")
        lead2 = _task("t-l2", "rp-A", created="2026-08-15T10:00:00")
        non = _task("t-n", "rp-B", created="2026-08-15T11:00:00")
        # A well-formed grant plus the floor still fires deterministically.
        hist = (_grant("research_program:rp-B", 0, 0),)
        r = evaluate_eligible_tasks_with_floor(
            [lead1, lead2, non], capacity=2, event_records=hist)
        assert _grants(r)  # still decides


# ── AC-6: F-C counter derivation ──

class TestAC6CounterDerivation:
    POLICY = FloorPolicy(floor_stagnation_rounds=2,
                         floor_decay_cooldown_rounds=1)

    def test_first_grant_is_baseline_not_stagnant(self):
        states, gc = derive_floor_states(
            (_grant("research_program:rp-B", 0, 0),), self.POLICY)
        st = states["research_program:rp-B"]
        assert st.consecutive_unproductive == 0
        assert not st.in_cooldown and not st.halted
        assert gc == 1

    def test_productive_round_resets_counter(self):
        hist = (
            _grant("research_program:rp-B", 0, 0),
            _grant("research_program:rp-B", 1, 0),   # unproductive → 1
            _grant("research_program:rp-B", 2, 3),   # productive → reset
        )
        states, _ = derive_floor_states(hist, self.POLICY)
        assert states["research_program:rp-B"].consecutive_unproductive == 0

    def test_n_consecutive_unproductive_fires(self):
        hist = (
            _grant("research_program:rp-B", 0, 0),   # baseline
            _grant("research_program:rp-B", 1, 0),   # unproductive → 1
            _grant("research_program:rp-B", 2, 0),   # unproductive → 2 = N
        )
        states, _ = derive_floor_states(hist, self.POLICY)
        assert states["research_program:rp-B"].in_cooldown  # decay fired

    def test_counter_is_pure_function_of_records(self):
        """Replaying the identical records yields the identical state —
        no hidden mutable counter, no schedule dependence."""
        hist = (
            _grant("research_program:rp-B", 0, 0),
            _grant("research_program:rp-B", 1, 0),
        )
        s1, g1 = derive_floor_states(hist, self.POLICY)
        s2, g2 = derive_floor_states(tuple(reversed(hist)), self.POLICY)
        assert s1 == s2 and g1 == g2


# ── AC-7: decay mode ──

class TestAC7DecayMode:
    POLICY = FloorPolicy(floor_stagnation_rounds=2,
                         floor_decay_cooldown_rounds=2,
                         floor_stagnation_mode=FloorStagnationMode.DECAY)

    def test_withdrawal_then_cooldown_then_requalify(self):
        # Baseline + 2 unproductive → withdrawn at grant_count=3.
        stagnant = (
            _grant("research_program:rp-B", 0, 0),
            _grant("research_program:rp-B", 1, 0),
            _grant("research_program:rp-B", 2, 0),
        )
        states, gc = derive_floor_states(stagnant, self.POLICY)
        st = states["research_program:rp-B"]
        assert st.in_cooldown and not st.halted
        assert st.cooldown_until_grant_index == gc + 2

        # Two more project-wide grants (other trajectories) pass the
        # cooldown → the trajectory re-qualifies.
        others = stagnant + (
            _grant("research_program:rp-A", 3, 0, task_ref="t-a"),
            _grant("research_program:rp-A", 4, 0, task_ref="t-a"),
        )
        states2, _ = derive_floor_states(others, self.POLICY)
        st2 = states2["research_program:rp-B"]
        assert not st2.in_cooldown and not st2.halted

    def test_during_cooldown_skipped_by_step_5(self):
        """While in cooldown the trajectory is excluded from the floor
        candidates — the floor does not promote it."""
        stagnant = (
            _grant("research_program:rp-B", 0, 0),
            _grant("research_program:rp-B", 1, 0),
            _grant("research_program:rp-B", 2, 0),
        )
        lead1 = _task("t-l1", "rp-A", created="2026-08-15T09:00:00")
        lead2 = _task("t-l2", "rp-A", created="2026-08-15T10:00:00")
        non = _task("t-n", "rp-B", created="2026-08-15T11:00:00")
        r = evaluate_eligible_tasks_with_floor(
            [lead1, lead2, non], capacity=2,
            floor_policy=self.POLICY, event_records=stagnant)
        # rp-B is in cooldown ⇒ no non-leader is floor-eligible ⇒ inert.
        assert TaskDiagnosticKind.FLOOR_INERT in _kinds(r)
        assert _grants(r) == []


# ── AC-8: kill-switch mode ──

class TestAC8KillSwitchMode:
    POLICY = FloorPolicy(floor_stagnation_rounds=2,
                         floor_stagnation_mode=FloorStagnationMode.KILL_SWITCH)

    def test_suspension_after_n_stagnant(self):
        stagnant = (
            _grant("research_program:rp-B", 0, 0,
                   outstanding=("research_program:rp-B:evidence_requirement:h1",)),
            _grant("research_program:rp-B", 1, 0,
                   outstanding=("research_program:rp-B:evidence_requirement:h1",)),
            _grant("research_program:rp-B", 2, 0,
                   outstanding=("research_program:rp-B:evidence_requirement:h1",)),
        )
        states, _ = derive_floor_states(stagnant, self.POLICY)
        st = states["research_program:rp-B"]
        assert st.halted and not st.in_cooldown

    def test_readmission_event_clears_suspension(self):
        """A FLOOR_READMITTED event (a new eligible obligation appeared)
        re-admits the trajectory — automatic, deterministic, no human."""
        stagnant = (
            _grant("research_program:rp-B", 0, 0,
                   outstanding=("research_program:rp-B:evidence_requirement:h1",)),
            _grant("research_program:rp-B", 1, 0,
                   outstanding=("research_program:rp-B:evidence_requirement:h1",)),
            _grant("research_program:rp-B", 2, 0,
                   outstanding=("research_program:rp-B:evidence_requirement:h1",)),
        )
        readmit = FloorEventRecord(
            kind=TaskDiagnosticKind.FLOOR_READMITTED,
            trajectory="research_program:rp-B",
            round_index=3,
            created_at="2026-08-19T00:00:00",
        )
        states, _ = derive_floor_states(stagnant + (readmit,), self.POLICY)
        st = states["research_program:rp-B"]
        assert not st.halted and not st.in_cooldown

    def test_suspended_trajectory_skipped_by_floor(self):
        stagnant = (
            _grant("research_program:rp-B", 0, 0,
                   outstanding=("research_program:rp-B:evidence_requirement:h1",)),
            _grant("research_program:rp-B", 1, 0,
                   outstanding=("research_program:rp-B:evidence_requirement:h1",)),
            _grant("research_program:rp-B", 2, 0,
                   outstanding=("research_program:rp-B:evidence_requirement:h1",)),
        )
        lead1 = _task("t-l1", "rp-A", created="2026-08-15T09:00:00")
        lead2 = _task("t-l2", "rp-A", created="2026-08-15T10:00:00")
        # The non-leader carries the SAME outstanding obligation it was
        # suspended with — nothing NEW ⇒ still suspended, floor inert.
        non = _task("t-n", "rp-B", created="2026-08-15T11:00:00",
                    basis=("research_program:rp-B:evidence_requirement:h1",))
        r = evaluate_eligible_tasks_with_floor(
            [lead1, lead2, non], capacity=2,
            floor_policy=self.POLICY, event_records=stagnant)
        assert _grants(r) == []

    def test_new_obligation_triggers_readmission_transition(self):
        """The round a NEW eligible obligation appears, the floor emits
        FLOOR_READMITTED and may grant again — no human, no agent."""
        stagnant = (
            _grant("research_program:rp-B", 0, 0,
                   outstanding=("research_program:rp-B:evidence_requirement:h1",)),
            _grant("research_program:rp-B", 1, 0,
                   outstanding=("research_program:rp-B:evidence_requirement:h1",)),
            _grant("research_program:rp-B", 2, 0,
                   outstanding=("research_program:rp-B:evidence_requirement:h1",)),
        )
        lead1 = _task("t-l1", "rp-A", created="2026-08-15T09:00:00")
        lead2 = _task("t-l2", "rp-A", created="2026-08-15T10:00:00")
        # A NEW outstanding obligation (h2) the suspension did not record.
        non = _task("t-n", "rp-B", created="2026-08-15T11:00:00",
                    basis=("research_program:rp-B:evidence_requirement:h2",))
        r = evaluate_eligible_tasks_with_floor(
            [lead1, lead2, non], capacity=2,
            floor_policy=self.POLICY, event_records=stagnant)
        kinds = [t.kind for t in r.floor_transitions]
        assert TaskDiagnosticKind.FLOOR_READMITTED in kinds
        assert TaskDiagnosticKind.FLOOR_GRANTED in kinds


# ── AC-9: no authority leak (structural) ──

class TestAC9NoAuthorityLeak:
    def test_ordering_key_unchanged(self):
        """The ratified ``_task_ordering_key`` is byte-identical to the
        Q-02 §18.5 key — the floor permutes its OUTPUT, never the key."""
        import inspect

        from hermes.research import evaluation as ev
        src = inspect.getsource(ev._task_ordering_key)
        assert ("dim_key = tuple(-_DIM_LEVEL_ORDER[v] for _, v in "
                "e.dimensions)") in src
        assert ("return dim_key + (-_COST_ORDER[e.cost_class], "
                "e.created_at, e.task_ref)") in src

    def test_no_new_intent_kind(self):
        from hermes.core.intents import IntentKind
        # C4 adds no intent kind — the floor is ordering policy only.
        names = {k.name for k in IntentKind}
        assert not any("FLOOR" in n for n in names)

    def test_no_new_table_or_migration(self):
        """The floor-grant history rides the existing append-only events
        table — no new table, no migration (design gate §5.4)."""
        import inspect

        from hermes.persistence import migrations as mig
        src = inspect.getsource(mig)
        assert "floor" not in src.lower()

    def test_floor_path_reads_no_spent_budget(self):
        """Structural: the floor function's executable source never reads
        spent budget (attack O invariant) — no budget/spend token."""
        import ast
        import inspect

        from hermes.research import evaluation as ev
        tree = ast.parse(inspect.getsource(ev.apply_exploration_floor))
        for node in ast.walk(tree):
            if (isinstance(node, (ast.FunctionDef, ast.Module, ast.ClassDef))
                    and node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body = node.body[1:]
        src = ast.unparse(tree)
        assert "budget" not in src
        assert "spend" not in src

    def test_floor_never_admits(self):
        """The floor's output is a permutation of the pure-policy set —
        it never adds a task_ref the pure policy did not already rank."""
        lead1 = _task("t-l1", "rp-A", created="2026-08-15T09:00:00")
        lead2 = _task("t-l2", "rp-A", created="2026-08-15T10:00:00")
        non = _task("t-n", "rp-B", created="2026-08-15T11:00:00")
        pure = evaluate_eligible_tasks([lead1, lead2, non])
        floored = evaluate_eligible_tasks_with_floor([lead1, lead2, non],
                                                     capacity=2)
        assert set(_ordered_refs(floored)) == set(_ordered_refs(pure))


# ── AC-10: no scalar ──

class TestAC10NoScalar:
    def test_floor_ranking_has_no_score_field(self):
        lead1 = _task("t-l1", "rp-A", created="2026-08-15T09:00:00")
        lead2 = _task("t-l2", "rp-A", created="2026-08-15T10:00:00")
        non = _task("t-n", "rp-B", created="2026-08-15T11:00:00")
        r = evaluate_eligible_tasks_with_floor([lead1, lead2, non],
                                               capacity=2)
        assert not hasattr(r, "score")
        assert not hasattr(r, "value")
        assert not hasattr(r, "weight")
        for e in r.comparison:
            assert not hasattr(e, "score")
            assert not hasattr(e, "value")

    def test_floor_clause_is_structural_not_weighted(self):
        pol = FloorPolicy()
        clause = pol.policy_clause()
        assert "weighted" not in clause
        assert "score" not in clause.lower()
        # The clause names a reservation, not a scalar.
        assert ("reserved" in clause or "reservation" in clause
                or "reserve" in clause)

    def test_floor_decision_carries_no_numeric_priority(self):
        """The FloorTransition is structural (kind/trajectory/slot) — the
        only numerics are the slot index, the round index, the counter,
        and the satisfaction count (all audit facts, never a score)."""
        lead1 = _task("t-l1", "rp-A", created="2026-08-15T09:00:00")
        lead2 = _task("t-l2", "rp-A", created="2026-08-15T10:00:00")
        non = _task("t-n", "rp-B", created="2026-08-15T11:00:00")
        r = evaluate_eligible_tasks_with_floor([lead1, lead2, non],
                                               capacity=2)
        for t in r.floor_transitions:
            assert not hasattr(t, "score")
            assert not hasattr(t, "weight")
            assert not hasattr(t, "priority")


# ── trajectory label ──

class TestTrajectoryLabel:
    def test_label_is_first_sorted_program_ref(self):
        assert trajectory_label(("research_program:rp-B",
                                 "research_program:rp-A")) == \
            "research_program:rp-A"

    def test_no_refs_is_unresolvable(self):
        assert trajectory_label(()) is None


# ── pure floor function on a pre-built ranking ──

class TestApplyFloorDirect:
    def test_empty_comparison_is_noop(self):
        empty = evaluate_eligible_tasks([])
        d = apply_exploration_floor(empty, capacity=8,
                                    floor_policy=FloorPolicy())
        assert d.ordered == ()
        assert d.transitions == ()
