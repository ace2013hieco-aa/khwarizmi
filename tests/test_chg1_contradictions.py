"""CHG-1 contradiction lifecycle tests (ratified CHG-1 contract).

Covers: detection (CLASSIFICATION_CONFLICT only), deterministic
identity, duplicate/replay semantics, OPEN→RESOLVED→(terminal) and
OPEN→SUPERSEDED state machine, human-gated resolution authority,
head-only supersession, new-evidence cases A–E, active reader,
re-review seeds, HR-08 OPEN_CONTRADICTION denial, project isolation,
detector/journal failure, S5 follow-on supersession, recovery
(no-reopen).
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
    ContradictionRepository,
    OperatorCredentialRepository,
    ProjectRepository,
    _append_event_to_db,
)
from hermes.research.contradictions import (
    CONTRADICTION_DETECTOR_VERSION,
    contradiction_id_of,
)
from hermes.research.controller import Controller
from hermes.research.evidence_ladder import classification_content_hash
from hermes.research.gateway import (
    EVIDENCE_REF,
    PROPOSAL,
    STALE,
    GatewayRejection,
    apply_intent,
)

CLOCK = "2026-01-01T00:00:00.000000+00:00"
OP_ID = "op-1"
OP_TOKEN = "op-token-1"


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


def _insert_artifact(db, artifact_id, *, artifact_type="source_result",
                     content_hash=None, project="p1", task_id=None,
                     meta=None):
    db.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type,
            content_hash, size_bytes, storage_path, producer,
            metadata_json, created_at)
           VALUES (?, ?, ?, ?, ?, 1, 'x', 't', ?, ?)""",
        (artifact_id, project, task_id, artifact_type,
         content_hash or f"ch-{artifact_id}",
         json.dumps(meta) if meta is not None else None, CLOCK))


def _insert_classification(db, *, cls_art="fc-1", project="p1",
                           program_ref="rp-1", hypothesis_ref="h1",
                           failure_class="DECLARED_CONSTRAINT_VIOLATION",
                           falsifying_refs=None):
    """A digest-valid classification artifact. Returns artifact_id."""
    if falsifying_refs is None:
        falsifying_refs = ["evidence:evhash1"]
    from hermes.research.failure_classification import (
        ACTION_MAP,
        FailureClass,
    )
    permitted = sorted(
        a.value for a in ACTION_MAP[FailureClass(failure_class)])
    meta = {
        "schema_version": "1",
        "failure_class": failure_class,
        "hypothesis_ref": hypothesis_ref,
        "program_ref": program_ref,
        "classification_id": cls_art,
        "classifier_version": "1.0",
        "contributing_factors": [],
        "evidence_refs": list(falsifying_refs),
        "constraint_ref": f"hypothesis:{hypothesis_ref}:falsification_condition",
        "failed_mechanism_ref": None,
        "regime_ref": None,
        "resource_gap": None,
        "scope_brief_ref": None,
        "scope_brief_field": None,
        "explanation": f"chg1 test {cls_art}",
        "proposed_by": "DIRECTOR",
        "falsifying_evidence_refs": list(falsifying_refs),
        "permitted_actions": permitted,
    }
    content_hash = classification_content_hash(meta, project)
    _insert_artifact(db, cls_art, artifact_type="failure_classification",
                     content_hash=content_hash, project=project, meta=meta)
    return cls_art


def _insert_evidence(db, artifact_id="art-ev1", *, content_hash="evhash1",
                     project="p1"):
    _insert_artifact(db, artifact_id, artifact_type="evidence",
                     content_hash=content_hash, project=project)


def _conflicting_pair(db, *, project="p1", program_ref="rp-1",
                      hypothesis_ref="h1", evidence_hash="evhash1",
                      evidence_id="art-ev1", cls_a="fc-a", cls_b="fc-b"):
    """Two digest-valid classifications, same target, different classes,
    sharing one evidence artifact. Returns (id_a, id_b)."""
    _insert_evidence(db, evidence_id, content_hash=evidence_hash,
                     project=project)
    _insert_classification(
        db, cls_art=cls_a, project=project, program_ref=program_ref,
        hypothesis_ref=hypothesis_ref,
        failure_class="DECLARED_CONSTRAINT_VIOLATION",
        falsifying_refs=[f"evidence:{evidence_hash}"])
    _insert_classification(
        db, cls_art=cls_b, project=project, program_ref=program_ref,
        hypothesis_ref=hypothesis_ref,
        failure_class="IMPLEMENTATION_FAILURE",
        falsifying_refs=[f"evidence:{evidence_hash}"])
    return cls_a, cls_b


def _record(db, party_a, party_b, *, detector_version=None,
            supersedes_ref="", project="p1"):
    return apply_intent(db, Intent(
        kind=IntentKind.RECORD_CONTRADICTION, proposed_by="DETERMINISTIC",
        project_id=project, justification="chg1 test",
        payload={"party_a": party_a, "party_b": party_b,
                 "detector_version": detector_version
                 or CONTRADICTION_DETECTOR_VERSION,
                 "supersedes_ref": supersedes_ref}))


def _resolve(db, contradiction_id, *, operator_id=OP_ID,
             project="p1") -> dict:
    ctrl = _make(db, project=project)
    return ctrl.record_contradiction_resolution(
        contradiction_id=contradiction_id,
        operator_id=operator_id, operator_token=OP_TOKEN)


def _status(db, contradiction_id):
    row = db.execute(
        "SELECT status FROM contradictions WHERE contradiction_id = ?",
        (contradiction_id,)).fetchone()
    return row["status"] if row else None


