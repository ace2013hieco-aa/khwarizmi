"""Q-04 controller consumption — the read-only advisory surfaces.

The controller exposes the derived failure-propagation graph (failure_cone /
blocked_roots / change_blast_radius) exactly like ``classification_proposals``:
read-only, version-bound, hashed, never persisted, never a scheduler input.
These fixtures pin the integration (dependencies loaded project-scoped,
Q-05 classification labels riding the cone) and the no-authority boundary
(the surfaces never write).
"""
from __future__ import annotations

import pytest

from hermes.core import frozen_clock
from hermes.core.node import NodeContract, NodeType
from hermes.core.task_status import TaskStatus
from hermes.persistence.database import connect
from hermes.persistence.failure_classifications import (
    FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
)
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ProjectRepository, TaskRepository
from hermes.research.controller import Controller

CLOCK = "2026-01-01T00:00:00.000000+00:00"


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Test")
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
    """The ratified ladder to a terminal FAILED (PENDING → READY → RUNNING
    → FAILED — the same path the controller's recovery ladder uses)."""
    tr = TaskRepository(db)
    tr.transition_status(task_id, TaskStatus.READY, caused_by="test")
    tr.transition_status(task_id, TaskStatus.RUNNING, caused_by="test")
    tr.transition_status(task_id, TaskStatus.FAILED, caused_by="test")


def _classify(db, task_id, failure_class="IMPLEMENTATION_FAILURE"):
    """A Q-05 classification artifact bound to the task (the label the graph
    rides). Inserted at the row level — the D8 advisory boundary: the graph
    consumes the read-only digest, never the classification as evidence."""
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


def _make(db, **kwargs):
    return Controller(db, project_id="p1", clock=frozen_clock(CLOCK), **kwargs)


class TestFailureConeSurface:
    def test_cone_carries_root_cause_and_classification_label(self, db):
        _task(db, "A", status=TaskStatus.PENDING)
        _task(db, "B", deps=["A"])
        _task(db, "C", deps=["B"])
        _task(db, "E", deps=["A"])
        _fail(db, "A")
        _classify(db, "A", "REFUTED")
        ctrl = _make(db)
        cone = ctrl.failure_cone(["A"])
        assert cone["version"] == "1"
        items = {i["task_id"]: i for i in cone["items"]}
        assert sorted(items) == ["B", "C", "E"]
        assert items["C"]["blocking_ancestor"] == "A"  # root cause
        assert items["C"]["blocking_status"] == TaskStatus.FAILED.value
        assert items["B"]["classification_label"] == "REFUTED"
        assert cone["content_hash"]  # version-bound identity

    def test_succeeded_seed_has_empty_cone(self, db):
        _task(db, "A", status=TaskStatus.SUCCEEDED)
        _task(db, "B", deps=["A"])
        cone = _make(db).failure_cone(["A"])
        assert cone["items"] == []

    def test_blocked_roots_terminal_only(self, db):
        _task(db, "R", status=TaskStatus.RETRYING)
        _task(db, "F", status=TaskStatus.FAILED)
        _task(db, "t1", deps=["R"])
        _task(db, "t2", deps=["F"])
        ctrl = _make(db)
        roots = ctrl.blocked_roots()
        # t1 is transient (RETRYING ancestor — the recovery ladder owns it);
        # t2 is permanent (FAILED-terminal ancestor).
        assert roots["items"] == ["t2"]
        assert roots["version"] == "1"

    def test_blast_radius_regardless_of_status(self, db):
        _task(db, "A", status=TaskStatus.SUCCEEDED)
        _task(db, "B", deps=["A"])
        _task(db, "C", deps=["B"])
        radius = _make(db).change_blast_radius(["A"])
        assert radius["items"] == ["B", "C"]

    def test_surfaces_never_write(self, db):
        _task(db, "A", status=TaskStatus.FAILED)
        _task(db, "B", deps=["A"])
        ctrl = _make(db)
        before = db.execute(
            "SELECT COUNT(*) FROM task_dependencies").fetchone()[0]
        before_tasks = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        before_artifacts = db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
        ctrl.failure_cone(["A"])
        ctrl.blocked_roots()
        ctrl.change_blast_radius(["A"])
        assert db.execute(
            "SELECT COUNT(*) FROM task_dependencies").fetchone()[0] == before
        assert db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == before_tasks
        assert db.execute(
            "SELECT COUNT(*) FROM artifacts").fetchone()[0] == before_artifacts
        # And the surfaces agree with themselves (determinism).
        assert ctrl.failure_cone(["A"]) == ctrl.failure_cone(["A"])


