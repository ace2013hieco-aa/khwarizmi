"""Q-04 §5 extension — the concrete re-review candidate set: the artifact
blast radius joined with OUTSTANDING Q-05 classifications, plus the
SOURCE_RETRACTED event as its seed trigger.

The pure intersection (``re_review_candidates`` in core/graph.py) names
exactly the downstream artifacts that carry a D8-valid, unflagged
classification; the controller surfaces it read-only, version-bound, and
hashed, and ``record_source_retraction`` records the ratified
SourceRetracted event (append-only audit — nothing is retracted or
modified by the record itself).
"""
from __future__ import annotations

import json as _json
import sqlite3

import pytest

from hermes.core import frozen_clock, utc_now
from hermes.core.graph import (
    GRAPH_QUERY_VERSION,
    ArtifactBlastEntry,
    ReviewCandidate,
    re_review_candidates,
)
from hermes.persistence.database import connect
from hermes.persistence.failure_classifications import (
    FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
)
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.program_obligations import (
    ProgramRequirementSatisfactionRepository,
    ValidationVerdictRepository,
)
from hermes.persistence.repositories import ProjectRepository
from hermes.research.controller import Controller, SourceRetractionError
from hermes.research.failure_classification import (
    FailureClass,
    permitted_actions_for,
)

CLOCK = "2026-01-01T00:00:00.000000+00:00"


def _blast(*entries):
    """Build ArtifactBlastEntry tuples from (artifact_id, via, edge) triples."""
    return tuple(ArtifactBlastEntry(
        artifact_id=a, reached_via=v, edge_type=e) for a, v, e in entries)


def _digest_item(artifact_id, cls="IMPLEMENTATION_FAILURE", ref="failure_classification:abc"):
    return {
        "classification_id": "fc-" + artifact_id,
        "failure_class_ref": ref,
        "failure_class": cls,
        "classifier_version": "1.0",
        "hypothesis_ref": "h1",
        "permitted_actions": [],
        "requires_human_confirmation": False,
        "evidence_refs": [],
        "integrity_flags": [],
    }


class TestPureReReviewCandidates:
    def test_intersection_only(self):
        blast = _blast(("ev-a", "src-1", "derived_from"),
                       ("ev-b", "src-1", "derived_from"))
        by_artifact = {"ev-a": [_digest_item("ev-a")]}
        out = re_review_candidates(blast, by_artifact)
        # ev-b has no classification — not a candidate.
        assert out == (ReviewCandidate(
            artifact_id="ev-a", reached_via="src-1",
            edge_type="derived_from",
            classification_refs=("failure_classification:abc",),
            failure_classes=("IMPLEMENTATION_FAILURE",),
            requires_human_confirmation=False),)

    def test_multiple_classifications_carried(self):
        blast = _blast(("ev-a", "src-1", "cites"))
        by_artifact = {"ev-a": [
            _digest_item("ev-a", cls="IMPLEMENTATION_FAILURE",
                         ref="failure_classification:r1"),
            _digest_item("ev-a", cls="UNKNOWN",
                         ref="failure_classification:r2",
                         )]}
        out = re_review_candidates(blast, by_artifact)[0]
        assert out.classification_refs == (
            "failure_classification:r1", "failure_classification:r2")
        assert out.failure_classes == ("IMPLEMENTATION_FAILURE", "UNKNOWN")

    def test_requires_human_confirmation_aggregated(self):
        blast = _blast(("ev-a", "src-1", "cites"))
        item = _digest_item("ev-a")
        item["requires_human_confirmation"] = True
        out = re_review_candidates(blast, {"ev-a": [item]})[0]
        assert out.requires_human_confirmation is True

    def test_no_classifications_is_empty(self):
        assert re_review_candidates(_blast(("ev-a", "s", "cites")), {}) == ()

    def test_deterministic(self):
        blast = _blast(("b", "s", "cites"), ("a", "s", "cites"))
        by = {"a": [_digest_item("a")], "b": [_digest_item("b")]}
        first = re_review_candidates(blast, by)
        assert re_review_candidates(blast, by) == first
        assert [c.artifact_id for c in first] == ["a", "b"]

    def test_flagged_classifications_are_not_outstanding(self):
        """The surface's 'outstanding' filter happens upstream (the digest's
        unflagged items) — but the pure function must also never invent a
        ref for a classification that lacks one (fail-closed)."""
        blast = _blast(("ev-a", "s", "cites"))
        item = _digest_item("ev-a")
        item["failure_class_ref"] = None
        assert re_review_candidates(blast, {"ev-a": [item]}) == ()


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Test")
    ProjectRepository(conn).create("p2", "Other")
    yield conn
    conn.close()


