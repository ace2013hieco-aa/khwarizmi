"""Evidence Ladder APPLY — the deterministic rung derivation (design AC-1..5).

Pure derivation consumed by the controller's APPLY pass (the ladder's ONE
write path, IDR-041 AC-1..5): every rung is derived from ratified sources —
the recorded per-requirement satisfaction links (IDR-038 §3.1) for the
obligation climbs, the admitted + re-verified EVIDENCE_TRANSITION_PROPOSED
records for the ratified REFUTED terminus — never from the stored cache row
(F2: the stored row is the pass's own append-only output, compared against,
never trusted as the desired rung).

This module is pure: no SQL, no persistence imports, no write path, no LLM
input. The controller owns the transaction and the event emission; this
module answers "what rung do the ratified facts certify" and "what is the
deterministic identity of the transition that records it".
"""
from __future__ import annotations

import hashlib
import json as _json
from typing import Any, Mapping, Sequence

from hermes.research.programs import (
    LADDER_OBLIGATIONS,
    LadderTarget,
    canonical_json,
    sha256_hex,
)

# The ratified climb order (v6 §10.2). LADDER_OBLIGATIONS sets are nested
# (SUPPORTED ⊆ ROBUST ⊆ REPLICATED), so the highest certified rung is the
# first whose artifact set is fully satisfied.
RUNG_ORDER: tuple[str, ...] = (
    "SUPPORTED",
    "ROBUST",
    "REPLICATED",
)

# REFUTED is the terminal rung — above every climb rung, never left (the
# admission validator already enforces "no transition may leave REFUTED").
RUNG_INDEX: dict[str, int] = {
    "SUPPORTED": 0,
    "ROBUST": 1,
    "REPLICATED": 2,
    "REFUTED": 3,
}


def rung_above(a: str | None, b: str | None) -> bool:
    """True iff rung ``a`` is strictly above rung ``b`` (None = no rung yet)."""
    ia = RUNG_INDEX[a] if a is not None else -1
    ib = RUNG_INDEX[b] if b is not None else -1
    return ia > ib


def derive_obligation_rung(
    program: Mapping[str, Any],
    hypothesis: Mapping[str, Any],
    satisfied_classes: Sequence[str] | frozenset[str] | None,
) -> str | None:
    """The highest ladder rung the recorded satisfactions certify for one
    hypothesis, or None when even the SUPPORTED obligations are incomplete.

    ``hypothesis`` is a compiled ``hypotheses`` entry (``ref`` +
    ``ladder_target``); the per-requirement satisfaction facts for its
    ``claim_ref`` (the hypothesis ref) are the artifact CLASSES linked to it
    (IDR-038 §3.1). Because the obligation sets are nested, the first unmet
    rung caps the climb. A hypothesis without a confirmatory target, or a
    requirement whose classes cannot be read, certifies nothing (fail-closed
    — a corrupt program never becomes a rung fact).

    M1 / HR-02 precondition: ``satisfied_classes`` is VERDICT-COVERED by
    construction — the satisfaction read reports only classes whose linked
    artifacts carry a dereferenceable PASS validation verdict covering
    their content hash (the write path refuses links without one). This
    pure function therefore never sees a class lacking a verdict; a bare
    artifact class can never climb the ladder.
    """
    target = hypothesis.get("ladder_target")
    if target not in RUNG_ORDER:
        return None
    satisfied = set(satisfied_classes or ())
    derived: str | None = None
    for rung in RUNG_ORDER:
        artifacts, _ = LADDER_OBLIGATIONS[LadderTarget(rung)]
        if not set(artifacts) <= satisfied:
            break  # nested obligations — the first unmet rung caps the climb
        derived = rung
    return derived


def obligation_transition_id(
    program_id: str, hypothesis_ref: str, rung: str,
) -> str:
    """The deterministic identity of an obligation climb to ``rung``.

    Depends only on (program, hypothesis, rung) — the requirement is binary
    (all classes of the rung satisfied or not), so identical stored facts
    always derive the same transition id: the APPLY is idempotent across
    crashes and replays. ``LADDER_OBLIGATIONS`` is the ratified constant, so
    the id is stable for the policy's lifetime.
    """
    return "eltr_" + _digest({
        "program_id": program_id,
        "hypothesis_ref": hypothesis_ref,
        "rung": rung,
        "driver": "obligations",
    })


