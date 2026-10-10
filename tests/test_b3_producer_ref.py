"""R-2 B3 producer ref: admissions carry the shared source-artifact ref.

P-AUTO-5-FIX residual N5 (B3 PARTIAL, declared scope): the vault projector's
validity predicate could not match a bare ``SourceRetracted`` to a
``CuratedKnowledgeAdmitted``, because the admission's journal row carried no
shared artifact ref — the matched refs lived only in the registry table
``curated_knowledge_retraction_basis``, invisible to a journal-only derived
view. The producer now emits those refs in ``artifact_ids_json``
(ADDITIVE: every admission payload key and value is unchanged), so the
journal alone suffices to retire the admission when its evidence source is
retracted — by either retraction producer (the gateway S5 cascade and the
bare ``Controller.record_source_retraction`` audit event).

Journal-level contract: every emitted admission carries resolvable,
in-project shared refs equal to the stored retraction basis, and a later
retraction names the same ``artifact:`` namespace key. Derived-view
consequence: the projected admission note moves out of the authoritative
graph with a supersede link.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes.core import frozen_clock
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    ProjectRepository,
    _append_event_to_db,
)
from hermes.research.controller import Controller
from hermes.research.feature_binding import (
    FEATURE_BINDING_ARTIFACT_TYPE,
    FEATURE_BINDING_REF_PREFIX,
    signature_from_binding,
)
from hermes.research.gateway import apply_intent  # noqa: F401  (harness use)
from hermes.vault.projection import (
    _row_subject_keys,
    note_filename,
    project,
)
from tests.test_step7_curated_registry import (
    CLOCK,
    _hyp,
    _record_s5_human_decision,
    _retract,
    curate,
    insert_artifact,
    insert_binding,
    insert_classification,
    insert_ladder_refuted,
    insert_program,
    insert_transition_event,
)

# The chartered admission payload (gateway.py step 5) — the ADDITIVE-ONLY
# contract pins this set: the shared refs ride artifact_ids_json instead.
ADMISSION_PAYLOAD_KEYS = frozenset({
    "admission_decision_ref", "curated_id", "evidence_basis",
    "hypothesis_ref", "kind", "operation", "operator_id", "program_ref",
    "signature_json", "source_binding_ref", "source_decision_event_ref",
    "supersedes_ref",
})

SOURCE_ARTIFACT_TYPES = frozenset(
    {"source_result", "source_payload", "source_search"})


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, frozen_clock(CLOCK)).create("p1", "Test")
    yield conn
    conn.close()


def _admit(db, *, source_count=1):
    """The production CURATE_KNOWLEDGE path with source_result evidence.

    ``source_count`` basis members (source_result artifacts), so the test can
    assert every member is carried, not just a single one.
    """
    insert_program(db, "rp-1", hypotheses=[_hyp("h1")])
    refs = []
    for index in range(source_count):
        artifact_id = f"art-src{index + 1}"
        content_hash = f"srchash{index + 1}"
        insert_artifact(db, artifact_id, "source_result",
                        content_hash=content_hash)
        refs.append(f"source_result:{content_hash}")
    cls_ref = insert_classification(db, falsifying_refs=refs)
    insert_ladder_refuted(db)
    insert_transition_event(db, classification_ref=cls_ref)
    binding_ref = insert_binding(db)
    binding_meta = json.loads(db.execute(
        "SELECT metadata_json FROM artifacts WHERE artifact_id = 'art-fb1'"
    ).fetchone()["metadata_json"])
    seed = {"program_id": "rp-1", "hypothesis_ref": "h1",
            "binding_ref": binding_ref,
            "signature_json": signature_from_binding(binding_meta),
            "evidence_id": "art-src1", "evidence_hash": "srchash1",
            "evidence_ids": [f"art-src{i + 1}" for i in range(source_count)]}
    return curate(db, seed), seed


def _admitted_row(db):
    row = db.execute(
        "SELECT event_id, artifact_ids_json, payload_json FROM events "
        "WHERE event_type = 'CuratedKnowledgeAdmitted'").fetchone()
    return row


def _subject_keys(db, event_id):
    row = dict(db.execute(
        "SELECT event_type, task_id, artifact_ids_json, payload_json "
        "FROM events WHERE event_id = ?", (event_id,)).fetchone())
    return _row_subject_keys(row)


def _note_text(root, event_id):
    return (Path(root) / note_filename(
        event_id, "CuratedKnowledgeAdmitted")).read_text(encoding="utf-8")


# ── journal-level contract ──

def test_admitted_record_carries_resolvable_shared_refs(db):
    """Every emitted admission carries the shared refs, and each one
    resolves to an artifact row of the same project (never a dangling id)."""
    _result, seed = _admit(db)
    row = _admitted_row(db)
    carried = json.loads(row["artifact_ids_json"])
    payload = json.loads(row["payload_json"])
    assert carried, "the emitted admission carries no shared ref"
    assert carried == payload["evidence_basis"] == seed["evidence_ids"]
    for artifact_id in carried:
        resolved = db.execute(
            "SELECT project_id FROM artifacts WHERE artifact_id = ?",
            (artifact_id,)).fetchone()
        assert resolved is not None, f"unresolvable carried ref {artifact_id}"
        assert resolved["project_id"] == "p1"


def test_source_member_is_a_retractable_source_artifact(db):
    _result, seed = _admit(db)
    carried = json.loads(_admitted_row(db)["artifact_ids_json"])
    types = {db.execute(
        "SELECT artifact_type FROM artifacts WHERE artifact_id = ?",
        (artifact_id,)).fetchone()["artifact_type"]
        for artifact_id in carried}
    assert types & SOURCE_ARTIFACT_TYPES, types
    assert seed["evidence_id"] in carried


def test_every_basis_member_is_carried_sorted_and_complete(db):
    """Journal == registry: artifact_ids_json equals the stored retraction
    basis rows (every member, deterministic sorted order)."""
    _result, _seed = _admit(db, source_count=3)
    carried = json.loads(_admitted_row(db)["artifact_ids_json"])
    basis_rows = [row["evidence_artifact_id"] for row in db.execute(
        "SELECT evidence_artifact_id FROM curated_knowledge_retraction_basis "
        "ORDER BY evidence_artifact_id").fetchall()]
    assert carried == basis_rows == sorted(carried)
    assert len(carried) == 3


def test_admission_payload_is_unchanged_additive_only(db):
    """ADDITIVE ONLY: the payload key set and values are untouched; the new
    refs ride the separate artifact_ids_json column."""
    result, seed = _admit(db)
    payload = json.loads(_admitted_row(db)["payload_json"])
    assert frozenset(payload) == ADMISSION_PAYLOAD_KEYS
    assert "artifact_ids" not in payload and "artifact_id" not in payload
    assert payload["curated_id"] == result.entity_id
    assert payload["kind"] == "REFUTED_PATTERN"
    assert payload["operation"] == "ADMIT"
    # Pre-existing shape (unchanged): the payload records the binding ROW id.
    binding_row = db.execute(
        "SELECT artifact_id FROM artifacts WHERE artifact_type = ?",
        (FEATURE_BINDING_ARTIFACT_TYPE,)).fetchone()["artifact_id"]
    assert payload["source_binding_ref"] == binding_row
    # The prefixed content ref used by the curation resolves to that same
    # row; it is deliberately NOT part of the chartered payload.
    row_hash = db.execute(
        "SELECT content_hash FROM artifacts WHERE artifact_id = ?",
        (binding_row,)).fetchone()["content_hash"]
    assert seed["binding_ref"] == FEATURE_BINDING_REF_PREFIX + row_hash
    assert payload["evidence_basis"] == [seed["evidence_id"]]
    assert payload["supersedes_ref"] == ""


def test_supersede_admission_carries_refs_too(db):
    """The invariant holds for both curation operations (one emission site)."""
    first, seed = _admit(db)
    seed2 = dict(seed)
    seed2["binding_ref"] = insert_binding(
        db, artifact_id="art-fb2", instrument="eurusd")
    seed2["signature_json"] = signature_from_binding(json.loads(db.execute(
        "SELECT metadata_json FROM artifacts WHERE artifact_id = 'art-fb2'"
    ).fetchone()["metadata_json"]))
    second = curate(db, seed2, operation="SUPERSEDE",
                    supersedes_ref=first.entity_id)
    rows = db.execute(
        "SELECT artifact_ids_json, payload_json FROM events "
        "WHERE event_type = 'CuratedKnowledgeAdmitted' "
        "ORDER BY event_id ASC").fetchall()
    assert len(rows) == 2
    for row in rows:
        carried = json.loads(row["artifact_ids_json"])
        assert carried == json.loads(row["payload_json"])["evidence_basis"]
        assert carried
    assert second.row["operation"] == "SUPERSEDE"


def test_retraction_rows_share_the_artifact_key(db):
    """The journal-level match: the admission's carried ref and both
    retraction producers' refs land in the same ``artifact:`` namespace."""
    _admit(db)
    admission = _admitted_row(db)
    Controller(db, project_id="p1").record_source_retraction(
        "art-src1", caused_by="operator", reason="REMOVED_OR_RETRACTED")
    retracted = db.execute(
        "SELECT event_id FROM events WHERE event_type = 'SourceRetracted'"
    ).fetchone()
    shared = (_subject_keys(db, admission["event_id"])
              & _subject_keys(db, retracted["event_id"]))
    assert "artifact:art-src1" in shared


