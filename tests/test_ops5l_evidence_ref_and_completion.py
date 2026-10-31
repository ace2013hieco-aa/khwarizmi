"""OPS-5L — the ref reaches the stage, and a citationless run is not a success.

Run 19 fetched a 33 KB artifact, was refused at ``EVIDENCE`` for citing a claim
ref, and its diagnostic report said ``terminal_state: SUCCEEDED`` with six of
nine stages. Two defects, both pinned here against the real chain (the real OPS-5C
capability supply with a scripted transport, the real gateway, the real substrate,
the real live methodology driver, the real report builder; no network):

1. **the reader gap** — the gateway normalises the observation handle
   (``evidence/<id>``) at admission (OPS-5K), but the evidence selector read the
   *raw* payload and required the colon spelling, so an admitted handle was
   admitted **and ignored** and the ``EVIDENCE`` node was refused for an empty
   ref. The fix is read-side canonicalisation; the gateway and the substrate are
   untouched.
2. **the terminal** — the report derived its terminal from the stage-run states
   alone. Every stage *run* ended ``SUCCEEDED`` (a refused proposal is data, and
   ``stop_when: proposals_raised`` counts raised drafts), so the report said
   success while the driver had returned a refusal and the task row said
   otherwise.

And the new channel: a ``runtime.evidence`` envelope carrying exactly
``{"evidence_ref", "artifact_id"}``, appended from the first stage after an
admission — **absent**, never a "none" sentinel, while there is no admitted ref.

The four falsifiers the design gate names:

- the ``EVIDENCE`` prompt carries ``runtime.evidence`` with the admitted ref, and
  a scripted run citing it is admitted with ``EVIDENCE.external_ref`` = the
  fetched artifact (§1, §2);
- raw ``evidence/<id>`` is admitted **and selected**, and the node carries
  ``evidence:<id>`` (§3);
- the run-19 shape cannot terminate ``SUCCEEDED`` (§6, §7, §10);
- a stage before any admission carries no ``runtime.evidence`` part (§1.3).

What this file deliberately does **not** fix: the latent second path (§8) — a
stage run that ends non-SUCCEEDED after an earlier admission still reached the
handler's ``completed`` branch, because the handler's only gate was a run-level
admission count. That was a task-state semantics change outside this slice; it
was demonstrated and named here, never asserted as correct. **OPS-5M has since
taken it**: §8's test now asserts the task state too, because the defect it was
protecting no longer exists.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from hermes.agents.runtime.assembly import (
    EVIDENCE_ORIGIN,
    PROJECT_INDEX_ORIGIN,
    evidence_envelope,
)
from hermes.agents.runtime.config import load_profiles
from hermes.agents.runtime.types import (
    Admission,
    Proposal,
    ProposalSet,
    TaskStatus,
)
from hermes.agents.runtime.wiring import RuntimeWiring
from hermes.artifacts.store import ArtifactStore
from hermes.cli import _root_task_outcomes, main
from hermes.composition import plan_capability_plane
from hermes.core.intents import Intent, IntentKind
from hermes.eval.live_vector import StageRunSnapshot
from hermes.methodology.substrate import MALFORMED_PAYLOAD
from hermes.methodology.swap_test import chain_inputs
from hermes.methodology.workflows import (
    LITERATURE_REVIEW_DOCUMENT,
    MethodologyRefusal,
    _admitted_evidence_proposal,
    _evidence_ref_of,
    parse_methodology,
)
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    ArtifactRepository,
    ProjectRepository,
    TaskRepository,
)
from hermes.research.capability_supply import (
    SUPPLIED_CAPABILITY_IDS,
    build_research_egress_supply,
    supplied_capability_risks,
)
from hermes.research.chain_refs import RefProvenanceReader
from hermes.research.controller import Controller
from hermes.research.evidence_transitions import (
    EVIDENCE_HANDLE_REF_PREFIX,
    EVIDENCE_REF_PREFIX,
    canonical_evidence_ref,
)
from hermes.research.gateway import apply_intent
from hermes.research.live_fetch import ALLOWLIST_HOSTS, build_live_fetch_wiring
from hermes.research.task_handlers import build_methodology_handler
from hermes.research.task_handlers.methodology_driver import (
    MethodologyExecution,
    _canonical_citation,
)
from hermes.research.task_handlers.methodology_driver import (
    run_methodology as live_run_methodology,
)
from hermes.run_report import NO_EVIDENCE_REASON, build_run_report, write_run_report
from hermes.tools.capabilities.invoke import (
    CapabilityInvoker,
    InMemoryIdempotencyLedger,
)
from hermes.tools.models.router import ModelProposal, ModelRefusal
from hermes.tools.providers.base import RequestSpec, TransportResponse
from tests.test_ops1_live_cli import (
    KEY,
    _anthropic_reply,
    _install_transport,
    _project,
    _status,
)
from tests.test_ops5d_proposal_content import (
    AGENT_EVIDENCE,
    CLOCK,
    FETCH_BODY,
    FETCH_HASH,
    PROJECT,
    QUESTION,
    TASK,
    URL,
    Clock,
    FetchThenCiteModel,
    Rig,
    SilentModel,
    _artifact_entry,
    _proposal,
    _public_resolve,
    _stage_of,
)
from tests.test_ops10_run_report import RUN_DIR, _config, _report_files

#: The nine declared stages of the shipped literature review, in order.
STAGES = ("QUESTION", "HYPOTHESIS", "PREDICTION", "EXPERIMENT", "OBSERVATION",
          "EVIDENCE", "CLAIM", "CRITIQUE", "CONCLUSION")

#: The stages that run after OBSERVATION's admission, so each must see the
#: envelope. OBSERVATION itself cannot: its prompt predates the admission.
AFTER_ADMISSION = ("EVIDENCE", "CLAIM", "CRITIQUE", "CONCLUSION")

HANDLE = f"{EVIDENCE_HANDLE_REF_PREFIX}{FETCH_HASH}"
CANONICAL = f"{EVIDENCE_REF_PREFIX}{FETCH_HASH}"

ENVELOPE_RATIONALE = "the run's admitted evidence ref, read from its own envelope"
HANDLE_RATIONALE = "cite the artifact with the capability plane's handle"
GHOST_CLAIM = "claim:prior-art-sars19/c1"

#: The run-19 shape's own artifact positions, for the CLI-level test.
ARTIFACT_SEED = "e" * 64


def _transition(ref: str, *, from_state: str, to_state: str,
                rationale: str) -> dict[str, Any]:
    return {
        "kind": "EVIDENCE_TRANSITION",
        "rationale": rationale,
        "payload": {
            "evidence_artifact_ref": ref,
            "from_state": from_state,
            "to_state": to_state,
            "rationale": rationale,
        },
    }


# ═══════════════════ prompt-side helpers ═══════════════════


def _is_review(call: Any) -> bool:
    return any(part.origin == "runtime.review" for part in call.prompt)


def _envelope_parts(call: Any) -> tuple[Any, ...]:
    return tuple(part for part in call.prompt if part.origin == EVIDENCE_ORIGIN)


def _envelope_documents(model: Any) -> dict[str, list[dict[str, Any]]]:
    """stage -> the ``runtime.evidence`` documents that stage's prompt carried."""
    found: dict[str, list[dict[str, Any]]] = {}
    for call in model.calls:
        if _is_review(call):
            continue
        stage = _stage_of(call)
        for part in _envelope_parts(call):
            found.setdefault(stage, []).append(json.loads(part.text))
    return found


