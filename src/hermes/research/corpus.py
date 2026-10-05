"""GR3 v0 corpus admission — pure substrate (P1a, IDR-042 reserved).

The bounded real-document corpus that P1b extraction will cite, and the
deterministic task template that admits it:

- ``CORPUS_REFS`` — the P1a cohort: the six ratified-baseline
  documents (IDR-042). UNCHANGED by GR3-P2-b4fixtures — P1b's
  certified extraction expectations are anchored on exactly these six.
- ``CORPUS_B4_COHORT_REFS`` — the B4 reference cohort: the real
  documents the P1a six directly cite (GR3-P2-b4fixtures).
- ``GOVERNED_CORPUS_REFS`` — the allowlist the boundary enforces
  (the union of both cohorts). Membership, not the cohort split, is
  what admission checks: a ref outside the union is refused at both
  the loader and the write boundary, never silently added.
- ``build_corpus_admit_task_payload`` — the deterministic CORPUS_ADMIT
  task template: an ordinary ``INSERT_TASK`` payload (``TOOL_TASK``,
  DETERMINISTIC profile, content-addressed task id + idempotency key
  from corpus ref + template version). Admitted through the existing
  gateway — no new intent kind, no new scheduler, no new authority.
- ``corpus_admission_from_mapping`` — strict mapping →
  ``CorpusAdmission`` validation (fail-closed on unknown keys,
  EC-F01 style).
- ``load_corpus_bytes`` — read one corpus document from an explicit
  root (closed ref membership, traversal guard, size cap).

Pure: no DB, no clock, no writes, no network. The write boundary is
``hermes.persistence.corpus.CorpusRepository`` (own transaction); the
agreement constants are deliberately duplicated there (the EXTRACT
vocabulary triplication precedent — admission and the write path can
never disagree) and pinned byte-identical by
``tests/test_corpus_admission.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from hermes.research.programs import canonical_json, sha256_hex

__all__ = [
    "CORPUS_ADMIT_TEMPLATE",
    "CORPUS_B4_COHORT_REFS",
    "CORPUS_COST_CLASS",
    "CORPUS_MAX_BYTES",
    "CORPUS_PROFILE",
    "CORPUS_REFS",
    "CORPUS_SCHEMA_VERSION",
    "CORPUS_TEMPLATE_VERSION",
    "GOVERNED_CORPUS_REFS",
    "CorpusAdmission",
    "CorpusDraftError",
    "build_corpus_admit_task_payload",
    "corpus_admission_from_mapping",
    "corpus_idempotency_key",
    "corpus_task_id",
    "load_corpus_bytes",
]

#: Schema version of the corpus admission draft (bumped only with an explicit versioning decision — no such decision was issued in this workflow; treat any bump as a new charter).
CORPUS_SCHEMA_VERSION = "1"

#: Canonical CORPUS_ADMIT template marker (spec.template). Matched
#: normalized (casefolded + stripped) at the write boundary, so a
#: hand-built task row cannot case-spoof its way past admission.
CORPUS_ADMIT_TEMPLATE = "corpus_admit"

#: Template version pinned into task identity.
CORPUS_TEMPLATE_VERSION = "1"

#: The corpus-admit task's agent profile (deterministic controller
#: execution — file bytes are read, never model-judged).
CORPUS_PROFILE = "DETERMINISTIC"

#: Cost class for corpus-admit tasks (small deterministic bookkeeping).
CORPUS_COST_CLASS = "small"

#: Per-document size cap (20 KiB). Every P1a corpus member fits with
#: margin (largest: docs/ARCHITECTURE.md at 15,986 bytes); larger
#: baseline documents (v6 architecture, README, CONTRA review, IDR-041)
#: are excluded until a follow-up charter raises the bound with
#: extraction-span justification.
CORPUS_MAX_BYTES = 20 * 1024

#: The P1a cohort (IDR-042): repo-relative POSIX paths of the six
#: ratified-baseline documents. FROZEN — GR3-P2-b4fixtures grows the
#: governed allowlist below without moving this constant, because
#: P1b's certified extraction expectations (tests/test_gr3_edges.py)
#: are anchored on exactly these six documents.
CORPUS_REFS = frozenset({
    "AGENTS.md",
    "docs/API.md",
    "docs/ARCHITECTURE.md",
    "docs/STATE.md",
    "docs/idr/IDR-024.md",
    "docs/idr/IDR-028.md",
})

#: The B4 reference cohort (GR3-P2-b4fixtures): the real documents the
#: P1a six DIRECTLY cite, each within CORPUS_MAX_BYTES, entering
#: governance through the same ``CorpusRepository`` boundary as the
#: P1a cohort. Selection rule and per-document reasons:
#: ``docs/gr3-b4/P2-b4fixtures.md`` §Context. Disjoint from
#: ``CORPUS_REFS`` (pinned by ``tests/test_b4_ref_graphs.py``).
CORPUS_B4_COHORT_REFS = frozenset({
    "docs/idr/IDR-018.md",
    "docs/idr/IDR-023.md",
    "docs/idr/IDR-025.md",
    "docs/idr/IDR-026.md",
    "docs/idr/IDR-027.md",
    "docs/idr/IDR-036.md",
})

#: The GOVERNED allowlist: the P1a cohort plus the B4 reference cohort.
#: This union (not ``CORPUS_REFS`` alone) is what admission checks, so
#: the B4 cohort is a first-class governed source while the P1a
#: constant stays byte-identical to its certified value.
GOVERNED_CORPUS_REFS = CORPUS_REFS | CORPUS_B4_COHORT_REFS

#: INSERT_TASK payload keys the template owns (mirrors
#: gateway._TASK_PAYLOAD_KEYS — the payload must remain gateway-valid).
_TASK_PAYLOAD_KEYS = frozenset({
    "task_id", "task_type", "profile", "spec", "inputs", "outputs",
    "dependencies", "provenance", "idempotency_key", "iteration",
    "parent_task_id", "cost_class", "concurrency_group", "max_retries",
})

#: Closed admission-draft keys (EC-F01 style — unknown keys refused).
_ADMISSION_KEYS = frozenset({"corpus_ref", "content_hash", "size_bytes"})


class CorpusDraftError(ValueError):
    """A corpus admission draft or corpus document fails the closed
    contract — fail-closed, nothing derived from it."""


@dataclass(frozen=True)
class CorpusAdmission:
    """A validated corpus admission draft: one closed-set document,
    content-addressed. Bytes travel alongside (never inside) the draft;
    the write path re-derives the hash from the bytes."""

    corpus_ref: str
    content_hash: str
    size_bytes: int


def _require_ref(corpus_ref: Any) -> str:
    if not isinstance(corpus_ref, str) or not corpus_ref:
        raise CorpusDraftError(
            f"corpus_ref must be a non-empty string, "
            f"got {corpus_ref!r}")
    if corpus_ref not in GOVERNED_CORPUS_REFS:
        raise CorpusDraftError(
            f"corpus_ref {corpus_ref!r} is not in the governed corpus "
            f"{sorted(GOVERNED_CORPUS_REFS)} — unlisted documents are "
            f"refused, never silently added")
    return corpus_ref


def _require_hash(content_hash: Any) -> str:
    if not isinstance(content_hash, str) or len(content_hash) != 64:
        raise CorpusDraftError(
            f"content_hash must be a 64-hex sha256 digest, "
            f"got {content_hash!r}")
    try:
        int(content_hash, 16)
    except ValueError:
        raise CorpusDraftError(
            f"content_hash must be hexadecimal, got {content_hash!r}"
        ) from None
    return content_hash


def _require_size(size_bytes: Any) -> int:
    if (not isinstance(size_bytes, int) or isinstance(size_bytes, bool)
            or size_bytes <= 0):
        raise CorpusDraftError(
            f"size_bytes must be a positive int, got {size_bytes!r}")
    if size_bytes > CORPUS_MAX_BYTES:
        raise CorpusDraftError(
            f"size_bytes {size_bytes} exceeds the corpus cap "
            f"{CORPUS_MAX_BYTES} — larger documents need a charter")
    return size_bytes


def corpus_admission_from_mapping(data: Mapping[str, Any]) -> CorpusAdmission:
    """Strictly map an admission draft to a ``CorpusAdmission``.

    Fail-closed on unknown keys (EC-F01 style) — a schema-drift draft is
    a validation error, never a silent field drop.
    """
    if not isinstance(data, Mapping):
        raise TypeError(
            f"corpus admission must be a mapping, got {type(data).__name__}")
    unknown = sorted(set(data) - _ADMISSION_KEYS)
    if unknown:
        raise CorpusDraftError(
            f"corpus admission: unknown keys {unknown} — the admission "
            f"schema is closed")
    return CorpusAdmission(
        corpus_ref=_require_ref(data.get("corpus_ref")),
        content_hash=_require_hash(data.get("content_hash")),
        size_bytes=_require_size(data.get("size_bytes")),
    )


def corpus_task_id(
    corpus_ref: str,
    template_version: str = CORPUS_TEMPLATE_VERSION,
) -> str:
    """Content-addressed CORPUS_ADMIT task id: ``corpus_<sha256>[:24]``.

    Same corpus ref + template version ⇒ same task (PA4 at the task
    level — re-admission of an unchanged document is the same task).
    """
    _require_ref(corpus_ref)
    return "corpus_" + sha256_hex(canonical_json({
        "kind": "corpus_admit_task",
        "corpus_ref": corpus_ref,
        "template_version": template_version,
    }))[:24]


def corpus_idempotency_key(
    corpus_ref: str,
    template_version: str = CORPUS_TEMPLATE_VERSION,
) -> str:
    """The task's idempotency key (sha256 of the admission identity)."""
    _require_ref(corpus_ref)
    return sha256_hex(canonical_json({
        "kind": "corpus_admit",
        "corpus_ref": corpus_ref,
        "template_version": template_version,
    }))


