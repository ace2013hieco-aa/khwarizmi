"""COND-TYPE (GAP-1 D4-A): condition_type ingestion + command-hash v2.

Pins the ruling D4-A contract: RECORD_CLASSIFICATION accepts the closed
``ConditionType`` key (absent/None == the declared ``UNDETERMINED``
default), the key enters the canonical command bytes, new decisions bind
the v2 hash, and pre-bump (v1) decisions still verify under dual-read for
the default mapping only. Classification content identity is unchanged:
the ``fc_`` hash already covered condition_type.
"""
from __future__ import annotations

import json

import pytest

from hermes.core import frozen_clock
from hermes.core.events import EventType
from hermes.core.intents import Intent, IntentKind
from hermes.core.node import NodeContract
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    OperatorCredentialRepository,
    ProjectRepository,
    TaskRepository,
    _append_event_to_db,
)
from hermes.research.controller import Controller
from hermes.research.failure_classification import (
    CLASSIFICATION_COMMAND_HASH_VERSION,
    ConditionType,
    FailureClassificationDraft,
    FalsificationRecord,
    classification_command_hash,
    classification_command_preimage,
    classify_failure,
    legacy_classification_command_hash,
)
from hermes.research.gateway import (
    MALFORMED_PAYLOAD,
    PROPOSAL,
    GatewayRejection,
    apply_intent,
)
from hermes.research.programs import canonical_json, sha256_hex

CLOCK = "2026-01-01T00:00:00.000000+00:00"
OP_ID = "op-1"
OP_TOKEN = "op-token-1-long"
EXPLANATION = "operator analysis ENVIRONMENT_MISMATCH"
_MISSING = object()


def _insert_program(db, program_id="rp-1", *, project="p1"):
    db.execute(
        """INSERT INTO research_programs
           (program_id, project_id, version, content_hash, supersedes_id,
            scope_ref, epistemic_objective, compiler_version, policy_version,
            schema_version, input_hash, hypothesis_json, prediction_json,
            discrimination_json, evidence_json, gate_json, methodology_json,
            task_graph_template_ref, produced_by, reason, created_at)
           VALUES (?, ?, ?, ?, NULL, 'b', 'o', 'c1', 'p1', '1', 'ih', ?,
                   ?, '[]', '[]', '[]', '[]', NULL, 'director', NULL, ?)""",
        (program_id, project, 1, "ch-" + program_id,
         json.dumps([{"ref": "h1", "ladder_target": "SUPPORTED",
                      "falsification_condition": "fc", "rival_of": None,
                      "rival_status": None}]),
         json.dumps([{"ref": "p1"}]), CLOCK),
    )


def _insert_evidence_chain(db, *, ev_id="art-ev1", ev_hash="evhash1",
                           outcome_id="art-out1", task_id="t-prod",
                           project="p1"):
    repo = TaskRepository(db, frozen_clock(CLOCK))
    repo.create(NodeContract(
        task_id=task_id, project_id=project, task_type="TOOL_TASK",
        idempotency_key=f"idem-{task_id}", dependencies=[]))
    db.execute("UPDATE tasks SET status = 'RUNNING' WHERE task_id = ?",
               (task_id,))
    for aid, atype, ch in ((outcome_id, "source_result",
                            f"outhash-{outcome_id}"),
                           (ev_id, "source_result", ev_hash)):
        db.execute(
            """INSERT INTO artifacts
               (artifact_id, project_id, task_id, artifact_type,
                content_hash, size_bytes, storage_path, producer,
                metadata_json, created_at)
               VALUES (?, ?, NULL, ?, ?, 1, 'x', 't', NULL, ?)""",
            (aid, project, atype, ch, CLOCK))
    for child, parent in ((outcome_id, task_id), (ev_id, outcome_id)):
        db.execute(
            """INSERT INTO provenance_edges
               (artifact_id, upstream_id, edge_type, created_at)
               VALUES (?, ?, 'derived_from', ?)""",
            (child, parent, CLOCK))


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, frozen_clock(CLOCK)).create("p1", "Test")
    OperatorCredentialRepository(conn, frozen_clock(CLOCK)).register(
        OP_ID, OP_TOKEN, "Test Operator")
    _insert_program(conn)
    _insert_evidence_chain(conn)
    yield conn
    conn.close()


def _command(condition_type=_MISSING):
    command = {
        "program_ref": "rp-1",
        "hypothesis_ref": "h1",
        "failure_class": "ENVIRONMENT_MISMATCH",
        "evidence_refs": ["source_result:evhash1"],
        "falsifying_evidence_refs": ["source_result:evhash1"],
        "explanation": EXPLANATION,
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
    }
    if condition_type is not _MISSING:
        command["condition_type"] = condition_type
    return command


