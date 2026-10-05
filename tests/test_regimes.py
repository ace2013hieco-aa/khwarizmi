"""IDR-044 (Step 4 / S-R1) golden fixtures — the regime-axis registry.

Proves the slice's acceptance rows against ``src/hermes/research/regimes.py``:

- the closed REGISTRY is seeded with exactly the ICSS-v1 axis entries the
  live tree already assumes (verify-not-invent: exactly one, ``low-vol``);
- unknown ids refuse (``UNREGISTERED_REGIME``) and bare/unversioned refs
  refuse (``UNVERSIONED_REGIME``);
- membership evaluation is deterministic within a version;
- post-outcome fields are structurally unrepresentable in
  ``RegimeSnapshot`` (the constructed attempt fails);
- ``notes`` are excluded from definition identity;
- the INDETERMINATE verdict is a closed enum member with no free-text
  reason and refuses when submitted as authority (decision-inertness).

Pure deterministic core only: no persistence, no events, no clock.
"""
from __future__ import annotations

import dataclasses

import pytest

from hermes.research.regimes import (
    REGISTRY,
    RegimeDefinition,
    RegimeEvaluation,
    RegimeRef,
    RegimeResolutionError,
    RegimeSnapshot,
    RegimeTransition,
    RegimeVerdict,
    TransitionResponse,
    authoritative_transition,
    authoritative_verdict,
    derive_transition,
    evaluate_regime,
    parse_regime_ref,
    resolve_regime,
)

# ── fixture builder ──

def snapshot(**overrides) -> RegimeSnapshot:
    fields: dict = {
        "project_id": "p1",
        "hypothesis_ref": "h1",
        "program_ref": "prog-1",
        "falsifying_evidence_refs": ("e1",),
        "claim_context_tags": {"regime": "ICSS-v1:low-vol"},
    }
    fields.update(overrides)
    return RegimeSnapshot(**fields)


# ── acceptance row: the registry is seeded with exactly the live
#    assumptions (verify against the live tree, invent none) ──

def test_registry_seeded_exactly_with_the_live_icss_v1_axis_entry():
    """The live tree assumes exactly one regime value: 'ICSS-v1:low-vol'.

    (claims.py CONTEXT/DEREFERENCE_DIMENSIONS + the P7 fixtures' resolver
    stub; the failure-classification write path refuses ENVIRONMENT_MISMATCH
    until this axis lands.) Nothing else may be seeded.
    """
    assert {(d.version, d.regime_id) for d in REGISTRY} == {("ICSS-v1", "low-vol")}


def test_parse_and_resolve_roundtrip():
    ref = parse_regime_ref("ICSS-v1:low-vol")
    assert ref == RegimeRef(id="low-vol", version="ICSS-v1")
    assert ref.tag == "ICSS-v1:low-vol"
    definition = resolve_regime(ref)
    assert (definition.version, definition.regime_id) == ("ICSS-v1", "low-vol")


# ── acceptance row: unknown id refused (UNREGISTERED_REGIME) ──

def test_unknown_id_refused():
    ref = parse_regime_ref("ICSS-v1:high-vol")  # well-formed, not registered
    with pytest.raises(RegimeResolutionError) as excinfo:
        resolve_regime(ref)
    assert excinfo.value.code == "UNREGISTERED_REGIME"


def test_known_id_under_unknown_version_refused():
    """Identity is the (version, id) pair — a known id under a new version
    is NOT registered (versions are never silently interchangeable)."""
    ref = parse_regime_ref("ICSS-v2:low-vol")
    with pytest.raises(RegimeResolutionError) as excinfo:
        resolve_regime(ref)
    assert excinfo.value.code == "UNREGISTERED_REGIME"


# ── acceptance row: bare/unversioned ref refused (UNVERSIONED_REGIME) ──

@pytest.mark.parametrize("raw", ["low-vol", "ICSS-v1:", ":low-vol", ":", "a:b:c"])
def test_bare_or_unversioned_ref_refused(raw: str):
    with pytest.raises(RegimeResolutionError) as excinfo:
        parse_regime_ref(raw)
    assert excinfo.value.code == "UNVERSIONED_REGIME"


# ── acceptance row: determinism within a version ──

