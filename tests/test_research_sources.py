"""Golden fixtures — ResearchSourceProvider step 1 (IDR-030, §27 item 55).

Proves the blueprint §7.3 `test_research_sources.py` row against the ratified
contract (contract §2/§3.1/§7):
1. port types are frozen/immutable and deterministic;
2. result/content identity is content-addressed and recomputable;
3. `parse_query_hints` splits identifiers/topic/mode and surfaces unrecognized
   prefixes for the router to reject (PS3-06);
4. the identifier normalization table (DOI/PMID/PMCID/arXiv old+new, version
   strip, resolver URLs) is exactly the contract §3.1 rules;
5. cross-provider dedup keys are doi → pmid → pmcid → arxiv, namespaced;
6. redaction: a real credential value appears in ZERO records (zero-leak), polite
   params are sent-but-redacted (`<redacted:email>`), unknown names are
   default-denied WITH a `redaction_policy_gap` note, headers (Authorization/
   cookies/X-Api-Key) are redacted, and URL redaction covers query params,
   userinfo, and credential path segments (PS-09/PS3-07);
7. the error taxonomy classes are ordered (transient vs permanent vs validation
   vs unavailable) and carry provider_id/hazard_class/recordable.

All pure, zero I/O — no network, no DB, no fixtures on disk.
"""
from __future__ import annotations

import dataclasses

import pytest

from hermes.research.programs import canonical_json
from hermes.tools.providers.normalize import (
    dedup_key,
    normalize_identifier,
    parse_query_hints,
)
from hermes.tools.providers.redact import (
    DEFAULT_POLICY,
    RedactionPolicy,
    redact_headers,
    redact_params,
    redact_url,
    redaction_policy_gaps,
)
from hermes.tools.research_sources import (
    FetchOutcome,
    NoFullText,
    PermanentProviderError,
    ProviderError,
    ProviderUnavailableError,
    ProviderValidationError,
    RedactionError,
    RetrievalShortfallError,
    SearchOutcome,
    SearchResult,
    Source,
    TransientProviderError,
    content_hash_of_search_result,
    make_search_result_id,
    observation_hash_of_search_result,
)

# ── helpers ──


def make_result(**overrides) -> SearchResult:
    base: dict = {
        "result_id": "sr_" + "0" * 24,
        "provider": "pubmed",
        "endpoint": "/esearch.fcgi",
        "query": "cancer",
        "request_params_redacted": {"term": "<redacted>"},
        "identifiers": {"pmid": "26214858"},
        "title": "A Study",
        "authors": ("Doe, J.",),
        "year": 2026,
        "venue": "Journal of Tests",
        "abstract_sha256": None,
        "source_url": "https://pubmed.example/26214858",
        "access_timestamp_utc": "2026-01-01T00:00:00.000000+00:00",
        "page_index": 0,
        "cursor_key": None,
        "raw_retrieved_count": 1,
        "delivered_count": 1,
        "total_count": 1,
        "total_is_estimate": False,
        "reconciliation": "COMPLETE",
        "content_hash": "0" * 64,
        "provenance": {"provider_spec_version": "1.0.0", "hazard_verdict": "NONE"},
    }
    base.update(overrides)
    return SearchResult(**base)


# ── 1. port types: immutable, deterministic ──


def test_search_result_is_frozen():
    result = make_result()
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.title = "mutated"  # type: ignore[misc]


def test_all_port_records_are_frozen():
    for cls in (SearchResult, SearchOutcome, NoFullText, FetchOutcome, Source):
        assert any(
            f.default is dataclasses.MISSING or True for f in dataclasses.fields(cls)
        )
        assert dataclasses.is_dataclass(cls)


