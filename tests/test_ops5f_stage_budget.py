"""OPS-5F — the stage declares its budget **and its job**.

What this file proves, against the real chain where it matters (the OPS-5C
capability supply, a real artifact row, the real gateway, the real live
methodology driver; no network):

1. ``StageSpec.max_ticks`` is an optional, bounded stage field: a document that
   omits it parses to ``None``, serializes without the key and keeps its digest
   to the byte; the shipped document declares ``OBSERVATION: 3`` and moves its
   content revision ``1 → 2``;
2. ``StageSpec.objective`` joins the same revision: the shipped document
   declares one per stage, an old-form document declares none, and a stage
   without one renders no objective at all;
3. the objective reaches the stage prompt as untrusted payload data on the
   existing ``runtime.payload`` origin — no new origin and no new envelope
   port — and the budget reaches it as the existing tick marker
   (``tick 1 of 3``);
4. the objective is stage configuration, not chain content: it does not enter
   ``predecessor_content`` and never re-enters the next stage's prompt;
5. **the fetch → cite falsifier**: OBSERVATION with three ticks searches, then
   fetches the handle's row, then proposes an ``EVIDENCE_TRANSITION`` naming
   the artifact it fetched — and the ``EVIDENCE`` node's ref is that artifact,
   accepted by the gateway's ``EVIDENCE_REF``;
6. a stage that proposes on tick 1 still stops there: the budget is the bound,
   the objective is guidance;
7. a stage with no proposal for its whole budget ends at ``TICK_LIMIT`` and the
   chain stops at ``EVIDENCE`` rather than inventing a ref;
8. the cost table is reproducible from the parsed document and the profiles:
   27/16 today, 31/18 with the stage budget, 46/25 and 65/34 for global 2/3.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from dataclasses import dataclass, replace
from typing import Any

import pytest

from hermes.agents.runtime.assembly import (
    EVIDENCE_ORIGIN,
    PAYLOAD_ORIGIN,
    TASK_ORIGIN,
)
from hermes.agents.runtime.config import load_profiles
from hermes.agents.runtime.run import TOOL_CALL_KEYS
from hermes.agents.runtime.types import (
    TaskStatus,
    Termination,
    canonical_json,
)
from hermes.agents.runtime.wiring import RuntimeWiring
from hermes.artifacts.store import ArtifactStore
from hermes.composition import build_capability_tool_notes, plan_capability_plane
from hermes.methodology.substrate import MALFORMED_PAYLOAD, digest_of
from hermes.methodology.swap_test import chain_inputs, engineering_investigation
from hermes.methodology.workflows import (
    LITERATURE_REVIEW_DOCUMENT,
    MAX_STAGE_TICKS,
    STAGE_KEYS,
    MethodologyConfigError,
    MethodologyInputs,
    MethodologyRefusal,
    literature_review,
    methodology_identity,
    parse_methodology,
)
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    ArtifactRepository,
    ProjectRepository,
)
from hermes.research.capability_supply import (
    RESEARCH_EGRESS_TOOL_SET_ID,
    SUPPLIED_CAPABILITY_IDS,
    build_research_egress_supply,
    supplied_capability_risks,
)
from hermes.research.chain_refs import RefProvenanceReader
from hermes.research.gateway import apply_intent
from hermes.research.live_fetch import ALLOWLIST_HOSTS, build_live_fetch_wiring
from hermes.research.task_handlers.methodology_driver import (
    MethodologyExecution,
    project_stage,
    stage_projections,
)
from hermes.research.task_handlers.methodology_driver import (
    run_methodology as live_run_methodology,
)
from hermes.tools.capabilities.invoke import (
    CapabilityInvoker,
    InMemoryIdempotencyLedger,
)
from hermes.tools.capabilities.types import (
    InvokeRequest,
    Observation,
    RiskLevel,
    ToolGrant,
)
from hermes.tools.models.router import ModelProposal
from hermes.tools.providers.base import TransportResponse

CLOCK = "2026-10-25T12:00:00.000000+00:00"
PROJECT = "p-ops5f"
TASK = "task-ops5f"
QUESTION = "does the fetched source support the claim?"
TOPIC = "CRISPR delivery"

FETCH_BODY = b"OPS5F-FETCHED-FULLTEXT - the artifact the stage cites\n"
FETCH_HASH = hashlib.sha256(FETCH_BODY).hexdigest()

TITLES = (
    "OPS5F-SENTINEL-TITLE-ALPHA a distinctive first hit",
    "OPS5F-SENTINEL-TITLE-BRAVO a distinctive second hit",
)
URLS = (
    "https://openalex.org/W910000001",
    "https://openalex.org/W910000002",
)
DOIS = (
    "https://doi.org/10.5555/ops5f.alpha",
    "https://doi.org/10.5555/ops5f.bravo",
)

#: The governed-document pins. Old form: the document before phase 2 (no
#: stage fields, version 1). New: the document that declares OBSERVATION's
#: three ticks and every stage's objective. Control: the swap fixture, which
#: declares neither and therefore does not move.
OLD_FORM_DIGEST = "a5ba891919badaa4e7b01db2e993689d069e325fe598e1e6e54f9f7cd25a845d"
SHIPPED_DIGEST = "493ddb056e53ac822d0448a3b8dfe93525737476e1ccf83103e7c3021d7aad8d"
#: Moved when HYPOTHESIS, PREDICTION and CLAIM gained the proposal envelope in
#: their objective (+204 bytes each): a live run stopped at HYPOTHESIS in four
#: of four attempts because the model wrote the stage name where an intent kind
#: belongs. The bytes are the cost of saying it where the model reads its task.
#: Moved when the swap fixture's OBSERVATION stage moved from `experimenter`
#: (which has no source tools and could not observe anything) to `researcher`.
#: The control still controls: it is pinned so an unrelated change to the
#: shipped document cannot move it silently.
CONTROL_DIGEST = "b27cf7ed13baec7aef6230c7d643af0daa3113b130ac2d86f70b9b872148aab1"

#: Per-stage objective bytes (UTF-8), the delta each stage adds to its prompt.
OBJECTIVE_BYTES = {
    "QUESTION": 85,
    "HYPOTHESIS": 481,
    "PREDICTION": 311,
    "EXPERIMENT": 106,
    "OBSERVATION": 471,
    "EVIDENCE": 110,
    "CLAIM": 299,
    "CRITIQUE": 87,
    "CONCLUSION": 73,
}


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


def _old_form_document() -> dict[str, Any]:
    """The document as it was before this revision: no stage fields, version 1."""
    stages = [
        {key: value for key, value in stage.items()
         if key in ("stage", "profile", "governance_action")}
        for stage in LITERATURE_REVIEW_DOCUMENT["stages"]
    ]
    document = dict(LITERATURE_REVIEW_DOCUMENT)
    document["version"] = "1"
    document["stages"] = stages
    return document


def _search_body() -> bytes:
    return json.dumps({
        "total": 2,
        "meta": {"count": 2},
        "results": [
            {"id": url, "doi": doi, "title": title,
             "publication_year": 2021 + index}
            for index, (url, doi, title) in enumerate(
                zip(URLS, DOIS, TITLES, strict=True))
        ],
    }).encode("utf-8")


SEARCH_BODY = _search_body()


# ═══════════════════════ prompt readers ═══════════════════════


def _payload_document(request: Any, key: str) -> dict[str, Any] | None:
    for part in request.prompt:
        if part.origin != PAYLOAD_ORIGIN:
            continue
        try:
            document = json.loads(part.text)
        except ValueError:
            continue
        if isinstance(document, dict) and key in document:
            return document
    return None


def _stage_of(request: Any) -> str:
    document = _payload_document(request, "stage")
    return str(document["stage"]) if document else ""


def _tick_of(request: Any) -> tuple[int, int]:
    for part in request.prompt:
        if part.origin != "runtime.tick":
            continue
        match = re.fullmatch(r"tick (\d+) of (\d+)", part.text)
        if match is not None:
            return int(match.group(1)), int(match.group(2))
    return 0, 0


def _feedback(request: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for part in request.prompt:
        if not part.origin.startswith("runtime.observation"):
            continue
        try:
            document = json.loads(part.text)
        except ValueError:
            continue
        if isinstance(document, dict):
            records.append(document)
    return records


def _handle_from_feedback(request: Any) -> str:
    for record in reversed(_feedback(request)):
        match = re.search(r"search_handle=(search_[0-9a-f]{64})",
                          str(record.get("detail", "")))
        if match is not None:
            return match.group(1)
    return ""


def _artifact_from_feedback(request: Any) -> str:
    for record in reversed(_feedback(request)):
        for artifact in record.get("artifacts") or ():
            if str(artifact).startswith("evidence/"):
                return str(artifact)
    return ""


# ═══════════════════════ scripted models ═══════════════════════


class SearchFetchCiteModel:
    """OBSERVATION: search, then fetch the handle's row, then cite it.

    Each tick reads only what the previous tick's feedback carried — the
    search handle and then the fetched artifact ref — exactly the information a
    real model would have, and the order the objective prescribes.
    """

    def __init__(self) -> None:
        self.calls: list[Any] = []
        self.evidence_ref = ""

    def invoke(self, request: Any) -> ModelProposal:
        self.calls.append(request)
        if any(part.origin == "runtime.review" for part in request.prompt):
            return _proposal(request, {})
        if _stage_of(request) != "OBSERVATION":
            return _proposal(request, {})
        tick, _ = _tick_of(request)
        if tick == 1:
            return _proposal(request, {"tool_calls": [{
                "capability_id": "source_search",
                "arguments": {"provider": "openalex", "topic": TOPIC,
                              "max_results": 2},
                "rationale": "find a source before citing one",
            }]})
        if tick == 2:
            handle = _handle_from_feedback(request)
            assert handle, "the search handle did not reach the next tick"
            return _proposal(request, {"tool_calls": [{
                "capability_id": "source_fetch",
                "arguments": {"provider": "openalex", "search_handle": handle,
                              "row_index": 0},
                "rationale": "fetch the top-ranked row the search returned",
            }]})
        artifact = _artifact_from_feedback(request)
        assert artifact, "the fetched artifact did not reach the next tick"
        self.evidence_ref = "evidence:" + artifact.split("/", 1)[1]
        return _proposal(request, {
            "kind": "EVIDENCE_TRANSITION",
            "rationale": "cite the artifact this stage fetched",
            "payload": {
                "evidence_artifact_ref": self.evidence_ref,
                "from_state": "SUPPORTED",
                "to_state": "ROBUST",
                "rationale": "the fetched source supports the rung",
            },
        })


class Run40Model:
    """Run 40's exact shape: search + a refused transition, then fetch, then cite.

    Tick 1 carries a correct ``source_search`` **and** an ``EVIDENCE_TRANSITION``
    naming a ref that does not exist. The gateway refuses the transition
    (``EVIDENCE_REF``), but the search executes; before this slice the refused
    draft counted as raised and the stage ended on that tick. Now the stage
    reaches tick 2 (fetch the handle's row) and tick 3 (cite the artifact).
    """

    def __init__(self) -> None:
        self.calls: list[Any] = []
        self.evidence_ref = ""

    def invoke(self, request: Any) -> ModelProposal:
        self.calls.append(request)
        if any(part.origin == "runtime.review" for part in request.prompt):
            return _proposal(request, {})
        if _stage_of(request) != "OBSERVATION":
            return _proposal(request, {})
        tick, _ = _tick_of(request)
        if tick == 1:
            return _proposal(request, {
                "kind": "EVIDENCE_TRANSITION",
                "rationale": ("No evidence artifact has been fetched yet; I "
                              "must search and fetch before proposing."),
                "payload": {
                    "evidence_artifact_ref":
                        "evidence:obs-sars-covid-40-brazil-india",
                    "from_state": "SUPPORTED",
                    "to_state": "ROBUST",
                    "rationale": "defer the verdict to a later tick",
                },
                "tool_calls": [{
                    "capability_id": "source_search",
                    "arguments": {"provider": "openalex", "topic": TOPIC,
                                  "max_results": 2},
                    "rationale": "find a source before citing one",
                }],
            })
        if tick == 2:
            handle = _handle_from_feedback(request)
            assert handle, "the search handle did not reach the next tick"
            return _proposal(request, {"tool_calls": [{
                "capability_id": "source_fetch",
                "arguments": {"provider": "openalex", "search_handle": handle,
                              "row_index": 0},
                "rationale": "fetch the row the search delivered",
            }]})
        artifact = _artifact_from_feedback(request)
        assert artifact, "the fetched artifact did not reach the next tick"
        self.evidence_ref = "evidence:" + artifact.split("/", 1)[1]
        return _proposal(request, {
            "kind": "EVIDENCE_TRANSITION",
            "rationale": "cite the artifact this stage fetched",
            "payload": {
                "evidence_artifact_ref": self.evidence_ref,
                "from_state": "SUPPORTED",
                "to_state": "ROBUST",
                "rationale": "the fetched source supports the rung",
            },
        })


class SilentModel:
    """Records every call and proposes nothing — a stage with no work."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def invoke(self, request: Any) -> ModelProposal:
        self.calls.append(request)
        return _proposal(request, {})


class EarlyProposalModel:
    """Proposes an admitted transition on tick 1, before gathering anything.

    The ref is a real artifact row written before the run, so the proposal is
    admitted: the only reason the stage stops after one tick is its own
    ``stop_when`` policy, not a refusal.
    """

    def __init__(self, evidence_ref: str) -> None:
        self.calls: list[Any] = []
        self.evidence_ref = evidence_ref

    def invoke(self, request: Any) -> ModelProposal:
        self.calls.append(request)
        if any(part.origin == "runtime.review" for part in request.prompt):
            return _proposal(request, {})
        if _stage_of(request) != "OBSERVATION":
            return _proposal(request, {})
        return _proposal(request, {
            "kind": "EVIDENCE_TRANSITION",
            "rationale": "propose first, gather never",
            "payload": {
                "evidence_artifact_ref": self.evidence_ref,
                "from_state": "SUPPORTED",
                "to_state": "ROBUST",
                "rationale": "cites an artifact observed before this stage",
            },
        })


@dataclass
class Rig:
    conn: Any
    store: ArtifactStore
    invoker: CapabilityInvoker
    plan: Any
    supply: Any
    calls: list[Any]

    def read_artifact(self, project_id: str, artifact_id: str) -> bytes | None:
        """The composition's OPS-5Z3 byte port, project-scoped (test double)."""
        repo = ArtifactRepository(self.conn, lambda: CLOCK)
        if not repo.in_project(artifact_id, project_id):
            return None
        row = repo.get(artifact_id)
        try:
            return self.store.read_verified(row["content_hash"])
        except FileNotFoundError:
            return None

    def fetch_once(self) -> str:
        """Write one real artifact row through the shipped fetch chain."""
        result = self.invoker.invoke(InvokeRequest(
            capability_id="source_fetch",
            arguments={"provider": "openalex", "url": URLS[0]},
            idempotency_key="idem-ops5f-seed",
            lease_generation="lease-ops5f",
            profile="RESEARCHER",
            rationale="seed one artifact for the early-proposal control",
            grant=ToolGrant(
                grant_id="grant.ops5f",
                profile="RESEARCHER",
                tool_set_ids=frozenset({RESEARCH_EGRESS_TOOL_SET_ID}),
                max_risk=RiskLevel.MEDIUM.value)))
        assert isinstance(result, Observation), result
        assert result.ok(), result.detail
        artifact = next(ref for ref in result.artifacts
                        if ref.startswith("evidence/"))
        return "evidence:" + artifact.split("/", 1)[1]

    def run(self, model: Any, *, config: Any = None,
            inputs: MethodologyInputs | None = None,
            ) -> MethodologyExecution | MethodologyRefusal:
        wiring = RuntimeWiring(
            model=model,
            orchestration=lambda intent: apply_intent(self.conn, intent),
            lease_generation="lease-ops5f",
            profiles=load_profiles(),
            grants=self.plan.grants,
            capabilities=self.invoker,
            capability_tool_notes=build_capability_tool_notes(
                self.plan, self.supply, item_keys=TOOL_CALL_KEYS),
            clock=lambda: CLOCK)
        return live_run_methodology(
            literature_review() if config is None else config,
            chain_inputs(PROJECT, QUESTION) if inputs is None else inputs,
            wiring=wiring,
            project_id=PROJECT,
            task_id=TASK,
            provenance_of=RefProvenanceReader(self.conn),
            artifact_reader=self.read_artifact)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    connection = connect(":memory:")
    migrate_to_latest(connection)
    ProjectRepository(connection, lambda: CLOCK).create(PROJECT, "OPS-5F")
    store = ArtifactStore(
        str(tmp_path / "store"),
        ArtifactRepository(connection, lambda: CLOCK),
        clock=lambda: CLOCK)
    wiring = build_live_fetch_wiring(
        connection, store, lambda: CLOCK, dns_resolve=_public_resolve)
    calls: list[Any] = []

    def scripted(spec):
        calls.append(spec)
        path = urllib.parse.urlsplit(spec.url).path
        if path == "/works":
            return TransportResponse(
                status=200, body=SEARCH_BODY, headers={},
                content_type="application/json")
        return TransportResponse(
            status=200, body=FETCH_BODY, headers={},
            content_type="text/plain")

    monkeypatch.setattr(wiring.http_transport, "request", scripted)
    machinery = replace(wiring.machinery, clock=Clock())
    supply = build_research_egress_supply(
        conn=connection, store=store, clock=lambda: CLOCK,
        project_id=PROJECT, machinery=machinery, allowlist=ALLOWLIST_HOSTS,
        dns_resolve=_public_resolve)
    invoker = CapabilityInvoker(
        registry=supply.registry,
        implementations=supply.implementations,
        clock=Clock(),
        ledger=InMemoryIdempotencyLedger(),
        sandbox_enabled=False)
    plan = plan_capability_plane(
        load_profiles(), supplied=SUPPLIED_CAPABILITY_IDS,
        risks=supplied_capability_risks())
    yield Rig(conn=connection, store=store, invoker=invoker, plan=plan,
              supply=supply, calls=calls)
    connection.close()


def _artifact_rows(conn) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(
        "SELECT * FROM artifacts WHERE artifact_type = 'source_payload' "
        "AND project_id = ?", (PROJECT,))]


