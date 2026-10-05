"""Shared thin-adapter machinery (CHG-2, step 5).

``JsonSearchAdapter`` implements the four ``ProviderAdapter`` hooks
plus ``validate_fetch`` defaults over declarative per-provider tables
(base URL, paths, field candidates, pagination style). Provider modules
declare tables only — no per-provider control flow — so all adapters
satisfy the identical contract and the same contract tests.

JSON is the primary payload shape. XML payloads (arXiv Atom, PubMed
eutils) are handled by the small shared Atom/item extractor below
(stdlib ``xml.etree`` only, deterministic element order); providers
whose record shapes need richer XML handling note it on the module and
return an empty page with a note rather than fake-parsing.
"""
from __future__ import annotations

from typing import Any
from xml.etree import ElementTree as _ET

from hermes.tools.providers.base import (
    Page,
    PageState,
    ProviderAdapter,
    ProviderContractCard,
    RateProfile,
    RequestSpec,
)
from hermes.tools.providers.normalize import RetrievalHints, normalize_identifier
from hermes.tools.research_sources import SearchResult

__all__ = [
    "JsonSearchAdapter",
    "extract_xml_items",
    "first_present",
    "make_contract",
]


def first_present(record: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """First present non-empty value for a candidate key list."""
    if not isinstance(record, dict):
        return None
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value is not None and not isinstance(value, str):
            return value
    return None


def extract_xml_items(payload: str, item_tags: tuple[str, ...],
                      field_tags: dict[str, tuple[str, ...]]) -> list[dict]:
    """Minimal deterministic Atom/XML item extractor (stdlib only).

    Matches elements whose local tag name is in ``item_tags`` and reads
    child-element text for each ``field_tags`` entry (first non-empty
    match wins; ``@attr`` entries read attributes). Namespaces are
    ignored by local-name comparison. Returns raw dict rows.
    """
    try:
        root = _ET.fromstring(payload)
    except _ET.ParseError:
        return []

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    out: list[dict] = []
    for element in root.iter():
        if local(element.tag) not in item_tags:
            continue
        row: dict[str, object] = {}
        children = list(element)
        for field, tags in field_tags.items():
            for tag in tags:
                if tag.startswith("@"):
                    value = element.get(tag[1:])
                    if value:
                        row[field] = value
                        break
                    continue
                for child in children:
                    if local(child.tag) == tag and child.text is not None \
                            and child.text.strip():
                        row[field] = child.text.strip()
                        break
                if field in row:
                    break
        out.append(row)
    return out


def make_contract(
    provider_id: str,
    base_url: str,
    *,
    auth_policy: str = "none",
    hint_routes: dict[str, str] | None = None,
    pagination: dict | None = None,
    hazard_spec_version: str = "unshipped",
    rate_profile: RateProfile | None = None,
    retry_class_map: dict[str, str] | None = None,
) -> ProviderContractCard:
    """Contract card with sane CHG-2 defaults (explicit per-provider
    overrides live on the adapter module)."""
    return ProviderContractCard(
        provider_id=provider_id,
        base_url=base_url,
        auth_policy=auth_policy,  # type: ignore[arg-type]
        hint_routes=dict(hint_routes or {}),
        pagination=dict(pagination or {"kind": "offset"}),
        hazard_spec_version=hazard_spec_version,
        rate_profile=rate_profile or RateProfile(
            rps=1.0, burst=2, concurrency=1, daily_cap=1000),
        retry_class_map=dict(retry_class_map or {}),
    )


_ID_KINDS = ("doi", "pmid", "pmcid", "arxiv", "openalex_id", "core_id",
             "mag_id", "url")


class JsonSearchAdapter(ProviderAdapter):
    """Declarative JSON search adapter (CHG-2 step-5 thin shape).

    Subclasses set class attributes only: ``provider_id``,
    ``base_url``, ``contract``, ``search_path``, ``query_param``,
    ``items_paths``, field-candidate tuples, and optionally
    ``xml_item_tags``/``xml_field_tags`` for XML payloads.
    """

    provider_id: str = ""
    adapter_version: str = "1"
    parser_version: str = "1"
    # ``contract`` is inherited from ProviderAdapter and set per
    # provider module (each subclass assigns its own card).

    base_url: str = ""
    search_path: str = ""
    query_param: str = "q"
    page_param: str = "page"
    page_size_param: str = "page_size"
    # Fixed provider params merged into every search request (format
    # selectors, database selectors — never credentials).
    extra_params: dict[str, str] = {}
    items_paths: tuple[str, ...] = ("items", "results", "records", "works",
                                    "docs", "message.items")
    id_fields: tuple[str, ...] = ("id",)
    title_fields: tuple[str, ...] = ("title", "display_name")
    url_fields: tuple[str, ...] = ("url", "id", "link")
    snippet_fields: tuple[str, ...] = ("abstract", "snippet", "description")
    authors_fields: tuple[str, ...] = ("authors",)
    year_fields: tuple[str, ...] = ("year", "publication_year", "published")
    venue_fields: tuple[str, ...] = ("venue", "journal", "container-title",
                                     "publisher")
    xml_item_tags: tuple[str, ...] = ()
    xml_field_tags: dict[str, tuple[str, ...]] = {}

    def _query_text(self, hints: RetrievalHints) -> str:
        if hints.topic:
            return hints.topic
        for kind in sorted(hints.identifiers):
            value = hints.identifiers[kind]
            if value:
                return f"{kind}:{value}"
        return ""

    def build_request(self, hints: RetrievalHints, state: PageState,
                      page_size: int) -> RequestSpec:
        params = {self.query_param: self._query_text(hints),
                  self.page_size_param: str(page_size)}
        params.update(self.extra_params)
        if state.cursor is not None:
            params["cursor"] = state.cursor
        if state.offset is not None:
            params["offset"] = str(state.offset)
        elif state.page_index:
            params[self.page_param] = str(state.page_index + 1)
        return RequestSpec(url=self.base_url + self.search_path,
                           params=params, headers_meta={})

    def _items_from_json(self, payload: object) -> tuple[list[dict], int | None]:
        if not isinstance(payload, dict):
            return [], None
        total = payload.get("total")
        if not isinstance(total, int):
            meta = payload.get("meta")
            if isinstance(meta, dict) and isinstance(
                    meta.get("total"), int):
                total = meta["total"]
            else:
                message = payload.get("message")
                if isinstance(message, dict) and isinstance(
                        message.get("total-results"), int):
                    total = message["total-results"]
                else:
                    total = None
        for path in self.items_paths:
            node: object = payload
            for part in path.split("."):
                if not isinstance(node, dict):
                    node = None
                    break
                node = node.get(part)
            if isinstance(node, list):
                rows = [r for r in node if isinstance(r, dict)]
                return rows, total
        return [], total

    def _row_to_record(self, row: dict) -> dict[str, Any]:
        record: dict[str, Any] = {}
        for key, fields in (("title", self.title_fields),
                            ("url", self.url_fields),
                            ("snippet", self.snippet_fields),
                            ("venue", self.venue_fields)):
            value = first_present(row, fields)
            if isinstance(value, str):
                record[key] = value
        authors = first_present(row, self.authors_fields)
        if isinstance(authors, list):
            names = [a.get("name") if isinstance(a, dict) else a
                     for a in authors]
            record["authors"] = "; ".join(
                str(n) for n in names if n)
        elif isinstance(authors, str):
            record["authors"] = authors
        year = first_present(row, self.year_fields)
        if year is not None:
            record["year"] = str(year)
        for key in self.id_fields:
            value = row.get(key)
            if isinstance(value, (str, int)) and str(value).strip():
                record[key] = str(value).strip()
        return record

    def parse_page(self, payload: object, state: PageState) -> Page:
        if isinstance(payload, str):
            if not self.xml_item_tags:
                return Page(records=(), total=None, next_state=None,
                            notes=(("non-JSON payload not parsed by "
                                    f"{self.provider_id} adapter"),))
            rows = extract_xml_items(payload, self.xml_item_tags,
                                     self.xml_field_tags)
            records = tuple(self._row_to_record(r) for r in rows)
            return Page(records=records, total=None, next_state=None,
                        notes=())
        rows, total = self._items_from_json(payload)
        records = tuple(self._row_to_record(r) for r in rows)
        return Page(records=records, total=total, next_state=None, notes=())

    def extract_ids(self, record: dict) -> dict[str, str]:
        if not isinstance(record, dict):
            return {}
        out: dict[str, str] = {}
        for kind in _ID_KINDS:
            raw = record.get(kind)
            if not isinstance(raw, str) or not raw:
                continue
            canonical = normalize_identifier(kind, raw)
            if canonical is not None:
                out[kind] = canonical
        return out

    def build_fetch_request(self, source: SearchResult) -> RequestSpec:
        url = source.source_url
        if not isinstance(url, str) or not url:
            from hermes.tools.research_sources import ProviderValidationError
            raise ProviderValidationError(
                f"cannot fetch source without a URL "
                f"(provider {self.provider_id!r})")
        return RequestSpec(url=url, params={}, headers_meta={})