def _retract(db, source_ref="src-a", decision_ref="hd-1", project="p1",
             reason="source retracted by publisher"):
    return apply_intent(db, Intent(
        kind=IntentKind.RETRACT_SOURCE, proposed_by="DETERMINISTIC",
        project_id=project, justification="chg1 test",
        payload={"source_ref": source_ref, "reason": reason,
                 "human_decision_ref": decision_ref}))


# ═══════════════════════ detection ═══════════════════════


class TestDetection:
    def test_detect_and_record_conflict(self, db):
        a, b = _conflicting_pair(db)
        ctrl = _make(db)
        out = ctrl.detect_contradictions()
        assert out["rejected"] is False
        assert out["refused"] == []
        assert len(out["recorded"]) == 1
        cid = out["recorded"][0]
        assert cid == contradiction_id_of(a, b) == contradiction_id_of(b, a)
        assert _status(db, cid) == "OPEN"
        ev = db.execute(
            "SELECT * FROM events WHERE event_type = ?",
            (EventType.CONTRADICTION_DETECTED.value,)).fetchone()
        assert ev is not None
        assert ev["correlation_id"] == cid

    def test_same_class_no_record(self, db):
        _insert_evidence(db)
        _insert_classification(db, cls_art="fc-a")
        _insert_classification(
            db, cls_art="fc-b",
            failure_class="DECLARED_CONSTRAINT_VIOLATION")
        out = _make(db).detect_contradictions()
        assert out["rejected"] is False
        assert out["recorded"] == []
        assert db.execute(
            "SELECT COUNT(*) c FROM contradictions").fetchone()["c"] == 0

    def test_different_hypothesis_no_record(self, db):
        _insert_evidence(db)
        _insert_classification(db, cls_art="fc-a", hypothesis_ref="h1")
        _insert_classification(
            db, cls_art="fc-b", hypothesis_ref="h2",
            failure_class="IMPLEMENTATION_FAILURE")
        out = _make(db).detect_contradictions()
        assert out["recorded"] == []

    def test_no_overlap_no_record(self, db):
        _insert_evidence(db, "art-e1", content_hash="evhash1")
        _insert_evidence(db, "art-e2", content_hash="evhash2")
        _insert_classification(db, cls_art="fc-a",
                               falsifying_refs=["evidence:evhash1"])
        _insert_classification(
            db, cls_art="fc-b", failure_class="IMPLEMENTATION_FAILURE",
            falsifying_refs=["evidence:evhash2"])
        out = _make(db).detect_contradictions()
        assert out["recorded"] == []

    def test_invalidated_party_no_record(self, db):
        a, _b = _conflicting_pair(db)
        db.execute(
            "UPDATE artifacts SET metadata_json = ? WHERE artifact_id = ?",
            (json.dumps({"invalidation_marker": "INVALIDATED"}), a))
        out = _make(db).detect_contradictions()
        assert out["recorded"] == []

    def test_natural_language_not_inferred(self, db):
        # Two claims with opposing statements produce no contradiction:
        # Hermes never infers conflict from prose.
        db.execute(
            """INSERT INTO research_claims
               (claim_id, project_id, content_hash, statement, source_ref,
                schema_version, extracted_by, reason, created_at,
                context_tags_json)
               VALUES ('cl-1', 'p1', 'ch1', 'X causes Y',
                       'source_result:hh', '1', 't', NULL, ?, '{}')""",
            (CLOCK,))
        db.execute(
            """INSERT INTO research_claims
               (claim_id, project_id, content_hash, statement, source_ref,
                schema_version, extracted_by, reason, created_at,
                context_tags_json)
               VALUES ('cl-2', 'p1', 'ch2', 'X does not cause Y',
                       'source_result:hh', '1', 't', NULL, ?, '{}')""",
            (CLOCK,))
        out = _make(db).detect_contradictions()
        assert out["recorded"] == []


# ═══════════════════════ identity / duplicates ═══════════════════════


