"""S-2 characterization tests (DG-3A V-suite): HumanDecision
idempotent-append shared by the four V-a verdict surfaces.

Behavioral pins established BEFORE the extraction; assertions are
identical after it. Classification and resolution are exercised
end-to-end here (idempotent double-record, failure propagation,
ordering, project isolation); retraction-decision and curation are
covered by their existing suites (S5 retraction ingestion /
S5-L2 resolution; step7 curation registry), whose duplicate,
ordering, and scoping assertions are re-run unchanged before and
after the extraction.
"""
from __future__ import annotations

import json
from unittest import mock

import pytest

from hermes.core import frozen_clock
from hermes.core.events import EventType
from hermes.core.node import NodeContract
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    OperatorCredentialRepository,
    ProjectRepository,
    TaskRepository,
)
from hermes.research.contradictions import contradiction_id_of
from hermes.research.controller import Controller

CLOCK = "2026-01-01T00:00:00.000000+00:00"
OP_ID = "op-1"
OP_TOKEN = "op-token-1-long"


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, frozen_clock(CLOCK)).create("p1", "Test")
    ProjectRepository(conn, frozen_clock(CLOCK)).create("p2", "Other")
    OperatorCredentialRepository(conn, frozen_clock(CLOCK)).register(
        OP_ID, OP_TOKEN, "Test Operator")
    yield conn
    conn.close()


def _make(db, project="p1"):
    return Controller(db, project_id=project, clock=frozen_clock(CLOCK))


def _program(db, program_id="rp-1", *, project="p1"):
    db.execute(
        """INSERT INTO research_programs
           (program_id, project_id, version, content_hash, supersedes_id,
            scope_ref, epistemic_objective, compiler_version, policy_version,
            schema_version, input_hash, hypothesis_json, prediction_json,
            discrimination_json, evidence_json, gate_json, methodology_json,
            task_graph_template_ref, produced_by, reason, created_at)
           VALUES (?, ?, 1, ?, NULL, 'b', 'o', 'c1', 'p1', '1', 'ih', ?,
                   ?, '[]', '[]', '[]', '[]', NULL, 'director', NULL, ?)""",
        (program_id, project, "ch-" + program_id,
         json.dumps([{"ref": "h1", "ladder_target": "SUPPORTED",
                      "falsification_condition": "fc", "rival_of": None,
                      "rival_status": None}]),
         json.dumps([{"ref": "p1"}]), CLOCK))
    db.commit()


def _task(db, task_id, *, project="p1"):
    TaskRepository(db, frozen_clock(CLOCK)).create(NodeContract(
        task_id=task_id, project_id=project, task_type="TOOL_TASK",
        idempotency_key=f"idem-{task_id}", dependencies=[]))
    db.execute("UPDATE tasks SET status = 'RUNNING' WHERE task_id = ?",
               (task_id,))
    db.commit()


def _chain(db, *, ev_id, ev_hash, outcome_id, task_id, project="p1"):
    for aid, ch in ((outcome_id, f"outhash-{outcome_id}"),
                    (ev_id, ev_hash)):
        db.execute(
            """INSERT INTO artifacts
               (artifact_id, project_id, task_id, artifact_type,
                content_hash, size_bytes, storage_path, producer,
                metadata_json, created_at)
               VALUES (?, ?, NULL, 'source_result', ?, 1, 'x', 't',
                       NULL, ?)""",
            (aid, project, ch, CLOCK))
    for child, parent in ((outcome_id, task_id), (ev_id, outcome_id)):
        db.execute(
            """INSERT INTO provenance_edges
               (artifact_id, upstream_id, edge_type, created_at)
               VALUES (?, ?, 'derived_from', ?)""",
            (child, parent, CLOCK))
    db.commit()


def _classify(db, task_id="t1", **kw):
    return _make(db).record_failure_classification(
        program_ref="rp-1", hypothesis_ref="h1",
        failure_class="DECLARED_CONSTRAINT_VIOLATION",
        evidence_refs=["source_result:evhash1"],
        falsifying_evidence_refs=["source_result:evhash1"],
        explanation="operator analysis", classifier_version="1.0",
        constraint_ref="hypothesis:h1:falsification_condition",
        proposed_by="operator:op-1", producing_task_id=task_id,
        rationale="", operator_id=OP_ID, operator_token=OP_TOKEN, **kw)


