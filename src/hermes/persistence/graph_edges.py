"""GR3 v0 typed-edge extraction — the write boundary (P1b, IDR-043 reserved).

``GraphEdgeRepository.record`` persists one citing document's validated
``cites`` edges (admitted-corpus-artifact → admitted-corpus-artifact)
with §14 edge rows — atomically, task-bound, idempotent:

- Accepts ONLY ``ADMITTED`` validation results (there is no write path
  for unvalidated extraction — the IDR-026 Decision 2.1 discipline);
  the extractor version must match, else refusal.
- Re-derives the citing identity from the BYTES (sha256 must equal the
  result's citing hash) and binds every endpoint to its ADMITTED row:
  each content hash must resolve in-project via the certified
  ``_source_artifact_resolves`` predicate AND its row metadata
  ``corpus_ref`` must equal the claimed ref (anti-substitution: a
  caller-supplied ref→hash map is untrusted input, verified here).
- In-transaction task binding (exists / same project / ``TOOL_TASK`` /
  ``gr3_extract`` template marker / RUNNING / ``spec.corpus_ref``
  equality) so the status read is atomic with the write.
- Additive idempotency (no one-shot — see below): the prepared triple
  set vs the existing triples from the citing artifact — all present
  → IDENTICAL, else the missing triples insert. Edited documents are
  new content hashes (new nodes), so staleness is impossible by
  construction and history is never rewritten. Inserted vs reused
  counts are precise (per-statement rowcounts — the P1a O1 polish,
  fixed here).
- Triples commit in ONE transaction; any failure rolls back to zero
  partial state. No event is emitted (the audit is the edge rows +
  the producing task's existing events).

Agreement constants are deliberately duplicated from
``hermes.research.graph_edges`` (the EXTRACT triplication precedent)
and pinned byte-identical by ``tests/test_gr3_edges.py``. This module
imports nothing from ``hermes.research`` (DG-5); the resolver import
is intra-persistence (the ``repositories.py:51`` precedent).

Transaction census note: this ``record`` is a new persistence
acquisition owner (``BEGIN IMMEDIATE``) — persistence 17 → 18 owners,
same certified structure (pre-tx pure validation, in-tx binding
re-check, single commit, rollback on any error).
"""
from __future__ import annotations

import hashlib
import sqlite3
from typing import Any, Mapping

from hermes.core import Clock, utc_now
from hermes.core.task_status import TaskStatus
from hermes.persistence.source_outcomes import _source_artifact_resolves

__all__ = [
    "GR3_EDGE_SCHEMA_VERSION",
    "GR3_EDGE_TYPES",
    "GR3_EXTRACTOR_VERSION",
    "GR3_EXTRACT_TEMPLATE",
    "GR3_TEMPLATE_VERSION",
    "GraphEdgeBindingError",
    "GraphEdgeError",
    "GraphEdgeIntegrityError",
    "GraphEdgeRepository",
]

#: Agreement with hermes.research.graph_edges (byte-identical by test).
GR3_EDGE_SCHEMA_VERSION = "1"
GR3_EXTRACTOR_VERSION = "1"
GR3_EXTRACT_TEMPLATE = "gr3_extract"
GR3_TEMPLATE_VERSION = "1"
GR3_EDGE_TYPES = frozenset({"cites"})

#: Closed result keys (EC-F01 style).
_RESULT_KEYS = frozenset({
    "verdict", "citing_ref", "citing_hash", "extractor_version",
    "edges", "skipped", "errors",
})

#: Closed per-edge keys.
_EDGE_KEYS = frozenset({"citing_ref", "cited_ref", "edge_type"})


class GraphEdgeError(Exception):
    """Base error for the GR3 edge write path (fail-closed: nothing
    written on any subclass)."""


class GraphEdgeBindingError(GraphEdgeError):
    """The extraction batch is not bound to its producing task (task
    exists, project match, TOOL_TASK, template marker, RUNNING, spec
    ref match) — no write."""


class GraphEdgeIntegrityError(GraphEdgeError):
    """The result is not ADMITTED, the extractor version mismatches,
    an endpoint does not resolve to its admitted row in-project, or a
    caller-supplied identity does not re-derive — fail-closed, nothing
    written."""


