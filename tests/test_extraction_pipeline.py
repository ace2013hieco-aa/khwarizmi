"""Golden fixtures for the IDR-028 extraction pipeline (v6 §29, P7).

Proves the 8 acceptance criteria of IDR-028 against real SQLite:
1. an EXTRACT task admitted via ordinary INSERT_TASK is an AGENT_TASK with
   the C-tier profile and the content-derived idempotency key;
2. a well-formed ExtractionDraft output → validate_extraction ADMITTED →
   record_extraction → rows + links + edges exist; task SUCCEEDED;
3. a malformed output → INVALID → task FAILED/RETRYING, 0 rows/links/edges
   (no partial write);
4. re-running the same extraction after a crash → idempotent (task-level and
   artifact-level; no duplicate rows/edges);
5. the acceptance wiring emits no new event type (catalog + allowlist
   unchanged);
6. the wiring can never promote evidence, pass a gate, or set a status other
   than ACTIVE;
7. an EXTRACT task for a source whose dereference fails (missing
   dataset_manifest) is rejected at admission (IDR-027 F02 discipline);
8. model_ref is recorded on rows and is never authoritative lineage.
"""
from __future__ import annotations

import pytest

from hermes.core.intents import Intent, IntentKind
from hermes.core.task_status import TaskStatus
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    ClaimAssumptionRepository,
    ProjectRepository,
    ResearchClaimError,
    TaskRepository,
)
from hermes.research.extraction import (
    EXTRACT_PROFILE,
    EXTRACT_TEMPLATE_VERSION,
    ExtractionNotBoundToTask,
    ExtractionOutputRejected,
    accept_extraction_output,
    build_extract_task_payload,
    extract_idempotency_key,
    extract_task_id,
    extraction_draft_from_mapping,
)
from hermes.research.gateway import GatewayRejection, apply_intent

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
        ("dm-1", "p1", "x.csv", "csv", 1, "[]", "[]", "[]",
         "h1", None, "2026-01-01T00:00:00.000000+00:00"),
    )
    yield conn
    conn.close()


def count_rows(conn, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]


def count_edges(conn) -> int:
    return count_rows(conn, "provenance_edges")


def event_types(conn) -> set[str]:
    return {r["event_type"] for r in
            conn.execute("SELECT DISTINCT event_type FROM events")}


def admit_extract_task(db, source_ref="dataset_manifest:dm-1",
                      scope="both") -> str:
    """Admit an EXTRACT task via the ordinary gateway and start it (RUNNING)."""
    payload = build_extract_task_payload(source_ref, scope)
    result = apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1", payload=payload))
    task_id = result.entity_id
    tr = TaskRepository(db)
    tr.transition_status(task_id, TaskStatus.READY, caused_by="test")
    tr.transition_status(task_id, TaskStatus.RUNNING, caused_by="test")
    return task_id


# a canonical extraction output (valid against dm-1)
def good_output() -> dict:
    # V6-P7-E03: the draft's source_ref is the artifact the task extracted —
    # it must equal the producing task's spec.source_ref.
    return {
        "source_ref": "dataset_manifest:dm-1",
        "claims": [{
            "ref": "c1",
            "statement": "Alpha reduces beta under gamma conditions.",
            "source_ref": "dataset_manifest:dm-1",
            "support_state": "INFERRED",
            # claim-ground G10: no span on a non-readable carrier (dataset_manifest
            # is unverifiable); the canonical output carries no span.
            "span_ref": None,
            "claim_type": "causal",
            "context_tags": {"regime": "ICSS-v1:low-vol",
                             "dataset_ref": "dm-1"},
            "assumption_refs": ["a1"],
        }],
        "assumptions": [{
            "ref": "a1",
            "statement": "The sample is representative.",
            "context_tags": {"population": "adults-18-65"},
            "supporting_artifact_refs": ["dataset_manifest:dm-1"],
        }],
        "extracted_by": "model_ref:c-tier-1",
        "schema_version": "2",
    }


def output_with_related_claims() -> dict:
    """good_output with a claim carrying non-empty related_claims."""
    out = good_output()
    out["claims"][0]["related_claims"] = ["cl_alpha", "cl_beta"]
    return out


def malformed_output() -> dict:
    """INVALID: a claim referencing a missing assumption."""
    out = good_output()
    out["claims"][0]["assumption_refs"] = ["missing"]
    return out


