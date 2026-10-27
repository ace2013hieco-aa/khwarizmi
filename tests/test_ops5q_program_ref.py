"""OPS-5Q — one program, one spelling.

The gateway admits a classification's program reference as a bare
``<program_id>`` or as ``research_program:<content_hash>`` and stores the
raw value. The N1 detector grouped by the raw string and the HR-08
completion gate exact-compared the raw string, so two classifications of
one program recorded under different spellings never paired — and a
project could complete over an open conflict.

This file pins the rulings:

1. **One canonicaliser, one home.** ``hermes.core.program_refs`` resolves
   both spellings to the row's ``program_id`` through the project's
   program rows. A bare ref is already canonical; a prefixed ref needs a
   row (its suffix may be an id or a content hash), and without one it
   fails closed.
2. **Equivalence.** The two spellings of one program produce one detector
   group, one contradiction row, and one ``OPEN_CONTRADICTION`` denial.
3. **No over-normalisation.** Two different programs never pair; two
   different hypotheses never pair; a hypothesis literally named
   ``hypothesis:<x>`` is not merged with ``<x>``.
4. **Fail closed.** An unresolvable prefixed ref is not paired and denies
   completion (``PROGRAM_REF_UNRESOLVED``); never a guessed key.
"""

from __future__ import annotations

import json
from typing import Any

from hermes.core.program_refs import (
    HYPOTHESIS_REF_PREFIX,
    PROGRAM_REF_PREFIX,
    canonical_program_id,
    canonical_program_scope,
    program_ref_key,
)
from hermes.persistence.database import connect
from hermes.persistence.failure_classifications import (
    FailureClassificationRepository,
    classifications_digest,
)
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ProjectRepository
from hermes.research.completion import (
    OPEN_CONTRADICTION,
    PROGRAM_REF_UNRESOLVED,
    can_complete_research,
)
from hermes.research.contradiction_candidates import detector_candidate_rows
from hermes.research.contradictions import (
    DETECTOR_UNCANONICALISED,
    contradiction_id_of,
    detect_classification_conflicts,
)
from hermes.research.controller import Controller
from hermes.research.evidence_ladder import classification_content_hash
from hermes.research.failure_classification import ACTION_MAP, FailureClass

PROJECT = "p1"
CLOCK = "2026-01-01T00:00:00.000000+00:00"

#: The project's program rows: one program in both spellings.
PROGRAMS = [{
    "program_id": "rp-1",
    "content_hash": "ch-rp-1",
    "version": 1,
    "hypotheses": [{"ref": "h1"}],
}]


def _db() -> Any:
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: CLOCK).create(PROJECT, "OPS-5Q")
    return conn


def _insert_program(
    conn: Any, program_id: str, content_hash: str, *,
    version: int = 1, hypotheses: tuple[str, ...] = ("h1",),
) -> None:
    conn.execute(
        """INSERT INTO research_programs
           (program_id, project_id, version, content_hash, supersedes_id,
            scope_ref, epistemic_objective, compiler_version, policy_version,
            schema_version, input_hash, hypothesis_json, prediction_json,
            discrimination_json, evidence_json, gate_json, methodology_json,
            task_graph_template_ref, produced_by, reason, created_at)
           VALUES (?, ?, ?, ?, NULL, 'b', 'o', 'c1', 'p1', '1', 'ih', ?,
                   '[]', '[]', '[]', '[]', '[]', NULL, 'director', NULL, ?)""",
        (program_id, PROJECT, version, content_hash,
         json.dumps([{"ref": h} for h in hypotheses]), CLOCK))


