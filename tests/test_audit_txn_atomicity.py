"""AUDIT-TXN — same-transaction audit append (IDR-013 addendum A1.6).

The design record is the contract (``docs/idr/IDR-013.md`` addendum
AUDIT-TXN). This module ships its eight falsifiers:

1. a fault injected BETWEEN the mutation write and its COMMIT leaves
   NEITHER row (the crash window is closed in the forward direction);
2. a fault injected AFTER the COMMIT leaves BOTH rows (backward direction);
3. a rejection still journals exactly one ``IntentRejected`` with its exact
   code and the unchanged payload;
4. a stale-project rejection still falls back to ``project_id = NULL``
   without touching any mutation;
5. the 4 KiB cap refuses before any write, and an over-cap audit append
   inside a fused transaction rolls the mutation back;
6. for one intent per dispatch branch, ``IntentApplied.prev_hash`` is the
   mutation event's ``chain_hash`` (same-transaction adjacency);
7. a duplicate replay lands exactly one ``IntentApplied`` and writes nothing;
8. the journal still verifies (``CHAIN_OK``) after a fused apply.

The fixtures deliberately mirror the shipped per-slice tests (q05 / step7 /
chg1 / cond-type) so the branch setups are the ones those suites already
pin.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Callable

import pytest

from hermes.core import frozen_clock
from hermes.core.events import EventType
from hermes.core.intents import Intent, IntentKind
from hermes.core.node import NodeContract
from hermes.persistence import repositories as repo_mod
from hermes.persistence.database import connect
from hermes.persistence.event_validation import EventValidationError
from hermes.persistence.journal_chain import verify_journal
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    AuditRecord,
    OperatorCredentialRepository,
    ProjectRepository,
    TaskRepository,
    _append_event_to_db,
)
from hermes.research import gateway as gateway_mod
from hermes.research.contradictions import (
    CONTRADICTION_DETECTOR_VERSION,
    contradiction_id_of,
)
from hermes.research.evidence_ladder import classification_content_hash
from hermes.research.failure_classification import (
    classification_command_hash,
)
from hermes.research.feature_binding import (
    CURATED_KIND_REFUTED_PATTERN,
    FEATURE_BINDING_ARTIFACT_TYPE,
    FEATURE_BINDING_REF_PREFIX,
    binding_content_hash,
    curation_command_hash,
    signature_from_binding,
)
from hermes.research.gateway import (
    MALFORMED_PAYLOAD,
    PROJECT_NOT_FOUND,
    ROLE,
    GatewayRejection,
    _contradiction_resolution_id,
    apply_intent,
)

CLOCK = "2026-01-01T00:00:00.000000+00:00"
OP_ID = "op-1"
OP_TOKEN = "op-token-1"
FC_TYPE = "failure_classification"


def _clock() -> str:
    return CLOCK


def _fresh(*, brief: bool = False) -> sqlite3.Connection:
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, frozen_clock(CLOCK)).create("p1", "Test")
    OperatorCredentialRepository(conn, frozen_clock(CLOCK)).register(
        OP_ID, OP_TOKEN, "Test Operator")
    if brief:
        conn.execute(
            """INSERT INTO scope_briefs
               (brief_id, project_id, version, content_hash, supersedes_id,
                scope_text_json, rationale, created_at, frozen_at)
               VALUES (?, ?, 1, ?, NULL, ?, NULL, ?, ?)""",
            ("brief-1", "p1", "briefhash1", json.dumps({"scope": "x"}),
             CLOCK, CLOCK),
        )
    return conn


def _insert_artifact(
    conn: sqlite3.Connection,
    artifact_id: str,
    artifact_type: str = "evidence",
    *,
    content_hash: str | None = None,
    meta: dict | None = None,
) -> str:
    conn.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type, content_hash,
            size_bytes, storage_path, producer, metadata_json, created_at)
           VALUES (?, 'p1', NULL, ?, ?, 1, 'x', 'test', ?, ?)""",
        (artifact_id, artifact_type, content_hash or f"ch-{artifact_id}",
         json.dumps(meta) if meta is not None else None, CLOCK),
    )
    return content_hash or f"ch-{artifact_id}"


def _max_event_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(event_id) AS m FROM events").fetchone()
    return row["m"] or 0


def _events_after(conn: sqlite3.Connection, mark: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM events WHERE event_id > ? ORDER BY event_id",
        (mark,)).fetchall()


