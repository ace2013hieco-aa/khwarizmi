"""C-F-01 regression: vault validity against writer-emitted payload shapes.

Each authoritative class is proven against the payload dict its production
writer emits (shapes copied from the write sites, cited below). Before the
substrate alignment these rows yielded ``subjects == frozenset()`` and the
admitted/resolved notes stayed ``authoritative: true`` despite their paired
invalidating rows; after, the curated/contradiction pairs retire on their
shared production keys, the ladder shape is recognized (non-empty
subjects, correctly live — no production invalidator carries the ladder
key), and the gate task pair + human decision behave as before.

Authority sets are unchanged (no class added/removed); the journal is only
read (SELECTs in ``project``).
"""
from __future__ import annotations

import json
from pathlib import Path

from hermes.vault.projection import (
    _row_subject_keys,
    note_filename,
    project,
)

CLOCK = "2026-01-01T00:00:00.000000+00:00"


def _db():
    from hermes.persistence.database import connect
    from hermes.persistence.migrations import migrate_to_latest
    from hermes.persistence.repositories import ProjectRepository

    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: CLOCK).create("p1", "Test")
    return conn


def _emit(conn, event_type, task_id=None, payload=None, artifacts=None,
          correlation="c", reason="probe"):
    if task_id is not None:
        conn.execute(
            "INSERT OR IGNORE INTO tasks (task_id, project_id, task_type, "
            "idempotency_key, created_at) VALUES (?, ?, ?, ?, ?)",
            (task_id, "p1", "AGENT_TASK", str(task_id) + "-key", CLOCK),
        )
    row = conn.execute(
        "INSERT INTO events (event_type, project_id, task_id, from_state, "
        "to_state, correlation_id, caused_by, reason, artifact_ids_json, "
        "payload_json, created_at) VALUES (?, ?, ?, NULL, NULL, ?, ?, ?, "
        "?, ?, ?)",
        (event_type, "p1", task_id, correlation, "probe", reason,
         json.dumps(artifacts) if artifacts is not None else None,
         json.dumps(payload, sort_keys=True) if payload is not None else None,
         CLOCK),
    )
    conn.commit()
    return row.lastrowid


def _subjects(conn, event_id):
    row = conn.execute(
        "SELECT event_type, task_id, artifact_ids_json, payload_json "
        "FROM events WHERE event_id = ?", (event_id,)).fetchone()
    return _row_subject_keys(dict(row))


def _note_text(root, event_id, event_type):
    return (Path(root) / note_filename(event_id, event_type)).read_text(
        encoding="utf-8")


def test_production_curated_admission_retired_by_invalidation(tmp_path):
    """gateway.py admission_payload vs S5 CuratedKnowledgeInvalidated."""
    conn = _db()
    try:
        curated_id = "ck_prod_001"
        # Writer: gateway.py _validate_curate_knowledge admission_payload.
        admit = _emit(conn, "CuratedKnowledgeAdmitted", payload={
            "curated_id": curated_id, "kind": "REFUTED_PATTERN",
            "operation": "ADMIT", "signature_json": "{}",
            "source_binding_ref": "fb-1",
            "source_decision_event_ref": "d-1",
            "program_ref": "prog-1", "hypothesis_ref": "h-1",
            "admission_decision_ref": "curate-decision-x",
            "evidence_basis": ["a-1"], "operator_id": "op-1",
            "supersedes_ref": "",
        }, correlation="cmd-hash-1", reason="admitted")
        # Writer: gateway.py S5 curated follow-on payload.
        _emit(conn, "CuratedKnowledgeInvalidated", payload={
            "curated_id": curated_id, "retraction_id": "ret-1",
            "source_artifact_id": "a-1", "matched_evidence": ["a-1"],
        }, correlation="ret-1", reason="S5 cascade")
        assert _subjects(conn, admit) == frozenset(
            {f"curated:{curated_id}"})
        root = str(tmp_path / "v")
        project(conn, "p1", root, cursor=0)
        text = _note_text(root, admit, "CuratedKnowledgeAdmitted")
        assert "authoritative: false" in text
        assert "superseded by" in text
    finally:
        conn.close()