def _artifact(conn, aid, atype="source_result"):
    conn.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type,
            content_hash, size_bytes, storage_path, producer,
            metadata_json, created_at)
           VALUES (?, 'p1', NULL, ?, ?, 0, 'inline://test', 'test', NULL, ?)""",
        (aid, atype, "ch-" + aid, CLOCK),
    )


def _edge(conn, down, up, etype="cites"):
    conn.execute(
        "INSERT INTO provenance_edges "
        "(artifact_id, upstream_id, edge_type, created_at) "
        "VALUES (?, ?, ?, ?)",
        (down, up, etype, CLOCK),
    )


def _classify(conn, cls_art, evidence_ref, cls="IMPLEMENTATION_FAILURE"):
    """A D8-valid classification row mirroring the ratified write path's
    stored metadata (evidence_refs + permitted_actions present), citing the
    evidence artifact it classifies."""
    meta = {
        "failure_class": cls,
        "hypothesis_ref": "h1",
        "classifier_version": "1.0",
        "classification_id": cls_art,
        "evidence_refs": ["evidence:" + evidence_ref],
        "program_ref": "rp-1",
        "falsifying_evidence_refs": [],
        "permitted_actions": sorted(
            a.value for a in permitted_actions_for(FailureClass(cls))),
    }
    conn.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type,
            content_hash, size_bytes, storage_path, producer,
            metadata_json, created_at)
           VALUES (?, 'p1', NULL, ?, ?, 0, 'inline://fc', 'test', ?, ?)""",
        (cls_art, FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
         "ch-" + cls_art, _json.dumps(meta, sort_keys=True), CLOCK),
    )
    _edge(conn, cls_art, evidence_ref, "cites")


def _make(conn, **kwargs):
    return Controller(conn, project_id="p1", clock=utc_now, **kwargs)


class TestReReviewCandidateSurface:
    def test_candidate_is_blast_radius_intersection(self, db):
        conn = db
        _artifact(conn, "src-1")
        _artifact(conn, "ev-a", "evidence")
        _artifact(conn, "ev-b", "evidence")
        _edge(conn, "ev-a", "src-1", "derived_from")
        _edge(conn, "ev-b", "src-1", "derived_from")
        _classify(conn, "fc-ev-a", "ev-a")  # only ev-a is classified
        out = _make(conn).re_review_candidates(["src-1"])
        assert out["version"] == GRAPH_QUERY_VERSION
        assert [i["artifact_id"] for i in out["items"]] == ["ev-a"]
        item = out["items"][0]
        assert item["reached_via"] == "src-1"
        assert item["edge_type"] == "derived_from"
        assert item["failure_classes"] == ["IMPLEMENTATION_FAILURE"]
        assert item["classification_refs"] == ["failure_classification:ch-fc-ev-a"]
        assert out["content_hash"]

    def test_flagged_classification_is_not_outstanding(self, db):
        conn = db
        _artifact(conn, "src-1")
        _artifact(conn, "ev-a", "evidence")
        _edge(conn, "ev-a", "src-1", "derived_from")
        _classify(conn, "fc-ev-a", "ev-a")
        # tamper: metadata claims a forged classification_id
        conn.execute(
            "UPDATE artifacts SET metadata_json = ? WHERE artifact_id = ?",
            (_json.dumps({"failure_class": "IMPLEMENTATION_FAILURE",
                          "hypothesis_ref": "h1",
                          "classifier_version": "1.0",
                          "classification_id": "FORGED",
                          "evidence_refs": ["evidence:ev-a"],
                          "permitted_actions": []}, sort_keys=True),
             "fc-ev-a"),
        )
        out = _make(conn).re_review_candidates(["src-1"])
        # the forged row is dropped by the digest (FORGED_IDENTITY) — the
        # candidate set is empty, never a false candidate.
        assert out["items"] == []

    def test_never_writes(self, db):
        conn = db
        _artifact(conn, "src-1")
        _artifact(conn, "ev-a", "evidence")
        _edge(conn, "ev-a", "src-1", "derived_from")
        _classify(conn, "fc-ev-a", "ev-a")
        ctrl = _make(conn)
        before_a = conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
        before_e = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        ctrl.re_review_candidates(["src-1"])
        assert conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == before_a
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == before_e
        assert ctrl.re_review_candidates(["src-1"]) ==             ctrl.re_review_candidates(["src-1"])


