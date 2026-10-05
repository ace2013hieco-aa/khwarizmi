"""P6 production classification writer tests (ratified P6 contract).

Proves the legitimate production boundary: operator-asserted failure
classifications admitted through the RECORD_CLASSIFICATION internal
intent (credential + lease + HumanDecision + gateway validator that
delegates semantics to the existing write boundary), consumed by the
existing detector/lifecycle/review/completion machinery.

Matrix: E2E detection→contradiction→resolution; identity; duplicate/
replay; state machine; authority (OPERATOR/LOCK/ROLE/fabricated);
supersession; evidence A–E; active reader; re-review seeds; HR-08
denial/clearance/isolation; N1–N7 negatives; determinism across
rebuilds; S5 follow-on supersession; journal-failure atomicity.
"""
from __future__ import annotations

import json

import pytest

from hermes.core import frozen_clock
from hermes.core.events import EventType
from hermes.core.intents import Intent, IntentKind
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    OperatorCredentialRepository,
    ProjectRepository,
    _append_event_to_db,
)
from hermes.research.contradictions import (
    CONTRADICTION_DETECTOR_VERSION,
    contradiction_id_of,
)
from hermes.research.controller import Controller
from hermes.research.gateway import (
    EVIDENCE_REF,
    PROPOSAL,
    GatewayRejection,
    apply_intent,
)

CLOCK = "2026-01-01T00:00:00.000000+00:00"
OP_ID = "op-1"
OP_TOKEN = "op-token-1-long"


# ═══════════════════════ fixtures ═══════════════════════


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


def _insert_program(db, program_id="rp-1", *, project="p1", version=1,
                    hypotheses=("h1",), predictions=("p1",)):
    db.execute(
        """INSERT INTO research_programs
           (program_id, project_id, version, content_hash, supersedes_id,
            scope_ref, epistemic_objective, compiler_version, policy_version,
            schema_version, input_hash, hypothesis_json, prediction_json,
            discrimination_json, evidence_json, gate_json, methodology_json,
            task_graph_template_ref, produced_by, reason, created_at)
           VALUES (?, ?, ?, ?, NULL, 'b', 'o', 'c1', 'p1', '1', 'ih', ?,
                   ?, '[]', '[]', '[]', '[]', NULL, 'director', NULL, ?)""",
        (program_id, project, version, "ch-" + program_id,
         json.dumps([{"ref": h, "ladder_target": "SUPPORTED",
                      "falsification_condition": "fc", "rival_of": None,
                      "rival_status": None} for h in hypotheses]),
         json.dumps([{"ref": p} for p in predictions]), CLOCK))


def _insert_task(db, task_id, status="RUNNING", *, project="p1"):
    from hermes.core.node import NodeContract
    from hermes.persistence.repositories import TaskRepository
    repo = TaskRepository(db, frozen_clock(CLOCK))
    node = NodeContract(
        task_id=task_id, project_id=project, task_type="TOOL_TASK",
        idempotency_key=f"idem-{task_id}", dependencies=[])
    repo.create(node)
    if status != "PENDING":
        db.execute("UPDATE tasks SET status = ? WHERE task_id = ?",
                   (status, task_id))


def _insert_evidence_chain(db, *, ev_id="art-ev1", ev_hash="evhash1",
                            outcome_id="art-out1", task_id="t-prod",
                            project="p1", ev_type="source_result"):
    """Two-hop lineage: evidence -> outcome -> task (D4 ownership)."""
    _insert_task(db, task_id, status="RUNNING", project=project)
    for aid, atype, ch in ((outcome_id, "source_result",
                            f"outhash-{outcome_id}"),
                           (ev_id, ev_type, ev_hash)):
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