def test_membership_evaluation_deterministic_within_version():
    ref = parse_regime_ref("ICSS-v1:low-vol")
    expected = RegimeEvaluation(ref=ref, verdict=RegimeVerdict.IN_REGIME)
    # Same snapshot object, repeated calls.
    assert evaluate_regime(ref, snapshot()) == expected
    assert evaluate_regime("ICSS-v1:low-vol", snapshot()) == expected
    # Structurally equal snapshots (rebuilt, dict input, different pair order)
    # evaluate identically — canonicalization is order-insensitive.
    rebuilt = RegimeSnapshot(
        project_id="p1",
        hypothesis_ref="h1",
        program_ref="prog-1",
        falsifying_evidence_refs=("e1",),
        claim_context_tags=(("regime", "ICSS-v1:low-vol"),),
    )
    reordered = snapshot(claim_context_tags={"dataset_ref": "dm-1",
                                             "regime": "ICSS-v1:low-vol"})
    assert rebuilt == snapshot()
    assert evaluate_regime(ref, rebuilt) == expected
    assert evaluate_regime(ref, reordered) == expected


# ── acceptance row: post-outcome fields unrepresentable ──

def test_post_outcome_fields_unrepresentable_in_snapshot():
    """Constructing the attempt fails: a RegimeSnapshot has NO post-outcome
    field (falsified flag, observed outcome, realized performance) — the
    classification-time surface is exhaustive by construction."""
    base = {
        "project_id": "p1",
        "hypothesis_ref": "h1",
        "program_ref": "prog-1",
        "falsifying_evidence_refs": ("e1",),
        "claim_context_tags": {"regime": "ICSS-v1:low-vol"},
    }
    for post_outcome in ("outcome", "falsified", "observed_return",
                         "classification", "verdict"):
        with pytest.raises(TypeError):
            RegimeSnapshot(**base, **{post_outcome: "REFUTED"})
    field_names = {f.name for f in dataclasses.fields(RegimeSnapshot)}
    assert field_names == {
        "project_id", "hypothesis_ref", "program_ref",
        "falsifying_evidence_refs", "claim_context_tags",
    }


# ── acceptance row: notes excluded from identity ──

def test_notes_excluded_from_identity():
    def predicate(snapshot: RegimeSnapshot) -> bool:
        return True

    a = RegimeDefinition(regime_id="low-vol", version="ICSS-v1",
                         predicate=predicate, notes="wording one")
    b = RegimeDefinition(regime_id="low-vol", version="ICSS-v1",
                         predicate=predicate, notes="wording two")
    assert a != RegimeDefinition(regime_id="high-vol", version="ICSS-v1",
                                 predicate=predicate, notes="wording one")
    assert a == b and hash(a) == hash(b)
    assert len(frozenset({a, b})) == 1


# ── acceptance row: INDETERMINATE closed enum + decision-inertness ──

def test_verdict_vocabulary_is_a_closed_three_member_enum():
    assert {v.value for v in RegimeVerdict} == {
        "IN_REGIME", "NOT_IN_REGIME", "INDETERMINATE"}
    with pytest.raises(ValueError):
        RegimeVerdict("UNDECIDED")


def test_no_regime_declared_is_indeterminate_and_decision_inert():
    """No regime declaration in the claim context ⇒ INDETERMINATE (the
    honest fallback, never a guess) — and it refuses as authority."""
    ref = parse_regime_ref("ICSS-v1:low-vol")
    evaluation = evaluate_regime(ref, snapshot(claim_context_tags={
        "population": "adults-18-65"}))
    assert evaluation == RegimeEvaluation(ref=ref,
                                          verdict=RegimeVerdict.INDETERMINATE)
    with pytest.raises(RegimeResolutionError) as excinfo:
        authoritative_verdict(evaluation)
    assert excinfo.value.code == "INDETERMINATE_NOT_AUTHORITY"


def test_indeterminate_carries_no_free_text_reason():
    """The evaluation record has no rationale field by construction."""
    assert [f.name for f in dataclasses.fields(RegimeEvaluation)] == [
        "ref", "verdict"]


def test_resolved_verdicts_pass_the_authority_gate():
    ref = parse_regime_ref("ICSS-v1:low-vol")
    inside = evaluate_regime(ref, snapshot())
    outside = evaluate_regime(ref, snapshot(claim_context_tags={
        "regime": "ICSS-v1:high-vol"}))
    assert inside.verdict is RegimeVerdict.IN_REGIME
    assert authoritative_verdict(inside) is RegimeVerdict.IN_REGIME
    assert outside.verdict is RegimeVerdict.NOT_IN_REGIME
    assert authoritative_verdict(outside) is RegimeVerdict.NOT_IN_REGIME


