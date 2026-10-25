"""OPS-5B — the fetched bytes become a citable ``source_payload`` row.

The falsifier this file exists for: a live-shaped run with a scripted
``tool_calls`` reply executes ``source_fetch`` and then an
``EVIDENCE_TRANSITION`` naming ``evidence:<artifact_id>`` is admitted by the
real gateway. The row is attributable, content-addressed, project-scoped and
confined to the executor; the model cannot name its content, identity, type,
project or destination.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from hermes.agents.runtime.config import load_profiles
from hermes.agents.runtime.run import AgentRuntime
from hermes.agents.runtime.types import RunLimits, TaskContext
from hermes.artifacts.store import ArtifactStore
from hermes.composition import plan_capability_plane
from hermes.core.intents import Intent, IntentKind
from hermes.eval.loop_metrics import repeat_tool_rate
from hermes.eval.loop_observations import RecordingCapabilityPort
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ArtifactRepository, ProjectRepository
from hermes.research.capability_supply import (
    RESEARCH_EGRESS_TOOL_SET_ID,
    SUPPLIED_CAPABILITY_IDS,
    build_research_egress_supply,
)
from hermes.research.gateway import apply_intent
from hermes.research.live_fetch import ALLOWLIST_HOSTS, build_live_fetch_wiring
from hermes.tools.capabilities.invoke import (
    CapabilityInvoker,
    InMemoryIdempotencyLedger,
)
from hermes.tools.capabilities.types import (
    CapabilityRefusal,
    FailureKind,
    InvokeRequest,
    Observation,
    RiskLevel,
    ToolGrant,
)
from hermes.tools.models.router import ModelProposal
from hermes.tools.providers.base import TransportResponse

CLOCK = "2026-10-25T12:00:00.000000+00:00"
PROJECT = "p1"
OTHER = "p2"
PROFILE = "RESEARCHER"
URL = "https://openalex.org/W2060313932"
FETCH_BODY = (b"Curated full text about CRISPR systems.\n"
              b"OPS5B-ARTIFACT-MARKER")
FETCH_HASH = hashlib.sha256(FETCH_BODY).hexdigest()


class Clock:
    def now_utc(self) -> str:
        return CLOCK

    def monotonic(self) -> float:
        return 1000.0

    def sleep(self, delay: float) -> None:
        return None


def _public_resolve(host: str) -> tuple[str, ...]:
    return ("93.184.216.34",)


@dataclass
class Rig:
    conn: Any
    store: ArtifactStore
    supply: Any
    invoker: CapabilityInvoker
    calls: list[Any]

    def fetch(self, key: str = "idem-fetch") -> Observation:
        result = self.invoker.invoke(InvokeRequest(
            capability_id="source_fetch",
            arguments={"provider": "openalex", "url": URL},
            idempotency_key=key,
            lease_generation="lease-gen-7",
            profile=PROFILE,
            rationale="the brief asks for an admitted source",
            grant=ToolGrant(
                grant_id="grant.live.researcher",
                profile=PROFILE,
                tool_set_ids=frozenset({RESEARCH_EGRESS_TOOL_SET_ID}),
                max_risk=RiskLevel.MEDIUM.value),
            deadline_seconds=30.0))
        assert isinstance(result, Observation), result
        return result


@pytest.fixture
def conn():
    connection = connect(":memory:")
    migrate_to_latest(connection)
    ProjectRepository(connection, lambda: CLOCK).create(PROJECT, "OPS-5B")
    ProjectRepository(connection, lambda: CLOCK).create(OTHER, "OPS-5B other")
    yield connection
    connection.close()


@pytest.fixture
def store(conn, tmp_path):
    return ArtifactStore(
        str(tmp_path / "store"),
        ArtifactRepository(conn, lambda: CLOCK),
        clock=lambda: CLOCK)


@pytest.fixture
def rig(conn, store, monkeypatch):
    wiring = build_live_fetch_wiring(
        conn, store, lambda: CLOCK, dns_resolve=_public_resolve)
    calls: list[Any] = []

    def scripted(spec):
        calls.append(spec)
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
    return Rig(conn=conn, store=store, supply=supply, invoker=invoker,
               calls=calls)


def _rows(conn, artifact_type: str, project_id: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(
        "SELECT * FROM artifacts WHERE artifact_type = ? AND project_id = ?",
        (artifact_type, project_id))]


def _seed_row(conn, *, project_id: str, artifact_type: str,
              artifact_id: str) -> None:
    ArtifactRepository(conn, lambda: CLOCK).record(
        artifact_id=artifact_id, artifact_type=artifact_type,
        content_hash=FETCH_HASH, size_bytes=len(FETCH_BODY),
        storage_path=f"seed/{artifact_id}", producer="test",
        project_id=project_id)


def test_the_fetch_persists_one_attributable_source_payload_row(rig) -> None:
    observation = rig.fetch()
    payload = json.loads(observation.payload.text)
    assert payload["status"] == "FETCHED"
    assert payload["artifact_id"] == FETCH_HASH
    assert payload["content_hash"] == FETCH_HASH
    assert payload["source_ref"] == f"source_payload:{FETCH_HASH}"
    assert "text" not in payload
    assert observation.artifacts == (
        f"evidence/{FETCH_HASH}", f"source_payload/{FETCH_HASH}")
    assert rig.store.read_verified(FETCH_HASH) == FETCH_BODY
    rows = _rows(rig.conn, "source_payload", PROJECT)
    assert len(rows) == 1
    row = rows[0]
    assert row["artifact_id"] == FETCH_HASH
    assert row["content_hash"] == FETCH_HASH
    assert row["task_id"] is None
    assert Path(row["storage_path"]).as_posix() == (
        f"{FETCH_HASH[:2]}/{FETCH_HASH[2:4]}/{FETCH_HASH}")
    metadata = json.loads(row["metadata_json"])
    assert metadata["provider"] == "openalex"
    assert metadata["host"] == "api.openalex.org"
    assert metadata["content_digest"] == FETCH_HASH
    assert metadata["source_url_redacted"] == (
        "https://api.openalex.org/W2060313932")
    assert metadata["idempotency_key"] == "idem-fetch"
    assert metadata["lease_generation"] == "lease-gen-7"
    assert row["producer"].startswith(
        "capability:source_fetch:openalex:RESEARCHER:")


def test_the_row_is_accepted_by_evidence_ref_through_the_real_gateway(rig) -> None:
    observation = rig.fetch()
    payload = json.loads(observation.payload.text)
    result = apply_intent(rig.conn, Intent(
        kind=IntentKind.EVIDENCE_TRANSITION,
        proposed_by=PROFILE, project_id=PROJECT,
        payload={
            "evidence_artifact_ref": f"evidence:{payload['artifact_id']}",
            "from_state": "SUPPORTED",
            "to_state": "ROBUST",
            "rationale": "the fetched source supports the rung",
        }))
    assert result.entity_id
    assert rig.conn.execute(
        "SELECT 1 FROM events WHERE event_type = ?",
        ("EvidenceTransitionProposed",)).fetchone() is not None


def test_the_model_cannot_influence_artifact_content_identity_type_project_or_destination(
        rig) -> None:
    # The declared schema has only provider and url; every artifact property
    # is fixed by the executor and the store.
    tool = rig.supply.registry.tool("source_fetch")
    assert tool is not None
    assert {field.name for field in tool.inputs} == {"provider", "url"}
    refusal = rig.invoker.invoke(InvokeRequest(
        capability_id="source_fetch",
        arguments={
            "provider": "openalex", "url": URL,
            "artifact_id": "model-chosen", "artifact_type": "evidence",
            "project_id": OTHER, "storage_path": "../../escape",
            "content_hash": "model-chosen-hash",
        },
        idempotency_key="idem-hostile",
        lease_generation="lease-gen-7",
        profile=PROFILE,
        rationale="try to choose the row",
        grant=ToolGrant(
            grant_id="grant.live.researcher", profile=PROFILE,
            tool_set_ids=frozenset({RESEARCH_EGRESS_TOOL_SET_ID}),
            max_risk=RiskLevel.MEDIUM.value)))
    assert isinstance(refusal, CapabilityRefusal)
    assert refusal.code == "MALFORMED_PAYLOAD"
    assert _rows(rig.conn, "source_payload", PROJECT) == []
    assert _rows(rig.conn, "source_payload", OTHER) == []

    observation = rig.fetch()
    payload = json.loads(observation.payload.text)
    row = _rows(rig.conn, "source_payload", PROJECT)[0]
    assert row["artifact_id"] == FETCH_HASH
    assert row["artifact_type"] == "source_payload"
    assert row["project_id"] == PROJECT
    assert row["content_hash"] == hashlib.sha256(FETCH_BODY).hexdigest()
    assert Path(row["storage_path"]).as_posix() == (
        f"{FETCH_HASH[:2]}/{FETCH_HASH[2:4]}/{FETCH_HASH}")
    assert payload["artifact_id"] != "model-chosen"
    assert payload["content_hash"] != "model-chosen-hash"


def test_cross_project_content_dedup_fails_closed(rig) -> None:
    _seed_row(rig.conn, project_id=OTHER, artifact_type="source_payload",
              artifact_id="p2-row")
    observation = rig.invoker.invoke(InvokeRequest(
        capability_id="source_fetch",
        arguments={"provider": "openalex", "url": URL},
        idempotency_key="idem-cross-project",
        lease_generation="lease-gen-7",
        profile=PROFILE,
        rationale="fetch into p1",
        grant=ToolGrant(
            grant_id="grant.live.researcher", profile=PROFILE,
            tool_set_ids=frozenset({RESEARCH_EGRESS_TOOL_SET_ID}),
            max_risk=RiskLevel.MEDIUM.value)))
    assert isinstance(observation, Observation)
    assert observation.ok() is False
    assert observation.failure is FailureKind.TOOL_ERROR
    assert _rows(rig.conn, "source_payload", PROJECT) == []
    assert len(_rows(rig.conn, "source_payload", OTHER)) == 1


def test_same_hash_different_type_fails_closed(rig) -> None:
    _seed_row(rig.conn, project_id=PROJECT,
              artifact_type="provider_response", artifact_id="provider-row")
    observation = rig.invoker.invoke(InvokeRequest(
        capability_id="source_fetch",
        arguments={"provider": "openalex", "url": URL},
        idempotency_key="idem-type-conflict",
        lease_generation="lease-gen-7",
        profile=PROFILE,
        rationale="fetch with a same-hash conflict",
        grant=ToolGrant(
            grant_id="grant.live.researcher", profile=PROFILE,
            tool_set_ids=frozenset({RESEARCH_EGRESS_TOOL_SET_ID}),
            max_risk=RiskLevel.MEDIUM.value)))
    assert isinstance(observation, Observation)
    assert observation.ok() is False
    assert observation.failure is FailureKind.TOOL_ERROR
    assert _rows(rig.conn, "source_payload", PROJECT) == []
    assert len(_rows(rig.conn, "provider_response", PROJECT)) == 1


def test_a_repeat_fetch_reuses_the_same_row_and_handles(rig) -> None:
    first = rig.fetch("idem-first")
    second = rig.fetch("idem-second")
    assert first.ok() and second.ok()
    first_payload = json.loads(first.payload.text)
    second_payload = json.loads(second.payload.text)
    assert first_payload["artifact_id"] == second_payload["artifact_id"]
    assert first.artifacts == second.artifacts
    assert len(_rows(rig.conn, "source_payload", PROJECT)) == 1


class _ToolThenEvidence:
    """Tick 1 fetches; tick 2 reads the new row and cites it; the review passes."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn
        self.requests: list[Any] = []
        self.tool_tick = False

    def invoke(self, request: Any) -> ModelProposal:
        self.requests.append(request)
        if any(part.origin == "runtime.review" for part in request.prompt):
            return ModelProposal(
                provider_id="script", model_id="script", tier="m",
                profile=request.profile,
                lease_generation=request.lease_generation,
                structured={"rationale": "nothing to object to"})
        if not self.tool_tick:
            self.tool_tick = True
            structured: dict[str, Any] = {"tool_calls": [{
                "capability_id": "source_fetch",
                "arguments": {"provider": "openalex", "url": URL},
                "rationale": "fetch the source first",
            }]}
        else:
            row = self._conn.execute(
                "SELECT artifact_id FROM artifacts "
                "WHERE artifact_type = 'source_payload' AND project_id = ?",
                (PROJECT,)).fetchone()
            assert row is not None, "the tool did not persist a row"
            structured = {
                "kind": "EVIDENCE_TRANSITION",
                "rationale": "cite the source observed last tick",
                "payload": {
                    "evidence_artifact_ref": f"evidence:{row['artifact_id']}",
                    "from_state": "SUPPORTED",
                    "to_state": "ROBUST",
                    "rationale": "the fetched source supports the rung",
                },
            }
        return ModelProposal(
            provider_id="script", model_id="script", tier="m",
            profile=request.profile,
            lease_generation=request.lease_generation,
            structured=structured)


