"""Q-05 persistence-slice golden fixtures (design §4 + fail-closed matrix).

Proves the 10 acceptance criteria of ``hermes_q05_persistence_slice_design.md``
against real SQLite, plus the fail-closed matrix and adversarial attacks:

1. ADMITTED classification persists: row + ``cites``(evidence) +
   ``derived_from``(task) edges, atomic.
2. Identity re-derivation: forged ``claimed`` classification →
   ``FailureClassificationIntegrityError``, nothing written.
3. Crash-retry: identical content → REUSED, no duplicate rows/edges.
4. Reclassification under a new classifier version → new row, old row intact,
   both queryable.
5. Task binding: foreign / stale / not-RUNNING producing task → refused.
6. Cross-project: classification of p2 evidence under p1 → refused.
7. ENVIRONMENT_MISMATCH write: the resolver-resolver asymmetry is LIFTED —
   Step 4 / S-R2 wires the regime resolver to the closed registry (both
   layers admit the registered tag; the old substrate-admits/write-refuses
   asymmetry is gone, IDR-044).
8. R02 cross-type reuse → refused loudly.
9. D3 dereference contract: ``failure_classification_ref`` resolves only to a
   project-scoped ``failure_classification`` row.
10. Advisory boundary (D8): the classification is unreachable by any evidence
    resolver (structural scan) + zero new events (D7).

Plus: non-ADMITTED drafts, missing/wrong class citations, FRAMING_ERROR
without scope mutation, RESOURCE_CONSTRAINT without budget/task mutation,
IMPLEMENTATION_FAILURE without auto-replacement, evidence owned by a
different task, a classification cited as evidence, stale evidence, and the
D8 read surface.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from hermes.core.node import AgentProfile, NodeContract, NodeType
from hermes.core.task_status import TaskStatus
from hermes.persistence.database import connect
from hermes.persistence.failure_classifications import (
    DIGEST_VERSION,
    FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
    FAILURE_CLASSIFICATION_REF_PREFIX,
    FailureClassificationBindingError,
    FailureClassificationError,
    FailureClassificationIntegrityError,
    FailureClassificationRepository,
    classifications_digest,
)
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    EventRepository,
    ProjectRepository,
    ResearchProgramRepository,
    TaskRepository,
)
from hermes.research.controller import Controller
from hermes.research.failure_classification import (
    FAILURE_CLASS_SCHEMA_VERSION,
    ConditionType,
    FailureClass,
    FailureClassification,
    FailureClassificationDraft,
    FalsificationRecord,
    ResourceGap,
    classify_failure,
    permitted_actions_for,
)
from hermes.research.programs import compile_from_payload

MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src" / "hermes" / "persistence" / "failure_classifications.py"
)

TS = "2026-01-01T00:00:00.000000+00:00"


# ── fixtures ──

def _insert_brief(conn, brief_id, project_id, content_hash, scope_text,
                  version=1):
    conn.execute(
        """INSERT INTO scope_briefs
           (brief_id, project_id, version, content_hash, supersedes_id,
            scope_text_json, rationale, created_at, frozen_at)
           VALUES (?, ?, ?, ?, NULL, ?, NULL, ?, ?)""",
        (brief_id, project_id, version, content_hash,
         json.dumps(scope_text), TS, TS),
    )


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Test")
    ProjectRepository(conn).create("p2", "Other")
    _insert_brief(conn, "brief-1", "p1", "briefhash1", {
        "core_question": "Does momentum predict XAUUSD returns?",
        "constraints": ["icss-v1 regime only"],
    })
    _insert_brief(conn, "brief-2", "p2", "briefhash2", {
        "core_question": "Other project question",
    })
    # OQ-1: a NON-structured brief — the scope-field resolver must fail closed
    _insert_brief(conn, "brief-flat", "p1", "briefhash3",
                  "unstructured prose", version=2)
    yield conn
    conn.close()


@pytest.fixture
def program(db):
    """A COMPILED ResearchProgram for p1 (H1/H0, predictions P1/P0,
    methodology_constraints ["icss-v1"]), compiled against brief-1."""
    payload = {
        "scope_ref": "brief-1",
        "epistemic_objective": "Establish whether momentum predicts XAUUSD returns",
        "hypotheses": [
            {"ref": "H1", "ladder_target": "SUPPORTED",
             "falsification_condition": "returns do not follow momentum",
             "rival_of": None, "rival_status": None},
            {"ref": "H0", "ladder_target": "SPECULATIVE",
             "falsification_condition": "null hypothesis",
             "rival_of": "H1", "rival_status": "ACTIVE"},
        ],
        "predictions": [
            {"ref": "P1", "claim_ref": "H1", "observable": "20d_returns",
             "direction": "FOR", "condition": "trend_up"},
            {"ref": "P0", "claim_ref": "H0", "observable": "20d_returns",
             "direction": "NEUTRAL", "condition": "trend_up"},
        ],
        "discrimination_requirements": [
            {"ref": "D1", "hypothesis_a": "H1", "hypothesis_b": "H0",
             "observable": "20d_returns",
             "expected_difference": "H1 positive, H0 zero",
             "required_condition": "trend_up", "measurement_method_ref": "method-1"},
        ],
        "methodology_constraints": ["icss-v1"],
        "task_graph_template_ref": None,
        "compiler_version": "1.0.0",
        "policy_version": "rp-2026.1",
        "schema_version": "1",
        "supersedes_ref": None,
    }
    result = compile_from_payload(
        payload, project_id="p1", scope_content_hash="briefhash1",
        superseded_program_ids=frozenset())
    assert result.compiled, [
        f"{e.code}@{e.field_path}" for e in result.errors]
    return ResearchProgramRepository(db).record(
        "p1", result, produced_by="director", reason="fixture")


# ── builders ──

def seed_task(db, task_id, project_id="p1",
              status=TaskStatus.RUNNING) -> str:
    """Create a task and move it to the requested status (RUNNING default)."""
    node = NodeContract(
        task_id=task_id,
        project_id=project_id,
        task_type=NodeType.AGENT_TASK.value,
        profile=AgentProfile.RESEARCHER.value,
        idempotency_key=f"idem-{task_id}",
        iteration=1,
        spec={},
        inputs=[],
        outputs=[],
        dependencies=[],
        provenance=[],
        cost_class="small",
        concurrency_group=None,
        max_retries=3,
        parent_task_id=None,
    )
    tr = TaskRepository(db)
    tr.create(node)
    tr.transition_status(task_id, TaskStatus.READY, caused_by="test")
    if status in (TaskStatus.RUNNING, TaskStatus.SUCCEEDED):
        tr.transition_status(task_id, TaskStatus.RUNNING, caused_by="test")
    if status is TaskStatus.SUCCEEDED:
        tr.transition_status(task_id, TaskStatus.SUCCEEDED, caused_by="test")
    return task_id


def seed_evidence(db, task_id, *hashes, project_id="p1",
                  artifact_type="validation") -> None:
    """Evidence chain: task →(derived_from) outcome →(derived_from) evidence
    rows — the two-hop reachability the write path requires (D4)."""
    outcome_id = f"outcome-{task_id}"
    db.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type, content_hash,
            size_bytes, storage_path, producer, metadata_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (outcome_id, project_id, task_id, "falsification_outcome",
         f"oh-{task_id}", 0, "inline://falsification_outcome",
         "falsification", "{}", TS),
    )
    db.execute(
        """INSERT INTO provenance_edges
           (artifact_id, upstream_id, edge_type, created_at)
           VALUES (?, ?, ?, ?)""",
        (outcome_id, task_id, "derived_from", TS),
    )
    for h in hashes:
        db.execute(
            """INSERT INTO artifacts
               (artifact_id, project_id, task_id, artifact_type, content_hash,
                size_bytes, storage_path, producer, metadata_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (f"art-{h}", project_id, task_id, artifact_type, h, 0,
             f"inline://{artifact_type}", "falsification", "{}", TS),
        )
        db.execute(
            """INSERT INTO provenance_edges
               (artifact_id, upstream_id, edge_type, created_at)
               VALUES (?, ?, ?, ?)""",
            (f"art-{h}", outcome_id, "derived_from", TS),
        )


def rec(program_ref, project_id="p1", hypothesis_ref="H1",
        evidence=("validation:ev1",)) -> FalsificationRecord:
    return FalsificationRecord(
        project_id=project_id,
        hypothesis_ref=hypothesis_ref,
        program_ref=program_ref,
        falsifying_evidence_refs=evidence,
    )