# ── 1. EXTRACT task template + ordinary INSERT_TASK admission ──

def test_1_exact_template_shape():
    payload = build_extract_task_payload("dataset_manifest:dm-1", "both")
    assert payload["task_type"] == "AGENT_TASK"
    assert payload["profile"] == EXTRACT_PROFILE == "RESEARCHER"
    assert payload["cost_class"] == "small"
    assert payload["task_id"].startswith("extract_")
    assert payload["task_id"] == extract_task_id("dataset_manifest:dm-1", "both")
    assert payload["idempotency_key"] == extract_idempotency_key(
        "dataset_manifest:dm-1", "both")
    assert payload["spec"] == {
        "template": "extract",
        "template_version": EXTRACT_TEMPLATE_VERSION,
        "source_ref": "dataset_manifest:dm-1",
        "scope": "both",
    }
    assert set(payload) == {
        "task_id", "task_type", "profile", "spec", "inputs", "outputs",
        "dependencies", "provenance", "idempotency_key", "iteration",
        "parent_task_id", "cost_class", "concurrency_group", "max_retries",
    }


def test_1b_template_identity_deterministic_and_content_sensitive():
    a = build_extract_task_payload("dataset_manifest:dm-1", "both")
    b = build_extract_task_payload("dataset_manifest:dm-1", "both")
    c = build_extract_task_payload("dataset_manifest:dm-2", "both")
    d = build_extract_task_payload("dataset_manifest:dm-1", "claims")
    assert a["task_id"] == b["task_id"]
    assert a["idempotency_key"] == b["idempotency_key"]
    assert a["task_id"] != c["task_id"]
    assert a["task_id"] != d["task_id"]


def test_1c_bad_scope_rejected():
    import pytest as _pt
    with _pt.raises(ValueError, match="scope"):
        build_extract_task_payload("dataset_manifest:dm-1", "everything")
    with _pt.raises(ValueError, match="artifact_type:ref"):
        build_extract_task_payload("no-colon", "both")


def test_1d_admitted_via_ordinary_insert_task(db):
    """An EXTRACT task lands in the graph through apply_intent — AGENT_TASK,
    C-tier profile, content-derived idempotency key (criterion 1)."""
    payload = build_extract_task_payload("dataset_manifest:dm-1", "both")
    result = apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1", payload=payload))
    assert result.entity_type == "task"
    assert result.duplicate is False
    row = TaskRepository(db).get(result.entity_id)
    assert row["task_type"] == "AGENT_TASK"
    assert row["profile"] == "RESEARCHER"
    assert row["idempotency_key"] == extract_idempotency_key(
        "dataset_manifest:dm-1", "both")
    assert row["status"] == "PENDING"
    # one TaskCreated event (the gateway's own event) — nothing else new
    assert count_rows(db, "tasks") == 1


# ── 2. well-formed output → ADMITTED → rows + links + edges; SUCCEEDED ──

def test_2_acceptance_persists_and_task_succeeds(db):
    task_id = admit_extract_task(db)
    task_repo = TaskRepository(db)

    draft = extraction_draft_from_mapping(good_output())
    outcome = accept_extraction_output(
        db, "p1", task_id, draft, extracted_by="model_ref:c-tier-1")

    assert outcome["verdict"] == "ADMITTED"
    assert len(outcome["claims"]) == 1
    assert len(outcome["assumptions"]) == 1
    assert count_rows(db, "research_claims") == 1
    assert count_rows(db, "research_assumptions") == 1
    assert count_rows(db, "claim_assumption_links") == 1
    assert count_edges(db) == 2  # derived_from + cites

    task_repo.transition_status(task_id, TaskStatus.SUCCEEDED,
                                caused_by="test")
    assert task_repo.get_status(task_id) is TaskStatus.SUCCEEDED


# ── Regression: related_claims integrity (Step 3 redteam FIX 1) ──

