"""OPS-5P — the evidence transition's vocabulary, stated where the fields are.

Run 31 produced the programme's first two admitted PubMed artifacts, named one
of them in its rationale, and then lost the citation twice:

    MALFORMED_PAYLOAD: payload.from_state 'OBSERVED' is not a ratified
    evidence state (['REFUTED', 'REPLICATED', 'ROBUST', 'SUPPORTED'])

    MALFORMED_PAYLOAD: payload.evidence_artifact_ref must be
    'evidence:<artifact_id>' …; got 'source_payload:705db439…'

Both refusals enforce a vocabulary the contract never stated. ``OBSERVED`` is a
stage name, not an evidence verdict; ``source_payload:<hash>`` is the content
ref, not the artifact ref the field takes. This file pins the three rulings:

1. the contract states the ratified evidence-state values and says what they
   mean — verdicts about the claim, not positions in the research chain; the
   pair is required, must differ, and may not leave REFUTED;
2. ``evidence_artifact_ref`` is stated as the artifact-ref field (both accepted
   spellings) and says the content ref is not accepted there and has no field
   in this payload;
3. both vocabularies are read from the validator's own constants at call time,
   so adding a state or moving a ref prefix moves the rendered text — and every
   stated value is one the validator accepts.
"""

from __future__ import annotations

from typing import Any

import pytest

import hermes.research.evidence_transitions as transitions_module
import hermes.research.gateway as gateway_module
from hermes.agents.runtime.config import load_profiles
from hermes.agents.runtime.run import output_contract_for
from hermes.agents.runtime.types import MALFORMED_PAYLOAD
from hermes.composition import live_contract_rules, live_required_payload_fields
from hermes.core.intents import Intent, IntentKind
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ArtifactRepository, ProjectRepository
from hermes.research.capability_supply import (
    SOURCE_PAYLOAD_HANDLE_PREFIX,
    SOURCE_REF_SEPARATOR,
)
from hermes.research.evidence_transitions import (
    EVIDENCE_HANDLE_REF_PREFIX,
    EVIDENCE_REF_PREFIX,
    RATIFIED_EVIDENCE_STATES,
    EvidenceState,
    canonical_evidence_ref,
)
from hermes.research.gateway import (
    EVIDENCE_REF,
    GatewayRejection,
    RequiredPayloadField,
    apply_intent,
    intent_payload_required_fields,
)
from hermes.tools.models.cloud import render_system
from hermes.tools.models.router import _contract_mapping

PROJECT = "p-ops5p"
ARTIFACT = "art_ops5p"
CONTENT_HASH = "a" * 64
CLOCK = "2026-10-27T12:00:00.000000+00:00"

#: The content ref the field must not take.
CONTENT_REF = f"{SOURCE_PAYLOAD_HANDLE_PREFIX}{SOURCE_REF_SEPARATOR}{CONTENT_HASH}"

#: The content ref as the contract and the refusal spell it.
CONTENT_REF_FORM = (
    f"'{SOURCE_PAYLOAD_HANDLE_PREFIX}{SOURCE_REF_SEPARATOR}<content_hash>'")

#: The legal state values, rendered in the contract's sorted order.
STATE_VALUES = ", ".join(sorted(RATIFIED_EVIDENCE_STATES))


def _db() -> Any:
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: CLOCK).create(PROJECT, "OPS-5P")
    ArtifactRepository(conn, lambda: CLOCK).record(
        artifact_id=ARTIFACT, artifact_type="source_payload",
        content_hash=CONTENT_HASH, size_bytes=1, storage_path="seed/one",
        producer="test", project_id=PROJECT)
    return conn


def _payload() -> dict[str, Any]:
    return {
        "evidence_artifact_ref": f"{EVIDENCE_REF_PREFIX}{ARTIFACT}",
        "from_state": "SUPPORTED",
        "to_state": "ROBUST",
        "rationale": "the fetched source raises the rung",
    }


def _transition(**overrides: Any) -> Intent:
    payload = _payload()
    payload.update(overrides)
    return Intent(kind=IntentKind.EVIDENCE_TRANSITION, proposed_by="RESEARCHER",
                  project_id=PROJECT, payload=payload)


def _transition_without(key: str) -> Intent:
    payload = _payload()
    payload.pop(key)
    return Intent(kind=IntentKind.EVIDENCE_TRANSITION, proposed_by="RESEARCHER",
                  project_id=PROJECT, payload=payload)


