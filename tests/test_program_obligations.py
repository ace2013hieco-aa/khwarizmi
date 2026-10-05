"""IDR-038 §3.1 — per-requirement satisfaction links (write path + derivation).

The migration-8→9 slice records that a SPECIFIC artifact satisfies a SPECIFIC
evidence requirement of a SPECIFIC program. These fixtures pin the four
admission validations, idempotency, append-only structure, and the
per-requirement derivation (fulfillment per hypothesis, never per artifact
class) — including the tamper cases where a forged/wrong-class link must not
fake satisfaction.
"""
from __future__ import annotations

import json as _json

import pytest

from hermes.core import frozen_clock
from hermes.core.node import NodeContract, NodeType
from hermes.core.task_status import TaskStatus
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.program_obligations import (
    ProgramRequirementSatisfactionRepository,
    RequirementSatisfactionError,
    ValidationVerdictError,
    ValidationVerdictRepository,
    satisfaction_id_of,
    validation_verdict_id_of,
)
from hermes.persistence.repositories import ProjectRepository, TaskRepository
from hermes.research.controller import Controller
from hermes.research.evaluation import DimensionLevel
from hermes.research.extraction import (
    EXTRACT_TEMPLATE,
    extraction_draft_from_mapping,
)
from hermes.research.task_obligations import program_obligation_dimensions

CLOCK = "2026-01-01T00:00:00.000000+00:00"
REQUIRED = ("pre_registered_experiment", "statistical_analysis")


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Test")
    conn.execute(
        """INSERT INTO dataset_manifests
           (manifest_id, project_id, location, format, size_bytes,
            headers_json, schema_observations_json, query_recipes_json,
            content_hash, provenance_json, created_at, immutable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        ("dm-1", "p1", "x.csv", "csv", 1, "[]", "[]", "[]",
         "h1", None, CLOCK),
    )
    yield conn
    conn.close()


def insert_program(db, program_id, *, project="p1", evidence=None):
    db.execute(
        """INSERT INTO research_programs
           (program_id, project_id, version, content_hash, supersedes_id,
            scope_ref, epistemic_objective, compiler_version, policy_version,
            schema_version, input_hash, hypothesis_json, prediction_json,
            discrimination_json, evidence_json, gate_json, methodology_json,
            task_graph_template_ref, produced_by, reason, created_at)
           VALUES (?, ?, 1, ?, NULL, 'b', 'o', 'c1', 'p1', '1', 'ih', '[]',
                   '[]', '[]', ?, '[]', '[]', NULL, 'director', NULL, ?)""",
        (program_id, project, f"ch-{program_id}", _json.dumps(evidence or []),
         CLOCK),
    )


def insert_artifact(db, artifact_id, artifact_type, *, project="p1"):
    db.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type,
            content_hash, size_bytes, storage_path, producer,
            metadata_json, created_at)
           VALUES (?, ?, NULL, ?, ?, 1, 'x', 't', '{}', ?)""",
        (artifact_id, project, artifact_type, f"ch-{artifact_id}", CLOCK),
    )


def add_verdict(db, artifact_id, verdict="PASS", *, project="p1"):
    """Record a content-validation verdict (M1/HR-02) for an artifact."""
    ValidationVerdictRepository(db, clock=frozen_clock(CLOCK)).record(
        project_id=project, artifact_id=artifact_id, verdict=verdict)


def req(claim_ref, classes=REQUIRED):
    return {"claim_ref": claim_ref, "ladder_target": "SUPPORTED",
            "required_artifacts": list(classes), "associated_gates": []}


@pytest.fixture
def program_with_requirement(db):
    insert_program(db, "rp-1", evidence=[req("h1")])
    for typ in REQUIRED:
        insert_artifact(db, f"art-{typ}", typ)
    return db


# ── the validated write path ──

