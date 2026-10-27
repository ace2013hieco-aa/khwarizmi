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
  requirement) **and is still live** — a retracted artifact's PASS covers
  nothing (OPS-5T);
- the mandatory gate requirements of the program, evidenced by ``GatePassed``
  audit events on **succeeding gate tasks planned for this program** — not on a
  task of another program, not on a task that ended ``FAILED``, not on a task
  that is not a gate (OPS-5T);
- the well-formedness of the obligations themselves: a malformed requirement
  denies completion instead of vanishing from it (OPS-5T);
- the refutation state — a confirmatory hypothesis whose ladder record is
  REFUTED has NOT been satisfied (refutation routes to revision, §6.1, never
  to completion);
- the contradiction state — a classification conflict touching the
  program's classifications routes to adjudication (CHG-1), never to
  completion; the conflict set is re-derived at read time (stored OPEN
  rows plus a fresh pure-detector pass over the current classification
  rows), so a conflict admitted after the last detector pass cannot be
  invisible (no completion blind window);
- the stored program/hypothesis refs — canonicalised through the project's
  program rows (OPS-5Q), so the bare and ``research_program:<hash>``
  spellings of one program cannot hide a conflict; an unresolvable ref is
  a denial, never a silent grouping.

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
from typing import Any

from hermes.core.program_refs import canonical_program_scope
from hermes.persistence.repositories import (
    _research_program_row_to_dict,
    artifact_is_active,
)


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
PROGRAM_REF_UNRESOLVED = "PROGRAM_REF_UNRESOLVED"
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


def _project_programs(
    conn: sqlite3.Connection, project_id: str,
) -> list[dict]:
    """Every parseable program row in the project, deterministically ordered.

    The canonicalisation context for both admitted program-ref spellings
    (OPS-5Q): a bare ``<program_id>`` and a
    ``research_program:<content_hash>`` ref resolve through these rows. A
    corrupt row cannot name a program and is skipped; a classification
    citing it then fails canonicalisation and blocks completion (fail
    closed), never silently names a different program.
    """
    rows = conn.execute(
        "SELECT * FROM research_programs WHERE project_id = ? "
        "ORDER BY version, program_id",
        (project_id,),
    ).fetchall()
    programs: list[dict] = []
    for row in rows:
        try:
            programs.append(_research_program_row_to_dict(row))
        except ValueError:
            continue
    return programs


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

    OPS-5T: a **retracted** artifact contributes nothing either. The link and
    its PASS verdict survive a retraction — retraction is a metadata marker on
    the artifact row, not a delete — so without this filter a retracted
    artifact's PASS still covered the requirement it was linked to, and a
    project could complete on evidence that had been withdrawn. The marker is
    read through the repository's own rule (``artifact_is_active``), not a
    second copy of it: the same predicate that retires a contradiction party
    decides whether a satisfaction link still covers its requirement.
    """
    rows = conn.execute(
        """SELECT s.program_id, s.requirement_ref, s.artifact_id, a.artifact_type
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
    active: dict[str, bool] = {}
    for r in rows:
        artifact_id = r["artifact_id"]
        if artifact_id not in active:
            active[artifact_id] = artifact_is_active(conn, artifact_id)
        if not active[artifact_id]:
            continue
        out.setdefault(r["program_id"], {}).setdefault(
            r["requirement_ref"], set()).add(r["artifact_type"])
    return out