def _stage_calls(model: Any) -> dict[str, list[Any]]:
    calls: dict[str, list[Any]] = {}
    for call in model.calls:
        if _is_review(call):
            continue
        calls.setdefault(_stage_of(call), []).append(call)
    return calls


def _snapshots(results: list[ProposalSet]) -> list[StageRunSnapshot]:
    return [StageRunSnapshot(
        stage=str(result.task_id).rsplit(":", 1)[-1], result=result)
        for result in results]


# ═══════════════════ scripted models ═══════════════════


class CiteTheEnvelopeModel:
    """Fetch, cite at OBSERVATION, then cite **what the envelope says** at EVIDENCE.

    The falsifier's second half: the ref the run admitted is readable by the
    stage that must cite it, so a scripted stage can quote it back verbatim
    instead of inventing a claim ref.
    """

    def __init__(self) -> None:
        self.calls: list[Any] = []
        self.observed_ref = ""
        self.cited_ref = ""
        self.envelope_document: dict[str, Any] = {}

    def invoke(self, request: Any) -> ModelProposal:
        self.calls.append(request)
        if _is_review(request):
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
            self.observed_ref = EVIDENCE_REF_PREFIX + entry.split(":", 1)[1]
            return _proposal(request, _transition(
                self.observed_ref, from_state="SUPPORTED", to_state="ROBUST",
                rationale="cite the artifact the agent fetched"))
        if stage == "EVIDENCE":
            parts = _envelope_parts(request)
            if len(parts) == 1:
                self.envelope_document = json.loads(parts[0].text)
                self.cited_ref = str(
                    self.envelope_document.get("evidence_ref", ""))
            return _proposal(request, _transition(
                self.cited_ref, from_state="ROBUST", to_state="REPLICATED",
                rationale=ENVELOPE_RATIONALE))
        return _proposal(request, {})


class SlashHandleModel:
    """Cites the capability plane's own handle (``evidence/<id>``) verbatim.

    The gateway admits it (OPS-5K). Before OPS-5L the driver's selector read the
    raw payload, skipped it, and the ``EVIDENCE`` node was refused for an empty
    ref — admitted and ignored. That is the regression this model pins.
    """

    def __init__(self) -> None:
        self.calls: list[Any] = []
        self.cited_ref = ""

    def invoke(self, request: Any) -> ModelProposal:
        self.calls.append(request)
        if _is_review(request):
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
            self.cited_ref = EVIDENCE_HANDLE_REF_PREFIX + entry.split(":", 1)[1]
            return _proposal(request, _transition(
                self.cited_ref, from_state="SUPPORTED", to_state="ROBUST",
                rationale=HANDLE_RATIONALE))
        return _proposal(request, {})


class Run19Model:
    """The run-19 shape: nothing is ever admitted as evidence.

    OBSERVATION proposes the placeholder run 19 wrote; ``EVIDENCE``, holding no
    admitted ref, cites a claim ref. Both are refused by the gateway — refusal is
    data — and each stage still ends ``SUCCEEDED``.
    """

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def invoke(self, request: Any) -> ModelProposal:
        self.calls.append(request)
        if _is_review(request):
            return _proposal(request, {})
        stage = _stage_of(request)
        if stage == "OBSERVATION":
            return _proposal(request, _transition(
                "pending", from_state="SUPPORTED", to_state="ROBUST",
                rationale="I will cite whatever I fetch"))
        if stage == "EVIDENCE":
            return _proposal(request, _transition(
                GHOST_CLAIM, from_state="SUPPORTED", to_state="ROBUST",
                rationale="No admitted evidence id appears in the fragments"))
        return _proposal(request, {})


class StageRefusalModel:
    """The latent second path: an admission, then a terminal model refusal.

    OBSERVATION cites a seeded artifact (a real admission through the one write
    path) and ``EVIDENCE`` returns a refusal the runtime cannot recover from. The
    driver breaks and returns an *execution*, so the handler's only gate — a
    run-level admission count — sees a non-zero number.
    """

    def __init__(self, artifact_id: str) -> None:
        self.calls: list[Any] = []
        self.artifact_id = artifact_id

    def invoke(self, request: Any) -> Any:
        self.calls.append(request)
        if _is_review(request):
            return _proposal(request, {})
        stage = _stage_of(request)
        if stage == "OBSERVATION":
            return _proposal(request, _transition(
                f"{EVIDENCE_REF_PREFIX}{self.artifact_id}",
                from_state="SUPPORTED", to_state="ROBUST",
                rationale="cite the seeded row"))
        if stage == "EVIDENCE":
            return ModelRefusal(code="PROPOSAL",
                                detail="scripted terminal refusal at EVIDENCE")
        return _proposal(request, {
            "kind": "INSERT_TASK", "rationale": "one ordinary task",
            "payload": {"spec": {"goal": "stage output"}}})


