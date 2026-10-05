"""Q-05 permitted-action intents through the gateway (IDR-040 §2).

The Director loop consumes reconcile_digest() and emits one
PROPOSE_CLASSIFICATION_ACTION intent per permitted action cited by the
re-review candidate's classifications. Proposal-ONLY: the gateway admits
the proposal as a ratified ClassificationActionProposed event (the audit IS
the record); the ACTION itself still requires its existing authority. These
fixtures pin the gateway admission contract (D3 dereference, ratified
action member, candidate existence, Director-only role, idempotency) and
the controller loop (digest consumption, filtering, never-executes).
"""
from __future__ import annotations

import json as _json

import pytest

from hermes.core import utc_now
from hermes.core.intents import Intent, IntentKind
from hermes.persistence.database import connect
from hermes.persistence.failure_classifications import (
    FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
)
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ProjectRepository
from hermes.research.controller import Controller
from hermes.research.failure_classification import (
    FailureClass,
    permitted_actions_for,
)
from hermes.research.gateway import GatewayRejection, apply_intent

CLOCK = "2026-01-01T00:00:00.000000+00:00"


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Test")
    yield conn
    conn.close()


def _artifact(conn, aid, atype="evidence", cls_ref=None):
    meta = None
    if cls_ref is not None:
        meta = _json.dumps({
            "failure_class": "IMPLEMENTATION_FAILURE",
            "hypothesis_ref": "h1", "classifier_version": "1.0",
            "classification_id": aid,
            "evidence_refs": ["evidence:ev-a"],
            "program_ref": "rp-1", "falsifying_evidence_refs": [],
            "permitted_actions": sorted(
                a.value for a in permitted_actions_for(
                    FailureClass("IMPLEMENTATION_FAILURE")))},
            sort_keys=True)
    conn.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type,
            content_hash, size_bytes, storage_path, producer,
            metadata_json, created_at)
           VALUES (?, 'p1', NULL, ?, ?, 0, 'inline://t', 'test', ?, ?)""",
        (aid, atype, "ch-" + aid, meta, CLOCK),
    )


def _edge(conn, down, up, etype="cites"):
    conn.execute(
        "INSERT INTO provenance_edges (artifact_id, upstream_id,"
        " edge_type, created_at) VALUES (?, ?, ?, ?)",
        (down, up, etype, CLOCK),
    )


def _classification(conn, cls_art="fc-ev-a", evidence_ref="ev-a"):
    """A D3-valid classification row: ref failure_classification:ch-fc-ev-a
    dereferences to the row's content hash + type + project."""
    _artifact(conn, cls_art, FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
              cls_ref=evidence_ref)
    _edge(conn, cls_art, evidence_ref, "cites")


def _proposal_intent(**overrides):
    payload = {
        "classification_ref": "failure_classification:ch-fc-ev-a",
        "action": "REVIEW_DOWNSTREAM_IMPACT",
        "candidate_artifact_ref": "ev-a",
        "rationale": "retracted source downstream",
    }
    payload.update(overrides.pop("payload", {}))
    return Intent(
        kind=IntentKind.PROPOSE_CLASSIFICATION_ACTION,
        proposed_by=overrides.pop("proposed_by", "DIRECTOR"),
        project_id=overrides.pop("project_id", "p1"),
        payload=payload,
        justification="test",
    )


def _make(conn, **kwargs):
    return Controller(conn, project_id="p1", clock=utc_now, **kwargs)


