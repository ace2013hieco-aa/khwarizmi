"""OPS-5Z5 — one text model, and a gate that is actually called.

The integration audit's reproduction, on the real 33,727-byte OpenAlex record:

    claim "The COVID-19 model considered 2 transmission scenarios."
    check_claim(raw JSON, subjects=("COVID-19",))   -> GROUNDED  (level:2)
    check_claim(semantic_text, same subjects)       -> REFUSED
    evidence_inspect                                -> 0 figures, 0 dates

Three consumers, three answers. This file is the falsification of the fix:

* the three consumers read the same content (the seam is closed);
* ``"The COVID-19 work is 3087879971."`` is not grounded — an identifier is
  not a quantity, on the content *and* on the serialization;
* a claim quoting the reconstructed abstract is grounded (the control against
  "refuse everything");
* a claim asserting a figure the abstract does not contain is refused;
* the incident is refused **through the methodology CLAIM path**, by the
  driver, before the claim node is written;
* an artifact whose abstract cannot be reconstructed produces a verdict a
  caller can distinguish from "the source states nothing".

The inputs are the real bytes served by the real fetch capability, the real
artifact store, the real gateway and the real live methodology driver. No
network, no model.

The false-refusal measurement is here too: every sentence of the reconstructed
abstract, asserted as a claim, is grounded; paraphrases are caveated, not
refused. Nothing correct is refused.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from hermes.agents.runtime.assembly import (
    PROJECT_INDEX_ORIGIN,
    evidence_envelope,
)
from hermes.agents.runtime.config import load_profiles
from hermes.agents.runtime.wiring import RuntimeWiring
from hermes.artifacts.store import ArtifactStore
from hermes.composition import plan_capability_plane
from hermes.methodology.substrate import SubstrateNode
from hermes.methodology.swap_test import CHAIN_STATEMENTS, chain_inputs
from hermes.methodology.workflows import (
    LITERATURE_REVIEW_DOCUMENT,
    MethodologyInputs,
    MethodologyRefusal,
    parse_methodology,
)
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    ArtifactRepository,
    ProjectRepository,
)
from hermes.research.capability_supply import (
    FALSIFICATION_TOOL_SET_ID,
    INSPECT_CONTENT_UNREADABLE,
    SUPPLIED_CAPABILITY_IDS,
    build_research_egress_supply,
    supplied_capability_risks,
)
from hermes.research.chain_refs import RefProvenanceReader
from hermes.research.gateway import apply_intent
from hermes.research.grounding import (
    CaveatCode,
    RefusalCode,
    check_claim,
    figures_in,
)
from hermes.research.live_fetch import ALLOWLIST_HOSTS, build_live_fetch_wiring
from hermes.research.project_index import ProjectIndexReader
from hermes.research.task_handlers.methodology_driver import (
    MethodologyExecution,
)
from hermes.research.task_handlers.methodology_driver import (
    run_methodology as live_run_methodology,
)
from hermes.tools.capabilities.content import (
    ArtifactRead,
    read_content,
    semantic_text,
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

CLOCK = "2026-10-30T12:00:00.000000+00:00"
PROJECT = "p-ops5z5"
TASK = "task-ops5z5"
QUESTION = "does the source support the claim?"
URL = "https://openalex.org/W3087879971"
PROFILE = "ADVERSARY"

FIXTURES = Path(__file__).parent / "fixtures" / "source_payloads"
OPENALEX_WORK = FIXTURES / "openalex_work_33727.json"

INCIDENT = "The COVID-19 model considered 2 transmission scenarios."
IDENTIFIER = "The COVID-19 work is 3087879971."
CONTROL = (
    "When a novel infectious disease emerges, enhanced contact tracing and "
    "isolation are implemented to prevent a major epidemic, and indeed, they "
    "have been successful for the control of severe acute respiratory "
    "syndrome (SARS) and Middle East respiratory syndrome (MERS), which have "
    "been greatly reduced without causing a global pandemic.")
SUBJECTS = ("COVID-19",)

#: A record whose abstract index exists but names two words for one slot. The
#: content model refuses to invent a sentence and says the abstract could not
#: be reconstructed; the title is still readable.
UNREADABLE = json.dumps({
    "title": "A record whose abstract cannot be rebuilt",
    "abstract_inverted_index": {"two": [0], "words": [0]},
}).encode("utf-8")


class Clock:
    def now_utc(self) -> str:
        return CLOCK

    def monotonic(self) -> float:
        return 1000.0

    def sleep(self, delay: float) -> None:
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
                    and str(entry.get("id", "")).startswith(
                        "source_payload:")):
                return str(entry["id"])
    return ""


class FetchThenCiteModel:
    """Fetch the source in HYPOTHESIS; cite it in OBSERVATION.

    The shipped document allows one tick per stage, so the fetch and the
    citation cannot share a tick. The artifact appears in the project index
    the OBSERVATION run reads, and that run cites it as evidence.
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