def _transition_events(conn) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(
        "SELECT * FROM events WHERE event_type = 'EvidenceTransitionProposed' "
        "ORDER BY rowid")]


def _node_content(execution: MethodologyExecution, kind: str) -> dict[str, Any]:
    nodes = list(execution.store.nodes_of_kind(kind, project_id=PROJECT))
    assert nodes, f"no {kind} node was recorded"
    return dict(nodes[-1][1].content)


def _stage_calls(model: Any, stage: str) -> list[Any]:
    return [request for request in model.calls
            if _stage_of(request) == stage
            and not any(part.origin == "runtime.review"
                        for part in request.prompt)]


# ═══════════════ 1. the schema: optional, bounded, additive ═══════════════


def test_the_stage_vocabulary_gained_exactly_the_two_keys() -> None:
    assert frozenset({
        "stage", "profile", "governance_action", "required",
        "max_ticks", "objective"}) == STAGE_KEYS
    assert MAX_STAGE_TICKS == 5


def test_the_shipped_document_declares_the_budget_and_every_stage_job() -> None:
    config = literature_review()
    assert config.version == "3"
    ticks = {stage.stage: stage.effective_ticks(
        config.termination.max_ticks_per_stage) for stage in config.stages}
    assert ticks == {
        "QUESTION": 1, "HYPOTHESIS": 1, "PREDICTION": 1, "EXPERIMENT": 1,
        "OBSERVATION": 3, "EVIDENCE": 1, "CLAIM": 1, "CRITIQUE": 1,
        "CONCLUSION": 1,
    }
    for stage in config.stages:
        assert stage.objective, f"{stage.stage} declares no objective"
        assert stage.objective == stage.objective.strip()
        assert stage.objective is not None
        assert " " in stage.objective
    observation = next(stage for stage in config.stages
                       if stage.stage == "OBSERVATION")
    assert observation.max_ticks == 3
    # The objective names the causal chain and the order, in plain words.
    text = observation.objective or ""
    assert "Gather first, propose last" in text
    assert "source_search" in text
    assert "source_fetch" in text
    assert "evidence:<artifact_id>" in text
    assert "stop_when: proposals_raised" in text


