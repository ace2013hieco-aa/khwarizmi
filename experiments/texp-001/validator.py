"""TEXP-001 S1 — reference typed-edge validator (Case B, outside src/).

Case-B reference implementation: pure, deterministic, stdlib-only. No model
calls, no RNG, no clock, no SQL, no writes. Validates candidate bridge paths
against a closed edge-type vocabulary plus an admissible-sequences table.

PROVENANCE (binding — see SOURCES.md):
- ``EDGE_ALPHABET``: TRANSCRIBED from v6 §14 line 780
  (``hermes_research_architecture_v6.md``) — the 14 knowledge-edge classes.
- ``ADMISSIBLE_SEQUENCES``: STIPULATED per v1.3 terms — minimal table,
  documented as stipulated in SOURCES.md and per-entry below. NEVER
  presented as transcribed: no GR3 proposal document exists (declared
  absent, SOURCES.md), and v6 contains no sequences table (zero
  "admissible sequence" hits in the 1483-line doc).
- Module shape is original authorship. No third-party code is copied or
  imported (EPL-2.0 constraint honored; no FaceChain content).

K2 seed: ``VALIDATOR_PROVENANCE`` carries the machine-readable provenance
flag that the lock's ``validator_ref`` must quote (alphabet transcribed,
sequences stipulated, GR3 absent).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

# ── v6 §14-transcribed edge alphabet (14 knowledge-edge classes) ──
EDGE_ALPHABET: frozenset[str] = frozenset({
    "supports",
    "contradicts",
    "entails",
    "refines",
    "analogous_to",
    "tested_by",
    "produced_by",
    "depends_on",
    "invalidates",
    "requires",
    "blocks",
    "applies_to",
    "observed_in",
    "replicated_by",
})

# ── STIPULATED admissible-sequences table (v1.3 terms) ──
# Minimal by construction: each entry below is STIPULATED, never transcribed.
# Any production use requires the real GR3 sequences; until then this table
# is the explicit, versioned stand-in both the generator and every arm share.
ADMISSIBLE_SEQUENCES: frozenset[tuple[str, ...]] = frozenset({
    ("supports",),          # STIPULATED
    ("entails",),            # STIPULATED
    ("supports", "supports"),      # STIPULATED
    ("supports", "entails"),       # STIPULATED
    ("entails", "supports"),       # STIPULATED
    ("refines", "supports"),       # STIPULATED
    ("supports", "refines"),       # STIPULATED
    ("analogous_to", "supports"),  # STIPULATED
    ("supports", "supports", "supports"),  # STIPULATED (S5-unify: D2 ℓ3 strata need)
    ("supports", "supports", "supports", "supports"),  # STIPULATED (S5-unify: D2 ℓ4 strata need)
})

# ── K2 provenance flag (seeded here; lock validator_ref must quote it) ──
VALIDATOR_PROVENANCE: dict[str, str] = {
    "alphabet_source": "v6-§14-transcribed",
    "sequences": "stipulated",
    "gr3_proposal": "absent",
    "validator_module": "experiments/texp-001/validator.py",
}


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """One path verdict. ``accepted`` iff non-empty, well-formed, alphabet
    members only, and the type sequence is in the table."""

    accepted: bool
    reason: str  # EMPTY_PATH | MALFORMED_EDGE | UNKNOWN_EDGE_TYPE |
                 # INADMISSIBLE_SEQUENCE | OK


def edge_types_of(path: Sequence[Mapping[str, object]]) -> tuple[str, ...]:
    """Project a path to its edge-type tuple. Raises TypeError on malformed
    entries (non-mapping path, missing/non-string edge_type) — malformed
    input is a caller bug, never a silent reject."""
    if not isinstance(path, Sequence) or isinstance(path, (str, bytes)):
        raise TypeError(
            f"path must be a sequence of edge mappings, got {type(path).__name__}")
    out: list[str] = []
    for i, edge in enumerate(path):
        if not isinstance(edge, Mapping):
            raise TypeError(
                f"path[{i}] must be a mapping, got {type(edge).__name__}")
        etype = edge.get("edge_type")
        if not isinstance(etype, str) or not etype:
            raise TypeError(
                f"path[{i}].edge_type must be a non-empty string, got {etype!r}")
        out.append(etype)
    return tuple(out)


def validate_path(path: Sequence[Mapping[str, object]]) -> ValidationResult:
    """Deterministically validate one candidate bridge path. Pure: no I/O,
    no RNG, no clock — same input always yields the same verdict."""
    types = edge_types_of(path)
    if not types:
        return ValidationResult(False, "EMPTY_PATH")
    for etype in types:
        if etype not in EDGE_ALPHABET:
            return ValidationResult(
                False, f"UNKNOWN_EDGE_TYPE:{etype}")
    if types not in ADMISSIBLE_SEQUENCES:
        return ValidationResult(False, "INADMISSIBLE_SEQUENCE")
    return ValidationResult(True, "OK")