# ── Step 4 / S-R2 (IDR-044 wiring): transitions + C2 hardening ──
# S-R1 substrate reference: the registry shape pinned above is the
# step-4/s-r1-polfix@7fa79df ratified shape (pinned by the seed test).

TRANS_KW = {"timestamp": "2026-09-27T22:00:00.000000+00:00",
            "program_ref": "prog-1", "hypothesis_ref": "h1"}


def test_transition_citation_rule_resolved_responses_are_cited():
    # derive IN_REGIME without evidence -> TRANSITION_EVIDENCE_REQUIRED
    with pytest.raises(RegimeResolutionError) as excinfo:
        derive_transition("ICSS-v1:low-vol", snapshot(), **TRANS_KW)
    assert excinfo.value.code == "TRANSITION_EVIDENCE_REQUIRED"
    # cited -> OK; response re-derived; determinism (freeze-at-classification)
    t1 = derive_transition("ICSS-v1:low-vol", snapshot(),
                           evidence_refs=("validation:ev1",), **TRANS_KW)
    t2 = derive_transition("ICSS-v1:low-vol", snapshot(),
                           evidence_refs=("validation:ev1",), **TRANS_KW)
    assert t1 == t2
    assert t1.response is TransitionResponse.IN_REGIME
    assert t1.evidence_refs == ("validation:ev1",)


def test_transition_provenance_omission_and_wrong_tag_refused():
    kw = dict(regime=parse_regime_ref("ICSS-v1:low-vol"),
              response=TransitionResponse.IN_REGIME,
              evidence_refs=("validation:ev1",), **TRANS_KW)
    # omission -> TypeError (required, no default)
    with pytest.raises(TypeError):
        RegimeTransition(**kw)
    # wrong tag -> INVALID_TRANSITION_PROVENANCE (omission is not defaulted,
    # a tag is not silently correctable)
    for wrong in ("LIVE", "SIMULATED ", "", "simulated"):
        with pytest.raises(RegimeResolutionError) as excinfo:
            RegimeTransition(**kw, provenance=wrong)
        assert excinfo.value.code == "INVALID_TRANSITION_PROVENANCE", wrong
    # the literal is admitted
    t = RegimeTransition(**kw, provenance="SIMULATED")
    assert t.provenance == "SIMULATED"


def test_transition_ladder_support_states_vocabulary_refuse_simulated():
    """Cross-vocabulary SIMULATED discipline: 'SIMULATED' is the regime
    transition layer's provenance literal ONLY — it is not admissible in
    any other closed vocabulary."""
    from hermes.research.claims import (
        SUPPORT_STATES,
        ExtractionDraft,
        ExtractionVerdict,
        ResearchClaimDraft,
        validate_extraction,
    )
    from hermes.research.programs import LadderTarget
    # 1. SUPPORT_STATES: 'SIMULATED' is not a support state...
    assert "SIMULATED" not in SUPPORT_STATES
    # ...and a claim claiming it refuses (invalid_support_state).
    result = validate_extraction(ExtractionDraft(
        source_ref="task_evidence:run-1",
        claims=(ResearchClaimDraft(
            ref="c1", statement="Alpha reduces beta.",
            source_ref="validation:ev1", support_state="SIMULATED",
            span_ref=None, claim_type="causal", context_tags={},
            assumption_refs=()),),
        assumptions=(), extracted_by="model_ref:golden-1", schema_version="2"))
    assert result.verdict is ExtractionVerdict.INVALID
    assert [e.code for e in result.errors] == ["invalid_support_state"]
    # 2. ladder target vocabulary: 'SIMULATED' is not a ladder rung.
    with pytest.raises(ValueError):
        LadderTarget("SIMULATED")


def test_transition_indeterminate_stays_decision_inert():
    ref = parse_regime_ref("ICSS-v1:low-vol")
    kw = dict(regime=ref, response=TransitionResponse.INDETERMINATE,
              provenance="SIMULATED", **TRANS_KW)
    # EXTRANEOUS evidence refuses (decision-inert: nothing may attach)
    with pytest.raises(RegimeResolutionError) as excinfo:
        RegimeTransition(**kw, evidence_refs=("validation:ev1",))
    assert excinfo.value.code == "EXTRANEOUS_TRANSITION_EVIDENCE"
    # the honest fallback takes no evidence...
    t = RegimeTransition(**kw)
    assert t.evidence_refs == ()
    # ...and refuses as transition authority (exact code).
    with pytest.raises(RegimeResolutionError) as excinfo:
        authoritative_transition(t)
    assert excinfo.value.code == "INDETERMINATE_NOT_AUTHORITY"


