"""OPS-14 — the `profile` value set and the `inputs` shape.

Run 6's dominant refusal (6 of 10) was:

    MALFORMED_PAYLOAD: payload.profile must be an AgentProfile value

and run 7 added the same family one key over:

    MALFORMED_PAYLOAD: payload.inputs must be a list of strings

Both keys are legal `INSERT_TASK` payload keys; neither the values `profile`
accepts nor the shape `inputs` requires was ever stated. The contract now
renders both from the validator's own sources — the `AgentProfile` enum and the
shape constant `_require_str_list` uses in its refusal — and says whether each
key may be omitted.

The rendered clauses are guidance. The validator keeps the set and the check,
the runtime keeps its default for `profile`, and every refusal is pinned below.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import hermes.research.gateway as gateway_module
from hermes.agents.runtime.config import load_profiles
from hermes.agents.runtime.run import output_contract_for
from hermes.agents.runtime.types import MALFORMED_PAYLOAD
from hermes.cli import main
from hermes.composition import live_contract_rules
from hermes.core.intents import Intent, IntentKind
from hermes.core.node import AgentProfile, NodeType
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ProjectRepository
from hermes.research.gateway import (
    _PAYLOAD_LIST_SHAPE,
    INTENT_PAYLOAD_SHAPES,
    INTENT_PAYLOAD_VALUE_SETS,
    GatewayRejection,
    apply_intent,
)
from hermes.tools.models.cloud import render_system
from hermes.tools.models.router import _contract_mapping
from tests.test_ops1_live_cli import (
    KEY,
    _config,
    _install_transport,
    _methodology_task,
    _project,
    _proposal_reply,
)
from tests.test_ops1_live_cli import (
    _ScriptedTransport as _LiveTransport,
)
from tests.test_ops8_contract_kinds import _anthropic_reply
from tests.test_ops9_contract_rules import _run

PROJECT = "p-ops14"
LEASE = "gen-ops14"

#: The legal `profile` values, derived from the enum rather than typed here.
PROFILE_VALUES = tuple(sorted(member.value for member in AgentProfile))

#: The `inputs` shape, derived from the gateway constant rather than typed here.
INPUTS_SHAPE = _PAYLOAD_LIST_SHAPE


def _mapping_with_rules(spec: Any) -> tuple[dict[str, Any], str]:
    """The contract mapping plus the four gateway-derived guidance sets."""
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
    return mapping, render_system(spec.name, mapping)


def _profile_line(kinds: str = "INSERT_TASK") -> str:
    return (f'For {kinds}, the payload key "profile" is optional '
            "(omitting it takes the runtime's default); when supplied it "
            "must be one of: " + ", ".join(PROFILE_VALUES)
            + ". Any other value is refused.")


def _inputs_line(kinds: str = "INSERT_TASK") -> str:
    return (f'For {kinds}, the payload key "inputs" is optional '
            "(omitting it takes the validator's default); when supplied it "
            f"must be {INPUTS_SHAPE}. Any other value is refused.")


def _gateway_db() -> Any:
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create(PROJECT, "OPS-14")
    return conn


def _task_payload(**extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "task_id": "task-ops14",
        "task_type": "AGENT_TASK",
        "idempotency_key": "idem-ops14",
    }
    payload.update(extra)
    return payload


# ── 1. the rendered clauses, derived from the validator's sources ──

def test_task_profiles_render_the_profile_values_and_inputs_shape() -> None:
    profiles = load_profiles()
    assert len(profiles) == 6

    with_task = 0
    for spec in profiles.values():
        mapping, rendered = _mapping_with_rules(spec)
        if "INSERT_TASK" not in spec.authority.proposable_kinds:
            # The clauses follow the declared kinds: no task draft, no rule.
            assert 'the payload key "profile"' not in rendered
            assert 'the payload key "inputs"' not in rendered
            continue
        with_task += 1
        assert _profile_line() in rendered
        assert _inputs_line() in rendered
        # The injected sets are the validator's own — no extra, no missing.
        assert mapping["payload_values"]["INSERT_TASK"]["profile"] == list(
            PROFILE_VALUES)
        assert mapping["payload_shapes"]["INSERT_TASK"][
            "inputs"] == INPUTS_SHAPE

    assert with_task == 4, "planner, researcher, experimenter, synthesizer"


def test_the_value_set_is_the_agent_profile_enum() -> None:
    expected = {
        IntentKind.INSERT_TASK: {
            "task_type": frozenset(
                member.value for member in NodeType),
            "profile": frozenset(PROFILE_VALUES),
        },
    }
    assert expected == INTENT_PAYLOAD_VALUE_SETS
    assert len(PROFILE_VALUES) == 5
    assert set(PROFILE_VALUES) == {member.value for member in AgentProfile}


def test_the_inputs_shape_is_the_validator_constant() -> None:
    # OPS-17 completed the list family; OPS-5K added the dict/scalar shapes.
    # This pin stays focused on the four `_require_str_list` keys; the full
    # map is pinned in test_ops5k_ref_spelling.
    list_keys = ("inputs", "outputs", "dependencies", "provenance")
    shapes = INTENT_PAYLOAD_SHAPES[IntentKind.INSERT_TASK]
    assert {key: shapes[key] for key in list_keys} == dict.fromkeys(
        list_keys, INPUTS_SHAPE)
    # The check and the sentence share one source: a refused shape names it.
    conn = _gateway_db()
    try:
        with pytest.raises(GatewayRejection) as info:
            apply_intent(conn, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="RESEARCHER",
                project_id=PROJECT,
                payload=_task_payload(inputs="artifact:not-a-list")))
        assert info.value.code == MALFORMED_PAYLOAD
        assert info.value.reason == (
            "payload.inputs must be "
            f"{INTENT_PAYLOAD_SHAPES[IntentKind.INSERT_TASK]['inputs']}")
    finally:
        conn.close()


def test_without_the_injected_sets_the_clauses_are_absent() -> None:
    """A stale contract — one that stopped carrying the gateway's rules — omits both.

    This is the drift guard's other half: the clauses only appear because the
    injected mapping carries them, so they can never be sentences written once
    and left behind by a later enum or shape change.
    """
    spec = load_profiles()["planner"]
    mapping = _contract_mapping(output_contract_for(spec))
    assert mapping is not None
    rendered = render_system(spec.name, mapping)
    assert 'the payload key "profile"' not in rendered
    assert 'the payload key "inputs"' not in rendered


def test_profile_drift_flows_into_the_contract(monkeypatch: Any) -> None:
    spec = load_profiles()["planner"]
    monkeypatch.setattr(gateway_module, "INTENT_PAYLOAD_VALUE_SETS", {
        IntentKind.INSERT_TASK: {"profile": frozenset({"PROBE_PROFILE"})}})

    _, rendered = _mapping_with_rules(spec)

    assert "PROBE_PROFILE" in rendered
    assert "DIRECTOR" not in rendered
    assert ('For INSERT_TASK, the payload key "profile" is optional '
            "(omitting it takes the runtime's default); when supplied it must "
            "be one of: PROBE_PROFILE. Any other value is refused.") in rendered


def test_shape_drift_flows_into_the_contract(monkeypatch: Any) -> None:
    spec = load_profiles()["planner"]
    monkeypatch.setattr(gateway_module, "INTENT_PAYLOAD_SHAPES", {
        IntentKind.INSERT_TASK: {"inputs": "a probe shape"}})

    _, rendered = _mapping_with_rules(spec)

    assert ("must be a probe shape. Any other value is refused.") in rendered
    assert INPUTS_SHAPE not in rendered


# ── 2. the line that must not move: guidance, not enforcement ──

def test_an_unknown_profile_still_refuses_malformed_payload() -> None:
    conn = _gateway_db()
    try:
        with pytest.raises(GatewayRejection) as info:
            apply_intent(conn, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="RESEARCHER",
                project_id=PROJECT,
                payload=_task_payload(profile="ARCHITECT")))
        assert info.value.code == MALFORMED_PAYLOAD
        assert "payload.profile must be an AgentProfile value" in info.value.reason
    finally:
        conn.close()


def test_a_non_list_inputs_still_refuses_malformed_payload() -> None:
    conn = _gateway_db()
    try:
        with pytest.raises(GatewayRejection) as info:
            apply_intent(conn, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="RESEARCHER",
                project_id=PROJECT,
                payload=_task_payload(inputs="artifact:one")))
        assert info.value.code == MALFORMED_PAYLOAD
        assert "payload.inputs must be a list of strings" in info.value.reason
    finally:
        conn.close()


def test_a_non_string_input_still_refuses_malformed_payload() -> None:
    conn = _gateway_db()
    try:
        with pytest.raises(GatewayRejection) as info:
            apply_intent(conn, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="RESEARCHER",
                project_id=PROJECT,
                payload=_task_payload(inputs=["artifact:one", 3])))
        assert info.value.code == MALFORMED_PAYLOAD
        assert "payload.inputs must be a list of strings" in info.value.reason
    finally:
        conn.close()


def test_an_omitted_profile_admits_as_null() -> None:
    """The validator's own default is `None` — not the runtime's DIRECTOR.

    `_payload_to_node` parses `profile` only when it is supplied; an absent key
    admits a task with no profile. The rendered "runtime's default" describes
    the draft surface (`_derive_payload`), not a validator default.
    """
    conn = _gateway_db()
    try:
        result = apply_intent(conn, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="RESEARCHER",
            project_id=PROJECT, payload=_task_payload()))
        assert result.entity_type == "task"
        assert result.row["profile"] is None
    finally:
        conn.close()


def test_an_omitted_inputs_admits_an_empty_list() -> None:
    conn = _gateway_db()
    try:
        result = apply_intent(conn, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="RESEARCHER",
            project_id=PROJECT, payload=_task_payload()))
        assert result.row["inputs"] == []
    finally:
        conn.close()


def test_supplied_inputs_are_admitted_in_order() -> None:
    conn = _gateway_db()
    try:
        result = apply_intent(conn, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="RESEARCHER",
            project_id=PROJECT,
            payload=_task_payload(inputs=["artifact:one", "artifact:two"])))
        assert result.row["inputs"] == ["artifact:one", "artifact:two"]
    finally:
        conn.close()


def test_a_legal_profile_still_drafts() -> None:
    result, _ = _run(
        "planner",
        {"kind": "INSERT_TASK", "rationale": "a legal profile",
         "payload": {"profile": "IMPLEMENTER", "spec": {"goal": "run"}}},
        child_scripts={"verifier": [
            {"rationale": "nothing to object to", "proposals": []}]})

    assert result.refusal_codes() == ()
    assert result.proposals[0].intent.kind is IntentKind.INSERT_TASK
    assert result.proposals[0].intent.payload["profile"] == "IMPLEMENTER"


def test_omitting_the_profile_drafts_with_the_runtime_default() -> None:
    result, _ = _run(
        "planner",
        {"kind": "INSERT_TASK", "rationale": "no profile",
         "payload": {"spec": {"goal": "run"}}},
        child_scripts={"verifier": [
            {"rationale": "nothing to object to", "proposals": []}]})

    assert result.refusal_codes() == ()
    supplied = result.proposals[0].intent.payload["profile"]
    assert supplied in set(PROFILE_VALUES)
    assert supplied == "DIRECTOR", "the planner profile's agent_profile"


def test_a_legal_profile_still_admits() -> None:
    conn = _gateway_db()
    try:
        result = apply_intent(conn, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="RESEARCHER",
            project_id=PROJECT,
            payload=_task_payload(profile="ADVERSARY")))
        assert result.entity_type == "task"
        assert result.row["profile"] == "ADVERSARY"
    finally:
        conn.close()


# ── 3. the live composition injects both rules into the actual system text ──

def test_the_live_composition_renders_profile_and_inputs(
        tmp_path: Any, capsys: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    transport = _LiveTransport(_anthropic_reply(_proposal_reply()))
    _install_transport(monkeypatch, transport)
    db = _project(tmp_path, _methodology_task())
    cfg = _config(tmp_path, db, {"m": "anthropic:test-model"})

    rc = main(["--config", str(cfg), "run", "p1", "--ticks", "2"])
    capsys.readouterr()
    assert rc == 0
    assert transport.specs
    body = json.loads(transport.specs[0].body)
    system = body["system"]
    assert _profile_line() in system
    assert _inputs_line() in system
    for value in PROFILE_VALUES:
        assert value in system