def _mapping_with_rules(spec: Any) -> tuple[dict[str, Any], str]:
    mapping = _contract_mapping(output_contract_for(spec))
    assert mapping is not None
    available, payload_keys, payload_values, payload_shapes = (
        live_contract_rules())
    mapping["available_kinds"] = sorted(available)
    mapping["payload_keys"] = {
        kind: list(keys) for kind, keys in sorted(payload_keys.items())}
    mapping["payload_values"] = {
        kind: {key: list(values) for key, values in sets.items()}
        for kind, sets in sorted(payload_values.items())}
    mapping["payload_shapes"] = {
        kind: dict(shapes) for kind, shapes in sorted(payload_shapes.items())}
    mapping["payload_required_fields"] = live_required_payload_fields()
    return mapping, render_system(spec.name, mapping)


def _state_line(key: str, values: str = STATE_VALUES) -> str:
    return (f'For EVIDENCE_TRANSITION, the payload key "{key}" is required '
            "(there is no default); it must be one of: "
            f"{values}.")


# ═══════════════ 1. the contract states the verdict vocabulary ═══════════════


def test_the_contract_states_both_state_values_and_their_meaning() -> None:
    _, rendered = _mapping_with_rules(load_profiles()["researcher"])

    for key in ("from_state", "to_state"):
        assert _state_line(key) in rendered
    assert "evidence verdicts before and after this transition" in rendered
    assert "a verdict about the claim, not a position in the research chain" in (
        rendered)
    assert "not a stage name" in rendered
    assert "the pair must differ (an equal pair is refused)" in rendered
    assert "no transition may leave REFUTED (the terminal state)" in rendered
    # The states are required, never offered as optional with a default.
    for key in ("from_state", "to_state"):
        assert f'the payload key "{key}" is optional' not in rendered


def test_the_stated_state_values_are_the_validator_set() -> None:
    fields = intent_payload_required_fields()[IntentKind.EVIDENCE_TRANSITION]
    assert fields["from_state"].values == RATIFIED_EVIDENCE_STATES
    assert fields["to_state"].values == RATIFIED_EVIDENCE_STATES
    assert frozenset(
        member.value for member in EvidenceState) == RATIFIED_EVIDENCE_STATES
    # Every value the sentence lists, and no other, is a validator state.
    assert set(STATE_VALUES.split(", ")) == set(RATIFIED_EVIDENCE_STATES)


def test_every_required_field_is_a_legal_payload_key() -> None:
    required = intent_payload_required_fields()
    for kind, fields in required.items():
        assert set(fields) <= set(gateway_module.INTENT_PAYLOAD_KEYS[kind])
    evidence = required[IntentKind.EVIDENCE_TRANSITION]
    assert set(evidence) == {
        "evidence_artifact_ref", "from_state", "to_state"}
    # The two genuinely optional keys are not stated as required.
    assert "ratification_ref" not in evidence
    assert "rationale" not in evidence


def test_the_optional_evidence_keys_may_be_omitted() -> None:
    conn = _db()
    try:
        payload = {
            "evidence_artifact_ref": f"{EVIDENCE_REF_PREFIX}{ARTIFACT}",
            "from_state": "SUPPORTED",
            "to_state": "ROBUST",
        }
        result = apply_intent(conn, Intent(
            kind=IntentKind.EVIDENCE_TRANSITION, proposed_by="RESEARCHER",
            project_id=PROJECT, payload=payload))
        assert result.duplicate is False
    finally:
        conn.close()


def test_an_omitted_state_is_refused_and_the_message_says_required() -> None:
    conn = _db()
    try:
        for key in ("from_state", "to_state"):
            with pytest.raises(GatewayRejection) as info:
                apply_intent(conn, _transition_without(key))
            assert info.value.code == MALFORMED_PAYLOAD
            assert info.value.reason.startswith(
                f"payload.{key} is required and must be one of the ratified "
                "evidence states (")
            for state in RATIFIED_EVIDENCE_STATES:
                assert state in info.value.reason
    finally:
        conn.close()


def test_a_stage_name_refuses_and_the_message_names_the_legal_values() -> None:
    conn = _db()
    try:
        for key in ("from_state", "to_state"):
            with pytest.raises(GatewayRejection) as info:
                apply_intent(conn, _transition(**{key: "OBSERVED"}))
            assert info.value.code == MALFORMED_PAYLOAD
            assert "OBSERVED" in info.value.reason
            assert "not a ratified evidence state" in info.value.reason
            assert "not a stage name" in info.value.reason
            for state in RATIFIED_EVIDENCE_STATES:
                assert state in info.value.reason
    finally:
        conn.close()


def test_an_equal_pair_refuses_because_a_transition_must_change_state() -> None:
    conn = _db()
    try:
        with pytest.raises(GatewayRejection) as info:
            apply_intent(conn, _transition(
                from_state="SUPPORTED", to_state="SUPPORTED"))
        assert info.value.code == MALFORMED_PAYLOAD
        assert "a transition must change state" in info.value.reason
        assert "SUPPORTED" in info.value.reason
    finally:
        conn.close()


