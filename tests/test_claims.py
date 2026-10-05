"""Golden fixtures for the P7 CONTRA substrate (v6 §29.4, IDR-024, IDR-025).

Per the manual-proof-first rule (v6 §29.2 rule 7 / §27 item 52), this is the
S8-pattern golden-fixture suite for ``ResearchClaim`` / ``ResearchAssumption``
+ ``ClaimAssumptionValidator`` (``src/hermes/research/claims.py``). It proves
the §29.4 P7 acceptance row:

- deterministic claim identity (same source ⇒ same id; batch refs never enter
  the content identity);
- assumption↔claim links maintained (dependent back-references, sorted);
- dangling context refs rejected (dereference discipline on
  ``dataset_ref``/``regime``);
- never-evidence structural test (no ladder surface, no Validation claim,
  no gate input — PA2/GR3 "never evidence" verbatim).

Plus the substrate's closed-schema / fail-closed contract, mirroring the
ResearchProgramValidator pattern (``test_research_program.py``). Pure
deterministic core only: no persistence, no events, no clock — the P7 runtime
integration is explicitly deferred (IDR-025).
"""
from __future__ import annotations

from hermes.research.claims import (
    CLAIM_SCHEMA_VERSION,
    CONTEXT_DIMENSIONS,
    DEREFERENCE_DIMENSIONS,
    SUPPORT_STATES,
    ExtractionDraft,
    ExtractionVerdict,
    ResearchAssumptionDraft,
    ResearchClaimDraft,
    SupportState,
    claim_id_of,
    validate_extraction,
)

# ── fixture builders ──

def claim(ref: str = "c1", **overrides) -> ResearchClaimDraft:
    fields = {
        "ref": ref,
        "statement": "Alpha reduces beta under gamma conditions.",
        "source_ref": "dataset_manifest:dm-1",
        "support_state": "INFERRED",
        "span_ref": "sec.3",
        "claim_type": "causal",
        "context_tags": {"regime": "ICSS-v1:low-vol", "dataset_ref": "dm-1"},
        "assumption_refs": ("a1",),
        "related_claims": (),
    }
    fields.update(overrides)
    return ResearchClaimDraft(**fields)


def assumption(ref: str = "a1", **overrides) -> ResearchAssumptionDraft:
    fields = {
        "ref": ref,
        "statement": "The sample is representative of the target population.",
        "context_tags": {"population": "adults-18-65"},
        "supporting_artifact_refs": ("dataset_manifest:dm-1",),
    }
    fields.update(overrides)
    return ResearchAssumptionDraft(**fields)


def extraction(**overrides) -> ExtractionDraft:
    fields = {
        "source_ref": "task_evidence:run-1",
        "claims": (claim(),),
        "assumptions": (assumption(),),
        "extracted_by": "model_ref:golden-1",
        "schema_version": CLAIM_SCHEMA_VERSION,
    }
    fields.update(overrides)
    return ExtractionDraft(**fields)


# resolver stub: only "dm-1" (dataset) and "ICSS-v1:low-vol" (regime) exist
def resolver(dimension: str, value: str) -> bool:
    return {
        "dataset_ref": value == "dm-1",
        "regime": value == "ICSS-v1:low-vol",
    }.get(dimension, True)


# ── acceptance row: deterministic claim identity ──

def test_golden_claim_identity_deterministic():
    """Same assertion content ⇒ same claim_id across batches."""
    r1 = validate_extraction(extraction())
    r2 = validate_extraction(extraction())
    assert r1.admitted and r2.admitted
    assert r1.claims[0].claim_id == r2.claims[0].claim_id


def test_golden_identity_ignores_batch_refs_and_provenance():
    """Batch-local refs and extraction provenance never enter the identity."""
    a = validate_extraction(extraction(claims=(claim(ref="x1"),),
                                        extracted_by="model_ref:other"))
    b = validate_extraction(extraction(claims=(claim(ref="x2"),),
                                        extracted_by="model_ref:y"))
    assert a.claims[0].claim_id == b.claims[0].claim_id


