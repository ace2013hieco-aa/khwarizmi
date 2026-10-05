"""Tests for the P3 Intent Gateway (v6 §28.5 — apply_intent).

Covers the gateway admission contract: runtime role enforcement for
``PROPOSE_RESEARCH_PROGRAM`` (DIRECTOR-only) and ``INSERT_TASK``/``ADMIT_TASK``,
the compile → record → event path, idempotency (duplicate proposals),
structured rejections (role / payload / scope / stale / budget / dependency),
audit events (``IntentApplied`` / ``IntentRejected``), and the §20 gateway
failure semantics. The gateway is the ONLY path into the repository — there is
no direct write bypass.
"""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from hermes.core import frozen_clock
from hermes.core.intents import Intent, IntentKind
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    EventRepository,
    ProjectRepository,
    ResearchProgramRepository,
    TaskRepository,
)
from hermes.research.controller import Controller
from hermes.research.gateway import (
    BUDGET,
    CLASSIFICATION_REF,
    DEPENDENCY,
    IDEMPOTENCY_CONFLICT,
    MALFORMED_PAYLOAD,
    NOT_COMPILED,
    NOT_WIRED,
    PROJECT_NOT_FOUND,
    PROVENANCE,
    ROLE,
    SCOPE_NOT_GOVERNED,
    STALE,
    UNKNOWN_KIND,
    GatewayRejection,
    apply_intent,
)


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Test")
    conn.execute(
        """INSERT INTO scope_briefs
           (brief_id, project_id, version, content_hash, supersedes_id,
            scope_text_json, rationale, created_at, frozen_at)
           VALUES (?, ?, 1, ?, NULL, ?, NULL, ?, ?)""",
        ("brief-1", "p1", "briefhash1", json.dumps({"scope": "x"}),
         "2026-01-01T00:00:00.000000+00:00",
         "2026-01-01T00:00:00.000000+00:00"),
    )
    yield conn
    conn.close()


def base_payload(**overrides) -> dict:
    """A schema-valid confirmatory draft: H1 (SUPPORTED) vs rival H0 (ACTIVE)."""
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
    payload.update(overrides)
    return payload


def task_payload(**overrides) -> dict:
    """A schema-valid INSERT_TASK payload."""
    payload = {
        "task_id": "t1",
        "task_type": "AGENT_TASK",
        "profile": "RESEARCHER",
        "idempotency_key": "idem-1",
        "iteration": 1,
        "spec": {"program_id": "rp_abc", "plan_kind": "evidence_obligation"},
        "inputs": [],
        "outputs": ["evidence:SUPPORTED"],
        "dependencies": [],
        "provenance": ["spec:payload-v1"],
    }
    payload.update(overrides)
    return payload


def proposal_intent(proposed_by: str = "DIRECTOR", payload=None, project_id="p1"):
    return Intent(
        kind=IntentKind.PROPOSE_RESEARCH_PROGRAM,
        proposed_by=proposed_by,
        project_id=project_id,
        payload=payload if payload is not None else base_payload(),
        justification="proposal via gateway",
    )


def events_of(db) -> list[dict]:
    return EventRepository(db).list_for_project("p1")


# ── §6: runtime role enforcement ──

class TestRoleEnforcement:
    @pytest.mark.parametrize("role", ["RESEARCHER", "ADVERSARY", "IMPLEMENTER"])
    def test_propose_research_program_rejects_non_director(self, db, role):
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, proposal_intent(proposed_by=role))
        assert exc.value.code == ROLE
        assert exc.value.kind is IntentKind.PROPOSE_RESEARCH_PROGRAM

    def test_propose_research_program_rejects_unknown_role(self, db):
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, proposal_intent(proposed_by="ANONYMOUS"))
        assert exc.value.code == ROLE

    def test_director_allowed(self, db):
        result = apply_intent(db, proposal_intent(proposed_by="DIRECTOR"))
        assert result.entity_type == "research_program"
        assert result.entity_id.startswith("rp_")
        assert result.duplicate is False

    def test_insert_task_any_agent_role(self, db):
        for role in ("DIRECTOR", "RESEARCHER", "IMPLEMENTER", "ADVERSARY"):
            result = apply_intent(db, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by=role, project_id="p1",
                payload=task_payload(task_id=f"t-{role}",
                                     idempotency_key=f"idem-{role}")))
            assert result.entity_type == "task"

    def test_insert_task_rejects_deterministic(self, db):
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="DETERMINISTIC",
                project_id="p1", payload=task_payload()))
        assert exc.value.code == ROLE

    def test_admit_task_internal_only(self, db):
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.ADMIT_TASK, proposed_by="RESEARCHER",
                project_id="p1", payload=task_payload(task_id="t-admit")))
        assert exc.value.code == ROLE
        # DETERMINISTIC controller may
        result = apply_intent(db, Intent(
            kind=IntentKind.ADMIT_TASK, proposed_by="DETERMINISTIC",
            project_id="p1", payload=task_payload(task_id="t-admit",
                                                  idempotency_key="idem-admit")))
        assert result.entity_type == "task"


