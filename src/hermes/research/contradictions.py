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
from typing import Any, Iterator, Mapping, Sequence

__all__ = [
    "CONTRADICTION_DETECTOR_VERSION",
    "CONTRADICTION_SCHEMA_VERSION",
    "CONTRADICTION_TYPE_CLASSIFICATION_CONFLICT",
    "DEFAULT_MAX_PAIRS",
    "DETECTOR_TRUNCATED",
    "ContradictionError",
    "canonical_pair",
    "contradiction_id_of",
    "detect_classification_conflicts",
]

CONTRADICTION_SCHEMA_VERSION = 1

CONTRADICTION_TYPE_CLASSIFICATION_CONFLICT = "CLASSIFICATION_CONFLICT"

# Upper bound on pairs emitted per detector pass. A group of n mutually
# conflicting classifications has n(n-1)/2 pairs; the cap keeps one
# pass's intent fan-out bounded. Exceeding it sets DETECTOR_TRUNCATED
# in the caller's diagnostics — never a silent partial result.
# The cap is shared across groups via round-robin (per-group budget,
# late groups are not starved); truncated groups are listed per group.
DEFAULT_MAX_PAIRS = 500
DETECTOR_TRUNCATED = "DETECTOR_TRUNCATED"

# Detector version: pinned per contradiction row for replay audit. A
# detector change that alters the pair-selection rule MUST bump this;
# identity is unaffected (version is provenance, not identity).
# v3: pair selection changed from sorted-group sequential (first groups
# starve later ones under the cap) to sorted-group round-robin fairness.
CONTRADICTION_DETECTOR_VERSION = "cx-detect-v3"


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


def _group_label(key: tuple[str, str, str]) -> str:
    """Display-only group label for diagnostics (provenance, NOT identity).

    Identity is the pair-keyed ``cx_`` hash alone; the label never feeds
    it. ``/`` is display-only (refs in practice never contain it).
    """
    return f"{key[0]}/{key[1]}/{key[2]}"