def test_golden_identity_sensitive_to_content():
    """A changed statement, source, span, type, context tag, or related_claims ⇒ new id."""
    base = claim_id_of("s", "dm:1", None, "", {})
    variants = [
        claim_id_of("s2", "dm:1", None, "", {}),                  # statement
        claim_id_of("s", "dm:2", None, "", {}),                  # source
        claim_id_of("s", "dm:1", "x", "", {}),                   # span
        claim_id_of("s", "dm:1", None, "causal", {}),            # type
        claim_id_of("s", "dm:1", None, "", {"regime": "a"}),     # context
        claim_id_of("s", "dm:1", None, "", {}, related_claims=("cl_abc",)),  # related
    ]
    assert all(v != base for v in variants)
    assert len({base, *variants}) == 7


def test_golden_identity_empty_related_claims_reproduces_pre_change_hash():
    """AC-1 Delta=0: with no cross-references the derivation must reproduce the
    pre-change hash byte-for-byte.

    ``cl_73c4308a4357edca8fcd6dad`` is the literal the pre-change derivation
    produced for these inputs (it never carried a ``related_claims`` key).
    Emitting the key unconditionally would silently re-identify every claim
    persisted before the field existed, so this is pinned as a literal on
    purpose: a change to it is an identity break, not a refactor.
    """
    assert claim_id_of("s", "dm:1", None, "", {}) == \
        "cl_73c4308a4357edca8fcd6dad"
    # the explicit empty tuple is the same derivation (the default is total)
    assert claim_id_of("s", "dm:1", None, "", {}, related_claims=()) == \
        "cl_73c4308a4357edca8fcd6dad"


def test_golden_identity_non_empty_related_claims_changes_hash():
    """The conditional key still feeds identity when present: a claim with
    cross-references is a different claim, and the ref set is order-insensitive."""
    base = claim_id_of("s", "dm:1", None, "", {})
    one = claim_id_of("s", "dm:1", None, "", {}, related_claims=("cl_a",))
    two = claim_id_of("s", "dm:1", None, "", {}, related_claims=("cl_b",))
    both = claim_id_of("s", "dm:1", None, "", {},
                       related_claims=("cl_a", "cl_b"))
    assert len({base, one, two, both}) == 4
    # sorted into the preimage ⇒ the ref order never changes the identity
    assert claim_id_of("s", "dm:1", None, "", {},
                       related_claims=("cl_b", "cl_a")) == both
    assert one.startswith("cl_") and len(one) == 3 + 24


def test_golden_identity_prefix_and_hash_form():
    r = validate_extraction(extraction())
    assert r.claims[0].claim_id.startswith("cl_")
    assert r.assumptions[0].assumption_id.startswith("as_")
    assert len(r.claims[0].claim_id) == 3 + 24
    assert len(r.assumptions[0].assumption_id) == 3 + 24


def test_golden_content_hash_equals_identity():
    """One canonical derivation: content_hash is the identity, never a second
    hash path (the same discipline as EC-V6-20 for programs)."""
    r = validate_extraction(extraction())
    assert r.claims[0].content_hash == r.claims[0].claim_id
    assert r.assumptions[0].content_hash == r.assumptions[0].assumption_id


# ── acceptance row: assumption↔claim links maintained ──

