"""HR-04 golden fixtures — source identifier capture at admission.

Pins the cheap half of scholarly lineage: stable bibliographic identifiers
are captured canonically at SOURCE admission, before any future lineage
reasoning exists. The invariant under test (brief §2):

    content_hash equality  ≠  scholarly independence
    different content_hash ≠  independent research study

The walk's single normalization choke point is
``canonicalize_identifiers`` (normalize.py, HR-04): every identifier map that
reaches a persisted ``SearchResult`` passes through it — the record-extraction
branch (``adapter.extract_ids``) and the valid-negative branch (hand-built
``spec.hints`` payloads that bypass ``parse_query_hints``). Acceptance tests
A–J from the HR-04 brief, plus the unit table for the canonicalizer itself.

No lineage graph, no independence scoring, no DOI resolver — identifier
preservation only (brief §17 path B).
"""
from __future__ import annotations

import dataclasses
import json

import pytest

from hermes.core.intents import Intent, IntentKind
from hermes.core.task_status import TaskStatus
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ProjectRepository, TaskRepository
from hermes.persistence.source_outcomes import (
    SourceOutcomeBindingError,
    SourceOutcomeIntegrityError,
    SourceOutcomeRepository,
)
from hermes.research.gateway import apply_intent
from hermes.research.source_templates import build_source_search_task_payload
from hermes.tools.providers.base import (
    Page,
    PageState,
    ProviderAdapter,
    ProviderContractCard,
    RateProfile,
    RequestSpec,
    TransportResponse,
    WalkRequest,
)
from hermes.tools.providers.hazards import SPEC_SCHEMA, load_hazard_spec
from hermes.tools.providers.normalize import (
    RetrievalHints,
    canonicalize_identifiers,
    parse_query_hints,
)
from hermes.tools.providers.paginate import combine, walk
from hermes.tools.research_sources import (
    PermanentProviderError,
    RequestLogRecord,
    SearchOutcome,
    SearchResult,
    content_hash_of_search_result,
    make_search_result_id,
    search_result_from_mapping,
    search_result_to_mapping,
)

# ── deterministic fakes (walk-test shape — self-contained per repo style) ──


class FakeTransport:
    def __init__(self, script: list[dict]) -> None:
        self._script = list(script)
        self.last: dict | None = None

    def request(self, spec: RequestSpec) -> TransportResponse:
        self.last = self._script.pop(0) if self._script else None
        if self.last is None:
            raise PermanentProviderError("no scripted response",
                                         hazard_class="MALFORMED_200")
        body = self.last.get("body")
        if body is None:
            body = {k: v for k, v in self.last.items()
                    if k not in ("status", "headers", "body")}
        raw = json.dumps(body).encode() if isinstance(body, dict) else (body or b"")
        return TransportResponse(status=self.last.get("status", 200), body=raw,
                                 headers=self.last.get("headers", {}))


class FakeAdapter(ProviderAdapter):
    """Passes every identifier-bearing record field straight through as a
    RAW identifier — exactly the shape a real adapter's ``extract_ids`` has
    before the walk's canonicalization choke point (HR-04)."""

    def __init__(self, transport: FakeTransport, provider_id: str = "arxiv") -> None:
        self.transport = transport
        self.contract = ProviderContractCard(
            provider_id=provider_id,
            base_url="https://fake.example/api",
            auth_policy="none",
            hint_routes={"doi": "lookup", "pmid": "lookup", "pmcid": "lookup",
                         "arxiv": "lookup", "url": "lookup"},
            pagination={"kind": "cursor", "page_size_cap": 100,
                        "max_pages": 50, "loop_guard": 100},
            hazard_spec_version="1.0.0",
            rate_profile=RateProfile(rps=1.0, burst=1, concurrency=1, daily_cap=1000),
            retry_class_map={},
        )

    def build_request(self, hints: RetrievalHints, state: PageState,
                      page_size: int) -> RequestSpec:
        return RequestSpec(url="https://fake.example/api/search",
                           params={"q": hints.topic or "lookup",
                                   "cursor": state.cursor or ""},
                           headers_meta={})

    def parse_page(self, payload: object, state: PageState) -> Page:
        entry = self.transport.last or {}
        records = tuple(entry.get("records", []))
        next_cursor = entry.get("next_cursor")
        next_state = (PageState(state.page_index + 1, cursor=next_cursor)
                      if next_cursor is not None else None)
        return Page(records=records, total=entry.get("total"),
                    next_state=next_state)

    def extract_ids(self, record: dict[str, object]) -> dict[str, str]:
        # A real adapter decides which fields are identifiers — including
        # provider-native kinds (openalex_id, core_id, …) that are NOT in the
        # walk's IDENTIFIER_KINDS dedup tuple. Pass through every string field
        # except the bibliographic `title` so native ids reach the walk's
        # canonicalization choke point (HR-04 acceptance F).
        return {k: str(v) for k, v in record.items()
                if k != "title" and isinstance(v, str) and v}

    def build_fetch_request(self, source) -> RequestSpec:  # pragma: no cover
        return RequestSpec(url="https://fake.example/api/fulltext",
                           params={}, headers_meta={})


