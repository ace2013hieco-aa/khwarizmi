"""OPS-5T — the completion predicate must count what happened.

Two defects, one question: *does a run that recorded nothing still count as a
run that did something?* Both answers were yes.

1. **Refusals counted as admissions** (C3). ``FencedIntentApplier.__call__``
   incremented ``writes`` *before* the apply, and ``_apply`` turns a gateway
   refusal into ``(Admission.REFUSED, ...)`` data — so the increment was never
   unwound. The methodology driver then read ``applied`` off that counter, and
   the handler's S6-B2 gate failed only when ``applied == 0``. A run whose every
   proposal was refused therefore passed S6-B2 and was recorded ``SUCCEEDED``
   with no durable effect.
2. **The predicate failed open** (C4), four ways: the gate join was scoped to
   the project alone (no program, no task type, no terminal state); the
   satisfaction join never read the artifact invalidation marker; a malformed
   obligation was ``continue``-d; and ``["x", 5]`` silently became ``{x}``.

The falsifiers, in the charter's order:

- a methodology whose every proposal is refused **fails** S6-B2 (§1.1);
- a methodology with one genuine admission still passes (§1.2);
- a duplicate is not a new row, and a duplicate-only run does not pass (§1.3);
- a ``GatePassed`` from another program does not satisfy this program's
  requirement (§2.1);
- a ``GatePassed`` on a task that ended ``FAILED`` does not satisfy it (§2.2);
- a retracted artifact does not cover its requirement (§3);
- a malformed requirement or a non-string artifact class **denies** (§4).

No network and no live model: the S6-B2 cases run through the real `Controller`
and the real gateway over an in-memory spine, with a scripted model; the
predicate cases build rows directly, because the predicate is a read.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

import hermes.research.completion as completion_module
from hermes.agents.runtime.config import ProfileSpec, parse_profile
from hermes.agents.runtime.types import Admission, TaskStatus
from hermes.agents.runtime.wiring import FencedIntentApplier, LeaseFence
from hermes.core.intents import Intent, IntentKind, IntentRejectedError
from hermes.methodology.swap_test import CHAIN_STATEMENTS
from hermes.methodology.workflows import LITERATURE_REVIEW_DOCUMENT
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.program_obligations import (
    ProgramRequirementSatisfactionRepository,
    ValidationVerdictRepository,
)
from hermes.persistence.repositories import ProjectRepository
from hermes.research.completion import (
    GATE_NOT_PASSED,
    PROGRAM_CORRUPT,
    REQUIREMENT_UNSATISFIED,
    can_complete_research,
)
from hermes.research.controller import Controller
from hermes.research.gateway import apply_intent
from hermes.research.task_handlers import build_methodology_handler
from hermes.research.task_handlers.methodology_driver import (
    METHODOLOGY_COMPLETE,
    run_methodology,
)
from hermes.tools.models.router import ModelProposal

PROJECT = "p-ops5t"
METH_TEMPLATE = "methodology_run"
TASK = "t-ops5t"
CLOCK = "2026-10-27T12:00:00.000000+00:00"
LEASE = "gen-ops5t"

#: The two declared stages the S6-B2 fixtures run. Two, not one: a one-stage
#: document cannot show that a *chain* of refusals still reaches ``COMPLETE``,
#: and the point is that every stage's proposal was refused and the chain
#: finished anyway. Neither stage is an evidence position, so no citation is
#: needed and the substrate cannot be the reason the run stops.
STAGES = ("QUESTION", "HYPOTHESIS")

MANDATORY_GATES = ("hypothesis", "pre_compute", "pre_live")

#: The four classes a SUPPORTED ladder target obliges (``LADDER_OBLIGATIONS``).
SUPPORTED_CLASSES = ("pre_registered_experiment", "statistical_analysis",
                     "validation", "adversarial_critique")

_WALK_TO_REPORTING = (
    "SCOPING", "LITERATURE_REVIEW", "HYPOTHESIS_FORMULATION",
    "EXPERIMENT_DESIGN", "DATA_ACQUISITION", "DATA_VALIDATION",
    "IMPLEMENTATION", "EXPERIMENTATION", "ANALYSIS", "VALIDATION",
    "ADVERSARIAL_REVIEW", "REPLICATION", "REPORTING",
)


# ═══════════════════════ 1. C3 — the admission record decides ═══════════════


def _spine() -> Any:
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: CLOCK).create(PROJECT, "OPS-5T")
    return conn


def _profile(name: str) -> ProfileSpec:
    """A stage profile that may propose an ordinary task and nothing else."""
    return parse_profile({
        "name": name,
        "role": f"{name} role",
        "agent_profile": "RESEARCHER",
        "model_policy": {"tier": "research", "structured_fields": ["proposals"]},
        "tools": [],
        "authority": {"proposable_kinds": ["INSERT_TASK"]},
        "termination": {"max_ticks": 1, "max_proposals": 5,
                        "stop_when": "proposals_raised"},
    }, source=name)


def _stage_profiles() -> dict[str, ProfileSpec]:
    return {name: _profile(name) for name in ("planner", "researcher",
                                              "experimenter", "verifier",
                                              "synthesizer", "critic")}


def _document(stages: tuple[str, ...] = STAGES) -> dict[str, Any]:
    """The shipped document cut to ``stages`` — a chain, not a fragment."""
    document = dict(LITERATURE_REVIEW_DOCUMENT)
    declared = [dict(stage) for stage in document["stages"]]
    keep = [stage for stage in declared if stage["stage"] in stages]
    document["stages"] = keep
    document["termination"] = {**dict(document["termination"]),
                               "max_stages": len(keep)}
    return document


def _admit(conn: Any, task_id: str, document: dict[str, Any]) -> str:
    result = apply_intent(conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id=PROJECT,
        payload={
            "task_id": task_id,
            "task_type": "AGENT_TASK",
            "spec": {"template": METH_TEMPLATE, "methodology": document,
                     "inputs": {"question": "does it hold?",
                                "stage_content": dict(CHAIN_STATEMENTS)}},
            "idempotency_key": f"idem-{task_id}",
            "iteration": 1, "provenance": [], "inputs": [], "outputs": [],
            "dependencies": [], "cost_class": "LOW",
        }), clock=lambda: CLOCK)
    return str(result.entity_id)


def _dispatch(conn: Any, model: Any, document: dict[str, Any],
              task_id: str) -> tuple[Any, list[Any]]:
    """Admit the methodology task, then run one tick through the Controller."""
    _admit(conn, task_id, document)
    collected: list[Any] = []
    handler = build_methodology_handler(
        model=model, profiles=_stage_profiles(),
        on_stage=lambda _wiring, result: collected.append(result))
    ctrl = Controller(conn, project_id=PROJECT,
                      task_handlers={METH_TEMPLATE: handler},
                      clock=lambda: CLOCK)
    return ctrl.tick(), collected


def _status(conn: Any, task_id: str) -> str:
    row = conn.execute("SELECT status FROM tasks WHERE task_id = ?",
                       (task_id,)).fetchone()
    return str(row["status"]) if row is not None else ""


def _reason(conn: Any, task_id: str) -> str:
    """The reason the task's own failed transition recorded."""
    row = conn.execute(
        "SELECT reason FROM events WHERE task_id = ? "
        "AND event_type = 'TaskStatusChanged' AND to_state = 'FAILED' "
        "ORDER BY event_id DESC LIMIT 1",
        (task_id,)).fetchone()
    return str(row["reason"] or "") if row is not None else ""