def _hd_count(db, correlation):
    return db.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = ? "
        "AND correlation_id = ?",
        (EventType.HUMAN_DECISION_RECEIVED.value, correlation)
        ).fetchone()["c"]


class TestCS21IdempotentDoubleRecord:
    def test_classification_double_submit_one_decision(self, db):
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        r1 = _classify(db)
        assert r1["rejected"] is False
        r2 = _classify(db)
        assert r2["duplicate"] is True
        assert r2["entity_id"] == r1["entity_id"]
        assert _hd_count(db, r1["decision_ref"]) == 1

    def test_resolution_double_submit_one_decision(self, db):
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        a = _classify(db)["entity_id"]
        b = _make(db).record_failure_classification(
            program_ref="rp-1", hypothesis_ref="h1",
            failure_class="IMPLEMENTATION_FAILURE",
            evidence_refs=["source_result:evhash1"],
            falsifying_evidence_refs=["source_result:evhash1"],
            explanation="operator analysis IMPLEMENTATION_FAILURE",
            classifier_version="1.0",
            failed_mechanism_ref="prediction:p1",
            proposed_by="operator:op-1", producing_task_id="t1",
            rationale="", operator_id=OP_ID,
            operator_token=OP_TOKEN)["entity_id"]
        cid = _make(db).detect_contradictions()["recorded"][0]
        assert cid == contradiction_id_of(a, b)
        c1 = _make(db).record_contradiction_resolution(
            contradiction_id=cid, operator_id=OP_ID,
            operator_token=OP_TOKEN)
        assert c1["rejected"] is False
        c2 = _make(db).record_contradiction_resolution(
            contradiction_id=cid, operator_id=OP_ID,
            operator_token=OP_TOKEN)
        assert c2["duplicate"] is True
        hd_ref = f"contradiction-decision-{c1['resolution_id']}" \
            if "resolution_id" in c1 else None
        assert hd_ref is not None
        assert _hd_count(db, hd_ref) == 1


class TestCS22FailurePropagation:
    def test_classification_append_failure_raises_no_gateway_no_state(
            self, db):
        import hermes.research.controller as ctrl_mod
        import hermes.research.verdict_decisions as vd_mod
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")

        def _failing(conn, clock, event_type, *a, **kw):
            raise RuntimeError("simulated journal failure")

        arts_before = db.execute(
            "SELECT COUNT(*) c FROM artifacts").fetchone()["c"]
        evts_before = db.execute(
            "SELECT COUNT(*) c FROM events").fetchone()["c"]
        # Both append seams are patched so the pin holds pre- AND
        # post-extraction: the controller performs the HumanDecision
        # append itself pre-extraction; the shared helper performs it
        # post-extraction. Either way the failure must abort the verdict
        # BEFORE any gateway admission, leaving zero partial state.
        with mock.patch.object(ctrl_mod, "_append_event_to_db", _failing), \
                mock.patch.object(vd_mod, "_append_event_to_db", _failing), \
                pytest.raises(RuntimeError):
            _classify(db)
        assert db.execute(
            "SELECT COUNT(*) c FROM artifacts").fetchone()["c"] \
            == arts_before
        assert db.execute(
            "SELECT COUNT(*) c FROM events").fetchone()["c"] \
            == evts_before
        assert ctrl_mod._append_event_to_db is not None

    def test_resolution_append_failure_raises_no_gateway_no_state(
            self, db):
        import hermes.research.controller as ctrl_mod
        import hermes.research.verdict_decisions as vd_mod
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        a = _classify(db)["entity_id"]
        b = _make(db).record_failure_classification(
            program_ref="rp-1", hypothesis_ref="h1",
            failure_class="IMPLEMENTATION_FAILURE",
            evidence_refs=["source_result:evhash1"],
            falsifying_evidence_refs=["source_result:evhash1"],
            explanation="operator analysis IMPLEMENTATION_FAILURE",
            classifier_version="1.0",
            failed_mechanism_ref="prediction:p1",
            proposed_by="operator:op-1", producing_task_id="t1",
            rationale="", operator_id=OP_ID,
            operator_token=OP_TOKEN)["entity_id"]
        cid = _make(db).detect_contradictions()["recorded"][0]
        assert cid == contradiction_id_of(a, b)

        def _failing(conn, clock, event_type, *a, **kw):
            raise RuntimeError("simulated journal failure")

        row_before = db.execute(
            "SELECT status, resolution_event_ref FROM contradictions "
            "WHERE contradiction_id = ?", (cid,)).fetchone()
        row_before = (row_before["status"],
                      row_before["resolution_event_ref"])
        evts_before = db.execute(
            "SELECT COUNT(*) c FROM events").fetchone()["c"]
        with mock.patch.object(ctrl_mod, "_append_event_to_db", _failing), \
                mock.patch.object(vd_mod, "_append_event_to_db", _failing), \
                pytest.raises(RuntimeError):
            _make(db).record_contradiction_resolution(
                contradiction_id=cid, operator_id=OP_ID,
                operator_token=OP_TOKEN)
        assert db.execute(
            "SELECT COUNT(*) c FROM events").fetchone()["c"] \
            == evts_before
        row_after = db.execute(
            "SELECT status, resolution_event_ref FROM contradictions "
            "WHERE contradiction_id = ?", (cid,)).fetchone()
        assert (row_after["status"], row_after["resolution_event_ref"]) \
            == row_before
        # The caller (not the helper) still released its lease in finally.
        assert db.execute(
            "SELECT COUNT(*) c FROM scheduler_lock WHERE id = 0"
        ).fetchone()["c"] == 0