class _EmptyIdModel:
    """OBSERVATION's transition cites ``evidence:`` with no artifact id."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def invoke(self, request: Any) -> ModelProposal:
        self.calls.append(request)
        if _is_review(request):
            return _proposal(request, {})
        if _stage_of(request) == "OBSERVATION":
            return _proposal(request, _transition(
                EVIDENCE_REF_PREFIX, from_state="SUPPORTED", to_state="ROBUST",
                rationale="an id nobody can dereference"))
        return _proposal(request, {})


# ═══════════════════ fixture: the real capability supply ═══════════════════


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The OPS-5D rig, rebuilt here so this file cannot be softened by its host."""
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: CLOCK).create(PROJECT, "OPS-5L")
    store = ArtifactStore(
        str(tmp_path / "store"), ArtifactRepository(conn, lambda: CLOCK),
        clock=lambda: CLOCK)
    wiring = build_live_fetch_wiring(
        conn, store, lambda: CLOCK, dns_resolve=_public_resolve)

    def scripted(spec: Any) -> TransportResponse:
        return TransportResponse(status=200, body=FETCH_BODY, headers={},
                                 content_type="text/plain")

    monkeypatch.setattr(wiring.http_transport, "request", scripted)
    machinery = replace(wiring.machinery, clock=Clock())
    supply = build_research_egress_supply(
        conn=conn, store=store, clock=lambda: CLOCK, project_id=PROJECT,
        machinery=machinery, allowlist=ALLOWLIST_HOSTS,
        dns_resolve=_public_resolve)
    invoker = CapabilityInvoker(
        registry=supply.registry, implementations=supply.implementations,
        clock=Clock(), ledger=InMemoryIdempotencyLedger(), sandbox_enabled=False)
    plan = plan_capability_plane(
        load_profiles(), supplied=SUPPLIED_CAPABILITY_IDS,
        risks=supplied_capability_risks())
    yield Rig(conn=conn, store=store, invoker=invoker, plan=plan)
    conn.close()


def _nodes(execution: MethodologyExecution, kind: str) -> list[tuple[str, Any]]:
    return list(execution.store.nodes_of_kind(kind, project_id=PROJECT))


def _transition_events(conn: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(
        "SELECT * FROM events WHERE event_type = "
        "'EvidenceTransitionProposed' ORDER BY rowid")]


# ═══════════════ 1. the runtime.evidence envelope ═══════════════


def test_the_evidence_prompt_carries_the_admitted_ref(rig: Rig) -> None:
    """Falsifier 1, first half: the ref the run admitted is in the prompt."""
    model = FetchThenCiteModel()
    execution = rig.run(model)
    assert isinstance(execution, MethodologyExecution), execution
    assert model.evidence_ref == AGENT_EVIDENCE

    call = _stage_calls(model)["EVIDENCE"][-1]
    parts = _envelope_parts(call)
    assert len(parts) == 1, "the evidence envelope is not exactly one part"
    part = parts[0]
    assert part.origin == EVIDENCE_ORIGIN == "runtime.evidence"
    assert part.ref == f"{TASK}:EVIDENCE:evidence"
    assert json.loads(part.text) == {
        "artifact_id": FETCH_HASH, "evidence_ref": AGENT_EVIDENCE}

    # Bounded by construction: two short strings. No content, no provider, no
    # URL, no state rung, no rationale — nothing a validator could read as a
    # directive or a second admissibility claim.
    assert set(json.loads(part.text)) == {"evidence_ref", "artifact_id"}
    assert len(part.text.encode("utf-8")) < 4_096
    assert URL not in part.text
    assert "SUPPORTED" not in part.text
    assert "openalex" not in part.text


def test_the_envelope_rides_every_stage_after_the_admission(
        rig: Rig) -> None:
    """It is a run-level fact: every later stage reads the same value."""
    model = FetchThenCiteModel()
    execution = rig.run(model)
    assert isinstance(execution, MethodologyExecution)

    documents = _envelope_documents(model)
    for stage in AFTER_ADMISSION:
        assert documents.get(stage), f"{stage} carries no evidence envelope"
        assert {d["evidence_ref"] for d in documents[stage]} == {AGENT_EVIDENCE}
        assert {d["artifact_id"] for d in documents[stage]} == {FETCH_HASH}
        # one part per stage run, never two competing shapes
        for call in _stage_calls(model)[stage]:
            assert len(_envelope_parts(call)) == 1


def test_a_stage_before_the_admission_carries_no_envelope(rig: Rig) -> None:
    """Falsifier 4: absent, never a "none" sentinel, before any admission."""
    model = FetchThenCiteModel()
    execution = rig.run(model)
    assert isinstance(execution, MethodologyExecution)

    documents = _envelope_documents(model)
    for stage in ("QUESTION", "HYPOTHESIS", "PREDICTION", "EXPERIMENT",
                  "OBSERVATION"):
        assert stage not in documents, f"{stage} carries an envelope too early"

    # The admitting stage cannot see its own admission: the prompt predates it.
    for call in _stage_calls(model)["OBSERVATION"]:
        assert _envelope_parts(call) == ()

    # Its position in the assembled prompt is deterministic: after the project
    # index, before the payload parts.
    call = _stage_calls(model)["EVIDENCE"][-1]
    origins = [part.origin for part in call.prompt]
    position = origins.index(EVIDENCE_ORIGIN)
    assert position > origins.index(PROJECT_INDEX_ORIGIN)
    assert all(origin != EVIDENCE_ORIGIN for origin in origins[position + 1:])


def test_a_run_with_no_admitted_ref_has_no_envelope_anywhere(rig: Rig) -> None:
    """No admission means no value to render — including at EVIDENCE itself."""
    for model in (SilentModel(), Run19Model()):
        execution = rig.run(model)
        assert isinstance(execution, MethodologyRefusal), execution
        # The stop moved to OBSERVATION: with no admitted ref there is nothing
        # to cite, so the observation itself cannot be recorded.
        assert execution.stage == "OBSERVATION"
        assert execution.source == "substrate"
        assert execution.code == MALFORMED_PAYLOAD
        assert "cites nothing" in execution.detail
        assert _envelope_documents(model) == {}
        for call in model.calls:
            assert _envelope_parts(call) == ()


def test_a_refusal_is_still_data_after_the_envelope_lands(rig: Rig) -> None:
    """The envelope changes what a stage can read, never what a stage may do.

    Run 19's EVIDENCE refusal is kept: an ``EVIDENCE`` stage that cites a claim
    ref is refused by the gateway, and the run stops on the substrate's own rule.
    A surfaces a ref; it does not create one and it does not relax a check.
    """
    model = Run19Model()
    execution = rig.run(model)
    assert isinstance(execution, MethodologyRefusal)
    assert not _transition_events(rig.conn)
    assert _envelope_documents(model) == {}


# ═══════════════ 2. citing the envelope is admitted and recorded ═══════════════