class TestWritePath:
    def test_valid_link_recorded(self, program_with_requirement):
        add_verdict(program_with_requirement, "art-pre_registered_experiment")
        repo = ProgramRequirementSatisfactionRepository(
            program_with_requirement, clock=frozen_clock(CLOCK))
        row = repo.record(project_id="p1", program_id="rp-1",
                          requirement_ref="h1", artifact_id="art-pre_registered_experiment")
        assert row["program_id"] == "rp-1"
        assert row["requirement_ref"] == "h1"
        assert row["satisfaction_id"] == satisfaction_id_of(
            "rp-1", "h1", "art-pre_registered_experiment")

    def test_link_without_validation_verdict_refused(self, program_with_requirement):
        """M1/HR-02 — the satisfaction write refuses a link whose artifact
        carries no PASS validation verdict: a bare artifact class can never
        satisfy a requirement (rule 5)."""
        repo = ProgramRequirementSatisfactionRepository(
            program_with_requirement)
        with pytest.raises(
                RequirementSatisfactionError, match="validation verdict"):
            repo.record(project_id="p1", program_id="rp-1",
                        requirement_ref="h1",
                        artifact_id="art-pre_registered_experiment")

    def test_fail_verdict_does_not_cover(self, program_with_requirement):
        """M1/HR-02 — a FAIL validation verdict does NOT cover: the artifact
        was validated and found wanting, so it still cannot satisfy."""
        add_verdict(program_with_requirement, "art-pre_registered_experiment",
                    verdict="FAIL")
        repo = ProgramRequirementSatisfactionRepository(
            program_with_requirement)
        with pytest.raises(
                RequirementSatisfactionError, match="validation verdict"):
            repo.record(project_id="p1", program_id="rp-1",
                        requirement_ref="h1",
                        artifact_id="art-pre_registered_experiment")

    def test_forged_requirement_ref_rejected(self, program_with_requirement):
        repo = ProgramRequirementSatisfactionRepository(program_with_requirement)
        with pytest.raises(RequirementSatisfactionError, match="does not dereference"):
            repo.record(project_id="p1", program_id="rp-1",
                        requirement_ref="h1-FORGED",
                        artifact_id="art-pre_registered_experiment")

    def test_foreign_artifact_rejected(self, db):
        ProjectRepository(db).create("other", "Other")
        insert_program(db, "rp-1", evidence=[req("h1")])
        insert_artifact(db, "art-foreign", "statistical_analysis", project="other")
        repo = ProgramRequirementSatisfactionRepository(db)
        with pytest.raises(RequirementSatisfactionError, match="does not exist in project"):
            repo.record(project_id="p1", program_id="rp-1",
                        requirement_ref="h1", artifact_id="art-foreign")

    def test_wrong_class_artifact_rejected(self, program_with_requirement):
        # h1 requires pre_registered_experiment + statistical_analysis; a
        # failure_classification artifact can never satisfy it (rule 4).
        insert_artifact(program_with_requirement, "art-cls", "failure_classification")
        repo = ProgramRequirementSatisfactionRepository(program_with_requirement)
        with pytest.raises(RequirementSatisfactionError, match="not among the required classes"):
            repo.record(project_id="p1", program_id="rp-1",
                        requirement_ref="h1", artifact_id="art-cls")

    def test_foreign_program_rejected(self, db):
        ProjectRepository(db).create("other", "Other")
        insert_program(db, "rp-1", evidence=[req("h1")])
        insert_program(db, "rp-other", evidence=[req("h1")], project="other")
        insert_artifact(db, "art-x", "statistical_analysis")
        repo = ProgramRequirementSatisfactionRepository(db)
        with pytest.raises(RequirementSatisfactionError, match="not governed by project"):
            repo.record(project_id="p1", program_id="rp-other",
                        requirement_ref="h1", artifact_id="art-x")

    def test_idempotent_duplicate(self, program_with_requirement):
        add_verdict(program_with_requirement, "art-pre_registered_experiment")
        repo = ProgramRequirementSatisfactionRepository(
            program_with_requirement, clock=frozen_clock(CLOCK))
        first = repo.record(project_id="p1", program_id="rp-1",
                            requirement_ref="h1",
                            artifact_id="art-pre_registered_experiment")
        second = repo.record(project_id="p1", program_id="rp-1",
                             requirement_ref="h1",
                             artifact_id="art-pre_registered_experiment")
        assert second["satisfaction_id"] == first["satisfaction_id"]
        n = program_with_requirement.execute(
            "SELECT COUNT(*) c FROM program_requirement_satisfactions").fetchone()["c"]
        assert n == 1

    def test_append_only_no_update_or_delete_path(self):
        import hermes.persistence.program_obligations as po_mod
        with open(po_mod.__file__, encoding="utf-8") as fh:
            src = fh.read()
        assert "UPDATE program_requirement_satisfactions" not in src
        assert "DELETE FROM program_requirement_satisfactions" not in src
        assert "UPDATE validation_verdicts" not in src
        assert "DELETE FROM validation_verdicts" not in src


# ── M1/HR-02: validation-verdict substrate ──