class FakeLimiter:
    def acquire(self, provider: str) -> tuple[bool, str]:
        return True, ""

    def release(self, provider: str) -> None:
        pass

    def note_throttled(self, provider: str, retry_after: float | None) -> None:
        pass

    def last_denial_reason(self, provider: str) -> str:
        return ""


class FakeRecorder:
    def __init__(self) -> None:
        self.logs: list[RequestLogRecord] = []

    def record(self, log: RequestLogRecord) -> None:
        self.logs.append(log)


class FakeClock:
    def now_utc(self) -> str:
        return "2026-08-19T00:00:00Z"

    def monotonic(self) -> float:
        return 0.0

    def sleep(self, delay: float) -> None:
        pass


def fake_spec(provider_id: str = "arxiv"):
    return load_hazard_spec(provider_id, {
        "schema": SPEC_SCHEMA,
        "provider_id": provider_id,
        "version": "1.0.0",
        "markers": [],
        "empty_body_rule": "treat-as-failure",
        "error_field": None,
        "count_semantics": "exact",
        "counts_raw_rows": False,
        "required_fields": ["records"],
        "cursor_rule": {"kind": "cursor", "loop_guard": 100},
        "throttle_signature": [],
        "rewrite_suspect": [],
        "fetch": None,
        "valid_negative_statuses": [404],
    })


def page(*, records: list[dict] | None = None, total: int | None = None,
         next_cursor: str | None = None, status: int = 200) -> dict:
    return {"status": status, "records": records or [], "total": total,
            "next_cursor": next_cursor}


def run_walk(script: list[dict], hints: RetrievalHints,
             provider_id: str = "arxiv") -> SearchOutcome:
    transport = FakeTransport(script)
    adapter = FakeAdapter(transport, provider_id=provider_id)
    return walk(adapter, hints, WalkRequest(max_results=50), transport,
                FakeLimiter(), FakeRecorder(), FakeClock(),
                hazard_spec=fake_spec(provider_id))


def topic_hints() -> RetrievalHints:
    return parse_query_hints("epistemic compilers")


# ── unit table: canonicalize_identifiers (the single normalization path) ──


def test_canonicalize_doi_variants_converge():
    # brief §4 / acceptance C — every provider representation of one DOI
    # normalizes to one canonical value
    for raw in ("10.1038/NATURE12373",           # uppercase
                "doi:10.1038/nature12373",        # prefixed
                "https://doi.org/10.1038/nature12373",  # resolver URL
                "http://dx.doi.org/10.1038/nature12373",
                "10.1038/nature12373.",           # trailing dot
                " 10.1038/nature12373 "):         # whitespace
        assert canonicalize_identifiers({"doi": raw}) == \
            {"doi": "10.1038/nature12373"}, raw


def test_canonicalize_kind_key_is_case_insensitive():
    # a provider that upper-cases the KIND key cannot forge a second identity
    assert canonicalize_identifiers({"DOI": "10.1038/NATURE12373"}) == \
        {"doi": "10.1038/nature12373"}
    assert canonicalize_identifiers({"PMID": "PMID:26214858"}) == {"pmid": "26214858"}


def test_canonicalize_arxiv_version_stripped():
    assert canonicalize_identifiers({"arxiv": "2103.15348v2"}) == \
        {"arxiv": "2103.15348"}
    assert canonicalize_identifiers(
        {"arxiv": "https://arxiv.org/abs/hep-th/9901001v3"}) == \
        {"arxiv": "hep-th/9901001"}


def test_canonicalize_is_idempotent():
    # acceptance H prerequisite — normalizing an already-canonical map (the
    # parse_query_hints path) is a no-op, so both entry points converge
    raw = {"doi": "10.1038/NATURE12373", "pmid": "PMID:26214858",
           "arxiv": "2103.15348v2", "openalex_id": "W2741809807"}
    once = canonicalize_identifiers(raw)
    assert canonicalize_identifiers(once) == once


def test_canonicalize_provider_native_preserved_verbatim():
    # acceptance F — provider-native kinds are never parsed, coerced, or
    # mistaken for a universal identity
    ids = {"openalex_id": "W2741809807", "core_id": "82071694",
           "url": "https://example.com/paper.pdf"}
    assert canonicalize_identifiers(ids) == ids


def test_canonicalize_invalid_known_kind_dropped():
    # acceptance G — a malformed instance of a KNOWN kind is dropped
    # deterministically (storing it would forge a garbage identity)
    assert canonicalize_identifiers({"doi": "not-a-doi"}) == {}
    assert canonicalize_identifiers({"doi": "10.abc/foo"}) == {}
    assert canonicalize_identifiers({"pmcid": "4922062"}) == {}  # bare-number ambiguity
    # a valid sibling survives the drop
    assert canonicalize_identifiers({"doi": "not-a-doi", "pmid": "26214858"}) == \
        {"pmid": "26214858"}


# ── A. same DOI, same content → one identity ──


def test_a_same_doi_different_raw_forms_one_identity():
    # the same scholarly work reported by a provider in two raw DOI forms
    # normalizes to ONE identifier map and ONE semantic content hash
    out_upper = run_walk(
        [page(records=[{"doi": "10.1038/NATURE12373", "title": "T"}], total=1)],
        topic_hints())
    out_canon = run_walk(
        [page(records=[{"doi": "10.1038/nature12373", "title": "T"}], total=1)],
        topic_hints())
    r1, r2 = out_upper.per_provider[0], out_canon.per_provider[0]
    assert r1.identifiers == {"doi": "10.1038/nature12373"}
    assert r1.identifiers == r2.identifiers
    assert r1.content_hash == r2.content_hash  # one identity, not two


