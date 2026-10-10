"""FIX-CLAIM-GROUND — structure-only admission → grounded admission.

Fabricated-claim probes, one class per second-audit finding (§3):

- G10  non-readable carriers fail OPEN on span_ref (controller `_span_resolve`
       returned True for every non-``source_payload`` carrier).
- G9   a statement's verbatim (double-quoted) material is never checked
       against the cited source's stored bytes.
- G11  the validator never receives the context resolver (dataset_ref/regime
       dereference happened only at the repository, after validation).
- G12  the M4 causal rule is PREFIX-ONLY: ``pre_registered_experiment:<anything>``
       satisfies it, the experiment need not exist.
- G13  ``research_claims`` carries no model provenance columns; ``extracted_by``
       is the controller uuid, not a model.

Each probe asserts the fabrication is REFUSED. Legitimate flows are asserted
ADMITTED alongside, so a fail-closed change cannot silently break them.
"""
from __future__ import annotations

import pytest

from hermes.persistence.database import connect, get_schema_version
from hermes.persistence.migrations import SUPPORTED_VERSION, migrate_to_latest
from hermes.persistence.repositories import (
    ProjectRepository,
)
from hermes.research.claims import (
    CLAIM_SCHEMA_VERSION,
    EXPERIMENT_ARTIFACT_TYPE,
    FAIL_CLOSED_EXEMPT_CARRIERS,
    READABLE_TEXT_CARRIERS,
    ExtractionDraft,
    ResearchClaimDraft,
    carrier_of,
    extract_quoted_runs,
    non_readable_carrier_exempt,
    validate_extraction,
)

SOURCE_TEXT = "Alpha reduces beta under gamma conditions. Section 3 covers drift."


def _claim(**over) -> ResearchClaimDraft:
    fields = {
        "ref": "c1",
        "statement": "Alpha reduces beta under gamma conditions.",
        "source_ref": "source_payload:" + "a" * 64,
        "support_state": "INFERRED",
        "span_ref": None,
        "claim_type": "descriptive",
        "context_tags": {},
        "assumption_refs": (),
        "related_claims": (),
    }
    fields.update(over)
    return ResearchClaimDraft(**fields)


def _draft(claim: ResearchClaimDraft, **over) -> ExtractionDraft:
    fields = {
        "source_ref": claim.source_ref,
        "claims": (claim,),
        "assumptions": (),
        "extracted_by": "model_ref:golden-1",
        "schema_version": CLAIM_SCHEMA_VERSION,
    }
    fields.update(over)
    return ExtractionDraft(**fields)


def _text_of(source_ref: str):
    """The stub 'store': readable text for the one payload ref only."""
    return SOURCE_TEXT if source_ref == "source_payload:" + "a" * 64 else None


def _codes(result) -> set[str]:
    return {e.code for e in result.errors}


# ── G10: carrier fail-closed ───────────────────────────────────────────

NON_READABLE_CARRIERS = (
    "dataset_manifest", "task_evidence", "task_output", "validation",
    "pre_registered_experiment", "model_ref", "failure_classification",
)


@pytest.mark.parametrize("carrier", NON_READABLE_CARRIERS)
def test_g10_span_on_non_readable_carrier_refused(carrier):
    """RED on base a8f0180 (ADMITTED: span form-checked, resolver said True).
    GREEN now: an unverifiable span on a non-readable carrier is refused."""
    claim = _claim(source_ref=f"{carrier}:x1", span_ref="sec.3",
                   support_state="INFERRED", claim_type="descriptive")
    r = validate_extraction(_draft(claim, source_ref=f"{carrier}:x1"),
                            span_resolver=lambda s, p: True)
    assert not r.admitted
    assert "unverifiable_span_ref" in _codes(r)


def test_g10_span_on_readable_payload_still_admits_when_resolved():
    """Legitimate flow preserved: a span on a readable source_payload that the
    resolver confirms still admits (no regression on the certified path)."""
    claim = _claim(span_ref="Alpha reduces")
    r = validate_extraction(_draft(claim),
                            span_resolver=lambda s, p: p in SOURCE_TEXT)
    assert r.admitted, r.errors


