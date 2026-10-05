"""Golden fixtures for the IDR-026 P7 write path (v6 §29, P7 row).

Proves the 10 acceptance criteria of IDR-026 against real SQLite:
1. genuine ADMITTED extraction persists atomically (rows + links + edges);
2. forged claim_id/content_hash → ResearchClaimIntegrityError, 0 rows, 0 edges;
3. INVALID verdict → ResearchClaimError, 0 rows (no partial batch);
4. genuine duplicate batch → idempotent (same rows, no new rows/edges);
5. supersession head-only; unchanged-content supersession fails loudly;
   target assumption flips to SUPERSEDED deterministically;
6. dangling/cross-project dataset_ref → rejection at the write path
   (real resolver over dataset_manifests);
7. failure injection at any step → rollback, no half-state;
8. never-evidence structural: rows expose no ladder/validation surface;
   status CHECK is the advisory vocabulary only;
9. no new event: event count/type set unchanged by record_extraction;
10. queries: claims_depending_on / assumptions_of return the maintained links.

Also covers migration 4→5 upgrade path and FK enforcement.
"""
from __future__ import annotations

import sqlite3

import pytest

from hermes.core import frozen_clock
from hermes.core.node import AgentProfile, NodeContract, NodeType
from hermes.core.task_status import TaskStatus
from hermes.persistence.database import connect, get_schema_version
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    ClaimAssumptionRepository,
    EventRepository,
    ExtractionTaskBindingError,
    NotFoundError,
    ProjectRepository,
    ResearchClaimError,
    ResearchClaimIntegrityError,
    TaskRepository,
)
from hermes.research.claims import (
    CLAIM_SCHEMA_VERSION,
    ExtractionDraft,
    ExtractionResult,
    ExtractionVerdict,
    ResearchAssumption,
    ResearchAssumptionDraft,
    ResearchClaim,
    ResearchClaimDraft,
    validate_extraction,
)

# ── fixtures ──

