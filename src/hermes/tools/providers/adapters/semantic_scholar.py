"""Semantic Scholar adapter (CHG-2 step 5) — paper search (JSON).

Search: ``GET graph/v1/paper/search`` with ``query`` (+ ``limit``).
Records live under ``data``. Auth policy ``query`` (API key travels as
a deployment-configured query/header credential — injected at request
construction, never logged; see ``RequestSpec.headers_meta``).
"""
from __future__ import annotations

from hermes.tools.providers.adapters.base_adapter import (
    JsonSearchAdapter,
    make_contract,
)

__all__ = ["SemanticScholarAdapter"]


class SemanticScholarAdapter(JsonSearchAdapter):
    provider_id = "semantic-scholar"
    base_url = "https://api.semanticscholar.org/"
    contract = make_contract(
        "semantic-scholar", base_url,
        auth_policy="query",
        hint_routes={"doi": "graph/v1/paper/search", "arxiv": "",
                     "topic": "graph/v1/paper/search"},
        pagination={"kind": "offset", "start_param": "offset",
                    "page_size_cap": 100, "max_pages": 50,
                    "loop_guard": 200},
        hazard_spec_version="unshipped",
        retry_class_map={"THROTTLED": "transient", "TIMEOUT": "transient",
                         "MALFORMED_200": "permanent",
                         "HTTP_429": "transient"})
    search_path = "graph/v1/paper/search"
    query_param = "query"
    page_size_param = "limit"
    extra_params = {"fields": "title,abstract,authors,year,venue,url,"
                              "externalIds"}
    items_paths = ("data", "items", "results")
    id_fields = ("paperId", "doi", "arxivId", "id")
    title_fields = ("title",)
    url_fields = ("url", "openAccessPdf", "doi")
    snippet_fields = ("abstract", "tldr")
    authors_fields = ("authors",)
    year_fields = ("year",)
    venue_fields = ("venue", "journal")
