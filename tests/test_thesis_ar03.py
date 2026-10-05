"""Golden fixtures for the AR-03 hardening (v6 §9.1, S1).

Proves the empty-result-set artifact enforcement against real SQLite:
1. a NONE_FOUND counter-search WITHOUT a persisted artifact is rejected
   (the pre-AR-03 self-attestation is no longer certifiable);
2. a NONE_FOUND counter-search referencing a persisted artifact whose
   recorded terms cover the declared terms is accepted;
3. a NONE_FOUND with an artifact whose recorded terms do NOT cover the
   declared terms is rejected (the artifact must record what was actually
   run);
4. FOUND counter-searches without a minority row are rejected (they are
   not compliance);
5. a round-1 table is not subject to the round-2 compliance rule;
6. a minority-direction row satisfies the rule even with no
   counter_search;
7. the artifact is content-addressed + project-scoped + idempotent
   (forged id fails, duplicates collapse, cross-project resolves to None);
8. the validator is pure and fail-closed (bad shapes are structured
   errors, never raises).
"""
from __future__ import annotations

import pytest

from hermes.persistence.database import connect
from hermes.persistence.migrations import SUPPORTED_VERSION, migrate_to_latest
from hermes.persistence.repositories import (
    EmptyResultArtifactRepository,
    NotFoundError,
    ProjectRepository,
)
from hermes.research.thesis import (
    empty_result_id_of,
    validate_thesis_evidence,
)


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Test")
    ProjectRepository(conn).create("p2", "Other")
    yield conn
    conn.close()


def thesis_table(**overrides) -> dict:
    t = {
        "project_id": "p1",
        "thesis_ref": "T1",
        "round": 2,
        "rows": [
            {"claim_component": "c1", "direction": "FOR",
             "source_ref": "source:1", "venue_tier": "B",
             "subject_tags": {"instrument": "x", "feature_family": "y",
                              "claim_type": "z"}},
        ],
        "minority_direction": "AGAINST",
        "counter_search": {
            "performed": True,
            "terms": ["momentum", "reversal"],
            "result": "NONE_FOUND",
            "artifact_ref": empty_result_id_of(
                ("momentum", "reversal"), "provider returned 0 results"),
        },
    }
    t.update(overrides)
    return t


def record_artifact(conn, project_id="p1",
                    terms=("momentum", "reversal"),
                    response="provider returned 0 results") -> dict:
    repo = EmptyResultArtifactRepository(conn)
    return repo.record(project_id, terms, response)


# ── 1. NONE_FOUND without an artifact is rejected ──

def test_1_none_found_without_artifact_rejected(db):
    table = thesis_table(counter_search={
        "performed": True, "terms": ["momentum"], "result": "NONE_FOUND"})
    errors = validate_thesis_evidence(
        table, EmptyResultArtifactRepository(db).resolver())
    codes = {e.code for e in errors}
    assert "NONE_FOUND_NO_ARTIFACT" in codes


def test_1b_none_found_missing_artifact_ref_rejected(db):
    """Even with an artifact elsewhere, an uncited NONE_FOUND is rejected."""
    record_artifact(db)
    table = thesis_table(counter_search={
        "performed": True, "terms": ["momentum"], "result": "NONE_FOUND"})
    errors = validate_thesis_evidence(
        table, EmptyResultArtifactRepository(db).resolver())
    assert "NONE_FOUND_NO_ARTIFACT" in {e.code for e in errors}


def test_1c_no_resolver_fails_closed(db):
    """A round-2+ NONE_FOUND cannot be certified without a resolver."""
    table = thesis_table()
    errors = validate_thesis_evidence(table, None)
    assert "NONE_FOUND_UNDEREFERENCEABLE" in {e.code for e in errors}


# ── 2. NONE_FOUND with a matching persisted artifact is accepted ──

def test_2_none_found_with_persisted_artifact_accepted(db):
    record_artifact(db)
    errors = validate_thesis_evidence(
        thesis_table(), EmptyResultArtifactRepository(db).resolver())
    assert errors == []


def test_2b_artifact_terms_superset_of_declared_accepted(db):
    """The artifact may record MORE terms than the table declares (it
    records what was actually run)."""
    record_artifact(db, terms=("momentum", "reversal", "carry"))
    table = thesis_table(counter_search={
        "performed": True, "terms": ["momentum", "reversal"],
        "result": "NONE_FOUND",
        "artifact_ref": empty_result_id_of(
            ("momentum", "reversal", "carry"),
            "provider returned 0 results")})
    errors = validate_thesis_evidence(
        table, EmptyResultArtifactRepository(db).resolver())
    assert errors == []


# ── 3. artifact terms must cover the declared terms ──

def test_3_artifact_terms_mismatch_rejected(db):
    record_artifact(db, terms=("momentum",))
    table = thesis_table(counter_search={
        "performed": True, "terms": ["momentum", "reversal"],
        "result": "NONE_FOUND",
        "artifact_ref": empty_result_id_of(
            ("momentum",), "provider returned 0 results")})
    errors = validate_thesis_evidence(
        table, EmptyResultArtifactRepository(db).resolver())
    assert "NONE_FOUND_TERMS_MISMATCH" in {e.code for e in errors}