@dataclass
class Rig:
    conn: Any
    store: ArtifactStore
    invoker: CapabilityInvoker
    plan: Any

    def claim_inputs(self, statement: str,
                     subjects: tuple[str, ...] = SUBJECTS,
                     ) -> MethodologyInputs:
        claim: dict[str, Any] = {"statement": statement}
        if subjects:
            claim["subjects"] = list(subjects)
        return replace(chain_inputs(PROJECT, QUESTION), stage_content={
            **CHAIN_STATEMENTS, "CLAIM": claim})

    def artifact_reader(self, project_id: str,
                        artifact_id: str) -> ArtifactRead | None:
        repo = ArtifactRepository(self.conn, lambda: CLOCK)
        if not repo.in_project(artifact_id, project_id):
            return None
        row = repo.get(artifact_id)
        try:
            data = self.store.read_verified(row["content_hash"])
        except FileNotFoundError:
            return None
        metadata = row.get("metadata") or {}
        declared = metadata.get("content_format")
        return ArtifactRead(
            data=bytes(data),
            format=declared if isinstance(declared, str) else "")

    def run(self, model: Any, inputs: MethodologyInputs,
            on_stage: Any = None,
            ) -> MethodologyExecution | MethodologyRefusal:
        wiring = RuntimeWiring(
            model=model,
            orchestration=lambda intent: apply_intent(self.conn, intent),
            lease_generation="lease-ops5z5",
            profiles=load_profiles(),
            grants=self.plan.grants,
            capabilities=self.invoker,
            clock=lambda: CLOCK)
        return live_run_methodology(
            parse_methodology(dict(LITERATURE_REVIEW_DOCUMENT)),
            inputs,
            wiring=wiring,
            project_id=PROJECT,
            task_id=TASK,
            project_index=ProjectIndexReader(self.conn),
            on_stage=on_stage,
            provenance_of=RefProvenanceReader(self.conn),
            artifact_reader=self.artifact_reader)

    def inspect(self, ref: str, *, key: str) -> Observation:
        result = self.invoker.invoke(InvokeRequest(
            capability_id="evidence_inspect",
            arguments={"ref": ref},
            idempotency_key=key,
            lease_generation="lease-ops5z5",
            profile=PROFILE,
            rationale="read what the artifact states, by rule",
            grant=ToolGrant(
                grant_id="grant.ops5z5",
                profile=PROFILE,
                tool_set_ids=frozenset({FALSIFICATION_TOOL_SET_ID}),
                max_risk=RiskLevel.LOW.value),
            deadline_seconds=10.0))
        assert isinstance(result, Observation), result
        return result


def _fixture_rig(tmp_path: Path, monkeypatch, body: bytes,
                 content_type: str = "application/json") -> Rig:
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: CLOCK).create(PROJECT, "OPS-5Z5")
    store = ArtifactStore(
        str(tmp_path / "store"), ArtifactRepository(conn, lambda: CLOCK),
        clock=lambda: CLOCK)
    wiring = build_live_fetch_wiring(
        conn, store, lambda: CLOCK, dns_resolve=_public_resolve)

    def scripted(spec):
        return TransportResponse(
            status=200, body=body, headers={}, content_type=content_type)

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
        risks=supplied_capability_risks())
    return Rig(conn=conn, store=store, invoker=invoker, plan=plan)


@pytest.fixture
def real_rig(tmp_path, monkeypatch):
    rig = _fixture_rig(tmp_path, monkeypatch, OPENALEX_WORK.read_bytes())
    yield rig
    rig.conn.close()