def test_golden_links_maintained_deterministically():
    """dependent_claim_ids back-references are sorted and complete."""
    r = validate_extraction(extraction(
        claims=(
            claim(ref="c1", assumption_refs=("a1",)),
            claim(ref="c2", statement="Omega rises under delta.",
                  assumption_refs=("a1", "a2")),
        ),
        assumptions=(
            assumption(ref="a1"),
            assumption(ref="a2", statement="Delta is measurable."),
        ),
    ))
    assert r.admitted
    by_id = {a.assumption_id: a for a in r.assumptions}
    c1 = r.claims[0]
    c2 = r.claims[1]
    # c1 links only a1; c2 links a1 and a2
    assert len(c1.assumption_ids) == 1
    assert len(c2.assumption_ids) == 2
    # a1 depends on both claims; a2 only on c2 (identify by premise content)
    a1 = by_id[c1.assumption_ids[0]]
    a2 = next(a for aid, a in by_id.items()
              if a.statement == "Delta is measurable.")
    assert a1.dependent_claim_ids == tuple(sorted((c1.claim_id, c2.claim_id)))
    assert a2.dependent_claim_ids == (c2.claim_id,)
    assert a1.dependent_claim_ids == tuple(sorted(a1.dependent_claim_ids))


def test_golden_assumption_identity_independent_of_links():
    """Assumption identity derives from the premise, not from which claims
    depend on it (links are maintained, never part of the content hash)."""
    a = validate_extraction(extraction(assumptions=(assumption(),)))
    b = validate_extraction(extraction(
        claims=(claim(assumption_refs=()),),
        assumptions=(assumption(),),
    ))
    assert a.admitted and b.admitted
    assert a.assumptions[0].assumption_id == b.assumptions[0].assumption_id


# ── acceptance row: dangling context refs rejected ──

def test_golden_dangling_dataset_ref_rejected():
    r = validate_extraction(extraction(
        claims=(claim(context_tags={"dataset_ref": "dm-999"}),)),
        context_resolver=resolver)
    assert not r.admitted
    codes = {e.code for e in r.errors}
    assert "dangling_context_ref" in codes


def test_golden_dangling_regime_ref_rejected():
    r = validate_extraction(extraction(
        claims=(claim(context_tags={"regime": "ICSS-v1:no-such-axis"}),)),
        context_resolver=resolver)
    assert not r.admitted
    assert "dangling_context_ref" in {e.code for e in r.errors}


def test_golden_valid_refs_accepted_with_resolver():
    r = validate_extraction(extraction(), context_resolver=resolver)
    assert r.admitted


def test_golden_unknown_context_dimension_rejected():
    """Closed CONTEXT_DIMENSIONS set: a non-vocabulary dimension is rejected
    even when a resolver is present (no free-form context blobs)."""
    r = validate_extraction(extraction(
        claims=(claim(context_tags={"vibes": "high"}),)),
        context_resolver=resolver)
    assert not r.admitted
    assert "unknown_context_dimension" in {e.code for e in r.errors}


# ── acceptance row: never-evidence structural test ──

def test_never_evidence_no_ladder_surface():
    """The advisory substrate has no evidence surface at all: no Validation,
    no ladder status, no promotion method — PA2/GR3 verbatim."""
    r = validate_extraction(extraction())
    cl = r.claims[0]
    assert not hasattr(cl, "validation")
    assert not hasattr(cl, "ladder_status")
    assert not hasattr(cl, "promote")
    assert not hasattr(cl, "evidence")
    assert all("ladder" not in f for f in cl.__dataclass_fields__)
    assert all("evidence" not in f for f in cl.__dataclass_fields__)
    asm = r.assumptions[0]
    assert all("ladder" not in f for f in asm.__dataclass_fields__)
    assert all("evidence" not in f for f in asm.__dataclass_fields__)


def test_never_evidence_verdicts_are_admission_only():
    """ADMITTED/INVALID are admission verdicts, not epistemic verdicts."""
    assert ExtractionVerdict.ADMITTED.value == "ADMITTED"
    assert ExtractionVerdict.INVALID.value == "INVALID"
    assert set(ExtractionVerdict) == {
        ExtractionVerdict.ADMITTED, ExtractionVerdict.INVALID}


def test_never_evidence_assumption_status_is_advisory():
    """Assumption status is the advisory lifecycle, never an evidence state."""
    r = validate_extraction(extraction())
    assert r.assumptions[0].status == "ACTIVE"


# ── fail-closed schema contract (house validator pattern) ──

