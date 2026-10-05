"""v6 adversarial attack battery (Part 5 §21, attacks A–N).

Every attack must either fail, be routed through the correct authority, or be
explicitly handled per v6. This battery attacks the integrated P3 path:
gateway admission (A/B/C), repository integrity (D–G), authority boundaries
(H/I/J/K/L), staleness (M), and crash/retry idempotency (N). Attacks D–G
re-assert the Step-5 integrity boundary (EC-V6-11..16) at the attack level;
the gateway-level claim is that an attacker CANNOT inject a forged program
through ``apply_intent`` at all — the gateway only accepts schema'd payloads.
"""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from hermes.core.intents import Intent, IntentKind
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    EventRepository,
    ProjectRepository,
    ResearchProgramIntegrityError,
    ResearchProgramRepository,
)
from hermes.research.evaluation import (
    CandidateAction,
    DimensionLevel,
    evaluate_candidates,
)
from hermes.research.gateway import GatewayRejection, apply_intent
from hermes.research.programs import (
    CompilationResult,
    CompilationStatus,
    compile_from_payload,
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
        "discrimination_requirements": [],
        "methodology_constraints": ["icss-v1"],
        "task_graph_template_ref": None,
        "compiler_version": "1.0.0",
        "policy_version": "rp-2026.1",
        "schema_version": "1",
        "supersedes_ref": None,
    }
    payload.update(overrides)
    return payload


def compiled(db, payload=None):
    return compile_from_payload(
        payload or base_payload(), project_id="p1",
        scope_content_hash="briefhash1")


class TestAttacksAB:
    """A: Researcher proposes a ResearchProgram. B: Adversary does too."""

    @pytest.mark.parametrize("role", ["RESEARCHER", "ADVERSARY"])
    def test_unauthorized_proposer_rejected_nothing_persisted(self, db, role):
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.PROPOSE_RESEARCH_PROGRAM, proposed_by=role,
                project_id="p1", payload=base_payload()))
        assert exc.value.code == "ROLE"
        assert ResearchProgramRepository(db).current("p1") is None


class TestAttackC:
    """C: Director submits a forged COMPILED program.

    The gateway never accepts a forged COMPILED object: it only admits
    schema'd payloads (identity/status fields are unknown keys → rejected at
    compilation), and a forged object handed directly to the repository is
    rejected by the Step-5 integrity boundary (EC-V6-11..16).
    """

    def test_payload_cannot_carry_forged_identity(self, db):
        forged = base_payload(content_hash="forged", program_id="rp_forged")
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.PROPOSE_RESEARCH_PROGRAM, proposed_by="DIRECTOR",
                project_id="p1", payload=forged))
        assert exc.value.code == "NOT_COMPILED"
        assert ResearchProgramRepository(db).current("p1") is None

    def test_forged_compiled_object_rejected_at_write_path(self, db):
        result = compiled(db)
        forged = replace(result.program, content_hash="forged-content-hash",
                         program_id="rp_attacker")
        repo = ResearchProgramRepository(db)
        with pytest.raises(ResearchProgramIntegrityError):
            repo.record("p1", CompilationResult(CompilationStatus.COMPILED, (), forged))
        assert repo.list_for_project("p1") == []


class TestAttacksDEFG:
    """D–G: forged content hash / program id / input hash / obligations."""

    def _forge(self, db, **replacements):
        result = compiled(db)
        return replace(result.program, **replacements)

    @pytest.mark.parametrize("replacement", [
        {"content_hash": "forged-content-hash"},
        {"program_id": "rp_attacker-chosen"},
        {"input_hash": "forged-input-hash"},
        {"schema_version": "9"},
        {"evidence_requirements": ()},
        {"gate_requirements": ()},
    ])
    def test_identity_and_obligation_forgery_rejected(self, db, replacement):
        repo = ResearchProgramRepository(db)
        forged = self._forge(db, **replacement)
        with pytest.raises(ResearchProgramIntegrityError):
            repo.record("p1", CompilationResult(
                CompilationStatus.COMPILED, (), forged))
        assert repo.list_for_project("p1") == []
        assert [e for e in EventRepository(db).list_for_project("p1")
                if e["event_type"] == "ResearchProgramCompiled"] == []


class TestAttacksHI:
    """H: ResearchProgram attempts direct task creation. I: evidence promotion."""

    def test_h_task_plan_has_no_write_surface(self):
        import inspect

        import hermes.research.task_plan as tp
        # pure projection: no DB / repository / event imports in the module
        source = inspect.getsource(tp)
        for banned in ("sqlite3", "import repositories", "persistence.",
                       "_append_event_to_db"):
            assert banned not in source

    def test_i_payload_cannot_promote_evidence(self, db):
        # E8: no status field exists in the program schema; unknown keys such
        # as an evidence-status claim fail closed at compilation.
        attack = base_payload(status="SUPPORTED", evidence_status="PROMOTED")
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.PROPOSE_RESEARCH_PROGRAM, proposed_by="DIRECTOR",
                project_id="p1", payload=attack))
        assert exc.value.code == "NOT_COMPILED"
        assert "status" in exc.value.reason