class TestIdentity:
    def test_canonical_pair_ordering(self, db):
        _ = _conflicting_pair(db, cls_a="fc-b", cls_b="fc-a")
        r1 = _record(db, "fc-a", "fc-b")
        assert r1.duplicate is False
        assert r1.entity_id == contradiction_id_of("fc-a", "fc-b")

    def test_overlap_and_version_excluded_from_identity(self, db):
        a, b = _conflicting_pair(db)
        r1 = _record(db, a, b, detector_version="cx-detect-v1")
        r2 = _record(db, b, a, detector_version="cx-detect-v9")
        assert r1.entity_id == r2.entity_id
        assert r2.duplicate is True

    def test_different_pair_different_id(self, db):
        _insert_evidence(db)
        for cls in ("fc-a", "fc-b", "fc-c"):
            _insert_classification(db, cls_art=cls)
        _insert_classification(
            db, cls_art="fc-d", failure_class="IMPLEMENTATION_FAILURE")
        r1 = _record(db, "fc-a", "fc-d")
        r2 = _record(db, "fc-b", "fc-d")
        assert r1.entity_id != r2.entity_id

    def test_duplicate_replay_zero_effects(self, db):
        a, b = _conflicting_pair(db)
        r1 = _record(db, a, b)
        before = db.execute(
            "SELECT COUNT(*) c FROM events").fetchone()["c"]
        r2 = _record(db, a, b)
        r3 = _record(db, b, a)
        assert r2.duplicate is True and r3.duplicate is True
        assert r2.entity_id == r1.entity_id == r3.entity_id
        after = db.execute(
            "SELECT COUNT(*) c FROM events").fetchone()["c"]
        # Only the two IntentApplied audit rows for the replays.
        assert after - before == 2
        assert db.execute(
            "SELECT COUNT(*) c FROM contradictions").fetchone()["c"] == 1

    def test_separate_process_replay_duplicate(self, db):
        _ = _conflicting_pair(db)
        ctrl1 = _make(db)
        ctrl2 = Controller(db, project_id="p1", clock=frozen_clock(CLOCK))
        assert ctrl1.detect_contradictions()["recorded"] != []
        out = ctrl2.detect_contradictions()
        assert out["recorded"] == []
        assert out["duplicates"] == 1

    def test_contradictory_link_refused(self, db):
        a, b = _conflicting_pair(db)
        r1 = _record(db, a, b)
        # Same pair but a differing supersede link is contradictory
        # admission, not a duplicate.
        _insert_evidence(db, "art-e2", content_hash="evhash2")
        _insert_classification(db, cls_art="fc-c",
                               falsifying_refs=["evidence:evhash2"])
        _insert_classification(
            db, cls_art="fc-d", failure_class="IMPLEMENTATION_FAILURE",
            falsifying_refs=["evidence:evhash2"])
        r2 = _record(db, "fc-c", "fc-d", supersedes_ref=r1.entity_id)
        assert r2.duplicate is False
        with pytest.raises(GatewayRejection) as exc:
            _record(db, "fc-a", "fc-b", supersedes_ref=r2.entity_id)
        assert exc.value.code == PROPOSAL


# ═══════════════════════ state machine ═══════════════════════


class TestStateMachine:
    def _resolved(self, db):
        a, b = _conflicting_pair(db)
        r = _record(db, a, b)
        out = _resolve(db, r.entity_id)
        assert out["rejected"] is False
        return r.entity_id

    def test_open_to_resolved(self, db):
        cid = self._resolved(db)
        assert _status(db, cid) == "RESOLVED"
        ev = db.execute(
            "SELECT * FROM events WHERE event_type = ?",
            (EventType.CONTRADICTION_RESOLVED.value,)).fetchone()
        assert ev is not None

    def test_open_to_superseded(self, db):
        a, b = _conflicting_pair(db)
        r1 = _record(db, a, b)
        _insert_evidence(db, "art-e2", content_hash="evhash2")
        _insert_classification(db, cls_art="fc-c",
                               falsifying_refs=["evidence:evhash2"])
        _insert_classification(
            db, cls_art="fc-d", failure_class="IMPLEMENTATION_FAILURE",
            falsifying_refs=["evidence:evhash2"])
        r2 = _record(db, "fc-c", "fc-d", supersedes_ref=r1.entity_id)
        assert _status(db, r1.entity_id) == "SUPERSEDED"
        assert _status(db, r2.entity_id) == "OPEN"
        ev = db.execute(
            "SELECT * FROM events WHERE event_type = ?",
            (EventType.CONTRADICTION_SUPERSEDED.value,)).fetchone()
        assert ev is not None

    def test_resolved_never_reopens(self, db):
        cid = self._resolved(db)
        out = _resolve(db, cid)
        # Identical replay of the single verdict: idempotent, still RESOLVED.
        assert out["duplicate"] is True
        assert _status(db, cid) == "RESOLVED"

    def test_superseded_never_resolves(self, db):
        a, b = _conflicting_pair(db)
        r1 = _record(db, a, b)
        _insert_evidence(db, "art-e2", content_hash="evhash2")
        _insert_classification(db, cls_art="fc-c",
                               falsifying_refs=["evidence:evhash2"])
        _insert_classification(
            db, cls_art="fc-d", failure_class="IMPLEMENTATION_FAILURE",
            falsifying_refs=["evidence:evhash2"])
        _record(db, "fc-c", "fc-d", supersedes_ref=r1.entity_id)
        out = _resolve(db, r1.entity_id)
        assert out["rejected"] is True
        assert out["code"] == STALE
        assert _status(db, r1.entity_id) == "SUPERSEDED"

    def test_resolved_never_superseded(self, db):
        cid = self._resolved(db)
        _insert_evidence(db, "art-e2", content_hash="evhash2")
        _insert_classification(db, cls_art="fc-c",
                               falsifying_refs=["evidence:evhash2"])
        _insert_classification(
            db, cls_art="fc-d", failure_class="IMPLEMENTATION_FAILURE",
            falsifying_refs=["evidence:evhash2"])
        with pytest.raises(GatewayRejection) as exc:
            _record(db, "fc-c", "fc-d", supersedes_ref=cid)
        assert exc.value.code == STALE
        assert _status(db, cid) == "RESOLVED"

    def test_stale_target_refused(self, db):
        a, b = _conflicting_pair(db)
        r1 = _record(db, a, b)
        _insert_evidence(db, "art-e2", content_hash="evhash2")
        _insert_classification(db, cls_art="fc-c",
                               falsifying_refs=["evidence:evhash2"])
        _insert_classification(
            db, cls_art="fc-d", failure_class="IMPLEMENTATION_FAILURE",
            falsifying_refs=["evidence:evhash2"])
        _record(db, "fc-c", "fc-d", supersedes_ref=r1.entity_id)
        _insert_evidence(db, "art-e3", content_hash="evhash3")
        _insert_classification(db, cls_art="fc-e",
                               falsifying_refs=["evidence:evhash3"])
        _insert_classification(
            db, cls_art="fc-f", failure_class="IMPLEMENTATION_FAILURE",
            falsifying_refs=["evidence:evhash3"])
        # r1 is no longer the head (r2 superseded it).
        with pytest.raises(GatewayRejection) as exc:
            _record(db, "fc-e", "fc-f", supersedes_ref=r1.entity_id)
        assert exc.value.code == STALE

    def test_self_supersession_refused(self, db):
        a, b = _conflicting_pair(db)
        own = contradiction_id_of(a, b)
        # A record cannot name itself: on first admission the target does
        # not exist (PROPOSAL); once recorded, re-admission takes the
        # duplicate path. Self-supersession is unrepresentable.
        with pytest.raises(GatewayRejection) as exc:
            _record(db, a, b, supersedes_ref=own)
        assert exc.value.code == PROPOSAL

    def test_nonexistent_target_refused(self, db):
        a, b = _conflicting_pair(db)
        with pytest.raises(GatewayRejection) as exc:
            _record(db, a, b, supersedes_ref="cx-ghost")
        assert exc.value.code == PROPOSAL


