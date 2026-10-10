"""Tavily adapter (IDR-046) — web search (JSON, POST).

Search: ``POST https://api.tavily.com/search`` with a JSON body
(``query`` + ``max_results``). Records live under ``results``. Auth
policy ``header`` (``Authorization: Bearer`` travels as a
deployment-configured header credential — injected at request
construction, never logged; see ``RequestSpec.headers_meta``). The POST
body carries no credential.

Commercial API. Code shipped here is our own; no vendor source is
copied. **ToS review REQUIRED before registration.** No live credential
is configured by this module — the leg is registered but unreachable
until an operator supplies one through the existing
deployment-credential path (same posture as the existing
credential-carriers).
"""
from __future__ import annotations

import json as _json

from hermes.tools.providers.adapters.base_adapter import (
    JsonSearchAdapter,
    make_contract,
)
from hermes.tools.providers.base import PageState, RequestSpec
from hermes.tools.providers.normalize import RetrievalHints
from hermes.tools.research_sources import ProviderValidationError

__all__ = ["TavilyAdapter"]


class TavilyAdapter(JsonSearchAdapter):
    provider_id = "tavily"
    base_url = "https://api.tavily.com/"
    contract = make_contract(
        "tavily", base_url,
        auth_policy="header",
        hint_routes={"topic": "search"},
        pagination={"kind": "none", "page_size_cap": 100, "max_pages": 50,
                    "loop_guard": 100},
        hazard_spec_version="shipped",
        retry_class_map={"THROTTLED": "transient", "TIMEOUT": "transient",
                         "MALFORMED_200": "permanent"})
    search_path = "search"
    # D4 rule 4 — the adapter-declared JSON content type (never guessed);
    # the transport sets it on the POST wire form.
    content_type = "application/json"
    body_query_field = "query"
    body_count_field = "max_results"
    items_paths = ("results", "items")
    id_fields = ("url", "id")
    title_fields = ("title",)
    url_fields = ("url",)
    snippet_fields = ("content", "snippet")
    authors_fields = ()
    year_fields = ("published_date",)
    venue_fields = ()

    def build_request(self, hints: RetrievalHints, state: PageState,
                      page_size: int) -> RequestSpec:
        if self.content_type != "application/json":
            raise ProviderValidationError(
                f"tavily declares non-JSON content type "
                f"{self.content_type!r} — refusing (POST content type "
                f"is never guessed)")
        raw = _json.dumps(
            {self.body_query_field: self._query_text(hints),
             self.body_count_field: page_size},
            sort_keys=True, separators=(",", ":"),
            ensure_ascii=False).encode("utf-8")
        if not raw:
            raise ProviderValidationError(
                "tavily POST request has an empty body — refusing (a POST "
                "with no body is never issued)")
        return RequestSpec(url=self.base_url + self.search_path,
                           params={}, headers_meta={},
                           method="POST", body=raw)
