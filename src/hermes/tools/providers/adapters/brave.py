"""Brave Search adapter (IDR-046) — web search (JSON, GET).

Search: ``GET res/v1/web/search`` with ``q`` (+ ``count``/``offset``).
Records live under ``web.results``. Auth policy ``header``
(``X-Subscription-Token`` travels as a deployment-configured header
credential — injected at request construction, never logged; see
``RequestSpec.headers_meta``).

Commercial API, subscription. Code shipped here is our own; no vendor
source is copied. **ToS review REQUIRED before registration**
(redistribution of results, rate-plan terms). No live credential is
configured by this module — the leg is registered but unreachable until
an operator supplies one through the existing deployment-credential
path (same posture as the existing credential-carriers).
"""
from __future__ import annotations

from hermes.tools.providers.adapters.base_adapter import (
    JsonSearchAdapter,
    make_contract,
)

__all__ = ["BraveAdapter"]


class BraveAdapter(JsonSearchAdapter):
    provider_id = "brave"
    base_url = "https://api.search.brave.com/"
    contract = make_contract(
        "brave", base_url,
        auth_policy="header",
        hint_routes={"topic": "res/v1/web/search"},
        pagination={"kind": "offset", "start_param": "offset",
                    "page_size_cap": 20, "max_pages": 50,
                    "loop_guard": 200},
        hazard_spec_version="shipped",
        retry_class_map={"THROTTLED": "transient", "TIMEOUT": "transient",
                         "MALFORMED_200": "permanent"})
    search_path = "res/v1/web/search"
    query_param = "q"
    page_size_param = "count"
    page_param = "offset"
    items_paths = ("web.results", "results", "items")
    id_fields = ("url", "id")
    title_fields = ("title",)
    url_fields = ("url",)
    snippet_fields = ("description", "snippet")
    authors_fields = ()
    year_fields = ("age", "page_age")
    venue_fields = ()
