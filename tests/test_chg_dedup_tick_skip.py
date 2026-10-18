"""CHG-DEDUP-1 — the P1-9 upstream skip: already-recorded contradiction
pairs are never resubmitted by the controller's detector pass.

``_detect_contradictions_pass`` consults the project's recorded
contradictions (read-only; pair identity recomputed, never trusted;
any-row status predicate) before building an intent, so a stable
recorded pair no longer appends one duplicate ``IntentApplied`` audit
row per ACTIVE tick. Pins:

- multi-tick: stable classifications record once; further ticks add
  zero journal rows (the item's missing exit check);
- a recorded OPEN pair is skipped while a genuinely new pair is still
  recorded; RESOLVED and SUPERSEDED rows are skipped too (any-row is
  exact: the gateway duplicate path is status-blind and no un-retract
  exists);
- the journal stays append-only (no row deleted, appended or
  rewritten by repeated passes) and the gateway is untouched — a
  direct replay still returns ``duplicate=True`` and still appends its
  ``IntentApplied`` row (suppressing those is prohibited);
- HR8-1 interplay: a fresh conflict still denies completion, exactly
  once, before and after the recording pass;
- project scoping and the recompute-never-trust identity discipline.
"""
from __future__ import annotations

import hashlib
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
from hermes.research.completion import (
    OPEN_CONTRADICTION,
    can_complete_research,
)
from hermes.research.contradictions import (
    CONTRADICTION_DETECTOR_VERSION,
    contradiction_id_of,
)
from hermes.research.controller import Controller
from hermes.research.evidence_ladder import classification_content_hash
from hermes.research.gateway import apply_intent

CLOCK = "2026-01-01T00:00:00.000000+00:00"
OP_ID = "op-1"
OP_TOKEN = "op-token-1"