class TestValidationVerdicts:
    def test_verdict_recorded_keyed_to_content_hash(self, db):
        insert_artifact(db, "art-x", "pre_registered_experiment")
        repo = ValidationVerdictRepository(db, clock=frozen_clock(CLOCK))
        row = repo.record(project_id="p1", artifact_id="art-x",
                          verdict="PASS")
        # input_hash is the artifact's CONTENT hash, re-derived from the
        # artifact row — never accepted from the caller, never a stored field.
        assert row["input_hash"] == "ch-art-x"
        assert row["verdict_id"] == validation_verdict_id_of("p1", "art-x")
        stored = db.execute(
            "SELECT input_hash, verdict FROM validation_verdicts "
            "WHERE artifact_id = 'art-x'").fetchone()
        assert tuple(stored) == ("ch-art-x", "PASS")

    def test_verdict_requires_existing_artifact(self, db):
        repo = ValidationVerdictRepository(db)
        with pytest.raises(ValidationVerdictError, match="does not exist"):
            repo.record(project_id="p1", artifact_id="ghost",
                        verdict="PASS")

    def test_verdict_vocabulary_closed(self, db):
        insert_artifact(db, "art-x", "pre_registered_experiment")
        repo = ValidationVerdictRepository(db)
        with pytest.raises(ValidationVerdictError, match="PASS/FAIL"):
            repo.record(project_id="p1", artifact_id="art-x",
                        verdict="MAYBE")

    def test_verdict_idempotent(self, db):
        insert_artifact(db, "art-x", "pre_registered_experiment")
        repo = ValidationVerdictRepository(db, clock=frozen_clock(CLOCK))
        first = repo.record(project_id="p1", artifact_id="art-x",
                            verdict="PASS")
        second = repo.record(project_id="p1", artifact_id="art-x",
                             verdict="PASS")
        assert second["verdict_id"] == first["verdict_id"]
        n = db.execute(
            "SELECT COUNT(*) FROM validation_verdicts").fetchone()[0]
        assert n == 1

    def test_coverage_read_reverifies_input_hash(self, db):
        """F2 — the coverage read re-verifies the verdict's input-hash
        against the artifact row: a tampered verdict (input_hash rewritten)
        loses coverage, never silently counts."""
        insert_artifact(db, "art-a", "pre_registered_experiment")
        insert_artifact(db, "art-b", "statistical_analysis")
        insert_artifact(db, "art-c", "validation")
        repo = ValidationVerdictRepository(db, clock=frozen_clock(CLOCK))
        repo.record(project_id="p1", artifact_id="art-a", verdict="PASS")
        repo.record(project_id="p1", artifact_id="art-b", verdict="PASS")
        repo.record(project_id="p1", artifact_id="art-c", verdict="FAIL")
        assert repo.verdict_covered_artifact_ids("p1") == frozenset(
            {"art-a", "art-b"})
        db.execute(
            "UPDATE validation_verdicts SET input_hash = 'forged' "
            "WHERE artifact_id = 'art-b'")
        # FAIL verdicts never cover; a tampered input-hash loses coverage
        assert repo.verdict_covered_artifact_ids("p1") == frozenset(
            {"art-a"})


# ── per-requirement derivation + tamper resistance ──