def test_refuted_is_terminal_and_may_not_be_a_from_state() -> None:
    conn = _db()
    try:
        with pytest.raises(GatewayRejection) as info:
            apply_intent(conn, _transition(
                from_state="REFUTED", to_state="SUPPORTED"))
        assert info.value.code == MALFORMED_PAYLOAD
        assert "REFUTED is the terminal evidence state" in info.value.reason
        assert "no transition may leave it" in info.value.reason
    finally:
        conn.close()


@pytest.mark.parametrize(("from_state", "to_state"), [
    ("SUPPORTED", "ROBUST"),
    ("SUPPORTED", "REPLICATED"),
    ("SUPPORTED", "REFUTED"),
    ("ROBUST", "SUPPORTED"),
    ("ROBUST", "REPLICATED"),
    ("ROBUST", "REFUTED"),
    ("REPLICATED", "SUPPORTED"),
    ("REPLICATED", "ROBUST"),
    ("REPLICATED", "REFUTED"),
])
def test_a_legal_verdict_pair_drafts(from_state: str, to_state: str) -> None:
    conn = _db()
    try:
        result = apply_intent(conn, _transition(
            from_state=from_state, to_state=to_state,
            rationale=f"{from_state} -> {to_state} on the fetched source"))
        assert result.entity_type == "evidence_transition_proposal"
        assert result.duplicate is False
    finally:
        conn.close()


# ═══════════════ 2. the contract states which ref the field takes ═══════════


def test_the_contract_states_the_artifact_ref_and_rejects_the_content_ref() -> None:
    _, rendered = _mapping_with_rules(load_profiles()["researcher"])

    assert 'the payload key "evidence_artifact_ref" is required' in rendered
    assert f"'{EVIDENCE_REF_PREFIX}<artifact_id>'" in rendered
    assert f"'{EVIDENCE_HANDLE_REF_PREFIX}<artifact_id>'" in rendered
    assert CONTENT_REF_FORM in rendered
    assert "The content ref" in rendered
    assert "is not accepted in evidence_artifact_ref" in rendered
    assert "no payload field of EVIDENCE_TRANSITION takes it" in rendered


def test_the_artifact_ref_and_the_content_ref_are_not_interchangeable() -> None:
    evidence_ref = f"{EVIDENCE_REF_PREFIX}{ARTIFACT}"
    assert canonical_evidence_ref(evidence_ref) == evidence_ref
    assert canonical_evidence_ref(
        f"{EVIDENCE_HANDLE_REF_PREFIX}{ARTIFACT}") == evidence_ref
    assert canonical_evidence_ref(CONTENT_REF) is None


def test_an_evidence_ref_drafts() -> None:
    conn = _db()
    try:
        result = apply_intent(conn, _transition())
        assert result.duplicate is False
    finally:
        conn.close()


def test_a_content_ref_refuses_and_names_which_ref_the_field_takes() -> None:
    conn = _db()
    try:
        with pytest.raises(GatewayRejection) as info:
            apply_intent(conn, _transition(evidence_artifact_ref=CONTENT_REF))
        assert info.value.code == MALFORMED_PAYLOAD
        assert f"'{EVIDENCE_REF_PREFIX}<artifact_id>'" in info.value.reason
        assert f"'{EVIDENCE_HANDLE_REF_PREFIX}<artifact_id>'" in info.value.reason
        assert CONTENT_REF_FORM in info.value.reason
        assert "the field takes the artifact ref" in info.value.reason
        assert "not the content ref" in info.value.reason
        assert "no payload field of EVIDENCE_TRANSITION takes that form" in (
            info.value.reason)
        assert CONTENT_HASH in info.value.reason
    finally:
        conn.close()


def test_a_legal_shaped_ref_with_a_ghost_id_still_refuses_evidence_ref() -> None:
    """The shape check does not replace the one artifact-row check."""
    conn = _db()
    try:
        with pytest.raises(GatewayRejection) as info:
            apply_intent(conn, _transition(
                evidence_artifact_ref=f"evidence:{CONTENT_HASH}"))
        # The shape was legal; the id is not an artifact row, so the gateway's
        # only artifact-row check refuses it.
        assert info.value.code == EVIDENCE_REF
    finally:
        conn.close()


# ═══════════════ 3. drift: the contract reads the validator's constants ══════


