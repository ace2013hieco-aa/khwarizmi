"""TEXP-001 S2 — reference energy function (Case B, outside src/).

Implements the P0-supplement draft signature VERBATIM. STIPULATED in full
per v1.3 terms (no code source exists to transcribe — B2 evidence); the
function FORM is the stipulation, and it is deliberately minimal so the
stipulation surface stays auditable. Never presented as transcribed.

Five MUSTs (enforced by construction + tests):
1. Pure — no I/O, no RNG, no clock, no SQL, no writes (stdlib typing +
   dataclasses only).
2. Deterministic — same (path, context) always yields the same float.
3. Label-blind inputs — energy reads path STRUCTURE (length) only;
   edge extras (including any label-like keys) cannot change the output,
   and ``SearchContext`` has no label fields (unknown kwargs raise).
4. Validator-owns-G1 — energy assumes validator-admissible input and
   encodes no admissibility of its own; type violations are the
   reference validator's refusal (S1), never an energy penalty.
5. Never persisted — returns a float; writes nothing anywhere.

Minimal-form rationale: ``len(path)`` is the smallest total,
label-blind, deterministic cost with zero extra stipulated parameters.
Informativeness is NOT claimed here — pilot fixture F2 is the tripwire:
if length-energy is uninformative, F2 fails and the energy is revised
before any TUNE spend (pilot-gate). A richer energy would add
unstipulated parameters with no evidence behind them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

# An edge as the generator represents it. Energy reads STRUCTURE only
# (sequence length); every other key — including any label-like extra —
# is ignored by construction (blindness tests pin this).
TypedEdge = Mapping[str, object]


@dataclass(frozen=True, slots=True)
class SearchContext:
    """Label-free search context. Deliberately minimal: the reference
    energy is context-independent by stipulation (future energies may
    use context fields; any added field must pass a blindness review
    first). Frozen + slots: unknown kwargs (e.g. planted labels) raise
    TypeError instead of smuggling in."""

    graph_id: str


def reference_energy(path: Sequence[TypedEdge],
                     context: SearchContext) -> float:
    """Pure, deterministic path cost. Inputs MUST exclude planted labels
    (D2 secrecy); MUST NOT consult RNG or wall-clock (B5); MUST assume
    validator-admissible input — type violations are the validator's
    refusal (G1), never an energy penalty; result MUST be finite and MUST
    never be written to any evidence/claim/confidence field (C5)."""
    if not isinstance(context, SearchContext):
        raise TypeError(
            f"context must be a SearchContext, got {type(context).__name__}")
    items = list(path)
    for i, edge in enumerate(items):
        if not isinstance(edge, Mapping):
            raise TypeError(
                f"path[{i}] must be a mapping, got {type(edge).__name__}")
    _ = context.graph_id  # accepted (namespacing); unused in computation
    return float(len(items))
