"""EVIDENCE_TRANSITION admission vocabulary (IDR-041 §4, AC-4).

The evidence ladder itself is a Phase 0 placeholder (v6 §10.1/§10.2 — no
evidence table, no EvidenceRepository); this module lands the ratified
VOCABULARY the gateway validator checks at admission: the closed set of
evidence states and the ``evidence:<artifact_id>`` dereference prefix.

The ratified states are exactly what the architecture already names:
the ladder rungs ``SUPPORTED`` / ``ROBUST`` / ``REPLICATED`` (the authority
map's "ladder targets above SUPPORTED (ROBUST/REPLICATED)") and the
falsification terminus ``REFUTED`` ("any → REFUTED" on decisive
falsification, v6 §10.2). No new state machine is introduced here — the
admission checks labels and refs; applying a transition (the APPLIED side)
remains the future ladder's authority.

The ratification-ref contract (AC-4) is enforced by the gateway validator,
not here: an EVIDENCE_TRANSITION admission carrying a ``ratification_ref``
must dereference to an APPROVED REJECT_BRANCH proposal whose action is in
the classification's permitted set (recomputed, F2), or the admission
fails closed.
"""
from __future__ import annotations

from enum import Enum

__all__ = [
    "EVIDENCE_REF_PREFIX",
    "MAX_EVIDENCE_TRANSITION_RATIONALE",
    "RATIFIED_EVIDENCE_STATES",
    "EvidenceState",
]


class EvidenceState(str, Enum):
    """The closed evidence-state vocabulary (v6 §10 — ratified names only).

    ``REFUTED`` is the terminal: no transition may leave REFUTED, and any
    state may transition TO it on decisive falsification (the ratified
    "any → REFUTED" rule). The rung ordering is the ladder's, not this
    module's — deep ladder rules belong to the future Evidence Ladder.
    """

    SUPPORTED = "SUPPORTED"
    ROBUST = "ROBUST"
    REPLICATED = "REPLICATED"
    REFUTED = "REFUTED"


# The closed admission set (str values for payload validation).
RATIFIED_EVIDENCE_STATES = frozenset(s.value for s in EvidenceState)

# The evidence dereference identity: ``evidence:<artifact_id>``.
EVIDENCE_REF_PREFIX = "evidence:"

# Capped admission rationale (schema discipline — never a citation).
MAX_EVIDENCE_TRANSITION_RATIONALE = 2000