class TestDerivationIntegration:
    def test_requirement_fulfilled_only_by_its_own_links(self, program_with_requirement):
        repo = ProgramRequirementSatisfactionRepository(program_with_requirement)
        for typ in REQUIRED:
            add_verdict(program_with_requirement, f"art-{typ}")
            repo.record(project_id="p1", program_id="rp-1",
                        requirement_ref="h1", artifact_id=f"art-{typ}")
        sat = repo.satisfaction_types_by_requirement("p1")
        assert sat == {"rp-1": {"h1": frozenset(REQUIRED)}}
        dims, _ = program_obligation_dimensions(
            [{"program_id": "rp-1", "evidence_requirements": [req("h1")],
              "hypotheses": [], "discrimination_requirements": []}],
      
            satisfactions=sat)
        assert dims["evidence_gap_closure"] is DimensionLevel.LOW

    def test_second_requirement_not_satisfied_by_firsts_links(self, program_with_requirement):
        # Only h1 has links — h2 must stay outstanding (per-hypothesis).
        repo = ProgramRequirementSatisfactionRepository(program_with_requirement)
        for typ in REQUIRED:
            add_verdict(program_with_requirement, f"art-{typ}")
            repo.record(project_id="p1", program_id="rp-1",
                        requirement_ref="h1", artifact_id=f"art-{typ}")
        sat = repo.satisfaction_types_by_requirement("p1")
        dims, _ = program_obligation_dimensions(
            [{"program_id": "rp-1",
              "evidence_requirements": [req("h1"), req("h2")],
              "hypotheses": [], "discrimination_requirements": []}],
            satisfactions=sat)
        assert dims["evidence_gap_closure"] is DimensionLevel.MEDIUM  # h2 only

    def test_forged_link_without_verdict_cannot_fake_satisfaction(self, program_with_requirement):
        """M1/HR-02 — a forged satisfaction link (direct SQL, bypassing the
        write path) whose artifact carries NO validation verdict contributes
        NOTHING to the derivation: the read reports only verdict-covered
        classes, so the requirement stays outstanding (the T-EMPTY-CLIMB
        shape — content absent, no climb)."""
        insert_artifact(program_with_requirement, "art-fc",
                        "pre_registered_experiment")
        program_with_requirement.execute(
            """INSERT INTO program_requirement_satisfactions
               (satisfaction_id, project_id, program_id, requirement_ref,
                artifact_id, created_at)
               VALUES (?, 'p1', 'rp-1', 'h1', 'art-fc', ?)""",
            ("ss_forged", CLOCK),
        )
        sat = ProgramRequirementSatisfactionRepository(
            program_with_requirement).satisfaction_types_by_requirement("p1")
        # Even a RIGHT-CLASS forged link without a verdict is refused — the
        # read reports nothing (no verdict-covered row survives the JOIN).
        assert sat == {}
        dims, _ = program_obligation_dimensions(
            [{"program_id": "rp-1", "evidence_requirements": [req("h1")],
              "hypotheses": [], "discrimination_requirements": []}],
            satisfactions=sat)
        assert dims["evidence_gap_closure"] is not DimensionLevel.LOW

    def test_tampered_verdict_input_hash_loses_coverage(self, db):
        """M1/HR-02 — a verdict whose input-hash no longer matches the
        artifact's content hash (tampered) loses coverage at read time: the
        read re-verifies against the artifact row, never trusting the stored
        field."""
        insert_program(db, "rp-1", evidence=[req("h1")])
        insert_artifact(db, "art-x", "pre_registered_experiment")
        add_verdict(db, "art-x")
        db.execute(
            "UPDATE validation_verdicts SET input_hash = 'forged-hash' "
            "WHERE artifact_id = 'art-x'")
        # The write path refuses (rule 5 re-verifies) and the read excludes.
        repo = ProgramRequirementSatisfactionRepository(db)
        with pytest.raises(
                RequirementSatisfactionError, match="validation verdict"):
            repo.record(project_id="p1", program_id="rp-1",
                        requirement_ref="h1", artifact_id="art-x")
        assert repo.satisfaction_types_by_requirement("p1") == {}

    def test_satisfactions_are_project_scoped(self, db):
        ProjectRepository(db).create("other", "Other")
        insert_program(db, "rp-1", evidence=[req("h1")])
        insert_program(db, "rp-other", evidence=[req("h1")], project="other")
        insert_artifact(db, "art-x", "statistical_analysis", project="other")
        add_verdict(db, "art-x", project="other")
        repo = ProgramRequirementSatisfactionRepository(db)
        repo.record(project_id="other", program_id="rp-other",
                    requirement_ref="h1", artifact_id="art-x")
        assert repo.satisfaction_types_by_requirement("p1") == {}
        assert repo.satisfaction_types_by_requirement("other") == {
            "rp-other": {"h1": frozenset({"statistical_analysis"})}}


# ── controller integration: per-requirement links drive the ordering ──

