"""OPS-5Z6 — five content sources, each read against a captured response.

The rule this batch is built on: **no extractor without a captured response.**
Each provider below was fetched once, for real; the exact body and the
response's media type are pinned in ``tests/fixtures/source_payloads/`` and
hashed in ``capture_manifest.json``. The extractor in
``hermes.tools.capabilities.content`` was written against those bytes, not
against a shape described in a prompt or an audit.

The falsifiers, one set per provider:

1. the captured record reads as ``content``, and its facts come from the
   record's own prose (title and abstract) — never from its metadata;
2. the record's citation count, identifier (DOI, or the arXiv id) and
   publication date produce no figure and no date;
3. a number in the abstract is a figure, bound to the subject the text names
   at that position;
4. the host's 5,590-byte cookie wall is still refused (``NON_CONTENT_PAYLOAD``)
   by the real fetch path, where a challenge page actually arrives;
5. an unknown shape with a declared format is ``unreadable``, never
   ``fallback``;
6. the control: the real 1,260-character OpenAlex record still reads, and a
   verbatim quotation is still grounded.

Every new extractor has a red proof: stub it to ``raw.decode`` and falsifier 2
fails — the raw serialization's citation count / DOI / date becomes the
source's facts. That is the defect being fixed.

Provenance is not re-typed here: the manifest is the record of what was
requested, what came back, and what its hash is. A fixture edited after the
fact fails the integrity test.
"""
from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as _ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from hermes.research.grounding import check_claim
from hermes.research.inspection import facts_in
from hermes.research.live_fetch import ALLOWLIST_ENTRIES, ALLOWLIST_HOSTS
from hermes.tools.capabilities import content as content_module
from hermes.tools.capabilities.content import (
    ContentRead,
    ContentState,
    read_content,
)
from hermes.tools.providers.adapters import resolve_adapter
from hermes.tools.providers.base import (
    PageState,
    RequestSpec,
    TransportResponse,
)
from hermes.tools.providers.hazards import SPEC_SCHEMA, load_hazard_spec
from hermes.tools.providers.paginate import fetch_batch
from hermes.tools.research_sources import (
    FetchRequest,
    RetryPolicy,
    SearchResult,
)

CLOCK = "2026-10-30T18:00:00.000000+00:00"
FIXTURES = Path(__file__).parent / "fixtures" / "source_payloads"
MANIFEST = FIXTURES / "capture_manifest.json"
WALL = FIXTURES / "pubmed_cookie_wall_5590.html"
CONTROL = FIXTURES / "openalex_work_33727.json"

SUBJECTS = ("COVID-19",)
CONTROL_CLAIM = (
    "When a novel infectious disease emerges, enhanced contact tracing and "
    "isolation are implemented to prevent a major epidemic, and indeed, they "
    "have been successful for the control of severe acute respiratory "
    "syndrome (SARS) and Middle East respiratory syndrome (MERS), which have "
    "been greatly reduced without causing a global pandemic."
)

QUERY_FEED = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<feed xmlns="http://www.w3.org/2005/Atom">'
    b"<title>arXiv Query: search_query=x</title>"
    b"<updated>2026-10-30T17:00:00Z</updated>"
    b"</feed>"
)


@dataclass(frozen=True)
class Capture:
    """One provider's captured record and the metadata that must not be mined."""

    provider: str
    token: str
    fixture: str
    media_type: str
    url: str
    citation: str          # the record's own citation count ("" when none)
    identifier: str        # the DOI, or arXiv's record id
    publication_literal: str   # the publication date as the record states it
    publication_date: str      # the same date as an ISO fact, when day-precise
    figure: tuple[str, str]    # (literal, entity) in the abstract
    figure_date: str           # an ISO date the abstract states ("" when none)