@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Test")
    ProjectRepository(conn).create("p2", "Other")
    conn.execute(
        """INSERT INTO dataset_manifests
           (manifest_id, project_id, location, format, size_bytes,
            headers_json, schema_observations_json, query_recipes_json,
            content_hash, provenance_json, created_at, immutable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        ("dm-1", "p1", "data/x.csv", "csv", 100, "[]", "[]", "[]",
         "dmhash1", None, "2026-01-01T00:00:00.000000+00:00"),
    )
    conn.execute(
        """INSERT INTO dataset_manifests
           (manifest_id, project_id, location, format, size_bytes,
            headers_json, schema_observations_json, query_recipes_json,
            content_hash, provenance_json, created_at, immutable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        ("dm-2", "p2", "data/y.csv", "csv", 200, "[]", "[]", "[]",
         "dmhash2", None, "2026-01-01T00:00:00.000000+00:00"),
    )
    yield conn
    conn.close()


@pytest.fixture
def repos(db):
    return (ClaimAssumptionRepository(db), EventRepository(db))


# ── builders ──

def claim(ref: str = "c1", **overrides) -> ResearchClaimDraft:
    fields = {
        "ref": ref,
        "statement": "Alpha reduces beta under gamma conditions.",
        "source_ref": "dataset_manifest:dm-1",
        "support_state": "INFERRED",
        "span_ref": "sec.3",
        "claim_type": "causal",
        "context_tags": {"regime": "ICSS-v1:low-vol", "dataset_ref": "dm-1"},
        "assumption_refs": ("a1",),
    }
    fields.update(overrides)
    return ResearchClaimDraft(**fields)


def assumption(ref: str = "a1", **overrides) -> ResearchAssumptionDraft:
    fields = {
        "ref": ref,
        "statement": "The sample is representative of the target population.",
        "context_tags": {"population": "adults-18-65"},
        "supporting_artifact_refs": ("dataset_manifest:dm-1",),
    }
    fields.update(overrides)
    return ResearchAssumptionDraft(**fields)


def admitted_result(**overrides) -> ExtractionResult:
    fields = {
        "source_ref": "task_evidence:run-1",
        "claims": (claim(),),
        "assumptions": (assumption(),),
        "extracted_by": "model_ref:golden-1",
        "schema_version": CLAIM_SCHEMA_VERSION,
    }
    fields.update(overrides)
    return validate_extraction(ExtractionDraft(**fields))


def invalid_result() -> ExtractionResult:
    """An INVALID verdict (dangling assumption ref) — must not persist."""
    return validate_extraction(ExtractionDraft(
        source_ref="task_evidence:run-1",
        claims=(claim(assumption_refs=("missing",)),),
    ))


def admit_extract_task(db, source_ref: str = "task_evidence:run-1",
                       tag: str = "t") -> str:
    """Create a RUNNING EXTRACT task for ``source_ref`` (V6-P7-A2 write
    binding): the producing task the write path now requires."""
    task_id = f"extract-{tag}-{len(source_ref)}"
    node = NodeContract(
        task_id=task_id,
        project_id="p1",
        task_type=NodeType.AGENT_TASK.value,
        profile=AgentProfile.RESEARCHER.value,
        idempotency_key=f"extract-{tag}-{source_ref}",
        iteration=1,
        spec={"template": "extract", "template_version": "1",
              "source_ref": source_ref, "scope": "both"},
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
    tr.transition_status(task_id, TaskStatus.RUNNING, caused_by="test")
    return task_id


def count_rows(conn, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]


def count_edges(conn) -> int:
    return count_rows(conn, "provenance_edges")


def count_events(conn) -> int:
    return count_rows(conn, "events")


# ── 1. genuine admission persists atomically ──

def test_1_admitted_extraction_persists_atomically(db, repos):
    repo, _ = repos
    result = admitted_result()
    outcome = repo.record_extraction(
        "p1", result, producing_task_id=admit_extract_task(db, tag="t1"),
        extracted_by="task-1")

    assert outcome["verdict"] == "ADMITTED"
    assert len(outcome["claims"]) == 1
    assert len(outcome["assumptions"]) == 1
    # rows really exist in SQLite
    assert count_rows(db, "research_claims") == 1
    assert count_rows(db, "research_assumptions") == 1
    assert count_rows(db, "claim_assumption_links") == 1
    # §14 edges: derived_from (claim→source) + cites (claim→assumption)
    assert count_edges(db) == 2

    cl = repo.get_claim(outcome["claims"][0]["claim_id"])
    assert cl["statement"] == result.claims[0].statement
    assert cl["source_ref"] == "dataset_manifest:dm-1"
    assert cl["context_tags"]["regime"] == "ICSS-v1:low-vol"
    assert cl["schema_version"] == CLAIM_SCHEMA_VERSION
    asm = repo.get_assumption(outcome["assumptions"][0]["assumption_id"])
    assert asm["status"] == "ACTIVE"
    assert asm["supporting_artifact_refs"] == ["dataset_manifest:dm-1"]


# ── 2. forged identity fails closed ──

def test_2a_forged_claim_id_rejected(db, repos):
    repo, _ = repos
    result = admitted_result()
    cl = result.claims[0]
    forged = ResearchClaim(
        claim_id="cl_" + "0" * 24,
        statement=cl.statement,
        source_ref=cl.source_ref,
        support_state=cl.support_state,
        span_ref=cl.span_ref,
        claim_type=cl.claim_type,
        context_tags=cl.context_tags,
        assumption_ids=cl.assumption_ids,
        related_claim_ids=cl.related_claim_ids,
        content_hash=cl.content_hash,
        schema_version=cl.schema_version,
        supersedes_ref=cl.supersedes_ref,
    )
    forged_result = ExtractionResult(
        ExtractionVerdict.ADMITTED,
        claims=(forged,),
        assumptions=result.assumptions,
    )
    with pytest.raises(ResearchClaimIntegrityError, match="identity"):
        repo.record_extraction(
            "p1", forged_result,
            producing_task_id=admit_extract_task(db, tag="t2a"))
    assert count_rows(db, "research_claims") == 0
    assert count_rows(db, "research_assumptions") == 0
    assert count_edges(db) == 0


def test_2b_forged_content_hash_rejected(db, repos):
    repo, _ = repos
    result = admitted_result()
    cl = result.claims[0]
    forged = ResearchClaim(
        claim_id=cl.claim_id,
        statement=cl.statement,
        source_ref=cl.source_ref,
        support_state=cl.support_state,
        span_ref=cl.span_ref,
        claim_type=cl.claim_type,
        context_tags=cl.context_tags,
        assumption_ids=cl.assumption_ids,
        related_claim_ids=cl.related_claim_ids,
        content_hash="cl_forgedhash",
        schema_version=cl.schema_version,
        supersedes_ref=cl.supersedes_ref,
    )
    forged_result = ExtractionResult(
        ExtractionVerdict.ADMITTED,
        claims=(forged,),
        assumptions=result.assumptions,
    )
    with pytest.raises(ResearchClaimIntegrityError, match="identity"):
        repo.record_extraction(
            "p1", forged_result,
            producing_task_id=admit_extract_task(db, tag="t2b"))
    assert count_rows(db, "research_claims") == 0
    assert count_edges(db) == 0


def test_2c_forged_schema_version_rejected(db, repos):
    repo, _ = repos
    result = admitted_result()
    cl = result.claims[0]
    forged = ResearchClaim(
        claim_id=cl.claim_id,
        statement=cl.statement,
        source_ref=cl.source_ref,
        support_state=cl.support_state,
        span_ref=cl.span_ref,
        claim_type=cl.claim_type,
        context_tags=cl.context_tags,
        assumption_ids=cl.assumption_ids,
        related_claim_ids=cl.related_claim_ids,
        content_hash=cl.content_hash,
        schema_version="999",
        supersedes_ref=cl.supersedes_ref,
    )
    forged_result = ExtractionResult(
        ExtractionVerdict.ADMITTED,
        claims=(forged,),
        assumptions=result.assumptions,
    )
    with pytest.raises(ResearchClaimIntegrityError, match="schema"):
        repo.record_extraction(
            "p1", forged_result,
            producing_task_id=admit_extract_task(db, tag="t2c"))
    assert count_rows(db, "research_claims") == 0
    assert count_edges(db) == 0


def test_2d_out_of_batch_assumption_link_rejected(db, repos):
    repo, _ = repos
    result = admitted_result()
    cl = result.claims[0]
    forged = ResearchClaim(
        claim_id=cl.claim_id,
        statement=cl.statement,
        source_ref=cl.source_ref,
        support_state=cl.support_state,
        span_ref=cl.span_ref,
        claim_type=cl.claim_type,
        context_tags=cl.context_tags,
        assumption_ids=("as_" + "f" * 24,),  # not in this batch
        related_claim_ids=cl.related_claim_ids,
        content_hash=cl.content_hash,
        schema_version=cl.schema_version,
        supersedes_ref=cl.supersedes_ref,
    )
    forged_result = ExtractionResult(
        ExtractionVerdict.ADMITTED,
        claims=(forged,),
        assumptions=result.assumptions,
    )
    with pytest.raises(ResearchClaimIntegrityError, match="outside the batch"):
        repo.record_extraction(
            "p1", forged_result,
            producing_task_id=admit_extract_task(db, tag="t2d"))
    assert count_rows(db, "research_claims") == 0
    assert count_edges(db) == 0


# ── 3. INVALID verdict has no write path ──

def test_3_invalid_verdict_rejected_no_partial_batch(db, repos):
    repo, _ = repos
    result = invalid_result()
    assert not result.admitted
    with pytest.raises(ResearchClaimError, match="non-ADMITTED"):
        repo.record_extraction(
            "p1", result,
            producing_task_id=admit_extract_task(db, tag="t3"))
    assert count_rows(db, "research_claims") == 0
    assert count_rows(db, "research_assumptions") == 0
    assert count_rows(db, "claim_assumption_links") == 0
    assert count_edges(db) == 0


def test_3b_empty_admitted_result_rejected(db, repos):
    repo, _ = repos
    empty = ExtractionResult(ExtractionVerdict.ADMITTED)
    with pytest.raises(ResearchClaimError, match="empty extraction"):
        repo.record_extraction(
            "p1", empty, producing_task_id=admit_extract_task(db, tag="t3b"))
    assert count_rows(db, "research_claims") == 0


# ── 4. idempotency (PA4) ──

def test_4_genuine_duplicate_idempotent(db, repos):
    repo, _ = repos
    tid = admit_extract_task(db, tag="t4")
    r1 = repo.record_extraction(
        "p1", admitted_result(), producing_task_id=tid, extracted_by="task-1")
    r2 = repo.record_extraction(
        "p1", admitted_result(), producing_task_id=tid, extracted_by="task-2")
    assert r1["claims"][0]["claim_id"] == r2["claims"][0]["claim_id"]
    assert r1["assumptions"][0]["assumption_id"] == \
        r2["assumptions"][0]["assumption_id"]
    # no duplicate rows, no duplicate links/edges
    assert count_rows(db, "research_claims") == 1
    assert count_rows(db, "research_assumptions") == 1
    assert count_rows(db, "claim_assumption_links") == 1
    assert count_edges(db) == 2
    # provenance of first admission retained
    assert repo.get_claim(r1["claims"][0]["claim_id"])["extracted_by"] == "task-1"


def test_4b_evolved_batch_inserts_only_new(db, repos):
    """A changed batch (same source, a new claim) adds only the new row."""
    repo, _ = repos
    repo.record_extraction(
        "p1", admitted_result(),
        producing_task_id=admit_extract_task(db, tag="t4b1"))
    evolved = admitted_result(
        claims=(claim(ref="c1"), claim(ref="c2", statement="Omega rises under delta.")),
    )
    outcome = repo.record_extraction(
        "p1", evolved, producing_task_id=admit_extract_task(db, tag="t4b2"),
        extracted_by="task-2")
    assert count_rows(db, "research_claims") == 2
    assert count_rows(db, "research_assumptions") == 1
    # the new claim links to the existing assumption (content-addressed)
    assert len(outcome["claims"]) == 2
    assert count_rows(db, "claim_assumption_links") == 2


# ── 5. supersession ──

def test_5_supersession_head_only_and_deterministic_status(db, repos):
    repo, _ = repos
    base = admitted_result()
    repo.record_extraction(
        "p1", base, producing_task_id=admit_extract_task(db, tag="t5a"))
    asm_id = base.assumptions[0].assumption_id

    # v2 supersedes the head: different content
    v2 = admitted_result(
        assumptions=(assumption(statement="The sample is representative."),),
    )
    v2_asm = v2.assumptions[0]
    assert v2_asm.assumption_id != asm_id
    out2 = repo.record_extraction(
        "p1", v2,
        producing_task_id=admit_extract_task(db, tag="t5b"),
        extracted_by="task-2",
        reason="revised premise",
    )
    # v2 did not supersede (its supersedes_ref is None) → still two rows
    assert count_rows(db, "research_assumptions") == 2
    assert out2["superseded"] == []

    # explicit supersession: v3 supersedes v2
    v3r = validate_extraction(ExtractionDraft(
        source_ref="task_evidence:run-3",
        claims=(),
        assumptions=(
            ResearchAssumptionDraft(
                ref="a1", statement="The sample is representative, v3.",
                context_tags={"population": "adults-18-65"},
                supporting_artifact_refs=("dataset_manifest:dm-1",),
                supersedes_ref=v2_asm.assumption_id,
            ),
        ),
    ))
    v3_asm = v3r.assumptions[0]
    assert v3_asm.assumption_id != v2_asm.assumption_id
    out3 = repo.record_extraction(
        "p1", v3r,
        producing_task_id=admit_extract_task(
            db, source_ref="task_evidence:run-3", tag="t5c"),
        extracted_by="task-3")
    assert out3["superseded"] == [v2_asm.assumption_id]
    # target deterministically flipped
    assert repo.get_assumption(v2_asm.assumption_id)["status"] == "SUPERSEDED"
    assert repo.get_assumption(v3_asm.assumption_id)["status"] == "ACTIVE"
    # supersedes edge present
    rows = db.execute(
        "SELECT 1 FROM provenance_edges WHERE artifact_id = ? "
        "AND upstream_id = ? AND edge_type = 'supersedes'",
        (v3_asm.assumption_id, v2_asm.assumption_id),
    ).fetchone()
    assert rows is not None

    # head-only: superseding the already-superseded v2 is rejected
    v4 = validate_extraction(ExtractionDraft(
        source_ref="task_evidence:run-4",
        claims=(),
        assumptions=(
            ResearchAssumptionDraft(
                ref="a1", statement="The sample is representative, v4.",
                context_tags={"population": "adults-18-65"},
                supporting_artifact_refs=("dataset_manifest:dm-1",),
                supersedes_ref=v2_asm.assumption_id,
            ),
        ),
    ))
    with pytest.raises(ResearchClaimError, match="current head"):
        repo.record_extraction(
            "p1", v4,
            producing_task_id=admit_extract_task(
                db, source_ref="task_evidence:run-4", tag="t5d"),
            extracted_by="task-4")
    assert count_rows(db, "research_assumptions") == 3  # unchanged


def test_5b_unchanged_content_supersession_fails_loudly(db, repos):
    repo, _ = repos
    base = admitted_result()
    repo.record_extraction(
        "p1", base, producing_task_id=admit_extract_task(db, tag="t5b1"))
    asm_id = base.assumptions[0].assumption_id

    # supersede with IDENTICAL content → loud failure, no silent drop
    dup = validate_extraction(ExtractionDraft(
        source_ref="task_evidence:run-2",
        claims=(),
        assumptions=(
            ResearchAssumptionDraft(
                ref="a1", statement=base.assumptions[0].statement,
                context_tags={"population": "adults-18-65"},
                supporting_artifact_refs=("dataset_manifest:dm-1",),
                supersedes_ref=asm_id,
            ),
        ),
    ))
    # Identical content ⇒ content identity equals the target ⇒ the substrate
    # itself rejects it as self-supersession before the repository sees it
    # (identity is content-derived). Either way it fails loudly, no rows.
    with pytest.raises(ResearchClaimError, match="supersession"):
        repo.record_extraction(
            "p1", dup,
            producing_task_id=admit_extract_task(
                db, source_ref="task_evidence:run-2", tag="t5b2"),
            extracted_by="task-2")
    assert count_rows(db, "research_assumptions") == 1
    assert repo.get_assumption(asm_id)["status"] == "ACTIVE"


def test_5c_supersede_target_missing_rejected(db, repos):
    repo, _ = repos
    r = validate_extraction(ExtractionDraft(
        source_ref="task_evidence:run-1",
        claims=(),
        assumptions=(
            ResearchAssumptionDraft(
                ref="a1", statement="brand new premise",
                context_tags={"population": "adults-18-65"},
                supporting_artifact_refs=("dataset_manifest:dm-1",),
                supersedes_ref="as_" + "0" * 24,
            ),
        ),
    ))
    with pytest.raises(ResearchClaimError, match="not found"):
        repo.record_extraction(
            "p1", r, producing_task_id=admit_extract_task(db, tag="t5c2"))
    assert count_rows(db, "research_assumptions") == 0


# ── 6. dataset_ref dereference at the write path ──

def test_6_dangling_dataset_ref_rejected(db, repos):
    repo, _ = repos
    r = admitted_result(claims=(claim(context_tags={"dataset_ref": "dm-999"}),))
    with pytest.raises(ResearchClaimError, match="dangling context ref"):
        repo.record_extraction(
            "p1", r, producing_task_id=admit_extract_task(db, tag="t6"))
    assert count_rows(db, "research_claims") == 0
    assert count_rows(db, "research_assumptions") == 0
    assert count_edges(db) == 0


def test_6b_cross_project_dataset_ref_rejected(db, repos):
    repo, _ = repos
    # dm-2 belongs to p2; claiming it from p1 must fail
    r = admitted_result(claims=(claim(source_ref="dataset_manifest:dm-2",
                                      context_tags={"dataset_ref": "dm-2"}),))
    with pytest.raises(ResearchClaimError, match="dangling context ref"):
        repo.record_extraction(
            "p1", r, producing_task_id=admit_extract_task(db, tag="t6b"))
    assert count_rows(db, "research_claims") == 0


def test_6c_valid_dataset_ref_accepted(db, repos):
    repo, _ = repos
    outcome = repo.record_extraction(
        "p1", admitted_result(),
        producing_task_id=admit_extract_task(db, tag="t6c"))
    assert len(outcome["claims"]) == 1


# ── 7. failure injection → rollback, no half-state ──

class _FailingConnection:
    """Wraps a connection and fails on any statement containing a marker."""

    def __init__(self, real, marker: str):
        self._real = real
        self._marker = marker

    def execute(self, sql, *args):
        if self._marker in sql:
            raise sqlite3.OperationalError("injected failure")
        return self._real.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_7_link_insert_failure_rolls_back_everything(db, repos):
    repo, _ = repos
    failing = _FailingConnection(db, "INSERT OR IGNORE INTO claim_assumption_links")
    failing_repo = ClaimAssumptionRepository(failing)

    tid = admit_extract_task(db, tag="t7")
    with pytest.raises(sqlite3.OperationalError, match="injected failure"):
        failing_repo.record_extraction(
            "p1", admitted_result(), producing_task_id=tid)

    # no half-state: nothing persisted
    assert count_rows(db, "research_claims") == 0
    assert count_rows(db, "research_assumptions") == 0
    assert count_rows(db, "claim_assumption_links") == 0
    assert count_edges(db) == 0

    # the next attempt with the real repo succeeds
    outcome = repo.record_extraction(
        "p1", admitted_result(), producing_task_id=tid)
    assert len(outcome["claims"]) == 1


def test_7b_edge_insert_failure_rolls_back_everything(db, repos):
    _repo, _ = repos
    failing = _FailingConnection(db, "INSERT OR IGNORE INTO provenance_edges")
    failing_repo = ClaimAssumptionRepository(failing)

    tid = admit_extract_task(db, tag="t7b")
    with pytest.raises(sqlite3.OperationalError, match="injected failure"):
        failing_repo.record_extraction(
            "p1", admitted_result(), producing_task_id=tid)

    assert count_rows(db, "research_claims") == 0
    assert count_rows(db, "research_assumptions") == 0
    assert count_rows(db, "claim_assumption_links") == 0
    assert count_edges(db) == 0


# ── 8. never-evidence structural ──

def test_8_no_ladder_validation_surface(db):
    """The persisted rows carry no ladder/validation columns (structural)."""
    for table in ("research_claims", "research_assumptions"):
        cols = {r["name"] for r in db.execute(
            f"PRAGMA table_info({table})")}
        assert "ladder_status" not in cols
        assert "evidence" not in cols
        assert "validation" not in cols
        assert "promote" not in cols


def test_8b_status_check_advisory_vocabulary(db):
    """status CHECK is the advisory lifecycle only — a bad status fails."""
    ts = "2026-01-01T00:00:00.000000+00:00"
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """INSERT INTO research_assumptions
               (assumption_id, project_id, content_hash, statement,
                context_tags_json, supporting_artifact_refs_json, status,
                schema_version, supersedes_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
            ("as_x", "p1", "h", "s", "{}", "[]", "EVIDENCE",
             CLAIM_SCHEMA_VERSION, ts),
        )


def test_8c_repository_has_no_promotion_surface(db, repos):
    repo, _ = repos
    assert not hasattr(repo, "promote")
    assert not hasattr(repo, "advance")
    assert not hasattr(repo, "update")
    assert not hasattr(repo, "delete")


# ── 9. no new event ──

def test_9_record_extraction_emits_no_events(db, repos):
    repo, _event_repo = repos
    tid = admit_extract_task(db, tag="t9")  # task lifecycle events happen HERE
    events_before = count_events(db)
    types_before = {
        r["event_type"] for r in db.execute("SELECT DISTINCT event_type FROM events")
    }
    repo.record_extraction("p1", admitted_result(), producing_task_id=tid)
    assert count_events(db) == events_before
    types_after = {
        r["event_type"] for r in db.execute("SELECT DISTINCT event_type FROM events")
    }
    assert types_after == types_before


# ── 10. link queries ──

def test_10_link_queries_return_maintained_links(db, repos):
    repo, _ = repos
    two = admitted_result(
        claims=(
            claim(ref="c1", assumption_refs=("a1",)),
            claim(ref="c2", statement="Omega rises under delta.",
                  assumption_refs=("a1", "a2")),
        ),
        assumptions=(
            assumption(ref="a1"),
            assumption(ref="a2", statement="Delta is measurable."),
        ),
    )
    outcome = repo.record_extraction(
        "p1", two, producing_task_id=admit_extract_task(db, tag="t10"))
    by_statement = {c["statement"]: c["claim_id"] for c in outcome["claims"]}
    c1 = repo.get_claim(by_statement["Alpha reduces beta under gamma conditions."])
    c2 = repo.get_claim(by_statement["Omega rises under delta."])
    a1 = next(a for a in repo.assumptions_for_project("p1")
              if a["statement"] == "The sample is representative of the target population.")
    a2 = next(a for a in repo.assumptions_for_project("p1")
              if a["statement"] == "Delta is measurable.")

    assert {a["assumption_id"] for a in repo.assumptions_of(c1["claim_id"])} == {a1["assumption_id"]}
    assert {a["assumption_id"] for a in repo.assumptions_of(c2["claim_id"])} == {a1["assumption_id"], a2["assumption_id"]}
    assert {c["claim_id"] for c in repo.claims_depending_on(a1["assumption_id"])} == {c1["claim_id"], c2["claim_id"]}
    assert {c["claim_id"] for c in repo.claims_depending_on(a2["assumption_id"])} == {c2["claim_id"]}


def test_10b_head_follows_supersession_chain(db, repos):
    repo, _ = repos
    base = admitted_result()
    repo.record_extraction(
        "p1", base, producing_task_id=admit_extract_task(db, tag="t10b"))
    cid = base.claims[0].claim_id
    assert repo.head(cid)["claim_id"] == cid
    with pytest.raises(NotFoundError):
        repo.get_claim("cl_" + "0" * 24)


# ── migration 4→5 upgrade path ──

def test_migration_v4_to_v5_upgrade_path():
    import hermes.persistence.migrations as m
    conn = connect(":memory:")
    clock = frozen_clock("2026-01-01T00:00:00.000000+00:00")
    for fn in m._MIGRATIONS[:4]:   # migrate 0 → 4
        conn.execute("BEGIN")
        fn(conn, clock)
        conn.execute("COMMIT")
    assert get_schema_version(conn) == 4
    ProjectRepository(conn).create("p1", "Test")
    migrate_to_latest(conn)
    assert get_schema_version(conn) == 19  # Q-02: 8 → 9; IDR-041: 9 → 10; A4: 10 → 11; F9: 11 → 12; M1: 12 → 13; M4: 13 → 14; Step 7: 14 → 15; CHG-1/CHG-2: 15 → 16; P4 closure: 16 → 17; Step 3 FIX 1: 17 → 18 (advisory related_claim_ids); 18 → 19 (ADR-041: parallel-regime-test columns on research_programs)
    # new tables usable after upgrade
    conn.execute(
        """INSERT INTO dataset_manifests
           (manifest_id, project_id, location, format, size_bytes,
            headers_json, schema_observations_json, query_recipes_json,
            content_hash, provenance_json, created_at, immutable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        ("dm-1", "p1", "x.csv", "csv", 1, "[]", "[]", "[]",
         "h", None, "2026-01-01T00:00:00.000000+00:00"),
    )
    repo = ClaimAssumptionRepository(conn)
    task_id = admit_extract_task(conn, tag="tmig")
    outcome = repo.record_extraction(
        "p1", admitted_result(), producing_task_id=task_id)
    assert len(outcome["claims"]) == 1
    # the task link column landed with the migration
    cols = {r["name"] for r in conn.execute(
        "PRAGMA table_info(research_claims)")}
    assert "producing_task_id" in cols
    conn.close()


def test_foreign_keys_enforced(db):
    """claim_assumption_links FKs reference real rows."""
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO claim_assumption_links "
            "(claim_id, assumption_id) VALUES (?, ?)",
            ("cl_missing", "as_missing"),
        )


# ── V6-P7-F01..F04 remediation regressions (independent audit) ──

def test_f01_forged_status_forced_to_active(db, repos):
    """V6-P7-F01: status is governance, never caller-supplied. A hand-built
    artifact claiming SUSPENDED/SUPERSEDED at admission lands ACTIVE."""
    _repo, _ = repos
    base = admitted_result()
    a = base.assumptions[0]
    for forged_status in ("SUSPENDED", "SUPERSEDED"):
        forged = ResearchAssumption(
            assumption_id=a.assumption_id,
            statement=a.statement,
            context_tags=a.context_tags,
            supporting_artifact_refs=a.supporting_artifact_refs,
            dependent_claim_ids=a.dependent_claim_ids,
            status=forged_status,
            content_hash=a.content_hash,
            schema_version=a.schema_version,
            supersedes_ref=a.supersedes_ref,
        )
        forged_result = ExtractionResult(
            ExtractionVerdict.ADMITTED,
            claims=base.claims,
            assumptions=(forged,),
            source_ref=base.source_ref,
        )
        conn2 = connect(":memory:")
        migrate_to_latest(conn2)
        ProjectRepository(conn2).create("p1", "Test")
        conn2.execute(
            """INSERT INTO dataset_manifests (manifest_id, project_id,
               location, format, size_bytes, headers_json,
               schema_observations_json, query_recipes_json, content_hash,
               provenance_json, created_at, immutable)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            ("dm-1", "p1", "x.csv", "csv", 1, "[]", "[]", "[]",
             "h1", None, "2026-01-01T00:00:00.000000+00:00"),
        )
        repo2 = ClaimAssumptionRepository(conn2)
        t2 = TaskRepository(conn2)
        tid = "extract-f01"
        t2.create(NodeContract(
            task_id=tid, project_id="p1",
            task_type=NodeType.AGENT_TASK.value,
            profile=AgentProfile.RESEARCHER.value,
            idempotency_key="extract-f01", iteration=1,
            spec={"template": "extract", "template_version": "1",
                  "source_ref": "task_evidence:run-1", "scope": "both"},
            inputs=[], outputs=[], dependencies=[], provenance=[],
            cost_class="small", concurrency_group=None, max_retries=3,
            parent_task_id=None,
        ))
        t2.transition_status(tid, TaskStatus.READY, caused_by="test")
        t2.transition_status(tid, TaskStatus.RUNNING, caused_by="test")
        repo2.record_extraction("p1", forged_result, producing_task_id=tid)
        assert repo2.get_assumption(a.assumption_id)["status"] == "ACTIVE"
        conn2.close()


def test_f02_dangling_source_ref_rejected(db, repos):
    """V6-P7-F02: source_ref dereferences at the write path — a claim citing
    a nonexistent dataset_manifest is rejected even with clean context tags."""
    repo, _ = repos
    r = admitted_result(claims=(claim(source_ref="dataset_manifest:dm-999"),))
    with pytest.raises(ResearchClaimError, match="dangling source_ref"):
        repo.record_extraction(
            "p1", r, producing_task_id=admit_extract_task(db, tag="tf02"))
    assert count_rows(db, "research_claims") == 0
    assert count_edges(db) == 0


def test_f02b_dangling_supporting_artifact_ref_rejected(db, repos):
    """V6-P7-F02: assumption supporting_artifact_refs dereference too."""
    repo, _ = repos
    r = admitted_result(
        assumptions=(assumption(supporting_artifact_refs=(
            "dataset_manifest:dm-999",)),))
    with pytest.raises(ResearchClaimError, match="dangling supporting artifact"):
        repo.record_extraction(
            "p1", r, producing_task_id=admit_extract_task(db, tag="tf02b"))
    assert count_rows(db, "research_assumptions") == 0


def test_f02c_deferred_artifact_type_source_accepted(db, repos):
    """V6-P7-F02 boundary: artifact types whose stores are DEFERRED (task
    outputs, notes) are form-checked by the validator and accepted — the
    documented extension point, not a bypass."""
    repo, _ = repos
    r = admitted_result(claims=(claim(source_ref="task_output:run-1"),))
    outcome = repo.record_extraction(
        "p1", r, producing_task_id=admit_extract_task(db, tag="tf02c"))
    assert len(outcome["claims"]) == 1


def test_f03_unknown_project_structured_error(db, repos):
    """V6-P7-F03: a nonexistent project raises ResearchClaimError, never a
    raw sqlite3.IntegrityError — even for a claim with no dereference tags."""
    repo, _ = repos
    bare = admitted_result(claims=(claim(
        source_ref="task_output:run-1",
        context_tags={}, assumption_refs=()),))
    with pytest.raises(ResearchClaimError, match="Project not found"):
        repo.record_extraction(
            "no-such-project", bare,
            producing_task_id=admit_extract_task(db, tag="tf03"))
    assert count_rows(db, "research_claims") == 0


def test_f04_reason_persisted(db, repos):
    """V6-P7-F04: the reason parameter is persisted, not dead."""
    repo, _ = repos
    outcome = repo.record_extraction(
        "p1", admitted_result(),
        producing_task_id=admit_extract_task(db, tag="tf04"),
        extracted_by="task-1",
        reason="extraction acceptance",
    )
    assert repo.get_claim(outcome["claims"][0]["claim_id"])["reason"] == \
        "extraction acceptance"
    assert repo.get_assumption(
        outcome["assumptions"][0]["assumption_id"])["reason"] == \
        "extraction acceptance"


# ── V6-P7-A2-01..03 remediation regressions (independent audit 2) ──

def test_a2_01_missing_producing_task_refused(db, repos):
    """A2-01: record_extraction requires a real producing task — bare
    persistence (no task anywhere) is refused with 0 rows."""
    repo, _ = repos
    with pytest.raises(ExtractionTaskBindingError, match="does not exist"):
        repo.record_extraction(
            "p1", admitted_result(), producing_task_id="extract_forged")
    assert count_rows(db, "research_claims") == 0
    assert count_rows(db, "research_assumptions") == 0
    assert count_edges(db) == 0


def test_a2_01_cross_project_task_refused(db, repos):
    """A2-01: a task from another project cannot produce this project's
    claims."""
    repo, _ = repos
    # admit an EXTRACT task into p2
    task_id = "extract-p2"
    tr = TaskRepository(db)
    tr.create(NodeContract(
        task_id=task_id, project_id="p2",
        task_type=NodeType.AGENT_TASK.value,
        profile=AgentProfile.RESEARCHER.value,
        idempotency_key="extract-p2", iteration=1,
        spec={"template": "extract", "template_version": "1",
              "source_ref": "task_evidence:run-1", "scope": "both"},
        inputs=[], outputs=[], dependencies=[], provenance=[],
        cost_class="small", concurrency_group=None, max_retries=3,
        parent_task_id=None,
    ))
    tr.transition_status(task_id, TaskStatus.READY, caused_by="test")
    tr.transition_status(task_id, TaskStatus.RUNNING, caused_by="test")
    with pytest.raises(ExtractionTaskBindingError, match="project"):
        repo.record_extraction("p1", admitted_result(), producing_task_id=task_id)
    assert count_rows(db, "research_claims") == 0


def test_a2_01_non_extract_task_refused(db, repos):
    """A2-01: a RUNNING task that is not an EXTRACT task cannot produce
    claims."""
    repo, _ = repos
    task_id = "plain-1"
    tr = TaskRepository(db)
    tr.create(NodeContract(
        task_id=task_id, project_id="p1",
        task_type=NodeType.AGENT_TASK.value,
        profile=AgentProfile.RESEARCHER.value,
        idempotency_key="plain-1", iteration=1,
        spec={"template": "analyze", "template_version": "1",
              "source_ref": "task_evidence:run-1", "scope": "both"},
        inputs=[], outputs=[], dependencies=[], provenance=[],
        cost_class="small", concurrency_group=None, max_retries=3,
        parent_task_id=None,
    ))
    tr.transition_status(task_id, TaskStatus.READY, caused_by="test")
    tr.transition_status(task_id, TaskStatus.RUNNING, caused_by="test")
    with pytest.raises(ExtractionTaskBindingError, match="not an EXTRACT"):
        repo.record_extraction("p1", admitted_result(), producing_task_id=task_id)
    assert count_rows(db, "research_claims") == 0


def test_a2_01_source_mismatch_refused(db, repos):
    """A2-01: the extraction's source must equal the producing task's
    spec.source_ref."""
    repo, _ = repos
    tid = admit_extract_task(db, source_ref="task_evidence:run-1", tag="ta2s")
    mismatched = admitted_result(source_ref="task_evidence:run-9")
    with pytest.raises(ExtractionTaskBindingError, match="source_ref"):
        repo.record_extraction("p1", mismatched, producing_task_id=tid)
    assert count_rows(db, "research_claims") == 0


def test_a2_02_non_running_task_refused(db, repos):
    """A2-02: the producing task must be RUNNING — PENDING and SUCCEEDED
    are both refused with 0 rows."""
    repo, _ = repos
    # PENDING (never started)
    tid = "extract-pending"
    tr = TaskRepository(db)
    tr.create(NodeContract(
        task_id=tid, project_id="p1",
        task_type=NodeType.AGENT_TASK.value,
        profile=AgentProfile.RESEARCHER.value,
        idempotency_key=tid, iteration=1,
        spec={"template": "extract", "template_version": "1",
              "source_ref": "task_evidence:run-1", "scope": "both"},
        inputs=[], outputs=[], dependencies=[], provenance=[],
        cost_class="small", concurrency_group=None, max_retries=3,
        parent_task_id=None,
    ))
    with pytest.raises(ExtractionTaskBindingError, match="not RUNNING"):
        repo.record_extraction("p1", admitted_result(), producing_task_id=tid)
    # SUCCEEDED (finished)
    tid2 = "extract-done"
    tr.create(NodeContract(
        task_id=tid2, project_id="p1",
        task_type=NodeType.AGENT_TASK.value,
        profile=AgentProfile.RESEARCHER.value,
        idempotency_key=tid2, iteration=1,
        spec={"template": "extract", "template_version": "1",
              "source_ref": "task_evidence:run-1", "scope": "both"},
        inputs=[], outputs=[], dependencies=[], provenance=[],
        cost_class="small", concurrency_group=None, max_retries=3,
        parent_task_id=None,
    ))
    tr.transition_status(tid2, TaskStatus.READY, caused_by="test")
    tr.transition_status(tid2, TaskStatus.RUNNING, caused_by="test")
    tr.transition_status(tid2, TaskStatus.SUCCEEDED, caused_by="test")
    with pytest.raises(ExtractionTaskBindingError, match="not RUNNING"):
        repo.record_extraction("p1", admitted_result(), producing_task_id=tid2)
    assert count_rows(db, "research_claims") == 0
    assert count_rows(db, "research_assumptions") == 0


def test_a2_03_divergent_output_from_same_task_refused(db, repos):
    """A2-03: one execution, one output — a second, DIFFERENT output from
    the same task is refused with no new rows."""
    repo, _ = repos
    tid = admit_extract_task(db, tag="ta23")
    repo.record_extraction("p1", admitted_result(), producing_task_id=tid)
    divergent = admitted_result(
        claims=(claim(ref="c1",
                      statement="A DIFFERENT claim from the same execution."),),
    )
    with pytest.raises(ExtractionTaskBindingError, match="already produced"):
        repo.record_extraction("p1", divergent, producing_task_id=tid)
    assert count_rows(db, "research_claims") == 1  # first output only
    assert count_edges(db) == 2


def test_a2_03_identical_rerun_stays_idempotent(db, repos):
    """A2-03: an IDENTICAL re-acceptance (crash/rerun) from the same task
    stays idempotent — same rows, no duplicates (PA4)."""
    repo, _ = repos
    tid = admit_extract_task(db, tag="ta23b")
    r1 = repo.record_extraction("p1", admitted_result(), producing_task_id=tid)
    r2 = repo.record_extraction("p1", admitted_result(), producing_task_id=tid)
    assert r1["claims"][0]["claim_id"] == r2["claims"][0]["claim_id"]
    assert count_rows(db, "research_claims") == 1
    assert count_rows(db, "research_assumptions") == 1
    assert count_rows(db, "claim_assumption_links") == 1
    assert count_edges(db) == 2


def test_a2_05_producing_task_id_persisted(db, repos):
    """A2-01 schema: the producing task is recorded on every persisted row
    (migration 5→6) and surfaces through the read side."""
    repo, _ = repos
    tid = admit_extract_task(db, tag="ta25")
    outcome = repo.record_extraction("p1", admitted_result(),
                                     producing_task_id=tid)
    cl = repo.get_claim(outcome["claims"][0]["claim_id"])
    asm = repo.get_assumption(outcome["assumptions"][0]["assumption_id"])
    assert cl["producing_task_id"] == tid
    assert asm["producing_task_id"] == tid
    # and the FK is enforced at the schema level
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO research_claims (claim_id, project_id, content_hash, "
            "statement, source_ref, context_tags_json, schema_version, "
            "extracted_by, producing_task_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("cl_fk", "p1", "h", "s", "dataset_manifest:dm-1", "{}",
             CLAIM_SCHEMA_VERSION, "x", "no_such_task",
             "2026-01-01T00:00:00.000000+00:00"),
        )


# ── 26. closed dereference vocabulary (F1 audit generalization) ──
#
# _dereference_artifact_ref now FAILS CLOSED: every artifact type is
# explicitly decided — real resolver (dataset_manifest / source_result /
# source_payload), documented deferred carrier (task_evidence /
# task_output), or refusal (failure_classification D8 + everything else).
# Unknown or unsupported types are never silently form-checked.

class TestClosedDereferenceVocabulary:
    def _refused(self, db, repo, ref, tag):
        tid = admit_extract_task(db, tag=tag)
        with pytest.raises(ResearchClaimError, match="must dereference"):
            repo.record_extraction(
                "p1", admitted_result(claims=(claim(source_ref=ref),)),
                producing_task_id=tid)
        assert count_rows(db, "research_claims") == 0
        assert count_rows(db, "research_assumptions") == 0
        assert count_edges(db) == 0

    def test_unknown_artifact_type_refused(self, db, repos):
        repo, _ = repos
        self._refused(db, repo, "xyz:123", "t26a")

    def test_validation_ref_refused(self, db, repos):
        repo, _ = repos
        self._refused(db, repo, "validation:ev1", "t26b")

    def test_generic_artifact_catchall_refused(self, db, repos):
        """`artifact:` is a generic catch-all — the D8 bypass vector. A
        classification hash cited via the `artifact:` prefix must refuse
        exactly like `failure_classification:` (F1 audit finding)."""
        repo, _ = repos
        self._refused(db, repo, "artifact:note-1", "t26c")

    def test_model_ref_not_citable_as_source(self, db, repos):
        """`model_ref:` is advisory extracted_by provenance, never a claim
        source carrier — refused as source_ref while remaining accepted as
        the advisory field (which is not dereferenced)."""
        repo, _ = repos
        self._refused(db, repo, "model_ref:golden-1", "t26d")
        # advisory provenance still flows (not dereferenced): a write whose
        # extracted_by is a model_ref succeeds — the advisory field is not a
        # dereference carrier
        tid = admit_extract_task(db, tag="t26d2")
        repo.record_extraction(
            "p1", admitted_result(extracted_by="model_ref:golden-1"),
            producing_task_id=tid)
        assert count_rows(db, "research_claims") == 1

    def test_external_id_ref_refused(self, db, repos):
        """External document ids (doi:/arxiv:/pmid:) have no carrier on the
        write path — a bare id string must not be silently accepted."""
        repo, _ = repos
        self._refused(db, repo, "doi:10.1103/PhysRevLett.116.061102", "t26e")

    def test_research_program_not_citable_as_source(self, db, repos):
        """A research program is a plan, not a source document — not citable
        as claim evidence through this path."""
        repo, _ = repos
        self._refused(db, repo, "research_program:prog-1", "t26f")

    def test_assumption_supporting_ref_refused(self, db, repos):
        repo, _ = repos
        tid = admit_extract_task(db, tag="t26g")
        with pytest.raises(ResearchClaimError, match="must dereference"):
            repo.record_extraction(
                "p1", admitted_result(
                    assumptions=(assumption(
                        supporting_artifact_refs=("artifact:note-1",)),)),
                producing_task_id=tid)
        assert count_rows(db, "research_assumptions") == 0

    def test_deferred_carriers_still_accepted(self, db, repos):
        """Positive control: the documented deferred carriers (task-output
        context) keep passing the form-check — an explicit decision, not a
        silent catch-all."""
        repo, _ = repos
        for i, ref in enumerate(("task_evidence:run-1", "task_output:run-1")):
            # the extraction's own source_ref must equal the task spec
            # (V6-P7-A2-01), so it matches the deferred carrier too
            tid = admit_extract_task(db, source_ref=ref, tag=f"t26h{i}")
            out = repo.record_extraction(
                "p1", admitted_result(
                    source_ref=ref, claims=(claim(source_ref=ref),)),
                producing_task_id=tid)
            assert out["claims"][0]["source_ref"] == ref

    def test_source_result_carrier_resolves(self, db, repos):
        """Positive control: the real source_result resolver branch — a
        source artifact row in the project dereferences at the write path."""
        repo, _ = repos
        db.execute(
            """INSERT INTO artifacts
               (artifact_id, project_id, task_id, artifact_type, content_hash,
                size_bytes, storage_path, producer, metadata_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("art-sr1", "p1", None, "source_result", "sr-hash-1", 0,
             "inline://source_result", "fetch", "{}",
             "2026-01-01T00:00:00.000000+00:00"),
        )
        tid = admit_extract_task(db, tag="t26i")
        out = repo.record_extraction(
            "p1", admitted_result(
                claims=(claim(source_ref="source_result:sr-hash-1"),)),
            producing_task_id=tid)
        assert count_rows(db, "research_claims") == 1
        assert out["claims"][0]["source_ref"] == "source_result:sr-hash-1"

    def test_dangling_dataset_manifest_still_refused(self, db, repos):
        """Positive control: real resolvers still fail when dangling."""
        repo, _ = repos
        self._refused(db, repo, "dataset_manifest:dm-999", "t26j")


# ── Step 4 / S-R2 (IDR-044): the regime dim resolves live at the write path ──

def test_r2_regime_registered_tag_resolves_live(db, repos):
    """Positive wire control: the registered tag dereferences through the
    closed registry at the write path (the positive case is exercised by
    test_1's context; pinned here against dim drift)."""
    repo, _ = repos
    tid = admit_extract_task(db, tag="r2a")
    out = repo.record_extraction("p1", admitted_result(), producing_task_id=tid)
    assert out["claims"][0]["context_tags"]["regime"] == "ICSS-v1:low-vol"


def test_r2_regime_unregistered_tag_dangling_at_write_path(db, repos):
    """A well-formed versioned tag whose (version, id) pair is NOT
    registered is dangling at the write path — a hand-marked ADMITTED
    verdict cannot evade the dim re-check (C1: dims re-checked with the
    real resolver at the boundary, never trusted)."""
    repo, _ = repos
    result = admitted_result(
        claims=(claim(context_tags={"regime": "ICSS-v1:high-vol",
                                    "dataset_ref": "dm-1"}),))
    assert result.verdict is ExtractionVerdict.ADMITTED  # form-checked only
    tid = admit_extract_task(db, tag="r2b")
    with pytest.raises(ResearchClaimError, match="dangling context ref"):
        repo.record_extraction("p1", result, producing_task_id=tid)
    assert count_rows(db, "research_claims") == 0


def test_r2_regime_bare_id_dangling_at_write_path(db, repos):
    """The bare/unversioned form is dangling too — the versioned-form
    discipline is live at the write path."""
    repo, _ = repos
    result = admitted_result(
        claims=(claim(context_tags={"regime": "low-vol",
                                    "dataset_ref": "dm-1"}),))
    tid = admit_extract_task(db, tag="r2c")
    with pytest.raises(ResearchClaimError, match="dangling context ref"):
        repo.record_extraction("p1", result, producing_task_id=tid)
    assert count_rows(db, "research_claims") == 0
