"""OPS-5D — the evidence position records the agent's admitted artifact.

What this file proves, against the real chain (a real fetch through the OPS-5C
capability supply, a real artifact row, the real gateway and the real live
methodology driver; no network):

1. a scripted run where the model fetches, proposes an ``EVIDENCE_TRANSITION``
   citing that artifact, and is admitted records an ``EVIDENCE`` node whose
   ``external_ref`` is **that** artifact — not an operator seed;
2. the same run's ``OBSERVATION`` node cites it and the ``CLAIM`` node admits
   it, while the claim identity stays prior art (labelled);
3. a seed carrying an ``evidence:`` ref is refused before any model call;
4. a run with no admitted evidence transition stops at ``EVIDENCE`` and does
   not record a synthetic ref;
5. a proposal citing a nonexistent artifact is refused by the gateway's
   ``EVIDENCE_REF`` (the only artifact-row check), and the driver's source
   contains no second check;
6. a replay reproduces the same ``EVIDENCE`` content and ``mnode_`` id, and
   the durable transition event carries the ref.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any

import pytest

from hermes.agents.runtime.assembly import PROJECT_INDEX_ORIGIN
from hermes.agents.runtime.config import load_profiles
from hermes.agents.runtime.wiring import RuntimeWiring
from hermes.artifacts.store import ArtifactStore
from hermes.composition import plan_capability_plane
from hermes.methodology.substrate import MALFORMED_PAYLOAD, SubstrateNode
from hermes.methodology.swap_test import chain_inputs
from hermes.methodology.workflows import (
    LITERATURE_REVIEW_DOCUMENT,
    MethodologyInputs,
    MethodologyRefusal,
    parse_methodology,
)
from hermes.methodology.workflows import (
    run_methodology as plane_run_methodology,
)
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    ArtifactRepository,
    ProjectRepository,
)
from hermes.research.capability_supply import (
    SUPPLIED_CAPABILITY_IDS,
    build_research_egress_supply,
)
from hermes.research.gateway import apply_intent
from hermes.research.live_fetch import ALLOWLIST_HOSTS, build_live_fetch_wiring
from hermes.research.project_index import ProjectIndexReader
from hermes.research.task_handlers.methodology_driver import (
    MethodologyExecution,
)
from hermes.research.task_handlers.methodology_driver import (
    run_methodology as live_run_methodology,
)
from hermes.tools.capabilities.invoke import (
    CapabilityInvoker,
    InMemoryIdempotencyLedger,
)
from hermes.tools.models.router import ModelProposal
from hermes.tools.providers.base import TransportResponse

CLOCK = "2026-10-25T12:00:00.000000+00:00"
PROJECT = "p-ops5d"
TASK = "task-ops5d"
QUESTION = "does the fetched source support the claim?"
URL = "https://openalex.org/W2060313932"
FETCH_BODY = b"OPS5D-FETCHED-FULLTEXT - the artifact the agent cites\n"
FETCH_HASH = hashlib.sha256(FETCH_BODY).hexdigest()
AGENT_EVIDENCE = f"evidence:{FETCH_HASH}"


class Clock:
    def now_utc(self) -> str:
        return CLOCK

    def monotonic(self) -> float:
        return 0.0

    def sleep(self, seconds: float) -> None:
        return None


def _public_resolve(host: str) -> tuple[str, ...]:
    return ("93.184.216.34",)


def _proposal(request: Any, structured: dict[str, Any]) -> ModelProposal:
    return ModelProposal(
        provider_id="scripted", model_id="scripted", tier="research",
        profile=request.profile, lease_generation=request.lease_generation,
        structured=dict(structured))


def _stage_of(request: Any) -> str:
    for part in request.prompt:
        if part.origin != "runtime.payload":
            continue
        try:
            document = json.loads(part.text)
        except ValueError:
            continue
        if isinstance(document, dict) and "stage" in document:
            return str(document["stage"])
    return ""


def _artifact_entry(request: Any) -> str:
    for part in request.prompt:
        if part.origin != PROJECT_INDEX_ORIGIN:
            continue
        try:
            document = json.loads(part.text)
        except ValueError:
            continue
        for entry in document.get("entries", ()):
            if (isinstance(entry, dict) and entry.get("kind") == "artifact"
                    and str(entry.get("id", "")).startswith("source_payload:")):
                return str(entry["id"])
    return ""


class FetchThenCiteModel:
    """HYPOTHESIS fetches; OBSERVATION cites the fetched artifact.

    The shipped methodology allows one tick per stage, so the fetch and the
    citation cannot share a tick (proposals are admitted before tools). The
    fetch happens in the HYPOTHESIS run; the artifact appears in the OPS-18
    project index read by the OBSERVATION run, which cites it.
    """

    def __init__(self) -> None:
        self.calls: list[Any] = []
        self.evidence_ref = ""

    def invoke(self, request: Any) -> ModelProposal:
        self.calls.append(request)
        if any(part.origin == "runtime.review" for part in request.prompt):
            return _proposal(request, {})
        stage = _stage_of(request)
        if stage == "HYPOTHESIS":
            return _proposal(request, {
                "tool_calls": [{
                    "capability_id": "source_fetch",
                    "arguments": {"provider": "openalex", "url": URL},
                    "rationale": "fetch the source before the observation",
                }],
            })
        if stage == "OBSERVATION":
            entry = _artifact_entry(request)
            assert entry, "the fetched artifact is not in the project index"
            self.evidence_ref = "evidence:" + entry.split(":", 1)[1]
            return _proposal(request, {
                "kind": "EVIDENCE_TRANSITION",
                "rationale": "cite the artifact the agent fetched",
                "payload": {
                    "evidence_artifact_ref": self.evidence_ref,
                    "from_state": "SUPPORTED",
                    "to_state": "ROBUST",
                    "rationale": "the fetched source supports the rung",
                },
            })
        return _proposal(request, {})


class SilentModel:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def invoke(self, request: Any) -> ModelProposal:
        self.calls.append(request)
        return _proposal(request, {})


class GhostEvidenceModel:
    """Proposes an evidence ref that is not an artifact row."""

    def __init__(self, ref: str = "evidence:ghost-not-an-artifact") -> None:
        self.calls: list[Any] = []
        self.ref = ref

    def invoke(self, request: Any) -> ModelProposal:
        self.calls.append(request)
        if any(part.origin == "runtime.review" for part in request.prompt):
            return _proposal(request, {})
        if _stage_of(request) == "OBSERVATION":
            return _proposal(request, {
                "kind": "EVIDENCE_TRANSITION",
                "rationale": "cite a ref nobody fetched",
                "payload": {
                    "evidence_artifact_ref": self.ref,
                    "from_state": "SUPPORTED",
                    "to_state": "ROBUST",
                    "rationale": "the ref does not resolve",
                },
            })
        return _proposal(request, {})


@dataclass
class Rig:
    conn: Any
    store: ArtifactStore
    invoker: CapabilityInvoker
    plan: Any

    def run(self, model: Any, *, inputs: MethodologyInputs | None = None,
            on_stage: Any = None, project_index: bool = True,
            ) -> MethodologyExecution | MethodologyRefusal:
        wiring = RuntimeWiring(
            model=model,
            orchestration=lambda intent: apply_intent(self.conn, intent),
            lease_generation="lease-ops5d",
            profiles=load_profiles(),
            grants=self.plan.grants,
            capabilities=self.invoker,
            clock=lambda: CLOCK)
        return live_run_methodology(
            parse_methodology(dict(LITERATURE_REVIEW_DOCUMENT)),
            chain_inputs(PROJECT, QUESTION) if inputs is None else inputs,
            wiring=wiring,
            project_id=PROJECT,
            task_id=TASK,
            project_index=(ProjectIndexReader(self.conn)
                           if project_index else None),
            on_stage=on_stage)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: CLOCK).create(PROJECT, "OPS-5D")
    store = ArtifactStore(
        str(tmp_path / "store"), ArtifactRepository(conn, lambda: CLOCK),
        clock=lambda: CLOCK)
    wiring = build_live_fetch_wiring(
        conn, store, lambda: CLOCK, dns_resolve=_public_resolve)

    def scripted(spec):
        return TransportResponse(
            status=200, body=FETCH_BODY, headers={},
            content_type="text/plain")

    monkeypatch.setattr(wiring.http_transport, "request", scripted)
    machinery = replace(wiring.machinery, clock=Clock())
    supply = build_research_egress_supply(
        conn=conn, store=store, clock=lambda: CLOCK, project_id=PROJECT,
        machinery=machinery, allowlist=ALLOWLIST_HOSTS,
        dns_resolve=_public_resolve)
    invoker = CapabilityInvoker(
        registry=supply.registry,
        implementations=supply.implementations,
        clock=Clock(),
        ledger=InMemoryIdempotencyLedger(),
        sandbox_enabled=False)
    plan = plan_capability_plane(
        load_profiles(), supplied=SUPPLIED_CAPABILITY_IDS,
        risks={"source_fetch": "MEDIUM", "source_search": "MEDIUM"})
    yield Rig(conn=conn, store=store, invoker=invoker, plan=plan)
    conn.close()


def _nodes(execution: MethodologyExecution, kind: str
           ) -> list[tuple[str, SubstrateNode]]:
    return list(execution.store.nodes_of_kind(kind, project_id=PROJECT))


def _artifact_rows(conn) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(
        "SELECT * FROM artifacts WHERE artifact_type = 'source_payload' "
        "AND project_id = ?", (PROJECT,))]


def _transition_events(conn) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(
        "SELECT * FROM events WHERE event_type = "
        "'EvidenceTransitionProposed' ORDER BY rowid")]


# ═══════════════ 1. the fetched artifact becomes the EVIDENCE ref ═══════════


def test_the_fetched_artifact_is_the_evidence_node_ref(rig, capsys) -> None:
    model = FetchThenCiteModel()
    execution = rig.run(model)
    assert isinstance(execution, MethodologyExecution), execution
    assert execution.termination == "COMPLETE"
    assert _artifact_rows(rig.conn), "the model's fetch wrote no artifact"
    assert len(_artifact_rows(rig.conn)) == 1
    assert model.evidence_ref == AGENT_EVIDENCE

    evidence = _nodes(execution, "EVIDENCE")
    assert len(evidence) == 1
    evidence_id, node = evidence[0]
    assert evidence_id == node.derived_id()
    assert node.content["external_ref"] == AGENT_EVIDENCE
    assert node.content["external_ref"] != ""
    assert "evidence:synthetic" not in str(node.content)

    _observation_id, observation = _nodes(execution, "OBSERVATION")[0]
    assert observation.content.get("cited_refs") == (AGENT_EVIDENCE,)
    _claim_id, claim = _nodes(execution, "CLAIM")[0]
    assert claim.content.get("admitted_refs") == (AGENT_EVIDENCE,)
    assert claim.content["external_ref"].startswith("claim:")

    # The gateway's EVIDENCE_REF check accepted the same artifact row; the
    # admission is the durable event, and it carries the ref.
    events = _transition_events(rig.conn)
    assert events
    payload = json.loads(events[-1]["payload_json"])
    assert payload["evidence_artifact_ref"] == AGENT_EVIDENCE
    assert ArtifactRepository(rig.conn).in_project(
        FETCH_HASH, PROJECT) is True

    # The prior-art positions are labelled; the evidence rationale is the
    # proposal's. None of this is content.
    hypothesis = _nodes(execution, "HYPOTHESIS")[0][1]
    assert "prior-art citation (no producer in this build)" in (
        hypothesis.rationale)
    assert ("claim identity is prior art; support is the recorded evidence "
            "ref") in claim.rationale
    assert "grounded" not in str(hypothesis.content)

    print("EVIDENCE NODE ID:", evidence_id)
    print("EVIDENCE CONTENT:", json.dumps(dict(node.content), sort_keys=True))
    print("EVIDENCE RATIONALE:", node.rationale)
    print("TRANSITION EVENT REF:", payload["evidence_artifact_ref"])


def test_the_evaluation_of_the_evidence_ref_is_the_gateway_check(rig) -> None:
    # The same artifact row is accepted by EVIDENCE_REF; a ghost is refused.
    model = FetchThenCiteModel()
    execution = rig.run(model)
    assert isinstance(execution, MethodologyExecution)
    assert _nodes(execution, "EVIDENCE")
    assert ArtifactRepository(rig.conn).in_project(FETCH_HASH, PROJECT)

    from hermes.core.intents import Intent, IntentKind
    from hermes.research.gateway import GatewayRejection
    with pytest.raises(GatewayRejection) as refused:
        apply_intent(rig.conn, Intent(
            kind=IntentKind.EVIDENCE_TRANSITION,
            proposed_by="RESEARCHER", project_id=PROJECT,
            payload={
                "evidence_artifact_ref": "evidence:ghost",
                "from_state": "SUPPORTED",
                "to_state": "ROBUST",
                "rationale": "a ref nobody fetched",
            }))
    assert refused.value.code == "EVIDENCE_REF"


# ═══════════════ 2. the seed evidence ref is refused ═══════════════


class _SpyModel:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def invoke(self, request: Any) -> ModelProposal:
        self.calls.append(request)
        return _proposal(request, {})


def test_a_seed_evidence_ref_is_refused() -> None:
    base = chain_inputs(PROJECT, QUESTION)
    cases = (
        MethodologyInputs(
            question=base.question,
            external_refs={**base.external_refs,
                           "EVIDENCE": "evidence:synthetic-sars13/e1"},
            admission_refs=base.admission_refs),
        MethodologyInputs(
            question=base.question,
            external_refs=base.external_refs,
            admission_refs=base.admission_refs + ("evidence:synthetic-sars13/e1",)),
        MethodologyInputs(
            question=base.question,
            external_refs=base.external_refs,
            admission_refs=base.admission_refs,
            stage_content={"EVIDENCE": {
                "external_ref": "evidence:synthetic-sars13/e1"}}),
    )
    for number, inputs in enumerate(cases):
        model = _SpyModel()
        outcome = plane_run_methodology(
            parse_methodology(dict(LITERATURE_REVIEW_DOCUMENT)),
            PROJECT, f"{TASK}-seed-{number}", "gen", inputs,
            model=model, orchestration=lambda intent: None,
            profiles=load_profiles())
        assert isinstance(outcome, MethodologyRefusal)
        assert outcome.source == "inputs"
        assert outcome.code == MALFORMED_PAYLOAD
        assert model.calls == []


# ═══════════════ 3. no admitted transition stops at EVIDENCE ═══════════════


def test_a_run_without_an_admitted_transition_stops_at_evidence(rig) -> None:
    model = SilentModel()
    execution = rig.run(model)
    assert isinstance(execution, MethodologyRefusal), execution
    assert execution.source == "substrate"
    assert execution.stage == "EVIDENCE"
    assert execution.code == MALFORMED_PAYLOAD
    assert "needs a non-empty 'external_ref'" in execution.detail
    assert not _transition_events(rig.conn)
    assert not _artifact_rows(rig.conn)


# ═══════════════ 4. a ghost ref is refused by the gateway, then stops ═══════════


def test_a_ghost_ref_is_refused_by_the_gateway_and_stops_at_evidence(rig) -> None:
    seen: list[Any] = []
    execution = rig.run(
        GhostEvidenceModel(), on_stage=lambda wiring, result: seen.append(result))
    assert isinstance(execution, MethodologyRefusal), execution
    assert execution.stage == "EVIDENCE"
    observation_results = [
        result for result in seen
        if str(getattr(result, "task_id", "")).endswith(":OBSERVATION")]
    assert observation_results, "the OBSERVATION stage did not run"
    result = observation_results[-1]
    # The runtime's frozen plane vocabulary maps the gateway's EVIDENCE_REF to
    # PROPOSAL while keeping the spine code visible in the detail (C4).
    assert "PROPOSAL" in result.refusal_codes()
    assert any("EVIDENCE_REF" in refusal.detail
               for refusal in result.refusals)
    assert not _transition_events(rig.conn)
    assert not _artifact_rows(rig.conn)


def test_the_drivers_have_no_second_artifact_row_check() -> None:
    from pathlib import Path

    import hermes.methodology.workflows as plane_module
    import hermes.research.task_handlers.methodology_driver as live_module
    for module in (plane_module, live_module):
        source = Path(str(module.__file__)).read_text(encoding="utf-8")
        assert "ArtifactRepository" not in source
        assert "in_project" not in source
        assert "SELECT 1 FROM artifacts" not in source


# ═══════════════ 5. replay ═══════════════


def test_a_replay_reproduces_the_evidence_node_content_and_id(rig) -> None:
    first_model = FetchThenCiteModel()
    first = rig.run(first_model)
    assert isinstance(first, MethodologyExecution)
    first_id, first_node = _nodes(first, "EVIDENCE")[0]

    second_model = FetchThenCiteModel()
    second = rig.run(second_model)
    assert isinstance(second, MethodologyExecution)
    second_id, second_node = _nodes(second, "EVIDENCE")[0]

    assert first_model.evidence_ref == second_model.evidence_ref
    assert first_id == second_id
    assert dict(first_node.content) == dict(second_node.content)
    assert first_node.rationale == second_node.rationale
    assert first_node.derived_id() == first_id
    assert second_node.derived_id() == second_id
    # The transition event is idempotent: the replay is a duplicate, not a
    # second durable transition.
    assert len(_transition_events(rig.conn)) == 1