def test_the_shipped_document_digest_moves_and_the_control_does_not() -> None:
    config = literature_review()
    assert config.digest() == SHIPPED_DIGEST
    assert methodology_identity(config) == "mth_" + SHIPPED_DIGEST[:24]
    assert engineering_investigation().digest() == CONTROL_DIGEST


def test_an_old_form_document_parses_to_no_stage_fields_and_keeps_its_digest(
        ) -> None:
    config = parse_methodology(_old_form_document())
    assert config.version == "1"
    assert config.digest() == OLD_FORM_DIGEST
    for stage in config.stages:
        assert stage.max_ticks is None
        assert stage.objective is None
        assert stage.effective_ticks(config.termination.max_ticks_per_stage) == 1
        mapping = stage.to_mapping()
        assert "max_ticks" not in mapping
        assert "objective" not in mapping
    # The old form's serialized stages carry no new key at all; the two keys a
    # document may omit are the documented defaults, not absent serialization.
    assert config.to_mapping()["stages"] == [
        {"stage": stage["stage"], "profile": stage["profile"],
         "governance_action": stage.get("governance_action", ""),
         "required": True}
        for stage in _old_form_document()["stages"]]


def test_the_shipped_document_round_trips_its_declared_fields() -> None:
    config = literature_review()
    again = parse_methodology(config.to_mapping())
    assert again.to_mapping() == config.to_mapping()
    assert again.digest() == config.digest()