CAPTURES: tuple[Capture, ...] = (
    Capture(
        provider="crossref",
        token="crossref",
        fixture="crossref_work_ligo_116061102.json",
        media_type="application/json",
        url="https://api.crossref.org/works/10.1103/PhysRevLett.116.061102",
        citation="12042",
        identifier="10.1103/physrevlett.116.061102",
        publication_literal="2016-02-11",
        publication_date="2016-02-11",
        figure=("24", "ratio"),
        figure_date="2015-09-14",
    ),
    Capture(
        provider="arxiv",
        token="arxiv",
        fixture="arxiv_entry_ligo_160203837.xml",
        media_type="application/atom+xml; charset=utf-8",
        url="https://export.arxiv.org/api/query?id_list=1602.03837&max_results=1",
        # The Atom entry carries no citation count and no DOI. Its metadata is
        # the arXiv id, the published/updated timestamps, links and categories;
        # those are what must not become facts.
        citation="",
        identifier="1602.03837",
        publication_literal="2016-02-11",
        publication_date="2016-02-11",
        figure=("24", "ratio"),
        figure_date="2015-09-14",
    ),
    Capture(
        provider="inspirehep",
        token="inspirehep",
        fixture="inspirehep_record_muon_g2_813721.json",
        media_type="application/json",
        url="https://inspirehep.net/api/literature/813721?format=json",
        citation="1319",
        identifier="10.1016/j.physrep.2009.04.003",
        # The record states a publication year (2009) and a month-precision
        # preprint date (2009-02), not a day; the year is the load-bearing
        # literal, and the content states none of it.
        publication_literal="2009",
        publication_date="",
        figure=("14", "remarkable"),
        figure_date="",
    ),
    Capture(
        provider="semantic-scholar",
        token="semantic-scholar",
        fixture="semanticscholar_paper_ligo_116061102.json",
        media_type="application/json",
        url=(
            "https://api.semanticscholar.org/graph/v1/paper/"
            "DOI:10.1103/PhysRevLett.116.061102?fields=title,abstract,year,"
            "venue,externalIds,citationCount,publicationDate"
        ),
        citation="4241",
        identifier="10.1103/PhysRevLett.116.061102",
        publication_literal="2016-02-11",
        publication_date="2016-02-11",
        figure=("24", "ratio"),
        figure_date="2015-09-14",
    ),
    Capture(
        provider="europepmc",
        token="europepmc",
        fixture="europepmc_search_isaric_1985.json",
        media_type="application/json;charset=UTF-8",
        url=(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
            "?query=DOI:10.1136/bmj.m1985&format=json&resultType=core"
            "&pageSize=1"
        ),
        citation="2459",
        identifier="10.1136/bmj.m1985",
        publication_literal="2020-05-22",
        publication_date="2020-05-22",
        figure=("208", "Setting"),
        figure_date="2020-04-19",
    ),
)


# ── the fixtures and the independent oracle ──


def _bytes(capture: Capture) -> bytes:
    return (FIXTURES / capture.fixture).read_bytes()


def _captured_title(capture: Capture) -> str:
    """The record's title, read from the fixture without calling the extractor."""
    raw = _bytes(capture)
    if capture.token == "arxiv":
        root = _ET.fromstring(raw.decode("utf-8"))
        entry = next(element for element in root.iter()
                     if element.tag.rsplit("}", 1)[-1] == "entry")
        title = next(child for child in entry
                     if child.tag.rsplit("}", 1)[-1] == "title")
        return " ".join("".join(title.itertext()).split())
    document = json.loads(raw.decode("utf-8"))
    if capture.token == "crossref":
        return " ".join(document["message"]["title"])
    if capture.token == "inspirehep":
        return document["metadata"]["titles"][0]["title"]
    if capture.token == "semantic-scholar":
        return document["title"]
    if capture.token == "europepmc":
        return document["resultList"]["result"][0]["title"]
    raise AssertionError(capture.token)


def _read(capture: Capture) -> ContentRead:
    return read_content(_bytes(capture), format=capture.token)


def _metadata_absent(capture: Capture, read: ContentRead) -> bool:
    """Falsifier 2 as one predicate, so the red proof can assert it flips."""
    facts = facts_in(read)
    literals = {figure.literal for figure in facts.figures}
    dates = {date.iso for date in facts.dates}
    if capture.citation and (
            capture.citation in read.text or capture.citation in literals):
        return False
    if capture.identifier in read.text:
        return False
    if capture.publication_literal in read.text:
        return False
    return not (capture.publication_date
                and capture.publication_date in dates)