class TestRecordSourceRetraction:
    def test_records_ratified_event_bound_to_artifact(self, db):
        conn = db
        _artifact(conn, "src-1")
        ctrl = _make(conn)
        ctrl.record_source_retraction(
            "src-1", caused_by="director", reason="retracted by publisher")
        row = conn.execute(
            "SELECT * FROM events WHERE event_type = 'SourceRetracted'"
        ).fetchone()
        assert row is not None
        assert row["artifact_ids_json"] == '["src-1"]'
        assert "src-1" in row["payload_json"]
        assert row["reason"] == "retracted by publisher"

    def test_refuses_non_source_artifact(self, db):
        conn = db
        _artifact(conn, "ev-a", "evidence")
        with pytest.raises(SourceRetractionError):
            _make(conn).record_source_retraction(
                "ev-a", caused_by="x", reason="y")
        assert conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE event_type = 'SourceRetracted'"
        ).fetchone()[0] == 0

    def test_refuses_missing_artifact(self, db):
        conn = db
        with pytest.raises(SourceRetractionError):
            _make(conn).record_source_retraction(
                "nope", caused_by="x", reason="y")
        assert conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE event_type = 'SourceRetracted'"
        ).fetchone()[0] == 0

    def test_digest_fold_fail_closed_deterministic(self, db):
        """Audit-register follow-up: the reconcile digest fold under the
        failure-injection lens. A corrupt classification row, tampered
        proposal stored states, and duplicate events must leave the digest
        deterministic and fail-closed: corruption is observable (FORGED_IDENTITY
        error + DEGRADED status — never a silent 'no classification'), the
        gate is recomputed from the classification (never trusted from stored
        state, both tamper directions), the schema-level one-verdict index
        refuses a duplicate decision, and the pending replay cannot be
        resurrected by a duplicate proposal event."""
        conn = db
        _artifact(conn, "src-1")
        _artifact(conn, "ev-a", "evidence")
        _edge(conn, "ev-a", "src-1", "derived_from")
        _classify(conn, "fc-ev-a", "ev-a")
        ctrl = _make(conn)

        def proposal_event(action, state, correlation):
            conn.execute(
                "INSERT INTO events (event_type, project_id, task_id, "
                "from_state, to_state, correlation_id, caused_by, reason, "
                "artifact_ids_json, payload_json, created_at) "
                "VALUES ('ClassificationActionProposed', 'p1', NULL, NULL, "
                "NULL, ?, 'gateway', 'admitted', NULL, ?, ?)",
                (correlation, _json.dumps({
                    "classification_ref":
                        "failure_classification:ch-fc-ev-a",
                    "action": action, "state": state}), CLOCK))

        proposal_event("ROUTE_TO_SCOPE_REVIEW", "PENDING_HUMAN_APPROVAL",
                       "prop-1")
        # tamper: stored PENDING on a NON-authority action (gate False)
        proposal_event("REVIEW_DOWNSTREAM_IMPACT", "PENDING_HUMAN_APPROVAL",
                       "prop-2")
        # corrupt: forge the classification identity in stored metadata
        conn.execute("UPDATE artifacts SET metadata_json = ? "
                     "WHERE artifact_id = 'fc-ev-a'",
                     (_json.dumps({
                         "failure_class": "IMPLEMENTATION_FAILURE",
                         "hypothesis_ref": "h1",
                         "classifier_version": "1.0",
                         "classification_id": "FORGED",
                         "evidence_refs": ["evidence:ev-a"],
                         "program_ref": "rp-1",
                         "falsifying_evidence_refs": [],
                         "permitted_actions": []}),))
        d1 = ctrl.reconcile_digest()
        d2 = ctrl.reconcile_digest()
        # corruption observable: FORGED_IDENTITY error, DEGRADED, never a
        # silent "no classification", and the digest is deterministic
        props = d1["classification_proposals"]
        assert [e["code"] for e in props["errors"]] == ["FORGED_IDENTITY"]
        assert props["integrity_status"] == "DEGRADED"
        assert props["items"] == []
        assert d1["content_hash"] == d2["content_hash"]
        # gate recomputation, both tamper directions
        assert [p["proposal_id"] for p in d1["pending_proposals"]] == ["prop-1"]
        assert any("tamper signal" in n for n in ctrl._notes)
        # duplicate decision refused by the F9 schema-level one-verdict index
        def decision_event():
            conn.execute(
                "INSERT INTO events (event_type, project_id, task_id, "
                "from_state, to_state, correlation_id, caused_by, reason, "
                "artifact_ids_json, payload_json, created_at) "
                "VALUES ('ClassificationActionDecision', 'p1', NULL, NULL, "
                "NULL, 'prop-1', 'operator', 'approved', NULL, '{}', ?)",
                (CLOCK,))
        decision_event()
        with pytest.raises(sqlite3.IntegrityError):
            decision_event()
        # after the decision, a duplicate proposal cannot resurrect the
        # pending replay, and the digest stays deterministic
        proposal_event("ROUTE_TO_SCOPE_REVIEW", "PENDING_HUMAN_APPROVAL",
                       "prop-1")
        d3 = ctrl.reconcile_digest()
        d4 = ctrl.reconcile_digest()
        assert [p["proposal_id"] for p in d3["pending_proposals"]] == []
        assert d3["content_hash"] == d4["content_hash"]

    def test_cross_project_retraction_never_leaks_between_projects(self, db):
        """Closure-directive follow-up (the cross-project edge): a
        SourceRetracted event forged for project p2 must never seed
        candidates in p1, and a p2 source artifact must be refused by p1's
        record_source_retraction. The write is project-scoped, the advisory
        read is project-scoped, and artifact_id is GLOBALLY unique — a
        same-id cross-project collision is impossible at the schema level."""
        conn = db
        _artifact(conn, "src-1")          # p1
        _artifact(conn, "ev-a", "evidence")
        _edge(conn, "ev-a", "src-1", "derived_from")
        _classify(conn, "fc-ev-a", "ev-a")
        # p2's own source artifact
        conn.execute(
            "INSERT INTO artifacts (artifact_id, project_id, task_id, "
            "artifact_type, content_hash, size_bytes, storage_path, "
            "producer, metadata_json, created_at) "
            "VALUES ('p2-src', 'p2', NULL, 'source_result', 'ch-p2-src', "
            "0, 'inline://test', 'test', NULL, ?)", (CLOCK,))
        ctrl1 = _make(conn)
        ctrl2 = Controller(conn, project_id="p2", clock=utc_now)
        # write-side project scoping, both directions
        with pytest.raises(SourceRetractionError):
            ctrl1.record_source_retraction(
                "p2-src", caused_by="d", reason="r")
        with pytest.raises(SourceRetractionError):
            ctrl2.record_source_retraction(
                "src-1", caused_by="d", reason="r")
        # each project records its OWN source
        ctrl1.record_source_retraction("src-1", caused_by="d1", reason="r1")
        ctrl2.record_source_retraction("p2-src", caused_by="d2", reason="r2")
        # forge a p2 event naming p1's artifact id
        conn.execute(
            "INSERT INTO events (event_type, project_id, task_id, "
            "from_state, to_state, correlation_id, caused_by, reason, "
            "artifact_ids_json, payload_json, created_at) "
            "VALUES ('SourceRetracted', 'p2', NULL, NULL, NULL, '', "
            "'forged', 'forged', '[\"src-1\"]', '{}', ?)", (CLOCK,))
        # p1's advisory is untouched by the foreign event
        c1 = ctrl1.retracted_source_review_candidates()
        assert [i["artifact_id"] for i in c1["items"]] == ["ev-a"]
        assert not any("not resolvable" in n for n in ctrl1._notes)
        # p2 fails closed on the unresolvable seed, with an observable note
        c2 = ctrl2.retracted_source_review_candidates()
        assert c2["items"] == []
        assert any("not resolvable" in n for n in ctrl2._notes)

    def test_two_director_records_same_source_two_audit_events_one_seed(
            self, db):
        """F6-lens follow-up (Director-side path): two concurrent retraction
        records for the SAME source are two observations — the append-only
        journal carries both (distinct caused_by), and the advisory seeds
        exactly once, so the second record can never duplicate the candidate
        set. The records are append-only audit: no artifact, task, or ladder
        mutation anywhere on the path."""
        conn = db
        _artifact(conn, "src-1")
        _artifact(conn, "ev-a", "evidence")
        _edge(conn, "ev-a", "src-1", "derived_from")
        _classify(conn, "fc-ev-a", "ev-a")
        ctrl = _make(conn)
        ctrl.record_source_retraction(
            "src-1", caused_by="director-1", reason="retracted by publisher")
        ctrl.record_source_retraction(
            "src-1", caused_by="director-2", reason="confirmed retracted")
        rows = conn.execute(
            "SELECT caused_by, artifact_ids_json FROM events "
            "WHERE event_type = 'SourceRetracted' ORDER BY event_id"
        ).fetchall()
        assert len(rows) == 2
        assert [r["caused_by"] for r in rows] == ["director-1", "director-2"]
        assert all(_json.loads(r["artifact_ids_json"]) == ["src-1"]
                   for r in rows)
        # advisory identical to the single-record state (the DELETE is
        # probe-only — production events are append-only)
        two = ctrl.retracted_source_review_candidates()
        assert [i["artifact_id"] for i in two["items"]] == ["ev-a"]
        conn.execute("DELETE FROM events WHERE event_type = 'SourceRetracted' "
                     "AND caused_by = 'director-2'")
        one = ctrl.retracted_source_review_candidates()
        assert two["items"] == one["items"]
        assert two["content_hash"] == one["content_hash"]
        # append-only: nothing else was written
        assert conn.execute(
            "SELECT COUNT(*) FROM artifacts").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM evidence_ladder_state").fetchone()[0] == 0

    def test_append_only_no_other_mutation(self, db):
        conn = db
        _artifact(conn, "src-1")
        ctrl = _make(conn)
        before = conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
        ctrl.record_source_retraction("src-1", caused_by="x", reason="y")
        assert conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == before
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