def _proposal(request: Any, structured: dict[str, Any]) -> ModelProposal:
    return ModelProposal(
        provider_id="scripted", model_id="scripted", tier="research",
        profile=request.profile,
        lease_generation=request.lease_generation,
        structured=structured)


class RefusedModel:
    """Proposes an ordinary task at every stage — and the spine refuses it.

    ``spec`` is a string where the gateway's closed shape requires a dict, so
    every proposal reaches ``apply_intent`` and comes back
    ``MALFORMED_PAYLOAD``. The refusal is *data*: the run records it and keeps
    going, so every stage run still ends ``SUCCEEDED`` and the chain still
    reaches ``COMPLETE``. That is exactly the shape C3 made invisible.
    """

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def invoke(self, request: Any) -> ModelProposal:
        self.calls.append(request)
        return _proposal(request, {
            "kind": "INSERT_TASK",
            "rationale": "a task the spine will not take",
            "payload": {"spec": "not-a-dict"},
        })


class OneAdmissionModel:
    """One genuine admission at QUESTION, silence afterwards.

    The control: the same two-stage chain, one proposal the spine takes. The
    stage that proposes nothing is still a ``SUCCEEDED`` stage (``NO_PROPOSALS``
    is how a stage stops, not how it fails), so the chain finishes with a
    non-zero admission count and S6-B2 must stay silent.
    """

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def invoke(self, request: Any) -> ModelProposal:
        self.calls.append(request)
        if len(self.calls) == 1:
            return _proposal(request, {
                "kind": "INSERT_TASK", "rationale": "one real task",
                "payload": {"spec": {"goal": "the one durable row"}},
            })
        return _proposal(request, {})


