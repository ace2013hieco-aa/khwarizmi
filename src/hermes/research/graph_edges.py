"""GR3 v0 typed-edge extraction — pure substrate (P1b, IDR-043 reserved).

Deterministic structural citation extraction over the P1a corpus, and
the task template that carries it:

- ``GR3_EDGE_TYPES`` — the CLOSED v0 edge vocabulary: exactly
  ``{"cites"}``. The sole relation deterministic structural extraction
  can author honestly between corpus documents is explicit textual
  citation. Every other type is refused through this boundary (each
  has its own certified writer or is deferred with reasons in the P1b
  report) — an unknown or out-of-scope edge type fails the whole
  batch closed, never a silent field drop.
- ``extract_cites_mentions`` — pure ``(citing_ref, text)`` scan for
  explicit references to corpus members (repo path, basename, IDR tag
  forms; word-boundary matched; self-mentions excluded). No model
  calls anywhere on this path — extraction is FULLY deterministic:
  same bytes + same extractor version ⇒ same edge set. (There is no
  LLM output to envelop, so no UntrustedContent boundary is needed;
  the governed bytes are read from admitted artifacts, never
  model-authored.)
- ``validate_gr3_extraction`` — the deterministic admissibility gate
  (mirrors ``validate_extraction`` as the entry point): the claimed
  edge set must EQUAL the derived set exactly (a hallucinated edge or
  a silent drop is INVALID), endpoints must be well-formed, the
  extractor version must match. Returns a ``GR3ExtractionResult``;
  never raises on content (raises only on contract misuse).
- ``build_gr3_extract_task_payload`` — the deterministic GR3_EXTRACT
  task template: an ordinary ``INSERT_TASK`` payload (``TOOL_TASK``,
  DETERMINISTIC profile, content-addressed task id + idempotency key
  from corpus ref + template version). Admitted through the existing
  gateway — no new intent kind, no new scheduler, no new authority.

Pure: no DB, no clock, no writes, no network. The write boundary is
``hermes.persistence.graph_edges.GraphEdgeRepository`` (own
transaction; accepts only ADMITTED results and re-derives endpoint
identities). Agreement constants are deliberately duplicated there
(the EXTRACT triplication precedent) and pinned byte-identical by
``tests/test_gr3_edges.py``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Mapping

from hermes.research.programs import canonical_json, sha256_hex

__all__ = [
    "GR3_COST_CLASS",
    "GR3_EDGE_SCHEMA_VERSION",
    "GR3_EDGE_TYPES",
    "GR3_EXTRACTOR_VERSION",
    "GR3_EXTRACT_TEMPLATE",
    "GR3_PROFILE",
    "GR3_TEMPLATE_VERSION",
    "GR3EdgeDraft",
    "GR3EdgeError",
    "GR3ExtractionResult",
    "GR3ExtractionVerdict",
    "build_gr3_extract_task_payload",
    "extract_cites_mentions",
    "gr3_edge_draft_from_mapping",
    "gr3_idempotency_key",
    "gr3_task_id",
    "mention_forms_for",
    "validate_gr3_extraction",
]

#: Schema version of the v0 edge draft (bumped only with an explicit versioning decision — no such decision was issued in this workflow; treat any bump as a new charter).
GR3_EDGE_SCHEMA_VERSION = "1"

#: Deterministic extractor version pinned into every result (same
#: bytes + same version ⇒ same edge set; a rule change MUST bump this
#: so re-extraction drift is attributable, never silent).
GR3_EXTRACTOR_VERSION = "1"

#: Canonical GR3_EXTRACT template marker (spec.template). Matched
#: normalized (casefolded + stripped) at the write boundary.
GR3_EXTRACT_TEMPLATE = "gr3_extract"

#: Template version pinned into task identity.
GR3_TEMPLATE_VERSION = "1"

#: The gr3-extract task's agent profile (deterministic controller
#: execution — bytes are scanned, never model-judged).
GR3_PROFILE = "DETERMINISTIC"

#: Cost class for gr3-extract tasks (small deterministic bookkeeping).
GR3_COST_CLASS = "small"

#: The CLOSED v0 edge vocabulary. Scope rationale (full table in the
#: P1b report): ``cites`` is the only relation structural extraction
#: can author honestly. ``supports``/``entails`` need semantic
#: judgment (model authority — forbidden — or a declared-substrate
#: boundary — director-gated future). ``derived_from``/``used_as_input``
#: /``justifies``/``supersedes`` each have a certified writer already;
#: this boundary must not co-author them.
GR3_EDGE_TYPES = frozenset({"cites"})

#: INSERT_TASK payload keys the template owns (mirrors
#: gateway._TASK_PAYLOAD_KEYS — the payload must remain gateway-valid).
_TASK_PAYLOAD_KEYS = frozenset({
    "task_id", "task_type", "profile", "spec", "inputs", "outputs",
    "dependencies", "provenance", "idempotency_key", "iteration",
    "parent_task_id", "cost_class", "concurrency_group", "max_retries",
})

#: Closed edge-draft keys (EC-F01 style).
_EDGE_KEYS = frozenset({"citing_ref", "cited_ref", "edge_type"})

#: A document-looking token: dotted path or IDR tag (candidates for
#: the skipped set when they resolve outside the corpus).
_MENTION_RE = re.compile(
    r"(?<![A-Za-z0-9_/.\-])"
    r"([A-Za-z0-9_][A-Za-z0-9_.\-/]*\.md\b|IDR-\d+)"
)

#: An IDR-tagged corpus member contributes its tag as a mention form
#: (e.g. docs/idr/IDR-024.md ⇔ "IDR-024").
_IDR_STEM_RE = re.compile(r"IDR-\d+\Z")


class GR3EdgeError(ValueError):
    """A GR3 edge draft, mention scan, or extraction result fails the
    closed v0 contract — fail-closed, nothing derived from it."""


@dataclass(frozen=True)
class GR3EdgeDraft:
    """One claimed v0 edge: citing corpus document → cited corpus
    document, always ``cites`` (the type is carried so unknown types
    fail loudly at the mapping layer, not downstream)."""

    citing_ref: str
    cited_ref: str
    edge_type: str


@dataclass(frozen=True)
class GR3ExtractionResult:
    """The deterministic admissibility verdict over one citing document."""

    verdict: GR3ExtractionVerdict
    citing_ref: str
    citing_hash: str
    extractor_version: str
    edges: tuple[GR3EdgeDraft, ...] = ()
    skipped: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


class GR3ExtractionVerdict(str, Enum):
    """Closed verdict vocabulary."""

    ADMITTED = "ADMITTED"
    INVALID = "INVALID"


def mention_forms_for(corpus_ref: str) -> tuple[str, ...]:
    """All textual forms under which ``corpus_ref`` may be cited.

    Full repo path + basename always; the IDR tag additionally for
    IDR-tagged members. Sorted, deterministic.
    """
    pure = PurePosixPath(corpus_ref)
    forms = {corpus_ref, pure.name}
    if _IDR_STEM_RE.match(pure.stem):
        forms.add(pure.stem)
    return tuple(sorted(forms))


def _boundaries(form: str) -> re.Pattern[str]:
    return re.compile(
        r"(?<![A-Za-z0-9_/.\-])" + re.escape(form)
        + r"(?![A-Za-z0-9_])")


def extract_cites_mentions(
    citing_ref: str,
    text: str,
    corpus_refs: tuple[str, ...] | frozenset[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Scan ``text`` for explicit citations of corpus members.

    Returns ``(cited, skipped)`` — both sorted tuples. ``cited`` holds
    corpus refs with at least one boundary-matched mention form
    (self-mentions excluded: a document citing itself is not a graph
    edge). ``skipped`` holds document-looking tokens that resolve to
    no corpus member (outside-world references are observed, never
    edges). Pure: same inputs ⇒ same outputs, no I/O, no clock.
    """
    if not isinstance(text, str):
        raise GR3EdgeError(
            f"citing text must be a string, got {type(text).__name__}")
    members = tuple(sorted(set(corpus_refs)))
    if citing_ref not in members:
        raise GR3EdgeError(
            f"citing_ref {citing_ref!r} is not a corpus member")
    form_to_ref: dict[str, str] = {}
    for ref in members:
        for form in mention_forms_for(ref):
            form_to_ref.setdefault(form, ref)
    cited: set[str] = set()
    for form, ref in form_to_ref.items():
        if ref != citing_ref and _boundaries(form).search(text):
            cited.add(ref)
    tokens = {m.group(1) for m in _MENTION_RE.finditer(text)}
    indexed_forms = set(form_to_ref)
    skipped = sorted(t for t in tokens if t not in indexed_forms)
    return (tuple(sorted(cited)), tuple(skipped))


