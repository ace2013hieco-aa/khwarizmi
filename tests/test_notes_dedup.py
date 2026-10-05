"""FIX-NOTES-DEDUP — per-tick duplicate appends to ``Controller._notes``.

A-F-01 (blind-scan probe: 3 ACTIVE ticks -> 6 entries, 2 distinct) and
IMPROVE-B-F-05 (independent probe, parked-gate path: notes 2->3->4->5 across
three ticks) found tick-frequency ``self._notes.append(...)`` sites that
bypass ``_note_once``. ``_notes`` is never cleared, so each repeated
condition grew the list once per tick. These fixtures pin the invariant on
the shipped tick surfaces: repeated ticks emit distinct notes only — a
repeated condition refreshes its existing entry in place.

Red leg (before the fix): the ACTIVE fixture records 6 notes, 2 distinct;
the parked fixture records 5 notes, 2 distinct. Green leg (after): 2 notes
each, all distinct.
"""
from __future__ import annotations

import pytest

from hermes.core import frozen_clock
from hermes.core.intents import Intent, IntentKind
from hermes.core.node import NodeContract, NodeType
from hermes.core.task_status import TaskStatus
from hermes.persistence.database import connect
from hermes.persistence.failure_classifications import (
    FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
)
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    OperatorCredentialRepository,
    ProjectRepository,
    TaskRepository,
)
from hermes.research.controller import Controller
from hermes.research.extraction import (
    build_extract_task_payload,
    extraction_draft_from_mapping,
)
from hermes.research.gateway import apply_intent

CLOCK = "2026-01-01T00:00:00.000000+00:00"
OP_ID = "op-1"
OP_TOKEN = "op-token-1"


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, frozen_clock(CLOCK)).create("p1", "Test")
    OperatorCredentialRepository(conn, frozen_clock(CLOCK)).register(
        OP_ID, OP_TOKEN, "Test Operator")
    conn.execute(
        """INSERT INTO dataset_manifests
           (manifest_id, project_id, location, format, size_bytes,
            headers_json, schema_observations_json, query_recipes_json,
            content_hash, provenance_json, created_at, immutable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        ("dm-1", "p1", "x.csv", "csv", 1, "[]", "[]", "[]",
         "h1", None, CLOCK),
    )
    yield conn
    conn.close()


def _task(db, task_id, *, deps=(), status=TaskStatus.PENDING):
    repo = TaskRepository(db, clock=lambda: CLOCK)
    return repo.create(NodeContract(
        task_id=task_id, project_id="p1", task_type=NodeType.AGENT_TASK.value,
        idempotency_key=task_id, status=status.value,
        spec={"template": "x"}, dependencies=list(deps),
        provenance=[], cost_class="LOW",
    ))


def _fail(db, task_id):
    """The ratified ladder to a terminal FAILED."""
    tr = TaskRepository(db)
    tr.transition_status(task_id, TaskStatus.READY, caused_by="test")
    tr.transition_status(task_id, TaskStatus.RUNNING, caused_by="test")
    tr.transition_status(task_id, TaskStatus.FAILED, caused_by="test")


def _classify(db, task_id, failure_class="IMPLEMENTATION_FAILURE"):
    """A Q-05 classification artifact bound to the task (the cone label)."""
    db.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type,
            content_hash, size_bytes, storage_path, producer,
            metadata_json, created_at)
           VALUES (?, ?, ?, ?, ?, 0, 'inline://failure_classification',
                   ?, ?, ?)""",
        (f"fc-{task_id}", "p1", task_id,
         FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
         f"ch-{task_id}", f"falsification:{task_id}",
         f'{{"failure_class": "{failure_class}"}}', CLOCK),
    )


def _admit_extract_task(db):
    result = apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR", project_id="p1",
        payload=build_extract_task_payload("dataset_manifest:dm-1", "both")))
    return result.entity_id


def _admit_gate_with_dep(db, dep_id, gid):
    result = apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={
            "task_id": gid, "task_type": "HUMAN_GATE",
            "profile": "DIRECTOR", "idempotency_key": gid + "-key",
            "iteration": 1, "spec": {"gate_requirement": "hypothesis"},
            "inputs": [], "outputs": [], "dependencies": [dep_id],
            "provenance": [], "cost_class": None, "concurrency_group": None,
            "max_retries": 3, "parent_task_id": None,
        }))
    return result.entity_id


def _good_extract_fn():
    def _fn(task, untrusted):
        return extraction_draft_from_mapping({
            "source_ref": "dataset_manifest:dm-1",
            "claims": [{
                "ref": "c1",
                "statement": "Alpha reduces beta under gamma conditions.",
                "source_ref": "dataset_manifest:dm-1",
                "support_state": "INFERRED",
                "span_ref": "sec.3",
                "claim_type": "causal",
                "context_tags": {"regime": "ICSS-v1:low-vol",
                                 "dataset_ref": "dm-1"},
                "assumption_refs": ["a1"],
            }],
            "assumptions": [{
                "ref": "a1",
                "statement": "The sample is representative.",
                "context_tags": {"population": "adults-18-65"},
                "supporting_artifact_refs": ["dataset_manifest:dm-1"],
            }],
            "extracted_by": "model_ref:c-tier-1",
            "schema_version": "2",
        })
    return _fn


