"""OPS-5Z Group C — an unrecognised shape is not content.

The second pass on the audit's N-F finding. The first pass modelled Crossref,
OpenAlex wrappers and PubMed inside a single shape-sniffing reader, but left
``semantic_text`` as a string and ``raw.decode`` as the fallback for anything
unrecognised. A caller could still mine a serialization as prose, and a shape
nobody modelled was still read as one.

This file pins the states, not just the text:

* a declared format with an extractor is ``content`` (or ``unreadable`` when
  the bytes are not that shape — never ``fallback``);
* a serialization whose carrier declared no format is ``fallback``: legible,
  never mined;
* ``facts_in`` extracts only from ``content`` and states a reason otherwise.

The four falsifiers, plus the control that stops this becoming "refuse
everything":

1. Crossref — content/unreadable only; ``is-referenced-by-count`` is not a
   figure.
2. OpenAlex search wrapper — ``results[0]`` is unwrapped; ``cited_by_count`` is
   not a figure; a prose figure binds to a name, not to a meta value.
3. PubMed XML — ``ArticleTitle``/``AbstractText`` only; ``1,200`` binds to the
   article's own noun, not to the title or a tag.
4. An unknown shape — unreadable when a format was declared, fallback (with a
   reason) when none was; ``facts_in`` returns no facts either way.
5. Control — the real 33,727-byte OpenAlex work still reads as its title and
   abstract, and a verbatim quotation is still grounded.

Every falsifier has a red proof: stub the extractor to the old ``raw.decode``
and the same assertion fails.

Provenance of the bytes: the OpenAlex record and wrapper use the real
``openalex_work_33727.json`` fixture served by the live fetch path. The
Crossref and PubMed bodies are constructed from the audit's description (no
fixture exists in the repository) and are labelled as such at their
definitions.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from hermes.artifacts.store import ArtifactStore
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ArtifactRepository, ProjectRepository
from hermes.research import capability_supply as supply_module
from hermes.research.capability_supply import build_research_egress_supply
from hermes.research.grounding import check_claim
from hermes.research.inspection import facts_in
from hermes.research.live_fetch import ALLOWLIST_HOSTS, build_live_fetch_wiring
from hermes.tools.capabilities import content as content_module
from hermes.tools.capabilities.content import (
    ContentRead,
    ContentState,
    read_content,
    semantic_text,
)
from hermes.tools.capabilities.invoke import (
    CapabilityInvoker,
    InMemoryIdempotencyLedger,
)
from hermes.tools.capabilities.types import (
    InvokeRequest,
    Observation,
    RiskLevel,
    ToolGrant,
)

CLOCK = "2026-10-30T16:00:00.000000+00:00"
PROJECT = "p-ops5z-group-c"
PROFILE = "ADVERSARY"
FIXTURES = Path(__file__).parent / "fixtures" / "source_payloads"
OPENALEX_WORK = FIXTURES / "openalex_work_33727.json"

SUBJECTS = ("COVID-19",)
CONTROL = (
    "When a novel infectious disease emerges, enhanced contact tracing and "
    "isolation are implemented to prevent a major epidemic, and indeed, they "
    "have been successful for the control of severe acute respiratory "
    "syndrome (SARS) and Middle East respiratory syndrome (MERS), which have "
    "been greatly reduced without causing a global pandemic."
)

#: Constructed from the audit's description; no Crossref fixture exists here.
#: The abstract is the audit's sentence; the metadata are the fields the old
#: fallback mined (date-parts, is-referenced-by-count, DOI).
CROSSREF = json.dumps({
    "status": "ok",
    "message": {
        "title": ["Containment estimates for COVID-19"],
        "abstract": ("<jats:p>Hubei averted 1,200 cases between "
                     "23 January 2020 and 2 February 2020.</jats:p>"),
        "issued": {"date-parts": [[2020, 9, 18]]},
        "is-referenced-by-count": 34,
        "DOI": "10.1234/example",
    },
}).encode("utf-8")

#: A Crossref record with none of the content fields. A declared Crossref
#: artifact must be unreadable, never a fallback: the provider promised the
#: shape and did not deliver it.
CROSSREF_NO_CONTENT = json.dumps({
    "status": "ok",
    "message": {"issued": {"date-parts": [[2020, 9, 18]]},
                "is-referenced-by-count": 34},
}).encode("utf-8")

#: Constructed from the audit's description (PubMed is a supported provider).
#: The title precedes an abstract that *begins* with the figure — the shape
#: that bound ``1,200`` to ``Containment`` when the whole document was read as
#: prose. The PMID and the journal date are metadata, not statements.
PUBMED = b"""<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticle>
  <MedlineCitation>
    <PMID>32456789</PMID>
    <Article>
      <Journal><JournalIssue><PubDate><Year>2020</Year><Month>Sep</Month>
        <Day>23</Day></PubDate></JournalIssue></Journal>
      <ArticleTitle>Containment</ArticleTitle>
      <Abstract><AbstractText>1,200 cases were averted between
        23 January 2020 and 2 February 2020.</AbstractText></Abstract>
    </Article>
  </MedlineCitation>
