"""PMC adapter (CHG-2 step 5) — NCBI PMC OA utility + E-utilities search.

Search: ``GET esearch.fcgi`` (``db=pmc``). Records are ``IdList/Id``
elements (XML) or ``esearchresult/idlist`` (JSON). Full-text links
resolve through the OA utility (``oa.fcgi?id=PMCID``) at fetch time via
``build_fetch_request`` when the source URL names it. No credentials
(auth ``none``).
"""
from __future__ import annotations

from hermes.tools.providers.adapters.base_adapter import (
    JsonSearchAdapter,
    make_contract,
)

__all__ = ["PmcAdapter"]


class PmcAdapter(JsonSearchAdapter):
    provider_id = "pmc"
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    contract = make_contract(
        "pmc", base_url,
        hint_routes={"pmcid": "esearch.fcgi?db=pmc", "doi": "",
                     "topic": "esearch.fcgi?db=pmc"},
        pagination={"kind": "offset", "start_param": "retstart",
                    "page_size_cap": 100, "max_pages": 50,
                    "loop_guard": 200},
        hazard_spec_version="shipped",
        retry_class_map={"THROTTLED": "transient", "TIMEOUT": "transient",
                         "MALFORMED_200": "permanent"})
    search_path = "esearch.fcgi"
    query_param = "term"
    page_size_param = "retmax"
    extra_params = {"db": "pmc", "retmode": "json"}
    items_paths = ("esearchresult.idlist", "items", "results")
    id_fields = ("pmcid", "id")
    title_fields = ("title",)
    url_fields = ("url", "id")
    snippet_fields = ("abstract", "snippet")
    authors_fields = ("authors",)
    year_fields = ("pubdate", "year")
    venue_fields = ("source", "journal")
    xml_item_tags = ("Id", "record")
    xml_field_tags = {
        "pmcid": ("Id", "id"),
        "title": ("ArticleTitle",),
        "abstract": ("AbstractText",),
        "author": ("Author", "LastName"),
        "pubdate": ("PubDate", "Year"),
        "source": ("Title", "Journal"),
    }
