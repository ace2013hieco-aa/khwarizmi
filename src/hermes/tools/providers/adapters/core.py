"""CORE adapter (CHG-2 step 5) — works search (JSON).

Search: ``GET v3/search/works`` with ``q``. Records live under
``results``. Auth policy ``header`` (API key travels as a
deployment-configured header credential — injected at request
construction, never logged; see ``RequestSpec.headers_meta``).
"""
from __future__ import annotations

from hermes.tools.providers.adapters.base_adapter import (
    JsonSearchAdapter,
    make_contract,
)

__all__ = ["CoreAdapter"]


class CoreAdapter(JsonSearchAdapter):
    provider_id = "core"
    base_url = "https://api.core.ac.uk/"
    contract = make_contract(
        "core", base_url,
        auth_policy="header",
        hint_routes={"doi": "v3/search/works", "core_id": "",
                     "topic": "v3/search/works"},
        pagination={"kind": "offset", "start_param": "offset",
                    "page_size_cap": 100, "max_pages": 50,
                    "loop_guard": 200},
        hazard_spec_version="unshipped",
        retry_class_map={"THROTTLED": "transient", "TIMEOUT": "transient",
                         "MALFORMED_200": "permanent"})
    search_path = "v3/search/works"
    query_param = "q"
    page_size_param = "limit"
    items_paths = ("results", "data", "items")
    id_fields = ("id", "doi", "core_id")
    title_fields = ("title",)
    url_fields = ("downloadUrl", "url", "doi")
    snippet_fields = ("abstract", "description")
    authors_fields = ("authors",)
    year_fields = ("yearPublished", "year")
    venue_fields = ("publisher", "journal", "venue")
