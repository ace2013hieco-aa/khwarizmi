"""The text a reader would call an artifact's content — and whether it is.

One implementation, every consumer: the evidence envelope a model reads
(``hermes.agents.runtime.assembly``), the deterministic facts a capability
reports (``evidence_inspect``), the controller's stored-text and span readers,
and the methodology claim gate. A second extractor would let the model and the
falsifier disagree about the same bytes, which is the defect this function
exists to prevent.

It lives in ``hermes.tools.capabilities``, not ``hermes.tools.providers``,
because the agent runtime may import only ``hermes.core``, ``hermes.security``,
``hermes.tools.models``, ``hermes.tools.capabilities`` and itself — a provider
import there would cross a boundary the module-invariant test refuses. The
format *declarations* live on the adapters (``hermes.tools.providers.adapters``);
the one extractor implementation lives here, where both the runtime and the
research layer can reach it without importing a provider.

A read is a state, not a string
--------------------------------
``ContentRead`` carries the rendered text **and** what the renderer actually
read, as one of three states:

* ``content`` — the artifact's prose was extracted. Safe to mine.
* ``fallback`` — no format was declared for these bytes and they are a
  serialization. The blob is legible to a model, but it is never prose: a
  reader may show it and must never mine it.
* ``unreadable`` — a declared format could not be read (malformed, the wrong
  shape, or a provider supported at fetch and unsupported at read). Say why.

``semantic_text`` used to return the raw ``raw.decode`` of any shape it did not
recognise, and ``facts_in`` mined it as prose. That is how Crossref's
``is-referenced-by-count`` and ``date-parts``, an OpenAlex search wrapper's
``cited_by_count`` and ``publication_date``, and PubMed's PMID and journal date
became the source's facts (OPS-5Z audit N-F, second pass). The fix is not
"return nothing": a raw blob is legible, and showing it is not the bug. Mining
it is. So the state travels with the text and :func:`facts_in` refuses every
state but ``content``.

Deterministic and pure: no clock, no I/O, no model. The same bytes and the
same declared format always yield the same read.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as _ET
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from html import unescape
from typing import Any

__all__ = [
    "CONTENT_FIELDS",
    "REFUSED_CONTENT_FORMAT",
    "ArtifactRead",
    "ContentFormat",
    "ContentRead",
    "ContentState",
    "html_text",
    "read_content",
    "reconstruct_inverted",
    "semantic_text",
]

#: A reserved ``content_format`` token for a stored artifact the fetch gate
#: refused. It is **not** a provider format and no fetch path emits it; the
#: OPS-5Z backfill writes it so a refused artifact is unreadable for *every*
#: byte shape. An empty format would be enough for JSON or markup (both
#: ``fallback``), but undeclared plain text is ``content`` — and a refused
#: 203 text/plain body must not become prose. A reader that sees this token
#: returns ``unreadable`` with the gate's reason.
REFUSED_CONTENT_FORMAT = "refused"

#: Fields that carry a record's *content*, in the order a reader wants them.
#: An OpenAlex work is 33 KB of metadata, ORCIDs and affiliation strings, and its
#: abstract sits at byte 31,556 — past any excerpt a prompt can afford. A byte
#: prefix of that record is a title and a list of universities; it is not the
#: source. So the content is selected, not prefixed.
CONTENT_FIELDS: tuple[str, ...] = ("title", "display_name", "abstract")


class ContentState(StrEnum):
    """What the reader could make of an artifact's bytes."""

    CONTENT = "content"
    FALLBACK = "fallback"
    UNREADABLE = "unreadable"


class ContentFormat(StrEnum):
    """A format a fetch path can declare for the bytes it stored.

    A *declared* token is a fact about the response the provider returned; it is
    never inferred from the bytes. A token with no extractor (for example a
    provider whose search page is modelled but whose fetched record is not) is
    reported ``unreadable`` — the signal that a provider is supported at fetch
    and unsupported at read.
    """

    OPENALEX = "openalex"
    CROSSREF = "crossref"
    PUBMED = "pubmed"
    ARXIV = "arxiv"
    INSPIREHEP = "inspirehep"
    SEMANTIC_SCHOLAR = "semantic-scholar"
    EUROPEPMC = "europepmc"
    HTML = "html"
    TEXT = "text"


