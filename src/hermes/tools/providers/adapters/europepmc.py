"""Europe PMC adapter (CHG-2 step 5) — REST search (JSON).

Search: ``GET search`` with ``query`` + ``format=json``. Records live
under ``resultList.result``. No credentials (auth ``none``).
"""
from __future__ import annotations

from hermes.tools.capabilities.content import ContentFormat
from hermes.tools.providers.adapters.base_adapter import (
    JsonSearchAdapter,
    make_contract,
)
from hermes.tools.providers.base import media_kind

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
    content_format = ContentFormat.EUROPEPMC

    def fetch_content_format(self, media_type: str | None) -> str:
        """Europe PMC's record body is JSON (a ``resultList.result`` record).

        The captured response is ``application/json;charset=UTF-8``. The
        content-bearing search shape needs ``resultType=core`` in the request;
        a ``lite`` result carries no ``abstractText`` and reads ``unreadable``
        rather than being mined for its metadata.
        """
        if media_kind(media_type) == "json":
            return ContentFormat.EUROPEPMC
        return super().fetch_content_format(media_type)