def _classify(db, *, failure_class, evidence_ref, program_ref="rp-1",
              hypothesis_ref="h1", task_id="t-prod", operator_id=OP_ID,
              classifier_version="1.0", constraint_ref=None,
              failed_mechanism_ref=None, resource_gap=None, rationale=""):
    ctrl = _make(db)
    kwargs = {}
    if constraint_ref is not None:
        kwargs["constraint_ref"] = constraint_ref
    if failed_mechanism_ref is not None:
        kwargs["failed_mechanism_ref"] = failed_mechanism_ref
    if resource_gap is not None:
        kwargs["resource_gap"] = resource_gap
    return ctrl.record_failure_classification(
        program_ref=program_ref, hypothesis_ref=hypothesis_ref,
        failure_class=failure_class, evidence_refs=[evidence_ref],
        falsifying_evidence_refs=[evidence_ref],
        explanation=f"operator analysis {failure_class}",
        classifier_version=classifier_version,
        proposed_by=f"operator:{operator_id}",
        producing_task_id=task_id, rationale=rationale,
        operator_id=operator_id, operator_token=OP_TOKEN, **kwargs)


def _conflicting_pair(db, *, ev_hash="evhash1", ev_id="art-ev1"):
    """Two operator-recorded classifications, same target, different
    classes, shared evidence. Returns (id_a, id_b)."""
    _insert_program(db)
    _insert_evidence_chain(db, ev_id=ev_id, ev_hash=ev_hash)
    ref = f"source_result:{ev_hash}"
    r1 = _classify(
        db, failure_class="DECLARED_CONSTRAINT_VIOLATION", evidence_ref=ref,
        constraint_ref="hypothesis:h1:falsification_condition")
    assert r1["rejected"] is False, r1
    r2 = _classify(
        db, failure_class="IMPLEMENTATION_FAILURE", evidence_ref=ref,
        failed_mechanism_ref="prediction:p1")
    assert r2["rejected"] is False, r2
    return r1["entity_id"], r2["entity_id"]


def _status(db, contradiction_id):
    row = db.execute(
        "SELECT status FROM contradictions WHERE contradiction_id = ?",
        (contradiction_id,)).fetchone()
    return row["status"] if row else None


# ═══════════════════════ E2E: record → detect → resolve ═══════════════════════


class TestEndToEnd:
    def test_record_two_classifications_then_contradiction(self, db):
        a, b = _conflicting_pair(db)
        assert a != b
        ctrl = _make(db)
        det = ctrl.detect_contradictions()
        assert det["rejected"] is False
        assert det["recorded"] == [contradiction_id_of(a, b)]
        cid = det["recorded"][0]
        assert _status(db, cid) == "OPEN"
        res = ctrl.record_contradiction_resolution(
            contradiction_id=cid, operator_id=OP_ID,
            operator_token=OP_TOKEN)
        assert res["rejected"] is False
        assert _status(db, cid) == "RESOLVED"

    def test_provenance_chain_persisted(self, db):
        a, b = _conflicting_pair(db)
        cid = contradiction_id_of(a, b)
        _make(db).detect_contradictions()
        row = db.execute(
            "SELECT * FROM contradictions WHERE contradiction_id = ?",
            (cid,)).fetchone()
        assert row["party_a"] == min(a, b)
        assert row["party_b"] == max(a, b)
        assert row["detector_version"]
        assert row["detection_event_ref"] == cid
        det = db.execute(
            "SELECT * FROM events WHERE event_type = ?",
            (EventType.CONTRADICTION_DETECTED.value,)).fetchone()
        assert det is not None
        assert det["correlation_id"] == cid


# ═══════════════════════ identity / duplicates ═══════════════════════