def _count(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    return conn.execute(sql, params).fetchone()[0]


def _count_type(conn: sqlite3.Connection, event_type: str) -> int:
    return _count(
        conn, "SELECT COUNT(*) FROM events WHERE event_type = ?",
        (event_type,))


# ── the branch fixtures (one per dispatch branch) ───────────────────────────


def _base_payload() -> dict:
    """The schema-valid confirmatory draft used by tests/test_gateway.py."""
    return {
        "scope_ref": "brief-1",
        "epistemic_objective": "Establish whether momentum predicts XAUUSD returns",
        "hypotheses": [
            {"ref": "H1", "ladder_target": "SUPPORTED",
             "falsification_condition": "returns do not follow momentum",
             "rival_of": None, "rival_status": None},
            {"ref": "H0", "ladder_target": "SPECULATIVE",
             "falsification_condition": "null hypothesis",
             "rival_of": "H1", "rival_status": "ACTIVE"},
        ],
        "predictions": [
            {"ref": "P1", "claim_ref": "H1", "observable": "20d_returns",
             "direction": "FOR", "condition": "trend_up"},
            {"ref": "P0", "claim_ref": "H0", "observable": "20d_returns",
             "direction": "NEUTRAL", "condition": "trend_up"},
        ],
        "discrimination_requirements": [
            {"ref": "D1", "hypothesis_a": "H1", "hypothesis_b": "H0",
             "observable": "20d_returns",
             "expected_difference": "H1 positive, H0 zero",
             "required_condition": "trend_up",
             "measurement_method_ref": "method-1"},
        ],
        "methodology_constraints": ["icss-v1"],
        "task_graph_template_ref": None,
        "compiler_version": "1.0.0",
        "policy_version": "rp-2026.1",
        "schema_version": "1",
        "supersedes_ref": None,
    }


def _proposal_intent() -> Intent:
    return Intent(
        kind=IntentKind.PROPOSE_RESEARCH_PROGRAM,
        proposed_by="DIRECTOR", project_id="p1",
        payload=_base_payload(), justification="audit-txn branch")


def _task_payload(**overrides) -> dict:
    payload = {
        "task_id": "t1",
        "task_type": "AGENT_TASK",
        "profile": "RESEARCHER",
        "idempotency_key": "idem-1",
        "iteration": 1,
        "spec": {"program_id": "rp_abc", "plan_kind": "evidence_obligation"},
        "inputs": [],
        "outputs": ["evidence:SUPPORTED"],
        "dependencies": [],
        "provenance": ["spec:payload-v1"],
    }
    payload.update(overrides)
    return payload


def _admitted_classification(
    conn: sqlite3.Connection, cls_id: str, *, program_ref: str,
    hypothesis_ref: str, failure_class: str,
) -> str:
    """An ADMITTED classification artifact permitting a parallel regime."""
    meta = {
        "schema_version": "1",
        "classification_id": cls_id,
        "failure_class": failure_class,
        "hypothesis_ref": hypothesis_ref,
        "program_ref": program_ref,
        "condition_type": "ACCIDENTAL",
        "regime_ref": "regime:icss-v1:trend",
        "classifier_version": "1.0",
        "contributing_factors": [],
        "evidence_refs": [],
        "constraint_ref": None,
        "failed_mechanism_ref": None,
        "resource_gap": None,
        "scope_brief_ref": None,
        "scope_brief_field": None,
        "explanation": "audit-txn test classification",
        "proposed_by": "DIRECTOR",
        "falsifying_evidence_refs": [],
        "permitted_actions": ["PROPOSE_SCOPE_NARROWING",
                              "PROPOSE_PARALLEL_REGIME_TEST"],
        "requires_human_confirmation": failure_class == "FRAMING_ERROR",
        "status": "ADMITTED",
    }
    return _insert_artifact(
        conn, cls_id, FC_TYPE, content_hash=f"ch-{cls_id}", meta=meta)


def _q05_classification(
    conn: sqlite3.Connection, failure_class: str, *,
    cls_art: str = "fc-x", ev: str = "ev-x",
) -> str:
    """The q05 shape: a classification + its cited evidence artifact."""
    _insert_artifact(conn, ev, "evidence")
    meta = {
        "failure_class": failure_class, "hypothesis_ref": "h1",
        "classifier_version": "1.0", "classification_id": cls_art,
        "evidence_refs": ["evidence:" + ev], "program_ref": "rp-1",
        "falsifying_evidence_refs": [],
        "permitted_actions": ["ROUTE_TO_SCOPE_REVIEW"],
    }
    _insert_artifact(conn, cls_art, FC_TYPE, meta=meta)
    conn.execute(
        "INSERT INTO provenance_edges (artifact_id, upstream_id, edge_type,"
        " created_at) VALUES (?, ?, 'cites', ?)",
        (cls_art, ev, CLOCK))
    return "failure_classification:ch-" + cls_art


def _propose_action_intent(action: str) -> Intent:
    return Intent(
        kind=IntentKind.PROPOSE_CLASSIFICATION_ACTION,
        proposed_by="DIRECTOR", project_id="p1",
        payload={"classification_ref": "failure_classification:ch-fc-x",
                 "action": action, "candidate_artifact_ref": "ev-x",
                 "rationale": "audit-txn"},
        justification="audit-txn branch")


def _resolve_intent(proposal_id: str) -> Intent:
    return Intent(
        kind=IntentKind.RESOLVE_CLASSIFICATION_PROPOSAL,
        proposed_by="DETERMINISTIC", project_id="p1",
        payload={"proposal_id": proposal_id, "decision": "APPROVED",
                 "rationale": "operator ok", "operator_id": OP_ID},
        justification="audit-txn branch")


def _digest_classification(
    conn: sqlite3.Connection, cls_art: str, failure_class: str,
    *, falsifying_refs: list[str],
) -> str:
    """A digest-valid classification artifact (the chg1 shape)."""
    from hermes.research.failure_classification import ACTION_MAP, FailureClass
    permitted = sorted(
        a.value for a in ACTION_MAP[FailureClass(failure_class)])
    meta = {
        "schema_version": "1",
        "failure_class": failure_class,
        "hypothesis_ref": "h1",
        "program_ref": "rp-1",
        "classification_id": cls_art,
        "classifier_version": "1.0",
        "contributing_factors": [],
        "evidence_refs": list(falsifying_refs),
        "constraint_ref": "hypothesis:h1:falsification_condition",
        "failed_mechanism_ref": None,
        "regime_ref": None,
        "resource_gap": None,
        "scope_brief_ref": None,
        "scope_brief_field": None,
        "explanation": f"audit-txn {cls_art}",
        "proposed_by": "DIRECTOR",
        "falsifying_evidence_refs": list(falsifying_refs),
        "permitted_actions": permitted,
    }
    content_hash = classification_content_hash(meta, "p1")
    assert content_hash is not None
    _insert_artifact(
        conn, cls_art, FC_TYPE, content_hash=content_hash, meta=meta)
    return "failure_classification:" + content_hash


def _conflicting_pair(conn: sqlite3.Connection) -> tuple[str, str]:
    _insert_artifact(conn, "art-ev1", "evidence", content_hash="evhash1")
    _digest_classification(
        conn, "fc-a", "DECLARED_CONSTRAINT_VIOLATION",
        falsifying_refs=["evidence:evhash1"])
    _digest_classification(
        conn, "fc-b", "IMPLEMENTATION_FAILURE",
        falsifying_refs=["evidence:evhash1"])
    return "fc-a", "fc-b"


def _contradiction_intent(party_a: str, party_b: str) -> Intent:
    return Intent(
        kind=IntentKind.RECORD_CONTRADICTION,
        proposed_by="DETERMINISTIC", project_id="p1",
        payload={"party_a": party_a, "party_b": party_b,
                 "detector_version": CONTRADICTION_DETECTOR_VERSION,
                 "supersedes_ref": ""},
        justification="audit-txn branch")


def _event(conn: sqlite3.Connection, event_type: str, correlation_id: str,
           payload: dict) -> None:
    _append_event_to_db(
        conn, frozen_clock(CLOCK), event_type,
        project_id="p1", correlation_id=correlation_id,
        caused_by="operator", reason="test fixture", payload=payload)


def _retract_intent() -> Intent:
    return Intent(
        kind=IntentKind.RETRACT_SOURCE, proposed_by="DETERMINISTIC",
        project_id="p1",
        payload={"source_ref": "src-a",
                 "reason": "source retracted by publisher",
                 "human_decision_ref": "hd-1"},
        justification="audit-txn branch")


# ── curated-knowledge seed (the step7 shape) ────────────────────────────────


def _curate_seed(conn: sqlite3.Connection) -> dict:
    conn.execute(
        """INSERT INTO research_programs
           (program_id, project_id, version, content_hash, supersedes_id,
            scope_ref, epistemic_objective, compiler_version, policy_version,
            schema_version, input_hash, hypothesis_json, prediction_json,
            discrimination_json, evidence_json, gate_json, methodology_json,
            task_graph_template_ref, produced_by, reason, created_at)
           VALUES ('rp-1', 'p1', 1, 'ch-rp-1', NULL, 'b', 'o', 'c1', 'p1',
                   '1', 'ih', ?, '[]', '[]', '[]', '[]', '[]', NULL,
                   'director', NULL, ?)""",
        (json.dumps([{"ref": "h1", "ladder_target": "SUPPORTED",
                      "falsification_condition": "fc", "rival_of": None,
                      "rival_status": None}]), CLOCK),
    )
    _insert_artifact(conn, "art-ev1", "evidence", content_hash="evhash1")
    cls_ref = _digest_classification(
        conn, "fc-1", "DECLARED_CONSTRAINT_VIOLATION",
        falsifying_refs=["evidence:evhash1"])
    conn.execute(
        """INSERT INTO evidence_ladder_state
           (state_id, project_id, program_id, hypothesis_ref, version, rung,
            transition_id, derived_from, created_at)
           VALUES ('ls-1', 'p1', 'rp-1', 'h1', 1, 'REFUTED', 'tr-1',
                   'ratification', ?)""",
        (CLOCK,),
    )
    _append_event_to_db(
        conn, frozen_clock(CLOCK),
        EventType.EVIDENCE_TRANSITION_APPLIED.value,
        project_id="p1", correlation_id="tr-1",
        from_state="SUPPORTED", to_state="REFUTED",
        caused_by="controller",
        reason="evidence ladder ratification transition: SUPPORTED -> REFUTED",
        payload={"program_id": "rp-1", "hypothesis_ref": "h1",
                 "from_rung": "SUPPORTED", "to_rung": "REFUTED",
                 "driver": "ratification", "ratified_by": "classification",
                 "classification_ref": cls_ref})
    binding = {
        "schema_version": 1, "project_ref": "p1", "program_ref": "rp-1",
        "hypothesis_ref": "h1", "instrument": "xauusd",
        "feature_family": "momentum", "claim_type": "directional",
    }
    binding_hash = binding_content_hash(binding)
    _insert_artifact(
        conn, "art-fb1", FEATURE_BINDING_ARTIFACT_TYPE,
        content_hash=binding_hash, meta=binding)
    return {
        "program_id": "rp-1", "hypothesis_ref": "h1",
        "binding_ref": FEATURE_BINDING_REF_PREFIX + binding_hash,
        "signature_json": signature_from_binding(binding),
        "decision_event_ref": "tr-1",
    }


def _curate_intent(conn: sqlite3.Connection, seed: dict) -> Intent:
    command = {
        "operation": "ADMIT",
        "kind": CURATED_KIND_REFUTED_PATTERN,
        "program_ref": seed["program_id"],
        "hypothesis_ref": seed["hypothesis_ref"],
        "source_binding_ref": seed["binding_ref"],
        "source_decision_event_ref": seed["decision_event_ref"],
        "signature_json": seed["signature_json"],
        "supersedes_ref": "",
    }
    command_hash = curation_command_hash(command)
    decision_ref = "curate-decision-" + command_hash
    _event(conn, EventType.HUMAN_DECISION_RECEIVED.value, decision_ref, {
        "decision": "CURATE_KNOWLEDGE", "curation_id": command_hash,
        "operator_id": OP_ID, "rationale": ""})
    return Intent(
        kind=IntentKind.CURATE_KNOWLEDGE, proposed_by="DETERMINISTIC",
        project_id="p1",
        payload={**command, "human_decision_ref": decision_ref,
                 "operator_id": OP_ID},
        justification="audit-txn branch")


# ── failure-classification seed (the cond-type shape) ───────────────────────


def _classification_command() -> dict:
    return {
        "program_ref": "rp-1",
        "hypothesis_ref": "h1",
        "failure_class": "ENVIRONMENT_MISMATCH",
        "evidence_refs": ["source_result:evhash1"],
        "falsifying_evidence_refs": ["source_result:evhash1"],
        "explanation": "audit-txn operator analysis ENVIRONMENT_MISMATCH",
        "classifier_version": "1.0",
        "constraint_ref": None,
        "failed_mechanism_ref": None,
        "regime_ref": "ICSS-v1:low-vol",
        "resource_gap": None,
        "scope_brief_ref": None,
        "scope_brief_field": None,
        "contributing_factors": [],
        "proposed_by": f"operator:{OP_ID}",
        "producing_task_id": "t-prod",
        "condition_type": "UNDETERMINED",
    }


def _record_classification_seed(conn: sqlite3.Connection) -> Intent:
    conn.execute(
        """INSERT INTO research_programs
           (program_id, project_id, version, content_hash, supersedes_id,
            scope_ref, epistemic_objective, compiler_version, policy_version,
            schema_version, input_hash, hypothesis_json, prediction_json,
            discrimination_json, evidence_json, gate_json, methodology_json,
            task_graph_template_ref, produced_by, reason, created_at)
           VALUES ('rp-1', 'p1', 1, 'ch-rp-1', NULL, 'b', 'o', 'c1', 'p1',
                   '1', 'ih', ?, ?, '[]', '[]', '[]', '[]', NULL,
                   'director', NULL, ?)""",
        (json.dumps([{"ref": "h1", "ladder_target": "SUPPORTED",
                      "falsification_condition": "fc", "rival_of": None,
                      "rival_status": None}]),
         json.dumps([{"ref": "p1"}]), CLOCK),
    )
    TaskRepository(conn, frozen_clock(CLOCK)).create(NodeContract(
        task_id="t-prod", project_id="p1", task_type="TOOL_TASK",
        idempotency_key="idem-t-prod", dependencies=[]))
    conn.execute("UPDATE tasks SET status = 'RUNNING' WHERE task_id = 't-prod'")
    for aid, atype, ch in (("art-out1", "source_result", "outhash-out1"),
                           ("art-ev1", "source_result", "evhash1")):
        _insert_artifact(conn, aid, atype, content_hash=ch)
    for child, parent in (("art-out1", "t-prod"), ("art-ev1", "art-out1")):
        conn.execute(
            """INSERT INTO provenance_edges
               (artifact_id, upstream_id, edge_type, created_at)
               VALUES (?, ?, 'derived_from', ?)""",
            (child, parent, CLOCK))
    command = _classification_command()
    command_hash = classification_command_hash(command)
    _event(conn, EventType.HUMAN_DECISION_RECEIVED.value, "hd-class", {
        "decision": "RECORD_CLASSIFICATION",
        "classification_hash": command_hash,
        "operator_id": OP_ID, "rationale": ""})
    return Intent(
        kind=IntentKind.RECORD_CLASSIFICATION, proposed_by="DETERMINISTIC",
        project_id="p1",
        payload={**command, "human_decision_ref": "hd-class",
                 "operator_id": OP_ID},
        justification="audit-txn branch")


@dataclass
class Branch:
    """One dispatch branch: a fresh DB, the intent, and its mutation event.

    ``mutation_event`` is the journal row the audit row must be adjacent to.
    RECORD_CLASSIFICATION has none — its mutation is the artifact row.
    """

    label: str
    conn: sqlite3.Connection
    intent: Intent
    mutation_event: str | None


def _branch_program() -> Branch:
    return Branch("PROPOSE_RESEARCH_PROGRAM", _fresh(brief=True),
                  _proposal_intent(), "ResearchProgramCompiled")


def _branch_emit_parallel() -> Branch:
    conn = _fresh(brief=True)
    parent_id = apply_intent(conn, _proposal_intent(), clock=_clock).entity_id
    _admitted_classification(
        conn, "fc-par", program_ref=parent_id, hypothesis_ref="H1",
        failure_class="ENVIRONMENT_MISMATCH")
    intent = Intent(
        kind=IntentKind.EMIT_PARALLEL_REGIME_PROGRAM,
        proposed_by="DETERMINISTIC", project_id="p1",
        payload={"parent_program_id": parent_id,
                 "parent_hypothesis_ref": "H1",
                 "target_regime": "ICSS-v1:low-vol",
                 "triggering_classification_id": "fc-par"},
        justification="audit-txn branch")
    return Branch("EMIT_PARALLEL_REGIME_PROGRAM", conn, intent,
                  "ResearchProgramCompiled")


def _branch_propose_action() -> Branch:
    conn = _fresh()
    _q05_classification(conn, "FRAMING_ERROR")
    return Branch("PROPOSE_CLASSIFICATION_ACTION", conn,
                  _propose_action_intent("ROUTE_TO_SCOPE_REVIEW"),
                  "ClassificationActionProposed")


def _branch_resolve() -> Branch:
    conn = _fresh()
    _q05_classification(conn, "FRAMING_ERROR")
    prop = apply_intent(
        conn, _propose_action_intent("ROUTE_TO_SCOPE_REVIEW"), clock=_clock)
    return Branch("RESOLVE_CLASSIFICATION_PROPOSAL", conn,
                  _resolve_intent(prop.entity_id),
                  "ClassificationActionDecision")


def _branch_scope_review() -> Branch:
    conn = _fresh()
    _q05_classification(conn, "FRAMING_ERROR")
    prop = apply_intent(
        conn, _propose_action_intent("ROUTE_TO_SCOPE_REVIEW"), clock=_clock)
    apply_intent(conn, _resolve_intent(prop.entity_id), clock=_clock)
    intent = Intent(
        kind=IntentKind.RECORD_SCOPE_REVIEW_DECISION,
        proposed_by="DETERMINISTIC", project_id="p1",
        payload={"proposal_id": prop.entity_id,
                 "scope_decision": "CONFIRM_SCOPE",
                 "rationale": "audit-txn", "operator_id": OP_ID},
        justification="audit-txn branch")
    return Branch("RECORD_SCOPE_REVIEW_DECISION", conn, intent,
                  "ScopeReviewDecided")


def _branch_evidence_transition() -> Branch:
    conn = _fresh()
    _insert_artifact(conn, "ev-y", "evidence")
    cls_ref = _digest_classification(
        conn, "fc-y", "DECLARED_CONSTRAINT_VIOLATION",
        falsifying_refs=["evidence:ev-y"])
    # The ratified REJECT_BRANCH approval, built directly: the ratified gate
    # never produces one for a class that requires human confirmation.
    _event(conn, EventType.CLASSIFICATION_ACTION_PROPOSED.value, "prop-rb", {
        "classification_ref": cls_ref, "action": "REJECT_BRANCH",
        "candidate_artifact_ref": "ev-y", "rationale": "r",
        "state": "EFFECTIVE"})
    _event(conn, EventType.CLASSIFICATION_ACTION_DECISION.value, "prop-rb", {
        "proposal_id": "prop-rb", "decision": "APPROVED", "rationale": "op"})
    intent = Intent(
        kind=IntentKind.EVIDENCE_TRANSITION, proposed_by="RESEARCHER",
        project_id="p1",
        payload={"evidence_artifact_ref": "evidence:ev-y",
                 "from_state": "SUPPORTED", "to_state": "REFUTED",
                 "ratification_ref": "prop-rb", "rationale": "decisive"},
        justification="audit-txn branch")
    return Branch("EVIDENCE_TRANSITION", conn, intent,
                  "EvidenceTransitionProposed")


def _branch_retract() -> Branch:
    conn = _fresh()
    _insert_artifact(conn, "src-a", "source_result")
    _event(conn, EventType.HUMAN_DECISION_RECEIVED.value, "hd-1", {
        "decision": "RETRACT_SOURCE", "source_ref": "src-a",
        "reason_digest": hashlib.sha256(
            b"source retracted by publisher").hexdigest()})
    return Branch("RETRACT_SOURCE", conn, _retract_intent(), "SourceRetracted")


def _branch_curate() -> Branch:
    conn = _fresh()
    seed = _curate_seed(conn)
    return Branch("CURATE_KNOWLEDGE", conn, _curate_intent(conn, seed),
                  "CuratedKnowledgeAdmitted")


def _branch_contradiction() -> Branch:
    conn = _fresh()
    a, b = _conflicting_pair(conn)
    return Branch("RECORD_CONTRADICTION", conn,
                  _contradiction_intent(a, b), "ContradictionDetected")


def _branch_resolution() -> Branch:
    conn = _fresh()
    a, b = _conflicting_pair(conn)
    apply_intent(conn, _contradiction_intent(a, b), clock=_clock)
    cid = contradiction_id_of(a, b)
    resolution_id = _contradiction_resolution_id(cid)
    decision_ref = "contradiction-decision-" + resolution_id
    _event(conn, EventType.HUMAN_DECISION_RECEIVED.value, decision_ref, {
        "decision": "CONTRADICTION_RESOLUTION",
        "resolution_id": resolution_id,
        "contradiction_id": cid,
        "operator_id": OP_ID,
        "rationale": "audit-txn"})
    intent = Intent(
        kind=IntentKind.CONTRADICTION_RESOLUTION,
        proposed_by="DETERMINISTIC", project_id="p1",
        payload={"contradiction_id": cid,
                 "human_decision_ref": decision_ref,
                 "operator_id": OP_ID},
        justification="audit-txn branch")
    return Branch("CONTRADICTION_RESOLUTION", conn, intent,
                  "ContradictionResolved")


def _branch_record_classification() -> Branch:
    conn = _fresh()
    intent = _record_classification_seed(conn)
    return Branch("RECORD_CLASSIFICATION", conn, intent, None)


def _branch_revoke() -> Branch:
    conn = _fresh()
    intent = Intent(
        kind=IntentKind.REVOKE_OPERATOR_CREDENTIAL, proposed_by="DIRECTOR",
        project_id="p1",
        payload={"operator_id": OP_ID, "reason": "lost device"},
        justification="audit-txn branch")
    return Branch("REVOKE_OPERATOR_CREDENTIAL", conn, intent,
                  "OperatorCredentialRevoked")


def _branch_task() -> Branch:
    conn = _fresh()
    intent = Intent(
        kind=IntentKind.ADMIT_TASK, proposed_by="DETERMINISTIC",
        project_id="p1", payload=_task_payload(),
        justification="audit-txn branch")
    return Branch("ADMIT_TASK", conn, intent, "TaskCreated")


BRANCHES: list[Callable[[], Branch]] = [
    _branch_program,
    _branch_emit_parallel,
    _branch_propose_action,
    _branch_resolve,
    _branch_scope_review,
    _branch_evidence_transition,
    _branch_retract,
    _branch_curate,
    _branch_contradiction,
    _branch_resolution,
    _branch_record_classification,
    _branch_revoke,
    _branch_task,
]


# ── falsifier 1: fault BETWEEN the mutation and the COMMIT ─────────────────


def _inject_pre_commit_fault(monkeypatch) -> None:
    """Raise only for the IntentApplied append, in both writer bindings."""
    real_repo = repo_mod._append_event_to_db

    def boom(conn, clock, event_type, *args, **kwargs):
        if event_type == "IntentApplied":
            raise RuntimeError("injected fault before COMMIT")
        return real_repo(conn, clock, event_type, *args, **kwargs)

    monkeypatch.setattr(repo_mod, "_append_event_to_db", boom)
    monkeypatch.setattr(gateway_mod, "_append_event_to_db", boom)


def _curated_count(conn: sqlite3.Connection) -> int:
    return _count(conn, "SELECT COUNT(*) FROM curated_knowledge_entries")


def _classification_count(conn: sqlite3.Connection) -> int:
    return _count(
        conn, "SELECT COUNT(*) FROM artifacts WHERE artifact_type = ?",
        (FC_TYPE,))


@pytest.mark.parametrize(
    "build, count_mutation, mutation_event",
    [
        (_branch_task,
         lambda c: _count(c, "SELECT COUNT(*) FROM tasks"), "TaskCreated"),
        (_branch_curate, _curated_count, "CuratedKnowledgeAdmitted"),
        (_branch_record_classification, _classification_count, None),
    ],
    ids=["persistence-owner", "gateway-owner", "artifact-only-mutation"],
)
def test_fault_between_mutation_and_commit_leaves_neither_row(
    monkeypatch, build, count_mutation, mutation_event,
):
    """The crash window is closed in the forward direction: the audit append
    is in the mutation's transaction, so its failure takes the mutation
    down with it — and the refusal is still journalled as data."""
    branch = build()
    assert count_mutation(branch.conn) == 0
    _inject_pre_commit_fault(monkeypatch)

    with pytest.raises(RuntimeError):
        apply_intent(branch.conn, branch.intent, clock=_clock)

    assert count_mutation(branch.conn) == 0
    if mutation_event is not None:
        assert _count_type(branch.conn, mutation_event) == 0
    assert _count_type(branch.conn, "IntentApplied") == 0
    assert _count_type(branch.conn, "IntentRejected") == 1


# ── falsifier 2: fault AFTER the COMMIT ────────────────────────────────────


def test_fault_after_commit_leaves_both_rows(monkeypatch):
    """The backward direction: once the transaction commits, the mutation and
    its IntentApplied row are both durable — the post-commit fault cannot
    strand a mutation without its audit row."""
    branch = _branch_task()
    real_create = TaskRepository.create

    def create_then_raise(self, node, *, audit=None):
        real_create(self, node, audit=audit)
        raise RuntimeError("injected fault after COMMIT")

    monkeypatch.setattr(TaskRepository, "create", create_then_raise)

    with pytest.raises(RuntimeError):
        apply_intent(branch.conn, branch.intent, clock=_clock)

    assert _count(
        branch.conn, "SELECT COUNT(*) FROM tasks WHERE task_id = 't1'") == 1
    assert _count_type(branch.conn, "TaskCreated") == 1
    assert _count_type(branch.conn, "IntentApplied") == 1
    # The existing except-Exception arm still journals the fault as a
    # rejection; the mutation is durable, so the applied row is not a lie.
    assert _count_type(branch.conn, "IntentRejected") == 1


# ── falsifier 3: a rejection still journals its exact code ─────────────────


@pytest.mark.parametrize(
    "intent, code",
    [
        (Intent(kind=IntentKind.INSERT_TASK, proposed_by="DETERMINISTIC",
                project_id="p1", payload=_task_payload(),
                justification="role refusal"),
         ROLE),
        (Intent(kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
                project_id="p-missing", payload=_task_payload(),
                justification="project refusal"),
         PROJECT_NOT_FOUND),
        (Intent(kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
                project_id="p1", payload={**_task_payload(), "extra": 1},
                justification="payload refusal"),
         MALFORMED_PAYLOAD),
    ],
    ids=["role", "project", "payload"],
)
def test_rejection_journals_exact_code(intent, code):
    conn = _fresh()
    with pytest.raises(GatewayRejection) as exc:
        apply_intent(conn, intent, clock=_clock)
    assert exc.value.code == code

    rows = conn.execute(
        "SELECT * FROM events WHERE event_type = 'IntentRejected'").fetchall()
    assert len(rows) == 1
    assert rows[0]["reason"] == "intent rejected"
    assert rows[0]["caused_by"] == intent.proposed_by
    assert rows[0]["correlation_id"] == f"intent-{intent.kind.value}-{CLOCK}"
    payload = json.loads(rows[0]["payload_json"])
    assert payload == {
        "intent_kind": intent.kind.value,
        "proposed_by": intent.proposed_by,
        "project_id": intent.project_id,
        "justification": intent.justification,
    }
    assert _count_type(conn, "IntentApplied") == 0


# ── falsifier 4: stale project falls back to project_id = NULL ─────────────


def test_stale_project_rejection_falls_back_to_null_project():
    conn = _fresh()
    intent = Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p-missing", payload=_task_payload(),
        justification="stale project")

    with pytest.raises(GatewayRejection) as exc:
        apply_intent(conn, intent, clock=_clock)
    assert exc.value.code == PROJECT_NOT_FOUND

    rows = conn.execute(
        "SELECT * FROM events WHERE event_type = 'IntentRejected'").fetchall()
    assert len(rows) == 1
    assert rows[0]["project_id"] is None
    assert json.loads(rows[0]["payload_json"])["project_id"] == "p-missing"

    # No mutation table was touched.
    assert _count(conn, "SELECT COUNT(*) FROM tasks") == 0
    assert _count(conn, "SELECT COUNT(*) FROM task_dependencies") == 0
    assert _count_type(conn, "TaskCreated") == 0
    assert _count_type(conn, "IntentApplied") == 0