def test_2c_related_claims_persisted_without_integrity_error(db):
    """FIX 1 regression: record_extraction must include related_claim_ids in
    the claim_id_of re-derivation call. Pre-fix it omitted the field, so a
    claim with non-empty related_claims would fail the integrity re-check
    with ResearchClaimIntegrityError.

    The claim is advisory cross-ref data (content-addressed cl_ IDs of
    other claims) — it must not raise, and the claim must persist + read
    back with the correct claim_id.
    """
    task_id = admit_extract_task(db)
    draft = extraction_draft_from_mapping(output_with_related_claims())
    outcome = accept_extraction_output(
        db, "p1", task_id, draft, extracted_by="model_ref:c-tier-1")

    # ADMITTED (the integrity re-derivation passed — no ResearchClaimIntegrityError)
    assert outcome["verdict"] == "ADMITTED"
    assert len(outcome["claims"]) == 1

    # the persisted claim's claim_id is stable and correct
    claim_id = outcome["claims"][0]["claim_id"]
    assert claim_id.startswith("cl_")
    assert count_rows(db, "research_claims") == 1

    # reads back from the DB
    row = ClaimAssumptionRepository(db).get_claim(claim_id)
    assert row["claim_id"] == claim_id
    assert row["project_id"] == "p1"
    assert row["statement"] == "Alpha reduces beta under gamma conditions."
    # the related_claim_ids survived persistence (Step 3 FIX 1b — schema)
    assert row["related_claim_ids"] == ("cl_alpha", "cl_beta")


# ── 3. malformed output → no partial write ──

def test_3_malformed_output_rejected_no_partial_write(db):
    task_id = admit_extract_task(db)
    task_repo = TaskRepository(db)

    draft = extraction_draft_from_mapping(malformed_output())
    with pytest.raises(ExtractionOutputRejected) as excinfo:
        accept_extraction_output(db, "p1", task_id, draft,
                                 extracted_by="model_ref:c-tier-1")
    assert "unresolved_assumption_ref" in str(excinfo.value)
    # no partial write
    assert count_rows(db, "research_claims") == 0
    assert count_rows(db, "research_assumptions") == 0
    assert count_rows(db, "claim_assumption_links") == 0
    assert count_edges(db) == 0
    # task remains non-terminal (controller decides FAILED/RETRYING — the
    # wiring itself never transitions the task)
    assert task_repo.get_status(task_id) is TaskStatus.RUNNING


def test_3b_schema_drift_output_fails_closed(db):
    """An unknown key in the output is a hard error, never a silent drop."""
    out = good_output()
    out["claims"][0]["extra_key"] = "sneak"
    with pytest.raises(ValueError, match="unknown keys"):
        extraction_draft_from_mapping(out)
    assert count_rows(db, "research_claims") == 0


# ── 4. crash / re-run idempotency ──

def test_4_rerun_after_crash_idempotent(db):
    task_id = admit_extract_task(db)
    task_repo = TaskRepository(db)

    # first attempt: accepted (task is RUNNING)
    draft = extraction_draft_from_mapping(good_output())
    out1 = accept_extraction_output(db, "p1", task_id, draft,
                                    extracted_by="model_ref:c-tier-1")
    # crash before SUCCEEDED → controller re-runs the same task
    second = apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload=build_extract_task_payload("dataset_manifest:dm-1", "both")))
    assert second.duplicate is True          # task-level idempotency (PA4)
    out2 = accept_extraction_output(
        db, "p1", task_id,
        extraction_draft_from_mapping(good_output()),
        extracted_by="model_ref:c-tier-1")
    # artifact-level idempotency
    assert out1["claims"][0]["claim_id"] == out2["claims"][0]["claim_id"]
    assert count_rows(db, "research_claims") == 1
    assert count_rows(db, "research_assumptions") == 1
    assert count_rows(db, "claim_assumption_links") == 1
    assert count_edges(db) == 2
    assert task_repo.get(task_id)["idempotency_key"] == extract_idempotency_key(
        "dataset_manifest:dm-1", "both")


# ── 5. no new event type ──

def test_5_no_new_event_types(db):
    before = event_types(db)
    task_id = admit_extract_task(db)
    draft = extraction_draft_from_mapping(good_output())
    accept_extraction_output(db, "p1", task_id, draft,
                             extracted_by="model_ref:c-tier-1")
    after = event_types(db)
    # only the gateway's own events (IntentApplied/TaskCreated) plus the
    # task lifecycle events the fixtures themselves cause (TaskStatusChanged)
    # may appear; no ClaimExtractionAdmitted-style type exists
    assert after <= (before | {"IntentApplied", "TaskCreated",
                               "TaskStatusChanged"})