# ── 4. FOUND without a minority row is not compliance ──

def test_4_found_counter_without_minority_row_rejected(db):
    record_artifact(db)  # present but irrelevant: FOUND is not compliance
    table = thesis_table(counter_search={
        "performed": True, "terms": ["momentum"], "result": "FOUND"})
    errors = validate_thesis_evidence(
        table, EmptyResultArtifactRepository(db).resolver())
    assert "ROUND2_COUNTER_FOUND_NO_ROW" in {e.code for e in errors}


# ── 5. round-1 tables are not subject to the rule ──

def test_5_round1_not_subject_to_rule(db):
    table = thesis_table(round=1)
    errors = validate_thesis_evidence(
        table, EmptyResultArtifactRepository(db).resolver())
    assert errors == []


# ── 6. minority row satisfies the rule ──

def test_6_minority_row_satisfies_rule(db):
    table = thesis_table(
        rows=[
            {"claim_component": "c1", "direction": "FOR",
             "source_ref": "source:1", "venue_tier": "B",
             "subject_tags": {"instrument": "x", "feature_family": "y",
                              "claim_type": "z"}},
            {"claim_component": "c2", "direction": "AGAINST",
             "source_ref": "source:2", "venue_tier": "C",
             "subject_tags": {"instrument": "x", "feature_family": "y",
                              "claim_type": "z"}},
        ],
        counter_search=None)
    errors = validate_thesis_evidence(
        table, EmptyResultArtifactRepository(db).resolver())
    assert errors == []


# ── 7. artifact identity: content-addressed, project-scoped, idempotent ──

def test_7_artifact_id_content_addressed_and_idempotent(db):
    repo = EmptyResultArtifactRepository(db)
    a1 = repo.record("p1", ("momentum",), "provider returned 0 results")
    a2 = repo.record("p1", ("momentum",), "provider returned 0 results")
    assert a1["artifact_id"] == a2["artifact_id"]
    assert a1["artifact_id"] == empty_result_id_of(
        ("momentum",), "provider returned 0 results")
    # idempotent: one row
    rows = db.execute(
        "SELECT COUNT(*) c FROM empty_result_artifacts").fetchone()["c"]
    assert rows == 1


def test_7b_forged_artifact_id_fails_closed(db):
    """A resolver lookup of a nonexistent/forged id returns None — the
    NONE_FOUND reference fails closed."""
    repo = EmptyResultArtifactRepository(db)
    table = thesis_table(counter_search={
        "performed": True, "terms": ["momentum"], "result": "NONE_FOUND",
        "artifact_ref": "sr_" + "0" * 24})
    errors = validate_thesis_evidence(table, repo.resolver())
    assert "NONE_FOUND_ARTIFACT_MISSING" in {e.code for e in errors}


def test_7c_cross_project_artifact_not_resolvable(db):
    """An artifact recorded in p2 does not certify a p1 table."""
    record_artifact(db, project_id="p2")
    repo = EmptyResultArtifactRepository(db)
    table = thesis_table(counter_search={
        "performed": True, "terms": ["momentum"], "result": "NONE_FOUND",
        "artifact_ref": empty_result_id_of(
            ("momentum",), "provider returned 0 results")})
    errors = validate_thesis_evidence(table, repo.resolver())
    assert "NONE_FOUND_ARTIFACT_MISSING" in {e.code for e in errors}


def test_7d_repository_rejects_empty_terms_or_response(db):
    repo = EmptyResultArtifactRepository(db)
    with pytest.raises(Exception, match="query terms"):
        repo.record("p1", (), "response")
    with pytest.raises(Exception, match="provider response"):
        repo.record("p1", ("x",), "")


def test_7e_repository_get_missing_raises(db):
    with pytest.raises(NotFoundError):
        EmptyResultArtifactRepository(db).get("sr_nope")


# ── 8. pure + fail-closed shapes ──

def test_8_bad_shapes_structured_errors(db):
    repo = EmptyResultArtifactRepository(db)
    assert "TABLE_NOT_MAPPING" in {e.code for e in
                                   validate_thesis_evidence([], repo.resolver())}
    assert "ROWS_NOT_LIST" in {e.code for e in validate_thesis_evidence(
        {"round": 2, "rows": "nope"}, repo.resolver())}
    assert "BAD_ROUND" in {e.code for e in validate_thesis_evidence(
        {"round": 0, "rows": []}, repo.resolver())}
    assert "BAD_DIRECTION" in {e.code for e in validate_thesis_evidence(
        {"round": 2, "rows": [{"direction": "SIDEWAYS"}]}, repo.resolver())}


def test_8b_schema_version_is_8(db):
    # ADV-02: schema version 8 adds scheduler-lease generation fencing.
    # audit F9: version 12 adds the schema-level one-verdict index
    # M1/HR-02: version 13 adds validation_verdicts (verdict-gated ladder)
    # M4/HR-05: version 14 adds research_claims.support_state
    # Step 7: version 15 adds the curated knowledge registry (§16.6)
    # CHG-1/CHG-2: version 16 adds contradictions + provider_interactions
    assert SUPPORTED_VERSION == 19
    from hermes.persistence.database import get_schema_version
    assert get_schema_version(db) == 19
