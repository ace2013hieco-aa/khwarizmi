"""HR-08 — the research-completion invariant (pure eligibility contract).

This module pins, as a deterministic and side-effect-free predicate, the
invariant that a research project MUST NOT transition to ``COMPLETED``
merely because its tasks are terminal and its mandatory gates have passed.

    Operational termination is not epistemic completion.

The following operational conditions are, each and together, INSUFFICIENT to
establish research completion and are deliberately NOT consulted by this
contract:

- all tasks are in a terminal status;
- the three mandatory human gates (or any gate) have passed;
- the compute/admission budget is exhausted;
- no READY task remains in the graph.

Completion is an EPISTEMIC property: it requires that every mandatory
research obligation the compiled program declares has been VALIDLY satisfied.
"satisfied" is defined exclusively by the existing Hermes contracts — never
by raw artifact existence, never by artifact class alone, never by a cached
ladder row:

- ``ResearchProgram.evidence_requirements`` — the DERIVED §10.2 obligations
  of the project's current (head) compiled program;
- the per-requirement satisfaction links (IDR-038 §3.1), and only those whose
  linked artifact carries a dereferenceable PASS validation verdict covering
  its content hash (M1 / HR-02 — a bare artifact class can never satisfy a
  requirement);
- the mandatory gate requirements of the program, evidenced by ``GatePassed``
  audit events on the gate tasks that carry them;
- the refutation state — a confirmatory hypothesis whose ladder record is
  REFUTED has NOT been satisfied (refutation routes to revision, §6.1, never
  to completion);
- the contradiction state — an OPEN classification conflict touching the
  program's classifications routes to adjudication (CHG-1), never to
  completion.

The predicate is pure and project-scoped: it performs read-only queries
against the project's own rows, uses no clock and no randomness, writes
nothing, and fails CLOSED — any missing, corrupt, or unverifiable input is a
denial, never a silent pass. It returns a structured ``CompletionEligibility``
whose ``denials`` enumerate every unmet obligation, so a refusal is always
explainable and actionable.

Authority boundary
------------------
This module DECIDES eligibility; it never mutates state and never performs
the transition. The single lifecycle write path
(``ProjectRepository.transition_lifecycle``) consults it as the guard for the
``REPORTING → COMPLETED`` edge, so no current or future driver can reach
``COMPLETED`` without the invariant holding. The future production lifecycle
driver (the component that will decide WHEN to attempt the transition) remains
deferred; when it lands, it MUST call ``can_complete_research`` and MUST NOT
substitute any operational condition for it.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from hermes.persistence.repositories import _research_program_row_to_dict


@dataclass(frozen=True, slots=True)
class CompletionDenial:
    """One structured reason the completion invariant is not met.

    Mirrors the ``CompilationError`` style (Part 2 §12): a machine-readable
    ``code``, the ``subject`` the denial is about (hypothesis ref, gate name,
    or ``project``), the ``requirement`` statement, a human ``explanation``,
    and a ``suggested_next_action``.
    """

    code: str
    subject: str
    requirement: str
    explanation: str
    suggested_next_action: str


@dataclass(frozen=True, slots=True)
class CompletionEligibility:
    """The deterministic verdict of ``can_complete_research``.

    ``eligible`` is True iff ``denials`` is empty. A refusal always carries
    at least one structured denial; the predicate never fails open.
    """

    eligible: bool
    denials: tuple[CompletionDenial, ...] = ()


# ── denial codes (closed vocabulary) ──
NO_PROGRAM = "NO_PROGRAM"
PROGRAM_CORRUPT = "PROGRAM_CORRUPT"
HYPOTHESIS_REFUTED = "HYPOTHESIS_REFUTED"
REQUIREMENT_UNSATISFIED = "REQUIREMENT_UNSATISFIED"
GATE_NOT_PASSED = "GATE_NOT_PASSED"
OPEN_CONTRADICTION = "OPEN_CONTRADICTION"


def _current_program(conn: sqlite3.Connection, project_id: str) -> dict | None:
    """The head of the project's supersession chain (max version), parsed.

    Returns None when the project has no compiled program. Raises ValueError
    when the head row exists but cannot be parsed (fail-closed upstream).
    """
    row = conn.execute(
        "SELECT * FROM research_programs WHERE project_id = ? "
        "ORDER BY version DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    if row is None:
        return None
    return _research_program_row_to_dict(row)


def _verdict_covered_classes(
    conn: sqlite3.Connection, project_id: str,
) -> dict[str, dict[str, set[str]]]:
    """``{program_id: {requirement_ref: set(artifact_types)}}`` — the
    satisfaction facts that count (M1 / HR-02).

    Recomputed from the satisfaction links joined to the artifact rows and the
    PASS validation verdicts whose ``input_hash`` still matches the artifact's
    content hash. A linked artifact without a covering PASS verdict (or whose
    verdict no longer covers its content) contributes nothing — a bare
    artifact class can never satisfy a requirement. Nothing stored is trusted;
    the coverage is re-derived at read time.
    """
    rows = conn.execute(
        """SELECT s.program_id, s.requirement_ref, a.artifact_type
           FROM program_requirement_satisfactions s
           JOIN artifacts a ON a.artifact_id = s.artifact_id
           JOIN validation_verdicts v ON v.artifact_id = s.artifact_id
           WHERE s.project_id = ?
             AND v.project_id = s.project_id
             AND v.verdict = 'PASS'
             AND v.input_hash = a.content_hash""",
        (project_id,),
    ).fetchall()
    out: dict[str, dict[str, set[str]]] = {}
    for r in rows:
        out.setdefault(r["program_id"], {}).setdefault(
            r["requirement_ref"], set()).add(r["artifact_type"])
    return out


def _passed_gate_requirements(
    conn: sqlite3.Connection, project_id: str,
) -> set[str]:
    """The gate requirement names evidenced by a ``GatePassed`` audit event.

    A gate task carries its requirement in ``spec.gate_requirement``
    (task_plan); the ``GatePassed`` event references the task. Only gate names
    that dereference through a real task with a ``GatePassed`` event count —
    an unparseable spec or a missing requirement field contributes nothing
    (fail-closed).
    """
    rows = conn.execute(
        """SELECT t.spec_json
           FROM events e
           JOIN tasks t ON t.task_id = e.task_id
           WHERE e.project_id = ? AND e.event_type = 'GatePassed'""",
        (project_id,),
    ).fetchall()
    passed: set[str] = set()
    for r in rows:
        try:
            spec = json.loads(r["spec_json"] or "{}")
        except (TypeError, ValueError):
            continue
        gate = spec.get("gate_requirement") if isinstance(spec, dict) else None
        if isinstance(gate, str) and gate:
            passed.add(gate)
    return passed


def _open_program_contradictions(
    conn: sqlite3.Connection, project_id: str, program_id: str,
) -> list[str]:
    """OPEN contradiction IDs touching the program's classifications.

    A contradiction touches the program unless proven otherwise: either
    party's classification metadata naming this program suffices (both
    parties share it by the detection rule), and an unreadable party
    row fails closed (deny — a contradiction whose parties cannot be
    verified must block completion, matching the predicate's corrupt-
    program posture). Only rows with both parties verified live and
    foreign to this program are excluded, as are rows with an
    invalidated party (retired; the S5 follow-on supersedes eagerly).
    Deterministic (contradiction_id ASC).
    """
    rows = conn.execute(
        "SELECT contradiction_id, party_a, party_b FROM contradictions "
        "WHERE project_id = ? AND status = 'OPEN' "
        "ORDER BY contradiction_id ASC",
        (project_id,),
    ).fetchall()
    touching = []
    for row in rows:
        if _contradiction_touches_program(
                conn, project_id, program_id,
                row["party_a"], row["party_b"]):
            touching.append(row["contradiction_id"])
    return touching


def _contradiction_touches_program(
    conn: sqlite3.Connection, project_id: str, program_id: str,
    party_a: str, party_b: str,
) -> bool:
    """True unless both parties verify as live and foreign to the
    program. Evaluation order is fixed: (1) any unreadable party row
    fails closed (touching — corruption itself must block completion);
    (2) any invalidation-marked party retires the pair (not touching);
    (3) otherwise touching iff either party names this program."""
    metas = []
    for party in (party_a, party_b):
        prow = conn.execute(
            "SELECT metadata_json FROM artifacts "
            "WHERE artifact_id = ? AND project_id = ?",
            (party, project_id)).fetchone()
        if prow is None:
            return True
        try:
            meta = json.loads(prow["metadata_json"] or "{}")
        except ValueError:
            return True
        if not isinstance(meta, dict):
            return True
        metas.append(meta)
    if any(m.get("invalidation_marker") == "INVALIDATED" for m in metas):
        return False
    return any(m.get("program_ref") == program_id for m in metas)


def _refuted_hypothesis_refs(
    conn: sqlite3.Connection, project_id: str,
) -> set[str]:
    """The hypothesis refs whose ladder record is the REFUTED terminus.

    The ``evidence_ladder_state`` REFUTED row is the ratified applied record
    (written only by the ladder APPLY pass from re-verified ratified input,
    append-only) — consumed here as a recorded falsification fact, never as a
    cached climb rung.
    """
    rows = conn.execute(
        "SELECT hypothesis_ref FROM evidence_ladder_state "
        "WHERE project_id = ? AND rung = 'REFUTED'",
        (project_id,),
    ).fetchall()
    return {r["hypothesis_ref"] for r in rows}


def can_complete_research(
    conn: sqlite3.Connection, project_id: str,
) -> CompletionEligibility:
    """The deterministic completion-eligibility predicate (HR-08).

    Pure, project-scoped, side-effect-free, fail-closed. Answers: *has every
    mandatory research obligation of the project's current compiled program
    been validly satisfied?* It consults ONLY the epistemic contracts
    (program obligations, verdict-covered satisfaction links, gate audit
    events, refutation state) and NEVER the operational conditions (task
    terminality, budget, READY absence).

    Returns a ``CompletionEligibility``; ``eligible`` is True iff no denial
    was found. Every denial is structured and explainable.
    """
    denials: list[CompletionDenial] = []

    # 1. The project must have a current compiled epistemic contract. Without
    #    one there is nothing to have completed — fail closed.
    try:
        program = _current_program(conn, project_id)
    except ValueError:
        denials.append(CompletionDenial(
            PROGRAM_CORRUPT, "project",
            "the current ResearchProgram row must be parseable",
            "the head research_programs row is corrupt and cannot be "
            "dereferenced — completion cannot be verified",
            "repair or supersede the corrupt program row"))
        return CompletionEligibility(False, tuple(denials))
    if program is None:
        denials.append(CompletionDenial(
            NO_PROGRAM, "project",
            "a compiled ResearchProgram must govern the project",
            "no compiled ResearchProgram exists for this project — there is "
            "no epistemic contract whose obligations could be satisfied",
            "compile and ratify a ResearchProgram before completing"))
        return CompletionEligibility(False, tuple(denials))

    program_id = program.get("program_id") or ""
    evidence_requirements = program.get("evidence_requirements") or []
    gate_requirements = program.get("gate_requirements") or []

    covered = _verdict_covered_classes(conn, project_id)
    program_covered = covered.get(program_id, {})
    refuted = _refuted_hypothesis_refs(conn, project_id)

    # 2. Each derived evidence requirement must be validly satisfied: every
    #    required artifact class is covered by a verdict-backed satisfaction
    #    link, and the hypothesis is not refuted.
    for req in evidence_requirements:
        if not isinstance(req, dict):
            continue
        claim_ref = req.get("claim_ref") or ""
        required = req.get("required_artifacts") or []
        required_set = {c for c in required if isinstance(c, str)}

        if claim_ref in refuted:
            denials.append(CompletionDenial(
                HYPOTHESIS_REFUTED, claim_ref,
                "a confirmatory hypothesis must not be refuted to complete",
                f"hypothesis {claim_ref!r} carries a REFUTED ladder record — "
                "refutation routes to revision (§6.1), never to completion",
                "reformulate the hypothesis or record the project outcome "
                "as FAILED/ABANDONED, not COMPLETED"))

        satisfied = program_covered.get(claim_ref, set())
        missing = sorted(required_set - satisfied)
        if missing:
            denials.append(CompletionDenial(
                REQUIREMENT_UNSATISFIED, claim_ref,
                "every required artifact class must be satisfied by a "
                "verdict-covered satisfaction link",
                f"requirement {claim_ref!r} is missing verdict-covered "
                f"satisfaction for: {', '.join(missing)}",
                "produce and validate the missing evidence, then record the "
                "satisfaction links with PASS validation verdicts"))

    # 3. Every mandatory gate requirement must be evidenced by a GatePassed
    #    audit event. Gate passage alone is NOT completion, but an unpassed
    #    mandatory gate is a denial.
    passed = _passed_gate_requirements(conn, project_id)
    for gate in gate_requirements:
        if not isinstance(gate, str) or not gate:
            continue
        if gate not in passed:
            denials.append(CompletionDenial(
                GATE_NOT_PASSED, gate,
                "every mandatory gate requirement must have a GatePassed "
                "audit event",
                f"gate requirement {gate!r} has no GatePassed event on a "
                "gate task that carries it",
                "resolve the gate through the ratified operator/handler "
                "verdict path so the GatePassed event is recorded"))

    # 4. No OPEN contradiction may touch the program's classifications:
    # an unresolved classification conflict routes to adjudication
    # (§6.1 style), never to completion.
    for contradiction_id in _open_program_contradictions(
            conn, project_id, program_id):
        denials.append(CompletionDenial(
            OPEN_CONTRADICTION, contradiction_id,
            "no open classification conflict may touch the program's "
            "classifications at completion",
            f"contradiction {contradiction_id!r} is OPEN over "
            "classifications of this program — unresolved conflict "
            "routes to adjudication, never to completion",
            "resolve the contradiction through the ratified human "
            "verdict path, or record the project outcome as "
            "FAILED/ABANDONED, not COMPLETED"))

    return CompletionEligibility(not denials, tuple(denials))