@dataclass(frozen=True, slots=True)
class ArtifactRead:
    """An artifact's bytes and the format the fetch path declared for them.

    The pair travels together so no reader has to infer the shape from the
    bytes. ``format`` is a :class:`ContentFormat` token; an empty value means
    the artifact's carrier did not declare one.
    """

    data: bytes
    format: str = ""


@dataclass(frozen=True, slots=True)
class ContentRead:
    """The rendered content and what the renderer could and could not read.

    ``state`` is the whole contract: ``content`` is prose that is safe to
    mine; ``fallback`` is a serialization that may be shown but never mined;
    ``unreadable`` is nothing extracted, with ``detail`` naming why. ``fields``
    names what was read, so a partial read (``("title",)`` with an
    unreconstructable abstract) is visible even though the title itself is
    content. ``format`` echoes the declared token (empty when none was
    declared), so a caller can see which dispatcher answered.
    """

    text: str
    state: ContentState
    format: str = ""
    fields: tuple[str, ...] = ()
    detail: str = ""

    @property
    def is_content(self) -> bool:
        """True exactly when ``text`` is the artifact's prose."""
        return self.state == ContentState.CONTENT

    @property
    def partial(self) -> bool:
        """True when some part of the artifact could not be read.

        A partial read is still ``content`` for what it did extract — a title
        is prose — but the detail names the part that is missing, and the
        claim gate treats the artifact as not fully readable.
        """
        return self.is_content and bool(self.detail)

    def __iter__(self) -> Iterator[str | ContentState]:
        """The ``(text, state)`` pair, for a caller that unpacks the read."""
        yield self.text
        yield self.state

    def to_mapping(self) -> dict[str, Any]:
        """The canonical, JSON-ready form a capability reports.

        ``read`` carries the state vocabulary (not a boolean): the envelope's
        field of that name has always meant "what did the reader do", and a
        caller that wants a yes/no asks ``state == "content"`` explicitly.
        """
        return {"read": self.state.value, "format": self.format,
                "fields": list(self.fields), "detail": self.detail}


def reconstruct_inverted(index: Mapping[str, Any]) -> str:
    """OpenAlex stores an abstract as ``{word: [positions]}``; rebuild the prose.

    Positions are 0-based word slots, so sorting them recovers the original
    order without guessing at punctuation. A malformed entry is skipped, never
    guessed at: a reconstruction that invents a word is worse than one that is
    short, and ``facts_in`` reports what it could not read.
    """
    slots: list[tuple[int, str]] = []
    for word, places in index.items():
        if not isinstance(word, str) or not isinstance(places, Sequence):
            # Malformed index. Dropping the word would return a *different*
            # abstract — a shorter one the source never wrote — and the reader
            # cannot tell. Say nothing instead: no abstract is honest, a
            # quietly truncated one is not.
            return ""
        if isinstance(places, (str, bytes)):
            return ""
        for place in places:
            if isinstance(place, bool) or not isinstance(place, int):
                return ""
            slots.append((place, word))
    slots.sort(key=lambda slot: slot[0])
    by_position: dict[int, set[str]] = {}
    for place, word in slots:
        by_position.setdefault(place, set()).add(word)
    if any(len(words) > 1 for words in by_position.values()):
        # Two different words claim one slot. Joining them in sort order
        # produces a sentence that never existed, which is worse than none.
        return ""
    return " ".join(word for _, word in slots)


def html_text(markup: str) -> str:
    """Tag-stripped, entity-decoded, whitespace-collapsed text."""
    without_script = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", markup)
    text = re.sub(r"(?s)<[^>]+>", " ", without_script)
    return " ".join(unescape(text).split())


_MARKUP_TAG = re.compile(r"<\s*/?\s*[A-Za-z!][^>]*>")


