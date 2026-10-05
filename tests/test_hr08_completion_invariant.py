"""HR-08 — the research-completion invariant (acceptance tests).

Pins the invariant that a research project MUST NOT transition to COMPLETED
merely because its tasks are terminal and its mandatory gates have passed:
operational termination is not epistemic completion. COMPLETED requires the
valid satisfaction of every mandatory research obligation of the project's
current compiled program (verdict-covered satisfaction links, mandatory gate
audit events, no refuted hypothesis).

Negative cases A–G each deny COMPLETED; the positive case completes; the
guard-property tests pin the write-path behavior (ROLLBACK, no event,
determinism, side-effect freedom).
"""
from __future__ import annotations

import json as _json

import pytest

from hermes.core import frozen_clock
from hermes.core.lifecycle import LifecycleState, TransitionError
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.program_obligations import (
    ProgramRequirementSatisfactionRepository,
    ValidationVerdictRepository,
)
from hermes.persistence.repositories import ProjectRepository
from hermes.research.completion import (
    GATE_NOT_PASSED,
    HYPOTHESIS_REFUTED,
    NO_PROGRAM,
    PROGRAM_CORRUPT,
    REQUIREMENT_UNSATISFIED,
    can_complete_research,
)
from hermes.research.programs import LADDER_OBLIGATIONS, LadderTarget

CLOCK = "2026-01-01T00:00:00.000000+00:00"

SUPPORTED_CLASSES = ("pre_registered_experiment", "statistical_analysis",
                     "validation", "adversarial_critique")
MANDATORY_GATES = ("hypothesis", "pre_compute", "pre_live")

# The full lifecycle walk to REPORTING (v4 §6.1 happy path).
_WALK_TO_REPORTING = (
    LifecycleState.SCOPING,
    LifecycleState.LITERATURE_REVIEW,
    LifecycleState.HYPOTHESIS_FORMULATION,
    LifecycleState.EXPERIMENT_DESIGN,
    LifecycleState.DATA_ACQUISITION,
    LifecycleState.DATA_VALIDATION,
    LifecycleState.IMPLEMENTATION,
    LifecycleState.EXPERIMENTATION,
    LifecycleState.ANALYSIS,
    LifecycleState.VALIDATION,
    LifecycleState.ADVERSARIAL_REVIEW,
    LifecycleState.REPLICATION,
    LifecycleState.REPORTING,
)


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, clock=frozen_clock(CLOCK)).create("p1", "Test")
    yield conn
    conn.close()


def _walk_to_reporting(db):
    """Drive the project to REPORTING through the valid transition table."""
    repo = ProjectRepository(db, clock=frozen_clock(CLOCK))
    for state in _WALK_TO_REPORTING:
        repo.transition_lifecycle("p1", state, caused_by="test")
    assert repo.get_lifecycle("p1") == LifecycleState.REPORTING
    return repo


def _req(claim_ref, ladder="SUPPORTED"):
    """A compiled evidence requirement (the derived §10.2 shape)."""
    artifacts, _ = LADDER_OBLIGATIONS[LadderTarget(ladder)]
    return {"claim_ref": claim_ref, "ladder_target": ladder,
            "required_artifacts": list(artifacts), "associated_gates": []}


def insert_program(db, program_id="rp-1", *, hypotheses=(), evidence=(),
                   gates=(), version=1):
    """A minimal research_programs row with controllable gate_requirements."""
    db.execute(
        """INSERT INTO research_programs
           (program_id, project_id, version, content_hash, supersedes_id,
            scope_ref, epistemic_objective, compiler_version, policy_version,
            schema_version, input_hash, hypothesis_json, prediction_json,
            discrimination_json, evidence_json, gate_json, methodology_json,
            task_graph_template_ref, produced_by, reason, created_at)
           VALUES (?, ?, ?, ?, NULL, 'b', 'o', 'c1', 'p1', '1', 'ih', ?,
                   '[]', '[]', ?, ?, '[]', NULL, 'director', NULL, ?)""",
        (program_id, "p1", version, "ch-" + program_id,
         _json.dumps(list(hypotheses)), _json.dumps(list(evidence)),
         _json.dumps(list(gates)), CLOCK),
    )


def _hyp(ref, ladder="SUPPORTED"):
    return {"ref": ref, "ladder_target": ladder,
            "falsification_condition": "fc", "rival_of": None,
            "rival_status": None}