# ═══════════════════════ authority ═══════════════════════


class TestAuthority:
    def test_llm_proposed_resolution_refused(self, db):
        a, b = _conflicting_pair(db)
        r = _record(db, a, b)
        for role in ("DIRECTOR", "RESEARCHER", "LLM"):
            with pytest.raises(GatewayRejection) as exc:
                apply_intent(db, Intent(
                    kind=IntentKind.CONTRADICTION_RESOLUTION,
                    proposed_by=role, project_id="p1",
                    justification="x",
                    payload={"contradiction_id": r.entity_id,
                             "human_decision_ref": "hd-x",
                             "operator_id": OP_ID}))
            assert exc.value.code == "ROLE"

    def test_llm_proposed_record_refused(self, db):
        a, b = _conflicting_pair(db)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.RECORD_CONTRADICTION,
                proposed_by="RESEARCHER", project_id="p1",
                justification="x",
                payload={"party_a": a, "party_b": b,
                         "detector_version": "v1", "supersedes_ref": ""}))
        assert exc.value.code == "ROLE"

    def test_unauthorized_resolution_refused(self, db):
        a, b = _conflicting_pair(db)
        r = _record(db, a, b)
        out = _resolve(db, r.entity_id, operator_id="bad-op")
        assert out["rejected"] is True
        assert out["code"] == "OPERATOR"
        assert _status(db, r.entity_id) == "OPEN"

    def test_lease_contention_refused(self, db):
        a, b = _conflicting_pair(db)
        r = _record(db, a, b)
        ctrl = _make(db)
        other = _make(db)
        assert other._acquire_lock() is True
        out = ctrl.record_contradiction_resolution(
            contradiction_id=r.entity_id,
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is True
        assert out["code"] == "LOCK"
        other._release_lock()
        out = ctrl.record_contradiction_resolution(
            contradiction_id=r.entity_id,
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is False

    def test_fabricated_decision_refused(self, db):
        a, b = _conflicting_pair(db)
        r = _record(db, a, b)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.CONTRADICTION_RESOLUTION,
                proposed_by="DETERMINISTIC", project_id="p1",
                justification="chg1 direct",
                payload={"contradiction_id": r.entity_id,
                         "human_decision_ref": "hd-ghost",
                         "operator_id": OP_ID}))
        assert exc.value.code == PROPOSAL


# ═══════════════════════ new evidence A–E ═══════════════════════