class TestIdentity:
    def test_command_hash_deterministic(self, db):
        a, _b = _conflicting_pair(db)
        # Same logical command re-recorded: content-hash idempotent.
        r = _classify(
            db, failure_class="DECLARED_CONSTRAINT_VIOLATION",
            evidence_ref="source_result:evhash1",
            constraint_ref="hypothesis:h1:falsification_condition")
        assert r["duplicate"] is True
        assert r["entity_id"] == a
        assert db.execute(
            "SELECT COUNT(*) c FROM artifacts "
            "WHERE artifact_type = 'failure_classification'"
        ).fetchone()["c"] == 2

    def test_contradiction_identity_stable(self, db):
        a, b = _conflicting_pair(db)
        assert contradiction_id_of(a, b) == contradiction_id_of(b, a)
        ctrl = _make(db)
        assert ctrl.detect_contradictions()["recorded"] == [
            contradiction_id_of(a, b)]
        # Re-detection is duplicate, never a second row.
        assert ctrl.detect_contradictions()["duplicates"] == 1
        assert db.execute(
            "SELECT COUNT(*) c FROM contradictions").fetchone()["c"] == 1

    def test_unrelated_pair_independent(self, db):
        a, b = _conflicting_pair(db)
        # Regime axis deferred — fail closed at the write path.
        r_env = _classify(
            db, failure_class="ENVIRONMENT_MISMATCH",
            evidence_ref="source_result:evhash1")
        assert r_env["rejected"] is True
        # A third class over SHARED evidence creates two new pairs;
        # the original pair is untouched until detection.
        r = _classify(
            db, failure_class="RESOURCE_CONSTRAINT",
            evidence_ref="source_result:evhash1",
            resource_gap={"resource_kind": "gpu",
                          "observed": 1.0, "required": 8.0,
                          "unit": "cards"})
        assert r["rejected"] is False, r
        c = r["entity_id"]
        det = _make(db).detect_contradictions()
        assert det["rejected"] is False
        assert len(det["recorded"]) == 3
        assert contradiction_id_of(a, b) in det["recorded"]
        assert contradiction_id_of(a, c) in det["recorded"]
        assert contradiction_id_of(b, c) in det["recorded"]
        assert db.execute(
            "SELECT COUNT(*) c FROM contradictions").fetchone()["c"] == 3


# ═══════════════════════ authority ═══════════════════════


class TestAuthority:
    def test_bad_credential_refused_zero_writes(self, db):
        _insert_program(db)
        _insert_evidence_chain(db)
        before = db.execute(
            "SELECT COUNT(*) c FROM events").fetchone()["c"]
        out = _classify(db, failure_class="DECLARED_CONSTRAINT_VIOLATION",
                        evidence_ref="source_result:evhash1",
                        constraint_ref="hypothesis:h1:"
                                       "falsification_condition",
                        operator_id="bad-op")
        assert out["rejected"] is True
        assert out["code"] == "OPERATOR"
        assert db.execute(
            "SELECT COUNT(*) c FROM events").fetchone()["c"] == before
        assert db.execute(
            "SELECT COUNT(*) c FROM artifacts WHERE artifact_type = ?",
            ("failure_classification",)).fetchone()["c"] == 0

    def test_held_lease_refused_then_lands(self, db):
        _insert_program(db)
        _insert_evidence_chain(db)
        ctrl = _make(db)
        other = _make(db)
        assert other._acquire_lock() is True
        out = ctrl.record_failure_classification(
            program_ref="rp-1", hypothesis_ref="h1",
            failure_class="DECLARED_CONSTRAINT_VIOLATION",
            evidence_refs=["source_result:evhash1"],
            falsifying_evidence_refs=["source_result:evhash1"],
            explanation="x", classifier_version="1.0",
            constraint_ref="hypothesis:h1:falsification_condition",
            proposed_by="operator:op-1", producing_task_id="t-prod",
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is True
        assert out["code"] == "LOCK"
        other._release_lock()
        out = ctrl.record_failure_classification(
            program_ref="rp-1", hypothesis_ref="h1",
            failure_class="DECLARED_CONSTRAINT_VIOLATION",
            evidence_refs=["source_result:evhash1"],
            falsifying_evidence_refs=["source_result:evhash1"],
            explanation="x", classifier_version="1.0",
            constraint_ref="hypothesis:h1:falsification_condition",
            proposed_by="operator:op-1", producing_task_id="t-prod",
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is False

    def test_llm_proposed_record_refused(self, db):
        _insert_program(db)
        _insert_evidence_chain(db)
        for role in ("DIRECTOR", "RESEARCHER", "IMPLEMENTER", "ADVERSARY"):
            with pytest.raises(GatewayRejection) as exc:
                apply_intent(db, Intent(
                    kind=IntentKind.RECORD_CLASSIFICATION,
                    proposed_by=role, project_id="p1",
                    justification="x",
                    payload={"program_ref": "rp-1", "hypothesis_ref": "h1",
                             "failure_class": "UNKNOWN",
                             "evidence_refs": [],
                             "falsifying_evidence_refs": [],
                             "explanation": "x", "classifier_version": "1.0",
                             "constraint_ref": None,
                             "failed_mechanism_ref": None,
                             "regime_ref": None, "resource_gap": None,
                             "scope_brief_ref": None,
                             "scope_brief_field": None,
                             "contributing_factors": [],
                             "proposed_by": "llm",
                             "producing_task_id": "t-prod",
                             "human_decision_ref": "hd-x",
                             "operator_id": OP_ID}))
            assert exc.value.code == "ROLE"

    def test_resolution_requires_human_verdict(self, db):
        _ = _conflicting_pair(db)
        cid = _make(db).detect_contradictions()["recorded"][0]
        # Fabricated decision reference: fail closed.
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.CONTRADICTION_RESOLUTION,
                proposed_by="DETERMINISTIC", project_id="p1",
                justification="x",
                payload={"contradiction_id": cid,
                         "human_decision_ref": "hd-ghost",
                         "operator_id": OP_ID}))
        assert exc.value.code == PROPOSAL
        assert _status(db, cid) == "OPEN"