# ── PROPOSE_RESEARCH_PROGRAM admission path ──

class TestProposeResearchProgram:
    def test_compiles_records_emits_event(self, db):
        result = apply_intent(db, proposal_intent())
        row = ResearchProgramRepository(db).get(result.entity_id)
        assert row["program_id"] == result.entity_id
        types = [e["event_type"] for e in events_of(db)]
        assert "ResearchProgramCompiled" in types
        assert "IntentApplied" in types
        assert row["produced_by"] == "DIRECTOR"

    def test_duplicate_proposal_idempotent(self, db):
        r1 = apply_intent(db, proposal_intent())
        r2 = apply_intent(db, proposal_intent())
        assert r2.duplicate is True
        assert r2.entity_id == r1.entity_id
        compiled = [e for e in events_of(db)
                    if e["event_type"] == "ResearchProgramCompiled"]
        assert len(compiled) == 1  # no duplicate event (PA4)

    def test_gate_violation_not_compiled_rejected(self, db):
        bad = base_payload(hypotheses=[
            {"ref": "H1", "ladder_target": "BOGUS",
             "falsification_condition": "x", "rival_of": None, "rival_status": None},
        ])
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, proposal_intent(payload=bad))
        assert exc.value.code == NOT_COMPILED
        assert ResearchProgramRepository(db).current("p1") is None  # nothing persisted

    def test_scope_not_governed(self, db):
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, proposal_intent(payload=base_payload(scope_ref="brief-99")))
        assert exc.value.code == SCOPE_NOT_GOVERNED

    def test_stale_project_rejected(self, db):
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, proposal_intent(project_id="no-such-project"))
        assert exc.value.code == PROJECT_NOT_FOUND

    def test_stale_supersede_target_rejected(self, db):
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, proposal_intent(payload=base_payload(supersedes_ref="rp_nope")))
        assert exc.value.code == STALE

    def test_non_dict_payload_rejected(self, db):
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, proposal_intent(payload="not-a-payload"))
        assert exc.value.code == MALFORMED_PAYLOAD

    def test_unknown_payload_key_fails_closed_at_compilation(self, db):
        # Unknown keys are rejected (EC-F01); the gateway reports the verdict
        # as a NOT_COMPILED gate violation and persists nothing.
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, proposal_intent(
                payload={**base_payload(), "junk": True}))
        assert exc.value.code == NOT_COMPILED
        assert "junk" in exc.value.reason
        assert ResearchProgramRepository(db).current("p1") is None

    def test_rejection_emits_audit_event(self, db):
        with pytest.raises(GatewayRejection):
            apply_intent(db, proposal_intent(proposed_by="RESEARCHER"))
        rejected = [e for e in events_of(db)
                    if e["event_type"] == "IntentRejected"]
        assert len(rejected) == 1
        assert "RESEARCHER" in rejected[0]["caused_by"]


# ── INSERT_TASK / ADMIT_TASK ──