def build_corpus_admit_task_payload(
    corpus_ref: str,
    *,
    dependencies: tuple[str, ...] = (),
    provenance: tuple[str, ...] = (),
    template_version: str = CORPUS_TEMPLATE_VERSION,
) -> dict[str, Any]:
    """The INSERT_TASK payload for a CORPUS_ADMIT task (deterministic).

    An ordinary ``TOOL_TASK`` admitted through the gateway — the task
    graph is the operational authority; nothing is inserted outside
    ``apply_intent``. One task admits exactly one corpus document
    (``spec.corpus_ref``); the write path re-checks the equality.
    """
    _require_ref(corpus_ref)
    payload = {
        "task_id": corpus_task_id(corpus_ref, template_version),
        "task_type": "TOOL_TASK",
        "profile": CORPUS_PROFILE,
        "idempotency_key": corpus_idempotency_key(
            corpus_ref, template_version),
        "iteration": 1,
        "spec": {
            "template": CORPUS_ADMIT_TEMPLATE,
            "template_version": template_version,
            "corpus_ref": corpus_ref,
        },
        "inputs": [],
        "outputs": [],
        "dependencies": list(dependencies),
        "provenance": list(provenance),
        "cost_class": CORPUS_COST_CLASS,
        "concurrency_group": None,
        "max_retries": 3,
        "parent_task_id": None,
    }
    unknown = sorted(set(payload) - _TASK_PAYLOAD_KEYS)
    if unknown:  # pragma: no cover — template/gateway key-set agreement
        raise CorpusDraftError(
            f"corpus task payload keys {unknown} are outside "
            f"gateway._TASK_PAYLOAD_KEYS")
    return payload