class TestNewEvidence:
    def _pair(self, db):
        return _conflicting_pair(db)

    def test_a_supports_party_a(self, db):
        a, b = self._pair(db)
        r = _record(db, a, b)
        _insert_evidence(db, "art-e2", content_hash="evhash2")
        out = _make(db).detect_contradictions()
        assert out["recorded"] == []  # duplicate-suppressed, row intact
        assert out["duplicates"] == 1
        assert _status(db, r.entity_id) == "OPEN"

    def test_b_supports_party_b(self, db):
        a, b = self._pair(db)
        r = _record(db, a, b)
        # New classification agreeing with B (same class): no new pair.
        _insert_evidence(db, "art-e2", content_hash="evhash2")
        _insert_classification(
            db, cls_art="fc-c", failure_class="IMPLEMENTATION_FAILURE",
            falsifying_refs=["evidence:evhash2"])
        out = _make(db).detect_contradictions()
        assert out["recorded"] == []
        assert _status(db, r.entity_id) == "OPEN"

    def test_c_undermines_both(self, db):
        a, b = self._pair(db)
        r = _record(db, a, b)
        # A third classification with a third class over the same
        # evidence creates NEW pairs; the original stays OPEN.
        _insert_classification(
            db, cls_art="fc-c", failure_class="ENVIRONMENT_MISMATCH")
        out = _make(db).detect_contradictions()
        assert len(out["recorded"]) == 2
        assert _status(db, r.entity_id) == "OPEN"

    def test_d_disappearance_supersedes(self, db):
        # Parties downstream of a retracted source: S5 supersedes the
        # OPEN contradiction in-transaction.
        _insert_artifact(db, "src-s", content_hash="shash1")
        _insert_artifact(db, "art-evx", artifact_type="evidence",
                         content_hash="evx")
        _insert_artifact(db, "fc-a", artifact_type="failure_classification",
                         content_hash="ch-a")
        self._meta(db, "fc-a", "DECLARED_CONSTRAINT_VIOLATION")
        _insert_artifact(db, "fc-b", artifact_type="failure_classification",
                         content_hash="ch-b")
        self._meta(db, "fc-b", "IMPLEMENTATION_FAILURE")
        db.execute(
            "INSERT INTO provenance_edges (artifact_id, upstream_id, "
            "edge_type, created_at) VALUES ('fc-a', 'src-s', 'cites', ?)",
            (CLOCK,))
        db.execute(
            "INSERT INTO provenance_edges (artifact_id, upstream_id, "
            "edge_type, created_at) VALUES ('fc-b', 'src-s', 'cites', ?)",
            (CLOCK,))
        r = _record(db, "fc-a", "fc-b")
        assert _status(db, r.entity_id) == "OPEN"
        _record_decision(db)
        apply_intent(db, Intent(
            kind=IntentKind.RETRACT_SOURCE, proposed_by="DETERMINISTIC",
            project_id="p1", justification="s5",
            payload={"source_ref": "src-s", "reason": "retracted",
                     "human_decision_ref": "hd-1"}))
        assert _status(db, r.entity_id) == "SUPERSEDED"
        ev = db.execute(
            "SELECT * FROM events WHERE event_type = ?",
            (EventType.CONTRADICTION_SUPERSEDED.value,)).fetchone()
        assert ev is not None

    @staticmethod
    def _meta(db, artifact_id, failure_class):
        from hermes.research.failure_classification import (
            ACTION_MAP,
            FailureClass,
        )
        meta = {
            "schema_version": "1", "failure_class": failure_class,
            "hypothesis_ref": "h1", "program_ref": "rp-1",
            "classification_id": artifact_id, "classifier_version": "1.0",
            "contributing_factors": [], "evidence_refs": ["evidence:evx"],
            "constraint_ref": "hypothesis:h1:falsification_condition",
            "failed_mechanism_ref": None, "regime_ref": None,
            "resource_gap": None, "scope_brief_ref": None,
            "scope_brief_field": None, "explanation": "d-test",
            "proposed_by": "DIRECTOR",
            "falsifying_evidence_refs": ["evidence:evx"],
            "permitted_actions": sorted(
                a.value for a in ACTION_MAP[FailureClass(failure_class)]),
        }
        from hermes.research.evidence_ladder import classification_content_hash as cch
        content_hash = cch(meta, "p1")
        db.execute(
            "UPDATE artifacts SET metadata_json = ?, content_hash = ? "
            "WHERE artifact_id = ?",
            (json.dumps(meta), content_hash, artifact_id))

    def test_e_new_contradiction_appears(self, db):
        a, b = self._pair(db)
        r1 = _record(db, a, b)
        _insert_evidence(db, "art-e2", content_hash="evhash2")
        _insert_classification(db, cls_art="fc-c",
                               falsifying_refs=["evidence:evhash2"])
        _insert_classification(
            db, cls_art="fc-d", failure_class="ENVIRONMENT_MISMATCH",
            falsifying_refs=["evidence:evhash2"])
        r2 = _record(db, "fc-c", "fc-d")
        assert r2.entity_id != r1.entity_id
        assert _status(db, r1.entity_id) == "OPEN"
        assert _status(db, r2.entity_id) == "OPEN"


# ═══════════════════════ N1 domain wall ═══════════════════════


class TestPartyDomainWall:
    """N1 closure: ONLY admitted classification artifacts can be
    contradiction parties. Resolution events, evidence artifacts,
    claims, and sources are structurally excludable — the detector
    consumes digest items alone, and the validator enforces
    artifact_type == failure_classification on both parties."""

    def test_resolution_event_cannot_be_party(self, db):
        a, b = _conflicting_pair(db)
        r = _record(db, a, b)
        _resolve(db, r.entity_id)
        # A resolution event is not an artifact row at all: naming
        # anything that is not a classification artifact fails.
        with pytest.raises(GatewayRejection):
            _record(db, a, "rd-ghost-decision")
        # Nor can the recorded verdict be smuggled in: the verdict
        # lives in the journal, outside the artifact domain entirely.
        rows = db.execute(
            "SELECT * FROM artifacts WHERE artifact_id LIKE 'rd-%'"
        ).fetchall()
        assert rows == []

    def test_evidence_artifact_cannot_be_party(self, db):
        _insert_evidence(db, "art-e1", content_hash="evhash1")
        _insert_evidence(db, "art-e2", content_hash="evhash2")
        with pytest.raises(GatewayRejection) as exc:
            _record(db, "art-e1", "art-e2")
        assert exc.value.code == EVIDENCE_REF

    def test_source_artifact_cannot_be_party(self, db):
        _insert_artifact(db, "src-1")
        _insert_artifact(db, "src-2")
        with pytest.raises(GatewayRejection) as exc:
            _record(db, "src-1", "src-2")
        assert exc.value.code == EVIDENCE_REF

    def test_prose_claim_cannot_be_party(self, db):
        db.execute(
            """INSERT INTO research_claims
               (claim_id, project_id, content_hash, statement, source_ref,
                schema_version, extracted_by, reason, created_at,
                context_tags_json)
               VALUES ('cl-9', 'p1', 'ch9', 'X causes Y',
                       'source_result:hh', '1', 't', NULL, ?, '{}')""",
            (CLOCK,))
        _insert_evidence(db)
        _insert_classification(db, cls_art="fc-a")
        # cl-9 exists as a claim row but has no artifact row: the
        # validator resolves parties in the artifact domain only.
        with pytest.raises(GatewayRejection) as exc:
            _record(db, "cl-9", "fc-a")
        assert exc.value.code == EVIDENCE_REF

    def test_later_conflict_independent_after_resolution(self, db):
        a, b = _conflicting_pair(db)
        r1 = _record(db, a, b)
        _resolve(db, r1.entity_id)
        _insert_evidence(db, "art-e2", content_hash="evhash2")
        _insert_classification(db, cls_art="fc-c",
                               falsifying_refs=["evidence:evhash2"])
        _insert_classification(
            db, cls_art="fc-d", failure_class="ENVIRONMENT_MISMATCH",
            falsifying_refs=["evidence:evhash2"])
        r2 = _record(db, "fc-c", "fc-d")
        assert r2.entity_id != r1.entity_id
        assert _status(db, r1.entity_id) == "RESOLVED"
        assert _status(db, r2.entity_id) == "OPEN"

    def test_detector_consumes_classifications_only(self, db):
        # Even with sources, claims, decisions, and evidence present,
        # the detector emits pairs of classification artifacts only.
        _insert_artifact(db, "src-x")
        _insert_evidence(db, "art-ex", content_hash="evhashx")
        a, b = _conflicting_pair(db)
        ctrl = _make(db)
        out = ctrl.detect_contradictions()
        assert out["recorded"] == [contradiction_id_of(a, b)]