def insert_artifact(db, artifact_id, artifact_type):
    db.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type,
            content_hash, size_bytes, storage_path, producer,
            metadata_json, created_at)
           VALUES (?, 'p1', NULL, ?, ?, 1, 'x', 't', '{}', ?)""",
        (artifact_id, artifact_type, "ch-" + artifact_id, CLOCK),
    )


def satisfy(db, program_id, requirement_ref, classes, prefix="art",
            *, verdicts: bool = True):
    """Insert required-class artifacts and record satisfaction links.

    ``verdicts=True`` records a PASS validation verdict per artifact (the
    M1/HR-02 shape). ``verdicts=False`` inserts the links via raw SQL (the
    pre-M1 shape) — the write path refuses verdict-less links, so this
    exercises structural-only satisfaction that the predicate must deny.
    """
    repo = ProgramRequirementSatisfactionRepository(
        db, clock=frozen_clock(CLOCK))
    verdict_repo = ValidationVerdictRepository(db, clock=frozen_clock(CLOCK))
    for i, cls in enumerate(classes):
        aid = f"{prefix}-{i}-{cls}"
        insert_artifact(db, aid, cls)
        if verdicts:
            verdict_repo.record(project_id="p1", artifact_id=aid,
                                verdict="PASS")
            repo.record(project_id="p1", program_id=program_id,
                        requirement_ref=requirement_ref, artifact_id=aid)
        else:
            db.execute(
                """INSERT INTO program_requirement_satisfactions
                   (satisfaction_id, project_id, program_id, requirement_ref,
                    artifact_id, created_at)
                   VALUES (?, 'p1', ?, ?, ?, ?)""",
                (f"ss_{prefix}_{i}_{cls}", program_id, requirement_ref,
                 aid, CLOCK))


def insert_gate_task(db, task_id, gate_name):
    """A HUMAN_GATE task carrying its requirement in spec.gate_requirement."""
    db.execute(
        """INSERT INTO tasks
           (task_id, project_id, task_type, idempotency_key, status,
            spec_json, created_at)
           VALUES (?, 'p1', 'HUMAN_GATE', ?, 'SUCCEEDED', ?, ?)""",
        (task_id, f"idem-{task_id}",
         _json.dumps({"gate_requirement": gate_name}), CLOCK),
    )


def gate_passed(db, task_id):
    """A GatePassed audit event referencing the gate task."""
    db.execute(
        """INSERT INTO events
           (event_type, project_id, task_id, caused_by, reason, created_at)
           VALUES ('GatePassed', 'p1', ?, 'operator', 'human verdict
           APPROVED', ?)""",
        (task_id, CLOCK),
    )


def pass_all_gates(db):
    """Evidence every mandatory gate with a GatePassed event."""
    for g in MANDATORY_GATES:
        insert_gate_task(db, f"gate-{g}", g)
        gate_passed(db, f"gate-{g}")


def insert_terminal_tasks(db, n=4):
    """Operational termination: a graph of tasks all in terminal status."""
    for i in range(n):
        db.execute(
            """INSERT INTO tasks
               (task_id, project_id, task_type, idempotency_key, status,
                spec_json, created_at)
               VALUES (?, 'p1', 'AGENT_TASK', ?, 'SUCCEEDED', '{}', ?)""",
            (f"task-{i}", f"idem-task-{i}", CLOCK),
        )


def insert_refuted(db, program_id, hypothesis_ref):
    """A ratified REFUTED ladder terminus (the falsification fact)."""
    db.execute(
        """INSERT INTO evidence_ladder_state
           (state_id, project_id, program_id, hypothesis_ref, version,
            rung, transition_id, derived_from, created_at)
           VALUES (?, 'p1', ?, ?, 1, 'REFUTED', ?, 'ratification', ?)""",
        (f"elst-refuted-{hypothesis_ref}", program_id, hypothesis_ref,
         f"eltr-refuted-{hypothesis_ref}", CLOCK),
    )


def _fully_satisfied(db):
    """The positive baseline: program + full verdict-covered satisfaction +
    all mandatory gates passed, no refutation."""
    insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")],
                   gates=list(MANDATORY_GATES))
    satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES)
    pass_all_gates(db)


def _codes(eligibility):
    return {d.code for d in eligibility.denials}