@pytest.fixture
def unreadable_rig(tmp_path, monkeypatch):
    rig = _fixture_rig(tmp_path, monkeypatch, UNREADABLE,
                      content_type="application/json")
    yield rig
    rig.conn.close()


def _nodes(execution: MethodologyExecution, kind: str
           ) -> list[tuple[str, SubstrateNode]]:
    return list(execution.store.nodes_of_kind(kind, project_id=PROJECT))


# ═══════════════ 1. the three consumers agree ═══════════════


def test_the_three_consumers_read_the_same_content(real_rig) -> None:
    """Envelope, gate and capability over the real record: one text, one answer."""
    raw = OPENALEX_WORK.read_bytes()
    content = semantic_text(raw, format="openalex").text
    read = read_content(raw, format="openalex")
    assert read.state == "content"
    assert read.fields == ("title", "display_name", "abstract")
    assert read.text == content

    # The envelope renders that very text.
    envelope = evidence_envelope(
        task_id=f"{TASK}:EVIDENCE", evidence_ref="evidence:" + "a" * 64,
        artifact_bytes=raw, artifact_format="openalex")
    excerpt = json.loads(envelope.text)["excerpt"]
    assert excerpt["text"] == content
    assert excerpt["read"] == "content"
    assert excerpt["format"] == "openalex"

    # The gate sees 0 figures in the content — not the 299 the serialized
    # record carries. (The audit measured 299 with the old tokeniser; the
    # quoted-JSON rule now drops serialized identifiers too, but the
    # serialization is still full of numbers the prose does not state.)
    assert len(figures_in(raw.decode("utf-8", "replace"))) > 100
    assert figures_in(content) == ()

    # The capability reads the same content through the real executor. The
    # run uses the grounded control claim so the chain reaches its end and the
    # artifact stays citable.
    model = FetchThenCiteModel()
    execution = real_rig.run(model, real_rig.claim_inputs(CONTROL,
                                                         subjects=()))
    assert isinstance(execution, MethodologyExecution), execution
    entry = _nodes(execution, "OBSERVATION")[0][1].content["cited_refs"][0]
    artifact_id = str(entry).partition(":")[2]
    observation = real_rig.inspect(f"evidence/{artifact_id}",
                                   key="inspect-real")
    payload = json.loads(observation.payload.text)
    assert payload["facts"]["figures"] == []
    assert payload["facts"]["dates"] == []
    assert payload["read"] == {"read": "content", "format": "openalex",
                               "fields": ["title", "display_name", "abstract"],
                               "detail": ""}
    # Capability tokens and gate tokens agree: both empty. The two readers
    # cannot report different figures for the same bytes.
    assert [figure.raw for figure in figures_in(content)] == [
        figure["literal"] for figure in payload["facts"]["figures"]]


# ═══════════════ 2. an identifier is not a quantity ═══════════════


def test_the_openalex_id_is_not_grounded(real_rig) -> None:
    raw = OPENALEX_WORK.read_bytes()
    content = semantic_text(raw, format="openalex").text

    for name, text in (("content", content),
                       ("serialization", raw.decode("utf-8", "replace"))):
        verdict = check_claim(IDENTIFIER, text, subjects=SUBJECTS)
        assert verdict.grounded is False, (name, verdict)
        assert verdict.refusal is RefusalCode.ASSERTION_NOT_FOUND, (name,
                                                                    verdict)

    # The rule that makes the serialization safe too: a quoted JSON scalar is
    # a field value, not prose. The claim's own numeral is not quoted.
    assert figures_in('"mag":"3087879971"') == ()
    assert [figure.raw for figure in figures_in(
        "The work is 3087879971.")] == ["3087879971"]


# ═══════════════ 3. the control: a quotation is grounded ═══════════════