class TestRetractedSourceCandidates:
    def _seed(self, db):
        conn = db
        _artifact(conn, "src-1")
        _artifact(conn, "ev-a", "evidence")
        _edge(conn, "ev-a", "src-1", "derived_from")
        _classify(conn, "fc-ev-a", "ev-a")
        return conn

    def test_surfaces_exactly_the_retracted_downstream_set(self, db):
        conn = self._seed(db)
        _artifact(conn, "ev-b", "evidence")
        _edge(conn, "ev-b", "src-1", "derived_from")  # not classified
        ctrl = _make(conn)
        ctrl.record_source_retraction("src-1", caused_by="d", reason="r")
        out = ctrl.retracted_source_review_candidates()
        assert [i["artifact_id"] for i in out["items"]] == ["ev-a"]
        assert out["version"] == GRAPH_QUERY_VERSION

    def test_empty_when_no_retraction_recorded(self, db):
        conn = self._seed(db)
        out = _make(conn).retracted_source_review_candidates()
        assert out["items"] == []

    def test_corrupt_event_fails_closed_with_note(self, db):
        conn = self._seed(db)
        ctrl = _make(conn)
        ctrl.record_source_retraction("src-1", caused_by="d", reason="r")
        conn.execute(
            "UPDATE events SET artifact_ids_json = 'not-json{' "
            "WHERE event_type = 'SourceRetracted'")
        out = ctrl.retracted_source_review_candidates()
        assert out["items"] == []  # no silent seed, no crash
        assert any("corrupt SourceRetracted event" in n for n in ctrl._notes)

    def test_event_naming_missing_artifact_is_skipped_with_note(self, db):
        conn = self._seed(db)
        ctrl = _make(conn)
        ctrl.record_source_retraction("src-1", caused_by="d", reason="r")
        conn.execute(
            "UPDATE events SET artifact_ids_json = ? "
            "WHERE event_type = 'SourceRetracted'",
            ('["gone"]',))
        out = ctrl.retracted_source_review_candidates()
        assert out["items"] == []
        assert any("not resolvable in project" in n for n in ctrl._notes)

    def test_deterministic_and_project_scoped(self, db):
        conn = self._seed(db)
        ctrl = _make(conn)
        ctrl.record_source_retraction("src-1", caused_by="d", reason="r")
        # a second project's retraction event must not seed this surface
        conn.execute(
            """INSERT INTO events (event_type, project_id, caused_by,
               reason, artifact_ids_json, payload_json, created_at)
               VALUES ('SourceRetracted', 'p2', 'd', 'r',
                       '["other-src"]', '{"artifact_id": "other-src"}', ?)""",
            (CLOCK,),
        )
        first = ctrl.retracted_source_review_candidates()
        assert ctrl.retracted_source_review_candidates() == first
        assert [i["artifact_id"] for i in first["items"]] == ["ev-a"]