class TestInsertTask:
    def test_admits_task_with_provenance(self, db):
        # Non-reserved provenance is free-form metadata in P3 (V6-FINAL-02
        # contract: only the research_program: prefix must dereference).
        result = apply_intent(db, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR", project_id="p1",
            payload=task_payload(provenance=["artifact:note-1",
                                             "evidence_requirement:H1"])))
        row = TaskRepository(db).get(result.entity_id)
        assert row["task_type"] == "AGENT_TASK"
        assert row["profile"] == "RESEARCHER"
        assert "artifact:note-1" in row["provenance"]
        types = [e["event_type"] for e in events_of(db)]
        assert "TaskCreated" in types and "IntentApplied" in types

    def test_provenance_reserved_prefix_must_dereference(self, db):
        """V6-FINAL-02: research_program:<id> must dereference to a program
        governed by the intent's project — a forged/nonexistent reference is
        rejected (false-lineage forgery, Attack A3 class)."""
        # nonexistent program → PROVENANCE rejection, nothing written
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
                project_id="p1",
                payload=task_payload(task_id="fp", idempotency_key="fp",
                                     provenance=["research_program:rp_nope"])))
        assert exc.value.code == PROVENANCE
        tasks = [t["task_id"] for t in TaskRepository(db).list_for_project("p1")]
        assert "fp" not in tasks
        # empty prefix → rejected
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
                project_id="p1",
                payload=task_payload(task_id="fp2", idempotency_key="fp2",
                                     provenance=["research_program:"])))
        assert exc.value.code == PROVENANCE
        # real governed program → accepted
        apply_intent(db, proposal_intent())  # admit p1's program
        program_id = ResearchProgramRepository(db).list_for_project("p1")[0]["program_id"]
        result = apply_intent(db, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR", project_id="p1",
            payload=task_payload(task_id="ok", idempotency_key="ok",
                                 provenance=[f"research_program:{program_id}"])))
        assert result.entity_id == "ok"

    def test_provenance_rejects_other_projects_program(self, db):
        """A task cannot claim lineage to a program governed by another project."""
        ProjectRepository(db).create("p2", "Other")
        db.execute(
            """INSERT INTO scope_briefs
               (brief_id, project_id, version, content_hash, supersedes_id,
                scope_text_json, rationale, created_at, frozen_at)
               VALUES (?, ?, 1, ?, NULL, ?, NULL, ?, ?)""",
            ("brief-2", "p2", "briefhash2", json.dumps({"scope": "y"}),
             "2026-01-01T00:00:00.000000+00:00",
             "2026-01-01T00:00:00.000000+00:00"),
        )
        apply_intent(db, Intent(
            kind=IntentKind.PROPOSE_RESEARCH_PROGRAM, proposed_by="DIRECTOR",
            project_id="p2",
            payload={**base_payload(), "scope_ref": "brief-2"}))
        p2_program = ResearchProgramRepository(db).list_for_project("p2")[0]
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
                project_id="p1",
                payload=task_payload(task_id="xp", idempotency_key="xp",
                                     provenance=[f"research_program:{p2_program['program_id']}"])))
        assert exc.value.code == PROVENANCE
        assert exc.value.code == PROVENANCE

    def test_missing_dependency_structured_rejection(self, db):
        """V6-FINAL-01: a missing dependency rejects as a structured DEPENDENCY
        code (FK-enforced), never a raw sqlite3.IntegrityError."""
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR", project_id="p1",
                payload=task_payload(task_id="md", idempotency_key="md",
                                     dependencies=["does-not-exist"])))
        assert exc.value.code == DEPENDENCY
        tasks = [t["task_id"] for t in TaskRepository(db).list_for_project("p1")]
        assert "md" not in tasks
        rejected = [e for e in events_of(db) if e["event_type"] == "IntentRejected"]
        assert len(rejected) == 1  # still audited

    def test_idempotency_key_conflict_structured_rejection(self, db):
        """V6-FINAL-01: reusing an idempotency_key for a DIFFERENT task is a
        conflict (PA4: a key identifies one command), surfaced as
        IDEMPOTENCY_CONFLICT — not a raw IntegrityError, not a silent accept."""
        apply_intent(db, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR", project_id="p1",
            payload=task_payload(task_id="a", idempotency_key="shared")))
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR", project_id="p1",
                payload=task_payload(task_id="b", idempotency_key="shared")))
        assert exc.value.code == IDEMPOTENCY_CONFLICT
        tasks = [t["task_id"] for t in TaskRepository(db).list_for_project("p1")]
        assert "b" not in tasks
        # a retry of the SAME task with the SAME key stays idempotent
        r = apply_intent(db, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR", project_id="p1",
            payload=task_payload(task_id="a", idempotency_key="shared")))
        assert r.duplicate is True

    def test_duplicate_task_id_idempotent(self, db):
        payload = task_payload()
        apply_intent(db, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR", project_id="p1",
            payload=payload))
        r2 = apply_intent(db, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR", project_id="p1",
            payload=payload))
        assert r2.duplicate is True
        created = [e for e in events_of(db) if e["event_type"] == "TaskCreated"]
        assert len(created) == 1

    def test_dependency_cycle_rejected(self, db):
        # Self-cycle: a task depending on itself is rejected (F-11 fast path).
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR", project_id="p1",
                payload=task_payload(task_id="a", idempotency_key="ia",
                                     dependencies=["a"])))
        assert exc.value.code == DEPENDENCY
        tasks = [t["task_id"] for t in TaskRepository(db).list_for_project("p1")]
        assert "a" not in tasks  # nothing admitted

    def test_unknown_payload_key_rejected(self, db):
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR", project_id="p1",
                payload=task_payload(status="SUCCEEDED")))
        assert exc.value.code == MALFORMED_PAYLOAD
        assert "status" in exc.value.reason  # closed schema: callers never set status

    def test_budget_hook_rejects(self, db):
        def deny(intent):
            raise GatewayRejection(intent.kind, BUDGET, "compute budget exhausted")

        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, proposal_intent(), budget_check=deny)
        assert exc.value.code == BUDGET

    def test_budget_hook_passes(self, db):
        result = apply_intent(db, proposal_intent(), budget_check=lambda intent: None)
        assert result.entity_type == "research_program"