def detect_classification_conflicts(
    rows: Sequence[Mapping[str, Any]],
    *,
    max_pairs: int = DEFAULT_MAX_PAIRS,
    diagnostics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Pure CLASSIFICATION_CONFLICT detector over candidate rows.

    Each row: ``{artifact_id, project_id, program_ref, hypothesis_ref,
    failure_class, evidence: <iterable of bare artifact IDs>,
    invalidated: bool}``. Rows already filtered to digest-valid,
    admitted classifications by the caller; this function applies the
    pair rule only: same project/program/hypothesis, different
    failure_class, neither invalidated, non-empty evidence overlap.

    Pair budget: at most ``max_pairs`` pairs are emitted. The budget is
    shared across groups by round-robin over groups in sorted key order
    (one eligible pair per group per round), so a large early group
    cannot starve later groups. The budget TRUNCATES the pair list —
    pair identity (``cx_`` over the canonical pair, N1) is unchanged.
    A capped run records ``DETECTOR_TRUNCATED`` with per-group emission
    (never a silent partial result).

    Returns deterministically-ordered candidate dicts
    ``{type, party_a, party_b, contradiction_id, evidence_overlap}``
    sorted by ``contradiction_id``. No I/O, no clock, no randomness:
    identical inputs always yield identical outputs. Detector failure
    modes belong to the caller (a crash here means no assertion —
    absence of a record is never evidence of absence).
    """
    if max_pairs < 1:
        raise ContradictionError("max_pairs must be >= 1")
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
    # Dict artifact_id -> row per group (sort-once + index pairs: each
    # artifact is looked up once via by_id, no per-pair group scan).
    # Groups in sorted key order so the pair cap cuts deterministically
    # regardless of the order rows were supplied in.
    ordered_keys = sorted(by_group)
    group_by_id: dict[tuple[str, str, str], dict[str, Mapping[str, Any]]] = {}
    for key in ordered_keys:
        members = by_group[key]
        by_id: dict[str, Mapping[str, Any]] = {}
        for m in members:
            aid = m.get("artifact_id")
            if isinstance(aid, str):
                by_id.setdefault(aid, m)
        group_by_id[key] = by_id
    found: dict[str, dict[str, Any]] = {}
    per_emitted: dict[tuple[str, str, str], int] = dict.fromkeys(
        ordered_keys, 0)
    group_iters: list[
        tuple[tuple[str, str, str],
              Iterator[tuple[str, str, list[str]]]]] = [
        (k, _eligible_pairs(group_by_id[k])) for k in ordered_keys]
    alive: dict[tuple[str, str, str], bool] = dict.fromkeys(
        ordered_keys, True)
    # Round-robin: one eligible pair per group per round in sorted group
    # order until the global budget is spent or every group is exhausted.
    # Duplicate cids across groups (same artifact pair in two groups)
    # are skipped without consuming budget; identity is never redefined.
    capped = False
    while len(found) < max_pairs:
        if not any(alive.values()):
            break
        progress_in_round = False
        for key, it in group_iters:
            if not alive[key]:
                continue
            if len(found) >= max_pairs:
                capped = True
                break
            while True:
                try:
                    aid_a, aid_b, overlap = next(it)
                except StopIteration:
                    alive[key] = False
                    break
                cid = contradiction_id_of(aid_a, aid_b)
                if cid in found:
                    continue
                if len(found) >= max_pairs:
                    # Budget reached on a novel pair: this group still
                    # has at least this pair beyond the cap. The peek
                    # phase below re-derives the remainder precisely
                    # from fresh iterators, so no state to stash here.
                    capped = True
                    alive[key] = True
                    break
                found[cid] = {
                    "type": CONTRADICTION_TYPE_CLASSIFICATION_CONFLICT,
                    "party_a": aid_a,
                    "party_b": aid_b,
                    "contradiction_id": cid,
                    "evidence_overlap": overlap,
                }
                per_emitted[key] += 1
                progress_in_round = True
                break
            if capped:
                break
        if capped:
            break
        if not progress_in_round:
            # No novel pair this round and some iterators still claim
            # alive: remaining advances were all cross-group duplicates
            # that are now skipped to exhaustion, or nothing remains.
            # Defensive break against a non-advancing loop.
            break
    # Fail-visible truncation: capped runs must prove a remainder exists
    # (peek one novel pair per live group) rather than assert it, so an
    # exact-fit cap (eligible == max_pairs) does not misreport TRUNCATED.
    truncated_groups: list[str] = []
    per_truncated: dict[str, bool] = {}
    if capped or (len(found) >= max_pairs and any(alive.values())):
        # Re-derive remainder precisely: fresh iterators minus emitted.
        emitted_ids: set[str] = set(found)
        remainder_by_group: dict[tuple[str, str, str], bool] = {}
        for key in ordered_keys:
            if not alive[key]:
                remainder_by_group[key] = False
                continue
            has_more = False
            for aid_a, aid_b, _ov in _eligible_pairs(
                    group_by_id[key]):
                if contradiction_id_of(aid_a, aid_b) not in emitted_ids:
                    has_more = True
                    break
            remainder_by_group[key] = has_more
            alive[key] = has_more
        if any(remainder_by_group.values()):
            capped = True
            for key in ordered_keys:
                label = _group_label(key)
                is_trunc = bool(remainder_by_group[key])
                per_truncated[label] = is_trunc
                if is_trunc:
                    truncated_groups.append(label)
        else:
            capped = False
    if capped and truncated_groups:
        per_group: dict[str, dict[str, object]] = {}
        for key in ordered_keys:
            label = _group_label(key)
            per_group[label] = {
                "emitted": per_emitted[key],
                "truncated": per_truncated.get(label, False),
            }
        if diagnostics is not None:
            # Fail-visible: a capped run asserts only the pairs it
            # emitted. The caller surfaces this; absence of a pair is
            # not evidence that the pair does not contradict.
            diagnostics[DETECTOR_TRUNCATED] = {
                "max_pairs": max_pairs, "emitted": len(found),
                "groups": len(ordered_keys),
                "truncated_groups": sorted(truncated_groups),
                "per_group": per_group,
            }
    elif diagnostics is not None:
        # Under-cap runs leave no TRUNCATED key (as before): absence of
        # the key means nothing was cut. Per-group emission is available
        # to the caller via the returned pairs alone.
        diagnostics.pop(DETECTOR_TRUNCATED, None)
    return [found[k] for k in sorted(found)]


def _eligible_pairs(by_id: Mapping[str, Mapping[str, Any]],
                    ) -> Iterator[tuple[str, str, list[str]]]:
    """Yield ``(party_a, party_b, overlap)`` in canonical sorted order.

    Eligibility is the CHG-1 pair rule (different failure class,
    non-empty evidence overlap). Each artifact is looked up once via
    ``by_id`` (no per-pair scan of the group).
    """
    ids = sorted(by_id)
    for i, aid_a in enumerate(ids):
        left = by_id[aid_a]
        for aid_b in ids[i + 1:]:
            right = by_id[aid_b]
            if left["failure_class"] == right["failure_class"]:
                continue
            overlap = _overlap(left, right)
            if overlap:
                yield aid_a, aid_b, overlap