def test_s5_cascade_rows_share_the_artifact_key(db):
    _result, seed = _admit(db)
    _record_s5_human_decision(db)
    _retract(db, f"source_result:{seed['evidence_hash']}")
    admission_keys = _subject_keys(db, _admitted_row(db)["event_id"])
    for event_type in ("SourceRetracted", "CuratedKnowledgeInvalidated"):
        row = db.execute(
            "SELECT event_id FROM events WHERE event_type = ?",
            (event_type,)).fetchone()
        assert row is not None, event_type
        assert f"artifact:{seed['evidence_id']}" in \
            (_subject_keys(db, row["event_id"]) & admission_keys)


# ── derived-view consequence (the B3 residual itself) ──

def test_bare_source_retracted_retires_the_produced_note(db, tmp_path):
    """Before the producer fix the note stayed ``authoritative: true``
    (stale): a bare Controller retraction has no curated follow-on, so the
    only possible match is the shared source-artifact ref."""
    _result, _seed = _admit(db)
    admission = _admitted_row(db)
    Controller(db, project_id="p1").record_source_retraction(
        "art-src1", caused_by="operator", reason="REMOVED_OR_RETRACTED")
    root = str(tmp_path / "v")
    project(db, "p1", root, cursor=0)
    text = _note_text(root, admission["event_id"])
    assert "authoritative: false" in text.split("---")[1]
    assert "superseded by" in text


