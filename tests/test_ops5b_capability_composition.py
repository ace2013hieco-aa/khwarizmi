"""OPS-5B — the live capability plane and its artifact supply chain.

Phase-2 falsifiers, in the order the charter states them:

1. a live-shaped run with a scripted ``tool_calls`` reply executes the tool and
   leaves an ``artifacts`` row that ``EVIDENCE_REF`` accepts;
2. a declared-but-unsupplied capability is withheld, named and journaled, and
   the run proceeds;
3. M2 is numeric, including a measured ``0.000``;
4. the capability line states the environment and the withheld set;
5. an out-of-allowlist host refuses before a dial;
6. the model cannot influence artifact content/identity/type/project/destination;
7. drain-only stays byte-identical;
8. the registry-generated prompt schema drifts with the registry.

Every provider interaction is scripted at the inner HTTP edge; no test here
contacts the network.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import hermes.tools.models.cloud as cloud_module
from hermes.agents.runtime.config import load_profiles
from hermes.agents.runtime.run import (
    TOOL_CALL_KEYS,
    AgentRuntime,
    output_contract_for,
)
from hermes.agents.runtime.supervisor import Supervisor
from hermes.agents.runtime.types import RunLimits, TaskContext
from hermes.composition import (
    CloudModelSpec,
    build_capability_tool_notes,
    build_live_composition,
    plan_capability_plane,
)
from hermes.config import HermesConfig, load_config
from hermes.core.events import EventType
from hermes.eval.live_vector import LiveVector
from hermes.eval.loop_observations import (
    RecordingCapabilityPort,
    RecordingModelPort,
)
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import EventRepository, ProjectRepository
from hermes.research.capability_supply import (
    FALSIFICATION_CAPABILITY_IDS,
    FALSIFICATION_TOOL_SET_ID,
    RESEARCH_CAPABILITY_IDS,
    RESEARCH_EGRESS_TOOL_SET_ID,
    SUPPLIED_CAPABILITY_IDS,
)
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
    ToolSet,
)
from hermes.tools.models.cloud import render_system
from hermes.tools.models.router import ModelProposal, ModelRefusal
from hermes.tools.providers.base import RequestSpec, TransportResponse

KEY = "sk-test-0123456789abcdefghijklmnop"
ENV = {"ANTHROPIC_API_KEY": KEY}
PROJECT = "p1"
CLOCK = "2026-10-25T12:00:00+00:00"


class _NullTransport:
    """A model transport that must never be dialed by these tests."""

    def request(self, spec: RequestSpec) -> TransportResponse:
        raise AssertionError("the test composition must not dial the model")


class _NoPin:
    """The model host pin without DNS: the scripted transport is the edge."""

    def __init__(self, inner: Any, *, host: str, resolve: Any = None) -> None:
        self._inner = inner

    def request(self, spec: RequestSpec) -> TransportResponse:
        return self._inner.request(spec)


def _config(tmp_path: Path, db: Path) -> Path:
    path = tmp_path / "hermes.toml"
    path.write_text(
        f'[sqlite]\ndatabase_path = "{db.as_posix()}"\n'
        f'[artifacts]\nartifact_root = "{(tmp_path / "store").as_posix()}"\n'
        '[model_tiers]\nm = "anthropic:test-model"\n',
        encoding="utf-8")
    return path


def _spec() -> CloudModelSpec:
    return CloudModelSpec(
        provider_id="anthropic", dialect="anthropic",
        model_id="test-model", api_key_env="ANTHROPIC_API_KEY")


@pytest.fixture
def live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A composed live run over a temp DB, with a model transport that never runs."""
    monkeypatch.setattr(cloud_module, "HostPinnedTransport", _NoPin)
    db = tmp_path / "hermes.db"
    conn = connect(str(db))
    migrate_to_latest(conn)
    ProjectRepository(conn).create(PROJECT, "OPS-5B")
    cfg: HermesConfig = load_config(_config(tmp_path, db))
    composed = build_live_composition(
        cfg, conn, project_id=PROJECT, specs=(_spec(),), environ=ENV,
        transport=_NullTransport())
    yield conn, composed
    conn.close()


# ── the capability plan ──


#: Every supplied capability's declared risk. A grant cannot be derived
#: without one, so the plan refuses rather than invent a ceiling.
RISKS = {
    "source_fetch": "MEDIUM", "source_search": "MEDIUM",
    "evidence_inspect": "LOW", "contradiction_scan": "LOW",
    "statistic_check": "LOW",
}


