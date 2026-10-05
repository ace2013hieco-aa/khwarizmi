"""P3 walking skeleton (v6 §24 / §28.5) — the EC acceptance vehicle.

A fully stubbed project: a compiled ResearchProgram is admitted through the
Intent Gateway, projected into a task plan (gates + evidence obligations),
instantiated via ordinary INSERT_TASK, driven through all three mandatory
human gates (hypothesis, pre_compute, pre_live) with canned human decisions,
and the evidence tasks complete with canned results. Stands as a regression
test: the EC pipeline compiles → admits → gates → completes, and no task
appears outside the gateway's INSERT_TASK path.
"""
from __future__ import annotations

import json

import pytest

from hermes.core.intents import Intent, IntentKind
from hermes.core.task_status import TaskStatus
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    DependencyError,
    EventRepository,
    ProjectRepository,
    TaskRepository,
    _append_event_to_db,
)
from hermes.research.gateway import apply_intent
from hermes.research.programs import (
    CompilationStatus,
    compile_from_payload,
)
from hermes.research.task_plan import build_task_plan, plan_to_payloads


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


def compile_program(payload=None):
    result = compile_from_payload(
        payload or base_payload(),
        project_id="p1",
        scope_content_hash="briefhash1",
    )
    assert result.status is CompilationStatus.COMPILED
    return result.program


def run_skeleton(db, program, *, reject_gate: str | None = None):
    """Drive a compiled program through gates + evidence (canned decisions).

    Returns (plan, statuses, task_by_type) after admitting the program
    through the gateway (the compiled program is recorded first — task
    provenance must dereference to the governed program, V6-FINAL-02),
    admitting every plan task through the gateway, and running it to a
    terminal state. ``reject_gate`` names a HUMAN_GATE to fail (GateFailed);
    everything else passes. A replay on the same db is idempotent (the
    program and task admissions return the existing rows).
    """
    apply_intent(db, Intent(
        kind=IntentKind.PROPOSE_RESEARCH_PROGRAM, proposed_by="DIRECTOR",
        project_id="p1", payload=base_payload()))
    plan = build_task_plan(program)
    repo = TaskRepository(db)
    by_type = {t.task_id: t.task_type for t in plan.ordered}

    admitted = []
    for payload in plan_to_payloads(plan, "p1"):
        result = apply_intent(db, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
            project_id="p1", payload=payload))
        assert result.duplicate is False
        admitted.append(result.entity_id)

    statuses: dict[str, str] = {}
    stopped = False
    for task_id in admitted:
        task_type = by_type[task_id]
        if stopped:
            statuses[task_id] = repo.get_status(task_id).value  # still PENDING
            continue
        repo.transition_status(task_id, TaskStatus.READY, caused_by="skeleton")
        repo.transition_status(task_id, TaskStatus.RUNNING, caused_by="skeleton")
        if task_type == "HUMAN_GATE":
            repo.transition_status(task_id, TaskStatus.WAITING_HUMAN,
                                   caused_by="skeleton")
            _append_event_to_db(
                db, lambda: "2026-01-01T00:00:00+00:00",
                "HumanApprovalRequested", "p1", task_id,
                caused_by="skeleton", reason="canned human gate request")
            repo.transition_status(task_id, TaskStatus.RUNNING,
                                   caused_by="human")
            rejected = bool(reject_gate) and task_id.endswith(
                f"-gate-{reject_gate}")
            _append_event_to_db(
                db, lambda: "2026-01-01T00:00:00+00:00",
                "GateFailed" if rejected else "GatePassed",
                "p1", task_id, caused_by="human")
            if rejected:
                repo.transition_status(task_id, TaskStatus.FAILED,
                                       caused_by="human",
                                       reason="gate rejected: revise the plan")
                stopped = True
            else:
                repo.transition_status(task_id, TaskStatus.SUCCEEDED,
                                       caused_by="human")
        elif task_type == "GATE":
            _append_event_to_db(
                db, lambda: "2026-01-01T00:00:00+00:00",
                "GatePassed", "p1", task_id, caused_by="deterministic")
            repo.transition_status(task_id, TaskStatus.SUCCEEDED,
                                   caused_by="deterministic")
        else:  # AGENT_TASK — evidence obligation with canned result
            repo.transition_status(task_id, TaskStatus.SUCCEEDED,
                                   caused_by="skeleton",
                                   reason="canned evidence result")
        statuses[task_id] = repo.get_status(task_id).value
    return plan, statuses, by_type