class TestReconcileDigest:
    def _seed(self, db):
        conn = db
        _artifact(conn, "src-1")
        _artifact(conn, "ev-a", "evidence")
        _edge(conn, "ev-a", "src-1", "derived_from")
        _classify(conn, "fc-ev-a", "ev-a")
        return conn

    def test_folds_proposals_and_candidates_versioned_and_hashed(self, db):
        conn = self._seed(db)
        ctrl = _make(conn)
        ctrl.record_source_retraction("src-1", caused_by="d", reason="r")
        digest = ctrl.reconcile_digest()
        assert digest["digest_version"] == "4"
        assert "classification_proposals" in digest
        assert digest["pending_proposals"] == []
        assert digest["classification_proposals"]["count"] == 1
        assert [i["artifact_id"] for i in digest["re_review_candidates"]["items"]] == ["ev-a"]
        assert digest["content_hash"]

    def test_never_writes_and_deterministic(self, db):
        conn = self._seed(db)
        ctrl = _make(conn)
        ctrl.record_source_retraction("src-1", caused_by="d", reason="r")
        before = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        first = ctrl.reconcile_digest()
        second = ctrl.reconcile_digest()
        assert first == second
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == before
        assert conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 3

    def test_empty_digest_is_stable(self, db):
        digest = _make(db).reconcile_digest()
        assert digest["classification_proposals"]["count"] == 0
        assert digest["re_review_candidates"]["items"] == []
        assert digest["content_hash"]