def _insert_evidence(conn: Any, artifact_id: str, content_hash: str) -> None:
    conn.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type, content_hash,
            size_bytes, storage_path, producer, metadata_json, created_at)
           VALUES (?, ?, NULL, 'evidence', ?, 1, 'x', 't', NULL, ?)""",
        (artifact_id, PROJECT, content_hash, CLOCK))


def _insert_classification(
    conn: Any, artifact_id: str, *, program_ref: str,
    hypothesis_ref: str = "h1",
    failure_class: str = "DECLARED_CONSTRAINT_VIOLATION",
) -> None:
    permitted = sorted(
        action.value for action in ACTION_MAP[FailureClass(failure_class)])
    meta = {
        "schema_version": "1",
        "failure_class": failure_class,
        "hypothesis_ref": hypothesis_ref,
        "program_ref": program_ref,
        "classification_id": artifact_id,
        "classifier_version": "1.0",
        "contributing_factors": [],
        "evidence_refs": ["evidence:evhash1"],
        "constraint_ref": (
            f"hypothesis:{hypothesis_ref}:falsification_condition"),
        "failed_mechanism_ref": None,
        "regime_ref": None,
        "resource_gap": None,
        "scope_brief_ref": None,
        "scope_brief_field": None,
        "explanation": f"OPS-5Q test {artifact_id}",
        "proposed_by": "DIRECTOR",
        "falsifying_evidence_refs": ["evidence:evhash1"],
        "permitted_actions": permitted,
    }
    content_hash = classification_content_hash(meta, PROJECT)
    conn.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type, content_hash,
            size_bytes, storage_path, producer, metadata_json, created_at)
           VALUES (?, ?, NULL, 'failure_classification', ?, 1, 'x', 't',
                   ?, ?)""",
        (artifact_id, PROJECT, content_hash, json.dumps(meta), CLOCK))


def _rows(conn: Any) -> list[dict]:
    digest = classifications_digest(
        FailureClassificationRepository(conn).classifications_for_project(
            PROJECT))
    return detector_candidate_rows(conn, PROJECT, digest.get("items", []))


def _row(
    artifact_id: str, program_ref: str, *,
    hypothesis_ref: str = "h1",
    failure_class: str = "DECLARED_CONSTRAINT_VIOLATION",
) -> dict:
    return {
        "artifact_id": artifact_id,
        "project_id": PROJECT,
        "program_ref": program_ref,
        "hypothesis_ref": hypothesis_ref,
        "failure_class": failure_class,
        "evidence": ["art-ev1"],
        "invalidated": False,
    }


def _pair(rows: list[dict], programs: Any = PROGRAMS) -> list[dict]:
    return detect_classification_conflicts(rows, programs=programs)


def _denials(result: Any, code: str) -> list[Any]:
    return [denial for denial in result.denials if denial.code == code]


# ═══════════════ 1. the canonicaliser ═══════════════


def test_program_ref_key_strips_exactly_one_prefix() -> None:
    assert program_ref_key("rp-1") == "rp-1"
    assert program_ref_key(f"{PROGRAM_REF_PREFIX}rp-1") == "rp-1"
    assert program_ref_key(f"{PROGRAM_REF_PREFIX}ch-rp-1") == "ch-rp-1"
    assert program_ref_key(f"{PROGRAM_REF_PREFIX}{PROGRAM_REF_PREFIX}x") == (
        f"{PROGRAM_REF_PREFIX}x")
    assert program_ref_key("") is None
    assert program_ref_key(None) is None
    assert program_ref_key(f"{PROGRAM_REF_PREFIX}") is None


def test_both_admitted_spellings_resolve_to_one_program_id() -> None:
    assert canonical_program_id("rp-1", PROGRAMS) == "rp-1"
    assert canonical_program_id(f"{PROGRAM_REF_PREFIX}ch-rp-1", PROGRAMS) == (
        "rp-1")
    # The suffix may itself be the program id; the resolver accepts it.
    assert canonical_program_id(f"{PROGRAM_REF_PREFIX}rp-1", PROGRAMS) == (
        "rp-1")
    # A bare content hash is the resolver's other accepted bare key.
    assert canonical_program_id("ch-rp-1", PROGRAMS) == "rp-1"


def test_an_unknown_prefixed_ref_fails_closed() -> None:
    assert canonical_program_id(f"{PROGRAM_REF_PREFIX}ghost", PROGRAMS) is None
    # A bare id needs no row: it is already the canonical form.
    assert canonical_program_id("ghost", PROGRAMS) == "ghost"
    # A prefixed ref needs the row even when the project has no rows.
    assert canonical_program_id("rp-1", []) == "rp-1"
    assert canonical_program_id(f"{PROGRAM_REF_PREFIX}ch-rp-1", []) is None


def test_an_ambiguous_ref_is_not_guessed() -> None:
    ambiguous = [
        {"program_id": "rp-a", "content_hash": "x", "hypotheses": []},
        {"program_id": "rp-b", "content_hash": "rp-a", "hypotheses": []},
    ]
    # "rp-a" is rp-a's id and rp-b's content hash: two programs, no guess.
    assert canonical_program_id("rp-a", ambiguous) is None


