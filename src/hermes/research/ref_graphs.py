"""GR3-P2-b4fixtures — B4 reference graphs (pure substrate).

Turns the P1b v0 ``cites`` extractor into a *packaged, content-addressed
reference graph set* — real typed-edge graphs over governed documents —
so the TEXP-001 twin can consume real structure instead of its
``no real graph exists — B4`` placeholder (``experiments/texp-001``
``generator.py``, ``StrataParams``).

Design (all pure: no DB, no clock, no network, no writes):

- ``B4_FIXTURE_SPECS`` — the handful of reference graphs. Each spec
  names a ``fixture_id``, a rationale, and a closed SOURCE SET drawn
  from ``GOVERNED_CORPUS_REFS`` (the P1a cohort plus the B4 reference
  cohort admitted through ``CorpusRepository``). Different specs are
  different strata of the same real corpus, not different corpora.
- ``build_reference_graph`` — re-runs the certified extractor over the
  supplied bytes and REQUIRES the claimed edge set to equal the derived
  set (``validate_gr3_extraction`` ⇒ ADMITTED). A hallucinated or
  dropped edge therefore cannot enter a fixture: the packaging path is
  gated by the same deterministic admissibility gate as the write path.
- ``reference_graph_bytes`` / ``reference_graph_digest`` — canonical
  JSON (``programs.canonical_json``) plus sha256 over those exact bytes.
  The fixture FILE NAME is the digest, so a fixture is addressed by its
  content and any edit to the file is detectable without a signature.
- ``parse_reference_graph`` — strict, closed-key reader (EC-F01 style):
  unknown keys, count drift, non-governed refs, or a self-edge fail
  closed, nothing returned.

Twin-namespace convention: every fixture declares
``namespace = B4_NAMESPACE`` (the ``texp-001`` twin) and
``consumption = B4_CONSUMPTION`` (``SIMULATED``), and carries
``authority = B4_AUTHORITY`` (``ADVISORY``). A B4 reference graph is
fidelity evidence for the twin — it is never production state, never a
governed artifact, and never authority for any transition.

Imports only ``hermes.research.*`` (no persistence import), so this
module sits cleanly on the research side of DG-5.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from hermes.research.corpus import (
    GOVERNED_CORPUS_REFS,
    load_corpus_bytes,
)
from hermes.research.graph_edges import (
    GR3_EXTRACTOR_VERSION,
    extract_cites_mentions,
    validate_gr3_extraction,
)
from hermes.research.programs import canonical_json, sha256_hex

__all__ = [
    "B4_AUTHORITY",
    "B4_CONSUMPTION",
    "B4_EDGE_TYPE",
    "B4_FIXTURES_DIRNAME",
    "B4_FIXTURE_SCHEMA_VERSION",
    "B4_FIXTURE_SPECS",
    "B4_NAMESPACE",
    "B4FixtureError",
    "B4FixtureSpec",
    "B4ReferenceGraph",
    "B4SourceDoc",
    "build_all_reference_graphs",
    "build_reference_graph",
    "fixture_filename",
    "parse_reference_graph",
    "reference_graph_body",
    "reference_graph_bytes",
    "reference_graph_digest",
]

#: Schema version of the packaged fixture body (bumped only with an explicit versioning decision — no such decision was issued in this workflow; treat any bump as a new charter).
B4_FIXTURE_SCHEMA_VERSION = "1"

#: Twin namespace marker: these graphs are consumed by the TEXP-001 twin.
B4_NAMESPACE = "texp-001-twin"

#: Consumption marker: twin fixtures are simulations, never production.
B4_CONSUMPTION = "SIMULATED"

#: Authority marker: advisory structure only — never a transition input.
B4_AUTHORITY = "ADVISORY"

#: The only edge type v0 extraction authorises (mirrors GR3_EDGE_TYPES).
B4_EDGE_TYPE = "cites"

#: Repo-relative directory the packaged fixtures live in.
B4_FIXTURES_DIRNAME = "docs/gr3-b4/b4-fixtures"

#: The doc-side spine: the four non-IDR documents of the governed corpus.
_DOC_SPINE = frozenset({
    "AGENTS.md",
    "docs/API.md",
    "docs/ARCHITECTURE.md",
    "docs/STATE.md",
})

_SIX = frozenset({"AGENTS.md", "docs/API.md", "docs/ARCHITECTURE.md",
                  "docs/STATE.md", "docs/idr/IDR-024.md",
                  "docs/idr/IDR-028.md"})


class B4FixtureError(ValueError):
    """A B4 reference graph, fixture body, or source set fails the
    closed contract — fail closed, nothing derived from it."""


@dataclass(frozen=True, slots=True)
class B4FixtureSpec:
    """One packaged reference graph: a closed, governed source set plus
    the reason that set is a useful stratum of the corpus."""

    fixture_id: str
    rationale: str
    source_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class B4SourceDoc:
    """One governed source document, content-addressed."""

    corpus_ref: str
    content_hash: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class B4ReferenceGraph:
    """A real typed-edge graph extracted from governed bytes.

    ``edges`` are ``(citing_ref, cited_ref, edge_type)`` triples;
    ``skipped`` are document-looking tokens that resolved outside the
    source set (observed, never edges). Both are sorted tuples.
    """

    fixture_id: str
    rationale: str
    fixture_schema_version: str
    extraction_version: str
    namespace: str
    consumption: str
    authority: str
    sources: tuple[B4SourceDoc, ...]
    edges: tuple[tuple[str, str, str], ...]
    skipped: tuple[str, ...]


def _spec(fixture_id: str, rationale: str,
          refs: frozenset[str]) -> B4FixtureSpec:
    return B4FixtureSpec(fixture_id=fixture_id, rationale=rationale,
                         source_refs=tuple(sorted(refs)))


#: The packaged reference graphs (count is discretion: enough to replace
#: the twin's "no real graph exists" assumption, deliberately not
#: exhaustive). Every source set is a subset of GOVERNED_CORPUS_REFS.
B4_FIXTURE_SPECS: tuple[B4FixtureSpec, ...] = (
    _spec(
        "b4-c1-p1a-baseline",
        "The P1a six alone: the certified P1b v0 citations graph "
        "(AGENTS.md -> 3, docs/API.md -> 1, docs/STATE.md -> 1; the two "
        "IDRs are empty no-ops). Retained as the baseline stratum so "
        "the B4 delta is measurable against the certified graph.",
        _SIX,
    ),
    _spec(
        "b4-c2-expanded-cohort",
        "The full expanded sample: the P1a six plus the six real "
        "documents they directly cite. The reference graph -- 12 nodes, "
        "the richest stratum, and the set that turns previously "
        "observed 'skipped' outside-world mentions into real edges.",
        GOVERNED_CORPUS_REFS,
    ),
    _spec(
        "b4-c3-idr-design-chain",
        "The eight IDR members of the cohort: the decision-record "
        "citation chain (IDR-023 -> IDR-018; IDR-028 -> {IDR-025, "
        "IDR-026, IDR-027}; IDR-036 -> IDR-026). The design-history "
        "stratum, structurally distinct from the doc spine.",
        GOVERNED_CORPUS_REFS - _DOC_SPINE,
    ),
    _spec(
        "b4-c4-authority-spine",
        "The four non-IDR documents: AGENTS.md, docs/API.md, "
        "docs/ARCHITECTURE.md, docs/STATE.md -- the operating-rules / "
        "surface / map / state spine the twin's authority discussion "
        "references. The most cited stratum.",
        _DOC_SPINE,
    ),
)


def _require_spec_refs(spec: B4FixtureSpec) -> tuple[str, ...]:
    if not isinstance(spec, B4FixtureSpec):
        raise TypeError(
            f"spec must be a B4FixtureSpec, got {type(spec).__name__}")
    refs = tuple(spec.source_refs)
    if not refs:
        raise B4FixtureError(
            f"fixture {spec.fixture_id!r}: an empty source set builds "
            f"no graph")
    ungoverned = sorted(set(refs) - GOVERNED_CORPUS_REFS)
    if ungoverned:
        raise B4FixtureError(
            f"fixture {spec.fixture_id!r}: source refs {ungoverned} are "
            f"outside the governed corpus — a reference graph is built "
            f"only from documents that entered through admission")
    return refs


def build_reference_graph(
    spec: B4FixtureSpec,
    source_bytes: Mapping[str, bytes],
    *,
    extractor_version: str = GR3_EXTRACTOR_VERSION,
) -> B4ReferenceGraph:
    """Extract one reference graph over the spec's closed source set.

    Fully deterministic and gated: every document is re-scanned for
    corpus mentions, the derived citations are re-validated through
    ``validate_gr3_extraction`` (which requires claimed == derived), and
    only then is the graph packaged. ``source_bytes`` must be EXACTLY
    the spec's source set — a missing document refuses (a fixture
    silently built on fewer docs would misrepresent its source set).
    """
    refs = _require_spec_refs(spec)
    if not isinstance(source_bytes, Mapping):
        raise TypeError(
            f"source_bytes must be a mapping, got "
            f"{type(source_bytes).__name__}")
    missing = [r for r in refs if r not in source_bytes]
    if missing:
        raise B4FixtureError(
            f"fixture {spec.fixture_id!r}: source_bytes is missing "
            f"{missing}")
    extra = sorted(set(source_bytes) - set(refs))
    if extra:
        raise B4FixtureError(
            f"fixture {spec.fixture_id!r}: source_bytes carries "
            f"unlisted refs {extra} — the source set is closed")

    raw: dict[str, bytes] = {}
    hashes: dict[str, str] = {}
    for ref in refs:
        data = source_bytes[ref]
        if not isinstance(data, (bytes, bytearray)):
            raise B4FixtureError(
                f"fixture {spec.fixture_id!r}: bytes for {ref!r} are "
                f"{type(data).__name__}, not bytes")
        body = bytes(data)
        if not body:
            raise B4FixtureError(
                f"fixture {spec.fixture_id!r}: {ref!r} is empty — "
                f"nothing to extract")
        raw[ref] = body
        hashes[ref] = sha256_hex(body)

    edges: list[tuple[str, str, str]] = []
    skipped: set[str] = set()
    for ref in refs:
        try:
            text = raw[ref].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise B4FixtureError(
                f"fixture {spec.fixture_id!r}: {ref!r} is not UTF-8 "
                f"({exc})") from None
        cited, outside = extract_cites_mentions(ref, text, refs)
        claimed: list[Mapping[str, Any]] = [
            {"citing_ref": ref, "cited_ref": c, "edge_type": B4_EDGE_TYPE}
            for c in cited
        ]
        result = validate_gr3_extraction(
            ref, raw[ref], claimed, {c: hashes[c] for c in cited}, refs,
            extractor_version=extractor_version)
        if result.verdict != "ADMITTED":
            raise B4FixtureError(
                f"fixture {spec.fixture_id!r}: {ref!r} failed the "
                f"admissibility gate: {list(result.errors)}")
        for edge in result.edges:
            edges.append(
                (edge.citing_ref, edge.cited_ref, edge.edge_type))
        skipped.update(outside)

    return B4ReferenceGraph(
        fixture_id=spec.fixture_id,
        rationale=spec.rationale,
        fixture_schema_version=B4_FIXTURE_SCHEMA_VERSION,
        extraction_version=extractor_version,
        namespace=B4_NAMESPACE,
        consumption=B4_CONSUMPTION,
        authority=B4_AUTHORITY,
        sources=tuple(
            B4SourceDoc(corpus_ref=r, content_hash=hashes[r],
                        size_bytes=len(raw[r]))
            for r in refs),
        edges=tuple(sorted(edges)),
        skipped=tuple(sorted(skipped)),
    )


def build_all_reference_graphs(
    root: str | Path,
    *,
    specs: tuple[B4FixtureSpec, ...] = B4_FIXTURE_SPECS,
) -> tuple[B4ReferenceGraph, ...]:
    """Build every packaged fixture from live repo bytes under ``root``.

    Deterministic in (specs, bytes at root): the same tree always yields
    the same graphs, which is what makes a committed fixture verifiable
    by regeneration.
    """
    built: list[B4ReferenceGraph] = []
    for spec in specs:
        refs = _require_spec_refs(spec)
        payload = {ref: load_corpus_bytes(root, ref) for ref in refs}
        built.append(build_reference_graph(spec, payload))
    return tuple(built)


def reference_graph_body(graph: B4ReferenceGraph) -> dict[str, Any]:
    """The canonical fixture body (closed keys, sorted, digest-free)."""
    if not isinstance(graph, B4ReferenceGraph):
        raise TypeError(
            f"graph must be a B4ReferenceGraph, got "
            f"{type(graph).__name__}")
    return {
        "fixture_id": graph.fixture_id,
        "rationale": graph.rationale,
        "fixture_schema_version": graph.fixture_schema_version,
        "extraction_version": graph.extraction_version,
        "namespace": graph.namespace,
        "consumption": graph.consumption,
        "authority": graph.authority,
        "source_set": [
            {"corpus_ref": s.corpus_ref, "content_hash": s.content_hash,
             "size_bytes": s.size_bytes}
            for s in graph.sources
        ],
        "edges": [
            {"citing_ref": a, "cited_ref": b, "edge_type": t}
            for a, b, t in graph.edges
        ],
        "skipped": list(graph.skipped),
        "counts": {
            "sources": len(graph.sources),
            "edges": len(graph.edges),
            "skipped": len(graph.skipped),
        },
    }


def reference_graph_bytes(graph: B4ReferenceGraph) -> bytes:
    """Canonical fixture bytes (the digest is sha256 over EXACTLY this)."""
    return (canonical_json(reference_graph_body(graph)) + "\n").encode(
        "utf-8")


def reference_graph_digest(graph: B4ReferenceGraph) -> str:
    """The fixture's content address."""
    return sha256_hex(reference_graph_bytes(graph))


