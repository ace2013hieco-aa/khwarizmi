"""TEXP-001 S1 — validator acceptance tests (F6-ready decoy classes).

Run: .venv/Scripts/python.exe -m pytest experiments/texp-001/test_validator.py -q
Deterministic: no RNG, no clock, no I/O. Covers admissible sequences,
type-violating shortcuts, near-miss paths, malformed input, and the K2
provenance seed.
"""

import pytest

from validator import (
    ADMISSIBLE_SEQUENCES,
    EDGE_ALPHABET,
    VALIDATOR_PROVENANCE,
    edge_types_of,
    validate_path,
)


def edge(t, **kw):
    return {"edge_type": t, **kw}


def test_alphabet_is_fourteen_v6_classes():
    assert len(EDGE_ALPHABET) == 14
    for required in ("supports", "contradicts", "entails", "refines",
                     "analogous_to", "tested_by", "produced_by",
                     "depends_on", "invalidates", "requires", "blocks",
                     "applies_to", "observed_in", "replicated_by"):
        assert required in EDGE_ALPHABET


@pytest.mark.parametrize("seq", sorted(ADMISSIBLE_SEQUENCES))
def test_accepts_every_table_entry(seq):
    result = validate_path([edge(t) for t in seq])
    assert result.accepted, result.reason
    assert result.reason == "OK"


def test_accepts_planted_style_bridge():
    # D2-flavored: admissible typed sequence across a bridge.
    result = validate_path([edge("supports"), edge("entails")])
    assert result.accepted


def test_rejects_unknown_edge_type():
    result = validate_path([edge("supports"), edge("foo")])
    assert not result.accepted
    assert result.reason == "UNKNOWN_EDGE_TYPE:foo"


def test_rejects_process_edge_as_bridge_type():
    # "cites" is a real Hermes process edge but NOT in the knowledge
    # alphabet — the reference validator must refuse it here.
    result = validate_path([edge("supports"), edge("cites")])
    assert not result.accepted


def test_rejects_type_violating_shortcut():
    # D2 decoy class: admissible prefix + inadmissible edge (near-miss).
    result = validate_path([edge("supports"), edge("contradicts")])
    assert not result.accepted
    assert result.reason == "INADMISSIBLE_SEQUENCE"


def test_rejects_empty_path():
    result = validate_path([])
    assert not result.accepted
    assert result.reason == "EMPTY_PATH"


def test_malformed_edge_raises_not_silent():
    with pytest.raises(TypeError):
        validate_path([{"no_type": "supports"}])
    with pytest.raises(TypeError):
        validate_path(["supports"])
    with pytest.raises(TypeError):
        validate_path("supports")


def test_deterministic_repeated_calls_agree():
    path = [edge("refines"), edge("supports")]
    assert validate_path(path) == validate_path(path)


def test_edge_types_of_projects_and_rejects_garbage():
    assert edge_types_of([edge("a"), edge("b")]) == ("a", "b")
    with pytest.raises(TypeError):
        edge_types_of([edge("a"), 42])


def test_k2_provenance_seed_present_and_honest():
    assert VALIDATOR_PROVENANCE["alphabet_source"] == "v6-§14-transcribed"
    assert VALIDATOR_PROVENANCE["sequences"] == "stipulated"
    assert VALIDATOR_PROVENANCE["gr3_proposal"] == "absent"