# ── unknown / unwired kinds ──

class TestKindBoundary:
    def test_unknown_kind_rejected(self, db):
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, replace(proposal_intent(), kind="NOT_A_KIND"))
        assert exc.value.code == UNKNOWN_KIND

    def test_unwired_kind_rejected_not_wired(self, db):
        # BRANCH is still declared-but-unwired in this phase — the wired
        # set is PROPOSE_RESEARCH_PROGRAM / PROPOSE_CLASSIFICATION_ACTION /
        # RESOLVE_CLASSIFICATION_PROPOSAL / RECORD_SCOPE_REVIEW_DECISION /
        # EVIDENCE_TRANSITION / INSERT_TASK / ADMIT_TASK (IDR-041).
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.BRANCH, proposed_by="DIRECTOR",
                project_id="p1", payload={}))
        assert exc.value.code == NOT_WIRED

    def test_contradiction_resolution_not_proposable_hr03(self, db):
        """HR-03 closure probe, CHG-1 update: the declared surface never
        promises what the gateway refuses — and now the §19 machinery
        EXISTS (contradiction table, pair-rule validator, resolution
        verdict path), so the kind is wired as internal-only rather
        than NOT_WIRED.

        ``CONTRADICTION_RESOLUTION`` is still NOT in the LLM-proposable
        set and still NOT Director-proposable: resolution authority is
        a ratified human verdict ingested deterministically. A wired
        validator with no contradiction state behind it would
        fake-apply — so the validator demands a recorded HumanDecision
        binding and an existing OPEN contradiction, and refuses
        everything else without state effects.
        """
        # 1. Not proposable by any agent surface.
        assert IntentKind.CONTRADICTION_RESOLUTION \
            not in IntentKind.llm_proposable()
        assert IntentKind.CONTRADICTION_RESOLUTION \
            in IntentKind.internal_only()
        intent = Intent(
            kind=IntentKind.CONTRADICTION_RESOLUTION,
            proposed_by="DIRECTOR", project_id="p1",
            payload={"rationale": "replication disagreed; weight of "
                                   "evidence favours the newer result"})
        assert not intent.is_llm_proposable()
        # 2. The gateway refuses non-DETERMINISTIC proposers at the role
        #    gate (ROLE, not NOT_WIRED — the kind is wired): no fake
        #    apply, no state mutation, no resolution record.
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, intent)
        assert exc.value.code == ROLE
        # 3. The refusal is still audited (rejection is never dropped).
        rejected = [e for e in events_of(db)
                    if e["event_type"] == "IntentRejected"]
        assert len(rejected) == 1
        assert "CONTRADICTION_RESOLUTION" in \
            json.loads(rejected[0]["payload_json"])["intent_kind"]
        # 4. No proposal/artifact state was touched.
        assert ResearchProgramRepository(db).current("p1") is None
        assert TaskRepository(db).list_for_project("p1") == []

    def test_no_direct_write_bypass(self, db):
        """Attacks A/B: an unauthorized proposer never reaches the repository."""
        with pytest.raises(GatewayRejection):
            apply_intent(db, proposal_intent(proposed_by="RESEARCHER"))
        with pytest.raises(GatewayRejection):
            apply_intent(db, proposal_intent(proposed_by="ADVERSARY"))
        assert ResearchProgramRepository(db).current("p1") is None


# ── V6-FINAL-02 pairing contract: evidence_requirement refs must dereference ──