def test_plan_keeps_every_supplied_declaration_and_withholds_the_rest() -> None:
    profiles = load_profiles()
    plan = plan_capability_plane(
        profiles, supplied=SUPPLIED_CAPABILITY_IDS, risks=RISKS,
        tool_sets=(
            ToolSet(RESEARCH_EGRESS_TOOL_SET_ID, RESEARCH_CAPABILITY_IDS),
            ToolSet(FALSIFICATION_TOOL_SET_ID, FALSIFICATION_CAPABILITY_IDS)))
    assert plan.profiles["researcher"].tools == (
        "source_search", "source_fetch")
    assert plan.profiles["researcher"].model_policy.allows_tool_calls is True
    # OPS-5Z4: the critic and verifier declared falsifiers that are now
    # supplied, so their composed tools are kept rather than emptied.
    assert plan.profiles["critic"].tools == (
        "evidence_inspect", "contradiction_scan")
    assert plan.profiles["verifier"].tools == (
        "evidence_inspect", "statistic_check")
    assert plan.profiles["planner"].tools == ()
    # profile data is not edited: only the composed copy is narrowed
    assert plan.profiles["critic"].model_policy.allows_tool_calls is True
    assert profiles["critic"].tools == (
        "evidence_inspect", "contradiction_scan")
    assert set(plan.grants) == {"ADVERSARY", "RESEARCHER"}
    grant = plan.grants["RESEARCHER"]
    assert grant.profile == "RESEARCHER"
    assert grant.tool_set_ids == frozenset({RESEARCH_EGRESS_TOOL_SET_ID})
    assert grant.max_risk == "MEDIUM"
    adversary = plan.grants["ADVERSARY"]
    assert adversary.tool_set_ids == frozenset({FALSIFICATION_TOOL_SET_ID})
    assert adversary.max_risk == "LOW"
    assert len(plan.withheld) == 6
    assert {item.capability_id for item in plan.withheld} == {
        "artifact_store", "experiment_execute", "graph_read",
        "provenance_read"}
    assert all(item.capability_id not in SUPPLIED_CAPABILITY_IDS
               for item in plan.withheld)
    assert plan.withheld == tuple(sorted(
        plan.withheld,
        key=lambda item: (item.agent_profile, item.profile,
                          item.capability_id)))


def test_a_mixed_profile_keeps_its_supplied_subset_and_grants() -> None:
    profiles = load_profiles()
    mixed = replace(
        profiles["researcher"], name="mixed",
        tools=("source_search", "graph_read"))
    plan = plan_capability_plane(
        {**profiles, "mixed": mixed}, supplied=SUPPLIED_CAPABILITY_IDS,
        risks=RISKS)
    assert plan.profiles["mixed"].tools == ("source_search",)
    assert "mixed/graph_read" in plan.capability_line
    assert plan.grants["RESEARCHER"].profile == "RESEARCHER"


def test_a_zero_supplied_profile_gets_no_grant_and_keeps_its_declaration() -> None:
    plan = plan_capability_plane(
        load_profiles(), supplied=SUPPLIED_CAPABILITY_IDS, risks=RISKS)
    assert "DIRECTOR" not in plan.grants
    assert plan.profiles["planner"].tools == ()
    assert set(plan.grants) == {"ADVERSARY", "RESEARCHER"}
    assert plan.profiles["critic"].model_policy.structured_fields == (
        "proposals", "tool_calls")


def test_the_capability_line_names_environment_and_withheld_set() -> None:
    plan = plan_capability_plane(
        load_profiles(), supplied=SUPPLIED_CAPABILITY_IDS, risks=RISKS)
    line = plan.capability_line
    assert "in-process (no sandbox)" in line
    assert "source_fetch" in line and "source_search" in line
    assert "evidence_inspect" in line and "statistic_check" in line
    assert "planner/graph_read" in line
    assert "granted 2 profile(s) (ADVERSARY, RESEARCHER)" in line
    assert "token" not in line.lower()
    assert "dollar" not in line.lower()
    assert "budget" not in line.lower()


class _SupplyWith:
    def __init__(self, registry: CapabilityRegistry) -> None:
        self.registry = registry


