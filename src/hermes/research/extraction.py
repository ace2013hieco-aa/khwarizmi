"""EXTRACT task template + task-output acceptance wiring (IDR-028, v6 §29).

The P7 extraction pipeline that feeds the claim/assumption write path:

- ``build_extract_task_payload`` — the deterministic EXTRACT task template:
  an ordinary ``INSERT_TASK`` payload (``AGENT_TASK``, RESEARCHER/C-tier,
  content-addressed task id + idempotency key from source + scope +
  template version). Admitted through the existing gateway — no new intent
  kind, no new scheduler (IDR-028 Decision 1, §29.2 rule 8).
- ``extraction_draft_from_mapping`` — strict JSON → ``ExtractionDraft``
  mapping (fail-closed on unknown keys, EC-F01 style).
- ``accept_extraction_output`` — the S6 validated-before-acceptance wiring,
  **bound to its producing task** (V6-P7-E03): the ``task_id`` must exist, be
  RUNNING, be an EXTRACT task, and its ``spec.source_ref`` must equal the
  draft's ``source_ref`` — otherwise ``ExtractionNotBoundToTask`` and no
  write. ``validate_extraction`` then decides admissibility (deterministic);
  on ADMITTED it calls ``ClaimAssumptionRepository.record_extraction``; on
  INVALID it raises ``ExtractionOutputRejected`` with the structured reasons
  — a retryable task failure with no partial write (IDR-028 Decision 2).

Journaling is the producing task's existing ``TaskCreated`` /
``TaskStatusChanged`` events + the immutable rows + §14 edges + ``model_ref``
on the rows — no new event type is ever emitted (IDR-028 Decision 3;
IDR-026 Decision 4). Nothing here can promote evidence, pass a gate, or set a
status other than ACTIVE (the write path forces it, V6-P7-F01).
"""
from __future__ import annotations

from typing import Any, Mapping

from hermes.core.task_status import TaskStatus
from hermes.research.claims import (
    CLAIM_SCHEMA_VERSION,
    ExtractionDraft,
    ResearchAssumptionDraft,
    ResearchClaimDraft,
    validate_extraction,
)
from hermes.research.programs import canonical_json, sha256_hex

__all__ = [
    "EXTRACT_COST_CLASS",
    "EXTRACT_PROFILE",
    "EXTRACT_SCOPES",
    "EXTRACT_TEMPLATE",
    "EXTRACT_TEMPLATE_VERSION",
    "ExtractionNotBoundToTask",
    "ExtractionOutputRejected",
    "accept_extraction_output",
    "build_extract_task_payload",
    "extract_idempotency_key",
    "extract_task_id",
    "extraction_draft_from_mapping",
]

# The canonical EXTRACT template marker (spec.template). The gateway matches
# on this — normalized (casefolded + stripped) — so a hand-built payload
# cannot case-spoof its way past the EXTRACT admission checks (V6-P7-E01).
EXTRACT_TEMPLATE = "extract"

EXTRACT_TEMPLATE_VERSION = "1"

# The C-tier extraction scope vocabulary (IDR-028 Decision 1).
EXTRACT_SCOPES = frozenset({"claims", "assumptions", "both"})

# The EXTRACT task's agent profile (M1: C-tier "researcher bookkeeping").
EXTRACT_PROFILE = "RESEARCHER"

# The EXTRACT task's cost class (M1 small-cost bookkeeping; V6-P7-E02).
EXTRACT_COST_CLASS = "small"

# INSERT_TASK payload keys the template owns (mirrors gateway._TASK_PAYLOAD_KEYS).
_TASK_PAYLOAD_KEYS = frozenset({
    "task_id", "task_type", "profile", "spec", "inputs", "outputs",
    "dependencies", "provenance", "idempotency_key", "iteration",
    "parent_task_id", "cost_class", "concurrency_group", "max_retries",
})


class ExtractionOutputRejected(Exception):
    """An EXTRACT task output failed deterministic validation.

    Carries the ``ClaimValidationError`` reasons. This is a retryable task
    failure signal — nothing was written, no partial record exists (S6,
    IDR-028 Decision 2).
    """

    def __init__(self, result) -> None:
        self.result = result
        reasons = [
            f"{e.code}@{e.field_path}: {e.explanation}"
            for e in result.errors
        ]
        super().__init__(
            f"extraction output rejected (verdict={result.verdict.value}): "
            f"{'; '.join(reasons)}"
        )