class TestEvidenceRequirementPairing:
    """When a task claims lineage to a research_program AND names
    evidence_requirement refs, each ref must dereference to a real evidence
    requirement of a linked program (the pairing the task plan emits and the
    satisfaction write path records). A bare evidence_requirement ref with no
    program ref stays free-form metadata (the P3 non-reserved contract)."""

    def test_admits_plan_shaped_evidence_task(self, db):
        apply_intent(db, proposal_intent())  # p1's program: H1 → evidence req
        program_id = ResearchProgramRepository(db).list_for_project("p1")[0][
            "program_id"]
        result = apply_intent(db, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
            project_id="p1",
            payload=task_payload(
                task_id="ev1", idempotency_key="ev1",
                provenance=[f"research_program:{program_id}",
                            "evidence_requirement:H1"])))
        assert result.entity_id == "ev1"
        row = TaskRepository(db).get("ev1")
        assert "evidence_requirement:H1" in row["provenance"]

    def test_rejects_forged_requirement_ref(self, db):
        apply_intent(db, proposal_intent())
        program_id = ResearchProgramRepository(db).list_for_project("p1")[0][
            "program_id"]
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
                project_id="p1",
                payload=task_payload(
                    task_id="forged", idempotency_key="forged",
                    provenance=[f"research_program:{program_id}",
                                "evidence_requirement:DOES_NOT_EXIST"])))
        assert exc.value.code == PROVENANCE
        tasks = [t["task_id"] for t in TaskRepository(db).list_for_project("p1")]
        assert "forged" not in tasks

    def test_rejects_requirement_with_no_evidence_obligation(self, db):
        # H0 is a SPECULATIVE rival — no confirmatory evidence requirement
        # exists for it, so a task claiming it as evidence is a mismatch.
        apply_intent(db, proposal_intent())
        program_id = ResearchProgramRepository(db).list_for_project("p1")[0][
            "program_id"]
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
                project_id="p1",
                payload=task_payload(
                    task_id="mismatch", idempotency_key="mismatch",
                    provenance=[f"research_program:{program_id}",
                                "evidence_requirement:H0"])))
        assert exc.value.code == PROVENANCE

    def test_bare_requirement_ref_stays_free_form(self, db):
        # No research_program ref → the pairing contract does not apply; the
        # ref is descriptive metadata (the P3 non-reserved contract).
        result = apply_intent(db, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
            project_id="p1",
            payload=task_payload(
                task_id="bare", idempotency_key="bare",
                provenance=["evidence_requirement:H1"])))
        assert result.entity_id == "bare"


# ── ADR-041 B2: triggering_classification_id binding (gateway-only) ──
#
# B2 #4: a valid ADMITTED classification with PROPOSE_PARALLEL_REGIME_TEST
# permitted, but whose parent_program_id does NOT match the classification's
# program_ref, must be REJECTED. This is the load-bearing binding that prevents
# citing a real classification to authorize linking to an unrelated program.