def _make(db, **kwargs):
    kwargs.setdefault("extract_fn", _good_extract_fn())
    kwargs.setdefault("clock", frozen_clock(CLOCK))
    return Controller(db, project_id="p1", **kwargs)


# ── A-F-01: the ACTIVE tick surfaces (contradiction summary + cone note) ──

def test_active_ticks_produce_distinct_notes_only(db):
    """Three ACTIVE ticks over one blocked, classified task.

    Red leg: 6 entries, 2 distinct (the A-F-01 probe shape). Green leg:
    2 entries, both distinct — the repeated conditions refresh in place.
    """
    _task(db, "A", status=TaskStatus.PENDING)
    _task(db, "B", deps=["A"])
    _fail(db, "A")
    _classify(db, "A", "REFUTED")
    ctrl = _make(db)
    for _ in range(3):
        ctrl.tick()
    assert len(ctrl.notes) == len(set(ctrl.notes)), (
        f"duplicate notes across ticks: {ctrl.notes}")
    # Dedup must not drop the distinct conditions.
    joined = "\n".join(ctrl.notes)
    assert "contradiction detection:" in joined
    assert "Q-04: dispatch blocked by failure cone of task A" in joined


# ── B-F-05: the parked-gate diagnostic path ──

def test_parked_gate_ticks_produce_distinct_notes_only(db):
    """Three parked-mode ticks while the gate's dep is INVALIDATED.

    Red leg: 5 entries, 2 distinct. Green leg: 2 entries, both distinct.
    """
    dep_id = _admit_extract_task(db)
    gate_id = _admit_gate_with_dep(db, dep_id, "gate-note")
    tr = TaskRepository(db)
    ctrl = _make(db)
    ctrl.tick()          # dep SUCCEEDED
    ctrl.tick()          # gate parks at WAITING_HUMAN
    assert tr.get_status(gate_id) is TaskStatus.WAITING_HUMAN
    tr.transition_status(dep_id, TaskStatus.INVALIDATED, caused_by="audit",
                         reason="evidence reclassified")
    for _ in range(3):
        ctrl.tick()      # parked-mode ticks surface the diagnostic
    assert len(ctrl.notes) == len(set(ctrl.notes)), (
        f"duplicate notes across parked ticks: {ctrl.notes}")
    assert any("INVALIDATED" in n and gate_id in n for n in ctrl.notes)


def test_resolve_surface_does_not_duplicate_the_tick_note(db):
    """The verdict surface reports the same condition as the tick surface.

    One controller that already noted the parked-gate condition on a tick
    must not append a byte-identical second entry at resolve time.
    """
    dep_id = _admit_extract_task(db)
    gate_id = _admit_gate_with_dep(db, dep_id, "gate-resolve")
    tr = TaskRepository(db)
    ctrl = _make(db)
    ctrl.tick()
    ctrl.tick()
    tr.transition_status(dep_id, TaskStatus.INVALIDATED, caused_by="audit",
                         reason="evidence reclassified")
    ctrl.tick()          # the tick surface records the diagnostic
    out = ctrl.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED", operator_id=OP_ID,
        operator_token=OP_TOKEN)
    assert out["rejected"] is False
    assert len(ctrl.notes) == len(set(ctrl.notes)), (
        f"duplicate notes across tick/resolve surfaces: {ctrl.notes}")


# ── C-F-04: the corrupt-read surfaces (13 direct appends → keyed notes) ──

def test_corrupt_read_surfaces_note_once_per_condition(db):
    """One corrupt proposal row + one corrupt retraction row, read twice.

    Red leg (C-F-04 probe): 4 notes — +1 per read call per surface. Green
    leg: 2 notes, both distinct — each corrupt row is one keyed condition
    (``read:corrupt-proposal:<event_id>`` /
    ``read:corrupt-sourceretracted-notjson:<event_id>``) refreshed in
    place, never appended per call. No condition is dropped: both corrupt
    rows stay observable.
    """
    db.execute(
        "INSERT INTO events (event_type, project_id, correlation_id, "
        "caused_by, reason, payload_json, created_at) "
        "VALUES ('ClassificationActionProposed', 'p1', 'prop-1', 't', "
        "'r', 'NOT-JSON', ?)", (CLOCK,))
    db.execute(
        "INSERT INTO events (event_type, project_id, correlation_id, "
        "caused_by, reason, artifact_ids_json, created_at) "
        "VALUES ('SourceRetracted', 'p1', 'ret-1', 't', 'r', "
        "'NOT-JSON', ?)", (CLOCK,))
    db.commit()
    ctrl = _make(db)
    ctrl.pending_classification_proposals()
    ctrl.pending_classification_proposals()
    ctrl.retracted_source_review_candidates()
    ctrl.retracted_source_review_candidates()
    assert len(ctrl.notes) == 2, f"notes grew per read call: {ctrl.notes}"
    assert len(ctrl.notes) == len(set(ctrl.notes))
    joined = "\n".join(ctrl.notes)
    assert "ClassificationActionProposed" in joined
    assert "SourceRetracted" in joined