# ── content-addressed task identity (deterministic, one derivation) ──

def extract_task_id(
    source_ref: str,
    scope: str,
    template_version: str = EXTRACT_TEMPLATE_VERSION,
) -> str:
    """Content-addressed EXTRACT task id: ``extract_<sha256>[:24]``.

    Same source + scope + template version ⇒ same task (PA4 at the task
    level — re-extraction of an unchanged source is the same task).
    """
    return "extract_" + sha256_hex(canonical_json({
        "kind": "extract_task",
        "source_ref": source_ref,
        "scope": scope,
        "template_version": template_version,
    }))[:24]


def extract_idempotency_key(
    source_ref: str,
    scope: str,
    template_version: str = EXTRACT_TEMPLATE_VERSION,
) -> str:
    """The task's idempotency key (sha256 of spec + inputs, PA4)."""
    return sha256_hex(canonical_json({
        "kind": "extract",
        "source_ref": source_ref,
        "scope": scope,
        "template_version": template_version,
    }))


# ── the EXTRACT task template ──

def build_extract_task_payload(
    source_ref: str,
    scope: str = "both",
    *,
    dependencies: tuple[str, ...] = (),
    provenance: tuple[str, ...] = (),
    template_version: str = EXTRACT_TEMPLATE_VERSION,
) -> dict[str, Any]:
    """The INSERT_TASK payload for an EXTRACT task (deterministic template).

    An ordinary ``AGENT_TASK`` admitted through the gateway — the task graph
    is the operational authority; nothing is inserted outside ``apply_intent``.
    """
    if not isinstance(source_ref, str) or ":" not in source_ref:
        raise ValueError(
            f"EXTRACT source_ref must be an 'artifact_type:ref' reference, "
            f"got {source_ref!r}"
        )
    if scope not in EXTRACT_SCOPES:
        raise ValueError(
            f"EXTRACT scope must be one of {sorted(EXTRACT_SCOPES)}, "
            f"got {scope!r}"
        )
    return {
        "task_id": extract_task_id(source_ref, scope, template_version),
        "task_type": "AGENT_TASK",
        "profile": EXTRACT_PROFILE,
        "idempotency_key": extract_idempotency_key(
            source_ref, scope, template_version),
        "iteration": 1,
        "spec": {
            "template": EXTRACT_TEMPLATE,
            "template_version": template_version,
            "source_ref": source_ref,
            "scope": scope,
        },
        "inputs": [],
        "outputs": [],
        "dependencies": list(dependencies),
        "provenance": list(provenance),
        "cost_class": EXTRACT_COST_CLASS,
        "concurrency_group": None,
        "max_retries": 3,
        "parent_task_id": None,
    }


# ── strict JSON → ExtractionDraft (fail-closed, EC-F01 style) ──

_DRAFT_KEYS = frozenset({"source_ref", "claims", "assumptions",
                         "extracted_by", "schema_version"})
_CLAIM_KEYS = frozenset({"ref", "statement", "source_ref", "support_state",
                         "span_ref", "claim_type", "context_tags",
                         "assumption_refs", "related_claims", "supersedes_ref"})
_ASSUMPTION_KEYS = frozenset({"ref", "statement", "context_tags",
                              "supporting_artifact_refs", "supersedes_ref"})


def _check_unknown(mapping: Mapping[str, Any], allowed: frozenset[str],
                   path: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise ValueError(
            f"{path}: unknown keys {unknown} — the extraction schema is closed"
        )


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"expected string or null, got {type(value).__name__}")
    return value


