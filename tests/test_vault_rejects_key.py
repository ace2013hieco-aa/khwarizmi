"""C-FIX-3 regression: vault _rejects honors production "decision" key.

C-F-02: _rejects read payload["verdict"] while production
HumanDecisionReceived writers emit {"decision": ...} (controller.py:2186,
2335,2550,2692), so a refusing human decision slipped the non-acceptance
filter. HumanGateResolved still emits {"verdict": ...}
(controller.py:1923), so both keys are honored with the same refusing
vocabulary — no authority change (AUTHORITATIVE_EVENT_TYPES untouched).
"""
from __future__ import annotations

import json
from pathlib import Path

from hermes.vault.projection import (
    _rejects,
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


def _emit(conn, event_type, task_id=None, payload=None):
    if task_id is not None:
        conn.execute(
            "INSERT OR IGNORE INTO tasks (task_id, project_id, task_type, "
            "idempotency_key, created_at) VALUES (?, ?, ?, ?, ?)",
            (task_id, "p1", "AGENT_TASK", str(task_id) + "-key", CLOCK),
        )
    row = conn.execute(
        "INSERT INTO events (event_type, project_id, task_id, caused_by, "
        "reason, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            event_type,
            "p1",
            task_id,
            "probe",
            "probe",
            json.dumps(payload, sort_keys=True)
            if payload is not None
            else None,
            CLOCK,
        ),
    )
    conn.commit()
    return row.lastrowid


def _note_text(root, event_id, event_type):
    return (Path(root) / note_filename(event_id, event_type)).read_text(
        encoding="utf-8"
    )


def _row(event_id, event_type, payload):
    return {
        "event_id": event_id,
        "event_type": event_type,
        "payload_json": json.dumps(payload),
    }


def test_human_decision_decision_rejected_excluded(tmp_path):
    """Refusing HumanDecisionReceived (production decision key) is process."""
    conn = _db()
    try:
        refused = _emit(
            conn,
            "HumanDecisionReceived",
            payload={
                "decision": "REJECTED",
                "retraction_id": "ret-1",
                "operator_id": "op-1",
            },
        )
        assert _rejects(_row(refused, "HumanDecisionReceived", {
            "decision": "REJECTED",
        })) is True
        root = str(tmp_path / "v")
        project(conn, "p1", root, cursor=0)
        text = _note_text(root, refused, "HumanDecisionReceived")
        assert "authoritative: false" in text
    finally:
        conn.close()


def test_human_decision_accepting_stays_authoritative(tmp_path):
    """Production accepting decision is not over-filtered."""
    conn = _db()
    try:
        decided = _emit(
            conn,
            "HumanDecisionReceived",
            payload={
                "decision": "RETRACT_SOURCE",
                "retraction_id": "ret-1",
                "source_ref": "src-1",
                "reason_digest": "d" * 64,
                "operator_id": "op-1",
            },
        )
        root = str(tmp_path / "v")
        project(conn, "p1", root, cursor=0)
        text = _note_text(root, decided, "HumanDecisionReceived")
        assert "authoritative: true" in text
    finally:
        conn.close()


def test_human_gate_verdict_rejected_still_excluded(tmp_path):
    """Verdict path preserved: REJECTED gate stays process."""
    conn = _db()
    try:
        gate = _emit(
            conn,
            "HumanGateResolved",
            task_id="gate-1",
            payload={
                "verdict": "REJECTED",
                "rationale": "no",
                "operator_id": "op-1",
            },
        )
        root = str(tmp_path / "v")
        project(conn, "p1", root, cursor=0)
        text = _note_text(root, gate, "HumanGateResolved")
        assert "authoritative: false" in text
    finally:
        conn.close()
