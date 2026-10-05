"""CHG-2 provider adapter registry (step 5) — code-owned allowlist map.

``PROVIDER_REGISTRY`` maps every ratified allowlist provider id to its
thin adapter class. Lookup is deterministic (exact id match — unknown
ids refuse before any I/O, preserving the IDR-030 admission refusal).
Registration authority is code review: adding a provider means a new
adapter module + hazard spec + contract tests in this package. Registry
edits never mutate existing fixtures (fixtures pin provider +
adapter + parser versions independently).
"""
from __future__ import annotations

from hermes.tools.providers.adapters.arxiv import ArxivAdapter
from hermes.tools.providers.adapters.biorxiv import BiorxivAdapter
from hermes.tools.providers.adapters.core import CoreAdapter
from hermes.tools.providers.adapters.crossref import CrossrefAdapter
from hermes.tools.providers.adapters.europepmc import EuropePmcAdapter
from hermes.tools.providers.adapters.medrxiv import MedrxivAdapter
from hermes.tools.providers.adapters.openalex import OpenalexAdapter
from hermes.tools.providers.adapters.pmc import PmcAdapter
from hermes.tools.providers.adapters.pubmed import PubmedAdapter
from hermes.tools.providers.adapters.semantic_scholar import (
    SemanticScholarAdapter,
)
from hermes.tools.providers.adapters.unpaywall import UnpaywallAdapter
from hermes.tools.providers.base import ProviderAdapter
from hermes.tools.research_sources import (
    SOURCE_PROVIDER_ALLOWLIST,
    ProviderValidationError,
)

__all__ = [
    "PROVIDER_REGISTRY",
    "resolve_adapter",
]

PROVIDER_REGISTRY: dict[str, type[ProviderAdapter]] = {
    "pubmed": PubmedAdapter,
    "pmc": PmcAdapter,
    "europepmc": EuropePmcAdapter,
    "arxiv": ArxivAdapter,
    "biorxiv": BiorxivAdapter,
    "medrxiv": MedrxivAdapter,
    "openalex": OpenalexAdapter,
    "crossref": CrossrefAdapter,
    "semantic-scholar": SemanticScholarAdapter,
    "core": CoreAdapter,
    "unpaywall": UnpaywallAdapter,
}

_MISSING = sorted(set(SOURCE_PROVIDER_ALLOWLIST) - set(PROVIDER_REGISTRY))
if _MISSING:  # pragma: no cover — registry/allowlist drift is a bug
    raise ImportError(
        f"provider registry does not cover allowlist ids {_MISSING}")


def resolve_adapter(provider_id: str) -> type[ProviderAdapter]:
    """Deterministic adapter lookup (exact id match). Unknown ids raise
    ``ProviderValidationError`` before any I/O — the IDR-030 refusal."""
    try:
        return PROVIDER_REGISTRY[provider_id]
    except KeyError:
        raise ProviderValidationError(
            f"no adapter for provider {provider_id!r} — not in the "
            f"allowlist (IDR-030); nothing was issued") from None
