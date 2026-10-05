"""GR3 v0 corpus admission — the write boundary (P1a, IDR-042 reserved).

``CorpusRepository.record`` persists one closed-set corpus document as a
``source_payload`` artifact (bytes via the injected ``ArtifactStore``,
metadata row in ``artifacts``) with its §14 ``derived_from`` edge to the
admitting task — atomically, task-bound, idempotent:

- Pure validation BEFORE the transaction (closed draft schema, sha256
  re-derivation from the bytes, size-cap agreement) — identity is
  derived, never authored.
- In-transaction task binding (exists / same project / ``TOOL_TASK`` /
  ``corpus_admit`` template marker / RUNNING / ``spec.corpus_ref``
  equality) so the status read is atomic with the write (TOCTOU
  closure, the V6-P7-A2 discipline).
- One-shot acceptance per task (IDENTICAL reuses, DIVERGENT refuses);
  global content-hash reuse across tasks (edge-carried ownership).
- Rows + edge commit in ONE transaction; any failure rolls back to
  zero partial state. No event is emitted (the audit is the immutable
  row + edge + the producing task's existing events).

Agreement constants (template marker, cohort sets, size cap, schema
version) are deliberately duplicated from ``hermes.research.corpus``
— the EXTRACT vocabulary triplication precedent (admission and the
write path can never disagree) — and pinned byte-identical by
``tests/test_corpus_admission.py``. This module imports nothing from
``hermes.research`` (DG-5: no new persistence→research dependency).

Transaction census note: this ``record`` is a new persistence
acquisition owner (``BEGIN IMMEDIATE``), extending the certified
pattern — persistence 16 → 17 owners. It weakens nothing: same
structure as ``SourceOutcomeRepository.record`` (pre-tx pure
validation, in-tx binding re-check, single commit, rollback on any
error).
"""
from __future__ import annotations

import hashlib
import sqlite3
from typing import Any, Mapping

from hermes.core import Clock, utc_now
from hermes.core.task_status import TaskStatus

__all__ = [
    "CORPUS_ADMIT_TEMPLATE",
    "CORPUS_B4_COHORT_REFS",
    "CORPUS_MAX_BYTES",
    "CORPUS_REFS",
    "CORPUS_SCHEMA_VERSION",
    "CORPUS_TEMPLATE_VERSION",
    "GOVERNED_CORPUS_REFS",
    "CorpusBindingError",
    "CorpusConflictError",
    "CorpusError",
    "CorpusIntegrityError",
    "CorpusRepository",
]

#: Agreement with hermes.research.corpus (byte-identical by test).
CORPUS_SCHEMA_VERSION = "1"
CORPUS_ADMIT_TEMPLATE = "corpus_admit"
CORPUS_TEMPLATE_VERSION = "1"
CORPUS_MAX_BYTES = 20 * 1024
#: P1a cohort (IDR-042) — FROZEN; see the research layer for why.
CORPUS_REFS = frozenset({
    "AGENTS.md",
    "docs/API.md",
    "docs/ARCHITECTURE.md",
    "docs/STATE.md",
    "docs/idr/IDR-024.md",
    "docs/idr/IDR-028.md",
})
#: B4 reference cohort (GR3-P2-b4fixtures) — the real documents the P1a
#: six directly cite; admitted through this same boundary.
CORPUS_B4_COHORT_REFS = frozenset({
    "docs/idr/IDR-018.md",
    "docs/idr/IDR-023.md",
    "docs/idr/IDR-025.md",
    "docs/idr/IDR-026.md",
    "docs/idr/IDR-027.md",
    "docs/idr/IDR-036.md",
})
#: The governed allowlist this boundary enforces (union of the cohorts).
GOVERNED_CORPUS_REFS = CORPUS_REFS | CORPUS_B4_COHORT_REFS

#: Closed admission-draft keys (EC-F01 style).
_ADMISSION_KEYS = frozenset({"corpus_ref", "content_hash", "size_bytes"})