def draft(failure_class, *, evidence=("validation:ev1",),
          **kw) -> FailureClassificationDraft:
    base = {
        "failure_class": failure_class,
        "explanation": "the falsifying evidence contradicts the declared frame",
        "evidence_refs": evidence,
        "proposed_by": "ADVERSARY",
        "classifier_version": "q05-2026.1",
    }
    base.update(kw)
    return FailureClassificationDraft(**base)


def constraint_draft(**kw):
    return draft(FailureClass.DECLARED_CONSTRAINT_VIOLATION.value,
                 constraint_ref=kw.pop("constraint_ref",
                                       "hypothesis:H1:falsification_condition"),
                 **kw)


# ── §4 acceptance fixtures ──

class TestAcceptance1Persists:
    def test_row_edges_atomic(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1", "ev2")
        repo = FailureClassificationRepository(db)
        r = repo.record(
            "p1", rec(program["program_id"],
                      evidence=("validation:ev1", "validation:ev2")),
            draft(FailureClass.DECLARED_CONSTRAINT_VIOLATION.value,
                  evidence=("validation:ev1", "validation:ev2"),
                  constraint_ref="hypothesis:H1:falsification_condition"),
            producing_task_id="t1")
        assert r["decision"] == "NEW"
        rows = repo.classifications_for_project("p1")
        assert len(rows) == 1
        row = rows[0]
        assert row["artifact_type"] == FAILURE_CLASSIFICATION_ARTIFACT_TYPE
        assert row["content_hash"] == r["content_hash"]
        assert row["project_id"] == "p1"
        assert row["task_id"] == "t1"
        assert row["producer"] == "falsification:t1"
        assert row["storage_path"] == "inline://failure_classification"
        meta = row["metadata"]
        assert meta["failure_class"] == "DECLARED_CONSTRAINT_VIOLATION"
        assert set(meta["evidence_refs"]) == {"validation:ev1", "validation:ev2"}
        assert meta["constraint_ref"] == "hypothesis:H1:falsification_condition"
        assert meta["classifier_version"] == "q05-2026.1"
        assert set(meta["permitted_actions"]) == {
            "REJECT_BRANCH", "REVIEW_DOWNSTREAM_IMPACT"}
        assert meta["requires_human_confirmation"] is False
        assert meta["proposed_by"] == "ADVERSARY"
        assert list(meta["falsifying_evidence_refs"]) == [
            "validation:ev1", "validation:ev2"]
        edges = db.execute(
            "SELECT edge_type, upstream_id FROM provenance_edges "
            "WHERE artifact_id = ? ORDER BY edge_type, upstream_id",
            (row["artifact_id"],)).fetchall()
        assert {e["edge_type"] for e in edges} == {"cites", "derived_from"}
        cited = {e["upstream_id"] for e in edges if e["edge_type"] == "cites"}
        assert cited == {"validation:ev1", "validation:ev2"}
        derived = [e["upstream_id"] for e in edges
                   if e["edge_type"] == "derived_from"]
        assert derived == ["t1"]


class TestAcceptance2ForgedIdentity:
    def test_forged_claimed_hash_refused(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        # A "claimed" classification with DIFFERENT content (tampered
        # classifier_version) — the write path re-derives and refuses.
        forged = classify_failure(
            rec(program["program_id"]),
            constraint_draft(classifier_version="q05-2026.FORGED"),
            evidence_resolver=lambda p, r: True,
            constraint_resolver=lambda p, pr, r: True,
        )
        assert forged.admitted
        with pytest.raises(FailureClassificationIntegrityError) as exc:
            repo.record(
                "p1", rec(program["program_id"]),
                constraint_draft(),
                producing_task_id="t1", claimed=forged.classification)
        assert "re-derived" in str(exc.value)
        assert repo.classifications_for_project("p1") == []
        assert db.execute(
            "SELECT COUNT(*) AS n FROM provenance_edges "
            "WHERE artifact_id LIKE 'fc_%'"
        ).fetchone()["n"] == 0


class TestAcceptance3CrashRetry:
    def test_identical_content_reuses(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        rec_ = rec(program["program_id"])
        dra = constraint_draft()
        r1 = repo.record("p1", rec_, dra, producing_task_id="t1")
        r2 = repo.record("p1", rec_, dra, producing_task_id="t1")
        assert r2["decision"] == "REUSED"
        assert r2["classification_id"] == r1["classification_id"]
        assert len(repo.classifications_for_project("p1")) == 1
        n_edges = db.execute(
            "SELECT COUNT(*) AS n FROM provenance_edges "
            "WHERE artifact_id = ?",
            (r1["classification_id"],)).fetchone()["n"]
        assert n_edges == 2  # cites + derived_from — no duplicates


class TestAcceptance4Reclassification:
    def test_new_classifier_version_new_row(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        v1 = repo.record(
            "p1", rec(program["program_id"]),
            constraint_draft(classifier_version="q05-2026.1"),
            producing_task_id="t1")
        v2 = repo.record(
            "p1", rec(program["program_id"]),
            constraint_draft(classifier_version="q05-2026.2"),
            producing_task_id="t1")
        assert v2["decision"] == "NEW"
        assert v2["classification_id"] != v1["classification_id"]
        rows = repo.classifications_for_project("p1")
        assert len(rows) == 2
        versions = {row["metadata"]["classifier_version"] for row in rows}
        assert versions == {"q05-2026.1", "q05-2026.2"}
        old = next(row for row in rows
                   if row["metadata"]["classifier_version"] == "q05-2026.1")
        assert old["content_hash"] == v1["content_hash"]
        assert old["metadata"]["failure_class"] == "DECLARED_CONSTRAINT_VIOLATION"


class TestAcceptance5TaskBinding:
    def test_foreign_stale_not_running_refused(self, db, program):
        seed_task(db, "t1")  # the evidence chain needs its producing task
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        dra = constraint_draft()
        # (a) nonexistent task
        with pytest.raises(FailureClassificationBindingError):
            repo.record("p1", rec(program["program_id"]), dra,
                        producing_task_id="nope")
        # (b) foreign-project task
        seed_task(db, "t2", project_id="p2")
        with pytest.raises(FailureClassificationBindingError):
            repo.record("p1", rec(program["program_id"]), dra,
                        producing_task_id="t2")
        # (c) not RUNNING
        seed_task(db, "t3", status=TaskStatus.SUCCEEDED)
        with pytest.raises(FailureClassificationBindingError):
            repo.record("p1", rec(program["program_id"]), dra,
                        producing_task_id="t3")
        assert repo.classifications_for_project("p1") == []


class TestAcceptance6CrossProject:
    def test_p2_evidence_under_p1_refused(self, db, program):
        seed_task(db, "t2", project_id="p2")
        seed_evidence(db, "t2", "evX", project_id="p2")
        repo = FailureClassificationRepository(db)
        dra = draft(FailureClass.DECLARED_CONSTRAINT_VIOLATION.value,
                    evidence=("validation:evX",),
                    constraint_ref="hypothesis:H1:falsification_condition")
        with pytest.raises(FailureClassificationError) as exc:
            repo.record("p1", rec(program["program_id"]), dra,
                        producing_task_id="t2")
        assert "non-ADMITTED" in str(exc.value)
        assert repo.classifications_for_project("p1") == []


class TestAcceptance7EnvironmentMismatch:
    def test_registered_tag_admitted_both_layers(self, db, program):
        """Step 4 / S-R2 (IDR-044): the asymmetry is LIFTED — the regime
        resolver is wired to the closed registry, so a registered versioned
        tag admits at BOTH layers (the old substrate-admits/write-refuses
        boundary is gone)."""
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        dra = draft(FailureClass.ENVIRONMENT_MISMATCH.value,
                    regime_ref="ICSS-v1:low-vol")
        # registered tag admits at the substrate layer...
        sub = classify_failure(
            rec(program["program_id"]), dra,
            evidence_resolver=lambda p, r: True,
            regime_resolver=lambda p, r: True)
        assert sub.admitted
        # ...and at the write path (resolver wired to the registry).
        r = repo.record("p1", rec(program["program_id"]), dra,
                        producing_task_id="t1")
        assert r["decision"] == "NEW"
        meta = repo.classifications_for_project("p1")[0]["metadata"]
        assert meta["failure_class"] == "ENVIRONMENT_MISMATCH"
        assert meta["regime_ref"] == "ICSS-v1:low-vol"

    def test_unregistered_versioned_tag_refused_both_layers(self, db, program):
        """A well-formed versioned tag whose (version, id) pair is NOT
        registered does not resolve (globally) — the write path refuses
        (non-ADMITTED, nothing written)."""
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        assert repo._regime_resolver("p1", "ICSS-v1:high-vol") is False
        dra = draft(FailureClass.ENVIRONMENT_MISMATCH.value,
                    regime_ref="ICSS-v1:high-vol")
        with pytest.raises(FailureClassificationError) as exc:
            repo.record("p1", rec(program["program_id"]), dra,
                        producing_task_id="t1")
        assert "non-ADMITTED" in str(exc.value)
        assert repo.classifications_for_project("p1") == []

    def test_bare_id_refused_both_layers(self, db, program):
        """The bare/unversioned form never regains admission: a bare ID has
        no version, so it does not resolve (UNVERSIONED discipline)."""
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        assert repo._regime_resolver("p1", "low-vol") is False
        dra = draft(FailureClass.ENVIRONMENT_MISMATCH.value,
                    regime_ref="low-vol")
        with pytest.raises(FailureClassificationError):
            repo.record("p1", rec(program["program_id"]), dra,
                        producing_task_id="t1")
        assert repo.classifications_for_project("p1") == []

    def test_forged_claimed_identity_dies_at_boundary(self, db, program):
        """C1 (S-R1 audit F-3 / A2 precedent): a caller-authored 'claimed'
        classification with a fabricated identity cannot preempt the re-run
        — the write path re-runs the substrate with the wired resolver
        FIRST; a claimed identity for a draft whose regime does not resolve
        dies at the re-run (FailureClassificationError) BEFORE any claimed
        comparison, and the forged object is never consulted."""
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        dra = draft(FailureClass.ENVIRONMENT_MISMATCH.value,
                    regime_ref="ICSS-v1:trend")  # unregistered pair
        forged = FailureClassification(
            classification_id="fc_forged00000000000000000000",
            schema_version=FAILURE_CLASS_SCHEMA_VERSION,
            classifier_version="forged-2026",
            project_id="p1",
            hypothesis_ref="H1",
            program_ref=program["program_id"],
            failure_class=FailureClass.ENVIRONMENT_MISMATCH,
            contributing_factors=(),
            evidence_refs=(),
            constraint_ref=None,
            failed_mechanism_ref=None,
            regime_ref="ICSS-v1:trend",
            resource_gap=None,
            scope_brief_ref=None,
            scope_brief_field=None,
            explanation="forged",
            proposed_by="forged",
            condition_type=ConditionType.ACCIDENTAL,
            permitted_actions=(),
            requires_human_confirmation=False,
            content_hash="forged000000000000000000000000000000",
        )
        with pytest.raises(FailureClassificationError):
            repo.record("p1", rec(program["program_id"]), dra,
                        claimed=forged, producing_task_id="t1")
        assert repo.classifications_for_project("p1") == []


class TestAcceptance8R02:
    def test_cross_type_reuse_refused(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        rec_ = rec(program["program_id"])
        dra = constraint_draft()
        # the deterministic content hash — resolver behavior never enters the
        # identity (only the verdict), so any admission yields the same hash
        probe = classify_failure(
            rec_, dra,
            evidence_resolver=lambda p, r: True,
            constraint_resolver=lambda p, pr, r: True)
        assert probe.admitted
        db.execute(
            """INSERT INTO artifacts
               (artifact_id, project_id, task_id, artifact_type, content_hash,
                size_bytes, storage_path, producer, metadata_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("art_bogus", "p1", "t1", "source_result",
             probe.classification.content_hash, 0,
             "inline://source_result", "source", "{}", TS),
        )
        with pytest.raises(FailureClassificationIntegrityError) as exc:
            repo.record("p1", rec_, dra, producing_task_id="t1")
        assert "different artifact type" in str(exc.value)
        assert "R02" in str(exc.value)
        assert repo.classifications_for_project("p1") == []


class TestAcceptance9Dereference:
    def test_ref_resolves_only_project_scoped_row(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        r = repo.record("p1", rec(program["program_id"]),
                        constraint_draft(), producing_task_id="t1")
        ref = f"{FAILURE_CLASSIFICATION_REF_PREFIX}{r['content_hash']}"
        assert repo.dereference_failure_classification_ref("p1", ref) is True
        assert repo.dereference_failure_classification_ref(
            "p1", "failure_classification:nope") is False
        assert repo.dereference_failure_classification_ref("p2", ref) is False
        assert repo.dereference_failure_classification_ref(
            "p1", "bogus:ref") is False
        assert repo.dereference_failure_classification_ref(
            "p1", "failure_classification:") is False


class TestAcceptance10AdvisoryBoundary:
    def test_no_events_and_no_foreign_writes(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        events_before = EventRepository(db).count()
        repo.record("p1", rec(program["program_id"]),
                    constraint_draft(), producing_task_id="t1")
        # D7 — zero new events
        assert EventRepository(db).count() == events_before
        # D8 — structural scan: the module's ONLY writes are the artifact row
        # + provenance edges; it never writes scope/tasks/programs/events and
        # never imports the gateway/intent/event machinery.
        src = MODULE_PATH.read_text(encoding="utf-8")
        for forbidden in (
                "INSERT INTO scope_briefs", "INSERT INTO tasks",
                "INSERT INTO research_programs", "INSERT INTO events",
                "UPDATE scope_briefs", "UPDATE tasks",
                "UPDATE research_programs", "DELETE FROM"):
            assert forbidden not in src, forbidden
        assert "self._artifacts.record(" in src  # D1: existing repository
        assert "INSERT OR IGNORE INTO provenance_edges" in src
        for forbidden in (
                "from hermes.research.gateway", "from hermes.core.intents",
                "from hermes.core.events", "import gateway", "import intents"):
            assert forbidden not in src, forbidden

    def test_classification_never_evidence(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        r1 = repo.record("p1", rec(program["program_id"]),
                         draft(FailureClass.UNKNOWN.value),
                         producing_task_id="t1")
        # the resolver refuses a failure_classification ref outright (D8)
        ref = f"{FAILURE_CLASSIFICATION_REF_PREFIX}{r1['content_hash']}"
        assert repo._evidence_resolver("p1", ref) is False
        # and a draft citing it as falsifying evidence is refused
        rec2 = FalsificationRecord(
            project_id="p1", hypothesis_ref="H1",
            program_ref=program["program_id"],
            falsifying_evidence_refs=(ref,))
        with pytest.raises(FailureClassificationError) as exc:
            repo.record(
                "p1", rec2,
                draft(FailureClass.DECLARED_CONSTRAINT_VIOLATION.value,
                      evidence=(ref,),
                      constraint_ref="hypothesis:H1:falsification_condition"),
                producing_task_id="t1")
        assert "non-ADMITTED" in str(exc.value)
        assert len(repo.classifications_for_project("p1")) == 1


# ── fail-closed matrix + adversarial ──

class TestRejectedDrafts:
    def test_no_evidence_for_evidence_required_class(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        with pytest.raises(FailureClassificationError):
            repo.record(
                "p1", rec(program["program_id"]),
                draft(FailureClass.DECLARED_CONSTRAINT_VIOLATION.value,
                      evidence=(),
                      constraint_ref="hypothesis:H1:falsification_condition"),
                producing_task_id="t1")
        assert repo.classifications_for_project("p1") == []

    def test_missing_class_citation(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        # DECLARED_CONSTRAINT_VIOLATION without a constraint ref
        with pytest.raises(FailureClassificationError):
            repo.record(
                "p1", rec(program["program_id"]),
                draft(FailureClass.DECLARED_CONSTRAINT_VIOLATION.value),
                producing_task_id="t1")

    def test_constraint_ref_wrong_object(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        with pytest.raises(FailureClassificationError):
            repo.record(
                "p1", rec(program["program_id"]),
                constraint_draft(
                    constraint_ref="hypothesis:NOPE:falsification_condition"),
                producing_task_id="t1")

    def test_mechanism_ref_wrong_object(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        with pytest.raises(FailureClassificationError):
            repo.record(
                "p1", rec(program["program_id"]),
                draft(FailureClass.IMPLEMENTATION_FAILURE.value,
                      failed_mechanism_ref="prediction:NOPE"),
                producing_task_id="t1")

    def test_foreign_program_ref(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        with pytest.raises(FailureClassificationError):
            repo.record(
                "p1", rec("rp_does_not_exist"),
                constraint_draft(), producing_task_id="t1")

    def test_evidence_outside_record(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1", "ev2")
        repo = FailureClassificationRepository(db)
        # draft cites ev2, but the record's falsifying evidence is only ev1
        with pytest.raises(FailureClassificationError):
            repo.record(
                "p1", rec(program["program_id"]),
                constraint_draft(evidence=("validation:ev2",)),
                producing_task_id="t1")

    def test_record_project_mismatch(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        with pytest.raises(FailureClassificationError) as exc:
            repo.record(
                "p2", rec(program["program_id"]),  # record is p1-scoped
                draft(FailureClass.UNKNOWN.value),
                producing_task_id="t1")
        assert "does not match" in str(exc.value)

    def test_stale_evidence_refused(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        db.execute("DELETE FROM artifacts WHERE content_hash = 'ev1'")
        db.execute("DELETE FROM provenance_edges "
                   "WHERE artifact_id = 'art-ev1' OR upstream_id = 'art-ev1'")
        repo = FailureClassificationRepository(db)
        with pytest.raises(FailureClassificationError) as exc:
            repo.record(
                "p1", rec(program["program_id"]),
                constraint_draft(), producing_task_id="t1")
        assert "non-ADMITTED" in str(exc.value)
        assert repo.classifications_for_project("p1") == []


class TestEvidenceOwnership:
    def test_evidence_owned_by_other_task(self, db, program):
        seed_task(db, "t1")
        seed_task(db, "t2")
        seed_evidence(db, "t1", "ev1")  # ev1 belongs to t1
        repo = FailureClassificationRepository(db)
        with pytest.raises(FailureClassificationBindingError) as exc:
            repo.record("p1", rec(program["program_id"]),
                        constraint_draft(), producing_task_id="t2")
        assert "produced by task" in str(exc.value)
        assert repo.classifications_for_project("p1") == []

    def test_untyped_evidence_ref(self, db, program):
        seed_task(db, "t1")
        repo = FailureClassificationRepository(db)
        rec_ = FalsificationRecord(
            project_id="p1", hypothesis_ref="H1",
            program_ref=program["program_id"],
            falsifying_evidence_refs=("bare-ref",))
        with pytest.raises(FailureClassificationError):
            repo.record("p1", rec_,
                        constraint_draft(evidence=("bare-ref",)),
                        producing_task_id="t1")


class TestPerClassSemantics:
    def test_framing_error_persists_without_mutating_scope(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        before = db.execute(
            "SELECT scope_text_json FROM scope_briefs "
            "WHERE brief_id = 'brief-1'").fetchone()["scope_text_json"]
        r = repo.record(
            "p1", rec(program["program_id"]),
            draft(FailureClass.FRAMING_ERROR.value,
                  scope_brief_ref="brief-1",
                  scope_brief_field="core_question"),
            producing_task_id="t1")
        assert r["requires_human_confirmation"] is True
        row = repo.classifications_for_project("p1")[0]
        assert row["metadata"]["requires_human_confirmation"] is True
        assert row["metadata"]["scope_brief_ref"] == "brief-1"
        assert row["metadata"]["scope_brief_field"] == "core_question"
        assert set(row["metadata"]["permitted_actions"]) == {
            "ROUTE_TO_SCOPE_REVIEW"}
        after = db.execute(
            "SELECT scope_text_json FROM scope_briefs "
            "WHERE brief_id = 'brief-1'").fetchone()["scope_text_json"]
        assert after == before  # the brief is never mutated

    def test_framing_error_requires_scope_citation(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        # no scope citation → substrate rejects
        with pytest.raises(FailureClassificationError):
            repo.record(
                "p1", rec(program["program_id"]),
                draft(FailureClass.FRAMING_ERROR.value),
                producing_task_id="t1")
        # unstructured brief → scope resolver fails closed (OQ-1)
        with pytest.raises(FailureClassificationError):
            repo.record(
                "p1", rec(program["program_id"]),
                draft(FailureClass.FRAMING_ERROR.value,
                      scope_brief_ref="brief-flat",
                      scope_brief_field="core_question"),
                producing_task_id="t1")

    def test_resource_constraint_no_side_effects(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        tasks_before = db.execute(
            "SELECT COUNT(*) AS n FROM tasks").fetchone()["n"]
        progs_before = db.execute(
            "SELECT COUNT(*) AS n FROM research_programs").fetchone()["n"]
        r = repo.record(
            "p1", rec(program["program_id"]),
            draft(FailureClass.RESOURCE_CONSTRAINT.value,
                  resource_gap=ResourceGap(
                      resource_kind="tokens", observed=10.0,
                      required=50.0, unit="M")),
            producing_task_id="t1")
        assert r["decision"] == "NEW"
        assert db.execute(
            "SELECT COUNT(*) AS n FROM tasks").fetchone()["n"] == tasks_before
        assert db.execute(
            "SELECT COUNT(*) AS n FROM research_programs").fetchone()[
            "n"] == progs_before
        meta = repo.classifications_for_project("p1")[0]["metadata"]
        assert meta["resource_gap"] == {
            "resource_kind": "tokens", "observed": 10.0,
            "required": 50.0, "unit": "M"}
        status = db.execute(
            "SELECT status FROM tasks WHERE task_id = 't1'"
        ).fetchone()["status"]
        assert status == TaskStatus.RUNNING.value

    def test_resource_gap_not_a_deficit(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        with pytest.raises(FailureClassificationError):
            repo.record(
                "p1", rec(program["program_id"]),
                draft(FailureClass.RESOURCE_CONSTRAINT.value,
                      resource_gap=ResourceGap(
                          resource_kind="tokens", observed=60.0,
                          required=50.0, unit="M")),
                producing_task_id="t1")

    def test_implementation_failure_no_replacement(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        tasks_before = db.execute(
            "SELECT COUNT(*) AS n FROM tasks").fetchone()["n"]
        progs_before = db.execute(
            "SELECT COUNT(*) AS n FROM research_programs").fetchone()["n"]
        r = repo.record(
            "p1", rec(program["program_id"]),
            draft(FailureClass.IMPLEMENTATION_FAILURE.value,
                  failed_mechanism_ref="prediction:P1"),
            producing_task_id="t1")
        assert r["decision"] == "NEW"
        assert ("fc_" + r["content_hash"][:24], "validation:ev1", "cites") \
            in r["edges"]
        assert ("fc_" + r["content_hash"][:24], "t1", "derived_from") \
            in r["edges"]
        assert db.execute(
            "SELECT COUNT(*) AS n FROM tasks").fetchone()["n"] == tasks_before
        assert db.execute(
            "SELECT COUNT(*) AS n FROM research_programs").fetchone()[
            "n"] == progs_before
        meta = repo.classifications_for_project("p1")[0]["metadata"]
        assert set(meta["permitted_actions"]) == {
            "PROPOSE_MECHANISM_SUBSTITUTION"}

    def test_unknown_persists_without_evidence(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        r = repo.record("p1", rec(program["program_id"]),
                        draft(FailureClass.UNKNOWN.value, evidence=()),
                        producing_task_id="t1")
        assert r["decision"] == "NEW"
        edges = db.execute(
            "SELECT edge_type FROM provenance_edges WHERE artifact_id = ?",
            (r["classification_id"],)).fetchall()
        assert [e["edge_type"] for e in edges] == ["derived_from"]  # no cites
        meta = repo.classifications_for_project("p1")[0]["metadata"]
        assert meta["permitted_actions"] == ["ESCALATE_TO_DIRECTOR"]


class TestReadSurface:
    def test_classifications_for_evidence(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1", "ev2")
        repo = FailureClassificationRepository(db)
        repo.record("p1", rec(program["program_id"]),
                    draft(FailureClass.UNKNOWN.value, evidence=()),
                    producing_task_id="t1")
        repo.record(
            "p1", rec(program["program_id"],
                      evidence=("validation:ev1", "validation:ev2")),
            draft(FailureClass.DECLARED_CONSTRAINT_VIOLATION.value,
                  evidence=("validation:ev1", "validation:ev2"),
                  constraint_ref="hypothesis:H1:falsification_condition"),
            producing_task_id="t1")
        by_ev = repo.classifications_for_evidence("p1", "validation:ev1")
        assert len(by_ev) == 1
        assert by_ev[0]["metadata"]["failure_class"] == \
            "DECLARED_CONSTRAINT_VIOLATION"
        assert repo.classifications_for_evidence(
            "p1", "validation:missing") == []
        assert repo.classifications_for_evidence("p2", "validation:ev1") == []

    def test_methodology_constraint_and_hash_ref_styles(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        r1 = repo.record(
            "p1", rec(program["program_id"]),
            constraint_draft(constraint_ref="methodology_constraint:0"),
            producing_task_id="t1")
        assert r1["decision"] == "NEW"
        r2 = repo.record(
            "p1", rec(f"research_program:{program['content_hash']}"),
            draft(FailureClass.IMPLEMENTATION_FAILURE.value,
                  failed_mechanism_ref="prediction:P1"),
            producing_task_id="t1")
        assert r2["decision"] == "NEW"
        assert len(repo.classifications_for_project("p1")) == 2


# ── D8 consumption: the advisory digest + controller accessor ──

class TestDigest:
    def test_pure_deterministic_and_empty(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        repo.record("p1", rec(program["program_id"]), constraint_draft(),
                    producing_task_id="t1")
        rows = repo.classifications_for_project("p1")
        d1 = classifications_digest(rows)
        d2 = classifications_digest(rows)
        assert d1 == d2  # deterministic given identical input
        assert d1["digest_version"] == DIGEST_VERSION
        assert d1["integrity_status"] == "OK"
        assert d1["count"] == 1
        assert d1["errors"] == []
        entry = d1["items"][0]
        assert entry["failure_class"] == "DECLARED_CONSTRAINT_VIOLATION"
        assert entry["classifier_version"] == "q05-2026.1"
        assert entry["permitted_actions"] == [
            "REJECT_BRANCH", "REVIEW_DOWNSTREAM_IMPACT"]
        assert entry["requires_human_confirmation"] is False
        assert entry["evidence_refs"] == ["validation:ev1"]
        assert entry["failure_class_ref"].startswith(
            FAILURE_CLASSIFICATION_REF_PREFIX)
        # empty input — no corruption, nothing surfaced
        empty = classifications_digest([])
        assert empty["count"] == 0 and empty["items"] == []
        assert empty["integrity_status"] == "OK" and empty["errors"] == []

    def test_groups_by_hypothesis_and_sorts(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        repo.record("p1", rec(program["program_id"]), constraint_draft(),
                    producing_task_id="t1")
        repo.record("p1", rec(program["program_id"], hypothesis_ref="H2"),
                    draft(FailureClass.UNKNOWN.value, evidence=()),
                    producing_task_id="t1")
        d = classifications_digest(repo.classifications_for_project("p1"))
        assert sorted(i["hypothesis_ref"] for i in d["items"]) == ["H1", "H2"]
        assert ([i for i in d["items"]
                if i["hypothesis_ref"] == "H1"][0]["failure_class"] ==
                "DECLARED_CONSTRAINT_VIOLATION")
        assert [i for i in d["items"]
                if i["hypothesis_ref"] == "H2"][0]["failure_class"] == "UNKNOWN"

    def test_malformed_row_skipped_never_fails_open(self):
        rows = [
            {"artifact_id": "fc_bad", "artifact_type": "failure_classification",
             "content_hash": "h1", "metadata": "nope"},
            {"artifact_id": "fc_ok", "artifact_type": "failure_classification",
             "content_hash": "h2",
             "metadata": {"classification_id": "fc_ok",
                          "hypothesis_ref": "H1",
                          "failure_class": "UNKNOWN",
                          "classifier_version": "q05-2026.1",
                          "permitted_actions": ["ESCALATE_TO_DIRECTOR"],
                          "requires_human_confirmation": False,
                          "evidence_refs": []}},
        ]
        d = classifications_digest(rows)
        assert d["count"] == 1
        assert d["items"][0]["hypothesis_ref"] == "H1"
        # the malformed row is reported, never silently dropped
        assert d["integrity_status"] == "DEGRADED"
        assert d["errors"] == [{
            "artifact_id": "fc_bad", "code": "MALFORMED_METADATA",
            "detail": "row 'fc_bad' metadata is not a JSON object"}]

    def test_digest_function_is_pure(self):
        """Structural: the digest is a pure function — the module's ONLY
        writes remain the artifact row + provenance edges (no new write path
        crept in with the consumption surface)."""
        src = MODULE_PATH.read_text(encoding="utf-8")
        for forbidden in (
                "INSERT INTO scope_briefs", "INSERT INTO tasks",
                "INSERT INTO research_programs", "INSERT INTO events",
                "UPDATE scope_briefs", "UPDATE tasks",
                "UPDATE research_programs", "DELETE FROM"):
            assert forbidden not in src, forbidden


class TestControllerConsumption:
    def test_classification_proposals_read_only(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        repo.record("p1", rec(program["program_id"]), constraint_draft(),
                    producing_task_id="t1")
        artifacts_before = db.execute(
            "SELECT COUNT(*) AS n FROM artifacts").fetchone()["n"]
        edges_before = db.execute(
            "SELECT COUNT(*) AS n FROM provenance_edges").fetchone()["n"]
        events_before = EventRepository(db).count()

        ctl = Controller(db, project_id="p1")
        digest = ctl.classification_proposals()
        assert digest["count"] == 1
        entry = digest["items"][0]
        assert entry["failure_class"] == "DECLARED_CONSTRAINT_VIOLATION"
        assert entry["permitted_actions"] == [
            "REJECT_BRANCH", "REVIEW_DOWNSTREAM_IMPACT"]
        # read-only: nothing new written, task status untouched
        assert db.execute(
            "SELECT COUNT(*) AS n FROM artifacts").fetchone()["n"] \
            == artifacts_before
        assert db.execute(
            "SELECT COUNT(*) AS n FROM provenance_edges").fetchone()["n"] \
            == edges_before
        assert EventRepository(db).count() == events_before
        status = db.execute(
            "SELECT status FROM tasks WHERE task_id = 't1'"
        ).fetchone()["status"]
        assert status == TaskStatus.RUNNING.value

    def test_proposals_empty_when_none_recorded(self, db):
        ctl = Controller(db, project_id="p1")
        digest = ctl.classification_proposals()
        assert digest["count"] == 0
        assert digest["items"] == [] and digest["errors"] == []
        assert digest["integrity_status"] == "OK"

    def test_proposals_after_tick_still_read_only(self, db, program):
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        repo.record("p1", rec(program["program_id"]), constraint_draft(),
                    producing_task_id="t1")
        ctl = Controller(db, project_id="p1")
        ctl.tick()  # lock acquire/release cycle rebuilds the fenced repos
        digest = ctl.classification_proposals()
        assert digest["count"] == 1
        assert digest["integrity_status"] == "OK"
        # the fenced read after a tick wrote nothing
        assert db.execute(
            "SELECT COUNT(*) AS n FROM provenance_edges WHERE artifact_id "
            "LIKE 'fc_%'").fetchone()["n"] == 2  # cites + derived_from only


# ── independent-audit remediations (IDR-037 D8 boundary + digest integrity) ──

class TestAuditRemediations:
    def test_claim_cannot_cite_classification_as_source(self, db, program):
        """Fix A — the CONTRA write path's generic artifact dereference must
        refuse a `failure_classification:` ref: a classification is advisory
        metadata, never a source document (IDR-037 D8)."""
        from hermes.research.claims import (
            ExtractionDraft,
            ResearchClaimDraft,
            validate_extraction,
        )
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        r = repo.record("p1", rec(program["program_id"]),
                        draft(FailureClass.UNKNOWN.value, evidence=()),
                        producing_task_id="t1")
        fc_ref = f"{FAILURE_CLASSIFICATION_REF_PREFIX}{r['content_hash']}"
        claim = ResearchClaimDraft(
            ref="c1", statement="Alpha reduces beta.",
            source_ref=fc_ref, support_state="INFERRED",
            # claim-ground G10: no span on a non-readable carrier (the
            # classification ref is unverifiable). The write-path refusal this
            # test proves is unchanged: the classification is never a source.
            span_ref=None, claim_type="causal",
            context_tags={}, assumption_refs=())
        result = validate_extraction(ExtractionDraft(
            source_ref="task_evidence:run-1", claims=(claim,),
            assumptions=(), extracted_by="model_ref:golden-1",
            schema_version="2"))
        # the substrate admits (form-checked); the WRITE PATH must refuse —
        # the classification never dereferences as a claim source (Fix A).
        assert result.admitted
        with pytest.raises(Exception) as exc:
            from hermes.persistence.repositories import ClaimAssumptionRepository
            ClaimAssumptionRepository(db).record_extraction(
                "p1", result, producing_task_id="t1")
        assert "must dereference" in str(exc.value)

    def test_digest_recomputes_permitted_actions(self, db, program):
        """Fix B — the digest derives permitted_actions from the failure class
        via the ratified ACTION_MAP; tampered row metadata cannot make it
        surface actions the taxonomy does not permit."""
        import json as _json
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        r = repo.record("p1", rec(program["program_id"]),
                        draft(FailureClass.UNKNOWN.value, evidence=()),
                        producing_task_id="t1")
        # tamper: UNKNOWN row's metadata claims REJECT_BRANCH (not in map)
        db.execute(
            "UPDATE artifacts SET metadata_json = ? WHERE artifact_id = ?",
            (_json.dumps({
                "classification_id": r["classification_id"],
                "hypothesis_ref": "H1", "failure_class": "UNKNOWN",
                "classifier_version": "q05-2026.1",
                "permitted_actions": ["REJECT_BRANCH"],
                "requires_human_confirmation": False, "evidence_refs": []}),
             r["classification_id"]))
        d = classifications_digest(repo.classifications_for_project("p1"))
        entry = d["items"][0]
        # recomputed value surfaces; the stored mismatch is REPORTED
        assert entry["permitted_actions"] == ["ESCALATE_TO_DIRECTOR"]
        assert entry["integrity_flags"] == ["STORED_ACTIONS_MISMATCH"]
        assert d["integrity_status"] == "FLAGGED"
        # a corrupt failure_class row is reported, never fails the digest
        # open and never surfaces as a recommendation
        db.execute(
            "UPDATE artifacts SET metadata_json = ? WHERE artifact_id = ?",
            (_json.dumps({
                "classification_id": r["classification_id"],
                "hypothesis_ref": "H1", "failure_class": "FORGED",
                "classifier_version": "q05-2026.1"}),
             r["classification_id"]))
        d2 = classifications_digest(repo.classifications_for_project("p1"))
        assert d2["count"] == 0
        assert d2["integrity_status"] == "DEGRADED"
        assert d2["errors"][0]["code"] == "INVALID_FAILURE_CLASS"


class TestF2DerivedFieldsRecomputed:
    def test_digest_recomputes_requires_human_confirmation(self, db, program):
        """F2 rule — requires_human_confirmation is DERIVED from the failure
        class (True iff FRAMING_ERROR). The digest recomputes it from the
        ratified substrate; a tampered stored value can never change what
        the advisory view reports (both tamper directions)."""
        import json as _json
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        # direction 1: non-FRAMING row tampered to CLAIM human confirmation
        r1 = repo.record(
            "p1", rec(program["program_id"]),
            draft(FailureClass.UNKNOWN.value, evidence=()),
            producing_task_id="t1")
        db.execute(
            "UPDATE artifacts SET metadata_json = ? WHERE artifact_id = ?",
            (_json.dumps({
                "classification_id": r1["classification_id"],
                "hypothesis_ref": "H1", "failure_class": "UNKNOWN",
                "classifier_version": "q05-2026.1",
                "permitted_actions": ["ESCALATE_TO_DIRECTOR"],
                "requires_human_confirmation": True, "evidence_refs": []}),
             r1["classification_id"]))
        d = classifications_digest(repo.classifications_for_project("p1"))
        h1_item = [i for i in d["items"]
                   if i["hypothesis_ref"] == "H1"][0]
        assert h1_item["requires_human_confirmation"] is False
        # the tampered stored flag is reported as a mismatch
        assert "STORED_CONFIRMATION_MISMATCH" in h1_item[
            "integrity_flags"]
        # direction 2: FRAMING_ERROR row tampered to DENY confirmation
        r2 = repo.record(
            "p1", rec(program["program_id"], hypothesis_ref="H2"),
            draft(FailureClass.FRAMING_ERROR.value,
                  scope_brief_ref="brief-1",
                  scope_brief_field="core_question"),
            producing_task_id="t1")
        db.execute(
            "UPDATE artifacts SET metadata_json = ? WHERE artifact_id = ?",
            (_json.dumps({
                "classification_id": r2["classification_id"],
                "hypothesis_ref": "H2", "failure_class": "FRAMING_ERROR",
                "classifier_version": "q05-2026.1",
                "permitted_actions": ["ROUTE_TO_SCOPE_REVIEW"],
                "requires_human_confirmation": False, "evidence_refs": []}),
             r2["classification_id"]))
        d2 = classifications_digest(repo.classifications_for_project("p1"))
        h2_item = [i for i in d2["items"]
                   if i["hypothesis_ref"] == "H2"][0]
        assert h2_item["requires_human_confirmation"] is True
        assert "STORED_CONFIRMATION_MISMATCH" in h2_item[
            "integrity_flags"]

    def test_digest_gates_contributing_framing_error(self, db, program):
        """Red-team §2 remediation (digest): a FRAMING_ERROR CONTRIBUTING
        FACTOR on a non-authority primary class derives requires_human_
        confirmation True — the digest recomputes it from the metadata's
        contributors (F2), and a tampered stored False is flagged, never
        trusted."""
        import json as _json
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        r = repo.record(
            "p1", rec(program["program_id"]),
            draft(FailureClass.RESOURCE_CONSTRAINT.value,
                  evidence=("validation:ev1",),
                  contributing_factors=(FailureClass.FRAMING_ERROR.value,),
                  resource_gap=ResourceGap(
                      "compute_hours", 10.0, 40.0, "h")),
            producing_task_id="t1")
        d = classifications_digest(repo.classifications_for_project("p1"))
        assert d["items"][0]["requires_human_confirmation"] is True
        assert not d["items"][0]["integrity_flags"]
        # tampered stored False is flagged and never trusted
        meta = _json.loads(db.execute(
            "SELECT metadata_json FROM artifacts WHERE artifact_id = ?",
            (r["classification_id"],)).fetchone()[0])
        meta["requires_human_confirmation"] = False
        db.execute(
            "UPDATE artifacts SET metadata_json = ? WHERE artifact_id = ?",
            (_json.dumps(meta), r["classification_id"]))
        d2 = classifications_digest(repo.classifications_for_project("p1"))
        assert d2["items"][0]["requires_human_confirmation"] is True
        assert "STORED_CONFIRMATION_MISMATCH" in d2["items"][0][
            "integrity_flags"]

    def test_digest_recomputes_both_derived_fields(self, db, program):
        """F2 rule — both derived fields (permitted_actions AND
        requires_human_confirmation) come from the class, never storage:
        a row tampered on BOTH surfaces only the ratified values."""
        import json as _json
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        r = repo.record(
            "p1", rec(program["program_id"], hypothesis_ref="H3"),
            draft(FailureClass.IMPLEMENTATION_FAILURE.value,
                  failed_mechanism_ref="prediction:P1"),
            producing_task_id="t1")
        db.execute(
            "UPDATE artifacts SET metadata_json = ? WHERE artifact_id = ?",
            (_json.dumps({
                "classification_id": r["classification_id"],
                "hypothesis_ref": "H3", "failure_class": "IMPLEMENTATION_FAILURE",
                "classifier_version": "q05-2026.1",
                "permitted_actions": ["REJECT_BRANCH",
                                     "PROPOSE_MECHANISM_SUBSTITUTION"],
                "requires_human_confirmation": True, "evidence_refs": []}),
             r["classification_id"]))
        d = classifications_digest(repo.classifications_for_project("p1"))
        entry = d["items"][0]
        assert entry["permitted_actions"] == sorted(
            a.value for a in permitted_actions_for(
                FailureClass.IMPLEMENTATION_FAILURE))
        assert entry["requires_human_confirmation"] is False
        assert entry["integrity_flags"] == [
            "STORED_ACTIONS_MISMATCH", "STORED_CONFIRMATION_MISMATCH"]


class TestDigestCorruptionObservable:
    """Issue-1 fixtures — persisted corruption is observable and never
    silently disappears: a corrupt row is either DROPPED with an explicit
    diagnostic or SURFACED with recomputed values and an integrity flag,
    and the digest never turns a malformed row into a recommendation."""

    @staticmethod
    def _row(artifact_id="fc_x", metadata=None, artifact_type=
             "failure_classification", content_hash="hx"):
        return {
            "artifact_id": artifact_id,
            "artifact_type": artifact_type,
            "content_hash": content_hash,
            "metadata": metadata,
        }

    def test_forged_payload_identity_diagnostic(self):
        # metadata claims a classification_id that is not the row identity
        d = classifications_digest([self._row(
            "fc_real",
            metadata={"classification_id": "fc_forged",
                      "hypothesis_ref": "H1", "failure_class": "UNKNOWN",
                      "classifier_version": "q05-2026.1",
                      "permitted_actions": ["ESCALATE_TO_DIRECTOR"],
                      "requires_human_confirmation": False,
                      "evidence_refs": []})])
        assert d["count"] == 0
        assert d["integrity_status"] == "DEGRADED"
        assert d["errors"][0]["code"] == "FORGED_IDENTITY"

    def test_wrong_artifact_type_diagnostic(self):
        d = classifications_digest([self._row(
            "fc_x", artifact_type="source_result",
            metadata={"classification_id": "fc_x", "hypothesis_ref": "H1",
                      "failure_class": "UNKNOWN",
                      "classifier_version": "q05-2026.1",
                      "permitted_actions": ["ESCALATE_TO_DIRECTOR"],
                      "requires_human_confirmation": False,
                      "evidence_refs": []})])
        assert d["count"] == 0
        assert d["errors"][0]["code"] == "WRONG_ARTIFACT_TYPE"

    def test_missing_required_metadata_diagnostic(self):
        # hypothesis_ref missing (and separately classifier_version missing)
        for meta, code in (
                ({"classification_id": "fc_x", "failure_class": "UNKNOWN",
                  "classifier_version": "q05-2026.1",
                  "permitted_actions": ["ESCALATE_TO_DIRECTOR"]},
                 "MISSING_REQUIRED_METADATA"),
                ({"classification_id": "fc_x", "hypothesis_ref": "H1",
                  "failure_class": "UNKNOWN",
                  "permitted_actions": ["ESCALATE_TO_DIRECTOR"]},
                 "MISSING_REQUIRED_METADATA"),
                ({"hypothesis_ref": "H1", "failure_class": "UNKNOWN"},
                 "MISSING_REQUIRED_METADATA")):
            d = classifications_digest([self._row("fc_x", metadata=meta)])
            assert d["count"] == 0, code
            assert d["errors"][0]["code"] == code
        # a row with NO artifact identity and no metadata identity
        d = classifications_digest([{
            "artifact_type": "failure_classification",
            "content_hash": "hx", "metadata": {"failure_class": "UNKNOWN"}}])
        assert d["errors"][0]["code"] == "MISSING_CLASSIFICATION_ID"

    def test_malformed_permitted_action_set_flagged(self):
        # not a list of action strings → surfaced (recomputed) + flag
        for stored in ("REJECT_BRANCH", ["REJECT_BRANCH", 42], ["NOPE"], []):
            d = classifications_digest([self._row(
                "fc_x", metadata={
                    "classification_id": "fc_x", "hypothesis_ref": "H1",
                    "failure_class": "UNKNOWN",
                    "classifier_version": "q05-2026.1",
                    "permitted_actions": stored,
                    "requires_human_confirmation": False,
                    "evidence_refs": []})])
            assert d["count"] == 1, stored
            assert d["items"][0]["permitted_actions"] == [
                "ESCALATE_TO_DIRECTOR"], stored  # recomputed, never stored
            assert d["items"][0]["integrity_flags"] == [
                "MALFORMED_PERMITTED_ACTIONS"], stored
            assert d["integrity_status"] == "FLAGGED", stored
        # a well-formed but semantically wrong set is a MISMATCH (F2):
        # the recomputed value surfaces and the disagreement is reported
        d = classifications_digest([self._row(
            "fc_x", metadata={
                "classification_id": "fc_x", "hypothesis_ref": "H1",
                "failure_class": "UNKNOWN",
                "classifier_version": "q05-2026.1",
                "permitted_actions": ["REJECT_BRANCH"],
                "requires_human_confirmation": False,
                "evidence_refs": []})])
        assert d["items"][0]["permitted_actions"] == ["ESCALATE_TO_DIRECTOR"]
        assert d["items"][0]["integrity_flags"] == ["STORED_ACTIONS_MISMATCH"]
        # absent stored set is likewise a non-conforming row
        d = classifications_digest([self._row(
            "fc_x", metadata={"classification_id": "fc_x",
                              "hypothesis_ref": "H1",
                              "failure_class": "UNKNOWN",
                              "classifier_version": "q05-2026.1",
                              "requires_human_confirmation": False})])
        assert d["items"][0]["integrity_flags"] == [
            "MALFORMED_EVIDENCE_REFS", "MALFORMED_PERMITTED_ACTIONS"]

    def test_mixed_valid_and_corrupt_rows(self, db, program):
        """Fixture 7 — valid rows stay visible AND corruption is reported."""
        import json as _json
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        repo.record("p1", rec(program["program_id"]), constraint_draft(),
                    producing_task_id="t1")
        # inject a corrupt row directly (forged identity)
        db.execute(
            "INSERT INTO artifacts (artifact_id, project_id, task_id, "
            "artifact_type, content_hash, size_bytes, storage_path, "
            "producer, metadata_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("fc_corrupt", "p1", "t1", "failure_classification",
             "corrupt-hash", 0, "inline://failure_classification", "x",
             _json.dumps({"classification_id": "fc_other",
                          "hypothesis_ref": "H9",
                          "failure_class": "UNKNOWN",
                          "classifier_version": "q05-2026.1"}),
             "2026-01-01T00:00:00.000000+00:00"))
        d = classifications_digest(repo.classifications_for_project("p1"))
        assert d["count"] == 1
        assert d["items"][0]["failure_class"] == \
            "DECLARED_CONSTRAINT_VIOLATION"
        assert d["integrity_status"] == "DEGRADED"
        assert d["errors"] == [{
            "artifact_id": "fc_corrupt", "code": "FORGED_IDENTITY",
            "detail": ("row 'fc_corrupt' metadata claims classification_id "
                       "'fc_other' but the artifact identity is "
                       "'fc_corrupt'")}]

    def test_deterministic_result_same_state(self, db, program):
        """Fixture 8 — same database state, byte-identical digest."""
        import json as _json
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        repo.record("p1", rec(program["program_id"]), constraint_draft(),
                    producing_task_id="t1")
        db.execute(
            "INSERT INTO artifacts (artifact_id, project_id, task_id, "
            "artifact_type, content_hash, size_bytes, storage_path, "
            "producer, metadata_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("fc_bad2", "p1", "t1", "failure_classification",
             "bad-hash-2", 0, "inline://failure_classification", "x",
             _json.dumps({"classification_id": "fc_bad2",
                          "failure_class": "FORGED"}),
             "2026-01-01T00:00:00.000000+00:00"))
        rows = repo.classifications_for_project("p1")
        assert classifications_digest(rows) == classifications_digest(rows)


class TestResolverSnapshotImmutability:
    """Issue 2 — resolver snapshot / immutability proof (Option A).

    The class-specific citation targets are structurally immutable:
    ``research_programs`` has NO UPDATE/DELETE path (immutability is
    structural — the ResearchProgramRepository contract; a new version
    SUPERSEDES as a NEW row) and ``scope_briefs`` are frozen (``frozen_at``)
    with no UPDATE path in src. So a citation resolved pre-transaction cannot
    change before commit; the mutable parts (task binding, evidence
    ownership, one-shot identity) are re-verified INSIDE ``BEGIN IMMEDIATE``.
    """

    def _program_v2(self, db, program):
        """A COMPILED supersession (v2) of the fixture program."""
        payload = {
            "scope_ref": "brief-1",
            "epistemic_objective": "Amended: momentum and reversal both tested",
            "hypotheses": [
                {"ref": "H1", "ladder_target": "SUPPORTED",
                 "falsification_condition": "returns do not follow momentum",
                 "rival_of": None, "rival_status": None},
                {"ref": "H0", "ladder_target": "SPECULATIVE",
                 "falsification_condition": "null hypothesis",
                 "rival_of": "H1", "rival_status": "ACTIVE"},
            ],
            "predictions": [
                {"ref": "P1", "claim_ref": "H1", "observable": "20d_returns",
                 "direction": "FOR", "condition": "trend_up"},
                {"ref": "P0", "claim_ref": "H0", "observable": "20d_returns",
                 "direction": "NEUTRAL", "condition": "trend_up"},
            ],
            "discrimination_requirements": [
                {"ref": "D1", "hypothesis_a": "H1", "hypothesis_b": "H0",
                 "observable": "20d_returns",
                 "expected_difference": "H1 positive, H0 zero",
                 "required_condition": "trend_up",
                 "measurement_method_ref": "method-1"},
            ],
            "methodology_constraints": ["icss-v1"],
            "task_graph_template_ref": None,
            "compiler_version": "1.0.0",
            "policy_version": "rp-2026.1",
            "schema_version": "1",
            "supersedes_ref": program["program_id"],
        }
        result = compile_from_payload(
            payload, project_id="p1", scope_content_hash="briefhash1",
            superseded_program_ids=frozenset({program["program_id"]}))
        assert result.compiled, [
            f"{e.code}@{e.field_path}" for e in result.errors]
        return ResearchProgramRepository(db).record(
            "p1", result, produced_by="director", reason="fixture-v2")

    def test_program_target_frozen_across_supersession(self, db, program):
        """Frozen target cannot change: superseding the program leaves the
        cited program row and the recorded classification BYTE-IDENTICAL, and
        a new classification can still cite the old (superseded) version."""
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        r = repo.record("p1", rec(program["program_id"]), constraint_draft(),
                        producing_task_id="t1")
        prog_before = db.execute(
            "SELECT * FROM research_programs WHERE program_id = ?",
            (program["program_id"],)).fetchone()
        cls_before = db.execute(
            "SELECT * FROM artifacts WHERE artifact_id = ?",
            (r["classification_id"],)).fetchone()
        v2 = self._program_v2(db, program)
        assert v2["program_id"] != program["program_id"]
        prog_after = db.execute(
            "SELECT * FROM research_programs WHERE program_id = ?",
            (program["program_id"],)).fetchone()
        cls_after = db.execute(
            "SELECT * FROM artifacts WHERE artifact_id = ?",
            (r["classification_id"],)).fetchone()
        assert dict(prog_before) == dict(prog_after)
        assert dict(cls_before) == dict(cls_after)
        # the citation binds to the immutable row, not to the head
        r2 = repo.record("p1", rec(program["program_id"]),
                         constraint_draft(classifier_version="q05-2026.2"),
                         producing_task_id="t1")
        assert r2["decision"] == "NEW"

    def test_stale_program_ref_fails_closed(self, db):
        """A foreign (stale) program reference fails closed: the constraint
        resolver is project-scoped and cannot bind to a target in another
        project — resolution and persistence cannot diverge on a target the
        resolver never saw."""
        seed_task(db, "t1", project_id="p1")
        seed_evidence(db, "t1", "ev1", project_id="p1")
        payload = {
            "scope_ref": "brief-2",
            "epistemic_objective": "p2 objective",
            "hypotheses": [
                {"ref": "H1", "ladder_target": "SUPPORTED",
                 "falsification_condition": "x", "rival_of": None,
                 "rival_status": None},
                {"ref": "H0", "ladder_target": "SPECULATIVE",
                 "falsification_condition": "null", "rival_of": "H1",
                 "rival_status": "ACTIVE"},
            ],
            "predictions": [
                {"ref": "P1", "claim_ref": "H1", "observable": "20d_returns",
                 "direction": "FOR", "condition": "trend_up"},
                {"ref": "P0", "claim_ref": "H0", "observable": "20d_returns",
                 "direction": "NEUTRAL", "condition": "trend_up"},
            ],
            "discrimination_requirements": [
                {"ref": "D1", "hypothesis_a": "H1", "hypothesis_b": "H0",
                 "observable": "20d_returns",
                 "expected_difference": "H1 positive, H0 zero",
                 "required_condition": "trend_up",
                 "measurement_method_ref": "method-1"},
            ],
            "methodology_constraints": [],
            "task_graph_template_ref": None,
            "compiler_version": "1.0.0",
            "policy_version": "rp-2026.1",
            "schema_version": "1",
            "supersedes_ref": None,
        }
        result = compile_from_payload(
            payload, project_id="p2", scope_content_hash="briefhash2",
            superseded_program_ids=frozenset())
        assert result.compiled
        row = ResearchProgramRepository(db).record(
            "p2", result, produced_by="director", reason="fixture")
        repo = FailureClassificationRepository(db)
        with pytest.raises(FailureClassificationError) as exc:
            repo.record("p1", rec(row["program_id"]), constraint_draft(),
                        producing_task_id="t1")
        assert "non-ADMITTED" in str(exc.value)
        assert repo.classifications_for_project("p1") == []

    def test_stale_brief_ref_fails_closed(self, db, program):
        """Stale ScopeBrief references fail closed: a foreign brief and a
        same-project brief lacking the cited field both refuse the write."""
        seed_task(db, "t1")
        seed_evidence(db, "t1", "ev1")
        repo = FailureClassificationRepository(db)
        with pytest.raises(FailureClassificationError):
            repo.record("p1", rec(program["program_id"]),
                        draft(FailureClass.FRAMING_ERROR.value,
                              scope_brief_ref="brief-2",
                              scope_brief_field="core_question"),
                        producing_task_id="t1")
        with pytest.raises(FailureClassificationError):
            repo.record("p1", rec(program["program_id"]),
                        draft(FailureClass.FRAMING_ERROR.value,
                              scope_brief_ref="brief-1",
                              scope_brief_field="no_such_field"),
                        producing_task_id="t1")
        assert repo.classifications_for_project("p1") == []


class TestDigestStoredFactIntegrity:
    """Independent-review findings F3/F4 — stored-fact corruption must be
    flagged, never silently surfaced as valid advisory data."""

    @staticmethod
    def _row(artifact_id="fc_x", content_hash="hx", meta_extra=None,
             meta=None):
        base = {"classification_id": artifact_id, "hypothesis_ref": "H1",
                "failure_class": "UNKNOWN", "classifier_version": "q05-2026.1",
                "permitted_actions": ["ESCALATE_TO_DIRECTOR"],
                "requires_human_confirmation": False, "evidence_refs": []}
        base.update(meta_extra or {})
        return {"artifact_id": artifact_id,
                "artifact_type": "failure_classification",
                "content_hash": content_hash,
                "metadata": meta if meta is not None else base}

    def test_bare_string_evidence_refs_flagged_not_per_char(self):
        """F3 — a non-list evidence_refs must NOT iterate per-character into
        garbage refs; the row is flagged and the surfaced refs are empty."""
        d = classifications_digest([self._row(
            meta_extra={"evidence_refs": "validation:ev1"})])
        item = d["items"][0]
        assert item["evidence_refs"] == [], item["evidence_refs"]
        assert item["integrity_flags"] == ["MALFORMED_EVIDENCE_REFS"]
        assert d["integrity_status"] == "FLAGGED"

    def test_classification_ref_as_evidence_flagged(self):
        """D8 — a tampered row claiming a failure_classification ref as its
        evidence is flagged (a classification can never be evidence)."""
        d = classifications_digest([self._row(
            meta_extra={"evidence_refs": ["failure_classification:abc"]})])
        assert d["items"][0]["evidence_refs"] == []
        assert "MALFORMED_EVIDENCE_REFS" in d["items"][0]["integrity_flags"]

    def test_missing_content_hash_flagged(self):
        """F4 — a row without a content hash can never satisfy the D3
        dereference contract; flagged, never silently OK."""
        d = classifications_digest([self._row(content_hash="")])
        item = d["items"][0]
        assert item["failure_class_ref"] is None
        assert "MISSING_CONTENT_HASH" in item["integrity_flags"]
        assert d["integrity_status"] == "FLAGGED"

    def test_valid_evidence_refs_unflagged(self):
        """Positive control: proper typed refs surface unchanged, no flag."""
        d = classifications_digest([self._row(
            meta_extra={"evidence_refs": ["validation:ev1", "source_result:h"]})])
        assert d["items"][0]["evidence_refs"] == [
            "source_result:h", "validation:ev1"]
        assert d["items"][0]["integrity_flags"] == []
        assert d["integrity_status"] == "OK"
