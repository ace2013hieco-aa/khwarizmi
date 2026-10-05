"""Q-02 IDR-038 §3.1 (evaluator 1.2.0) — per-requirement satisfaction links (persistence).

The Q-02 obligation derivation consumes, per program, which artifact CLASSES
have satisfied each evidence requirement. This slice stores the link an
artifact → a specific requirement (identified by its ``claim_ref``) of a
specific program, with hard validation at admission:

1. the program exists and is governed by the project (dereference);
2. the requirement dereferences to a real evidence requirement of that
   program;
3. the artifact exists and belongs to the project;
4. the artifact's ``artifact_type`` is one of the requirement's
   ``required_artifacts`` classes — a link can never claim a class the
   requirement does not require;
5. the artifact carries a dereferenceable PASS validation verdict whose
   input-hash covers the artifact's content hash (M1 / HR-02 — content
   validation gates the ladder: a bare artifact class can never satisfy
   a requirement).

The link is a *recorded fact*, never a derived verdict: the derivation
recomputes satisfaction from the rows + artifact types + verdict coverage
(nothing stored is derived). Idempotent (``UNIQUE (program_id,
requirement_ref, artifact_id)``), append-only (no UPDATE/DELETE path), no
new event type (audit is the immutable rows). This slice adds no authority:
the write validates and records; the Q-02 ordering and the Evidence Ladder
only read.

``validation_verdicts`` (migration 12→13) is the M1 verdict substrate: one
row per (project, artifact) recording that the artifact's CONTENT was
validated (PASS/FAIL), keyed to the artifact's content hash — ``input_hash``
must equal ``artifacts.content_hash`` at write AND at read (the derivation
re-verifies against the artifact row, never trusting a stored field). Only
PASS verdicts cover; the satisfaction write requires one and the read
reports only verdict-covered classes.
"""
from __future__ import annotations

import sqlite3

from hermes.core import Clock, utc_now
from hermes.persistence.repositories import _research_program_row_to_dict


class RequirementSatisfactionError(Exception):
    """A satisfaction-link write violates the IDR-038 §3.1 contract."""


class ValidationVerdictError(Exception):
    """A validation-verdict write violates the M1 content-validation
    contract (HR-02 closure)."""


def validation_verdict_id_of(project_id: str, artifact_id: str) -> str:
    """Content-derived identity (PA4): same (project, artifact) ⇒ same id."""
    from hermes.research.programs import canonical_json, sha256_hex
    payload = canonical_json({
        "project_id": project_id,
        "artifact_id": artifact_id,
    })
    return f"vv_{sha256_hex(payload)[:24]}"