def _passed_gate_requirements(
    conn: sqlite3.Connection, project_id: str, program_id: str,
) -> set[str]:
    """The gate requirement names this program has actually had passed.

    A gate task carries its requirement in ``spec.gate_requirement`` and the
    program it was planned for in ``spec.program_id`` (``task_plan.build_task_plan``,
    whose task identity is content-addressed over that program id). A
    ``GatePassed`` audit event references the task, so the join reads five
    facts, not one (OPS-5T):

    - the event is in this project;
    - the task is in the same project as the event (a mis-filed event cannot
      borrow a foreign task's spec);
    - the task is a gate — ``GATE`` or ``HUMAN_GATE``, the two types the
      planner mints for ``gate_requirements``;
    - the task is **terminal ``SUCCEEDED``** — a ``GatePassed`` that outlived
      its task's failure (``_commit_gate`` is two writes, H4) is not a pass;
    - the task's spec names **this** program.

    The last one is the program scope. Before it, a gate passed by an older
    program satisfied the current one: the planner issues a fresh gate task per
    program (its idempotency key digests the program id), so the older task was
    never the task this program's contract names — the predicate was reading a
    verdict about a different contract. A gate task that carries no
    ``program_id``, or an unparseable spec, contributes nothing: it cannot
    prove it belongs to this program, and completion is fail-closed.
    """
    rows = conn.execute(
        """SELECT t.spec_json
           FROM events e
           JOIN tasks t ON t.task_id = e.task_id
           WHERE e.project_id = ?
             AND e.event_type = 'GatePassed'
             AND t.project_id = e.project_id
             AND t.task_type IN ('GATE', 'HUMAN_GATE')
             AND t.status = 'SUCCEEDED'""",
        (project_id,),
    ).fetchall()
    passed: set[str] = set()
    for r in rows:
        try:
            spec = json.loads(r["spec_json"] or "{}")
        except (TypeError, ValueError):
            continue
        if not isinstance(spec, dict):
            continue
        if spec.get("program_id") != program_id:
            continue
        gate = spec.get("gate_requirement")
        if isinstance(gate, str) and gate:
            passed.add(gate)
    return passed


def _open_program_contradictions(
    conn: sqlite3.Connection, project_id: str, program_id: str,
    programs: list[dict], fresh: list[dict],
) -> list[str]:
    """Contradiction IDs blocking completion for this program.

    The blocking set is re-derived at read time, never trusted from
    storage alone: stored rows with status OPEN (the recorded, not-yet-
    adjudicated conflicts) PLUS ``fresh`` — the pure production detector
    re-run over the current digest-valid classification rows — so a
    conflict that appears after the last detector pass cannot be
    invisible (the P1-10 blind window). A recomputed pair re-blocks only
    when no contradiction row for its identity exists: a pair already
    adjudicated (RESOLVED) or retired (SUPERSEDED) stays non-blocking,
    mirroring the stored OPEN-only rule.

    A contradiction touches the program unless proven otherwise: either
    party's canonical program scope names this program suffices (both
    parties share it by the detection rule), and an unreadable party row
    or an uncanonicalisable ref fails closed (deny — a contradiction
    whose parties cannot be verified must block completion, matching the
    predicate's corrupt-program posture). Only rows with both parties
    verified live and foreign to this program are excluded, as are rows
    with an invalidated party (retired; the S5 follow-on supersedes
    eagerly). Deterministic (contradiction_id ASC).
    """
    stored = conn.execute(
        "SELECT contradiction_id, party_a, party_b, status "
        "FROM contradictions WHERE project_id = ? "
        "ORDER BY contradiction_id ASC",
        (project_id,),
    ).fetchall()
    stored_ids = {row["contradiction_id"] for row in stored}
    touching = []
    for row in stored:
        if row["status"] != "OPEN":
            continue
        if _contradiction_touches_program(
                conn, project_id, program_id, programs,
                row["party_a"], row["party_b"]):
            touching.append(row["contradiction_id"])
    for candidate in fresh:
        if candidate["contradiction_id"] in stored_ids:
            continue
        if _contradiction_touches_program(
                conn, project_id, program_id, programs,
                candidate["party_a"], candidate["party_b"]):
            touching.append(candidate["contradiction_id"])
    return sorted(touching)