def test_5b_event_allowlist_unchanged(db):
    """The persistence-boundary allowlist derives from the enum catalog —
    nothing added by the pipeline."""
    from hermes.core import events
    from hermes.persistence import event_validation
    allow = set(event_validation.KNOWN_EVENT_TYPES)
    catalog = {e.value for e in events.EventType}
    assert "ClaimExtractionAdmitted" not in catalog
    # ADV-05: the validator catalog is DERIVED from the enum — ONE canonical
    # catalog. The pre-fix hand-maintained allowlist carried five names the
    # enum never declared (BudgetExceeded, EvidenceTransitionProposed,
    # IterationAdvanced, SourceRetracted, ThesisInvestigationCompleted — the
    # F-15 class drift); those are now enum members, so the drift is closed
    # and the delta is exactly ZERO.
    assert (allow - catalog) == set()
    assert (catalog - allow) == set()


# ── 6. never promote evidence / pass gates / set non-ACTIVE status ──

def test_6_acceptance_cannot_promote_or_set_status(db):
    task_id = admit_extract_task(db)
    draft = extraction_draft_from_mapping(good_output())
    outcome = accept_extraction_output(db, "p1", task_id, draft,
                                       extracted_by="model_ref:c-tier-1")
    cl = ClaimAssumptionRepository(db).get_claim(
        outcome["claims"][0]["claim_id"])
    assert "ladder_status" not in cl
    assert "evidence" not in set(cl)
    # status is forced ACTIVE by the write path (V6-P7-F01) — the wiring
    # cannot express a forged status
    assert outcome["assumptions"][0]["status"] == "ACTIVE"
    # no evidence/promotion events and no gate events from the pipeline
    after = event_types(db)
    assert not (after & {"EvidenceTransitionApplied",
                         "EvidenceTransitionRejected",
                         "GatePassed", "GateFailed", "GateEvaluated"})


def test_6b_no_promotion_surface_on_wiring():
    assert not hasattr(accept_extraction_output, "promote")
    import inspect
    src = inspect.getsource(accept_extraction_output)
    assert "EVIDENCE_TRANSITION" not in src
    assert "ladder" not in src


# ── 7. source dereference fails at admission (IDR-027 F02) ──

def test_7_missing_manifest_rejected_at_admission(db):
    payload = build_extract_task_payload("dataset_manifest:dm-999", "both")
    with pytest.raises(GatewayRejection) as excinfo:
        apply_intent(db, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
            project_id="p1", payload=payload))
    assert excinfo.value.code == "PROVENANCE"
    assert count_rows(db, "tasks") == 0
    # and the output-side dereference is also enforced: a task extracting
    # dm-1 whose claim cites a missing manifest is refused at the write path
    task_id = admit_extract_task(db)
    bad = good_output()
    bad["claims"][0]["source_ref"] = "dataset_manifest:dm-999"
    bad["claims"][0]["context_tags"]["dataset_ref"] = "dm-999"
    with pytest.raises(ResearchClaimError, match="dangling"):
        accept_extraction_output(db, "p1", task_id,
                                 extraction_draft_from_mapping(bad),
                                 extracted_by="model_ref:c-tier-1")
    assert count_rows(db, "research_claims") == 0


# ── 8. model_ref recorded, never authoritative lineage ──

def test_8_model_ref_recorded_on_rows(db):
    task_id = admit_extract_task(db)
    outcome = accept_extraction_output(
        db, "p1", task_id, extraction_draft_from_mapping(good_output()),
        extracted_by="model_ref:c-tier-1", reason="extract task t1")
    repo = ClaimAssumptionRepository(db)
    cl = repo.get_claim(outcome["claims"][0]["claim_id"])
    asm = repo.get_assumption(outcome["assumptions"][0]["assumption_id"])
    # extracted_by is recorded on the claim row (the artifact's provenance)
    assert cl["extracted_by"] == "model_ref:c-tier-1"
    assert cl["reason"] == "extract task t1"
    # claim-ground G13: model_ref is a NULLABLE advisory provenance column on
    # the CLAIM row. It records the DECLARED model (the draft's extracted_by),
    # so it equals the declared value. Template and run were NOT declared by
    # this extraction, so they are NULL (unknown, never fabricated). Assumptions
    # carry no model column. No lineage or ladder field exists on either.
    assert "model_ref" in set(cl)
    assert cl["model_ref"] == "model_ref:c-tier-1"
    assert cl["prompt_template_version"] is None
    assert cl["run_id"] is None
    assert "model_ref" not in set(asm)
    assert "ladder_status" not in set(cl)
    assert "ladder_status" not in set(asm)