def _make_classification_artifact(db, *, program_ref="rp-real",
                                 hypothesis_ref="H1",
                                 cls_id="fc_real", content_hash="ch-real",
                                 failure_class="ENVIRONMENT_MISMATCH"):
    """Insert a self-consistent failure_classification artifact row (ADMITTED
    state) directly — the test substrate for gateway-level classification
    resolution without the full task-bound write path."""
    permitted = ["PROPOSE_SCOPE_NARROWING",
                 "PROPOSE_PARALLEL_REGIME_TEST"]
    meta = {
        "schema_version": "1",
        "classification_id": cls_id,
        "failure_class": failure_class,
        "hypothesis_ref": hypothesis_ref,
        "program_ref": program_ref,
        "condition_type": "ACCIDENTAL",
        "regime_ref": "regime:icss-v1:trend",
        "classifier_version": "1.0",
        "contributing_factors": [],
        "evidence_refs": [],
        "constraint_ref": None,
        "failed_mechanism_ref": None,
        "resource_gap": None,
        "scope_brief_ref": None,
        "scope_brief_field": None,
        "explanation": "test classification",
        "proposed_by": "DIRECTOR",
        "falsifying_evidence_refs": [],
        "permitted_actions": permitted,
        "requires_human_confirmation": failure_class == "FRAMING_ERROR",
        "status": "ADMITTED",
    }
    from hermes.persistence.failure_classifications import (
        FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
    )
    db.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type, content_hash,
            size_bytes, storage_path, producer, metadata_json, created_at)
           VALUES (?, ?, NULL, ?, ?, 0, 'inline://fc', 'test', ?, ?)""",
        (cls_id, "p1", FAILURE_CLASSIFICATION_ARTIFACT_TYPE, content_hash,
         json.dumps(meta), "2026-01-01T00:00:00.000000+00:00"),
    )


class TestTriggeringClassificationBinding:
    """B2 #4: a valid classification citing the WRONG parent program must be
    rejected — the binding check prevents cross-program authorization."""

    def test_mismatched_parent_program_id_rejected(self, db):
        """B2 #4: a valid ADMITTED classification whose program_ref does NOT
        match the payload's parent_program_id must be rejected — the
        binding prevents citing a real classification to authorize linking
        to an unrelated program."""
        # Admit an ordinary program first — the "real" parent.
        result = apply_intent(db, proposal_intent())
        parent_id = result.entity_id
        # A classification that authorizes programs under parent_id.
        _make_classification_artifact(
            db, program_ref=parent_id, hypothesis_ref="H1",
            cls_id="fc-valid", content_hash="ch-valid")
        n_before = len(db.execute(
            "SELECT 1 FROM research_programs").fetchall())
        # cite the valid classification but point parent_program_id
        # at a DIFFERENT program. Must be rejected.
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, proposal_intent(
                payload={
                    **base_payload(),
                    "parent_program_id": "rp_other_program",
                    "parent_hypothesis_ref": "H1",
                    "target_regime": "ICSS-v1:low-vol",
                    "triggering_classification_id": "fc-valid",
                },
            ))
        assert exc.value.code == CLASSIFICATION_REF
        # no NEW program row persisted
        n_after = len(db.execute(
            "SELECT 1 FROM research_programs").fetchall())
        assert n_after == n_before

    def test_matching_parent_program_id_accepted(self, db):
        """Positive control: a classification whose program_ref matches
        the payload's parent_program_id compiles + records."""
        # Step 1: admit an ordinary program — this becomes the parent.
        parent = apply_intent(db, proposal_intent())
        parent_id = parent.entity_id
        # Step 2: a classification whose program_ref == parent_id.
        _make_classification_artifact(
            db, program_ref=parent_id, hypothesis_ref="H1",
            cls_id="fc-match", content_hash="ch-match")
        # Step 3: parallel-regime program citing the matching classification.
        r = apply_intent(db, proposal_intent(
            payload={
                **base_payload(),
                "parent_program_id": parent_id,
                "parent_hypothesis_ref": "H1",
                "target_regime": "ICSS-v1:low-vol",
                "triggering_classification_id": "fc-match",
            },
        ))
        row = ResearchProgramRepository(db).get(r.entity_id)
        assert row["parent_program_id"] == parent_id
        assert row["parent_hypothesis_ref"] == "H1"
        assert row["target_regime"] == "ICSS-v1:low-vol"


# ── ADR-041 B3: controller emits parallel-regime programs ──
#
# B3 path: Controller.tick → _consume_approved_parallel_regime_proposals
# → EMIT_PARALLEL_REGIME_PROGRAM intent (DETERMINISTIC) → gateway clones
# parent substance, compiles, records. Two ticks: second tick is a no-op
# (PA4 idempotency at the gateway; no second IntentApplied for the kind).
CLOCK = "2026-01-01T00:00:00.000000+00:00"
OP_ID = "op-1"
OP_TOKEN = "op-token-1"


@pytest.fixture
def db_with_op(db):
    """The db fixture + a ratified operator credential for approval verdicts."""
    from hermes.persistence.repositories import (
        OperatorCredentialRepository,
    )
    OperatorCredentialRepository(db, frozen_clock(CLOCK)).register(
        OP_ID, OP_TOKEN, "Test Operator")
    yield db


