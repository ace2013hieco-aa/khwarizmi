"""OPS-5G — state the ``tool_calls`` shape, not just its keys.

Run 15's first tool-call attempt emitted ``capability_id`` and ``arguments`` at
the top level of its reply. The model knew what a call consists of and not where
it goes. The OPS-5B note said *"Item keys: arguments, capability_id,
rationale."* — key names, never the nesting.

This file pins the four falsifiers:

1. the rendered contract states the nested shape with the validator's own field
   name (``TOOL_CALLS_FIELD``) and every key of its closed set
   (``TOOL_CALL_KEYS``), and states that the flat form is refused;
2. a top-level ``capability_id``/``arguments`` reply still refuses
   ``MALFORMED_PAYLOAD`` — guidance, not enforcement;
3. a correctly nested array drafts, and the call reaches the capability port;
4. the rendered shape moves when the validator's key set moves.

The shape is prompt data. The router's whole-reply unknown-key check and the
runtime's per-item key check remain the authority, exactly as before.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from hermes.agents.runtime.config import load_profiles
from hermes.agents.runtime.run import (
    TOOL_CALL_KEYS,
    TOOL_CALLS_FIELD,
    AgentRuntime,
    output_contract_for,
)
from hermes.agents.runtime.types import (
    MALFORMED_PAYLOAD,
    RunLimits,
    TaskContext,
)
from hermes.composition import (
    build_capability_tool_notes,
    plan_capability_plane,
)
from hermes.core.intents import IntentKind
from hermes.research.capability_supply import RESEARCH_EGRESS_TOOL_SET_ID
from hermes.tools.capabilities.registry import CapabilityRegistry
from hermes.tools.capabilities.types import (
    IN_PROCESS_ENVIRONMENT,
    Capability,
    CapabilityKind,
    InputField,
    InvokeRequest,
    Observation,
    RiskLevel,
    Tool,
    ToolGrant,
    ToolSet,
)
from hermes.tools.models.cloud import render_system
from hermes.tools.models.router import ModelRefusal, _contract_mapping
from tests.test_loop4_hygiene import _Applier
from tests.test_loop4_hygiene import _profile as _runtime_profile
from tests.test_model_plane import (
    ScriptedProvider,
    _policy,
    _request,
    _response,
    _router,
)
from tests.test_model_plane import (
    _profile as _model_profile,
)

PROJECT = "p1"


# ── the composed note, from a registry declaration and the real constants ──


@dataclass
class _Supply:
    registry: CapabilityRegistry


def _registry() -> CapabilityRegistry:
    registry = CapabilityRegistry(allowlist=frozenset({"source_search"}))
    registry.register_tool(Tool(
        tool_id="source_search", summary="search a scholarly provider",
        inputs=(
            InputField(name="provider", type="string",
                       allowed_values=frozenset({"openalex", "pubmed"})),
            InputField(name="topic", type="string"),
        ),
        risk=RiskLevel.MEDIUM, network=True, sandboxed=False,
        environment=IN_PROCESS_ENVIRONMENT))
    registry.register_capability(Capability(
        capability_id="source_search", tool_id="source_search",
        kind=CapabilityKind.TOOL, risk=RiskLevel.MEDIUM))
    registry.register_tool_set(ToolSet(
        set_id=RESEARCH_EGRESS_TOOL_SET_ID,
        capability_ids=("source_search",)))
    return registry


def _plan():
    return plan_capability_plane(
        load_profiles(), supplied=("source_search",),
        risks={"source_search": "MEDIUM"})


def _note(item_keys: frozenset[str] = TOOL_CALL_KEYS) -> str:
    plan = _plan()
    return build_capability_tool_notes(
        plan, _Supply(_registry()), item_keys=item_keys)["researcher"]


# ── 1. the rendered shape ──


def test_the_rendered_contract_states_the_nested_shape() -> None:
    plan = _plan()
    note = build_capability_tool_notes(
        plan, _Supply(_registry()), item_keys=TOOL_CALL_KEYS)["researcher"]
    contract = output_contract_for(
        plan.profiles["researcher"], capability_tool_note=note)
    rendered = render_system("researcher", _contract_mapping(contract))

    shape = (
        f'"{TOOL_CALLS_FIELD}" is an array; each item is an object with '
        'exactly these keys: {"arguments": {...}, "capability_id": "...", '
        '"rationale": "..."}; the flat form — those keys at the reply\'s top '
        'level — is refused (MALFORMED_PAYLOAD).')
    assert shape in rendered
    # The old key-list phrasing cannot satisfy the falsifier: it said what a
    # call carries and not where it goes.
    assert "Item keys:" not in rendered
    assert "each item is an object" in rendered
    assert "flat form" in rendered

    # The note is generated for every profile, including the no-grant case.
    critic = build_capability_tool_notes(
        plan, _Supply(_registry()), item_keys=TOOL_CALL_KEYS)["critic"]
    assert f'"{TOOL_CALLS_FIELD}" is an array' in critic
    assert "no capability is reachable" in critic


# ── 4. the drift guard ──


def test_the_rendered_shape_moves_when_the_validator_key_set_moves() -> None:
    plan = _plan()
    supply = _Supply(_registry())
    before = build_capability_tool_notes(
        plan, supply, item_keys=TOOL_CALL_KEYS)["researcher"]
    grown = TOOL_CALL_KEYS | {"timeout_seconds"}
    after = build_capability_tool_notes(
        plan, supply, item_keys=grown)["researcher"]

    assert "timeout_seconds" not in before
    assert '"timeout_seconds": "..."' in after
    assert before != after
    # The baseline render carries exactly the validator's closed set, and the
    # grown render carries exactly the grown set. Adding a key to TOOL_CALL_KEYS
    # therefore moves the prompt, not just a test-local copy.
    assert set(re.findall(r'"(\w+)":', before)) == set(TOOL_CALL_KEYS)
    assert set(re.findall(r'"(\w+)":', after)) == set(grown)


# ── 2. the flat form still refuses ──


def test_the_flat_form_still_refuses_malformed_payload() -> None:
    """Run 15's exact failure: the right keys, one level too high.

    The contract now tells the model where the keys go; it does not accept them
    at the top level. This pin keeps the note guidance, never enforcement.
    """
    plan = _plan()
    contract = output_contract_for(
        plan.profiles["researcher"],
        capability_tool_note=_note())
    flat = {
        "rationale": "the source should be searched before it is cited",
        "capability_id": "source_search",
        "arguments": {"provider": "openalex", "topic": "crispr"},
    }
    provider = ScriptedProvider("alpha", (_model_profile(),), [
        _response(json.dumps(flat)) for _ in range(3)])
    router = _router(
        [provider],
        policy=_policy(tier_refs={"s": "alpha:m1"}, fallback_chain=()))

    result = router.invoke(_request(output_contract=contract))

    assert isinstance(result, ModelRefusal)
    assert result.code == MALFORMED_PAYLOAD
    assert "['arguments', 'capability_id']" in result.detail
    assert "runtime_proposal_v1" in result.detail


# ── 3. the nested form drafts and reaches the supply ──


class _CapturingSupply:
    """A capability port that records the request the runtime actually made."""

    def __init__(self) -> None:
        self.requests: list[InvokeRequest] = []

    def invoke(self, request: InvokeRequest) -> Observation:
        self.requests.append(request)
        return Observation(capability_id=request.capability_id, status="OK")


def test_a_nested_tool_calls_array_drafts_and_reaches_the_supply() -> None:
    plan = _plan()
    note = build_capability_tool_notes(
        plan, _Supply(_registry()), item_keys=TOOL_CALL_KEYS)["researcher"]
    # A controlled profile without a review child isolates the two facts this
    # pin owns: the draft is admitted, and the nested call reaches the port.
    profile = _runtime_profile(
        "researcher", max_ticks=1, capabilities=("source_search",),
        fields=("proposals", "tool_calls"))
    nested = {
        "kind": "INSERT_TASK",
        "rationale": "search first, then cite what the search found",
        "payload": {"goal": "find a source"},
        "tool_calls": [{
            "capability_id": "source_search",
            "arguments": {"provider": "openalex", "topic": "crispr"},
            "rationale": "gather before proposing",
        }],
    }
    provider = ScriptedProvider("alpha", (_model_profile(),), [
        _response(json.dumps(nested))])
    router = _router(
        [provider],
        policy=_policy(tier_refs={"research": "alpha:m1"},
                       fallback_chain=()))
    capabilities = _CapturingSupply()
    runtime = AgentRuntime(
        model=router,
        orchestration=_Applier(),
        capabilities=capabilities,
        profiles={"researcher": profile},
        grants={"RESEARCHER": ToolGrant(
            grant_id="grant.live.researcher", profile="RESEARCHER",
            tool_set_ids=frozenset({RESEARCH_EGRESS_TOOL_SET_ID}),
            max_risk=RiskLevel.MEDIUM.value)},
        capability_tool_notes={"researcher": note})

    result = runtime.run("researcher", TaskContext(
        task_id="t1", project_id=PROJECT, lease_generation="gen",
        limits=RunLimits(max_ticks=1, max_tool_calls=1)))

    assert result.state == "SUCCEEDED"
    assert not result.refusals
    assert len(result.proposals) == 1
    assert result.proposals[0].was_admitted()
    assert result.proposals[0].intent.kind is IntentKind.INSERT_TASK
    assert len(capabilities.requests) == 1
    call = capabilities.requests[0]
    assert call.capability_id == "source_search"
    assert call.arguments == {"provider": "openalex", "topic": "crispr"}
    assert call.rationale == "gather before proposing"
