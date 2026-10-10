"""SearXNG adapter (IDR-046) — web search (JSON, GET).

Search: ``GET {base_url}search`` with ``q`` (+ ``format=json`` /
``pageno``). Records live under ``results``. Auth policy ``none`` —
instance auth, when used, is deployment configuration (a header, never
a param).

**Self-hosted open-source instance** — the operator runs it; there is
no vendor and no vendor ToS. The `base_url` default below is the
conventional local default; the deployment owns the real base URL
(lowest egress of the four legs — the operator's own infrastructure).
"""
from __future__ import annotations

from hermes.tools.providers.adapters.base_adapter import (
    JsonSearchAdapter,
    make_contract,
)

__all__ = ["SearxngAdapter"]


class SearxngAdapter(JsonSearchAdapter):
    provider_id = "searxng"
    # Deployment-owned default (conventional local SearXNG port) — the
    # operator configures the real instance base URL.
    base_url = "http://localhost:8888/"
    contract = make_contract(
        "searxng", base_url,
        auth_policy="none",
        hint_routes={"topic": "search"},
        pagination={"kind": "offset", "start_param": "pageno",
                    "page_size_cap": 20, "max_pages": 50,
                    "loop_guard": 200},
        hazard_spec_version="shipped",
        retry_class_map={"THROTTLED": "transient", "TIMEOUT": "transient",
                         "MALFORMED_200": "permanent"})
    search_path = "search"
    query_param = "q"
    page_param = "pageno"
    extra_params = {"format": "json"}
    items_paths = ("results", "items")
    id_fields = ("url", "id")
    title_fields = ("title",)
    url_fields = ("url",)
    snippet_fields = ("content", "snippet")
    authors_fields = ()
    year_fields = ("publishedDate",)
    venue_fields = ("engine",)
