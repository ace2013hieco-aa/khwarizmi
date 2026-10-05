"""bioRxiv adapter (CHG-2 step 5) — interval listing API (JSON).

The bioRxiv API offers date-interval listing
(``/details/biorxiv/{from}/{to}/{cursor}``), NOT keyword search:
topic/identifier queries are refused before any I/O (fail-closed —
discovery belongs on a search-capable provider such as europepmc).
Records live under ``collection``. No credentials (auth ``none``).
"""
from __future__ import annotations

from hermes.tools.providers.adapters.base_adapter import (
    JsonSearchAdapter,
    make_contract,
)
from hermes.tools.providers.base import PageState, RequestSpec
from hermes.tools.providers.normalize import RetrievalHints
from hermes.tools.research_sources import ProviderValidationError

__all__ = ["BiorxivAdapter"]


class BiorxivAdapter(JsonSearchAdapter):
    provider_id = "biorxiv"
    base_url = "https://api.biorxiv.org/"
    contract = make_contract(
        "biorxiv", base_url,
        hint_routes={},
        pagination={"kind": "cursor", "start_param": "cursor",
                    "page_size_cap": 100, "max_pages": 50,
                    "loop_guard": 200},
        hazard_spec_version="unshipped",
        retry_class_map={"THROTTLED": "transient", "TIMEOUT": "transient",
                         "MALFORMED_200": "permanent"})
    search_path = "details/biorxiv/1970-01-01/2100-01-01/0"
    query_param = "q"
    items_paths = ("collection", "items", "results")
    id_fields = ("doi", "biorxiv_doi", "id")
    title_fields = ("title",)
    url_fields = ("biorxiv_url", "url", "doi")
    snippet_fields = ("abstract",)
    authors_fields = ("authors",)
    year_fields = ("date", "year")
    venue_fields = ("server", "journal")

    def build_request(self, hints: RetrievalHints, state: PageState,
                      page_size: int) -> RequestSpec:
        if hints.topic or hints.identifiers:
            raise ProviderValidationError(
                "biorxiv offers interval listing only — topic/identifier "
                "queries are refused before I/O (use a search-capable "
                "provider for discovery)")
        path = self.search_path
        if state.cursor is not None:
            path = f"details/biorxiv/1970-01-01/2100-01-01/{state.cursor}"
        return RequestSpec(url=self.base_url + path, params={}, headers_meta={})
