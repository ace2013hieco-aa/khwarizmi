"""HR8-1 — the HR-08 completion blind window (P1-10 closure pins).

``can_complete_research`` re-derives the conflict set at read time:
stored OPEN contradiction rows PLUS the pure production detector
re-run over the current digest-valid classification rows, so a
conflict admitted after the last detector pass cannot be invisible.

These pins FAIL on the pre-fix predicate (stored-rows-only: a fresh
conflict silently completes) and PASS on the fix:

- a fresh, never-recorded conflict denies completion (predicate and
  write path);
- a recomputed-but-RESOLVED pair does not re-block (the naive
  recompute breaks this);
- a SUPERSEDED pair does not re-block and an INVALIDATED party is
  excluded from the recomputed set;
- stored OPEN rows keep blocking with exactly one denial (the
  recompute never double-counts);
- a fresh conflict foreign to the head program does not deny it;
- repeated checks return an identical, side-effect-free verdict.
"""
from __future__ import annotations

import json

import pytest

from hermes.core import frozen_clock
from hermes.core.intents import Intent, IntentKind
from hermes.core.lifecycle import LifecycleState, TransitionError
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    OperatorCredentialRepository,
    ProjectRepository,
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

# The full lifecycle walk to REPORTING (v4 §6.1 happy path).
_WALK_TO_REPORTING = (
    LifecycleState.SCOPING,
    LifecycleState.LITERATURE_REVIEW,
    LifecycleState.HYPOTHESIS_FORMULATION,
    LifecycleState.EXPERIMENT_DESIGN,
    LifecycleState.DATA_ACQUISITION,
    LifecycleState.DATA_VALIDATION,
    LifecycleState.IMPLEMENTATION,
    LifecycleState.EXPERIMENTATION,
    LifecycleState.ANALYSIS,
    LifecycleState.VALIDATION,
    LifecycleState.ADVERSARIAL_REVIEW,
    LifecycleState.REPLICATION,
    LifecycleState.REPORTING,
)


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, frozen_clock(CLOCK)).create("p1", "Test")
    OperatorCredentialRepository(conn, frozen_clock(CLOCK)).register(
        OP_ID, OP_TOKEN, "Test Operator")
    yield conn
    conn.close()