def test_empty_batch_rejected():
    r = validate_extraction(extraction(claims=(), assumptions=()))
    assert not r.admitted
    assert "empty_extraction" in {e.code for e in r.errors}


def test_duplicate_batch_refs_rejected():
    r = validate_extraction(extraction(
        claims=(claim(ref="x"), claim(ref="x", statement="different"))))
    assert not r.admitted
    assert "duplicate_ref" in {e.code for e in r.errors}


def test_unresolved_assumption_ref_rejected():
    r = validate_extraction(extraction(claims=(claim(assumption_refs=("nope",)),)))
    assert not r.admitted
    assert "unresolved_assumption_ref" in {e.code for e in r.errors}


def test_invalid_source_ref_rejected():
    r = validate_extraction(extraction(claims=(claim(source_ref="no-colon"),)))
    assert not r.admitted
    assert "invalid_source_ref" in {e.code for e in r.errors}


def test_empty_statement_rejected():
    r = validate_extraction(extraction(claims=(claim(statement="  "),)))
    assert not r.admitted
    assert "empty_statement" in {e.code for e in r.errors}


def test_claim_type_cap_rejected():
    r = validate_extraction(extraction(claims=(claim(claim_type="x" * 65),)))
    assert not r.admitted
    assert "invalid_claim_type" in {e.code for e in r.errors}


def test_self_supersession_rejected():
    r = validate_extraction(extraction(claims=(claim(supersedes_ref="cl_self"),)))
    # build a claim whose identity equals its supersedes_ref
    r2 = validate_extraction(extraction(claims=(claim(),)))
    cid = r2.claims[0].claim_id
    r3 = validate_extraction(extraction(claims=(claim(supersedes_ref=cid),)))
    assert r.admitted and r2.admitted
    assert not r3.admitted
    assert "self_supersession" in {e.code for e in r3.errors}


def test_type_error_on_non_draft():
    import pytest
    with pytest.raises(TypeError):
        validate_extraction({"claims": []})  # type: ignore[arg-type]


def test_errors_collect_all_in_class():
    """Fail-closed but exhaustive: all structural errors in a class surface,
    not just the first (house validator behavior)."""
    r = validate_extraction(extraction(
        claims=(
            claim(source_ref="bad"),
            claim(ref="x2", statement="", assumption_refs=("missing",)),
        )))
    codes = {e.code for e in r.errors}
    assert "invalid_source_ref" in codes
    assert "empty_statement" in codes
    assert "unresolved_assumption_ref" in codes


# ── purity / no write surface ──

def test_pure_module_no_persistence_imports():
    """The substrate must have zero persistence/event surface (static check on
    actual imports — the docstring may name the absent surfaces)."""
    import inspect

    import hermes.research.claims as mod
    src = inspect.getsource(mod)
    for banned in ("import sqlite3", "from hermes.persistence",
                   "import hermes.persistence", "EventRepository",
                   "from hermes.core.events", "import events",
                   "apply_intent", "from hermes.core.intents"):
        assert banned not in src, f"substrate must not import {banned!r}"


def test_validator_returns_result_never_raises():
    """validate_extraction returns an ExtractionResult for any draft — the
    fail-closed contract surfaces structured errors, not exceptions."""
    from hermes.research.claims import ClaimValidationError
    for draft in (extraction(claims=(), assumptions=()),
                  extraction(claims=(claim(source_ref="bad"),))):
        result = validate_extraction(draft)
        assert result.verdict is ExtractionVerdict.INVALID
        assert isinstance(result.errors, tuple)
        assert all(isinstance(e, ClaimValidationError) for e in result.errors)


def test_dereference_dimensions_are_closed_subset():
    assert DEREFERENCE_DIMENSIONS <= CONTEXT_DIMENSIONS


# ── HR-05 / M4: closed support-state vocabulary + span dereference ──