def test_a_methodology_whose_every_proposal_is_refused_fails_s6b2() -> None:
    """Falsifier 1 — the regression test that did not exist.

    Before OPS-5T this run reached ``SUCCEEDED``: the wiring counted the refused
    call as a write, the driver read that count as an admission, and S6-B2 saw a
    non-zero number. Every stage's proposal was refused, the chain still
    reported ``COMPLETE``, and nothing durable had happened.
    """
    conn = _spine()
    try:
        model = RefusedModel()
        out, collected = _dispatch(conn, model, _document(), "t-ops5t-refused")

        # Every stage ran, and every stage run is SUCCEEDED — a refusal is data.
        assert [str(r.task_id).rsplit(":", 1)[-1] for r in collected] == list(
            STAGES)
        assert all(result.state == TaskStatus.SUCCEEDED.value
                   for result in collected)
        # Every proposal the model made was refused by the spine.
        proposals = [p for result in collected for p in result.proposals]
        assert len(proposals) == len(STAGES)
        assert all(p.admission == Admission.REFUSED.value for p in proposals)

        # And the run is not an outcome.
        assert out.succeeded == []
        assert out.retried == ["t-ops5t-refused"]
        assert _status(conn, "t-ops5t-refused") == TaskStatus.RETRYING.value

        reason = _reason(conn, "t-ops5t-refused")
        assert reason.startswith("PROPOSAL:")
        assert "(S6-B2)" in reason
        # The operator learns *that the proposals were refused*, not just that
        # the count was zero.
        assert "all 2 proposal(s)" in reason
        assert "refused by the spine" in reason
        assert "MALFORMED_PAYLOAD" in reason
        assert "OPS-5M" not in reason          # not the truncation gate
    finally:
        conn.close()


def test_a_methodology_with_one_genuine_admission_still_passes() -> None:
    """Falsifier 2 — the fix must not fail an honest run.

    One admitted row, one silent stage, two recorded stages, ``COMPLETE``. The
    count is one, so S6-B2 stays silent and the root task succeeds.
    """
    conn = _spine()
    try:
        out, collected = _dispatch(conn, OneAdmissionModel(), _document(),
                                   "t-ops5t-honest")
        assert out.succeeded == ["t-ops5t-honest"]
        assert out.retried == []
        assert _status(conn, "t-ops5t-honest") == TaskStatus.SUCCEEDED.value
        admitted = [p for result in collected
                    for p in result.proposals if p.was_admitted()]
        assert len(admitted) == 1
    finally:
        conn.close()


# ── the driver's count, with a scripted spine ──