# ═══════════════════════ reconstruction (issue #2) ═══════════════════════


class TestReconstruction:
    """Materialized-state proof: the journal + classification artifacts
    preserve complete lifecycle truth. Deleting contradiction rows
    destroys no research truth: re-detection reproduces identical IDs,
    and the journal still carries every lifecycle event."""

    def _lifecycle(self, db):
        a, b = _conflicting_pair(db)
        r1 = _record(db, a, b)
        _resolve(db, r1.entity_id)
        _insert_evidence(db, "art-e2", content_hash="evhash2")
        _insert_classification(db, cls_art="fc-c",
                               falsifying_refs=["evidence:evhash2"])
        _insert_classification(
            db, cls_art="fc-d", failure_class="IMPLEMENTATION_FAILURE",
            falsifying_refs=["evidence:evhash2"])
        # r1 is RESOLVED: supersede a fresh OPEN row instead.
        _insert_evidence(db, "art-e3", content_hash="evhash3")
        _insert_classification(db, cls_art="fc-e",
                               falsifying_refs=["evidence:evhash3"])
        _insert_classification(
            db, cls_art="fc-f", failure_class="RESOURCE_CONSTRAINT",
            falsifying_refs=["evidence:evhash3"])
        r3 = _record(db, "fc-e", "fc-f")
        _record(db, "fc-c", "fc-d", supersedes_ref=r3.entity_id)
        return r1.entity_id

    def test_delete_rows_loses_no_truth(self, db):
        r1 = self._lifecycle(db)
        # Journal preserves the complete lifecycle.
        detected = db.execute(
            "SELECT correlation_id FROM events WHERE event_type = ? "
            "ORDER BY event_id ASC",
            (EventType.CONTRADICTION_DETECTED.value,)).fetchall()
        # Journal order is admission order (not sorted) — the SET is
        # what reconstruction must reproduce.
        detected_ids = {r["correlation_id"] for r in detected}
        assert len(detected) == 3
        assert r1 in detected_ids
        resolved = db.execute(
            "SELECT correlation_id FROM events WHERE event_type = ?",
            (EventType.CONTRADICTION_RESOLVED.value,)).fetchall()
        assert len(resolved) == 1
        superseded = db.execute(
            "SELECT correlation_id FROM events WHERE event_type = ?",
            (EventType.CONTRADICTION_SUPERSEDED.value,)).fetchall()
        assert len(superseded) == 1
        # Destroy the materialized projection entirely.
        db.execute("DELETE FROM contradictions")
        assert db.execute(
            "SELECT COUNT(*) c FROM contradictions").fetchone()["c"] == 0
        # Underlying truth intact: classifications + evidence + markers.
        assert db.execute(
            "SELECT COUNT(*) c FROM artifacts "
            "WHERE artifact_type = 'failure_classification'"
        ).fetchone()["c"] == 6
        # Re-detection reproduces IDENTICAL identities.
        out = _make(db).detect_contradictions()
        assert sorted(out["recorded"]) == sorted(
            r["correlation_id"] for r in detected)
        # ...except resolved/superseded history, which lives in the
        # journal alone (re-detection re-records as OPEN — history is
        # audit, not living state; the events above remain the truth).
        for cid in out["recorded"]:
            assert _status(db, cid) == "OPEN"


