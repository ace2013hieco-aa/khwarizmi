"""Europe PMC adapter (CHG-2 step 5) — REST search (JSON).

Search: ``GET search`` with ``query`` + ``format=json``. Records live
under ``resultList.result``. No credentials (auth ``none``).
"""
from __future__ import annotations

from hermes.tools.providers.adapters.base_adapter import (
    JsonSearchAdapter,
    make_contract,
)

__all__ = ["EuropePmcAdapter"]


class EuropePmcAdapter(JsonSearchAdapter):
    provider_id = "europepmc"
    base_url = "https://www.ebi.ac.uk/europepmc/webservices/rest/"
    contract = make_contract(
        "europepmc", base_url,
        hint_routes={"pmid": "search", "pmcid": "search", "doi": "search",
                     "topic": "search"},
        pagination={"kind": "offset", "start_param": "cursorMark",
                    "page_size_cap": 100, "max_pages": 50,
                    "loop_guard": 200},
        hazard_spec_version="shipped",
        retry_class_map={"THROTTLED": "transient", "TIMEOUT": "transient",
                         "MALFORMED_200": "permanent"})
    search_path = "search"
    query_param = "query"
    page_size_param = "pageSize"
    extra_params = {"format": "json"}
    items_paths = ("resultList.result", "items", "results")
    id_fields = ("id", "pmid", "pmcid", "doi")
    title_fields = ("title",)
    url_fields = ("fullTextUrlList", "id", "doi")
    snippet_fields = ("abstractText", "abstract")
    authors_fields = ("authorString", "authors")
    year_fields = ("pubYear", "firstPublicationDate", "year")
    venue_fields = ("journalInfo", "journalTitle", "journal")