class ValidationVerdictRepository:
    """Read/write ``validation_verdicts`` (migration 12→13, M1/HR-02).

    Records that an artifact's CONTENT was validated (PASS/FAIL), keyed to
    the artifact's content hash. The write validates at admission; the
    coverage read re-verifies ``input_hash`` against the artifact row at
    read time (F2: never trust a stored field — a tampered verdict row or
    artifact content hash loses coverage, never silently). Idempotent
    (``UNIQUE (project_id, artifact_id)``), append-only (no UPDATE/DELETE
    path). Adds no authority: this records a fact; the satisfaction write
    and the ladder derivation decide what the verdict covers.
    """

    def __init__(self, conn: sqlite3.Connection, clock: Clock | None = None):
        self._conn = conn
        self._clock = clock or utc_now

    # ── the validated write path ──

    def record(
        self,
        *,
        project_id: str,
        artifact_id: str,
        verdict: str,
    ) -> dict:
        """Record that one artifact's content was validated (PASS/FAIL).

        Raises ``ValidationVerdictError`` for any contract violation (M1):
        the artifact must exist in the project (dereference), and the
        verdict must be in the closed PASS/FAIL vocabulary. The row's
        ``input_hash`` is the artifact's CONTENT hash re-derived from the
        artifacts row — never accepted from the caller, never a stored
        field. Idempotent: a duplicate (project, artifact) returns the
        existing row and writes nothing new.
        """
        # 1. The artifact must exist and belong to the project.
        art = self._conn.execute(
            "SELECT artifact_id, content_hash FROM artifacts "
            "WHERE artifact_id = ? AND project_id = ?",
            (artifact_id, project_id),
        ).fetchone()
        if art is None:
            raise ValidationVerdictError(
                f"artifact {artifact_id!r} does not exist in project "
                f"{project_id!r} — a validation verdict must dereference "
                f"(M1)")

        # 2. The verdict must be in the closed vocabulary.
        if verdict not in ("PASS", "FAIL"):
            raise ValidationVerdictError(
                f"verdict {verdict!r} is not in the closed PASS/FAIL "
                f"vocabulary (M1)")

        # 3. Idempotent: an existing (project, artifact) row returns it.
        existing = self._conn.execute(
            "SELECT * FROM validation_verdicts "
            "WHERE project_id = ? AND artifact_id = ?",
            (project_id, artifact_id),
        ).fetchone()
        if existing is not None:
            return dict(existing)

        verdict_id = validation_verdict_id_of(project_id, artifact_id)
        ts = self._clock()
        self._conn.execute(
            """INSERT INTO validation_verdicts
               (verdict_id, project_id, artifact_id, input_hash,
                verdict, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (verdict_id, project_id, artifact_id, art["content_hash"],
             verdict, ts),
        )
        return {
            "verdict_id": verdict_id,
            "project_id": project_id,
            "artifact_id": artifact_id,
            "input_hash": art["content_hash"],
            "verdict": verdict,
            "created_at": ts,
        }

    # ── read helpers (verdict coverage, re-verified against the artifact row) ──

    def verdict_covered_artifact_ids(
        self, project_id: str,
    ) -> frozenset[str]:
        """The artifact ids whose content is covered by a PASS verdict
        (M1). Re-verifies ``input_hash`` against the artifact row at read
        time — a verdict whose input-hash no longer matches the artifact's
        content hash (tamper, or a hash collision on rewrite) loses
        coverage, never silently counts."""
        rows = self._conn.execute(
            """SELECT v.artifact_id
               FROM validation_verdicts v
               JOIN artifacts a ON a.artifact_id = v.artifact_id
               WHERE v.project_id = ? AND v.verdict = 'PASS'
                 AND v.input_hash = a.content_hash""",
            (project_id,),
        ).fetchall()
        return frozenset(r["artifact_id"] for r in rows)


def satisfaction_id_of(program_id: str, requirement_ref: str,
                       artifact_id: str) -> str:
    """Content-derived identity (PA4): same triple ⇒ same id."""
    from hermes.research.programs import canonical_json, sha256_hex
    payload = canonical_json({
        "program_id": program_id,
        "requirement_ref": requirement_ref,
        "artifact_id": artifact_id,
    })
    return f"ss_{sha256_hex(payload)[:24]}"


class ProgramRequirementSatisfactionRepository:
    """Read/write ``program_requirement_satisfactions`` (migration 8→9)."""

    def __init__(self, conn: sqlite3.Connection, clock: Clock | None = None):
        self._conn = conn
        self._clock = clock or utc_now

    # ── the validated write path ──

    def record(
        self,
        *,
        project_id: str,
        program_id: str,
        requirement_ref: str,
        artifact_id: str,
    ) -> dict:
        """Record that an artifact satisfies one evidence requirement.

        Raises ``RequirementSatisfactionError`` for any contract violation
        (IDR-038 §3.1 rules 1–4). Idempotent: a duplicate triple returns the
        existing row and writes nothing new. No free-form metadata: the row
        IS the audit (append-only, content-derived identity).
        """
        # 1. Program must exist and be governed by the project.
        row = self._conn.execute(
            "SELECT * FROM research_programs "
            "WHERE program_id = ? AND project_id = ?",
            (program_id, project_id),
        ).fetchone()
        if row is None:
            raise RequirementSatisfactionError(
                f"research_program:{program_id!r} is not governed by project "
                f"{project_id!r} — a satisfaction link must dereference "
                f"(IDR-038 §3.1 rule 1)")
        try:
            program = _research_program_row_to_dict(row)
        except ValueError:
            # F8: a corrupt program row cannot be dereferenced — refuse the
            # link with a domain error, never a raw parse traceback (the same
            # fail-closed discipline as the dispatch-path F5 fix).
            raise RequirementSatisfactionError(
                f"research_program:{program_id!r} row is corrupt and cannot "
                f"be dereferenced — satisfaction link refused (IDR-038 "
                f"§3.1 rule 2)") from None

        # 2. The requirement must dereference within that program.
        requirement = None
        for req in program.get("evidence_requirements") or []:
            if isinstance(req, dict) and req.get("claim_ref") == requirement_ref:
                requirement = req
                break
        if requirement is None:
            raise RequirementSatisfactionError(
                f"requirement_ref {requirement_ref!r} does not dereference to "
                f"an evidence requirement of research_program:{program_id!r} "
                f"(IDR-038 §3.1 rule 2)")
        required_classes = requirement.get("required_artifacts") or []

        # 3. The artifact must exist and belong to the project.
        art = self._conn.execute(
            "SELECT * FROM artifacts WHERE artifact_id = ?",
            (artifact_id,),
        ).fetchone()
        if art is None or art["project_id"] != project_id:
            raise RequirementSatisfactionError(
                f"artifact {artifact_id!r} does not exist in project "
                f"{project_id!r} (IDR-038 §3.1 rule 3)")

        # 4. The artifact class must be one the requirement actually requires.
        if art["artifact_type"] not in required_classes:
            raise RequirementSatisfactionError(
                f"artifact {artifact_id!r} is of type {art['artifact_type']!r} "
                f"which is not among the required classes of requirement "
                f"{requirement_ref!r} in research_program:{program_id!r} — a "
                f"link can never claim a class the requirement does not "
                f"require (IDR-038 §3.1 rule 4)")

        # 5. The artifact must carry a dereferenceable PASS validation
        #    verdict whose input-hash covers the artifact's content hash
        #    (M1 / HR-02: a bare artifact class can never satisfy a
        #    requirement — content validation gates the ladder). Re-verified
        #    at write time against the artifact row (F2: never trust a
        #    stored field).
        verdict = self._conn.execute(
            """SELECT 1 FROM validation_verdicts v
               JOIN artifacts a ON a.artifact_id = v.artifact_id
               WHERE v.project_id = ? AND v.artifact_id = ?
                 AND v.verdict = 'PASS'
                 AND v.input_hash = a.content_hash""",
            (project_id, artifact_id),
        ).fetchone()
        if verdict is None:
            raise RequirementSatisfactionError(
                f"artifact {artifact_id!r} carries no dereferenceable PASS "
                f"validation verdict covering its content — a satisfaction "
                f"link requires a content-validation verdict (M1, IDR-038 "
                f"§3.1 rule 5)")

        # 6. Idempotent: an existing triple returns the existing row.
        existing = self._conn.execute(
            "SELECT * FROM program_requirement_satisfactions "
            "WHERE program_id = ? AND requirement_ref = ? AND artifact_id = ?",
            (program_id, requirement_ref, artifact_id),
        ).fetchone()
        if existing is not None:
            return dict(existing)

        satisfaction_id = satisfaction_id_of(
            program_id, requirement_ref, artifact_id)
        ts = self._clock()
        self._conn.execute(
            """INSERT INTO program_requirement_satisfactions
               (satisfaction_id, project_id, program_id, requirement_ref,
                artifact_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (satisfaction_id, project_id, program_id, requirement_ref,
             artifact_id, ts),
        )
        return {
            "satisfaction_id": satisfaction_id,
            "project_id": project_id,
            "program_id": program_id,
            "requirement_ref": requirement_ref,
            "artifact_id": artifact_id,
            "created_at": ts,
        }

    # ── read helpers (the Q-02 derivation context) ──

    def satisfaction_types_by_requirement(
        self, project_id: str,
    ) -> dict[str, dict[str, frozenset[str]]]:
        """``{program_id: {requirement_ref: frozenset(artifact_types)}}`` —
        the per-requirement satisfaction facts the Q-02 derivation and the
        Evidence Ladder consume (IDR-038 §3; M1/HR-02). Recomputed from the
        rows + artifact types + verdict coverage; no stored derived field is
        ever trusted. Only VERDICT-COVERED classes are reported: a linked
        artifact whose content carries no PASS validation verdict (or whose
        verdict's input-hash no longer matches the artifact's content hash)
        contributes nothing — ``derive_obligation_rung`` refuses classes
        lacking verdicts by construction.
        """
        rows = self._conn.execute(
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
        out: dict[str, dict[str, frozenset[str]]] = {}
        for r in rows:
            per_req = out.setdefault(r["program_id"], {})
            per_req.setdefault(r["requirement_ref"], set()).add(  # type: ignore[attr-defined]
                r["artifact_type"])
        return {pid: {ref: frozenset(types)
                      for ref, types in per_req.items()}
                for pid, per_req in out.items()}
