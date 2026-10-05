"""S-1 characterization tests (DG-2 C1–C8): detector row derivation.

Behavioral first (public Controller behavior → same output), plus
direct row-shape pins through the preserved Controller facade.
The facade keeps every assertion location-agnostic across the
S-1 extraction into contradiction_candidates.
"""
from __future__ import annotations

import json

import pytest

from hermes.core import frozen_clock
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


def _classify(db, *, failure_class, evidence_ref, task_id, **kw):
    return _make(db).record_failure_classification(
        program_ref="rp-1", hypothesis_ref="h1",
        failure_class=failure_class, evidence_refs=[evidence_ref],
        falsifying_evidence_refs=[evidence_ref],
        explanation=f"operator analysis {failure_class}",
        classifier_version="1.0", proposed_by="operator:op-1",
        producing_task_id=task_id, rationale="",
        operator_id=OP_ID, operator_token=OP_TOKEN, **kw)


def _dcv(db, ref, task_id, **kw):
    return _classify(
        db, failure_class="DECLARED_CONSTRAINT_VIOLATION",
        evidence_ref=ref, task_id=task_id,
        constraint_ref="hypothesis:h1:falsification_condition", **kw)


def _impl(db, ref, task_id, **kw):
    return _classify(
        db, failure_class="IMPLEMENTATION_FAILURE",
        evidence_ref=ref, task_id=task_id,
        failed_mechanism_ref="prediction:p1", **kw)


def _pair(db, ev_hash="evhash1", task_id="t1"):
    a = _dcv(db, f"source_result:{ev_hash}", task_id)["entity_id"]
    b = _impl(db, f"source_result:{ev_hash}", task_id)["entity_id"]
    return a, b


def _rows_by_id(db, project="p1"):
    return {r["artifact_id"]: r
            for r in _make(db, project)._detector_candidate_rows()}


class TestC1RowShape:
    def test_fields_and_values(self, db):
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        a, _b = _pair(db)
        rows = _rows_by_id(db)
        assert set(rows) == {a, [k for k in rows if k != a][0]}
        row = rows[a]
        assert row == {
            "artifact_id": a,
            "project_id": "p1",
            "program_ref": "rp-1",
            "hypothesis_ref": "h1",
            "failure_class": "DECLARED_CONSTRAINT_VIOLATION",
            "evidence": ["art-ev1"],
            "invalidated": False,
        }

    def test_invalidated_flag(self, db):
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        a, _b = _pair(db)
        meta = json.loads(db.execute(
            "SELECT metadata_json FROM artifacts WHERE artifact_id = ?",
            (a,)).fetchone()["metadata_json"])
        meta["invalidation_marker"] = "INVALIDATED"
        db.execute(
            "UPDATE artifacts SET metadata_json = ? WHERE artifact_id = ?",
            (json.dumps(meta), a))
        db.commit()
        assert _rows_by_id(db)[a]["invalidated"] is True

    def test_detection_outcome_from_rows(self, db):
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        a, b = _pair(db)
        det = _make(db).detect_contradictions()
        assert det["recorded"] == [contradiction_id_of(a, b)]


class TestC2Ordering:
    def test_evidence_sorted_and_cids_deterministic(self, db):
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev2", ev_hash="evhash2",
               outcome_id="art-out2", task_id="t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        a, b = _pair(db, "evhash1", "t1")
        rows = _rows_by_id(db)
        assert rows[a]["evidence"] == sorted(rows[a]["evidence"])
        det = _make(db).detect_contradictions()
        assert det["recorded"] == sorted(det["recorded"])
        assert det["recorded"] == [contradiction_id_of(a, b)]


class TestC3Isolation:
    def test_no_cross_project_rows(self, db):
        _program(db)
        _program(db, program_id="rp-x", project="p2")
        _task(db, "t1")
        _task(db, "t2", project="p2")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        _chain(db, ev_id="art-ev2", ev_hash="evhash2",
               outcome_id="art-out2", task_id="t2", project="p2")
        p1_ids = set(_rows_by_id(db, "p1"))
        p2_ids = set(_rows_by_id(db, "p2"))
        assert p1_ids.isdisjoint(p2_ids)
        assert _make(db, "p2").detect_contradictions()["recorded"] == []


class TestC4Retraction:
    def test_retracted_evidence_contributes_nothing(self, db):
        from hermes.core.events import EventType
        from hermes.core.intents import Intent, IntentKind
        from hermes.persistence.repositories import _append_event_to_db
        from hermes.research.gateway import apply_intent
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        a, b = _pair(db)
        assert _rows_by_id(db)[a]["evidence"] == ["art-ev1"]
        _append_event_to_db(
            db, frozen_clock(CLOCK),
            EventType.HUMAN_DECISION_RECEIVED.value,
            project_id="p1", correlation_id="hd-1", caused_by="operator",
            reason="operator decision", payload={"decision": "RETRACT"})
        apply_intent(db, Intent(
            kind=IntentKind.RETRACT_SOURCE, proposed_by="DETERMINISTIC",
            project_id="p1", justification="s1",
            payload={"source_ref": "source_result:evhash1",
                     "reason": "retracted", "human_decision_ref": "hd-1"}))
        rows = _rows_by_id(db)
        assert rows[a]["evidence"] == []
        assert rows[b]["evidence"] == []
        assert _make(db).detect_contradictions()["recorded"] == []


class TestC5Exceptions:
    def test_corrupt_rows_skipped_never_raise(self, db):
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        _pair(db)
        db.execute(
            """INSERT INTO artifacts (artifact_id, project_id, task_id,
               artifact_type, content_hash, size_bytes, storage_path,
               producer, metadata_json, created_at)
               VALUES ('fc-bogus', 'p1', NULL, 'failure_classification',
                       'bogushash', 1, 'x', 't', 'NOT-JSON', ?)""",
            (CLOCK,))
        db.commit()
        rows = _make(db)._detector_candidate_rows()
        assert all(r["artifact_id"] != "fc-bogus" for r in rows)
        assert _make(db).detect_contradictions()["recorded"] != []


class TestC6Empty:
    def test_empty_db_empty_rows(self, db):
        assert _make(db)._detector_candidate_rows() == []
        assert _make(db)._open_contradiction_parties() == []
        assert _make(db).detect_contradictions()["recorded"] == []


class TestC7Repeated:
    def test_repeated_evaluation_identical(self, db):
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        a, b = _pair(db)
        ctrl = _make(db)
        first = ctrl._detector_candidate_rows()
        second = ctrl._detector_candidate_rows()
        assert first == second
        d1 = ctrl.detect_contradictions()
        d2 = ctrl.detect_contradictions()
        assert d1["recorded"] == [contradiction_id_of(a, b)]
        assert d2["recorded"] == [] and d2["duplicates"] == 1


class TestC8Determinism:
    def test_rebuild_identical_rows(self, db):
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        _pair(db)
        expected = _make(db)._detector_candidate_rows()

        conn2 = connect(":memory:")
        migrate_to_latest(conn2)
        ProjectRepository(conn2, frozen_clock(CLOCK)).create("p1", "Test")
        OperatorCredentialRepository(conn2, frozen_clock(CLOCK)).register(
            OP_ID, OP_TOKEN, "Test Operator")
        try:
            _program(conn2)
            _task(conn2, "t1")
            _chain(conn2, ev_id="art-ev1", ev_hash="evhash1",
                   outcome_id="art-out1", task_id="t1")
            _pair(conn2)
            got = _make(conn2)._detector_candidate_rows()
            assert got == expected
        finally:
            conn2.close()
