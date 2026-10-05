"""Step 7 (v6 §16.6 / §10.1) — the FeatureBinding signature carrier.

A ``FeatureBinding`` is a separate Implementer-produced, content-addressed,
immutable artifact (v6:524, 723, 900, 902) that binds a REFUTED hypothesis to
the exact feature axes the refutation speaks about. It is the ONLY authority
for curated-registry signatures: no axis is ever inferred from hypothesis
text, claims, literature, falsification prose, or operator text — the binding
carries what its producer wrote, canonicalized deterministically.

Binding content (closed schema):

- ``schema_version = 1`` (integer)
- ``project_ref`` / ``program_ref`` / ``hypothesis_ref`` — the authoritative
  hypothesis identity (project_id, program_id, hypothesis_ref) the binding
  was produced for (Step 7 §3; the refs are provenance, never signature
  axes).
- mandatory axes: ``instrument``, ``feature_family``, ``claim_type``
- optional axes: ``slot_ref``, ``reward_hack_family``

Canonicalization (per string field, charter §2): type must be string →
NFC-normalize → lowercase → strip whitespace → reject empty → reject more
than 64 characters. An OPTIONAL axis that is absent or JSON null is omitted
from the canonical form (null ≡ absent — both produce identical canonical
bytes, deterministically).

Signature (charter §2)::

    signature_from_binding(binding) ==
        json.dumps({"schema_version": 1, "axes": {...}},
                   sort_keys=True, separators=(",", ":"))

over the canonical axes only (mandatory always; optional when present). The
refs never enter the signature — two projects refuting the same feature
combination derive the SAME signature.

Curated identity (charter §6)::

    curated_id = "curated_" + sha256(json.dumps({
        "schema_version": 1,
        "kind": kind,
        "signature": signature_json,
        "source_decision_event_ref": source_decision_event_ref,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

The FeatureBinding reference is provenance, NOT part of curated identity.

This module is pure: no SQL, no persistence imports, no LLM input — the
gateway owns admission and the repository owns reads (the evidence_ladder.py
contract).
"""
from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any, Mapping

__all__ = [
    "CURATED_ID_SCHEMA_VERSION",
    "CURATED_KIND_REFUTED_PATTERN",
    "CURATION_OPERATIONS",
    "FEATURE_BINDING_ARTIFACT_TYPE",
    "FEATURE_BINDING_MAX_AXIS_CHARS",
    "FEATURE_BINDING_REF_PREFIX",
    "FEATURE_BINDING_SCHEMA_VERSION",
    "MANDATORY_AXES",
    "MAX_EVIDENCE_BASIS_MEMBERS",
    "OPTIONAL_AXES",
    "FeatureBindingError",
    "binding_content",
    "binding_content_hash",
    "canonical_axes",
    "canonical_binding",
    "curated_id_of",
    "curation_command_hash",
    "signature_from_axes",
    "signature_from_binding",
]


class FeatureBindingError(ValueError):
    """A binding (or axis, or curation command) fails the closed Step 7
    canonicalization contract — fail-closed, nothing derived from it."""


# The artifact type (open ``artifact_type`` column — no migration needed for
# the type itself; the registry tables land with migration 14 → 15) and the
# D3-style ref prefix ``feature_binding:<content_hash>``.
FEATURE_BINDING_ARTIFACT_TYPE = "feature_binding"
FEATURE_BINDING_REF_PREFIX = "feature_binding:"
FEATURE_BINDING_SCHEMA_VERSION = 1

# Per-field canonical bounds (charter §2).
FEATURE_BINDING_MAX_AXIS_CHARS = 64

# The signature axes — mandatory always; optional only when present.
MANDATORY_AXES: tuple[str, ...] = ("claim_type", "feature_family", "instrument")
OPTIONAL_AXES: tuple[str, ...] = ("reward_hack_family", "slot_ref")

# The closed binding field set (refs + axes + schema_version).
_BINDING_REF_FIELDS: tuple[str, ...] = ("project_ref", "program_ref",
                                        "hypothesis_ref")
_BINDING_ALLOWED_KEYS: frozenset[str] = frozenset(
    {"schema_version", *_BINDING_REF_FIELDS, *MANDATORY_AXES, *OPTIONAL_AXES})

