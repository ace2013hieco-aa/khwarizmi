"""crawl4ai markdown provider (S2 spike) — the ONLY importer of crawl4ai.

Adoption §4 rule 1: the third-party library lives in its own provider module,
imported nowhere else. This is that boundary for ``crawl4ai 0.9.4`` (the
S4-audited version; commit e5d2e78…). It is **not** in ``PROVIDER_REGISTRY``
and no other ``src/`` module imports it.

Why crawl4ai does not fetch here
--------------------------------
Adoption S2 requires a Khwarizmi-owned resolve-and-pin egress guard in front of
crawl4ai. crawl4ai's own ``egress_policy.py`` states the library "deliberately
has no egress policy of its own" and that a *validator* hook is insufficient
because "the client re-resolves when it dials, which is the DNS-rebinding
window" — the library's Docker server therefore uses a pinning forward proxy.
Passing a URL to crawl4ai for fetching would recreate exactly that window: the
guard's resolution would not be the connection. This provider therefore puts
the guard on the network leg (:class:`hermes.security.egress.GuardedFetcher`
owns the socket, pins the address, re-vets every hop) and confines crawl4ai to
the pure HTML → markdown transform, where it performs no I/O. Browser
rendering behind the guard remains a wiring-gate decision (S2 record §5).

Contract
--------
- **Exact pin.** ``CRAWL4AI_PIN`` is checked at import time of the pinned
  module via ``importlib.metadata``; absent or different version →
  ``Crawl4aiUnavailableError``. No static ``import crawl4ai`` anywhere.
- **All output is ``UntrustedContent``.** Even the intermediate raw/cited/
  references strings are wrapped; the provider returns a ``Crawl4aiPage``
  whose payload is reachable only through the envelope's explicit ``.text``.
- **Refusal-as-data.** Non-2xx fetches and non-HTML content types are refused
  with codes (``Crawl4aiProviderError``) before any markdown is produced.
- **Provenance.** Library name + exact version + config fingerprint, the guard
  policy fingerprint, every dialed hop with its pinned address, source and
  markdown hashes, encoding, content type. Bounded by
  ``MAX_PROVENANCE_BYTES`` (4 KiB discipline) — the markdown payload itself is
  artifact-store material, never an event payload.

S2 status: spike wiring only — no EXTRACT/controller integration, no
persistence, no event payloads, no ``ProviderHTTPTransport`` change (PS-03
reconciliation is a design-gate decision).
"""
from __future__ import annotations

import codecs
import hashlib
import importlib
import importlib.metadata
import json
from dataclasses import dataclass
from typing import Any, Mapping, Tuple

from hermes.security.boundaries import UntrustedContent
from hermes.security.egress import FetchedPage, GuardedFetcher

__all__ = [
    "CRAWL4AI_PIN",
    "MAX_PROVENANCE_BYTES",
    "RECORD_VERSION",
    "Crawl4aiConfig",
    "Crawl4aiPage",
    "Crawl4aiProvenance",
    "Crawl4aiProviderError",
    "Crawl4aiUnavailableError",
    "MarkdownRender",
    "canonical_json",
    "render_markdown",
    "render_page",
]

CRAWL4AI_PIN = "0.9.4"
"""The exact crawl4ai version audited by S4 (commit e5d2e78…, 2026-09-25)."""

RECORD_VERSION = "s2-crawl4ai/1"
"""Fixture record schema version (bump only with a fixture-diff migration)."""

MAX_PROVENANCE_BYTES = 4096
"""The S6 bounded-payload discipline, applied to the provenance record."""

MARKDOWN_ORIGIN = "crawl4ai.markdown"
_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})


class Crawl4aiUnavailableError(RuntimeError):
    """crawl4ai is absent or a non-pinned version is installed (fail closed)."""


class Crawl4aiProviderError(RuntimeError):
    """A refusal with a closed-set code — refusal-as-data, never silent."""

    def __init__(self, code: str, url: str, detail: str) -> None:
        self.code = code
        self.url = url
        self.detail = detail
        super().__init__(f"crawl4ai provider refused [{code}]: {detail}")