# ═══════════════════════ supersession / evidence / reader ═══════════════════════


class TestLifecycle:
    def test_supersede_chain(self, db):
        _ = _conflicting_pair(db)
        r1 = _make(db).detect_contradictions()["recorded"][0]
        # A second pair on other evidence, recorded naming r1.
        _insert_evidence_chain(db, ev_id="art-ev2", ev_hash="evhash2",
                               outcome_id="art-out2", task_id="t-prod2")
        ids = _classify_pair_on_evidence(db, "evhash2", task_id="t-prod2")
        r2 = _record(db, ids[0], ids[1], supersedes_ref=r1)
        assert r2.duplicate is False
        assert _status(db, r1) == "SUPERSEDED"
        assert _status(db, r2.entity_id) == "OPEN"
        ev = db.execute(
            "SELECT * FROM events WHERE event_type = ?",
            (EventType.CONTRADICTION_SUPERSEDED.value,)).fetchone()
        assert ev is not None

    def test_re_review_seeds(self, db):
        a, b = _conflicting_pair(db)
        _insert_artifact_simple(db, "src-s")
        _insert_artifact_simple(db, "down-1")
        db.execute(
            "INSERT INTO provenance_edges (artifact_id, upstream_id, "
            "edge_type, created_at) VALUES ('down-1', 'src-s', 'cites', ?)",
            (CLOCK,))
        ctrl = _make(db)
        before = ctrl.re_review_candidates(["src-s"])
        base_ids = [i["artifact_id"] for i in before["items"]]
        ctrl.detect_contradictions()
        after = ctrl.re_review_candidates(["src-s"])
        after_ids = [i["artifact_id"] for i in after["items"]]
        assert [i for i in after_ids if i in base_ids] == base_ids
        for party in (a, b):
            matches = [i for i in after["items"]
                       if i["artifact_id"] == party]
            assert len(matches) == 1
            assert matches[0]["reached_via"] == "contradiction"


def _classify_pair_on_evidence(db, ev_hash, *, task_id,
                               classes=("DECLARED_CONSTRAINT_VIOLATION",
                                        "IMPLEMENTATION_FAILURE")):
    ref = f"source_result:{ev_hash}"
    ids = []
    for failure_class in classes:
        kw = {}
        if failure_class == "DECLARED_CONSTRAINT_VIOLATION":
            kw["constraint_ref"] = "hypothesis:h1:falsification_condition"
        else:
            kw["failed_mechanism_ref"] = "prediction:p1"
        out = _classify(db, failure_class=failure_class, evidence_ref=ref,
                        task_id=task_id, **kw)
        assert out["rejected"] is False, out
        ids.append(out["entity_id"])
    return ids