# The curated registry (charter §4–§6).
CURATED_KIND_REFUTED_PATTERN = "REFUTED_PATTERN"
CURATED_ID_SCHEMA_VERSION = 1
# Admission refuses a basis set above this many members (charter §4.7 / §8:
# the bound also keeps the admission event payload inside the 4096-byte
# journal cap without ever truncating evidence).
MAX_EVIDENCE_BASIS_MEMBERS = 32

# The chartered curation operations (charter §9 check 4).
CURATION_OPERATIONS: frozenset[str] = frozenset({"ADMIT", "SUPERSEDE"})


def canonicalize_axis(value: Any, field: str) -> str:
    """One canonical string (charter §2): string type → NFC → lowercase →
    strip → non-empty → at most 64 characters. ANY deviation raises
    ``FeatureBindingError`` (fail-closed; the caller never invents a value).
    The length bound applies to the canonical value (what is stored and
    signed)."""
    if not isinstance(value, str):
        raise FeatureBindingError(
            f"{field}: must be a string, got {type(value).__name__}")
    canonical = unicodedata.normalize("NFC", value).lower().strip()
    if not canonical:
        raise FeatureBindingError(
            f"{field}: empty after canonicalization — rejected")
    if len(canonical) > FEATURE_BINDING_MAX_AXIS_CHARS:
        raise FeatureBindingError(
            f"{field}: {len(canonical)} chars after canonicalization — "
            f"exceeds the {FEATURE_BINDING_MAX_AXIS_CHARS}-char bound")
    return canonical


def canonical_axes(
    *,
    instrument: Any,
    feature_family: Any,
    claim_type: Any,
    slot_ref: Any = None,
    reward_hack_family: Any = None,
) -> dict[str, str]:
    """The canonical axes dict (sorted-key friendly): the three mandatory
    axes canonicalized; each optional axis canonicalized when present,
    omitted when absent or JSON null (null ≡ absent — identical canonical
    bytes, deterministically)."""
    axes = {
        "claim_type": canonicalize_axis(claim_type, "claim_type"),
        "feature_family": canonicalize_axis(feature_family, "feature_family"),
        "instrument": canonicalize_axis(instrument, "instrument"),
    }
    if slot_ref is not None:
        axes["slot_ref"] = canonicalize_axis(slot_ref, "slot_ref")
    if reward_hack_family is not None:
        axes["reward_hack_family"] = canonicalize_axis(
            reward_hack_family, "reward_hack_family")
    return axes


def canonical_binding(binding: Mapping[str, Any]) -> dict[str, Any]:
    """The canonical form of a full binding (closed schema).

    Rejects: non-mappings, unknown keys (closed schema — never silently
    dropped), a ``schema_version`` other than the integer 1, any missing or
    malformed mandatory field. Optional axes absent or null are omitted.
    Returns ``{"schema_version": 1, "project_ref": ..., "program_ref": ...,
    "hypothesis_ref": ..., "axes": {...}}`` with every string canonical.
    """
    if not isinstance(binding, Mapping):
        raise FeatureBindingError(
            f"binding must be a mapping, got {type(binding).__name__}")
    unknown = sorted(set(binding) - _BINDING_ALLOWED_KEYS)
    if unknown:
        raise FeatureBindingError(
            f"binding carries unknown keys {unknown} — the FeatureBinding "
            f"schema is closed")
    schema_version = binding.get("schema_version")
    if (not isinstance(schema_version, int)
            or isinstance(schema_version, bool)
            or schema_version != FEATURE_BINDING_SCHEMA_VERSION):
        raise FeatureBindingError(
            f"binding.schema_version must be the integer "
            f"{FEATURE_BINDING_SCHEMA_VERSION}, got {schema_version!r}")
    refs = {
        field: canonicalize_axis(binding.get(field), field)
        for field in _BINDING_REF_FIELDS
    }
    axes = canonical_axes(
        instrument=binding.get("instrument"),
        feature_family=binding.get("feature_family"),
        claim_type=binding.get("claim_type"),
        slot_ref=binding.get("slot_ref"),
        reward_hack_family=binding.get("reward_hack_family"),
    )
    return {
        "schema_version": FEATURE_BINDING_SCHEMA_VERSION,
        "project_ref": refs["project_ref"],
        "program_ref": refs["program_ref"],
        "hypothesis_ref": refs["hypothesis_ref"],
        "axes": axes,
    }