# ── B. same DOI, different provider, different content → distinct identities ──


def test_b_same_doi_different_provider_content_distinct():
    # brief §6 — same scholarly identifier ≠ same byte artifact: both
    # provenance observations are preserved with the shared identifier, and
    # the content identities remain DISTINCT (no automatic dedup)
    out_a = run_walk(
        [page(records=[{"doi": "10.1038/nature12373", "title": "Publisher PDF"}],
              total=1)],
        topic_hints(), provider_id="arxiv")
    out_b = run_walk(
        [page(records=[{"doi": "10.1038/nature12373", "title": "Preprint copy"}],
              total=1)],
        topic_hints(), provider_id="openalex")
    r1, r2 = out_a.per_provider[0], out_b.per_provider[0]
    assert r1.identifiers == r2.identifiers == {"doi": "10.1038/nature12373"}
    assert r1.provider != r2.provider
    assert r1.content_hash != r2.content_hash  # distinct byte/content identity
    # both survive the cross-provider combine — neither is deduplicated away
    combined = combine([out_a, out_b])
    assert len(combined.per_provider) == 2


# ── C. DOI formatting variants normalize identically (walk-level) ──


def test_c_doi_format_variants_identical_through_the_walk():
    variants = ("doi:10.1103/PhysRevLett.116.061102",
                "https://doi.org/10.1103/PhysRevLett.116.061102",
                "10.1103/PHYSREVLETT.116.061102.")
    hashes = set()
    for raw in variants:
        out = run_walk([page(records=[{"doi": raw, "title": "T"}], total=1)],
                       topic_hints())
        r = out.per_provider[0]
        assert r.identifiers == {"doi": "10.1103/physrevlett.116.061102"}
        hashes.add(r.content_hash)
    assert len(hashes) == 1  # all variants converge on one identity


# ── D. multiple identifiers all preserved ──


def test_d_multiple_identifiers_all_preserved():
    # brief §7 — a source may carry DOI + PMID + PMCID + arXiv simultaneously;
    # ALL recognized identifiers are preserved (no universal-identity pick),
    # each in canonical form, provider-native kinds verbatim
    out = run_walk([page(records=[{
        "doi": "10.1038/NATURE12373",
        "pmid": "PMID:26214858",
        "pmcid": "pmc4922062",
        "arxiv": "2103.15348v2",
        "title": "T",
    }], total=1)], topic_hints())
    r = out.per_provider[0]
    assert r.identifiers == {
        "doi": "10.1038/nature12373",
        "pmid": "26214858",
        "pmcid": "PMC4922062",
        "arxiv": "2103.15348",
    }
    # persistence round-trip preserves the full identifier set
    restored = search_result_from_mapping(search_result_to_mapping(r))
    assert restored.identifiers == r.identifiers
    assert content_hash_of_search_result(restored) == r.content_hash


# ── E. no DOI → source remains admissible ──


def test_e_missing_identifiers_source_still_admissible():
    # brief §8 — identifier absence means UNKNOWN LINEAGE, never an invalid
    # source: a url-only record is delivered (it simply participates in no
    # cross-provider dedup set)
    out = run_walk([page(records=[{
        "url": "https://example.com/working-paper.pdf", "title": "T",
    }], total=1)], topic_hints())
    assert out.aggregate == "COMPLETE"
    r = out.per_provider[0]
    assert r.identifiers == {"url": "https://example.com/working-paper.pdf"}
    assert not any("MALFORMED_ROW" in n for n in out.notes)


def test_e2_record_with_no_identifier_at_all_is_malformed_row():
    # the existing walk contract: a record with NO identifier field is a
    # MALFORMED_ROW note (skipped), never a walk failure — unchanged by HR-04
    out = run_walk([page(records=[{"title": "no ids"},
                                  {"doi": "10.1000/ok", "title": "T"}],
                         total=2)], topic_hints())
    assert any(n.startswith("MALFORMED_ROW") for n in out.notes)
    assert len(out.per_provider) == 1


# ── F. provider-native identifier preserved, not universal identity ──


def test_f_provider_native_identifier_not_universal_identity():
    # an openalex-only record is delivered with its native id VERBATIM, and
    # dedup_key refuses to treat it as a cross-provider identity
    out = run_walk([page(records=[{"openalex_id": "W2741809807", "title": "T"}],
                         total=1)], topic_hints())
    r = out.per_provider[0]
    assert r.identifiers == {"openalex_id": "W2741809807"}
    from hermes.tools.providers.normalize import dedup_key
    assert dedup_key(r.identifiers) is None  # no dedup set membership


# ── G. malformed identifier → deterministic documented behavior ──


def test_g_malformed_doi_dropped_deterministically():
    # a record whose ONLY identifier is a malformed known kind is dropped to
    # the MALFORMED_ROW path — deterministic, never a stored forged identity
    out = run_walk([page(records=[{"doi": "not-a-doi", "title": "T"}],
                         total=1)], topic_hints())
    assert len(out.per_provider) == 0
    assert any(n.startswith("MALFORMED_ROW") for n in out.notes)


