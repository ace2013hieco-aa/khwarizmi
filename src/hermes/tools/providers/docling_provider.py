"""docling document-conversion provider (S1 spike) — the ONLY importer of docling.

Adoption-proposal §4 rule 1: a third-party library lives in its own provider
module and is imported nowhere else. This module is that boundary for
``docling-project/docling``. It is **not** in ``PROVIDER_REGISTRY`` and no
other ``src/`` module imports it.

Contract (spike scope)
----------------------
- **Exact pin.** ``DOCLING_PIN`` is the S4-audited version. The module never
  imports docling at module import time; ``_load_docling`` resolves the
  installed distribution via ``importlib.metadata`` and fails closed
  (``DoclingUnavailableError``) when docling is absent or a different version
  is installed. No other version may run through this wrapper.
- **UntrustedContent + provenance, always.** ``convert_pdf`` returns a
  ``DoclingDocument`` whose payload is reachable only through its
  ``UntrustedContent`` envelope; ``DoclingProvenance`` records library name,
  exact version, config fingerprint, source ref, and input hash. Nothing here
  writes to trusted state: the document is an untrusted transport artifact
  until a caller dereferences a span (adoption §4 rule 3).
- **Spans.** Every payload block carries page / bbox / charspan records
  (``DoclingSpan``); ``locate(quote)`` is the only dereference seam — it finds
  the quote *exactly* inside a recorded block and returns its absolute payload
  charspan together with the block's page and bbox. Nothing fuzzy: a drifted
  index or a quote spanning block boundaries refuses instead of guessing.
  ``resolver_for(document)`` adapts to the certified HR-05 protocol
  ``Callable[[source_ref, span_ref], bool]`` — and, per AUDIT-S1 MUST-FIX
  A1, the ``span_ref`` it admits is the document's digest-anchored token
  (``span_ref_for`` / ``span_ref_token``): a bare substring is never a
  citation; the token binds the quote to the recorded payload bytes.
- **Bbox honesty.** docling provenance is block-level (an item's union bbox),
  so a located quote inherits the *block's* bbox — not a glyph-tight box. The
  fixture record and the S1 spike record state this limit explicitly.
- **Determinism.** Records contain no clock, no random, no process identity:
  re-running the same conversion on the same bytes yields the identical
  ``structure_digest`` (fixture test S1). The digest is computed over
  coordinates quantized to ``COORD_DECIMALS`` (0.001 pt); raw float values
  stay in the record. Rationale, from the S1 corpus: docling's model
  pipeline emitted a table-region bbox differing by ~2e-5 pt between two
  processes on one of four papers while payload, item spans and cells were
  bit-identical — the quantum is ~50x coarser than that observed variance
  and ~1000x finer than a glyph, so it removes model float noise without
  hiding any structural movement (a 0.001 pt shift still changes the digest).
- **Separate process (adoption §4 rule 5).** Model inference runs in a
  dedicated process with no access to secrets or the vault. This module reads
  exactly one file (the given PDF path), holds no credentials, consults no
  config/vault directory, and performs no network I/O of its own beyond what
  docling's pinned model downloader does on first use.

S1 status: spike wiring only — no EXTRACT/controller integration, no
persistence, no event payloads. Wiring into the controller remains gated on
the S1 verdict and a follow-up design gate.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, Tuple

from hermes.security.boundaries import UntrustedContent

__all__ = [
    "COORD_DECIMALS",
    "DOCLING_PIN",
    "MAX_PROVENANCE_BYTES",
    "RECORD_VERSION",
    "DoclingCell",
    "DoclingConfig",
    "DoclingDocument",
    "DoclingProvenance",
    "DoclingRecordError",
    "DoclingSpan",
    "DoclingTable",
    "DoclingUnavailableError",
    "LocatedSpan",
    "canonical_json",
    "convert_pdf",
    "resolver_for",
    "resolver_for_store_key",
    "span_ref_token",
    "span_token_resolves",
]

DOCLING_PIN = "2.131.0"
"""The exact docling version audited by S4 (commit d6f0307…, 2026-09-30)."""

COORD_DECIMALS = 3
"""Digest coordinate quantum (0.001 pt); raw values are kept in records."""

RECORD_VERSION = "s1-docling/1"
"""Fixture record schema version (bump only with a fixture-diff migration)."""

MAX_PROVENANCE_BYTES = 4096
"""The S6 bounded-payload discipline, applied to the provenance record."""

_ORIGIN = "docling.pdf"
_SPAN_KINDS = frozenset({"text", "table_cell"})
_BLOCK_SEP = "\n\n"
_CELL_SEP = " | "


class DoclingUnavailableError(RuntimeError):
    """docling is absent or a non-pinned version is installed (fail closed)."""


class DoclingRecordError(ValueError):
    """A serialized DoclingDocument record is corrupt or unsupported."""


def canonical_json(value: Any) -> str:
    """Stable canonical JSON (sorted keys, compact) — hash input only."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _quantized(value: Any) -> Any:
    """Recursively round floats to ``COORD_DECIMALS`` (digest input only)."""
    if isinstance(value, float):
        return round(value, COORD_DECIMALS)
    if isinstance(value, Mapping):
        return {key: _quantized(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_quantized(item) for item in value]
    return value


def _as_text(value: Any) -> str:
    return value if isinstance(value, str) else ""


# ── config + provenance ──


@dataclass(frozen=True, slots=True)
class DoclingConfig:
    """The conversion configuration recorded in every provenance record."""

    pipeline: str = "standard"
    do_ocr: bool = False
    do_table_structure: bool = True

    def to_mapping(self) -> dict[str, Any]:
        return {
            "pipeline": self.pipeline,
            "do_ocr": self.do_ocr,
            "do_table_structure": self.do_table_structure,
        }

    @property
    def fingerprint(self) -> str:
        """Content hash of the config (recorded; recomputed by tests)."""
        return _sha256_hex(canonical_json(self.to_mapping()).encode("utf-8"))

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "DoclingConfig":
        return cls(
            pipeline=str(mapping["pipeline"]),
            do_ocr=bool(mapping["do_ocr"]),
            do_table_structure=bool(mapping["do_table_structure"]),
        )


@dataclass(frozen=True, slots=True)
class DoclingProvenance:
    """Library name, exact version, config, input identity, and counts."""

    version: str
    config: DoclingConfig
    config_fingerprint: str
    source_ref: str
    pdf_sha256: str
    pdf_bytes: int
    filename: str
    page_count: int
    page_sizes: Tuple[Tuple[float, float], ...]
    item_count: int
    text_item_count: int
    table_count: int
    span_count: int
    skipped_nontext_items: int
    library: str = "docling"

    def to_mapping(self) -> dict[str, Any]:
        return {
            "library": self.library,
            "version": self.version,
            "config": self.config.to_mapping(),
            "config_fingerprint": self.config_fingerprint,
            "source_ref": self.source_ref,
            "pdf_sha256": self.pdf_sha256,
            "pdf_bytes": self.pdf_bytes,
            "filename": self.filename,
            "page_count": self.page_count,
            "page_sizes": [list(size) for size in self.page_sizes],
            "item_count": self.item_count,
            "text_item_count": self.text_item_count,
            "table_count": self.table_count,
            "span_count": self.span_count,
            "skipped_nontext_items": self.skipped_nontext_items,
        }

    def size_bytes(self) -> int:
        """Serialized size — must stay under the 4 KiB event-payload cap."""
        return len(canonical_json(self.to_mapping()).encode("utf-8"))

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "DoclingProvenance":
        sizes = tuple(
            (float(pair[0]), float(pair[1]))
            for pair in mapping["page_sizes"]
        )
        return cls(
            library=str(mapping["library"]),
            version=str(mapping["version"]),
            config=DoclingConfig.from_mapping(mapping["config"]),
            config_fingerprint=str(mapping["config_fingerprint"]),
            source_ref=str(mapping["source_ref"]),
            pdf_sha256=str(mapping["pdf_sha256"]),
            pdf_bytes=int(mapping["pdf_bytes"]),
            filename=str(mapping["filename"]),
            page_count=int(mapping["page_count"]),
            page_sizes=sizes,
            item_count=int(mapping["item_count"]),
            text_item_count=int(mapping["text_item_count"]),
            table_count=int(mapping["table_count"]),
            span_count=int(mapping["span_count"]),
            skipped_nontext_items=int(mapping["skipped_nontext_items"]),
        )


# ── spans / tables ──


@dataclass(frozen=True, slots=True)
class DoclingSpan:
    """One resolvable location: payload charspan + page + bbox + label."""

    kind: str                 # "text" | "table_cell"
    label: str                # docling label ("text", "section_header", …)
    page: int                 # 1-based, docling page_no
    bbox: Tuple[float, float, float, float]  # (l, t, r, b), BOTTOMLEFT
    coord_origin: str         # docling CoordOrigin (recorded, not assumed)
    char_start: int           # half-open range into the payload text
    char_end: int
    item_index: int           # reading-order item that produced the block
    table_index: int = -1     # set for kind == "table_cell"

    def to_mapping(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "page": self.page,
            "bbox": list(self.bbox),
            "coord_origin": self.coord_origin,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "item_index": self.item_index,
            "table_index": self.table_index,
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "DoclingSpan":
        bbox = tuple(float(v) for v in mapping["bbox"])
        if len(bbox) != 4:
            raise DoclingRecordError("span bbox must have 4 coordinates")
        kind = str(mapping["kind"])
        if kind not in _SPAN_KINDS:
            raise DoclingRecordError(f"unknown span kind {kind!r}")
        return cls(
            kind=kind,
            label=str(mapping["label"]),
            page=int(mapping["page"]),
            bbox=(bbox[0], bbox[1], bbox[2], bbox[3]),
            coord_origin=str(mapping["coord_origin"]),
            char_start=int(mapping["char_start"]),
            char_end=int(mapping["char_end"]),
            item_index=int(mapping["item_index"]),
            table_index=int(mapping.get("table_index", -1)),
        )


@dataclass(frozen=True, slots=True)
class DoclingCell:
    """One table cell: grid position + its exact payload charspan."""

    row: int
    col: int
    row_span: int
    col_span: int
    char_start: int
    char_end: int

    def to_mapping(self) -> dict[str, Any]:
        return {
            "row": self.row, "col": self.col,
            "row_span": self.row_span, "col_span": self.col_span,
            "char_start": self.char_start, "char_end": self.char_end,
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "DoclingCell":
        return cls(
            row=int(mapping["row"]), col=int(mapping["col"]),
            row_span=int(mapping["row_span"]),
            col_span=int(mapping["col_span"]),
            char_start=int(mapping["char_start"]),
            char_end=int(mapping["char_end"]),
        )


@dataclass(frozen=True, slots=True)
class DoclingTable:
    """A table's canonical, round-trippable structure (cells + payload spans)."""

    index: int
    item_index: int
    page: int
    bbox: Tuple[float, float, float, float]
    coord_origin: str
    rows: int
    cols: int
    cells: Tuple[DoclingCell, ...]

    def to_mapping(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "item_index": self.item_index,
            "page": self.page,
            "bbox": list(self.bbox),
            "coord_origin": self.coord_origin,
            "rows": self.rows,
            "cols": self.cols,
            "cells": [cell.to_mapping() for cell in self.cells],
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "DoclingTable":
        bbox = tuple(float(v) for v in mapping["bbox"])
        return cls(
            index=int(mapping["index"]),
            item_index=int(mapping["item_index"]),
            page=int(mapping["page"]),
            bbox=(bbox[0], bbox[1], bbox[2], bbox[3]),
            coord_origin=str(mapping["coord_origin"]),
            rows=int(mapping["rows"]),
            cols=int(mapping["cols"]),
            cells=tuple(DoclingCell.from_mapping(c)
                        for c in mapping["cells"]),
        )


# ── the document ──


@dataclass(frozen=True, slots=True)
class LocatedSpan:
    """A quote located inside a recorded span (exact absolute coordinates)."""

    span: DoclingSpan
    char_start: int
    char_end: int


@dataclass(frozen=True, slots=True)
class DoclingDocument:
    """The provider output: an untrusted payload + provenance + span index."""

    content: UntrustedContent
    provenance: DoclingProvenance
    spans: Tuple[DoclingSpan, ...]
    tables: Tuple[DoclingTable, ...]

    @property
    def payload(self) -> str:
        """The deliberate ``.text`` unwrap (grep-auditable trust seam).

        The only read of the envelope payload in this module; the resolver and
        the fixture serializer are the two callers, and neither writes state.
        """
        return self.content.text

    def payload_sha256(self) -> str:
        return _sha256_hex(self.payload.encode("utf-8"))

    def structure_digest(self) -> str:
        """Deterministic digest over payload + spans + tables + provenance.

        Coordinates are quantized to ``COORD_DECIMALS`` only for this digest;
        the record itself keeps docling's raw floats. See the module docstring
        for the S1-observed reason (model-level float variance ~2e-5 pt).
        """
        canonical = _quantized(self.to_record())
        return _sha256_hex(canonical_json(canonical).encode("utf-8"))

    def locate(self, quote: str) -> Tuple[LocatedSpan, ...]:
        """All exact occurrences of ``quote`` inside recorded spans.

        An empty tuple means the quote does not dereference — a fabricated,
        re-flowed, or block-crossing span is refused, never guessed. Each
        result carries the quote's absolute payload charspan plus the
        containing span (page + block bbox). Coordinate drift in a serialized
        record is caught here because the payload slice must match exactly.
        """
        if not isinstance(quote, str) or not quote:
            return ()
        payload = self.payload
        width = len(quote)
        located: list[LocatedSpan] = []
        for span in self.spans:
            if span.char_start < 0 or span.char_end <= span.char_start \
                    or span.char_end > len(payload):
                continue
            # find(sub, start, end) requires the whole match inside
            # [start, end) — so pass the span end as the bound directly.
            pos = payload.find(quote, span.char_start, span.char_end)
            while pos != -1:
                located.append(LocatedSpan(
                    span=span, char_start=pos, char_end=pos + width))
                pos = payload.find(quote, pos + 1, span.char_end)
        return tuple(located)

    def span_ref_for(self, quote: str) -> str:
        """The digest-anchored span_ref token for ``quote`` (AUDIT-S1 A1).

        The token binds (payload_sha256, the *host recorded span's exact
        payload slice*, the quote's absolute charspan inside that slice):
        unforgeable without this document, and verifiable without knowing
        the quote a priori (the host slice is recoverable from the index).
        A bare substring ("the", "T") carries no anchor and refuses.
        """
        located = self.locate(quote)
        if not located:
            raise ValueError(
                "quote does not dereference inside any recorded span; "
                "no span_ref token exists for it")
        first = located[0]
        return span_ref_token(
            self.payload_sha256(),
            self.payload[first.span.char_start:first.span.char_end],
            (first.char_start, first.char_end))

    def to_record(self) -> dict[str, Any]:
        """The fixture-serializable record (payload included, no clock)."""
        return {
            "record_version": RECORD_VERSION,
            "content": {
                "text": self.payload,
                "origin": self.content.origin,
                "ref": self.content.ref,
            },
            "provenance": self.provenance.to_mapping(),
            "spans": [span.to_mapping() for span in self.spans],
            "tables": [table.to_mapping() for table in self.tables],
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "DoclingDocument":
        """Strict loader (closed schema; corrupt fixtures fail loudly)."""
        version = record.get("record_version")
        if version != RECORD_VERSION:
            raise DoclingRecordError(
                f"unsupported record_version {version!r} "
                f"(expected {RECORD_VERSION!r})")
        content = record["content"]
        payload = content["text"]
        if not isinstance(payload, str):
            raise DoclingRecordError("content.text must be a string")
        spans = tuple(DoclingSpan.from_mapping(s) for s in record["spans"])
        tables = tuple(DoclingTable.from_mapping(t) for t in record["tables"])
        for span in spans:
            if not 0 <= span.char_start < span.char_end <= len(payload):
                raise DoclingRecordError(
                    f"span charspan [{span.char_start}, {span.char_end}) "
                    f"outside payload of length {len(payload)}")
        document = cls(
            content=UntrustedContent(
                text=payload,
                origin=str(content["origin"]),
                ref=str(content["ref"]),
            ),
            provenance=DoclingProvenance.from_mapping(record["provenance"]),
            spans=spans,
            tables=tables,
        )
        if document.provenance.span_count != len(spans):
            raise DoclingRecordError(
                "provenance.span_count does not match the span index")
        return document


def span_ref_token(payload_sha256: str, slice_text: str,
                   charspan: Tuple[int, int]) -> str:
    """The A1 span anchor: ``span:<sha256-16>:<start>:<end>``.

    The digest binds (payload hash, host span's exact payload slice, the
    cited quote's absolute charspan) — unforgeable without the document.
    The trailing charspan travels in the clear so the verifier can recover
    the candidate slice from the recorded index in O(host spans); it is
    digest-bound, so altering it invalidates the token. The payload hash
    binds the token to the exact recorded bytes: a rewritten payload
    invalidates every token derived from the pre-rewrite document.
    """
    digest = hashlib.sha256(canonical_json({
        "span_anchor/1": [payload_sha256, slice_text,
                          [int(charspan[0]), int(charspan[1])]],
    }).encode("utf-8")).hexdigest()[:16]
    return f"span:{digest}:{int(charspan[0])}:{int(charspan[1])}"


def span_token_resolves(document: DoclingDocument, span_ref: str) -> bool:
    """True iff ``span_ref`` is a valid digest anchor for this document.

    The AUDIT-S1 A1 token check on its own, shared by both admission seams:
    ``span_ref`` must be ``span:<sha256-16>:<start>:<end>``, the digest must
    recompute over this document's payload hash, the host recorded span's
    exact payload slice and the token's charspans, and the cited slice must
    locate inside the recorded spans at exactly those charspans. No
    ``source_ref`` is consulted — the caller owns citation identity.
    """
    if not isinstance(span_ref, str):
        return False
    # token shape: span:<digest16>:<start>:<end>
    parts = span_ref.split(":")
    if (len(parts) != 4 or parts[0] != "span"
            or len(parts[1]) != 16):
        return False
    try:
        start, end = int(parts[2]), int(parts[3])
    except ValueError:
        return False
    if not 0 <= start < end:
        return False
    payload = document.payload
    # the charspan is digest-bound, but recover the candidate host from
    # the recorded index first (O(spans)); a forged charspan either
    # finds no host or fails the digest recomputation below.
    # multiple recorded spans may contain the charspan (nested prov
    # entries); the token names exactly one (slice, charspan) pair, so
    # scan every host and admit only on a full recomputation match.
    for span in document.spans:
        if not (span.char_start <= start and end <= span.char_end
                and 0 <= span.char_start < span.char_end <= len(payload)):
            continue
        slice_text = payload[span.char_start:span.char_end]
        recomputed = span_ref_token(
            document.payload_sha256(), slice_text, (start, end))
        if recomputed != span_ref:
            continue
        cited = payload[start:end]
        located = document.locate(cited)
        if any(loc.char_start == start and loc.char_end == end
               for loc in located):
            return True
    return False


def resolver_for(document: DoclingDocument) -> Callable[[str, str], bool]:
    """Adapt the document's span index to the certified HR-05 protocol.

    Digest-anchored span refs (AUDIT-S1 MUST-FIX A1): ``resolve`` returns
    True only when (a) ``source_ref`` is the document's own ref AND (b)
    ``span_ref`` passes :func:`span_token_resolves` over this document's
    payload hash, host slice and charspans. A bare substring ("the", "T")
    carries no anchor and refuses: the token, not the substring, is the
    citation.
    """
    own_ref = document.content.ref

    def resolve(source_ref: str, span_ref: str) -> bool:
        if not isinstance(source_ref, str) or source_ref != own_ref:
            return False
        return span_token_resolves(document, span_ref)

    return resolve


def resolver_for_store_key(
        document: DoclingDocument,
) -> Callable[[str, str], bool]:
    """Adapt the span index when the citation ref is the payload store key.

    FETCH-FIX-M1 (merge/fetch@8e6f1b0 finding): the controller's HR-05 seam
    reads the payload through ``repos.read_payload``, which only resolves
    content-addressed ``source_payload:<sha256-64>`` keys. Under
    :func:`resolver_for` the citation ref had to equal the record's inner
    ``content.ref`` — but that inner ref is a string INSIDE the bytes the
    key hashes, so equality would require the record to contain the hash of
    itself: a fixed point no recorded document can satisfy.

    Admission here uses the identity the store already proved — the
    ``source_payload:`` key that yielded these bytes — plus this record's
    own ref chain and digest chain:

    (a) ``content.ref == provenance.source_ref`` must hold, so a spliced
        record (content from one document, provenance from another) fails
        closed;
    (b) ``span_ref`` must pass :func:`span_token_resolves`, recomputed over
        the bytes read at the store key.

    The inner ref is deliberately NOT an authorization key at this seam: it
    is author-declared metadata, and every other payload path cites the
    content-addressed key. The provider-level :func:`resolver_for` keeps its
    strict equality for the recorded seam.
    """
    def resolve(source_ref: str, span_ref: str) -> bool:
        if (not isinstance(source_ref, str)
                or not source_ref.startswith("source_payload:")):
            return False
        digest = source_ref[len("source_payload:"):]
        if len(digest) != 64 or not all(
                c in "0123456789abcdef" for c in digest):
            return False  # never trust a truncated alias as a key (SD2-04/§18)
        if document.content.ref != document.provenance.source_ref:
            return False
        return span_token_resolves(document, span_ref)

    return resolve


# ── the conversion (the only docling-touching code) ──


def _load_docling() -> Tuple[Any, Any, Any, Any]:
    """Resolve the pinned docling distribution or fail closed."""
    try:
        installed = importlib.metadata.version("docling")
    except importlib.metadata.PackageNotFoundError:
        raise DoclingUnavailableError(
            f"docling is not installed; this provider requires the exact "
            f"pin {DOCLING_PIN!r}"
        ) from None
    if installed != DOCLING_PIN:
        raise DoclingUnavailableError(
            f"docling {installed!r} is installed but this provider is pinned "
            f"to {DOCLING_PIN!r}; upgrade/downgrade goes through a fixture-diff "
            f"test (adoption §4 rule 2)")
    base_models = importlib.import_module("docling.datamodel.base_models")
    pipeline_options = importlib.import_module(
        "docling.datamodel.pipeline_options")
    converter_mod = importlib.import_module("docling.document_converter")
    return (base_models, pipeline_options, converter_mod, installed)


def _bbox_of(prov: Any) -> Tuple[float, float, float, float]:
    bbox = prov.bbox
    return (float(bbox.l), float(bbox.t), float(bbox.r), float(bbox.b))


def _coord_origin_of(prov: Any) -> str:
    origin = getattr(prov.bbox, "coord_origin", None)
    return str(origin) if origin is not None else ""


def _page_of(prov: Any) -> int:
    return int(getattr(prov, "page_no", 0))


def convert_pdf(
    pdf_path: str | Path,
    *,
    source_ref: str,
    config: DoclingConfig | None = None,
) -> DoclingDocument:
    """Convert one PDF into an untrusted payload + provenance + span index.

    Runs docling exactly once for the given bytes. ``source_ref`` must be an
    ``artifact_type:ref`` reference (the extraction pipeline's form).
    """
    config = config or DoclingConfig()
    if config.pipeline != "standard":
        raise ValueError(
            f"only the standard pipeline is wired in this spike, "
            f"got {config.pipeline!r}")
    if ":" not in source_ref:
        raise ValueError(
            f"source_ref must be an 'artifact_type:ref' reference, "
            f"got {source_ref!r}")

    path = Path(pdf_path)
    raw = path.read_bytes()
    if not raw:
        raise ValueError(f"empty PDF {path}")

    base_models, pipeline_options, converter_mod, installed = _load_docling()
    opts = pipeline_options.PdfPipelineOptions(
        do_ocr=config.do_ocr,
        do_table_structure=config.do_table_structure,
    )
    converter = converter_mod.DocumentConverter(
        format_options={
            base_models.InputFormat.PDF:
                converter_mod.PdfFormatOption(pipeline_options=opts),
        })
    result = converter.convert(str(path))
    doc = result.document

    provenance = DoclingProvenance(
        version=installed,
        config=config,
        config_fingerprint=config.fingerprint,
        source_ref=source_ref,
        pdf_sha256=_sha256_hex(raw),
        pdf_bytes=len(raw),
        filename=path.name,
        page_count=len(doc.pages),
        page_sizes=_page_sizes(doc),
        item_count=0,
        text_item_count=0,
        table_count=len(doc.tables),
        span_count=0,
        skipped_nontext_items=0,
    )
    payload, spans, tables, counts = _compose(doc)
    provenance = _replace_counts(provenance, counts, len(spans))
    if provenance.size_bytes() > MAX_PROVENANCE_BYTES:
        raise ValueError(
            f"provenance record is {provenance.size_bytes()} bytes — over the "
            f"{MAX_PROVENANCE_BYTES}-byte bound; it must become a "
            f"content-hash artifact ref before any event carries it")
    return DoclingDocument(
        content=UntrustedContent(
            text=payload, origin=_ORIGIN, ref=source_ref),
        provenance=provenance,
        spans=spans,
        tables=tables,
    )


def _page_sizes(doc: Any) -> Tuple[Tuple[float, float], ...]:
    sizes: list[Tuple[float, float]] = []
    for page_no in sorted(doc.pages):
        page = doc.pages[page_no]
        size = page.size
        sizes.append((float(size.width), float(size.height)))
    return tuple(sizes)


def _replace_counts(
    provenance: DoclingProvenance,
    counts: Mapping[str, int],
    span_count: int,
) -> DoclingProvenance:
    return DoclingProvenance(
        version=provenance.version,
        config=provenance.config,
        config_fingerprint=provenance.config_fingerprint,
        source_ref=provenance.source_ref,
        pdf_sha256=provenance.pdf_sha256,
        pdf_bytes=provenance.pdf_bytes,
        filename=provenance.filename,
        page_count=provenance.page_count,
        page_sizes=provenance.page_sizes,
        item_count=counts["items"],
        text_item_count=counts["text_items"],
        table_count=provenance.table_count,
        span_count=span_count,
        skipped_nontext_items=counts["skipped"],
    )


def _compose(doc: Any) -> Tuple[
        str, Tuple[DoclingSpan, ...], Tuple[DoclingTable, ...],
        dict[str, int]]:
    """Reading-order composition of the docling document.

    Text-bearing items become exact payload blocks; each `prov` entry becomes
    a span with its page/bbox and its charspan shifted into payload
    coordinates. Table items become a deterministic ``cells separated by
    " | ", rows separated by newline`` block; every physical cell resolves to
    an exact payload slice.

    The payload is provider-composed from docling item/cell texts (not
    ``export_to_markdown``): that keeps every charspan exact by construction,
    and the spike record states the trade (markdown fidelity is not claimed).
    """
    blocks: list[str] = []
    spans: list[DoclingSpan] = []
    tables: list[DoclingTable] = []
    cursor = 0
    counts = {"items": 0, "text_items": 0, "skipped": 0}

    for item_index, entry in enumerate(doc.iterate_items()):
        item, _level = entry if isinstance(entry, tuple) else (entry, 0)
        type_name = type(item).__name__
        text = _as_text(getattr(item, "text", None))
        if type_name == "TableItem":
            block, built_cells = _table_block(item, item_index, len(tables))
            if block:
                blocks.append(block)
                spans.extend(
                    _shift_spans([c.span for c in built_cells],
                                 cursor, item_index))
                tables.append(_table_record(item, item_index, len(tables),
                                            built_cells, cursor))
                cursor += len(block) + len(_BLOCK_SEP)
            else:
                counts["skipped"] += 1
        elif text:
            block_spans = _text_spans(item, text, item_index)
            if block_spans:
                blocks.append(text)
                spans.extend(_shift_spans(block_spans, cursor, item_index))
                cursor += len(text) + len(_BLOCK_SEP)
                counts["text_items"] += 1
            else:
                counts["skipped"] += 1
        else:
            counts["skipped"] += 1
        counts["items"] += 1

    payload = _BLOCK_SEP.join(blocks)
    return payload, tuple(spans), tuple(tables), counts


def _text_spans(item: Any, text: str, item_index: int) -> list[DoclingSpan]:
    label = str(getattr(item, "label", "") or "")
    out: list[DoclingSpan] = []
    for prov in getattr(item, "prov", []) or []:
        charspan = tuple(getattr(prov, "charspan", (0, 0)) or (0, 0))
        start, end = int(charspan[0]), int(charspan[1])
        if not (0 <= start < end <= len(text)):
            continue  # an unusable provenance entry is dropped, not guessed
        out.append(DoclingSpan(
            kind="text",
            label=label,
            page=_page_of(prov),
            bbox=_bbox_of(prov),
            coord_origin=_coord_origin_of(prov),
            char_start=start,
            char_end=end,
            item_index=item_index,
        ))
    return out


def _shift_spans(
    spans: Sequence[DoclingSpan], offset: int, item_index: int,
) -> list[DoclingSpan]:
    return [DoclingSpan(
        kind=span.kind,
        label=span.label,
        page=span.page,
        bbox=span.bbox,
        coord_origin=span.coord_origin,
        char_start=span.char_start + offset,
        char_end=span.char_end + offset,
        item_index=item_index,
        table_index=span.table_index,
    ) for span in spans]


@dataclass(frozen=True, slots=True)
class _BuiltCell:
    """A cell placed in block-local coordinates (internal builder type)."""

    span: DoclingSpan
    row: int
    col: int
    row_span: int
    col_span: int


def _table_block(
    table_item: Any, item_index: int, table_index: int,
) -> Tuple[str, list[_BuiltCell]]:
    """Build the table block; return it plus cells in block-local coords.

    Row-major over the physical grid; a merged cell is placed once, at its
    first appearance (later grid positions hold the same object). Cells are
    joined with ``" | "`` and rows with ``"\n"``, so every cell's charspan
    is exact by construction.
    """
    data = table_item.data
    grid = getattr(data, "grid", None) or []
    first_appearance: dict[int, Tuple[int, int]] = {}
    for r, row in enumerate(grid):
        for c, cell in enumerate(row):
            first_appearance.setdefault(id(cell), (r, c))

    lines: list[str] = []
    built: list[_BuiltCell] = []
    table_prov = (getattr(table_item, "prov", None) or [None])[0]
    cursor = 0
    for r, row in enumerate(grid):
        parts: list[str] = []
        for c, cell in enumerate(row):
            if first_appearance.get(id(cell)) != (r, c):
                continue  # merged-cell continuation: text already placed
            cell_text = _as_text(getattr(cell, "text", None))
            if not cell_text:
                continue
            if parts:
                cursor += len(_CELL_SEP)
            cell_bbox = getattr(cell, "bbox", None)
            if cell_bbox is not None:
                bbox = (float(cell_bbox.l), float(cell_bbox.t),
                        float(cell_bbox.r), float(cell_bbox.b))
                origin = str(getattr(cell_bbox, "coord_origin", ""))
            elif table_prov is not None:
                bbox = _bbox_of(table_prov)
                origin = _coord_origin_of(table_prov)
            else:
                bbox = (0.0, 0.0, 0.0, 0.0)
                origin = ""
            page = _page_of(table_prov) if table_prov is not None else 0
            span = DoclingSpan(
                kind="table_cell",
                label="table_cell",
                page=page,
                bbox=bbox,
                coord_origin=origin,
                char_start=cursor,
                char_end=cursor + len(cell_text),
                item_index=item_index,
                table_index=table_index,
            )
            built.append(_BuiltCell(
                span=span,
                row=int(getattr(cell, "start_row_offset_idx", r)),
                col=int(getattr(cell, "start_col_offset_idx", c)),
                row_span=int(getattr(cell, "row_span", 1) or 1),
                col_span=int(getattr(cell, "col_span", 1) or 1),
            ))
            parts.append(cell_text)
            cursor += len(cell_text)
        if parts:
            lines.append(_CELL_SEP.join(parts))
            cursor += 1  # the newline between rows
    return "\n".join(lines), built


def _table_record(
    table_item: Any, item_index: int, table_index: int,
    built_cells: Sequence[_BuiltCell], payload_offset: int,
) -> DoclingTable:
    data = table_item.data
    prov = (getattr(table_item, "prov", None) or [None])[0]
    bbox = _bbox_of(prov) if prov is not None else (0.0, 0.0, 0.0, 0.0)
    origin = _coord_origin_of(prov) if prov is not None else ""
    page = _page_of(prov) if prov is not None else 0
    cells = tuple(
        DoclingCell(
            row=cell.row,
            col=cell.col,
            row_span=cell.row_span,
            col_span=cell.col_span,
            char_start=cell.span.char_start + payload_offset,
            char_end=cell.span.char_end + payload_offset,
        )
        for cell in built_cells
    )
    return DoclingTable(
        index=table_index,
        item_index=item_index,
        page=page,
        bbox=bbox,
        coord_origin=origin,
        rows=int(getattr(data, "num_rows", 0)),
        cols=int(getattr(data, "num_cols", 0)),
        cells=cells,
    )