</PubmedArticle>
"""

#: A JSON object with none of the content fields (the audit's "unknown shape").
UNKNOWN = json.dumps({"foo": "bar", "cited_by_count": 34,
                      "publication_date": "2020-09-27"}).encode("utf-8")

#: One wrapper, built around a small work whose prose states a figure and a
#: date; the wrapper's meta and the work's metadata state different ones.
WRAPPER_WORK = {
    "title": "A wrapped work",
    "abstract": ("Hubei averted 1,200 cases between 23 January 2020 and "
                 "2 February 2020."),
    "cited_by_count": 34,
    "publication_date": "2020-09-27",
}
WRAPPER = json.dumps({
    "meta": {"count": 1, "page": 1, "per_page": 25},
    "results": [WRAPPER_WORK],
}).encode("utf-8")


def _raw_decode_as_content(text: str, fmt: str) -> ContentRead:
    """The defect, made explicit: the serialization is called content."""
    return ContentRead(text=text, state=ContentState.CONTENT, format=fmt,
                       fields=("text",))


def _literal_entities(read: ContentRead) -> list[tuple[str, str]]:
    return [(figure.literal, figure.entity) for figure in facts_in(read).figures]


def test_semantic_text_is_a_text_state_pair() -> None:
    """The typed result is the pair the old string could not carry."""
    text, state = semantic_text(b"Hubei averted 1,200 cases.")
    assert text == "Hubei averted 1,200 cases."
    assert state == "content"
    # The same call on a serialization: the bytes are still returned, and the
    # state says they are not prose.
    blob, blob_state = semantic_text(b'{"cited_by_count": 34}')
    assert blob == '{"cited_by_count": 34}'
    assert blob_state == "fallback"


# ═══════════════ 1. Crossref — content or unreadable, never fallback ═══════════════


def _assert_crossref_is_content_not_mined(read: ContentRead) -> None:
    assert read.state is ContentState.CONTENT
    assert read.format == "crossref"
    assert read.fields == ("title", "abstract")
    # The fields the old fallback mined are not in the content at all.
    assert "is-referenced-by-count" not in read.text
    assert "2020-09-18" not in read.text
    facts = facts_in(read)
    assert [figure.literal for figure in facts.figures] == ["1,200"]
    assert [figure.entity for figure in facts.figures] == ["Hubei"]
    assert {date.iso for date in facts.dates} == {
        "2020-01-23", "2020-02-02"}


def test_crossref_is_content_or_unreadable_never_fallback() -> None:
    _assert_crossref_is_content_not_mined(
        read_content(CROSSREF, format="crossref"))
    # A declared Crossref record that carries no content is unreadable — not
    # a fallback, because "crossref" is a shape the reader models.
    missing = read_content(CROSSREF_NO_CONTENT, format="crossref")
    assert missing.state is ContentState.UNREADABLE
    assert "date-parts" in missing.detail
    assert facts_in(missing).figures == ()
    assert "unreadable" in facts_in(missing).not_mined


def test_red_proof_crossref_falling_through_to_raw_decode_is_mined(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(content_module._EXTRACTORS, "crossref",
                        _raw_decode_as_content)
    read = read_content(CROSSREF, format="crossref")
    # The stub lies: the serialization is returned as content. The falsifier
    # fails exactly where the metadata would have become facts.
    assert read.state is ContentState.CONTENT
    with pytest.raises(AssertionError):
        _assert_crossref_is_content_not_mined(read)
    literals = [literal for literal, _ in _literal_entities(read)]
    assert "34" in literals and "1,200" in literals


# ═══════════════ 2. OpenAlex wrapper — results[0], no metadata facts ═══════════════


def test_the_real_work_inside_a_wrapper_is_unwrapped_not_mined() -> None:
    work = json.loads(OPENALEX_WORK.read_text(encoding="utf-8"))
    wrapper = json.dumps({
        "meta": {"count": 1, "page": 1, "per_page": 25},
        "results": [work],
    }).encode("utf-8")

    read = read_content(wrapper, format="openalex")
    direct = read_content(OPENALEX_WORK.read_bytes(), format="openalex")
    assert read.state is ContentState.CONTENT
    # Wrapper → results[0] → the same work the direct read extracts.
    assert read.text == direct.text
    assert work["publication_date"] not in read.text
    assert '"cited_by_count"' not in read.text
    assert facts_in(read).figures == ()
    assert facts_in(read).dates == ()


def _assert_wrapper_figure_binds_to_a_name(read: ContentRead) -> None:
    assert read.state is ContentState.CONTENT
    facts = facts_in(read)
    assert [(figure.literal, figure.entity) for figure in facts.figures] == [
        ("1,200", "Hubei")]
    assert {date.iso for date in facts.dates} == {
        "2020-01-23", "2020-02-02"}


def test_a_figure_inside_the_wrapper_is_bound_to_a_name() -> None:
    _assert_wrapper_figure_binds_to_a_name(
        read_content(WRAPPER, format="openalex"))


def test_red_proof_wrapper_falling_through_to_raw_decode_binds_metadata(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(content_module._EXTRACTORS, "openalex",
                        _raw_decode_as_content)
    read = read_content(WRAPPER, format="openalex")
    with pytest.raises(AssertionError):
        _assert_wrapper_figure_binds_to_a_name(read)
    literals = [literal for literal, _ in _literal_entities(read)]
    # The wrapper's 25-per-page and the work's citation count become facts;
    # the prose figure is also present, bound to something else.
    assert "25" in literals and "34" in literals


# ═══════════════ 3. PubMed XML — title and abstract, never tags ═══════════════


def _assert_pubmed_is_field_wise(read: ContentRead) -> None:
    assert read.state is ContentState.CONTENT
    assert read.format == "pubmed"
    assert read.fields == ("title", "abstract")
    assert read.text.startswith("Containment")
    # The PMID and the journal date are metadata, not prose.
    assert "32456789" not in read.text
    assert "Sep" not in read.text
    facts = facts_in(read)
    assert [figure.literal for figure in facts.figures] == ["1,200"]
    # The figure is in the abstract, so it binds to the abstract's noun — not
    # to the title above it and not to a tag name.
    assert facts.figures[0].entity not in ("Containment", "AbstractText")
    assert facts.figures[0].entity == "cases"
    assert {date.iso for date in facts.dates} == {
        "2020-01-23", "2020-02-02"}


def test_pubmed_xml_is_read_field_wise_not_tag_stripped() -> None:
    _assert_pubmed_is_field_wise(read_content(PUBMED, format="pubmed"))


def test_red_proof_pubmed_falling_through_to_raw_decode_is_tag_soup(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(content_module._EXTRACTORS, "pubmed",
                        _raw_decode_as_content)
    read = read_content(PUBMED, format="pubmed")
    with pytest.raises(AssertionError):
        _assert_pubmed_is_field_wise(read)
    literals = [literal for literal, _ in _literal_entities(read)]
    # The PMID, the XML version and the journal day are figures now.
    assert "32456789" in literals
    assert "1.0" in literals
    assert "23" in literals


# ═══════════════ 4. Unknown shape — unreadable/fallback, never mined ═══════════════


def test_an_unknown_shape_is_unreadable_when_a_format_was_declared() -> None:
    read = read_content(UNKNOWN, format="openalex")
    assert read.state is ContentState.UNREADABLE
    assert "no content field" in read.detail
    facts = facts_in(read)
    assert facts.figures == () and facts.dates == () and facts.quotes == ()
    assert "not mined" in facts.not_mined
    assert "cited_by_count" not in " ".join(
        figure.literal for figure in facts.figures)


def test_an_undeclared_serialization_is_a_fallback_with_a_reason() -> None:
    read = read_content(UNKNOWN)
    assert read.state is ContentState.FALLBACK
    # Legible: the blob is still returned for a model to read.
    assert read.text == UNKNOWN.decode("utf-8")
    assert "JSON serialization" in read.detail
    facts = facts_in(read)
    assert facts.figures == () and facts.dates == ()
    assert "not mined" in facts.not_mined


def test_red_proof_unformatted_falling_through_to_raw_decode_is_mined(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        content_module, "_unformatted_read",
        lambda text: ContentRead(text=text, state=ContentState.CONTENT,
                                 format="", fields=("text",)))
    read = read_content(UNKNOWN)
    assert read.state is ContentState.CONTENT
    facts = facts_in(read)
    assert [figure.literal for figure in facts.figures] == ["34"]
    assert {date.iso for date in facts.dates} == {"2020-09-27"}
    with pytest.raises(AssertionError):
        assert read.state is ContentState.FALLBACK
    with pytest.raises(AssertionError):
        assert facts.figures == ()


# ═══════════════ 5. The control — the real work still reads ═══════════════


def _assert_the_real_work_still_reads(read: ContentRead) -> None:
    document = json.loads(OPENALEX_WORK.read_text(encoding="utf-8"))
    assert read.state is ContentState.CONTENT
    assert read.format == "openalex"
    assert read.fields == ("title", "display_name", "abstract")
    # 1,260 characters of title + abstract, not 33,727 of metadata. (The
    # pre-D1 report's 1,379 counted the identical display_name a second time;
    # the D1 dedup states the same title once, and the content is unchanged.)
    assert len(read.text) == 1260
    assert read.text.count(document["title"]) == 1
    assert read.text.startswith(document["title"])
    assert document["publication_date"] not in read.text
    assert "cited_by_count" not in read.text


def test_the_real_openalex_work_still_reads_and_a_quotation_is_grounded() -> None:
    read = read_content(OPENALEX_WORK.read_bytes(), format="openalex")
    _assert_the_real_work_still_reads(read)
    verdict = check_claim(CONTROL, read.text, subjects=SUBJECTS)
    assert verdict.grounded is True, verdict.detail
    assert verdict.refusal is None and verdict.caveat is None


def test_the_adapters_declare_the_formats_the_readers_dispatch() -> None:
    """The format is declared at fetch, not passed in by the reader's caller.

    The real fetch path is exercised end to end in
    ``test_ops5z5_one_text_model.py`` (the fetched artifact's metadata carries
    ``content_format`` and ``evidence_inspect`` dispatches on it); this test
    pins the declarations themselves, including the one provider shape the
    reader must refuse instead of guess at.
    """
    from hermes.tools.providers.adapters import resolve_adapter

    assert resolve_adapter("openalex")().fetch_content_format(
        "application/json") == "openalex"
    assert resolve_adapter("crossref")().fetch_content_format(
        "application/json") == "crossref"
    assert resolve_adapter("pubmed")().fetch_content_format(
        "text/xml") == "pubmed"
    # XHTML is a page, not an XML record: the HTML branch must win over the
    # generic `+xml` suffix, or a real page is declared unmodelled XML.
    assert resolve_adapter("openalex")().fetch_content_format(
        "application/xhtml+xml") == "html"
    # A provider supported at fetch and unsupported at read declares no
    # format; the reader reports that instead of guessing at the bytes.
    # (Semantic Scholar and Europe PMC declared their formats in OPS-5Z6;
    # CORE still has no content extractor, so it stays the honest example.)
    assert resolve_adapter("semantic-scholar")().fetch_content_format(
        "application/json") == "semantic-scholar"
    assert resolve_adapter("core")().fetch_content_format(
        "application/json") == ""


def test_red_proof_the_control_falling_through_to_raw_decode_loses_the_quote(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(content_module._EXTRACTORS, "openalex",
                        _raw_decode_as_content)
    read = read_content(OPENALEX_WORK.read_bytes(), format="openalex")
    with pytest.raises(AssertionError):
        _assert_the_real_work_still_reads(read)
    # The abstract is an inverted index in the serialization, so the verbatim
    # sentence is not present as prose and the gate cannot ground it.
    verdict = check_claim(CONTROL, read.text, subjects=SUBJECTS)
    assert verdict.grounded is False


# ═══════════════ the capability seam — carried, not inferred ═══════════════


class Clock:
    def now_utc(self) -> str:
        return CLOCK

    def monotonic(self) -> float:
        return 1000.0


class Rig:
    def __init__(self, conn: Any, store: ArtifactStore, supply: Any) -> None:
        self.conn = conn
        self.store = store
        self.invoker = CapabilityInvoker(
            registry=supply.registry,
            implementations=supply.implementations,
            clock=Clock(),
            ledger=InMemoryIdempotencyLedger(),
            sandbox_enabled=False)

    def inspect(self, ref: str, *, key: str) -> Observation:
        result = self.invoker.invoke(InvokeRequest(
            capability_id="evidence_inspect",
            arguments={"ref": ref},
            idempotency_key=key,
            lease_generation="lease-ops5z-group-c",
            profile=PROFILE,
            rationale="falsify the source's facts before accepting them",
            grant=ToolGrant(
                grant_id="grant.ops5z-group-c",
                profile=PROFILE,
                tool_set_ids=frozenset(
                    {supply_module.FALSIFICATION_TOOL_SET_ID}),
                max_risk=RiskLevel.LOW.value),
            deadline_seconds=10.0))
        assert isinstance(result, Observation), result
        assert result.ok(), result.detail
        return result

    def admit(self, data: bytes, artifact_id: str, *,
              content_format: str = "") -> dict[str, Any]:
        metadata = ({"content_format": content_format}
                    if content_format else None)
        return self.store.write(
            data, "source_payload", "test.ops5z-group-c",
            project_id=PROJECT, artifact_id=artifact_id, metadata=metadata)


@pytest.fixture
def rig(tmp_path: Path):
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: CLOCK).create(PROJECT, "OPS-5Z Group C")
    store = ArtifactStore(
        str(tmp_path / "store"),
        ArtifactRepository(conn, lambda: CLOCK),
        clock=lambda: CLOCK)
    wiring = build_live_fetch_wiring(conn, store, lambda: CLOCK)
    supply = build_research_egress_supply(
        conn=conn, store=store, clock=lambda: CLOCK, project_id=PROJECT,
        machinery=wiring.machinery, allowlist=ALLOWLIST_HOSTS)
    yield Rig(conn, store, supply)
    conn.close()


def _payload(observation: Observation) -> dict[str, Any]:
    assert observation.payload is not None
    return json.loads(observation.payload.text)


def test_evidence_inspect_dispatches_on_the_carried_format(rig) -> None:
    row = rig.admit(CROSSREF, "art-carried", content_format="crossref")
    payload = _payload(rig.inspect(f"evidence/{row['artifact_id']}",
                                   key="carried"))
    assert payload["read"]["read"] == "content"
    assert payload["read"]["format"] == "crossref"
    assert [figure["literal"] for figure in payload["facts"]["figures"]] == [
        "1,200"]


def test_evidence_inspect_reports_an_undeclared_fallback_not_silence(rig) -> None:
    """The same bytes, no carried format: shown as a fallback, never mined."""
    row = rig.admit(CROSSREF, "art-undeclared")
    observation = rig.inspect(f"evidence/{row['artifact_id']}",
                              key="undeclared")
    payload = _payload(observation)
    assert payload["read"]["read"] == "fallback"
    assert payload["facts"]["figures"] == []
    assert payload["facts"]["dates"] == []
    # The empty fact list names its reason; it is not "the source says
    # nothing".
    assert "not mined" in payload["facts"]["not_mined"]
    assert "no fact was extracted" in observation.detail


def test_evidence_inspect_refuses_a_declared_shape_that_is_not_there(rig) -> None:
    row = rig.admit(CROSSREF_NO_CONTENT, "art-missing",
                    content_format="crossref")
    result = rig.invoker.invoke(InvokeRequest(
        capability_id="evidence_inspect",
        arguments={"ref": f"evidence/{row['artifact_id']}"},
        idempotency_key="missing",
        lease_generation="lease-ops5z-group-c",
        profile=PROFILE,
        rationale="the record's content is not readable",
        grant=ToolGrant(
            grant_id="grant.ops5z-group-c",
            profile=PROFILE,
            tool_set_ids=frozenset({supply_module.FALSIFICATION_TOOL_SET_ID}),
            max_risk=RiskLevel.LOW.value),
        deadline_seconds=10.0))
    assert isinstance(result, Observation), result
    payload = _payload(result)
    assert payload["status"] == "REFUSED"
    assert payload["code"] == supply_module.INSPECT_CONTENT_UNREADABLE