def test_s5_retraction_retires_the_produced_note(db, tmp_path):
    _result, seed = _admit(db)
    admission = _admitted_row(db)
    _record_s5_human_decision(db)
    _retract(db, f"source_result:{seed['evidence_hash']}")
    root = str(tmp_path / "v")
    project(db, "p1", root, cursor=0)
    text = _note_text(root, admission["event_id"])
    assert "authoritative: false" in text.split("---")[1]
    assert "superseded by" in text


def test_legacy_admission_without_refs_still_projects(db, tmp_path):
    """Pre-fix journal rows carry no shared ref; projection still works and
    nothing is fabricated (no historical backfill — the derived view never
    invents a match), so the legacy row's validity is unchanged."""
    _append_event_to_db(
        db, frozen_clock(CLOCK), "CuratedKnowledgeAdmitted",
        project_id="p1", correlation_id="legacy-1", caused_by="DETERMINISTIC",
        reason="legacy row (pre-R-2 producer)",
        payload={"curated_id": "curated_legacy", "kind": "REFUTED_PATTERN",
                 "operation": "ADMIT", "signature_json": "{}",
                 "source_binding_ref": "art-fb1",
                 "source_decision_event_ref": "tr-1",
                 "program_ref": "rp-1", "hypothesis_ref": "h1",
                 "admission_decision_ref": "d-1", "evidence_basis": [],
                 "operator_id": "op-1", "supersedes_ref": ""})
    legacy = db.execute(
        "SELECT event_id FROM events WHERE event_type = "
        "'CuratedKnowledgeAdmitted'").fetchone()
    insert_artifact(db, "art-src1", "source_result", content_hash="srchash1")
    Controller(db, project_id="p1").record_source_retraction(
        "art-src1", caused_by="operator", reason="REMOVED_OR_RETRACTED")
    root = str(tmp_path / "v")
    project(db, "p1", root, cursor=0)          # no crash, no fabrication
    text = _note_text(root, legacy["event_id"])
    assert "authoritative: true" in text.split("---")[1]
    assert "superseded by" not in text