class _Applied:
    """The shape `run._apply` reads off an injected Orchestration API result."""

    def __init__(self, *, duplicate: bool = False) -> None:
        self.entity_id = "ent-ops5t"
        self.duplicate = duplicate


class RefusingIntentRejected(IntentRejectedError):
    """A refusal carrying the spine's own code, as `GatewayRejection` does.

    ``MALFORMED_PAYLOAD`` is a member of the plane's frozen refusal set, so the
    runtime forwards it verbatim; a code outside that set would be surfaced as
    ``PROPOSAL`` with the spine's code kept in the detail.
    """

    code = "MALFORMED_PAYLOAD"


class ScriptedApplier:
    """Answers each proposal with a scripted verdict, in call order.

    ``"admit"`` records a row, ``"duplicate"`` answers an idempotent re-emit,
    ``"refuse"`` raises the spine's rejection. The verdicts are consumed in
    order; a script that runs out admits (so an unscripted call never silently
    refuses).
    """

    def __init__(self, verdicts: list[str]) -> None:
        self.verdicts = list(verdicts)
        self.calls: list[Intent] = []

    def __call__(self, intent: Intent) -> Any:
        self.calls.append(intent)
        verdict = self.verdicts.pop(0) if self.verdicts else "admit"
        if verdict == "refuse":
            raise RefusingIntentRejected(intent.kind, "the spine said no")
        return _Applied(duplicate=verdict == "duplicate")


class _Model:
    """Proposes ``count`` ordinary tasks per tick, in one multi-proposal reply."""

    def __init__(self, count: int = 1) -> None:
        self.count = count
        self.calls: list[Any] = []

    def invoke(self, request: Any) -> ModelProposal:
        self.calls.append(request)
        return _proposal(request, {"proposals": [
            {"kind": "INSERT_TASK", "rationale": "because",
             "statement": "the run's own conjecture",
             "payload": {"spec": {"goal": f"slot {slot}"}}}
            for slot in range(self.count)]})


def _driver_run(applier: ScriptedApplier, *, stages: tuple[str, ...] = STAGES,
                count: int = 1) -> Any:
    from hermes.agents.runtime.wiring import RuntimeWiring
    from hermes.methodology.workflows import MethodologyInputs, parse_methodology

    wiring = RuntimeWiring(
        model=_Model(count), orchestration=applier, lease_generation=LEASE,
        profiles=_stage_profiles(), clock=lambda: CLOCK)
    return run_methodology(
        parse_methodology(_document(stages)),
        MethodologyInputs(question="does it hold?"),
        wiring=wiring, project_id=PROJECT, task_id=TASK)


def test_a_stage_counts_the_admission_records_not_the_calls() -> None:
    """Three proposals, three different answers, three different counts.

    This is the whole of C3 in one stage: one admitted (a new row), one refused
    (no row), one duplicate (a row that was already there). A call counter says
    three; the admission records say one.
    """
    applier = ScriptedApplier(["admit", "refuse", "duplicate"])
    execution = _driver_run(applier, count=3)
    assert not isinstance(execution, Exception)
    assert execution.termination == METHODOLOGY_COMPLETE

    record = execution.stages[0]
    assert record.intents_proposed == 3
    assert record.intents_applied == 1
    assert record.intents_refused == 1
    assert record.intents_duplicate == 1
    assert record.refusal_codes == ("MALFORMED_PAYLOAD",)


def test_a_duplicate_is_not_a_new_row() -> None:
    """A replay that hit an existing row is not an admission.

    The intent was identical to one the spine already held, so this run added
    nothing. It counts as a duplicate — visible, but never as ``applied``: a
    run made only of replays records no new row, and S6-B2 is a statement about
    new rows.
    """
    execution = _driver_run(ScriptedApplier(["duplicate"]))
    assert not isinstance(execution, Exception)
    record = execution.stages[0]
    assert record.intents_proposed == 1
    assert record.intents_applied == 0
    assert record.intents_duplicate == 1
    assert record.intents_refused == 0