def test_g2_whitespace_and_case_variants_are_not_forged_identities():
    # whitespace/case variants of one DOI collapse to one delivered record
    # via the dedup key — the second sighting is a dedup note, not a second
    # identity
    out = run_walk([page(records=[
        {"doi": "10.1038/NATURE12373", "title": "T"},
        {"doi": " 10.1038/nature12373 ", "title": "T"},
    ], total=2)], topic_hints())
    assert len(out.per_provider) == 1
    assert any("dedup" in n for n in out.notes)


# ── H. replay: identical input → identical normalized metadata ──


def test_h_replay_identical_normalized_metadata():
    script = [page(records=[{"doi": "10.1038/NATURE12373",
                             "pmid": "PMID:26214858", "title": "T"}], total=1)]
    r1 = run_walk(list(script), topic_hints()).per_provider[0]
    r2 = run_walk(list(script), topic_hints()).per_provider[0]
    assert r1.identifiers == r2.identifiers
    assert r1.result_id == r2.result_id
    assert r1.content_hash == r2.content_hash


# ── I. cross-provider observations preserve provenance ──


def test_i_cross_provider_provenance_preserved():
    out_a = run_walk([page(records=[{"doi": "10.1000/shared", "title": "A"}],
                           total=1)], topic_hints(), provider_id="arxiv")
    out_b = run_walk([page(records=[{"doi": "10.1000/shared", "title": "B"}],
                           total=1)], topic_hints(), provider_id="openalex")
    combined = combine([out_a, out_b])
    providers = {r.provider for r in combined.per_provider}
    assert providers == {"arxiv", "openalex"}
    for r in combined.per_provider:
        # each observation keeps its own provider-spec provenance
        assert "provider_spec_version" in r.provenance
        assert r.identifiers == {"doi": "10.1000/shared"}


# ── valid-negative path: hand-built hints are canonicalized too ──


def test_valid_negative_carries_canonical_identifier():
    # a hand-built spec.hints payload (source_handlers._hints_from_spec)
    # bypasses parse_query_hints — the walk's valid-negative branch must
    # still persist the CANONICAL identifier + valid_negative_for
    raw_hints = RetrievalHints(
        identifiers={"doi": "10.1038/NATURE12373"}, topic="", mode="IDENTIFIER")
    out = run_walk([page(status=404)], raw_hints)
    vn = out.per_provider[0]
    assert vn.valid_negative is True
    assert vn.identifiers == {"doi": "10.1038/nature12373"}
    assert vn.valid_negative_for == "10.1038/nature12373"


# ── J. identifier mutation after admission → immutable history ──

CLOCK = "2026-08-19T00:00:00.000000+00:00"


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Test One")
    yield conn
    conn.close()


def _make_result(doi: str = "10.1234/abc", title: str = "A study") -> SearchResult:
    ids = {"doi": doi}
    r = SearchResult(
        result_id=make_search_result_id("arxiv", "search", "cancer", 0, None, ids),
        provider="arxiv", endpoint="search", query="cancer",
        request_params_redacted={}, identifiers=ids, title=title,
        authors=("Ada Lovelace",), year=2026, venue="",
        abstract_sha256=None, source_url="", access_timestamp_utc=CLOCK,
        page_index=0, cursor_key=None, raw_retrieved_count=1, delivered_count=1,
        total_count=1, total_is_estimate=False, reconciliation="COMPLETE",
        content_hash="", provenance={"provider_spec_version": "1.0.0"})
    return dataclasses.replace(r, content_hash=content_hash_of_search_result(r))


def _make_outcome(result: SearchResult, log_provider: str = "arxiv") -> SearchOutcome:
    log = RequestLogRecord(
        provider=log_provider, endpoint="search", query="cancer",
        request_params_redacted={}, timestamps=("t1", "t2"),
        cursor_chain=(None,), page_counts=((1, 1),),
        reconciliation="COMPLETE", total_is_estimate=False,
        hazard_verdicts=("NONE",), provider_spec_version="1.0.0",
        raw_artifact_hashes=())
    return SearchOutcome(per_provider=(result,), aggregate="COMPLETE",
                         notes=(), request_log=log)


def _admit_running_search_task(db) -> str:
    payload = build_source_search_task_payload(
        "arxiv", {"identifiers": {}, "topic": "cancer", "mode": "TOPIC",
                  "unrecognized_hints": []}, scope_ref="p1")
    result = apply_intent(db, Intent(kind=IntentKind.INSERT_TASK,
                                     proposed_by="DIRECTOR",
                                     project_id="p1", payload=payload))
    task_id = result.entity_id
    tr = TaskRepository(db)
    tr.transition_status(task_id, TaskStatus.READY, caused_by="test")
    tr.transition_status(task_id, TaskStatus.RUNNING, caused_by="test")
    return task_id


