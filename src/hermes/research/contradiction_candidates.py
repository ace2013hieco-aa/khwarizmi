"""Detector candidate-row derivation (S-1 internal seam).

Moved verbatim from ``Controller`` (S-1 extraction): pure read-only
derivation of contradiction-detector candidate rows from recorded
classifications. No transactions, no leases, no journal, no
authority, no identity authoring, no provider calls.

The evidence resolver recognizes exactly six typed prefixes — ``evidence``,
``source_result``, ``source_payload``, ``source_search``,
``failure_classification``, ``feature_binding`` — plus the bare-ID row
check. Any other ref returns ``None`` and is silently dropped: no log, no
counter, no diagnostic key, no journal event. That is acceptable today
because admission
(``FailureClassificationRepository._verify_evidence_owned`` in
``src/hermes/persistence/failure_classifications.py``) admits only typed
refs reachable from the producing task by the two-hop ``derived_from``
check, so a ref kind this resolver does not recognize cannot reach a
persisted classification's evidence list. The drop is latent, not live.

The coupling is an obligation, not an enforcement: this prefix set must
stay a subset of what admission can produce. If admission is ever widened
to admit a new kind, this set must be widened in the same slice;
otherwise the drop becomes live and silent. Keeping the boundary true is
a reviewer obligation, not a property this module can enforce.

INTERNAL implementation location — not a supported public surface
(no ``__all__``; behavior is pinned by
``tests/test_s1_detector_rows.py`` through ``Controller``).
"""
from __future__ import annotations

from typing import Any

from hermes.persistence.source_outcomes import (
    source_artifact_is_web_derived,
    source_artifact_retracted,
)


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
        if row is None:
            return None
        # IDR-046 D2/E5 — the bare-id path has no type check at all, so
        # the web bar is explicit here too: web-derived rows contribute
        # nothing (fail-safe skip).
        if source_artifact_is_web_derived(conn, row["artifact_id"]):
            return None
        return row["artifact_id"]
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
    if row is None:
        return None
    # IDR-046 D2/E5 — the typed path: web-derived rows are barred from
    # the detector row's evidence (fail-safe skip, mirroring the gateway
    # basis derivation).
    if source_artifact_is_web_derived(conn, row["artifact_id"]):
        return None
    return row["artifact_id"]


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


def recorded_pair_keys(conn: Any, project_id: str) -> set[str]:
    """Recomputed pair identities of every recorded contradiction row
    in the project — the CHG-DEDUP-1 upstream-skip input (read-only
    advisory, the ``open_contradiction_parties`` precedent: no
    transaction, no lease, no journal, no identity authoring).

    Any-row predicate: a row in any status (OPEN / RESOLVED /
    SUPERSEDED) means the pair is already recorded, because an existing
    row takes the gateway's duplicate path unchanged (zero mutation)
    regardless of status — the resubmission only ever appended a fresh
    ``IntentApplied`` audit row per tick. Retraction-driven supersession
    retires a pair whose party is invalidated in the same transaction
    and no un-retract exists, so a superseded pair can never
    legitimately need re-recording.

    Content-hash discipline: the identity is recomputed from the stored
    parties (``contradiction_id_of``), never read from the
    ``contradiction_id`` column; a row that cannot be keyed is omitted
    and any candidate falling through is still gated fail-closed by the
    gateway. Project-scoped and delegated to the certified any-status
    read (``ContradictionRepository.all_entries``) — rows of other
    projects never suppress detection here and no new query is added;
    the read is a plain SELECT keyed on the project, so the row count
    is the project's recorded-contradiction count (EXT-6 bounds the
    OPEN portion; resolution/supersession retire the rest).
    """
    from hermes.persistence.repositories import ContradictionRepository
    from hermes.research.contradictions import (
        ContradictionError,
        contradiction_id_of,
    )

    keys: set[str] = set()
    for row in ContradictionRepository(conn).all_entries(project_id):
        try:
            keys.add(contradiction_id_of(row["party_a"], row["party_b"]))
        except ContradictionError:
            continue
    return keys