def test_the_wiring_does_not_count_a_refusal_as_a_write() -> None:
    """The counter itself, at the seam: a refused call is a refusal, not a write.

    The driver no longer reads this number, but a counter that says "write"
    must not count one that was refused — the next reader would believe it.
    """
    def refuse(_intent: Intent) -> Any:
        raise RefusingIntentRejected(IntentKind.INSERT_TASK, "no")

    applier = FencedIntentApplier(fence=LeaseFence(LEASE), inner=refuse)
    with pytest.raises(IntentRejectedError):
        applier(Intent(kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
                       project_id=PROJECT, payload={"spec": {"goal": "g"}}))
    assert applier.writes == 0
    assert applier.refusals == 1


# ═══════════════════════ 2. C4 — the gate join ═══════════════════════


@pytest.fixture
def db() -> Any:
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, clock=lambda: CLOCK).create(PROJECT, "OPS-5T")
    yield conn
    conn.close()


def _insert_program(db: Any, program_id: str = "rp_ops5t", *, version: int = 1,
                    evidence: list[dict] | None = None,
                    gates: tuple[str, ...] = MANDATORY_GATES) -> None:
    db.execute(
        """INSERT INTO research_programs
           (program_id, project_id, version, content_hash, supersedes_id,
            scope_ref, epistemic_objective, compiler_version, policy_version,
            schema_version, input_hash, hypothesis_json, prediction_json,
            discrimination_json, evidence_json, gate_json, methodology_json,
            task_graph_template_ref, produced_by, reason, created_at)
           VALUES (?, ?, ?, ?, NULL, 'b', 'o', 'c1', 'p1', '1', 'ih', ?, '[]',
                   '[]', ?, ?, '[]', NULL, 'director', NULL, ?)""",
        (program_id, PROJECT, version, "ch-" + program_id,
         json.dumps([{"ref": "h1", "ladder_target": "SUPPORTED",
                      "falsification_condition": "fc", "rival_of": None,
                      "rival_status": None}]),
         json.dumps(list(evidence or [])), json.dumps(list(gates)), CLOCK),
    )


def _requirement(claim_ref: str = "h1",
                 classes: tuple[str, ...] = SUPPORTED_CLASSES) -> dict[str, Any]:
    return {"claim_ref": claim_ref, "ladder_target": "SUPPORTED",
            "required_artifacts": list(classes), "associated_gates": []}