def _record(db, party_a, party_b, *, detector_version=None,
            supersedes_ref="", project="p1"):
    return apply_intent(db, Intent(
        kind=IntentKind.RECORD_CONTRADICTION, proposed_by="DETERMINISTIC",
        project_id=project, justification="p6 test",
        payload={"party_a": party_a, "party_b": party_b,
                 "detector_version": detector_version
                 or CONTRADICTION_DETECTOR_VERSION,
                 "supersedes_ref": supersedes_ref}))


# ═══════════════════════ HR-08 ═══════════════════════


class TestHR08:
    def test_open_contradiction_denies_completion(self, db):
        from hermes.research.completion import can_complete_research
        _ = _conflicting_pair(db)
        _make(db).detect_contradictions()
        result = can_complete_research(db, "p1")
        assert result.eligible is False
        assert "OPEN_CONTRADICTION" in [d.code for d in result.denials]

    def test_resolved_clears_denial(self, db):
        from hermes.research.completion import can_complete_research
        _ = _conflicting_pair(db)
        cid = _make(db).detect_contradictions()["recorded"][0]
        _make(db).record_contradiction_resolution(
            contradiction_id=cid, operator_id=OP_ID,
            operator_token=OP_TOKEN)
        result = can_complete_research(db, "p1")
        assert "OPEN_CONTRADICTION" not in [
            d.code for d in result.denials]

    def test_unrelated_program_unaffected(self, db):
        from hermes.research.completion import can_complete_research
        _conflicting_pair(db)  # program rp-1
        _insert_program(db, program_id="rp-2", version=2)
        _make(db).detect_contradictions()
        result = can_complete_research(db, "p1")
        # Head is rp-2 (version 2): the rp-1 contradiction is foreign.
        assert "OPEN_CONTRADICTION" not in [
            d.code for d in result.denials]


def _record_direct(db, party_a, party_b):
    return apply_intent(db, Intent(
        kind=IntentKind.RECORD_CONTRADICTION, proposed_by="DETERMINISTIC",
        project_id="p1", justification="p6",
        payload={"party_a": party_a, "party_b": party_b,
                 "detector_version": "test", "supersedes_ref": ""}))


# ═══════════════════════ negatives N1–N7 ═══════════════════════


class TestNegatives:
    def test_n1_ghost_evidence_refused(self, db):
        _insert_program(db)
        _insert_task(db, "t-prod")
        out = _classify(
            db, failure_class="DECLARED_CONSTRAINT_VIOLATION",
            evidence_ref="source_result:00",
            constraint_ref="hypothesis:h1:falsification_condition")
        assert out["rejected"] is True

    def test_n2_cross_project_evidence_refused(self, db):
        _insert_program(db)
        _insert_evidence_chain(db)
        _insert_program(db, program_id="rp-x", project="p2")
        out = _classify_pair_cross(db)
        assert out["rejected"] is True

    def test_n3_invalid_class_refused(self, db):
        _insert_program(db)
        _insert_evidence_chain(db)
        out = _classify(
            db, failure_class="NOT_A_CLASS",
            evidence_ref="source_result:evhash1",
            constraint_ref="hypothesis:h1:falsification_condition")
        assert out["rejected"] is True
        assert out["code"] == "MALFORMED_PAYLOAD"

    def test_n3b_regime_class_refused(self, db):
        _insert_program(db)
        _insert_evidence_chain(db)
        out = _classify(
            db, failure_class="ENVIRONMENT_MISMATCH",
            evidence_ref="source_result:evhash1")
        assert out["rejected"] is True

    def test_n4_duplicate_idempotent(self, db):
        a, _b = _conflicting_pair(db)
        r = _classify(
            db, failure_class="DECLARED_CONSTRAINT_VIOLATION",
            evidence_ref="source_result:evhash1",
            constraint_ref="hypothesis:h1:falsification_condition")
        assert r["duplicate"] is True
        assert r["entity_id"] == a

    def test_n5_unauthorized_resolution_refused(self, db):
        _ = _conflicting_pair(db)
        cid = _make(db).detect_contradictions()["recorded"][0]
        out = _make(db).record_contradiction_resolution(
            contradiction_id=cid, operator_id="bad-op",
            operator_token="wrong")
        assert out["rejected"] is True
        assert out["code"] == "OPERATOR"
        assert _status(db, cid) == "OPEN"

    def test_n6_classifier_cannot_resolve(self, db):
        # No classifier-side surface resolves: the only resolution
        # path is the human-verdict intent (internal-only).
        assert IntentKind.CONTRADICTION_RESOLUTION \
            not in IntentKind.llm_proposable()
        assert IntentKind.CONTRADICTION_RESOLUTION \
            in IntentKind.internal_only()
        assert IntentKind.RECORD_CLASSIFICATION \
            not in IntentKind.llm_proposable()
        assert IntentKind.RECORD_CLASSIFICATION \
            in IntentKind.internal_only()

    def test_n7_invalidated_party_excluded(self, db):
        a, b = _conflicting_pair(db)
        db.execute(
            "UPDATE artifacts SET metadata_json = ? WHERE artifact_id = ?",
            (json.dumps({"invalidation_marker": "INVALIDATED"}), a))
        out = _make(db).detect_contradictions()
        assert out["recorded"] == []
        # And the validator refuses a hand-built pair naming it.
        with pytest.raises(GatewayRejection) as exc:
            _record_direct(db, a, b)
        assert exc.value.code == EVIDENCE_REF