class TestActiveReader:
    def test_open_listed_resolved_excluded(self, db):
        a, b = _conflicting_pair(db)
        r1 = _record(db, a, b)
        repo = ContradictionRepository(db)
        assert [r["contradiction_id"] for r in repo.open_contradictions(
            "p1")] == [r1.entity_id]
        _resolve(db, r1.entity_id)
        assert repo.open_contradictions("p1") == []

    def test_superseded_excluded(self, db):
        a, b = _conflicting_pair(db)
        r1 = _record(db, a, b)
        _insert_evidence(db, "art-e2", content_hash="evhash2")
        _insert_classification(db, cls_art="fc-c",
                               falsifying_refs=["evidence:evhash2"])
        _insert_classification(
            db, cls_art="fc-d", failure_class="IMPLEMENTATION_FAILURE",
            falsifying_refs=["evidence:evhash2"])
        _record(db, "fc-c", "fc-d", supersedes_ref=r1.entity_id)
        repo = ContradictionRepository(db)
        assert [r["contradiction_id"] for r in repo.open_contradictions(
            "p1")] != [r1.entity_id]
        assert r1.entity_id not in {
            r["contradiction_id"] for r in repo.open_contradictions("p1")}

    def test_invalidated_party_excluded(self, db):
        a, b = _conflicting_pair(db)
        r = _record(db, a, b)
        db.execute(
            "UPDATE artifacts SET metadata_json = ? WHERE artifact_id = ?",
            (json.dumps({"invalidation_marker": "INVALIDATED"}), a))
        repo = ContradictionRepository(db)
        assert repo.open_contradictions("p1") == []
        # Row itself is untouched (lazy rule — eager path is S5).
        assert _status(db, r.entity_id) == "OPEN"

    def test_cross_project_isolation(self, db):
        a, b = _conflicting_pair(db)
        r = _record(db, a, b)
        repo = ContradictionRepository(db)
        assert repo.open_contradictions("p2") == []
        assert repo.entry("p2", r.entity_id) is None
        entry = repo.entry("p1", r.entity_id)
        assert entry is not None
        assert entry["contradiction_id"] == r.entity_id

    def test_deterministic_ordering(self, db):
        _insert_evidence(db)
        for cls in ("fc-1", "fc-2"):
            _insert_classification(db, cls_art=cls)
        _insert_classification(
            db, cls_art="fc-3", failure_class="IMPLEMENTATION_FAILURE")
        _record(db, "fc-1", "fc-3")
        _record(db, "fc-2", "fc-3")
        repo = ContradictionRepository(db)
        ids = [r["contradiction_id"] for r in repo.open_contradictions("p1")]
        assert ids == sorted(ids)
        assert len(ids) == 2


class TestReReview:
    def test_contradiction_parties_surface(self, db):
        a, b = _conflicting_pair(db)
        ctrl = _make(db)
        before = ctrl.re_review_candidates(["no-such-seed"])
        assert before["items"] == []
        _record(db, a, b)
        after = ctrl.re_review_candidates(["no-such-seed"])
        # Radius is empty for a ghost seed, so parties surface only
        # through the contradiction-seed path when a radius exists...
        # with no radius the advisory stays empty (no scope creep).
        assert after["items"] == []

    def test_parties_join_existing_candidates(self, db):
        a, b = _conflicting_pair(db)
        _insert_artifact(db, "src-s", content_hash="shash9")
        _insert_artifact(db, "down-1")
        db.execute(
            "INSERT INTO provenance_edges (artifact_id, upstream_id, "
            "edge_type, created_at) VALUES ('down-1', 'src-s', 'cites', ?)",
            (CLOCK,))
        ctrl = _make(db)
        baseline = ctrl.re_review_candidates(["src-s"])
        base_ids = [i["artifact_id"] for i in baseline["items"]]
        _record(db, a, b)
        merged = ctrl.re_review_candidates(["src-s"])
        merged_ids = [i["artifact_id"] for i in merged["items"]]
        # Unrelated candidates keep identical entries and relative order.
        assert [i for i in merged_ids if i in base_ids] == base_ids
        for party in (a, b):
            matches = [i for i in merged["items"]
                       if i["artifact_id"] == party]
            assert len(matches) == 1
            assert matches[0]["reached_via"] == "contradiction"
        assert merged_ids == sorted(merged_ids)


def _insert_program(db, program_id="rp-1", project="p1"):
    db.execute(
        """INSERT INTO research_programs
           (program_id, project_id, version, content_hash, supersedes_id,
            scope_ref, epistemic_objective, compiler_version, policy_version,
            schema_version, input_hash, hypothesis_json, prediction_json,
            discrimination_json, evidence_json, gate_json, methodology_json,
            task_graph_template_ref, produced_by, reason, created_at)
           VALUES (?, ?, 1, ?, NULL, 'b', 'o', 'c1', 'p1', '1', 'ih', '[]',
                   '[]', '[]', '[]', '[]', '[]', NULL, 'director', NULL, ?)""",
        (program_id, project, "ch-" + program_id, CLOCK))


class TestHR08:
    def test_open_contradiction_denies_completion(self, db):
        from hermes.research.completion import can_complete_research
        _insert_program(db)
        _conflicting_pair(db)
        _record(db, "fc-a", "fc-b")
        result = can_complete_research(db, "p1")
        assert result.eligible is False
        codes = [d.code for d in result.denials]
        assert "OPEN_CONTRADICTION" in codes

    def test_unrelated_program_unaffected(self, db):
        from hermes.research.completion import can_complete_research
        _insert_program(db, program_id="rp-1", project="p1")
        _insert_program(db, program_id="rp-9", project="p2")
        _conflicting_pair(db)  # program rp-1, project p1
        _record(db, "fc-a", "fc-b")
        result = can_complete_research(db, "p2")
        codes = [d.code for d in result.denials]
        assert "OPEN_CONTRADICTION" not in codes

    def test_resolved_contradiction_clears_denial(self, db):
        from hermes.research.completion import can_complete_research
        _insert_program(db)
        _conflicting_pair(db)
        r = _record(db, "fc-a", "fc-b")
        _resolve(db, r.entity_id)
        result = can_complete_research(db, "p1")
        codes = [d.code for d in result.denials]
        assert "OPEN_CONTRADICTION" not in codes


# ═══════════════════════ failure / recovery ═══════════════════════