def test_a_stage_citing_the_envelope_ref_is_admitted_and_recorded(
        rig: Rig) -> None:
    """Falsifier 1, second half: read the ref, cite it, the node carries it."""
    model = CiteTheEnvelopeModel()
    collected: list[ProposalSet] = []
    execution = rig.run(model, on_stage=lambda _w, r: collected.append(r))
    assert isinstance(execution, MethodologyExecution), execution
    assert execution.termination == "COMPLETE"
    assert len(execution.stages) == len(STAGES)

    # The EVIDENCE stage quoted the envelope verbatim.
    assert model.envelope_document == {
        "evidence_ref": AGENT_EVIDENCE, "artifact_id": FETCH_HASH}
    assert model.cited_ref == AGENT_EVIDENCE

    evidence = _nodes(execution, "EVIDENCE")
    assert len(evidence) == 1
    _node_id, node = evidence[0]
    assert node.content["external_ref"] == AGENT_EVIDENCE
    assert ENVELOPE_RATIONALE in node.rationale

    # The second transition is a fresh admission, not a duplicate: a different
    # rung on the same artifact is a different transition identity.
    admitted = [proposal for result in collected
                for proposal in result.admitted()
                if proposal.intent.kind == IntentKind.EVIDENCE_TRANSITION]
    assert len(admitted) == 2
    assert [p.admission for p in admitted] == [Admission.ADMITTED.value] * 2
    assert [str(p.intent.payload["from_state"]) for p in admitted] == [
        "SUPPORTED", "ROBUST"]

    events = _transition_events(rig.conn)
    assert len(events) == 2
    assert [json.loads(row["payload_json"])["evidence_artifact_ref"]
            for row in events] == [AGENT_EVIDENCE, AGENT_EVIDENCE]


def test_an_admission_at_evidence_itself_reaches_the_later_stages(
        rig: Rig) -> None:
    """The pinned one-stage lag: absent in its own stage, present from CLAIM on."""
    model = CiteTheEnvelopeModel()
    execution = rig.run(model)
    assert isinstance(execution, MethodologyExecution)

    documents = _envelope_documents(model)
    # OBSERVATION admitted first, so EVIDENCE already carries it here; the lag
    # is one stage, never zero and never hidden.
    assert documents["EVIDENCE"][0]["evidence_ref"] == AGENT_EVIDENCE
    for stage in ("CLAIM", "CRITIQUE", "CONCLUSION"):
        assert {d["evidence_ref"] for d in documents[stage]} == {AGENT_EVIDENCE}


# ═══════════════ 3. the reader gap: an admitted handle is selected ═══════════


def test_an_admitted_handle_is_selected_and_the_node_is_canonical(
        rig: Rig) -> None:
    """Falsifier 2: raw ``evidence/<id>`` is admitted **and selected**.

    Before OPS-5L this run admitted the handle and ignored it: the selector
    required the colon spelling in the raw payload, ``evidence_ref`` stayed
    empty, and the ``EVIDENCE`` node was refused.
    """
    model = SlashHandleModel()
    execution = rig.run(model)
    assert model.cited_ref == HANDLE
    assert isinstance(execution, MethodologyExecution), (
        f"the admitted handle selected as nothing: {execution}")
    assert execution.termination == "COMPLETE"
    assert len(execution.stages) == len(STAGES)

    # The node carries the canonical spelling, not the handle the model wrote.
    _node_id, node = _nodes(execution, "EVIDENCE")[0]
    assert node.content["external_ref"] == CANONICAL
    assert EVIDENCE_HANDLE_REF_PREFIX not in str(dict(node.content))

    # The same canonical ref flows through every place it is read, so one
    # artifact keeps one reference.
    _obs_id, observation = _nodes(execution, "OBSERVATION")[0]
    assert observation.content["cited_refs"] == (CANONICAL,)
    _claim_id, claim = _nodes(execution, "CLAIM")[0]
    assert claim.content["admitted_refs"] == (CANONICAL,)
    documents = _envelope_documents(model)
    assert {d["evidence_ref"] for d in documents["EVIDENCE"]} == {CANONICAL}

    # The gateway's own event was already canonical (OPS-5K): the reader was the
    # missing half, not the writer.
    events = _transition_events(rig.conn)
    assert len(events) == 1
    assert json.loads(events[-1]["payload_json"])[
        "evidence_artifact_ref"] == CANONICAL


def _proposal_for(ref: str, *, admission: str = Admission.ADMITTED.value
                  ) -> Proposal:
    return Proposal(
        intent=Intent(kind=IntentKind.EVIDENCE_TRANSITION,
                      proposed_by="RESEARCHER", project_id=PROJECT,
                      payload={"evidence_artifact_ref": ref,
                               "from_state": "SUPPORTED", "to_state": "ROBUST",
                               "rationale": "scripted"}),
        rationale="scripted", tick=1, profile="researcher",
        agent_profile="RESEARCHER", lease_generation="gen",
        admission=admission)


def test_the_selector_canonicalises_an_admitted_handle() -> None:
    """The unit behind it: an injected grammar, never a second artifact check."""
    handle = _proposal_for(f"{EVIDENCE_HANDLE_REF_PREFIX}art-1")
    colon = _proposal_for(f"{EVIDENCE_REF_PREFIX}art-1")
    claim = _proposal_for("claim:c1")

    # With the research plane's canonicaliser (what the live driver injects),
    # the handle selects, and reads back canonical.
    assert _admitted_evidence_proposal(
        (handle,), canonicalise=canonical_evidence_ref) is handle
    assert _evidence_ref_of(
        handle, canonicalise=canonical_evidence_ref) == f"{EVIDENCE_REF_PREFIX}art-1"

    # A ref that is no evidence ref at all still selects as nothing.
    assert _admitted_evidence_proposal(
        (claim,), canonicalise=canonical_evidence_ref) is None
    assert _evidence_ref_of(claim, canonicalise=canonical_evidence_ref) == ""

    # The latest admitted one still wins.
    assert _admitted_evidence_proposal(
        (handle, colon), canonicalise=canonical_evidence_ref) is colon


def test_the_plane_default_keeps_its_colon_only_reading() -> None:
    """Recorded, out of scope: the plane's own driver never sees a handle.

    ``hermes.methodology.workflows.run_methodology`` (the reference/swap driver)
    has no capability plane, so its default keeps the historical colon-only
    reading. OPS-5L fixes the *live* driver's reader; it does not silently widen
    the plane's default, which is why this is a pin rather than a behaviour.
    """
    handle = _proposal_for(f"{EVIDENCE_HANDLE_REF_PREFIX}art-1")
    colon = _proposal_for(f"{EVIDENCE_REF_PREFIX}art-1")

    assert _admitted_evidence_proposal((handle,)) is None
    assert _admitted_evidence_proposal((colon,)) is colon
    assert _evidence_ref_of(_admitted_evidence_proposal((colon,))) == (
        f"{EVIDENCE_REF_PREFIX}art-1")