def _clean(text: str) -> str:
    """A field's text: markup stripped when it is markup, whitespace bounded.

    A tag is `<name ...>` or `</name>`, not any `<`. A statistics abstract that
    says ``p < 0.05 and q > 0.1`` must not lose the words between the
    comparison signs to a tag-strip that thought it saw markup.
    """
    if _MARKUP_TAG.search(text):
        return html_text(text)
    return text.strip()


def _has_content_field(document: Mapping[str, Any]) -> bool:
    title = document.get("title")
    if isinstance(title, (list, tuple)) and any(
            isinstance(item, str) and item.strip() for item in title):
        return True
    for name in CONTENT_FIELDS:
        value = document.get(name)
        if isinstance(value, str) and value.strip():
            return True
    return isinstance(document.get("abstract_inverted_index"), Mapping)


def _work_parts(document: Mapping[str, Any]
                ) -> tuple[list[str], list[str], list[str]]:
    """One record's selected content fields, and any read problem.

    Crossref puts ``title`` in a list and its abstract in JATS markup; OpenAlex
    puts a display name beside the title and its abstract in an inverted index.
    Both are selected by *name*, never by scanning the serialization, so
    ``date-parts``, ``is-referenced-by-count`` and ``cited_by_count`` never
    become the artifact's facts.
    """
    parts: list[str] = []
    fields: list[str] = []
    problems: list[str] = []

    def add(name: str, text: str) -> None:
        cleaned = _clean(text)
        if not cleaned:
            return
        if cleaned not in parts:
            parts.append(cleaned)
        if name not in fields:
            fields.append(name)

    title = document.get("title")
    if isinstance(title, (list, tuple)):
        joined = " ".join(str(item) for item in title
                          if isinstance(item, str) and item.strip())
        if joined:
            add("title", joined)
    for name in CONTENT_FIELDS:
        value = document.get(name)
        if not isinstance(value, str) or not value.strip():
            continue
        if name == "title" and "title" in fields:
            continue
        add(name, value)
    # The plain abstract wins. ``abstract_inverted_index`` reconstructs the
    # same field, so appending both stated every date and figure twice — an
    # inflation of what the source appears to say (OPS-5Z audit N-F).
    if "abstract" not in fields:
        inverted = document.get("abstract_inverted_index")
        if isinstance(inverted, Mapping):
            rebuilt = reconstruct_inverted(inverted)
            if rebuilt:
                add("abstract", rebuilt)
            elif inverted:
                # An index is present, so an abstract exists; returning the
                # title alone would say this record has none.
                problems.append(
                    "the abstract index is present but cannot be "
                    "reconstructed (malformed or ambiguous)")
    return parts, fields, problems


def _record_read(document: Mapping[str, Any], fmt: str,
                 missing: str) -> ContentRead:
    parts, fields, problems = _work_parts(document)
    if parts:
        return ContentRead(text="\n\n".join(parts), state=ContentState.CONTENT,
                           format=fmt, fields=tuple(fields),
                           detail="; ".join(problems))
    return ContentRead(text="", state=ContentState.UNREADABLE, format=fmt,
                       detail=missing)


def _json_document(text: str, fmt: str) -> Mapping[str, Any] | ContentRead:
    """The parsed top-level object, or the unreadable result that replaces it."""
    try:
        document = json.loads(text)
    except ValueError:
        return ContentRead(
            text=text, state=ContentState.UNREADABLE, format=fmt,
            detail=(f"the artifact is declared {fmt!r} but does not parse as "
                    "JSON; no field could be selected"))
    if not isinstance(document, Mapping):
        return ContentRead(
            text=text, state=ContentState.UNREADABLE, format=fmt,
            detail=(f"the artifact is declared {fmt!r} but the document is a "
                    f"{type(document).__name__}, not a record"))
    return document


#: The record-list keys a fetched wrapper can use. A wrapper is *not* content:
#: it is a container, and only the first record (the fetched source) is read.
_WRAPPER_KEYS: tuple[str, ...] = ("results", "data", "items")