class TestForgedRetractionEventsVsLadder:
    """F6-lens follow-up (external red-team RT-01 probe): a forged
    SourceRetracted event — hand-inserted past every repository — can never
    touch Evidence Ladder state. The APPLY pass derives from ratified
    satisfaction facts, transition proposals, and Q-05 falsification facts
    only; the retraction event is advisory input at most. Corrupt and
    unresolvable events fail closed with observable notes."""

    def test_forged_retraction_events_never_touch_ladder_state(self, db):
        conn = db
        ctrl = _make(conn)
        # climb to SUPPORTED via the ratified obligation path
        _ladder_program(
            conn,
            hypotheses=[_ladder_hyp("h1", "SUPPORTED")],
            evidence=[_ladder_req("h1")])
        _satisfy_ladder(conn, "h1", SUPPORTED_CLASSES)
        ctrl.tick()
        before = _ladder_rows(conn)
        assert before                    # the climb landed
        applied_before = len(_applied_events(conn))

        # advisory shape: retracted source -> evidence -> classification
        _artifact(conn, "src-1")
        _artifact(conn, "ev-a", "evidence")
        _edge(conn, "ev-a", "src-1", "derived_from")
        _classify(conn, "fc-ev-a", "ev-a")

        # forge events directly (tamper lens, bypassing every repository)
        def forge(aids_json, payload="{}"):
            conn.execute(
                "INSERT INTO events (event_type, project_id, task_id, "
                "from_state, to_state, correlation_id, caused_by, reason, "
                "artifact_ids_json, payload_json, created_at) "
                "VALUES ('SourceRetracted', 'p1', NULL, NULL, NULL, '', "
                "'forged', 'forged', ?, ?, ?)",
                (aids_json, payload, CLOCK))

        forge('["src-1"]', '{"artifact_id": "src-1"}')  # valid-looking forged
        forge("not-json")                                # corrupt
        forge('["ghost"]')                               # unresolvable

        # the tick after the forgery must not move ladder state nor apply
        # anything new — and must not crash
        ctrl.tick()
        assert _ladder_rows(conn) == before
        assert len(_applied_events(conn)) == applied_before

        # the advisory is seeded exactly once from the valid-looking forged
        # event; corrupt + unresolvable fail closed with observable notes
        adv = ctrl.retracted_source_review_candidates()
        assert [i["artifact_id"] for i in adv["items"]] == ["ev-a"]
        fail_closed = [n for n in ctrl._notes
                       if "corrupt" in n or "not resolvable" in n]
        assert len(fail_closed) == 2
        # the advisory is read-only: nothing new was written by it
        assert _ladder_rows(conn) == before