def extraction_draft_from_mapping(data: Mapping[str, Any]) -> ExtractionDraft:
    """Strictly map task-output JSON to an ``ExtractionDraft``.

    Fail-closed on unknown keys (EC-F01 style) — a schema-drift output is a
    validation error, never a silent field drop.
    """
    if not isinstance(data, Mapping):
        raise TypeError(
            f"extraction output must be a mapping, got {type(data).__name__}")
    _check_unknown(data, _DRAFT_KEYS, "extraction")

    claims_raw = data.get("claims", [])
    assumptions_raw = data.get("assumptions", [])
    if not isinstance(claims_raw, list) or not isinstance(assumptions_raw, list):
        raise ValueError("extraction.claims/assumptions must be lists")

    claims: list[ResearchClaimDraft] = []
    for i, raw in enumerate(claims_raw):
        if not isinstance(raw, Mapping):
            raise TypeError(f"extraction.claims[{i}] must be a mapping")
        _check_unknown(raw, _CLAIM_KEYS, f"extraction.claims[{i}]")
        tags = raw.get("context_tags", {})
        if not isinstance(tags, Mapping) or not all(
                isinstance(k, str) and isinstance(v, str)
                for k, v in tags.items()):
            raise ValueError(f"extraction.claims[{i}].context_tags must be "
                             f"a mapping of string → string")
        refs = raw.get("assumption_refs", [])
        if not isinstance(refs, list) or not all(
                isinstance(r, str) for r in refs):
            raise ValueError(f"extraction.claims[{i}].assumption_refs must "
                             f"be a list of strings")
        related = raw.get("related_claims", [])
        if not isinstance(related, list) or not all(
                isinstance(r, str) for r in related):
            raise ValueError(f"extraction.claims[{i}].related_claims must "
                             f"be a list of strings")
        claims.append(ResearchClaimDraft(
            ref=_required_str(raw, "ref", f"extraction.claims[{i}]"),
            statement=_required_str(raw, "statement", f"extraction.claims[{i}]"),
            source_ref=_required_str(raw, "source_ref", f"extraction.claims[{i}]"),
            support_state=_opt_str(raw.get("support_state")),
            span_ref=_opt_str(raw.get("span_ref")),
            claim_type=raw.get("claim_type", ""),
            context_tags=dict(tags),
            assumption_refs=tuple(refs),
            related_claims=tuple(related),
            supersedes_ref=_opt_str(raw.get("supersedes_ref")),
        ))

    assumptions: list[ResearchAssumptionDraft] = []
    for i, raw in enumerate(assumptions_raw):
        if not isinstance(raw, Mapping):
            raise TypeError(f"extraction.assumptions[{i}] must be a mapping")
        _check_unknown(raw, _ASSUMPTION_KEYS, f"extraction.assumptions[{i}]")
        tags = raw.get("context_tags", {})
        if not isinstance(tags, Mapping) or not all(
                isinstance(k, str) and isinstance(v, str)
                for k, v in tags.items()):
            raise ValueError(f"extraction.assumptions[{i}].context_tags must "
                             f"be a mapping of string → string")
        refs = raw.get("supporting_artifact_refs", [])
        if not isinstance(refs, list) or not all(
                isinstance(r, str) for r in refs):
            raise ValueError(f"extraction.assumptions[{i}].supporting_artifact_"
                             f"refs must be a list of strings")
        assumptions.append(ResearchAssumptionDraft(
            ref=_required_str(raw, "ref", f"extraction.assumptions[{i}]"),
            statement=_required_str(raw, "statement", f"extraction.assumptions[{i}]"),
            context_tags=dict(tags),
            supporting_artifact_refs=tuple(refs),
            supersedes_ref=_opt_str(raw.get("supersedes_ref")),
        ))

    return ExtractionDraft(
        source_ref=_required_str(data, "source_ref", "extraction"),
        claims=tuple(claims),
        assumptions=tuple(assumptions),
        extracted_by=data.get("extracted_by", ""),
        schema_version=data.get("schema_version", CLAIM_SCHEMA_VERSION),
    )


def _required_str(mapping: Mapping[str, Any], key: str, path: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path}.{key} must be a non-empty string")
    return value


# ── the acceptance wiring (S6 validated-before-acceptance) ──


class ExtractionNotBoundToTask(Exception):
    """An extraction output was refused because it is not the output of the
    producing EXTRACT task it claims to be (V6-P7-E03).

    Raised when the producing ``task_id`` is missing, is not an EXTRACT task,
    is not RUNNING, or its ``spec.source_ref`` does not match the draft's
    ``source_ref``. Nothing is written — acceptance is an operation *of* a
    task, so a binding failure is a hard refusal before any row exists.
    """