class TestGatewayProposalAdmission:
    def test_valid_proposal_admitted_as_audit_event(self, db):
        conn = db
        _artifact(conn, "ev-a")
        _classification(conn)
        result = apply_intent(conn, _proposal_intent(), clock=lambda: CLOCK)
        assert result.duplicate is False
        assert result.entity_type == "classification_action_proposal"
        assert result.entity_id.startswith("prop_")
        row = conn.execute(
            "SELECT payload_json FROM events "
            "WHERE event_type = 'ClassificationActionProposed'"
        ).fetchone()
        payload = _json.loads(row["payload_json"])
        assert payload["action"] == "REVIEW_DOWNSTREAM_IMPACT"
        assert payload["candidate_artifact_ref"] == "ev-a"
        assert payload["classification_ref"] == "failure_classification:ch-fc-ev-a"
        # proposal-only: no task, no artifact mutation
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0

    def test_forged_classification_ref_rejected(self, db):
        conn = db
        _artifact(conn, "ev-a")
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, _proposal_intent(payload={
                "classification_ref": "failure_classification:deadbeef",
            }), clock=lambda: CLOCK)
        assert exc.value.code == "CLASSIFICATION_REF"
        assert conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE event_type = 'ClassificationActionProposed'"
        ).fetchone()[0] == 0
        # the rejection is audited
        assert conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = 'IntentRejected'"
        ).fetchone()[0] == 1

    def test_unratified_action_rejected(self, db):
        conn = db
        _artifact(conn, "ev-a")
        _classification(conn)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, _proposal_intent(payload={
                "action": "EXECUTE_NOW",
            }), clock=lambda: CLOCK)
        assert exc.value.code == "CLASSIFICATION_REF"

    def test_unknown_payload_key_rejected(self, db):
        conn = db
        _artifact(conn, "ev-a")
        _classification(conn)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, _proposal_intent(payload={
                "extra": "nope",
            }), clock=lambda: CLOCK)
        assert exc.value.code == "MALFORMED_PAYLOAD"

    def test_candidate_not_in_project_rejected(self, db):
        conn = db
        _classification(conn)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, _proposal_intent(payload={
                "candidate_artifact_ref": "ghost",
            }), clock=lambda: CLOCK)
        assert exc.value.code == "CLASSIFICATION_REF"

    def test_non_director_proposer_rejected(self, db):
        conn = db
        _artifact(conn, "ev-a")
        _classification(conn)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, _proposal_intent(proposed_by="RESEARCHER"),
                         clock=lambda: CLOCK)
        assert exc.value.code == "ROLE"

    def test_duplicate_proposal_is_idempotent(self, db):
        conn = db
        _artifact(conn, "ev-a")
        _classification(conn)
        first = apply_intent(conn, _proposal_intent(), clock=lambda: CLOCK)
        second = apply_intent(conn, _proposal_intent(), clock=lambda: CLOCK)
        assert first.entity_id == second.entity_id
        assert second.duplicate is True
        assert conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE event_type = 'ClassificationActionProposed'"
        ).fetchone()[0] == 1


class TestDirectorActionLoop:
    def _seed(self, db):
        conn = db
        # retracted source -> downstream evidence -> classification
        _artifact(conn, "src-1", "source_result")
        _artifact(conn, "ev-a", "evidence")
        _edge(conn, "ev-a", "src-1", "derived_from")
        _classification(conn)
        ctrl = _make(conn)
        ctrl.record_source_retraction(
            "src-1", caused_by="director", reason="retracted")
        return conn, ctrl

    def test_loop_emits_permitted_actions_for_candidates(self, db):
        conn, ctrl = self._seed(db)
        out = ctrl.propose_review_actions()
        # IMPLEMENTATION_FAILURE -> exactly the ratified action set
        expected = sorted(a.value for a in permitted_actions_for(
            FailureClass("IMPLEMENTATION_FAILURE")))
        assert sorted(out["proposed"])  # non-empty, one per action
        rows = conn.execute(
            "SELECT payload_json FROM events "
            "WHERE event_type = 'ClassificationActionProposed'").fetchall()
        admitted = sorted(_json.loads(r["payload_json"])["action"]
                          for r in rows)
        assert admitted == expected

    def test_loop_is_idempotent_across_runs(self, db):
        conn, ctrl = self._seed(db)
        first = ctrl.propose_review_actions()
        second = ctrl.propose_review_actions()
        assert len(second["proposed"]) == 0
        assert sorted(second["duplicates"]) == sorted(first["proposed"])
        assert conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE event_type = 'ClassificationActionProposed'"
        ).fetchone()[0] == len(first["proposed"])

    def test_loop_can_be_filtered_by_candidate(self, db):
        _conn, ctrl = self._seed(db)
        out = ctrl.propose_review_actions(candidate_artifact_ids=["ev-a"])
        assert out["proposed"]
        out2 = ctrl.propose_review_actions(
            candidate_artifact_ids=["other-artifact"])
        assert out2["proposed"] == [] and out2["rejected"] == []

    def test_loop_never_executes(self, db):
        conn, ctrl = self._seed(db)
        before_tasks = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        before_arts = conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
        ctrl.propose_review_actions()
        # only events were appended — no task, no artifact, no status change
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == before_tasks
        assert conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == before_arts

    def test_loop_on_empty_digest_is_empty(self, db):
        conn = db
        out = _make(conn).propose_review_actions()
        assert out["proposed"] == [] and out["duplicates"] == []
        assert out["rejected"] == []

    def test_loop_proposals_carry_the_ratified_actions_only(self, db):
        """The admitted proposals never contain an action outside the
        taxonomy — the gateway rejects before admission (never-executed
        authority stays at the existing paths)."""
        conn, ctrl = self._seed(db)
        ctrl.propose_review_actions()
        rows = conn.execute(
            "SELECT payload_json FROM events "
            "WHERE event_type = 'ClassificationActionProposed'").fetchall()
        ratified = {a.value for a in __import__(
            "hermes.research.failure_classification",
            fromlist=["PermittedAction"]).PermittedAction}
        for r in rows:
            assert _json.loads(r["payload_json"])["action"] in ratified