# ── strict mapping contract ──

def test_mapping_rejects_unknown_draft_key():
    data = good_output()
    data["rogue"] = 1
    with pytest.raises(ValueError, match="unknown keys"):
        extraction_draft_from_mapping(data)


def test_mapping_type_errors():
    with pytest.raises(TypeError):
        extraction_draft_from_mapping([1, 2, 3])
    data = good_output()
    data["claims"] = "not-a-list"
    with pytest.raises(ValueError, match="lists"):
        extraction_draft_from_mapping(data)


# ── V6-P7-E01: the EXTRACT marker is normalized at admission ──

def test_e01_case_spoofed_template_treated_as_extract(db):
    """'Extract'/'EXTRACT' match the normalized marker — so the full EXTRACT
    contract (profile/scope/cost + dereference) applies to them."""
    for spoof in ("Extract", "EXTRACT", " extract "):
        payload = build_extract_task_payload("dataset_manifest:dm-1", "both")
        payload["spec"]["template"] = spoof
        payload["profile"] = "ADVERSARY"          # would slip past pre-fix
        with pytest.raises(GatewayRejection, match="profile") as excinfo:
            apply_intent(db, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
                project_id="p1", payload=payload))
        assert excinfo.value.code == "MALFORMED_PAYLOAD"
        assert count_rows(db, "tasks") == 0


def test_e01_upper_spoof_with_missing_source_still_rejected(db):
    """The strongest form: spoofed marker + missing manifest → PROVENANCE."""
    payload = build_extract_task_payload("dataset_manifest:dm-999", "both")
    payload["spec"]["template"] = "EXTRACT"
    with pytest.raises(GatewayRejection) as excinfo:
        apply_intent(db, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
            project_id="p1", payload=payload))
    assert excinfo.value.code == "PROVENANCE"
    assert count_rows(db, "tasks") == 0


# ── V6-P7-E02: the EXTRACT contract is enforced at admission ──

def test_e02_profile_scope_cost_are_gateway_invariants(db):
    """Hand-built payloads cannot admit EXTRACT tasks with tampered
    profile / scope / cost_class (helper defaults are not the contract)."""
    base = build_extract_task_payload("dataset_manifest:dm-1", "both")

    bad_profile = dict(base)
    bad_profile["profile"] = "ADVERSARY"
    with pytest.raises(GatewayRejection, match="profile") as excinfo:
        apply_intent(db, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
            project_id="p1", payload=bad_profile))
    assert excinfo.value.code == "MALFORMED_PAYLOAD"

    bad_scope = dict(base)
    bad_scope["spec"] = dict(base["spec"])
    bad_scope["spec"]["scope"] = "everything"
    with pytest.raises(GatewayRejection, match="scope") as excinfo:
        apply_intent(db, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
            project_id="p1", payload=bad_scope))
    assert excinfo.value.code == "MALFORMED_PAYLOAD"

    bad_cost = dict(base)
    bad_cost["cost_class"] = "huge"
    with pytest.raises(GatewayRejection, match="cost_class") as excinfo:
        apply_intent(db, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
            project_id="p1", payload=bad_cost))
    assert excinfo.value.code == "MALFORMED_PAYLOAD"

    assert count_rows(db, "tasks") == 0  # nothing admitted


def test_e02_canonical_payload_still_admitted(db):
    """The template's own payload passes the enforced contract."""
    task_id = admit_extract_task(db)
    row = TaskRepository(db).get(task_id)
    assert row["profile"] == "RESEARCHER"
    assert row["cost_class"] == "small"
    assert row["spec"]["scope"] == "both"


# ── V6-P7-E03: acceptance is bound to a producing task ──

def test_e03_acceptance_requires_existing_task(db):
    """No task → refusal, no write."""
    draft = extraction_draft_from_mapping(good_output())
    with pytest.raises(ExtractionNotBoundToTask, match="does not exist"):
        accept_extraction_output(db, "p1", "extract_nonexistent", draft,
                                 extracted_by="model_ref:c-tier-1")
    assert count_rows(db, "research_claims") == 0
    assert count_rows(db, "research_assumptions") == 0


