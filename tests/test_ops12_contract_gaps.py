"""OPS-12 — close the contract gaps run 4 exposed.

Run 4 drafted, then refused for five rules the prompt never stated: a missing
single-form `kind`, an invented payload key, a supplied identity key, a
declared-but-unwired kind, and both proposal forms. Each statement is rendered
from the validator's own constant; each behaviour is still the validator's.
The drift guard changes the payload-key and derived-key sets and proves the
prompt follows them.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import hermes.agents.runtime.run as run_module
import hermes.research.gateway as gateway_module
from hermes.agents.runtime.config import load_profiles
from hermes.agents.runtime.run import (
    AUTHORED_KEYS,
    AgentRuntime,
    output_contract_for,
)
from hermes.agents.runtime.types import MALFORMED_PAYLOAD, RunLimits, TaskContext
from hermes.cli import main
from hermes.composition import live_contract_rules
from hermes.core.intents import Intent, IntentKind
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ProjectRepository
from hermes.research.gateway import (
    INTENT_PAYLOAD_KEYS,
    NOT_WIRED,
    WIRED_INTENT_KINDS,
    GatewayRejection,
    apply_intent,
)
from hermes.tools.models.cloud import render_system
from hermes.tools.models.router import FieldSpec, OutputContract, _contract_mapping
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
from tests.test_ops8_contract_kinds import (
    _anthropic_reply,
    _binding,
    _request,
)
from tests.test_ops8_contract_kinds import (
    _ScriptedTransport as _ModelTransport,
)
from tests.test_ops9_contract_rules import _run, _ScriptedModel

PROJECT = "p-ops12"
LEASE = "gen-ops12"


def _mapping_with_rules(spec: Any) -> tuple[dict[str, Any], str]:
    """The contract mapping plus the two gateway-derived guidance sets."""
    mapping = _contract_mapping(output_contract_for(spec))
    assert mapping is not None
    available, payload_keys = live_contract_rules()
    mapping["available_kinds"] = sorted(available)
    mapping["payload_keys"] = {
        kind: list(keys) for kind, keys in sorted(payload_keys.items())}
    return mapping, render_system(spec.name, mapping)


def _gateway_db() -> Any:
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create(PROJECT, "OPS-12")
    return conn


# ── 1. each statement appears, generated from the validator's constants ──


def test_every_shipped_profile_renders_the_five_statements() -> None:
    profiles = load_profiles()
    assert len(profiles) == 6

    for spec in profiles.values():
        mapping, rendered = _mapping_with_rules(spec)
        declared = list(spec.authority.proposable_kinds)
        available = {kind.value for kind in WIRED_INTENT_KINDS}

        # 1. the single form requires the kind field.
        assert ('If you use the single-proposal form, the top-level "kind" '
                "field is required.") in rendered
        assert ('The multi-proposal form requires "kind" on each proposal '
                "item.") in rendered
        assert ("required in the single-proposal form; omit it in the "
                "multi-proposal form") in rendered

        # 2. the payload is closed, with the keys its validator checks.
        assert "The payload object is closed." in rendered
        legal = [kind for kind in declared
                 if IntentKind(kind) in INTENT_PAYLOAD_KEYS]
        for kind in legal:
            # The model-facing list excludes the identity keys the runtime
            # derives; those are named by the next statement. The exact
            # substring is the proof the list has no extra keys.
            keys = sorted(set(INTENT_PAYLOAD_KEYS[IntentKind(kind)])
                          - AUTHORED_KEYS)
            assert f"{kind}: " + ", ".join(keys) in rendered
        if not legal:
            assert ("No legal payload keys are available because the declared "
                    "kinds are not applicable") in rendered

        # 3. identity keys are named from the runtime's validator set.
        assert "Never supply identity keys in a payload: " in rendered
        for key in sorted(AUTHORED_KEYS):
            assert key in rendered

        # 4. declared-but-unwired kinds are named from the gateway's set.
        unavailable = [kind for kind in declared if kind not in available]
        assert unavailable, "every shipped profile has an unwired declared kind"
        assert (
            "Declared but unavailable in this phase (the gateway has no "
            "validator for them): " + ", ".join(unavailable)
            + ". Choosing one is refused.") in rendered

        # 5. both forms are still stated, and the field list no longer invites
        #    two optional siblings without a rule.
        assert ("Choose exactly one proposal form: the single-proposal form "
                "(a top-level \"kind\" field) or the multi-proposal form (a "
                "\"proposals\" array). A reply carrying both is refused; "
                "exactly one is allowed.") in rendered
        assert ("use this array alone; do not also supply the single-form "
                "field") in rendered

        # The sets the contract carries are the validator's, not a second table.
        assert mapping["derived_keys"] == sorted(AUTHORED_KEYS)
        assert mapping["available_kinds"] == sorted(available)
        assert mapping["payload_keys"] == {
            kind: sorted(keys) for kind, keys in INTENT_PAYLOAD_KEYS.items()
            if kind.value in available}


# ── 2. the five refusal pins ──


def test_missing_single_form_kind_still_refuses_role() -> None:
    transport = _ModelTransport(_anthropic_reply(json.dumps({
        "rationale": "no kind here"})))
    # The live contract marks kind optional at the field level: the *form*
    # rule requires it, and the kind check is what refuses its absence (ROLE).
    contract = OutputContract(
        name="proposal",
        fields=(FieldSpec("kind", "string", required=False),
                FieldSpec("rationale", "string")),
        kind_field="kind", rationale_field="rationale",
        proposable_kinds=("INSERT_TASK",))
    outcome = _binding(transport).invoke(_request(contract))
    assert getattr(outcome, "code", "") == "ROLE"
    assert "kind None" in getattr(outcome, "detail", "")


def test_an_unknown_payload_key_still_refuses_malformed_payload() -> None:
    conn = _gateway_db()
    try:
        with pytest.raises(GatewayRejection) as info:
            apply_intent(conn, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="RESEARCHER",
                project_id=PROJECT, payload={"stage": "invented"}))
        assert info.value.code == MALFORMED_PAYLOAD
        assert "unknown payload keys: ['stage']" in info.value.reason
    finally:
        conn.close()


def test_a_supplied_identity_key_still_refuses_malformed_payload() -> None:
    result, _ = _run("planner", {
        "kind": "INSERT_TASK",
        "rationale": "forged identity",
        "payload": {"task_id": "task-forged"},
    })
    assert MALFORMED_PAYLOAD in result.refusal_codes()
    assert any("supplies the derived key(s) ['task_id']"
               in refusal.detail for refusal in result.refusals)


def test_a_declared_but_unwired_kind_refuses_not_wired() -> None:
    conn = _gateway_db()
    try:
        with pytest.raises(GatewayRejection) as info:
            apply_intent(conn, Intent(
                kind=IntentKind.BRANCH, proposed_by="RESEARCHER",
                project_id=PROJECT, payload={}))
        assert info.value.code == NOT_WIRED
        assert "BRANCH is declared but its gateway validator" in info.value.reason
    finally:
        conn.close()

    class _RejectingApplier:
        def __call__(self, intent: Intent) -> Any:
            raise GatewayRejection(
                intent.kind, NOT_WIRED,
                f"{intent.kind.value} is declared but its gateway validator "
                f"is not wired in this phase")

    runtime = AgentRuntime(
        model=_ScriptedModel({"planner": [{
            "kind": "BRANCH", "rationale": "branch", "payload": {}}]}),
        orchestration=_RejectingApplier(), profiles=load_profiles())
    result = runtime.run("planner", TaskContext(
        task_id="task-ops12", project_id=PROJECT, lease_generation=LEASE,
        limits=RunLimits(max_ticks=1)))
    # The operator-facing code is PROPOSAL, with the spine's NOT_WIRED kept.
    # The rejecting applier also refuses the planner's review-child creation,
    # so the run may record that second refusal too; the BRANCH pin is the
    # entry that carries the spine code.
    assert "PROPOSAL" in result.refusal_codes()
    assert any("(spine code NOT_WIRED)" in refusal.detail
               and "BRANCH" in refusal.detail
               for refusal in result.refusals)


def test_both_proposal_forms_still_refuse_malformed_payload() -> None:
    result, _ = _run("critic", {
        "kind": "ABANDON", "rationale": "both", "payload": {},
        "proposals": [{"kind": "ABANDON", "rationale": "both", "payload": {}}],
    })
    assert result.refusal_codes() == (MALFORMED_PAYLOAD,)
    assert "both the single-proposal and the multi-proposal form" in (
        result.refusals[0].detail)


def test_wired_kinds_match_the_dispatch() -> None:
    """The availability set is the dispatch's behavior, not a hand-typed guess."""
    conn = _gateway_db()
    try:
        for kind in IntentKind:
            if kind in IntentKind.director_only():
                proposer = "DIRECTOR"
            elif kind in IntentKind.internal_only():
                proposer = "DETERMINISTIC"
            else:
                proposer = "RESEARCHER"
            try:
                apply_intent(conn, Intent(
                    kind=kind, proposed_by=proposer, project_id=PROJECT,
                    payload={}))
            except GatewayRejection as exc:
                if kind in WIRED_INTENT_KINDS:
                    assert exc.code != NOT_WIRED, (
                        kind.value, exc.code, exc.reason)
                else:
                    assert exc.code == NOT_WIRED, (
                        kind.value, exc.code, exc.reason)
            else:
                assert kind in WIRED_INTENT_KINDS, kind.value
    finally:
        conn.close()