class TestAttacksJK:
    """J: ActionEvaluation attempts direct dispatch. K: missing gate approval."""

    def test_j_evaluator_has_no_dispatch_surface(self):
        import inspect

        import hermes.research.evaluation as ev
        source = inspect.getsource(ev)
        for banned in ("sqlite3", "import repositories", "persistence.",
                       "apply_intent", "dispatch"):
            assert banned not in source

    def test_k_gate_blocked_candidate_never_ranked(self):
        blocked = CandidateAction(
            candidate_ref="cand-blocked",
            action_type="experiment",
            objective_ref="obj-1",
            dimensions={
                "evidence_gap_closure": DimensionLevel.HIGH,
                "contradiction_reduction": DimensionLevel.HIGH,
                "rival_discrimination": DimensionLevel.HIGH,
                "replication_value": DimensionLevel.HIGH,
                "frontier_value": DimensionLevel.HIGH,
                "coverage": DimensionLevel.HIGH,
            },
            blocked_by=("pre_compute",),  # missing gate approval → HARD exclusion
        )
        ranking = evaluate_candidates([blocked])
        assert [e.candidate_ref for e in ranking.exclusions] == [blocked.candidate_ref]
        assert all(c.candidate_ref != blocked.candidate_ref
                   for c in ranking.comparison)
        assert "pre_compute" in ranking.exclusions[0].exclusion_reason


class TestAttackL:
    """L: graph-derived suggestion attempts to mutate state.

    No graph component exists in this phase (deferred); the research stack's
    only write surfaces are the gateway (admission) and the repositories
    (persistence of gateway-approved mutations). Structural check:
    """

    def test_research_stack_write_surfaces_are_only_gateway_and_repos(self):
        import inspect

        import hermes.research.evaluation as ev
        import hermes.research.gateway as gw
        import hermes.research.programs as pr
        import hermes.research.task_plan as tp
        for module in (pr, tp, ev):
            source = inspect.getsource(module)
            assert "INSERT INTO" not in source
            assert "CREATE TABLE" not in source
        assert "apply_intent" in inspect.getsource(gw)


class TestAttackM:
    """M: program becomes stale after a ScopeBrief content change (R-02)."""

    def test_stale_scope_content_hash_rejected_at_write_path(self, db):
        from hermes.persistence.repositories import ResearchProgramError
        repo = ResearchProgramRepository(db)
        # A program compiled against a DIFFERENT brief content hash than the
        # frozen brief's current hash (the scope changed under it) is stale:
        # R-02 resolves the CURRENT hash and rejects — recompilation required.
        stale = compile_from_payload(
            base_payload(), project_id="p1",
            scope_content_hash="briefhash2-CHANGED",  # old/foreign hash
        )
        assert stale.status is CompilationStatus.COMPILED  # compiles fine
        with pytest.raises(ResearchProgramError) as exc:
            repo.record("p1", stale)
        assert "content hash" in str(exc.value)
        # the fix: recompile against the actual frozen brief hash
        fresh = compiled(db)
        row = repo.record("p1", fresh)
        assert row["program_id"] == fresh.program.program_id


class TestAttackN:
    """N: duplicate request after crash/retry — idempotent, no duplicates."""

    def test_duplicate_proposal_idempotent(self, db):
        r1 = apply_intent(db, Intent(
            kind=IntentKind.PROPOSE_RESEARCH_PROGRAM, proposed_by="DIRECTOR",
            project_id="p1", payload=base_payload()))
        r2 = apply_intent(db, Intent(
            kind=IntentKind.PROPOSE_RESEARCH_PROGRAM, proposed_by="DIRECTOR",
            project_id="p1", payload=base_payload()))
        assert r1.entity_id == r2.entity_id and r2.duplicate is True

    def test_duplicate_task_request_idempotent(self, db):
        payload = {
            "task_id": "retry-task", "task_type": "AGENT_TASK",
            "profile": "RESEARCHER", "idempotency_key": "idem-retry",
            "iteration": 1, "spec": {}, "inputs": [], "outputs": [],
            "dependencies": [], "provenance": ["artifact:retry-spec"],
        }
        intent = Intent(kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
                        project_id="p1", payload=payload)
        r1 = apply_intent(db, intent)
        r2 = apply_intent(db, intent)
        assert r2.duplicate is True and r1.entity_id == r2.entity_id
        created = [e for e in EventRepository(db).list_for_project("p1")
                   if e["event_type"] == "TaskCreated"]
        assert len(created) == 1