def test_the_hypothesis_spelling_resolves_against_the_registry() -> None:
    assert canonical_program_scope("rp-1", "h1", PROGRAMS) == ("rp-1", "h1")
    assert canonical_program_scope(
        "rp-1", f"{HYPOTHESIS_REF_PREFIX}h1", PROGRAMS) == ("rp-1", "h1")
    assert canonical_program_scope("rp-1", "h2", PROGRAMS) is None
    assert canonical_program_scope("rp-1", None, PROGRAMS) is None


def test_a_literal_prefixed_hypothesis_is_not_merged() -> None:
    """An exact registered ref wins over the prefix interpretation."""
    programs = [{
        "program_id": "rp-1", "content_hash": "ch-rp-1", "version": 1,
        "hypotheses": [{"ref": "h1"}, {"ref": "hypothesis:h1"}],
    }]
    assert canonical_program_scope(
        "rp-1", "hypothesis:h1", programs) == ("rp-1", "hypothesis:h1")
    assert canonical_program_scope("rp-1", "h1", programs) == ("rp-1", "h1")


def test_no_hypothesis_registry_keeps_the_stored_ref() -> None:
    programs = [{
        "program_id": "rp-1", "content_hash": "ch-rp-1", "version": 1,
        "hypotheses": [],
    }]
    assert canonical_program_scope(
        "rp-1", "h1", programs) == ("rp-1", "h1")


# ═══════════════ 2. the detector pairs the two spellings ═══════════════


def test_two_spellings_of_one_program_pair() -> None:
    rows = [
        _row("fc-a", "rp-1"),
        _row("fc-b", f"{PROGRAM_REF_PREFIX}ch-rp-1",
             failure_class="IMPLEMENTATION_FAILURE"),
    ]
    found = _pair(rows)

    assert [pair["contradiction_id"] for pair in found] == [
        contradiction_id_of("fc-a", "fc-b")]
    assert (found[0]["party_a"], found[0]["party_b"]) == ("fc-a", "fc-b")


def test_the_hypothesis_spelling_also_pairs() -> None:
    rows = [
        _row("fc-a", "rp-1", hypothesis_ref="h1"),
        _row("fc-b", f"{PROGRAM_REF_PREFIX}ch-rp-1",
             hypothesis_ref=f"{HYPOTHESIS_REF_PREFIX}h1",
             failure_class="IMPLEMENTATION_FAILURE"),
    ]
    assert len(_pair(rows)) == 1


def test_two_different_programs_do_not_pair() -> None:
    programs = PROGRAMS + [{
        "program_id": "rp-2", "content_hash": "ch-rp-2", "version": 1,
        "hypotheses": [{"ref": "h1"}],
    }]
    rows = [
        _row("fc-a", "rp-1"),
        _row("fc-b", f"{PROGRAM_REF_PREFIX}ch-rp-2",
             failure_class="IMPLEMENTATION_FAILURE"),
    ]
    assert _pair(rows, programs) == []


def test_two_different_hypotheses_do_not_pair() -> None:
    programs = [{
        "program_id": "rp-1", "content_hash": "ch-rp-1", "version": 1,
        "hypotheses": [{"ref": "h1"}, {"ref": "h2"}],
    }]
    rows = [
        _row("fc-a", "rp-1", hypothesis_ref="h1"),
        _row("fc-b", f"{PROGRAM_REF_PREFIX}ch-rp-1", hypothesis_ref="h2",
             failure_class="IMPLEMENTATION_FAILURE"),
    ]
    assert _pair(rows, programs) == []


def test_an_unresolvable_ref_is_not_paired_and_is_reported() -> None:
    diagnostics: dict = {}
    rows = [
        _row("fc-a", "rp-1"),
        _row("fc-b", f"{PROGRAM_REF_PREFIX}ghost",
             failure_class="IMPLEMENTATION_FAILURE"),
    ]
    found = detect_classification_conflicts(
        rows, programs=PROGRAMS, diagnostics=diagnostics)

    assert found == []
    unresolved = diagnostics[DETECTOR_UNCANONICALISED]
    assert unresolved["count"] == 1
    assert unresolved["rows"] == [{
        "artifact_id": "fc-b",
        "program_ref": f"{PROGRAM_REF_PREFIX}ghost",
        "hypothesis_ref": "h1",
    }]


