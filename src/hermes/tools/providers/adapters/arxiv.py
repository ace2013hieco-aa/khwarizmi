"""arXiv adapter (CHG-2 step 5) — Atom API (XML).

Search: ``GET {base_url}`` with ``search_query``/``start``/``max_results``.
Records are Atom ``entry`` elements. No credentials (auth ``none``).
"""
from __future__ import annotations

from hermes.tools.capabilities.content import ContentFormat
from hermes.tools.providers.adapters.base_adapter import (
    JsonSearchAdapter,
    make_contract,
)
from hermes.tools.providers.base import PageState, RequestSpec
from hermes.tools.providers.normalize import RetrievalHints

__all__ = ["ArxivAdapter"]


class ArxivAdapter(JsonSearchAdapter):
    provider_id = "arxiv"
    base_url = "http://export.arxiv.org/api/query"
    contract = make_contract(
        "arxiv", base_url,
        hint_routes={"arxiv": "", "doi": "", "topic": ""},
        pagination={"kind": "offset", "start_param": "start",
                    "page_size_cap": 100, "max_pages": 50,
                    "loop_guard": 200},
        hazard_spec_version="shipped",
        retry_class_map={"THROTTLED": "transient", "TIMEOUT": "transient",
                         "MALFORMED_200": "permanent"})
    search_path = ""
    query_param = "search_query"
    page_size_param = "max_results"
    id_fields = ("id", "arxiv")
    title_fields = ("title",)
    url_fields = ("id", "link")
    snippet_fields = ("summary",)
    authors_fields = ("author",)
    year_fields = ("published",)
    venue_fields = ()
    xml_item_tags = ("entry",)
    xml_field_tags = {
        "id": ("id",),
        "title": ("title",),
        "summary": ("summary",),
        "author": ("author", "name"),
        "published": ("published",),
        "link": ("link",),
    }
    content_format = ContentFormat.ARXIV

    def fetch_content_format(self, media_type: str | None) -> str:
        """An Atom feed is an arXiv record; a web page is still a page.

        The captured response is ``application/atom+xml; charset=utf-8``. Only
        that concrete type is declared ``arxiv`` — a generic ``application/xml``
        body has not been captured from this host and is not guessed at.
        """
        kind = (media_type or "").split(";", 1)[0].strip().lower()
        if kind == "application/atom+xml":
            return ContentFormat.ARXIV
        return super().fetch_content_format(media_type)

    def build_request(self, hints: RetrievalHints, state: PageState,
                      page_size: int) -> RequestSpec:
        params = {self.query_param: self._query_text(hints),
                  self.page_size_param: str(page_size),
                  "start": str(state.offset or 0)}
        params.update(self.extra_params)
        return RequestSpec(url=self.base_url + self.search_path,
                           params=params, headers_meta={})