class GraphEdgeRepository:
    """The ONE GR3 edge write boundary (P1b).

    ``record`` takes an ``ADMITTED`` validation result plus the citing
    bytes plus the caller-observed ref→hash map, re-derives and
    re-resolves everything inside one transaction, and inserts the
    missing ``cites`` triples. The controller owns task transitions
    (this method never touches task status).
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        clock: Clock | None = None,
    ) -> None:
        from hermes.persistence.repositories import _json_loads
        self._conn = conn
        self._clock = clock or utc_now
        self._json_loads = _json_loads

    # ── public write boundary ──

    def record(
        self,
        project_id: str,
        task_id: str,
        result: Mapping[str, Any],
        citing_bytes: bytes,
        cited_hashes: Mapping[str, str],
    ) -> dict[str, Any]:
        """Persist one citing document's validated cites edges.

        Raises ``GraphEdgeBindingError`` (task binding),
        ``GraphEdgeIntegrityError`` (verdict/version/endpoint/identity).
        Returns a summary dict with precise inserted/reused counts.

        No producer stamp exists on ``provenance_edges`` (fixed schema)
        — the audit is the edge rows plus the producing task's existing
        events, so no ``produced_by`` parameter is accepted (no metadata
        smuggling surface).
        """
        batch = self._validate_result(result, cited_hashes)
        self._validate_citing_bytes(batch, citing_bytes)

        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._validate_task_binding(project_id, task_id, batch)
            self._validate_project(project_id)
            citing_id = self._resolve_endpoint(
                project_id, batch["citing_hash"], batch["citing_ref"],
                role="citing")
            triples: list[tuple[str, str, str]] = []
            for cited_ref, cited_hash in batch["cited"]:
                cited_id = self._resolve_endpoint(
                    project_id, cited_hash, cited_ref, role="cited")
                triples.append((citing_id, cited_id, "cites"))
            summary = self._commit(task_id, project_id, batch, triples)
            self._conn.execute("COMMIT")
            return summary
        except GraphEdgeError:
            self._conn.execute("ROLLBACK")
            raise
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    # ── pure validation (before the transaction) ──

    def _validate_result(
        self,
        result: Mapping[str, Any],
        cited_hashes: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Closed-schema result validation. The verdict gate is first:
        anything but ADMITTED has no write path."""
        if not isinstance(result, Mapping):
            raise GraphEdgeIntegrityError(
                f"gr3 result must be a mapping, "
                f"got {type(result).__name__}")
        unknown = sorted(set(result) - _RESULT_KEYS)
        if unknown:
            raise GraphEdgeIntegrityError(
                f"gr3 result: unknown keys {unknown} — the result "
                f"schema is closed")
        if result.get("verdict") != "ADMITTED":
            raise GraphEdgeIntegrityError(
                f"gr3 result verdict {result.get('verdict')!r} is not "
                f"ADMITTED — there is no write path for unvalidated "
                f"extraction")
        if result.get("extractor_version") != GR3_EXTRACTOR_VERSION:
            raise GraphEdgeIntegrityError(
                f"gr3 extractor_version "
                f"{result.get('extractor_version')!r} != supported "
                f"{GR3_EXTRACTOR_VERSION!r}")
        citing_ref = result.get("citing_ref")
        if not isinstance(citing_ref, str) or not citing_ref:
            raise GraphEdgeIntegrityError(
                f"citing_ref must be a non-empty string, "
                f"got {citing_ref!r}")
        citing_hash = result.get("citing_hash")
        self._require_hash(citing_hash, "citing_hash")
        raw_edges = result.get("edges", ())
        if not isinstance(raw_edges, (list, tuple)):
            raise GraphEdgeIntegrityError(
                f"edges must be a list, got {type(raw_edges).__name__}")
        if not isinstance(cited_hashes, Mapping):
            raise GraphEdgeIntegrityError(
                f"cited_hashes must be a mapping, "
                f"got {type(cited_hashes).__name__}")
        cited: list[tuple[str, str]] = []
        seen: set[str] = set()
        for i, raw in enumerate(raw_edges):
            if not isinstance(raw, Mapping):
                raise GraphEdgeIntegrityError(
                    f"edges[{i}] must be a mapping")
            unknown_e = sorted(set(raw) - _EDGE_KEYS)
            if unknown_e:
                raise GraphEdgeIntegrityError(
                    f"edges[{i}]: unknown keys {unknown_e}")
            if raw.get("citing_ref") != citing_ref:
                raise GraphEdgeIntegrityError(
                    f"edges[{i}]: citing_ref {raw.get('citing_ref')!r} "
                    f"!= batch citing {citing_ref!r}")
            cited_ref = raw.get("cited_ref")
            if not isinstance(cited_ref, str) or not cited_ref:
                raise GraphEdgeIntegrityError(
                    f"edges[{i}]: cited_ref must be a non-empty string")
            if cited_ref == citing_ref:
                raise GraphEdgeIntegrityError(
                    f"edges[{i}]: self-edge refused")
            if raw.get("edge_type") not in GR3_EDGE_TYPES:
                raise GraphEdgeIntegrityError(
                    f"edges[{i}]: edge_type {raw.get('edge_type')!r} "
                    f"outside v0 {sorted(GR3_EDGE_TYPES)}")
            cited_hash = self._require_hash(
                cited_hashes.get(cited_ref), f"cited_hash[{cited_ref!r}]")
            if cited_ref not in seen:
                seen.add(cited_ref)
                cited.append((cited_ref, cited_hash))
        return {
            "citing_ref": citing_ref,
            "citing_hash": citing_hash,
            "cited": cited,
        }

    @staticmethod
    def _require_hash(value: Any, name: str) -> str:
        if not isinstance(value, str) or len(value) != 64:
            raise GraphEdgeIntegrityError(
                f"{name} must be a 64-hex sha256 digest, got {value!r}")
        try:
            int(value, 16)
        except ValueError:
            raise GraphEdgeIntegrityError(
                f"{name} must be hexadecimal, got {value!r}") from None
        return value

    def _validate_citing_bytes(
        self, batch: Mapping[str, Any], citing_bytes: Any,
    ) -> None:
        """Re-derive the citing identity from the bytes."""
        if not isinstance(citing_bytes, (bytes, bytearray)):
            raise GraphEdgeIntegrityError(
                f"citing bytes must be bytes, "
                f"got {type(citing_bytes).__name__}")
        raw = bytes(citing_bytes)
        if not raw:
            raise GraphEdgeIntegrityError("citing bytes are empty")
        if hashlib.sha256(raw).hexdigest() != batch["citing_hash"]:
            raise GraphEdgeIntegrityError(
                "sha256(citing bytes) != result citing_hash — citing "
                "identity is derived, never authored")

    # ── in-transaction validation ──

    def _validate_task_binding(
        self,
        project_id: str,
        task_id: str,
        batch: Mapping[str, Any],
    ) -> None:
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,),
        ).fetchone()
        if row is None:
            raise GraphEdgeBindingError(
                f"gr3 batch refused: producing task {task_id!r} does "
                f"not exist")
        if row["project_id"] != project_id:
            raise GraphEdgeBindingError(
                f"gr3 batch refused: producing task {task_id!r} belongs "
                f"to project {row['project_id']!r}, not {project_id!r}")
        if row["task_type"] != "TOOL_TASK":
            raise GraphEdgeBindingError(
                f"gr3 batch refused: producing task {task_id!r} is "
                f"{row['task_type']}, not TOOL_TASK")
        spec = self._json_loads(row["spec_json"]) or {}
        template = spec.get("template")
        if (not isinstance(template, str)
                or template.strip().casefold()
                != GR3_EXTRACT_TEMPLATE):
            raise GraphEdgeBindingError(
                f"gr3 batch refused: producing task {task_id!r} is not "
                f"a {GR3_EXTRACT_TEMPLATE} task "
                f"(spec.template={template!r})")
        if row["status"] != TaskStatus.RUNNING.value:
            raise GraphEdgeBindingError(
                f"gr3 batch refused: producing task {task_id!r} is "
                f"{row['status']}, not RUNNING")
        if spec.get("corpus_ref") != batch["citing_ref"]:
            raise GraphEdgeBindingError(
                f"gr3 batch refused: task spec.corpus_ref "
                f"{spec.get('corpus_ref')!r} != batch citing "
                f"{batch['citing_ref']!r} — one task extracts exactly "
                f"one corpus document")

    def _validate_project(self, project_id: str) -> None:
        row = self._conn.execute(
            "SELECT 1 FROM projects WHERE project_id = ?", (project_id,),
        ).fetchone()
        if row is None:
            raise GraphEdgeBindingError(
                f"Project not found: {project_id!r} — gr3 edges are "
                f"project-scoped")

    def _resolve_endpoint(
        self,
        project_id: str,
        content_hash: str,
        claimed_ref: str,
        *,
        role: str,
    ) -> str:
        """Bind a content hash to its admitted artifact id in-project.

        Two independent checks: the certified edge-carried resolver
        (governance) AND the admitted row's metadata ``corpus_ref``
        (anti-substitution against the caller-supplied ref→hash map).
        A dangling or cross-project endpoint refuses the whole batch.
        """
        if not _source_artifact_resolves(
                self._conn, project_id, content_hash, "source_payload"):
            raise GraphEdgeIntegrityError(
                f"gr3 {role} endpoint {claimed_ref!r} "
                f"(source_payload:{content_hash[:12]}…) does not "
                f"resolve in project {project_id!r} — dangling and "
                f"cross-project endpoints refuse the batch")
        row = self._conn.execute(
            "SELECT artifact_id, metadata_json FROM artifacts "
            "WHERE content_hash = ? AND artifact_type = 'source_payload'",
            (content_hash,),
        ).fetchone()
        if row is None:  # pragma: no cover — resolver already failed
            raise GraphEdgeIntegrityError(
                f"gr3 {role} endpoint {claimed_ref!r}: no "
                f"source_payload row for the hash")
        try:
            meta = self._json_loads(row["metadata_json"]) or {}
        except ValueError:
            raise GraphEdgeIntegrityError(
                f"gr3 {role} endpoint {claimed_ref!r}: admitted row "
                f"metadata is corrupt") from None
        if meta.get("corpus_ref") != claimed_ref:
            raise GraphEdgeIntegrityError(
                f"gr3 {role} endpoint: admitted row metadata "
                f"corpus_ref {meta.get('corpus_ref')!r} != claimed "
                f"{claimed_ref!r} — ref→hash substitution refused")
        return row["artifact_id"]

    # ── the transactional commit (THE ONLY writer) ──

    def _commit(
        self,
        task_id: str,
        project_id: str,
        batch: Mapping[str, Any],
        triples: list[tuple[str, str, str]],
    ) -> dict[str, Any]:
        ts = self._clock()
        prepared = [(a, u) for a, u, _ in triples]
        existing: set[tuple[str, str]] = set()
        if prepared:
            existing = {
                (r["artifact_id"], r["upstream_id"])
                for r in self._conn.execute(
                    "SELECT artifact_id, upstream_id "
                    "FROM provenance_edges "
                    "WHERE artifact_id = ? AND edge_type = 'cites'",
                    (prepared[0][0],),
                ).fetchall()
            }
        missing = [t for t in prepared if t not in existing]
        inserted = 0
        for artifact_id, upstream_id in missing:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO provenance_edges "
                "(artifact_id, upstream_id, edge_type, created_at) "
                "VALUES (?, ?, ?, ?)",
                (artifact_id, upstream_id, "cites", ts),
            )
            inserted += cur.rowcount
        reused = len(prepared) - inserted
        triple_strs = sorted(f"{a}>{u}#cites" for a, u in prepared)
        if not prepared:
            decision = "EMPTY"
        elif not missing:
            decision = "IDENTICAL"
        else:
            decision = "NEW"
        return {
            "decision": decision,
            "task_id": task_id,
            "project_id": project_id,
            "citing_ref": batch["citing_ref"],
            "edges_prepared": len(prepared),
            "edges_written": inserted,
            "edges_reused": reused,
            "triples": triple_strs,
        }