def test_a_refused_handle_never_selects() -> None:
    """Admission is the gate: a refusal is data, not an evidence ref."""
    refused = _proposal_for(HANDLE, admission=Admission.REFUSED.value)
    assert _admitted_evidence_proposal(
        (refused,), canonicalise=canonical_evidence_ref) is None
    assert _admitted_evidence_proposal(
        (refused,)) is None


# ═══════════════ 4. the empty-id guard (injection-only shape) ═══════════════


@pytest.mark.parametrize("ref", [EVIDENCE_REF_PREFIX, EVIDENCE_HANDLE_REF_PREFIX])
def test_the_guard_maps_a_canonicaliser_that_names_no_artifact(ref: str) -> None:
    """``canonical_evidence_ref`` maps ``evidence/`` to ``evidence:``; we don't.

    The real gateway refuses an empty id (``MALFORMED_PAYLOAD``, OPS-5K), so this
    shape is reachable only behind an injected applier. Left as a selected ref it
    would raise inside the next stage's envelope; the guard makes it select as no
    admitted ref instead, so the run stops on the substrate's own refusal.
    """
    assert canonical_evidence_ref(ref) == EVIDENCE_REF_PREFIX
    assert _canonical_citation(ref) is None
    assert _canonical_citation(f"{ref}art-1") == f"{EVIDENCE_REF_PREFIX}art-1"
    assert _canonical_citation("claim:c1") is None
    assert _canonical_citation("") is None


def test_an_admitted_empty_id_ref_stops_the_run_without_raising() -> None:
    """Through the real runtime, with an applier that admits anything."""
    model = _EmptyIdModel()
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: CLOCK).create(PROJECT, "OPS-5L")

    class _Applied:
        def __init__(self) -> None:
            self.entity_id = "ent-ops5l"
            self.duplicate = False

    def grant(intent: Intent) -> _Applied:
        return _Applied()

    try:
        wiring = RuntimeWiring(
            model=model, orchestration=grant, lease_generation="gen-ops5l",
            profiles=load_profiles(), clock=lambda: CLOCK)
        collected: list[ProposalSet] = []
        execution = live_run_methodology(
            parse_methodology(dict(LITERATURE_REVIEW_DOCUMENT)),
            chain_inputs(PROJECT, QUESTION), wiring=wiring,
            project_id=PROJECT, task_id=TASK,
            on_stage=lambda _w, r: collected.append(r),
            provenance_of=RefProvenanceReader(conn))
    finally:
        conn.close()

    # No ValueError from the envelope: the empty id selects as nothing.
    assert isinstance(execution, MethodologyRefusal), execution
    assert execution.source == "substrate"
    assert "cites nothing" in execution.detail
    assert _envelope_documents(model) == {}
    # The admission really happened — the reader declined it, the spine did not.
    assert any(p.was_admitted() for r in collected
               for p in r.proposals if p.intent.kind == IntentKind.EVIDENCE_TRANSITION)


# ═══════════════ 5. the envelope's own guard ═══════════════


@pytest.mark.parametrize("ref", [
    "evidence:", "evidence/", "claim:c1", "", "Evidence:abc", "evidence~abc",
])
def test_the_envelope_refuses_a_non_canonical_ref(ref: str) -> None:
    """A half-document is a programming error, not a prompt to render."""
    with pytest.raises(ValueError, match="canonical"):
        evidence_envelope(task_id=f"{TASK}:EVIDENCE", evidence_ref=ref)


def test_the_envelope_is_pure_and_derives_the_artifact_id() -> None:
    first = evidence_envelope(task_id=f"{TASK}:EVIDENCE", evidence_ref=CANONICAL)
    second = evidence_envelope(task_id=f"{TASK}:EVIDENCE", evidence_ref=CANONICAL)
    assert first == second
    assert json.loads(first.text) == {
        "artifact_id": FETCH_HASH, "evidence_ref": CANONICAL}
    assert first.ref == f"{TASK}:EVIDENCE:evidence"
    assert first.origin == EVIDENCE_ORIGIN


# ═══════════════ 6. the run-19 shape cannot report success ═══════════════


def test_the_run_19_shape_reports_failed_without_a_task_outcome(
        rig: Rig) -> None:
    """Falsifier 3 at the driver level.

    Every stage *run* ends SUCCEEDED — exactly why the old rule said success. The
    backstop reads the admitted proposals' *kind*, so a review child's
    INSERT_TASK cannot mask the missing evidence.
    """
    model = Run19Model()
    collected: list[ProposalSet] = []
    execution = rig.run(model, on_stage=lambda _w, r: collected.append(r))
    assert isinstance(execution, MethodologyRefusal)
    assert execution.stage == "OBSERVATION"
    assert execution.source == "substrate"

    # Five of nine stage runs happened, and each one is SUCCEEDED. EVIDENCE no
    # longer runs: an observation that cites nothing stops the chain first.
    assert [str(r.task_id).rsplit(":", 1)[-1] for r in collected] == list(
        STAGES[:5])
    assert [r.state for r in collected] == [TaskStatus.SUCCEEDED.value] * 5
    # The only admissions are bookkeeping: no EVIDENCE_TRANSITION anywhere.
    assert all(p.intent.kind != IntentKind.EVIDENCE_TRANSITION
               for r in collected for p in r.admitted())

    report = build_run_report(
        run_id="run_ops5l", project_id=PROJECT, started_at=CLOCK, ticks=3,
        stage_runs=_snapshots(collected), ledger=(), notes=(), vector="")
    assert report["terminal_state"] == "FAILED"
    assert report["terminal_reason"] == NO_EVIDENCE_REASON
    assert "EVIDENCE_TRANSITION" in report["terminal_reason"]
    # Five stage runs: the chain stopped at OBSERVATION, so EVIDENCE never ran.
    # The terminal is still FAILED — a run with no admitted transition has no
    # evidence, whether or not it reached the stage that would have cited it.
    assert len(report["stages"]) == 5


def _result(stage: str, *, state: str = TaskStatus.SUCCEEDED.value,
            termination: str = "STOP_WHEN",
            kinds: tuple[str, ...] = ()) -> ProposalSet:
    """One synthetic stage run — the report's own input surface."""
    proposals = tuple(_proposal_of(kind) for kind in kinds)
    return ProposalSet(
        run_id=f"run-{stage}", profile="researcher",
        agent_profile="RESEARCHER", task_id=f"{TASK}:{stage}",
        project_id=PROJECT, lease_generation="gen", state=state,
        termination=termination, ticks=1, proposals=proposals)