def test_a_claim_quoting_the_abstract_is_grounded(real_rig) -> None:
    content = semantic_text(OPENALEX_WORK.read_bytes(), format="openalex").text
    verdict = check_claim(CONTROL, content, subjects=SUBJECTS)
    assert verdict.grounded is True, verdict.detail
    assert verdict.refusal is None and verdict.caveat is None

    # The same claim through the CLAIM stage: the chain completes and the
    # stage records the gate's verdict. A qualitative quotation binds no
    # figure, so a declared subject list neither refuses the correct claim nor
    # is recorded as if it bound something.
    model = FetchThenCiteModel()
    execution = real_rig.run(model, real_rig.claim_inputs(CONTROL))
    assert isinstance(execution, MethodologyExecution), execution
    assert execution.termination == "COMPLETE"
    claim_node = _nodes(execution, "CLAIM")[0][1]
    assert "subjects" not in claim_node.content
    record = next(stage for stage in execution.stages
                  if stage.stage == "CLAIM")
    assert record.grounding is not None
    assert record.grounding.verdict == "GROUNDED"
    assert record.grounding.code == ""

    # The verdict reaches the journal's structured channel: the handler token
    # and the depth payload, not only the stage mapping.
    from hermes.research.controller import _handler_depth_details
    from hermes.research.source_handlers import HandlerResult
    from hermes.research.task_handlers import _grounding_token

    token, detail = _grounding_token(execution)
    assert token == "GROUNDED"
    assert detail.startswith("grounded")
    assert "verbatim" in detail
    details = _handler_depth_details(
        HandlerResult(status="completed", grounding=token))
    assert details is not None and details["grounding"] == "GROUNDED"


# ═══════════════ 4. a figure the abstract does not contain is refused ═══════


def test_a_figure_the_abstract_does_not_state_is_refused(real_rig) -> None:
    content = semantic_text(OPENALEX_WORK.read_bytes(), format="openalex").text
    verdict = check_claim(INCIDENT, content, subjects=SUBJECTS)
    assert verdict.grounded is False
    assert verdict.refusal is RefusalCode.ASSERTION_NOT_FOUND
    assert "COVID-19 2" in verdict.detail


# ═══════════════ 5. the gate refuses the incident end to end ═══════════════


def test_the_incident_is_refused_through_the_methodology_claim_path(
        real_rig) -> None:
    model = FetchThenCiteModel()
    outcome = real_rig.run(model, real_rig.claim_inputs(INCIDENT))

    assert isinstance(outcome, MethodologyRefusal), outcome
    assert outcome.stage == "CLAIM"
    assert outcome.source == "grounding"
    assert outcome.code == RefusalCode.ASSERTION_NOT_FOUND.value
    assert "assertion_not_found" in outcome.detail
    assert "COVID-19 2" in outcome.detail
    # The chain stopped before the claim: six stages recorded, no CLAIM node.
    assert outcome.stages_recorded == 6
    assert outcome.stages_declared == 9

    # The refusal is a real driver result, not a direct check_claim call: the
    # claim never became a node.
    assert model.evidence_ref.startswith("evidence:")


# ═══════════════ 6. a failed read is visible ═══════════════


def test_a_malformed_abstract_is_a_named_read_failure() -> None:
    read = read_content(UNREADABLE, format="openalex")
    # The title was read, so what it extracted is content; the detail names
    # the part that could not be reconstructed, and `partial` makes it visible.
    assert read.state == "content"
    assert read.partial is True
    assert read.fields == ("title",)
    assert "abstract index" in read.detail

    sentence = "The COVID-19 model considered 2 transmission scenarios."
    # Without the read status the gate blames the claim (assertion not found);
    # with it, the same bytes produce a caveat that says the reader could not
    # read them. The two verdicts are different codes, not different prose.
    blamed = check_claim(sentence, read.text, subjects=SUBJECTS)
    assert blamed.refusal is RefusalCode.ASSERTION_NOT_FOUND
    unread = check_claim(sentence, read.text, subjects=SUBJECTS,
                         unreadable_detail=read.detail)
    assert unread.refusal is None
    assert unread.caveat is CaveatCode.SOURCE_NOT_READABLE
    assert "abstract index" in unread.detail


