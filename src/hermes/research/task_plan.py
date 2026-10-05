"""ResearchProgram → ResearchTaskPlan mapping (v6 §28.2.6, P3).

A compiled ``ResearchProgram`` is an epistemic contract: it declares what must
be established and which obligations govern success. It is NOT the task
graph. This module projects the contract into ordinary task-graph nodes —
gate tasks (``HUMAN_GATE``) and evidence tasks (``AGENT_TASK``) — that are
admitted ONLY through the Intent Gateway (INSERT_TASK for LLM-
proposable paths, ADMIT_TASK for the deterministic plan-admission pass
— IDR-045 D1 — both through the single `apply_intent` path).

Properties (AC-05/10/12, IDR-019 discipline):

- **deterministic + content-addressed**: identical programs yield identical
  task ids and idempotency keys — re-running the plan cannot duplicate work;
- **pure**: no DB access, no writes, no clock, no random — a projection;
- **provenance-bearing**: every task carries structural provenance links
  (``research_program:<id>``, ``evidence_requirement:<claim_ref>``,
  ``hypothesis:<claim_ref>``, ``scope_brief:<scope_ref>``) so "why does task
  T exist" is answerable from identifiers, never from LLM prose;
- **gate-ordered**: gate tasks chain (hypothesis → pre_compute → …); evidence
  tasks depend on every gate except the final (reporting) gate; the final gate
  depends on all evidence tasks (v4 §9.1 gate semantics preserved).

The mapping has no authority surface: it cannot create tasks, mutate state,
promote evidence, or bypass the gateway.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hermes.core.node import AgentProfile, NodeContract, NodeType
from hermes.research.programs import (
    ResearchProgram,
    canonical_json,
    sha256_hex,
)

__all__ = [
    "PlanTask",
    "ResearchTaskPlan",
    "build_task_plan",
    "plan_to_nodes",
    "plan_to_payloads",
]


def _slug(text: str, limit: int = 24) -> str:
    """Deterministic slug: lowercase alphanumerics, non-alnum → '_'."""
    out = "".join(ch if ch.isalnum() else "_" for ch in text.lower())
    return out.strip("_")[:limit] or "req"


@dataclass(frozen=True, slots=True)
class PlanTask:
    """One task in the plan — the projection of one requirement to a node."""

    task_id: str
    task_type: str            # NodeType value
    profile: str | None       # AgentProfile value
    idempotency_key: str
    iteration: int
    spec: dict[str, Any]
    inputs: list[str]
    outputs: list[str]
    dependencies: list[str]
    provenance: list[str]
    cost_class: str | None = None


@dataclass(frozen=True, slots=True)
class ResearchTaskPlan:
    """The full deterministic projection of a program.

    ``gate_tasks`` chain (each depends on the previous); ``evidence_tasks``
    depend on every gate except the final one; the final gate task depends on
    every evidence task. ``ordered`` is the admission order (gates first,
    then evidence), matching the DAG.
    """

    program_id: str
    gate_tasks: tuple[PlanTask, ...]
    evidence_tasks: tuple[PlanTask, ...]

    @property
    def ordered(self) -> tuple[PlanTask, ...]:
        """Admission order — topological: leading gates, then evidence, then
        the final (reporting) gate (its dependency edges reference the
        evidence tasks, so it must be admitted after them)."""
        if not self.gate_tasks:
            return self.evidence_tasks
        if len(self.gate_tasks) == 1:
            return (self.gate_tasks[0],) + self.evidence_tasks
        return (self.gate_tasks[:-1] + self.evidence_tasks
                + self.gate_tasks[-1:])

    @property
    def task_ids(self) -> frozenset[str]:
        return frozenset(t.task_id for t in self.ordered)


def _identity(program: ResearchProgram, role: str, ref: str) -> str:
    """Content-addressed identity for a plan task (stable across runs)."""
    return sha256_hex(canonical_json({
        "program_id": program.program_id,
        "plan_role": role,
        "ref": ref,
        "plan_version": 1,
    }))


def build_task_plan(program: ResearchProgram) -> ResearchTaskPlan:
    """Deterministically project a compiled program into a task plan.

    Raises ``ValueError`` for an uncompiled program (no ``program_id``) —
    the plan maps only compiled, content-addressed contracts.
    """
    if not program.program_id:
        raise ValueError(
            "build_task_plan requires a compiled ResearchProgram "
            "(program_id must be set)")
    pid_short = program.program_id[3:11]  # "rp_<8 hex>" readable prefix

    # Lifecycle DAG (v4 §9.1): the three mandatory human gates form the
    # spine hypothesis → pre_compute → … ; deterministic integrity gates
    # (adversarial/data/leakage/methodology/statistical for confirmatory
    # targets) are evidence-stage checks; pre_live gates REPORTING and fires
    # only after the evidence is complete.
    MANDATORY = ("hypothesis", "pre_compute", "pre_live")
    human_gates = [g for g in MANDATORY if g in program.gate_requirements]
    integrity_gates = sorted(set(program.gate_requirements) - set(MANDATORY))
    # spine: hypothesis → pre_compute → integrity checks → pre_live (reporting)
    pre_live_present = "pre_live" in human_gates
    spine = ([g for g in human_gates if g != "pre_live"]
             + integrity_gates
             + (["pre_live"] if pre_live_present else []))

    def _gate_task(gate_name: str, kind: str, dependencies: list[str]) -> PlanTask:
        task_id = f"rp-{pid_short}-gate-{_slug(gate_name)}"
        node_type = (NodeType.HUMAN_GATE.value if kind == "human"
                     else NodeType.GATE.value)
        return PlanTask(
            task_id=task_id,
            task_type=node_type,
            profile=None,
            idempotency_key=_identity(program, "gate", gate_name),
            iteration=1,
            spec={
                "program_id": program.program_id,
                "gate_requirement": gate_name,
                "epistemic_objective": program.epistemic_objective,
                "plan_kind": "human_gate" if kind == "human" else "integrity_gate",
            },
            inputs=[],
            outputs=[f"gate:{gate_name}"],
            dependencies=dependencies,
            provenance=[
                f"research_program:{program.program_id}",
                f"gate_requirement:{gate_name}",
            ],
        )

    gate_tasks: list[PlanTask] = []
    last: str | None = None
    for gate_name in spine:
        deps = [last] if last else []
        gate_tasks.append(_gate_task(
            gate_name,
            "human" if gate_name in human_gates else "integrity",
            deps,
        ))
        last = gate_tasks[-1].task_id

    # evidence depends on everything before it, except the final reporting gate
    evidence_deps = ([t.task_id for t in gate_tasks[:-1]]
                     if pre_live_present else
                     [t.task_id for t in gate_tasks])
    evidence_tasks: list[PlanTask] = []
    for i, req in enumerate(program.evidence_requirements):
        task_id = f"rp-{pid_short}-ev-{i:02d}-{_slug(req.claim_ref)}"
        provenance = [
            f"research_program:{program.program_id}",
            f"evidence_requirement:{req.claim_ref}",
            f"hypothesis:{req.claim_ref}",
            f"scope_brief:{program.scope_ref}",
        ]
        evidence_tasks.append(PlanTask(
            task_id=task_id,
            task_type=NodeType.AGENT_TASK.value,
            profile=AgentProfile.RESEARCHER.value,
            idempotency_key=_identity(program, "evidence", req.claim_ref),
            iteration=1,
            spec={
                "program_id": program.program_id,
                "requirement_ref": req.claim_ref,
                "ladder_target": req.ladder_target.value,
                "required_artifacts": list(req.required_artifacts),
                "associated_gates": list(req.associated_gates),
                "epistemic_objective": program.epistemic_objective,
                "plan_kind": "evidence_obligation",
            },
            inputs=[],
            outputs=list(req.required_artifacts),
            dependencies=list(evidence_deps),
            provenance=provenance,
        ))

    # pre_live fires after the evidence is complete (it is already last in
    # the spine; add the evidence edges).
    if pre_live_present and gate_tasks:
        trailing = gate_tasks[-1]
        gate_tasks[-1] = PlanTask(
            task_id=trailing.task_id,
            task_type=trailing.task_type,
            profile=trailing.profile,
            idempotency_key=trailing.idempotency_key,
            iteration=trailing.iteration,
            spec=trailing.spec,
            inputs=trailing.inputs,
            outputs=trailing.outputs,
            dependencies=trailing.dependencies
            + [t.task_id for t in evidence_tasks],
            provenance=trailing.provenance,
            cost_class=trailing.cost_class,
        )

    return ResearchTaskPlan(
        program_id=program.program_id,
        gate_tasks=tuple(gate_tasks),
        evidence_tasks=tuple(evidence_tasks),
    )


def plan_to_nodes(
    plan: ResearchTaskPlan, project_id: str,
) -> list[NodeContract]:
    """Convert a plan into NodeContract nodes (still no writes)."""
    nodes: list[NodeContract] = []
    for task in plan.ordered:
        nodes.append(NodeContract(
            task_id=task.task_id,
            project_id=project_id,
            task_type=task.task_type,
            profile=task.profile,
            idempotency_key=task.idempotency_key,
            iteration=task.iteration,
            spec=task.spec,
            inputs=task.inputs,
            outputs=task.outputs,
            dependencies=task.dependencies,
            provenance=task.provenance,
            cost_class=task.cost_class,
        ))
    return nodes


def plan_to_payloads(
    plan: ResearchTaskPlan, project_id: str,
) -> list[dict[str, Any]]:
    """Convert a plan into INSERT_TASK gateway payloads (deterministic).

    The walking skeleton admits these as INSERT_TASK (DIRECTOR); the
    controller plan-admission pass (IDR-045 D1) admits the same payloads
    as ADMIT_TASK (DETERMINISTIC) — both through the single `apply_intent` path, never by writing nodes directly.
    """
    payloads: list[dict[str, Any]] = []
    for node in plan_to_nodes(plan, project_id):
        payloads.append({
            "task_id": node.task_id,
            "task_type": node.task_type,
            "profile": node.profile,
            "idempotency_key": node.idempotency_key,
            "iteration": node.iteration,
            "spec": node.spec,
            "inputs": node.inputs,
            "outputs": node.outputs,
            "dependencies": node.dependencies,
            "provenance": node.provenance,
            "cost_class": node.cost_class,
        })
    return payloads