def _classify_pair_cross(db):
    return _classify(
        db, failure_class="DECLARED_CONSTRAINT_VIOLATION",
        evidence_ref="source_result:evhash1",
        constraint_ref="hypothesis:h1:falsification_condition",
        program_ref="rp-x")


# ═══════════════════════ determinism / S5 / failure ═══════════════════════


class TestDeterminism:
    def test_identical_rebuild_identical_ids(self, db):
        a, b = _conflicting_pair(db)
        first = (a, b, contradiction_id_of(a, b))

        def rebuild():
            conn = connect(":memory:")
            migrate_to_latest(conn)
            ProjectRepository(conn, frozen_clock(CLOCK)).create(
                "p1", "Test")
            OperatorCredentialRepository(
                conn, frozen_clock(CLOCK)).register(
                    OP_ID, OP_TOKEN, "Test Operator")
            return conn

        conn2 = rebuild()
        try:
            _insert_program(conn2)
            _insert_evidence_chain(conn2)
            ctrl2 = Controller(conn2, project_id="p1",
                               clock=frozen_clock(CLOCK))
            ref = "source_result:evhash1"
            r1 = ctrl2.record_failure_classification(
                program_ref="rp-1", hypothesis_ref="h1",
                failure_class="DECLARED_CONSTRAINT_VIOLATION",
                evidence_refs=[ref], falsifying_evidence_refs=[ref],
                explanation="operator analysis "
                            "DECLARED_CONSTRAINT_VIOLATION",
                classifier_version="1.0",
                constraint_ref="hypothesis:h1:falsification_condition",
                proposed_by="operator:op-1", producing_task_id="t-prod",
                operator_id=OP_ID, operator_token=OP_TOKEN)
            r2 = ctrl2.record_failure_classification(
                program_ref="rp-1", hypothesis_ref="h1",
                failure_class="IMPLEMENTATION_FAILURE",
                evidence_refs=[ref], falsifying_evidence_refs=[ref],
                explanation="operator analysis IMPLEMENTATION_FAILURE",
                classifier_version="1.0",
                failed_mechanism_ref="prediction:p1",
                proposed_by="operator:op-1", producing_task_id="t-prod",
                operator_id=OP_ID, operator_token=OP_TOKEN)
            assert (r1["entity_id"], r2["entity_id"],
                    contradiction_id_of(r1["entity_id"], r2["entity_id"])) \
                == first
            det = ctrl2.detect_contradictions()
            assert det["recorded"] == [first[2]]
        finally:
            conn2.close()

    def test_journal_failure_rolls_back(self, db):
        from unittest import mock

        import hermes.research.controller as ctrl_mod
        import hermes.research.verdict_decisions as vd_mod

        _ = _conflicting_pair(db)
        real_append = ctrl_mod._append_event_to_db

        def failing(conn, clock, event_type, *a, **kw):
            raise RuntimeError("simulated storage failure")

        # Both append seams are patched: the failure must hold whether the
        # controller (pre-extraction) or the helper (post-extraction) owns
        # the verdict's first journal write.
        with mock.patch.object(ctrl_mod, "_append_event_to_db", failing), \
                mock.patch.object(vd_mod, "_append_event_to_db", failing), \
                pytest.raises(RuntimeError):
                _classify(
                    db, failure_class="RESOURCE_CONSTRAINT",
                    evidence_ref="source_result:evhash1",
                    resource_gap={"resource_kind": "gpu", "observed": 1.0,
                                  "required": 8.0, "unit": "cards"})
        assert db.execute(
            "SELECT COUNT(*) c FROM artifacts "
            "WHERE artifact_type = 'failure_classification'"
        ).fetchone()["c"] == 2
        assert real_append is ctrl_mod._append_event_to_db

    def test_lease_released_after_paths(self, db):
        _ = _conflicting_pair(db)
        ctrl = _make(db)
        ctrl.detect_contradictions()
        assert db.execute(
            "SELECT COUNT(*) c FROM scheduler_lock").fetchone()["c"] == 0
        ctrl.record_failure_classification(
            program_ref="rp-1", hypothesis_ref="h1",
            failure_class="UNKNOWN", evidence_refs=[],
            falsifying_evidence_refs=[],
            explanation="x", classifier_version="1.0",
            proposed_by="operator:op-1", producing_task_id="t-prod",
            operator_id="bad-op", operator_token="wrong")
        assert db.execute(
            "SELECT COUNT(*) c FROM scheduler_lock").fetchone()["c"] == 0