def _is_extract_spec(spec: Any) -> bool:
    """True iff ``spec`` carries the canonical EXTRACT template marker."""
    if not isinstance(spec, dict):
        return False
    template = spec.get("template")
    return isinstance(template, str) and (
        template.strip().casefold() == EXTRACT_TEMPLATE)


def accept_extraction_output(
    conn: Any,
    project_id: str,
    task_id: str,
    draft: ExtractionDraft,
    *,
    extracted_by: str,
    reason: str = "",
    claim_repo: Any = None,
    span_resolver: Any = None,
    context_resolver: Any = None,
    text_resolver: Any = None,
    experiment_resolver: Any = None,
) -> dict:
    """Accept an EXTRACT task's output, bound to its producing task.

    V6-P7-E03: acceptance is an operation *of* a task. The producing
    ``task_id`` must exist, be RUNNING (non-terminal), be an EXTRACT task, and
    its ``spec.source_ref`` must equal the draft's ``source_ref`` — the
    artifact the task extracted is the artifact the output describes. Any
    binding failure raises ``ExtractionNotBoundToTask`` with no write.

    Then ``validate_extraction`` decides admissibility; on ADMITTED the
    result is persisted through ``ClaimAssumptionRepository.record_extraction``;
    on INVALID, ``ExtractionOutputRejected`` is raised with the structured
    reasons — a retryable task failure, and no partial write exists (S6,
    IDR-028 Decision 2). Returns ``record_extraction``'s outcome dict.

    ``span_resolver`` (HR-05) is an optional ``(source_ref, span_ref) -> bool``
    callable threaded into ``validate_extraction``: the caller that holds the
    artifact store (the controller) supplies it so a fabricated ``span_ref``
    pointing at a nonexistent section of a text-bearing source is rejected
    deterministically. When None, span_ref is form-checked only.
    """
    from hermes.persistence.repositories import (
        ClaimAssumptionRepository,
        NotFoundError,
        TaskRepository,
    )

    task_repo = TaskRepository(conn)
    try:
        task = task_repo.get(task_id)
    except NotFoundError:
        raise ExtractionNotBoundToTask(
            f"extraction output refused: producing task {task_id!r} does not "
            f"exist (V6-P7-E03) — acceptance is bound to a real task"
        ) from None
    if task["project_id"] != project_id:
        raise ExtractionNotBoundToTask(
            f"extraction output refused: producing task {task_id!r} belongs "
            f"to project {task['project_id']!r}, not {project_id!r}"
        )
    if not _is_extract_spec(task.get("spec")):
        raise ExtractionNotBoundToTask(
            f"extraction output refused: task {task_id!r} is not an EXTRACT "
            f"task (spec.template != {EXTRACT_TEMPLATE!r})"
        )
    status = task_repo.get_status(task_id)
    if status is not TaskStatus.RUNNING:
        raise ExtractionNotBoundToTask(
            f"extraction output refused: producing task {task_id!r} is "
            f"{status.value}, not RUNNING — an output may only be accepted "
            f"from a task currently executing"
        )
    task_source = (task.get("spec") or {}).get("source_ref")
    if task_source != draft.source_ref:
        raise ExtractionNotBoundToTask(
            f"extraction output refused: draft.source_ref {draft.source_ref!r} "
            f"does not match the producing task's spec.source_ref "
            f"{task_source!r} — the output describes a different source than "
            f"the task extracted (V6-P7-E03)"
        )

    result = validate_extraction(
        draft,
        span_resolver=span_resolver,
        context_resolver=context_resolver,
        text_resolver=text_resolver,
        experiment_resolver=experiment_resolver,
    )
    if not result.admitted:
        raise ExtractionOutputRejected(result)

    claim_repo = claim_repo or ClaimAssumptionRepository(conn)
    return claim_repo.record_extraction(
        project_id, result,
        producing_task_id=task_id,
        extracted_by=extracted_by,
        reason=reason or f"extract task {task_id} output",
    )
