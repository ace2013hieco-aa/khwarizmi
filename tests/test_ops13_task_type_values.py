"""OPS-13 — the `task_type` value set, rendered from the enum the validator uses.

Run 5's one remaining contract gap: `task_type` was listed as a legal
`INSERT_TASK` payload key, but the values it accepts were never stated, so the
model supplied a plausible non-`NodeType` string and the validator refused it
(`MALFORMED_PAYLOAD`). The contract now renders the enum's own values beside the
payload-key line and says whether the key may be omitted.

The rendered sentence is guidance. The validator keeps the set, the runtime
keeps the default, and both refusals are pinned below.
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
from hermes.core.node import NodeType
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ProjectRepository
from hermes.research.gateway import (
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

PROJECT = "p-ops13"
LEASE = "gen-ops13"

#: The legal values, derived from the enum rather than typed here.
TASK_TYPE_VALUES = tuple(sorted(member.value for member in NodeType))


def _mapping_with_rules(spec: Any) -> tuple[dict[str, Any], str]:
    """The contract mapping plus the three gateway-derived guidance sets."""
    mapping = _contract_mapping(output_contract_for(spec))
    assert mapping is not None
    available, payload_keys, payload_values, _ = live_contract_rules()
    mapping["available_kinds"] = sorted(available)
    mapping["payload_keys"] = {
        kind: list(keys) for kind, keys in sorted(payload_keys.items())}
    mapping["payload_values"] = {
        kind: {key: list(values) for key, values in sets.items()}
        for kind, sets in sorted(payload_values.items())}
    return mapping, render_system(spec.name, mapping)


def _rendered_line(kinds: str = "INSERT_TASK") -> str:
    return (f'For {kinds}, the payload key "task_type" is optional '
            "(omitting it takes the runtime's default); when supplied it "
            "must be one of: " + ", ".join(TASK_TYPE_VALUES)
            + ". Any other value is refused.")


def _gateway_db() -> Any:
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create(PROJECT, "OPS-13")
    return conn


# ── 1. the rendered line, derived from the enum ──


def test_task_profiles_render_the_node_type_values() -> None:
    profiles = load_profiles()
    assert len(profiles) == 6

    with_task = 0
    for spec in profiles.values():
        mapping, rendered = _mapping_with_rules(spec)
        if "INSERT_TASK" not in spec.authority.proposable_kinds:
            # The line follows the declared kinds: no task draft, no task rule.
            assert 'the payload key "task_type"' not in rendered
            continue
        with_task += 1
        assert _rendered_line() in rendered
        # The injected set is the enum's own values — no extra, no missing.
        assert mapping["payload_values"]["INSERT_TASK"]["task_type"] == list(
            TASK_TYPE_VALUES)

    assert with_task == 4, "planner, researcher, experimenter, synthesizer"


def test_the_value_set_is_the_node_type_enum() -> None:
    # OPS-14 added `profile` to the map and owns its full equality. This pin is
    # OPS-13's claim: the `task_type` entry is the NodeType enum, nothing else.
    assert INTENT_PAYLOAD_VALUE_SETS[IntentKind.INSERT_TASK][
        "task_type"] == frozenset(TASK_TYPE_VALUES)
    assert len(TASK_TYPE_VALUES) == 5
    assert set(TASK_TYPE_VALUES) == {member.value for member in NodeType}


def test_without_the_injected_set_the_line_is_absent() -> None:
    """A stale contract — one that stopped carrying the gateway's set — omits it.

    This is the drift guard's other half: the sentence only appears because the
    injected mapping carries it, so it can never be a sentence written once and
    left behind by a later enum change.
    """
    spec = load_profiles()["planner"]
    mapping = _contract_mapping(output_contract_for(spec))
    assert mapping is not None
    rendered = render_system(spec.name, mapping)
    assert 'the payload key "task_type"' not in rendered


def test_value_set_drift_flows_into_the_contract(monkeypatch: Any) -> None:
    spec = load_profiles()["planner"]
    monkeypatch.setattr(gateway_module, "INTENT_PAYLOAD_VALUE_SETS", {
        IntentKind.INSERT_TASK: {"task_type": frozenset({"PROBE_TASK"})}})

    _, rendered = _mapping_with_rules(spec)

    assert "PROBE_TASK" in rendered
    assert "AGENT_TASK" not in rendered
    assert ("must be one of: PROBE_TASK. Any other value is refused."
            in rendered)


# ── 2. the line that must not move: guidance, not enforcement ──


def test_an_unknown_task_type_still_refuses_malformed_payload() -> None:
    conn = _gateway_db()
    try:
        with pytest.raises(GatewayRejection) as info:
            apply_intent(conn, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="RESEARCHER",
                project_id=PROJECT,
                payload={"task_id": "task-ops13", "task_type": "RESEARCHER",
                         "idempotency_key": "idem-ops13"}))
        assert info.value.code == MALFORMED_PAYLOAD
        assert "payload.task_type must be a NodeType value" in info.value.reason
    finally:
        conn.close()


def test_the_validator_requires_the_key_a_draft_may_omit() -> None:
    """The rendered "optional" is the runtime's default, not a validator relaxation.

    `_payload_to_node` reads `task_type` through `_require_str` before the parse:
    a payload that reaches the gateway without it refuses. The contract can say
    "optional" only because `AgentRuntime._derive_payload` supplies the default
    first — pinned by the draft test below.
    """
    conn = _gateway_db()
    try:
        with pytest.raises(GatewayRejection) as info:
            apply_intent(conn, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="RESEARCHER",
                project_id=PROJECT,
                payload={"task_id": "task-ops13",
                         "idempotency_key": "idem-ops13"}))
        assert info.value.code == MALFORMED_PAYLOAD
        assert "payload.task_type must be a non-empty string" in info.value.reason
    finally:
        conn.close()


def test_a_legal_node_type_still_drafts() -> None:
    result, _ = _run(
        "planner",
        {"kind": "INSERT_TASK", "rationale": "a tool task",
         "payload": {"task_type": "TOOL_TASK", "spec": {"goal": "run"}}},
        child_scripts={"verifier": [
            {"rationale": "nothing to object to", "proposals": []}]})

    assert result.refusal_codes() == ()
    proposal = result.proposals[0]
    assert proposal.intent.kind is IntentKind.INSERT_TASK
    assert proposal.intent.payload["task_type"] == "TOOL_TASK"


def test_omitting_the_key_drafts_with_the_runtime_default() -> None:
    result, _ = _run(
        "planner",
        {"kind": "INSERT_TASK", "rationale": "no task type",
         "payload": {"spec": {"goal": "run"}}},
        child_scripts={"verifier": [
            {"rationale": "nothing to object to", "proposals": []}]})

    assert result.refusal_codes() == ()
    supplied = result.proposals[0].intent.payload["task_type"]
    assert supplied in set(TASK_TYPE_VALUES)
    assert supplied == "AGENT_TASK"


def test_a_legal_node_type_still_admits() -> None:
    conn = _gateway_db()
    try:
        result = apply_intent(conn, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="RESEARCHER",
            project_id=PROJECT,
            payload={"task_id": "task-ops13-admitted",
                     "task_type": "GATE",
                     "idempotency_key": "idem-ops13"}))
        assert result.entity_type == "task"
        assert result.row["task_type"] == "GATE"
    finally:
        conn.close()


# ── 3. the live composition injects the set into the actual system text ──


def test_the_live_composition_renders_the_value_set(
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
    assert _rendered_line() in system
    for value in TASK_TYPE_VALUES:
        assert value in system