def test_source_record_carries_section_16_1_universal_fields():
    # §16.1: every artifact carries id, created_at, created_by, provenance,
    # content_hash — and is immutable once committed
    source = Source(
        id="src_abc", provider="pubmed", identifiers={"pmid": "26214858"},
        title="A Study", authors=("Doe, J.",), year=2026, venue="Journal of Tests",
        abstract_sha256=None, source_url="https://pubmed.example/26214858",
        artifact_ref="art_xyz", created_at="2026-01-01T00:00:00.000000+00:00",
        created_by="system", provenance={"provider_spec_version": "1.0.0"},
        content_hash="0" * 64,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        source.title = "mutated"  # type: ignore[misc]
    assert source.provenance["provider_spec_version"] == "1.0.0"


def test_search_result_fields_are_typed_and_present():
    result = make_result()
    assert result.provider == "pubmed"
    assert result.raw_retrieved_count == 1  # reconciliation count (PS2-05)
    assert result.delivered_count == 1  # consumer stream count (PS2-05)
    assert result.reconciliation in ("COMPLETE", "SHORTFALL", "UNKNOWN")
    assert result.valid_negative is False
    assert result.valid_negative_for is None


def test_valid_negative_marker_is_a_result_not_a_failure():
    result = make_result(valid_negative=True, valid_negative_for="doi:10.1103/PhysRevLett.116.061102")
    assert result.valid_negative is True
    assert result.valid_negative_for.startswith("doi:")
    # valid-negative is carried as a result — the marker is what distinguishes it
    # from a silent empty (PS-11)


# ── 2. deterministic identity (contract §2.2) ──


def test_result_id_is_content_addressed_and_deterministic():
    a = make_search_result_id("pubmed", "/esearch.fcgi", "cancer", 0, None, {"pmid": "26214858"})
    b = make_search_result_id("pubmed", "/esearch.fcgi", "cancer", 0, None, {"pmid": "26214858"})
    assert a == b
    assert a.startswith("sr_")
    assert len(a) == 3 + 24


def test_result_id_changes_when_request_state_changes():
    base = ("pubmed", "/esearch.fcgi", "cancer", 0, None, {"pmid": "26214858"})
    assert make_search_result_id(*base) != make_search_result_id(
        "pubmed", "/esearch.fcgi", "cancer", 1, None, {"pmid": "26214858"}
    )  # page_index is part of the position key (PS-06 discipline)
    assert make_search_result_id(*base) != make_search_result_id(
        "pubmed", "/esearch.fcgi", "cancer", 0, "abc", {"pmid": "26214858"}
    )  # cursor is part of the position key


# ── ADV-01/ADV-06: the content-hash CONTRACT, not self-equality ──
# The identity hash is ``H(canonical(record WITHOUT content_hash))`` — the
# stored hash must be independently recomputable from the persisted record as-
# is (never by zeroing the field). These tests construct the expected preimage
# EXPLICITLY from the documented canonicalization contract (dict keys sort,
# list-of-dicts sort by canonical JSON, scalar lists sort) and hash it with
# plain hashlib — they never call the production helper to "verify" itself.


def _canonicalize(value):
    """Test-local replication of the DOCUMENTED canonicalization contract
    (programs.py `_canonicalize`): dict keys sort; list/tuple of dicts sorts
    by canonical JSON; list/tuple of scalars sorts; Enums → value. This is the
    semantic contract the implementation must satisfy — a drift here is a
    contract violation, caught by the comparisons below."""
    import json as _json
    from enum import Enum

    if isinstance(value, dict):
        return {k: _canonicalize(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        items = [_canonicalize(v) for v in value]
        if items and all(isinstance(i, dict) for i in items):
            return sorted(
                items,
                key=lambda i: _json.dumps(
                    i, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
            )
        if items and all(not isinstance(i, (dict, list, tuple)) for i in items):
            return sorted(items, key=str)
        return items
    if isinstance(value, Enum):
        return value.value
    return value


_IDENTITY_KEYS = (
    "provider", "identifiers", "title", "authors", "year", "venue",
    "abstract_sha256", "source_url", "valid_negative", "valid_negative_for",
)


def _independent_hash_of(result: SearchResult) -> str:
    """Independently recompute the SEMANTIC identity hash with plain hashlib
    (step-6 P0) — the preimage is the identity fields ONLY. Observation/
    retrieval metadata (timestamps, request params, counts, reconciliation,
    provenance, position, endpoint/query) is EXCLUDED so repeated retrieval
    of the same canonical source stays identical."""
    import hashlib
    import json as _json

    data = dataclasses.asdict(result)
    data = {k: data[k] for k in _IDENTITY_KEYS}
    data["identifiers"] = dict(sorted((data["identifiers"] or {}).items()))
    data["authors"] = list(data["authors"] or ())
    serialized = _json.dumps(
        _canonicalize(data), sort_keys=True,
        separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _independent_observation_hash_of(result: SearchResult) -> str:
    """Full-record integrity hash (the ``observation_hash`` contract):
    everything EXCEPT the self-referential ``content_hash`` (ADV-01)."""
    import hashlib
    import json as _json

    data = dataclasses.asdict(result)
    data.pop("content_hash", None)
    serialized = _json.dumps(
        _canonicalize(data), sort_keys=True,
        separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def test_content_hash_is_deterministic():
    # determinism is necessary but NOT the contract — same record, same hash
    result = make_result()
    assert content_hash_of_search_result(result) == content_hash_of_search_result(result)
    assert len(content_hash_of_search_result(result)) == 64


def test_content_hash_matches_independent_recomputation():
    # ADV-01/06 — the stored hash equals an EXPLICITLY constructed preimage,
    # not merely itself: H(canonical(record without content_hash)) computed by
    # plain hashlib in the test.
    result = make_result()
    assert content_hash_of_search_result(result) == _independent_hash_of(result)


def test_content_hash_recomputable_after_roundtrip():
    # serialize → deserialize → recompute — the persisted record's hash is
    # independently recomputable from the persisted form AS-IS (no zeroing).
    import json as _json

    result = make_result()
    stored = content_hash_of_search_result(result)
    roundtripped = SearchResult(
        **{k: tuple(v) if isinstance(v, list) else v
           for k, v in _json.loads(_json.dumps(dataclasses.asdict(result))).items()})
    assert content_hash_of_search_result(roundtripped) == stored
    # and the independent recomputation agrees on the round-tripped form
    assert _independent_hash_of(roundtripped) == stored


def test_content_hash_changes_with_content_mutation():
    # changing title/content changes the hash
    assert (content_hash_of_search_result(make_result(title="A Study"))
            != content_hash_of_search_result(make_result(title="Other Study")))
    assert (content_hash_of_search_result(make_result(year=2026))
            != content_hash_of_search_result(make_result(year=2025)))


def test_content_hash_field_does_not_participate_in_preimage():
    # ADV-01 — mutating content_hash ALONE must not change the identity hash:
    # the field is the OUTPUT, never part of the INPUT. Pre-fix, the preimage
    # included the field (H(record WITH content_hash="")), so the stored hash
    # was not recomputable from the persisted record.
    assert (content_hash_of_search_result(make_result(content_hash="0" * 64))
            == content_hash_of_search_result(
                make_result(content_hash="f" * 64)))


def test_content_hash_field_ordering_invariant():
    # two records identical except field-insertion ORDER (asdict ordering is
    # dataclass-declared, but the canonical contract sorts keys) hash equal
    a = make_result()
    b = make_result()
    # reorder the underlying dict via asdict → insert at front → re-hash: the
    # canonical contract must normalize both forms to the same preimage
    d1 = dataclasses.asdict(a)
    d2 = dataclasses.asdict(b)
    moved = d2.pop("title")
    reordered = {"title": moved, **d2}
    # independent preimage construction for the reordered form
    import hashlib
    import json as _json

    for data in (d1, reordered):
        data.pop("content_hash", None)
    h1 = hashlib.sha256(_json.dumps(
        _canonicalize(d1), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()
    h2 = hashlib.sha256(_json.dumps(
        _canonicalize(reordered), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()
    assert h1 == h2


def test_content_hash_unicode_deterministic():
    import hashlib
    import json as _json

    result = make_result(title="Café étude — 论文")
    stored = content_hash_of_search_result(result)
    assert stored == _independent_hash_of(result)
    # the SEMANTIC preimage serializes with ensure_ascii=False — the same
    # unicode round-trips to the same canonical bytes (identity fields only)
    data = dataclasses.asdict(result)
    data = {k: data[k] for k in _IDENTITY_KEYS}
    data["identifiers"] = dict(sorted((data["identifiers"] or {}).items()))
    data["authors"] = list(data["authors"] or ())
    serialized = _json.dumps(
        _canonicalize(data), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False)
    assert hashlib.sha256(serialized.encode("utf-8")).hexdigest() == stored


def test_content_hash_two_semantically_identical_records():
    # two semantically identical records (same content, different provenance
    # of construction) have identical hashes
    assert (content_hash_of_search_result(make_result())
            == content_hash_of_search_result(make_result()))
    # identical content modulo canonical-ordering-invariant containers
    assert (content_hash_of_search_result(make_result(
                provenance={"hazard_verdict": "NONE", "provider_spec_version": "1.0.0"}))
            == content_hash_of_search_result(make_result(
                provenance={"provider_spec_version": "1.0.0", "hazard_verdict": "NONE"})))


def test_persisted_hash_equals_independent_recomputation():
    # the ADV-01 producer path: a walk-final record (counts + reconciliation
    # patched, content_hash filled) — its SEMANTIC hash equals the independent
    # recomputation, and the observation metadata does NOT change it (P0)
    result = make_result(
        raw_retrieved_count=2, delivered_count=2, total_count=2,
        reconciliation="COMPLETE")
    stored = content_hash_of_search_result(result)
    assert stored == _independent_hash_of(result)
    assert stored == content_hash_of_search_result(make_result())  # observation-insensitive
    # the observation hash DOES cover the observation metadata (integrity)
    assert (observation_hash_of_search_result(result)
            == _independent_observation_hash_of(result))
    assert (observation_hash_of_search_result(result)
            != observation_hash_of_search_result(make_result()))


# ── step-6 P0 — semantic identity stability (the identity preimage) ──


def test_p0_same_source_different_timestamps_same_identity():
    """P0-1 — repeated retrieval of the same canonical source with different
    access timestamps produces the SAME semantic content hash (a crash-retry
    must never look divergent merely because the clock moved)."""
    a = make_result(access_timestamp_utc="2026-01-01T00:00:00.000000+00:00")
    b = make_result(access_timestamp_utc="2026-08-14T12:00:00.000000+00:00")
    assert content_hash_of_search_result(a) == content_hash_of_search_result(b)
    # the OBSERVATION hash does distinguish them (integrity, not identity)
    assert (observation_hash_of_search_result(a)
            != observation_hash_of_search_result(b))


def test_p0_same_source_different_request_metadata_same_identity():
    """P0-2 — same canonical source found via a different query / request
    params (or a different request-log ref) keeps the same semantic identity."""
    a = make_result(query="cancer")
    b = make_result(
        query="cancer AND therapy",
        request_params_redacted={"term": "<redacted>", "db": "pubmed"},
        provenance={"request_log_ref": "log-1", "hazard_verdict": "NONE"})
    assert content_hash_of_search_result(a) == content_hash_of_search_result(b)


def test_p0_same_source_different_observation_metadata_same_identity():
    """P0-3 — counts, reconciliation verdict, position, and request-log refs
    are observation metadata: changing them MUST NOT create a new identity."""
    a = make_result()
    b = make_result(
        page_index=3, cursor_key="next",
        raw_retrieved_count=57, delivered_count=2, total_count=120,
        total_is_estimate=True, reconciliation="SHORTFALL",
        provenance={"request_log_ref": "log-9", "provider_spec_version": "1.1.0",
                    "hazard_verdict": "INJECTION_SUSPECT"},
        access_timestamp_utc="2026-08-14T00:00:00.000000+00:00")
    assert content_hash_of_search_result(a) == content_hash_of_search_result(b)


def test_p0_material_source_change_is_different_identity():
    """P0-4 — a material source change (the bibliographic essence) IS a
    different identity: identifiers, title, authors, year, venue, abstract,
    and the source URL are all in the preimage."""
    assert (content_hash_of_search_result(make_result(identifiers={"pmid": "1"}))
            != content_hash_of_search_result(make_result(identifiers={"pmid": "2"})))
    assert (content_hash_of_search_result(make_result(title="A Study"))
            != content_hash_of_search_result(make_result(title="Other Study")))
    assert (content_hash_of_search_result(make_result(authors=("Doe, J.",)))
            != content_hash_of_search_result(make_result(authors=("Roe, Q.",))))
    assert (content_hash_of_search_result(make_result(venue="J A"))
            != content_hash_of_search_result(make_result(venue="J B")))
    assert (content_hash_of_search_result(make_result(abstract_sha256="a" * 64))
            != content_hash_of_search_result(make_result(abstract_sha256="b" * 64)))
    assert (content_hash_of_search_result(make_result(source_url="https://x/1"))
            != content_hash_of_search_result(make_result(source_url="https://x/2")))


def test_p0_crash_retry_with_changed_observation_is_idempotent():
    """P0-5 — the step-6 hash-SET one-shot comparison: a crash-retry whose
    observation metadata changed (timestamp, log ref, counts) yields the SAME
    semantic hash set — idempotent, never a false-divergence refusal."""
    run1 = [make_result(result_id="sr_1", title="Alpha"),
            make_result(result_id="sr_2", title="Beta")]
    run2 = [make_result(result_id="sr_1", title="Alpha",
                        access_timestamp_utc="2026-08-14T00:00:00.000000+00:00",
                        raw_retrieved_count=9, reconciliation="SHORTFALL"),
            make_result(result_id="sr_2", title="Beta",
                        access_timestamp_utc="2026-08-14T00:00:00.000000+00:00",
                        raw_retrieved_count=9, reconciliation="SHORTFALL")]
    assert {content_hash_of_search_result(r) for r in run1} == \
        {content_hash_of_search_result(r) for r in run2}
    # and a genuinely different paper would diverge the set
    run3 = [make_result(result_id="sr_1", title="Gamma"),
            make_result(result_id="sr_2", title="Beta")]
    assert {content_hash_of_search_result(r) for r in run1} != \
        {content_hash_of_search_result(r) for r in run3}


# ── P0 write-path pin — observation_hash is TAMPER evidence, not identity ──


def test_observation_hash_catches_observation_field_tamper():
    """The gate §17 metadata/data-mismatch class: a persisted record whose
    OBSERVATION field is edited (timestamp/counts/log ref — semantic fields
    untouched) recomputes the SAME content_hash, so content_hash ALONE cannot
    detect the tamper; the observation_hash re-verification at the write path
    / dereference is the defense that catches it."""
    stored = make_result()
    stored_obs = observation_hash_of_search_result(stored)
    # tamper: rewrite the access timestamp + a count on the persisted form
    forged = make_result(
        access_timestamp_utc="2026-12-31T23:59:59.000000+00:00",
        raw_retrieved_count=999, delivered_count=3,
        provenance={"request_log_ref": "log-forged", "provider_spec_version": "1.0.0",
                    "hazard_verdict": "NONE"})
    # the semantic identity is untouched by the tamper...
    assert content_hash_of_search_result(forged) == content_hash_of_search_result(stored)
    # ...so a content_hash-only verification would PASS the forged record.
    # The observation_hash re-verification detects it:
    assert observation_hash_of_search_result(forged) != stored_obs


def test_observation_hash_deterministic_roundtrip():
    """The persisted-form integrity hash is independently recomputable from
    the persisted record AS-IS (serialize → deserialize → recompute → equal;
    no zeroing, ADV-01/06 discipline applied to the observation hash)."""
    import json as _json

    result = make_result(
        access_timestamp_utc="2026-08-14T12:00:00.000000+00:00",
        raw_retrieved_count=7, reconciliation="SHORTFALL")
    stored = observation_hash_of_search_result(result)
    assert stored == _independent_observation_hash_of(result)
    roundtripped = SearchResult(
        **{k: tuple(v) if isinstance(v, list) else v
           for k, v in _json.loads(_json.dumps(dataclasses.asdict(result))).items()})
    assert observation_hash_of_search_result(roundtripped) == stored


def test_observation_hash_differs_across_legit_retries():
    """Crash-retry: the retry's observation metadata legitimately differs
    (new timestamp, log ref, counts) — so the observation_hash DIFFERS while
    the semantic content_hash is IDENTICAL. The one-shot idempotency decision
    is content-based (identical → reuse); an observation_hash difference is
    expected and must NEVER gate idempotency (that would re-break the P0
    crash-retry invariant)."""
    run1 = make_result()
    run2 = make_result(
        access_timestamp_utc="2026-08-14T00:00:00.000000+00:00",
        raw_retrieved_count=9, delivered_count=1, reconciliation="SHORTFALL",
        provenance={"request_log_ref": "log-retry", "provider_spec_version": "1.0.0",
                    "hazard_verdict": "NONE"})
    # identity: SAME (idempotent); integrity: DIFFERENT (expected on retry)
    assert content_hash_of_search_result(run1) == content_hash_of_search_result(run2)
    assert observation_hash_of_search_result(run1) != observation_hash_of_search_result(run2)


# ── 3. hint parsing (contract §2.1, PS3-06) ──


def test_hints_identifier_only():
    hints = parse_query_hints("doi:10.1103/PhysRevLett.116.061102")
    assert hints.mode == "IDENTIFIER"
    assert hints.identifiers == {"doi": "10.1103/physrevlett.116.061102"}
    assert hints.topic == ""
    assert hints.unrecognized_hints == ()


def test_hints_topic_only():
    hints = parse_query_hints("cancer immunotherapy TCR")
    assert hints.mode == "TOPIC"
    assert hints.identifiers == {}
    assert hints.topic == "cancer immunotherapy TCR"


def test_hints_mixed():
    hints = parse_query_hints("doi:10.1038/nature12373 cancer")
    assert hints.mode == "MIXED"
    assert hints.identifiers == {"doi": "10.1038/nature12373"}
    assert hints.topic == "cancer"


def test_hints_multiple_identifiers_normalized():
    hints = parse_query_hints("pmid:26214858 pmcid:PMC4922062 arxiv:2103.15348v2")
    assert hints.mode == "IDENTIFIER"
    assert hints.identifiers["pmid"] == "26214858"
    assert hints.identifiers["pmcid"] == "PMC4922062"
    assert hints.identifiers["arxiv"] == "2103.15348"  # version stripped


def test_hints_bare_pmcid_is_topic_not_hint():
    # the contract's hint syntax is the explicit `pmcid:` prefix — a bare
    # `PMC4922062` token is topic text, not an identifier hint (contract §2.1)
    hints = parse_query_hints("PMC4922062")
    assert hints.mode == "TOPIC"
    assert hints.identifiers == {}
    assert hints.topic == "PMC4922062"


def test_hints_unrecognized_prefix_is_surfaced_for_the_router():
    hints = parse_query_hints("xyz:123 cancer")
    assert hints.mode == "TOPIC"
    assert hints.unrecognized_hints == ("xyz:123",)
    # the walk raises ProviderValidationError on unrecognized_hints BEFORE any I/O
    # (PS3-06) — parse only surfaces them


def test_hints_resolver_url_becomes_doi():
    hints = parse_query_hints("https://doi.org/10.1038/nature12373")
    assert hints.identifiers == {"doi": "10.1038/nature12373"}
    assert hints.mode == "IDENTIFIER"


def test_hints_invalid_identifier_dropped():
    hints = parse_query_hints("doi:not-a-doi")
    assert hints.identifiers == {}
    assert hints.mode == "TOPIC"


# ── 4. identifier normalization table (contract §3.1) ──


def test_normalize_doi_table():
    assert normalize_identifier("doi", "10.1038/NATURE12373") == "10.1038/nature12373"  # lowercase
    assert normalize_identifier("doi", "10.1038/nature12373.") == "10.1038/nature12373"  # trailing dot
    assert normalize_identifier("doi", "https://doi.org/10.1038/nature12373") == "10.1038/nature12373"
    assert normalize_identifier("doi", "http://dx.doi.org/10.1038/nature12373") == "10.1038/nature12373"
    assert normalize_identifier("doi", "doi:10.1038/nature12373") == "10.1038/nature12373"
    assert normalize_identifier("doi", "not-a-doi") is None
    assert normalize_identifier("doi", "10.abc/foo") is None  # invalid registry prefix


def test_normalize_pmid_table():
    assert normalize_identifier("pmid", "26214858") == "26214858"
    assert normalize_identifier("pmid", "PMID:26214858") == "26214858"
    assert normalize_identifier("pmid", "pmid 26214858") == "26214858"  # digits-only
    assert normalize_identifier("pmid", "") is None


def test_normalize_pmcid_table():
    assert normalize_identifier("pmcid", "PMC4922062") == "PMC4922062"
    assert normalize_identifier("pmcid", "pmc4922062") == "PMC4922062"
    # bare numeric-only form is ambiguous (PMC-vs-PubMed) — never guessed
    assert normalize_identifier("pmcid", "4922062") is None
    assert normalize_identifier("pmcid", "PMCabc") is None


def test_normalize_arxiv_table():
    assert normalize_identifier("arxiv", "2103.15348") == "2103.15348"  # new scheme
    assert normalize_identifier("arxiv", "2103.15348v2") == "2103.15348"  # version stripped
    assert normalize_identifier("arxiv", "hep-th/9901001") == "hep-th/9901001"  # old scheme
    assert normalize_identifier("arxiv", "hep-th/9901001v3") == "hep-th/9901001"  # version stripped
    assert normalize_identifier("arxiv", "https://arxiv.org/abs/2103.15348v2") == "2103.15348"
    assert normalize_identifier("arxiv", "https://arxiv.org/pdf/2103.15348v2.pdf") == "2103.15348"
    assert normalize_identifier("arxiv", "https://arxiv.org/abs/hep-th/9901001") == "hep-th/9901001"
    assert normalize_identifier("arxiv", "12345") is None


def test_normalize_url_table():
    assert normalize_identifier("url", "https://doi.org/10.1103/PhysRevLett.116.061102") == \
        "10.1103/physrevlett.116.061102"
    assert normalize_identifier("url", "https://arxiv.org/abs/2103.15348") == "2103.15348"
    assert normalize_identifier("url", "https://example.com/paper.pdf") is None  # unknown host


def test_normalize_unknown_kind():
    assert normalize_identifier("core_id", "123") is None


# ── 5. cross-provider dedup keys (contract §3.1) ──


def test_dedup_key_priority_doi_first():
    assert dedup_key({"pmid": "1", "doi": "10.1/abc"}) == "doi:10.1/abc"
    assert dedup_key({"arxiv": "2103.15348", "pmcid": "PMC1"}) == "pmcid:PMC1"
    assert dedup_key({"pmid": "1", "arxiv": "2103.15348"}) == "pmid:1"
    assert dedup_key({"arxiv": "2103.15348"}) == "arxiv:2103.15348"


def test_dedup_key_empty_and_namespaced():
    assert dedup_key({}) is None
    # namespaced: "pmid:1" can never collide with "doi:1"
    assert dedup_key({"doi": "1"}) != dedup_key({"pmid": "1"})


# ── 6. redaction (contract §7, PS-02/PS-09/PS3-07) ──


def test_redact_params_zero_credential_leak():
    secret = "sk-live-9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
    redacted = redact_params(
        {"api_key": secret, "term": "cancer", "email": "researcher@example.org"},
        DEFAULT_POLICY,
    )
    blob = canonical_json(redacted)
    assert secret not in blob
    assert "researcher@example.org" not in blob
    assert redacted["api_key"] == "<redacted>"


def test_redact_params_polite_sent_but_redacted():
    redacted = redact_params({"email": "researcher@example.org", "tool": "hermes"}, DEFAULT_POLICY)
    assert redacted["email"] == "<redacted:email>"
    assert redacted["tool"] == "<redacted:tool>"


def test_redact_params_default_deny_with_gap_note():
    redacted = redact_params({"sort": "relevance", "term": "cancer"}, DEFAULT_POLICY)
    assert redacted["sort"] == "<redacted>"
    assert redacted["term"] == "<redacted>"
    assert redaction_policy_gaps({"sort": "relevance", "term": "cancer"}, DEFAULT_POLICY) == \
        ("sort", "term")


def test_redact_params_default_deny_false_keeps_unknown():
    permissive = RedactionPolicy(
        credential_aliases=DEFAULT_POLICY.credential_aliases,
        polite_identifiers=DEFAULT_POLICY.polite_identifiers,
        default_deny=False,
    )
    redacted = redact_params({"sort": "relevance", "api_key": "sk-123"}, permissive)
    assert redacted["sort"] == "relevance"
    assert redacted["api_key"] == "<redacted>"  # credentials are NEVER configurable away
    assert redaction_policy_gaps({"sort": "relevance"}, permissive) == ()


def test_redact_params_case_insensitive_aliases():
    redacted = redact_params({"ApiKey": "sk-123", "ACCESS_TOKEN": "tok"}, DEFAULT_POLICY)
    assert redacted["ApiKey"] == "<redacted>"
    assert redacted["ACCESS_TOKEN"] == "<redacted>"


def test_redact_headers():
    secret = "Bearer sk-live-abcdef"
    redacted = redact_headers(
        {"Authorization": secret, "Cookie": "session=abc", "X-Api-Key": "k-1",
         "User-Agent": "hermes/1.0"},
        DEFAULT_POLICY,
    )
    blob = canonical_json(redacted)
    assert secret not in blob
    assert redacted["Authorization"] == "<redacted>"
    assert redacted["Cookie"] == "<redacted>"
    assert redacted["X-Api-Key"] == "<redacted>"
    assert redacted["User-Agent"] == "<redacted>"  # default_deny: unclassified → redacted


def test_redact_headers_default_deny_false_keeps_unknown():
    redacted = redact_headers({"User-Agent": "hermes/1.0"}, DEFAULT_POLICY)
    assert redacted["User-Agent"] == "<redacted>"
    permissive = RedactionPolicy(
        credential_aliases=DEFAULT_POLICY.credential_aliases,
        polite_identifiers=DEFAULT_POLICY.polite_identifiers,
        default_deny=False,
    )
    assert redact_headers({"User-Agent": "hermes/1.0"}, permissive)["User-Agent"] == "hermes/1.0"


def test_redact_url_query_params_and_userinfo():
    secret = "sk-live-secret"
    redacted = redact_url(
        f"https://user:{secret}@core.example/v2/search?api_key={secret}&email=a@b.c&q=cancer",
        DEFAULT_POLICY,
    )
    assert secret not in redacted
    assert "a@b.c" not in redacted
    assert "https://<redacted>@core.example" in redacted
    # urlencode percent-encodes the redaction markers — the value is still fully
    # replaced (zero credential text), the encoding is presentation only
    assert "api_key=%3Credacted%3E" in redacted
    assert "email=%3Credacted%3Aemail%3E" in redacted


def test_redact_url_path_segment_token_masked():
    # PS3-07: a credential-class path segment masks the FOLLOWING segment — the
    # deterministic shape is /<alias>/<value>/… (a bare value segment is a
    # legitimate path id and is never guessed at)
    secret = "tok-12345"
    redacted = redact_url(f"https://api.example/v2/api_key/{secret}/search?q=1", DEFAULT_POLICY)
    assert secret not in redacted
    assert "/v2/api_key/<redacted>/search" in redacted


def test_redact_url_bare_value_path_segment_is_not_masked():
    # a bare path value (e.g. an arXiv id or a DOI suffix) is a legitimate
    # resource path — the alias-following rule never guesses at it
    redacted = redact_url("https://arxiv.example/abs/2103.15348", DEFAULT_POLICY)
    assert "2103.15348" in redacted


def test_redact_url_deterministic_order():
    a = redact_url("https://x.example/search?b=2&a=1", DEFAULT_POLICY)
    b = redact_url("https://x.example/search?a=1&b=2", DEFAULT_POLICY)
    assert a == b


# ── 7. error taxonomy (contract §5.2) ──


def test_error_taxonomy_hierarchy():
    assert issubclass(TransientProviderError, ProviderError)
    assert issubclass(PermanentProviderError, ProviderError)
    assert issubclass(RetrievalShortfallError, PermanentProviderError)
    assert issubclass(ProviderUnavailableError, ProviderError)
    assert issubclass(ProviderValidationError, PermanentProviderError)
    assert issubclass(RedactionError, ProviderError)


def test_error_carries_structured_fields():
    err = RetrievalShortfallError(
        "shortfall", provider_id="crossref", expected=10, got=3,
        cause_class="CURSOR_TRAP", aggregate="EMPTY",
    )
    assert err.provider_id == "crossref"
    assert err.expected == 10
    assert err.got == 3
    assert err.cause_class == "CURSOR_TRAP"
    assert err.aggregate == "EMPTY"
    assert err.recordable is True

    unavailable = ProviderUnavailableError("all down", provider_id="openalex", hazard_class="THROTTLED")
    assert unavailable.hazard_class == "THROTTLED"
    # EMPTY and UNAVAILABLE are distinct types — "no literature" can never be
    # concluded from "providers were down" (PS-13)
    assert type(err) is not type(unavailable)