def test_j_identifier_mutation_after_admission_refused(db):
    # brief §14 J — a persisted source record's identifiers are IMMUTABLE:
    # tampering with the persisted identifier map is caught by the reuse
    # path's semantic-hash re-verification (OB-02), never silently accepted
    task_id = _admit_running_search_task(db)
    repo = SourceOutcomeRepository(db)
    outcome = _make_outcome(_make_result())
    first = repo.record("p1", task_id, outcome, outcome_kind="search")
    assert first["decision"] == "NEW"

    # forge a different DOI onto the persisted record
    row = db.execute(
        "SELECT artifact_id, metadata_json FROM artifacts "
        "WHERE artifact_type = 'source_result'").fetchone()
    meta = json.loads(row["metadata_json"])
    meta["record"]["identifiers"] = {"doi": "10.9999/forged"}
    db.execute("UPDATE artifacts SET metadata_json = ? WHERE artifact_id = ?",
               (json.dumps(meta), row["artifact_id"]))

    with pytest.raises(SourceOutcomeIntegrityError, match="semantic content_hash"):
        repo.record("p1", task_id, outcome, outcome_kind="search")


# ── Step 1 (frozen implementation sequence) — provider/source identity ──
# closure (ratification record §8, hermes_architecture_ratification.md)
#
# HR-04 §7 records the honest state: NO production adapters exist; the 11
# ratified adapters (IDR-030 allowlist) are declared but their extract_ids
# implementations are DEFERRED. The choke point (canonicalize_identifiers)
# is walk-level and adapter-proof by construction. Step 1 pins that closure:
# every allowlist provider's declared raw identifier shape canonicalizes
# correctly (unit + end-to-end through the walk), the construction-site
# inventory stays closed, the no-adapter state stays honest, and the
# post-admission mutation refusal (test_j) extends to provider-native ids.
# No lineage graph, no DOI resolver, no embeddings (HR-04 pinned constraints).

STEP1_RAW_SHAPES: dict[str, dict[str, str]] = {
    # HR-04 §7 capability table — each provider's declared raw identifier
    # shape, probe-verified against canonicalize_identifiers (2026-08-20).
    "pubmed": {"pmid": "PMID: 26214858", "doi": "10.1038/NATURE12373"},
    "pmc": {"pmcid": "pmc4922062", "doi": "DOI:10.7554/eLife.12345"},
    "europepmc": {"pmid": "26214858", "pmcid": "PMC4922062",
                  "doi": "10.1038/nature12373"},
    "arxiv": {"arxiv": "2103.15348v2"},
    "biorxiv": {"doi": "10.1101/2020.01.01.123456"},
    "medrxiv": {"doi": "DOI:10.1101/2021.06.07.21258542"},
    "openalex": {"openalex_id": "W2741809807", "doi": "10.1038/NATURE12373"},
    "crossref": {"doi": "https://doi.org/10.1103/PhysRevLett.116.061102"},
    "semantic-scholar": {
        "s2_paper_id": "649def34f8be52c8b66281af98ae884c09aef38b",
        "doi": "10.1038/NATURE12373"},
    "core": {"core_id": "82071694",
             "url": "https://core.ac.uk/download/82071694.pdf"},
    "unpaywall": {"doi": "10.1038/NATURE12373."},
}

STEP1_EXPECTED_CANONICAL: dict[str, dict[str, str]] = {
    "pubmed": {"pmid": "26214858", "doi": "10.1038/nature12373"},
    "pmc": {"pmcid": "PMC4922062", "doi": "10.7554/elife.12345"},
    "europepmc": {"pmid": "26214858", "pmcid": "PMC4922062",
                  "doi": "10.1038/nature12373"},
    "arxiv": {"arxiv": "2103.15348"},
    "biorxiv": {"doi": "10.1101/2020.01.01.123456"},
    "medrxiv": {"doi": "10.1101/2021.06.07.21258542"},
    "openalex": {"openalex_id": "W2741809807", "doi": "10.1038/nature12373"},
    "crossref": {"doi": "10.1103/physrevlett.116.061102"},
    "semantic-scholar": {
        "s2_paper_id": "649def34f8be52c8b66281af98ae884c09aef38b",
        "doi": "10.1038/nature12373"},
    "core": {"core_id": "82071694",
             "url": "https://core.ac.uk/download/82071694.pdf"},
    "unpaywall": {"doi": "10.1038/nature12373"},
}