# ── falsifier 5: the 4 KiB cap refuses before any write ────────────────────


def test_4kib_cap_refuses_before_any_write():
    conn = _fresh()
    intent = Intent(
        kind=IntentKind.ADMIT_TASK, proposed_by="DETERMINISTIC",
        project_id="p1", payload=_task_payload(),
        justification="x" * 5000)

    with pytest.raises(GatewayRejection) as exc:
        apply_intent(conn, intent, clock=_clock)
    assert exc.value.code == MALFORMED_PAYLOAD

    assert _count(conn, "SELECT COUNT(*) FROM tasks") == 0
    assert _count_type(conn, "TaskCreated") == 0
    assert _count_type(conn, "IntentApplied") == 0
    assert _count_type(conn, "IntentRejected") == 1


def test_secret_bearing_audit_payload_refuses_before_any_write():
    """The same pre-write gate rejects a secret-format echo; the refusal is
    still journalled, with the offending value omitted and marked."""
    conn = _fresh()
    intent = Intent(
        kind=IntentKind.ADMIT_TASK, proposed_by="DETERMINISTIC",
        project_id="p1", payload=_task_payload(),
        justification="leaked ghp_" + "a" * 36)

    with pytest.raises(GatewayRejection) as exc:
        apply_intent(conn, intent, clock=_clock)
    assert exc.value.code == MALFORMED_PAYLOAD

    assert _count(conn, "SELECT COUNT(*) FROM tasks") == 0
    assert _count_type(conn, "IntentApplied") == 0
    rows = conn.execute(
        "SELECT * FROM events WHERE event_type = 'IntentRejected'").fetchall()
    assert len(rows) == 1
    payload = json.loads(rows[0]["payload_json"])
    assert "justification" not in payload
    expected_marker = (
        "justification=<omitted: value in 'justification' matches known "
        "secret format — rejected>")
    assert payload["audit_bounded"] == [expected_marker]