@pytest.mark.parametrize("value", [0, -1, 6, True, 2.0, "3", None])
def test_a_budget_outside_one_to_five_is_refused_never_clamped(
        value: object) -> None:
    document = _old_form_document()
    stages = [dict(stage) for stage in document["stages"]]
    stages[4]["max_ticks"] = value
    document["stages"] = stages
    with pytest.raises(MethodologyConfigError):
        parse_methodology(document)


@pytest.mark.parametrize("value", [1, 5])
def test_a_budget_inside_the_bound_is_accepted(value: int) -> None:
    document = _old_form_document()
    stages = [dict(stage) for stage in document["stages"]]
    stages[4]["max_ticks"] = value
    document["stages"] = stages
    config = parse_methodology(document)
    assert config.stages[4].max_ticks == value
    assert config.termination.limits(config.stages[4].max_ticks).max_ticks == value


@pytest.mark.parametrize("value", ["", "   ", 3, None])
def test_a_declared_objective_must_be_non_empty_text(value: object) -> None:
    document = _old_form_document()
    stages = [dict(stage) for stage in document["stages"]]
    stages[0]["objective"] = value
    document["stages"] = stages
    with pytest.raises(MethodologyConfigError):
        parse_methodology(document)


def test_the_objective_byte_delta_per_stage_is_pinned() -> None:
    config = literature_review()
    measured = {stage.stage: len((stage.objective or "").encode("utf-8"))
                for stage in config.stages}
    assert measured == OBJECTIVE_BYTES
    # The rendered envelope is the canonical document the model reads.
    observation = next(stage for stage in config.stages
                       if stage.stage == "OBSERVATION")
    envelope = canonical_json({"objective": observation.objective})
    assert len(envelope.encode("utf-8")) == 487