class TestStep1ProviderSourceIdentityClosure:
    """Step 1 of the frozen implementation sequence: provider/source
    identity closure — the HR-04 normalization choke point covers every
    provider adapter before historical provider closure."""

    def test_allowlist_is_exactly_the_eleven_ratified_providers(self):
        from hermes.tools.research_sources import SOURCE_PROVIDER_ALLOWLIST
        assert set(SOURCE_PROVIDER_ALLOWLIST) == set(STEP1_RAW_SHAPES)
        assert len(SOURCE_PROVIDER_ALLOWLIST) == 11

    @pytest.mark.parametrize("provider", sorted(STEP1_RAW_SHAPES))
    def test_per_adapter_raw_shape_canonicalizes(self, provider):
        # Every allowlist provider's declared raw identifier shape (HR-04 §7)
        # passes through the single normalization path to its canonical form
        assert canonicalize_identifiers(STEP1_RAW_SHAPES[provider]) == \
            STEP1_EXPECTED_CANONICAL[provider]

    @pytest.mark.parametrize("provider", sorted(STEP1_RAW_SHAPES))
    def test_per_adapter_shape_end_to_end_through_the_walk(self, provider):
        # The walk delivers the record with CANONICAL identifiers for every
        # provider shape — the choke point is adapter-proof
        record = dict(STEP1_RAW_SHAPES[provider], title="T")
        out = run_walk([page(records=[record], total=1)], topic_hints(),
                       provider_id=provider)
        assert len(out.per_provider) == 1
        r = out.per_provider[0]
        assert r.provider == provider
        assert r.identifiers == STEP1_EXPECTED_CANONICAL[provider]

    @pytest.mark.parametrize("provider", sorted(STEP1_RAW_SHAPES))
    def test_per_adapter_replay_stable(self, provider):
        # Same raw shape twice → identical identifiers/result_id/content_hash
        record = dict(STEP1_RAW_SHAPES[provider], title="T")
        r1 = run_walk([page(records=[record], total=1)], topic_hints(),
                      provider_id=provider).per_provider[0]
        r2 = run_walk([page(records=[record], total=1)], topic_hints(),
                      provider_id=provider).per_provider[0]
        assert r1.identifiers == r2.identifiers
        assert r1.result_id == r2.result_id
        assert r1.content_hash == r2.content_hash

    def test_missing_identifiers_still_admissible_per_provider(self):
        # HR-04 §8 — identifier absence = unknown lineage, never invalid
        # source: a url-only record is delivered for any provider
        for provider in ("pubmed", "openalex", "core"):
            out = run_walk([page(records=[{
                "url": "https://example.com/paper.pdf", "title": "T",
            }], total=1)], topic_hints(), provider_id=provider)
            assert out.aggregate == "COMPLETE"
            assert out.per_provider[0].identifiers == \
                {"url": "https://example.com/paper.pdf"}

    def test_no_production_adapter_extract_ids_implementations(self):
        # HR-04 §7 honest-state pin, CHG-2 update: real adapters have
        # landed (step 5), so the pin evolves from "no implementations"
        # to the choke-point guarantee that motivated it — identifier
        # canonicalization happens ONLY through normalize_identifier
        # (contract §3.1), never via adapter-local mangling.
        #
        # Structural half: every concrete `def extract_ids` in src/
        # lives in tools/providers/adapters/ and its module imports
        # normalize_identifier from the normalize module.
        import re
        from pathlib import Path

        import hermes
        from hermes.tools.providers.normalize import normalize_identifier
        src_root = Path(hermes.__file__).resolve().parent
        hits = []
        for py in sorted(src_root.rglob("*.py")):
            if "__pycache__" in py.parts:
                continue
            for i, line in enumerate(
                    py.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"\bdef extract_ids\b", line):
                    hits.append((py.relative_to(src_root).as_posix(), i))
        assert hits, "abstract extract_ids declaration vanished"
        # The abstract declaration (base.py) plus exactly one shared
        # concrete implementation (adapters/base_adapter.py, which
        # funnels every kind through normalize_identifier) are the
        # only non-adapter definitions; every other override lives in
        # an adapter module and imports normalize_identifier.
        assert hits[0][0] == "tools/providers/adapters/base_adapter.py" \
            or hits[0][0] == "tools/providers/base.py", hits
        assert "tools/providers/base.py" in {h[0] for h in hits}, hits
        for path, _line in hits:
            if path in ("tools/providers/base.py",
                        "tools/providers/adapters/base_adapter.py"):
                continue
            assert path.startswith("tools/providers/adapters/"), path
            text = (src_root / path).read_text(encoding="utf-8")
            assert "normalize_identifier" in text, path
        # Behavioral half: every registered adapter's extract_ids output
        # equals normalize_identifier applied per kind — messy casing
        # and whitespace included. No adapter invents identities.
        from hermes.tools.providers.adapters import PROVIDER_REGISTRY
        messy = {"doi": "  10.1234/ABCDEF  ", "pmid": " 00123 ",
                 "arxiv": "arXiv:2401.00001v2 ", "url": "u"}
        expected = {}
        for kind, raw in messy.items():
            canonical = normalize_identifier(kind, raw)
            if canonical is not None:
                expected[kind] = canonical
        assert expected, "fixture must exercise the choke point"
        for provider_id in sorted(PROVIDER_REGISTRY):
            adapter = PROVIDER_REGISTRY[provider_id]()
            assert adapter.extract_ids(dict(messy)) == expected, provider_id

    def test_searchresult_construction_sites_closed_inventory(self):
        # Structural fixture: every SearchResult( construction site in src/
        # is one of the three audited sites — two walk sites (canonical ids
        # flow in from canonicalize_identifiers) and the closed-schema
        # deserializer (restores already-canonical persisted data). A NEW
        # construction site forces a choke-point review.
        import re
        from pathlib import Path

        import hermes
        src_root = Path(hermes.__file__).resolve().parent
        pat = re.compile(r"(?<![A-Za-z_])SearchResult\(")
        site_fns = set()
        for py in sorted(src_root.rglob("*.py")):
            if "__pycache__" in py.parts:
                continue
            rel = py.relative_to(src_root).as_posix()
            lines = py.read_text(encoding="utf-8").splitlines()
            for i, line in enumerate(lines, 1):
                if pat.search(line):
                    fn = None
                    for j in range(i - 1, -1, -1):
                        if lines[j].startswith("def "):
                            fn = lines[j].split("(")[0][4:].strip()
                            break
                    site_fns.add((rel, fn))
        assert site_fns == {
            ("tools/providers/paginate.py", "_make_result"),
            ("tools/providers/paginate.py", "_valid_negative_result"),
            ("tools/research_sources.py", "search_result_from_mapping"),
        }, site_fns

    def test_shipped_hazard_specs_are_allowlist_members_and_load(self):
        # The shipped hazard-spec files are a SUBSET of the allowlist, each
        # coherent (provider_id matches), each loads cleanly
        from pathlib import Path

        from hermes.tools.providers.hazards import load_hazard_spec
        from hermes.tools.research_sources import SOURCE_PROVIDER_ALLOWLIST
        spec_dir = (Path(__file__).resolve().parent.parent / "src" /
                    "hermes" / "tools" / "providers" / "hazard_specs")
        shipped = sorted(p.stem for p in spec_dir.glob("*.json"))
        assert shipped == ["arxiv", "europepmc", "openalex", "pmc"]
        for pid in shipped:
            assert pid in SOURCE_PROVIDER_ALLOWLIST
            spec = load_hazard_spec(pid, json.loads(
                (spec_dir / f"{pid}.json").read_text(encoding="utf-8")))
            assert spec.provider_id == pid

    def test_provider_without_shipped_spec_fails_closed(self):
        # 7 of 11 allowlist providers have no shipped hazard spec — the walk
        # refuses them fail-closed rather than guessing a spec (honest state)
        transport = FakeTransport([page(records=[], total=0)])
        adapter = FakeAdapter(transport, provider_id="pubmed")
        with pytest.raises(ValueError, match="no shipped hazard spec"):
            walk(adapter, topic_hints(), WalkRequest(max_results=50),
                 transport, FakeLimiter(), FakeRecorder(), FakeClock())

    @pytest.mark.parametrize("native_kind",
                             ["openalex_id", "core_id", "s2_paper_id"])
    def test_provider_native_ids_never_become_dedup_keys(self, native_kind):
        from hermes.tools.providers.normalize import dedup_key
        assert dedup_key({native_kind: "native123"}) is None

    def test_untrusted_search_result_exposes_no_identifiers(self):
        # The model-facing surface (M3) carries NO identifiers field —
        # identifiers are lineage hints for future reasoning, never model
        # context
        from hermes.research.source_handlers import UntrustedSearchResult
        names = {f.name for f in dataclasses.fields(UntrustedSearchResult)}
        assert "identifiers" not in names
        assert names == {"result_id", "source_url", "content_hash",
                         "title", "venue", "query"}

    def test_j2_native_identifier_mutation_after_admission_refused(self, db):
        # test_j extended (Step 1 adversarial gate): tampering a
        # PROVIDER-NATIVE identifier on the persisted record is refused by
        # the same OB-02 semantic-hash re-verification
        task_id = _admit_running_search_task(db)
        repo = SourceOutcomeRepository(db)
        ids = {"doi": "10.1234/abc", "openalex_id": "W2741809807"}
        r = SearchResult(
            result_id=make_search_result_id(
                "arxiv", "search", "cancer", 0, None, ids),
            provider="arxiv", endpoint="search", query="cancer",
            request_params_redacted={}, identifiers=ids, title="A study",
            authors=("Ada Lovelace",), year=2026, venue="",
            abstract_sha256=None, source_url="", access_timestamp_utc=CLOCK,
            page_index=0, cursor_key=None, raw_retrieved_count=1,
            delivered_count=1, total_count=1, total_is_estimate=False,
            reconciliation="COMPLETE", content_hash="",
            provenance={"provider_spec_version": "1.0.0"})
        r = dataclasses.replace(r, content_hash=content_hash_of_search_result(r))
        outcome = _make_outcome(r)
        first = repo.record("p1", task_id, outcome, outcome_kind="search")
        assert first["decision"] == "NEW"

        row = db.execute(
            "SELECT artifact_id, metadata_json FROM artifacts "
            "WHERE artifact_type = 'source_result'").fetchone()
        meta = json.loads(row["metadata_json"])
        meta["record"]["identifiers"]["openalex_id"] = "W_FORGED"
        db.execute("UPDATE artifacts SET metadata_json = ? WHERE artifact_id = ?",
                   (json.dumps(meta), row["artifact_id"]))

        with pytest.raises(SourceOutcomeIntegrityError,
                           match="semantic content_hash"):
            repo.record("p1", task_id, outcome, outcome_kind="search")


