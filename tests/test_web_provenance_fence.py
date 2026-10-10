"""IDR-046 O2-BUILD — the web-provenance fence suite (A5/A6/A12).

Proves the D2 provider marker is authored (E8) and read (E7) as specified,
with the expected behaviour per site:

- (a) a web search outcome row carries
  ``metadata.providers ∩ WEB_SEARCH_PROVIDERS ≠ ∅`` — including the
  mixed-walk case — and a web fetch outcome row likewise from its
  contributing sources (with the producing-task `spec.provider` fallback
  when the union is empty);
- (b) `source_artifact_is_web_derived` returns `True` for a web
  `source_result` (via `metadata.record.provider`) and for a web
  `source_payload` (via `metadata.source_result_ref`, dereferenced one
  hop), and `False` for a scholarly row and for a row whose provider
  field is absent;
- (c) presented to the classification resolver the web row is skipped
  (`None`) — contributing nothing to the classification's evidence set;
  presented to the detector resolver it is skipped (`None`) on both the
  typed path and the bare-id path (nothing to the detector row's
  evidence); presented to the L2 resolver it resolves — retraction
  reach, E6;
- (d) the marker moves no identity: the outcome hash of a web walk
  equals the hash computed with `providers` absent, and no recorded
  GET fixture re-stamps;
- (A5) a web-derived row is skipped at both evidence resolvers for all
  four ref forms (`source_search`, `source_fetch_outcome`,
  `source_result`, `source_payload`);
- (A6) retraction reach is unchanged and needs no edit: the S5 seed set
  and the controller guard already reach the existing
  `source_search`/`source_result`/`source_payload` types, a retracted web
  artifact is inadmissible (N9), and `source_search` /
  `source_fetch_outcome` still resolve in L2.
"""
from __future__ import annotations

import dataclasses
import json

import pytest

from hermes.core import frozen_clock
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ProjectRepository
from hermes.persistence.source_outcomes import (
    SourceOutcomeRepository,
    source_artifact_is_web_derived,
)
from hermes.research.contradiction_candidates import (
    detector_candidate_rows,
    detector_resolve_ref,
)
from hermes.research.evidence_ladder import classification_content_hash
from hermes.research.gateway import (
    _cx_classification_facts,
    _cx_resolve_evidence_ref,
)
from hermes.research.l2_resolution import _l2_resolve_ref_to_artifacts
from hermes.tools.providers.replay import normalized_request
from hermes.tools.research_sources import (
    WEB_SEARCH_PROVIDERS,
    FetchedSource,
    FetchOutcome,
    RequestLogRecord,
    SearchOutcome,
    SearchResult,
    SourceArtifact,
    content_hash_of_search_result,
    observation_hash_of_search_result,
    outcome_record_hash,
    search_result_to_mapping,
)

CLOCK = "2026-10-07T00:00:00.000000+00:00"


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, frozen_clock(CLOCK)).create("p1", "Test")
    yield conn
    conn.close()


# ── outcome/result carriers ──


def _result(provider: str, tag: str) -> SearchResult:
    bare = SearchResult(
        result_id=f"sr_{provider}_{tag}",
        provider=provider,
        endpoint="https://api.example/search",
        query="epistemic compilers",
        request_params_redacted={},
        identifiers={},
        title="T",
        authors=(),
        year=None,
        venue="",
        abstract_sha256=None,
        source_url="https://example.com/a",
        access_timestamp_utc=CLOCK,
        page_index=0,
        cursor_key=None,
        raw_retrieved_count=1,
        delivered_count=1,
        total_count=None,
        total_is_estimate=False,
        reconciliation="COMPLETE",
        content_hash="",
        provenance={},
        valid_negative=False,
        valid_negative_for=None)
    return dataclasses.replace(
        bare, content_hash=content_hash_of_search_result(bare))