class TestCS23Ordering:
    def test_decision_precedes_resolution_admission(self, db):
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        a = _classify(db)["entity_id"]
        b = _make(db).record_failure_classification(
            program_ref="rp-1", hypothesis_ref="h1",
            failure_class="IMPLEMENTATION_FAILURE",
            evidence_refs=["source_result:evhash1"],
            falsifying_evidence_refs=["source_result:evhash1"],
            explanation="x", classifier_version="1.0",
            failed_mechanism_ref="prediction:p1",
            proposed_by="operator:op-1", producing_task_id="t1",
            rationale="", operator_id=OP_ID,
            operator_token=OP_TOKEN)["entity_id"]
        cid = contradiction_id_of(a, b)
        _make(db).detect_contradictions()
        res = _make(db).record_contradiction_resolution(
            contradiction_id=cid, operator_id=OP_ID,
            operator_token=OP_TOKEN)
        assert res["rejected"] is False
        hd = db.execute(
            "SELECT event_id FROM events WHERE event_type = ? "
            "AND correlation_id = ?",
            (EventType.HUMAN_DECISION_RECEIVED.value,
             f"contradiction-decision-{res['resolution_id']}")).fetchone()
        done = db.execute(
            "SELECT event_id FROM events WHERE event_type = ? "
            "AND correlation_id = ?",
            (EventType.CONTRADICTION_RESOLVED.value,
             res["resolution_id"])).fetchone()
        assert hd is not None and done is not None
        assert hd["event_id"] < done["event_id"]


class TestCS25Isolation:
    def test_foreign_decision_ref_refused(self, db):
        from hermes.core.intents import Intent, IntentKind
        from hermes.research.gateway import (
            GatewayRejection,
            apply_intent,
        )
        _program(db)
        _program(db, program_id="rp-x", project="p2")
        _task(db, "t1")
        _task(db, "t2", project="p2")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        _chain(db, ev_id="art-ev2", ev_hash="evhash2",
               outcome_id="art-out2", task_id="t2", project="p2")
        r1 = _classify(db)
        assert r1["rejected"] is False
        # p1's decision correlation replayed under p2 must not satisfy
        # p2's project-scoped dereference (fail-closed PROPOSAL).
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.RECORD_CLASSIFICATION,
                proposed_by="DETERMINISTIC", project_id="p2",
                justification="s2 isolation probe",
                payload={"program_ref": "rp-x",
                         "hypothesis_ref": "h1",
                         "failure_class": "DECLARED_CONSTRAINT_VIOLATION",
                         "evidence_refs": ["source_result:evhash2"],
                         "falsifying_evidence_refs": [
                             "source_result:evhash2"],
                         "explanation": "x", "classifier_version": "1.0",
                         "constraint_ref":
                             "hypothesis:h1:falsification_condition",
                         "failed_mechanism_ref": None,
                         "regime_ref": None, "resource_gap": None,
                         "scope_brief_ref": None,
                         "scope_brief_field": None,
                         "contributing_factors": [],
                         "proposed_by": "operator:op-1",
                         "producing_task_id": "t2",
                         "human_decision_ref": r1["decision_ref"],
                         "operator_id": OP_ID}))
        assert exc.value.code == "PROPOSAL"
        assert _hd_count(db, r1["decision_ref"]) == 1