class CorpusError(Exception):
    """Base error for the corpus-admission write path (fail-closed:
    nothing written on any subclass)."""


class CorpusBindingError(CorpusError):
    """The admission is not bound to its producing task (task exists,
    project match, TOOL_TASK, template marker, RUNNING, spec ref
    match) — no write."""


class CorpusIntegrityError(CorpusError):
    """A caller-supplied identity (content_hash / size_bytes) does not
    match the canonical derivation from the bytes, the draft breaks the
    closed schema, or a reused persisted row fails re-verification —
    fail-closed, nothing written."""


class CorpusConflictError(CorpusError):
    """One-shot refusal: the producing task already admitted a
    DIFFERENT document. One task, one corpus document — a divergent
    re-admission is refused, never overwritten."""


class CorpusRepository:
    """The ONE corpus-admission write boundary (P1a).

    ``record`` validates the draft + bytes (pure, pre-transaction),
    then inside the write transaction re-checks the task binding, the
    project existence, and the one-shot (prior hash-SET by task vs the
    proposed SET — IDENTICAL reuses, DIVERGENT refuses, NEW inserts).
    Bytes + row + §14 edge commit in ONE transaction; the controller
    owns the RUNNING → SUCCEEDED/FAILED transition (this method never
    touches task status).
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        store: Any = None,
        clock: Clock | None = None,
    ) -> None:
        # Lazy: repositories.py must never import this module at its top
        # (no new upward/cycle surface); resolved here, inside __init__.
        from hermes.persistence.repositories import (
            ArtifactRepository,
            _json_loads,
        )
        self._conn = conn
        self._store = store
        self._clock = clock or utc_now
        self._artifacts = ArtifactRepository(conn, clock)
        self._json_loads = _json_loads

    # ── public write boundary ──

    def record(
        self,
        project_id: str,
        task_id: str,
        admission: Mapping[str, Any],
        content: bytes,
        *,
        produced_by: str = "",
    ) -> dict[str, Any]:
        """Persist one corpus document atomically (bytes + row + edge).

        Raises ``CorpusBindingError`` (task binding), ``CorpusIntegrityError``
        (closed schema / identity re-derivation / persisted-row
        re-verification), ``CorpusConflictError`` (one-shot divergent
        refusal). Returns a summary dict.
        """
        draft = self._validate_draft(admission)
        self._validate_content(draft, content)

        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._validate_task_binding(project_id, task_id, draft)
            self._validate_project(project_id)
            decision = self._resolve_idempotency(task_id, draft)
            summary = self._commit(
                project_id, task_id, draft, content,
                produced_by or f"task:{task_id}", decision)
            self._conn.execute("COMMIT")
            return summary
        except CorpusError:
            self._conn.execute("ROLLBACK")
            raise
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    # ── pure validation (before the transaction) ──

    def _validate_draft(
        self, admission: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Closed-schema draft validation (re-derived here so the write
        path never trusts the research layer's word for it)."""
        if not isinstance(admission, Mapping):
            raise CorpusIntegrityError(
                f"corpus admission must be a mapping, "
                f"got {type(admission).__name__}")
        unknown = sorted(set(admission) - _ADMISSION_KEYS)
        if unknown:
            raise CorpusIntegrityError(
                f"corpus admission: unknown keys {unknown} — the "
                f"admission schema is closed")
        corpus_ref = admission.get("corpus_ref")
        if not isinstance(corpus_ref, str) or not corpus_ref:
            raise CorpusIntegrityError(
                f"corpus_ref must be a non-empty string, "
                f"got {corpus_ref!r}")
        if corpus_ref not in GOVERNED_CORPUS_REFS:
            raise CorpusIntegrityError(
                f"corpus_ref {corpus_ref!r} is not in the governed "
                f"corpus — unlisted documents are refused")
        content_hash = admission.get("content_hash")
        if (not isinstance(content_hash, str)
                or len(content_hash) != 64):
            raise CorpusIntegrityError(
                f"content_hash must be a 64-hex sha256 digest, "
                f"got {content_hash!r}")
        try:
            int(content_hash, 16)
        except ValueError:
            raise CorpusIntegrityError(
                f"content_hash must be hexadecimal, "
                f"got {content_hash!r}") from None
        size_bytes = admission.get("size_bytes")
        if (not isinstance(size_bytes, int)
                or isinstance(size_bytes, bool) or size_bytes <= 0):
            raise CorpusIntegrityError(
                f"size_bytes must be a positive int, got {size_bytes!r}")
        if size_bytes > CORPUS_MAX_BYTES:
            raise CorpusIntegrityError(
                f"size_bytes {size_bytes} exceeds the corpus cap "
                f"{CORPUS_MAX_BYTES}")
        return {
            "corpus_ref": corpus_ref,
            "content_hash": content_hash,
            "size_bytes": size_bytes,
        }

    def _validate_content(
        self, draft: Mapping[str, Any], content: Any,
    ) -> None:
        """Re-derive identity from the bytes (ADV-01/06 discipline)."""
        if not isinstance(content, (bytes, bytearray)):
            raise CorpusIntegrityError(
                f"corpus content must be bytes, "
                f"got {type(content).__name__}")
        raw = bytes(content)
        if not raw:
            raise CorpusIntegrityError(
                "corpus content is empty — nothing to admit")
        if len(raw) != draft["size_bytes"]:
            raise CorpusIntegrityError(
                f"corpus size_bytes {draft['size_bytes']!r} does not "
                f"match len(content) {len(raw)} — identity is derived")
        derived = hashlib.sha256(raw).hexdigest()
        if derived != draft["content_hash"]:
            raise CorpusIntegrityError(
                f"sha256(content) {derived!r} != draft content_hash "
                f"{draft['content_hash']!r} — content identity is "
                f"derived, never authored")

    # ── in-transaction validation ──

    def _validate_task_binding(
        self,
        project_id: str,
        task_id: str,
        draft: Mapping[str, Any],
    ) -> None:
        """Task exists / same project / TOOL_TASK / corpus_admit marker /
        RUNNING / spec.corpus_ref equality — checked INSIDE the write
        transaction so the status read is atomic with the write."""
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,),
        ).fetchone()
        if row is None:
            raise CorpusBindingError(
                f"corpus admission refused: producing task {task_id!r} "
                f"does not exist")
        if row["project_id"] != project_id:
            raise CorpusBindingError(
                f"corpus admission refused: producing task {task_id!r} "
                f"belongs to project {row['project_id']!r}, not "
                f"{project_id!r}")
        if row["task_type"] != "TOOL_TASK":
            raise CorpusBindingError(
                f"corpus admission refused: producing task {task_id!r} "
                f"is {row['task_type']}, not TOOL_TASK — corpus bytes "
                f"are read deterministically, never model-judged")
        spec = self._json_loads(row["spec_json"]) or {}
        template = spec.get("template")
        if (not isinstance(template, str)
                or template.strip().casefold()
                != CORPUS_ADMIT_TEMPLATE):
            raise CorpusBindingError(
                f"corpus admission refused: producing task {task_id!r} "
                f"is not a {CORPUS_ADMIT_TEMPLATE} task "
                f"(spec.template={template!r})")
        if row["status"] != TaskStatus.RUNNING.value:
            raise CorpusBindingError(
                f"corpus admission refused: producing task {task_id!r} "
                f"is {row['status']}, not RUNNING — output may only be "
                f"accepted from a task currently executing")
        if spec.get("corpus_ref") != draft["corpus_ref"]:
            raise CorpusBindingError(
                f"corpus admission refused: producing task {task_id!r} "
                f"spec.corpus_ref {spec.get('corpus_ref')!r} does not "
                f"match the admission's {draft['corpus_ref']!r} — one "
                f"task admits exactly one corpus document")

    def _validate_project(self, project_id: str) -> None:
        row = self._conn.execute(
            "SELECT 1 FROM projects WHERE project_id = ?", (project_id,),
        ).fetchone()
        if row is None:
            raise CorpusBindingError(
                f"Project not found: {project_id!r} — corpus admissions "
                f"are project-scoped artifacts")

    def _resolve_idempotency(
        self, task_id: str, draft: Mapping[str, Any],
    ) -> str:
        """One-shot per task: prior source_payload hashes BY TASK vs the
        proposed SET. EQUAL → IDENTICAL (retry reuse); DIFFERENT →
        DIVERGENT (refusal); none → NEW."""
        prior = self._conn.execute(
            "SELECT content_hash FROM artifacts WHERE task_id = ? "
            "AND artifact_type = 'source_payload'",
            (task_id,),
        ).fetchall()
        if not prior:
            return "NEW"
        existing = {r["content_hash"] for r in prior}
        if existing == {draft["content_hash"]}:
            return "IDENTICAL"
        return "DIVERGENT"

    # ── the transactional commit (THE ONLY writer) ──

    def _commit(
        self,
        project_id: str,
        task_id: str,
        draft: Mapping[str, Any],
        content: bytes,
        produced_by: str,
        decision: str,
    ) -> dict[str, Any]:
        if decision == "DIVERGENT":
            raise CorpusConflictError(
                f"corpus admission refused: task {task_id!r} already "
                f"admitted a different document — one task, one corpus "
                f"document; identical re-admission is idempotent, "
                f"divergent admission is not")
        if self._store is None:
            raise CorpusError(
                "corpus admission refused: no artifact store wired — "
                "content bytes must persist with the admission")
        ts = self._clock()
        # Global content-hash reuse (SD-04 analog): the bytes are
        # content-addressed, so a document admitted before — by any
        # task — resolves to the same row; the edge below carries the
        # new task's ownership. Classified precisely: only a row this
        # commit inserts counts as written.
        preexisting = self._artifacts.get_by_hash(draft["content_hash"])
        row = self._store.write(
            bytes(content),
            artifact_type="source_payload",
            producer=produced_by,
            project_id=project_id,
            task_id=task_id,
            metadata={
                "corpus_ref": draft["corpus_ref"],
                "corpus_schema_version": CORPUS_SCHEMA_VERSION,
                "admitted_by": task_id,
            },
        )
        # R02 analog (final-review type discipline): the store dedups by
        # hash only — an existing row with the same content hash but a
        # DIFFERENT artifact type must never stand in for a
        # source_payload.
        if row["artifact_type"] != "source_payload":
            raise CorpusIntegrityError(
                f"corpus {draft['corpus_ref']!r}: content hash "
                f"{row['content_hash']!r} already exists as a "
                f"{row['artifact_type']} row — same hash, different "
                f"artifact type is refused, never reused as a payload")
        if row["content_hash"] != draft["content_hash"]:
            raise CorpusIntegrityError(
                f"corpus {draft['corpus_ref']!r}: store returned "
                f"content_hash {row['content_hash']!r} != "
                f"{draft['content_hash']!r}")
        reused = preexisting is not None
        self._conn.execute(
            "INSERT OR IGNORE INTO provenance_edges "
            "(artifact_id, upstream_id, edge_type, created_at) "
            "VALUES (?, ?, ?, ?)",
            (row["artifact_id"], task_id, "derived_from", ts),
        )
        return {
            "decision": decision,
            "task_id": task_id,
            "project_id": project_id,
            "corpus_ref": draft["corpus_ref"],
            "content_hash": draft["content_hash"],
            "artifact_id": row["artifact_id"],
            "artifacts_written": [] if reused else [row["artifact_id"]],
            "artifacts_reused": [row["artifact_id"]] if reused else [],
            "edges": 1,
        }
