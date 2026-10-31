"""Semantic Scholar adapter (CHG-2 step 5) — paper search (JSON).

Search: ``GET graph/v1/paper/search`` with ``query`` (+ ``limit``).
Records live under ``data``. Auth policy ``query`` (API key travels as
a deployment-configured query/header credential — injected at request
construction, never logged; see ``RequestSpec.headers_meta``).
"""
from __future__ import annotations

from hermes.tools.capabilities.content import ContentFormat
from hermes.tools.providers.adapters.base_adapter import (
    JsonSearchAdapter,
    make_contract,
)
from hermes.tools.providers.base import media_kind

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
    content_format = ContentFormat.SEMANTIC_SCHOLAR

    def fetch_content_format(self, media_type: str | None) -> str:
        """A paper record from the graph API is JSON; its search wrapper is not.

        The captured response is ``application/json`` for
        ``graph/v1/paper/DOI:…``. The declaration is made here so the artifact
        carries the shape; the reader still refuses a body that has no
        ``title``/``abstract`` (a search wrapper or an unknown shape) instead
        of mining its ``citationCount`` and ``externalIds``.
        """
        if media_kind(media_type) == "json":
            return ContentFormat.SEMANTIC_SCHOLAR
        return super().fetch_content_format(media_type)
