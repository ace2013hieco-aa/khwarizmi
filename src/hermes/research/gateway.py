"""Intent Gateway ``apply_intent`` (v3 §8, P3) — the single authoritative mutation path.

v6 §28.5 P3 slice: ``PROPOSE_RESEARCH_PROGRAM`` gateway wiring (per-kind
validator → ``compile_from_payload`` → ``ResearchProgramCompiled``) and
ordinary ``INSERT_TASK`` admission — the Program → task-graph instantiation
path (AC-05/10/12; walking skeleton). ``ADMIT_TASK`` (internal-only) is wired
with DETERMINISTIC-only enforcement; the plan-admission scheduler
(``Controller._plan_admission_pass``, IDR-045 D1) is the P3-general-runtime
proposer.

Closure-gate remediation (V6-FINAL-01/02): every repository-level constraint
failure on task admission is surfaced as a structured ``GatewayRejection``
code — never a raw ``sqlite3.IntegrityError`` (FK on a missing dependency →
``DEPENDENCY``; ``UNIQUE(idempotency_key, attempt)`` reused by a different
task → ``IDEMPOTENCY_CONFLICT``; other integrity violations →
``MALFORMED_PAYLOAD``). Provenance contract: ``provenance_json`` is
non-authoritative metadata in P3 (the ``provenance_edges`` table is the
future lineage mechanism), but the reserved ``research_program:<id>`` prefix
must dereference to a program governed by the intent's project at admission
(``PROVENANCE`` rejection otherwise) — requirement-level annotations
(``evidence_requirement:``/``hypothesis:``/``scope_brief:``) remain derived
context refs, truthful by construction for plan tasks, dereferenced by the
future lineage layer.

Authority model (v6 §28.2 Model D + v4 §8):

  Director      = bounded judgment / proposal      (never writes directly)
  validator     = epistemic derivation authority   (compile_from_payload)
  repository    = governance + identity/integrity authority (R-02, EC-V6-11..16)
  gateway       = admission authority: role, schema, budget, idempotency
  task graph    = operational authority (nodes appear only via INSERT_TASK)

Every admission emits an audit event (``IntentApplied`` / ``IntentRejected``)
on top of the mutation's own event (``ResearchProgramCompiled`` /
``TaskCreated``). The mutation + its own event are atomic inside the
repository (IDR-013); the audit event is appended by the gateway in its own
transaction — it is a record of the admission, never a gate on it.

Budget enforcement is a deferred subsystem (no budget ledger exists in this
tree): ``apply_intent`` accepts a ``budget_check`` hook that the future budget
slices plug in here; the default is a documented no-op.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from hermes.core.events import EventType
from hermes.core.intents import (
    CHARTER_VERSION_MAX_LENGTH,
    MODEL_REF_MAX_LENGTH,
    ORIGIN_KIND_MAX_LENGTH,
    ORIGIN_REF_MAX_LENGTH,
    PROMPT_TEMPLATE_VERSION_MAX_LENGTH,
    RUN_ID_MAX_LENGTH,
    Intent,
    IntentKind,
    IntentRejectedError,
)
from hermes.core.node import AgentProfile, NodeContract, NodeType
from hermes.core.program_refs import (
    canonical_program_scope,
    program_ref_key,
)
from hermes.core.task_status import TaskStatus
from hermes.persistence.event_validation import EventValidationError, validate_event
from hermes.persistence.repositories import (
    ArtifactRepository,
    AuditRecord,
    DatasetManifestRepository,
    DependencyError,
    EventRepository,
    NotFoundError,
    ProjectRepository,
    ResearchProgramRepository,
    TaskRepository,
    _append_event_to_db,
)
from hermes.persistence.source_outcomes import (
    _source_artifact_resolves,
    source_artifact_is_web_derived,
    source_artifact_retracted,
)
from hermes.research import verification
from hermes.research.extraction import (
    EXTRACT_COST_CLASS,
    EXTRACT_PROFILE,
    EXTRACT_SCOPES,
    EXTRACT_TEMPLATE,
)
from hermes.research.l2_resolution import _l2_resolve_upstream
from hermes.research.programs import (
    RESEARCH_PROGRAM_PAYLOAD_KEYS,
    CompilationStatus,
    compile_from_payload,
)
from hermes.research.source_templates import (
    SOURCE_COST_CLASS,
    SOURCE_FETCH_TEMPLATE,
    SOURCE_MAX_PAGES_CAP,
    SOURCE_MAX_SOURCES_CAP,
    SOURCE_PAGE_SIZE_CAP,
    SOURCE_PROFILE,
    SOURCE_SEARCH_TEMPLATE,
    SOURCE_SIZE_CAP_BYTES_CAP,
    _check_retry_policy,
)
from hermes.tools.research_sources import SOURCE_PROVIDER_ALLOWLIST

__all__ = [
    "INTENT_PAYLOAD_KEYS",
    "WIRED_INTENT_KINDS",
    "GatewayRejection",
    "IntentResult",
    "apply_intent",
]

# ── rejection codes (structured, stable for tests/audit) ──
ROLE = "ROLE"                       # proposed_by not permitted for this kind
UNKNOWN_KIND = "UNKNOWN_KIND"       # kind not in the vocabulary
NOT_WIRED = "NOT_WIRED"             # declared kind, gateway not yet wired
PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"  # stale / missing project
MALFORMED_PAYLOAD = "MALFORMED_PAYLOAD"  # schema violation or unknown key
SCOPE_NOT_GOVERNED = "SCOPE_NOT_GOVERNED"  # brief missing / non-resolvable
NOT_COMPILED = "NOT_COMPILED"       # program failed validation (gate violation)
STALE = "STALE"                     # supersession/chain-head violation
BUDGET = "BUDGET"                   # budget_check hook rejected
DEPENDENCY = "DEPENDENCY"           # task dependency violation (cycle or missing dep)
IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"  # identity collision: a task_id/idempotency_key claimed by a different command (content or project)
PROVENANCE = "PROVENANCE"           # reserved provenance ref does not dereference
CLASSIFICATION_REF = "CLASSIFICATION_REF"  # classification ref / action / candidate does not validate
PROPOSAL = "PROPOSAL"               # proposal not found / not pending / already decided differently
EVIDENCE_REF = "EVIDENCE_REF"       # evidence artifact ref does not dereference in-project
OPERATOR = "OPERATOR"               # operator credential is not ratified (A4)
CONTRADICTION_BACKLOG = "CONTRADICTION_BACKLOG"  # project OPEN-contradiction
#                                     ceiling reached (EXT-6/R4); a net-new
#                                     contradiction admission is refused
#                                     fail-closed until the backlog is triaged
#                                     (resolution — the only drain — stays open)

#: The kinds ``apply_intent`` can actually apply — the set the contract's
#: availability note is rendered from (OPS-12). Read-only: a kind outside this
#: set is refused ``NOT_WIRED`` by the dispatch below, and the authority
#: (``ProfileSpec.authority.proposable_kinds``) is never changed by this list.
WIRED_INTENT_KINDS: frozenset[IntentKind] = frozenset({
    IntentKind.REQUEST_ADDITIONAL_EXPERIMENT,
    IntentKind.RECORD_VERIFICATION_OUTCOME,
    IntentKind.PROPOSE_RESEARCH_PROGRAM,
    IntentKind.PROPOSE_CLASSIFICATION_ACTION,
    IntentKind.RESOLVE_CLASSIFICATION_PROPOSAL,
    IntentKind.RECORD_SCOPE_REVIEW_DECISION,
    IntentKind.RETRACT_SOURCE,
    IntentKind.CURATE_KNOWLEDGE,
    IntentKind.RECORD_CONTRADICTION,
    IntentKind.CONTRADICTION_RESOLUTION,
    IntentKind.RECORD_CLASSIFICATION,
    IntentKind.EMIT_PARALLEL_REGIME_PROGRAM,
    IntentKind.REVOKE_OPERATOR_CREDENTIAL,
    IntentKind.ROTATE_OPERATOR_CREDENTIAL,
    IntentKind.EVIDENCE_TRANSITION,
    IntentKind.INSERT_TASK,
    IntentKind.ADMIT_TASK,
})

# IDR-045 C5 — provenance field bounds, single source of truth. Enforced
# pre-write by ``_require_provenance_bounds`` (called from ``apply_intent``
# before any validator dispatches) and again fail-closed at construction in
# ``Intent.__post_init__``.
_PROVENANCE_FIELD_LIMITS: tuple[tuple[str, int], ...] = (
    ("origin_kind", ORIGIN_KIND_MAX_LENGTH),
    ("origin_ref", ORIGIN_REF_MAX_LENGTH),
    ("model_ref", MODEL_REF_MAX_LENGTH),
    ("run_id", RUN_ID_MAX_LENGTH),
    ("prompt_template_version", PROMPT_TEMPLATE_VERSION_MAX_LENGTH),
    ("charter_version", CHARTER_VERSION_MAX_LENGTH),
)

# Closed payload schema for INSERT_TASK / ADMIT_TASK (EC-F01 style: unknown
# keys are rejected, never silently dropped).
_TASK_PAYLOAD_KEYS = frozenset({
    "task_id", "task_type", "profile", "spec", "inputs", "outputs",
    "dependencies", "provenance", "idempotency_key", "iteration",
    "parent_task_id", "cost_class", "concurrency_group", "max_retries",
})

INTENT_PAYLOAD_MAX_DEPTH = 16
INTENT_PAYLOAD_MAX_CONTAINERS = 4096


class GatewayRejection(IntentRejectedError):
    """Structured gateway rejection: kind + stable code + reason.

    Subclasses ``IntentRejectedError`` so existing callers that catch the
    base rejection keep working; ``code`` is the stable machine-readable
    category (one of the module-level constants).
    """

    def __init__(self, kind: IntentKind, code: str, reason: str):
        self.code = code
        super().__init__(kind, reason)


@dataclass(frozen=True, slots=True)
class IntentResult:
    """The outcome of an applied intent.

    ``entity_type`` is ``"research_program"``, ``"task"`` or
    ``"verification_round"``; ``entity_id`` is the program_id / task_id / round
    id; ``duplicate`` is True when the admission was idempotent (existing row
    returned, no new event); ``row`` is the repository row (the round's journal
    record, for OPS-5Z Group E); ``event_type`` names the mutation's own event.
    """

    kind: IntentKind
    entity_type: str
    entity_id: str
    duplicate: bool
    row: dict
    event_type: str


def _require_provenance_bounds(intent: Intent) -> None:
    """IDR-045 C5 — refuse invalid provenance fields **before any write**.

    Called from ``apply_intent`` before the per-kind validator dispatches, so an
    invalid ``origin_*``/``model_ref``/``run_id``/``prompt_template_version``/
    ``charter_version`` field refuses with ``MALFORMED_PAYLOAD`` having written
    **zero** rows, and the refusal is journalled as ``IntentRejected`` by the
    caller's own audit path.

    MERGE-AUDIT-045 F2: this check previously lived in ``_append_audit_event``,
    which runs at ``apply_intent`` *after* ``_validate_insert_task`` has already
    committed its row. That produced a durable mutation with no
    ``IntentApplied`` and no ``IntentRejected`` row, reported to the caller as a
    refusal. Pre-write is the only position that satisfies the AGENTS.md rule
    "oversized verdicts refuse with RATIONALE before any write".

    MERGE-AUDIT-045-FIX C1/C2/C3: the check is **type-then-length**, and the
    type test must stay first. It was length-only, so a value inside its bound
    but not a ``str`` passed here and still reached the post-commit audit
    append, reproducing the F2 signature (durable row, no ``IntentApplied``, a
    bare ``TypeError`` to the caller instead of a refusal):

    - a non-serialisable object with ``__len__`` -> ``TypeError`` from
      ``json.dumps`` *after* the commit;
    - a ``dict``/``list`` -> applied unvalidated into the journal payload;
    - a non-sized object -> ``TypeError`` from ``len()``, escaping the
      documented ``except GatewayRejection`` contract of this path.

    Testing ``isinstance`` before ``len()`` closes all three: no non-``str`` can
    reach ``len()`` (so no bare ``TypeError``) and none can reach the payload
    builder (so no post-commit failure). Mirrors ``Intent.__post_init__``,
    which enforces the same two rules at construction; this is the
    gateway-boundary enforcement for callers that reach ``apply_intent`` without
    going through the dataclass constructor.
    """
    for name, limit in _PROVENANCE_FIELD_LIMITS:
        value = getattr(intent, name)
        if value is None:
            continue
        if not isinstance(value, str):
            raise _reject(
                intent.kind,
                MALFORMED_PAYLOAD,
                f"{name} must be a string, got {type(value).__name__}",
            )
        if len(value) > limit:
            raise _reject(
                intent.kind,
                MALFORMED_PAYLOAD,
                f"{name} exceeds max length {limit}: {len(value)}",
            )


def _require_payload_bounds(intent: Intent) -> None:
    """GAP-1 P2-10 — refuse an over-nested or over-wide payload pre-write.

    Applied gateway-wide before any validator dispatches (and before the
    caller-supplied budget/governance hooks), so every wired kind sees the
    same ``MALFORMED_PAYLOAD`` refusal with zero durable state written. The
    root payload is depth 1 and every dict/list/tuple node counts toward the
    container bound; a reference cycle is a refusal too (it is not a shape
    any admitted intent can carry, and it would otherwise defeat the walk).
    """
    containers = 0
    active: set[int] = set()

    def _walk(value: object, depth: int) -> str | None:
        nonlocal containers
        if not isinstance(value, (dict, list, tuple)):
            return None
        if depth > INTENT_PAYLOAD_MAX_DEPTH:
            return (f"payload nesting depth {depth} exceeds "
                    f"{INTENT_PAYLOAD_MAX_DEPTH}")
        marker = id(value)
        if marker in active:
            return "payload contains a reference cycle"
        active.add(marker)
        containers += 1
        if containers > INTENT_PAYLOAD_MAX_CONTAINERS:
            return (f"payload container count exceeds "
                    f"{INTENT_PAYLOAD_MAX_CONTAINERS}")
        try:
            items = value.values() if isinstance(value, dict) else value
            for item in items:
                violation = _walk(item, depth + 1)
                if violation is not None:
                    return violation
        finally:
            active.discard(marker)
        return None

    violation = _walk(intent.payload, 1)
    if violation is not None:
        raise _reject(intent.kind, MALFORMED_PAYLOAD, violation)


def _require_role(intent: Intent) -> None:
    """Enforce the actor/permission rules for ``intent.kind``.

    - the proposer must be a known ``AgentProfile``;
    - ``director_only`` kinds admit only ``DIRECTOR``;
    - ``internal_only`` kinds admit only ``DETERMINISTIC`` (controller);
    - LLM-proposable kinds admit any of the four agent profiles
      (DIRECTOR/RESEARCHER/IMPLEMENTER/ADVERSARY) — never DETERMINISTIC.
      Admission is positive: an LLM profile is admitted only for a kind
      in ``llm_proposable`` (ROLE-EXH-1) — a kind in none of the three
      partitions is refused for every profile, never silently admitted.
    """
    try:
        role = AgentProfile(intent.proposed_by)
    except ValueError:
        raise GatewayRejection(
            intent.kind, ROLE,
            f"proposed_by {intent.proposed_by!r} is not a known agent profile "
            f"({[p.value for p in AgentProfile]})",
        ) from None
    if intent.kind in IntentKind.director_only():
        if role is not AgentProfile.DIRECTOR:
            raise GatewayRejection(
                intent.kind, ROLE,
                f"{intent.kind.value} is Director-only (IDR-018) — "
                f"{role.value} may not propose it",
            )
        return
    if intent.kind in IntentKind.internal_only():
        if role is not AgentProfile.DETERMINISTIC:
            raise GatewayRejection(
                intent.kind, ROLE,
                f"{intent.kind.value} is internal-only (v4 §8) — only the "
                f"DETERMINISTIC controller may propose it, not {role.value}",
            )
        return
    if role is AgentProfile.DETERMINISTIC:
        raise GatewayRejection(
            intent.kind, ROLE,
            f"DETERMINISTIC may only propose internal-only kinds, not "
            f"{intent.kind.value}",
        )
    if intent.kind not in IntentKind.llm_proposable():
        raise GatewayRejection(
            intent.kind, ROLE,
            f"{intent.kind.value} is not LLM-proposable — no agent profile "
            f"may propose it",
        )


def _require_project(
    intent: Intent, project_repo: ProjectRepository,
) -> None:
    """Reject intents targeting a missing project (stale project check)."""
    try:
        project_repo.get(intent.project_id)
    except NotFoundError:
        raise GatewayRejection(
            intent.kind, PROJECT_NOT_FOUND,
            f"project {intent.project_id!r} does not exist — stale project "
            f"reference",
        ) from None


def _reject(kind: IntentKind, code: str, reason: str) -> GatewayRejection:
    return GatewayRejection(kind, code, reason)


#: The bound on a rejected value quoted in a refusal detail (OPS-5K). A
#: gateway refusal must show the operator what the model actually wrote, but
#: the detail also rides the runtime's INTENT_REFUSED event, so the value is
#: quoted and bounded — never dumped whole.
_MAX_REJECTED_VALUE_CHARS = 120


def _bounded_rejected(value: object) -> str:
    """A bounded ``repr`` of a rejected value, for a refusal detail (OPS-5K)."""
    text = repr(value)
    if len(text) <= _MAX_REJECTED_VALUE_CHARS:
        return text
    return text[:_MAX_REJECTED_VALUE_CHARS] + f"... ({len(text)} chars)"


# ── per-kind validators ──

def _validate_propose_research_program(
    conn: Any,
    intent: Intent,
    *,
    program_repo: ResearchProgramRepository,
    clock: Callable[[], str],
    audit: AuditRecord | None = None,
) -> IntentResult:
    """PROPOSE_RESEARCH_PROGRAM: draft payload → compile → record → event.

    Flow: payload schema → governance (frozen brief resolved by the
    repository, R-02) → ``compile_from_payload`` (deterministic verdict;
    NOT_COMPILED is a gate violation and is rejected, never persisted) →
    ``record`` (identity/obligation integrity EC-V6-11..16, idempotent).
    """
    payload = intent.payload
    if not isinstance(payload, dict):
        raise _reject(intent.kind, MALFORMED_PAYLOAD,
                      f"payload must be a dict, got {type(payload).__name__}")
    scope_ref = payload.get("scope_ref")
    if not isinstance(scope_ref, str) or not scope_ref:
        raise _reject(intent.kind, MALFORMED_PAYLOAD,
                      "payload.scope_ref must be a non-empty string")

    # Governance: the frozen brief is resolved here, never trusted from the
    # caller (R-02). A missing brief is SCOPE_NOT_GOVERNED.
    try:
        scope_content_hash = program_repo.resolve_scope_content_hash(
            intent.project_id, scope_ref)
    except Exception as exc:
        raise _reject(intent.kind, SCOPE_NOT_GOVERNED,
                      f"scope brief {scope_ref!r} not governed for project "
                      f"{intent.project_id!r}: {exc}") from exc

    # Supersession context: only the project's current chain head qualifies
    # (E9). A stale/foreign supersede target is STALE.
    try:
        superseded = program_repo.superseded_program_ids(
            intent.project_id, payload.get("supersedes_ref"))
    except Exception as exc:
        raise _reject(intent.kind, STALE, f"supersession rejected: {exc}") from exc

    # C1 (design gate §4.5/§5.3): the project's append-only slot vocabulary
    # — a read-only projection over the project's program rows, consumed by
    # E6. Fail-closed (AC-7): a corrupt/unresolvable row refuses the whole
    # admission (reject, never crash) — a shrunken vocabulary would let E6
    # mis-admit or mis-reject a slot.
    try:
        slot_vocabulary = program_repo.slot_vocabulary(intent.project_id)
    except Exception as exc:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"slot vocabulary unresolvable for project "
            f"{intent.project_id!r}: {exc}") from exc

    # AC-5 (IDR-041): the ratified rationale-evidence contract — an
    # optional ratification_ref must be an APPROVED
    # PROPOSE_MECHANISM_SUBSTITUTION proposal whose action is in the
    # classification's permitted set (recomputed, F2). Rationale evidence
    # only: the compile checks below are unchanged and still refuse a
    # program whose own evidence does not dereference.
    ratification_ref = payload.get("ratification_ref")
    if ratification_ref is not None:
        if not isinstance(ratification_ref, str) or not ratification_ref:
            raise _reject(
                intent.kind, MALFORMED_PAYLOAD,
                "payload.ratification_ref must be a non-empty string "
                "or absent")
        from hermes.research.failure_classification import PermittedAction
        if _resolve_ratified_proposal(
                conn, intent.project_id, ratification_ref,
                frozenset({PermittedAction.PROPOSE_MECHANISM_SUBSTITUTION})
        ) is None:
            raise _reject(
                intent.kind, PROPOSAL,
                f"ratification_ref {ratification_ref!r} is not an APPROVED "
                f"PROPOSE_MECHANISM_SUBSTITUTION proposal whose action is "
                f"in the classification's permitted set")

    # ADR-041 (triggering_classification_id): gateway-only — resolves an
    # ADMITTED FailureClassification that authorizes a parallel-regime-test
    # program. The classification_id is the bare artifact id (fc_<hash>),
    # NOT a prefixed ref. Mirrors ratification_ref: present in the payload
    # (via RESEARCH_PROGRAM_PAYLOAD_KEYS so it isn't rejected as extraneous), resolved
    # and validated at the gateway, absent from the draft/compiler entirely.
    triggering_classification_id = payload.get("triggering_classification_id")
    if triggering_classification_id is not None:
        if (not isinstance(triggering_classification_id, str)
                or not triggering_classification_id):
            raise _reject(
                intent.kind, MALFORMED_PAYLOAD,
                "payload.triggering_classification_id must be a non-empty "
                "string or absent")
        from hermes.persistence.failure_classifications import (
            FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
        )
        from hermes.research.failure_classification import (
            PermittedAction,
        )
        # Resolve the classification artifact (project-scoped by content hash).
        cls_row = conn.execute(
            "SELECT artifact_id, metadata_json FROM artifacts "
            "WHERE project_id = ? AND artifact_type = ? "
            "AND artifact_id = ?",
            (intent.project_id, FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
             triggering_classification_id)).fetchone()
        if cls_row is None:
            raise _reject(
                intent.kind, CLASSIFICATION_REF,
                f"triggering_classification_id "
                f"{triggering_classification_id!r} does not resolve to an "
                f"ADMITTED failure_classification in project "
                f"{intent.project_id!r}")
        try:
            import json as _json
            cls_meta = _json.loads(cls_row["metadata_json"] or "{}")
        except ValueError:
            raise _reject(
                intent.kind, CLASSIFICATION_REF,
                f"triggering classification "
                f"{triggering_classification_id!r} has corrupt metadata") from None
        if not isinstance(cls_meta, dict):
            raise _reject(
                intent.kind, CLASSIFICATION_REF,
                f"triggering classification "
                f"{triggering_classification_id!r} metadata is not a mapping")
        # The classification must be ADMITTED and must permit the action.
        if cls_meta.get("status") != "ADMITTED":
            raise _reject(
                intent.kind, CLASSIFICATION_REF,
                f"triggering classification "
                f"{triggering_classification_id!r} is not ADMITTED "
                f"(status={cls_meta.get('status')!r})")
        cls_permitted = cls_meta.get("permitted_actions", [])
        if (not isinstance(cls_permitted, list)
                or PermittedAction.PROPOSE_PARALLEL_REGIME_TEST.value
                not in cls_permitted):
            raise _reject(
                intent.kind, CLASSIFICATION_REF,
                f"triggering classification "
                f"{triggering_classification_id!r} does not permit "
                f"PROPOSE_PARALLEL_REGIME_TEST")
        # Load-bearing binding: the classification's own program_ref and
        # hypothesis_ref must match the payload's parent_program_id and
        # parent_hypothesis_ref. Without this, someone could cite a valid
        # classification to authorize linking to an unrelated program/hypothesis.
        parent_program_id = payload.get("parent_program_id")
        parent_hypothesis_ref = payload.get("parent_hypothesis_ref")
        if parent_program_id is None or parent_hypothesis_ref is None:
            raise _reject(
                intent.kind, MALFORMED_PAYLOAD,
                "payload.parent_program_id and parent_hypothesis_ref are "
                "required when triggering_classification_id is present")
        # The classification stores program_ref as either a bare program_id
        # or a 'research_program:<id>' ref (canonical comparison).
        # _canonical_or_none is defined in this module (used by CURATE_KNOWLEDGE).
        cls_program_ref = cls_meta.get("program_ref")
        cls_program_id = program_ref_key(cls_program_ref) or ""
        if _canonical_or_none(cls_program_id) != _canonical_or_none(
                parent_program_id):
            raise _reject(
                intent.kind, CLASSIFICATION_REF,
                f"triggering classification "
                f"{triggering_classification_id!r} targets program "
                f"{cls_program_ref!r}, not payload.parent_program_id "
                f"{parent_program_id!r} — classification-program binding "
                f"mismatch")
        if _canonical_or_none(cls_meta.get("hypothesis_ref")) != (
                _canonical_or_none(parent_hypothesis_ref)):
            raise _reject(
                intent.kind, CLASSIFICATION_REF,
                f"triggering classification "
                f"{triggering_classification_id!r} targets hypothesis "
                f"{cls_meta.get('hypothesis_ref')!r}, not "
                f"payload.parent_hypothesis_ref {parent_hypothesis_ref!r} "
                f"— classification-hypothesis binding mismatch")

    # Resolve known_program_ids and known_hypothesis_refs from the repository
    # (R-02 pattern), passing them into compile_from_payload so the compiler
    # can validate parent_program_id / parent_hypothesis_ref.
    try:
        known_program_ids = program_repo.known_program_ids(intent.project_id)
        known_hypothesis_refs = program_repo.known_hypothesis_refs(
            intent.project_id)
    except Exception as exc:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"parallel-regime-test context unresolvable for project "
            f"{intent.project_id!r}: {exc}") from exc

    result = compile_from_payload(
        payload,
        project_id=intent.project_id,
        scope_content_hash=scope_content_hash,
        superseded_program_ids=superseded,
        known_program_ids=known_program_ids,
        known_hypothesis_refs=known_hypothesis_refs,
        slot_vocabulary=slot_vocabulary,
    )
    if result.status is not CompilationStatus.COMPILED or result.program is None:
        first = result.errors[0] if result.errors else None
        detail = f"{first.code}: {first.explanation}" if first else result.status.value
        raise _reject(
            intent.kind, NOT_COMPILED,
            f"program validation failed ({result.status.value}) — {detail}; "
            f"compilation never equals approval (v6 §14) and nothing was "
            f"persisted",
        )

    program = result.program
    # Idempotency (PA4): a duplicate genuine compilation returns the existing
    # row and emits no new event (record() enforces this too; we detect it
    # here so IntentResult.duplicate is truthful).
    existing = program_repo.get_by_hash(program.content_hash)
    reason = intent.justification
    if ratification_ref is not None:
        # the ratification is recorded as rationale evidence on the row
        reason = f"{reason} (ratification_ref={ratification_ref})"
    # C1 (AC-5): the E6-validated new-slot declarations ride into the
    # admission event payload — vocabulary-growth provenance, never part of
    # the program's canonical content. record() emits them only on a
    # genuine (non-duplicate) admission.
    row = program_repo.record(
        intent.project_id, result,
        produced_by=intent.proposed_by, reason=reason,
        new_slot_declarations=payload.get("new_slot_declarations") or (),
        # AUDIT-TXN A1.2: hand the record only when the PRE-READ said "new".
        # record() appends it on whichever branch it lands (new write or an
        # in-transaction duplicate), so exactly one side appends even if the
        # row appears between this read and the transaction.
        audit=audit if existing is None else None,
    )
    return IntentResult(
        kind=intent.kind,
        entity_type="research_program",
        entity_id=program.program_id,
        duplicate=existing is not None,
        row=row,
        event_type=EventType.RESEARCH_PROGRAM_COMPILED.value,
    )


# ADR-041 B3: closed payload schema for EMIT_PARALLEL_REGIME_PROGRAM — the
# deterministic controller sends ONLY linkage fields; the gateway clones the
# substance from the parent program and validates the triggering classification.
# No substance fields are accepted on the intent — they are never trusted from
# the proposer, only derived from the parent program at the gateway.
_EMIT_PARALLEL_REGIME_PROGRAM_PAYLOAD_KEYS = frozenset({
    "parent_program_id", "parent_hypothesis_ref", "target_regime",
    "triggering_classification_id",
})


def _validate_emit_parallel_regime_program(
    conn: Any,
    intent: Intent,
    *,
    program_repo: ResearchProgramRepository,
    clock: Callable[[], str],
    audit: AuditRecord | None = None,
) -> IntentResult:
    """EMIT_PARALLEL_REGIME_PROGRAM: the deterministic controller's internal
    intent for ADR-041 AC-7 (parallel-regime-test program emission).

    Flow: closed-schema payload → triggering_classification_id guard (4-check,
    same codes as B2) → resolve parent program in-project → clone substance
    (scope_ref, epistemic_objective, hypotheses, predictions,
    discrimination_requirements, methodology_constraints) → compile_from_payload
    with gateway-resolved known_* sets → record (produced_by='DETERMINISTIC') →
    IntentResult with truthful duplicate from PA4.

    Authority: DETERMINISTIC-origin trail is preserved end-to-end — the intent
    carries proposed_by='DETERMINISTIC', record() is called with
    produced_by='DETERMINISTIC', and the audit event (IntentApplied) is
    attributed to DETERMINISTIC. No authorship re-attribution occurs.
    """
    payload = intent.payload
    if not isinstance(payload, dict):
        raise _reject(intent.kind, MALFORMED_PAYLOAD,
                      f"payload must be a dict, got {type(payload).__name__}")
    unknown = sorted(set(payload) - _EMIT_PARALLEL_REGIME_PROGRAM_PAYLOAD_KEYS)
    if unknown:
        raise _reject(intent.kind, MALFORMED_PAYLOAD,
                      f"unknown payload keys {unknown} for "
                      f"EMIT_PARALLEL_REGIME_PROGRAM")

    # ── 1. Validate the linkage fields. ──
    parent_program_id = payload.get("parent_program_id")
    if not isinstance(parent_program_id, str) or not parent_program_id:
        raise _reject(intent.kind, MALFORMED_PAYLOAD,
                      "payload.parent_program_id must be a non-empty string")
    parent_hypothesis_ref = payload.get("parent_hypothesis_ref")
    if not isinstance(parent_hypothesis_ref, str) or not parent_hypothesis_ref:
        raise _reject(intent.kind, MALFORMED_PAYLOAD,
                      "payload.parent_hypothesis_ref must be a non-empty string")
    target_regime = payload.get("target_regime")
    if not isinstance(target_regime, str) or not target_regime:
        raise _reject(intent.kind, MALFORMED_PAYLOAD,
                      "payload.target_regime must be a non-empty string")
    triggering_classification_id = payload.get("triggering_classification_id")
    if (not isinstance(triggering_classification_id, str)
            or not triggering_classification_id):
        raise _reject(intent.kind, MALFORMED_PAYLOAD,
                      "payload.triggering_classification_id must be a non-empty "
                      "string")

    # ── 2. 4-check triggering_classification_id guard (mirrors B2). ──
    # (a) must resolve to an ADMITTED failure_classification in this project
    # (b) must be ADMITTED (status)
    # (c) must permit PROPOSE_PARALLEL_REGIME_TEST
    # (d) must bind to the payload's parent_program_id + parent_hypothesis_ref
    import json as _json

    from hermes.persistence.failure_classifications import (
        FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
    )
    from hermes.research.failure_classification import PermittedAction
    cls_row = conn.execute(
        "SELECT artifact_id, metadata_json FROM artifacts "
        "WHERE project_id = ? AND artifact_type = ? "
        "AND (artifact_id = ? OR content_hash = ?)",
        (intent.project_id, FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
         triggering_classification_id, triggering_classification_id)).fetchone()
    if cls_row is None:
        raise _reject(
            intent.kind, CLASSIFICATION_REF,
            f"triggering_classification_id "
            f"{triggering_classification_id!r} does not resolve to a "
            f"failure_classification in project {intent.project_id!r}")
    try:
        cls_meta = _json.loads(cls_row["metadata_json"] or "{}")
    except ValueError:
        raise _reject(
            intent.kind, CLASSIFICATION_REF,
            f"triggering classification "
            f"{triggering_classification_id!r} has corrupt metadata") from None
    if not isinstance(cls_meta, dict):
        raise _reject(
            intent.kind, CLASSIFICATION_REF,
            f"triggering classification "
            f"{triggering_classification_id!r} metadata is not a mapping")
    if cls_meta.get("status") != "ADMITTED":
        raise _reject(
            intent.kind, CLASSIFICATION_REF,
            f"triggering classification "
            f"{triggering_classification_id!r} is not ADMITTED "
            f"(status={cls_meta.get('status')!r})")
    cls_permitted = cls_meta.get("permitted_actions", [])
    if (not isinstance(cls_permitted, list)
            or PermittedAction.PROPOSE_PARALLEL_REGIME_TEST.value
            not in cls_permitted):
        raise _reject(
            intent.kind, CLASSIFICATION_REF,
            f"triggering classification "
            f"{triggering_classification_id!r} does not permit "
            f"PROPOSE_PARALLEL_REGIME_TEST")
    # (d) classification-program-hypothesis binding
    cls_program_ref = cls_meta.get("program_ref")
    cls_program_id = program_ref_key(cls_program_ref) or ""
    if _canonical_or_none(cls_program_id) != _canonical_or_none(parent_program_id):
        raise _reject(
            intent.kind, CLASSIFICATION_REF,
            f"triggering classification "
            f"{triggering_classification_id!r} targets program "
            f"{cls_program_ref!r}, not payload.parent_program_id "
            f"{parent_program_id!r}")
    if (_canonical_or_none(cls_meta.get("hypothesis_ref"))
            != _canonical_or_none(parent_hypothesis_ref)):
        raise _reject(
            intent.kind, CLASSIFICATION_REF,
            f"triggering classification "
            f"{triggering_classification_id!r} targets hypothesis "
            f"{cls_meta.get('hypothesis_ref')!r}, not "
            f"payload.parent_hypothesis_ref {parent_hypothesis_ref!r}")

    # ── 3. Resolve parent program (in-project) and clone substance. ──
    parent = _resolve_program_in_project(
        conn, intent.project_id, parent_program_id)
    if parent is None:
        raise _reject(intent.kind, PROVENANCE,
                      f"parent_program_id {parent_program_id!r} does not "
                      f"resolve to a research program in project "
                      f"{intent.project_id!r}")
    # Clone the substance fields from the parent — never from the intent.
    cloned_scope_ref = parent.get("scope_ref")
    if not isinstance(cloned_scope_ref, str) or not cloned_scope_ref:
        raise _reject(intent.kind, MALFORMED_PAYLOAD,
                      f"parent program {parent_program_id!r} has no "
                      f"resolvable scope_ref — cannot emit child")
    # scope_content_hash is resolved from the parent program's stored
    # scope_ref (the parent's scope, not the proposal's).
    try:
        scope_content_hash = program_repo.resolve_scope_content_hash(
            intent.project_id, cloned_scope_ref)
    except Exception as exc:
        raise _reject(intent.kind, SCOPE_NOT_GOVERNED,
                      f"cloned scope_ref {cloned_scope_ref!r} not governed "
                      f"for project {intent.project_id!r}: {exc}") from exc

    # _resolve_program_in_project returns dict(row) with hypothesis_json
    # parsed to "hypotheses"; the other substance columns are raw JSON text
    # (prediction_json, discrimination_json, methodology_json) and must be
    # parsed here before they feed compile_from_payload.
    def _parse_list(val):
        if val is None:
            return []
        if isinstance(val, list):
            return val
        if isinstance(val, str):
            return _json.loads(val) if val else []
        return []

    compiled_payload = {
        "scope_ref": cloned_scope_ref,
        "epistemic_objective": parent.get("epistemic_objective"),
        "hypotheses": parent.get("hypotheses") or [],
        "predictions": _parse_list(parent.get("prediction_json")),
        "discrimination_requirements": _parse_list(parent.get("discrimination_json")),
        "methodology_constraints": _parse_list(parent.get("methodology_json")),
        "task_graph_template_ref": parent.get("task_graph_template_ref"),
        "compiler_version": parent.get("compiler_version"),
        "policy_version": parent.get("policy_version"),
        "schema_version": parent.get("schema_version") or "1",
        "supersedes_ref": None,
        # ADR-041: parallel-regime linkage fields (all-or-nothing).
        "parent_program_id": parent_program_id,
        "parent_hypothesis_ref": parent_hypothesis_ref,
        "target_regime": target_regime,
        # triggering_classification_id is gateway-only — validated here,
        # NOT passed to compile_from_payload.
    }

    # ── 4. Resolve known_* sets (R-02 pattern) + slot vocabulary. ──
    try:
        known_program_ids = program_repo.known_program_ids(intent.project_id)
        known_hypothesis_refs = program_repo.known_hypothesis_refs(
            intent.project_id)
        slot_vocabulary = program_repo.slot_vocabulary(intent.project_id)
    except Exception as exc:
        raise _reject(intent.kind, MALFORMED_PAYLOAD,
                      f"parallel-regime-test context unresolvable for "
                      f"project {intent.project_id!r}: {exc}") from exc

    # ── 5. Compile (deterministic verdict; NOT_COMPILED is a gate violation). ──
    result = compile_from_payload(
        compiled_payload,
        project_id=intent.project_id,
        scope_content_hash=scope_content_hash,
        superseded_program_ids=frozenset(),
        known_program_ids=known_program_ids,
        known_hypothesis_refs=known_hypothesis_refs,
        slot_vocabulary=slot_vocabulary,
    )
    if result.status is not CompilationStatus.COMPILED or result.program is None:
        first = result.errors[0] if result.errors else None
        detail = f"{first.code}: {first.explanation}" if first else result.status.value
        raise _reject(intent.kind, NOT_COMPILED,
                      f"program validation failed ({result.status.value}) — "
                      f"{detail}; compilation never equals approval (v6 §14) "
                      f"and nothing was persisted")

    program = result.program
    # ── 6. Idempotency (PA4): detect a pre-existing duplicate. ──
    existing = program_repo.get_by_hash(program.content_hash)
    # ── 7. Record (produced_by='DETERMINISTIC' preserves the origin trail). ──
    row = program_repo.record(
        intent.project_id, result,
        produced_by=intent.proposed_by,  # 'DETERMINISTIC' — origin preserved
        reason=intent.justification,
        new_slot_declarations=(),
        # AUDIT-TXN A1.2: as in the proposal branch, the pre-read decides
        # whether the record is handed down (see record()'s docstring).
        audit=audit if existing is None else None,
    )
    return IntentResult(
        kind=intent.kind,
        entity_type="research_program",
        entity_id=program.program_id,
        duplicate=existing is not None,
        row=row,
        event_type=EventType.RESEARCH_PROGRAM_COMPILED.value,
    )


_CLASSIFICATION_ACTION_PAYLOAD_KEYS = frozenset({
    "classification_ref", "action", "candidate_artifact_ref", "rationale",
    # ADR-041: target_regime is carried by PROPOSE_PARALLEL_REGIME_TEST
    # actions so the B3 consumer can read it from the recorded event.
    "target_regime",
})


def _validate_propose_classification_action(
    conn: Any,
    intent: Intent,
    *,
    clock: Callable[[], str],
    audit: AuditRecord | None = None,
) -> IntentResult:
    """PROPOSE_CLASSIFICATION_ACTION: a Q-05 permitted action for a
    re-review candidate, ADMITTED as a proposal — the audit event IS the
    record (the ``ClassificationActionProposed`` event, ratified catalog
    member). Proposal-ONLY: the action is never executed here; acting
    still requires the existing authority (ABANDON / EVIDENCE_TRANSITION /
    PROPOSE_RESEARCH_PROGRAM / S16 human amendment) — IDR-040 §2.

    Validated at admission: the classification ref must D3-dereference
    in-project (``failure_classification:<content_hash>`` -> a
    failure_classification artifact of the same project), the action must
    be a ratified ``PermittedAction`` member, and the candidate artifact
    must exist in the project. Idempotent: a repeat of the same
    (classification_ref, action, candidate) returns the existing proposal
    (duplicate=True) — the daily digest run never floods the audit.
    """
    payload = intent.payload
    if not isinstance(payload, dict):
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"payload must be a dict, got {type(payload).__name__}")
    unknown = sorted(set(payload) - _CLASSIFICATION_ACTION_PAYLOAD_KEYS)
    if unknown:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"unknown payload keys {unknown} for "
            f"PROPOSE_CLASSIFICATION_ACTION")
    classification_ref = payload.get("classification_ref")
    if not isinstance(classification_ref, str) or not classification_ref:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            "payload.classification_ref must be a non-empty string")
    action = payload.get("action")
    # Lazy: the substrate module is not imported at gateway top (cycle-safe,
    # the source_outcomes pattern).
    from hermes.research.failure_classification import PermittedAction
    try:
        action_member = PermittedAction(action)
    except ValueError:
        raise _reject(
            intent.kind, CLASSIFICATION_REF,
            f"payload.action {action!r} is not a ratified "
            f"PermittedAction member") from None
    candidate = payload.get("candidate_artifact_ref")
    if not isinstance(candidate, str) or not candidate:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            "payload.candidate_artifact_ref must be a non-empty string")
    rationale = payload.get("rationale")
    if rationale is not None and (not isinstance(rationale, str)
                                  or len(rationale) > 2000):
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            "payload.rationale must be a string of at most 2000 chars")

    # D3 — the classification ref must dereference in-project (the future
    # REFUTED record's dereference contract, applied at the proposal gate).
    from hermes.persistence.failure_classifications import (
        FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
        FAILURE_CLASSIFICATION_REF_PREFIX,
        FailureClassificationRepository,
    )
    fcrepo = FailureClassificationRepository(conn, clock)
    if not fcrepo.dereference_failure_classification_ref(
            intent.project_id, classification_ref):
        raise _reject(
            intent.kind, CLASSIFICATION_REF,
            f"classification ref {classification_ref!r} does not "
            f"dereference in project {intent.project_id!r}")

    # HUMAN-APPROVAL GATE (F2 — recomputed, never trusted from storage):
    # a proposal whose CLASS requires human confirmation (FRAMING_ERROR) OR
    # whose ACTION is authority-shaped (REJECT_BRANCH / ROUTE_TO_SCOPE_REVIEW
    # / PROPOSE_SCOPE_NARROWING — the IDR-041 decision) is admitted as
    # PENDING_HUMAN_APPROVAL — it cannot become executable until a ratified
    # RESOLVE_CLASSIFICATION_PROPOSAL decision.
    import json as _json

    from hermes.research.failure_classification import (
        FailureClass,
        parse_contributing_factors,
        proposal_requires_human_confirmation,
    )
    cls_row = ArtifactRepository(conn).metadata_json_by_hash(
        intent.project_id, FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
        classification_ref[len(FAILURE_CLASSIFICATION_REF_PREFIX):])
    if cls_row is None:
        raise _reject(
            intent.kind, CLASSIFICATION_REF,
            f"classification {classification_ref!r} does not dereference "
            f"in project {intent.project_id!r}")
    try:
        cls_meta = _json.loads(cls_row or "{}")
        failure_class = FailureClass(cls_meta.get("failure_class"))
        contributing = parse_contributing_factors(
            cls_meta.get("contributing_factors"))
    except (ValueError, TypeError):
        raise _reject(
            intent.kind, CLASSIFICATION_REF,
            f"classification {classification_ref!r} has corrupt metadata — "
            f"cannot gate the proposal") from None
    proposal_state = (
        "PENDING_HUMAN_APPROVAL"
        if proposal_requires_human_confirmation(
            failure_class, action_member, contributing)
        else "EFFECTIVE")

    # The candidate must be a real artifact of this project.
    if not ArtifactRepository(conn).in_project(candidate, intent.project_id):
        raise _reject(
            intent.kind, CLASSIFICATION_REF,
            f"candidate artifact {candidate!r} not in project "
            f"{intent.project_id!r}")

    # Deterministic proposal identity — the idempotency key (correlation_id).
    import hashlib
    import json as _json
    proposal_id = "prop_" + hashlib.sha256(_json.dumps(
        {"classification_ref": classification_ref,
         "action": action_member.value,
         "candidate_artifact_ref": candidate},
        sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    if EventRepository(conn).event_exists(
            EventType.CLASSIFICATION_ACTION_PROPOSED.value, proposal_id):
        return IntentResult(
            kind=intent.kind, entity_type="classification_action_proposal",
            entity_id=proposal_id, duplicate=True,
            row={"proposal_id": proposal_id},
            event_type=EventType.CLASSIFICATION_ACTION_PROPOSED.value)
    EventRepository(conn).append_transactional(
        clock, EventType.CLASSIFICATION_ACTION_PROPOSED.value,
        project_id=intent.project_id, correlation_id=proposal_id,
        caused_by=intent.proposed_by,
        payload={
            "classification_ref": classification_ref,
            "action": action_member.value,
            "candidate_artifact_ref": candidate,
            "rationale": rationale or "",
            "state": proposal_state,
            # ADR-041: target_regime is carried by PROPOSE_PARALLEL_REGIME_TEST
            # actions so the B3 consumer can read it from the recorded event.
            "target_regime": payload.get("target_regime") or "",
        },
        # AUDIT-TXN A1.2: the proposal event IS the mutation, so the audit
        # row is appended inside that same transaction. No retry fallback:
        # a fused ROLLBACK-retry would undo the mutation (A1.3).
        audit=audit,
    )
    return IntentResult(
        kind=intent.kind, entity_type="classification_action_proposal",
        entity_id=proposal_id, duplicate=False,
        row={"proposal_id": proposal_id},
        event_type=EventType.CLASSIFICATION_ACTION_PROPOSED.value)


_RESOLVE_PROPOSAL_PAYLOAD_KEYS = frozenset({
    "proposal_id", "decision", "rationale", "operator_id",
})


def _decision_append_transactional(
    conn: Any,
    clock: Callable[[], str],
    event_type: str,
    *,
    project_id: str,
    correlation_id: str,
    caused_by: str,
    payload: dict,
    verdict_key: str | None,
    verdict_value: str,
    audit: AuditRecord | None = None,
) -> tuple[str, str | None]:
    """F6 (audit): the one-verdict check and the append run in ONE
    BEGIN IMMEDIATE transaction - a concurrent contradictory verdict can
    no longer slip past the prior-read (the pre-fix check ran in
    autocommit, so two racing applies could both pass it and land two
    contradictory decisions on the same proposal). Returns
    (outcome, prior_verdict) with outcome in appended / duplicate /
    conflict.

    ``audit`` (AUDIT-TXN A1.2) is appended immediately before COMMIT on the
    ``appended`` branch only. A duplicate or conflict writes no decision, so
    it appends nothing and the gateway journals the duplicate itself.
    """
    import json as _json

    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT payload_json FROM events "
            "WHERE event_type = ? AND correlation_id = ? "
            "ORDER BY rowid LIMIT 1",
            (event_type, correlation_id)).fetchone()
        if row is not None:
            # verdict_key=None is the existence-only mode (transition
            # admissions): any prior row is a duplicate.
            if verdict_key is None:
                conn.execute("ROLLBACK")
                return ("duplicate", None)
            try:
                prior = _json.loads(row["payload_json"]).get(verdict_key)
            except ValueError:
                prior = None
            conn.execute("ROLLBACK")
            if prior == verdict_value:
                return ("duplicate", prior)
            return ("conflict", prior)
        _append_event_to_db(
            conn, clock, event_type,
            project_id=project_id, correlation_id=correlation_id,
            caused_by=caused_by, payload=payload)
        if audit is not None:
            _append_event_to_db(
                conn, clock, audit.event_type,
                project_id=audit.project_id,
                correlation_id=audit.correlation_id,
                caused_by=audit.caused_by,
                reason=audit.reason,
                payload=audit.payload)
        conn.execute("COMMIT")
        return ("appended", None)
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _validate_resolve_classification_proposal(
    conn: Any,
    intent: Intent,
    *,
    clock: Callable[[], str],
    audit: AuditRecord | None = None,
) -> IntentResult:
    """RESOLVE_CLASSIFICATION_PROPOSAL: the ratified HUMAN decision on a
    pending classification-action proposal (internal-only — the human has
    no agent profile; the deterministic layer ingests the operator verdict).

    Validated at admission: the proposal_id must reference an admitted
    ClassificationActionProposed event whose state is PENDING_HUMAN_APPROVAL
    (an EFFECTIVE proposal needs no decision), and the decision must be a
    ratified verdict (APPROVED / REJECTED). Idempotent: the same decision
    re-recorded returns duplicate=True; a CONTRADICTORY second decision is
    refused — one proposal, one ratified verdict. The decision appends the
    ClassificationActionDecision event (correlation_id = proposal_id): the
    proposal becomes executable (APPROVED) or closed (REJECTED).
    """
    payload = intent.payload
    if not isinstance(payload, dict):
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"payload must be a dict, got {type(payload).__name__}")
    unknown = sorted(set(payload) - _RESOLVE_PROPOSAL_PAYLOAD_KEYS)
    if unknown:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"unknown payload keys {unknown} for "
            f"RESOLVE_CLASSIFICATION_PROPOSAL")
    proposal_id = payload.get("proposal_id")
    if not isinstance(proposal_id, str) or not proposal_id:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            "payload.proposal_id must be a non-empty string")
    decision = payload.get("decision")
    if decision not in ("APPROVED", "REJECTED"):
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"payload.decision {decision!r} must be APPROVED or REJECTED")
    rationale = payload.get("rationale")
    if rationale is not None and (not isinstance(rationale, str)
                                  or len(rationale) > 2000):
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            "payload.rationale must be a string of at most 2000 chars")
    # A4: every operator decision cites a RATIFIED operator — the gateway
    # re-verifies the credential EXISTS (the token itself is verified at the
    # controller surface and never travels in an intent/event).
    operator_id = payload.get("operator_id")
    if not isinstance(operator_id, str) or not operator_id:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            "payload.operator_id must be a non-empty string")
    from hermes.persistence.repositories import OperatorCredentialRepository
    if not OperatorCredentialRepository(conn).exists(operator_id):
        raise _reject(
            intent.kind, OPERATOR,
            f"operator {operator_id!r} is not a ratified operator "
            f"credential — the verdict cannot be recorded")

    # The proposal must exist AND be pending.
    import json as _json
    prop = EventRepository(conn).payload_json(
        EventType.CLASSIFICATION_ACTION_PROPOSED.value, proposal_id)
    if prop is None:
        raise _reject(
            intent.kind, PROPOSAL,
            f"proposal {proposal_id!r} not found")
    try:
        prop_payload = _json.loads(prop)
    except ValueError:
        raise _reject(
            intent.kind, PROPOSAL,
            f"proposal {proposal_id!r} has corrupt payload") from None
    # F2 — the gate RECOMPUTES from the classification's class, never from
    # the stored admission state: a proposal is decidable iff its class
    # actually requires human confirmation. A tampered state can neither
    # fabricate a decidable pending proposal (upward tamper) nor block a
    # genuine one (downward tamper). Missing or corrupt classification
    # metadata fails closed — never a decision.
    from hermes.persistence.failure_classifications import (
        FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
        FAILURE_CLASSIFICATION_REF_PREFIX,
    )
    from hermes.research.failure_classification import (
        FailureClass,
        PermittedAction,
        parse_contributing_factors,
        proposal_requires_human_confirmation,
    )
    cls_ref = prop_payload.get("classification_ref")
    if not isinstance(cls_ref, str) or not cls_ref.startswith(
            FAILURE_CLASSIFICATION_REF_PREFIX):
        raise _reject(
            intent.kind, PROPOSAL,
            f"proposal {proposal_id!r} carries no dereferenceable "
            f"classification ref — cannot decide")
    cls_row = ArtifactRepository(conn).metadata_json_by_hash(
        intent.project_id, FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
        cls_ref[len(FAILURE_CLASSIFICATION_REF_PREFIX):])
    if cls_row is None:
        raise _reject(
            intent.kind, PROPOSAL,
            f"proposal {proposal_id!r} cites a classification that does not "
            f"dereference in project {intent.project_id!r} — cannot decide")
    try:
        cls_meta_d = _json.loads(cls_row or "{}")
        failure_class = FailureClass(cls_meta_d.get("failure_class"))
        contributing = parse_contributing_factors(
            cls_meta_d.get("contributing_factors"))
    except (ValueError, TypeError):
        raise _reject(
            intent.kind, PROPOSAL,
            f"proposal {proposal_id!r} cites a classification with corrupt "
            f"metadata — cannot decide") from None
    try:
        action_member = PermittedAction(prop_payload.get("action"))
    except (ValueError, TypeError):
        action_member = None
    if action_member is None or not proposal_requires_human_confirmation(
            failure_class, action_member, contributing):
        raise _reject(
            intent.kind, PROPOSAL,
            f"proposal {proposal_id!r}'s class {failure_class.value} and "
            f"action {prop_payload.get('action')!r} do not require human "
            f"confirmation — nothing to decide")

    # One proposal, one ratified verdict — checked AND appended in one
    # transaction (F6 audit): a concurrent contradictory verdict can no
    # longer slip past the prior-read. Identical re-record: duplicate.
    outcome, prior = _decision_append_transactional(
        conn, clock, EventType.CLASSIFICATION_ACTION_DECISION.value,
        project_id=intent.project_id, correlation_id=proposal_id,
        caused_by=intent.proposed_by,
        payload={
            "proposal_id": proposal_id,
            "decision": decision,
            "rationale": rationale or "",
            "operator_id": operator_id,
        },
        verdict_key="decision", verdict_value=decision, audit=audit)
    if outcome == "duplicate":
        return IntentResult(
            kind=intent.kind, entity_type="classification_action_proposal",
            entity_id=proposal_id, duplicate=True,
            row={"proposal_id": proposal_id, "decision": decision},
            event_type=EventType.CLASSIFICATION_ACTION_DECISION.value)
    if outcome == "conflict":
        raise _reject(
            intent.kind, PROPOSAL,
            f"proposal {proposal_id!r} already decided "
            f"{prior!r} — a contradictory verdict is refused")
    return IntentResult(
        kind=intent.kind, entity_type="classification_action_proposal",
        entity_id=proposal_id, duplicate=False,
        row={"proposal_id": proposal_id, "decision": decision},
        event_type=EventType.CLASSIFICATION_ACTION_DECISION.value)


def _resolve_ratified_proposal(
    conn: Any, project_id: str, proposal_id: str,
    allowed_actions: frozenset,
) -> dict | None:
    """The IDR-041 ratification-ref contract (AC-4): ``proposal_id``
    dereferences to a ratified human approval iff an admitted
    ClassificationActionProposed event (project-scoped) has an APPROVED
    ClassificationActionDecision, its action is in ``allowed_actions``, AND
    the action is in the classification's permitted set recomputed from the
    dereferenced class (F2 — never the stored state, never the stored
    permitted list). Returns the proposal payload, or None on ANY failure:
    a REJECTED/unknown proposal, a missing/corrupt classification, or an
    action outside the class's permitted set never yields a ratification.
    """
    import json as _json

    from hermes.persistence.failure_classifications import (
        FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
        FAILURE_CLASSIFICATION_REF_PREFIX,
    )
    from hermes.research.failure_classification import (
        FailureClass,
        PermittedAction,
        permitted_actions_for,
    )
    prop = EventRepository(conn).payload_json(
        EventType.CLASSIFICATION_ACTION_PROPOSED.value, proposal_id,
        project_id=project_id)
    if prop is None:
        return None
    try:
        payload = _json.loads(prop)
    except ValueError:
        return None
    decision = EventRepository(conn).payload_json(
        EventType.CLASSIFICATION_ACTION_DECISION.value, proposal_id)
    if decision is None:
        return None
    try:
        if _json.loads(decision).get("decision") != "APPROVED":
            return None
    except ValueError:
        return None
    action = payload.get("action")
    try:
        action_member = (PermittedAction(action)
                         if isinstance(action, str) else None)
    except ValueError:
        action_member = None
    if action_member is None or action_member not in allowed_actions:
        return None
    cls_ref = payload.get("classification_ref")
    if not isinstance(cls_ref, str) or not cls_ref.startswith(
            FAILURE_CLASSIFICATION_REF_PREFIX):
        return None
    row = ArtifactRepository(conn).metadata_json_by_hash(
        project_id, FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
        cls_ref[len(FAILURE_CLASSIFICATION_REF_PREFIX):])
    if row is None:
        return None
    try:
        failure_class = FailureClass(_json.loads(
            row or "{}").get("failure_class"))
    except (ValueError, TypeError):
        return None
    if action_member not in permitted_actions_for(failure_class):
        return None
    return payload
_EVIDENCE_TRANSITION_PAYLOAD_KEYS = frozenset({
    "evidence_artifact_ref", "from_state", "to_state",
    "ratification_ref", "rationale",
})

#: OPS-5Z Group E — the critic's round request and the spine's terminal
#: record. Closed top-level keys; the nested shapes are validated by
#: ``hermes.research.verification`` so the gateway and the executor cannot
#: disagree about them.
_REQUEST_ADDITIONAL_EXPERIMENT_PAYLOAD_KEYS = frozenset({
    "claims", "conflict", "mode", "targets",
})
_RECORD_VERIFICATION_OUTCOME_PAYLOAD_KEYS = frozenset({
    "round_id", "status", "winner_ref", "detail", "code", "evidence_refs",
    "branches",
})
_ROUND_MODE_VALUES: frozenset[str] = frozenset(verification.VERIFICATION_MODES)

#: The legal top-level payload keys, per kind, for the kinds an LLM profile can
#: actually propose and the gateway can apply (OPS-12). Each value is the same
#: frozenset its validator checks; the contract renders from this map, never
#: from a second hand-typed list. Kinds absent here have no closed top-level
#: schema exposed (or no validator); the availability note covers the latter.
INTENT_PAYLOAD_KEYS: Mapping[IntentKind, frozenset[str]] = {
    IntentKind.INSERT_TASK: _TASK_PAYLOAD_KEYS,
    IntentKind.ADMIT_TASK: _TASK_PAYLOAD_KEYS,
    IntentKind.EVIDENCE_TRANSITION: _EVIDENCE_TRANSITION_PAYLOAD_KEYS,
    IntentKind.REQUEST_ADDITIONAL_EXPERIMENT:
        _REQUEST_ADDITIONAL_EXPERIMENT_PAYLOAD_KEYS,
    IntentKind.RECORD_VERIFICATION_OUTCOME:
        _RECORD_VERIFICATION_OUTCOME_PAYLOAD_KEYS,
    IntentKind.PROPOSE_RESEARCH_PROGRAM: RESEARCH_PROGRAM_PAYLOAD_KEYS,
}

#: The legal ``task_type`` values, read from the enum ``_payload_to_node``
#: parses. Not a second typed list: adding a ``NodeType`` adds a legal value.
_TASK_TYPE_VALUES: frozenset[str] = frozenset(
    node_type.value for node_type in NodeType)

#: The legal ``profile`` values, read from the enum ``_payload_to_node`` parses
#: (OPS-14). Same rule: adding an ``AgentProfile`` adds a legal value.
_PROFILE_VALUES: frozenset[str] = frozenset(
    member.value for member in AgentProfile)

#: The enumerated payload values the validators check, per kind and key
#: (OPS-13, OPS-14), beside the closed-key map above. A supplied value outside
#: the set refuses ``MALFORMED_PAYLOAD``; a draft may omit either key, because
#: ``AgentRuntime._derive_payload`` supplies its default before the intent is
#: built. Only ``INSERT_TASK`` is mapped: it is the task kind a model can
#: propose. ``ADMIT_TASK`` shares ``_TASK_PAYLOAD_KEYS`` but is internal-only.
INTENT_PAYLOAD_VALUE_SETS: Mapping[IntentKind, Mapping[str, frozenset[str]]] = {
    IntentKind.INSERT_TASK: {
        "task_type": _TASK_TYPE_VALUES,
        "profile": _PROFILE_VALUES,
    },
    IntentKind.REQUEST_ADDITIONAL_EXPERIMENT: {
        "mode": _ROUND_MODE_VALUES,
    },
}

#: The shape ``_require_str_list`` checks, stated once so the validator's
#: refusal and the rendered contract cannot disagree (OPS-14). A free-form
#: list has no value set to enumerate, only a shape.
_PAYLOAD_LIST_SHAPE = "a list of strings"

#: The remaining `INSERT_TASK` shapes the validator enforces (OPS-5K). Each
#: phrase is the one its refusal interpolates, so a shape change moves both
#: the refusal and the contract.
_PAYLOAD_DICT_SHAPE = "a dict"
_PAYLOAD_INT_AT_LEAST_1_SHAPE = "an int >= 1"
_PAYLOAD_INT_AT_LEAST_0_SHAPE = "an int >= 0"
_PAYLOAD_NULLABLE_STRING_SHAPE = "a string or null"

#: The payload keys whose shape the contract states, per kind (OPS-14,
#: completed in OPS-17, extended in OPS-5K), beside the closed-key map above.
#: The value is the shape phrase the validator's refusal uses. The list family
#: is exactly the keys ``_payload_to_node`` passes through
#: ``_require_str_list``: ``inputs``, ``outputs``, ``dependencies`` and
#: ``provenance``. OPS-5K added the dict key ``spec`` and the scalar keys whose
#: bespoke checks the validator also enforces (``iteration``,
#: ``max_retries`` and the three nullable strings). Omission is accepted for
#: every key — the validator supplies its own default. Derived identity keys
#: (``task_id``, ``idempotency_key``) are not mapped: the contract forbids
#: supplying them at all.
INTENT_PAYLOAD_SHAPES: Mapping[IntentKind, Mapping[str, str]] = {
    IntentKind.REQUEST_ADDITIONAL_EXPERIMENT: {
        "claims": ("a list of exactly two claim objects "
                   "(ref, statement, source_ref)"),
        "conflict": ("the contradiction_scan conflict object "
                     "(kind, left, right, subject, date, detail)"),
        "mode": "one of the two modes derived from the claims' sources",
        "targets": ("a list of one (verify-one) or two, one per claim "
                    "(parallel-two), fetch targets "
                    "(claim_ref, provider, url)"),
    },
    IntentKind.INSERT_TASK: {
        "spec": _PAYLOAD_DICT_SHAPE,
        "inputs": _PAYLOAD_LIST_SHAPE,
        "outputs": _PAYLOAD_LIST_SHAPE,
        "dependencies": _PAYLOAD_LIST_SHAPE,
        "provenance": _PAYLOAD_LIST_SHAPE,
        "iteration": _PAYLOAD_INT_AT_LEAST_1_SHAPE,
        "max_retries": _PAYLOAD_INT_AT_LEAST_0_SHAPE,
        "parent_task_id": _PAYLOAD_NULLABLE_STRING_SHAPE,
        "cost_class": _PAYLOAD_NULLABLE_STRING_SHAPE,
        "concurrency_group": _PAYLOAD_NULLABLE_STRING_SHAPE,
    },
}


@dataclass(frozen=True, slots=True)
class RequiredPayloadField:
    """One required payload field's contract guidance (OPS-5P).

    ``values`` is the exact set the validator membership-checks (``None``
    when the field is a ref, not an enumeration); ``shape`` and ``note`` are
    the field's stated form and meaning. The contract renders all three.
    """

    values: frozenset[str] | None = None
    shape: str = ""
    note: str = ""


def intent_payload_required_fields() -> dict[
        IntentKind, dict[str, RequiredPayloadField]]:
    """The required payload fields, built from the validator's vocabulary.

    OPS-5P: ``EVIDENCE_TRANSITION``'s ``from_state``/``to_state`` are
    evidence verdicts, not stages, and the validator refuses an omitted or
    equal pair; ``evidence_artifact_ref`` takes the artifact ref, not the
    ``source_payload:<content_hash>`` content ref. Every value and form is
    read from the validator's own constants at call time — the ratified
    states, the two evidence ref prefixes ``canonical_evidence_ref`` accepts,
    and the content-ref form the field must not take — so a vocabulary
    change moves the rendered contract without a second hand-typed list.
    """
    from hermes.research.capability_supply import (
        SOURCE_PAYLOAD_HANDLE_PREFIX,
        SOURCE_REF_SEPARATOR,
    )
    from hermes.research.evidence_transitions import (
        EVIDENCE_HANDLE_REF_PREFIX,
        EVIDENCE_REF_PREFIX,
        RATIFIED_EVIDENCE_STATES,
    )

    state_note = (
        "from_state and to_state are the evidence verdicts before and after "
        "this transition — a verdict about the claim, not a position in the "
        "research chain and not a stage name; the pair must differ (an equal "
        "pair is refused), and no transition may leave REFUTED (the terminal "
        "state).")
    artifact_shape = (
        f"the artifact ref '{EVIDENCE_REF_PREFIX}<artifact_id>' (the "
        f"observation handle '{EVIDENCE_HANDLE_REF_PREFIX}<artifact_id>' is "
        f"also accepted and normalised to it)")
    artifact_note = (
        f"The content ref "
        f"'{SOURCE_PAYLOAD_HANDLE_PREFIX}{SOURCE_REF_SEPARATOR}"
        f"<content_hash>' is not accepted in evidence_artifact_ref; no "
        f"payload field of EVIDENCE_TRANSITION takes it.")
    round_note = (
        "The round carries the conflict that caused it (the contradiction_scan "
        "result) so the journal shows why an extra fetch happened. The mode is "
        "checked against the claims' sources — different sources cost one "
        "fetch, the same source on both sides is two branches; the spine "
        "derives it and the critic cannot choose past it.")
    return {
        IntentKind.EVIDENCE_TRANSITION: {
            "evidence_artifact_ref": RequiredPayloadField(
                shape=artifact_shape, note=artifact_note),
            "from_state": RequiredPayloadField(
                values=RATIFIED_EVIDENCE_STATES, note=state_note),
            "to_state": RequiredPayloadField(
                values=RATIFIED_EVIDENCE_STATES, note=state_note),
        },
        IntentKind.REQUEST_ADDITIONAL_EXPERIMENT: {
            "claims": RequiredPayloadField(
                shape=("a list of exactly two objects: {ref, statement, "
                       "source_ref} — the two conflicting claims and the "
                       "source each rests on"),
                note=round_note),
            "conflict": RequiredPayloadField(
                shape=("the contradiction_scan conflict object: {kind, left, "
                       "right, subject, date, detail}"),
                note=("This is the rationale: the journal records it with "
                      "the round. A conflict is the only reason a round "
                      "opens — a caveat is not.")),
            "mode": RequiredPayloadField(
                values=_ROUND_MODE_VALUES,
                note=("verify-one when the claims rest on different sources "
                      "(one targeted fetch); parallel-two when they share "
                      "one source and still disagree (two branches).")),
            "targets": RequiredPayloadField(
                shape=("a list of {claim_ref, provider, url}: one target for "
                       "verify-one, two (one per claim) for parallel-two"),
                note=("The primary source(s) the round fetches. The fetch "
                      "goes through the capability plane's source_fetch — "
                      "egress allowlist and content gate included.")),
        },
    }


def _validate_evidence_transition(
    conn: Any, intent: Intent, *, clock: Callable[[], str],
    audit: AuditRecord | None = None,
) -> IntentResult:
    """EVIDENCE_TRANSITION — the ratified branch-transition ADMISSION
    (IDR-041 AC-4). Validates the transition shape (ratified evidence
    states, an in-project ``evidence:<artifact_id>`` dereference) and, when
    a ``ratification_ref`` is carried, the ratification-ref contract: the
    ref must dereference to an APPROVED REJECT_BRANCH proposal whose action
    is in the classification's permitted set (recomputed, F2); a ref to a
    REJECTED/unknown proposal or an action outside the class's permitted
    set is refused. Proposal-shaped (the IDR-040 precedent): the admission
    appends EVIDENCE_TRANSITION_PROPOSED — the audit IS the record;
    APPLYING the transition (changing evidence state) remains the future
    Evidence Ladder's authority, and nothing here changes any state.
    Idempotent via a deterministic transition id: a repeat admission
    returns duplicate=True and never floods the audit.
    """
    payload = intent.payload
    if not isinstance(payload, dict):
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"payload must be a dict, got {type(payload).__name__}")
    unknown = sorted(set(payload) - _EVIDENCE_TRANSITION_PAYLOAD_KEYS)
    if unknown:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"unknown payload keys {unknown} for EVIDENCE_TRANSITION")
    from hermes.research.capability_supply import (
        SOURCE_PAYLOAD_HANDLE_PREFIX,
        SOURCE_REF_SEPARATOR,
    )
    from hermes.research.evidence_transitions import (
        EVIDENCE_HANDLE_REF_PREFIX,
        EVIDENCE_REF_PREFIX,
        MAX_EVIDENCE_TRANSITION_RATIONALE,
        RATIFIED_EVIDENCE_STATES,
        canonical_evidence_ref,
    )
    raw_ref = payload.get("evidence_artifact_ref")
    evidence_artifact_ref = (
        canonical_evidence_ref(raw_ref) if isinstance(raw_ref, str) else None)
    if evidence_artifact_ref is None:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"payload.evidence_artifact_ref must be "
            f"'{EVIDENCE_REF_PREFIX}<artifact_id>' (or the observation handle "
            f"'{EVIDENCE_HANDLE_REF_PREFIX}<artifact_id>'); the field takes "
            f"the artifact ref, not the content ref "
            f"'{SOURCE_PAYLOAD_HANDLE_PREFIX}{SOURCE_REF_SEPARATOR}"
            f"<content_hash>' (no payload field of EVIDENCE_TRANSITION takes "
            f"that form); got {_bounded_rejected(raw_ref)}")
    artifact_id = evidence_artifact_ref[len(EVIDENCE_REF_PREFIX):]
    if not artifact_id:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            "payload.evidence_artifact_ref has an empty artifact id; got "
            f"{_bounded_rejected(raw_ref)}")
    if not ArtifactRepository(conn).in_project(artifact_id, intent.project_id):
        raise _reject(
            intent.kind, EVIDENCE_REF,
            f"evidence artifact {_bounded_rejected(artifact_id)} (from "
            f"{_bounded_rejected(raw_ref)}) not in project "
            f"{intent.project_id!r}")
    from_state = payload.get("from_state")
    to_state = payload.get("to_state")

    def _state_reason(field: str, value: Any) -> str:
        if value is None:
            return (
                f"payload.{field} is required and must be one of the "
                f"ratified evidence states "
                f"({sorted(RATIFIED_EVIDENCE_STATES)})")
        return (
            f"payload.{field} {value!r} is not a ratified evidence state "
            f"({sorted(RATIFIED_EVIDENCE_STATES)}) — an evidence state is a "
            f"verdict about the claim, not a stage name")

    if from_state not in RATIFIED_EVIDENCE_STATES:
        raise _reject(intent.kind, MALFORMED_PAYLOAD,
                      _state_reason("from_state", from_state))
    if to_state not in RATIFIED_EVIDENCE_STATES:
        raise _reject(intent.kind, MALFORMED_PAYLOAD,
                      _state_reason("to_state", to_state))
    if from_state == to_state:
        raise _reject(intent.kind, MALFORMED_PAYLOAD,
                      f"payload.from_state == payload.to_state "
                      f"({from_state}) — a transition must change state")
    if from_state == "REFUTED":
        raise _reject(intent.kind, MALFORMED_PAYLOAD,
                      "REFUTED is the terminal evidence state — no "
                      "transition may leave it")
    ratification_ref = payload.get("ratification_ref")
    if ratification_ref is not None and (
            not isinstance(ratification_ref, str) or not ratification_ref):
        raise _reject(intent.kind, MALFORMED_PAYLOAD,
                      "payload.ratification_ref must be a non-empty string "
                      "or absent")
    rationale = payload.get("rationale")
    if rationale is not None and (not isinstance(rationale, str)
                                  or len(rationale)
                                  > MAX_EVIDENCE_TRANSITION_RATIONALE):
        raise _reject(intent.kind, MALFORMED_PAYLOAD,
                      "payload.rationale must be a string of at most "
                      f"{MAX_EVIDENCE_TRANSITION_RATIONALE} chars")

    # The ratification-ref contract (AC-4): when present, the ref must be an
    # APPROVED REJECT_BRANCH proposal with the action in the class's
    # permitted set — otherwise the transition is refused fail-closed.
    if ratification_ref is not None:
        from hermes.research.failure_classification import PermittedAction
        ratified = _resolve_ratified_proposal(
            conn, intent.project_id, ratification_ref,
            frozenset({PermittedAction.REJECT_BRANCH}))
        if ratified is None:
            raise _reject(
                intent.kind, PROPOSAL,
                f"ratification_ref {ratification_ref!r} is not an APPROVED "
                f"REJECT_BRANCH proposal whose action is in the "
                f"classification's permitted set")

    # Deterministic transition identity — the idempotency key. OPS-5K: the
    # ref was normalised above, so ``evidence/<id>`` and ``evidence:<id>``
    # produce the same id and the same stored payload — one reference, not two.
    import hashlib
    import json as _json
    transition_id = "tr_" + hashlib.sha256(_json.dumps(
        {"evidence_artifact_ref": evidence_artifact_ref,
         "from_state": from_state, "to_state": to_state,
         "ratification_ref": ratification_ref or ""},
        sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    # F9 (audit): the idempotency check and the append run in ONE
    # BEGIN IMMEDIATE transaction — a concurrent repeat admission can no
    # longer slip past the existence-read (same race class as F6; the
    # schema-level one-verdict index in migration 12 is the backstop).
    outcome, _prior = _decision_append_transactional(
        conn, clock, EventType.EVIDENCE_TRANSITION_PROPOSED.value,
        project_id=intent.project_id, correlation_id=transition_id,
        caused_by=intent.proposed_by,
        payload={
            "evidence_artifact_ref": evidence_artifact_ref,
            "from_state": from_state, "to_state": to_state,
            "ratification_ref": ratification_ref or "",
            "rationale": rationale or "",
        },
        verdict_key=None, verdict_value="", audit=audit)
    if outcome == "duplicate":
        return IntentResult(
            kind=intent.kind, entity_type="evidence_transition_proposal",
            entity_id=transition_id, duplicate=True,
            row={"transition_id": transition_id},
            event_type=EventType.EVIDENCE_TRANSITION_PROPOSED.value)
    return IntentResult(
        kind=intent.kind, entity_type="evidence_transition_proposal",
        entity_id=transition_id, duplicate=False,
        row={"transition_id": transition_id},
        event_type=EventType.EVIDENCE_TRANSITION_PROPOSED.value)
_SCOPE_REVIEW_DECISION_PAYLOAD_KEYS = frozenset({
    "proposal_id", "scope_decision", "rationale", "operator_id",
})


# ── S5 (v6 §7): RETRACT_SOURCE — the supersede-and-invalidate cascade ──

# The payload contract (v6 §7/S5): RETRACT_SOURCE {source_ref, reason,
# human_decision_ref}. Exactly these keys — unknown keys are rejected.
_RETRACT_SOURCE_PAYLOAD_KEYS = frozenset(
    {"source_ref", "reason", "human_decision_ref"})

# The cascade walks the LIVE dependency-class edge vocabulary (Step 4 §4.5
# gap record): of v6 §14's five CASCADE_DEPENDENCY_EDGES
# (`supports`, `cites`, `entails`, `derived_from`, `used_as_input`), the
# schema (migrations.py, provenance_edges CHECK) carries exactly these
# three; `supports`/`entails` are GR3 additions and land with GR3 — the
# cascade never walks `supersedes` (the supersession edge points BACKWARD
# in time: the new decision supersedes the source; the source never
# invalidates its supersedes-target) and never walks any non-dependency
# edge class.
_S5_DEPENDENCY_EDGE_TYPES = ("cites", "derived_from", "used_as_input")

# The source-artifact taxonomy (source_outcomes.SOURCE_ARTIFACT_TYPES
# members that name a SOURCE — the retraction target must BE a source).
_S5_SOURCE_ARTIFACT_TYPES = frozenset(
    {"source_result", "source_payload", "source_search"})

# The decision artifact (cascade step 2) — a ResearchDecision with a
# `supersedes` edge to the retracted source (v6 §7/S5 step 2).
_S5_DECISION_ARTIFACT_TYPE = "ResearchDecision"


def _s5_source_artifact_id(conn: Any, project_id: str, source_ref: str,
                           ) -> str:
    """Resolve ``source_ref`` to an artifact id, fail-closed.

    Two ratified ref forms (the retracted_source_review_candidates
    precedent, controller.py): a bare ``artifact_id`` (resolved in-project,
    type-checked source), or ``source_result:<hash>`` /
    ``source_payload:<hash>`` (the SD-05 dereference identity — resolved by
    content hash with the type prefix as part of the key). Returns the
    artifact id; raises ``_reject`` (MALFORMED_PAYLOAD / EVIDENCE_REF) on
    any non-resolution.
    """
    prefix, sep, h = source_ref.partition(":")
    if sep:
        if prefix not in _S5_SOURCE_ARTIFACT_TYPES or not h:
            raise _reject(
                IntentKind.RETRACT_SOURCE, MALFORMED_PAYLOAD,
                f"payload.source_ref {source_ref!r} must be "
                f"'<artifact_id>' or '<source_type>:<content_hash>' with "
                f"source_type in {sorted(_S5_SOURCE_ARTIFACT_TYPES)}")
        row = conn.execute(
            "SELECT artifact_id FROM artifacts "
            "WHERE project_id = ? AND content_hash = ? "
            "AND artifact_type = ? ORDER BY created_at LIMIT 1",
            (project_id, h, prefix)).fetchone()
        if row is None:
            raise _reject(
                IntentKind.RETRACT_SOURCE, EVIDENCE_REF,
                f"payload.source_ref {source_ref!r} does not resolve to a "
                f"{prefix} artifact in project {project_id!r}")
        return row["artifact_id"]
    row = conn.execute(
        "SELECT artifact_type FROM artifacts "
        "WHERE artifact_id = ? AND project_id = ?",
        (source_ref, project_id)).fetchone()
    if row is None:
        raise _reject(
            IntentKind.RETRACT_SOURCE, EVIDENCE_REF,
            f"payload.source_ref {source_ref!r} does not dereference in "
            f"project {project_id!r}")
    if row["artifact_type"] not in _S5_SOURCE_ARTIFACT_TYPES:
        raise _reject(
            IntentKind.RETRACT_SOURCE, EVIDENCE_REF,
            f"payload.source_ref {source_ref!r} names artifact type "
            f"{row['artifact_type']!r}, not a source artifact "
            f"({sorted(_S5_SOURCE_ARTIFACT_TYPES)})")
    return source_ref


def _s5_cone_closure(
    source_artifact_id: str,
    downstream: dict[str, list[str]],
) -> list[str]:
    """The deterministic downstream closure for one S5 source artifact.

    ``source_artifact_id`` is the seed; ``downstream`` is the caller-built
    adjacency map of canonical artifact identities (already project-scoped
    by the caller's emission JOIN). Returns the sorted, de-duplicated set of
    nodes reachable from the seed, EXCLUDING the seed itself; the input
    mapping is never mutated.

    Pure: no I/O, no SQL, no transaction control, no refusals, no identity
    derivation, no time or hash source. It must be called with the adjacency
    map built from the caller's in-transaction reads, and it can never
    participate in that transaction from here.
    """
    cone: list[str] = []
    seen = {source_artifact_id}
    stack = sorted(downstream.get(source_artifact_id, ()))
    while stack:
        artifact_id = stack.pop(0)
        if artifact_id in seen:
            continue
        seen.add(artifact_id)
        cone.append(artifact_id)
        stack.extend(sorted(downstream.get(artifact_id, ())))
    cone.sort()
    return cone


def _retract_source_command(intent: Intent) -> tuple[str, str, str]:
    """Validate the RETRACT_SOURCE payload; return the command fields.

    HYGIENE-2 P3-8: extracted verbatim from ``_validate_retract_source`` —
    the same checks, the same order, and the same ``MALFORMED_PAYLOAD``
    messages.
    """
    payload = intent.payload
    if not isinstance(payload, dict):
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"payload must be a dict, got {type(payload).__name__}")
    unknown = sorted(set(payload) - _RETRACT_SOURCE_PAYLOAD_KEYS)
    if unknown:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"unknown payload keys {unknown} for RETRACT_SOURCE")

    source_ref = payload.get("source_ref")
    if not isinstance(source_ref, str) or not source_ref:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            "payload.source_ref must be a non-empty string")
    reason = payload.get("reason")
    if (not isinstance(reason, str) or not reason.strip()):
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            "payload.reason must be a non-empty cited reason (v6 §7/S5)")
    human_decision_ref = payload.get("human_decision_ref")
    if not isinstance(human_decision_ref, str) or not human_decision_ref:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            "payload.human_decision_ref must be a non-empty string")
    return source_ref, reason, human_decision_ref


def _retract_source_binding(
    conn: Any, intent: Intent, source_ref: str, reason: str,
    human_decision_ref: str,
) -> None:
    """Verify a recorded HumanDecision binds this exact retraction command.

    HYGIENE-2 P3-8: extracted verbatim from ``_validate_retract_source`` —
    the same dereference query, binding checks, order, and ``PROPOSAL``
    messages.
    """
    # The HumanDecision contract (v6 §7/S5; RETRACT-1 closes P0-3): a
    # RECORDED human decision must exist — dereferenced against the
    # HumanDecisionReceived journal (event_id or correlation_id),
    # fail-closed — AND its payload must bind THIS command. Existence is
    # not authority: a decision recorded for another intent (e.g. a
    # classification verdict) or for another source/reason never
    # authorizes a retraction. No binding, no cascade: the gateway never
    # fabricates the human's authority. The binding mirrors the
    # classification/contradiction/curation precedents (payload load,
    # closed comparison, ``PROPOSAL`` refusal).
    import hashlib
    import json as _json
    decision_row = conn.execute(
        "SELECT event_id, correlation_id, payload_json FROM events "
        "WHERE project_id = ? AND event_type = ? "
        "AND (event_id = ? OR correlation_id = ?) "
        "ORDER BY rowid LIMIT 1",
        (intent.project_id, EventType.HUMAN_DECISION_RECEIVED.value,
         human_decision_ref, human_decision_ref)).fetchone()
    if decision_row is None:
        raise _reject(
            intent.kind, PROPOSAL,
            f"payload.human_decision_ref {human_decision_ref!r} does not "
            f"dereference to a recorded HumanDecision in project "
            f"{intent.project_id!r} — RETRACT_SOURCE requires a recorded "
            f"HumanDecision (v6 §7/S5)")
    try:
        decision_payload = _json.loads(decision_row["payload_json"] or "{}")
    except ValueError:
        raise _reject(
            intent.kind, PROPOSAL,
            f"recorded HumanDecision {human_decision_ref!r} has a corrupt "
            f"payload — its binding cannot be verified") from None
    if not isinstance(decision_payload, dict):
        raise _reject(
            intent.kind, PROPOSAL,
            f"recorded HumanDecision {human_decision_ref!r} has a corrupt "
            f"payload — its binding cannot be verified")
    if decision_payload.get("decision") != IntentKind.RETRACT_SOURCE.value:
        raise _reject(
            intent.kind, PROPOSAL,
            f"recorded HumanDecision {human_decision_ref!r} is a "
            f"{decision_payload.get('decision')!r} verdict, not a "
            f"RETRACT_SOURCE verdict — a decision for another intent never "
            f"authorizes a retraction")
    if decision_payload.get("source_ref") != source_ref:
        raise _reject(
            intent.kind, PROPOSAL,
            f"recorded HumanDecision {human_decision_ref!r} binds source "
            f"{decision_payload.get('source_ref')!r}, not {source_ref!r} — "
            f"the decision does not ratify this retraction")
    reason_digest = hashlib.sha256(reason.encode("utf-8")).hexdigest()
    if decision_payload.get("reason_digest") != reason_digest:
        raise _reject(
            intent.kind, PROPOSAL,
            f"recorded HumanDecision {human_decision_ref!r} does not bind "
            f"the cited reason (reason_digest mismatch) — the decision does "
            f"not ratify this retraction")


def _retract_source_id(
    source_ref: str, reason: str, human_decision_ref: str,
) -> str:
    """Deterministic idempotency key over the FULL retraction command.

    HYGIENE-2 P3-8: extracted verbatim from ``_validate_retract_source``.
    """
    import hashlib
    import json as _json
    return "retract_" + hashlib.sha256(_json.dumps(
        {"source_ref": source_ref, "reason": reason,
         "human_decision_ref": human_decision_ref},
        sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]


def _retract_source_record_decision(
    conn: Any, intent: Intent, clock: Callable[[], str], *,
    source_artifact_id: str, human_decision_ref: str, retraction_id: str,
    reason: str,
) -> str:
    """Write the ResearchDecision artifact + supersedes edge; return its id.

    HYGIENE-2 P3-8: extracted verbatim from ``_validate_retract_source``
    (Steps 1-2), inside the caller's transaction.
    """
    # ── Step 1: the ratified SourceRetracted event ──
    # ── Step 2: the ResearchDecision artifact + supersedes edge ──
    import hashlib
    import json as _json
    decision_artifact_id = f"rd-{retraction_id}"
    decision_content = _json.dumps({
        "schema_version": "1",
        "decision": "SOURCE_RETRACTED",
        "source_artifact_id": source_artifact_id,
        "human_decision_ref": human_decision_ref,
        "reason": reason,
        "proposed_by": intent.proposed_by,
    }, sort_keys=True, separators=(",", ":"))
    decision_hash = hashlib.sha256(
        decision_content.encode("utf-8")).hexdigest()
    conn.execute(
        "INSERT INTO artifacts "
        "(artifact_id, project_id, task_id, artifact_type, "
        " content_hash, size_bytes, storage_path, producer, "
        " metadata_json, created_at) "
        "VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)",
        (decision_artifact_id, intent.project_id,
         _S5_DECISION_ARTIFACT_TYPE, decision_hash,
         len(decision_content), "inline://research_decision",
         f"retract_source:{intent.proposed_by}",
         _json.dumps({"invalidation_marker": "INVALIDATED",
                      "decision": "SOURCE_RETRACTED",
                      "human_decision_ref": human_decision_ref}),
         clock()))
    conn.execute(
        "INSERT OR IGNORE INTO provenance_edges "
        "(artifact_id, upstream_id, edge_type, created_at) "
        "VALUES (?, ?, 'supersedes', ?)",
        (decision_artifact_id, source_artifact_id, clock()))
    return decision_artifact_id


def _retract_source_invalidate_cone(
    conn: Any, intent: Intent, clock: Callable[[], str], *,
    source_artifact_id: str, decision_artifact_id: str, retraction_id: str,
) -> tuple[list[str], list[str], list[str]]:
    """Invalidate the downstream cone + SUCCEEDED producing tasks.

    HYGIENE-2 P3-8: extracted verbatim from ``_validate_retract_source``
    (Step 3), inside the caller's transaction. Returns
    ``(cone, invalidated_artifacts, invalidated_tasks)`` in the original
    order.
    """
    import json as _json
    # ── Step 3: the dependency-class cone (Q-04 substrate) ──
    # Transitive downstream closure over the LIVE dependency-class
    # edges only — the artifact_blast_radius traversal (graph.py)
    # restricted to the S5 edge class; `supersedes`/`justifies` and
    # every non-dependency edge NEVER propagate invalidation.
    downstream: dict[str, list[str]] = {}
    rows = conn.execute(
        "SELECT e.upstream_id, e.artifact_id, e.edge_type "
        "FROM provenance_edges e "
        "JOIN artifacts a ON a.artifact_id = e.artifact_id "
        "WHERE a.project_id = ? AND e.edge_type IN (?,?,?)",
        (intent.project_id, *_S5_DEPENDENCY_EDGE_TYPES)).fetchall()
    # L2 read-path normalization: every stored upstream reference is
    # resolved to canonical artifact identities before matching. The
    # emitted downstream values are unchanged (project-JOIN-filtered
    # artifact rows), so project isolation is preserved by
    # construction; only previously-invisible-but-valid dependency
    # references newly participate. Unresolvable values resolve to
    # the empty set (fail-safe skip, the pre-existing posture).
    _l2_memo: dict = {}
    for r in rows:
        for canonical in sorted(_l2_resolve_upstream(
                conn, r["upstream_id"], r["edge_type"], _l2_memo)):
            downstream.setdefault(canonical, []).append(
                r["artifact_id"])
    cone = _s5_cone_closure(source_artifact_id, downstream)

    invalidated_artifacts: list[str] = []
    for artifact_id in cone:
        row = conn.execute(
            "SELECT metadata_json FROM artifacts "
            "WHERE artifact_id = ?", (artifact_id,)).fetchone()
        if row is None:
            continue
        import json as _mj
        try:
            meta = _mj.loads(row["metadata_json"]) if (
                row["metadata_json"]) else {}
        except ValueError:
            meta = {}
        if meta.get("invalidation_marker") == "INVALIDATED":
            continue  # already invalid — idempotent, no rewrite
        meta["invalidation_marker"] = "INVALIDATED"
        meta["invalidated_by"] = decision_artifact_id
        conn.execute(
            "UPDATE artifacts SET metadata_json = ? "
            "WHERE artifact_id = ?",
            (_json.dumps(meta), artifact_id))
        invalidated_artifacts.append(artifact_id)

    # Downstream tasks: every SUCCEEDED task that PRODUCED an
    # invalidated artifact transitions to the terminal INVALIDATED
    # status (archived-not-deleted; TaskInvalidated events). Tasks in
    # any other state are left to the existing lifecycle (INVALIDATED
    # is reachable only from SUCCEEDED — task_status.py).
    invalidated_tasks: list[str] = []
    for artifact_id in invalidated_artifacts:
        trow = conn.execute(
            "SELECT t.task_id, t.status FROM artifacts a "
            "JOIN tasks t ON t.task_id = a.task_id "
            "WHERE a.artifact_id = ? AND t.project_id = ?",
            (artifact_id, intent.project_id)).fetchone()
        if trow is None:
            continue
        if trow["status"] != TaskStatus.SUCCEEDED.value:
            continue
        conn.execute(
            "UPDATE tasks SET status = ?, completed_at = ? "
            "WHERE task_id = ?",
            (TaskStatus.INVALIDATED.value, clock(), trow["task_id"]))
        _append_event_to_db(
            conn, clock, EventType.TASK_INVALIDATED.value,
            project_id=intent.project_id, task_id=trow["task_id"],
            from_state=TaskStatus.SUCCEEDED.value,
            to_state=TaskStatus.INVALIDATED.value,
            correlation_id=retraction_id,
            caused_by=intent.proposed_by,
            reason=f"S5 cascade: source {source_artifact_id} retracted",
            payload={"source_artifact_id": source_artifact_id,
                     "retraction_id": retraction_id})
        invalidated_tasks.append(trow["task_id"])
    return cone, invalidated_artifacts, invalidated_tasks


def _retract_source_invalidate_curated(
    conn: Any, intent: Intent, clock: Callable[[], str], *,
    source_artifact_id: str, retraction_id: str,
    retracted_set: set[str],
) -> list[str]:
    """Invalidate ADMITTED curated entries whose basis intersects the set.

    HYGIENE-2 P3-8: extracted verbatim from ``_validate_retract_source``
    (Step 7), inside the caller's transaction.
    """
    # ── Step 7 (v6 §16.6): curated-knowledge follow-on ──
    # Chartered addition, INSIDE this same transaction: every ADMITTED
    # curated entry of this project whose stored retraction basis
    # intersects {source_artifact_id} ∪ cone is INVALIDATED —
    # deterministic curated_id ASC order, one CuratedKnowledgeInvalidated
    # per entry, all BEFORE the SourceRetracted emission. The predicate
    # consumes the cone EXACTLY as the existing walk produced it (the
    # known L2 identifier-form defect is untouched — future cone members
    # are recognized by the same predicate). Invalidate-on-ANY
    # (fail-closed, GAP-A D2).
    placeholders = ",".join("?" for _ in range(len(retracted_set)))
    curated_rows = conn.execute(
        "SELECT DISTINCT e.curated_id AS curated_id "
        "FROM curated_knowledge_entries e "
        "JOIN curated_knowledge_retraction_basis b "
        "  ON b.curated_id = e.curated_id "
        "WHERE e.status = 'ADMITTED' "
        "  AND e.source_project_id = ? "
        f"  AND b.evidence_artifact_id IN ({placeholders}) "
        "ORDER BY e.curated_id ASC",
        (intent.project_id, *sorted(retracted_set))).fetchall()
    invalidated_curated: list[str] = []
    for crow in curated_rows:
        curated_id = crow["curated_id"]
        basis_rows = conn.execute(
            "SELECT evidence_artifact_id "
            "FROM curated_knowledge_retraction_basis "
            "WHERE curated_id = ? "
            "ORDER BY evidence_artifact_id ASC",
            (curated_id,)).fetchall()
        matched = sorted(
            {r["evidence_artifact_id"] for r in basis_rows}
            & retracted_set)
        conn.execute(
            "UPDATE curated_knowledge_entries "
            "SET status = 'INVALIDATED', invalidation_event_ref = ? "
            "WHERE curated_id = ? AND status = 'ADMITTED'",
            (retraction_id, curated_id))
        _append_event_to_db(
            conn, clock, EventType.CURATED_KNOWLEDGE_INVALIDATED.value,
            project_id=intent.project_id,
            correlation_id=retraction_id,
            caused_by=intent.proposed_by,
            reason=(f"S5 retraction of {source_artifact_id} reached the "
                    f"curated entry's evidence basis"),
            payload={
                "curated_id": curated_id,
                "retraction_id": retraction_id,
                "source_artifact_id": source_artifact_id,
                "matched_evidence": matched,
            })
        invalidated_curated.append(curated_id)
    return sorted(invalidated_curated)


def _retract_source_supersede_contradictions(
    conn: Any, intent: Intent, clock: Callable[[], str], *,
    source_artifact_id: str, retraction_id: str,
    retracted_set: set[str],
) -> None:
    """Supersede OPEN contradictions with a party in the retracted set.

    HYGIENE-2 P3-8: extracted verbatim from ``_validate_retract_source``
    (CHG-1 follow-on), inside the caller's transaction.
    """
    # ── CHG-1 contradiction supersession follow-on ──
    # Additive consumer of retracted_set (the Step-7 curated-follow-on
    # precedent): every OPEN contradiction of this project with a
    # party in {source_artifact_id} ∪ cone is SUPERSEDED in this same
    # transaction (deterministic contradiction_id ASC order, one
    # ContradictionSuperseded event per row). S5 cone/edge/vocabulary
    # semantics are untouched — the predicate consumes the cone
    # exactly as produced.
    cx_placeholders = ",".join(
        "?" for _ in range(len(retracted_set)))
    cx_rows = conn.execute(
        "SELECT contradiction_id FROM contradictions "
        "WHERE project_id = ? AND status = 'OPEN' "
        f"  AND (party_a IN ({cx_placeholders}) "
        f"    OR party_b IN ({cx_placeholders})) "
        "ORDER BY contradiction_id ASC",
        (intent.project_id, *sorted(retracted_set),
         *sorted(retracted_set))).fetchall()
    for cx_row in cx_rows:
        cx_id = cx_row["contradiction_id"]
        conn.execute(
            "UPDATE contradictions SET status = 'SUPERSEDED' "
            "WHERE contradiction_id = ? AND status = 'OPEN'",
            (cx_id,))
        _append_event_to_db(
            conn, clock,
            EventType.CONTRADICTION_SUPERSEDED.value,
            project_id=intent.project_id,
            correlation_id=f"{cx_id}:superseded:{retraction_id}",
            caused_by=intent.proposed_by,
            reason=(f"S5 retraction of {source_artifact_id} retired "
                    f"a party of contradiction {cx_id}"),
            payload={"contradiction_id": cx_id,
                     "retraction_id": retraction_id,
                     "source_artifact_id": source_artifact_id})


def _retract_source_emit_retracted_event(
    conn: Any, intent: Intent, clock: Callable[[], str], *,
    source_ref: str, source_artifact_id: str, decision_artifact_id: str,
    human_decision_ref: str, retraction_id: str, reason: str,
    invalidated_artifacts: list[str], invalidated_tasks: list[str],
    invalidated_curated: list[str],
) -> None:
    """Emit the bounded S6 SourceRetracted event with the cone digest.

    HYGIENE-2 P3-8: extracted verbatim from ``_validate_retract_source``
    (S6 bounded retraction-fact payload), inside the caller's transaction.
    """
    # ── S6 bounded retraction-fact payload ──
    # The P3 SourceRetracted event carries the bounded retraction fact
    # plus a deterministic integrity commitment to the computed cone —
    # never the unbounded cone lists (S6: a sufficiently large
    # legitimate cone would otherwise exceed the 4 KiB S6 event cap
    # and make the source unretractable). ``s5-cone-v1`` means: S5
    # cone membership semantics over canonical sorted
    # artifact/task/curated lists, canonical JSON serialization
    # below, SHA-256 digest. Future cone-semantic changes require a
    # new algorithm identifier. The exact cone remains recoverable
    # from persisted state: artifacts via
    # ``invalidated_by = decision_artifact_id`` ordered by
    # artifact_id, tasks via TaskInvalidated ``correlation_id =
    # retraction_id``, curated entries via CuratedKnowledgeInvalidated
    # ``retraction_id``.
    import hashlib as _hashlib
    import json as _json
    cone_digest = _hashlib.sha256(_json.dumps(
        {"artifacts": sorted(invalidated_artifacts),
         "tasks": sorted(invalidated_tasks),
         "curated": sorted(invalidated_curated)},
        sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()
    _append_event_to_db(
        conn, clock, EventType.SOURCE_RETRACTED.value,
        project_id=intent.project_id,
        correlation_id=retraction_id,
        caused_by=intent.proposed_by,
        reason=reason,
        artifact_ids=[source_artifact_id],
        payload={
            "source_ref": source_ref,
            "source_artifact_id": source_artifact_id,
            "decision_artifact_id": decision_artifact_id,
            "human_decision_ref": human_decision_ref,
            "cone_algorithm": "s5-cone-v1",
            "cone_digest": cone_digest,
            "artifact_count": len(invalidated_artifacts),
            "task_count": len(invalidated_tasks),
            "curated_count": len(invalidated_curated),
        })


def _validate_retract_source(
    conn: Any, intent: Intent, *, clock: Callable[[], str],
    audit: AuditRecord | None = None,
) -> IntentResult:
    """RETRACT_SOURCE — the ratified S5 supersede-and-invalidate cascade
    (v6 §7/S5), implemented Step 5 per the Step 4 decision gate (verdict
    B: S5 READY).

    Authority: human-initiated per the §9.2 override discipline. The
    human has no agent profile; the deterministic layer ingests the
    ratified verdict through this internal intent (the
    ``record_operator_decision`` precedent, IDR-040 §3) — the payload
    therefore carries ``human_decision_ref`` and admission FAILS CLOSED
    unless it dereferences to a recorded HumanDecision event in this
    project whose payload BINDS this exact command — decision kind
    ``RETRACT_SOURCE``, the same ``source_ref`` and a ``reason_digest``
    over the same cited reason (the HumanDecisionReceived journal row is
    the evidence the human decision happened; no journal row or no
    binding, no cascade — a decision for another intent or another
    source never authorizes a retraction).

    The cascade (ONE atomic BEGIN IMMEDIATE transaction — a mid-cascade
    crash can never leave a partial invalidation):

      1. Emit the ratified ``SourceRetracted`` event (catalog member,
         events.py — never a second event type).
      2. Write the ``ResearchDecision`` artifact with a ``supersedes``
         edge to the retracted source (archived-not-deleted, §16.1).
      3. Mark every downstream artifact reachable via the LIVE
         dependency-class edges (cites / derived_from / used_as_input)
         ``INVALIDATED`` in artifact metadata (archived, never deleted),
         and transition every SUCCEEDED task that produced a directly
         invalidated artifact to the terminal INVALIDATED status
         (TaskInvalidated events; non-SUCCEEDED tasks are left to the
         existing lifecycle — INVALIDATED is reachable only from
         SUCCEEDED, task_status.py).
      4-5. §16.6 inadmissible-source screen + §21 vault projection:
         EXPLICITLY DEFERRED (Step 4 §8) — not implemented here.

    Idempotence: the deterministic correlation key
    ``retract:sha256(source_ref + human_decision_ref)`` makes an
    identical repeat admission return duplicate=True with ZERO semantic
    effects; a DIFFERENT second retraction of an already-invalidated
    source is refused STALE (the source is already superseded — a second
    decision artifact would double-supersede).

    Step 7 (v6 §16.6) curated follow-on — chartered addition, inside the
    SAME transaction: after the task-invalidation work and before the
    ``SourceRetracted`` emission, every ADMITTED curated-knowledge entry
    of this project whose stored retraction-basis intersects
    ``{source_artifact_id} ∪ cone`` is INVALIDATED (deterministic
    ``curated_id ASC`` order, one ``CuratedKnowledgeInvalidated`` event
    per entry) and the sorted invalidated curated_ids are folded into the
    ``SourceRetracted`` payload additively (``invalidated_curated_entries``).
    The cone algorithm itself, the dependency-edge vocabulary, and every
    existing identifier form are untouched (the known L2 provenance
    defect stays as-is — the predicate consumes the cone exactly as it
    is, so future cone members are recognized by the same predicate).

    Steps 4-5 boundary: this validator does NOT touch the §21 vault
    projection surface (does not exist); the S7 consumer/UI is deferred.
    """
    source_ref, reason, human_decision_ref = _retract_source_command(intent)
    _retract_source_binding(
        conn, intent, source_ref, reason, human_decision_ref)

    # Resolve the source (type-checked, in-project, fail-closed).
    source_artifact_id = _s5_source_artifact_id(
        conn, intent.project_id, source_ref)

    # Deterministic idempotency key (the EVIDENCE_TRANSITION precedent):
    # the FULL command {source_ref, reason, human_decision_ref} — an
    # identical repeat returns duplicate=True; any differing command
    # (e.g. a different cited reason) falls through to the STALE guard.
    retraction_id = _retract_source_id(
        source_ref, reason, human_decision_ref)

    # F9-class atomicity: idempotency check + cascade + event in ONE
    # BEGIN IMMEDIATE transaction.
    conn.execute("BEGIN IMMEDIATE")
    try:
        prior = conn.execute(
            "SELECT payload_json FROM events "
            "WHERE event_type = ? AND correlation_id = ? "
            "ORDER BY rowid LIMIT 1",
            (EventType.SOURCE_RETRACTED.value,
             retraction_id)).fetchone()
        if prior is not None:
            conn.execute("ROLLBACK")
            return IntentResult(
                kind=intent.kind,
                entity_type="artifact",
                entity_id=source_artifact_id,
                duplicate=True,
                row={"source_artifact_id": source_artifact_id,
                     "retraction_id": retraction_id},
                event_type=EventType.SOURCE_RETRACTED.value)

        # STALE guard: a DIFFERENT retraction of an already-retracted
        # source is refused — the source is already superseded; a second
        # decision artifact would double-supersede (one source, one
        # retraction). This ROLLBACK stays inside the BEGIN IMMEDIATE
        # owner below (HYGIENE-2: extracting it would create a second
        # rollback-only census participant).
        already = conn.execute(
            "SELECT event_id, payload_json FROM events "
            "WHERE event_type = ? AND correlation_id LIKE 'retract_%' "
            "AND payload_json LIKE ? ORDER BY rowid LIMIT 1",
            (EventType.SOURCE_RETRACTED.value,
             f'%{source_artifact_id}%')).fetchone()
        # The LIKE probe is a pre-filter only — the authoritative check
        # re-dereferences the artifact_id from the parsed payload (a hash
        # collision with an unrelated id can never decide STALE).
        if already is not None:
            import json as _sj
            try:
                prior_payload = _sj.loads(already["payload_json"])
            except ValueError:
                prior_payload = {}
            if prior_payload.get("source_artifact_id") == source_artifact_id:
                conn.execute("ROLLBACK")
                raise _reject(
                    intent.kind, STALE,
                    f"source artifact {source_artifact_id!r} is already "
                    f"retracted (event {already['event_id']}) — a source "
                    f"is retracted once; further cascades require a new "
                    f"superseding decision, not a second retraction")

        decision_artifact_id = _retract_source_record_decision(
            conn, intent, clock,
            source_artifact_id=source_artifact_id,
            human_decision_ref=human_decision_ref,
            retraction_id=retraction_id,
            reason=reason)

        cone, invalidated_artifacts, invalidated_tasks = (
            _retract_source_invalidate_cone(
                conn, intent, clock,
                source_artifact_id=source_artifact_id,
                decision_artifact_id=decision_artifact_id,
                retraction_id=retraction_id))

        retracted_set = {source_artifact_id} | set(cone)
        invalidated_curated = _retract_source_invalidate_curated(
            conn, intent, clock,
            source_artifact_id=source_artifact_id,
            retraction_id=retraction_id,
            retracted_set=retracted_set)

        _retract_source_supersede_contradictions(
            conn, intent, clock,
            source_artifact_id=source_artifact_id,
            retraction_id=retraction_id,
            retracted_set=retracted_set)

        _retract_source_emit_retracted_event(
            conn, intent, clock,
            source_ref=source_ref,
            source_artifact_id=source_artifact_id,
            decision_artifact_id=decision_artifact_id,
            human_decision_ref=human_decision_ref,
            retraction_id=retraction_id,
            reason=reason,
            invalidated_artifacts=invalidated_artifacts,
            invalidated_tasks=invalidated_tasks,
            invalidated_curated=invalidated_curated)
        if audit is not None:
            _append_event_to_db(
                conn, clock, audit.event_type,
                project_id=audit.project_id,
                correlation_id=audit.correlation_id,
                caused_by=audit.caused_by,
                reason=audit.reason,
                payload=audit.payload)
        conn.execute("COMMIT")
    except GatewayRejection:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise

    return IntentResult(
        kind=intent.kind,
        entity_type="artifact",
        entity_id=source_artifact_id,
        duplicate=False,
        row={"source_artifact_id": source_artifact_id,
             "decision_artifact_id": decision_artifact_id,
             "retraction_id": retraction_id,
             "invalidated_artifacts": invalidated_artifacts,
             "invalidated_tasks": invalidated_tasks,
             "invalidated_curated_entries": invalidated_curated},
        event_type=EventType.SOURCE_RETRACTED.value)


# ── Step 7 (v6 §16.6): CURATE_KNOWLEDGE — curated registry admission ──

# The payload contract (charter §9 check 3): exactly these keys — unknown
# keys are rejected (closed schema, never silently dropped).
_CURATE_KNOWLEDGE_PAYLOAD_KEYS = frozenset({
    "operation", "kind", "program_ref", "hypothesis_ref",
    "source_binding_ref", "source_decision_event_ref", "signature_json",
    "supersedes_ref", "human_decision_ref", "operator_id",
})


def _resolve_program_in_project(
    conn: Any, project_id: str, program_ref: str,
) -> dict | None:
    """Resolve a program ref (a bare ``program_id`` or a
    ``research_program:<content_hash>`` ref) to a project-scoped
    ``research_programs`` row, or None (the failure_classifications
    ``_resolve_program`` precedent)."""
    from hermes.persistence.repositories import _json_loads
    pid = program_ref_key(program_ref)
    if pid is None:
        return None
    row = conn.execute(
        "SELECT * FROM research_programs "
        "WHERE project_id = ? AND program_id = ?",
        (project_id, pid)).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT * FROM research_programs "
            "WHERE project_id = ? AND content_hash = ?",
            (project_id, pid)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["hypotheses"] = _json_loads(d.get("hypothesis_json")) or []
    return d


def _canonical_or_none(value: Any) -> str | None:
    """The canonical form of a linkage value (NFC → lowercase → strip), or
    None when the value is not a usable string (fail-closed linkage
    comparison — never a crash)."""
    import unicodedata
    if not isinstance(value, str):
        return None
    canonical = unicodedata.normalize("NFC", value).lower().strip()
    return canonical or None


def _validate_curate_knowledge(
    conn: Any, intent: Intent, *, clock: Callable[[], str],
    audit: AuditRecord | None = None,
) -> IntentResult:
    """CURATE_KNOWLEDGE — the Step 7 curated-knowledge registry admission
    (v6 §16.6), implemented per the Step 7E charter §9 ordering.

    Authority: a ratified operator decision (a recorded HumanDecision whose
    payload binds the full-command ``curation_id`` hash) admitted through
    this internal-only intent — the human has no agent profile; the
    deterministic layer ingests the verdict (the record_operator_decision
    precedent, IDR-040 §3). The validator FAILS CLOSED at every step;
    operator-supplied axes are NEVER authoritative (the signature is
    recomputed from the persisted FeatureBinding, the curated_id from the
    chartered formula, the evidence basis from the refuting classification's
    complete falsifying-evidence set).

    The admission is ONE atomic BEGIN IMMEDIATE transaction (charter §10):
    duplicate check → registry row → basis rows → (SUPERSEDE: supersession
    row + target status) → CuratedKnowledgeProposed → CuratedKnowledgeAdmitted
    → COMMIT. A crash before commit leaves no registry row, no basis rows,
    no admission events.
    """
    from hermes.persistence.event_validation import (
        DEFAULT_PAYLOAD_MAX_BYTES,
        EventValidationError,
        validate_payload_size,
    )
    from hermes.persistence.failure_classifications import (
        FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
        FAILURE_CLASSIFICATION_REF_PREFIX,
    )
    from hermes.research.evidence_ladder import (
        classification_content_matches,
    )
    from hermes.research.feature_binding import (
        CURATED_KIND_REFUTED_PATTERN,
        CURATION_OPERATIONS,
        FEATURE_BINDING_ARTIFACT_TYPE,
        FEATURE_BINDING_REF_PREFIX,
        MAX_EVIDENCE_BASIS_MEMBERS,
        FeatureBindingError,
        binding_content_hash,
        canonical_binding,
        curated_id_of,
        curation_command_hash,
        signature_from_binding,
    )

    kind = intent.kind

    # ── 1. Authorization: internal-only, DETERMINISTIC, never LLM-proposable
    # (defense-in-depth — apply_intent's role gate already enforced it).
    if kind not in IntentKind.internal_only():
        raise _reject(kind, ROLE, "CURATE_KNOWLEDGE is internal-only")
    if intent.proposed_by != "DETERMINISTIC":
        raise _reject(
            kind, ROLE,
            f"CURATE_KNOWLEDGE requires proposed_by='DETERMINISTIC', got "
            f"{intent.proposed_by!r}")
    if kind in IntentKind.llm_proposable():
        raise _reject(kind, ROLE, "CURATE_KNOWLEDGE is never LLM-proposable")

    # ── 2. Project exists.
    prow = conn.execute(
        "SELECT 1 FROM projects WHERE project_id = ?",
        (intent.project_id,)).fetchone()
    if prow is None:
        raise _reject(
            kind, PROJECT_NOT_FOUND,
            f"project {intent.project_id!r} does not exist — stale project "
            f"reference")

    # ── 3. Closed payload schema.
    payload = intent.payload
    if not isinstance(payload, dict):
        raise _reject(
            kind, MALFORMED_PAYLOAD,
            f"payload must be a dict, got {type(payload).__name__}")
    unknown = sorted(set(payload) - _CURATE_KNOWLEDGE_PAYLOAD_KEYS)
    if unknown:
        raise _reject(
            kind, MALFORMED_PAYLOAD,
            f"unknown payload keys {unknown} for CURATE_KNOWLEDGE")

    def _require_str(key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise _reject(
                kind, MALFORMED_PAYLOAD,
                f"payload.{key} must be a non-empty string")
        return value

    # ── 4. Operation is ADMIT or SUPERSEDE; kind is the closed registry
    # kind; the command fields are well-formed.
    operation = _require_str("operation")
    if operation not in CURATION_OPERATIONS:
        raise _reject(
            kind, MALFORMED_PAYLOAD,
            f"payload.operation {operation!r} must be one of "
            f"{sorted(CURATION_OPERATIONS)}")
    entry_kind = _require_str("kind")
    if entry_kind != CURATED_KIND_REFUTED_PATTERN:
        raise _reject(
            kind, MALFORMED_PAYLOAD,
            f"payload.kind {entry_kind!r} — the only chartered registry "
            f"kind is {CURATED_KIND_REFUTED_PATTERN!r}")
    program_ref = _require_str("program_ref")
    hypothesis_ref = _require_str("hypothesis_ref")
    source_binding_ref = _require_str("source_binding_ref")
    source_decision_event_ref = _require_str("source_decision_event_ref")
    signature_json = _require_str("signature_json")
    human_decision_ref = _require_str("human_decision_ref")
    operator_id = _require_str("operator_id")
    supersedes_ref = payload.get("supersedes_ref")
    if supersedes_ref is None:
        supersedes_ref = ""
    if not isinstance(supersedes_ref, str):
        raise _reject(
            kind, MALFORMED_PAYLOAD,
            "payload.supersedes_ref must be a string or absent")
    if operation == "ADMIT" and supersedes_ref:
        raise _reject(
            kind, MALFORMED_PAYLOAD,
            "payload.supersedes_ref must be absent for ADMIT — a "
            "supersession link belongs to SUPERSEDE only")
    if operation == "SUPERSEDE" and not supersedes_ref:
        raise _reject(
            kind, MALFORMED_PAYLOAD,
            "payload.supersedes_ref is required for SUPERSEDE")

    # ── 5. Event/payload bounds pass existing validation (the F3
    # precedent: pre-validate BEFORE any work — an oversized command fails
    # here with a structured refusal, never at the event boundary mid-write).
    try:
        validate_payload_size(payload, max_bytes=DEFAULT_PAYLOAD_MAX_BYTES)
    except EventValidationError as exc:
        raise _reject(
            kind, MALFORMED_PAYLOAD,
            f"command payload exceeds the event bounds: {exc}") from None

    # ── 6. Resolve HumanDecisionReceived by event ID or correlation ID
    # (project-scoped, fail-closed — the S5 dereference precedent).
    decision_row = conn.execute(
        "SELECT event_id, correlation_id, payload_json FROM events "
        "WHERE project_id = ? AND event_type = ? "
        "AND (event_id = ? OR correlation_id = ?) "
        "ORDER BY rowid LIMIT 1",
        (intent.project_id, EventType.HUMAN_DECISION_RECEIVED.value,
         human_decision_ref, human_decision_ref)).fetchone()
    if decision_row is None:
        raise _reject(
            kind, PROPOSAL,
            f"payload.human_decision_ref {human_decision_ref!r} does not "
            f"dereference to a recorded HumanDecision in project "
            f"{intent.project_id!r} — CURATE_KNOWLEDGE requires a recorded "
            f"HumanDecision (v6 §16.6)")

    # ── 7. The decision's curation_id must equal the computed full-command
    # correlation hash (the payload-binding precedent: proposal_id in
    # _validate_resolve_classification_proposal). The operator approved THIS
    # exact command — any drift fails closed.
    import json as _json
    try:
        decision_payload = _json.loads(decision_row["payload_json"] or "{}")
    except ValueError:
        decision_payload = {}
    if not isinstance(decision_payload, dict):
        decision_payload = {}
    command_hash = curation_command_hash(payload)
    if decision_payload.get("curation_id") != command_hash:
        raise _reject(
            kind, PROPOSAL,
            f"the recorded HumanDecision {human_decision_ref!r} binds "
            f"curation_id {decision_payload.get('curation_id')!r}, not the "
            f"computed full-command hash {command_hash!r} — the decision "
            f"does not ratify this command")

    # ── 8. Resolve the program in the project.
    program = _resolve_program_in_project(
        conn, intent.project_id, program_ref)
    if program is None:
        raise _reject(
            kind, PROVENANCE,
            f"program_ref {program_ref!r} does not resolve to a research "
            f"program in project {intent.project_id!r}")
    program_id = str(program.get("program_id") or "")

    # ── 9. The hypothesis exists in that program (exact ref match —
    # fail-closed, no normalization at resolution).
    hypotheses = program.get("hypotheses") or []
    if not any(isinstance(h, dict) and h.get("ref") == hypothesis_ref
               for h in hypotheses):
        raise _reject(
            kind, PROVENANCE,
            f"hypothesis_ref {hypothesis_ref!r} does not exist in program "
            f"{program_id!r}")

    # ── 10. The ladder head for (program_id, hypothesis_ref) is REFUTED.
    ladder_row = conn.execute(
        "SELECT rung FROM evidence_ladder_state "
        "WHERE project_id = ? AND program_id = ? AND hypothesis_ref = ? "
        "ORDER BY version DESC LIMIT 1",
        (intent.project_id, program_id, hypothesis_ref)).fetchone()
    if ladder_row is None or ladder_row["rung"] != "REFUTED":
        raise _reject(
            kind, STALE,
            f"the ladder head for program {program_id!r} hypothesis "
            f"{hypothesis_ref!r} is "
            f"{ladder_row['rung'] if ladder_row else '(none)'} — only a "
            f"REFUTED head is curatable")

    # ── 11. Resolve EvidenceTransitionApplied by the source decision event
    # ref (event_id or correlation_id, project-scoped, fail-closed).
    transition_row = conn.execute(
        "SELECT event_id, correlation_id, to_state, payload_json "
        "FROM events "
        "WHERE project_id = ? AND event_type = ? "
        "AND (event_id = ? OR correlation_id = ?) "
        "ORDER BY rowid LIMIT 1",
        (intent.project_id, EventType.EVIDENCE_TRANSITION_APPLIED.value,
         source_decision_event_ref, source_decision_event_ref)).fetchone()
    if transition_row is None:
        raise _reject(
            kind, PROPOSAL,
            f"source_decision_event_ref {source_decision_event_ref!r} does "
            f"not dereference to an EvidenceTransitionApplied event in "
            f"project {intent.project_id!r}")

    # ── 12. The resolved transition must be the terminal REFUTED apply.
    if transition_row["to_state"] != "REFUTED":
        raise _reject(
            kind, STALE,
            f"source decision event {transition_row['correlation_id']!r} "
            f"applied to_state {transition_row['to_state']!r}, not REFUTED")

    # ── 13. Extract source_decision_event_ref (canonical form) +
    # classification_ref; the transition must target THIS program/hypothesis
    # (the §3 hypothesis-identity contract).
    try:
        transition_payload = _json.loads(transition_row["payload_json"]
                                         or "{}")
    except ValueError:
        transition_payload = {}
    if not isinstance(transition_payload, dict):
        transition_payload = {}
    if (transition_payload.get("program_id") != program_id
            or transition_payload.get("hypothesis_ref") != hypothesis_ref):
        raise _reject(
            kind, PROVENANCE,
            f"source decision event {transition_row['correlation_id']!r} "
            f"targets program/hypothesis "
            f"({transition_payload.get('program_id')!r}, "
            f"{transition_payload.get('hypothesis_ref')!r}), not "
            f"({program_id!r}, {hypothesis_ref!r})")
    canonical_decision_ref = str(transition_row["correlation_id"])
    classification_ref = transition_payload.get("classification_ref")
    if (not isinstance(classification_ref, str)
            or not classification_ref.startswith(
                FAILURE_CLASSIFICATION_REF_PREFIX)):
        raise _reject(
            kind, PROPOSAL,
            f"source decision event {canonical_decision_ref!r} carries no "
            f"dereferenceable classification_ref — the refutation's "
            f"provenance carrier is missing")

    # ── 14. Resolve the FeatureBinding (prefixed ref form, project-scoped).
    if not source_binding_ref.startswith(FEATURE_BINDING_REF_PREFIX):
        raise _reject(
            kind, MALFORMED_PAYLOAD,
            f"payload.source_binding_ref must be "
            f"'{FEATURE_BINDING_REF_PREFIX}<content_hash>'")
    binding_hash = source_binding_ref[len(FEATURE_BINDING_REF_PREFIX):]
    if not binding_hash:
        raise _reject(
            kind, MALFORMED_PAYLOAD,
            "payload.source_binding_ref has an empty content hash")
    binding_row = conn.execute(
        "SELECT artifact_id, artifact_type, content_hash, metadata_json "
        "FROM artifacts WHERE project_id = ? AND content_hash = ?",
        (intent.project_id, binding_hash)).fetchone()
    if binding_row is None:
        raise _reject(
            kind, EVIDENCE_REF,
            f"source_binding_ref {source_binding_ref!r} does not resolve "
            f"in project {intent.project_id!r}")

    # ── 15. The resolved artifact must BE a feature_binding.
    if binding_row["artifact_type"] != FEATURE_BINDING_ARTIFACT_TYPE:
        raise _reject(
            kind, EVIDENCE_REF,
            f"source_binding_ref {source_binding_ref!r} names artifact "
            f"type {binding_row['artifact_type']!r}, not "
            f"{FEATURE_BINDING_ARTIFACT_TYPE!r}")

    # ── 16. Verify canonical binding content/hash (F13 discipline: the
    # stored metadata must RE-DERIVE the row's authoritative content hash —
    # any axis rewrite changes the derived hash and is refused as forged).
    try:
        binding_meta = _json.loads(binding_row["metadata_json"] or "{}")
    except ValueError:
        raise _reject(
            kind, EVIDENCE_REF,
            f"FeatureBinding {binding_row['artifact_id']!r} has corrupt "
            f"metadata — cannot canonicalize") from None
    if not isinstance(binding_meta, dict):
        raise _reject(
            kind, EVIDENCE_REF,
            f"FeatureBinding {binding_row['artifact_id']!r} metadata is "
            f"not a mapping")
    try:
        canonical = canonical_binding(binding_meta)
        recomputed_hash = binding_content_hash(binding_meta)
    except FeatureBindingError as exc:
        raise _reject(
            kind, EVIDENCE_REF,
            f"FeatureBinding {binding_row['artifact_id']!r} fails "
            f"canonicalization: {exc}") from None
    if recomputed_hash != binding_row["content_hash"]:
        raise _reject(
            kind, EVIDENCE_REF,
            f"FeatureBinding {binding_row['artifact_id']!r} metadata does "
            f"not re-derive its content hash — forged or corrupt binding")

    # ── 17. Verify binding project/program/hypothesis linkage (canonical
    # comparison — the binding's refs are stored canonical).
    if (_canonical_or_none(canonical["project_ref"])
            != _canonical_or_none(intent.project_id)):
        raise _reject(
            kind, PROVENANCE,
            f"FeatureBinding {binding_row['artifact_id']!r} was produced "
            f"for project {canonical['project_ref']!r}, not "
            f"{intent.project_id!r} — cross-project binding admission is "
            f"refused")
    if (_canonical_or_none(canonical["program_ref"])
            != _canonical_or_none(program_id)):
        raise _reject(
            kind, PROVENANCE,
            f"FeatureBinding {binding_row['artifact_id']!r} was produced "
            f"for program {canonical['program_ref']!r}, not "
            f"{program_id!r}")
    if (_canonical_or_none(canonical["hypothesis_ref"])
            != _canonical_or_none(hypothesis_ref)):
        raise _reject(
            kind, PROVENANCE,
            f"FeatureBinding {binding_row['artifact_id']!r} was produced "
            f"for hypothesis {canonical['hypothesis_ref']!r}, not "
            f"{hypothesis_ref!r}")

    # ── 18. Resolve the classification (project-scoped, by content hash).
    cls_hash = classification_ref[len(FAILURE_CLASSIFICATION_REF_PREFIX):]
    cls_row = conn.execute(
        "SELECT artifact_id, content_hash, metadata_json FROM artifacts "
        "WHERE project_id = ? AND artifact_type = ? AND content_hash = ?",
        (intent.project_id, FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
         cls_hash)).fetchone()
    if cls_row is None:
        raise _reject(
            kind, EVIDENCE_REF,
            f"classification {classification_ref!r} does not resolve in "
            f"project {intent.project_id!r}")

    # ── 19. The classification metadata agrees with program/hypothesis
    # (digest-valid identity + F13 content integrity + target agreement).
    try:
        cls_meta = _json.loads(cls_row["metadata_json"] or "{}")
    except ValueError:
        raise _reject(
            kind, EVIDENCE_REF,
            f"classification {cls_row['artifact_id']!r} has corrupt "
            f"metadata") from None
    if not isinstance(cls_meta, dict):
        raise _reject(
            kind, EVIDENCE_REF,
            f"classification {cls_row['artifact_id']!r} metadata is not "
            f"a mapping")
    if cls_meta.get("classification_id") != cls_row["artifact_id"]:
        raise _reject(
            kind, EVIDENCE_REF,
            f"classification {cls_row['artifact_id']!r} fails the "
            f"digest-valid identity check — forged classification")
    if not classification_content_matches(
            cls_meta, intent.project_id, str(cls_row["content_hash"] or "")):
        raise _reject(
            kind, EVIDENCE_REF,
            f"classification {cls_row['artifact_id']!r} metadata does not "
            f"re-derive its content hash — forged or corrupt")
    if cls_meta.get("hypothesis_ref") != hypothesis_ref:
        raise _reject(
            kind, PROVENANCE,
            f"classification {cls_row['artifact_id']!r} targets hypothesis "
            f"{cls_meta.get('hypothesis_ref')!r}, not {hypothesis_ref!r}")
    cls_program_ref = cls_meta.get("program_ref")
    cls_pid = program_ref_key(cls_program_ref) or ""
    if cls_pid not in (program_id, str(program.get("content_hash") or "")):
        raise _reject(
            kind, PROVENANCE,
            f"classification {cls_row['artifact_id']!r} targets program "
            f"{cls_program_ref!r}, not {program_id!r}")

    # ── 20. Extract the COMPLETE falsifying_evidence_refs (the
    # classification is a provenance carrier — advisory, never evidence;
    # the refs it carries are the retraction-basis source).
    evidence_refs = cls_meta.get("falsifying_evidence_refs")
    if not isinstance(evidence_refs, list) or not all(
            isinstance(r, str) for r in evidence_refs):
        raise _reject(
            kind, EVIDENCE_REF,
            f"classification {cls_row['artifact_id']!r} carries no "
            f"well-formed falsifying_evidence_refs — the retraction basis "
            f"cannot be derived")

    # ── 21/22. Resolve EVERY evidence ref into a bare artifact_id with
    # project ownership (the _source_artifact_resolves convention —
    # prefixed '<type>:<hash>' resolved project-scoped; the bare id comes
    # from the global content_hash UNIQUE row). Never store the prefixed
    # ref; never infer or invent missing provenance.
    evidence_basis: set[str] = set()
    for ref in evidence_refs:
        artifact_type, sep, content_hash = ref.partition(":")
        if not sep or not artifact_type or not content_hash:
            raise _reject(
                kind, EVIDENCE_REF,
                f"falsifying evidence ref {ref!r} is not a typed "
                f"'<artifact_type>:<content_hash>' ref — cannot resolve")
        if not _source_artifact_resolves(
                conn, intent.project_id, content_hash, artifact_type):
            raise _reject(
                kind, EVIDENCE_REF,
                f"falsifying evidence ref {ref!r} does not resolve in "
                f"project {intent.project_id!r} — unresolved or "
                f"cross-project evidence is refused")
        arow = conn.execute(
            "SELECT artifact_id FROM artifacts "
            "WHERE content_hash = ? AND artifact_type = ?",
            (content_hash, artifact_type)).fetchone()
        if arow is None:
            raise _reject(
                kind, EVIDENCE_REF,
                f"falsifying evidence ref {ref!r} resolved but has no "
                f"artifact row — inconsistent state")
        evidence_basis.add(arow["artifact_id"])

    # ── 23. Reject empty evidence.
    if not evidence_basis:
        raise _reject(
            kind, EVIDENCE_REF,
            "the refuting classification carries an empty "
            "falsifying-evidence set — REFUTED_PATTERN curation requires "
            "a non-empty retraction basis (fail-closed)")

    # ── 24. Reject more than 32 evidence artifacts (keeps the admission
    # event inside the 4096-byte journal cap without ever truncating).
    if len(evidence_basis) > MAX_EVIDENCE_BASIS_MEMBERS:
        raise _reject(
            kind, EVIDENCE_REF,
            f"the retraction basis has {len(evidence_basis)} members — "
            f"above the {MAX_EVIDENCE_BASIS_MEMBERS}-member bound")
    basis_sorted = sorted(evidence_basis)

    # ── 25/26. Recompute the signature from the PERSISTED binding and
    # compare against the submitted one (operator-supplied axes are never
    # authoritative).
    try:
        recomputed_signature = signature_from_binding(binding_meta)
    except FeatureBindingError as exc:
        raise _reject(
            kind, EVIDENCE_REF,
            f"FeatureBinding {binding_row['artifact_id']!r} cannot yield "
            f"a signature: {exc}") from None
    if signature_json != recomputed_signature:
        raise _reject(
            kind, MALFORMED_PAYLOAD,
            "payload.signature_json does not equal the signature "
            "recomputed from the persisted FeatureBinding — "
            "operator-supplied signatures are never authoritative")

    # ── 27. Recompute the curated_id (chartered formula — the binding ref
    # is provenance, not identity).
    curated_id = curated_id_of(
        entry_kind, recomputed_signature, canonical_decision_ref)

    # The admission event payloads (charter §8) — validated against the
    # journal cap BEFORE the transaction (never truncate evidence; the
    # 32-member bound keeps the basis inside the cap).
    admission_payload = {
        "curated_id": curated_id,
        "kind": entry_kind,
        "operation": operation,
        "signature_json": recomputed_signature,
        "source_binding_ref": binding_row["artifact_id"],
        "source_decision_event_ref": canonical_decision_ref,
        "program_ref": program_id,
        "hypothesis_ref": hypothesis_ref,
        "admission_decision_ref": human_decision_ref,
        "evidence_basis": basis_sorted,
        "operator_id": operator_id,
        "supersedes_ref": supersedes_ref,
    }
    proposed_payload = {
        "operation": operation,
        "kind": entry_kind,
        "program_ref": program_ref,
        "hypothesis_ref": hypothesis_ref,
        "source_binding_ref": source_binding_ref,
        "source_decision_event_ref": source_decision_event_ref,
        "signature_json": signature_json,
        "supersedes_ref": supersedes_ref,
        "human_decision_ref": human_decision_ref,
        "operator_id": operator_id,
    }
    try:
        validate_payload_size(admission_payload,
                              max_bytes=DEFAULT_PAYLOAD_MAX_BYTES)
        validate_payload_size(proposed_payload,
                              max_bytes=DEFAULT_PAYLOAD_MAX_BYTES)
    except EventValidationError as exc:
        raise _reject(
            kind, MALFORMED_PAYLOAD,
            f"the admission event payload exceeds the journal cap without "
            f"truncation possible: {exc}") from None

    # ── 29–31 + charter §10: the atomic admission transaction — duplicate
    # check → registry row → basis rows → (supersession) → Proposed →
    # Admitted → COMMIT. One-verdict discipline rides the extended
    # idx_events_one_verdict (migration 15) as the schema backstop.
    #
    # The duplicate check runs FIRST inside the transaction (the S5
    # precedent: duplicate precedes the STALE guard). An identical SUPERSEDE
    # replay must return duplicate=True with ZERO effects — the target it
    # names is already SUPERSEDED by the original, so the state-dependent
    # target check (28) would wrongly refuse the replay as STALE. Charter
    # §11 "duplicate replay must have zero effects" + §14 "replay consistent
    # with existing journal semantics" resolve the ordering.
    conn.execute("BEGIN IMMEDIATE")
    try:
        prior = conn.execute(
            "SELECT payload_json FROM events "
            "WHERE event_type = ? AND correlation_id = ? "
            "ORDER BY rowid LIMIT 1",
            (EventType.CURATED_KNOWLEDGE_ADMITTED.value,
             command_hash)).fetchone()
        if prior is not None:
            try:
                prior_payload = _json.loads(prior["payload_json"])
            except ValueError:
                prior_payload = {}
            conn.execute("ROLLBACK")
            if (isinstance(prior_payload, dict)
                    and prior_payload.get("curated_id") == curated_id
                    and prior_payload.get("operation") == operation):
                # Identical repeat — idempotent, ZERO effects.
                return IntentResult(
                    kind=kind, entity_type="curated_knowledge_entry",
                    entity_id=curated_id, duplicate=True,
                    row={"curated_id": curated_id, "operation": operation,
                         "curation_id": command_hash},
                    event_type=EventType.CURATED_KNOWLEDGE_ADMITTED.value)
            # A contradictory terminal decision on the same correlation —
            # refused (one command, one admission).
            raise _reject(
                kind, PROPOSAL,
                f"curation command {command_hash!r} already admitted a "
                f"different entry — a contradictory terminal decision is "
                f"refused")

        # ── 28. SUPERSEDE: the target must exist, be ADMITTED, and be the
        # current head (no supersession row may name it as superseded — a
        # stale/tampered target fails closed). Runs AFTER the duplicate
        # check so an identical replay is never misread as STALE.
        if operation == "SUPERSEDE":
            target_row = conn.execute(
                "SELECT curated_id, status FROM curated_knowledge_entries "
                "WHERE source_project_id = ? AND curated_id = ?",
                (intent.project_id, supersedes_ref)).fetchone()
            if target_row is None:
                conn.execute("ROLLBACK")
                raise _reject(
                    kind, STALE,
                    f"supersession target {supersedes_ref!r} does not exist "
                    f"in project {intent.project_id!r}")
            if target_row["status"] != "ADMITTED":
                conn.execute("ROLLBACK")
                raise _reject(
                    kind, STALE,
                    f"supersession target {supersedes_ref!r} is "
                    f"{target_row['status']!r}, not ADMITTED — only an "
                    f"ADMITTED entry is supersedeable")
            already_superseded = conn.execute(
                "SELECT 1 FROM curated_knowledge_supersession "
                "WHERE supersedes_ref = ? LIMIT 1",
                (supersedes_ref,)).fetchone()
            if already_superseded is not None:
                conn.execute("ROLLBACK")
                raise _reject(
                    kind, STALE,
                    f"supersession target {supersedes_ref!r} is not the "
                    f"current head — it is already superseded")
            if supersedes_ref == curated_id:
                conn.execute("ROLLBACK")
                raise _reject(
                    kind, STALE,
                    "an entry cannot supersede itself")

        # The curated identity is content-derived (kind + signature +
        # source decision event ref): a DIFFERENT command can still derive
        # the SAME curated_id (same refutation, same binding, new decision
        # event). The registry already holding that identity is a duplicate
        # admission — refused structurally, never a raw integrity crash.
        existing_entry = conn.execute(
            "SELECT status FROM curated_knowledge_entries "
            "WHERE curated_id = ? LIMIT 1", (curated_id,)).fetchone()
        if existing_entry is not None:
            conn.execute("ROLLBACK")
            raise _reject(
                kind, PROPOSAL,
                f"curated identity {curated_id!r} is already in the "
                f"registry (status {existing_entry['status']!r}) — a "
                f"second admission of the same identity is refused")

        ts = clock()
        # 2. registry entry insert
        conn.execute(
            "INSERT INTO curated_knowledge_entries "
            "(curated_id, kind, signature_json, source_project_id, "
            " source_binding_ref, source_decision_event_ref, program_ref, "
            " hypothesis_ref, admission_event_ref, admission_decision_ref, "
            " admitted_at, status, invalidation_event_ref) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ADMITTED', NULL)",
            (curated_id, entry_kind, recomputed_signature,
             intent.project_id, binding_row["artifact_id"],
             canonical_decision_ref, program_id, hypothesis_ref,
             command_hash, human_decision_ref, ts))
        # 3. basis-row inserts (sorted — deterministic write order)
        for evidence_artifact_id in basis_sorted:
            conn.execute(
                "INSERT INTO curated_knowledge_retraction_basis "
                "(curated_id, evidence_artifact_id) VALUES (?, ?)",
                (curated_id, evidence_artifact_id))
        # SUPERSEDE: the supersession row + the target's status flip,
        # atomic with the new entry.
        if operation == "SUPERSEDE":
            conn.execute(
                "INSERT INTO curated_knowledge_supersession "
                "(new_curated_id, supersedes_ref, supersession_event_ref) "
                "VALUES (?, ?, ?)",
                (curated_id, supersedes_ref, command_hash))
            conn.execute(
                "UPDATE curated_knowledge_entries "
                "SET status = 'SUPERSEDED' "
                "WHERE curated_id = ? AND status = 'ADMITTED'",
                (supersedes_ref,))
        # 4. CuratedKnowledgeProposed
        _append_event_to_db(
            conn, clock, EventType.CURATED_KNOWLEDGE_PROPOSED.value,
            project_id=intent.project_id,
            correlation_id=command_hash,
            caused_by=intent.proposed_by,
            reason=f"curated knowledge {operation} proposed for "
                   f"hypothesis {hypothesis_ref!r}",
            payload=proposed_payload)
        # 5. CuratedKnowledgeAdmitted
        # R-2/B3: the admission carries the SHARED source-artifact refs —
        # the stored retraction basis — in artifact_ids_json, additively
        # (every payload key/value is unchanged). The S5 predicate consumes
        # the same basis rows and the retraction producers (gateway S5
        # cascade and the Controller audit event) name the same artifact
        # ids, so a journal-only derived view (the vault projector) can
        # match a later SourceRetracted/CuratedKnowledgeInvalidated to this
        # admission without consulting the registry tables.
        _append_event_to_db(
            conn, clock, EventType.CURATED_KNOWLEDGE_ADMITTED.value,
            project_id=intent.project_id,
            correlation_id=command_hash,
            caused_by=intent.proposed_by,
            reason=f"curated knowledge {operation} admitted: {curated_id}",
            artifact_ids=basis_sorted,
            payload=admission_payload)
        # 6. commit
        if audit is not None:
            _append_event_to_db(
                conn, clock, audit.event_type,
                project_id=audit.project_id,
                correlation_id=audit.correlation_id,
                caused_by=audit.caused_by,
                reason=audit.reason,
                payload=audit.payload)
        conn.execute("COMMIT")
    except GatewayRejection:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise

    return IntentResult(
        kind=kind, entity_type="curated_knowledge_entry",
        entity_id=curated_id, duplicate=False,
        row={"curated_id": curated_id, "operation": operation,
             "kind": entry_kind, "signature_json": recomputed_signature,
             "curation_id": command_hash,
             "evidence_basis": basis_sorted,
             "supersedes_ref": supersedes_ref},
        event_type=EventType.CURATED_KNOWLEDGE_ADMITTED.value)


# ── CHG-1 contradiction lifecycle ──
#
# A contradiction is a relation between exactly two admitted
# classification artifacts (CLASSIFICATION_CONFLICT): same project,
# program, and hypothesis, different failure classes, both digest-valid,
# neither invalidated, with non-empty resolved evidence overlap. The
# contradiction table is derived working state (identity and active
# status recompute from classifications + evidence + markers); the
# journal events remain the audit truth.

_CONTRADICTION_TYPE = "CLASSIFICATION_CONFLICT"

_RECORD_CONTRADICTION_PAYLOAD_KEYS = frozenset(
    {"party_a", "party_b", "detector_version", "supersedes_ref"})

_RESOLVE_CONTRADICTION_PAYLOAD_KEYS = frozenset(
    {"contradiction_id", "human_decision_ref", "operator_id"})


def _cx_resolve_evidence_ref(conn: Any, project_id: str, ref: Any,
                             ) -> str | None:
    """Resolve one classification evidence ref to a bare artifact_id.

    Recognized typed forms only (the Step-7 basis-derivation discipline):
    ``source_result/source_payload/source_search/failure_classification/
    feature_binding:<content_hash>`` via project-scoped content lookup;
    ``evidence:<content_hash>`` likewise against type-``evidence`` rows
    (NOT the EVIDENCE_TRANSITION bare-ID convention, which belongs to
    that intent's contract alone). Anything else (deferred carriers,
    unknown prefixes, malformed, missing rows) resolves to None —
    fail-safe skip, never an exception. A currently retracted source
    (N9 — S5 retraction state) likewise resolves to None: retracted
    evidence is inadmissible for contradiction qualification.
    """
    if not isinstance(ref, str) or not ref:
        return None
    prefix, sep, rest = ref.partition(":")
    if not sep or not prefix or not rest:
        return None
    lookup_type = "evidence" if prefix == "evidence" else prefix
    if prefix not in ("evidence", "source_result", "source_payload",
                      "source_search", "failure_classification",
                      "feature_binding"):
        return None
    row = conn.execute(
        "SELECT artifact_id FROM artifacts "
        "WHERE project_id = ? AND content_hash = ? "
        "AND artifact_type = ? ORDER BY created_at LIMIT 1",
        (project_id, rest, lookup_type)).fetchone()
    if row is None:
        return None
    if source_artifact_retracted(conn, project_id, row["artifact_id"]):
        return None
    # IDR-046 D2/E4 — web-derived rows are barred from every evidence
    # position: a resolved row whose providers intersect
    # WEB_SEARCH_PROVIDERS contributes nothing (fail-safe skip).
    if source_artifact_is_web_derived(conn, row["artifact_id"]):
        return None
    return row["artifact_id"]


def _cx_classification_facts(conn: Any, project_id: str, artifact_id: str,
                             ) -> dict | None:
    """Digest-validity facts for one classification artifact, or None.

    Returns ``{program_ref, hypothesis_ref, failure_class, evidence}``
    with evidence as the sorted resolved bare artifact-ID set. None when
    the row is missing, foreign, mistyped, corrupt, forged
    (identity/content-hash mismatch), or invalidation-marked. F2: stored
    fields are verified against content identity, never trusted alone.
    """
    from hermes.research.evidence_ladder import classification_content_matches
    from hermes.research.failure_classification import FailureClass
    row = conn.execute(
        "SELECT artifact_id, artifact_type, content_hash, metadata_json "
        "FROM artifacts WHERE artifact_id = ? AND project_id = ?",
        (artifact_id, project_id)).fetchone()
    if row is None or row["artifact_type"] != "failure_classification":
        return None
    import json as _json
    try:
        meta = _json.loads(row["metadata_json"] or "{}")
    except ValueError:
        return None
    if not isinstance(meta, dict):
        return None
    if meta.get("classification_id") != row["artifact_id"]:
        return None
    if not classification_content_matches(
            meta, project_id, str(row["content_hash"] or "")):
        return None
    try:
        failure_class = FailureClass(meta.get("failure_class"))
    except (ValueError, TypeError):
        return None
    if meta.get("invalidation_marker") == "INVALIDATED":
        return None
    refs = meta.get("evidence_refs")
    if not isinstance(refs, list):
        return None
    evidence = set()
    for ref in refs:
        resolved = _cx_resolve_evidence_ref(conn, project_id, ref)
        if resolved is not None:
            evidence.add(resolved)
    program_ref = meta.get("program_ref")
    hypothesis_ref = meta.get("hypothesis_ref")
    if not isinstance(program_ref, str) or not program_ref:
        return None
    if not isinstance(hypothesis_ref, str) or not hypothesis_ref:
        return None
    return {"program_ref": program_ref, "hypothesis_ref": hypothesis_ref,
            "failure_class": failure_class.value, "evidence": evidence}


def _opened_rounds(conn: Any, project_id: str) -> list[dict]:
    """Every opened verification round in the project, oldest first.

    The round's record IS its journal event (OPS-5Z Group E): no new table,
    no new acquisition owner. A corrupt record is not skipped — the caller
    refuses fail-closed, because a budget check that cannot see a round is
    not a budget.
    """
    import json as _json

    rounds: list[dict] = []
    rows = EventRepository(conn).list_for_project(project_id)
    for row in rows:
        if row.get("event_type") != EventType.VERIFICATION_ROUND_OPENED.value:
            continue
        try:
            payload = _json.loads(row.get("payload_json") or "{}")
        except ValueError:
            raise ValueError(
                "the journal holds an unreadable verification-round record; "
                "refusing to open another") from None
        if not isinstance(payload, dict):
            raise ValueError(
                "the journal holds a malformed verification-round record; "
                "refusing to open another")
        rounds.append(payload)
    return rounds


def _validate_request_additional_experiment(
    conn: Any, intent: Intent, *, clock: Callable[[], str],
    audit: AuditRecord | None = None,
) -> IntentResult:
    """REQUEST_ADDITIONAL_EXPERIMENT — a conflict opens one bounded round.

    OPS-5Z Group E. The critic proposes; this validator decides. The payload
    is closed and parsed by ``hermes.research.verification`` (claims,
    conflict, mode, targets); the mode is checked against the claims' own
    declared sources. The round's identity is content-derived from the claim
    refs and the disputed question, and the **budget is one round per
    claim**: any prior round that names either claim refuses the new one
    with ``BUDGET`` — a persistent conflict is disputed, not reopened.

    The mutation is the ``VerificationRoundOpened`` event, which carries the
    conflict that caused the round (the journal shows *why* the extra fetch
    happened). An exact replay of the same round returns ``duplicate=True``.
    """
    try:
        round_ = verification.parse_round_payload(
            intent.payload, project_id=intent.project_id)
    except verification.VerificationError as exc:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"round request refused: {exc}") from None
    record = verification.round_payload(round_)
    try:
        prior = _opened_rounds(conn, intent.project_id)
    except ValueError as exc:
        raise _reject(intent.kind, MALFORMED_PAYLOAD, str(exc)) from None
    for existing in prior:
        if existing.get("round_id") != round_.round_id:
            continue
        if existing == record:
            return IntentResult(
                kind=intent.kind, entity_type="verification_round",
                entity_id=round_.round_id, duplicate=True, row=existing,
                event_type=EventType.VERIFICATION_ROUND_OPENED.value)
        raise _reject(
            intent.kind, BUDGET,
            f"round {round_.round_id!r} already exists with different "
            "content — one round, then escalate; a conflict that persists is "
            "DISPUTED, never a second fetch")
    refs = set(round_.claim_refs)
    for existing in prior:
        overlap = refs & set(existing.get("claim_refs") or ())
        if overlap:
            raise _reject(
                intent.kind, BUDGET,
                f"claim(s) {sorted(overlap)} already had verification round "
                f"{existing.get('round_id')!r} — one round, then escalate; "
                "a conflict that persists is DISPUTED, never a second fetch")
    try:
        validate_event(EventType.VERIFICATION_ROUND_OPENED.value, record)
    except EventValidationError as exc:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"the round record is not a valid event payload: {exc}") from None
    EventRepository(conn).append_transactional(
        clock, EventType.VERIFICATION_ROUND_OPENED.value,
        project_id=intent.project_id,
        correlation_id=round_.round_id,
        caused_by=intent.proposed_by,
        reason=intent.justification,
        payload=record, audit=audit)
    return IntentResult(
        kind=intent.kind, entity_type="verification_round",
        entity_id=round_.round_id, duplicate=False, row=record,
        event_type=EventType.VERIFICATION_ROUND_OPENED.value)


def _validate_record_verification_outcome(
    conn: Any, intent: Intent, *, clock: Callable[[], str],
    audit: AuditRecord | None = None,
) -> IntentResult:
    """RECORD_VERIFICATION_OUTCOME — the round's terminal record.

    Internal-only: the round produces evidence and the deterministic layer
    records which side (if either) it establishes. A RESOLVED outcome must
    name a claim of the opened round and an artifact that resolves in the
    project; a DISPUTED or REFUSED outcome must say why (and REFUSED, with
    which code). The round can close once; a differing second outcome is
    ``STALE`` and an exact replay is ``DUPLICATE``.
    """
    import json as _json

    try:
        outcome = verification.parse_outcome_payload(intent.payload)
    except verification.VerificationError as exc:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"verification outcome refused: {exc}") from None
    round_id = outcome["round_id"]
    events = EventRepository(conn)
    opened_raw = events.payload_json(
        EventType.VERIFICATION_ROUND_OPENED.value, round_id, intent.project_id)
    if opened_raw is None:
        raise _reject(
            intent.kind, PROPOSAL,
            f"no verification round {round_id!r} is open in this project")
    try:
        opened = _json.loads(opened_raw)
    except ValueError:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"verification round {round_id!r} has an unreadable record") from None
    if not isinstance(opened, dict):
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"verification round {round_id!r} has a malformed record")
    claim_refs = set(opened.get("claim_refs") or ())
    if outcome["status"] == "RESOLVED" and outcome["winner_ref"] not in claim_refs:
        raise _reject(
            intent.kind, PROPOSAL,
            f"winner_ref {outcome['winner_ref']!r} is not a claim of "
            f"round {round_id!r} ({sorted(claim_refs)})")
    # Every evidence ref a round records is an evidence position, whatever
    # the outcome: it must resolve in-project and pass the IDR-046 bar.
    for ref in outcome["evidence_refs"]:
        artifact_id = ref.partition(":")[2]
        if not _source_artifact_resolves(
                conn, intent.project_id, artifact_id, "source_payload"):
            raise _reject(
                intent.kind, EVIDENCE_REF,
                f"evidence ref {ref!r} does not resolve to a fetched "
                "source artifact in this project — a round cannot cite "
                "an artifact it did not fetch")
        # IDR-046 D2/E4 fence: a web-derived row is barred from every
        # evidence position. (N9 retraction fencing is FROZEN at four
        # predicate call sites — AGENTS.md, N9 cert 02cb976 — so this
        # evidence position is recorded as a frozen gap in
        # `tests/test_n9_resolve_path_pin.py` rather than adding a fifth
        # call here without the owning gate re-run.)
        if source_artifact_is_web_derived(conn, artifact_id):
            raise _reject(
                intent.kind, EVIDENCE_REF,
                f"evidence ref {ref!r} names a web-derived row — barred "
                "from every evidence position (IDR-046 D2/E4)")
    completed_raw = events.payload_json(
        EventType.VERIFICATION_ROUND_COMPLETED.value, round_id,
        intent.project_id)
    if completed_raw is not None:
        try:
            existing = _json.loads(completed_raw)
        except ValueError:
            raise _reject(
                intent.kind, MALFORMED_PAYLOAD,
                f"verification round {round_id!r} has an unreadable "
                "outcome record") from None
        if existing == outcome:
            return IntentResult(
                kind=intent.kind, entity_type="verification_round",
                entity_id=round_id, duplicate=True, row=existing,
                event_type=EventType.VERIFICATION_ROUND_COMPLETED.value)
        raise _reject(
            intent.kind, STALE,
            f"verification round {round_id!r} is already closed with a "
            "different outcome — a round has one terminal record")
    try:
        validate_event(EventType.VERIFICATION_ROUND_COMPLETED.value, outcome)
    except EventValidationError as exc:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"the outcome record is not a valid event payload: {exc}") from None
    events.append_transactional(
        clock, EventType.VERIFICATION_ROUND_COMPLETED.value,
        project_id=intent.project_id, correlation_id=round_id,
        caused_by=intent.proposed_by, reason=intent.justification,
        payload=outcome, audit=audit)
    return IntentResult(
        kind=intent.kind, entity_type="verification_round",
        entity_id=round_id, duplicate=False, row=outcome,
        event_type=EventType.VERIFICATION_ROUND_COMPLETED.value)


def _validate_record_contradiction(
    conn: Any, intent: Intent, *, clock: Callable[[], str],
    audit: AuditRecord | None = None,
) -> IntentResult:
    """RECORD_CONTRADICTION — deterministic derived-state admission
    (CHG-1, internal-only — detectors propose pairs, the deterministic
    layer records through this intent; never LLM-proposable).

    Validated at admission: both parties resolve to digest-valid
    classification artifacts in the project with equal program/
    hypothesis refs and different failure classes, neither invalidated,
    with non-empty resolved evidence overlap. Identity is recomputed
    (``cx_`` over the canonical pair — never trusted from the payload).
    Idempotent: an existing row returns duplicate=True with zero
    effects; a differing supersede link on an existing row is refused.
    Optional head-only supersession retires the target in the same
    transaction (new row OPEN, target SUPERSEDED, both events).

    Cumulative bound (EXT-6 / R4): a net-new admission is refused with
    the named code ``CONTRADICTION_BACKLOG`` once the project's OPEN set
    is at ``MAX_OPEN_CONTRADICTIONS`` — the human-adjudication backlog
    cannot grow without bound. Supersession (net-zero) and resolution
    (the only drain) are never gated.
    """
    import json as _json

    from hermes.research.contradictions import (
        CONTRADICTION_TYPE_CLASSIFICATION_CONFLICT,
        MAX_OPEN_CONTRADICTIONS,
        ContradictionError,
        canonical_pair,
        contradiction_id_of,
    )
    kind = intent.kind
    payload = intent.payload
    if not isinstance(payload, dict):
        raise _reject(
            kind, MALFORMED_PAYLOAD,
            f"payload must be a dict, got {type(payload).__name__}")
    unknown = sorted(set(payload) - _RECORD_CONTRADICTION_PAYLOAD_KEYS)
    if unknown:
        raise _reject(
            kind, MALFORMED_PAYLOAD,
            f"unknown payload keys {unknown} for RECORD_CONTRADICTION")
    prow = conn.execute(
        "SELECT 1 FROM projects WHERE project_id = ?",
        (intent.project_id,)).fetchone()
    if prow is None:
        raise _reject(
            kind, PROJECT_NOT_FOUND,
            f"project {intent.project_id!r} does not exist — stale project "
            f"reference")
    party_a = payload.get("party_a")
    party_b = payload.get("party_b")
    try:
        ordered = canonical_pair(party_a, party_b)
    except ContradictionError as exc:
        raise _reject(kind, MALFORMED_PAYLOAD, str(exc)) from None
    detector_version = payload.get("detector_version")
    if not isinstance(detector_version, str) or not detector_version:
        raise _reject(
            kind, MALFORMED_PAYLOAD,
            "payload.detector_version must be a non-empty string")
    supersedes_ref = payload.get("supersedes_ref", "")
    if not isinstance(supersedes_ref, str):
        raise _reject(
            kind, MALFORMED_PAYLOAD,
            "payload.supersedes_ref must be a string")
    # ── pair rule, re-derived from committed rows (never trusted) ──
    facts_a = _cx_classification_facts(conn, intent.project_id, ordered[0])
    facts_b = _cx_classification_facts(conn, intent.project_id, ordered[1])
    if facts_a is None or facts_b is None:
        raise _reject(
            kind, EVIDENCE_REF,
            "contradiction parties must resolve to digest-valid "
            f"classification artifacts in project {intent.project_id!r}")
    # OPS-5Q: compare the canonical program/hypothesis scope, not the raw
    # stored spelling. Both admitted program spellings of one program are
    # one target; an unresolvable ref fails closed (no pair).
    programs: list[dict] = []
    for facts in (facts_a, facts_b):
        program = _resolve_program_in_project(
            conn, intent.project_id, facts["program_ref"])
        if program is not None:
            programs.append(program)
    scope_a = canonical_program_scope(
        facts_a["program_ref"], facts_a["hypothesis_ref"], programs)
    scope_b = canonical_program_scope(
        facts_b["program_ref"], facts_b["hypothesis_ref"], programs)
    if scope_a is None or scope_b is None:
        raise _reject(
            kind, PROPOSAL,
            "contradiction party program/hypothesis refs cannot be "
            "canonicalised — the pair rule cannot be verified")
    if scope_a[0] != scope_b[0]:
        raise _reject(
            kind, PROPOSAL,
            "contradiction parties target different programs — not one "
            "classification conflict")
    if scope_a[1] != scope_b[1]:
        raise _reject(
            kind, PROPOSAL,
            "contradiction parties target different hypotheses — not one "
            "classification conflict")
    if facts_a["failure_class"] == facts_b["failure_class"]:
        raise _reject(
            kind, PROPOSAL,
            "contradiction parties share a failure class — agreement, "
            "not conflict")
    overlap = sorted(facts_a["evidence"] & facts_b["evidence"])
    if not overlap:
        raise _reject(
            kind, EVIDENCE_REF,
            "contradiction parties share no resolved evidence — overlap "
            "cannot be established")
    contradiction_id = contradiction_id_of(ordered[0], ordered[1])
    ts = clock()
    conn.execute("BEGIN IMMEDIATE")
    try:
        existing = conn.execute(
            "SELECT supersedes_ref FROM contradictions "
            "WHERE contradiction_id = ?",
            (contradiction_id,)).fetchone()
        if existing is not None:
            stored_link = existing["supersedes_ref"] or ""
            if supersedes_ref and supersedes_ref != stored_link:
                conn.execute("ROLLBACK")
                raise _reject(
                    kind, PROPOSAL,
                    f"contradiction {contradiction_id!r} is already "
                    "recorded with a different supersede link — "
                    "contradictory admission refused")
            conn.execute("ROLLBACK")
            return IntentResult(
                kind=kind, entity_type="contradiction",
                entity_id=contradiction_id, duplicate=True,
                row={"contradiction_id": contradiction_id},
                event_type=EventType.CONTRADICTION_DETECTED.value)
        # N9: re-resolve both parties' evidence INSIDE the write
        # transaction — a retraction committed after candidate derivation
        # (or after the pre-transaction pair rule above) still refuses.
        # The detector must not trust upstream filtering.
        fresh_a = _cx_classification_facts(
            conn, intent.project_id, ordered[0])
        fresh_b = _cx_classification_facts(
            conn, intent.project_id, ordered[1])
        if (fresh_a is None or fresh_b is None
                or not (set(fresh_a["evidence"])
                        & set(fresh_b["evidence"]))):
            conn.execute("ROLLBACK")
            raise _reject(
                kind, EVIDENCE_REF,
                "contradiction parties share no currently-valid resolved "
                "evidence — overlap cannot be established")
        # P2-17 (CX-OVERLAP-1, ruling R7): the recorded row carries the
        # FRESH overlap re-derived above, never the pre-transaction
        # snapshot — a resolution/retraction committing between the
        # pre-lock pair rule and BEGIN IMMEDIATE must not be recorded as
        # admitted provenance. The event payload and the intent result
        # stay on the pre-lock snapshot (byte-stable consumers); the
        # recorded row is the surface this slice re-tenants.
        fresh_overlap = sorted(
            set(fresh_a["evidence"]) & set(fresh_b["evidence"]))
        if supersedes_ref:
            target = conn.execute(
                "SELECT status FROM contradictions "
                "WHERE contradiction_id = ? AND project_id = ?",
                (supersedes_ref, intent.project_id)).fetchone()
            if target is None:
                conn.execute("ROLLBACK")
                raise _reject(
                    kind, PROPOSAL,
                    f"supersede target {supersedes_ref!r} does not exist")
            if target["status"] != "OPEN":
                conn.execute("ROLLBACK")
                raise _reject(
                    kind, STALE,
                    f"supersede target {supersedes_ref!r} is "
                    f"{target['status']} — only an OPEN head can be "
                    "superseded")
            head = conn.execute(
                "SELECT contradiction_id FROM contradictions "
                "WHERE supersedes_ref = ? LIMIT 1",
                (supersedes_ref,)).fetchone()
            if head is not None:
                conn.execute("ROLLBACK")
                raise _reject(
                    kind, STALE,
                    f"supersede target {supersedes_ref!r} is not the "
                    "current head — already superseded")
        # EXT-6 / R4 — cumulative OPEN-contradiction ceiling (fail-closed,
        # refusal-as-data — never a silent drop). Counted INSIDE the write
        # transaction so a concurrent admission cannot drift past the
        # ceiling. A net-new recording is refused once the project's OPEN
        # set is at the ceiling: nothing is inserted and existing OPEN
        # rows are untouched. Head-only supersession retires exactly one
        # OPEN row in this same transaction (validated above), so it nets
        # zero and is not gated. Resolution is a different intent and is
        # never gated — the only drain path stays open at any count.
        if not supersedes_ref:
            open_count = conn.execute(
                "SELECT COUNT(*) AS n FROM contradictions "
                "WHERE project_id = ? AND status = 'OPEN'",
                (intent.project_id,)).fetchone()["n"]
            if open_count >= MAX_OPEN_CONTRADICTIONS:
                # The refusal is raised INSIDE the transaction; the
                # ``except GatewayRejection`` handler below owns the
                # rollback, so this adds no transaction-control call and
                # the certified census figure (121) is unchanged.
                raise _reject(
                    kind, CONTRADICTION_BACKLOG,
                    f"project {intent.project_id!r} already holds "
                    f"{open_count} OPEN contradictions at the ceiling "
                    f"({MAX_OPEN_CONTRADICTIONS}) — a new contradiction is "
                    "refused until the backlog is triaged; resolve OPEN "
                    "items through the ratified human-verdict path (each "
                    "resolution frees one slot). Existing OPEN rows are "
                    "untouched and resolution is never blocked")
        conn.execute(
            "INSERT INTO contradictions "
            "(contradiction_id, project_id, type, party_a, party_b, "
            " evidence_overlap_json, status, detector_version, detected_at,"
            " detection_event_ref, resolution_event_ref, "
            " resolution_rationale_digest, supersedes_ref, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, NULL, NULL, ?, ?)",
            (contradiction_id, intent.project_id,
             CONTRADICTION_TYPE_CLASSIFICATION_CONFLICT,
             ordered[0], ordered[1],
             _json.dumps(fresh_overlap),
             detector_version, ts, contradiction_id,
             supersedes_ref or None, ts))
        if supersedes_ref:
            conn.execute(
                "UPDATE contradictions SET status = 'SUPERSEDED' "
                "WHERE contradiction_id = ? AND status = 'OPEN'",
                (supersedes_ref,))
            _append_event_to_db(
                conn, clock,
                EventType.CONTRADICTION_SUPERSEDED.value,
                project_id=intent.project_id,
                correlation_id=f"{supersedes_ref}:superseded-by:"
                               f"{contradiction_id}",
                caused_by=intent.proposed_by,
                reason="contradiction superseded by a newer record",
                payload={"contradiction_id": supersedes_ref,
                         "superseded_by": contradiction_id})
        _append_event_to_db(
            conn, clock, EventType.CONTRADICTION_DETECTED.value,
            project_id=intent.project_id,
            correlation_id=contradiction_id,
            caused_by=intent.proposed_by,
            reason="classification conflict detected",
            payload={"contradiction_id": contradiction_id,
                     "type": CONTRADICTION_TYPE_CLASSIFICATION_CONFLICT,
                     "party_a": ordered[0], "party_b": ordered[1],
                     "evidence_overlap": overlap,
                     "detector_version": detector_version,
                     "supersedes_ref": supersedes_ref or None})
        if audit is not None:
            _append_event_to_db(
                conn, clock, audit.event_type,
                project_id=audit.project_id,
                correlation_id=audit.correlation_id,
                caused_by=audit.caused_by,
                reason=audit.reason,
                payload=audit.payload)
        conn.execute("COMMIT")
    except GatewayRejection:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    return IntentResult(
        kind=kind, entity_type="contradiction",
        entity_id=contradiction_id, duplicate=False,
        row={"contradiction_id": contradiction_id,
             "party_a": ordered[0], "party_b": ordered[1],
             "evidence_overlap": overlap,
             "detector_version": detector_version,
             "supersedes_ref": supersedes_ref or None},
        event_type=EventType.CONTRADICTION_DETECTED.value)


def _contradiction_resolution_id(contradiction_id: str) -> str:
    """Deterministic resolution identity for one contradiction."""
    import hashlib as _hashlib
    import json as _json
    raw = _json.dumps({"contradiction_id": contradiction_id},
                      sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "cres_" + _hashlib.sha256(raw).hexdigest()[:24]


def _validate_contradiction_resolution(
    conn: Any, intent: Intent, *, clock: Callable[[], str],
    audit: AuditRecord | None = None,
) -> IntentResult:
    """CONTRADICTION_RESOLUTION — the ratified HUMAN verdict closing an
    OPEN contradiction (CHG-1, internal-only — the human has no agent
    profile; the deterministic layer ingests the operator verdict through
    the record_contradiction_resolution precedent, IDR-040 §3). The
    verdict acknowledges the conflict — it decides nothing between the
    parties and invalidates neither; both parties remain valid under the
    frozen N1 rule.

    Validated at admission: ratified operator credential, a recorded
    HumanDecision binding the deterministic ``resolution_id`` (verified
    fail-closed, never trusted), and a target contradiction that exists
    in-project and is OPEN. One contradiction, one verdict: an identical
    replay returns duplicate=True; a verdict on an already-RESOLVED row
    is refused (PROPOSAL); a verdict on a SUPERSEDED row is refused
    (STALE — retire the chain head instead). LLM-proposed resolution is
    impossible (internal-only role gate).

    CRES-DIGEST-1 (P3-17): the resolved row also carries
    ``resolution_rationale_digest`` — sha256 over the UTF-8 rationale
    bytes of the BOUND decision row, recomputed inside the resolution
    transaction (never taken from the command payload, which stays
    exactly {contradiction_id, human_decision_ref, operator_id}). The
    policy is NULL-safe: a bound row whose rationale key is absent or
    not a string stores NULL (the existing decision-binding validation
    remains the admission gate); an empty-string rationale digests as
    sha256(b"").
    """
    kind = intent.kind
    payload = intent.payload
    if not isinstance(payload, dict):
        raise _reject(
            kind, MALFORMED_PAYLOAD,
            f"payload must be a dict, got {type(payload).__name__}")
    unknown = sorted(set(payload) - _RESOLVE_CONTRADICTION_PAYLOAD_KEYS)
    if unknown:
        raise _reject(
            kind, MALFORMED_PAYLOAD,
            f"unknown payload keys {unknown} for "
            f"CONTRADICTION_RESOLUTION")
    contradiction_id = payload.get("contradiction_id")
    if not isinstance(contradiction_id, str) or not contradiction_id:
        raise _reject(
            kind, MALFORMED_PAYLOAD,
            "payload.contradiction_id must be a non-empty string")
    human_decision_ref = payload.get("human_decision_ref")
    if not isinstance(human_decision_ref, str) or not human_decision_ref:
        raise _reject(
            kind, MALFORMED_PAYLOAD,
            "payload.human_decision_ref must be a non-empty string")
    # A4: the gateway re-verifies the credential EXISTS (the token
    # itself is verified at the controller surface and never travels in
    # an intent/event).
    operator_id = payload.get("operator_id")
    if not isinstance(operator_id, str) or not operator_id:
        raise _reject(
            kind, MALFORMED_PAYLOAD,
            "payload.operator_id must be a non-empty string")
    from hermes.persistence.repositories import OperatorCredentialRepository
    if not OperatorCredentialRepository(conn).exists(operator_id):
        raise _reject(
            kind, OPERATOR,
            f"operator {operator_id!r} is not a ratified operator "
            f"credential — the verdict cannot be recorded")
    # The HumanDecision contract: a RECORDED human decision binding the
    # deterministic resolution_id must exist — dereferenced against the
    # HumanDecisionReceived journal (event_id or correlation_id),
    # fail-closed. No recorded decision, no resolution.
    resolution_id = _contradiction_resolution_id(contradiction_id)
    import hashlib as _hashlib
    import json as _json
    decision_row = conn.execute(
        "SELECT payload_json FROM events "
        "WHERE project_id = ? AND event_type = ? "
        "AND (event_id = ? OR correlation_id = ?) "
        "ORDER BY rowid LIMIT 1",
        (intent.project_id, EventType.HUMAN_DECISION_RECEIVED.value,
         human_decision_ref, human_decision_ref)).fetchone()
    if decision_row is None:
        raise _reject(
            kind, PROPOSAL,
            f"payload.human_decision_ref {human_decision_ref!r} does not "
            f"dereference to a recorded HumanDecision in project "
            f"{intent.project_id!r} — resolution requires a recorded "
            f"human verdict")
    try:
        decision_payload = _json.loads(
            decision_row["payload_json"] or "{}")
    except ValueError:
        raise _reject(
            kind, PROPOSAL,
            f"recorded decision {human_decision_ref!r} has corrupt "
            f"payload") from None
    if not isinstance(decision_payload, dict):
        raise _reject(
            kind, PROPOSAL,
            f"recorded decision {human_decision_ref!r} has a corrupt "
            f"payload") from None
    if decision_payload.get("decision") != "CONTRADICTION_RESOLUTION":
        raise _reject(
            kind, PROPOSAL,
            f"recorded decision {human_decision_ref!r} is not a "
            f"contradiction-resolution verdict")
    if decision_payload.get("resolution_id") != resolution_id:
        raise _reject(
            kind, PROPOSAL,
            f"recorded decision {human_decision_ref!r} does not bind "
            f"contradiction {contradiction_id!r}")
    if decision_payload.get("contradiction_id") != contradiction_id:
        raise _reject(
            kind, PROPOSAL,
            f"recorded decision {human_decision_ref!r} targets a "
            f"different contradiction")
    conn.execute("BEGIN IMMEDIATE")
    try:
        target = conn.execute(
            "SELECT status FROM contradictions "
            "WHERE contradiction_id = ? AND project_id = ?",
            (contradiction_id, intent.project_id)).fetchone()
        if target is None:
            conn.execute("ROLLBACK")
            raise _reject(
                kind, PROPOSAL,
                f"contradiction {contradiction_id!r} does not exist in "
                f"project {intent.project_id!r}")
        if target["status"] == "RESOLVED":
            prior = conn.execute(
                "SELECT 1 FROM events WHERE event_type = ? "
                "AND correlation_id = ? LIMIT 1",
                (EventType.CONTRADICTION_RESOLVED.value,
                 resolution_id)).fetchone()
            conn.execute("ROLLBACK")
            if prior is not None:
                return IntentResult(
                    kind=kind, entity_type="contradiction",
                    entity_id=contradiction_id, duplicate=True,
                    row={"contradiction_id": contradiction_id},
                    event_type=EventType.CONTRADICTION_RESOLVED.value)
            raise _reject(
                kind, PROPOSAL,
                f"contradiction {contradiction_id!r} is already "
                f"RESOLVED — one contradiction, one verdict; contradictory "
                f"re-verdicts are refused")
        if target["status"] == "SUPERSEDED":
            conn.execute("ROLLBACK")
            raise _reject(
                kind, STALE,
                f"contradiction {contradiction_id!r} is SUPERSEDED — "
                f"resolve the chain head instead; historical rows are "
                f"never re-resolved")
        # CRES-DIGEST-1 (P3-17): digest the rationale of the BOUND
        # decision row, in-transaction, by the RETRACT_SOURCE
        # reason-binding convention (sha256 over the UTF-8 bytes, full
        # hexdigest). The command payload never carries a rationale, so
        # this value cannot be trusted from — or substituted by — the
        # request. NULL-safe policy: a bound row without rationale text
        # (key absent or not a string) stores NULL; a string that cannot
        # be canonically encoded is a corrupt decision and refuses
        # fail-closed (no explicit ROLLBACK here — the except
        # GatewayRejection handler below owns it, so the certified
        # census figure (121) is unchanged).
        rationale = decision_payload.get("rationale")
        if isinstance(rationale, str):
            try:
                rationale_digest = _hashlib.sha256(
                    rationale.encode("utf-8")).hexdigest()
            except UnicodeEncodeError:
                raise _reject(
                    kind, PROPOSAL,
                    f"recorded decision {human_decision_ref!r} carries a "
                    f"rationale that cannot be canonically encoded — "
                    f"resolution refused") from None
        else:
            rationale_digest = None
        conn.execute(
            "UPDATE contradictions "
            "SET status = 'RESOLVED', resolution_event_ref = ?, "
            "resolution_rationale_digest = ? "
            "WHERE contradiction_id = ? AND status = 'OPEN'",
            (resolution_id, rationale_digest, contradiction_id))
        _append_event_to_db(
            conn, clock, EventType.CONTRADICTION_RESOLVED.value,
            project_id=intent.project_id,
            correlation_id=resolution_id,
            caused_by=intent.proposed_by,
            reason="contradiction resolved by ratified human verdict",
            payload={"contradiction_id": contradiction_id,
                     "resolution_id": resolution_id,
                     "human_decision_ref": human_decision_ref,
                     "operator_id": operator_id})
        if audit is not None:
            _append_event_to_db(
                conn, clock, audit.event_type,
                project_id=audit.project_id,
                correlation_id=audit.correlation_id,
                caused_by=audit.caused_by,
                reason=audit.reason,
                payload=audit.payload)
        conn.execute("COMMIT")
    except GatewayRejection:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    return IntentResult(
        kind=kind, entity_type="contradiction",
        entity_id=contradiction_id, duplicate=False,
        row={"contradiction_id": contradiction_id,
             "resolution_id": resolution_id},
        event_type=EventType.CONTRADICTION_RESOLVED.value)


_RECORD_CLASSIFICATION_PAYLOAD_KEYS = frozenset({
    "program_ref", "hypothesis_ref", "failure_class", "evidence_refs",
    "falsifying_evidence_refs", "explanation", "classifier_version",
    "constraint_ref", "failed_mechanism_ref", "regime_ref",
    "resource_gap", "scope_brief_ref", "scope_brief_field",
    "contributing_factors", "proposed_by", "producing_task_id",
    "human_decision_ref", "operator_id", "condition_type"})


def _validate_record_classification(
    conn: Any, intent: Intent, *, clock: Callable[[], str],
    audit: AuditRecord | None = None,
) -> IntentResult:
    """RECORD_CLASSIFICATION — operator-asserted failure-classification
    admission (P6, internal-only — the human has no agent profile; the
    deterministic layer ingests the operator's classification judgment
    through the record_operator_decision precedent, IDR-040 §3).

    Judgment authorship is the operator's; EVERYTHING checkable is
    re-verified fail-closed: ratified operator credential, a recorded
    HumanDecision binding the deterministic command hash, closed
    payload schema, ratified failure class, and — via the existing
    ``FailureClassificationRepository.record`` write boundary (which
    owns its own transaction, so this validator opens none) — project
    match, evidence ownership, digest identity, and content-hash
    idempotency. LLM-proposed recording is impossible (internal-only
    role gate). No dedicated mutation event exists by design (the
    IntentApplied audit + artifact row are the trail — the outcome and
    claim write-path precedent); the contradiction detector consumes
    recorded rows through the existing readers.
    """
    from hermes.persistence.failure_classifications import (
        FailureClassificationBindingError,
        FailureClassificationError,
        FailureClassificationIntegrityError,
        FailureClassificationRepository,
    )
    from hermes.research.failure_classification import (
        ConditionType,
        FailureClass,
        FailureClassificationDraft,
        FalsificationRecord,
        ResourceGap,
        classification_command_hash,
        legacy_classification_command_hash,
    )
    kind = intent.kind
    payload = intent.payload
    if not isinstance(payload, dict):
        raise _reject(
            kind, MALFORMED_PAYLOAD,
            f"payload must be a dict, got {type(payload).__name__}")
    unknown = sorted(set(payload) - _RECORD_CLASSIFICATION_PAYLOAD_KEYS)
    if unknown:
        raise _reject(
            kind, MALFORMED_PAYLOAD,
            f"unknown payload keys {unknown} for RECORD_CLASSIFICATION")

    def _req_str(key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise _reject(
                kind, MALFORMED_PAYLOAD,
                f"payload.{key} must be a non-empty string")
        return value

    def _opt_str(key: str) -> str | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, str) or not value:
            raise _reject(
                kind, MALFORMED_PAYLOAD,
                f"payload.{key} must be a non-empty string or absent")
        return value

    def _req_str_list(key: str) -> list[str]:
        value = payload.get(key)
        if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value):
            raise _reject(
                kind, MALFORMED_PAYLOAD,
                f"payload.{key} must be a list of strings")
        return list(value)

    program_ref = _req_str("program_ref")
    hypothesis_ref = _req_str("hypothesis_ref")
    try:
        failure_class = FailureClass(payload.get("failure_class"))
    except (ValueError, TypeError):
        raise _reject(
            kind, MALFORMED_PAYLOAD,
            f"payload.failure_class {payload.get('failure_class')!r} is "
            f"not a ratified member") from None
    # COND-TYPE (GAP-1 D4-A): an absent/None condition_type is the
    # declared UNDETERMINED default (the pre-slice behavior, now explicit).
    condition_type_raw = payload.get("condition_type")
    try:
        condition_type = ConditionType(
            condition_type_raw
            if condition_type_raw is not None
            else ConditionType.UNDETERMINED)
    except (ValueError, TypeError):
        raise _reject(
            kind, MALFORMED_PAYLOAD,
            f"payload.condition_type {condition_type_raw!r} is not a "
            f"ratified member") from None
    evidence_refs = _req_str_list("evidence_refs")
    falsifying_evidence_refs = _req_str_list("falsifying_evidence_refs")
    explanation = _req_str("explanation")
    classifier_version = _req_str("classifier_version")
    constraint_ref = _opt_str("constraint_ref")
    failed_mechanism_ref = _opt_str("failed_mechanism_ref")
    regime_ref = _opt_str("regime_ref")
    scope_brief_ref = _opt_str("scope_brief_ref")
    scope_brief_field = _opt_str("scope_brief_field")
    contributing_factors = _req_str_list("contributing_factors")
    proposed_by = _req_str("proposed_by")
    producing_task_id = _req_str("producing_task_id")
    human_decision_ref = _req_str("human_decision_ref")
    resource_gap_raw = payload.get("resource_gap")
    resource_gap = None
    if resource_gap_raw is not None:
        if not isinstance(resource_gap_raw, dict):
            raise _reject(
                kind, MALFORMED_PAYLOAD,
                "payload.resource_gap must be a mapping or absent")
        try:
            resource_gap = ResourceGap(
                resource_kind=str(resource_gap_raw["resource_kind"]),
                observed=float(resource_gap_raw["observed"]),
                required=float(resource_gap_raw["required"]),
                unit=str(resource_gap_raw["unit"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise _reject(
                kind, MALFORMED_PAYLOAD,
                f"payload.resource_gap is malformed: {exc}") from None
    # A4: the gateway re-verifies the credential EXISTS (the token
    # itself is verified at the controller surface and never travels in
    # an intent/event).
    operator_id = _req_str("operator_id")
    from hermes.persistence.repositories import OperatorCredentialRepository
    if not OperatorCredentialRepository(conn).exists(operator_id):
        raise _reject(
            kind, OPERATOR,
            f"operator {operator_id!r} is not a ratified operator "
            f"credential — the classification cannot be recorded")
    # The HumanDecision contract: a RECORDED operator decision binding
    # the deterministic command hash must exist — dereferenced against
    # the HumanDecisionReceived journal (event_id or correlation_id),
    # fail-closed. No recorded decision, no recording.
    import json as _json
    command = {
        "program_ref": program_ref,
        "hypothesis_ref": hypothesis_ref,
        "failure_class": failure_class.value,
        "evidence_refs": evidence_refs,
        "falsifying_evidence_refs": falsifying_evidence_refs,
        "explanation": explanation,
        "classifier_version": classifier_version,
        "constraint_ref": constraint_ref,
        "failed_mechanism_ref": failed_mechanism_ref,
        "regime_ref": regime_ref,
        "resource_gap": ({
            "resource_kind": resource_gap.resource_kind,
            "observed": resource_gap.observed,
            "required": resource_gap.required,
            "unit": resource_gap.unit,
        } if resource_gap is not None else None),
        "scope_brief_ref": scope_brief_ref,
        "scope_brief_field": scope_brief_field,
        "contributing_factors": contributing_factors,
        "proposed_by": proposed_by,
        "producing_task_id": producing_task_id,
        "condition_type": condition_type.value,
    }
    command_hash = classification_command_hash(command)
    decision_row = conn.execute(
        "SELECT payload_json FROM events "
        "WHERE project_id = ? AND event_type = ? "
        "AND (event_id = ? OR correlation_id = ?) "
        "ORDER BY rowid LIMIT 1",
        (intent.project_id, EventType.HUMAN_DECISION_RECEIVED.value,
         human_decision_ref, human_decision_ref)).fetchone()
    if decision_row is None:
        raise _reject(
            kind, PROPOSAL,
            f"payload.human_decision_ref {human_decision_ref!r} does not "
            f"dereference to a recorded HumanDecision in project "
            f"{intent.project_id!r} — classification recording requires "
            f"a recorded human verdict")
    try:
        decision_payload = _json.loads(
            decision_row["payload_json"] or "{}")
    except ValueError:
        raise _reject(
            kind, PROPOSAL,
            f"recorded decision {human_decision_ref!r} has corrupt "
            f"payload") from None
    if not isinstance(decision_payload, dict):
        raise _reject(
            kind, PROPOSAL,
            f"recorded decision {human_decision_ref!r} has a corrupt "
            f"payload") from None
    if decision_payload.get("decision") != "RECORD_CLASSIFICATION":
        raise _reject(
            kind, PROPOSAL,
            f"recorded decision {human_decision_ref!r} is not a "
            f"classification-recording verdict")
    recorded_hash = decision_payload.get("classification_hash")
    if recorded_hash != command_hash:
        # COND-TYPE dual-read: a HumanDecision recorded before the
        # hash-version bump binds the v1 (pre-condition_type) command
        # hash. That approval predates the condition-type dimension, so
        # it authorizes ONLY the declared default UNDETERMINED mapping —
        # never a non-default condition type. Stored hashes are never
        # rehashed or mutated.
        legacy_hash = (
            legacy_classification_command_hash(command)
            if condition_type is ConditionType.UNDETERMINED else None)
        if recorded_hash != legacy_hash:
            raise _reject(
                kind, PROPOSAL,
                f"recorded decision {human_decision_ref!r} does not bind "
                f"this classification command")
    # The semantic core delegates to the existing write boundary (which
    # owns its transaction — this validator opens none — and re-runs
    # the substrate with the real resolvers: project match, evidence
    # ownership, digest identity, content-hash idempotency).
    try:
        record = FalsificationRecord(
            project_id=intent.project_id,
            hypothesis_ref=hypothesis_ref,
            program_ref=program_ref,
            falsifying_evidence_refs=tuple(falsifying_evidence_refs))
        draft = FailureClassificationDraft(
            failure_class=failure_class.value,
            explanation=explanation,
            evidence_refs=tuple(evidence_refs),
            contributing_factors=tuple(contributing_factors),
            constraint_ref=constraint_ref,
            failed_mechanism_ref=failed_mechanism_ref,
            regime_ref=regime_ref,
            resource_gap=resource_gap,
            scope_brief_ref=scope_brief_ref,
            scope_brief_field=scope_brief_field,
            proposed_by=proposed_by,
            classifier_version=classifier_version,
            condition_type=condition_type)
    except (TypeError, ValueError) as exc:
        raise _reject(
            kind, MALFORMED_PAYLOAD,
            f"classification record/draft construction failed: "
            f"{exc}") from None
    try:
        outcome = FailureClassificationRepository(
            conn, clock).record(
                intent.project_id, record, draft,
                producing_task_id=producing_task_id, audit=audit)
    except FailureClassificationBindingError as exc:
        raise _reject(kind, EVIDENCE_REF, str(exc)) from None
    except FailureClassificationIntegrityError as exc:
        raise _reject(kind, PROPOSAL, str(exc)) from None
    except FailureClassificationError as exc:
        raise _reject(kind, MALFORMED_PAYLOAD, str(exc)) from None
    return IntentResult(
        kind=kind, entity_type="failure_classification",
        entity_id=outcome["classification_id"],
        duplicate=(outcome["decision"] != "NEW"),
        row={"classification_id": outcome["classification_id"],
             "failure_class": outcome["failure_class"],
             "decision": outcome["decision"],
             "classification_hash": command_hash},
        event_type="")


def _validate_record_scope_review_decision(
    conn: Any, intent: Intent, *, clock: Callable[[], str],
    audit: AuditRecord | None = None,
) -> IntentResult:
    """RECORD_SCOPE_REVIEW_DECISION — the S16 scope-review intake
    (IDR-041 §4). Validated at admission: the ``proposal_id`` must be an
    APPROVED classification-action proposal whose action is S16-routed
    (ROUTE_TO_SCOPE_REVIEW / PROPOSE_SCOPE_NARROWING) AND in the
    classification's permitted set (the ratification-ref contract,
    recomputed F2); the ``scope_decision`` must be a ratified
    ScopeReviewDecision. ONE SCOPE DECISION PER APPROVAL: an identical
    re-record is idempotent; a second DIFFERENT scope decision on the same
    approval is refused. The record appends SCOPE_REVIEW_DECIDED
    (correlation_id = proposal_id): the decision is evidence-of-ratification
    for the S16 authority's separate, versioned brief amendment — nothing
    here amends a brief and nothing executes.
    """
    payload = intent.payload
    if not isinstance(payload, dict):
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"payload must be a dict, got {type(payload).__name__}")
    unknown = sorted(set(payload) - _SCOPE_REVIEW_DECISION_PAYLOAD_KEYS)
    if unknown:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"unknown payload keys {unknown} for "
            f"RECORD_SCOPE_REVIEW_DECISION")
    from hermes.research.scope_review import (
        MAX_SCOPE_RATIONALE,
        S16_SCOPE_ACTIONS,
        ScopeReviewDecision,
    )
    proposal_id = payload.get("proposal_id")
    if not isinstance(proposal_id, str) or not proposal_id:
        raise _reject(intent.kind, MALFORMED_PAYLOAD,
                      "payload.proposal_id must be a non-empty string")
    scope_decision = payload.get("scope_decision")
    if scope_decision not in {d.value for d in ScopeReviewDecision}:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"payload.scope_decision {scope_decision!r} must be one of "
            f"{sorted(d.value for d in ScopeReviewDecision)}")
    rationale = payload.get("rationale")
    if rationale is not None and (not isinstance(rationale, str)
                                  or len(rationale) > MAX_SCOPE_RATIONALE):
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"payload.rationale must be a string of at most "
            f"{MAX_SCOPE_RATIONALE} chars")
    # F7 (audit): A4 parity — every human scope verdict cites a RATIFIED
    # operator (the token itself is verified at the controller surface and
    # never travels in an intent/event); the gateway re-verifies existence.
    operator_id = payload.get("operator_id")
    if not isinstance(operator_id, str) or not operator_id:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            "payload.operator_id must be a non-empty string")
    from hermes.persistence.repositories import OperatorCredentialRepository
    if not OperatorCredentialRepository(conn).exists(operator_id):
        raise _reject(
            intent.kind, OPERATOR,
            f"operator {operator_id!r} is not a ratified operator "
            f"credential — the scope decision cannot be recorded")

    # The ratification-ref contract: the approval must be real, APPROVED,
    # S16-routed, and its action in the class's permitted set.
    if _resolve_ratified_proposal(
            conn, intent.project_id, proposal_id, S16_SCOPE_ACTIONS) is None:
        raise _reject(
            intent.kind, PROPOSAL,
            f"proposal_id {proposal_id!r} is not an APPROVED S16-routed "
            f"classification-action proposal whose action is in the "
            f"classification's permitted set")

    # One scope decision per approval — checked AND appended in one
    # transaction (F6 audit). Identical re-record: idempotent.
    outcome, prior = _decision_append_transactional(
        conn, clock, EventType.SCOPE_REVIEW_DECIDED.value,
        project_id=intent.project_id, correlation_id=proposal_id,
        caused_by=intent.proposed_by,
        payload={
            "proposal_id": proposal_id,
            "scope_decision": scope_decision,
            "rationale": rationale or "",
            "operator_id": operator_id,
        },
        verdict_key="scope_decision", verdict_value=scope_decision,
        audit=audit)
    if outcome == "duplicate":
        return IntentResult(
            kind=intent.kind, entity_type="scope_review_decision",
            entity_id=proposal_id, duplicate=True,
            row={"proposal_id": proposal_id,
                 "scope_decision": scope_decision},
            event_type=EventType.SCOPE_REVIEW_DECIDED.value)
    if outcome == "conflict":
        raise _reject(
            intent.kind, PROPOSAL,
            f"approval {proposal_id!r} already has scope decision "
            f"{prior!r} — a second contradictory scope decision "
            f"is refused")
    return IntentResult(
        kind=intent.kind, entity_type="scope_review_decision",
        entity_id=proposal_id, duplicate=False,
        row={"proposal_id": proposal_id, "scope_decision": scope_decision},
        event_type=EventType.SCOPE_REVIEW_DECIDED.value)


_OPERATOR_CREDENTIAL_MUTATION_PAYLOAD_KEYS = {
    IntentKind.REVOKE_OPERATOR_CREDENTIAL: frozenset({"operator_id", "reason"}),
    IntentKind.ROTATE_OPERATOR_CREDENTIAL: frozenset({"operator_id"}),
}
# CRED-1 bound: the revocation reason rides the journal event (4 KiB cap),
# so it is bounded pre-write here (refusal, not truncation) — the same
# discipline every other rationale-bearing admission follows.
_MAX_CREDENTIAL_REVOKE_REASON_LENGTH = 1024


def _validate_operator_credential_mutation(
    conn: Any, intent: Intent, *, clock: Callable[[], str],
    audit: AuditRecord | None = None,
) -> IntentResult:
    """REVOKE_OPERATOR_CREDENTIAL / ROTATE_OPERATOR_CREDENTIAL — the
    CRED-1 credential-lifecycle admissions.

    Closed payload schemas (revoke: ``operator_id`` + optional ``reason``;
    rotate: ``operator_id`` only). Both mutations run inside the
    persistence worker's OWN ``BEGIN IMMEDIATE`` (row re-read and
    re-validated in-transaction): an unknown operator or a revoked
    credential refuses fail-closed with ``OPERATOR``. Revoke is
    archive-not-delete and idempotent (an identical replay returns
    ``duplicate=True``, zero effects); rotate mints a fresh token
    server-side and returns it in ``result.row["new_token"]`` — the
    plaintext token never enters a payload or a journal event. The 4 KiB
    journal cap is enforced by the persistence boundary; the reason bound
    is enforced HERE, pre-write.
    """
    payload = intent.payload
    if not isinstance(payload, dict):
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"payload must be a dict, got {type(payload).__name__}")
    allowed = _OPERATOR_CREDENTIAL_MUTATION_PAYLOAD_KEYS[intent.kind]
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"unknown payload keys {unknown} for {intent.kind.value} "
            f"(closed schema: {sorted(allowed)})")
    operator_id = payload.get("operator_id")
    if not isinstance(operator_id, str) or not operator_id:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            "payload.operator_id must be a non-empty string")
    reason = ""
    if intent.kind is IntentKind.REVOKE_OPERATOR_CREDENTIAL:
        raw_reason = payload.get("reason")
        if raw_reason is not None and (
                not isinstance(raw_reason, str)
                or len(raw_reason) > _MAX_CREDENTIAL_REVOKE_REASON_LENGTH):
            raise _reject(
                intent.kind, MALFORMED_PAYLOAD,
                f"payload.reason must be a string of at most "
                f"{_MAX_CREDENTIAL_REVOKE_REASON_LENGTH} chars")
        reason = raw_reason or ""
    from hermes.persistence.repositories import OperatorCredentialRepository
    repo = OperatorCredentialRepository(conn, clock)
    try:
        if intent.kind is IntentKind.REVOKE_OPERATOR_CREDENTIAL:
            outcome = repo.revoke(
                operator_id, reason=reason, project_id=intent.project_id,
                audit=audit)
            event_type = EventType.OPERATOR_CREDENTIAL_REVOKED.value
        else:
            outcome = repo.rotate(
                operator_id, project_id=intent.project_id, audit=audit)
            event_type = EventType.OPERATOR_CREDENTIAL_ROTATED.value
    except ValueError as exc:
        # The worker's fail-closed refusals (unknown operator, revoked
        # credential) surface as the frozen OPERATOR code.
        raise _reject(intent.kind, OPERATOR, str(exc)) from None
    return IntentResult(
        kind=intent.kind, entity_type="operator_credential",
        entity_id=operator_id, duplicate=outcome["duplicate"],
        row=outcome["row"], event_type=event_type)


def _payload_to_node(intent: Intent) -> NodeContract:
    """Strictly convert an INSERT_TASK / ADMIT_TASK payload to a NodeContract.

    Fail-closed on type violations and unknown keys (EC-F01 style). The
    gateway builds the domain object; the repository persists it atomically.
    """
    payload = intent.payload
    if not isinstance(payload, dict):
        raise _reject(intent.kind, MALFORMED_PAYLOAD,
                      f"payload must be a dict, got {type(payload).__name__}")
    unknown = sorted(set(payload) - _TASK_PAYLOAD_KEYS)
    if unknown:
        raise _reject(intent.kind, MALFORMED_PAYLOAD,
                      f"unknown payload keys: {unknown} — the INSERT_TASK "
                      f"schema is closed")

    def _require_str(key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise _reject(intent.kind, MALFORMED_PAYLOAD,
                          f"payload.{key} must be a non-empty string")
        return value

    def _require_str_list(key: str) -> list[str]:
        value = payload.get(key, [])
        if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value):
            raise _reject(intent.kind, MALFORMED_PAYLOAD,
                          f"payload.{key} must be {_PAYLOAD_LIST_SHAPE}")
        return list(value)

    task_id = _require_str("task_id")
    try:
        task_type = NodeType(_require_str("task_type"))
    except ValueError:
        raise _reject(intent.kind, MALFORMED_PAYLOAD,
                      "payload.task_type must be a NodeType value") from None
    idempotency_key = _require_str("idempotency_key")

    profile: str | None = None
    if payload.get("profile") is not None:
        try:
            profile = AgentProfile(payload["profile"]).value
        except (ValueError, TypeError):
            raise _reject(intent.kind, MALFORMED_PAYLOAD,
                          "payload.profile must be an AgentProfile value") from None

    spec = payload.get("spec", {})
    if not isinstance(spec, dict):
        raise _reject(intent.kind, MALFORMED_PAYLOAD,
                      f"payload.spec must be {_PAYLOAD_DICT_SHAPE}; got "
                      f"{_bounded_rejected(spec)}")

    iteration = payload.get("iteration", 1)
    if not isinstance(iteration, int) or isinstance(iteration, bool) or iteration < 1:
        raise _reject(intent.kind, MALFORMED_PAYLOAD,
                      f"payload.iteration must be "
                      f"{_PAYLOAD_INT_AT_LEAST_1_SHAPE}; got "
                      f"{_bounded_rejected(iteration)}")

    max_retries = payload.get("max_retries", 3)
    if not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries < 0:
        raise _reject(intent.kind, MALFORMED_PAYLOAD,
                      f"payload.max_retries must be "
                      f"{_PAYLOAD_INT_AT_LEAST_0_SHAPE}; got "
                      f"{_bounded_rejected(max_retries)}")

    parent = payload.get("parent_task_id")
    if parent is not None and not isinstance(parent, str):
        raise _reject(intent.kind, MALFORMED_PAYLOAD,
                      f"payload.parent_task_id must be "
                      f"{_PAYLOAD_NULLABLE_STRING_SHAPE}; got "
                      f"{_bounded_rejected(parent)}")
    cost_class = payload.get("cost_class")
    if cost_class is not None and not isinstance(cost_class, str):
        raise _reject(intent.kind, MALFORMED_PAYLOAD,
                      f"payload.cost_class must be "
                      f"{_PAYLOAD_NULLABLE_STRING_SHAPE}; got "
                      f"{_bounded_rejected(cost_class)}")
    concurrency_group = payload.get("concurrency_group")
    if concurrency_group is not None and not isinstance(concurrency_group, str):
        raise _reject(intent.kind, MALFORMED_PAYLOAD,
                      f"payload.concurrency_group must be "
                      f"{_PAYLOAD_NULLABLE_STRING_SHAPE}; got "
                      f"{_bounded_rejected(concurrency_group)}")

    return NodeContract(
        task_id=task_id,
        project_id=intent.project_id,
        task_type=task_type.value,
        profile=profile,
        idempotency_key=idempotency_key,
        iteration=iteration,
        parent_task_id=parent,
        spec=spec,
        inputs=_require_str_list("inputs"),
        outputs=_require_str_list("outputs"),
        dependencies=_require_str_list("dependencies"),
        provenance=_require_str_list("provenance"),
        cost_class=cost_class,
        concurrency_group=concurrency_group,
        max_retries=max_retries,
    )


def _validate_provenance(
    intent: Intent, node: NodeContract, program_repo: ResearchProgramRepository,
) -> None:
    """Enforce the P3 provenance contract (V6-FINAL-02).

    ``provenance_json`` is descriptive metadata, not authoritative lineage (the
    ``provenance_edges`` table is the future authoritative mechanism). But the
    reserved ``research_program:<id>`` prefix is the one reference class that is
    unambiguously dereferenceable at admission and is produced by the task plan
    for every plan task — so a claim naming a program that does not exist (or
    belongs to another project) is a false-lineage forgery and is rejected.
    Requirement-level annotations (``evidence_requirement:``, ``hypothesis:``,
    ``scope_brief:``) are derived, context-dependent refs: truthful by
    construction for plan-generated tasks and dereferenced by the future
    lineage layer, not enforced here. ONE pairing is enforced at admission:
    when a task claims lineage to a research_program AND names
    ``evidence_requirement:<claim_ref>`` refs, each such ref must dereference
    to a real evidence requirement of a linked program — the same dereference
    rule the satisfaction write path applies, moved to admission so the
    controller only ever records links for gateway-validated pairs. A bare
    ``evidence_requirement:`` ref with NO program ref remains free-form
    metadata (the P3 non-reserved contract).
    """
    program_rows: list[dict] = []
    requirement_refs: list[str] = []
    for entry in node.provenance:
        if entry.startswith("research_program:"):
            program_id = program_ref_key(entry) or ""
            if not program_id:
                raise _reject(
                    intent.kind, PROVENANCE,
                    "empty research_program: reference in provenance",
                )
            try:
                row = program_repo.get(program_id)
            except NotFoundError:
                row = None
            if row is None or row["project_id"] != intent.project_id:
                raise _reject(
                    intent.kind, PROVENANCE,
                    f"provenance research_program:{program_id!r} does not "
                    f"dereference to a program governed by project "
                    f"{intent.project_id!r} (V6-FINAL-02 contract) — task "
                    f"cannot claim lineage to a program that does not exist",
                )
            program_rows.append(row)
        elif entry.startswith("evidence_requirement:"):
            claim_ref = entry[len("evidence_requirement:"):]
            if claim_ref:
                requirement_refs.append(claim_ref)
    if requirement_refs and program_rows:
        # Pairing contract: every evidence_requirement ref must dereference
        # to a real evidence requirement of a linked program (the plan emits
        # exactly this pairing; a forged/mismatched ref is a false-lineage
        # claim and is rejected at admission, never recorded as satisfaction).
        for claim_ref in requirement_refs:
            if not any(
                any(
                    isinstance(req, dict) and req.get("claim_ref") == claim_ref
                    for req in (program.get("evidence_requirements") or []))
                for program in program_rows):
                raise _reject(
                    intent.kind, PROVENANCE,
                    f"provenance evidence_requirement:{claim_ref!r} does not "
                    f"dereference to an evidence requirement of any linked "
                    f"research_program (V6-FINAL-02 pairing contract) — the "
                    f"task cannot claim a requirement its programs do not have",
                )


def _is_extract_spec(spec: Any) -> bool:
    """True iff ``spec`` carries the canonical EXTRACT template marker.

    The comparison is normalized (strip + casefold) against the canonical
    ``EXTRACT_TEMPLATE`` constant — a hand-built payload cannot case-spoof its
    way past the EXTRACT admission checks (V6-P7-E01).
    """
    if not isinstance(spec, dict):
        return False
    template = spec.get("template")
    return isinstance(template, str) and (
        template.strip().casefold() == EXTRACT_TEMPLATE)


def _validate_extract_source(
    conn: Any, intent: Intent, node: NodeContract,
) -> None:
    """Reject an EXTRACT task whose ``spec.source_ref`` does not dereference.

    IDR-028 criterion 7: an EXTRACT task for a source whose dereference fails
    (e.g. a missing ``dataset_manifest``) is rejected at admission — the
    IDR-027 F02 discipline, enforced earlier than the write path. Only
    EXTRACT-template tasks are checked (normalized marker, V6-P7-E01); the
    check is the same project-scoped carrier resolution
    ``ClaimAssumptionRepository`` applies at the write path, so admission and
    acceptance never disagree. Other task templates are untouched (ordinary
    INSERT_TASK semantics preserved).

    V6-P7-E02: because the marker matches, the EXTRACT contract is enforced
    here too — the template's pinned ``profile`` (RESEARCHER/C-tier), ``scope``
    vocabulary, and ``cost_class`` are gateway invariants, not helper
    defaults. A hand-built payload cannot admit an EXTRACT task with
    ``ADVERSARY`` profile or ``huge`` cost.
    """
    spec = node.spec or {}
    if not _is_extract_spec(spec):
        return
    source_ref = spec.get("source_ref")
    if not isinstance(source_ref, str) or ":" not in source_ref:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            "EXTRACT spec.source_ref must be an 'artifact_type:ref' "
            "reference",
        )
    if node.profile != EXTRACT_PROFILE:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"EXTRACT task profile must be {EXTRACT_PROFILE!r} (C-tier "
            f"bookkeeping, IDR-028 Decision 1) — got {node.profile!r} "
            f"(V6-P7-E02)",
        )
    scope = spec.get("scope")
    if scope not in EXTRACT_SCOPES:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"EXTRACT spec.scope must be one of "
            f"{sorted(EXTRACT_SCOPES)} — got {scope!r} (V6-P7-E02)",
        )
    if node.cost_class != EXTRACT_COST_CLASS:
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"EXTRACT task cost_class must be {EXTRACT_COST_CLASS!r} — "
            f"got {node.cost_class!r} (V6-P7-E02)",
        )
    artifact_type, _, artifact_id = source_ref.partition(":")
    if (artifact_type == "dataset_manifest"
            and not DatasetManifestRepository(conn).exists_in_project(
                artifact_id, intent.project_id)):
            raise _reject(
                intent.kind, PROVENANCE,
                f"EXTRACT source_ref {source_ref!r} does not dereference to "
                f"a dataset_manifest governed by project "
                f"{intent.project_id!r} (IDR-028 criterion 7) — the extraction "
                f"source must exist before its task is admitted",
            )


def _is_source_search_spec(spec: Any) -> bool:
    """True iff ``spec`` carries the canonical SOURCE_SEARCH marker
    (normalized — a hand-built payload cannot case-spoof, V6-P7-E01)."""
    if not isinstance(spec, dict):
        return False
    template = spec.get("template")
    return isinstance(template, str) and (
        template.strip().casefold() == SOURCE_SEARCH_TEMPLATE)


def _is_source_fetch_spec(spec: Any) -> bool:
    if not isinstance(spec, dict):
        return False
    template = spec.get("template")
    return isinstance(template, str) and (
        template.strip().casefold() == SOURCE_FETCH_TEMPLATE)


def _validate_source_spec(
    conn: Any,
    intent: Intent,
    node: NodeContract,
    task_repo: TaskRepository,
) -> None:
    """OQ-5 — the SOURCE_SEARCH / SOURCE_FETCH admission contract, enforced
    at INSERT_TASK time (the V6-P7-E01/E02 precedent): canonical normalized
    marker, pinned RESEARCHER/C-tier profile + ``small`` cost class,
    provider-allowlist membership (IDR-030), and positive bounded sizes — a
    hand-built payload cannot case-spoof or over-bound past admission
    (rejected at admission, never at execution). SOURCE_FETCH additionally
    requires its provider to be allowlisted, its search task to exist, be a
    SOURCE_SEARCH task of the SAME project (P1 lineage — a cross-project
    citation is rejected even when the refs resolve under the global-content
    sharing model), be a declared dependency, and its ``source_result:
    <full-hash>`` refs to RESOLVE against the persisted artifacts
    (project-edge-scoped) — a forged or dangling ref fails closed here.
    """
    spec = node.spec or {}
    if _is_source_search_spec(spec):
        if node.profile != SOURCE_PROFILE:
            raise _reject(
                intent.kind, MALFORMED_PAYLOAD,
                f"SOURCE_SEARCH task profile must be {SOURCE_PROFILE!r} "
                f"(C-tier, OQ-5) — got {node.profile!r}",
            )
        if node.cost_class != SOURCE_COST_CLASS:
            raise _reject(
                intent.kind, MALFORMED_PAYLOAD,
                f"SOURCE_SEARCH task cost_class must be "
                f"{SOURCE_COST_CLASS!r} — got {node.cost_class!r} (OQ-5)",
            )
        provider = spec.get("provider")
        if not isinstance(provider, str) or provider not in SOURCE_PROVIDER_ALLOWLIST:
            raise _reject(
                intent.kind, MALFORMED_PAYLOAD,
                f"SOURCE_SEARCH spec.provider must be one of "
                f"{sorted(SOURCE_PROVIDER_ALLOWLIST)} — got {provider!r} "
                f"(IDR-030 allowlist, OQ-5)",
            )
        for key, cap in (("page_size", SOURCE_PAGE_SIZE_CAP),
                         ("max_pages", SOURCE_MAX_PAGES_CAP),
                         ("size_cap_bytes", SOURCE_SIZE_CAP_BYTES_CAP)):
            value = spec.get(key)
            if not isinstance(value, int) or isinstance(value, bool) \
                    or not (1 <= value <= cap):
                raise _reject(
                    intent.kind, MALFORMED_PAYLOAD,
                    f"SOURCE_SEARCH spec.{key} must be an integer in "
                    f"[1, {cap}] — got {value!r} (OQ-6; over-bound requests "
                    f"are rejected at admission, never at execution)",
                )
        if not isinstance(spec.get("hints"), dict):
            raise _reject(
                intent.kind, MALFORMED_PAYLOAD,
                "SOURCE_SEARCH spec.hints must be a mapping (the "
                "deterministic RetrievalHints form, D2)",
            )
    elif _is_source_fetch_spec(spec):
        if node.profile != SOURCE_PROFILE:
            raise _reject(
                intent.kind, MALFORMED_PAYLOAD,
                f"SOURCE_FETCH task profile must be {SOURCE_PROFILE!r} "
                f"(C-tier, OQ-5) — got {node.profile!r}",
            )
        if node.cost_class != SOURCE_COST_CLASS:
            raise _reject(
                intent.kind, MALFORMED_PAYLOAD,
                f"SOURCE_FETCH task cost_class must be "
                f"{SOURCE_COST_CLASS!r} — got {node.cost_class!r} (OQ-5)",
            )
        provider = spec.get("provider")
        if not isinstance(provider, str) or provider not in SOURCE_PROVIDER_ALLOWLIST:
            raise _reject(
                intent.kind, MALFORMED_PAYLOAD,
                f"SOURCE_FETCH spec.provider must be one of "
                f"{sorted(SOURCE_PROVIDER_ALLOWLIST)} — got {provider!r} "
                f"(IDR-030 allowlist, OQ-5; required — the fetch handler "
                f"routes the adapter by it, so a provider-less fetch is "
                f"rejected at admission, never at execution)",
            )
        # R03 — the fetch task's OWN bounds, validated at admission exactly
        # like the search bounds (over-bound requests are rejected here,
        # never at execution; the handler builds the runtime FetchRequest
        # from this persisted spec — admission semantics == execution
        # semantics).
        for key, cap in (("max_sources", SOURCE_MAX_SOURCES_CAP),
                         ("size_cap_bytes", SOURCE_SIZE_CAP_BYTES_CAP)):
            value = spec.get(key)
            if not isinstance(value, int) or isinstance(value, bool) \
                    or not (1 <= value <= cap):
                raise _reject(
                    intent.kind, MALFORMED_PAYLOAD,
                    f"SOURCE_FETCH spec.{key} must be an integer in [1, {cap}] "
                    f"— got {value!r} (R03; over-bound requests are rejected "
                    f"at admission, never at execution)",
                )
        try:
            retry = _check_retry_policy(spec.get("retry_policy"))
        except ValueError as exc:
            raise _reject(
                intent.kind, MALFORMED_PAYLOAD,
                f"SOURCE_FETCH spec.retry_policy malformed: {exc} (R03)",
            ) from exc
        spec["retry_policy"] = retry
        search_task_id = spec.get("search_task_id")
        if not isinstance(search_task_id, str) or not search_task_id:
            raise _reject(
                intent.kind, MALFORMED_PAYLOAD,
                "SOURCE_FETCH spec.search_task_id must be a non-empty string "
                "(the producing SOURCE_SEARCH task, D2)",
            )
        # the search task must exist, be a SOURCE_SEARCH task, and be a
        # DECLARED dependency (the task graph expresses search → fetch)
        try:
            search_row = task_repo.get(search_task_id)
        except NotFoundError:
            search_row = None
        if search_row is None:
            raise _reject(
                intent.kind, DEPENDENCY,
                f"SOURCE_FETCH search task {search_task_id!r} does not "
                f"exist — a fetch task must cite a real search task (D2)",
            )
        if not _is_source_search_spec(search_row.get("spec") or {}):
            raise _reject(
                intent.kind, MALFORMED_PAYLOAD,
                f"SOURCE_FETCH search task {search_task_id!r} is not a "
                f"SOURCE_SEARCH task (D2)",
            )
        # PRE-STEP-7 CLOSURE (P1) — the search lineage must be SAME-PROJECT:
        # a SOURCE_FETCH may only cite a SOURCE_SEARCH task belonging to the
        # same project. The refs check below is project-edge-scoped, so a
        # cross-project citation can still resolve when the content is
        # globally shared (the legitimate reuse model) — the cited PRODUCING
        # task must match regardless, or the lineage is ambiguous.
        if search_row.get("project_id") != intent.project_id:
            raise _reject(
                intent.kind, PROVENANCE,
                f"SOURCE_FETCH search task {search_task_id!r} belongs to "
                f"project {search_row.get('project_id')!r}, not "
                f"{intent.project_id!r} — a fetch task may only cite a "
                f"SOURCE_SEARCH task of its OWN project (P1 lineage)",
            )
        if search_task_id not in (node.dependencies or ()):
            raise _reject(
                intent.kind, DEPENDENCY,
                f"SOURCE_FETCH must declare its search task "
                f"{search_task_id!r} as a dependency — no alternate task-"
                f"insertion path (D2)",
            )
        refs = spec.get("source_refs")
        if not isinstance(refs, list) or not refs:
            raise _reject(
                intent.kind, MALFORMED_PAYLOAD,
                "SOURCE_FETCH spec.source_refs must be a non-empty list of "
                "'source_result:<full-hash>' references (D2)",
            )
        if len(refs) > SOURCE_MAX_SOURCES_CAP:
            raise _reject(
                intent.kind, MALFORMED_PAYLOAD,
                f"SOURCE_FETCH spec.source_refs exceed max_sources cap "
                f"{SOURCE_MAX_SOURCES_CAP} (OQ-6)",
            )
        for ref in refs:
            if not isinstance(ref, str) or not ref.startswith("source_result:"):
                raise _reject(
                    intent.kind, MALFORMED_PAYLOAD,
                    f"SOURCE_FETCH spec.source_refs must all be "
                    f"'source_result:<full-hash>' — got {ref!r} (D2)",
                )
            if not _source_artifact_resolves(
                    conn, intent.project_id, ref[len("source_result:"):],
                    "source_result", upstream_task_id=search_task_id):
                raise _reject(
                    intent.kind, PROVENANCE,
                    f"SOURCE_FETCH source_ref {ref!r} does not dereference to "
                    f"a persisted source_result of the cited search task "
                    f"{search_task_id!r} in project {intent.project_id!r} "
                    f"(SD-05/R01) — the search must have produced it before "
                    f"the fetch is admitted",
                )


def _task_exists(task_repo: TaskRepository, task_id: str) -> bool:
    try:
        task_repo.get(task_id)
        return True
    except NotFoundError:
        return False


# TASK-ADMIT-1 (GAP-1 P1-6, ruling D3-A) — the pinned canonical byte domain of
# task-content identity. These are exactly the admission command's content
# fields; runtime state (``attempt``/``status``/timestamps/heartbeat) is never
# part of identity — a requeue increments ``attempt`` and a dispatch changes
# ``status``, and neither may turn an exact replay into a refusal. Project
# ownership is checked separately (before content): a row belonging to another
# project refuses regardless of content.
_TASK_CONTENT_FIELDS: tuple[str, ...] = (
    "task_type", "profile", "idempotency_key", "iteration",
    "parent_task_id", "spec", "inputs", "outputs", "dependencies",
    "provenance", "cost_class", "concurrency_group", "max_retries",
)


def _canonical_task_content(content: dict[str, Any]) -> str:
    """The canonical serialization of a task's content projection.

    ``sort_keys`` + compact separators over PARSED structures on both sides
    (the row is read through ``TaskRepository.get``, which parses the
    ``*_json`` columns; the intent payload is a dict on the wire), so raw
    stored JSON text is never compared. Key-order and JSON-formatting
    variants of the same logical content compare equal — no false refusal of
    a logical replay. ``dependencies`` is normalized to sorted order: the
    edges are a SET held in ``task_dependencies`` rows, and the readback
    order is a query-plan artifact (SQLite may serve the
    ``UNIQUE(task_id, depends_on_task_id)`` index scan), never content. The
    remaining lists (``inputs``/``outputs``/``provenance`` and arrays inside
    ``spec``) are stored as single JSON arrays — their order round-trips
    exactly — and order is content: a JSON array is not a serializer
    variant, so a reordered array is a differing command and fails closed.
    """
    import json as _json

    projection = {field: content.get(field)
                  for field in _TASK_CONTENT_FIELDS}
    dependencies = projection.get("dependencies")
    if isinstance(dependencies, (list, tuple)):
        # A non-comparable member (impossible for gateway-validated task
        # content) raises here and the caller refuses fail-closed.
        projection["dependencies"] = sorted(dependencies)
    return _json.dumps(
        projection, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False)


def _validate_insert_task(
    conn: Any,
    intent: Intent,
    *,
    task_repo: TaskRepository,
    program_repo: ResearchProgramRepository,
    clock: Callable[[], str],
    audit: AuditRecord | None = None,
) -> IntentResult:
    """INSERT_TASK / ADMIT_TASK: strict payload → atomic task admission.

    Idempotency: an existing task_id returns the existing row (crash/retry
    duplicate, Attack N) instead of raising a PK conflict — but ONLY for an
    exact content replay (per the pinned canonical domain) in the SAME
    project (TASK-ADMIT-1, ruling D3-A): a differing proposal and a
    foreign-project row both refuse with ``IDEMPOTENCY_CONFLICT``, never a
    silent admission and never the foreign row returned as "yours".
    Dependency violations (cycles, missing deps) reject — never admitted.
    Every repository-level constraint failure is surfaced as a structured
    ``GatewayRejection`` code (V6-FINAL-01): FK violation on a missing
    dependency → ``DEPENDENCY``; ``UNIQUE(idempotency_key, attempt)`` reuse by
    a different task → ``IDEMPOTENCY_CONFLICT``; anything else →
    ``MALFORMED_PAYLOAD`` — never a raw ``sqlite3.IntegrityError``.
    """
    node = _payload_to_node(intent)
    _validate_provenance(intent, node, program_repo)
    _validate_extract_source(conn, intent, node)
    _validate_source_spec(conn, intent, node, task_repo)
    try:
        existing = task_repo.get(node.task_id)
    except NotFoundError:
        existing = None
    if existing is not None:
        # TASK-ADMIT-1 (GAP-1 P1-6, ruling D3-A): fail-closed. The row is
        # returned as a duplicate only when the task_id is already claimed by
        # the SAME command in the SAME project.
        if str(existing.get("project_id") or "") != node.project_id:
            raise _reject(
                intent.kind, IDEMPOTENCY_CONFLICT,
                f"task admission rejected: task_id {node.task_id!r} is "
                f"already admitted under project "
                f"{existing.get('project_id')!r}, not "
                f"{node.project_id!r} — a task_id identifies one task in one "
                f"project, never two (project isolation; PA4)",
            )
        incoming_content = {
            field: getattr(node, field) for field in _TASK_CONTENT_FIELDS
        }
        try:
            content_matches = (
                _canonical_task_content(incoming_content)
                == _canonical_task_content(existing)
            )
        except (TypeError, ValueError) as exc:
            raise _reject(
                intent.kind, MALFORMED_PAYLOAD,
                f"task admission rejected: the task content is not "
                f"canonically serialisable ({type(exc).__name__}: {exc}) — "
                f"identity cannot be compared, so the task_id collision "
                f"fails closed",
            ) from exc
        if not content_matches:
            raise _reject(
                intent.kind, IDEMPOTENCY_CONFLICT,
                f"task admission rejected: task_id {node.task_id!r} is "
                f"already admitted with different content — a task_id "
                f"identifies one command, never two (PA4); only an exact "
                f"content replay returns the stored row",
            )
        return IntentResult(
            kind=intent.kind,
            entity_type="task",
            entity_id=node.task_id,
            duplicate=True,
            row=existing,
            event_type=EventType.TASK_CREATED.value,
        )
    try:
        row = task_repo.create(node, audit=audit)
    except DependencyError as exc:
        raise _reject(
            intent.kind, DEPENDENCY,
            f"task admission rejected: {exc} — the task graph stays a DAG "
            f"(v4 \u00a77)",
        ) from exc
    except sqlite3.IntegrityError as exc:
        message = str(exc)
        if "FOREIGN KEY" in message:
            missing = [d for d in node.dependencies
                       if not _task_exists(task_repo, d)]
            raise _reject(
                intent.kind, DEPENDENCY,
                f"task admission rejected: dependency "
                f"{missing[0] if missing else '?'} does not exist (FK "
                f"enforced) — the task graph stays a DAG (v4 \u00a77)",
            ) from exc
        if "idempotency_key" in message:
            raise _reject(
                intent.kind, IDEMPOTENCY_CONFLICT,
                f"task admission rejected: idempotency_key "
                f"{node.idempotency_key!r} is already claimed by another "
                f"task — reuse a distinct key (PA4: a key identifies one "
                f"command, never two)",
            ) from exc
        raise _reject(
            intent.kind, MALFORMED_PAYLOAD,
            f"task admission rejected: integrity constraint {message}",
        ) from exc
    return IntentResult(
        kind=intent.kind,
        entity_type="task",
        entity_id=node.task_id,
        duplicate=False,
        row=row,
        event_type=EventType.TASK_CREATED.value,
    )


# ── the gateway ──

def apply_intent(
    conn: Any,
    intent: Intent,
    *,
    clock: Callable[[], str] | None = None,
    project_repo: ProjectRepository | None = None,
    task_repo: TaskRepository | None = None,
    program_repo: ResearchProgramRepository | None = None,
    budget_check: Callable[[Intent], None] | None = None,
    governance_consult: Callable[[Intent], None] | None = None,
) -> IntentResult:
    """The single authoritative mutation path (v3 §8, P3).

    Deterministic admission: kind → role → project → **provenance bounds** →
    **payload shape bounds** → budget → per-kind validator → mutation (atomic
    with its own event) → ``IntentApplied`` audit event. Any rejection emits
    ``IntentRejected`` and raises ``GatewayRejection`` (code = stable
    category).

    The provenance-bounds stage is IDR-045 C5, enforced pre-write by
    ``_require_provenance_bounds`` so an invalid field can never reach a
    validator that owns a transaction. It sits **before** ``budget_check``, so
    an intent that is both malformed and budget-rejected yields
    ``MALFORMED_PAYLOAD``, not ``BUDGET`` — a cheap local shape check precedes
    a caller-supplied hook. This precedence is deliberate and is pinned by
    ``tests/test_idr045_merge_audit_045_c1.py`` (MERGE-AUDIT-045-FIX C5).

    ``budget_check`` defaults to a no-op: the budget ledger is a deferred
    subsystem (v6 §27 items / §28.5), and this hook is where it plugs in.

    ``governance_consult`` is BIND-4's Site-A registration seam: an optional
    read-only preflight, supplied by the caller, that reads the governance
    plane's public entry (`evaluate_authority` over the shipped canonical
    policy) and refuses by raising this module's own ``GatewayRejection`` —
    the code travels verbatim (never translated), and any non-``GatewayRejection``
    failure is mapped to the frozen ``MALFORMED_PAYLOAD``. It defaults to
    ``None``, so every existing caller's behavior is byte-identical. The
    governance plane stays a pure library: nothing here imports it, and this
    module is not a governance consumer.
    """
    from hermes.core import utc_now

    clock = clock or utc_now
    project_repo = project_repo or ProjectRepository(conn, clock)
    task_repo = task_repo or TaskRepository(conn, clock)
    program_repo = program_repo or ResearchProgramRepository(conn, clock)

    if not isinstance(intent, Intent):
        raise TypeError(f"apply_intent requires an Intent, got {type(intent).__name__}")

    # Every admission stage is inside the try so that ANY rejection — role,
    # project, budget, payload, compilation — is recorded as an
    # ``IntentRejected`` audit event before the rejection propagates.
    try:
        if intent.kind not in IntentKind:
            raise GatewayRejection(
                intent.kind if isinstance(intent.kind, IntentKind) else IntentKind.INSERT_TASK,
                UNKNOWN_KIND, f"unknown intent kind {intent.kind!r}")

        _require_role(intent)
        _require_project(intent, project_repo)
        # IDR-045 C5 — provenance bounds, PRE-WRITE (MERGE-AUDIT-045 F2).
        # Must precede the validator dispatch below: validators own their own
        # transactions and commit rows, so a bound enforced after dispatch
        # would refuse an intent whose row is already durable.
        _require_provenance_bounds(intent)
        _require_payload_bounds(intent)

        if budget_check is not None:
            try:
                budget_check(intent)
            except GatewayRejection:
                raise
            except Exception as exc:
                raise _reject(intent.kind, BUDGET, f"budget check rejected: {exc}") from exc

        if governance_consult is not None:
            # BIND-4 Site A — the read-only governance preflight, REGISTERED
            # here by the caller (the composition root / the wired run). The
            # consult is pure (no clock, no store, no I/O): it evaluates the
            # public governance entry over the snapshots IT was handed, and
            # answers by raising a ``GatewayRejection`` — the spine's own
            # frozen code, surfaced NATIVELY and VERBATIM (governance's refusal
            # vocabulary mirrors this module's by construction, so nothing is
            # translated, remapped or wrapped). A refusal that is not a
            # ``GatewayRejection`` is the consult's own shape failure and maps
            # to the frozen ``MALFORMED_PAYLOAD`` — this seam never invents a
            # code. The consult writes nothing: a mutation is still only ever
            # the validator chain's, driven by this one function.
            try:
                governance_consult(intent)
            except GatewayRejection:
                raise
            except Exception as exc:
                raise _reject(
                    intent.kind, MALFORMED_PAYLOAD,
                    f"governance consult refused: {exc}") from exc

        # AUDIT-TXN (IDR-013 addendum A1.2/A1.3): the applied audit record is
        # built ONCE, here, and validated with the same 4 KiB / secret /
        # event-type gate the writer applies — before any validator can open
        # a transaction. An over-cap or secret-bearing record refuses
        # pre-write and journals IntentRejected like every other refusal;
        # under fusion a late refusal would otherwise unwind a committed
        # mutation. The record is then handed to the dispatched validator as
        # explicit data (never connection state).
        audit = _append_audit_event(clock, intent, applied=True)
        try:
            validate_event(audit.event_type, audit.payload)
        except EventValidationError as exc:
            raise _reject(
                intent.kind, MALFORMED_PAYLOAD,
                f"audit payload refused before dispatch: {exc}") from exc

        if intent.kind is IntentKind.PROPOSE_RESEARCH_PROGRAM:
            result = _validate_propose_research_program(
                conn, intent, program_repo=program_repo, clock=clock,
                audit=audit)
        elif intent.kind is IntentKind.PROPOSE_CLASSIFICATION_ACTION:
            result = _validate_propose_classification_action(
                conn, intent, clock=clock, audit=audit)
        elif intent.kind is IntentKind.RESOLVE_CLASSIFICATION_PROPOSAL:
            result = _validate_resolve_classification_proposal(
                conn, intent, clock=clock, audit=audit)
        elif intent.kind is IntentKind.RECORD_SCOPE_REVIEW_DECISION:
            result = _validate_record_scope_review_decision(
                conn, intent, clock=clock, audit=audit)
        elif intent.kind is IntentKind.RETRACT_SOURCE:
            result = _validate_retract_source(
                conn, intent, clock=clock, audit=audit)
        elif intent.kind is IntentKind.CURATE_KNOWLEDGE:
            result = _validate_curate_knowledge(
                conn, intent, clock=clock, audit=audit)
        elif intent.kind is IntentKind.RECORD_CONTRADICTION:
            result = _validate_record_contradiction(
                conn, intent, clock=clock, audit=audit)
        elif intent.kind is IntentKind.CONTRADICTION_RESOLUTION:
            result = _validate_contradiction_resolution(
                conn, intent, clock=clock, audit=audit)
        elif intent.kind is IntentKind.RECORD_CLASSIFICATION:
            result = _validate_record_classification(
                conn, intent, clock=clock, audit=audit)
        elif intent.kind is IntentKind.EMIT_PARALLEL_REGIME_PROGRAM:
            result = _validate_emit_parallel_regime_program(
                conn, intent, program_repo=program_repo, clock=clock,
                audit=audit)
        elif intent.kind in (IntentKind.REVOKE_OPERATOR_CREDENTIAL,
                             IntentKind.ROTATE_OPERATOR_CREDENTIAL):
            result = _validate_operator_credential_mutation(
                conn, intent, clock=clock, audit=audit)
        elif intent.kind is IntentKind.EVIDENCE_TRANSITION:
            result = _validate_evidence_transition(
                conn, intent, clock=clock, audit=audit)
        elif intent.kind in (IntentKind.INSERT_TASK, IntentKind.ADMIT_TASK):
            result = _validate_insert_task(
                conn, intent, task_repo=task_repo, program_repo=program_repo,
                clock=clock, audit=audit)
        elif intent.kind is IntentKind.REQUEST_ADDITIONAL_EXPERIMENT:
            result = _validate_request_additional_experiment(
                conn, intent, clock=clock, audit=audit)
        elif intent.kind is IntentKind.RECORD_VERIFICATION_OUTCOME:
            result = _validate_record_verification_outcome(
                conn, intent, clock=clock, audit=audit)
        else:
            raise _reject(
                intent.kind, NOT_WIRED,
                f"{intent.kind.value} is declared but its gateway validator "
                f"is not wired in this phase (PROPOSE_RESEARCH_PROGRAM, "
                f"PROPOSE_CLASSIFICATION_ACTION, RESOLVE_CLASSIFICATION_"
                f"PROPOSAL, RECORD_SCOPE_REVIEW_DECISION, EVIDENCE_"
                f"TRANSITION, INSERT_TASK, ADMIT_TASK)",
            )
    except GatewayRejection:
        _write_audit_event(
            conn, clock, _append_audit_event(clock, intent, applied=False))
        raise
    except Exception:
        _write_audit_event(
            conn, clock, _append_audit_event(clock, intent, applied=False))
        raise

    # AUDIT-TXN A1.3 invariant 2: on a duplicate the call wrote NO mutation,
    # so its audit row stands alone (the mutation it reports is durable from
    # the earlier admission, which fused its own audit row). On a real write
    # the owner already appended the record inside the mutation transaction —
    # writing it again here would duplicate it and break the crash window.
    if result.duplicate:
        _write_audit_event(conn, clock, audit)
    return result


def _append_audit_event(
    clock: Callable[[], str],
    intent: Intent,
    *,
    applied: bool,
) -> AuditRecord:
    """Build the IntentApplied / IntentRejected audit record (pure).

    AUDIT-TXN (IDR-013 addendum A1.2): this is a BUILDER, not a writer. It
    returns the record so ``apply_intent`` can hand it to the transaction
    that owns the mutation (fused append) or write it on its own (duplicate /
    rejection). The payload and its provenance-clamping logic are unchanged
    from the pre-fusion writer.

    The ``events.project_id`` column references ``projects`` (FK enforced), so
    when the rejection is a missing/stale project the column falls back to
    NULL — the project id stays in the payload (rejection is never dropped
    from the audit trail). That fallback lives in ``_write_audit_event``,
    which owns the retry.

    IDR-045 D2: provenance fields are appended **only when non-default**
    (``None``-guarded) so the default payload stays byte-identical (V2/V3).
    Per-field max lengths (C5) are **not** enforced here: this builder runs
    before dispatch, and the bounds are enforced pre-write by
    ``_require_provenance_bounds`` from ``apply_intent``, and fail-closed at
    construction in ``Intent.__post_init__``. The gateway's role gate reads
    ``proposed_by`` only — ``origin_*`` is never authority (V1).
    """
    kind_label = (intent.kind.value if isinstance(intent.kind, IntentKind)
                  else str(intent.kind))
    event_type = EventType.INTENT_APPLIED.value if applied else EventType.INTENT_REJECTED.value
    payload: dict[str, Any] = {
        "intent_kind": kind_label,
        "proposed_by": intent.proposed_by,
        "project_id": intent.project_id,
        "justification": intent.justification,
    }
    # V2/V3 — append provenance only when non-default (conditional insert).
    #
    # MERGE-AUDIT-045-FIX C1 / C1b ruling: the audit-event builder must never
    # fail on the values it reports, so refusal journaling is TOTAL. A rejected
    # intent reaches this function carrying the very value that
    # `_require_provenance_bounds` just refused. Writing that value verbatim
    # could not succeed: an over-bound string breaches the 4 KiB event cap
    # (S6) and a non-`str` raises `TypeError` from `json.dumps`. Either way the
    # structured `GatewayRejection` was replaced by a raw error and the refusal
    # lost its journal row — the exact F2 signature, by a second route.
    #
    # So: bound what is echoed, and mark that bounding happened. The rejection
    # code and reason stay exact; only the echoed value is clamped, and the
    # marker records what was clamped so nothing is silently misreported.
    # An applied intent can never reach here with an invalid value: the bounds
    # check refuses it before the validator commits, so this clamping only ever
    # affects a refusal record.
    _provenance_bounds: list[str] = []
    for _name, _limit in _PROVENANCE_FIELD_LIMITS:
        _value = getattr(intent, _name)
        if _value is None:
            continue
        if not isinstance(_value, str):
            _provenance_bounds.append(
                f"{_name}=<omitted non-str {type(_value).__name__}>")
            continue
        if len(_value) > _limit:
            payload[_name] = _value[:_limit]
            _provenance_bounds.append(
                f"{_name}=<truncated {len(_value)}->{_limit}>")
            continue
        payload[_name] = _value
    if _provenance_bounds:
        payload["provenance_bounded"] = _provenance_bounds
    return AuditRecord(
        event_type=event_type,
        project_id=intent.project_id,
        correlation_id=f"intent-{kind_label}-{clock()}",
        caused_by=intent.proposed_by,
        reason="" if applied else "intent rejected",
        payload=payload,
    )


def _write_audit_event(
    conn: Any,
    clock: Callable[[], str],
    record: AuditRecord,
) -> None:
    """Write one audit row in ITS OWN transaction.

    AUDIT-TXN (A1.2/A1.3): used ONLY where the call wrote no mutation — a
    duplicate replay and a rejection. A rejection produces no mutation, so
    there is nothing to fuse and nothing that can be stranded; keeping its
    own transaction is also what keeps the ``retry_without_project`` FK
    fallback available. The fused mutation path never reaches this function,
    so ``append_transactional``'s ROLLBACK-retry can never run inside a
    mutation transaction.

    Refusal journaling stays total even when the echoed value is itself why
    the row cannot be written (an over-cap or secret-bearing justification):
    the record is bounded once, marked, and written — the refusal code and
    reason are never lost.
    """
    try:
        _append_audit_row(conn, clock, record)
    except EventValidationError as exc:
        justification = record.payload.get("justification")
        if not isinstance(justification, str):
            raise
        bounded = dict(record.payload)
        if exc.field == "payload_json":
            bounded["justification"] = justification[:1024]
            marker = f"justification=<truncated {len(justification)}->1024>"
        else:
            # A secret-format match (or any other value defect): the echo is
            # omitted, never sanitised into something that looks authored.
            bounded.pop("justification", None)
            marker = f"justification=<omitted: {exc.reason}>"
        bounded["audit_bounded"] = [marker]
        _append_audit_row(
            conn, clock,
            AuditRecord(
                event_type=record.event_type,
                project_id=record.project_id,
                correlation_id=record.correlation_id,
                caused_by=record.caused_by,
                reason=record.reason,
                payload=bounded,
            ),
        )


def _append_audit_row(
    conn: Any,
    clock: Callable[[], str],
    record: AuditRecord,
) -> None:
    """The single own-transaction write of an ``AuditRecord``."""
    EventRepository(conn).append_transactional(
        clock, record.event_type,
        project_id=record.project_id,
        correlation_id=record.correlation_id,
        caused_by=record.caused_by,
        reason=record.reason,
        payload=record.payload,
        retry_without_project=True,
    )