# ── negative case A: all tasks terminal, evidence requirement unsatisfied ──

def test_negative_a_tasks_terminal_requirement_unsatisfied(db):
    insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")],
                   gates=list(MANDATORY_GATES))
    insert_terminal_tasks(db)          # operational termination holds
    pass_all_gates(db)                 # gates passed too — still not enough

    eligibility = can_complete_research(db, "p1")
    assert not eligibility.eligible
    assert REQUIREMENT_UNSATISFIED in _codes(eligibility)

    # The write path refuses and leaves the DB unchanged.
    repo = _walk_to_reporting(db)
    events_before = db.execute(
        "SELECT COUNT(*) n FROM events").fetchone()["n"]
    with pytest.raises(TransitionError) as exc:
        repo.transition_lifecycle("p1", LifecycleState.COMPLETED)
    assert "HR-08" in str(exc.value)
    assert repo.get_lifecycle("p1") == LifecycleState.REPORTING
    assert db.execute(
        "SELECT COUNT(*) n FROM events").fetchone()["n"] == events_before


# ── negative case B: gates passed, obligation missing ──

def test_negative_b_gates_passed_obligation_missing(db):
    insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")],
                   gates=list(MANDATORY_GATES))
    insert_terminal_tasks(db)
    pass_all_gates(db)                 # all three mandatory gates passed
    # satisfy only 3 of the 4 required classes — one obligation missing
    satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES[:3])

    eligibility = can_complete_research(db, "p1")
    assert not eligibility.eligible
    assert REQUIREMENT_UNSATISFIED in _codes(eligibility)
    # the missing class is named in the denial
    denial = next(d for d in eligibility.denials
                  if d.code == REQUIREMENT_UNSATISFIED)
    assert "adversarial_critique" in denial.explanation


# ── negative case C: budget exhausted is not completion ──

def test_negative_c_budget_exhausted_denied(db):
    # Budget exhaustion is modeled as full operational termination with no
    # remaining headroom: every task terminal, nothing schedulable. The
    # predicate never consults budget — completion still requires the
    # epistemic contract, which is absent here.
    insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")],
                   gates=list(MANDATORY_GATES))
    insert_terminal_tasks(db, n=8)     # exhausted: all work spent

    eligibility = can_complete_research(db, "p1")
    assert not eligibility.eligible
    assert REQUIREMENT_UNSATISFIED in _codes(eligibility)
    assert GATE_NOT_PASSED in _codes(eligibility)


# ── negative case D: no READY tasks remain is not completion ──

def test_negative_d_no_ready_tasks_denied(db):
    # No READY tasks: the graph has nothing schedulable (all terminal).
    # The predicate never consults task state — completion still denied.
    insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")],
                   gates=list(MANDATORY_GATES))
    insert_terminal_tasks(db, n=6)
    ready = db.execute(
        "SELECT COUNT(*) n FROM tasks WHERE status = 'READY'").fetchone()["n"]
    assert ready == 0                  # the operational condition holds

    eligibility = can_complete_research(db, "p1")
    assert not eligibility.eligible


# ── negative case E: structural links without verdicts ──

def test_negative_e_structural_links_without_verdicts_denied(db):
    insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")],
                   gates=list(MANDATORY_GATES))
    pass_all_gates(db)
    # All required satisfaction links exist STRUCTURALLY, but their artifacts
    # carry no PASS validation verdict (the pre-M1 shape). A bare artifact
    # class can never satisfy a requirement.
    satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES, verdicts=False)

    links = db.execute(
        "SELECT COUNT(*) n FROM program_requirement_satisfactions"
    ).fetchone()["n"]
    assert links == len(SUPPORTED_CLASSES)  # links are present

    eligibility = can_complete_research(db, "p1")
    assert not eligibility.eligible
    assert REQUIREMENT_UNSATISFIED in _codes(eligibility)


# ── negative case F: refuted hypothesis ──

def test_negative_f_refuted_hypothesis_denied(db):
    _fully_satisfied(db)               # obligations + gates all satisfied
    insert_refuted(db, "rp-1", "h1")   # but the hypothesis is refuted

    eligibility = can_complete_research(db, "p1")
    assert not eligibility.eligible
    assert HYPOTHESIS_REFUTED in _codes(eligibility)


