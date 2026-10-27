"""OPS-17 — the last two validator rules the contract never stated.

Run 9's CLAIM stage refused a 5811-byte proposal:

    RATIONALE: the model proposal exceeded the 4096-byte cap ...

and run 8's HYPOTHESIS stage refused a `provenance` string:

    MALFORMED_PAYLOAD: payload.provenance must be a list of strings

Both are rules the validator enforces and the contract omitted. The contract now
renders the cap from the same constant the refusal interpolates, and the full
`_require_str_list` family — `inputs`, `outputs`, `dependencies`, `provenance` —
from the gateway's own shape constant. The validator remains the authority; the
statements are guidance.

The two statements are pinned against their constants below, each has a drift
guard that moves the rendered text when the constant moves, and the two
refusals plus the happy paths are pinned unchanged.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import hermes.agents.runtime.run as run_module
import hermes.research.gateway as gateway_module
from hermes.agents.runtime.config import load_profiles
from hermes.agents.runtime.run import output_contract_for
from hermes.agents.runtime.types import (
    MALFORMED_PAYLOAD,
    MAX_PAYLOAD_BYTES,
    RATIONALE,
)
from hermes.cli import main
from hermes.composition import live_contract_rules
from hermes.core.intents import Intent, IntentKind
from hermes.persistence.database import connect
from hermes.persistence.event_validation import DEFAULT_PAYLOAD_MAX_BYTES
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ProjectRepository
from hermes.research.gateway import (
    _PAYLOAD_LIST_SHAPE,
    INTENT_PAYLOAD_SHAPES,
    GatewayRejection,
    apply_intent,
)
from hermes.tools.models.cloud import render_system
from hermes.tools.models.router import (
    MAX_PROPOSAL_BYTES,
    ModelArtifactOverflow,
    OutputContract,
    _contract_mapping,
)
from tests.test_agent_runtime import (
    ScriptedModel,
    _one_tick,
    _proposal,
    _runtime,
)
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

PROJECT = "p-ops17"
LEASE = "gen-ops17"

#: The four payload keys `_payload_to_node` passes through `_require_str_list`.
#: Named here so the map equality and the rendered-line loop use one source.
LIST_KEYS = ("dependencies", "inputs", "outputs", "provenance")


def _cap_line(cap: int = MAX_PROPOSAL_BYTES) -> str:
    return (f"The whole reply must be at most {cap} bytes — about {cap} "
            "characters of English text, and fewer if you use non-ASCII "
            "characters. A proposal over the cap is refused, and no artifact "
            "overflow port is wired today, so an over-cap body is neither "
            "preserved nor parsed.")


def _payload_cap_line(cap: int = MAX_PAYLOAD_BYTES) -> str:
    return (f"Each proposal's payload must fit the journal's {cap}-byte cap on "
            "its own; the runtime derives the identity keys after that, so "
            "leave room for them. A payload over the cap refuses that "
            "proposal.")


def _shape_line(key: str, shape: str = _PAYLOAD_LIST_SHAPE) -> str:
    return (f'For INSERT_TASK, the payload key "{key}" is optional '
            "(omitting it takes the validator's default); when supplied it "
            f"must be {shape}. Any other value is refused.")


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


def _gateway_db() -> Any:
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create(PROJECT, "OPS-17")
    return conn


def _task_payload(**extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "task_id": "task-ops17",
        "task_type": "AGENT_TASK",
        "idempotency_key": "idem-ops17",
    }
    payload.update(extra)
    return payload


# ── 1. the rendered statements, from the validator's own constants ──


def test_every_profile_states_the_cap_from_the_runtime_constant() -> None:
    profiles = load_profiles()
    assert len(profiles) == 6

    for spec in profiles.values():
        mapping, rendered = _mapping_with_rules(spec)
        assert mapping["max_proposal_bytes"] == MAX_PROPOSAL_BYTES
        assert _cap_line() in rendered
        assert _payload_cap_line() in rendered


def test_task_profiles_state_every_list_shape() -> None:
    profiles = load_profiles()
    with_task = 0
    for spec in profiles.values():
        _, rendered = _mapping_with_rules(spec)
        if "INSERT_TASK" not in spec.authority.proposable_kinds:
            for key in LIST_KEYS:
                assert f'the payload key "{key}"' not in rendered
            continue
        with_task += 1
        for key in LIST_KEYS:
            assert _shape_line(key) in rendered

    assert with_task == 4, "planner, researcher, experimenter, synthesizer"


def test_the_shape_map_is_exactly_the_str_list_family() -> None:
    # OPS-5K extended the map with `spec` and the scalar shapes; this pin stays
    # on the four keys `_require_str_list` owns, and the full map is pinned in
    # test_ops5k_ref_spelling.
    shapes = INTENT_PAYLOAD_SHAPES[IntentKind.INSERT_TASK]
    assert {key: shapes[key] for key in LIST_KEYS} == dict.fromkeys(
        LIST_KEYS, _PAYLOAD_LIST_SHAPE)


def test_the_payload_cap_is_the_journal_cap_and_the_proposal_cap_is_not() -> None:
    """OPS-5S separates two bounds this test used to pin together.

    The runtime refuses an over-cap *payload* with `MAX_PAYLOAD_BYTES`, which is
    the journal's own event-payload cap — that equality is the one that must
    hold, because a payload is written to a row. The model plane creates the
    overflow at `MAX_PROPOSAL_BYTES`, which bounds a *reply*, and a reply is
    never a row. Pinning the three equal (as this test did before OPS-5S) made
    the stated cap describe a check the model does not face.

    What must hold instead: the payload bound is still exactly the journal's,
    and the proposal bound is the one the runtime's overflow refusal states.
    """
    assert MAX_PAYLOAD_BYTES == DEFAULT_PAYLOAD_MAX_BYTES == 4096
    assert MAX_PROPOSAL_BYTES == 8192
    assert MAX_PROPOSAL_BYTES > MAX_PAYLOAD_BYTES
    assert run_module.MAX_PROPOSAL_BYTES == MAX_PROPOSAL_BYTES


def test_cap_drift_flows_into_the_contract(monkeypatch: Any) -> None:
    spec = load_profiles()["planner"]
    monkeypatch.setattr(run_module, "MAX_PROPOSAL_BYTES", 2048)

    mapping, rendered = _mapping_with_rules(spec)

    assert mapping["max_proposal_bytes"] == 2048
    assert _cap_line(2048) in rendered
    assert _cap_line() not in rendered


def test_payload_cap_drift_flows_into_the_contract(monkeypatch: Any) -> None:
    """The second bound is generated from its constant too, not hand-typed."""
    spec = load_profiles()["planner"]
    monkeypatch.setattr(run_module, "MAX_PAYLOAD_BYTES", 1024)

    mapping, rendered = _mapping_with_rules(spec)

    assert mapping["max_payload_bytes"] == 1024
    assert _payload_cap_line(1024) in rendered
    assert _payload_cap_line() not in rendered


def test_without_the_injected_cap_the_statement_is_absent() -> None:
    """A stale contract — one that stopped carrying the cap — omits the line."""
    mapping = _contract_mapping(OutputContract(name="stale"))
    assert mapping is not None
    rendered = render_system("planner", mapping)
    assert "at most" not in rendered
    assert "no artifact overflow port" not in rendered


def test_shape_drift_flows_into_the_contract(monkeypatch: Any) -> None:
    spec = load_profiles()["planner"]
    monkeypatch.setattr(gateway_module, "INTENT_PAYLOAD_SHAPES", {
        IntentKind.INSERT_TASK: {"provenance": "a probe provenance shape"}})

    _, rendered = _mapping_with_rules(spec)

    assert _shape_line("provenance", "a probe provenance shape") in rendered
    assert _shape_line("dependencies") not in rendered
    assert _PAYLOAD_LIST_SHAPE not in rendered


def test_without_the_injected_shapes_the_family_is_absent() -> None:
    spec = load_profiles()["planner"]
    mapping = _contract_mapping(output_contract_for(spec))
    assert mapping is not None
    rendered = render_system(spec.name, mapping)
    for key in LIST_KEYS:
        assert f'the payload key "{key}"' not in rendered


# ── 2. the refusals stay exactly where they were ──


def test_an_over_cap_proposal_still_refuses_with_the_same_message() -> None:
    overflow = ModelArtifactOverflow(body=b"x" * 5811, size_bytes=5811)
    result = _runtime(ScriptedModel({
        "planner": [_proposal({}, overflow=overflow)]})).run(
            "planner", _one_tick())

    assert result.refusal_codes() == (RATIONALE,)
    assert result.refusals[0].detail == (
        f"the model proposal exceeded the {MAX_PROPOSAL_BYTES}-byte cap "
        "(5811 bytes); no artifact overflow port is wired, so the body is not "
        "preserved — an overflowed body is not parsed")


def test_a_provenance_string_still_refuses_malformed_payload() -> None:
    conn = _gateway_db()
    try:
        with pytest.raises(GatewayRejection) as info:
            apply_intent(conn, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="RESEARCHER",
                project_id=PROJECT,
                payload=_task_payload(provenance="artifact:not-a-list")))
        assert info.value.code == MALFORMED_PAYLOAD
        assert info.value.reason == (
            f"payload.provenance must be {_PAYLOAD_LIST_SHAPE}")
    finally:
        conn.close()


@pytest.mark.parametrize("key", LIST_KEYS)
def test_each_stated_list_key_still_refuses_a_string(key: str) -> None:
    """Every mapped key names a check the validator actually performs."""
    conn = _gateway_db()
    try:
        with pytest.raises(GatewayRejection) as info:
            apply_intent(conn, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="RESEARCHER",
                project_id=PROJECT,
                payload=_task_payload(**{key: "artifact:not-a-list"})))
        assert info.value.code == MALFORMED_PAYLOAD
        assert info.value.reason == f"payload.{key} must be {_PAYLOAD_LIST_SHAPE}"
    finally:
        conn.close()


def test_a_provenance_list_still_admits_in_order() -> None:
    conn = _gateway_db()
    try:
        result = apply_intent(conn, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="RESEARCHER",
            project_id=PROJECT,
            payload=_task_payload(provenance=["note:one", "note:two"])))
        assert result.entity_type == "task"
        assert result.row["provenance"] == ["note:one", "note:two"]
    finally:
        conn.close()


def test_all_list_keys_still_draft() -> None:
    """The shapes are guidance: legal lists still draft."""
    result, _ = _run(
        "planner",
        {"kind": "INSERT_TASK", "rationale": "lists",
         "payload": {"spec": {"goal": "run"},
                     "inputs": ["artifact:one"],
                     "outputs": ["artifact:two"],
                     "dependencies": [],
                     "provenance": ["note:three"]}},
        child_scripts={"verifier": [
            {"rationale": "nothing to object to", "proposals": []}]})

    assert result.refusal_codes() == ()
    intent = result.proposals[0].intent
    assert intent.payload["inputs"] == ["artifact:one"]
    assert intent.payload["outputs"] == ["artifact:two"]
    assert intent.payload["dependencies"] == []
    assert intent.payload["provenance"] == ["note:three"]


# ── 3. the live composition injects both statements into the system text ──


def test_the_live_composition_renders_the_cap_and_the_list_family(
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
    assert _cap_line() in system
    for key in LIST_KEYS:
        assert _shape_line(key) in system