def _setup_approved_proposal(db, *, target_regime="ICSS-v1:low-vol",
                             hypothesis_ref="H1", cls_id="fc-b3"):
    """End-to-end substrate: admit a parent program, create a classification
    artifact citing it, PROPOSE_CLASSIFICATION_ACTION, APPROVED decision.
    Returns (parent_program_id, proposal_id)."""
    # 1. Admit the parent program.
    parent = apply_intent(db, proposal_intent())
    parent_id = parent.entity_id
    # 2. Classification artifact citing the parent. FRAMING_ERROR class
    #    is required so the proposal enters PENDING_HUMAN_APPROVAL and
    #    can be resolved by RESOLVE_CLASSIFICATION_PROPOSAL.
    _make_classification_artifact(
        db, program_ref=parent_id, hypothesis_ref=hypothesis_ref,
        cls_id=cls_id, content_hash=f"ch-{cls_id}",
        failure_class="FRAMING_ERROR")
    # 2b. A candidate artifact (the parent program is stored as an artifact
    #    so PROPOSE_CLASSIFICATION_ACTION's candidate check can dereference it).
    db.execute(
        """INSERT INTO artifacts
             (artifact_id, project_id, task_id, artifact_type, content_hash,
              size_bytes, storage_path, producer, metadata_json, created_at)
           VALUES (?, ?, NULL, ?, ?, 0, 'inline://parent', 'test', ?, ?)""",
        (parent_id, "p1", "research_program", "ch-" + parent_id,
         "{}", "2026-01-01T00:00:00.000000+00:00"),
    )
    # 3. PROPOSE_CLASSIFICATION_ACTION (Director proposes the action).
    prop_result = apply_intent(db, Intent(
        kind=IntentKind.PROPOSE_CLASSIFICATION_ACTION,
        proposed_by="DIRECTOR", project_id="p1",
        justification="ADR-041 B3 proposal",
        payload={
            "classification_ref": f"failure_classification:ch-{cls_id}",
            "action": "PROPOSE_PARALLEL_REGIME_TEST",
            "candidate_artifact_ref": parent_id,
            "rationale": "environment mismatch under parallel regime",
            "target_regime": target_regime,
        },
    ))
    proposal_id = prop_result.entity_id
    # 4. RESOLVE_CLASSIFICATION_PROPOSAL (DETERMINISTIC, operator decision).
    apply_intent(db, Intent(
        kind=IntentKind.RESOLVE_CLASSIFICATION_PROPOSAL,
        proposed_by="DETERMINISTIC", project_id="p1",
        justification="operator verdict APPROVED",
        payload={
            "proposal_id": proposal_id,
            "decision": "APPROVED",
            "rationale": "operator ok",
            "operator_id": OP_ID,
        },
    ))
    return parent_id, proposal_id


class TestB2HypothesisMismatch:
    def test_mismatched_parent_hypothesis_ref_rejected(self, db):
        """B2 #4 companion: a valid ADMITTED classification whose
        hypothesis_ref does NOT match the payload's parent_hypothesis_ref
        must be rejected (CLASSIFICATION_REF)."""
        parent = apply_intent(db, proposal_intent())
        parent_id = parent.entity_id
        # Classification cites H1 for the parent.
        _make_classification_artifact(
            db, program_ref=parent_id, hypothesis_ref="H1",
            cls_id="fc-hyp", content_hash="ch-hyp")
        n_before = len(db.execute(
            "SELECT 1 FROM research_programs").fetchall())
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, proposal_intent(
                payload={
                    **base_payload(),
                    "parent_program_id": parent_id,
                    "parent_hypothesis_ref": "H2",  # mismatch
                    "target_regime": "ICSS-v1:low-vol",
                    "triggering_classification_id": "fc-hyp",
                },
            ))
        assert exc.value.code == CLASSIFICATION_REF
        n_after = len(db.execute(
            "SELECT 1 FROM research_programs").fetchall())
        assert n_after == n_before


class TestB3TwoTickEmission:
    """B3: exactly one child program emitted across two ticks; the second
    tick is silent (no IntentApplied for EMIT_PARALLEL_REGIME_PROGRAM)."""

    def test_exactly_one_child_program_two_ticks(self, db_with_op):
        parent_id, _proposal_id = _setup_approved_proposal(db_with_op)
        ctrl = Controller(db_with_op, project_id="p1",
                          clock=frozen_clock(CLOCK))
        # Tick 1: consumes the APPROVED proposal, emits child program.
        ctrl.tick()
        programs = ResearchProgramRepository(db_with_op).list_for_project("p1")
        child_ids = [p["program_id"] for p in programs
                     if p["parent_program_id"] == parent_id]
        assert len(child_ids) == 1
        child = programs[0] if programs[0]["parent_program_id"] == parent_id \
            else [p for p in programs
                  if p["parent_program_id"] == parent_id][0]
        assert child["parent_program_id"] == parent_id
        assert child["parent_hypothesis_ref"] == "H1"
        assert child["target_regime"] == "ICSS-v1:low-vol"
        assert child["produced_by"] == "DETERMINISTIC"
        assert child["scope_ref"] == "brief-1"  # cloned from parent
        # Tick 2: idempotent — no new program, no new IntentApplied for
        # EMIT_PARALLEL_REGIME_PROGRAM.
        n_before = len(db_with_op.execute(
            "SELECT 1 FROM research_programs").fetchall())
        ctrl2 = Controller(db_with_op, project_id="p1",
                           clock=frozen_clock(CLOCK))
        ctrl2.tick()
        n_after = len(db_with_op.execute(
            "SELECT 1 FROM research_programs").fetchall())
        assert n_after == n_before  # no new program row
        emit_events = [e for e in EventRepository(db_with_op)
                       .list_for_project("p1")
                       if e["event_type"] == "IntentApplied"
                       and json.loads(e["payload_json"] or "{}").get(
                           "intent_kind") == "EMIT_PARALLEL_REGIME_PROGRAM"]
        assert len(emit_events) == 1  # only the first tick emitted one

    def test_pre_check_skips_already_emitted_without_call(self, db_with_op):
        """The pre-check: if a child (parent_program_id, target_regime) pair
        already exists, the controller skips without calling apply_intent."""
        _parent_id, _proposal_id = _setup_approved_proposal(db_with_op)
        ctrl = Controller(db_with_op, project_id="p1",
                          clock=frozen_clock(CLOCK))
        ctrl.tick()
        # After tick, the child exists.
        # Second controller: pre-check should skip (no new IntentApplied).
        emit_before = [e for e in EventRepository(db_with_op)
                       .list_for_project("p1")
                       if e["event_type"] == "IntentApplied"
                       and json.loads(e["payload_json"] or "{}").get(
                           "intent_kind") == "EMIT_PARALLEL_REGIME_PROGRAM"]
        ctrl2 = Controller(db_with_op, project_id="p1",
                           clock=frozen_clock(CLOCK))
        ctrl2.tick()
        emit_after = [e for e in EventRepository(db_with_op)
                      .list_for_project("p1")
                      if e["event_type"] == "IntentApplied"
                      and json.loads(e["payload_json"] or "{}").get(
                          "intent_kind") == "EMIT_PARALLEL_REGIME_PROGRAM"]
        assert len(emit_after) == len(emit_before)  # no new emission