def test_evidence_inspect_says_what_it_could_not_read(unreadable_rig) -> None:
    # Fetch the malformed record through the real fetch path: the failing read
    # is the subject, and the artifact backing stays FETCHED (a claimed ROW
    # artifact is refused by the substrate before the gate matters).
    model = FetchThenCiteModel()
    execution = unreadable_rig.run(
        model, unreadable_rig.claim_inputs(INCIDENT))
    # The run completes with a caveat, never a grounded claim.
    assert isinstance(execution, MethodologyExecution), execution
    claim_record = next(stage for stage in execution.stages
                        if stage.stage == "CLAIM")
    assert claim_record.grounding is not None
    assert claim_record.grounding.verdict == "CAVEATED"
    assert claim_record.grounding.code == CaveatCode.SOURCE_NOT_READABLE.value
    from hermes.research.task_handlers import _grounding_token
    token, detail = _grounding_token(execution)
    assert token == "CAVEATED:source_not_readable"
    assert "abstract index" in detail

    entry = _nodes(execution, "OBSERVATION")[0][1].content["cited_refs"][0]
    artifact_id = str(entry).partition(":")[2]
    observation = unreadable_rig.inspect(
        f"evidence/{artifact_id}", key="inspect-unreadable")
    payload = json.loads(observation.payload.text)
    assert payload["read"]["read"] == "content"
    assert payload["read"]["format"] == "openalex"
    assert payload["read"]["fields"] == ["title"]
    assert "abstract index" in payload["read"]["detail"]
    # The note scopes its negative: "in the text that could be read", not a
    # bare "nothing was found" over an artifact it could not read.
    assert "in the text that could be read" in observation.detail
    assert "read: title" in observation.detail
    assert "abstract index" in observation.detail


def test_evidence_inspect_refuses_an_unreadable_artifact(
        tmp_path, monkeypatch) -> None:
    rig = _fixture_rig(tmp_path, monkeypatch, b'{"id": "W1"}')
    try:
        # A *declared* format with no content field is unreadable: the
        # provider promised a shape the reader models and did not deliver it.
        # (An undeclared serialization would be a fallback — legible, never
        # mined — not a refusal.)
        row = rig.store.write(
            b'{"id": "W1"}', "source_payload", "test.ops5z5",
            project_id=PROJECT, artifact_id="art-no-content",
            metadata={"content_format": "openalex"})
        observation = rig.inspect(f"evidence/{row['artifact_id']}",
                                  key="inspect-no-content")
        payload = json.loads(observation.payload.text)
        assert payload["status"] == "REFUSED"
        assert payload["code"] == INSPECT_CONTENT_UNREADABLE
        assert "could not be read" in observation.detail
    finally:
        rig.conn.close()


def test_a_missing_artifact_read_is_marked_in_the_envelope(real_rig) -> None:
    """A wired read that returns nothing is not the ref-only envelope."""
    model = FetchThenCiteModel()
    deleted: list[str] = []

    def after_stage(wiring: Any, result: Any) -> None:
        if not str(getattr(result, "task_id", "")).endswith(":EVIDENCE"):
            return
        if deleted:
            return
        row = real_rig.conn.execute(
            "SELECT storage_path FROM artifacts WHERE project_id = ? "
            "AND artifact_type = 'source_payload'", (PROJECT,)).fetchone()
        assert row is not None
        path = Path(str(real_rig.store._root)) / str(row["storage_path"])
        path.unlink()
        deleted.append(str(row["storage_path"]))

    execution = real_rig.run(model, real_rig.claim_inputs(INCIDENT),
                             on_stage=after_stage)
    assert isinstance(execution, MethodologyExecution), execution
    assert deleted
    claim_record = next(stage for stage in execution.stages
                        if stage.stage == "CLAIM")
    assert claim_record.grounding is not None
    # The gate could not read bytes, so it caveats "nothing checked" rather
    # than refusing the claim or pretending the source is silent.
    assert claim_record.grounding.verdict == "CAVEATED"
    assert claim_record.grounding.code == CaveatCode.UNCHECKED_NO_BYTES.value

    claim_prompt = next(call for call in model.calls
                        if _stage_of(call) == "CLAIM")
    documents = [json.loads(part.text) for part in claim_prompt.prompt
                 if part.origin == "runtime.evidence"]
    excerpt = documents[-1]["excerpt"]
    assert excerpt["read"] == "unreadable"
    assert "could not be read" in excerpt["detail"]