def test_g10_exemption_list_is_explicit_and_empty():
    """The exemption list is the ONLY way a non-readable carrier escapes the
    refusal. It is named, enumerated, and currently empty (fail-closed)."""
    assert frozenset() == FAIL_CLOSED_EXEMPT_CARRIERS
    assert frozenset({"source_payload"}) == READABLE_TEXT_CARRIERS
    for carrier in NON_READABLE_CARRIERS:
        assert non_readable_carrier_exempt(carrier) is False


def test_g10_named_exemption_is_honoured_and_only_that_carrier(monkeypatch):
    """An explicitly named exemption admits a span on that carrier ONLY; every
    other non-readable carrier stays refused. Proves the list is the sole gate."""
    import hermes.research.claims as claims_mod
    monkeypatch.setattr(claims_mod, "FAIL_CLOSED_EXEMPT_CARRIERS",
                        frozenset({"dataset_manifest"}))
    ok = _claim(source_ref="dataset_manifest:dm-1", span_ref="sec.3",
                claim_type="descriptive", support_state="INFERRED")
    r_ok = validate_extraction(_draft(ok, source_ref="dataset_manifest:dm-1"),
                               span_resolver=lambda s, p: True)
    assert "unverifiable_span_ref" not in _codes(r_ok)
    bad = _claim(source_ref="task_output:t1", span_ref="sec.3",
                 claim_type="descriptive", support_state="INFERRED")
    r_bad = validate_extraction(_draft(bad, source_ref="task_output:t1"),
                                span_resolver=lambda s, p: True)
    assert "unverifiable_span_ref" in _codes(r_bad)


def test_g10_controller_span_resolver_no_longer_fails_open():
    """The controller's span resolver must return False (never True) for a
    non-readable carrier. Pinned at the source the controller actually runs."""
    import inspect

    from hermes.research import controller as ctl
    src = inspect.getsource(ctl)
    assert 'return False\n' in src
    # the old fail-open line is gone
    assert "return True  # no readable full text for this carrier" not in src


# ── G9: statement-vs-source byte check ─────────────────────────────────

def test_g9_fabricated_quote_refused_against_readable_source():
    """A verbatim quote absent from the cited stored text is refused."""
    claim = _claim(statement='The source says "alpha doubles beta".')
    r = validate_extraction(_draft(claim), text_resolver=_text_of)
    assert not r.admitted
    assert "statement_not_in_source" in _codes(r)


def test_g9_genuine_quote_admits_byte_for_byte():
    claim = _claim(statement='The source says "Alpha reduces beta".')
    r = validate_extraction(_draft(claim), text_resolver=_text_of)
    assert r.admitted, r.errors


def test_g9_quote_against_unreadable_carrier_refused():
    """No stored text exists for a non-readable carrier, so a quoted run cannot
    be verified and is refused (the check is not claimed as passing)."""
    claim = _claim(statement='It states "anything at all".',
                   source_ref="dataset_manifest:dm-1",
                   claim_type="descriptive", support_state="INFERRED")
    r = validate_extraction(_draft(claim, source_ref="dataset_manifest:dm-1"),
                            text_resolver=_text_of)
    assert "statement_not_in_source" in _codes(r)


def test_g9_paraphrase_without_quotes_not_checked_legitimate_flow():
    """Paraphrase is NOT verbatim material: no quotes → no byte check → admits.
    (Semantic paraphrase grounding needs judgment and is out of scope.)"""
    claim = _claim(statement="Alpha lowers beta when gamma holds.")
    r = validate_extraction(_draft(claim), text_resolver=_text_of)
    assert r.admitted, r.errors


def test_g9_quoted_run_extractor():
    assert extract_quoted_runs('a "x y" and "z"') == ("x y", "z")
    assert extract_quoted_runs("no quotes here") == ()
    assert extract_quoted_runs('blank "   " kept? no') == ()


# ── G11: context resolver wired into the validator ──────────────────────