# ═══════════════ 2. the stage budget reaches the run ═══════════════


def test_every_stage_projects_its_own_budget_and_inherits_the_rest() -> None:
    config = literature_review()
    projections = stage_projections(
        config, project_id=PROJECT, task_id=TASK, lease_generation="gen-1")
    ticks = {projection.stage: projection.context.limits.max_ticks
             for projection in projections}
    assert ticks["OBSERVATION"] == 3
    assert all(value == 1 for stage, value in ticks.items()
               if stage != "OBSERVATION")
    for projection in projections:
        limits = projection.context.limits
        assert limits.max_proposals == 1        # unchanged: one draft a stage
        assert limits.deadline_seconds == 180.0  # unchanged: the run deadline
        assert limits.max_tool_calls == 0        # unchanged: profile default


def test_a_one_tick_document_projects_one_tick_everywhere() -> None:
    config = parse_methodology(_old_form_document())
    projections = stage_projections(
        config, project_id=PROJECT, task_id=TASK, lease_generation="gen-1")
    assert [projection.context.limits.max_ticks for projection in projections] \
        == [1] * len(config.stages)


def test_a_stage_without_an_objective_projects_no_objective_key() -> None:
    config = parse_methodology(_old_form_document())
    projection = project_stage(
        config, config.stages[0], project_id=PROJECT, task_id=TASK,
        lease_generation="gen-1")
    assert "objective" not in projection.context.payload
    assert set(projection.context.payload) == {
        "stage", "methodology_id", "predecessor_stage"}


