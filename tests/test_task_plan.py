"""Tests for the ResearchProgram → ResearchTaskPlan mapping (v6 §28.2.6, P3).

The plan is a deterministic, pure projection of a compiled program into
ordinary task-graph nodes — never a write. It must be reproducible
(AC-01-class), content-addressed (re-running cannot duplicate work),
provenance-bearing (structural "why does task T exist" links), and
gate-ordered (v4 §9.1 gate semantics preserved in the DAG).
"""
from __future__ import annotations

import pytest

from hermes.core.node import NodeContract, NodeType
from hermes.research.programs import (
    CompilationStatus,
    compile_from_payload,
)
from hermes.research.task_plan import (
    build_task_plan,
    plan_to_nodes,
    plan_to_payloads,
)


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


def compile_program(payload=None):
    result = compile_from_payload(
        payload or base_payload(),
        project_id="p1",
        scope_content_hash="briefhash1",
    )
    assert result.status is CompilationStatus.COMPILED
    return result.program


class TestPlanDeterminism:
    def test_same_program_same_plan(self):
        p1 = build_task_plan(compile_program())
        p2 = build_task_plan(compile_program())
        assert p1.task_ids == p2.task_ids
        assert [t.idempotency_key for t in p1.ordered] == \
               [t.idempotency_key for t in p2.ordered]
        assert [t.task_id for t in p1.ordered] == [t.task_id for t in p2.ordered]

    def test_plan_is_pure_no_db(self):
        """No write surface: build the plan with no connection anywhere."""
        program = compile_program()
        plan = build_task_plan(program)
        nodes = plan_to_nodes(plan, "p1")
        assert isinstance(nodes[0], NodeContract)

    def test_requires_compiled_program(self):
        from hermes.research.programs import ResearchProgram
        empty = ResearchProgram(
            program_id="", project_id="p1", scope_ref="brief-1",
            scope_content_hash="h", epistemic_objective="x",
            hypotheses=(), predictions=(), discrimination_requirements=(),
            evidence_requirements=(), gate_requirements=(),
            methodology_constraints=(), task_graph_template_ref=None,
            compiler_version="", policy_version="", schema_version="1",
            input_hash="", content_hash="", supersedes_ref=None,
        )
        with pytest.raises(ValueError):
            build_task_plan(empty)


class TestPlanStructure:
    def test_confirmatory_program_three_mandatory_gates_present(self):
        plan = build_task_plan(compile_program())
        gate_names = [t.spec["gate_requirement"] for t in plan.gate_tasks]
        for mandatory in ("hypothesis", "pre_compute", "pre_live"):
            assert mandatory in gate_names
        # integrity gates for confirmatory targets are present too
        assert "statistical" in gate_names
        assert len(plan.evidence_tasks) >= 1

    def test_gate_chain_and_evidence_dependencies(self):
        plan = build_task_plan(compile_program())
        # gates chain: each depends on the previous
        for prev, cur in zip(plan.gate_tasks, plan.gate_tasks[1:]):
            assert prev.task_id in cur.dependencies
        pre_live = next(t for t in plan.gate_tasks
                        if t.spec["gate_requirement"] == "pre_live")
        # evidence depends on every gate except pre_live
        gate_ids = [t.task_id for t in plan.gate_tasks]
        for ev in plan.evidence_tasks:
            assert set(ev.dependencies) == set(gate_ids) - {pre_live.task_id}
        # pre_live depends on every evidence task
        assert set(pre_live.dependencies) >= {
            t.task_id for t in plan.evidence_tasks}

    def test_no_cycle_in_plan(self):
        plan = build_task_plan(compile_program())
        edges = {t.task_id: set(t.dependencies) for t in plan.ordered}
        for start in edges:
            rec_stack = set()
            visited = set()
            def walk(node, rec_stack=rec_stack, visited=visited,
                     start=start):
                if node in rec_stack:
                    pytest.fail(f"cycle detected involving {start}")
                if node in visited:
                    return
                rec_stack.add(node)
                for dep in edges.get(node, ()):
                    walk(dep)
                rec_stack.discard(node)
                visited.add(node)
            walk(start)

    def test_topological_admission_order(self):
        plan = build_task_plan(compile_program())
        ids = [t.task_id for t in plan.ordered]
        pre_live = next(t for t in plan.gate_tasks
                        if t.spec["gate_requirement"] == "pre_live")
        # pre_live is admitted AFTER evidence tasks
        assert ids.index(pre_live.task_id) > ids.index(
            plan.evidence_tasks[0].task_id)

    def test_speculative_program_single_gate(self):
        payload = base_payload(hypotheses=[
            {"ref": "H1", "ladder_target": "SPECULATIVE",
             "falsification_condition": "x", "rival_of": None, "rival_status": None},
        ], predictions=[])
        program = compile_program(payload)
        assert program.gate_requirements == ("hypothesis",)
        plan = build_task_plan(program)
        assert len(plan.gate_tasks) == 1
        assert plan.gate_tasks[0].spec["gate_requirement"] == "hypothesis"


class TestProvenance:
    def test_evidence_task_links_to_program_and_requirement(self):
        plan = build_task_plan(compile_program())
        ev = plan.evidence_tasks[0]
        assert f"research_program:{plan.program_id}" in ev.provenance
        assert any(p.startswith("evidence_requirement:") for p in ev.provenance)
        assert any(p.startswith("hypothesis:") for p in ev.provenance)
        assert any(p.startswith("scope_brief:") for p in ev.provenance)
        # the links are structural identifiers, never free-form prose
        for p in ev.provenance:
            assert ":" in p and not p.startswith("because")

    def test_gate_task_provenance(self):
        plan = build_task_plan(compile_program())
        gate = plan.gate_tasks[0]
        assert f"research_program:{plan.program_id}" in gate.provenance
        assert any(p.startswith("gate_requirement:") for p in gate.provenance)


class TestNodeAndPayloadConversion:
    def test_plan_to_nodes_contract(self):
        plan = build_task_plan(compile_program())
        nodes = plan_to_nodes(plan, "p1")
        for node in nodes:
            assert node.project_id == "p1"
            assert node.task_type in NodeType._value2member_map_
            assert node.status == "PENDING"  # callers never set status
            assert node.idempotency_key  # content-addressed

    def test_plan_to_payloads_are_valid_insert_task_payloads(self):
        plan = build_task_plan(compile_program())
        payloads = plan_to_payloads(plan, "p1")
        allowed = {
            "task_id", "task_type", "profile", "idempotency_key", "iteration",
            "spec", "inputs", "outputs", "dependencies", "provenance",
            "cost_class",
        }
        for p in payloads:
            assert set(p) == allowed  # closed schema, exactly
            assert p["task_type"] in NodeType._value2member_map_