class TestSupportStateVocabulary:
    """M4 (HR-05 closure): claim admission gains a closed support_state
    vocabulary plus span dereference, so fabricated causal overclaims
    citing nonexistent spans are rejected deterministically (audit
    PROBE P4 / T-CAUSAL-OVERCLAIM)."""

    def test_vocabulary_is_the_closed_six_states(self):
        assert frozenset({
            "DIRECT", "PARTIAL", "INFERRED", "SPECULATIVE",
            "CONTRADICTED", "UNSUPPORTED",
        }) == SUPPORT_STATES
        assert {s.value for s in SupportState} == SUPPORT_STATES

    def test_missing_support_state_rejected(self):
        r = validate_extraction(extraction(
            claims=(claim(support_state=None),)))
        assert not r.admitted
        assert "missing_support_state" in {e.code for e in r.errors}

    def test_unknown_support_state_rejected(self):
        r = validate_extraction(extraction(
            claims=(claim(support_state="PROVEN"),)))
        assert not r.admitted
        assert "invalid_support_state" in {e.code for e in r.errors}

    def test_each_closed_state_admits(self):
        for state in sorted(SUPPORT_STATES):
            # SPECULATIVE/INFERRED/CONTRADICTED/UNSUPPORTED causal claims are
            # exempt from the experiment-source rule; DIRECT/PARTIAL need an
            # experiment source, so use a non-causal type for the sweep.
            r = validate_extraction(extraction(
                claims=(claim(support_state=state, claim_type="descriptive"),)))
            assert r.admitted, f"{state} should admit: {r.errors}"
            assert r.claims[0].support_state == state

    def test_support_state_enters_content_identity(self):
        a = validate_extraction(extraction(
            claims=(claim(support_state="DIRECT", claim_type="descriptive"),)))
        b = validate_extraction(extraction(
            claims=(claim(support_state="PARTIAL", claim_type="descriptive"),)))
        assert a.claims[0].claim_id != b.claims[0].claim_id

    def test_causal_direct_requires_experiment_source(self):
        # T-CAUSAL-OVERCLAIM: a causal claim asserting DIRECT support from an
        # observational (dataset) source is rejected deterministically.
        r = validate_extraction(extraction(
            claims=(claim(support_state="DIRECT", claim_type="causal"),)))
        assert not r.admitted
        assert "causal_overclaim" in {e.code for e in r.errors}

    def test_causal_partial_requires_experiment_source(self):
        r = validate_extraction(extraction(
            claims=(claim(support_state="PARTIAL", claim_type="causal"),)))
        assert not r.admitted
        assert "causal_overclaim" in {e.code for e in r.errors}

    def test_causal_direct_from_experiment_source_admits(self):
        r = validate_extraction(extraction(
            claims=(claim(
                support_state="DIRECT", claim_type="causal",
                source_ref="pre_registered_experiment:exp-1"),)))
        assert r.admitted, r.errors

    def test_causal_speculative_from_observational_source_admits(self):
        # A speculative causal claim does not assert direct source support,
        # so an observational source is fine (the vocabulary stays usable).
        r = validate_extraction(extraction(
            claims=(claim(support_state="SPECULATIVE", claim_type="causal"),)))
        assert r.admitted, r.errors

    def test_causal_inferred_from_observational_source_admits(self):
        r = validate_extraction(extraction(
            claims=(claim(support_state="INFERRED", claim_type="causal"),)))
        assert r.admitted, r.errors

    def test_non_causal_direct_from_observational_source_admits(self):
        # The experiment-source rule applies only to causal/experimental
        # claim types; a descriptive DIRECT claim from a dataset is fine.
        r = validate_extraction(extraction(
            claims=(claim(support_state="DIRECT", claim_type="descriptive"),)))
        assert r.admitted, r.errors