def test_the_objective_rides_the_existing_payload_origin() -> None:
    assert PAYLOAD_ORIGIN == "runtime.payload"
    assert TASK_ORIGIN == "runtime.task"
    config = literature_review()
    observation = next(stage for stage in config.stages
                       if stage.stage == "OBSERVATION")
    projection = project_stage(
        config, observation, project_id=PROJECT, task_id=TASK,
        lease_generation="gen-1")
    assert projection.context.payload["objective"] == observation.objective


# ═══════════════ 3. the prompt: objective + budget + causal chain ═══════════════


def test_the_observation_prompt_carries_its_objective_and_its_budget(rig) -> None:
    model = SearchFetchCiteModel()
    execution = rig.run(model)
    assert isinstance(execution, MethodologyExecution), execution

    calls = _stage_calls(model, "OBSERVATION")
    assert len(calls) == 3
    objective = next(stage for stage in literature_review().stages
                     if stage.stage == "OBSERVATION").objective

    first = calls[0]
    assert _tick_of(first) == (1, 3)          # the budget, as the tick marker
    document = _payload_document(first, "objective")
    assert document is not None
    assert document["objective"] == objective
    part = next(part for part in first.prompt
                if part.origin == PAYLOAD_ORIGIN and part.ref.endswith(":objective"))
    assert part.ref == f"{TASK}:OBSERVATION:objective"
    # The objective is untrusted content on the existing origin, not a new one.
    assert part.origin == PAYLOAD_ORIGIN
    assert {item.origin for item in first.prompt} <= {
        PAYLOAD_ORIGIN, TASK_ORIGIN, "runtime.tick"}
    assert [_tick_of(call) for call in calls] == [(1, 3), (2, 3), (3, 3)]


def test_a_stage_without_an_objective_renders_none(rig) -> None:
    config = parse_methodology(_old_form_document())
    model = SilentModel()
    execution = rig.run(model, config=config)
    assert isinstance(execution, MethodologyRefusal), execution
    # A silent run stops at OBSERVATION, not EVIDENCE: it fetched nothing, so
    # it has nothing to cite. The objective-rendering subject is unchanged.
    assert execution.stage == "OBSERVATION"
    for request in model.calls:
        assert _payload_document(request, "objective") is None
        assert all(not part.ref.endswith(":objective") for part in request.prompt)