# ═══════════════════════ fixtures / helpers ═══════════════════════


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
                     content_hash=None, project="p1", meta=None):
    db.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type,
            content_hash, size_bytes, storage_path, producer,
            metadata_json, created_at)
           VALUES (?, ?, NULL, ?, ?, 1, 'x', 't', ?, ?)""",
        (artifact_id, project, artifact_type,
         content_hash or f"ch-{artifact_id}",
         json.dumps(meta) if meta is not None else None, CLOCK))


def _insert_evidence(db, artifact_id="art-ev1", *, content_hash="evhash1"):
    _insert_artifact(db, artifact_id, artifact_type="evidence",
                     content_hash=content_hash)


def _insert_classification(db, *, cls_art, failure_class, evidence_hash):
    from hermes.research.failure_classification import (
        ACTION_MAP,
        FailureClass,
    )
    permitted = sorted(
        a.value for a in ACTION_MAP[FailureClass(failure_class)])
    meta = {
        "schema_version": "1",
        "failure_class": failure_class,
        "hypothesis_ref": "h1",
        "program_ref": "rp-1",
        "classification_id": cls_art,
        "classifier_version": "1.0",
        "contributing_factors": [],
        "evidence_refs": [f"evidence:{evidence_hash}"],
        "constraint_ref": "hypothesis:h1:falsification_condition",
        "failed_mechanism_ref": None,
        "regime_ref": None,
        "resource_gap": None,
        "scope_brief_ref": None,
        "scope_brief_field": None,
        "explanation": f"chg-dedup test {cls_art}",
        "proposed_by": "DIRECTOR",
        "falsifying_evidence_refs": [f"evidence:{evidence_hash}"],
        "permitted_actions": permitted,
    }
    content_hash = classification_content_hash(meta, "p1")
    _insert_artifact(db, cls_art, artifact_type="failure_classification",
                     content_hash=content_hash, meta=meta)
    return cls_art


def _conflicting_pair(db, *, evidence_hash="evhash1", evidence_id="art-ev1",
                      cls_a="fc-a", cls_b="fc-b"):
    """Two digest-valid classifications, same target, different classes,
    sharing one evidence artifact. Returns (id_a, id_b)."""
    _insert_evidence(db, evidence_id, content_hash=evidence_hash)
    _insert_classification(
        db, cls_art=cls_a, evidence_hash=evidence_hash,
        failure_class="DECLARED_CONSTRAINT_VIOLATION")
    _insert_classification(
        db, cls_art=cls_b, evidence_hash=evidence_hash,
        failure_class="IMPLEMENTATION_FAILURE")
    return cls_a, cls_b


def _record(db, party_a, party_b, *, supersedes_ref="", project="p1"):
    return apply_intent(db, Intent(
        kind=IntentKind.RECORD_CONTRADICTION, proposed_by="DETERMINISTIC",
        project_id=project, justification="chg-dedup test",
        payload={"party_a": party_a, "party_b": party_b,
                 "detector_version": CONTRADICTION_DETECTOR_VERSION,
                 "supersedes_ref": supersedes_ref}))


def _resolve(db, contradiction_id, *, project="p1") -> dict:
    return _make(db, project=project).record_contradiction_resolution(
        contradiction_id=contradiction_id,
        operator_id=OP_ID, operator_token=OP_TOKEN)


def _status(db, contradiction_id):
    row = db.execute(
        "SELECT status FROM contradictions WHERE contradiction_id = ?",
        (contradiction_id,)).fetchone()
    return row["status"] if row else None


def _events(db):
    """Full ordered event rows — an append-only fingerprint: equal
    snapshots prove no row was appended, deleted, or rewritten."""
    return [tuple(r) for r in db.execute(
        "SELECT * FROM events ORDER BY event_id").fetchall()]


def _count(db, table):
    return db.execute(f"SELECT COUNT(*) n FROM {table}").fetchone()["n"]


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


def _record_decision(db, ref="hd-1", project="p1", *, source_ref="src-a",
                     reason="source retracted by publisher"):
    """Record the retraction decision bound to its command
    (RETRACT-1/P0-3): kind + source + reason digest."""
    _append_event_to_db(
        db, frozen_clock(CLOCK),
        EventType.HUMAN_DECISION_RECEIVED.value,
        project_id=project, correlation_id=ref, caused_by="operator",
        reason="operator decision",
        payload={"decision": "RETRACT_SOURCE", "source_ref": source_ref,
                 "reason_digest": hashlib.sha256(
                     reason.encode("utf-8")).hexdigest()})


def _retire_pair_via_retraction(db):
    """fc-a/fc-b both cite ``src-s``; retract it. Returns the recorded
    contradiction result (its row must be SUPERSEDED in-transaction)."""
    from hermes.research.failure_classification import (
        ACTION_MAP,
        FailureClass,
    )
    _insert_artifact(db, "src-s", content_hash="shash1")
    _insert_artifact(db, "art-evx", artifact_type="evidence",
                     content_hash="evx")
    for cls_art, failure_class in (
            ("fc-a", "DECLARED_CONSTRAINT_VIOLATION"),
            ("fc-b", "IMPLEMENTATION_FAILURE")):
        meta = {
            "schema_version": "1", "failure_class": failure_class,
            "hypothesis_ref": "h1", "program_ref": "rp-1",
            "classification_id": cls_art, "classifier_version": "1.0",
            "contributing_factors": [], "evidence_refs": ["evidence:evx"],
            "constraint_ref": "hypothesis:h1:falsification_condition",
            "failed_mechanism_ref": None, "regime_ref": None,
            "resource_gap": None, "scope_brief_ref": None,
            "scope_brief_field": None, "explanation": "chg-dedup retract",
            "proposed_by": "DIRECTOR",
            "falsifying_evidence_refs": ["evidence:evx"],
            "permitted_actions": sorted(
                a.value for a in ACTION_MAP[FailureClass(failure_class)]),
        }
        content_hash = classification_content_hash(meta, "p1")
        _insert_artifact(db, cls_art, artifact_type="failure_classification",
                         content_hash=content_hash, meta=meta)
        db.execute(
            "INSERT INTO provenance_edges (artifact_id, upstream_id, "
            "edge_type, created_at) VALUES (?, 'src-s', 'cites', ?)",
            (cls_art, CLOCK))
    recorded = _record(db, "fc-a", "fc-b")
    assert _status(db, recorded.entity_id) == "OPEN"
    _record_decision(db, source_ref="src-s", reason="retracted")
    apply_intent(db, Intent(
        kind=IntentKind.RETRACT_SOURCE, proposed_by="DETERMINISTIC",
        project_id="p1", justification="chg-dedup test",
        payload={"source_ref": "src-s", "reason": "retracted",
                 "human_decision_ref": "hd-1"}))
    assert _status(db, recorded.entity_id) == "SUPERSEDED"
    return recorded


def _open_denials(eligibility):
    return [d for d in eligibility.denials if d.code == OPEN_CONTRADICTION]


# ═══════════════════════ the exit check: multi-tick growth ═══════════════════════


class TestMultiTickGrowth:
    def test_stable_pair_records_once_then_zero_journal_growth(self, db):
        """Stable classifications over N ACTIVE ticks: the pair is
        recorded on the first tick; every further tick appends no
        journal row (the P1-9 unbounded-growth exit check)."""
        _conflicting_pair(db)
        ctrl = _make(db)
        ctrl.tick()
        first = _events(db)
        assert _count(db, "contradictions") == 1
        detected = [e for e in first
                    if e[1] == EventType.CONTRADICTION_DETECTED.value]
        assert len(detected) == 1
        for _ in range(4):
            ctrl.tick()
        assert _events(db) == first
        assert _count(db, "contradictions") == 1

    def test_recorded_open_pair_skipped_new_pair_still_recorded(self, db):
        """An already-recorded OPEN pair is not resubmitted (no audit
        row), while a genuinely new pair still records in the same
        pass — the skip is incremental, not a pass abort."""
        _conflicting_pair(db)                     # fc-a/fc-b over evhash1
        _insert_evidence(db, "art-ev2", content_hash="evhash2")
        _insert_classification(
            db, cls_art="fc-c", evidence_hash="evhash2",
            failure_class="DECLARED_CONSTRAINT_VIOLATION")
        _insert_classification(
            db, cls_art="fc-d", evidence_hash="evhash2",
            failure_class="IMPLEMENTATION_FAILURE")
        _record(db, "fc-a", "fc-b")
        before = _events(db)
        out = _make(db).detect_contradictions()
        assert out["rejected"] is False
        assert out["recorded"] == [contradiction_id_of("fc-c", "fc-d")]
        assert out["duplicates"] == 1
        assert out["refused"] == []
        delta = [e[1] for e in _events(db)[len(before):]]
        # Exactly the new pair's record + its audit row: nothing for
        # the already-recorded pair.
        assert delta == [EventType.CONTRADICTION_DETECTED.value,
                         EventType.INTENT_APPLIED.value]
        assert _status(db, contradiction_id_of("fc-a", "fc-b")) == "OPEN"


# ═══════════════════════ status semantics ═══════════════════════


class TestStatusPredicate:
    def test_resolved_pair_not_resubmitted(self, db):
        _conflicting_pair(db)
        r = _record(db, "fc-a", "fc-b")
        assert _resolve(db, r.entity_id)["rejected"] is False
        before = _events(db)
        out = _make(db).detect_contradictions()
        assert out["recorded"] == []
        assert out["duplicates"] == 1
        assert _events(db) == before
        assert _status(db, r.entity_id) == "RESOLVED"

    def test_superseded_pair_stays_skipped(self, db):
        """Any-row predicate: a SUPERSEDED row still suppresses the
        pair. The pair remains N1-eligible here (parties valid), so a
        non-SUPERSEDED predicate would resubmit it every tick — the
        exact growth this slice removes. SUPERSEDED is terminal: no
        un-retract exists, so re-recording is never legitimate."""
        _conflicting_pair(db)
        r1 = _record(db, "fc-a", "fc-b")
        _insert_evidence(db, "art-ev2", content_hash="evhash2")
        _insert_classification(
            db, cls_art="fc-c", evidence_hash="evhash2",
            failure_class="DECLARED_CONSTRAINT_VIOLATION")
        _insert_classification(
            db, cls_art="fc-d", evidence_hash="evhash2",
            failure_class="IMPLEMENTATION_FAILURE")
        r2 = _record(db, "fc-c", "fc-d", supersedes_ref=r1.entity_id)
        assert _status(db, r1.entity_id) == "SUPERSEDED"
        assert _status(db, r2.entity_id) == "OPEN"
        before = _events(db)
        out = _make(db).detect_contradictions()
        assert out["recorded"] == []
        assert out["duplicates"] == 2
        assert _events(db) == before
        assert _status(db, r1.entity_id) == "SUPERSEDED"

    def test_retraction_superseded_pair_not_redetected(self, db):
        """Retraction-driven supersession: the S5 follow-on retires the
        OPEN row and invalidates the parties in the same transaction;
        a later pass neither re-detects nor resubmits (and the row is
        never reopened)."""
        r = _retire_pair_via_retraction(db)
        before = _events(db)
        out = _make(db).detect_contradictions()
        assert out["recorded"] == []
        assert out["duplicates"] == 0
        assert out["refused"] == []
        assert _events(db) == before
        assert _status(db, r.entity_id) == "SUPERSEDED"


# ═══════════════════════ append-only / gateway untouched ═══════════════════════


class TestAppendOnly:
    def test_repeated_passes_append_delete_rewrite_nothing(self, db):
        _conflicting_pair(db)
        ctrl = _make(db)
        ctrl.detect_contradictions()
        events_before = _events(db)
        rows_before = [tuple(r) for r in db.execute(
            "SELECT * FROM contradictions ORDER BY contradiction_id"
        ).fetchall()]
        for _ in range(3):
            ctrl.detect_contradictions()
        assert _events(db) == events_before
        assert [tuple(r) for r in db.execute(
            "SELECT * FROM contradictions ORDER BY contradiction_id"
        ).fetchall()] == rows_before

    def test_direct_replay_still_appends_audit_row(self, db):
        """The gateway duplicate path is untouched: a direct
        resubmission still returns duplicate=True and still appends its
        IntentApplied row (suppressing those is prohibited; only the
        controller skips upstream)."""
        _conflicting_pair(db)
        r1 = _record(db, "fc-a", "fc-b")
        before = _events(db)
        r2 = _record(db, "fc-a", "fc-b")
        assert r2.duplicate is True
        assert r2.entity_id == r1.entity_id
        delta = [e[1] for e in _events(db)[len(before):]]
        assert delta == [EventType.INTENT_APPLIED.value]
        assert _count(db, "contradictions") == 1


# ═══════════════════════ HR8-1 interplay ═══════════════════════


class TestHR8Interplay:
    def test_fresh_conflict_still_denies_completion_exactly_once(self, db):
        _insert_program(db)
        _conflicting_pair(db)
        cid = contradiction_id_of("fc-a", "fc-b")

        # Blind window (HR8-1): a fresh, never-recorded conflict denies.
        fresh = can_complete_research(db, "p1")
        assert fresh.eligible is False
        assert [d.subject for d in _open_denials(fresh)] == [cid]

        # The recording pass records it; the denial stands, once.
        ctrl = _make(db)
        out = ctrl.detect_contradictions()
        assert out["recorded"] == [cid]
        recorded_verdict = can_complete_research(db, "p1")
        assert recorded_verdict.eligible is False
        assert [d.subject for d in _open_denials(recorded_verdict)] == [cid]

        # A skipped pass changes nothing: no growth, still one denial.
        before = _events(db)
        skipped = ctrl.detect_contradictions()
        assert skipped["recorded"] == []
        assert skipped["duplicates"] == 1
        assert _events(db) == before
        after = can_complete_research(db, "p1")
        assert after.eligible is False
        assert [d.subject for d in _open_denials(after)] == [cid]


# ═══════════════════════ identity discipline / scoping ═══════════════════════


class TestSkipIdentity:
    def test_project_scoped_and_recomputed_never_trusted(self, db):
        # Lazy import: this module must collect on base (fail-on-base
        # behavioural pins); only this helper-shaped test needs the
        # CHG-DEDUP-1 seam itself.
        from hermes.research.contradiction_candidates import (
            recorded_pair_keys,
        )

        a, b = _conflicting_pair(db)
        _record(db, a, b)
        cid = contradiction_id_of(a, b)
        assert recorded_pair_keys(db, "p1") == {cid}
        assert recorded_pair_keys(db, "p2") == set()

        # Tamper probe: the skip identity is recomputed from the
        # stored parties, never read from the stored column — the
        # helper still reports the pair under its recomputed key.
        db.execute(
            "UPDATE contradictions SET contradiction_id = 'cx-tampered' "
            "WHERE contradiction_id = ?", (cid,))
        assert recorded_pair_keys(db, "p1") == {cid}

        # And the pass still skips the recorded pair.
        before = _events(db)
        out = _make(db).detect_contradictions()
        assert out["recorded"] == []
        assert out["duplicates"] == 1
        assert _events(db) == before