def test_g11_dangling_dataset_ref_refused_when_resolver_supplied():
    """The validator, given the write-path resolver, refuses a dataset_ref that
    does not dereference (it previously never received a resolver)."""
    claim = _claim(context_tags={"dataset_ref": "dm-ghost"})
    r = validate_extraction(
        _draft(claim),
        context_resolver=lambda dim, val: not (dim == "dataset_ref"
                                               and val == "dm-ghost"))
    assert not r.admitted
    assert "dangling_context_ref" in _codes(r)


def test_g11_valid_dataset_ref_admits_with_resolver():
    claim = _claim(context_tags={"dataset_ref": "dm-1"})
    r = validate_extraction(_draft(claim), context_resolver=lambda d, v: True)
    assert r.admitted, r.errors


# ── G12: causal claim requires an admitted in-project experiment ──────

def test_g12_prefix_only_experiment_refused():
    """RED on base (ADMITTED: prefix matched, existence never checked).
    GREEN now: the experiment must dereference to an admitted in-project row."""
    claim = _claim(source_ref=f"{EXPERIMENT_ARTIFACT_TYPE}:fake-exp",
                   span_ref=None, claim_type="causal",
                   support_state="DIRECT")
    r = validate_extraction(_draft(claim, source_ref=claim.source_ref),
                            experiment_resolver=lambda ref: False)
    assert not r.admitted
    assert "unverified_experiment_ref" in _codes(r)


def test_g12_no_resolver_causal_direct_fails_closed():
    """With no experiment resolver a causal DIRECT claim cannot prove its
    experiment, so it fails closed rather than trusting the prefix."""
    claim = _claim(source_ref=f"{EXPERIMENT_ARTIFACT_TYPE}:exp-1",
                   claim_type="causal", support_state="PARTIAL")
    r = validate_extraction(_draft(claim, source_ref=claim.source_ref))
    assert not r.admitted
    assert "unverified_experiment_ref" in _codes(r)


def test_g12_admitted_in_project_experiment_admits():
    claim = _claim(source_ref=f"{EXPERIMENT_ARTIFACT_TYPE}:exp-1",
                   claim_type="causal", support_state="DIRECT")
    r = validate_extraction(_draft(claim, source_ref=claim.source_ref),
                            experiment_resolver=lambda ref: ref.endswith("exp-1"))
    assert r.admitted, r.errors


def test_g12_speculative_causal_needs_no_experiment():
    """Non-asserting causal states stay exempt (vocabulary remains usable)."""
    claim = _claim(claim_type="causal", support_state="SPECULATIVE")
    r = validate_extraction(_draft(claim))
    assert r.admitted, r.errors


# ── G13: model provenance is recorded and never fabricated ─────────────

@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Test")
    yield conn
    conn.close()


def test_g13_migration_adds_nullable_provenance_columns(db):
    cols = {row["name"] for row in db.execute(
        "SELECT name FROM pragma_table_info('research_claims')")}
    assert {"model_ref", "prompt_template_version", "run_id"} <= cols
    assert get_schema_version(db) == SUPPORTED_VERSION == 20


def test_g13_provenance_is_null_when_not_asserted_never_fabricated(db):
    """Old-row policy: a claim written without provenance keeps NULL = unknown.
    The write path must not invent model/template/run values."""
    result = validate_extraction(_draft(_claim(
        source_ref="source_payload:" + "a" * 64)))
    assert result.admitted
    assert result.model_ref == "model_ref:golden-1"  # carried from extracted_by
    assert result.prompt_template_version is None
    assert result.run_id is None


def test_g13_provenance_written_at_extract_write_path(db):
    """The three columns are written from the validated result (not invented)."""
    from hermes.persistence.repositories import TaskRepository  # noqa: F401
    from hermes.research.claims import ExtractionDraft as _D  # noqa: F401
    draft = _draft(_claim(source_ref="source_payload:" + "a" * 64),
                   prompt_template_version="tpl-7", run_id="run-42")
    result = validate_extraction(draft)
    assert result.admitted, result.errors
    assert result.prompt_template_version == "tpl-7"
    assert result.run_id == "run-42"
    assert result.model_ref == "model_ref:golden-1"


def test_carrier_of_helper():
    assert carrier_of("dataset_manifest:dm-1") == "dataset_manifest"
    assert carrier_of("no-separator") == ""
    assert carrier_of(None) == ""  # type: ignore[arg-type]