def _contradiction_touches_program(
    conn: sqlite3.Connection, project_id: str, program_id: str,
    programs: list[dict], party_a: str, party_b: str,
) -> bool:
    """True unless both parties verify as live and foreign to the
    program. Evaluation order is fixed: (1) any unreadable party row
    fails closed (touching — corruption itself must block completion);
    (2) any invalidation-marked party retires the pair (not touching);
    (3) otherwise touching iff either party's canonical program scope
    names this program. An uncanonicalisable ref fails closed (touching)."""
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
    for meta in metas:
        scope = canonical_program_scope(
            meta.get("program_ref"), meta.get("hypothesis_ref"), programs)
        if scope is None:
            return True  # cannot prove foreign → touching (fail closed)
        if scope[0] == program_id:
            return True
    return False


def _fresh_program_conflicts(
    conn: sqlite3.Connection, project_id: str, programs: list[dict],
    diagnostics: dict | None = None,
) -> list[dict]:
    """The pure production detector re-run over the CURRENT
    digest-valid classification rows (the P1-10 blind-window closure).

    Read-only, same transaction, deterministic: reuses the production
    candidate-row derivation (``detector_candidate_rows`` over the
    ``classifications_digest`` of the project's rows — the exact inputs
    the controller's detector pass consumes) and the pure N1 pair rule
    (``detect_classification_conflicts``), never a reimplementation. The
    project's program rows are the canonicalisation context (OPS-5Q);
    unresolved refs are reported in ``diagnostics``. Output is sorted by
    ``contradiction_id``; the per-pass pair budget is the production
    detector's own (``DEFAULT_MAX_PAIRS``).
    """
    from hermes.persistence.failure_classifications import (
        FailureClassificationRepository,
        classifications_digest,
    )
    from hermes.research.contradiction_candidates import (
        detector_candidate_rows,
    )
    from hermes.research.contradictions import (
        detect_classification_conflicts,
    )

    digest = classifications_digest(
        FailureClassificationRepository(conn).classifications_for_project(
            project_id))
    rows = detector_candidate_rows(
        conn, project_id, digest.get("items", []))
    return detect_classification_conflicts(
        rows, programs=programs, diagnostics=diagnostics)


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


def _obligation_list(
    program: dict, key: str, denials: list[CompletionDenial],
) -> list:
    """The program's obligation list under ``key``, or ``[]`` plus a denial.

    OPS-5T: a derived obligation list that is not a list cannot be enumerated,
    and "cannot be enumerated" is a denial, never an empty obligation set — an
    empty set is what a completed program looks like.
    """
    value = program.get(key) or []
    if isinstance(value, list):
        return value
    denials.append(CompletionDenial(
        PROGRAM_CORRUPT, "project",
        "every derived obligation of the program must be enumerable",
        f"the program's {key} is {type(value).__name__}, not a list — its "
        "obligations cannot be enumerated, so completion cannot be verified",
        "recompile the program so its derived obligations are well-formed, "
        "or supersede the corrupt row"))
    return []