class TestConeBlockedDispatchNote:
    """Q-04 §3.4 — when a dispatch pass finds nothing eligible and the idle
    dispatch is blocked by a failure cone whose blocking ancestor carries a
    Q-05 classification, the controller records a diagnostic note on the
    notes channel. Diagnostic only: the eligibility logic is untouched and
    nothing is written."""

    def test_note_when_dispatch_idle_blocked_by_classified_cone(self, db):
        _task(db, "A", status=TaskStatus.PENDING)
        _task(db, "B", deps=["A"])
        _fail(db, "A")
        _classify(db, "A", "REFUTED")
        ctrl = _make(db)
        ctrl.tick()
        assert any(
            "Q-04: dispatch blocked by failure cone of task A" in n
            and "FAILED" in n and "REFUTED" in n and "B" in n
            for n in ctrl._notes)

    def test_note_still_fires_after_a_prior_sequencer_pass(self, db):
        """Merge-audit M1: an earlier sequencer pass leaves a recorded-only
        seq artifact PENDING. Real work then runs out, so the dispatch pass
        is genuinely idle — the §3.4 diagnostic must fire exactly as it does
        with no sequencer in the project. The inert artifact must not make
        ``if not tasks:`` permanently false and silence the cone note."""
        _task(db, "A", status=TaskStatus.PENDING)
        _task(db, "B", deps=["A"])
        ctrl = _make(db)
        ctrl.tick()  # sequencer pass admits seq-p1-…; A is still unhandled
        assert db.execute(
            "SELECT COUNT(*) FROM tasks WHERE task_id LIKE 'seq-%'"
        ).fetchone()[0] == 1, "precondition: the seq artifact exists"
        assert db.execute(
            "SELECT status FROM tasks WHERE task_id = 'A'"
        ).fetchone()[0] == TaskStatus.PENDING.value
        assert not any("Q-04: dispatch blocked" in n for n in ctrl._notes)

        _fail(db, "A")
        _classify(db, "A", "REFUTED")
        ctrl.tick()  # idle: B is cone-blocked, only the seq row was eligible
        assert any(
            "Q-04: dispatch blocked by failure cone of task A" in n
            and "FAILED" in n and "REFUTED" in n and "B" in n
            for n in ctrl._notes)

    def test_no_note_when_blocking_ancestor_unclassified(self, db):
        _task(db, "A", status=TaskStatus.PENDING)
        _task(db, "B", deps=["A"])
        _fail(db, "A")  # blocks B, but carries no Q-05 classification
        ctrl = _make(db)
        ctrl.tick()
        assert not any("Q-04: dispatch blocked" in n for n in ctrl._notes)

    def test_no_note_when_eligible_work_exists(self, db):
        _task(db, "A", status=TaskStatus.PENDING)  # no deps — eligible
        ctrl = _make(db)
        ctrl.tick()
        assert not any("Q-04: dispatch blocked" in n for n in ctrl._notes)

    def test_note_is_diagnostic_only_no_state_change(self, db):
        _task(db, "A", status=TaskStatus.PENDING)
        _task(db, "B", deps=["A"])
        _fail(db, "A")
        _classify(db, "A")
        ctrl = _make(db)
        before = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        ctrl.tick()
        assert db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == before
        rows = {r["task_id"]: r["status"] for r in db.execute(
            "SELECT task_id, status FROM tasks")}
        assert rows["A"] == TaskStatus.FAILED.value
        assert rows["B"] == TaskStatus.PENDING.value  # untouched, still blocked

    def test_transient_retrying_node_blocked_behind_classified_ancestor(self, db):
        # RETRYING is itself eligible (the recovery ladder's state), so the
        # idle-dispatch note can only fire when the classified FAILED root
        # blocks everything downstream of it — including the RETRYING node.
        _task(db, "F", status=TaskStatus.PENDING)
        _task(db, "R", deps=["F"], status=TaskStatus.RETRYING)
        _task(db, "T", deps=["R"])
        _fail(db, "F")
        _classify(db, "F", "IMPLEMENTATION_FAILURE")
        ctrl = _make(db)
        ctrl.tick()
        assert any(
            "Q-04: dispatch blocked by failure cone of task F" in n
            and "FAILED" in n and "IMPLEMENTATION_FAILURE" in n
            and "R" in n and "T" in n for n in ctrl._notes)

    def test_note_never_claims_succeeded_member_blocked(self, db):
        """F10 (audit) — under tampered state (a SUCCEEDED task whose
        ancestor later failed — unreachable via the ratified ladder, F-10
        forbids the transition), the note lists only tasks actually not
        dispatchable: a SUCCEEDED cone member already ran and is not
        blocked, so it is never claimed as one."""
        for tid, st, deps in (("A", "FAILED", None),
                              ("B", "SUCCEEDED", "A"),
                              ("C", "PENDING", "A")):
            db.execute(
                "INSERT INTO tasks (task_id, project_id, task_type,"
                " idempotency_key, status, spec_json, cost_class,"
                " created_at, attempt, max_retries, iteration)"
                " VALUES (?, 'p1', 'AGENT_TASK', ?, ?, '{}', 'LOW', ?,"
                " 0, 3, 1)", (tid, tid, st, CLOCK))
            if deps:
                db.execute("INSERT INTO task_dependencies"
                           " (task_id, depends_on_task_id, created_at)"
                           " VALUES (?, ?, ?)", (tid, deps, CLOCK))
        _classify(db, "A", "REFUTED")
        ctrl = _make(db)
        ctrl.tick()
        notes = [n for n in ctrl._notes
                 if "Q-04: dispatch blocked" in n]
        assert len(notes) == 1
        assert "blocked dependents: C" in notes[0]
        assert "B" not in notes[0]