class TestS5FollowOn:
    def test_retraction_supersedes_open_contradiction(self, db):
        # Classifications cite source_result:evhash1 via cites edges;
        # retracting it puts both parties in the S5 cone.
        _ = _conflicting_pair(db)
        cid = _make(db).detect_contradictions()["recorded"][0]
        assert _status(db, cid) == "OPEN"
        _record_decision(db)
        _retract(db, source_ref="source_result:evhash1")
        assert _status(db, cid) == "SUPERSEDED"
        ev = db.execute(
            "SELECT * FROM events WHERE event_type = ?",
            (EventType.CONTRADICTION_SUPERSEDED.value,)).fetchone()
        assert ev is not None

    def test_s5_without_contradictions_unchanged(self, db):
        _record_decision(db)
        _insert_artifact_simple(db, "src-a")
        _insert_artifact_simple(db, "down-1")
        db.execute(
            "INSERT INTO provenance_edges (artifact_id, upstream_id, "
            "edge_type, created_at) VALUES ('down-1', 'src-a', 'cites', ?)",
            (CLOCK,))
        result = _retract(db, source_ref="src-a")
        assert result.row["invalidated_artifacts"] == ["down-1"]


def _insert_artifact_simple(db, artifact_id):
    db.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type,
            content_hash, size_bytes, storage_path, producer,
            metadata_json, created_at)
           VALUES (?, 'p1', NULL, 'source_result', ?, 1, 'x', 't', NULL,
                   ?)""",
        (artifact_id, f"ch-{artifact_id}", CLOCK))


def _record_decision(db, ref="hd-1", project="p1"):
    _append_event_to_db(
        db, frozen_clock(CLOCK),
        EventType.HUMAN_DECISION_RECEIVED.value,
        project_id=project, correlation_id=ref, caused_by="operator",
        reason="operator decision", payload={"decision": "RETRACT"})


def _retract(db, source_ref="src-a", decision_ref="hd-1", project="p1"):
    return apply_intent(db, Intent(
        kind=IntentKind.RETRACT_SOURCE, proposed_by="DETERMINISTIC",
        project_id=project, justification="p6 test",
        payload={"source_ref": source_ref, "reason": "retracted",
                 "human_decision_ref": decision_ref}))