def ratification_transition_id(proposal_id: str) -> str:
    """The deterministic identity of a ratified REFUTED apply.

    Depends only on the ADMITTED transition proposal id (the audit record
    the pass consumes and re-verifies) — one ratified proposal can apply at
    most once, deterministically.
    """
    return "eltr_" + _digest({
        "proposal_id": proposal_id,
        "rung": "REFUTED",
        "driver": "ratification",
    })


def repair_state_transition_id(
    program_id: str, hypothesis_ref: str, rung: str,
) -> str:
    """The deterministic identity of a cache-REPAIR write (a tampered
    cache row corrected to the true derived rung). Distinct from the
    applied-transition ids so a repair is never mistaken for a ratified
    transition — and it emits no APPLIED event."""
    return "eltr_rep_" + _digest({
        "program_id": program_id,
        "hypothesis_ref": hypothesis_ref,
        "rung": rung,
        "driver": "repair",
    })


def classification_transition_id(classification_ref: str) -> str:
    """The deterministic identity of a bare-classification REFUTED apply
    (IDR-041 AC-2 deferred branch): depends only on the digest-valid
    classification ref — one falsification record can apply at most once,
    deterministically, and the id is stable across replays."""
    return "eltr_" + _digest({
        "classification_ref": classification_ref,
        "rung": "REFUTED",
        "driver": "classification",
    })


def classification_content_hash(
    metadata: Mapping[str, Any], project_id: str,
) -> str | None:
    """The content hash the stored classification metadata re-derives
    (None on malformed values — fail-closed, never a crash). The content
    payload is exactly the ratified classification content — the
    metadata's content fields re-serialized with the project_id (never
    stored in the metadata). Shared by the APPLY's F13 content-integrity
    check and the fixture/acceptance builders, so there is one
    derivation, no drift."""
    try:
        cf = metadata.get("contributing_factors")
        ev = metadata.get("evidence_refs")
        content = {
            "schema_version": metadata.get("schema_version"),
            "classifier_version": metadata.get("classifier_version"),
            "project_id": project_id,
            "hypothesis_ref": metadata.get("hypothesis_ref"),
            "program_ref": metadata.get("program_ref"),
            "failure_class": metadata.get("failure_class"),
            "contributing_factors": (
                sorted(cf) if isinstance(cf, (list, tuple)) else []),
            "evidence_refs": (
                sorted(ev) if isinstance(ev, (list, tuple)) else []),
            "constraint_ref": metadata.get("constraint_ref"),
            "failed_mechanism_ref": metadata.get("failed_mechanism_ref"),
            "regime_ref": metadata.get("regime_ref"),
            "resource_gap": metadata.get("resource_gap"),
            "scope_brief_ref": metadata.get("scope_brief_ref"),
            "scope_brief_field": metadata.get("scope_brief_field"),
            "explanation": metadata.get("explanation"),
            "proposed_by": metadata.get("proposed_by"),
            "condition_type": metadata.get("condition_type"),
        }
        return sha256_hex(canonical_json(content))
    except (TypeError, ValueError):
        return None


def classification_content_matches(
    metadata: Mapping[str, Any], project_id: str, content_hash: str,
) -> bool:
    """True iff the stored classification metadata RE-DERIVES the row's
    authoritative content hash (IDR-036 EC-V6: identity is derived, never
    authored). ANY metadata rewrite (class, constraint citation,
    hypothesis target, ...) changes the derived hash and is refused by
    the APPLY as forged. F2: the stored fields are VERIFIED against the
    content identity, never trusted alone. Fail-closed on malformed
    values (never a crash)."""
    derived = classification_content_hash(metadata, project_id)
    return derived is not None and derived == content_hash


def ladder_state_id(program_id: str, hypothesis_ref: str, version: int) -> str:
    """The content-derived state row identity — deterministic per
    (program, hypothesis, version), so a replayed pass re-derives the same
    rows and a crashed pass never leaves a half-written version."""
    return "elst_" + _digest({
        "program_id": program_id,
        "hypothesis_ref": hypothesis_ref,
        "version": version,
    })


def _digest(fields: dict[str, Any]) -> str:
    return hashlib.sha256(_json.dumps(
        fields, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