class TestControllerIntegration:
    def test_satisfied_program_task_orders_before_unlinked(self, db):
        insert_program(db, "rp-1", evidence=[req("h1")])
        for typ in REQUIRED:
            insert_artifact(db, f"art-{typ}", typ)
            add_verdict(db, f"art-{typ}")
        repo = ProgramRequirementSatisfactionRepository(db)
        for typ in REQUIRED:
            repo.record(project_id="p1", program_id="rp-1",
                        requirement_ref="h1", artifact_id=f"art-{typ}")

        order: list[str] = []
        TaskRepository(db, clock=lambda: CLOCK).create(NodeContract(
            task_id="t-b", project_id="p1", task_type=NodeType.AGENT_TASK.value,
            idempotency_key="t-b", status=TaskStatus.PENDING.value,
            spec={"template": EXTRACT_TEMPLATE, "source_ref": "dataset_manifest:dm-1"},
            cost_class="LOW"))
        TaskRepository(db, clock=lambda: CLOCK).create(NodeContract(
            task_id="t-a", project_id="p1", task_type=NodeType.AGENT_TASK.value,
            idempotency_key="t-a", status=TaskStatus.PENDING.value,
            spec={"template": EXTRACT_TEMPLATE, "source_ref": "dataset_manifest:dm-1"},
            provenance=["research_program:rp-1"], cost_class="LOW"))

        def extract_fn(task, untrusted):
            order.append(task["task_id"])
            return extraction_draft_from_mapping({
                "source_ref": "dataset_manifest:dm-1",
                "claims": [{
                    "ref": "c1", "statement": f"Claim {task['task_id']}.",
                    "source_ref": "dataset_manifest:dm-1",
                    "support_state": "INFERRED", "span_ref": "s",
                    "claim_type": "causal",
                    # Step 4 / S-R2 (IDR-044): the regime dim resolves live,
                    # so the incidental tag must be the registered tag.
                    "context_tags": {"regime": "ICSS-v1:low-vol",
                                     "dataset_ref": "dm-1"},
                    "assumption_refs": []}],
                "assumptions": [],
                "extracted_by": "model_ref:c-tier-1", "schema_version": "2"})

        ctrl = Controller(db, project_id="p1", extract_fn=extract_fn,
                          clock=frozen_clock(CLOCK))
        result = ctrl.tick()
        # t-a is linked to a program whose obligation is satisfied → LOW beats
        # the unlinked task's NONE.
        assert order == ["t-a", "t-b"]
        assert result.ordering_policy_version == "task-eval-2026.1"


# ── adversarial-review regressions (F6/F8, 3fb91c6 → review) ──

class TestReviewFindings:
    def test_corrupt_program_row_refuses_link_cleanly(self, db):
        """F8 — a corrupt program row must refuse a satisfaction link with a
        domain error, never a raw JSONDecodeError traceback."""
        # rp-bad has invalid JSON in evidence_json (like the F5 dispatch-path
        # corruption, now on the write side).
        db.execute(
            """INSERT INTO research_programs
               (program_id, project_id, version, content_hash, supersedes_id,
                scope_ref, epistemic_objective, compiler_version,
                policy_version, schema_version, input_hash, hypothesis_json,
                prediction_json, discrimination_json, evidence_json, gate_json,
                methodology_json, task_graph_template_ref, produced_by, reason,
                created_at)
               VALUES (?, ?, 1, ?, NULL, 'b', 'o', 'c1', 'p1', '1', 'ih',
                       '[]', '[]', '[]', ?, '[]', '[]', NULL, 'director',
                       NULL, ?)""",
            ("rp-bad", "p1", "ch-bad", "{not json", CLOCK),
        )
        insert_artifact(db, "a1", "pre_registered_experiment")
        repo = ProgramRequirementSatisfactionRepository(db, frozen_clock(CLOCK))
        with pytest.raises(RequirementSatisfactionError) as ei:
            repo.record(project_id="p1", program_id="rp-bad",
                        requirement_ref="h1", artifact_id="a1")
        assert "corrupt" in str(ei.value)
        # And nothing was written.
        n = db.execute(
            "SELECT COUNT(*) FROM program_requirement_satisfactions"
        ).fetchone()[0]
        assert n == 0

    def test_record_has_no_freeform_reason(self, db):
        """F6 — record() accepts no free-form reason: the row itself is the
        audit (append-only, content-derived identity)."""
        insert_program(db, "rp-1", evidence=[{
            "claim_ref": "h1", "ladder_target": "CONFIRMED",
            "required_artifacts": list(REQUIRED),
        }])
        insert_artifact(db, "a1", "pre_registered_experiment")
        insert_artifact(db, "a2", "statistical_analysis")
        add_verdict(db, "a1")
        add_verdict(db, "a2")
        repo = ProgramRequirementSatisfactionRepository(db, frozen_clock(CLOCK))
        row = repo.record(project_id="p1", program_id="rp-1",
                          requirement_ref="h1", artifact_id="a1")
        repo.record(project_id="p1", program_id="rp-1",
                    requirement_ref="h1", artifact_id="a2")
        # The persisted row carries exactly the triple + identity + clock.
        assert set(row) == {"satisfaction_id", "project_id", "program_id",
                            "requirement_ref", "artifact_id", "created_at"}
        assert "reason" not in row
        cols = [c[1] for c in db.execute(
            "PRAGMA table_info(program_requirement_satisfactions)")]
        assert "reason" not in cols