def _insert_gate_task(db: Any, task_id: str, gate: str, *,
                      program_id: str = "rp_ops5t",
                      status: str = "SUCCEEDED",
                      task_type: str = "HUMAN_GATE") -> None:
    db.execute(
        """INSERT INTO tasks
           (task_id, project_id, task_type, idempotency_key, status,
            spec_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (task_id, PROJECT, task_type, f"idem-{task_id}", status,
         json.dumps({"program_id": program_id, "gate_requirement": gate}),
         CLOCK))


def _gate_passed(db: Any, task_id: str) -> None:
    db.execute(
        """INSERT INTO events
           (event_type, project_id, task_id, caused_by, reason, created_at)
           VALUES ('GatePassed', ?, ?, 'operator', 'approved', ?)""",
        (PROJECT, task_id, CLOCK))


def _satisfy(db: Any, requirement_ref: str, classes: tuple[str, ...],
             *, program_id: str = "rp_ops5t",
             marker: str = "", prefix: str = "art") -> None:
    """Link one artifact per class, each with a PASS verdict covering it."""
    repo = ProgramRequirementSatisfactionRepository(db, clock=lambda: CLOCK)
    verdicts = ValidationVerdictRepository(db, clock=lambda: CLOCK)
    metadata = json.dumps({"invalidation_marker": marker}) if marker else "{}"
    for index, artifact_class in enumerate(classes):
        artifact_id = f"{prefix}-{requirement_ref}-{index}"
        db.execute(
            """INSERT INTO artifacts
               (artifact_id, project_id, task_id, artifact_type, content_hash,
                size_bytes, storage_path, producer, metadata_json, created_at)
               VALUES (?, ?, NULL, ?, ?, 1, 'x', 't', ?, ?)""",
            (artifact_id, PROJECT, artifact_class, "ch-" + artifact_id,
             metadata, CLOCK))
        verdicts.record(project_id=PROJECT, artifact_id=artifact_id,
                        verdict="PASS")
        repo.record(project_id=PROJECT, program_id=program_id,
                    requirement_ref=requirement_ref, artifact_id=artifact_id)


def _codes(eligibility: Any) -> set[str]:
    return {denial.code for denial in eligibility.denials}


def _fully_satisfied(db: Any, *, program_id: str = "rp_ops5t",
                     marker: str = "") -> None:
    _insert_program(db, program_id, evidence=[_requirement()])
    _satisfy(db, "h1", SUPPORTED_CLASSES, program_id=program_id, marker=marker)
    for gate in MANDATORY_GATES:
        _insert_gate_task(db, f"gate-{gate}", gate, program_id=program_id)
        _gate_passed(db, f"gate-{gate}")


def test_the_baseline_program_is_eligible(db: Any) -> None:
    """The control every falsifier below is a single change from."""
    _fully_satisfied(db)
    eligibility = can_complete_research(db, PROJECT)
    assert eligibility.eligible, eligibility.denials


def test_a_gate_passed_by_another_program_does_not_satisfy(db: Any) -> None:
    """Falsifier 3 — a foreign program's pass is not this program's pass.

    The head program is ``rp_ops5t`` (version 2); the gate tasks were planned for
    ``rp_foreign`` (version 1) and passed there. Before OPS-5T the join read the
    project only, so an older program's verdict covered the current contract's
    obligation.
    """
    _fully_satisfied(db, program_id="rp_foreign")
    _insert_program(db, "rp_ops5t", version=2, evidence=[_requirement()])
    _satisfy(db, "h1", SUPPORTED_CLASSES, prefix="own")

    eligibility = can_complete_research(db, PROJECT)
    assert not eligibility.eligible
    assert GATE_NOT_PASSED in _codes(eligibility)
    assert REQUIREMENT_UNSATISFIED not in _codes(eligibility)


def test_a_gate_passed_on_a_failed_task_does_not_satisfy(db: Any) -> None:
    """Falsifier 4 — a GatePassed that outlived its task's failure is not a pass.

    ``_commit_gate`` is two writes (H4): the event lands, then the transition.
    A task that ended ``FAILED`` with a ``GatePassed`` row on the journal is the
    shape that ordering can leave behind, and the predicate must not read it as
    a pass.
    """
    _fully_satisfied(db)
    for gate in MANDATORY_GATES:
        db.execute("UPDATE tasks SET status = 'FAILED' WHERE task_id = ?",
                   (f"gate-{gate}",))

    eligibility = can_complete_research(db, PROJECT)
    assert not eligibility.eligible
    assert GATE_NOT_PASSED in _codes(eligibility)


def test_a_gate_task_without_a_program_ref_does_not_satisfy(db: Any) -> None:
    """A gate task that cannot name its program cannot prove it is ours."""
    _fully_satisfied(db)
    for gate in MANDATORY_GATES:
        db.execute(
            "UPDATE tasks SET spec_json = ? WHERE task_id = ?",
            (json.dumps({"gate_requirement": gate}), f"gate-{gate}"))

    eligibility = can_complete_research(db, PROJECT)
    assert not eligibility.eligible
    assert GATE_NOT_PASSED in _codes(eligibility)


def test_a_gate_passed_on_a_non_gate_task_does_not_satisfy(db: Any) -> None:
    """The requirement is a *gate* requirement: an AGENT_TASK cannot carry it."""
    _fully_satisfied(db)
    for gate in MANDATORY_GATES:
        db.execute(
            "UPDATE tasks SET task_type = 'AGENT_TASK' WHERE task_id = ?",
            (f"gate-{gate}",))

    eligibility = can_complete_research(db, PROJECT)
    assert not eligibility.eligible
    assert GATE_NOT_PASSED in _codes(eligibility)


def test_a_gate_passed_on_an_integrity_gate_task_satisfies(db: Any) -> None:
    """The scope accepts both gate types — ``GATE`` is what the planner mints
    for an integrity gate, and those are ``gate_requirements`` too."""
    _insert_program(db, evidence=[_requirement()], gates=("data",))
    _satisfy(db, "h1", SUPPORTED_CLASSES)
    _insert_gate_task(db, "gate-data", "data", task_type="GATE")
    _gate_passed(db, "gate-data")

    assert can_complete_research(db, PROJECT).eligible


# ═══════════════════════ 3. C4 — a retracted artifact ═══════════════════════


def test_a_retracted_artifact_does_not_cover_its_requirement(db: Any) -> None:
    """Falsifier 5 — the satisfaction join reads the invalidation marker.

    Retraction is a marker on the artifact row, not a delete: the link and its
    PASS verdict survive, so without the marker check a withdrawn artifact's
    PASS still covered the requirement it was linked to.
    """
    _fully_satisfied(db, marker="INVALIDATED")

    links = db.execute(
        "SELECT COUNT(*) n FROM program_requirement_satisfactions").fetchone()
    assert links["n"] == len(SUPPORTED_CLASSES)   # the links are still there

    eligibility = can_complete_research(db, PROJECT)
    assert not eligibility.eligible
    assert REQUIREMENT_UNSATISFIED in _codes(eligibility)


def test_a_retraction_marker_that_is_not_the_marker_is_ignored(db: Any) -> None:
    """The rule is the marker's exact value, not the key's presence."""
    _fully_satisfied(db, marker="SUPERSEDED")
    assert can_complete_research(db, PROJECT).eligible


# ═══════════════════════ 4. C4 — a malformed obligation denies ══════════════


@pytest.mark.parametrize("requirement, defect", [
    ("not-an-object", "it is str, not an object"),
    ({"required_artifacts": list(SUPPORTED_CLASSES)},
     "its claim_ref is not a non-empty string"),
    ({"claim_ref": "", "required_artifacts": list(SUPPORTED_CLASSES)},
     "its claim_ref is not a non-empty string"),
    ({"claim_ref": "h1", "required_artifacts": "validation"},
     "its required_artifacts is not a list"),
    ({"claim_ref": "h1", "required_artifacts": []},
     "its required_artifacts names no artifact class"),
    ({"claim_ref": "h1", "required_artifacts": ["x", 5]},
     "its required_artifacts[1] is not a non-empty string"),
    ({"claim_ref": "h1", "required_artifacts": ["x", ""]},
     "its required_artifacts[1] is not a non-empty string"),
])
def test_a_malformed_evidence_requirement_denies(
        db: Any, requirement: Any, defect: str) -> None:
    """Falsifier 6a — ``continue`` is not an option for a malformed obligation.

    Each of these used to be skipped (or, for ``["x", 5]``, silently narrowed to
    ``{x}``), so the program declared an obligation the predicate never read. The
    requirement is the only obligation in the program, so the denial below is
    the whole verdict.
    """
    _insert_program(db, evidence=[requirement], gates=())

    eligibility = can_complete_research(db, PROJECT)
    assert not eligibility.eligible
    assert PROGRAM_CORRUPT in _codes(eligibility)
    denial = next(d for d in eligibility.denials if d.code == PROGRAM_CORRUPT)
    assert "evidence_requirements[0]" in denial.explanation
    assert defect in denial.explanation


def test_a_non_string_artifact_class_is_not_narrowed_to_the_strings(
        db: Any) -> None:
    """The exact C4 shape: ``["x", 5]`` must not become ``{x}`` and pass.

    With the old comprehension the requirement read as ``{x}``; a project that
    linked one ``x`` artifact would have completed on a requirement that named
    two classes. It now denies.
    """
    _insert_program(db, evidence=[_requirement(classes=("validation",))],
                    gates=())
    _satisfy(db, "h1", ("validation",))
    # Sanity: the well-formed version of this program is eligible.
    assert can_complete_research(db, PROJECT).eligible

    db.execute("UPDATE research_programs SET evidence_json = ?",
               (json.dumps([{"claim_ref": "h1",
                             "required_artifacts": ["validation", 5]}]),))

    eligibility = can_complete_research(db, PROJECT)
    assert not eligibility.eligible
    assert PROGRAM_CORRUPT in _codes(eligibility)


@pytest.mark.parametrize("gate", [5, None, "", ["hypothesis"]])
def test_a_malformed_gate_requirement_denies(db: Any, gate: Any) -> None:
    """Falsifier 6b — a gate obligation that is not a gate name denies."""
    _insert_program(db, evidence=[], gates=(gate,))

    eligibility = can_complete_research(db, PROJECT)
    assert not eligibility.eligible
    assert PROGRAM_CORRUPT in _codes(eligibility)


def test_an_obligation_container_that_is_not_a_list_denies(db: Any) -> None:
    """A container that cannot be enumerated denies instead of reading empty."""
    _insert_program(db, evidence=[], gates=())
    db.execute("UPDATE research_programs SET gate_json = ?",
               (json.dumps({"hypothesis": True}),))

    eligibility = can_complete_research(db, PROJECT)
    assert not eligibility.eligible
    assert PROGRAM_CORRUPT in _codes(eligibility)
    assert any("gate_requirements" in denial.explanation
               for denial in eligibility.denials)


# ═══════════════════════ 5. the shape of the fix ═══════════════════════


def _function_source(path: Path, name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return ast.get_source_segment(
                path.read_text(encoding="utf-8"), node) or ""
    raise AssertionError(f"{name} not found in {path}")


def test_the_satisfaction_join_reuses_the_repository_marker_rule() -> None:
    """One definition of "retracted", not two.

    The predicate must call the repository's helper rather than spell the marker
    itself — a second spelling is a second definition, and the two drift.
    """
    source = _function_source(Path(str(completion_module.__file__)),
                              "_verdict_covered_classes")
    assert "artifact_is_active(" in source
    assert "INVALIDATED" not in source


def test_the_gate_join_reads_the_program_and_the_terminal_state() -> None:
    """Mechanically: the four facts are in the query, not implied by it."""
    source = _function_source(Path(str(completion_module.__file__)),
                              "_passed_gate_requirements")
    assert "t.task_type IN ('GATE', 'HUMAN_GATE')" in source
    assert "t.status = 'SUCCEEDED'" in source
    assert 'spec.get("program_id") != program_id' in source


def test_the_driver_no_longer_reads_the_transport_counter() -> None:
    """``spine_writes`` is a call count; nothing may decide an effect from it."""
    from hermes.research.task_handlers import methodology_driver as driver

    source = Path(str(driver.__file__)).read_text(encoding="utf-8")
    assert "spine_writes" not in source
    assert "_admission_tally(" in source
    assert "wired.result.proposals" in source


def test_the_predicate_still_denies_through_the_write_path(db: Any) -> None:
    """The invariant is a guard, not a report: the transition refuses too."""
    from hermes.core.lifecycle import LifecycleState, TransitionError

    _fully_satisfied(db, marker="INVALIDATED")
    repo = ProjectRepository(db, clock=lambda: CLOCK)
    for state in _WALK_TO_REPORTING:
        repo.transition_lifecycle(PROJECT, LifecycleState(state),
                                  caused_by="test")
    with pytest.raises(TransitionError) as exc:
        repo.transition_lifecycle(PROJECT, LifecycleState.COMPLETED,
                                  caused_by="test")
    assert "HR-08" in str(exc.value)