def test_the_objective_never_reenters_the_prompt_as_chain_content(rig) -> None:
    model = SearchFetchCiteModel()
    execution = rig.run(model)
    assert isinstance(execution, MethodologyExecution), execution
    observation = next(stage for stage in literature_review().stages
                       if stage.stage == "OBSERVATION")
    evidence_calls = _stage_calls(model, "EVIDENCE")
    assert len(evidence_calls) == 1
    request = evidence_calls[0]
    predecessor = _payload_document(request, "predecessor_content")
    assert predecessor is not None
    content = predecessor["predecessor_content"]
    assert "objective" not in content
    assert all(observation.objective not in part.text for part in request.prompt)
    # It is the recorded node content, not the stage configuration.
    assert tuple(content.get("cited_refs", ())) == (model.evidence_ref,)


# ═══════════════ 4. the fetch → cite falsifier ═══════════════


def test_observation_searches_fetches_then_cites_the_fetched_artifact(rig) -> None:
    model = SearchFetchCiteModel()
    execution = rig.run(model)
    assert isinstance(execution, MethodologyExecution), execution
    assert execution.termination == "COMPLETE"
    assert [record.stage for record in execution.stages] == [
        "QUESTION", "HYPOTHESIS", "PREDICTION", "EXPERIMENT", "OBSERVATION",
        "EVIDENCE", "CLAIM", "CRITIQUE", "CONCLUSION"]

    # Three model calls in the one stage: search, fetch, cite.
    calls = _stage_calls(model, "OBSERVATION")
    assert len(calls) == 3
    assert [_tick_of(call) for call in calls] == [(1, 3), (2, 3), (3, 3)]

    # One search dial and one fetch dial hit the scripted edge, and the fetch
    # dialed the row the search delivered (host-rewritten to the API surface).
    assert [urllib.parse.urlsplit(call.url).path for call in rig.calls] == [
        "/works", "/W910000001"]

    # One artifact row, and the model cited exactly it.
    rows = _artifact_rows(rig.conn)
    assert len(rows) == 1
    assert rows[0]["artifact_id"] == FETCH_HASH
    assert model.evidence_ref == f"evidence:{FETCH_HASH}"

    # The gateway admitted the transition; the EVIDENCE node records that ref.
    events = _transition_events(rig.conn)
    assert len(events) == 1
    assert _node_content(execution, "EVIDENCE")["external_ref"] == model.evidence_ref
    assert _node_content(execution, "OBSERVATION")["cited_refs"] == (
        model.evidence_ref,)
    assert _node_content(execution, "CLAIM")["admitted_refs"] == (
        model.evidence_ref,)

    # OPS-5Z3: the EVIDENCE stage's prompt carries the admitted artifact's
    # bytes, bounded — not just its id. The rig wires the composition's reader.
    evidence_call = next(call for call in model.calls
                         if _stage_of(call) == "EVIDENCE")
    evidence_envelopes = [part for part in evidence_call.prompt
                          if part.origin == EVIDENCE_ORIGIN]
    assert len(evidence_envelopes) == 1
    excerpt = json.loads(evidence_envelopes[0].text)["excerpt"]
    assert excerpt["text"] == FETCH_BODY.decode("utf-8")
    assert excerpt["bytes"] == len(FETCH_BODY)
    assert excerpt["truncated"] is False

    reconstruction = execution.reconstruction()
    assert reconstruction.complete() is True

    observation_record = next(record for record in execution.stages
                              if record.stage == "OBSERVATION")
    assert observation_record.termination == Termination.STOP_WHEN.value
    assert observation_record.state == TaskStatus.SUCCEEDED.value


def test_run_40s_reply_now_uses_all_three_ticks_and_cites_the_fetch(rig) -> None:
    """The falsifier: a refused tick-1 transition no longer kills the stage."""
    model = Run40Model()
    execution = rig.run(model)
    assert isinstance(execution, MethodologyExecution), execution

    calls = _stage_calls(model, "OBSERVATION")
    assert len(calls) == 3
    assert [_tick_of(call) for call in calls] == [(1, 3), (2, 3), (3, 3)]
    # The rig now advertises the capabilities the scripted model calls.
    notes = dict(calls[0].output_contract.field_notes)
    assert "source_search" in notes["tool_calls"]
    assert "source_fetch" in notes["tool_calls"]

    # Tick 2's prompt carries the tick-1 spine refusal, so the model can repair
    # the citation instead of repeating it blind.
    assert any("obs-sars-covid-40-brazil-india" in part.text
               for part in calls[1].prompt)

    # One search and one fetch dial hit the scripted edge; the fetch addressed
    # the row the search delivered.
    assert [urllib.parse.urlsplit(call.url).path for call in rig.calls] == [
        "/works", "/W910000001"]
    rows = _artifact_rows(rig.conn)
    assert len(rows) == 1
    assert model.evidence_ref == f"evidence:{FETCH_HASH}"
    assert len(_transition_events(rig.conn)) == 1
    assert _node_content(execution, "EVIDENCE")["external_ref"] == (
        model.evidence_ref)