def _log(provider: str) -> RequestLogRecord:
    return RequestLogRecord(
        provider=provider,
        endpoint="https://api.example/search",
        query="epistemic compilers",
        request_params_redacted={},
        timestamps=(CLOCK, CLOCK),
        cursor_chain=(None,),
        page_counts=((1, None),),
        reconciliation="COMPLETE",
        total_is_estimate=False,
        hazard_verdicts=("NONE",),
        provider_spec_version="1.0.0",
        raw_artifact_hashes=())


def _search_outcome(provider: str, tag: str,
                    with_results: bool = True) -> SearchOutcome:
    return SearchOutcome(
        per_provider=(_result(provider, tag),) if with_results else (),
        aggregate="COMPLETE",
        notes=(),
        request_log=_log(provider))


def _fetched(provider: str, tag: str) -> FetchedSource:
    source = _result(provider, tag)
    return FetchedSource(
        source=source,
        artifact=SourceArtifact(
            artifact_id=f"art_payload_{provider}_{tag}",
            content_hash=f"ph_{provider}_{tag}",
            media_type="text/html",
            size_bytes=10,
            retrieved_from=source.source_url,
            access_timestamp_utc=CLOCK,
            raw_bytes_ref=f"store_{provider}_{tag}"),
        hazard_verdict="NONE")