def test_the_envelope_and_extraction_view_mark_a_fallback_never_as_prose() -> None:
    """A blob may be shown; it is labelled, and it is never mined."""
    from hermes.research.source_handlers import UntrustedContentView

    raw = OPENALEX_WORK.read_bytes()
    # With the format the fetch path declares, the view shows the content.
    declared = UntrustedContentView(
        _load_search_results=lambda _: [],
        _read_payload=lambda ref: raw,
        _read_payload_format=lambda ref: "openalex")
    content = declared.fetched_text("source_payload:" + "a" * 64)
    assert content is not None
    assert content.origin == "fetched"
    assert content.text == semantic_text(raw, format="openalex").text
    assert '"abstract_inverted_index"' not in content.text

    # Without it, the raw serialization is still returned — a model can read a
    # blob, and dropping the source was a cost with no safety benefit — under
    # a distinct origin that says it is a fallback.
    undeclared = UntrustedContentView(
        _load_search_results=lambda _: [],
        _read_payload=lambda ref: raw)
    fallback = undeclared.fetched_text("source_payload:" + "a" * 64)
    assert fallback is not None
    assert fallback.origin == "fetched.fallback"
    assert fallback.text == raw.decode("utf-8", "replace")

    # The envelope renders a partial read and says it is partial.
    partial = json.loads(evidence_envelope(
        task_id="t:EVIDENCE", evidence_ref="evidence:" + "a" * 64,
        artifact_bytes=UNREADABLE,
        artifact_format="openalex").text)["excerpt"]
    assert partial["read"] == "content"
    assert partial["fields"] == ["title"]
    assert "abstract index" in partial["detail"]

    # An undeclared serialization is a fallback: shown, marked, never mined.
    fallback_doc = json.loads(evidence_envelope(
        task_id="t:EVIDENCE", evidence_ref="evidence:" + "a" * 64,
        artifact_bytes=b'{"id": "W1"}').text)["excerpt"]
    assert fallback_doc["read"] == "fallback"
    assert fallback_doc["text"] == '{"id": "W1"}'
    assert "JSON serialization" in fallback_doc["detail"]

    # A declared format that does not deliver its shape is unreadable: the
    # detail names why, and the bytes are still shown — labelled — rather than
    # dropping the source the run fetched.
    empty = json.loads(evidence_envelope(
        task_id="t:EVIDENCE", evidence_ref="evidence:" + "a" * 64,
        artifact_bytes=b'{"id": "W1"}',
        artifact_format="openalex").text)["excerpt"]
    assert empty["read"] == "unreadable"
    assert empty["text"] == '{"id": "W1"}'
    assert "no content field" in empty["detail"]


# ═══════════════ the subjects field is validated ═══════════════


def test_a_malformed_subjects_field_is_refused() -> None:
    from hermes.research.task_handlers.methodology_driver import (
        _claim_subjects,
    )

    def subjects_inputs(values: Any) -> MethodologyInputs:
        return replace(chain_inputs(PROJECT, QUESTION), stage_content={
            **CHAIN_STATEMENTS,
            "CLAIM": {"statement": INCIDENT, "subjects": values}})

    for values in ("COVID-19", 7, [""], ["COVID-19", 3], [1, 2]):
        refused = _claim_subjects(subjects_inputs(values), INCIDENT)
        assert isinstance(refused, MethodologyRefusal), (values, refused)
        assert refused.code == "MALFORMED_PAYLOAD"

    # A subject the claim never names cannot bind a figure; accepting it would
    # pretend to a check that check_claim would not perform.
    not_named = _claim_subjects(subjects_inputs(["Brazil"]), INCIDENT)
    assert isinstance(not_named, MethodologyRefusal)
    assert "does not occur" in not_named.detail

    too_many = _claim_subjects(
        subjects_inputs([f"COVID-19-{index}" for index in range(33)]),
        INCIDENT)
    assert isinstance(too_many, MethodologyRefusal)

    # A well-formed field is stripped, de-duplicated, and returned in order.
    accepted = _claim_subjects(
        subjects_inputs(["  COVID-19 ", "COVID-19"]), INCIDENT)
    assert accepted == ("COVID-19",)