def test_without_rows_a_bare_ref_stays_canonical_but_a_prefixed_one_does_not(
) -> None:
    bare = [_row("fc-a", "rp-1"), _row(
        "fc-b", "rp-1", failure_class="IMPLEMENTATION_FAILURE")]
    assert len(_pair(bare, [])) == 1

    unresolved = [_row("fc-a", "rp-1"), _row(
        "fc-b", f"{PROGRAM_REF_PREFIX}ch-rp-1",
        failure_class="IMPLEMENTATION_FAILURE")]
    assert _pair(unresolved, []) == []


# ═══════════════ 3. the completion gate ═══════════════


def _pair_db(*, second_ref: str = f"{PROGRAM_REF_PREFIX}ch-rp-1") -> Any:
    conn = _db()
    _insert_program(conn, "rp-1", "ch-rp-1")
    _insert_evidence(conn, "art-ev1", "evhash1")
    _insert_classification(
        conn, "fc-a", program_ref="rp-1",
        failure_class="DECLARED_CONSTRAINT_VIOLATION")
    _insert_classification(
        conn, "fc-b", program_ref=second_ref,
        failure_class="IMPLEMENTATION_FAILURE")
    return conn


def test_completion_denies_over_the_two_spellings() -> None:
    conn = _pair_db()
    try:
        result = can_complete_research(conn, PROJECT)
        assert result.eligible is False
        denials = _denials(result, OPEN_CONTRADICTION)
        assert [denial.subject for denial in denials] == [
            contradiction_id_of("fc-a", "fc-b")]
    finally:
        conn.close()


def test_completion_sees_no_pair_across_two_different_programs() -> None:
    conn = _db()
    try:
        _insert_program(conn, "rp-1", "ch-rp-1")
        _insert_program(conn, "rp-2", "ch-rp-2", version=2)
        _insert_evidence(conn, "art-ev1", "evhash1")
        _insert_classification(
            conn, "fc-a", program_ref="rp-1",
            failure_class="DECLARED_CONSTRAINT_VIOLATION")
        _insert_classification(
            conn, "fc-b", program_ref=f"{PROGRAM_REF_PREFIX}ch-rp-2",
            failure_class="IMPLEMENTATION_FAILURE")

        result = can_complete_research(conn, PROJECT)
        assert result.eligible is True
        assert _denials(result, OPEN_CONTRADICTION) == []
    finally:
        conn.close()


def test_completion_denies_when_a_ref_cannot_be_canonicalised() -> None:
    conn = _pair_db(second_ref=f"{PROGRAM_REF_PREFIX}ghost")
    try:
        result = can_complete_research(conn, PROJECT)
        assert result.eligible is False
        unresolved = _denials(result, PROGRAM_REF_UNRESOLVED)
        assert [denial.subject for denial in unresolved] == ["fc-b"]
        assert "ghost" in unresolved[0].explanation
        assert _denials(result, OPEN_CONTRADICTION) == []
    finally:
        conn.close()


def test_the_detector_and_the_gate_share_the_canonical_key() -> None:
    """The end-to-end path: candidate rows -> detector -> completion."""
    conn = _pair_db()
    try:
        rows = _rows(conn)
        found = detect_classification_conflicts(rows, programs=[{
            "program_id": "rp-1", "content_hash": "ch-rp-1",
            "version": 1, "hypotheses": [{"ref": "h1"}]}])
        assert [pair["contradiction_id"] for pair in found] == [
            contradiction_id_of("fc-a", "fc-b")]
        result = can_complete_research(conn, PROJECT)
        assert _denials(result, OPEN_CONTRADICTION)
    finally:
        conn.close()


def test_the_controller_records_the_pair_across_the_two_spellings() -> None:
    """Pairing is not just a pure-detector fact: the row is admitted."""
    conn = _pair_db()
    try:
        out = Controller(
            conn, project_id=PROJECT, clock=lambda: CLOCK
        ).detect_contradictions()

        assert out["rejected"] is False
        assert out["refused"] == []
        assert len(out["recorded"]) == 1
        rows = conn.execute(
            "SELECT contradiction_id, party_a, party_b FROM contradictions"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["contradiction_id"] == contradiction_id_of(
            "fc-a", "fc-b")
        assert {rows[0]["party_a"], rows[0]["party_b"]} == {"fc-a", "fc-b"}
    finally:
        conn.close()