SUPPORTED_CLASSES = ("pre_registered_experiment", "statistical_analysis",
                     "validation", "adversarial_critique")


def _ladder_hyp(ref, ladder="SUPPORTED"):
    return {"ref": ref, "ladder_target": ladder,
            "falsification_condition": "fc", "rival_of": None,
            "rival_status": None}


def _ladder_req(claim_ref, ladder="SUPPORTED"):
    return {"claim_ref": claim_ref, "ladder_target": ladder,
            "required_artifacts": list(SUPPORTED_CLASSES),
            "associated_gates": []}


def _ladder_program(conn, *, hypotheses=(), evidence=()):
    conn.execute(
        "INSERT INTO research_programs "
        "(program_id, project_id, version, content_hash, supersedes_id, "
        "scope_ref, epistemic_objective, compiler_version, policy_version, "
        "schema_version, input_hash, hypothesis_json, prediction_json, "
        "discrimination_json, evidence_json, gate_json, methodology_json, "
        "task_graph_template_ref, produced_by, reason, created_at) "
        "VALUES ('rp-1', 'p1', 1, 'ch-rp-1', NULL, 'b', 'o', 'c1', 'p1', "
        "'1', 'ih', ?, '[]', '[]', ?, '[]', '[]', NULL, 'director', "
        "NULL, ?)",
        (_json.dumps(list(hypotheses)), _json.dumps(list(evidence)), CLOCK))


def _satisfy_ladder(conn, requirement_ref, classes):
    repo = ProgramRequirementSatisfactionRepository(
        conn, clock=frozen_clock(CLOCK))
    verdict_repo = ValidationVerdictRepository(conn, clock=frozen_clock(CLOCK))
    for i, cls in enumerate(classes):
        aid = f"lart-{i}-{cls}"
        conn.execute(
            "INSERT INTO artifacts (artifact_id, project_id, task_id, "
            "artifact_type, content_hash, size_bytes, storage_path, "
            "producer, metadata_json, created_at) "
            "VALUES (?, 'p1', NULL, ?, ?, 1, 'x', 't', '{}', ?)",
            (aid, cls, "ch-" + aid, CLOCK))
        # M1/HR-02: a satisfaction link requires a PASS content-validation
        # verdict — record one so the ladder facts are real.
        verdict_repo.record(project_id="p1", artifact_id=aid, verdict="PASS")
        repo.record(project_id="p1", program_id="rp-1",
                    requirement_ref=requirement_ref, artifact_id=aid)


def _ladder_rows(conn):
    return [dict(r) for r in conn.execute(
        "SELECT program_id, hypothesis_ref, version, rung, transition_id, "
        "derived_from FROM evidence_ladder_state "
        "ORDER BY program_id, hypothesis_ref, version")]


def _applied_events(conn):
    return [dict(r) for r in conn.execute(
        "SELECT correlation_id, from_state, to_state "
        "FROM events WHERE event_type = 'EvidenceTransitionApplied' "
        "ORDER BY event_id")]