def _classify(db, *, condition_type=_MISSING):
    kwargs = {}
    if condition_type is not _MISSING:
        kwargs["condition_type"] = condition_type
    return Controller(db, project_id="p1", clock=frozen_clock(CLOCK)) \
        .record_failure_classification(
            program_ref="rp-1", hypothesis_ref="h1",
            failure_class="ENVIRONMENT_MISMATCH",
            evidence_refs=["source_result:evhash1"],
            falsifying_evidence_refs=["source_result:evhash1"],
            explanation=EXPLANATION,
            classifier_version="1.0",
            regime_ref="ICSS-v1:low-vol",
            proposed_by=f"operator:{OP_ID}",
            producing_task_id="t-prod",
            operator_id=OP_ID, operator_token=OP_TOKEN, **kwargs)


def _apply(db, command, decision_ref):
    payload = {**command, "human_decision_ref": decision_ref,
               "operator_id": OP_ID}
    return apply_intent(db, Intent(
        kind=IntentKind.RECORD_CLASSIFICATION,
        proposed_by="DETERMINISTIC", project_id="p1",
        justification="COND-TYPE test", payload=payload))


def _record_decision(db, ref, classification_hash):
    _append_event_to_db(
        db, frozen_clock(CLOCK),
        EventType.HUMAN_DECISION_RECEIVED.value,
        project_id="p1", correlation_id=ref, caused_by="operator",
        reason="operator classification verdict",
        payload={"decision": "RECORD_CLASSIFICATION",
                 "classification_hash": classification_hash,
                 "operator_id": OP_ID, "rationale": ""})


def _metadata(db, classification_id):
    row = db.execute(
        "SELECT metadata_json FROM artifacts WHERE artifact_id = ?",
        (classification_id,)).fetchone()
    return json.loads(row["metadata_json"])


def _artifact_count(db):
    return db.execute(
        "SELECT COUNT(*) c FROM artifacts WHERE artifact_type = ?",
        ("failure_classification",)).fetchone()["c"]


def _expected_identity(condition_type):
    record = FalsificationRecord(
        project_id="p1", hypothesis_ref="h1", program_ref="rp-1",
        falsifying_evidence_refs=("source_result:evhash1",))
    draft = FailureClassificationDraft(
        failure_class="ENVIRONMENT_MISMATCH",
        explanation=EXPLANATION,
        evidence_refs=("source_result:evhash1",),
        regime_ref="ICSS-v1:low-vol",
        proposed_by=f"operator:{OP_ID}",
        classifier_version="1.0",
        condition_type=condition_type)
    result = classify_failure(
        record, draft,
        evidence_resolver=lambda _pid, _ref: True,
        regime_resolver=lambda _pid, _ref: True)
    assert result.admitted and result.classification is not None
    return result.classification.classification_id


class TestCommandHashVersion:
    def test_v2_preimage_carries_condition_type_and_hash_version(self):
        command = _command("ACCIDENTAL")
        preimage = classification_command_preimage(command)
        assert CLASSIFICATION_COMMAND_HASH_VERSION == "2"
        assert '"condition_type":"ACCIDENTAL"' in preimage
        assert '"hash_version":"2"' in preimage
        assert classification_command_hash(command) == (
            "classify_" + sha256_hex(preimage)[:24])

    def test_absent_condition_type_hashes_as_undetermined(self):
        absent = _command()
        explicit = _command("UNDETERMINED")
        assert classification_command_preimage(absent) == (
            classification_command_preimage(explicit))
        assert classification_command_hash(absent) == (
            classification_command_hash(explicit))
        assert '"condition_type":"UNDETERMINED"' in (
            classification_command_preimage(absent))

    def test_condition_type_changes_the_command_hash(self):
        hashes = {
            classification_command_hash(_command(condition_type))
            for condition_type in ("INTRINSIC", "ACCIDENTAL", "UNDETERMINED")
        }
        assert len(hashes) == 3

    def test_legacy_hash_is_the_pre_cond_type_canonical_bytes(self):
        command = _command("INTRINSIC")
        legacy_projection = {
            "program_ref": "rp-1",
            "hypothesis_ref": "h1",
            "failure_class": "ENVIRONMENT_MISMATCH",
            "evidence_refs": ["source_result:evhash1"],
            "falsifying_evidence_refs": ["source_result:evhash1"],
            "explanation": EXPLANATION,
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
        }
        expected = "classify_" + sha256_hex(
            canonical_json(legacy_projection))[:24]
        assert legacy_classification_command_hash(command) == expected
        assert legacy_classification_command_hash(command) != (
            classification_command_hash(command))