def test_a_proposal_on_the_first_tick_still_stops_the_stage(rig) -> None:
    """The objective is guidance; the budget is the bound, not the trigger."""
    seeded = rig.fetch_once()
    model = EarlyProposalModel(seeded)
    execution = rig.run(model)
    assert isinstance(execution, MethodologyExecution), execution
    assert execution.termination == "COMPLETE"
    calls = _stage_calls(model, "OBSERVATION")
    assert len(calls) == 1, "a first-tick proposal must end the stage"
    assert _tick_of(calls[0]) == (1, 3)
    assert len(_artifact_rows(rig.conn)) == 1   # the seed only: it never gathered
    record = next(record for record in execution.stages
                  if record.stage == "OBSERVATION")
    assert record.termination == Termination.STOP_WHEN.value
    assert _node_content(execution, "EVIDENCE")["external_ref"] == seeded


def test_a_silent_stage_spends_its_budget_and_terminates(rig) -> None:
    model = SilentModel()
    execution = rig.run(model)
    assert isinstance(execution, MethodologyRefusal), execution
    # The refusal now names the stage that actually failed: OBSERVATION cites
    # nothing, so it cannot be recorded, and EVIDENCE is never reached.
    assert execution.stage == "OBSERVATION"
    assert execution.code == MALFORMED_PAYLOAD
    assert "cites nothing" in execution.detail
    assert len(_stage_calls(model, "OBSERVATION")) == 3
    assert not _transition_events(rig.conn)
    assert _artifact_rows(rig.conn) == []


def test_a_one_tick_stage_behaves_exactly_as_today(rig) -> None:
    config = parse_methodology(_old_form_document())
    model = SilentModel()
    execution = rig.run(model, config=config)
    assert isinstance(execution, MethodologyRefusal), execution
    assert execution.stage == "OBSERVATION"
    # One model call per stage that ran. EVIDENCE is no longer among them: an
    # observation that cites nothing stops the chain where it failed.
    assert [_stage_of(request) for request in model.calls] == [
        "QUESTION", "HYPOTHESIS", "PREDICTION", "EXPERIMENT", "OBSERVATION"]


# ═══════════════ 5. the cost table ═══════════════


def _cost(config: Any, ticks_of: Any) -> tuple[int, int, int, int]:
    profiles = load_profiles()
    stage_calls = nominal_stage = review_calls = nominal_review = 0
    for stage in config.stages:
        ticks = ticks_of(stage)
        profile = profiles[stage.profile]
        stage_calls += ticks * profile.termination.max_model_calls_per_tick
        nominal_stage += ticks
        if profile.review.required and profile.review.reviewer_profile:
            reviewer = profiles[profile.review.reviewer_profile]
            review_ticks = (1 if reviewer.termination.stop_when == "no_proposals"
                            else ticks)
            review_calls += (review_ticks
                             * reviewer.termination.max_model_calls_per_tick)
            nominal_review += 1
    return (stage_calls, review_calls, stage_calls + review_calls,
            nominal_stage + nominal_review)


def test_the_cost_table_is_reproducible_from_the_config() -> None:
    shipped = literature_review()
    old = parse_methodology(_old_form_document())

    today = _cost(old, lambda stage: 1)
    assert today == (16, 11, 27, 16)
    with_budget = _cost(
        shipped,
        lambda stage: shipped.termination.limits(stage.max_ticks).max_ticks)
    assert with_budget == (20, 11, 31, 18)
    # OBSERVATION alone pays the increase: 2 → 6 stage calls, review 2 → 2.
    observation = next(stage for stage in shipped.stages
                       if stage.stage == "OBSERVATION")
    profile = load_profiles()[observation.profile]
    assert 3 * profile.termination.max_model_calls_per_tick == 6
    assert _cost(old, lambda stage: 2) == (32, 14, 46, 25)
    assert _cost(old, lambda stage: 3) == (48, 17, 65, 34)


def test_the_digest_helper_sees_the_same_document() -> None:
    config = literature_review()
    assert digest_of(config.to_mapping()) == config.digest() == SHIPPED_DIGEST