def _read_evidence_requirement(
    position: int, requirement: Any,
) -> tuple[str, set[str], str]:
    """``(claim_ref, required_classes, defect)`` for one derived obligation.

    OPS-5T closes the two shapes the predicate used to swallow. A requirement
    that is not an object was ``continue``-d — the obligation simply vanished
    from the verdict. And ``required_artifacts`` was read as
    ``{c for c in required if isinstance(c, str)}``, so ``["x", 5]`` became
    ``{x}``: the malformed element disappeared and the requirement could be
    satisfied by a subset of what it named. Both are the same failure — a
    malformed obligation reading as *fewer* obligations than the program
    declares — so both now return a ``defect`` the caller turns into a denial.

    ``required_artifacts: []`` is a defect too. The write path refuses every
    satisfaction link for a requirement that names no class
    (``program_obligations``), so such a requirement can never be satisfied;
    the read path treating it as vacuously satisfied would be the write path
    and the predicate disagreeing about the same row.
    """
    if not isinstance(requirement, dict):
        return "", set(), f"it is {type(requirement).__name__}, not an object"
    claim_ref = requirement.get("claim_ref")
    if not isinstance(claim_ref, str) or not claim_ref:
        return "", set(), "its claim_ref is not a non-empty string"
    required = requirement.get("required_artifacts")
    if not isinstance(required, list):
        return claim_ref, set(), "its required_artifacts is not a list"
    if not required:
        return claim_ref, set(), "its required_artifacts names no artifact class"
    classes: set[str] = set()
    for index, item in enumerate(required):
        if not isinstance(item, str) or not item:
            return claim_ref, set(), (
                f"its required_artifacts[{index}] is not a non-empty string")
        classes.add(item)
    return claim_ref, classes, ""


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
    from hermes.research.contradictions import DETECTOR_UNCANONICALISED

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
    evidence_requirements = _obligation_list(
        program, "evidence_requirements", denials)
    gate_requirements = _obligation_list(program, "gate_requirements", denials)

    covered = _verdict_covered_classes(conn, project_id)
    program_covered = covered.get(program_id, {})
    refuted = _refuted_hypothesis_refs(conn, project_id)

    # 2. Each derived evidence requirement must be validly satisfied: every
    #    required artifact class is covered by a verdict-backed satisfaction
    #    link, and the hypothesis is not refuted. A malformed obligation is a
    #    denial (the program is corrupt), never a silently dropped one.
    for position, req in enumerate(evidence_requirements):
        claim_ref, required_set, defect = _read_evidence_requirement(
            position, req)
        if defect:
            denials.append(CompletionDenial(
                PROGRAM_CORRUPT, "project",
                "every derived evidence requirement must be a well-formed "
                "obligation of the program",
                f"the program's evidence_requirements[{position}] is "
                f"malformed — {defect} — so the obligation it states cannot be "
                "verified",
                "recompile the program so its derived obligations are "
                "well-formed, or supersede the corrupt row"))
            continue

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
    #    audit event on a succeeding gate task of THIS program. Gate passage
    #    alone is NOT completion, but an unpassed mandatory gate is a denial.
    #    A requirement that is not a gate name is a malformed obligation, which
    #    denies rather than being skipped (OPS-5T).
    passed = _passed_gate_requirements(conn, project_id, program_id)
    for position, gate in enumerate(gate_requirements):
        if not isinstance(gate, str) or not gate:
            denials.append(CompletionDenial(
                PROGRAM_CORRUPT, "project",
                "every derived gate requirement must be a non-empty gate name",
                f"the program's gate_requirements[{position}] is "
                f"{type(gate).__name__}, not a gate name — the obligation it "
                "states cannot be verified",
                "recompile the program so its derived obligations are "
                "well-formed, or supersede the corrupt row"))
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

    # 4. Every classification's stored refs must resolve to a project
    #    program and its registered hypothesis; an unresolvable ref is
    #    unverifiable input and denies completion (fail closed). Then no
    #    open classification conflict may touch the program's
    #    classifications — stored OPEN rows AND conflicts freshly
    #    recomputed over the canonical scope (no blind window): an
    #    unresolved conflict routes to adjudication (§6.1 style), never
    #    to completion.
    programs = _project_programs(conn, project_id)
    conflict_diagnostics: dict = {}
    fresh = _fresh_program_conflicts(
        conn, project_id, programs, conflict_diagnostics)
    for item in conflict_diagnostics.get(
            DETECTOR_UNCANONICALISED, {}).get("rows", []):
        artifact_id = str(item.get("artifact_id") or "")
        denials.append(CompletionDenial(
            PROGRAM_REF_UNRESOLVED, artifact_id,
            "every classification's program_ref and hypothesis_ref must "
            "resolve to a project program and its registered hypothesis",
            f"classification {artifact_id!r} cites program_ref "
            f"{item.get('program_ref')!r} / hypothesis_ref "
            f"{item.get('hypothesis_ref')!r}, which cannot be "
            "canonicalised — completion cannot be verified",
            "repair the classification's refs or supersede the row"))
    for contradiction_id in _open_program_contradictions(
            conn, project_id, program_id, programs, fresh):
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