def test_the_happy_path_still_drafts() -> None:
    result, _ = _run("critic", {
        "kind": "ABANDON", "rationale": "legal", "payload": {}})
    assert result.refusal_codes() == ()
    assert [proposal.intent.kind.value for proposal in result.proposals] == [
        "ABANDON"]


# ── 3. the drift guard: the prompt follows the validator's sets ──


def test_payload_key_drift_flows_into_the_contract(
        monkeypatch: Any) -> None:
    spec = load_profiles()["planner"]
    mutated = dict(INTENT_PAYLOAD_KEYS)
    mutated[IntentKind.INSERT_TASK] = (
        INTENT_PAYLOAD_KEYS[IntentKind.INSERT_TASK] | {"probe_key"})
    monkeypatch.setattr(gateway_module, "INTENT_PAYLOAD_KEYS", mutated)

    available, payload_keys = live_contract_rules()
    mapping = _contract_mapping(output_contract_for(spec))
    assert mapping is not None
    mapping["available_kinds"] = sorted(available)
    mapping["payload_keys"] = {
        kind: list(keys) for kind, keys in sorted(payload_keys.items())}
    rendered = render_system(spec.name, mapping)

    assert "probe_key" in payload_keys["INSERT_TASK"]
    assert "probe_key" in rendered


