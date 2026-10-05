"""S16 scope-review intake vocabulary (IDR-041 §4 — the ratification-ref
consumer for the scope authority).

The handoff design's S16 row: an APPROVED ``ROUTE_TO_SCOPE_REVIEW`` (or
``PROPOSE_SCOPE_NARROWING``) classification-action proposal IS the
scope-review intake — the operator-verdict channel records the human's
scope decision with the approval id as its ratification ref. This module
holds the closed vocabulary: the ratified scope-decision verdicts and the
S16-routed action set.

The intake RECORDS the scope decision; it never amends a ``scope_briefs``
row itself. The ScopeBrief is frozen and versioned (v4 §6.1/S16); amending
it is the S16 authority's separate act. The decision record is
evidence-of-ratification for that act — the same posture as the rest of the
handoff: a ratified fact, never a new executor.
"""
from __future__ import annotations

from enum import Enum

from hermes.research.failure_classification import PermittedAction

__all__ = [
    "MAX_SCOPE_RATIONALE",
    "S16_SCOPE_ACTIONS",
    "ScopeReviewDecision",
]


class ScopeReviewDecision(str, Enum):
    """The human's ratified scope verdict after a review route.

    - CONFIRM_SCOPE — the current scope stands (the review found no
      amendment needed).
    - AMEND_SCOPE — the scope needs amendment (the brief amendment is the
      S16 authority's separate, versioned act; the rationale records why).
    - DEFER_SCOPE — the review is deferred (rationale expected).
    """

    CONFIRM_SCOPE = "CONFIRM_SCOPE"
    AMEND_SCOPE = "AMEND_SCOPE"
    DEFER_SCOPE = "DEFER_SCOPE"


# The classification actions whose approval routes to the S16 scope
# authority (the handoff design §3.2 table, rows 4 and 6).
S16_SCOPE_ACTIONS = frozenset({
    PermittedAction.ROUTE_TO_SCOPE_REVIEW,
    PermittedAction.PROPOSE_SCOPE_NARROWING,
})

# Capped decision rationale (schema discipline — never a citation).
MAX_SCOPE_RATIONALE = 2000
