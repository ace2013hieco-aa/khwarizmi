"""Unpaywall adapter (CHG-2 step 5) — DOI lookup (JSON, id-based only).

The Unpaywall API offers DOI lookup (``/v2/{doi}?email=``), NOT keyword
search: topic-only queries are refused before any I/O (fail-closed).
The contact email is deployment configuration — this adapter never
carries one; callers supply it per deployment wiring (never logged).
"""
from __future__ import annotations

from hermes.tools.providers.adapters.base_adapter import (
    JsonSearchAdapter,
    make_contract,
)
from hermes.tools.providers.base import Page, PageState, RequestSpec
from hermes.tools.providers.normalize import RetrievalHints
from hermes.tools.research_sources import ProviderValidationError

__all__ = ["UnpaywallAdapter"]


class UnpaywallAdapter(JsonSearchAdapter):
    provider_id = "unpaywall"
    base_url = "https://api.unpaywall.org/"
    contract = make_contract(
        "unpaywall", base_url,
        auth_policy="query",
        hint_routes={"doi": "v2/{doi}"},
        pagination={"kind": "none", "page_size_cap": 1, "max_pages": 1,
                    "loop_guard": 2},
        hazard_spec_version="unshipped",
        retry_class_map={"THROTTLED": "transient", "TIMEOUT": "transient",
                         "MALFORMED_200": "permanent"})
    search_path = "v2/"
    query_param = "q"
    items_paths = ("items", "results")
    id_fields = ("doi", "id")
    title_fields = ("title",)
    url_fields = ("best_oa_location", "url", "doi")
    snippet_fields = ("abstract",)
    authors_fields = ("z_authors", "authors")
    year_fields = ("year", "published_date")
    venue_fields = ("journal_name", "publisher")

    def build_request(self, hints: RetrievalHints, state: PageState,
                      page_size: int) -> RequestSpec:
        doi = hints.identifiers.get("doi")
        if not doi:
            raise ProviderValidationError(
                "unpaywall offers DOI lookup only — topic queries are "
                "refused before I/O (a contact email is deployment "
                "configuration, never carried here)")
        return RequestSpec(url=f"{self.base_url}v2/{doi}", params={},
                           headers_meta={})

    def parse_page(self, payload: object, state: PageState) -> Page:
        if isinstance(payload, dict) and payload.get("doi"):
            return Page(records=(self._row_to_record(payload),),
                        total=1, next_state=None, notes=())
        return super().parse_page(payload, state)