def test_derived_key_drift_flows_into_the_contract(
        monkeypatch: Any) -> None:
    spec = load_profiles()["planner"]
    monkeypatch.setattr(
        run_module, "AUTHORED_KEYS",
        frozenset(set(AUTHORED_KEYS) | {"probe_key"}))
    mapping = _contract_mapping(output_contract_for(spec))
    assert mapping is not None
    rendered = render_system(spec.name, mapping)
    assert "probe_key" in rendered


def test_availability_drift_flows_into_the_contract(
        monkeypatch: Any) -> None:
    spec = load_profiles()["planner"]
    monkeypatch.setattr(
        gateway_module, "WIRED_INTENT_KINDS",
        frozenset(set(WIRED_INTENT_KINDS) - {IntentKind.INSERT_TASK}))
    available, payload_keys = live_contract_rules()
    mapping = _contract_mapping(output_contract_for(spec))
    assert mapping is not None
    mapping["available_kinds"] = sorted(available)
    mapping["payload_keys"] = {
        kind: list(keys) for kind, keys in sorted(payload_keys.items())}
    rendered = render_system(spec.name, mapping)
    assert "Declared but unavailable in this phase" in rendered
    assert "INSERT_TASK" in rendered.split(
        "Declared but unavailable in this phase", 1)[1]


# ── 4. the live composition injects the rules into the actual system text ──


def test_the_live_composition_renders_the_rules(
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
    assert "If you use the single-proposal form" in system
    assert "The payload object is closed" in system
    assert "INSERT_TASK: " in system
    assert "Never supply identity keys in a payload" in system
    assert "Declared but unavailable in this phase" in system
    assert "Choose exactly one proposal form" in system