# ── falsifier 1: the record reads as content, from its own prose ──


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda c: c.provider)
def test_the_record_reads_as_content_from_its_own_prose(
        capture: Capture) -> None:
    read = _read(capture)
    assert read.state is ContentState.CONTENT, read.detail
    assert read.format == capture.token
    assert read.fields == ("title", "abstract")
    # One field join, two parts: no third "metadata" part was appended.
    assert read.text.count("\n\n") == 1
    title = _captured_title(capture)
    assert read.text.startswith(title)
    abstract_start = len(title) + 2

    facts = facts_in(read)
    assert facts.figures, "the captured abstract states figures"
    for figure in facts.figures:
        # A figure is from the title (the source's own prose) or from the
        # abstract — never from a field between them or after the abstract.
        assert (figure.position < len(title)
                or figure.position >= abstract_start), figure
    for date in facts.dates:
        assert (date.position < len(title)
                or date.position >= abstract_start), date
    # The whole record is 2 KB–197 KB; the content is its prose, not its bytes.
    assert len(read.text) < len(_bytes(capture))


# ── falsifier 2: the metadata produces no figure and no date ──


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda c: c.provider)
def test_metadata_citation_doi_and_date_are_not_facts(capture: Capture) -> None:
    read = _read(capture)
    facts = facts_in(read)
    literals = [figure.literal for figure in facts.figures]
    dates = {date.iso for date in facts.dates}
    if capture.citation:
        assert capture.citation not in literals
        assert capture.citation not in read.text
    assert capture.identifier not in read.text
    assert capture.publication_literal not in read.text
    if capture.publication_date:
        assert capture.publication_date not in dates
    assert _metadata_absent(capture, read) is True


def _raw_decode_as_content(text: str, fmt: str) -> ContentRead:
    """The defect, made explicit: the serialization is called content."""
    return ContentRead(text=text, state=ContentState.CONTENT, format=fmt,
                       fields=("text",))


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda c: c.provider)
def test_red_proof_raw_decode_mines_the_metadata(
        capture: Capture, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(content_module._EXTRACTORS, capture.token,
                        _raw_decode_as_content)
    read = _read(capture)
    assert read.state is ContentState.CONTENT
    # The falsifier fails exactly where the metadata becomes the source.
    assert _metadata_absent(capture, read) is False
    facts = facts_in(read)
    literals = {figure.literal for figure in facts.figures}
    dates = {date.iso for date in facts.dates}
    assert (capture.identifier in read.text
            or capture.publication_literal in read.text
            or (capture.citation
                and (capture.citation in read.text
                     or capture.citation in literals))
            or (capture.publication_date
                and capture.publication_date in dates))


# ── falsifier 3: the abstract's own figure binds to its subject ──


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda c: c.provider)
def test_the_abstracts_figure_binds_to_the_subject_it_names(
        capture: Capture) -> None:
    read = _read(capture)
    title = _captured_title(capture)
    abstract_start = len(title) + 2
    facts = facts_in(read)
    abstract_figures = [
        figure for figure in facts.figures
        if figure.position >= abstract_start]
    literal, entity = capture.figure
    matches = [figure for figure in abstract_figures
               if (figure.literal, figure.entity) == (literal, entity)]
    assert matches, [(figure.literal, figure.entity)
                     for figure in abstract_figures]
    if capture.figure_date:
        assert capture.figure_date in {date.iso for date in facts.dates}


# ── falsifier 4: a wall from the host is still refused ──


class _Limiter:
    def acquire(self, provider: str) -> tuple[bool, str]:
        return True, ""

    def release(self, provider: str) -> None:
        return None

    def note_throttled(self, provider: str,
                       retry_after: float | None) -> None:
        return None


class _Clock:
    def now_utc(self) -> str:
        return CLOCK

    def monotonic(self) -> float:
        return 0.0

    def sleep(self, delay: float) -> None:
        return None


class _Transport:
    """One scripted response; counts calls so a refusal is pre-artifact."""

    def __init__(self, body: bytes, media_type: str) -> None:
        self._body = body
        self._media_type = media_type
        self.calls = 0

    def request(self, spec: RequestSpec) -> TransportResponse:
        self.calls += 1
        return TransportResponse(
            status=200, body=self._body, headers={},
            content_type=self._media_type)