def gr3_edge_draft_from_mapping(data: Mapping[str, Any]) -> GR3EdgeDraft:
    """Strictly map one claimed edge (fail-closed on unknown keys and
    on any edge type outside the v0 vocabulary)."""
    if not isinstance(data, Mapping):
        raise TypeError(
            f"gr3 edge must be a mapping, got {type(data).__name__}")
    unknown = sorted(set(data) - _EDGE_KEYS)
    if unknown:
        raise GR3EdgeError(
            f"gr3 edge: unknown keys {unknown} — the edge schema is closed")
    citing = data.get("citing_ref")
    cited = data.get("cited_ref")
    if not isinstance(citing, str) or not citing:
        raise GR3EdgeError(
            f"citing_ref must be a non-empty string, got {citing!r}")
    if not isinstance(cited, str) or not cited:
        raise GR3EdgeError(
            f"cited_ref must be a non-empty string, got {cited!r}")
    if citing == cited:
        raise GR3EdgeError(
            f"self-edge {citing!r} → {cited!r} refused — a document "
            f"citing itself is not a graph edge")
    edge_type = data.get("edge_type")
    if edge_type not in GR3_EDGE_TYPES:
        raise GR3EdgeError(
            f"edge_type {edge_type!r} is outside the v0 vocabulary "
            f"{sorted(GR3_EDGE_TYPES)} — unknown types fail closed")
    return GR3EdgeDraft(
        citing_ref=citing, cited_ref=cited, edge_type=edge_type)