def canonical_json(value: Any) -> str:
    """Stable canonical JSON (sorted keys, compact) — hash input only."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── config + provenance ──


@dataclass(frozen=True, slots=True)
class Crawl4aiConfig:
    """The transform configuration recorded in every provenance record."""

    citations: bool = True
    html2text_options: Tuple[Tuple[str, Any], ...] = ()

    def __post_init__(self) -> None:
        pairs = tuple(sorted(
            (str(key), value) for key, value in self.html2text_options))
        object.__setattr__(self, "html2text_options", pairs)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "citations": self.citations,
            "html2text_options": dict(self.html2text_options),
        }

    @property
    def fingerprint(self) -> str:
        return _sha256_hex(canonical_json(self.to_mapping()).encode("utf-8"))

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "Crawl4aiConfig":
        options = mapping.get("html2text_options") or {}
        return cls(
            citations=bool(mapping["citations"]),
            html2text_options=tuple(sorted(
                (str(key), value) for key, value in options.items())),
        )


@dataclass(frozen=True, slots=True)
class Crawl4aiProvenance:
    """Library identity, transform config, guard trail, and content hashes."""

    version: str
    config: Crawl4aiConfig
    config_fingerprint: str
    source_ref: str
    requested_url: str
    final_url: str
    status: int
    content_type: str
    encoding: str
    source_sha256: str
    source_bytes: int
    raw_markdown_sha256: str
    markdown_sha256: str
    references_sha256: str
    redirect_hops: Tuple[str, ...]
    guard_policy_fingerprint: str
    guard_hops: Tuple[Tuple[str, str], ...]  # (url, pinned address) per hop
    library: str = "crawl4ai"

    def to_mapping(self) -> dict[str, Any]:
        return {
            "library": self.library,
            "version": self.version,
            "config": self.config.to_mapping(),
            "config_fingerprint": self.config_fingerprint,
            "source_ref": self.source_ref,
            "requested_url": self.requested_url,
            "final_url": self.final_url,
            "status": self.status,
            "content_type": self.content_type,
            "encoding": self.encoding,
            "source_sha256": self.source_sha256,
            "source_bytes": self.source_bytes,
            "raw_markdown_sha256": self.raw_markdown_sha256,
            "markdown_sha256": self.markdown_sha256,
            "references_sha256": self.references_sha256,
            "redirect_hops": list(self.redirect_hops),
            "guard_policy_fingerprint": self.guard_policy_fingerprint,
            "guard_hops": [list(hop) for hop in self.guard_hops],
        }

    def size_bytes(self) -> int:
        """Serialized size — must stay under the 4 KiB event-payload cap."""
        return len(canonical_json(self.to_mapping()).encode("utf-8"))

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "Crawl4aiProvenance":
        return cls(
            library=str(mapping["library"]),
            version=str(mapping["version"]),
            config=Crawl4aiConfig.from_mapping(mapping["config"]),
            config_fingerprint=str(mapping["config_fingerprint"]),
            source_ref=str(mapping["source_ref"]),
            requested_url=str(mapping["requested_url"]),
            final_url=str(mapping["final_url"]),
            status=int(mapping["status"]),
            content_type=str(mapping["content_type"]),
            encoding=str(mapping["encoding"]),
            source_sha256=str(mapping["source_sha256"]),
            source_bytes=int(mapping["source_bytes"]),
            raw_markdown_sha256=str(mapping["raw_markdown_sha256"]),
            markdown_sha256=str(mapping["markdown_sha256"]),
            references_sha256=str(mapping["references_sha256"]),
            redirect_hops=tuple(str(h) for h in mapping["redirect_hops"]),
            guard_policy_fingerprint=str(
                mapping["guard_policy_fingerprint"]),
            guard_hops=tuple((str(hop[0]), str(hop[1]))
                             for hop in mapping["guard_hops"]),
        )


@dataclass(frozen=True, slots=True)
class MarkdownRender:
    """The transform result — each string wrapped as untrusted text."""

    raw: UntrustedContent
    cited: UntrustedContent
    references: UntrustedContent


@dataclass(frozen=True, slots=True)
class Crawl4aiPage:
    """The provider output: one untrusted markdown payload + provenance."""

    content: UntrustedContent
    provenance: Crawl4aiProvenance

    @property
    def payload(self) -> str:
        """The deliberate ``.text`` unwrap (grep-auditable trust seam)."""
        return self.content.text

    def to_record(self) -> dict[str, Any]:
        return {
            "record_version": RECORD_VERSION,
            "content": {
                "text": self.payload,
                "origin": self.content.origin,
                "ref": self.content.ref,
            },
            "provenance": self.provenance.to_mapping(),
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "Crawl4aiPage":
        if record.get("record_version") != RECORD_VERSION:
            raise ValueError(
                f"unsupported record_version {record.get('record_version')!r}")
        content = record["content"]
        text = content["text"]
        if not isinstance(text, str):
            raise ValueError("content.text must be a string")
        return cls(
            content=UntrustedContent(
                text=text,
                origin=str(content["origin"]),
                ref=str(content["ref"]),
            ),
            provenance=Crawl4aiProvenance.from_mapping(record["provenance"]),
        )


# ── the pinned library (the only crawl4ai-touching code) ──


def _load_generator_class() -> Any:
    """Resolve the pinned crawl4ai markdown generator or fail closed."""
    try:
        installed = importlib.metadata.version("crawl4ai")
    except importlib.metadata.PackageNotFoundError:
        raise Crawl4aiUnavailableError(
            f"crawl4ai is not installed; this provider requires the exact "
            f"pin {CRAWL4AI_PIN!r}"
        ) from None
    if installed != CRAWL4AI_PIN:
        raise Crawl4aiUnavailableError(
            f"crawl4ai {installed!r} is installed but this provider is pinned "
            f"to {CRAWL4AI_PIN!r}; upgrades go through a fixture-diff test "
            f"(adoption §4 rule 2)")
    module = importlib.import_module("crawl4ai.markdown_generation_strategy")
    return module.DefaultMarkdownGenerator


def render_markdown(
    html: str,
    *,
    base_url: str = "",
    config: Crawl4aiConfig | None = None,
) -> MarkdownRender:
    """Run the pinned crawl4ai markdown transform over already-fetched HTML.

    No network I/O: the input must come from the guard-owned fetch leg (or a
    committed fixture). Performs no writes and holds no state.
    """
    config = config or Crawl4aiConfig()
    generator_class = _load_generator_class()
    options = dict(config.html2text_options) or None
    generator = generator_class(options=options)
    result = generator.generate_markdown(
        input_html=html, base_url=base_url, citations=True)
    raw = str(getattr(result, "raw_markdown", "") or "")
    cited = str(getattr(result, "markdown_with_citations", "") or raw)
    references = str(getattr(result, "references_markdown", "") or "")
    return MarkdownRender(
        raw=UntrustedContent(text=raw, origin=MARKDOWN_ORIGIN,
                             ref=base_url),
        cited=UntrustedContent(text=cited, origin=MARKDOWN_ORIGIN,
                               ref=base_url),
        references=UntrustedContent(text=references, origin=MARKDOWN_ORIGIN,
                                    ref=base_url),
    )


def _encoding_of(content_type: str) -> str:
    for part in content_type.split(";")[1:]:
        key, _, value = part.strip().partition("=")
        if key.strip().lower() == "charset" and value.strip():
            candidate = value.strip().strip('"').lower()
            try:
                codecs.lookup(candidate)
            except LookupError:
                continue
            return candidate
    return "utf-8"


def render_page(
    url: str,
    *,
    fetcher: GuardedFetcher,
    config: Crawl4aiConfig | None = None,
    source_ref: str = "",
) -> Crawl4aiPage:
    """Guarded fetch → pinned crawl4ai markdown → one untrusted payload.

    The guard is exercised on every hop of the fetch leg; a refusal propagates
    as ``EgressRefused`` before any library code runs.
    """
    config = config or Crawl4aiConfig()
    # AUDIT-S2 E1 — seal provenance to the real GuardedFetcher so a duck-
    # typed fetcher cannot launder guard-anchored trails; the type guard
    # is the smallest change that closes the API-shape hazard.
    if not isinstance(fetcher, GuardedFetcher):
        raise TypeError(
            "render_page requires a hermes.security.egress.GuardedFetcher "
            f"(got {type(fetcher).__name__}); guard-anchored provenance "
            "cannot be produced by any other fetcher")
    page: FetchedPage = fetcher.fetch(url)
    if not 200 <= page.status < 300:
        raise Crawl4aiProviderError(
            "FETCH_STATUS", url,
            f"HTTP {page.status} is not renderable (non-2xx, fail closed)")
    content_type = page.content_type or ""
    if content_type not in _HTML_TYPES:
        raise Crawl4aiProviderError(
            "NOT_HTML", url,
            f"content type {content_type or '<missing>'!r} is not HTML")
    encoding = _encoding_of(
        page.header("Content-Type") or content_type)
    html = page.body.decode(encoding, errors="replace")
    render = render_markdown(html, base_url=page.url, config=config)
    payload = render.cited if config.citations else render.raw

    provenance = Crawl4aiProvenance(
        version=importlib.metadata.version("crawl4ai"),
        config=config,
        config_fingerprint=config.fingerprint,
        source_ref=source_ref or f"crawl4ai:{page.url}",
        requested_url=page.requested_url,
        final_url=page.url,
        status=page.status,
        content_type=content_type,
        encoding=encoding,
        source_sha256=_sha256_hex(page.body),
        source_bytes=len(page.body),
        raw_markdown_sha256=_sha256_hex(render.raw.text.encode("utf-8")),
        markdown_sha256=_sha256_hex(payload.text.encode("utf-8")),
        references_sha256=_sha256_hex(
            render.references.text.encode("utf-8")),
        redirect_hops=page.hops,
        guard_policy_fingerprint=fetcher.policy.fingerprint(),
        guard_hops=tuple((target.url, target.pinned)
                         for target in page.vetted),
    )
    if provenance.size_bytes() > MAX_PROVENANCE_BYTES:
        raise Crawl4aiProviderError(
            "PROVENANCE_TOO_LARGE", url,
            f"provenance is {provenance.size_bytes()} bytes — over the "
            f"{MAX_PROVENANCE_BYTES}-byte bound; it must become a content-hash "
            f"artifact ref before any event carries it")
    return Crawl4aiPage(content=payload, provenance=provenance)
