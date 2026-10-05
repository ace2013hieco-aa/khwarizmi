"""TEXP-001 S5-unify — fixture-criteria tests (F1–F7 contracts, pilot gate).

Complements `test_generator.py` (micro-instance behavior): this file pins
the CRITERIA contracts — verdict shapes, required parameters, guardrail
wiring, full-table completeness. Directional outcomes (F2/F7 inequalities)
are deliberately NOT asserted here (anti-Goodhart rule: direction is
pilot-scale under B-calibration; asserting it at micro-scale would pin a
lucky seed, not a truth).

Run: .venv/Scripts/python.exe -m pytest experiments/texp-001/test_fixtures.py -q
Deterministic: fixed seeds; F5 uses throwaway :memory: DB only.
"""

import pytest

from fixtures import (f1_determinism, f2_null_sanity, f3_label_shuffle,
                      f4_budget, f5_isolation, f6_validator, f7_sensitivity,
                      pilot_gate)
from generator import StrataParams, generate, recall_at_k
from validator import ADMISSIBLE_SEQUENCES, validate_path

P = StrataParams(n_nodes=48, n_communities=3, bridge_len=2, noise_rate=0.02,
                 n_hubs=2, n_warp_edges=3)
SEEDS = (11, 12, 13)
K, B, S = 8, 150, 40


def inst(seed=7):
    return generate(P, seed)


def test_f1_criterion_is_byte_identity():
    v = f1_determinism(P, 7)
    assert (v.fixture_id, v.passed) == ("F1", True)
    assert isinstance(v.details, str) and v.details


def test_f2_criterion_shape_not_direction():
    v = f2_null_sanity(inst().graph, inst().truth, SEEDS, K, B, S)
    assert v.fixture_id == "F2" and isinstance(v.passed, bool)
    assert isinstance(v.details, str) and "recalls=" in v.details
    v2 = f2_null_sanity(inst().graph, inst().truth, SEEDS, K, B, S)
    assert (v.passed, v.details) == (v2.passed, v2.details)


def test_f3_criterion_moves_labels_keeps_graph():
    v = f3_label_shuffle(inst().graph, inst().truth, SEEDS, K, B, S)
    assert "labels-moved=True" in v.details
    assert "graph-unchanged=True" in v.details


def test_f4_criterion_equal_counters_and_overrun():
    v = f4_budget(inst().graph, 11, B, S)
    assert v.passed, v.details
    assert "overrun=True" in v.details


def test_f5_criterion_twin_refused():
    v = f5_isolation()
    assert v.passed, v.details


def test_f6_criterion_zero_violations_planted_kept():
    v = f6_validator(inst().graph, inst().truth)
    assert v.passed, v.details
    assert "admitted-violations=0" in v.details


def test_f6_complete_over_full_table_incl_extension():
    assert len(ADMISSIBLE_SEQUENCES) == 10  # 8 S1 + 2 S5-unify ℓ3/ℓ4
    for seq in sorted(ADMISSIBLE_SEQUENCES):
        path = [{"src": f"n{i}", "dst": f"n{i + 1}", "edge_type": t}
                for i, t in enumerate(seq)]
        result = validate_path(path)
        assert result.accepted, (seq, result.reason)


def test_f7_criterion_structure_not_direction():
    v = f7_sensitivity(inst().graph, inst().truth, SEEDS, K, B, S)
    assert v.fixture_id == "F7" and isinstance(v.passed, bool)
    assert "crippled=" in v.details and "a1=" in v.details
    v2 = f7_sensitivity(inst().graph, inst().truth, SEEDS, K, B, S)
    assert (v.passed, v.details) == (v2.passed, v2.details)


def test_pilot_gate_bar_required_and_conjunction():
    rec = {"A0": 0.1, "A1": 0.5, "A2": 0.6}
    hub = {"A0": 0.9, "A1": 0.9, "A2": 0.9}  # extreme hubs: recorded…
    ok, det = pilot_gate(rec, hub, 0.2)
    assert ok is True
    assert det["hub_fractions"] == hub  # …never gated
    assert pilot_gate(rec, hub, 0.7)[0] is False  # bar binds
    bad = {"A0": 0.5, "A1": 0.4, "A2": 0.6}
    assert pilot_gate(bad, hub, 0.1)[0] is False  # F2 binds
    with pytest.raises(TypeError):
        pilot_gate(rec, hub)  # type: ignore[call-arg]  # bar has no default


def test_recall_units_sanity():
    p = (("a", "b", "supports"),)
    assert recall_at_k([p], [p]) == 1.0
    assert recall_at_k([], [p]) == 0.0