class TestEmptyArtifactNeverSatisfies:
    """Step-0 mandatory regression fixture (pre-P4 readiness brief §H /
    M1): the cleanest demonstration that the satisfaction contract
    validates CONTENT, not merely structure —

        empty artifact + correct required artifact type
                     + otherwise valid metadata
                     → NOT SATISFIED

    The M1/HR-02 contract gates every satisfaction link on a
    dereferenceable PASS content-validation verdict whose input-hash
    covers the artifact's content hash (rule 5). An empty artifact that
    has never been content-validated (or whose content FAILED validation)
    is therefore refused — the correct class alone is never enough.

    Delegated obligation (recorded, not pinned): the verdict SUBSTRATE
    (``ValidationVerdictRepository.record``) trusts the issuing validator
    — it records a PASS without inspecting bytes, because no production
    verdict issuer exists yet. Content non-emptiness is the obligation of
    the future content validator that issues verdicts (Step 9 era); a
    forged/buggy PASS on empty content is a validator-layer failure, not
    a satisfaction-layer one. The satisfaction layer's guarantee — no
    verdict (or a FAIL verdict) ⇒ no satisfaction — is pinned here.
    """

    def _insert_empty_artifact(self, db, artifact_id="art-empty"):
        db.execute(
            """INSERT INTO artifacts
               (artifact_id, project_id, task_id, artifact_type,
                content_hash, size_bytes, storage_path, producer,
                metadata_json, created_at)
               VALUES (?, 'p1', NULL, 'pre_registered_experiment', ?, 0,
                       'x', 't', '{}', ?)""",
            (artifact_id, f"ch-{artifact_id}", CLOCK),
        )
        return artifact_id

    def test_empty_artifact_correct_type_no_verdict_not_satisfied(
            self, program_with_requirement):
        """Empty + correct required type + valid metadata + NO content-
        validation verdict → refused at rule 5; nothing written; the
        derivation reports nothing."""
        db = program_with_requirement
        self._insert_empty_artifact(db)
        repo = ProgramRequirementSatisfactionRepository(
            db, clock=frozen_clock(CLOCK))
        with pytest.raises(RequirementSatisfactionError) as ei:
            repo.record(project_id="p1", program_id="rp-1",
                        requirement_ref="h1", artifact_id="art-empty")
        assert "PASS validation verdict" in str(ei.value)
        n = db.execute(
            "SELECT COUNT(*) FROM program_requirement_satisfactions"
        ).fetchone()[0]
        assert n == 0
        assert repo.satisfaction_types_by_requirement("p1") == {}

    def test_empty_artifact_fail_verdict_not_satisfied(
            self, program_with_requirement):
        """Empty + correct type + a FAIL content-validation verdict →
        still refused: only PASS verdicts cover, and a failed content
        validation can never satisfy an obligation."""
        db = program_with_requirement
        self._insert_empty_artifact(db)
        add_verdict(db, "art-empty", verdict="FAIL")
        repo = ProgramRequirementSatisfactionRepository(
            db, clock=frozen_clock(CLOCK))
        with pytest.raises(RequirementSatisfactionError):
            repo.record(project_id="p1", program_id="rp-1",
                        requirement_ref="h1", artifact_id="art-empty")
        n = db.execute(
            "SELECT COUNT(*) FROM program_requirement_satisfactions"
        ).fetchone()[0]
        assert n == 0
        assert repo.satisfaction_types_by_requirement("p1") == {}

    def test_empty_artifact_not_counted_even_if_linked_class_matches(
            self, program_with_requirement):
        """The derivation never reports the empty artifact's class: with
        no covering PASS verdict, ``satisfaction_types_by_requirement``
        contributes nothing for it, even though its artifact_type is
        exactly a required class."""
        db = program_with_requirement
        self._insert_empty_artifact(db)
        repo = ProgramRequirementSatisfactionRepository(
            db, clock=frozen_clock(CLOCK))
        facts = repo.satisfaction_types_by_requirement("p1")
        # no requirement is satisfied by the empty artifact's class
        assert facts.get("rp-1", {}).get("h1", frozenset()) == frozenset()
