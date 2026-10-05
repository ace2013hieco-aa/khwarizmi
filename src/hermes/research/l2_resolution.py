"""S5 L2 upstream-reference resolution — INTERNAL (S-3 extraction).

The read-path normalization half of the ratified S5 L2 design gate (verdict
"Option B"): every stored ``provenance_edges`` upstream reference form is
resolved to canonical ``artifacts.artifact_id`` identities so the S5
retraction cone can match on true artifact identity. Stored representations
are NEVER rewritten.

Extraction boundary (authorizing gate: DG-3B §18/§19, the L2 upstream-reference
resolution family, ``gateway.py:950-1103``): this module owns exactly that
family. It is an internal implementation detail — no ``__all__``, not exported
from the package, no public contract — and its single production caller is
``gateway._validate_retract_source``.

Hard properties (pinned by ``tests/test_s5_l2_resolution.py``):

* opens no transaction — no ``BEGIN`` / ``COMMIT`` / ``ROLLBACK``;
* performs no writes — every statement issued is a ``SELECT``;
* raises no refusal — malformed input never raises; unresolved values resolve
  to the empty set (or ``None`` per the single-row lookup);
* authors no identity — it consumes identifiers only: no hashing, no
  canonicalization, no UUID/clock/provider access;
* project isolation is enforced by the caller/emission layer: resolution is
  global-by-key by design, and the caller's project-scoped downstream JOIN is
  what keeps a foreign-project row out of the emitted cone.
"""
from __future__ import annotations

from typing import Any

# ── L2 upstream resolution (S5 read-path normalization, ratified S5 L2
# design gate — Option B). ──
#
# ``provenance_edges`` stores dependency references in the producers'
# durable forms: bare ``artifacts.artifact_id`` values, typed
# ``<artifact_type>:<content_hash>`` references (the ratified durable
# citation form — source/classification/binding/evidence refs), and bare
# ``tasks.task_id`` values (production lineage links). The S5 cone
# traversal operates on canonical artifact identity, so every stored
# upstream value is resolved to a set of bare ``artifacts.artifact_id``
# identities before BFS matching. Stored representations are NEVER
# rewritten (no migration, no writer changes); resolution is a pure,
# deterministic function of committed state.
#
# Precedence is fixed: (1) existing artifact row, (2) recognized typed
# reference, (3) task-hop, (4) otherwise unresolved (empty set).
# Project isolation is enforced at EMISSION by the cone query's existing
# project-scoped downstream JOIN (resolved values only ever serve as
# match keys against the seed set — a resolved upstream can never pull
# a foreign-project row into the emitted cone).

# Typed prefixes that denote artifact rows resolvable by content hash
# (the design-gate census forms, plus ``source_fetch_outcome`` completing
# the ratified SOURCE_ARTIFACT_TYPES taxonomy; the ``evidence:`` form
# carries a bare artifact id instead of a hash and is handled separately).
_L2_HASH_TYPED_PREFIXES = frozenset({
    "source_result",
    "source_payload",
    "source_search",
    "source_fetch_outcome",
    "failure_classification",
    "feature_binding",
})


def _l2_lookup_artifact_by_hash(conn: Any, content_hash: str,
                                artifact_type: str) -> str | None:
    """One artifact row by content identity (content_hash is UNIQUE, so at
    most one row exists globally; the ``created_at LIMIT 1`` mirrors the
    ``_s5_source_artifact_id`` deterministic-selection idiom)."""
    if not isinstance(content_hash, str) or not content_hash:
        return None
    row = conn.execute(
        "SELECT artifact_id FROM artifacts "
        "WHERE content_hash = ? AND artifact_type = ? "
        "ORDER BY created_at LIMIT 1",
        (content_hash, artifact_type)).fetchone()
    return row["artifact_id"] if row is not None else None