def test_without_the_injected_rules_the_vocabulary_is_absent() -> None:
    """A stale contract omits the clauses; they are injected, not written once."""
    spec = load_profiles()["researcher"]
    mapping = _contract_mapping(output_contract_for(spec))
    assert mapping is not None
    rendered = render_system(spec.name, mapping)
    assert "is required (there is no default)" not in rendered
    assert "not a stage name" not in rendered
    assert "no payload field of EVIDENCE_TRANSITION takes it" not in rendered


def test_adding_a_state_to_the_validator_set_moves_the_rendered_text(
        monkeypatch: Any) -> None:
    extended = RATIFIED_EVIDENCE_STATES | {"PROBE_VERDICT"}
    monkeypatch.setattr(
        transitions_module, "RATIFIED_EVIDENCE_STATES", extended)

    _, rendered = _mapping_with_rules(load_profiles()["researcher"])

    probe_values = ", ".join(sorted(extended))
    assert _state_line("from_state", probe_values) in rendered
    assert _state_line("to_state", probe_values) in rendered
    assert _state_line("from_state") not in rendered
    # The validator moved with the sentence: the new state is admitted.
    conn = _db()
    try:
        result = apply_intent(conn, _transition(
            from_state="PROBE_VERDICT", to_state="SUPPORTED"))
        assert result.duplicate is False
    finally:
        conn.close()


def test_moving_a_ref_prefix_moves_the_rendered_text(
        monkeypatch: Any) -> None:
    monkeypatch.setattr(transitions_module, "EVIDENCE_REF_PREFIX", "evref:")
    monkeypatch.setattr(
        transitions_module, "EVIDENCE_HANDLE_REF_PREFIX", "evref/")

    _, rendered = _mapping_with_rules(load_profiles()["researcher"])

    assert "'evref:<artifact_id>'" in rendered
    assert "'evref/<artifact_id>'" in rendered
    assert f"'{EVIDENCE_REF_PREFIX}<artifact_id>'" not in rendered
    assert f"'{EVIDENCE_HANDLE_REF_PREFIX}<artifact_id>'" not in rendered
    # The validator moved with the sentence: the new spelling is admitted.
    conn = _db()
    try:
        result = apply_intent(conn, _transition(
            evidence_artifact_ref=f"evref:{ARTIFACT}"))
        assert result.duplicate is False
    finally:
        conn.close()


def test_injected_rule_drift_moves_the_rendered_text(monkeypatch: Any) -> None:
    probe = {
        IntentKind.EVIDENCE_TRANSITION: {
            "from_state": RequiredPayloadField(
                values=frozenset({"PROBE_STATE"}),
                note="A probe verdict note."),
            "to_state": RequiredPayloadField(
                values=frozenset({"PROBE_STATE"}),
                note="A probe verdict note."),
            "evidence_artifact_ref": RequiredPayloadField(
                shape="a probe ref shape", note="A probe ref note."),
        },
    }
    monkeypatch.setattr(
        gateway_module, "intent_payload_required_fields", lambda: probe)

    _, rendered = _mapping_with_rules(load_profiles()["researcher"])

    assert "must be one of: PROBE_STATE" in rendered
    assert "A probe verdict note." in rendered
    assert "must be a probe ref shape" in rendered
    assert "A probe ref note." in rendered
    assert "must be one of: REFUTED, REPLICATED, ROBUST, SUPPORTED" not in (
        rendered)


class _Clock:
    def now_utc(self) -> str:
        return CLOCK

    def monotonic(self) -> float:
        return 0.0

    def sleep(self, seconds: float) -> None:
        return None


def test_the_live_rules_reach_the_router_contract() -> None:
    """The adapter's plain data crosses the router boundary intact."""
    from hermes.tools.models.router import (
        ModelPlanePolicy,
        ModelRequest,
        ModelRouter,
        OutputContract,
    )

    router = ModelRouter(
        providers=[],
        policy=ModelPlanePolicy(),
        clock=_Clock(),
        proposable_kinds=frozenset({"EVIDENCE_TRANSITION"}),
        payload_required_fields=live_required_payload_fields())
    mapping = router._contract_with_rules(ModelRequest(
        tier="s", profile="researcher", lease_generation="gen-ops5p",
        output_contract=OutputContract(
            name="probe", proposable_kinds=("EVIDENCE_TRANSITION",))))

    assert mapping is not None
    rules = mapping["payload_required_fields"]["EVIDENCE_TRANSITION"]
    assert rules["from_state"]["values"] == sorted(RATIFIED_EVIDENCE_STATES)
    assert rules["to_state"]["values"] == sorted(RATIFIED_EVIDENCE_STATES)
    assert "'evidence:<artifact_id>'" in (
        rules["evidence_artifact_ref"]["shape"])
    assert "'source_payload:<content_hash>'" in (
        rules["evidence_artifact_ref"]["note"])