def _proposal_of(kind: str) -> Proposal:
    payload: dict[str, Any] = {"spec": {"goal": "stage output"}}
    if kind == "EVIDENCE_TRANSITION":
        payload = {"evidence_artifact_ref": AGENT_EVIDENCE,
                   "from_state": "SUPPORTED", "to_state": "ROBUST",
                   "rationale": "the fetched source"}
    return Proposal(
        intent=Intent(kind=IntentKind(kind), proposed_by="RESEARCHER",
                      project_id=PROJECT, payload=payload),
        rationale="scripted", tick=1, profile="researcher",
        agent_profile="RESEARCHER", lease_generation="gen",
        admission=Admission.ADMITTED.value)


def _evidenced(stage: str, **kw: Any) -> ProposalSet:
    return _result(stage, kinds=("EVIDENCE_TRANSITION",), **kw)


def test_the_report_terminal_reads_the_task_record_not_the_stage_states() -> None:
    """The task row, not the stage runs, decides the terminal and says why."""
    report = build_run_report(
        run_id="run_ops5l", project_id=PROJECT, started_at=CLOCK, ticks=1,
        stage_runs=_snapshots([_result("QUESTION"), _evidenced("EVIDENCE")]),
        ledger=(), notes=(), vector="",
        task_outcomes=({"task_id": TASK, "state": "FAILED",
                        "reason": "MALFORMED_PAYLOAD: a EVIDENCE node"},))
    assert report["terminal_state"] == "FAILED"
    assert report["terminal_reason"] == "MALFORMED_PAYLOAD: a EVIDENCE node"


def test_a_quarantined_run_outranks_the_task_record() -> None:
    """The OPS-10 rule survives, at the top of the precedence."""
    report = build_run_report(
        run_id="run_ops5l", project_id=PROJECT, started_at=CLOCK, ticks=1,
        stage_runs=_snapshots([_evidenced("EVIDENCE")]), ledger=(),
        notes=("task t-meth quarantined after 3 failed attempts",), vector="",
        task_outcomes=({"task_id": TASK, "state": "FAILED",
                        "reason": "a lower-ranked reason"},))
    assert report["terminal_state"] == "QUARANTINED"
    assert "quarantin" in report["terminal_reason"].lower()
    assert report["quarantine_reason"]


def test_a_genuine_success_is_still_reported_as_success() -> None:
    """The fix must not fail closed on the good path."""
    report = build_run_report(
        run_id="run_ops5l", project_id=PROJECT, started_at=CLOCK, ticks=9,
        stage_runs=_snapshots([
            _result(stage, kinds=("EVIDENCE_TRANSITION",)
                    if stage in ("OBSERVATION", "EVIDENCE") else ())
            for stage in STAGES]),
        ledger=(), notes=(), vector="",
        task_outcomes=({"task_id": TASK, "state": "SUCCEEDED", "reason": ""},))
    assert report["terminal_state"] == "SUCCEEDED"
    assert report["terminal_reason"] == ""
    assert len(report["stages"]) == 9


def test_a_succeeded_task_with_no_admitted_evidence_is_still_failed() -> None:
    """The stage data can veto a task outcome, never promote one."""
    report = build_run_report(
        run_id="run_ops5l", project_id=PROJECT, started_at=CLOCK, ticks=9,
        stage_runs=_snapshots([_result(stage) for stage in STAGES]),
        ledger=(), notes=(), vector="",
        task_outcomes=({"task_id": TASK, "state": "SUCCEEDED", "reason": ""},))
    assert report["terminal_state"] == "FAILED"
    assert report["terminal_reason"] == NO_EVIDENCE_REASON


def test_a_failed_task_with_no_reason_on_file_says_so() -> None:
    report = build_run_report(
        run_id="run_ops5l", project_id=PROJECT, started_at=CLOCK, ticks=1,
        stage_runs=_snapshots([_evidenced("EVIDENCE")]), ledger=(), notes=(),
        vector="",
        task_outcomes=({"task_id": TASK, "state": "FAILED", "reason": ""},))
    assert report["terminal_state"] == "FAILED"
    assert report["terminal_reason"] == (
        f"root task {TASK!r} ended FAILED with no FAILED reason on file")


def test_a_non_succeeded_stage_names_the_stage_that_stopped() -> None:
    """With evidence admitted, a failed stage is reported as itself."""
    report = build_run_report(
        run_id="run_ops5l", project_id=PROJECT, started_at=CLOCK, ticks=3,
        stage_runs=_snapshots([
            _result("QUESTION"), _evidenced("EVIDENCE"),
            _result("CRITIQUE", state=TaskStatus.FAILED.value,
                    termination="MODEL_REFUSED")]),
        ledger=(), notes=(), vector="")
    assert report["terminal_state"] == "FAILED"
    assert report["terminal_reason"] == (
        "stage CRITIQUE ended FAILED (MODEL_REFUSED)")


def test_a_run_with_no_stage_runs_and_no_outcome_says_so() -> None:
    report = build_run_report(
        run_id="run_ops5l", project_id=PROJECT, started_at=CLOCK, ticks=0,
        stage_runs=(), ledger=(), notes=(), vector="")
    assert report["terminal_state"] == "NO_STAGE_RUNS"
    assert report["terminal_reason"] == ""


def test_a_long_terminal_reason_is_bounded() -> None:
    reason = "x" * 5_000
    report = build_run_report(
        run_id="run_ops5l", project_id=PROJECT, started_at=CLOCK, ticks=1,
        stage_runs=_snapshots([_evidenced("EVIDENCE")]), ledger=(), notes=(),
        vector="", excerpt_bytes=128,
        task_outcomes=({"task_id": TASK, "state": "FAILED", "reason": reason},))
    assert len(report["terminal_reason"].encode("utf-8")) <= 128
    assert report["terminal_reason"] != reason


def test_the_bounded_report_keeps_the_terminal_reason(tmp_path: Path) -> None:
    """The truncation path keeps the one field an operator reads first."""
    report = build_run_report(
        run_id="run_ops5l_cap", project_id=PROJECT, started_at=CLOCK, ticks=1,
        stage_runs=_snapshots([_evidenced("EVIDENCE")]), ledger=(), notes=(),
        vector="",
        task_outcomes=({"task_id": TASK, "state": "FAILED",
                        "reason": "MALFORMED_PAYLOAD: the bounded reason"},))
    report["refusals"] = [{"code": "MALFORMED_PAYLOAD", "detail": "x" * 500,
                           "profile": "planner", "tick": 1, "stage": "EVIDENCE",
                           "excerpt": "y" * 2_000} for _ in range(1_000)]
    path = write_run_report(tmp_path / "cap.json", report, max_bytes=4_096)
    fitted = json.loads(path.read_bytes())
    assert fitted["truncated"] is True
    assert fitted["terminal_state"] == "FAILED"
    assert fitted["terminal_reason"] == "MALFORMED_PAYLOAD: the bounded reason"


