"""OPS-5Z Group E — a conflict is a reason to investigate, not a verdict.

The incident's critic asked for the primary WHO figures and the runtime refused
``REQUEST_ADDITIONAL_EXPERIMENT`` with ``NOT_WIRED``. This file is the
falsification of the repair: a conflict opens one bounded round, the spine
fetches the primary source, the content gate refuses a challenge page, and the
round's terminal record names the conflict that caused it.

The chain is the real methodology driver over the real runtime, gateway,
capability supply and artifact store. The model is scripted; the fetch is the
capability plane's ``source_fetch`` over a transport that serves the primary
snapshot, a contradictory snapshot, or the real cookie wall.

The incident's two claims, as the audit records them (``AUDIT-OPS-5Z-SLICE``
D2 and ``AUDIT-INTEGRATION`` §4.4): claim[1] transcribes the fetched 18
September snapshot (India 5,275,035 / Brazil 4,467,433), claim[3] is the
qualitative "Brazil was ahead of India". They do **not** share a source — the
figures come from the fetched artifact, the ordering names none — so the
incident's mode is ``verify-one``. The ``parallel-two`` falsifier pins the
other branch of the split with two claims that do share a source.

Falsifiers:

1. a conflict opens a round (the journal's OPENED event names the conflict);
2. no conflict, no round;
3. a round that does not settle it ends DISPUTED, and a persistent conflict is
   refused a second round by the one-round budget;
4. verify-one fetches the primary, and the real cookie wall is refused by the
   content gate — never cited;
5. parallel-two produces two branches, one per side, both recorded;
6. the journal shows why: the round record's conflict is the scan's conflict.

The red proof stubs the applier to today's refusal (``NOT_WIRED``) and shows
falsifier 1 fail.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from hermes.agents.runtime.config import load_profiles
from hermes.agents.runtime.wiring import RuntimeWiring
from hermes.artifacts.store import ArtifactStore
from hermes.composition import plan_capability_plane
from hermes.core.events import EventType
from hermes.core.intents import Intent, IntentKind
from hermes.methodology.swap_test import CHAIN_STATEMENTS, chain_inputs
from hermes.methodology.workflows import (
    LITERATURE_REVIEW_DOCUMENT,
    MethodologyInputs,
    parse_methodology,
)
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ArtifactRepository, ProjectRepository
from hermes.research.capability_supply import (
    FALSIFICATION_TOOL_SET_ID,
    SUPPLIED_CAPABILITY_IDS,
    build_research_egress_supply,
    supplied_capability_risks,
)
from hermes.research.chain_refs import RefProvenanceReader
from hermes.research.gateway import NOT_WIRED, GatewayRejection, apply_intent
from hermes.research.inspection import ClaimText, conflicts_between
from hermes.research.live_fetch import ALLOWLIST_HOSTS, build_live_fetch_wiring
from hermes.research.project_index import ProjectIndexReader
from hermes.research.task_handlers.methodology_driver import (
    MethodologyExecution,
)
from hermes.research.task_handlers.methodology_driver import (
    run_methodology as live_run_methodology,
)
from hermes.research.verification import run_round
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
from hermes.tools.providers.base import TransportResponse

CLOCK = "2026-10-30T18:00:00.000000+00:00"
PROJECT = "p-ops5z-group-e"
TASK = "task-ops5z-group-e"
QUESTION = "Did India overtake Brazil by 1 September 2020?"
PROFILE = "ADVERSARY"
SNAPSHOT_URL = "https://openalex.org/W-SNAPSHOT"
PRIMARY_URL = "https://openalex.org/W-PRIMARY"
ORDER_URL = "https://openalex.org/W-ORDER"

FIXTURES = Path(__file__).parent / "fixtures" / "source_payloads"
COOKIE_WALL = FIXTURES / "pubmed_cookie_wall_5590.html"

#: Constructed from the audit's description of the missing primary snapshot:
#: the claim transcribes the 18 September figures it was given.
SNAPSHOT = (
    "On 18 September 2020, India reported 5,275,035 cases and Brazil "
    "reported 4,467,433 cases.")

#: The primary source the critic asked for, in the resolving form: the same
#: figures on the same date. (The incident's actual primary is the 1 September
#: snapshot; that is the DISPUTED variant below.)
PRIMARY = (
    "On 18 September 2020, India reported 5,275,035 cases and Brazil "
    "reported 4,467,433 cases.")

#: The 1 September snapshot from the audit: the figures the claim attributes to
#: 1 September are not there, so the figure side cannot be established.
PRIMARY_CONTRADICTORY = (
    "On 1 September 2020, Brazil reported 3,959,158 cases and India "
    "reported 3,769,523 cases.")

CLAIM_STATEMENT = (
    "India 5,275,035 cases and Brazil 4,467,433 cases on 18 September 2020.")
ORDER_STATEMENT = "Brazil was ahead of India on 18 September 2020."
AGREEING_STATEMENT = (
    "India 5,275,035 cases and Brazil 4,467,433 cases on 18 September 2020.")


class Clock:
    def now_utc(self) -> str:
        return CLOCK

    def monotonic(self) -> float:
        return 1000.0

    def sleep(self, delay: float) -> None:
        return None


def _public_resolve(host: str) -> tuple[str, ...]:
    return ("93.184.216.34",)


def _proposal(request: Any, structured: dict[str, Any]) -> Any:
    from hermes.tools.models.router import ModelProposal

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
    from hermes.agents.runtime.assembly import PROJECT_INDEX_ORIGIN

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


def _conflict(left_ref: str = "claim[1]", right_ref: str = "claim[3]",
              left: str = CLAIM_STATEMENT,
              right: str = ORDER_STATEMENT) -> Any:
    found = conflicts_between([
        ClaimText(left_ref, left), ClaimText(right_ref, right)])
    assert found, "the scripted pair must conflict for this falsifier"
    return found[0]


def _round_payload(evidence_ref: str, *, same_source: bool,
                   order_url: str = ORDER_URL) -> dict[str, Any]:
    conflict = _conflict()
    claims = [
        {"ref": "claim[1]", "statement": CLAIM_STATEMENT,
         "source_ref": evidence_ref},
        {"ref": "claim[3]", "statement": ORDER_STATEMENT,
         "source_ref": (evidence_ref if same_source else "")},
    ]
    if same_source:
        mode = "parallel-two"
        targets = [
            {"claim_ref": "claim[1]", "provider": "openalex",
             "url": PRIMARY_URL},
            {"claim_ref": "claim[3]", "provider": "openalex",
             "url": order_url},
        ]
    else:
        mode = "verify-one"
        targets = [
            {"claim_ref": "", "provider": "openalex", "url": PRIMARY_URL},
        ]
    return {
        "claims": claims,
        "conflict": {
            "kind": conflict.kind, "left": conflict.left,
            "right": conflict.right, "subject": conflict.subject,
            "date": conflict.date, "detail": conflict.detail,
        },
        "mode": mode,
        "targets": targets,
    }


class RoundModel:
    """Fetch the snapshot; cite it; at CRITIQUE scan and propose the round.

    The scan is a real capability call; the proposal carries the same refs and
    statements, and the conflict the pure scanner derives from them. The
    model's round payload is built at CRITIQUE time, when the admitted
    evidence ref exists.
    """

    def __init__(self, *, same_source: bool = False,
                 propose_round: bool = True,
                 order_url: str = ORDER_URL) -> None:
        self.same_source = same_source
        self.propose_round = propose_round
        self.order_url = order_url
        self.evidence_ref = ""
        self.calls: list[Any] = []
        self.round_payload: dict[str, Any] | None = None

    def invoke(self, request: Any) -> Any:
        self.calls.append(request)
        if any(part.origin == "runtime.review" for part in request.prompt):
            return _proposal(request, {})
        stage = _stage_of(request)
        if stage == "HYPOTHESIS":
            return _proposal(request, {
                "tool_calls": [{
                    "capability_id": "source_fetch",
                    "arguments": {"provider": "openalex",
                                  "url": SNAPSHOT_URL},
                    "rationale": "fetch the snapshot before the observation",
                }],
            })
        if stage == "OBSERVATION":
            entry = _artifact_entry(request)
            assert entry, "the fetched artifact is not in the project index"
            self.evidence_ref = "evidence:" + entry.split(":", 1)[1]
            return _proposal(request, {
                "kind": "EVIDENCE_TRANSITION",
                "rationale": "cite the artifact the run fetched",
                "payload": {
                    "evidence_artifact_ref": self.evidence_ref,
                    "from_state": "SUPPORTED",
                    "to_state": "ROBUST",
                    "rationale": "the fetched source supports the rung",
                },
            })
        if stage == "CRITIQUE":
            if not self.propose_round:
                return _proposal(request, {
                    "tool_calls": [{
                        "capability_id": "contradiction_scan",
                        "arguments": {
                            "refs": ["claim[1]", "claim[2]"],
                            "statements": [CLAIM_STATEMENT,
                                           AGREEING_STATEMENT],
                        },
                        "rationale": "check the claim against itself",
                    }],
                })
            self.round_payload = _round_payload(
                self.evidence_ref, same_source=self.same_source,
                order_url=self.order_url)
            return _proposal(request, {
                "tool_calls": [{
                    "capability_id": "contradiction_scan",
                    "arguments": {
                        "refs": ["claim[1]", "claim[3]"],
                        "statements": [CLAIM_STATEMENT, ORDER_STATEMENT],
                    },
                    "rationale": "check the claim against the recorded order",
                }],
                "kind": "REQUEST_ADDITIONAL_EXPERIMENT",
                "rationale": ("the scan reports an ORDER conflict; fetch the "
                              "primary source for the disputed figure"),
                "payload": self.round_payload,
            })
        return _proposal(request, {})


@dataclass
class Rig:
    conn: Any
    store: ArtifactStore
    invoker: CapabilityInvoker
    plan: Any

    def claim_inputs(self, statement: str,
                     subjects: tuple[str, ...] = ("India", "Brazil"),
                     ) -> MethodologyInputs:
        claim: dict[str, Any] = {"statement": statement}
        if subjects:
            claim["subjects"] = list(subjects)
        return replace(chain_inputs(PROJECT, QUESTION), stage_content={
            **CHAIN_STATEMENTS, "CLAIM": claim})

    def artifact_reader(self, project_id: str,
                        artifact_id: str) -> Any:
        from hermes.tools.capabilities.content import ArtifactRead

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

    def verification_runner(self, round_: Any) -> Any:
        return run_round(
            round_,
            invoke=self.invoker.invoke,
            read_artifact=self.artifact_reader,
            project_id=PROJECT,
            lease_generation="lease-ops5z-group-e",
            grant=self.plan.grants.get("RESEARCHER"),
            deadline_seconds=30.0)

    def run(self, model: Any, inputs: MethodologyInputs,
            orchestration: Any = None) -> Any:
        wiring = RuntimeWiring(
            model=model,
            orchestration=(orchestration
                           or (lambda intent: apply_intent(self.conn, intent))),
            lease_generation="lease-ops5z-group-e",
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
            provenance_of=RefProvenanceReader(self.conn),
            artifact_reader=self.artifact_reader,
            verification_runner=self.verification_runner)

    def events(self, event_type: EventType) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT payload_json, correlation_id FROM events "
            "WHERE event_type = ? ORDER BY event_id",
            (event_type.value,)).fetchall()
        return [{"payload": json.loads(row["payload_json"] or "{}"),
                 "correlation_id": row["correlation_id"]} for row in rows]

    def inspect(self, ref: str, *, key: str) -> Observation:
        result = self.invoker.invoke(InvokeRequest(
            capability_id="evidence_inspect",
            arguments={"ref": ref},
            idempotency_key=key,
            lease_generation="lease-ops5z-group-e",
            profile=PROFILE,
            rationale="read the artifact's facts",
            grant=ToolGrant(
                grant_id="grant.ops5z-group-e",
                profile=PROFILE,
                tool_set_ids=frozenset({FALSIFICATION_TOOL_SET_ID}),
                max_risk=RiskLevel.LOW.value),
            deadline_seconds=10.0))
        assert isinstance(result, Observation), result
        assert result.ok(), result.detail
        return result


def _rig(tmp_path: Path, monkeypatch, *, primary: bytes = PRIMARY.encode(),
         primary_content_type: str = "text/plain",
         order_body: bytes = PRIMARY.encode()) -> Rig:
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: CLOCK).create(PROJECT, "OPS-5Z Group E")
    store = ArtifactStore(
        str(tmp_path / "store"), ArtifactRepository(conn, lambda: CLOCK),
        clock=lambda: CLOCK)
    wiring = build_live_fetch_wiring(
        conn, store, lambda: CLOCK, dns_resolve=_public_resolve)

    def scripted(spec: Any) -> TransportResponse:
        if "W-PRIMARY" in spec.url:
            return TransportResponse(
                status=200, body=primary, headers={},
                content_type=primary_content_type)
        if "W-ORDER" in spec.url:
            return TransportResponse(
                status=200, body=order_body, headers={},
                content_type="text/plain")
        return TransportResponse(
            status=200, body=SNAPSHOT.encode(), headers={},
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
        risks=supplied_capability_risks(),
        # Two compositions exist; the critic's falsification set is only
        # reachable when the plan is given the supply's declared sets (OPS-5Z4).
        tool_sets=supply.tool_sets)
    return Rig(conn=conn, store=store, invoker=invoker, plan=plan)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    rig = _rig(tmp_path, monkeypatch)
    yield rig
    rig.conn.close()


def _assert_a_conflict_opened_a_round(rig: Rig, model: RoundModel,
                                      execution: Any) -> dict[str, Any]:
    opened = rig.events(EventType.VERIFICATION_ROUND_OPENED)
    assert len(opened) == 1, (
        "the conflict did not open a verification round; today's failure mode "
        f"is a conflict that becomes nothing (events: {opened})")
    record = opened[0]["payload"]
    assert record["conflict"]["kind"] == "ORDER"
    assert record["claim_refs"] == ["claim[1]", "claim[3]"]
    assert record["mode"] == "verify-one"
    assert record["budget"] == 1
    completed = rig.events(EventType.VERIFICATION_ROUND_COMPLETED)
    assert len(completed) == 1, "the round has no terminal record"
    assert completed[0]["payload"]["round_id"] == record["round_id"]
    assert isinstance(execution, MethodologyExecution), execution
    claim = next(stage for stage in execution.stages if stage.stage == "CLAIM")
    assert claim.verification is not None, (
        "the claim does not carry the round's record")
    assert claim.verification.round_id == record["round_id"]
    assert claim.verification.conflict_kind == "ORDER"
    return record


# ═══════════════ 1. a conflict opens a round ═══════════════


def test_a_conflict_opens_a_verification_round(rig) -> None:
    model = RoundModel()
    execution = rig.run(model, rig.claim_inputs(CLAIM_STATEMENT))
    record = _assert_a_conflict_opened_a_round(rig, model, execution)
    # The critic's scan, through the real capability, answers CONFLICT for the
    # pair the round names — the round is a response to an observed conflict,
    # not a proposal the model made up.
    scan = rig.invoker.invoke(InvokeRequest(
        capability_id="contradiction_scan",
        arguments={"refs": ["claim[1]", "claim[3]"],
                   "statements": [CLAIM_STATEMENT, ORDER_STATEMENT]},
        idempotency_key="group-e-scan",
        lease_generation="lease-ops5z-group-e",
        profile=PROFILE,
        rationale="confirm the conflict the round was opened for",
        grant=ToolGrant(
            grant_id="grant.ops5z-group-e",
            profile=PROFILE,
            tool_set_ids=frozenset({FALSIFICATION_TOOL_SET_ID}),
            max_risk=RiskLevel.LOW.value),
        deadline_seconds=10.0))
    assert isinstance(scan, Observation), scan
    assert scan.ok(), scan.detail
    assert "1 conflict(s)" in scan.detail
    assert "ORDER" in scan.detail
    # A round that ran is visible downstream: the conclusion's stage payload
    # carries the verdict, not only the journal.
    conclusion = next(call for call in model.calls
                      if _stage_of(call) == "CONCLUSION")
    documents = [json.loads(part.text) for part in conclusion.prompt
                 if part.origin == "runtime.payload"]
    assert any(document.get("verification", {}).get("status") == "RESOLVED"
               for document in documents)
    completed = rig.events(EventType.VERIFICATION_ROUND_COMPLETED)[0]["payload"]
    assert completed["status"] == "RESOLVED"
    assert completed["winner_ref"] == "claim[1]"
    claim = next(stage for stage in execution.stages if stage.stage == "CLAIM")
    assert claim.verification.status == "RESOLVED"
    assert claim.verification.winner_ref == "claim[1]"
    # The primary fetch went through the capability plane; the artifact it
    # wrote is the evidence the record cites.
    evidence = completed["evidence_refs"]
    assert len(evidence) == 1 and evidence[0].startswith("evidence:")
    artifact_id = evidence[0].partition(":")[2]
    assert rig.artifact_reader(PROJECT, artifact_id) is not None
    assert record["targets"][0]["url"] == PRIMARY_URL


def test_red_proof_without_the_wiring_a_conflict_opens_nothing(rig) -> None:
    """Today's behaviour: the applier refuses the round ``NOT_WIRED``.

    A conflict is then a log line (or a refused proposal), not an
    investigation. The same assertion that passes above fails here.
    """
    def not_wired(intent: Intent) -> Any:
        if intent.kind is IntentKind.REQUEST_ADDITIONAL_EXPERIMENT:
            raise GatewayRejection(
                intent.kind, NOT_WIRED,
                f"{intent.kind.value} is declared but its gateway validator "
                "is not wired in this phase")
        return apply_intent(rig.conn, intent)

    model = RoundModel()
    execution = rig.run(model, rig.claim_inputs(CLAIM_STATEMENT),
                        orchestration=not_wired)
    assert rig.events(EventType.VERIFICATION_ROUND_OPENED) == []
    assert isinstance(execution, MethodologyExecution), execution
    claim = next(stage for stage in execution.stages if stage.stage == "CLAIM")
    # The refusal is recorded, never a silent success — but no round ran.
    assert claim.verification is not None
    assert claim.verification.status == "REFUSED"
    assert claim.verification.code == "PROPOSAL"  # the runtime's closed code
    with pytest.raises(AssertionError):
        _assert_a_conflict_opened_a_round(rig, model, execution)


# ═══════════════ 2. no conflict, no round ═══════════════


def test_no_conflict_opens_no_round(rig) -> None:
    model = RoundModel(propose_round=False)
    execution = rig.run(model, rig.claim_inputs(CLAIM_STATEMENT))
    assert isinstance(execution, MethodologyExecution), execution
    assert rig.events(EventType.VERIFICATION_ROUND_OPENED) == []
    assert rig.events(EventType.VERIFICATION_ROUND_COMPLETED) == []
    critique = next(stage for stage in execution.stages
                    if stage.stage == "CRITIQUE")
    assert critique.verification is None
    # The stage ends as it does today: the critic called the scan and proposed
    # nothing; with one tick spent on the scan the stage hits its tick bound
    # rather than no_proposals, and the run still completes without a round.
    assert critique.state == "SUCCEEDED"
    assert execution.termination == "COMPLETE"


# ═══════════════ 3. the round is bounded ═══════════════


def test_a_round_that_does_not_settle_the_claim_is_disputed(
        tmp_path, monkeypatch) -> None:
    rig = _rig(tmp_path, monkeypatch,
               primary=PRIMARY_CONTRADICTORY.encode())
    try:
        model = RoundModel()
        execution = rig.run(model, rig.claim_inputs(CLAIM_STATEMENT))
        assert isinstance(execution, MethodologyExecution), execution
        assert execution.termination == "COMPLETE"
        record = rig.events(EventType.VERIFICATION_ROUND_OPENED)[0]["payload"]
        completed = rig.events(
            EventType.VERIFICATION_ROUND_COMPLETED)[0]["payload"]
        assert completed["status"] == "DISPUTED"
        assert completed["winner_ref"] == ""
        claim = next(stage for stage in execution.stages
                     if stage.stage == "CLAIM")
        assert claim.verification is not None
        assert claim.verification.status == "DISPUTED"
        assert claim.verification.round_id == record["round_id"]
        # Neither LOOP nor TICK_LIMIT: the chain finished, with the caveat.
        assert execution.termination != "LOOP"
        assert execution.termination != "TICK_LIMIT"
        # The one-round budget: a second request for either claim is refused
        # BUDGET at the spine, not a second fetch.
        second = _round_payload("evidence:" + "0" * 64, same_source=False)
        from hermes.research.verification import parse_round_payload
        round_ = parse_round_payload(second, project_id=PROJECT)
        with pytest.raises(GatewayRejection) as refusal:
            apply_intent(rig.conn, Intent(
                kind=IntentKind.REQUEST_ADDITIONAL_EXPERIMENT,
                proposed_by=PROFILE, project_id=PROJECT, payload=second,
                justification="the conflict persists"), clock=lambda: CLOCK)
        assert refusal.value.code == "BUDGET"
        assert "one round, then escalate" in str(refusal.value)
        assert round_.claim_refs == ("claim[1]", "claim[3]")
    finally:
        rig.conn.close()


# ═══════════════ 4. verify-one fetches the primary, through the gate ═══════════════


def test_verify_one_fetches_the_primary_and_the_gate_refuses_a_wall(
        tmp_path, monkeypatch) -> None:
    wall = COOKIE_WALL.read_bytes()
    rig = _rig(tmp_path, monkeypatch, primary=wall,
               primary_content_type="text/html")
    try:
        # The transport's 200 + HTML is a wall: use the real cookie-wall bytes
        # through the same content gate the fetch path uses.
        model = RoundModel()
        execution = rig.run(model, rig.claim_inputs(CLAIM_STATEMENT))
        assert isinstance(execution, MethodologyExecution), execution
        completed = rig.events(
            EventType.VERIFICATION_ROUND_COMPLETED)[0]["payload"]
        assert completed["status"] == "REFUSED"
        assert completed["code"] == "NON_CONTENT_PAYLOAD"
        assert completed["evidence_refs"] == []
        claim = next(stage for stage in execution.stages
                     if stage.stage == "CLAIM")
        assert claim.verification is not None
        assert claim.verification.status == "REFUSED"
        assert claim.verification.code == "NON_CONTENT_PAYLOAD"
        # The wall never became a citable artifact: the only source_payload
        # rows are the snapshot the observation fetched.
        rows = rig.conn.execute(
            "SELECT content_hash FROM artifacts WHERE artifact_type = "
            "'source_payload'").fetchall()
        assert len(rows) == 1
    finally:
        rig.conn.close()


# ═══════════════ 5. parallel-two, one branch per side ═══════════════


def test_parallel_two_records_a_branch_for_each_side(rig) -> None:
    model = RoundModel(same_source=True)
    execution = rig.run(model, rig.claim_inputs(CLAIM_STATEMENT))
    assert isinstance(execution, MethodologyExecution), execution
    opened = rig.events(EventType.VERIFICATION_ROUND_OPENED)[0]["payload"]
    assert opened["mode"] == "parallel-two"
    assert len(opened["targets"]) == 2
    assert {target["claim_ref"] for target in opened["targets"]} == {
        "claim[1]", "claim[3]"}
    completed = rig.events(EventType.VERIFICATION_ROUND_COMPLETED)[0]["payload"]
    branches = completed["branches"]
    assert len(branches) == 2, branches
    assert {branch["claim_ref"] for branch in branches} == {
        "claim[1]", "claim[3]"}
    assert all(branch["evidence_ref"].startswith("evidence:")
               for branch in branches)
    assert completed["status"] == "RESOLVED"
    assert completed["winner_ref"] == "claim[1]"


# ═══════════════ 6. the journal shows why ═══════════════


def test_the_round_record_names_the_conflict_that_caused_it(rig) -> None:
    model = RoundModel()
    execution = rig.run(model, rig.claim_inputs(CLAIM_STATEMENT))
    record = rig.events(EventType.VERIFICATION_ROUND_OPENED)[0]["payload"]
    assert model.round_payload is not None
    assert record["conflict"] == model.round_payload["conflict"]
    assert "Brazil was ahead of India" in record["conflict"]["detail"]
    assert "5,275,035" in record["conflict"]["detail"]
    # The terminal record points back at the opened round by identity, so the
    # journal is a chain: conflict -> round -> outcome.
    completed = rig.events(EventType.VERIFICATION_ROUND_COMPLETED)[0]["payload"]
    assert completed["round_id"] == record["round_id"]
    assert isinstance(execution, MethodologyExecution), execution