def fixture_filename(graph: B4ReferenceGraph) -> str:
    """``<sha256>.json`` — the fixture is addressed by its own content."""
    return f"{reference_graph_digest(graph)}.json"


#: Closed fixture-body keys (EC-F01 style).
_BODY_KEYS = frozenset({
    "fixture_id", "rationale", "fixture_schema_version",
    "extraction_version", "namespace", "consumption", "authority",
    "source_set", "edges", "skipped", "counts",
})
_SOURCE_KEYS = frozenset({"corpus_ref", "content_hash", "size_bytes"})
_EDGE_KEYS = frozenset({"citing_ref", "cited_ref", "edge_type"})
_COUNT_KEYS = frozenset({"sources", "edges", "skipped"})


def _require_keys(kind: str, data: Any,
                  allowed: frozenset[str]) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise B4FixtureError(
            f"{kind} must be a mapping, got {type(data).__name__}")
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise B4FixtureError(
            f"{kind}: unknown keys {unknown} — the schema is closed")
    return data


def parse_reference_graph(
    data: bytes,
    *,
    expected_digest: str | None = None,
) -> B4ReferenceGraph:
    """Strictly read one packaged fixture (fail-closed).

    Verifies the byte digest (when ``expected_digest`` is supplied — the
    file-name check the twin performs), the closed schemas, the
    declared counts, governed source membership, and edge well-formedness
    (including the self-edge refusal). Never returns a partially trusted
    graph.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise B4FixtureError(
            f"fixture bytes must be bytes, got {type(data).__name__}")
    raw = bytes(data)
    if expected_digest is not None:
        actual = sha256_hex(raw)
        if actual != expected_digest:
            raise B4FixtureError(
                f"fixture digest mismatch: file names "
                f"{expected_digest!r} but bytes hash to {actual!r} — the "
                f"fixture was edited or the name is forged")
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise B4FixtureError(f"fixture is not canonical JSON ({exc})") \
            from None
    body = _require_keys("fixture body", body, _BODY_KEYS)

    sources: list[B4SourceDoc] = []
    for i, entry in enumerate(body.get("source_set") or []):
        src = _require_keys(f"source_set[{i}]", entry, _SOURCE_KEYS)
        src_ref = src.get("corpus_ref")
        if src_ref not in GOVERNED_CORPUS_REFS:
            raise B4FixtureError(
                f"source_set[{i}]: {src_ref!r} is outside the governed "
                f"corpus — a B4 fixture cites governed bytes only")
        src_hash = src.get("content_hash")
        if not isinstance(src_hash, str) or len(src_hash) != 64:
            raise B4FixtureError(
                f"source_set[{i}]: content_hash must be 64-hex, got "
                f"{src_hash!r}")
        src_size = src.get("size_bytes")
        if (not isinstance(src_size, int) or isinstance(src_size, bool)
                or src_size <= 0):
            raise B4FixtureError(
                f"source_set[{i}]: size_bytes must be a positive int, "
                f"got {src_size!r}")
        sources.append(B4SourceDoc(corpus_ref=src_ref,
                                   content_hash=src_hash,
                                   size_bytes=src_size))

    edges: list[tuple[str, str, str]] = []
    for i, entry in enumerate(body.get("edges") or []):
        edge = _require_keys(f"edges[{i}]", entry, _EDGE_KEYS)
        citing, cited = edge.get("citing_ref"), edge.get("cited_ref")
        etype = edge.get("edge_type")
        if not isinstance(citing, str) or not isinstance(cited, str):
            raise B4FixtureError(
                f"edges[{i}]: citing_ref/cited_ref must be strings")
        if citing == cited:
            raise B4FixtureError(
                f"edges[{i}]: self-edge {citing!r} → {cited!r} refused")
        if etype != B4_EDGE_TYPE:
            raise B4FixtureError(
                f"edges[{i}]: edge_type {etype!r} is outside the v0 "
                f"vocabulary {{'{B4_EDGE_TYPE}'}}")
        edges.append((citing, cited, etype))

    skipped_raw = body.get("skipped") or []
    if not all(isinstance(s, str) for s in skipped_raw):
        raise B4FixtureError("skipped entries must all be strings")
    # ``canonical_json`` orders lists by their serialized form; restore
    # this module's own (stable) order convention so a rebuilt graph and
    # a parsed graph compare equal.
    sources.sort(key=lambda s: s.corpus_ref)
    edges.sort()
    skipped = tuple(sorted(str(s) for s in skipped_raw))

    graph = B4ReferenceGraph(
        fixture_id=str(body.get("fixture_id")),
        rationale=str(body.get("rationale")),
        fixture_schema_version=str(body.get("fixture_schema_version")),
        extraction_version=str(body.get("extraction_version")),
        namespace=str(body.get("namespace")),
        consumption=str(body.get("consumption")),
        authority=str(body.get("authority")),
        sources=tuple(sources),
        edges=tuple(edges),
        skipped=skipped,
    )
    declared = _require_keys("counts", body.get("counts") or {},
                             _COUNT_KEYS)
    actual = {"sources": len(graph.sources), "edges": len(graph.edges),
              "skipped": len(graph.skipped)}
    if dict(declared) != actual:
        raise B4FixtureError(
            f"fixture counts {dict(declared)} disagree with the body "
            f"{actual} — a tampered fixture fails closed")
    if graph.namespace != B4_NAMESPACE:
        raise B4FixtureError(
            f"fixture namespace {graph.namespace!r} is not the twin "
            f"namespace {B4_NAMESPACE!r}")
    if graph.consumption != B4_CONSUMPTION:
        raise B4FixtureError(
            f"fixture consumption {graph.consumption!r} is not "
            f"{B4_CONSUMPTION!r} — a twin artifact is never presented "
            f"as production")
    return graph