# ═══════════════ 7. the whole way down: the Controller's own dispatch ═════════


def _spine() -> Any:
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: CLOCK).create(PROJECT, "OPS-5L")
    ArtifactRepository(conn, lambda: CLOCK).record(
        artifact_id=ARTIFACT_SEED, artifact_type="source_payload",
        content_hash=ARTIFACT_SEED, size_bytes=1,
        storage_path=f"seed/{ARTIFACT_SEED}",
        producer="capability:source_fetch:test", project_id=PROJECT)
    return conn


def _admit(conn: Any, task_id: str) -> str:
    inputs = chain_inputs(PROJECT, QUESTION)
    result = apply_intent(conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id=PROJECT,
        payload={
            "task_id": task_id,
            "task_type": "AGENT_TASK",
            "spec": {"template": "methodology_run",
                     "methodology": dict(LITERATURE_REVIEW_DOCUMENT),
                     "inputs": {"question": inputs.question,
                                "stage_content": dict(inputs.stage_content)}},
            "idempotency_key": f"idem-{task_id}",
            "iteration": 1, "provenance": [], "inputs": [], "outputs": [],
            "dependencies": [], "cost_class": "LOW",
        }), clock=lambda: CLOCK)
    return result.entity_id


def _task_status(conn: Any, task_id: str) -> str:
    return TaskRepository(conn).get_status(task_id).value


def test_the_controller_dispatch_of_the_run_19_shape_fails_with_a_reason() -> None:
    """The task row never says success, and the report mirrors it.

    The handler returns ``failed_typed`` (the driver's refusal), the controller
    retries rather than succeeds the task, and the report carries the task's own
    FAILED reason — the substrate's sentence, not a generic one.
    """
    conn = _spine()
    try:
        collected: list[ProposalSet] = []
        handler = build_methodology_handler(
            model=Run19Model(), profiles=load_profiles(),
            on_stage=lambda _w, r: collected.append(r),
            provenance_of=RefProvenanceReader(conn))
        ctrl = Controller(conn, project_id=PROJECT,
                          task_handlers={"methodology_run": handler},
                          clock=lambda: CLOCK)
        task_id = _admit(conn, "t-ops5l-19")

        out = ctrl.tick()

        assert out.dispatched == [task_id]
        assert out.succeeded == []
        assert out.retried == [task_id]
        assert _task_status(conn, task_id) == TaskStatus.RETRYING.value

        snapshots = _snapshots(collected)
        outcomes = _root_task_outcomes(conn, PROJECT, snapshots)
        assert [o["task_id"] for o in outcomes] == ["t-ops5l-19"]
        assert outcomes[0]["state"] == TaskStatus.RETRYING.value
        assert outcomes[0]["reason"].startswith(
            "MALFORMED_PAYLOAD: an OBSERVATION node cites nothing")

        report = build_run_report(
            run_id="run_ops5l_ctrl", project_id=PROJECT, started_at=CLOCK,
            ticks=1, stage_runs=snapshots, ledger=(), notes=list(ctrl.notes),
            vector="", task_outcomes=outcomes)
        assert report["terminal_state"] == "FAILED"
        assert report["terminal_reason"].startswith(
            "MALFORMED_PAYLOAD: an OBSERVATION node cites nothing")
    finally:
        conn.close()


def test_the_report_read_is_project_scoped_and_fails_closed_to_empty() -> None:
    """A root outside the run's project is not read; a bad read is not a crash."""
    conn = _spine()
    try:
        collected: list[ProposalSet] = []
        handler = build_methodology_handler(
            model=Run19Model(), profiles=load_profiles(),
            on_stage=lambda _w, r: collected.append(r),
            provenance_of=RefProvenanceReader(conn))
        ctrl = Controller(conn, project_id=PROJECT,
                          task_handlers={"methodology_run": handler},
                          clock=lambda: CLOCK)
        task_id = _admit(conn, "t-ops5l-scope")
        ctrl.tick()
        snapshots = _snapshots(collected)

        assert _root_task_outcomes(conn, "p-not-this-one", snapshots) == ()
        assert _root_task_outcomes(conn, PROJECT, ()) == ()
        # A root that is not a task at all raises inside the helper and returns
        # (): the report then falls back to its stage-only terminal, and a
        # report read never fails a run.
        invented = StageRunSnapshot(stage="QUESTION", result=_result("QUESTION"))
        assert _root_task_outcomes(conn, PROJECT, (invented,)) == ()
        assert len(_root_task_outcomes(conn, PROJECT, snapshots)) == 1
        assert task_id == "t-ops5l-scope"
    finally:
        conn.close()


# ═══════════ 8. the latent second path: named here, fixed by OPS-5M ═══════════


def test_a_stage_refusal_after_an_admission_is_reported_failed() -> None:
    """The second path OPS-5L found and left; OPS-5M closed it.

    A stage run that ends non-SUCCEEDED after an earlier admission makes the
    driver return an *execution*, and the handler's only gate was a run-level
    admission count — so the task reached SUCCEEDED with the chain half
    recorded. OPS-5L named it and recommended
    ``execution.termination != "COMPLETE"`` as the handler's second gate; OPS-5M
    landed that gate (``tests/test_ops5m_truncated_chain.py``).

    So this test now asserts **both** halves: the row is not a success, and the
    report mirrors it. Before OPS-5M the row assertion would have failed — that
    is exactly why it was withheld, and why it can be made now.
    """
    conn = _spine()
    try:
        collected: list[ProposalSet] = []
        handler = build_methodology_handler(
            model=StageRefusalModel(ARTIFACT_SEED), profiles=load_profiles(),
            on_stage=lambda _w, r: collected.append(r),
            provenance_of=RefProvenanceReader(conn))
        ctrl = Controller(conn, project_id=PROJECT,
                          task_handlers={"methodology_run": handler},
                          clock=lambda: CLOCK)
        task_id = _admit(conn, "t-ops5l-latent")

        out = ctrl.tick()

        # The row: a truncated chain never reaches SUCCEEDED. The handler's
        # failed_typed verdict is retried, not succeeded.
        assert out.succeeded == []
        assert out.retried == [task_id]
        assert _task_status(conn, task_id) == TaskStatus.RETRYING.value

        snapshots = _snapshots(collected)
        outcomes = _root_task_outcomes(conn, PROJECT, snapshots)
        report = build_run_report(
            run_id="run_ops5l_latent", project_id=PROJECT, started_at=CLOCK,
            ticks=1, stage_runs=snapshots, ledger=(), notes=list(ctrl.notes),
            vector="", task_outcomes=outcomes)

        # The evidence the follow-up slice needed: the chain did not complete,
        # and a stage run did not succeed — so the stage-only rule alone was not
        # enough, and the record is what the report must read.
        assert [r.state for r in collected][-1] != TaskStatus.SUCCEEDED.value
        assert report["terminal_state"] != "SUCCEEDED"
        assert report["terminal_state"] == "FAILED"
        assert report["terminal_reason"]
        # And the reason the row now carries is the new gate's, not S6-B2's:
        # an admission happened, so the run was never effectless.
        assert "OPS-5M" in outcomes[0]["reason"]
        assert "S6-B2" not in outcomes[0]["reason"]
    finally:
        conn.close()


