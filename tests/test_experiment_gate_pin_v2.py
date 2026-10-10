"""Pin: causal DIRECT/PARTIAL are structurally inadmissible without an experiment.

EXPERIMENT-GATE-DOC-V2 (audit AUDIT-CLAIM-GROUND finding C, resolution (b)).
No experiment registry or gated declaration intent exists, so the production
path supplies no experiment resolver that admits anything. A causal/experimental
claim asserting DIRECT or PARTIAL support therefore refuses with the named code
``unverified_experiment_ref`` for EVERY experiment ref shape, and the stated
downgrade path (INFERRED / SPECULATIVE) still admits. Behavior is pinned as-is.
"""
from __future__ import annotations

import pytest

from hermes.research.claims import (
    CLAIM_SCHEMA_VERSION,
    EXPERIMENT_ARTIFACT_TYPE,
    ExtractionDraft,
    ResearchClaimDraft,
    validate_extraction,
)

# Every experiment ref shape: real-looking, fabricated, bare prefix, multi-segment.
EXPERIMENT_REFS = (
    f"{EXPERIMENT_ARTIFACT_TYPE}:exp-1",
    f"{EXPERIMENT_ARTIFACT_TYPE}:fabricated-999",
    f"{EXPERIMENT_ARTIFACT_TYPE}:",
    f"{EXPERIMENT_ARTIFACT_TYPE}:exp-1:replicate-2",
)


def _claim(source_ref: str, support_state: str) -> ResearchClaimDraft:
    return ResearchClaimDraft(
        ref="c1",
        statement="Alpha reduces beta under gamma conditions.",
        source_ref=source_ref,
        support_state=support_state,
        span_ref=None,
        claim_type="causal",
        context_tags={},
        assumption_refs=(),
        related_claims=(),
    )


def _extraction(claim: ResearchClaimDraft) -> ExtractionDraft:
    return ExtractionDraft(
        source_ref=claim.source_ref,
        claims=(claim,),
        assumptions=(),
        extracted_by="model_ref:pin-1",
        schema_version=CLAIM_SCHEMA_VERSION,
    )


@pytest.mark.parametrize("ref", EXPERIMENT_REFS)
@pytest.mark.parametrize("state", ["DIRECT", "PARTIAL"])
def test_causal_direct_partial_refused_for_any_experiment_ref(ref, state):
    # No resolver supplied (production has no admitting registry): refuse.
    r = validate_extraction(_extraction(_claim(ref, state)))
    assert not r.admitted
    assert "unverified_experiment_ref" in {e.code for e in r.errors}


@pytest.mark.parametrize("ref", EXPERIMENT_REFS)
@pytest.mark.parametrize("state", ["INFERRED", "SPECULATIVE"])
def test_causal_downgrade_states_admit_for_any_experiment_ref(ref, state):
    # Stated downgrade path: a causal claim that does not assert DIRECT/PARTIAL
    # support is not blocked by an unprovable experiment ref.
    r = validate_extraction(_extraction(_claim(ref, state)))
    assert r.admitted, r.errors
    assert r.claims[0].support_state == state