def test_an_unnameable_subject_stops_the_claim_path(real_rig) -> None:
    model = FetchThenCiteModel()
    outcome = real_rig.run(
        model, real_rig.claim_inputs(INCIDENT, subjects=("Brazil",)))
    assert isinstance(outcome, MethodologyRefusal), outcome
    assert outcome.stage == "CLAIM"
    assert outcome.source == "grounding"
    assert outcome.code == "MALFORMED_PAYLOAD"
    assert "does not occur" in outcome.detail
    assert outcome.stages_recorded == 6


def test_only_a_claim_may_declare_subjects() -> None:
    from hermes.methodology.substrate import (
        SubstrateNode,
        SubstrateRefusal,
        SubstrateStore,
        write_node,
    )

    store = SubstrateStore()
    node = SubstrateNode(
        kind="HYPOTHESIS", project_id="p-ops5z5",
        producing_task_id="t:HYPOTHESIS",
        content={"statement": "The effect holds.", "origin": "MINTED",
                 "subjects": ["effect"]},
        rationale="a conjecture declares no figure subjects")
    refused = write_node(store, node)
    assert isinstance(refused, SubstrateRefusal)
    assert refused.code == "MALFORMED_PAYLOAD"
    assert "only a CLAIM" in refused.detail


# ═══════════════ the controller's two prose seams ═══════════════


def test_the_controller_seams_read_content_not_serialization() -> None:
    """G9's stored text and the span fallback resolve against the content.

    The audit's corroborating false refusal: a quote from the envelope's own
    excerpt was INVALID — ``statement_not_in_source`` — because the stored
    bytes were the serialized record. The same reader now answers both the
    quote check and the span check.
    """
    from hermes.research.controller import _content_text, _span_in_content

    raw = OPENALEX_WORK.read_bytes()
    quoted = ("they have been successful for the control of severe acute "
              "respiratory syndrome (SARS)")
    stored = _content_text(raw, "openalex")
    assert stored is not None and quoted in stored      # after: prose
    assert quoted not in raw.decode("utf-8", "replace")  # before: inverted index

    assert _span_in_content(raw, "openalex", "contact tracing") is True
    # A span in the serialized record — a metadata key — is not verifiable
    # against what the model was shown.
    assert _span_in_content(raw, "openalex", '"publication_date"') is False

    # A partial read still answers for the fields it read; a fallback with no
    # readable field resolves nothing (fail closed).
    assert _content_text(UNREADABLE, "openalex") == read_content(
        UNREADABLE, format="openalex").text
    assert _span_in_content(UNREADABLE, "openalex", "cannot be rebuilt") is True
    assert _content_text(b'{"id": "W1"}') is None
    assert _span_in_content(b'{"id": "W1"}', "", "id") is False


# ═══════════════ the false-refusal measurement ═══════════════


def test_no_correct_claim_about_the_abstract_is_refused() -> None:
    content = semantic_text(OPENALEX_WORK.read_bytes(), format="openalex").text
    abstract = content.split("\n\n")[-1]
    sentences = [sentence.strip() for sentence in re.split(
        r"(?<=\.)\s+", abstract) if len(sentence.split()) >= 5]
    assert len(sentences) >= 5

    verdicts = [check_claim(sentence, content, subjects=SUBJECTS)
                for sentence in sentences]
    refused = [sentence for sentence, verdict in zip(sentences, verdicts)
               if verdict.refusal is not None]
    assert refused == []
    assert all(verdict.grounded for verdict in verdicts), [
        (sentence, verdict) for sentence, verdict in zip(sentences, verdicts)
        if not verdict.grounded]

    # Correct paraphrases are admissible: caveated, never refused. The gate
    # does not pretend to judge paraphrase, and it does not punish it either.
    paraphrases = [
        "Contact tracing and isolation controlled SARS and MERS.",
        "Asymptomatic transmission makes containment harder.",
        "The study uses a two-type branching process.",
        "Untraced cases lower the feasibility of containment.",
        "Swift isolation only prevents later secondary transmission.",
    ]
    for paraphrase in paraphrases:
        verdict = check_claim(paraphrase, content, subjects=SUBJECTS)
        assert verdict.grounded is False
        assert verdict.refusal is None, (paraphrase, verdict)
        assert verdict.caveat is CaveatCode.NO_CHECKABLE_ASSERTION
