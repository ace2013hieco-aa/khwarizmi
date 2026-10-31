"""INSPIRE-HEP adapter — literature search (JSON).

Search: ``GET literature`` with ``q`` (+ ``size``, ``page``). Records live
under ``hits.hits``, each one a ``{id, links, metadata}`` document: the title
is in ``metadata.titles[0].title`` and identifiers in ``metadata.dois`` /
``metadata.arxiv_eprints``. No credentials (auth ``none``).

Written against the captured search response
``inspirehep_search_muon_g2_813721.json`` and its single-record companion
``inspirehep_record_muon_g2_813721.json`` (see
``tests/fixtures/source_payloads/capture_manifest.json``). The record URL a
search row points at is the API's own JSON form — the ``links.json`` the
provider reports — so a fetch of that row returns the record, not an HTML
landing page.
"""
from __future__ import annotations

from typing import Any, Mapping

from hermes.tools.capabilities.content import ContentFormat
from hermes.tools.providers.adapters.base_adapter import (
    JsonSearchAdapter,
    make_contract,
)
from hermes.tools.providers.base import media_kind

__all__ = ["InspirehepAdapter"]


def _first_title(metadata: Mapping[str, Any]) -> str:
    titles = metadata.get("titles")
    if not isinstance(titles, list):
        return ""
    for item in titles:
        if isinstance(item, Mapping):
            value = item.get("title")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _publication_doi(metadata: Mapping[str, Any]) -> str:
    dois = metadata.get("dois")
    if not isinstance(dois, list):
        return ""
    for item in dois:
        if not isinstance(item, Mapping):
            continue
        value = item.get("value")
        if (isinstance(value, str) and value.strip()
                and item.get("material") in (None, "publication")):
            return value.strip()
    return ""


def _arxiv_id(metadata: Mapping[str, Any]) -> str:
    eprints = metadata.get("arxiv_eprints")
    if not isinstance(eprints, list):
        return ""
    for item in eprints:
        if isinstance(item, Mapping):
            value = item.get("value")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


class InspirehepAdapter(JsonSearchAdapter):
    provider_id = "inspirehep"
    base_url = "https://inspirehep.net/api/"
    contract = make_contract(
        "inspirehep", base_url,
        hint_routes={"doi": "literature", "arxiv": "literature",
                     "topic": "literature"},
        pagination={"kind": "offset", "start_param": "page",
                    "page_size_cap": 100, "max_pages": 50,
                    "loop_guard": 200},
        hazard_spec_version="unshipped",
        retry_class_map={"THROTTLED": "transient", "TIMEOUT": "transient",
                         "MALFORMED_200": "permanent"})
    search_path = "literature"
    query_param = "q"
    page_param = "page"
    page_size_param = "size"
    # The canonical record service is ``hits.hits``; the list-shaped
    # fallbacks keep the shared adapter contract (a page of records) true.
    items_paths = ("hits.hits", "items", "results")
    id_fields = ("id",)
    content_format = ContentFormat.INSPIREHEP

    def _row_to_record(self, row: dict) -> dict[str, Any]:
        """Project one INSPIRE hit onto the shared record keys.

        Only identifiers and the record URL leave this method: the walk carries
        ``title`` and ``source_url``, and a search row is provenance, not
        content. The content read is the artifact's job (``read_content``),
        and it reads the captured record shape, never this projection.
        """
        record = super()._row_to_record(row)
        metadata = row.get("metadata")
        if not isinstance(metadata, Mapping):
            return record
        title = _first_title(metadata)
        if title:
            record["title"] = title
        links = row.get("links")
        if isinstance(links, Mapping) and isinstance(links.get("json"), str):
            record["url"] = links["json"]
        elif row.get("id") not in (None, ""):
            record["url"] = f"{self.base_url}literature/{row['id']}?format=json"
        doi = _publication_doi(metadata)
        if doi:
            record["doi"] = doi
        arxiv = _arxiv_id(metadata)
        if arxiv:
            record["arxiv"] = arxiv
        return record

    def fetch_content_format(self, media_type: str | None) -> str:
        """A JSON record from the literature API is declared; a page is not."""
        if media_kind(media_type) == "json":
            return ContentFormat.INSPIREHEP
        return super().fetch_content_format(media_type)