def _spec(provider: str) -> Any:
    """A benign hazard spec: the content gate, not a marker, is under test."""
    return load_hazard_spec(provider, {
        "schema": SPEC_SCHEMA,
        "provider_id": provider,
        "version": "1.0.0",
        "markers": [],
        "empty_body_rule": "treat-as-failure",
        "error_field": None,
        "count_semantics": "exact",
        "counts_raw_rows": False,
        "required_fields": [],
        "cursor_rule": {"kind": "offset", "loop_guard": 100},
        "throttle_signature": [],
        "rewrite_suspect": [],
        "fetch": None,
        "valid_negative_statuses": [],
    })


def _source(capture: Capture) -> SearchResult:
    return SearchResult(
        result_id="sr-" + capture.provider,
        provider=capture.provider,
        endpoint=capture.url,
        query="",
        request_params_redacted={},
        identifiers={},
        title="the captured source",
        authors=(),
        year=None,
        venue="",
        abstract_sha256=None,
        source_url=capture.url,
        access_timestamp_utc=CLOCK,
        page_index=0,
        cursor_key=None,
        raw_retrieved_count=1,
        delivered_count=1,
        total_count=1,
        total_is_estimate=False,
        reconciliation="COMPLETE",
        content_hash="",
        provenance={},
    )


def _fetch(capture: Capture, body: bytes, media_type: str) -> Any:
    adapter = resolve_adapter(capture.provider)()
    transport = _Transport(body, media_type)
    return fetch_batch(
        adapter, [_source(capture)],
        FetchRequest(
            max_sources=1, size_cap_bytes=1_000_000,
            retry_policy=RetryPolicy(max_retries=0)),
        transport, _Limiter(), object(), _Clock(),
        hazard_spec=_spec(capture.provider))


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda c: c.provider)
def test_the_hosts_cookie_wall_is_still_refused(capture: Capture) -> None:
    """The exact 5,590-byte wall, through the real fetch path, as a page."""
    wall = WALL.read_bytes()
    assert len(wall) == 5590
    outcome = _fetch(capture, wall, "text/html")
    assert outcome.payloads == ()
    assert outcome.per_source == ()
    assert len(outcome.failed) == 1
    failure = outcome.failed[0]
    assert failure.code == "NON_CONTENT_PAYLOAD", failure
    assert failure.failure_class == "EMPTY_RESULT"


# ── the fetch path carries the declared format ──


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda c: c.provider)
def test_the_fetch_path_carries_each_declared_format(
        capture: Capture) -> None:
    outcome = _fetch(capture, _bytes(capture), capture.media_type)
    assert outcome.aggregate == "COMPLETE", outcome.failed
    assert len(outcome.payloads) == 1
    payload = outcome.payloads[0]
    assert payload.artifact.content_format == capture.token
    read = read_content(payload.raw_bytes,
                        format=payload.artifact.content_format)
    assert read.state is ContentState.CONTENT, read.detail
    assert read.fields == ("title", "abstract")


# ── falsifier 5: an unknown shape is unreadable, never fallback ──

_UNKNOWN: dict[str, bytes] = {
    "crossref": json.dumps({
        "status": "ok",
        "message": {"issued": {"date-parts": [[2020, 9, 18]]},
                    "is-referenced-by-count": 34},
    }).encode("utf-8"),
    "arxiv": QUERY_FEED,
    # The captured search wrapper: a hit list, not the fetched record.
    "inspirehep": (FIXTURES / "inspirehep_search_muon_g2_813721.json"
                   ).read_bytes(),
    "semantic-scholar": json.dumps({
        "paperId": "p1", "citationCount": 34,
        "externalIds": {"DOI": "10.1234/x"},
        "publicationDate": "2020-09-27",
    }).encode("utf-8"),
    "europepmc": json.dumps({
        "hitCount": 1, "request": {"queryString": "x"},
        "resultList": {"result": []},
    }).encode("utf-8"),
}


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda c: c.provider)
def test_an_unknown_shape_is_unreadable_not_fallback(
        capture: Capture) -> None:
    read = read_content(_UNKNOWN[capture.token], format=capture.token)
    assert read.state is ContentState.UNREADABLE, read
    assert read.format == capture.token
    facts = facts_in(read)
    assert facts.figures == () and facts.dates == ()
    assert "not mined" in facts.not_mined
    assert ("metadata" in read.detail or "envelope" in read.detail
            or "hit list" in read.detail), read.detail