# ── Step 1 follow-up — "no anonymous sources" four-field identity audit ──
# (operator-chartered tests-only pin, 2026-08-20)
#
# The operator's Step 1 invariant: every persisted source carries FOUR
# identity fields — provider, source ID, retrieval timestamp, content hash —
# and NO anonymous source may be admitted. Live-source audit at this HEAD
# (probe-verified, in-memory DB) found the current admission state:
#
#   provider             → REFUSED when empty, but only INCIDENTALLY via the
#                          task-binding check (V6-P7-A2-01), not a dedicated
#                          non-empty identity gate
#   identifiers          → ADMITTED when empty — RATIFIED BY DESIGN
#                          (HR-04 §14.5: absence = unknown lineage, never an
#                          invalid source; the walk-level MALFORMED_ROW drop
#                          is the real guard)
#   access_timestamp_utc → ADMITTED when empty — THE GENUINE HOLE
#   content_hash         → enforced (derived, never authored; test_j/test_j2)
#
# These tests PIN the current behavior so the gap cannot silently widen or
# shift. The fix (a dedicated non-empty identity gate in
# `_validate_identities`) is a SEPARATELY-CHARTERED production follow-up —
# deliberately NOT made here (tests-only charter). See the additive note in
# docs/idr/hr04_source_identifier_capture.md §16.


