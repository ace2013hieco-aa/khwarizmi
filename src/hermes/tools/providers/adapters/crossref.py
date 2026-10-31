"""Crossref adapter (CHG-2 step 5) — works search (JSON).

Search: ``GET works`` with ``query`` (+ ``rows``). Records live under
``message.items``. No credentials (auth ``none``; polite pool via
mailto belongs to deployment config, never to the adapter).
"""
from __future__ import annotations

from hermes.tools.capabilities.content import ContentFormat
from hermes.tools.providers.adapters.base_adapter import (
    JsonSearchAdapter,
    make_contract,
)
from hermes.tools.providers.base import media_kind

__all__ = ["CrossrefAdapter"]


class CrossrefAdapter(JsonSearchAdapter):
    provider_id = "crossref"
    base_url = "https://api.crossref.org/"
    contract = make_contract(
        "crossref", base_url,
        hint_routes={"doi": "works", "topic": "works"},
        pagination={"kind": "offset", "start_param": "offset",
                    "page_size_cap": 100, "max_pages": 50,
                    "loop_guard": 200},
        hazard_spec_version="unshipped",
        retry_class_map={"THROTTLED": "transient", "TIMEOUT": "transient",
                         "MALFORMED_200": "permanent"})
    search_path = "works"
    query_param = "query"
    page_size_param = "rows"
    items_paths = ("message.items", "items", "results")
    id_fields = ("DOI", "doi", "id")
    title_fields = ("title",)
    url_fields = ("URL", "url", "DOI", "doi")
    snippet_fields = ("abstract",)
    authors_fields = ("author", "authors")
    year_fields = ("published", "created", "year")
    venue_fields = ("container-title", "publisher", "journal")
    content_format = ContentFormat.CROSSREF

    def fetch_content_format(self, media_type: str | None) -> str:
        """A JSON body from Crossref is a ``message`` record or an items list."""
        if media_kind(media_type) == "json":
            return ContentFormat.CROSSREF
        return super().fetch_content_format(media_type)