def _insert_artifact(db, artifact_id, *, artifact_type="source_result",
                     content_hash=None, meta=None):
    db.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type,
            content_hash, size_bytes, storage_path, producer,
            metadata_json, created_at)
           VALUES (?, 'p1', NULL, ?, ?, 1, 'x', 't', ?, ?)""",
        (artifact_id, artifact_type, content_hash or f"ch-{artifact_id}",
         json.dumps(meta) if meta is not None else None, CLOCK))


def _insert_evidence(db, artifact_id="art-ev1", *, content_hash="evhash1"):
    _insert_artifact(db, artifact_id, artifact_type="evidence",
                     content_hash=content_hash)


def _insert_classification(db, *, cls_art,
                           failure_class="DECLARED_CONSTRAINT_VIOLATION",
                           evidence_hash="evhash1", invalidated=False):
    """A digest-valid classification artifact (the chg1 test shape)."""
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
        "explanation": f"hr8 blind-window test {cls_art}",
        "proposed_by": "DIRECTOR",
        "falsifying_evidence_refs": [f"evidence:{evidence_hash}"],
        "permitted_actions": permitted,
    }
    if invalidated:
        meta["invalidation_marker"] = "INVALIDATED"
    content_hash = classification_content_hash(meta, "p1")
    _insert_artifact(db, cls_art, artifact_type="failure_classification",
                     content_hash=content_hash, meta=meta)
    return cls_art


def _conflicting_pair(db, *, evidence_hash="evhash1",
                      evidence_id="art-ev1", cls_a="fc-a", cls_b="fc-b"):
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


def _insert_program(db, program_id="rp-1", version=1):
    db.execute(
        """INSERT INTO research_programs
           (program_id, project_id, version, content_hash, supersedes_id,
            scope_ref, epistemic_objective, compiler_version, policy_version,
            schema_version, input_hash, hypothesis_json, prediction_json,
            discrimination_json, evidence_json, gate_json, methodology_json,
            task_graph_template_ref, produced_by, reason, created_at)
           VALUES (?, 'p1', ?, ?, NULL, 'b', 'o', 'c1', 'p1', '1', 'ih',
                   '[]', '[]', '[]', '[]', '[]', '[]', NULL, 'director',
                   NULL, ?)""",
        (program_id, version, "ch-" + program_id, CLOCK))


def _record(db, party_a, party_b, *, supersedes_ref=""):
    return apply_intent(db, Intent(
        kind=IntentKind.RECORD_CONTRADICTION, proposed_by="DETERMINISTIC",
        project_id="p1", justification="hr8 blind-window test",
        payload={"party_a": party_a, "party_b": party_b,
                 "detector_version": CONTRADICTION_DETECTOR_VERSION,
                 "supersedes_ref": supersedes_ref}))


def _resolve(db, contradiction_id) -> dict:
    return Controller(db, project_id="p1", clock=frozen_clock(CLOCK)) \
        .record_contradiction_resolution(
            contradiction_id=contradiction_id,
            operator_id=OP_ID, operator_token=OP_TOKEN)


def _status(db, contradiction_id):
    row = db.execute(
        "SELECT status FROM contradictions WHERE contradiction_id = ?",
        (contradiction_id,)).fetchone()
    return row["status"] if row else None


def _open_denials(eligibility):
    return [d for d in eligibility.denials if d.code == OPEN_CONTRADICTION]


def _fresh_pairs(db, project_id="p1"):
    """The production detector derivation, called directly — proves a
    scenario is exactly the 'fresh candidate rows' shape."""
    from hermes.persistence.failure_classifications import (
        FailureClassificationRepository,
        classifications_digest,
    )
    from hermes.research.contradiction_candidates import (
        detector_candidate_rows,
    )
    from hermes.research.contradictions import (
        detect_classification_conflicts,
    )
    digest = classifications_digest(
        FailureClassificationRepository(db).classifications_for_project(
            project_id))
    rows = detector_candidate_rows(db, project_id, digest.get("items", []))
    return detect_classification_conflicts(rows)


def _walk_to_reporting(db):
    repo = ProjectRepository(db, clock=frozen_clock(CLOCK))
    for state in _WALK_TO_REPORTING:
        repo.transition_lifecycle("p1", state, caused_by="test")
    assert repo.get_lifecycle("p1") == LifecycleState.REPORTING
    return repo


# ── the blind window is closed: a conflict admitted after the last
#    detector pass denies completion (predicate + write path) ──


def test_fresh_conflict_denies_completion(db):
    _insert_program(db)
    _conflicting_pair(db)
    cid = contradiction_id_of("fc-a", "fc-b")
    assert db.execute(
        "SELECT COUNT(*) n FROM contradictions").fetchone()["n"] == 0

    result = can_complete_research(db, "p1")
    assert result.eligible is False
    denials = _open_denials(result)
    assert [d.subject for d in denials] == [cid]


def test_fresh_conflict_denies_the_write_path(db):
    _insert_program(db)
    _conflicting_pair(db)
    repo = _walk_to_reporting(db)
    events_before = db.execute(
        "SELECT COUNT(*) n FROM events").fetchone()["n"]

    with pytest.raises(TransitionError) as exc:
        repo.transition_lifecycle("p1", LifecycleState.COMPLETED)
    assert "HR-08" in str(exc.value)
    assert "OPEN_CONTRADICTION" in str(exc.value)
    assert repo.get_lifecycle("p1") == LifecycleState.REPORTING
    assert db.execute(
        "SELECT COUNT(*) n FROM events").fetchone()["n"] == events_before


# ── the naive recompute trap: a resolved pair stays non-blocking ──


def test_resolved_pair_does_not_reblock(db):
    _insert_program(db)
    _conflicting_pair(db)
    r = _record(db, "fc-a", "fc-b")
    _resolve(db, r.entity_id)
    assert _status(db, r.entity_id) == "RESOLVED"

    # The pair still matches the N1 rule (resolution touches no party):
    # this is exactly what a naive recompute would re-block on.
    assert [p["contradiction_id"] for p in _fresh_pairs(db)] == [
        r.entity_id]

    result = can_complete_research(db, "p1")
    assert result.eligible is True
    assert _open_denials(result) == []


def test_superseded_pair_does_not_reblock(db):
    _insert_program(db)
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
    _resolve(db, r2.entity_id)
    assert _status(db, r1.entity_id) == "SUPERSEDED"
    assert _status(db, r2.entity_id) == "RESOLVED"

    # Both pairs are still N1-eligible over the current rows.
    assert {p["contradiction_id"] for p in _fresh_pairs(db)} == {
        r1.entity_id, r2.entity_id}

    result = can_complete_research(db, "p1")
    assert result.eligible is True
    assert _open_denials(result) == []


def test_invalidated_party_excluded_from_fresh_set(db):
    _insert_program(db)
    _insert_evidence(db)
    _insert_classification(
        db, cls_art="fc-a",
        failure_class="DECLARED_CONSTRAINT_VIOLATION")
    _insert_classification(
        db, cls_art="fc-b", failure_class="IMPLEMENTATION_FAILURE",
        invalidated=True)
    assert _fresh_pairs(db) == []

    result = can_complete_research(db, "p1")
    assert result.eligible is True
    assert _open_denials(result) == []


# ── stored semantics unchanged: OPEN rows block, once ──


def test_stored_open_row_blocks_exactly_once(db):
    _insert_program(db)
    _conflicting_pair(db)
    r = _record(db, "fc-a", "fc-b")

    result = can_complete_research(db, "p1")
    assert result.eligible is False
    denials = _open_denials(result)
    assert [d.subject for d in denials] == [r.entity_id]


def test_fresh_conflict_foreign_to_head_program_unaffected(db):
    _insert_program(db, program_id="rp-2", version=2)
    _conflicting_pair(db)          # classifications name rp-1
    assert len(_fresh_pairs(db)) == 1

    result = can_complete_research(db, "p1")
    assert result.eligible is True
    assert _open_denials(result) == []


# ── idempotence: repeated checks, identical side-effect-free verdict ──


def test_repeated_checks_identical_side_effect_free_verdict(db):
    _insert_program(db)
    _conflicting_pair(db)
    cid = contradiction_id_of("fc-a", "fc-b")

    def _snapshot():
        return {t: db.execute(
            f"SELECT COUNT(*) n FROM {t}").fetchone()["n"]
            for t in ("contradictions", "artifacts", "events",
                      "research_programs")}

    before = _snapshot()
    first = can_complete_research(db, "p1")
    second = can_complete_research(db, "p1")
    after = _snapshot()

    assert first == second               # identical structured verdict
    assert first.eligible is False
    assert [d.subject for d in _open_denials(first)] == [cid]
    assert before == after               # read-only: no side effects

    # Once the next detector pass records the row, the verdict stands.
    out = Controller(db, project_id="p1", clock=frozen_clock(CLOCK)) \
        .detect_contradictions()
    assert out["rejected"] is False
    assert out["recorded"] == [cid]
    third = can_complete_research(db, "p1")
    assert third.eligible is False
    assert [d.subject for d in _open_denials(third)] == [cid]