def validate_gr3_extraction(
    citing_ref: str,
    citing_bytes: bytes,
    claimed: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
    cited_hashes: Mapping[str, str],
    corpus_refs: tuple[str, ...] | frozenset[str],
    *,
    extractor_version: str = GR3_EXTRACTOR_VERSION,
) -> GR3ExtractionResult:
    """Deterministic admissibility gate for one citing document.

    Re-runs the extractor over the BYTES and requires the claimed edge
    set to EQUAL the derived set exactly: a hallucinated edge or a
    silent drop is INVALID. ``cited_hashes`` maps each claimed cited
    ref to its admitted content hash (untrusted input — the write path
    re-verifies every hash against the admitted row metadata before
    writing). Never raises on content; contract misuse raises.
    """
    if extractor_version != GR3_EXTRACTOR_VERSION:
        raise GR3EdgeError(
            f"extractor_version {extractor_version!r} unsupported "
            f"(pinned {GR3_EXTRACTOR_VERSION})")
    if not isinstance(citing_bytes, (bytes, bytearray)):
        raise TypeError(
            f"citing bytes must be bytes, got {type(citing_bytes).__name__}")
    raw = bytes(citing_bytes)
    citing_hash = sha256_hex(raw)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return GR3ExtractionResult(
            verdict=GR3ExtractionVerdict.INVALID,
            citing_ref=citing_ref, citing_hash=citing_hash,
            extractor_version=extractor_version,
            errors=(f"decode: citing bytes are not UTF-8 ({exc})",))
    try:
        derived, skipped = extract_cites_mentions(
            citing_ref, text, corpus_refs)
    except GR3EdgeError as exc:
        return GR3ExtractionResult(
            verdict=GR3ExtractionVerdict.INVALID,
            citing_ref=citing_ref, citing_hash=citing_hash,
            extractor_version=extractor_version,
            errors=(f"scan: {exc}",))
    errors: list[str] = []
    claimed_drafts: list[GR3EdgeDraft] = []
    for i, raw_edge in enumerate(claimed):
        try:
            draft = gr3_edge_draft_from_mapping(raw_edge)
        except (GR3EdgeError, TypeError) as exc:
            errors.append(f"edge[{i}]: {exc}")
            continue
        if draft.citing_ref != citing_ref:
            errors.append(
                f"edge[{i}]: citing_ref {draft.citing_ref!r} != batch "
                f"citing {citing_ref!r} — one batch, one citing document")
            continue
        claimed_hash = cited_hashes.get(draft.cited_ref)
        if not isinstance(claimed_hash, str) or not claimed_hash:
            errors.append(
                f"edge[{i}]: no admitted content hash for cited "
                f"{draft.cited_ref!r}")
            continue
        claimed_drafts.append(draft)
    if errors:
        return GR3ExtractionResult(
            verdict=GR3ExtractionVerdict.INVALID,
            citing_ref=citing_ref, citing_hash=citing_hash,
            extractor_version=extractor_version,
            skipped=skipped, errors=tuple(errors))
    derived_set = set(derived)
    claimed_set = {d.cited_ref for d in claimed_drafts}
    if claimed_set != derived_set:
        problems = []
        for extra in sorted(claimed_set - derived_set):
            problems.append(
                f"hallucinated: {extra!r} not cited by the bytes")
        for missing in sorted(derived_set - claimed_set):
            problems.append(
                f"dropped: {missing!r} cited by the bytes but unclaimed")
        return GR3ExtractionResult(
            verdict=GR3ExtractionVerdict.INVALID,
            citing_ref=citing_ref, citing_hash=citing_hash,
            extractor_version=extractor_version,
            skipped=skipped, errors=tuple(problems))
    ordered = tuple(sorted(
        claimed_drafts, key=lambda d: (d.cited_ref, d.edge_type)))
    return GR3ExtractionResult(
        verdict=GR3ExtractionVerdict.ADMITTED,
        citing_ref=citing_ref, citing_hash=citing_hash,
        extractor_version=extractor_version,
        edges=ordered, skipped=skipped)