def _first_record(document: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for key in _WRAPPER_KEYS:
        value = document.get(key)
        if isinstance(value, list) and value and isinstance(value[0], Mapping):
            return value[0]
    return None


def _read_openalex(text: str, fmt: str) -> ContentRead:
    """An OpenAlex work — or a search wrapper's first result — field-wise."""
    document = _json_document(text, fmt)
    if isinstance(document, ContentRead):
        return document
    if not _has_content_field(document):
        first = _first_record(document)
        if first is not None and _has_content_field(first):
            document = first
        else:
            return ContentRead(
                text=text, state=ContentState.UNREADABLE, format=fmt,
                detail=("no content field (title, display_name, abstract) is "
                        "present in this OpenAlex record; cited_by_count, "
                        "publication_date and the wrapper's meta are metadata, "
                        "not prose"))
    return _record_read(
        document, fmt,
        "no content field (title, display_name, abstract) is present in this "
        "OpenAlex record; cited_by_count and publication_date are metadata, "
        "not prose")


def _read_crossref(text: str, fmt: str) -> ContentRead:
    """A Crossref ``message`` record — or a list wrapper's first item."""
    document = _json_document(text, fmt)
    if isinstance(document, ContentRead):
        return document
    message = document.get("message")
    if not isinstance(message, Mapping):
        return ContentRead(
            text=text, state=ContentState.UNREADABLE, format=fmt,
            detail=("the artifact is declared 'crossref' but carries no "
                    "'message' record; a Crossref response always wraps the "
                    "work, and the outer envelope is metadata, not prose"))
    first = _first_record(message)
    if first is not None:
        message = first
    if not _has_content_field(message):
        return ContentRead(
            text=text, state=ContentState.UNREADABLE, format=fmt,
            detail=("no content field (title, abstract) is present in this "
                    "Crossref record; date-parts and is-referenced-by-count "
                    "are metadata, not prose"))
    return _record_read(
        message, fmt,
        "no content field (title, abstract) is present in this Crossref "
        "record; date-parts and is-referenced-by-count are metadata, not "
        "prose")


def _local_name(tag: object) -> str:
    return str(tag).rsplit("}", 1)[-1].casefold()


def _element_text(element: Any) -> str:
    return " ".join("".join(element.itertext()).split())


def _read_pubmed(text: str, fmt: str) -> ContentRead:
    """PubMed XML read field-wise: titles and abstracts, never metadata.

    A whole-document tag strip made ``1,200`` bind to ``Containment`` and ``23``
    to ``Jan`` because the PMID, journal and publication date were prose too
    (OPS-5Z audit N-F). Only ``ArticleTitle`` and ``AbstractText`` are content.
    """
    try:
        root = _ET.fromstring(text.lstrip("\ufeff \t\r\n"))
    except _ET.ParseError as exc:
        return ContentRead(
            text=text, state=ContentState.UNREADABLE, format=fmt,
            detail=f"the artifact is declared 'pubmed' but the XML does not "
                   f"parse ({exc})")
    parts: list[str] = []
    fields: list[str] = []
    for record in root.iter():
        if _local_name(record.tag) not in ("pubmedarticle", "pubmedbookarticle"):
            continue
        title = next((_element_text(element) for element in record.iter()
                      if _local_name(element.tag) == "articletitle"), "")
        abstracts = [_element_text(element) for element in record.iter()
                     if _local_name(element.tag) == "abstracttext"]
        for name, value in (("title", title),
                            ("abstract", " ".join(item for item in abstracts
                                                  if item))):
            if not value:
                continue
            if value not in parts:
                parts.append(value)
            if name not in fields:
                fields.append(name)
    if not parts:
        return ContentRead(
            text=text, state=ContentState.UNREADABLE, format=fmt,
            detail=("no content field (title, abstract) is present in this "
                    "PubMed record; the PMID, journal and dates are metadata"))
    return ContentRead(text="\n\n".join(parts), state=ContentState.CONTENT,
                       format=fmt, fields=tuple(fields))


def _fields_read(fmt: str, parts: Sequence[str], fields: Sequence[str],
                 missing: str) -> ContentRead:
    """A read built from selected content fields, or the named refusal.

    The per-provider extractors below all end the same way: prose joined from
    the fields they selected, or ``unreadable`` naming the fields that are
    metadata. One shape keeps the refusal vocabulary identical across them.
    """
    if parts:
        return ContentRead(text="\n\n".join(parts), state=ContentState.CONTENT,
                           format=fmt, fields=tuple(fields))
    return ContentRead(text="", state=ContentState.UNREADABLE, format=fmt,
                       detail=missing)


def _read_arxiv(text: str, fmt: str) -> ContentRead:
    """An arXiv Atom feed: the first ``entry``'s title and summary.

    Written against ``arxiv_entry_ligo_160203837.xml`` — the exact bytes of a
    real ``export.arxiv.org/api/query?id_list=…`` response. The feed's ``id``,
    ``title``, ``updated`` and the ``opensearch`` counts are the query
    envelope, and the entry's ``id``, ``published``, ``updated``, ``link``,
    ``category`` and ``arxiv:journal_ref`` are metadata. Only the entry's
    ``title`` and ``summary`` are content.

    The first entry is read, not every entry: one fetched artifact is one
    source, and a multi-entry feed would concatenate several records' facts
    into prose the source never wrote.
    """
    try:
        root = _ET.fromstring(text.lstrip("\ufeff \t\r\n"))
    except _ET.ParseError as exc:
        return ContentRead(
            text=text, state=ContentState.UNREADABLE, format=fmt,
            detail=f"the artifact is declared 'arxiv' but the Atom feed does "
                   f"not parse ({exc})")
    entry = next((element for element in root.iter()
                  if _local_name(element.tag) == "entry"), None)
    if entry is None:
        return ContentRead(
            text=text, state=ContentState.UNREADABLE, format=fmt,
            detail=("no 'entry' element is present in this arXiv feed; the "
                    "feed id, title, updated and opensearch counts are the "
                    "query envelope, not the record"))
    parts: list[str] = []
    fields: list[str] = []
    for name, tag in (("title", "title"), ("abstract", "summary")):
        value = next((_element_text(child) for child in entry
                      if _local_name(child.tag) == tag), "")
        cleaned = _clean(value)
        if cleaned and cleaned not in parts:
            parts.append(cleaned)
            fields.append(name)
    return _fields_read(
        fmt, parts, fields,
        "no content field (title, summary) is present in this arXiv entry; "
        "the entry's id, published date, links and categories are metadata, "
        "not prose")


def _first_mapping_value(items: object, key: str) -> str:
    """The first non-empty string under ``key`` in a list of records."""
    if not isinstance(items, list):
        return ""
    for item in items:
        if not isinstance(item, Mapping):
            continue
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _read_inspirehep(text: str, fmt: str) -> ContentRead:
    """An INSPIRE-HEP literature record: its primary title and abstract.

    Written against ``inspirehep_record_muon_g2_813721.json`` — the exact
    bytes of ``inspirehep.net/api/literature/813721?format=json``. A fetched
    artifact is one record (``metadata`` at the top level), not a search
    wrapper: ``hits``/``links`` belong to the search envelope.

    Only the *first* title and the *first* abstract are read. The captured
    record repeats its title under an arXiv-sourced entry and can carry the
    same abstract in plain and LaTeX spellings; appending every variant would
    state each figure again — the Crossref/OPS-5Z N-F inflation in a new
    shape. ``citation_count``, ``dois``, ``preprint_date``,
    ``publication_info`` and the author list are metadata, not prose.
    """
    document = _json_document(text, fmt)
    if isinstance(document, ContentRead):
        return document
    metadata = document.get("metadata")
    if not isinstance(metadata, Mapping):
        return ContentRead(
            text=text, state=ContentState.UNREADABLE, format=fmt,
            detail=("no 'metadata' record is present in this INSPIRE-HEP "
                    "body; a search wrapper's hits and links are a hit list, "
                    "not the fetched record, and its counts are metadata"))
    parts: list[str] = []
    fields: list[str] = []
    for name, items, key in (
            ("title", metadata.get("titles"), "title"),
            ("abstract", metadata.get("abstracts"), "value")):
        cleaned = _clean(_first_mapping_value(items, key))
        if cleaned:
            parts.append(cleaned)
            fields.append(name)
    return _fields_read(
        fmt, parts, fields,
        "no content field (title, abstract) is present in this INSPIRE-HEP "
        "record; citation_count, dois and preprint_date are metadata, not "
        "prose")


def _read_semantic_scholar(text: str, fmt: str) -> ContentRead:
    """A Semantic Scholar paper record: ``title`` and ``abstract``.

    Written against ``semanticscholar_paper_ligo_116061102.json`` — the exact
    bytes of ``api.semanticscholar.org/graph/v1/paper/DOI:…``. The search
    wrapper (``data``) is a hit list, not the record: only a document that
    carries the fields itself is read. ``citationCount``, ``externalIds``
    (the DOI included), ``publicationDate``, ``year`` and ``venue`` are
    metadata, not prose.
    """
    document = _json_document(text, fmt)
    if isinstance(document, ContentRead):
        return document
    parts: list[str] = []
    fields: list[str] = []
    for name in ("title", "abstract"):
        value = document.get(name)
        cleaned = _clean(value) if isinstance(value, str) else ""
        if cleaned:
            parts.append(cleaned)
            fields.append(name)
    return _fields_read(
        fmt, parts, fields,
        "no content field (title, abstract) is present in this Semantic "
        "Scholar body; citationCount, externalIds and publicationDate are "
        "metadata, not prose")


def _read_europepmc(text: str, fmt: str) -> ContentRead:
    """A Europe PMC ``resultList.result`` record: ``title`` and abstract.

    Written against ``europepmc_search_isaric_1985.json`` — the exact bytes of
    ``ebi.ac.uk/europepmc/webservices/rest/search?…&resultType=core``. The
    first result is read; ``hitCount``, ``request`` and ``nextCursorMark``
    are the envelope. ``citedByCount``, ``doi``, ``pubYear``,
    ``firstPublicationDate``, ``journalInfo`` and the author list are
    metadata, not prose.
    """
    document = _json_document(text, fmt)
    if isinstance(document, ContentRead):
        return document
    listing = document.get("resultList")
    record = None
    if isinstance(listing, Mapping):
        rows = listing.get("result")
        if isinstance(rows, list):
            record = next((row for row in rows if isinstance(row, Mapping)),
                          None)
    if record is None:
        return ContentRead(
            text=text, state=ContentState.UNREADABLE, format=fmt,
            detail=("no 'resultList.result' record is present in this Europe "
                    "PMC body; hitCount, request and nextCursorMark are the "
                    "search envelope, not the fetched source"))
    parts: list[str] = []
    fields: list[str] = []
    for name, key in (("title", "title"), ("abstract", "abstractText")):
        value = record.get(key)
        cleaned = _clean(value) if isinstance(value, str) else ""
        if cleaned:
            parts.append(cleaned)
            fields.append(name)
    return _fields_read(
        fmt, parts, fields,
        "no content field (title, abstractText) is present in this Europe "
        "PMC record; citedByCount, doi and firstPublicationDate are "
        "metadata, not prose")


def _read_html(text: str, fmt: str) -> ContentRead:
    rendered = html_text(text)
    if not rendered:
        return ContentRead(
            text=text, state=ContentState.UNREADABLE, format=fmt,
            detail="the artifact is declared 'html' but carries no text")
    return ContentRead(text=rendered, state=ContentState.CONTENT, format=fmt,
                       fields=("html",))


def _read_text(text: str, fmt: str) -> ContentRead:
    if not text.strip():
        return ContentRead(
            text=text, state=ContentState.UNREADABLE, format=fmt,
            detail="the artifact is declared 'text' but is empty")
    return ContentRead(text=text, state=ContentState.CONTENT, format=fmt,
                       fields=("text",))


#: One extractor per declared token. A token absent here is not guessed at:
#: it is reported unreadable, which names a provider supported at fetch and
#: unsupported at read instead of mining whatever happens to be in the bytes.
_EXTRACTORS: dict[str, Callable[[str, str], ContentRead]] = {
    ContentFormat.OPENALEX: _read_openalex,
    ContentFormat.CROSSREF: _read_crossref,
    ContentFormat.PUBMED: _read_pubmed,
    ContentFormat.ARXIV: _read_arxiv,
    ContentFormat.INSPIREHEP: _read_inspirehep,
    ContentFormat.SEMANTIC_SCHOLAR: _read_semantic_scholar,
    ContentFormat.EUROPEPMC: _read_europepmc,
    ContentFormat.HTML: _read_html,
    ContentFormat.TEXT: _read_text,
}


def _format_token(value: ContentFormat | str | None) -> str:
    """A declared format as its canonical token (``""`` when none was given)."""
    if isinstance(value, ContentFormat):
        return value.value
    if not isinstance(value, str):
        return ""
    return value.strip().casefold()


def _unformatted_read(text: str) -> ContentRead:
    """The read for bytes whose carrier declared no format.

    Plain text is prose and is content. A serialization is not, and is not
    guessed at: the blob is legible to a model (``fallback``) and is never
    mined. This is the one place the state can be ``fallback``; a *declared*
    format that fails is ``unreadable``, because the provider promised a shape
    the reader models.
    """
    stripped = text.lstrip("\ufeff \t\r\n")
    if stripped.startswith("{") or stripped.startswith("["):
        return ContentRead(
            text=text, state=ContentState.FALLBACK, format="",
            detail=("the carrier declared no format and the bytes are a JSON "
                    "serialization; they are legible to a model but are not "
                    "prose, and were not mined"))
    if stripped.startswith("<"):
        return ContentRead(
            text=text, state=ContentState.FALLBACK, format="",
            detail=("the carrier declared no format and the bytes are markup; "
                    "they are legible to a model but tag-stripping would "
                    "present metadata as prose, so nothing was mined"))
    return ContentRead(text=text, state=ContentState.CONTENT,
                       format=ContentFormat.TEXT, fields=("text",))


def read_content(raw: bytes, *,
                 format: ContentFormat | str | None = None) -> ContentRead:
    """The part of an artifact a reader would call its content, plus its state.

    ``format`` is the shape the fetch path declared for these bytes — never a
    guess made here. A declared token with an extractor is read field-wise; a
    declared token without one is ``unreadable`` (supported at fetch,
    unsupported at read). The reserved :data:`REFUSED_CONTENT_FORMAT` token is a
    migration state, not a provider format: it is always unreadable, with the
    gate's reason, for every byte shape. With no declared format, plain text is
    content and a serialization is ``fallback``: legible, never mined.
    """
    declared = _format_token(format)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        # Keep a displayable rendering, but never call it a clean read: the
        # replacement characters stand for bytes the renderer did not read.
        text = raw.decode("utf-8", "replace")
        return ContentRead(
            text=text, state=ContentState.UNREADABLE, format=declared,
            detail="the artifact is not valid UTF-8 text")

    if declared == REFUSED_CONTENT_FORMAT:
        return ContentRead(
            text=text, state=ContentState.UNREADABLE, format=declared,
            detail=("the artifact is recorded not citable: the fetch gate "
                    "refused its bytes (the artifact's content_gate metadata "
                    "names the code)"))
    extractor = _EXTRACTORS.get(declared)
    if extractor is not None:
        return extractor(text, declared)
    if declared:
        return ContentRead(
            text=text, state=ContentState.UNREADABLE, format=declared,
            detail=(f"the artifact is declared {declared!r} but this reader "
                    "has no extractor for that format; the provider is "
                    "supported at fetch and unsupported at read, so the bytes "
                    "were not mined"))
    return _unformatted_read(text)


def semantic_text(raw: bytes, *,
                  format: ContentFormat | str | None = None) -> ContentRead:
    """The typed read of an artifact: ``(text, state)`` on one value.

    ``semantic_text`` is the name every consumer already calls; it now answers
    both questions a string could not: the text a model may read, and whether
    that text is the artifact's prose. A caller that mines facts passes this
    result to :func:`hermes.research.inspection.facts_in`, which refuses every
    state but ``content``.
    """
    return read_content(raw, format=format)