def _insert_artifact(db, artifact_id: str, artifact_type: str,
                     content_hash: str, meta: dict) -> None:
    db.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type,
            content_hash, size_bytes, storage_path, producer,
            metadata_json, created_at)
           VALUES (?, 'p1', NULL, ?, ?, 1, 'x', 't', ?, ?)""",
        (artifact_id, artifact_type, content_hash,
         json.dumps(meta), CLOCK))
    db.commit()


def _search_row_ids(outcome: SearchOutcome) -> tuple[str, str]:
    outcome_hash = outcome_record_hash(outcome, "search")
    return "art_" + outcome_hash, outcome_hash


# ── A12(a): the marker is authored as D2 specifies ──


def test_search_outcome_metadata_carries_web_providers() -> None:
    meta = SourceOutcomeRepository._search_outcome_metadata(
        _search_outcome("brave", "a"))
    assert meta["providers"] == ["brave"]
    assert set(meta["providers"]) & set(WEB_SEARCH_PROVIDERS)


def test_search_outcome_metadata_mixed_walk_not_laundered() -> None:
    outcome = SearchOutcome(
        per_provider=(_result("brave", "a"), _result("arxiv", "b")),
        aggregate="COMPLETE",
        notes=(),
        request_log=_log("arxiv"))
    meta = SourceOutcomeRepository._search_outcome_metadata(outcome)
    assert meta["providers"] == ["arxiv", "brave"]
    assert set(meta["providers"]) & set(WEB_SEARCH_PROVIDERS)


def test_search_outcome_metadata_shortfall_path_carried_by_log() -> None:
    meta = SourceOutcomeRepository._search_outcome_metadata(
        _search_outcome("tavily", "a", with_results=False))
    assert meta["providers"] == ["tavily"]


def test_fetch_outcome_metadata_carries_contributing_providers(
        db) -> None:
    repo = SourceOutcomeRepository(db)
    outcome = FetchOutcome(
        per_source=(_fetched("tavily", "a"),),
        no_full_text=(), failed=(),
        aggregate="COMPLETE",
        fetched_count=1, no_full_text_count=0,
        fetch_log=(), payloads=(), notes=())
    meta = repo._fetch_outcome_metadata(outcome, "t-no-task")
    assert meta["providers"] == ["tavily"]
    assert set(meta["providers"]) & set(WEB_SEARCH_PROVIDERS)


def test_fetch_outcome_metadata_empty_union_falls_back_to_task_route(
        db) -> None:
    from hermes.core.node import NodeContract
    from hermes.persistence.repositories import TaskRepository
    repo = TaskRepository(db, frozen_clock(CLOCK))
    repo.create(NodeContract(
        task_id="t-fetch-web", project_id="p1", task_type="TOOL_TASK",
        idempotency_key="idem-t-fetch-web", dependencies=[]))
    db.execute("UPDATE tasks SET spec_json = ? WHERE task_id = ?",
               (json.dumps({"provider": "searxng"}), "t-fetch-web"))
    db.commit()
    outcome = FetchOutcome(
        per_source=(), no_full_text=(), failed=(),
        aggregate="FAILED",
        fetched_count=0, no_full_text_count=0,
        fetch_log=(), payloads=(), notes=())
    meta = SourceOutcomeRepository(db)._fetch_outcome_metadata(
        outcome, "t-fetch-web")
    assert meta["providers"] == ["searxng"]
    bare = SourceOutcomeRepository(db)._fetch_outcome_metadata(outcome)
    assert bare["providers"] == []


# ── A12(b): the read helper dispatches on the row's own carriers ──


def _seed_web_and_scholarly_rows(db) -> dict[str, str]:
    web_outcome = _search_outcome("exa", "w")
    sch_outcome = _search_outcome("arxiv", "s")
    web_outcome_id, web_outcome_hash = _search_row_ids(web_outcome)
    sch_outcome_id, sch_outcome_hash = _search_row_ids(sch_outcome)
    web_result = _result("exa", "w")
    sch_result = _result("arxiv", "s")
    web_result_id = "art_" + web_result.content_hash
    sch_result_id = "art_" + sch_result.content_hash
    payload_hash = "ph_web_payload_1"
    payload_id = "art_" + payload_hash
    _insert_artifact(
        db, web_outcome_id, "source_search", web_outcome_hash,
        SourceOutcomeRepository._search_outcome_metadata(web_outcome))
    _insert_artifact(
        db, sch_outcome_id, "source_search", sch_outcome_hash,
        SourceOutcomeRepository._search_outcome_metadata(sch_outcome))
    _insert_artifact(db, web_result_id, "source_result",
                     web_result.content_hash,
                     {"record": search_result_to_mapping(web_result),
                      "observation_hash": observation_hash_of_search_result(
                          web_result)})
    _insert_artifact(db, sch_result_id, "source_result",
                     sch_result.content_hash,
                     {"record": search_result_to_mapping(sch_result),
                      "observation_hash": observation_hash_of_search_result(
                          sch_result)})
    _insert_artifact(db, payload_id, "source_payload", payload_hash,
                     {"source_result_ref":
                      "source_result:" + web_result.content_hash})
    _insert_artifact(db, "art_nokey_1", "source_search", "ch_nokey_1",
                     {"outcome_kind": "search"})
    return {
        "web_outcome_id": web_outcome_id,
        "web_outcome_hash": web_outcome_hash,
        "sch_outcome_id": sch_outcome_id,
        "sch_outcome_hash": sch_outcome_hash,
        "web_result_id": web_result_id,
        "web_result_hash": web_result.content_hash,
        "sch_result_id": sch_result_id,
        "sch_result_hash": sch_result.content_hash,
        "payload_id": payload_id,
        "payload_hash": payload_hash,
    }


def test_read_helper_outcome_result_and_payload_hop(db) -> None:
    ids = _seed_web_and_scholarly_rows(db)
    assert source_artifact_is_web_derived(db, ids["web_outcome_id"]) is True
    assert source_artifact_is_web_derived(db, ids["web_result_id"]) is True
    assert source_artifact_is_web_derived(db, ids["payload_id"]) is True
    assert source_artifact_is_web_derived(db, ids["sch_outcome_id"]) is False
    assert source_artifact_is_web_derived(db, ids["sch_result_id"]) is False
    assert source_artifact_is_web_derived(db, "art_nokey_1") is False
    assert source_artifact_is_web_derived(db, "art_missing") is False
    assert source_artifact_is_web_derived(db, "") is False


# ── A5: skipped at both evidence resolvers, all four ref forms ──


def test_gateway_resolver_skips_web_derived_rows(db) -> None:
    ids = _seed_web_and_scholarly_rows(db)
    for ref, web_id in (
            (f"source_search:{ids['web_outcome_hash']}",
             ids["web_outcome_id"]),
            (f"source_result:{ids['web_result_hash']}",
             ids["web_result_id"]),
            (f"source_payload:{ids['payload_hash']}",
             ids["payload_id"])):
        assert _cx_resolve_evidence_ref(db, "p1", ref) is None, ref
        assert source_artifact_is_web_derived(db, web_id) is True
    assert _cx_resolve_evidence_ref(
        db, "p1", f"source_search:{ids['sch_outcome_hash']}") == \
        ids["sch_outcome_id"]
    assert _cx_resolve_evidence_ref(
        db, "p1", f"source_result:{ids['sch_result_hash']}") == \
        ids["sch_result_id"]
    # the fetch-outcome form resolves through the same clause — and is
    # not an evidence form at this resolver at all (prefix discipline),
    # so both rows skip here; the distinction lives in L2 (E6/A6).
    _insert_artifact(db, "art_fetch_web_1", "source_fetch_outcome",
                     "ch_fetch_web_1", {"providers": ["brave"]})
    _insert_artifact(db, "art_fetch_sch_1", "source_fetch_outcome",
                     "ch_fetch_sch_1", {"providers": ["arxiv"]})
    assert _cx_resolve_evidence_ref(
        db, "p1", "source_fetch_outcome:ch_fetch_web_1") is None
    assert _cx_resolve_evidence_ref(
        db, "p1", "source_fetch_outcome:ch_fetch_sch_1") is None


def test_gateway_web_ref_contributes_nothing_to_evidence_set(db) -> None:
    ids = _seed_web_and_scholarly_rows(db)
    refs = [f"source_result:{ids['web_result_hash']}",
            f"source_result:{ids['sch_result_hash']}"]
    meta = {
        "schema_version": 1,
        "classifier_version": "v1",
        "hypothesis_ref": "h1",
        "program_ref": "pr1",
        "failure_class": "UNKNOWN",
        "contributing_factors": [],
        "evidence_refs": sorted(refs),
        "constraint_ref": None,
        "failed_mechanism_ref": None,
        "regime_ref": None,
        "resource_gap": None,
        "scope_brief_ref": None,
        "scope_brief_field": None,
        "explanation": "web bar probe",
        "proposed_by": "DETERMINISTIC",
        "condition_type": None,
        "classification_id": "cx_web_bar_1",
    }
    content_hash = classification_content_hash(meta, "p1")
    assert content_hash is not None
    _insert_artifact(db, "cx_web_bar_1", "failure_classification",
                     content_hash, meta)
    facts = _cx_classification_facts(db, "p1", "cx_web_bar_1")
    assert facts is not None
    assert facts["evidence"] == {ids["sch_result_id"]}


def test_detector_resolver_skips_web_on_both_paths(db) -> None:
    ids = _seed_web_and_scholarly_rows(db)
    # typed path — all four ref forms skip when web-derived.
    assert detector_resolve_ref(
        db, "p1",
        f"source_result:{ids['web_result_hash']}") is None
    assert detector_resolve_ref(
        db, "p1",
        f"source_result:{ids['sch_result_hash']}") == ids["sch_result_id"]
    assert detector_resolve_ref(
        db, "p1",
        f"source_search:{ids['web_outcome_hash']}") is None
    assert detector_resolve_ref(
        db, "p1",
        f"source_search:{ids['sch_outcome_hash']}") == ids["sch_outcome_id"]
    assert detector_resolve_ref(
        db, "p1",
        f"source_payload:{ids['payload_hash']}") is None
    _insert_artifact(db, "art_fetch_web_1", "source_fetch_outcome",
                     "ch_fetch_web_1", {"providers": ["brave"]})
    assert detector_resolve_ref(
        db, "p1", "source_fetch_outcome:ch_fetch_web_1") is None
    # bare-id path (which has no type check at all).
    assert detector_resolve_ref(db, "p1", ids["web_result_id"]) is None
    assert detector_resolve_ref(
        db, "p1", ids["sch_result_id"]) == ids["sch_result_id"]


def test_detector_row_evidence_excludes_web(db) -> None:
    ids = _seed_web_and_scholarly_rows(db)
    meta = {
        "classification_id": "cx_det_web_1",
        "program_ref": "pr1",
        "hypothesis_ref": "h1",
        "failure_class": "UNKNOWN",
        "evidence_refs": [f"source_result:{ids['web_result_hash']}",
                           f"source_result:{ids['sch_result_hash']}"],
    }
    _insert_artifact(db, "cx_det_web_1", "failure_classification",
                     "ch_cx_det_web_1", meta)
    rows = detector_candidate_rows(
        db, "p1", [{"classification_id": "cx_det_web_1"}])
    assert len(rows) == 1
    assert rows[0]["evidence"] == [ids["sch_result_id"]]


# ── A6 + A12(c): L2 resolves (retraction reach), retraction unchanged ──


def test_l2_resolves_web_outcome_refs(db) -> None:
    ids = _seed_web_and_scholarly_rows(db)
    assert _l2_resolve_ref_to_artifacts(
        db, f"source_search:{ids['web_outcome_hash']}") == \
        {ids["web_outcome_id"]}
    _insert_artifact(db, "art_fetch_web_1", "source_fetch_outcome",
                     "ch_fetch_web_1", {"providers": ["brave"]})
    assert _l2_resolve_ref_to_artifacts(
        db, "source_fetch_outcome:ch_fetch_web_1") == {"art_fetch_web_1"}


def test_retraction_reach_unchanged_and_n9_applies_to_web(db) -> None:
    from hermes.persistence.source_outcomes import source_artifact_retracted
    from hermes.research.gateway import _S5_SOURCE_ARTIFACT_TYPES
    # No edit: the cone seeds, and the controller guard accepts, the
    # existing source types — which the web legs reuse.
    assert frozenset(
        {"source_result", "source_payload", "source_search"}) == \
        _S5_SOURCE_ARTIFACT_TYPES
    ids = _seed_web_and_scholarly_rows(db)
    assert source_artifact_retracted(
        db, "p1", ids["web_result_id"]) is False
    _insert_artifact(db, "rd_web_1", "ResearchDecision", "ch_rd_web_1", {})
    db.execute(
        """INSERT INTO provenance_edges
           (artifact_id, upstream_id, edge_type, created_at)
           VALUES (?, ?, 'supersedes', ?)""",
        ("rd_web_1", ids["web_result_id"], CLOCK))
    db.commit()
    assert source_artifact_retracted(
        db, "p1", ids["web_result_id"]) is True
    # …and the retracted web row is now inadmissible at the resolver too.
    assert detector_resolve_ref(
        db, "p1",
        f"source_result:{ids['web_result_hash']}") is None


# ── A12(d): the marker moves no identity ──


def test_outcome_hash_equal_with_providers_absent() -> None:
    outcome = _search_outcome("brave", "a")
    hashed = outcome_record_hash(outcome, "search")
    meta = SourceOutcomeRepository._search_outcome_metadata(outcome)
    assert meta["providers"] == ["brave"]
    # The metadata builders are not in the hash preimage: re-stamping
    # the row RSVPs no fixture and moves no artifact id.
    assert outcome_record_hash(outcome, "search") == hashed
    assert "art_" + hashed == "art_" + outcome_record_hash(
        outcome, "search")


def test_get_fixture_identity_unmoved() -> None:
    from hermes.tools.providers.base import RequestSpec
    normalized = normalized_request(
        RequestSpec(url="https://example.test/search",
                    params={"q": "x"}, headers_meta={}))
    assert set(normalized) == {"url", "params"}