def _l2_resolve_ref_to_artifacts(conn: Any, value: Any) -> set[str]:
    """Rules 1+2: bare artifact identity, then recognized typed forms.

    Returns a set of canonical ``artifacts.artifact_id`` values (empty
    when unresolvable). Exact matching only — no prefix guessing, no
    truncation, no fuzzy matching. Never raises on malformed input.
    """
    if not isinstance(value, str) or not value:
        return set()
    row = conn.execute(
        "SELECT 1 FROM artifacts WHERE artifact_id = ?",
        (value,)).fetchone()
    if row is not None:
        return {value}
    prefix, sep, rest = value.partition(":")
    if not sep or not prefix or not rest:
        return set()
    if prefix == "evidence":
        # The ``evidence:`` form carries a bare artifact id (the
        # EVIDENCE_TRANSITION ``evidence_artifact_ref`` convention).
        bare = conn.execute(
            "SELECT artifact_id FROM artifacts WHERE artifact_id = ?",
            (rest,)).fetchone()
        return {bare["artifact_id"]} if bare is not None else set()
    if prefix in _L2_HASH_TYPED_PREFIXES:
        found = _l2_lookup_artifact_by_hash(conn, rest, prefix)
        return {found} if found is not None else set()
    return set()


def _l2_task_spec_refs(conn: Any, task_id: str) -> tuple[list[str], bool]:
    """The typed input references a task was admitted with
    (``spec.source_refs`` list + ``spec.source_ref`` singular). Returns
    ``(refs, ok)`` — ``ok`` is False when the task is missing or its
    spec is unparseable (fail-safe: resolve to nothing)."""
    row = conn.execute(
        "SELECT spec_json FROM tasks WHERE task_id = ?",
        (task_id,)).fetchone()
    if row is None:
        return [], False
    import json as _json
    try:
        spec = _json.loads(row["spec_json"]) if row["spec_json"] else {}
    except ValueError:
        return [], False
    if not isinstance(spec, dict):
        return [], False
    refs: list[str] = []
    multi = spec.get("source_refs")
    if isinstance(multi, list):
        refs.extend(r for r in multi if isinstance(r, str))
    single = spec.get("source_ref")
    if isinstance(single, str):
        refs.append(single)
    return refs, True


def _l2_task_outputs(conn: Any, task_id: str) -> set[str]:
    """Artifact identities actually produced by a task
    (``artifacts.task_id`` relationship)."""
    rows = conn.execute(
        "SELECT artifact_id FROM artifacts WHERE task_id = ?",
        (task_id,)).fetchall()
    return {r["artifact_id"] for r in rows}


def _l2_resolve_upstream(conn: Any, value: Any, edge_type: str,
                         _memo: dict | None = None) -> set[str]:
    """Rules 1–4 with fixed precedence (S5 L2 contract §4–§8).

    ``edge_type`` selects the task-hop semantics: ``derived_from`` →
    task INPUTS, ``used_as_input`` → task OUTPUTS, ``cites`` → both.
    Results are memoized per ``(value, edge_type)`` within a traversal
    (the bounded visited-task mechanism — each task expands at most
    once, and task-hop is single-level: spec refs resolve through
    rules 1+2 only, never into nested task-hops, so unbounded
    expansion is structurally impossible).
    """
    if _memo is None:
        _memo = {}
    key = (value, edge_type)
    if key in _memo:
        return set(_memo[key])
    # Rules 1+2 first (artifact identity wins over any task reading).
    resolved = _l2_resolve_ref_to_artifacts(conn, value)
    if not resolved and isinstance(value, str) and value:
        task = conn.execute(
            "SELECT 1 FROM tasks WHERE task_id = ?", (value,)).fetchone()
        if task is not None:
            if edge_type == "derived_from":
                refs, ok = _l2_task_spec_refs(conn, value)
                if ok:
                    for ref in refs:
                        resolved |= _l2_resolve_ref_to_artifacts(conn, ref)
            elif edge_type == "used_as_input":
                resolved |= _l2_task_outputs(conn, value)
            elif edge_type == "cites":
                refs, ok = _l2_task_spec_refs(conn, value)
                if ok:
                    for ref in refs:
                        resolved |= _l2_resolve_ref_to_artifacts(conn, ref)
                resolved |= _l2_task_outputs(conn, value)
    _memo[key] = resolved
    return set(resolved)