class TestFullSkeleton:
    def test_all_three_mandatory_gates_and_evidence_complete(self, db):
        program = compile_program()
        plan, statuses, _ = run_skeleton(db, program)
        assert all(st == "SUCCEEDED" for st in statuses.values())
        # all three mandatory gates were instantiated and passed
        gate_names = {t.spec["gate_requirement"] for t in plan.gate_tasks}
        assert {"hypothesis", "pre_compute", "pre_live"} <= gate_names
        events = EventRepository(db).list_for_project("p1")
        types = [e["event_type"] for e in events]
        assert types.count("GatePassed") >= 3
        assert types.count("TaskCreated") == len(plan.task_ids)
        # provenance on an evidence task answers "why does this task exist"
        row = TaskRepository(db).get(plan.evidence_tasks[0].task_id)
        assert f"research_program:{program.program_id}" in row["provenance"]

    def test_replay_is_idempotent(self, db):
        program = compile_program()
        plan1, _, _ = run_skeleton(db, program)
        # replay the same program: identical task ids, all duplicate admissions
        plan2 = build_task_plan(program)
        assert plan2.task_ids == plan1.task_ids
        created_before = [e for e in EventRepository(db).list_for_project("p1")
                          if e["event_type"] == "TaskCreated"]
        for payload in plan_to_payloads(plan2, "p1"):
            result = apply_intent(db, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
                project_id="p1", payload=payload))
            assert result.duplicate is True
        created_after = [e for e in EventRepository(db).list_for_project("p1")
                         if e["event_type"] == "TaskCreated"]
        assert len(created_after) == len(created_before)  # no duplicates

    def test_no_task_outside_gateway_path(self, db):
        """Every task in the graph has a matching INSERT_TASK intent applied."""
        program = compile_program()
        run_skeleton(db, program)
        events = EventRepository(db).list_for_project("p1")
        applied_inserts = [
            json.loads(e["payload_json"]).get("intent_kind")
            for e in events if e["event_type"] == "IntentApplied"
        ]
        assert applied_inserts.count("INSERT_TASK") == len(
            build_task_plan(program).task_ids)


class TestGateSemantics:
    def test_rejected_hypothesis_gate_blocks_evidence(self, db):
        program = compile_program()
        plan, statuses, _ = run_skeleton(db, program, reject_gate="hypothesis")
        hyp = next(t for t in plan.gate_tasks
                   if t.spec["gate_requirement"] == "hypothesis")
        assert statuses[hyp.task_id] == "FAILED"
        # evidence obligations cannot run: dependency not SUCCEEDED (F-10)
        repo = TaskRepository(db)
        ev = plan.evidence_tasks[0]
        assert repo.get_status(ev.task_id) is TaskStatus.PENDING
        repo.transition_status(ev.task_id, TaskStatus.READY, caused_by="skeleton")
        with pytest.raises(DependencyError):
            repo.transition_status(ev.task_id, TaskStatus.RUNNING,
                                   caused_by="skeleton")
        events = EventRepository(db).list_for_project("p1")
        assert "GateFailed" in [e["event_type"] for e in events]

    def test_pre_live_fires_after_evidence(self, db):
        program = compile_program()
        plan, statuses, _ = run_skeleton(db, program)
        pre_live = next(t for t in plan.gate_tasks
                        if t.spec["gate_requirement"] == "pre_live")
        # pre_live succeeded only after evidence: its deps include all evidence
        dep_ids = set(pre_live.dependencies)
        assert dep_ids >= {t.task_id for t in plan.evidence_tasks}
        assert statuses[pre_live.task_id] == "SUCCEEDED"