def gr3_task_id(
    corpus_ref: str,
    template_version: str = GR3_TEMPLATE_VERSION,
) -> str:
    """Content-addressed GR3_EXTRACT task id: ``gr3x_<sha256>[:24]``.

    Same corpus ref + template version ⇒ same task (PA4 at the task
    level — re-extraction of an unchanged document is the same task).
    """
    return "gr3x_" + sha256_hex(canonical_json({
        "kind": "gr3_extract_task",
        "corpus_ref": corpus_ref,
        "template_version": template_version,
    }))[:24]


def gr3_idempotency_key(
    corpus_ref: str,
    template_version: str = GR3_TEMPLATE_VERSION,
) -> str:
    """The task's idempotency key (sha256 of the extraction identity)."""
    return sha256_hex(canonical_json({
        "kind": "gr3_extract",
        "corpus_ref": corpus_ref,
        "template_version": template_version,
    }))


def build_gr3_extract_task_payload(
    corpus_ref: str,
    *,
    dependencies: tuple[str, ...] = (),
    provenance: tuple[str, ...] = (),
    template_version: str = GR3_TEMPLATE_VERSION,
) -> dict[str, Any]:
    """The INSERT_TASK payload for a GR3_EXTRACT task (deterministic).

    An ordinary ``TOOL_TASK`` admitted through the gateway — the task
    graph is the operational authority; nothing is inserted outside
    ``apply_intent``. One task extracts exactly one corpus document
    (``spec.corpus_ref``); the write path re-checks the equality.
    """
    if not isinstance(corpus_ref, str) or not corpus_ref:
        raise GR3EdgeError(
            f"corpus_ref must be a non-empty string, got {corpus_ref!r}")
    payload = {
        "task_id": gr3_task_id(corpus_ref, template_version),
        "task_type": "TOOL_TASK",
        "profile": GR3_PROFILE,
        "idempotency_key": gr3_idempotency_key(
            corpus_ref, template_version),
        "iteration": 1,
        "spec": {
            "template": GR3_EXTRACT_TEMPLATE,
            "template_version": template_version,
            "corpus_ref": corpus_ref,
        },
        "inputs": [],
        "outputs": [],
        "dependencies": list(dependencies),
        "provenance": list(provenance),
        "cost_class": GR3_COST_CLASS,
        "concurrency_group": None,
        "max_retries": 3,
        "parent_task_id": None,
    }
    unknown = sorted(set(payload) - _TASK_PAYLOAD_KEYS)
    if unknown:  # pragma: no cover — template/gateway key-set agreement
        raise GR3EdgeError(
            f"gr3 task payload keys {unknown} are outside "
            f"gateway._TASK_PAYLOAD_KEYS")
    return payload