def _make_result_with_identity(
    *,
    provider: str = "arxiv",
    ids: dict[str, str] | None = None,
    ts: str = CLOCK,
) -> SearchResult:
    """A minimal valid SearchResult with controllable identity fields."""
    ids = {"doi": "10.1234/abc"} if ids is None else ids
    r = SearchResult(
        result_id=make_search_result_id(
            provider or "arxiv", "search", "cancer", 0, None, ids),
        provider=provider, endpoint="search", query="cancer",
        request_params_redacted={}, identifiers=ids, title="A study",
        authors=("Ada Lovelace",), year=2026, venue="",
        abstract_sha256=None, source_url="", access_timestamp_utc=ts,
        page_index=0, cursor_key=None, raw_retrieved_count=1,
        delivered_count=1, total_count=1, total_is_estimate=False,
        reconciliation="COMPLETE", content_hash="",
        provenance={"provider_spec_version": "1.0.0"})
    return dataclasses.replace(r, content_hash=content_hash_of_search_result(r))


class TestStep1NoAnonymousSourcesCurrentBehavior:
    """Pin the CURRENT admission behavior of the four identity fields.

    These are pinning tests, not aspirational tests: they lock what the
    admission gate does TODAY so the known gap (empty retrieval timestamp
    admitted) is visible and cannot regress unnoticed. The empty-timestamp
    hole is documented for a separately-chartered fix.
    """

    def test_empty_access_timestamp_currently_admitted_known_gap(self, db):
        # THE HOLE (pinned): a source with an EMPTY access_timestamp_utc is
        # ADMITTED (decision NEW). `_now(clock)` returns "" when the clock
        # lacks now_utc (paginate.py:824-826), and `_validate_identities`
        # (source_outcomes.py:385) re-derives the content_hash but never
        # checks the timestamp is non-empty. This test PINS that current
        # behavior; the fix is a separately-chartered follow-up.
        task_id = _admit_running_search_task(db)
        repo = SourceOutcomeRepository(db)
        outcome = _make_outcome(_make_result_with_identity(ts=""))
        summary = repo.record("p1", task_id, outcome, outcome_kind="search")
        assert summary["decision"] == "NEW"  # admitted — the known gap

    def test_empty_provider_refused_via_task_binding(self, db):
        # PINNED MECHANISM: an empty provider is refused, but only because it
        # contradicts the producing task's spec.provider (V6-P7-A2-01 task
        # binding) — NOT via a dedicated non-empty identity gate. The log
        # provider is set to "" too, so the log-vs-results consistency layer
        # passes and the deeper task-binding layer is what fires. Documents
        # that the provider guard is incidental, so the follow-up charter can
        # decide whether to add an explicit gate.
        task_id = _admit_running_search_task(db)
        repo = SourceOutcomeRepository(db)
        outcome = _make_outcome(
            _make_result_with_identity(provider="", ts=CLOCK),
            log_provider="")
        with pytest.raises(SourceOutcomeBindingError,
                           match="does not match the producing task"):
            repo.record("p1", task_id, outcome, outcome_kind="search")

    def test_empty_identifiers_admitted_by_design(self, db):
        # PINNED BY DESIGN: an empty identifier map is ADMITTED — HR-04
        # §14.5 ratified "absence = unknown lineage, never an invalid
        # source." The walk-level MALFORMED_ROW drop (paginate.py:304-307)
        # is the real guard for malformed identifiers; a legitimately
        # identifier-less source is not anonymous-source-invalid here.
        task_id = _admit_running_search_task(db)
        repo = SourceOutcomeRepository(db)
        outcome = _make_outcome(_make_result_with_identity(ids={}, ts=CLOCK))
        summary = repo.record("p1", task_id, outcome, outcome_kind="search")
        assert summary["decision"] == "NEW"  # admitted by ratified design

    def test_content_hash_identity_gate_enforced(self, db):
        # PINNED (already enforced): a caller-authored content_hash that does
        # not match the canonical derivation is refused fail-closed — the one
        # identity field with a dedicated gate today (ADV-01/06).
        task_id = _admit_running_search_task(db)
        repo = SourceOutcomeRepository(db)
        r = _make_result_with_identity(ts=CLOCK)
        forged = dataclasses.replace(r, content_hash="deadbeef" * 8)
        outcome = _make_outcome(forged)
        with pytest.raises(SourceOutcomeIntegrityError,
                           match="content_hash"):
            repo.record("p1", task_id, outcome, outcome_kind="search")