def test_over_cap_audit_append_rolls_the_mutation_back():
    """The direct half: inside a fused transaction an over-cap audit append
    takes the owner's except path and rolls the mutation back."""
    conn = _fresh()
    node = NodeContract(
        task_id="t-direct", project_id="p1", task_type="TOOL_TASK",
        idempotency_key="idem-direct")
    huge = AuditRecord(
        event_type="IntentApplied", project_id="p1",
        correlation_id="intent-ADMIT_TASK-direct", caused_by="DETERMINISTIC",
        reason="", payload={"blob": "x" * 5000})

    with pytest.raises(EventValidationError):
        TaskRepository(conn, frozen_clock(CLOCK)).create(node, audit=huge)

    assert _count(
        conn, "SELECT COUNT(*) FROM tasks WHERE task_id = 't-direct'") == 0
    assert _count_type(conn, "TaskCreated") == 0


# ── falsifier 6: one applied intent per branch is adjacent to its mutation ─


@pytest.mark.parametrize("build", BRANCHES, ids=[b.__name__ for b in BRANCHES])
def test_every_applied_intent_has_one_adjacent_audit_row(build):
    branch = build()
    mark = _max_event_id(branch.conn)
    result = apply_intent(branch.conn, branch.intent, clock=_clock)
    assert result.duplicate is False

    rows = _events_after(branch.conn, mark)
    applied = [r for r in rows if r["event_type"] == "IntentApplied"]
    assert len(applied) == 1, branch.label
    assert applied[0]["project_id"] == "p1"
    assert applied[0]["caused_by"] == branch.intent.proposed_by

    if branch.mutation_event is not None:
        mutations = [r for r in rows if r["event_type"] == branch.mutation_event]
        assert mutations, branch.label
        assert applied[0]["prev_hash"] == mutations[-1]["chain_hash"], (
            branch.label)
        assert applied[0]["event_id"] == mutations[-1]["event_id"] + 1
    else:
        # RECORD_CLASSIFICATION's mutation is an artifact row, not an event:
        # the audit row is chained onto the transaction's tip and is the very
        # next journal row. Its same-transaction membership is proven by
        # test_fault_between_mutation_and_commit_leaves_neither_row
        # (artifact-only-mutation case).
        previous = branch.conn.execute(
            "SELECT chain_hash FROM events WHERE event_id < ? "
            "ORDER BY event_id DESC LIMIT 1",
            (applied[0]["event_id"],)).fetchone()
        assert previous is not None
        assert applied[0]["prev_hash"] == previous["chain_hash"]