# ── falsifier 6: the control ──


def test_the_real_openalex_work_still_reads_and_a_quotation_is_grounded(
        ) -> None:
    read = read_content(CONTROL.read_bytes(), format="openalex")
    document = json.loads(CONTROL.read_text(encoding="utf-8"))
    assert read.state is ContentState.CONTENT
    assert read.format == "openalex"
    assert read.fields == ("title", "display_name", "abstract")
    assert len(read.text) == 1260
    assert document["publication_date"] not in read.text
    assert "cited_by_count" not in read.text
    verdict = check_claim(CONTROL_CLAIM, read.text, subjects=SUBJECTS)
    assert verdict.grounded is True, verdict.detail


# ── the declarations, the adapter, and the manifest ──


def test_the_adapters_declare_the_captured_media_types() -> None:
    for capture in CAPTURES:
        adapter = resolve_adapter(capture.provider)()
        assert adapter.fetch_content_format(capture.media_type) == \
            capture.token, capture.provider
        # A page is always a page, and an un-captured XML type is not guessed.
        assert adapter.fetch_content_format("text/html") == "html"
    assert resolve_adapter("arxiv")().fetch_content_format(
        "application/xml") == ""


def test_the_inspirehep_adapter_reads_the_captured_search_row() -> None:
    adapter = resolve_adapter("inspirehep")()
    raw = (FIXTURES / "inspirehep_search_muon_g2_813721.json").read_bytes()
    page = adapter.parse_page(json.loads(raw.decode("utf-8")),
                              PageState(page_index=0))
    assert len(page.records) == 1
    row = page.records[0]
    assert row["title"] == "The Muon g-2"
    assert row["url"] == "https://inspirehep.net/api/literature/813721?format=json"
    assert adapter.extract_ids(row) == {
        "doi": "10.1016/j.physrep.2009.04.003",
        "arxiv": "0902.3360",
    }


def test_every_capture_is_pinned_by_hash_and_size() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = manifest["records"]
    assert len(records) == 6
    by_fixture = {record["fixture"]: record for record in records}
    for capture in CAPTURES:
        record = by_fixture[capture.fixture]
        raw = _bytes(capture)
        assert record["provider"] == capture.provider
        assert record["content_type"] == capture.media_type
        assert record["size_bytes"] == len(raw)
        assert record["sha256"] == hashlib.sha256(raw).hexdigest()
        assert record["request_url"] == capture.url


NEW_HOSTS = frozenset({
    "api.crossref.org",
    "export.arxiv.org",
    "inspirehep.net",
    "api.semanticscholar.org",
    "www.ebi.ac.uk",
})


def test_the_five_captured_hosts_are_allowlisted_with_a_review_record(
        ) -> None:
    assert set(ALLOWLIST_HOSTS) >= NEW_HOSTS
    assert [entry.host for entry in ALLOWLIST_ENTRIES] == list(ALLOWLIST_HOSTS)
    assert len({entry.host for entry in ALLOWLIST_ENTRIES}) == \
        len(ALLOWLIST_ENTRIES)
    for entry in ALLOWLIST_ENTRIES:
        assert entry.host == entry.host.strip().lower()
        assert entry.provider
        for field in ("operator", "serves", "credential",
                      "without_credential", "rate_limit"):
            assert getattr(entry, field).strip(), (entry.host, field)
    by_host = {entry.host: entry for entry in ALLOWLIST_ENTRIES}
    for capture in CAPTURES:
        host = capture.url.split("/")[2].split(":")[0].lower()
        assert host in NEW_HOSTS, capture.provider
        assert by_host[host].provider == capture.provider
    # The siblings that are different hosts are not smuggled in by a suffix:
    # a page host is not an API host, and a DOI resolver is not Crossref.
    for absent in ("arxiv.org", "doi.org", "api.inspirehep.net",
                   "www.semanticscholar.org", "ebi.ac.uk"):
        assert absent not in ALLOWLIST_HOSTS