def test_e03_acceptance_requires_running_task(db):
    """A PENDING/SUCCEEDED task cannot have output accepted."""
    payload = build_extract_task_payload("dataset_manifest:dm-1", "both")
    result = apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1", payload=payload))
    task_id = result.entity_id
    # PENDING — never started
    draft = extraction_draft_from_mapping(good_output())
    with pytest.raises(ExtractionNotBoundToTask, match="not RUNNING"):
        accept_extraction_output(db, "p1", task_id, draft,
                                 extracted_by="model_ref:c-tier-1")
    # SUCCEEDED — already finished
    tr = TaskRepository(db)
    tr.transition_status(task_id, TaskStatus.READY, caused_by="test")
    tr.transition_status(task_id, TaskStatus.RUNNING, caused_by="test")
    tr.transition_status(task_id, TaskStatus.SUCCEEDED, caused_by="test")
    with pytest.raises(ExtractionNotBoundToTask, match="not RUNNING"):
        accept_extraction_output(db, "p1", task_id, draft,
                                 extracted_by="model_ref:c-tier-1")
    assert count_rows(db, "research_claims") == 0


def test_e03_source_ref_mismatch_rejected(db):
    """An output describing a different source than the task extracted is
    refused — the draft is not this task's output."""
    task_id = admit_extract_task(db, source_ref="dataset_manifest:dm-1")
    out = good_output()
    out["source_ref"] = "dataset_manifest:dm-2"
    draft = extraction_draft_from_mapping(out)
    with pytest.raises(ExtractionNotBoundToTask, match="source_ref"):
        accept_extraction_output(db, "p1", task_id, draft,
                                 extracted_by="model_ref:c-tier-1")
    assert count_rows(db, "research_claims") == 0


def test_e03_cross_project_task_refused(db):
    """A task from another project cannot accept output into this one."""
    # dm-2 lives in p2 only
    conn = db
    conn.execute(
        """INSERT INTO dataset_manifests
           (manifest_id, project_id, location, format, size_bytes,
            headers_json, schema_observations_json, query_recipes_json,
            content_hash, provenance_json, created_at, immutable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        ("dm-2", "p2", "y.csv", "csv", 1, "[]", "[]", "[]",
         "h2", None, "2026-01-01T00:00:00.000000+00:00"),
    )
    payload = build_extract_task_payload("dataset_manifest:dm-2", "both")
    apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p2", payload=payload))
    tr = TaskRepository(db)
    task_id = payload["task_id"]
    tr.transition_status(task_id, TaskStatus.READY, caused_by="test")
    tr.transition_status(task_id, TaskStatus.RUNNING, caused_by="test")
    draft = extraction_draft_from_mapping(good_output())
    with pytest.raises(ExtractionNotBoundToTask, match="project"):
        accept_extraction_output(db, "p1", task_id, draft,
                                 extracted_by="model_ref:c-tier-1")
    assert count_rows(db, "research_claims") == 0


def test_e03_non_extract_task_refused(db):
    """A RUNNING AGENT_TASK that is not an EXTRACT task cannot feed claims."""
    payload = {
        "task_id": "plain-1",
        "task_type": "AGENT_TASK",
        "profile": "RESEARCHER",
        "idempotency_key": "plain-1-key",
        "iteration": 1,
        "spec": {"template": "analyze", "source_ref": "dataset_manifest:dm-1"},
        "inputs": [],
        "outputs": [],
        "dependencies": [],
        "provenance": [],
        "cost_class": "small",
        "max_retries": 3,
    }
    apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1", payload=payload))
    tr = TaskRepository(db)
    tr.transition_status("plain-1", TaskStatus.READY, caused_by="test")
    tr.transition_status("plain-1", TaskStatus.RUNNING, caused_by="test")
    draft = extraction_draft_from_mapping(good_output())
    with pytest.raises(ExtractionNotBoundToTask, match="not an EXTRACT"):
        accept_extraction_output(db, "p1", "plain-1", draft,
                                 extracted_by="model_ref:c-tier-1")
    assert count_rows(db, "research_claims") == 0