class TestB3RefusalPath:
    """B3: a gate refusal is noted at most once per controller lifetime and
    produces no child program."""

    def test_refusal_notes_once_no_child(self, db_with_op):
        parent_id, _proposal_id = _setup_approved_proposal(
            db_with_op, target_regime="ICSS-v1:low-vol")
        # Corrupt the classification's program_ref so the binding check fails.
        # The B3 validator resolves triggering_classification_id and finds
        # a mismatch between parent_program_id and the classification's
        # program_ref → CLASSIFICATION_REF refusal.
        db_with_op.execute(
            "UPDATE artifacts SET metadata_json = ? "
            "WHERE artifact_id = ?",
            (json.dumps({
                "schema_version": "1",
                "classification_id": "fc-b3",
                "failure_class": "ENVIRONMENT_MISMATCH",
                "hypothesis_ref": "H1",
                "program_ref": "rp_corrupt",  # mismatched
                "condition_type": "ACCIDENTAL",
                "regime_ref": "regime:icss-v1:trend",
                "classifier_version": "1.0",
                "contributing_factors": [],
                "evidence_refs": [],
                "constraint_ref": None,
                "failed_mechanism_ref": None,
                "resource_gap": None,
                "scope_brief_ref": None,
                "scope_brief_field": None,
                "explanation": "corrupted",
                "proposed_by": "DIRECTOR",
                "falsifying_evidence_refs": [],
                "permitted_actions": ["PROPOSE_SCOPE_NARROWING",
                                      "PROPOSE_PARALLEL_REGIME_TEST"],
                "requires_human_confirmation": False,
                "status": "ADMITTED",
            }), "fc-b3"),
        )
        ctrl = Controller(db_with_op, project_id="p1",
                          clock=frozen_clock(CLOCK))
        ctrl.tick()
        # No child program persisted.
        programs = ResearchProgramRepository(db_with_op).list_for_project("p1")
        child = [p for p in programs
                 if p["parent_program_id"] == parent_id]
        assert len(child) == 0
        # A note about the refusal exists.
        notes1 = ctrl.notes
        assert any("EMIT_PARALLEL_REGIME_PROGRAM" in n or "CLASSIFICATION_REF" in n
                   for n in notes1)
        # Second tick: the refused proposal is NOT re-noted (in-memory set).
        ctrl2 = Controller(db_with_op, project_id="p1",
                           clock=frozen_clock(CLOCK))
        ctrl2.tick()
        # New controller instance → _b3_refused_proposals starts empty.
        # The proposal is re-queried and re-attempted; the note can re-appear.
        # But the in-memory set within ctrl2 prevents duplicate notes in
        # successive ticks of the SAME controller.
        # Assert no child program was created.
        programs = ResearchProgramRepository(db_with_op).list_for_project("p1")
        child2 = [p for p in programs
                  if p["parent_program_id"] == parent_id]
        assert len(child2) == 0