def test_production_contradiction_resolved_retired_by_supersession(tmp_path):
    """gateway.py ContradictionResolved vs S5 ContradictionSuperseded."""
    conn = _db()
    try:
        cx_id = "cx_prod_001"
        # Writer: gateway.py _validate_contradiction_resolution payload.
        resolved = _emit(conn, "ContradictionResolved", payload={
            "contradiction_id": cx_id, "resolution_id": "cres_prod",
            "human_decision_ref": "contradiction-decision-cres_prod",
            "operator_id": "op-1",
        }, correlation="cres_prod", reason="resolved")
        # Writer: gateway.py S5 contradiction follow-on payload.
        _emit(conn, "ContradictionSuperseded", payload={
            "contradiction_id": cx_id, "retraction_id": "ret-1",
            "source_artifact_id": "a-1",
        }, correlation=f"{cx_id}:superseded:ret-1",
            reason="S5 retired party")
        assert _subjects(conn, resolved) == frozenset(
            {f"contradiction:{cx_id}"})
        root = str(tmp_path / "v")
        project(conn, "p1", root, cursor=0)
        text = _note_text(root, resolved, "ContradictionResolved")
        assert "authoritative: false" in text
        assert "superseded by" in text
    finally:
        conn.close()


def test_production_evidence_shape_recognized_and_live(tmp_path):
    """controller.py ladder write shape: recognized, correctly live."""
    conn = _db()
    try:
        # Writer: controller.py _record_ladder_transition payload.
        evid = _emit(conn, "EvidenceTransitionApplied", payload={
            "program_id": "prog-1", "hypothesis_ref": "h-1",
            "from_rung": "", "to_rung": "SUPPORTED", "driver": "ratification",
            "ratified_by": "op-1",
        }, correlation="tr-1", reason="ladder transition")
        assert _subjects(conn, evid) == frozenset({"ladder:prog-1:h-1"})
        root = str(tmp_path / "v")
        project(conn, "p1", root, cursor=0)
        text = _note_text(root, evid, "EvidenceTransitionApplied")
        assert "authoritative: true" in text
        assert "currently_valid: true" in text
    finally:
        conn.close()


def test_production_gate_task_pair_still_retires(tmp_path):
    """controller.py HumanGateResolved vs S5 TaskInvalidated (task key)."""
    conn = _db()
    try:
        # Writer: controller.py resolve_human_gate HumanGateResolved.
        gate = _emit(conn, "HumanGateResolved", task_id="gate-1", payload={
            "verdict": "APPROVED", "rationale": "ok", "operator_id": "op-1",
        }, correlation="g-1", reason="gate resolved")
        # Writer: gateway.py S5 TaskInvalidated (task column + payload).
        _emit(conn, "TaskInvalidated", task_id="gate-1", payload={
            "source_artifact_id": "a-9", "retraction_id": "ret-9",
        }, correlation="ret-9", reason="cascade")
        assert _subjects(conn, gate) == frozenset({"task:gate-1"})
        root = str(tmp_path / "v")
        project(conn, "p1", root, cursor=0)
        text = _note_text(root, gate, "HumanGateResolved")
        assert "authoritative: false" in text
        assert "superseded by" in text
    finally:
        conn.close()


def test_production_human_decision_stays_live(tmp_path):
    """controller.py RETRACT_SOURCE HumanDecisionReceived: root stays live."""
    conn = _db()
    try:
        # Writer: controller.py record_source_retraction_decision payload.
        decided = _emit(conn, "HumanDecisionReceived", payload={
            "decision": "RETRACT_SOURCE", "retraction_id": "ret-1",
            "source_ref": "src-1", "reason_digest": "d" * 64,
            "operator_id": "op-1",
        }, correlation="retract-decision-ret-1", reason="operator verdict")
        root = str(tmp_path / "v")
        project(conn, "p1", root, cursor=0)
        text = _note_text(root, decided, "HumanDecisionReceived")
        assert "authoritative: true" in text
        assert "currently_valid: true" in text
    finally:
        conn.close()
