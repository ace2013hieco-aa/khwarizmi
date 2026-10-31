"""Fetched-content validation — a 2xx is not automatically the source.

The fetch driver treats any 2xx as status-eligible (``hazards.py``), which is
correct for HTTP but not for evidence: a provider can answer 200/203 with a
consent interstitial, a challenge page or an error document. The fetched bytes
are what a citation ultimately rests on, so recording such a body as a
``source_payload`` would make an error page citable.

This module is the deterministic, network-free check the driver runs after the
hazard verdict and before an artifact can be constructed. It reads only a
bounded prefix, never parses the document, and returns data — the caller maps
the refusal onto its own failure shape.

Two independent signals, because either alone is insufficient:

* **HTTP 203** — a non-authoritative response is a transformed representation,
  never the origin's resource. The PubMed cookie wall arrived this way.
* **An interstitial body** — a 200 can still be a cookie wall or a challenge
  page. The marker set is deliberately narrow and matched only against
  HTML/XHTML prefixes, so a real article that merely contains the words later
  in its body is not refused.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "CONTENT_REFUSAL_CODES",
    "INTERSTITIAL_MARKERS",
    "NON_AUTHORITATIVE_STATUSES",
    "NON_CONTENT_MEDIA_TYPES",
    "ContentRefusal",
    "fetch_content_refusal",
]

#: A 203 is ``Non-Authoritative Information``: the payload came from a
#: transforming proxy, not from the resource's origin.
NON_AUTHORITATIVE_STATUSES: frozenset[int] = frozenset({203})

#: The media types whose bodies can carry an interstitial. JSON/plain-text
#: responses are not scanned: their content is the record, and a literal
#: marker in a JSON field is not a consent page.
_SCRIPT_STYLE = re.compile(r"(?is)<(script|style)\b.*?</\1>")
_TAG = re.compile(r"(?s)<[^>]+>")

NON_CONTENT_MEDIA_TYPES: frozenset[str] = frozenset({
    "text/html",
    "application/xhtml+xml",
})

#: Narrow, ordered markers. Each is a phrase an error/consent/challenge page
#: carries and a real article does not carry in its first 4 KiB. The exact
#: PubMed wall says "Cookies must be enabled" and carries a
#: ``cookie-required`` element; the Cloudflare family is named too.
#: ``(marker, label, needs_sparse_page)``. The last flag separates phrases only
#: an interstitial says from ones ordinary English also says.
#:
#: "captcha", "access denied", "request blocked" and "attention required" appear
#: in security writing and documentation — an article titled "How CAPTCHA
#: systems work" is not a challenge page, and refusing it costs the run its
#: source. A real interstitial is *mostly markup*: almost no readable text. So
#: those markers count only on a sparse page; the phrases no legitimate article
#: opens with apply regardless.
INTERSTITIAL_MARKERS: tuple[tuple[str, str, bool], ...] = (
    ("cookies must be enabled", "cookie interstitial", False),
    ("cookie-required", "cookie interstitial", False),
    ("enable cookies", "cookie interstitial", False),
    ("just a moment", "challenge page", False),
    ("checking your browser", "challenge page", False),
    ("verify you are human", "challenge page", False),
    ("cf-challenge", "challenge page", False),
    ("attention required", "error document", True),
    ("access denied", "error document", True),
    ("request blocked", "error document", True),
    ("captcha", "challenge page", True),
)

#: Readable characters below which a page is "sparse": a challenge page is a few
#: hundred characters of apology inside kilobytes of script and styling.
SPARSE_PROSE_CHARS = 1200

#: The named codes this module emits. Consumers use the set to recognize a
#: refusal that is data (the run continues) rather than a fatal fetch failure.
CONTENT_REFUSAL_CODES: frozenset[str] = frozenset({
    "NON_AUTHORITATIVE_RESPONSE",
    "NON_CONTENT_PAYLOAD",
})

_PREFIX_BYTES = 4096


@dataclass(frozen=True, slots=True)
class ContentRefusal:
    """A fetched body that is not a representation of the source."""

    code: str
    detail: str


def fetch_content_refusal(
    *,
    status: int,
    media_type: str | None,
    body: bytes,
) -> ContentRefusal | None:
    """Why these fetched bytes must not become a source artifact, or None.

    Pure and deterministic: no clock, no network, no model. ``status`` is the
    response status the hazard evaluator already saw; ``media_type`` is the
    transport's normalized content type; ``body`` is the raw payload.
    """
    if status in NON_AUTHORITATIVE_STATUSES:
        return ContentRefusal(
            "NON_AUTHORITATIVE_RESPONSE",
            f"HTTP {status} is a non-authoritative response — a transformed "
            "representation, not the source's origin record")
    normalized = (media_type or "").split(";", 1)[0].strip().lower()
    if normalized not in NON_CONTENT_MEDIA_TYPES:
        return None
    head = body[:_PREFIX_BYTES].decode("utf-8", errors="replace").lower()
    prose = _visible_characters(body)
    for marker, label, needs_sparse in INTERSTITIAL_MARKERS:
        if needs_sparse and prose >= SPARSE_PROSE_CHARS:
            # Enough readable text to be a document rather than a wall.
            continue
        if marker in head:
            return ContentRefusal(
                "NON_CONTENT_PAYLOAD",
                f"the body is a {label} (matched {marker!r}), not a "
                "representation of the source")
    return None


def _visible_characters(body: bytes) -> int:
    """Readable characters once tags, scripts and styling are removed.

    Cheap and deterministic — a regex, not a parser. It only has to separate "a
    few hundred characters of apology" from "an article".
    """
    text = body.decode("utf-8", errors="replace")
    text = _SCRIPT_STYLE.sub(" ", text)
    text = _TAG.sub(" ", text)
    return sum(1 for character in text if not character.isspace())
