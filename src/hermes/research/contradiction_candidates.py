"""Detector candidate-row derivation (S-1 internal seam).

Moved verbatim from ``Controller`` (S-1 extraction): pure read-only
derivation of contradiction-detector candidate rows from recorded
classifications. No transactions, no leases, no journal, no
authority, no identity authoring, no provider calls.

INTERNAL implementation location — not a supported public surface
(no ``__all__``; behavior is pinned by
``tests/test_s1_detector_rows.py`` through ``Controller``).
"""
from __future__ import annotations

from typing import Any

from hermes.persistence.source_outcomes import source_artifact_retracted


def detector_candidate_rows(
    conn: Any, project_id: str, digest_items: list,
) -> list[dict]:
    """Digest-valid classification rows for the detector pass.

    Each row: ``{artifact_id, project_id, program_ref,
    hypothesis_ref, failure_class, evidence (sorted bare artifact
    IDs), invalidated}``. Corrupt/unparseable classification rows
    are skipped (never crash the detector); evidence refs that do
    not resolve — or that resolve to currently retracted sources
    (N9) — contribute nothing (fail-safe, mirroring the
    gateway basis derivation).
    """
    import json as _json

    rows: list[dict] = []
    for item in digest_items:
        if not isinstance(item, dict) or item.get("integrity_flags"):
            continue
        classification_id = item.get("classification_id")
        if not isinstance(classification_id, str) or not classification_id:
            continue
        meta_row = conn.execute(
            "SELECT artifact_type, content_hash, metadata_json "
            "FROM artifacts WHERE artifact_id = ? AND project_id = ?",
            (classification_id, project_id)).fetchone()
        if meta_row is None:
            continue
        try:
            meta = _json.loads(meta_row["metadata_json"] or "{}")
        except ValueError:
            continue
        if not isinstance(meta, dict):
            continue
        if meta.get("classification_id") != classification_id:
            continue
        evidence: set[str] = set()
        refs = meta.get("evidence_refs")
        if isinstance(refs, list):
            for ref in refs:
                resolved = detector_resolve_ref(conn, project_id, ref)
                if resolved is None:
                    continue
                if source_artifact_retracted(conn, project_id, resolved):
                    continue
                evidence.add(resolved)
        rows.append({
            "artifact_id": classification_id,
            "project_id": project_id,
            "program_ref": meta.get("program_ref"),
            "hypothesis_ref": meta.get("hypothesis_ref"),
            "failure_class": meta.get("failure_class"),
            "evidence": sorted(evidence),
            "invalidated": (
                meta.get("invalidation_marker") == "INVALIDATED"),
        })
    return rows


def detector_resolve_ref(
    conn: Any, project_id: str, ref: object,
) -> str | None:
    """Resolve one evidence ref to a bare artifact ID (detector
    input derivation — typed recognized forms + bare-row check;
    unresolvable contributes nothing)."""
    if not isinstance(ref, str) or not ref:
        return None
    prefix, sep, rest = ref.partition(":")
    if not sep or not prefix or not rest:
        row = conn.execute(
            "SELECT artifact_id FROM artifacts "
            "WHERE artifact_id = ? AND project_id = ?",
            (ref, project_id)).fetchone()
        return row["artifact_id"] if row is not None else None
    # The ``evidence:`` form carries a content hash resolved against
    # type-``evidence`` rows (Step-7 basis convention).
    lookup_type = "evidence" if prefix == "evidence" else prefix
    if prefix not in ("evidence", "source_result", "source_payload",
                      "source_search", "failure_classification",
                      "feature_binding"):
        return None
    row = conn.execute(
        "SELECT artifact_id FROM artifacts "
        "WHERE project_id = ? AND content_hash = ? "
        "AND artifact_type = ? ORDER BY created_at LIMIT 1",
        (project_id, rest, lookup_type)).fetchone()
    return row["artifact_id"] if row is not None else None


def open_contradiction_parties(conn: Any, project_id: str) -> list[str]:
    """Sorted party artifact IDs of operationally active OPEN
    contradictions (read-only advisory input)."""
    from hermes.persistence.repositories import ContradictionRepository
    seen: set[str] = set()
    for row in ContradictionRepository(
            conn).open_contradictions(project_id):
        seen.add(row["party_a"])
        seen.add(row["party_b"])
    return sorted(seen)