def binding_content(binding: Mapping[str, Any]) -> str:
    """The canonical compact JSON content of the binding — the bytes the
    artifact's ``content_hash`` addresses (deterministic: sorted keys,
    compact separators)."""
    return json.dumps(
        canonical_binding(binding), sort_keys=True, separators=(",", ":"))


def binding_content_hash(binding: Mapping[str, Any]) -> str:
    """The SHA-256 hex digest of ``binding_content`` — the artifact identity
    (content-addressed, immutable)."""
    return hashlib.sha256(binding_content(binding).encode("utf-8")).hexdigest()


def signature_from_axes(axes: Mapping[str, str]) -> str:
    """The signature over an already-canonical axes mapping (the screen's
    path): ``{"schema_version":1,"axes":{...}}`` as canonical compact
    sorted-key JSON. The axes must be exactly a subset of the chartered axis
    vocabulary with every mandatory axis present."""
    if not isinstance(axes, Mapping):
        raise FeatureBindingError(
            f"axes must be a mapping, got {type(axes).__name__}")
    unknown = sorted(set(axes) - set(MANDATORY_AXES + OPTIONAL_AXES))
    if unknown:
        raise FeatureBindingError(
            f"axes carry unknown keys {unknown} — the axis vocabulary is "
            f"closed")
    missing = sorted(set(MANDATORY_AXES) - set(axes))
    if missing:
        raise FeatureBindingError(
            f"axes are missing mandatory axes {missing}")
    for name, value in axes.items():
        if value != canonicalize_axis(value, name):
            raise FeatureBindingError(
                f"axis {name!r} is not in canonical form")
    return json.dumps(
        {"schema_version": FEATURE_BINDING_SCHEMA_VERSION,
         "axes": dict(axes)},
        sort_keys=True, separators=(",", ":"))


def signature_from_binding(binding: Mapping[str, Any]) -> str:
    """The chartered signature (charter §2): canonical compact sorted-key
    JSON ``{"schema_version":1,"axes":{...}}`` derived from the binding's
    canonical axes — mandatory axes always, optional axes only when present.
    The refs never enter the signature. Nothing is inferred from hypothesis
    text, claims, literature, falsification prose, or operator text."""
    return signature_from_axes(canonical_binding(binding)["axes"])


def curated_id_of(
    kind: str, signature_json: str, source_decision_event_ref: str,
) -> str:
    """The chartered curated identity (charter §6) — verbatim formula. The
    FeatureBinding reference is provenance, NOT part of curated identity."""
    return "curated_" + hashlib.sha256(json.dumps(
        {
            "schema_version": CURATED_ID_SCHEMA_VERSION,
            "kind": kind,
            "signature": signature_json,
            "source_decision_event_ref": source_decision_event_ref,
        },
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def curation_command_hash(payload: Mapping[str, Any]) -> str:
    """The deterministic identity of the FULL curation command (charter §9
    check 7): the ``curation_id`` the operator's HumanDecisionReceived
    payload must bind. Covers every command field EXCEPT
    ``human_decision_ref`` (the decision event is recorded BEFORE the
    command is submitted, so the hash cannot depend on its own decision ref)
    and ``operator_id`` (the approver's identity, not the approved command).
    The ``retract_`` / ``eltr_`` precedent: prefix + sha256[:24] over the
    canonical compact JSON of the command fields."""
    return "curate_" + hashlib.sha256(json.dumps(
        {
            "operation": payload.get("operation") or "",
            "kind": payload.get("kind") or "",
            "program_ref": payload.get("program_ref") or "",
            "hypothesis_ref": payload.get("hypothesis_ref") or "",
            "source_binding_ref": payload.get("source_binding_ref") or "",
            "source_decision_event_ref":
                payload.get("source_decision_event_ref") or "",
            "signature_json": payload.get("signature_json") or "",
            "supersedes_ref": payload.get("supersedes_ref") or "",
        },
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()[:24]