def _schema_registry(summary: str) -> CapabilityRegistry:
    registry = CapabilityRegistry(allowlist=frozenset({"source_search"}))
    registry.register_tool(Tool(
        tool_id="source_search", summary=summary,
        inputs=(
            InputField(name="provider", type="string",
                       allowed_values=frozenset({"openalex", "pubmed"})),
            InputField(name="topic", type="string", required=False),
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


def test_the_tool_calls_schema_is_generated_from_the_registry_and_drifts() -> None:
    plan = plan_capability_plane(
        load_profiles(), supplied=("source_search",),
        risks={"source_search": "MEDIUM"})

    first = build_capability_tool_notes(
        plan, _SupplyWith(_schema_registry("FIRST REGISTRY SUMMARY")),
        item_keys=TOOL_CALL_KEYS)["researcher"]
    second = build_capability_tool_notes(
        plan, _SupplyWith(_schema_registry("SECOND REGISTRY SUMMARY")),
        item_keys=TOOL_CALL_KEYS)["researcher"]
    assert "FIRST REGISTRY SUMMARY" in first
    assert "SECOND REGISTRY SUMMARY" not in first
    assert "SECOND REGISTRY SUMMARY" in second
    assert first != second
    # The withheld source_fetch is not advertised; the schema came from the
    # registry declaration, not from a hand-typed list.
    assert "source_search" in first
    assert "source_fetch" not in first
    assert "provider: string, one of" in first
    assert "topic?: string" in first


def test_the_tool_calls_note_states_the_handle_forms_and_citing_rules() -> None:
    plan = plan_capability_plane(
        load_profiles(), supplied=("source_search",),
        risks={"source_search": "MEDIUM"})
    note = build_capability_tool_notes(
        plan, _SupplyWith(_schema_registry("SUMMARY")),
        item_keys=TOOL_CALL_KEYS)["researcher"]
    assert "evidence/<artifact_id>" in note
    assert "source_payload/<content_hash>" in note
    assert "evidence:<artifact_id>" in note
    assert "source_payload:<content_hash>" in note
    assert "<artifact_type>:<artifact_id>" in note
    # OPS-5K: the note says the handle spelling is accepted and normalised, so
    # the model need not translate the separator by hand.
    assert "is accepted and normalized to the same ref" in note
    assert "later tick" in note
    # A profile with no grant gets the empty-reach statement, not a legal id.
    planner = build_capability_tool_notes(
        plan, _SupplyWith(_schema_registry("SUMMARY")),
        item_keys=TOOL_CALL_KEYS)["planner"]
    assert "no capability is reachable" in planner
    assert "refused (ROLE)" in planner
    assert "source_search" not in planner


def test_the_contract_note_is_rendered_and_reaches_the_model_request() -> None:
    plan = plan_capability_plane(
        load_profiles(), supplied=("source_search",),
        risks={"source_search": "MEDIUM"})
    note = build_capability_tool_notes(
        plan, _SupplyWith(_schema_registry("SUMMARY")),
        item_keys=TOOL_CALL_KEYS)["researcher"]
    contract = output_contract_for(
        plan.profiles["researcher"], capability_tool_note=note)
    assert ("tool_calls", note) in contract.field_notes
    rendered = render_system("researcher", {
        "fields": [{"name": "tool_calls", "type": "array",
                    "required": False}],
        "field_notes": dict(contract.field_notes),
    })
    assert note in rendered
    # The note is optional: a caller that does not wire capabilities keeps
    # the pre-5B contract shape.
    plain = output_contract_for(plan.profiles["researcher"])
    assert all(field != "tool_calls" for field, _ in plain.field_notes)


def test_the_live_composition_journals_one_content_free_plane_event(live) -> None:
    conn, composed = live
    assert composed.supplied == tuple(sorted(SUPPLIED_CAPABILITY_IDS))
    assert composed.granted == ("ADVERSARY", "RESEARCHER")
    assert len(composed.withheld) == 6
    rows = [row for row in EventRepository(conn).list_for_project(PROJECT)
            if row["event_type"] == EventType.CAPABILITY_PLANE_COMPOSED.value]
    assert len(rows) == 1
    row = rows[0]
    assert row["caused_by"] == "composition"
    payload = json.loads(row["payload_json"])
    assert payload["environment"] == "in-process (no sandbox)"
    assert payload["supplied"] == list(composed.supplied)
    assert payload["granted"] == ["ADVERSARY", "RESEARCHER"]
    assert len(payload["withheld"]) == 6
    assert all(set(item) == {"profile", "agent_profile", "capability_id"}
               for item in payload["withheld"])
    serialized = row["payload_json"]
    assert "http" not in serialized
    assert "url" not in serialized.lower()


# ── the model request and the runtime gates ──


class _CaptureRefusal:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def invoke(self, request: Any) -> ModelRefusal:
        self.requests.append(request)
        return ModelRefusal(code="MALFORMED_PAYLOAD", detail="capture")


def test_the_model_request_advertises_no_native_tools() -> None:
    model = _CaptureRefusal()
    runtime = AgentRuntime(
        model=model, orchestration=lambda intent: None,
        profiles=load_profiles(),
        capability_tool_notes={"researcher": "LEGAL-NOTE"})
    runtime.run("researcher", TaskContext(
        task_id="t1", project_id=PROJECT, lease_generation="gen"))
    assert model.requests
    assert model.requests[0].tools == ()
    contract = model.requests[0].output_contract
    assert contract is not None
    assert ("tool_calls", "LEGAL-NOTE") in contract.field_notes


class _CapturePort:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def invoke(self, request: Any) -> Any:
        self.calls.append(request)
        raise AssertionError("a gated-out tool must never reach the port")


class _OneToolReply:
    def __init__(self, capability_id: str) -> None:
        self._capability_id = capability_id

    def invoke(self, request: Any) -> ModelProposal:
        return ModelProposal(
            provider_id="script", model_id="script", tier="m",
            profile=request.profile,
            lease_generation=request.lease_generation,
            structured={"tool_calls": [{
                "capability_id": self._capability_id,
                "arguments": {},
                "rationale": "a tool call"
            }]})


def test_f4_a_profile_without_the_field_cannot_execute_tool_calls() -> None:
    # The verifier now declares `tool_calls` (OPS-5Z4), so the gate is proven
    # on a profile whose declaration still lacks it.
    profiles = dict(load_profiles())
    verifier = profiles["verifier"]
    profiles["verifier"] = replace(
        verifier,
        model_policy=replace(
            verifier.model_policy,
            structured_fields=("proposals", "delegations")))
    port = _CapturePort()
    runtime = AgentRuntime(
        model=_OneToolReply("evidence_inspect"),
        orchestration=lambda intent: None,
        capabilities=port,
        profiles=profiles,
        grants={})
    result = runtime.run("verifier", TaskContext(
        task_id="t1", project_id=PROJECT, lease_generation="gen",
        limits=RunLimits(max_ticks=1)))
    assert port.calls == []
    assert any("declared contract" in refusal.detail
               for refusal in result.refusals)


class _InnerPort:
    def invoke(self, request: InvokeRequest) -> Observation:
        return Observation(capability_id=request.capability_id, status="OK")


class _UnusedModel:
    def invoke(self, request: Any) -> Any:
        raise AssertionError("the vector's M2 path does not call the model")


def _vector_with(capabilities: Any) -> LiveVector:
    return LiveVector(
        supervisor=Supervisor(),
        profiles=load_profiles(),
        recorder=RecordingModelPort(_UnusedModel()),
        capabilities=capabilities)


def test_m2_is_a_measured_zero_and_a_number_when_calls_happen() -> None:
    empty = _vector_with(RecordingCapabilityPort(_InnerPort()))
    assert empty._m2_text() == "M2(calls=0,repeat=0.000)"
    no_port = _vector_with(None)
    assert no_port._m2_text() == "M2=n/a (no capability port on this run)"

    recorder = RecordingCapabilityPort(_InnerPort())
    for _ in range(2):
        recorder.invoke(InvokeRequest(
            capability_id="source_search",
            arguments={"provider": "openalex", "topic": "crispr"},
            idempotency_key="idem-m2",
            lease_generation="gen",
            profile="RESEARCHER"))
    assert _vector_with(recorder)._m2_text() == (
        "M2(calls=2,repeat=0.500)")


def test_a_withheld_profile_call_is_role_skipped_and_the_tick_continues() -> None:
    # With only the pre-5Z4 supplied pair, the critic's declarations are
    # withheld, so its composed tools are empty while `allows_tool_calls`
    # stays true: the call is refused by the profile gate, not the port.
    profiles = plan_capability_plane(
        load_profiles(), supplied=RESEARCH_CAPABILITY_IDS,
        risks={"source_fetch": "MEDIUM", "source_search": "MEDIUM"}).profiles
    port = _CapturePort()
    runtime = AgentRuntime(
        model=_OneToolReply("evidence_inspect"),
        orchestration=lambda intent: None,
        capabilities=port,
        profiles=profiles,
        grants={})
    result = runtime.run("critic", TaskContext(
        task_id="t1", project_id=PROJECT, lease_generation="gen",
        limits=RunLimits(max_ticks=1)))
    assert port.calls == []
    assert any(refusal.code == "ROLE" for refusal in result.refusals)