def test_transition_unregistered_and_bare_refuse_without_freeze_violation():
    # unregistered pair -> UNREGISTERED_REGIME (freeze: versioned pair only)
    with pytest.raises(RegimeResolutionError) as excinfo:
        derive_transition("ICSS-v1:high-vol", snapshot(),
                          evidence_refs=("validation:ev1",), **TRANS_KW)
    assert excinfo.value.code == "UNREGISTERED_REGIME"
    # bare id -> UNVERSIONED_REGIME (no re-interpretation, no freeze break)
    with pytest.raises(RegimeResolutionError) as excinfo:
        derive_transition("high-vol", snapshot(),
                          evidence_refs=("validation:ev1",), **TRANS_KW)
    assert excinfo.value.code == "UNVERSIONED_REGIME"


def test_derive_path_pins_the_evaluation_out_of_the_signature():
    """C1: the production path has no caller-response/evaluation parameter
    (nothing to forge — TypeError at the boundary); a forged response can
    only enter via the record constructor, which still refuses an
    unregistered regime and a wrong provenance."""
    kw = {"timestamp": TRANS_KW["timestamp"],
          "program_ref": "prog-1", "hypothesis_ref": "h1",
          "evidence_refs": ("validation:ev1",)}
    forged = RegimeEvaluation(ref=parse_regime_ref("ICSS-v1:low-vol"),
                              verdict=RegimeVerdict.IN_REGIME)
    with pytest.raises(TypeError):
        derive_transition("ICSS-v1:low-vol", snapshot(),
                          evaluation=forged, **kw)  # pyright: ignore[reportCallIssue]
    with pytest.raises(TypeError):
        derive_transition(
            "ICSS-v1:low-vol", snapshot(),
            response=TransitionResponse.NOT_IN_REGIME,  # pyright: ignore[reportCallIssue]
            **kw)


def test_transition_registered_pair_rule_and_typed_refs():
    # a resolved response REQUIRES a registered pair (constructor refuses
    # unregistered even with provenance + evidence)
    with pytest.raises(RegimeResolutionError) as excinfo:
        RegimeTransition(regime=parse_regime_ref("ICSS-v1:crisis"),
                         response=TransitionResponse.IN_REGIME,
                         provenance="SIMULATED",
                         evidence_refs=("validation:ev1",), **TRANS_KW)
    assert excinfo.value.code == "UNREGISTERED_REGIME"
    # typed refs: bare-string / non-sequence evidence coerces nothing
    for bad in ("validation:ev1", 5):
        with pytest.raises(RegimeResolutionError) as excinfo:
            RegimeTransition(regime=parse_regime_ref("ICSS-v1:low-vol"),
                             response=TransitionResponse.IN_REGIME,
                             provenance="SIMULATED",
                             evidence_refs=bad, **TRANS_KW)
        assert excinfo.value.code == "MALFORMED_EVIDENCE_REFS", bad


# ── S-R1 audit C2 hardening (F-1/F-2): typed-input refusals with codes ──

def test_c2_f1_bare_string_evidence_refs_coerce_nothing():
    with pytest.raises(RegimeResolutionError) as excinfo:
        snapshot(falsifying_evidence_refs="e1")
    assert excinfo.value.code == "MALFORMED_EVIDENCE_REFS"
    with pytest.raises(RegimeResolutionError) as excinfo:
        snapshot(falsifying_evidence_refs=("e1", 5))
    assert excinfo.value.code == "MALFORMED_EVIDENCE_REFS"


def test_c2_f2_bare_string_context_tags_raise_coded_error():
    with pytest.raises(RegimeResolutionError) as excinfo:
        snapshot(claim_context_tags="regime")
    assert excinfo.value.code == "MALFORMED_REGIME_CONTEXT"
    with pytest.raises(RegimeResolutionError) as excinfo:
        snapshot(claim_context_tags=(("regime", "ICSS-v1:low-vol"), "stray"))
    assert excinfo.value.code == "MALFORMED_REGIME_CONTEXT"