# ═══════════════ 9. import discipline for the one new dependency ═══════════════


def test_the_citation_grammar_module_has_no_write_surface() -> None:
    """OPS-5L's one new driver import is a pure vocabulary module.

    ``test_wiring_w3.py`` widens the driver's allowed import set with
    ``hermes.research.evidence_transitions``; this is the reason it is safe: the
    module imports ``__future__`` and ``enum`` and nothing else — no repository,
    no connection, no gateway — so it cannot become a second validation path.
    """
    import hermes.research.evidence_transitions as module

    tree = ast.parse(Path(str(module.__file__)).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    assert imported == {"__future__", "enum"}


def test_the_live_driver_still_has_no_second_artifact_row_check() -> None:
    """The canonicaliser is a string shape, never a dereference."""
    import hermes.methodology.workflows as plane_module
    import hermes.research.task_handlers.methodology_driver as live_module

    for module in (plane_module, live_module):
        source = Path(str(module.__file__)).read_text(encoding="utf-8")
        assert "ArtifactRepository" not in source
        assert "in_project" not in source
        assert "SELECT 1 FROM artifacts" not in source
    assert "canonical_evidence_ref" in Path(
        str(live_module.__file__)).read_text(encoding="utf-8")


# ═══════════════ 10. the live CLI, end to end ═══════════════════


STAGE_MARKER = re.compile(r'\\"stage\\":\\"([A-Z]+)\\"')


def _run19_reply(stage: str) -> str:
    """The run-19 wire replies, in the live path's single-proposal form."""
    if stage == "OBSERVATION":
        return json.dumps(_transition(
            "pending", from_state="SUPPORTED", to_state="ROBUST",
            rationale="I will cite whatever I fetch"))
    if stage == "EVIDENCE":
        return json.dumps(_transition(
            GHOST_CLAIM, from_state="SUPPORTED", to_state="ROBUST",
            rationale="No admitted evidence id appears in the fragments"))
    return json.dumps({"rationale": "one ordinary task", "kind": "INSERT_TASK",
                       "payload": {"spec": {"goal": "stage output"}}})


class _Run19Transport:
    """The scripted provider edge: replies by stage, and counts evidence parts."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, int]] = []

    def request(self, spec: RequestSpec) -> TransportResponse:
        body = spec.body.decode("utf-8") if spec.body else ""
        stages = STAGE_MARKER.findall(body)
        stage = stages[0] if stages else ""
        self.requests.append((stage, body.count("runtime.evidence")))
        return _anthropic_reply(_run19_reply(stage))


def test_the_live_cli_of_the_run_19_shape_says_failed_with_a_reason(
        tmp_path: Path, capsys: Any, monkeypatch: Any) -> None:
    """The Director's run, at the surface an operator actually reads.

    Six stages, each SUCCEEDED, the CLI's own line reporting zero successes, and
    the report it writes naming the substrate's refusal. It is the report that
    lied in run 19, so the report is what this test reads.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    transport = _Run19Transport()
    _install_transport(monkeypatch, transport)
    task = ("meth-19", "AGENT_TASK", "RESEARCHER", {
        "template": "methodology_run",
        "methodology": dict(LITERATURE_REVIEW_DOCUMENT),
        "inputs": {"question": "does it hold?",
                   "stage_content": dict(
                       chain_inputs("p1", QUESTION).stage_content)},
    })
    db = _project(tmp_path, task)
    report_dir = tmp_path / RUN_DIR
    cfg = _config(tmp_path, db, tiers={"m": "anthropic:test-model"},
                  run_dir=report_dir)

    rc = main(["--config", str(cfg), "run", "p1", "--ticks", "1"])
    captured = capsys.readouterr()

    assert rc == 0
    assert "0 succeeded" in captured.out
    assert "report: " in captured.out

    # The record and the diagnostic agree. Run 19's row had exhausted its
    # attempts and read FAILED; this fixture gets one tick with retries left, so
    # the row is RETRYING — either way it is not SUCCEEDED, which is the half
    # that was missing: the report, not the row, was the liar.
    assert _status(db, "meth-19") != TaskStatus.SUCCEEDED.value
    assert _status(db, "meth-19") == TaskStatus.RETRYING.value

    files = _report_files(report_dir)
    assert len(files) == 1
    report = json.loads(files[0].read_text(encoding="utf-8"))

    assert report["terminal_state"] == "FAILED"
    assert report["terminal_reason"].startswith(
        "MALFORMED_PAYLOAD: an OBSERVATION node cites nothing")
    assert [stage["stage"] for stage in report["stages"]] == list(STAGES[:5])
    assert all(stage["state"] == TaskStatus.SUCCEEDED.value
               for stage in report["stages"])
    assert report["stages"][-1]["stage"] == "OBSERVATION"
    # The old assertion read the *last* stage's admission count, which only
    # worked while the chain still reached EVIDENCE and that stage admitted
    # nothing. The last stage is now OBSERVATION, which admits bookkeeping
    # intents — and the report carries counts, not kinds, so the absence of an
    # EVIDENCE_TRANSITION is asserted where it can be read: the driver-level
    # sibling test checks the admitted proposals' kind directly.

    # No admitted ref, so no envelope — the run holds nothing to surface.
    assert all(count == 0 for _stage, count in transport.requests)
    assert KEY not in files[0].read_text(encoding="utf-8")