class TestFailure:
    def test_detector_crash_refusal_as_data(self, db):
        from unittest import mock
        _ = _conflicting_pair(db)
        ctrl = _make(db)
        with mock.patch(
                "hermes.research.contradictions."
                "detect_classification_conflicts",
                side_effect=RuntimeError("boom")):
            out = ctrl.detect_contradictions()
        assert out["rejected"] is True
        assert out["code"] == "DETECTOR"
        assert db.execute(
            "SELECT COUNT(*) c FROM contradictions").fetchone()["c"] == 0

    def test_malformed_detector_output_never_recorded(self, db):
        # Corrupt classification rows are skipped by candidate-row
        # derivation — the detector never sees them, nothing records.
        _insert_artifact(db, "fc-bad",
                         artifact_type="failure_classification",
                         meta={"not": "a classification"})
        out = _make(db).detect_contradictions()
        assert out["rejected"] is False
        assert out["recorded"] == []

    def test_journal_failure_rolls_back(self, db):
        from unittest import mock

        import hermes.research.gateway as gw

        a, b = _conflicting_pair(db)
        real_append = gw._append_event_to_db

        def failing(conn, clock, event_type, *a, **kw):
            if event_type == EventType.CONTRADICTION_DETECTED.value:
                raise RuntimeError("simulated storage failure")
            return real_append(conn, clock, event_type, *a, **kw)

        with mock.patch.object(gw, "_append_event_to_db", failing), \
                pytest.raises(RuntimeError):
            _record(db, a, b)
        assert db.execute(
            "SELECT COUNT(*) c FROM contradictions").fetchone()["c"] == 0
        assert db.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type = ?",
            (EventType.CONTRADICTION_DETECTED.value,)).fetchone()["c"] == 0
        assert real_append is gw._append_event_to_db

    def test_no_reopen_after_supersede(self, db):
        a, b = _conflicting_pair(db)
        r1 = _record(db, a, b)
        _insert_evidence(db, "art-e2", content_hash="evhash2")
        _insert_classification(db, cls_art="fc-c",
                               falsifying_refs=["evidence:evhash2"])
        _insert_classification(
            db, cls_art="fc-d", failure_class="IMPLEMENTATION_FAILURE",
            falsifying_refs=["evidence:evhash2"])
        _record(db, "fc-c", "fc-d", supersedes_ref=r1.entity_id)
        # Re-detection returns duplicate; status stays SUPERSEDED.
        _make(db).detect_contradictions()
        assert _status(db, r1.entity_id) == "SUPERSEDED"

    def test_lease_released_after_paths(self, db):
        _ = _conflicting_pair(db)
        ctrl = _make(db)
        ctrl.detect_contradictions()
        assert db.execute(
            "SELECT COUNT(*) c FROM scheduler_lock").fetchone()["c"] == 0
        ctrl.record_contradiction_resolution(
            contradiction_id="cx-ghost",
            operator_id="bad-op", operator_token="wrong")
        assert db.execute(
            "SELECT COUNT(*) c FROM scheduler_lock").fetchone()["c"] == 0


# ═══════════════════════ tick-loop wiring guard ═══════════════════════
#
# Regression pin for the gap flagged in the continuation audit:
# `detect_contradictions` existed and was green under tests, but had NO
# production caller inside `tick()`. This test drives the REAL `tick()`
# over digest-valid conflicting classifications and asserts the detector
# fires end-to-end through the reconcile loop — the surface the audit
# found unwired. The lock-less core must run on the tick's already-held
# lease (the public method would DELETE the tick's scheduler_lock row).


# ═══════════════════════ S5 regression guard ═══════════════════════




class TestTickWiring:
    """The detector has NO production caller inside tick(); this is the
    regression pin. Driving the real reconcile loop over a conflicting
    classification pair must record a CONTRADICTION_DETECTED event."""

    def test_tick_detects_conflict(self, db):
        a, b = _conflicting_pair(db)
        ctrl = _make(db)
        out = ctrl.tick()  # does not raise on a healthy tick
        # The contradiction was recorded end-to-end through the loop.
        ev = db.execute(
            "SELECT * FROM events WHERE event_type = ? ORDER BY event_id",
            (EventType.CONTRADICTION_DETECTED.value,)).fetchall()
        assert len(ev) == 1
        assert ev[0]["correlation_id"] == contradiction_id_of(a, b)
        assert _status(db, ev[0]["correlation_id"]) == "OPEN"
        # A healthy tick that found no dispatchable work idles cleanly, never
        # silently errors — and crucially never raises through the loop.
        assert out.idle in ("", "no_eligible", "mode:ACTIVE") or not out.dispatched


class TestS5Unchanged:
    def test_retract_without_contradictions(self, db):
        _record_decision(db)
        _insert_artifact(db, "src-a")
        _insert_artifact(db, "down-1")
        db.execute(
            "INSERT INTO provenance_edges (artifact_id, upstream_id, "
            "edge_type, created_at) VALUES ('down-1', 'src-a', 'cites', ?)",
            (CLOCK,))
        result = _retract(db)
        assert result.row["invalidated_artifacts"] == ["down-1"]
        assert db.execute(
            "SELECT COUNT(*) c FROM contradictions").fetchone()["c"] == 0


def _record_decision(db, ref="hd-1", project="p1"):
    _append_event_to_db(
        db, frozen_clock(CLOCK),
        EventType.HUMAN_DECISION_RECEIVED.value,
        project_id=project, correlation_id=ref, caused_by="operator",
        reason="operator decision", payload={"decision": "RETRACT"})