# ── negative case G: no program / corrupt program ──

def test_negative_g_no_program_denied(db):
    insert_terminal_tasks(db)
    pass_all_gates(db)
    eligibility = can_complete_research(db, "p1")
    assert not eligibility.eligible
    assert NO_PROGRAM in _codes(eligibility)


def test_negative_g_corrupt_program_denied(db):
    # A head row whose evidence_json cannot be parsed is a denial, never a
    # crash and never a silent pass.
    db.execute(
        """INSERT INTO research_programs
           (program_id, project_id, version, content_hash, supersedes_id,
            scope_ref, epistemic_objective, compiler_version, policy_version,
            schema_version, input_hash, hypothesis_json, prediction_json,
            discrimination_json, evidence_json, gate_json, methodology_json,
            task_graph_template_ref, produced_by, reason, created_at)
           VALUES ('rp-bad', 'p1', 1, 'ch-bad', NULL, 'b', 'o', 'c1', 'p1',
                   '1', 'ih', 'NOT-JSON', '[]', '[]', '[]', '[]', '[]',
                   NULL, 'director', NULL, ?)""",
        (CLOCK,),
    )
    eligibility = can_complete_research(db, "p1")
    assert not eligibility.eligible
    assert PROGRAM_CORRUPT in _codes(eligibility)


# ── positive case: full valid satisfaction completes ──

def test_positive_full_satisfaction_completes(db):
    _fully_satisfied(db)

    eligibility = can_complete_research(db, "p1")
    assert eligibility.eligible
    assert eligibility.denials == ()

    repo = _walk_to_reporting(db)
    repo.transition_lifecycle("p1", LifecycleState.COMPLETED,
                              caused_by="test")
    assert repo.get_lifecycle("p1") == LifecycleState.COMPLETED
    # exactly one LifecycleTransition to COMPLETED
    row = db.execute(
        "SELECT COUNT(*) n FROM events WHERE event_type = "
        "'LifecycleTransition' AND to_state = 'COMPLETED'").fetchone()
    assert row["n"] == 1


# ── guard properties ──

def test_denied_transition_appends_no_event_and_rolls_back(db):
    insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")],
                   gates=list(MANDATORY_GATES))
    repo = _walk_to_reporting(db)
    events_before = db.execute(
        "SELECT COUNT(*) n FROM events").fetchone()["n"]
    state_before = repo.get_lifecycle("p1")

    with pytest.raises(TransitionError):
        repo.transition_lifecycle("p1", LifecycleState.COMPLETED)

    assert repo.get_lifecycle("p1") == state_before
    assert db.execute(
        "SELECT COUNT(*) n FROM events").fetchone()["n"] == events_before


def test_predicate_is_deterministic_and_side_effect_free(db):
    _fully_satisfied(db)

    def _snapshot():
        tables = ("research_programs", "artifacts", "validation_verdicts",
                  "program_requirement_satisfactions", "events",
                  "evidence_ladder_state", "tasks", "projects")
        return {t: db.execute(
            f"SELECT COUNT(*) n FROM {t}").fetchone()["n"] for t in tables}

    before = _snapshot()
    first = can_complete_research(db, "p1")
    second = can_complete_research(db, "p1")
    after = _snapshot()

    assert first.eligible == second.eligible
    assert first.denials == second.denials   # identical structured verdict
    assert before == after                   # no writes, no side effects


def test_denial_reason_enumerates_codes(db):
    insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")],
                   gates=list(MANDATORY_GATES))
    repo = _walk_to_reporting(db)
    with pytest.raises(TransitionError) as exc:
        repo.transition_lifecycle("p1", LifecycleState.COMPLETED)
    msg = str(exc.value)
    assert REQUIREMENT_UNSATISFIED in msg
    assert GATE_NOT_PASSED in msg


def test_non_completed_transitions_unguarded(db):
    """FAILED / ABANDONED remain reachable without the epistemic contract —
    operational termination of an unsuccessful project is legitimate."""
    repo = ProjectRepository(db, clock=frozen_clock(CLOCK))
    repo.transition_lifecycle("p1", LifecycleState.SCOPING)
    repo.transition_lifecycle("p1", LifecycleState.FAILED,
                              caused_by="test", reason="unrecoverable")
    assert repo.get_lifecycle("p1") == LifecycleState.FAILED
