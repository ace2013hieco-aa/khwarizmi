"""OpenAlex adapter (CHG-2 step 5) — works search (JSON).

Search: ``GET works`` with ``search`` (+ ``per-page``). Records live
under ``data``. No credentials (auth ``none``; polite pool via
mailto belongs to deployment config, never to the adapter).
"""
from __future__ import annotations

from hermes.tools.providers.adapters.base_adapter import (
    JsonSearchAdapter,
    make_contract,
)
from hermes.tools.providers.base import RequestSpec

__all__ = ["OpenalexAdapter"]


class OpenalexAdapter(JsonSearchAdapter):
    provider_id = "openalex"
    base_url = "https://api.openalex.org/"
    contract = make_contract(
        "openalex", base_url,
        hint_routes={"doi": "works", "openalex_id": "works",
                     "topic": "works"},
        pagination={"kind": "cursor", "start_param": "cursor",
                    "page_size_cap": 100, "max_pages": 50,
                    "loop_guard": 200},
        hazard_spec_version="shipped",
        retry_class_map={"THROTTLED": "transient", "TIMEOUT": "transient",
                         "MALFORMED_200": "permanent"})
    search_path = "works"
    query_param = "search"
    page_size_param = "per-page"
    items_paths = ("data", "items", "results")
    id_fields = ("id", "doi", "openalex_id")
    title_fields = ("title", "display_name")
    url_fields = ("id", "doi", "primary_location")
    snippet_fields = ("abstract", "abstract_inverted_index")
    authors_fields = ("authorships", "authors")
    year_fields = ("publication_year", "year")
    venue_fields = ("primary_location", "venue", "journal")

    def build_fetch_request(self, source) -> RequestSpec:
        """Fetch through the API host: a canonical ``openalex.org/W…`` URL
        is rewritten to ``api.openalex.org/works/W…`` (the record page
        blocks plain GETs; the works endpoint is the provider's own
        content surface). Any other URL passes through unchanged."""
        from urllib.parse import urlsplit, urlunsplit

        from hermes.tools.research_sources import ProviderValidationError

        url = source.source_url
        if not isinstance(url, str) or not url:
            raise ProviderValidationError(
                "cannot fetch source without a URL (provider 'openalex')")
        parts = urlsplit(url)
        if parts.netloc.lower() in ("openalex.org", "www.openalex.org"):
            parts = parts._replace(netloc="api.openalex.org")
            url = urlunsplit(parts)
        return RequestSpec(url=url, params={}, headers_meta={})