# ── falsifier 7: a duplicate replay writes nothing ─────────────────────────

_FINGERPRINT_TABLES = (
    "projects", "tasks", "task_dependencies", "artifacts",
    "provenance_edges", "research_programs", "contradictions",
    "curated_knowledge_entries", "curated_knowledge_retraction_basis",
    "curated_knowledge_supersession", "evidence_ladder_state",
    "scope_briefs",
)


def _state_fingerprint(conn: sqlite3.Connection) -> tuple:
    counts = tuple(
        (table, _count(conn, f"SELECT COUNT(*) FROM {table}"))
        for table in _FINGERPRINT_TABLES)
    credentials = tuple(
        tuple(row) for row in conn.execute(
            "SELECT operator_id, token_hash, revoked_at "
            "FROM operator_credentials ORDER BY operator_id").fetchall())
    return (counts, credentials)


@pytest.mark.parametrize("build", BRANCHES, ids=[b.__name__ for b in BRANCHES])
def test_duplicate_replay_lands_one_applied_row_and_no_write(build):
    branch = build()
    first = apply_intent(branch.conn, branch.intent, clock=_clock)
    assert first.duplicate is False

    before = _state_fingerprint(branch.conn)
    mark = _max_event_id(branch.conn)

    replay = apply_intent(branch.conn, branch.intent, clock=_clock)
    assert replay.duplicate is True

    rows = _events_after(branch.conn, mark)
    assert [r["event_type"] for r in rows].count("IntentApplied") == 1
    assert _count_type(branch.conn, "IntentRejected") == 0
    if branch.mutation_event is not None:
        assert not [r for r in rows
                    if r["event_type"] == branch.mutation_event]
    assert _state_fingerprint(branch.conn) == before


# ── falsifier 8: the chain still verifies after a fused apply ──────────────


@pytest.mark.parametrize(
    "build", [_branch_task, _branch_curate, _branch_program],
    ids=["persistence-owner", "gateway-owner", "program-owner"])
def test_chain_verifies_after_fused_apply(build):
    branch = build()
    apply_intent(branch.conn, branch.intent, clock=_clock)
    verdict = verify_journal(branch.conn)
    assert verdict["ok"] is True, verdict
    assert verdict["code"] == "CHAIN_OK"
    assert verdict["findings"] == ()