def load_corpus_bytes(root: str | Path, corpus_ref: str) -> bytes:
    """Read one corpus document's bytes from an explicit root.

    Closed ref membership first, then traversal defense-in-depth (no
    absolute paths, no ``..`` segments — membership alone already
    excludes them), then the size cap. Raises ``CorpusDraftError`` on
    any violation; ``FileNotFoundError`` propagates only for a listed
    ref missing on disk (a deployment defect, never silent).

    EOL-stable (C1): raw bytes are normalized CRLF -> LF before any
    size/hash check, so the governed identity (size_bytes/content_hash)
    is stable across core.autocrlf checkouts and matches the git
    blob (LF). The 12 governed sources are additionally pinned
    eol=lf in .gitattributes as defense-in-depth.
    """
    _require_ref(corpus_ref)
    pure = PurePosixPath(corpus_ref)
    if pure.is_absolute() or ".." in pure.parts:
        raise CorpusDraftError(
            f"corpus_ref {corpus_ref!r} fails the traversal guard")
    if not isinstance(root, (str, Path)):
        raise TypeError(
            f"corpus root must be a path, got {type(root).__name__}")
    _raw = (Path(root) / Path(*pure.parts)).read_bytes()
    data = _raw.replace(bytes([13, 10]), bytes([10]))
    if len(data) > CORPUS_MAX_BYTES:
        raise CorpusDraftError(
            f"corpus document {corpus_ref!r} is {len(data)} bytes, "
            f"over the cap {CORPUS_MAX_BYTES}")
    if not data:
        raise CorpusDraftError(
            f"corpus document {corpus_ref!r} is empty — nothing to admit")
    return data
