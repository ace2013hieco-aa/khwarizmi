"""Deterministic retrieval hints, identifier normalization, and dedup keys.

Step 1 of the Part 3 implementation (IDR-030). Pure, stdlib-only, zero I/O —
the contract §2.1/§3.1 normalization table as code:

- `parse_query_hints` splits the free-form query into canonical identifiers + topic
  and records *unrecognized* hint prefixes so the routing layer can raise
  `ProviderValidationError` before any I/O (PS3-06 — an unknown hint prefix is
  validation, never a search that "could not run").
- `normalize_identifier` applies the contract §3.1 rules: DOI lowercase + trailing-
  dot strip + resolver-URL strip; PMID digits-only; PMCID `PMC`+digits with the
  bare-number ambiguity resolved as None (the adapter resolves via the provider,
  never by guessing); arXiv new/old scheme with version suffix stripped for
  identity; URL → DOI/arXiv extraction on known resolver hosts.
- `dedup_key` is the cross-provider key: doi → pmid → pmcid → arxiv, first-seen
  wins (contract §3.1). Namespaced (`"doi:…"`) so no two kinds can collide.

All functions are deterministic and unit-tested in `tests/test_research_sources.py`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import unquote, urlsplit

__all__ = [
    "IDENTIFIER_KINDS",
    "RetrievalHints",
    "canonicalize_identifiers",
    "dedup_key",
    "normalize_identifier",
    "parse_query_hints",
]

IDENTIFIER_KINDS: tuple[str, ...] = ("doi", "pmid", "pmcid", "arxiv", "url")

# hint prefixes, case-insensitive: doi: / pmid: / pmcid: / arxiv: / url:
_HINT_PREFIX_RE = re.compile(r"^(doi|pmid|pmcid|arxiv|url):", re.IGNORECASE)

# arXiv schemes: new YYMM.NNNNN(vN)? ; old category/YYMMNNN(vN)? (contract §3.1)
_ARXIV_NEW_RE = re.compile(r"^(\d{4}\.\d{4,5})(?:v\d+)?$")
_ARXIV_OLD_RE = re.compile(r"^([a-z-]+(?:\.[a-z-]+)*/\d{7})(?:v\d+)?$")
_ARXIV_RESOLVER_RE = re.compile(
    r"^/?(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?$|"
    r"^/(?:abs|pdf)/([a-z-]+(?:\.[a-z-]+)*/\d{7})(?:v\d+)?(?:\.pdf)?$"
)
_DOI_PREFIX_RE = re.compile(r"^10\.\d{4,9}/")
_DOI_RESOLVER_HOSTS = frozenset({"doi.org", "dx.doi.org"})
_ARXIV_RESOLVER_HOSTS = frozenset({"arxiv.org"})

# Resolver prefixes stripped before normalization (contract §3.1).
_DOI_URL_PREFIXES = ("https://doi.org/", "http://doi.org/",
                     "https://dx.doi.org/", "http://dx.doi.org/")


@dataclass(frozen=True)
class RetrievalHints:
    """The deterministic hint parse (contract §2.1). `mode` is derived: an
    identifier-only query is IDENTIFIER, topic-only is TOPIC, both is MIXED."""

    identifiers: dict[str, str]  # kind -> canonical value (normalized)
    topic: str  # the free-text remainder (whitespace-joined)
    mode: Literal["IDENTIFIER", "TOPIC", "MIXED"]
    unrecognized_hints: tuple[str, ...] = ()  # e.g. "xyz:123" — the router raises
    #   ProviderValidationError on these BEFORE any I/O (PS3-06)


def _normalize_pmid(raw: str) -> str | None:
    digits = re.sub(r"[^0-9]", "", raw)
    return digits or None


def _normalize_pmcid(raw: str) -> str | None:
    value = raw.strip().upper()
    if value.startswith("PMC"):
        body = value[3:]
        if body.isdigit() and body:
            return "PMC" + body
        return None
    # Bare numeric-only form is ambiguous (PMC-vs-PubMed id) — the adapter resolves
    # via the provider, never by guessing (contract §3.1).
    return None


def _normalize_doi(raw: str) -> str | None:
    value = raw.strip().lower()
    for prefix in _DOI_URL_PREFIXES:
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    if value.startswith("doi:"):
        value = value[4:]
    value = value.rstrip(".")
    if not value.startswith("10."):
        return None
    # A real DOI has a registry prefix ("10.<reg>/<suffix>"). A bare "10." is invalid.
    if not _DOI_PREFIX_RE.match(value):
        return None
    return value


def _normalize_arxiv(raw: str) -> str | None:
    value = raw.strip()
    if value.startswith("arxiv:"):
        value = value[5:]
    # resolver URL forms (arxiv.org/abs/…, arxiv.org/pdf/…)
    if "arxiv.org" in value:
        path = urlsplit(value).path
        match = _ARXIV_RESOLVER_RE.match(path)
        if not match:
            return None
        return (match.group(1) or match.group(2))
    match = _ARXIV_NEW_RE.match(value)
    if match:
        return match.group(1)
    match = _ARXIV_OLD_RE.match(value)
    if match:
        return match.group(1)
    return None


def _normalize_url(raw: str) -> str | None:
    """Extract a DOI/arXiv id from a known resolver host (contract §3.1);
    otherwise None — the `url:` stays a fetch hint, not an identifier."""
    value = raw.strip()
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.netloc in _DOI_RESOLVER_HOSTS:
        return _normalize_doi(unquote(parts.path).lstrip("/"))
    if parts.netloc in _ARXIV_RESOLVER_HOSTS:
        return _normalize_arxiv(value)
    return None


def normalize_identifier(kind: str, raw: str) -> str | None:
    """Canonical form per contract §3.1; None when the raw value is not a valid
    instance of `kind` (the caller decides how to handle an invalid identifier —
    the walk raises `ProviderValidationError` for a bad identifier before I/O)."""
    if raw is None:
        return None
    kind_l = kind.lower()
    if kind_l == "doi":
        return _normalize_doi(raw)
    if kind_l == "pmid":
        return _normalize_pmid(raw)
    if kind_l == "pmcid":
        return _normalize_pmcid(raw)
    if kind_l == "arxiv":
        return _normalize_arxiv(raw)
    if kind_l == "url":
        return _normalize_url(raw)
    return None


def parse_query_hints(query: str) -> RetrievalHints:
    """Split the free-form query into canonical identifiers + topic (contract §2.1).

    Rules:
    - A token with a recognized prefix (`doi:`/`pmid:`/`pmcid:`/`arxiv:`/`url:`,
      case-insensitive) is parsed as a hint and its value normalized; a value that
      fails normalization is dropped from `identifiers` (the router validates).
    - A bare `https?://` URL token is treated as a `url:` hint.
    - A token with an UNRECOGNIZED `word:` prefix is captured in
      `unrecognized_hints` — the routing layer raises `ProviderValidationError`
      (PS3-06), never a silent "no route".
    - Everything else is topic text, whitespace-joined.
    """
    identifiers: dict[str, str] = {}
    unrecognized: list[str] = []
    topic_parts: list[str] = []
    for token in query.split():
        if not token:
            continue
        stripped = token.rstrip(".,;")
        if not stripped:
            continue
        prefix_match = _HINT_PREFIX_RE.match(stripped)
        if prefix_match:
            kind = prefix_match.group(1).lower()
            value = stripped[prefix_match.end():]
            if kind == "url":
                normalized = normalize_identifier("url", value)
                if normalized is not None and "doi" not in identifiers:
                    identifiers["doi"] = normalized  # a resolver URL IS a DOI id
                elif normalized is None and value:
                    unrecognized.append(stripped)
                continue
            normalized = normalize_identifier(kind, value)
            if normalized is not None:
                identifiers[kind] = normalized
            # an invalid value for a recognized prefix is dropped (router validates)
            continue
        # bare URL token → url: hint
        if stripped.lower().startswith(("http://", "https://")):
            normalized = normalize_identifier("url", stripped)
            if normalized is not None and "doi" not in identifiers:
                identifiers["doi"] = normalized
            elif normalized is None:
                unrecognized.append(stripped)
            continue
        # unrecognized word: prefix → validation surface (PS3-06)
        if re.match(r"^[A-Za-z][A-Za-z0-9_-]*:", stripped):
            unrecognized.append(stripped)
            continue
        topic_parts.append(stripped)

    has_id = bool(identifiers)
    has_topic = bool(topic_parts)
    if has_id and has_topic:
        mode: Literal["IDENTIFIER", "TOPIC", "MIXED"] = "MIXED"
    elif has_id:
        mode = "IDENTIFIER"
    else:
        mode = "TOPIC"
    return RetrievalHints(
        identifiers=identifiers,
        topic=" ".join(topic_parts),
        mode=mode,
        unrecognized_hints=tuple(unrecognized),
    )


def dedup_key(identifiers: dict[str, str]) -> str | None:
    """The cross-provider dedup key (contract §3.1): doi → pmid → pmcid → arxiv,
    first-seen wins. Namespaced so kinds can never collide; None when empty."""
    for kind in ("doi", "pmid", "pmcid", "arxiv"):
        value = identifiers.get(kind)
        if value:
            return f"{kind}:{value}"
    return None


# The four scholarly identifier kinds that carry a §3.1 normalization rule AND
# participate in the cross-provider dedup key. `url` is deliberately NOT here:
# it is a fetch hint (a non-resolver URL is a legitimate value that
# `_normalize_url` would drop), and provider-native kinds (openalex_id,
# core_id, …) are preserved verbatim — never forced through a universal parser.
_CANONICAL_SCHOLARLY_KINDS = ("doi", "pmid", "pmcid", "arxiv")


def canonicalize_identifiers(identifiers: dict[str, str]) -> dict[str, str]:
    """One deterministic canonicalization pass over a raw ``kind → value`` map
    (HR-04 — the single identity/normalization path of the source-admission
    contract §5).

    The walk's ``adapter.extract_ids(record)`` output and any hand-built
    ``spec.hints.identifiers`` are RAW provider strings; without this pass a
    non-canonical value (``10.1038/NATURE12373``, ``2103.15348v2``) would be
    persisted as a *competing identity* for the same scholarly work. This
    function is the choke point that prevents that:

    - A known scholarly kind (doi/pmid/pmcid/arxiv, matched case-insensitively)
      is re-keyed to its lowercase canonical form and its value normalized via
      ``normalize_identifier`` (contract §3.1). A value that fails
      normalization is DROPPED — it is not a valid instance of that kind, and
      storing it would forge a garbage identity (the same drop semantics
      ``parse_query_hints`` applies to an invalid hint value). Dropping is
      deterministic; if every identifier is dropped the walk's existing
      ``if not ids: MALFORMED_ROW`` path handles the record.
    - ``url`` and every provider-native kind (openalex_id, core_id, …) are
      preserved VERBATIM (key and value) — they are not in the §3.1 table and
      must not be mistaken for, or coerced into, a universal identity.

    The function is idempotent: canonicalizing an already-canonical map returns
    an equal map, so normalizing both the query-hint path (already canonical)
    and the record-extraction path is safe and converges on one identity.
    """
    out: dict[str, str] = {}
    for kind, value in identifiers.items():
        kind_l = kind.lower()
        if kind_l in _CANONICAL_SCHOLARLY_KINDS:
            normalized = normalize_identifier(kind_l, value)
            if normalized is not None:
                out[kind_l] = normalized
            # an invalid instance of a known kind is dropped, never stored
        else:
            out[kind] = value
    return out
