"""CHG-1 — contradiction lifecycle pure substrate.

A contradiction is a relation between exactly two admitted classification
artifacts (``CLASSIFICATION_CONFLICT``): same project, program, and
hypothesis, different failure classes, both digest-valid, neither
invalidated, with non-empty resolved evidence overlap. Nothing else is
asserted — not source disagreement, not model disagreement as such
(each model's output is admitted as a classification; the detector sees
only the classifications), not uncertainty, staleness, or supersession.

This module is pure: no SQL, no persistence imports, no LLM input — the
gateway owns admission and the repository owns reads (the
evidence_ladder.py / feature_binding.py contract).

Identity (ratified §6)::

    contradiction_id = "cx_" + sha256(json.dumps({
        "schema_version": 1,
        "type": "CLASSIFICATION_CONFLICT",
        "party_a": <lesser artifact_id>,
        "party_b": <greater artifact_id>,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:24]

Parties are canonically ordered (unordered pair by construction).
Evidence overlap and detector version are provenance, NOT identity: the
same logical contradiction keeps its ID across overlap refinements and
detector upgrades.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

__all__ = [
    "CONTRADICTION_DETECTOR_VERSION",
    "CONTRADICTION_SCHEMA_VERSION",
    "CONTRADICTION_TYPE_CLASSIFICATION_CONFLICT",
    "ContradictionError",
    "canonical_pair",
    "contradiction_id_of",
    "detect_classification_conflicts",
]

CONTRADICTION_SCHEMA_VERSION = 1

CONTRADICTION_TYPE_CLASSIFICATION_CONFLICT = "CLASSIFICATION_CONFLICT"

# Detector version: pinned per contradiction row for replay audit. A
# detector change that alters the pair-selection rule MUST bump this;
# identity is unaffected (version is provenance, not identity).
CONTRADICTION_DETECTOR_VERSION = "cx-detect-v1"


class ContradictionError(ValueError):
    """A contradiction candidate fails the closed CHG-1 contract —
    fail-closed, nothing derived from it."""


def canonical_pair(first: object, second: object) -> tuple[str, str]:
    """Lexicographically ordered party pair (unordered by construction).

    Raises ``ContradictionError`` on non-string, empty, or identical
    parties (self-contradiction is malformed, never recorded).
    """
    if not isinstance(first, str) or not first:
        raise ContradictionError("party_a must be a non-empty string")
    if not isinstance(second, str) or not second:
        raise ContradictionError("party_b must be a non-empty string")
    if first == second:
        raise ContradictionError("a classification cannot contradict itself")
    return (first, second) if first < second else (second, first)


def contradiction_id_of(party_a: object, party_b: object,
                        kind: str = CONTRADICTION_TYPE_CLASSIFICATION_CONFLICT,
                        ) -> str:
    """Deterministic contradiction identity over the canonical pair."""
    if kind != CONTRADICTION_TYPE_CLASSIFICATION_CONFLICT:
        raise ContradictionError(f"unknown contradiction type {kind!r}")
    ordered = canonical_pair(party_a, party_b)
    raw = json.dumps(
        {"schema_version": CONTRADICTION_SCHEMA_VERSION,
         "type": kind,
         "party_a": ordered[0],
         "party_b": ordered[1]},
        sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "cx_" + hashlib.sha256(raw).hexdigest()[:24]


def _overlap(left: Mapping[str, Any], right: Mapping[str, Any]) -> list[str]:
    """Sorted shared resolved evidence artifact IDs of two rows.

    Each row carries ``evidence`` as an iterable of bare artifact IDs
    (resolution happens at the admission boundary, never here).
    """
    try:
        lset = set(left["evidence"])
        rset = set(right["evidence"])
    except (KeyError, TypeError) as exc:
        raise ContradictionError(
            f"candidate rows must carry evidence sets: {exc}") from None
    return sorted(a for a in (lset & rset) if isinstance(a, str) and a)


def detect_classification_conflicts(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Pure CLASSIFICATION_CONFLICT detector over candidate rows.

    Each row: ``{artifact_id, project_id, program_ref, hypothesis_ref,
    failure_class, evidence: <iterable of bare artifact IDs>,
    invalidated: bool}``. Rows already filtered to digest-valid,
    admitted classifications by the caller; this function applies the
    pair rule only: same project/program/hypothesis, different
    failure_class, neither invalidated, non-empty evidence overlap.

    Returns deterministically-ordered candidate dicts
    ``{type, party_a, party_b, contradiction_id, evidence_overlap}``
    sorted by ``contradiction_id``. No I/O, no clock, no randomness:
    identical inputs always yield identical outputs. Detector failure
    modes belong to the caller (a crash here means no assertion —
    absence of a record is never evidence of absence).
    """
    by_group: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        try:
            key = (str(row["project_id"]), str(row["program_ref"]),
                   str(row["hypothesis_ref"]))
            if row.get("invalidated"):
                continue
            if not row.get("artifact_id") or not row.get("failure_class"):
                continue
        except (KeyError, TypeError) as exc:
            raise ContradictionError(
                f"candidate row is malformed: {exc}") from None
        by_group.setdefault(key, []).append(row)
    found: dict[str, dict[str, Any]] = {}
    for members in by_group.values():
        ordered = sorted(m["artifact_id"] for m in members
                         if isinstance(m.get("artifact_id"), str))
        for i in range(len(ordered)):
            for j in range(i + 1, len(ordered)):
                left = next(m for m in members
                            if m["artifact_id"] == ordered[i])
                right = next(m for m in members
                             if m["artifact_id"] == ordered[j])
                if left["failure_class"] == right["failure_class"]:
                    continue
                overlap = _overlap(left, right)
                if not overlap:
                    continue
                cid = contradiction_id_of(ordered[i], ordered[j])
                if cid not in found:
                    found[cid] = {
                        "type": CONTRADICTION_TYPE_CLASSIFICATION_CONFLICT,
                        "party_a": ordered[i],
                        "party_b": ordered[j],
                        "contradiction_id": cid,
                        "evidence_overlap": overlap,
                    }
    return [found[k] for k in sorted(found)]
