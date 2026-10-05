"""PubMed adapter (CHG-2 step 5) — NCBI E-utilities (XML + JSON).

Search: ``GET esearch.fcgi`` (``db=pubmed``, ``term``, ``retmode=json``
supported by the API). Records are ``IdList/Id`` elements (XML) or
``esearchresult/idlist`` (JSON). No credentials (auth ``none``).
"""
from __future__ import annotations

import xml.etree.ElementTree as _XET  # type: ignore[import-untyped]
from typing import Any

from hermes.tools.providers.adapters.base_adapter import (
    JsonSearchAdapter,
    make_contract,
)
from hermes.tools.providers.base import Page, PageState

__all__ = ["PubmedAdapter"]


class PubmedAdapter(JsonSearchAdapter):
    provider_id = "pubmed"
    # C1 (P-AUTO-3 redteam): `parse_page` gained the eutils JSON idlist / XML
    # Id paths — a parser-behavior change, so the version is bumped and the
    # recorded corpus is re-stamped to it. `RecordedTransport` refuses a
    # version mismatch, so a pre-bump (v1) fixture can never silently replay
    # under the v2 parser.
    parser_version = "2"
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    contract = make_contract(
        "pubmed", base_url,
        hint_routes={"pmid": "esearch.fcgi?db=pubmed", "doi": "",
                     "topic": "esearch.fcgi?db=pubmed"},
        pagination={"kind": "offset", "start_param": "retstart",
                    "page_size_cap": 100, "max_pages": 50,
                    "loop_guard": 200},
        hazard_spec_version="unshipped",
        retry_class_map={"THROTTLED": "transient", "TIMEOUT": "transient",
                         "MALFORMED_200": "permanent"})
    search_path = "esearch.fcgi"
    query_param = "term"
    page_size_param = "retmax"
    extra_params = {"db": "pubmed", "retmode": "json"}
    items_paths = ("esearchresult.idlist", "items", "results")
    id_fields = ("pmid", "id")
    title_fields = ("title",)
    url_fields = ("url", "id")
    snippet_fields = ("abstract", "snippet")
    authors_fields = ("authors",)
    year_fields = ("pubdate", "year")
    venue_fields = ("source", "journal")
    xml_item_tags = ("Id", "PubmedArticle")
    xml_field_tags = {
        "pmid": ("Id", "PMID"),
        "title": ("ArticleTitle",),
        "abstract": ("AbstractText",),
        "author": ("Author", "LastName"),
        "pubdate": ("PubDate", "Year"),
        "source": ("Title", "Journal"),
    }

    def parse_page(self, payload: object, state: PageState) -> Page:
        """Handle PubMed's esearch JSON string idlist and XML element-text Ids."""
        if isinstance(payload, dict):
            node: object = payload
            for part in ["esearchresult", "idlist"]:
                if not isinstance(node, dict):
                    node = None
                    break
                node = node.get(part)
            if isinstance(node, list) and node and all(
                isinstance(v, str) for v in node
            ):
                rows: list[dict[str, Any]] = [
                    {"pmid": v, "id": v, "url": f"https://pubmed.ncbi.nlm.nih.gov/{v}/"}
                    for v in node  # type: ignore[union-attr]
                ]
                records = tuple(self._row_to_record(r) for r in rows)
                total: int | None = None
                raw = payload.get("esearchresult")
                if isinstance(raw, dict) and isinstance(raw.get("count"), str):
                    try:
                        total = int(raw["count"])
                    except ValueError:
                        total = None
                return Page(records=records, total=total, next_state=None, notes=())
        if isinstance(payload, str):
            rows2: list[dict[str, Any]] = []
            try:
                def _local(tag: str) -> str:
                    return tag.rsplit("}", 1)[-1]

                root = _XET.fromstring(payload)
                for el in root.iter():
                    if _local(el.tag) != "Id":
                        continue
                    text = (el.text or "").strip()
                    if text:
                        rows2.append(
                            {
                                "pmid": text,
                                "id": text,
                                "url": f"https://pubmed.ncbi.nlm.nih.gov/{text}/",
                            }
                        )
                if rows2:
                    records2 = tuple(self._row_to_record(r) for r in rows2)
                    return Page(records=records2, total=None, next_state=None, notes=())
            except _XET.ParseError:
                pass
        return super().parse_page(payload, state)