class TestGatewayConditionType:
    def test_intrinsic_condition_is_admitted_with_narrow_action_set(self, db):
        out = _classify(db, condition_type="INTRINSIC")
        assert out["rejected"] is False, out
        meta = _metadata(db, out["entity_id"])
        assert meta["condition_type"] == "INTRINSIC"
        assert meta["permitted_actions"] == ["PROPOSE_SCOPE_NARROWING"]
        assert out["classification_hash"] == (
            classification_command_hash(_command("INTRINSIC")))
        decision = db.execute(
            "SELECT payload_json FROM events WHERE correlation_id = ? "
            "AND event_type = ?",
            (out["decision_ref"],
             EventType.HUMAN_DECISION_RECEIVED.value)).fetchone()
        assert json.loads(decision["payload_json"])["classification_hash"] == (
            out["classification_hash"])

    def test_default_condition_type_is_undetermined(self, db):
        command = _command()
        ref = "classification-decision-default"
        _record_decision(db, ref, classification_command_hash(command))
        out = _apply(db, command, ref)
        assert out.duplicate is False
        meta = _metadata(db, out.entity_id)
        assert meta["condition_type"] == "UNDETERMINED"
        assert meta["permitted_actions"] == [
            "PROPOSE_PARALLEL_REGIME_TEST", "PROPOSE_SCOPE_NARROWING"]

    def test_unknown_condition_type_refuses_as_malformed_payload(self, db):
        for forged in ("BOGUS", 7):
            with pytest.raises(GatewayRejection) as exc:
                _apply(db, _command(forged), "hd-any")
            assert exc.value.code == MALFORMED_PAYLOAD
            assert "condition_type" in str(exc.value)
        assert _artifact_count(db) == 0

    def test_legacy_decision_verifies_under_dual_read_same_identity(self, db):
        command = _command()
        legacy_hash = legacy_classification_command_hash(command)
        ref = "classification-decision-legacy-1"
        _record_decision(db, ref, legacy_hash)
        out = _apply(db, command, ref)
        assert out.duplicate is False
        assert out.entity_id == _expected_identity(
            ConditionType.UNDETERMINED)
        meta = _metadata(db, out.entity_id)
        assert meta["condition_type"] == "UNDETERMINED"
        decision = db.execute(
            "SELECT payload_json FROM events WHERE correlation_id = ? "
            "AND event_type = ?",
            (ref, EventType.HUMAN_DECISION_RECEIVED.value)).fetchone()
        assert json.loads(decision["payload_json"])["classification_hash"] == (
            legacy_hash)

    def test_legacy_decision_does_not_authorize_non_default_condition(self, db):
        command = _command("INTRINSIC")
        ref = "classification-decision-legacy-2"
        _record_decision(db, ref, legacy_classification_command_hash(command))
        with pytest.raises(GatewayRejection) as exc:
            _apply(db, command, ref)
        assert exc.value.code == PROPOSAL
        assert _artifact_count(db) == 0

    def test_new_decision_binds_the_condition_type(self, db):
        command = _command("INTRINSIC")
        ref = "classification-decision-v2-1"
        _record_decision(db, ref, classification_command_hash(command))
        out = _apply(db, command, ref)
        assert out.duplicate is False
        with pytest.raises(GatewayRejection) as exc:
            _apply(db, _command("ACCIDENTAL"), ref)
        assert exc.value.code == PROPOSAL
        assert _artifact_count(db) == 1


class TestConditionTypeIdentity:
    def test_same_content_and_condition_type_is_stable(self, db):
        first = _classify(db, condition_type="INTRINSIC")
        second = _classify(db, condition_type="INTRINSIC")
        assert first["rejected"] is False, first
        assert second["rejected"] is False, second
        assert second["duplicate"] is True
        assert second["entity_id"] == first["entity_id"]
        assert second["classification_hash"] == first["classification_hash"]
        assert _artifact_count(db) == 1
        decisions = db.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type = ?",
            (EventType.HUMAN_DECISION_RECEIVED.value,)).fetchone()["c"]
        assert decisions == 1

    def test_different_condition_type_is_a_distinct_record(self, db):
        intrinsic = _classify(db, condition_type="INTRINSIC")
        accidental = _classify(db, condition_type="ACCIDENTAL")
        assert intrinsic["rejected"] is False, intrinsic
        assert accidental["rejected"] is False, accidental
        assert accidental["duplicate"] is False
        assert accidental["entity_id"] != intrinsic["entity_id"]
        assert accidental["classification_hash"] != (
            intrinsic["classification_hash"])
        assert _artifact_count(db) == 2
        assert _metadata(db, intrinsic["entity_id"])[
            "permitted_actions"] == ["PROPOSE_SCOPE_NARROWING"]
        assert _metadata(db, accidental["entity_id"])[
            "permitted_actions"] == [
                "PROPOSE_PARALLEL_REGIME_TEST", "PROPOSE_SCOPE_NARROWING"]