def test_a_live_shaped_run_fetches_then_cites_an_artifact_it_can_prove(rig) -> None:
    plan = plan_capability_plane(
        load_profiles(), supplied=SUPPLIED_CAPABILITY_IDS,
        risks={"source_fetch": "MEDIUM", "source_search": "MEDIUM"})
    model = _ToolThenEvidence(rig.conn)
    capabilities = RecordingCapabilityPort(rig.invoker)
    runtime = AgentRuntime(
        model=model,
        orchestration=lambda intent: apply_intent(rig.conn, intent),
        capabilities=capabilities,
        profiles=plan.profiles,
        grants=plan.grants,
    )
    result = runtime.run("researcher", TaskContext(
        task_id="t1", project_id=PROJECT, lease_generation="gen",
        limits=RunLimits(max_ticks=3, max_tool_calls=2)))
    assert result.state == "SUCCEEDED", (
        result.state, result.termination, [r.detail for r in result.refusals])
    evidence = [proposal for proposal in result.proposals
                if proposal.intent.kind is IntentKind.EVIDENCE_TRANSITION]
    assert len(evidence) == 1
    assert evidence[0].admission == "ADMITTED"
    row = _rows(rig.conn, "source_payload", PROJECT)[0]
    assert rig.conn.execute(
        "SELECT 1 FROM events WHERE event_type = ?",
        ("EvidenceTransitionProposed",)).fetchone() is not None
    assert rig.store.read_verified(row["content_hash"]) == FETCH_BODY
    assert all(
        proposal.intent.payload["evidence_artifact_ref"].startswith("evidence:")
        for proposal in evidence)
    assert model.tool_tick is True
    assert len(capabilities.calls) == 1
    assert repeat_tool_rate(capabilities.calls) == 0.0