class TestSpanDereference:
    """HR-05 span dereference: a span_ref must resolve within the cited
    source when a span resolver is supplied (the write path supplies one
    over the stored source content)."""

    def test_fabricated_span_rejected_with_resolver(self):
        # A resolver that knows the source has no such span.
        def span_resolver(source_ref: str, span_ref: str) -> bool:
            return span_ref == "sec.1"  # only sec.1 exists
        r = validate_extraction(
            extraction(claims=(claim(span_ref="sec.999"),)),
            span_resolver=span_resolver)
        assert not r.admitted
        assert "dangling_span_ref" in {e.code for e in r.errors}

    def test_resolving_span_admits_with_resolver(self):
        def span_resolver(source_ref: str, span_ref: str) -> bool:
            return span_ref == "sec.3"
        r = validate_extraction(
            extraction(claims=(claim(span_ref="sec.3"),)),
            span_resolver=span_resolver)
        assert r.admitted, r.errors

    def test_no_resolver_form_checks_only(self):
        # Without a resolver (substrate-level fixtures), span_ref is
        # form-checked only — a nonexistent span is not rejected here.
        r = validate_extraction(extraction(claims=(claim(span_ref="sec.999"),)))
        assert r.admitted, r.errors

    def test_none_span_ref_admits_with_resolver(self):
        def span_resolver(source_ref: str, span_ref: str) -> bool:
            return False  # would reject any span
        r = validate_extraction(
            extraction(claims=(claim(span_ref=None),)),
            span_resolver=span_resolver)
        assert r.admitted, r.errors


# ── related_claims: content-addressed cross-ref (advisory only) ──

class TestRelatedClaims:
    """related_claims are content-addressed cl_ IDs for cross-referencing.

    Pure advisory: no DB/persistence import, no dereference, no influence
    on SUPPORT_STATES, gate inputs, or the ladder. Form-check only.
    """

    def test_admitted_with_related_claims(self):
        r = validate_extraction(extraction(claims=(
            claim(related_claims=("cl_abc123", "cl_def456")),)))
        assert r.admitted, r.errors
        assert r.claims[0].related_claim_ids == (
            "cl_abc123", "cl_def456")

    def test_related_claims_sorted_deterministically(self):
        r1 = validate_extraction(extraction(claims=(
            claim(related_claims=("cl_b", "cl_a")),)))
        r2 = validate_extraction(extraction(claims=(
            claim(related_claims=("cl_a", "cl_b")),)))
        assert r1.admitted and r2.admitted
        assert r1.claims[0].related_claim_ids == r2.claims[0].related_claim_ids
        assert r1.claims[0].related_claim_ids == ("cl_a", "cl_b")

    def test_empty_related_claims_admits(self):
        r = validate_extraction(extraction(claims=(claim(related_claims=()),)))
        assert r.admitted, r.errors
        assert r.claims[0].related_claim_ids == ()

    def test_default_related_claims_empty(self):
        r = validate_extraction(extraction(claims=(claim(),)))
        assert r.admitted, r.errors
        assert r.claims[0].related_claim_ids == ()

    def test_invalid_related_claim_id_rejected(self):
        r = validate_extraction(extraction(claims=(
            claim(related_claims=("cl_valid", "", "  ")),)))
        assert not r.admitted
        assert "invalid_related_claim_id" in {e.code for e in r.errors}

    def test_non_string_related_claim_rejected(self):
        r = validate_extraction(extraction(claims=(
            claim(related_claims=(123,)),)))
        assert not r.admitted
        assert "invalid_related_claim_id" in {e.code for e in r.errors}

    def test_related_claims_enters_content_identity(self):
        """Same statement + different related_claims ⇒ different claim_id."""
        base = claim()
        r1 = validate_extraction(extraction(claims=(base,)))
        r2 = validate_extraction(extraction(claims=(
            claim(related_claims=("cl_other",)),)))
        assert r1.admitted and r2.admitted
        assert r1.claims[0].claim_id != r2.claims[0].claim_id

    def test_content_hash_equals_identity_with_related_claims(self):
        """content_hash is the identity, includes related_claims."""
        r = validate_extraction(extraction(claims=(
            claim(related_claims=("cl_abc", "cl_def")),)))
        assert r.claims[0].content_hash == r.claims[0].claim_id
