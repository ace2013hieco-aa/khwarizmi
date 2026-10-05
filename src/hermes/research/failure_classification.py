"""Q-05 — FALSIFIED/REFUTED failure classification (v6 §10.2 substrate).

Hermes' ratified falsification terminus is **REFUTED** (v6 §10.1/§10.2: "any →
REFUTED" on decisive falsification). The Evidence Ladder itself is a Phase 0
placeholder on this baseline (no evidence table, no EvidenceRepository); Q-05
lands the FIRST implementable piece: a pure, deterministic failure-
classification substrate that answers *why* a hypothesis failed — with a
versioned taxonomy, citation validation, and a deterministic permitted-action
map — WITHOUT building the ladder, without a new state machine, without a
write path, and without any authority.

Design record: ``hermes_q05_failure_classification_design.md`` (design gate
passed, hostile self-review clean). Reconciliation of the surviving-ideas
framework: ``hermes_surviving_ideas_repo_reconciliation.md``.

Non-negotiables (each is a structural property of this module, not a rule):
- **No writes.** No SQL, no repository imports, no gateway imports, no event
  writes, no filesystem/network. The module is a pure function of
  (``FalsificationRecord``, ``FailureClassificationDraft``, injected
  resolvers).
- **No authority.** An ADMITTED classification is advisory metadata. The
  permitted-action set is a *permission* computation — the mapping never
  executes the action, never creates a hypothesis/task, never revises a
  ScopeBrief, never changes ladder state, never touches a budget.
- **No state machine.** The taxonomy is a classification vocabulary, not a
  lifecycle. The consumed record is the shape the future REFUTED write path
  will persist (substrate-first; the manual-proof-first rule, v6 §29.2
  rule 7).
- **Citation discipline.** Every ADMITTED classification traces to the
  falsified evidence (``draft.evidence_refs ⊆ record.falsifying_evidence_refs``),
  the hypothesis, the program, and the class-required citation — each of
  which must RESOLVE via the injected project-scoped resolver, or the
  classification is REJECTED (fail-closed, mirroring ``thesis.py``).
- **Determinism + versioning.** Same (record, draft, resolver behavior) ⇒
  identical structured output; ``classification_id`` is content-derived and
  binds (``schema_version``, ``classifier_version``, content). A
  reclassification under a new classifier version is a NEW derived record —
  historical truth is never mutated.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping

from hermes.research.programs import canonical_json, sha256_hex

__all__ = [
    "ACTION_MAP",
    "FAILURE_CLASS_SCHEMA_VERSION",
    "MAX_EXPLANATION_LENGTH",
    "ClassificationError",
    "ClassificationResult",
    "ClassificationVerdict",
    "ConditionType",
    "FailureClass",
    "FailureClassification",
    "FailureClassificationDraft",
    "FalsificationRecord",
    "PermittedAction",
    "ResourceGap",
    "certifies_decisive_falsification",
    "classification_command_hash",
    "classify_failure",
    "permitted_actions_for",
    "proposal_requires_human_confirmation",
    "requires_human_confirmation_for",
    "requires_human_confirmation_for_action",
    "summarize_classification",
]

# ── taxonomy version (the enum + action map are schema-versioned) ──
FAILURE_CLASS_SCHEMA_VERSION = "2"

# Capped advisory rationale length (schema discipline — never a citation).
MAX_EXPLANATION_LENGTH = 4000


class FailureClass(str, Enum):
    """The closed taxonomy of *why* a hypothesis failed (v6 §10.2 substrate).

    Rebased on Hermes-native carriers (reconciliation §2.3): "axiom" has no
    Hermes concept, so HARD_AXIOM_VIOLATION became DECLARED_CONSTRAINT_VIOLATION;
    UNKNOWN is the honest fallback the framework's own §12 demands. Exactly-one
    primary + optional ``contributing_factors``; MULTI_FACTOR is not a class.
    """

    DECLARED_CONSTRAINT_VIOLATION = "DECLARED_CONSTRAINT_VIOLATION"
    IMPLEMENTATION_FAILURE = "IMPLEMENTATION_FAILURE"
    ENVIRONMENT_MISMATCH = "ENVIRONMENT_MISMATCH"
    RESOURCE_CONSTRAINT = "RESOURCE_CONSTRAINT"
    FRAMING_ERROR = "FRAMING_ERROR"
    MECHANISM_DECAYED = "MECHANISM_DECAYED"
    UNKNOWN = "UNKNOWN"


class ConditionType(str, Enum):
    """The nature of the environmental difference that produced an
    ENVIRONMENT_MISMATCH (v6 §10.2 substrate).

    Meaningful ONLY for ENVIRONMENT_MISMATCH; UNDETERMINED and ignored for
    every other class.

    * ``INTRINSIC`` — the environment that differs is the *same kind* of
      environment the hypothesis targets (e.g. the target market's own
      regime). The mismatch is a property of the hypothesis, not the
      evaluation. Admits only PROPOSE_SCOPE_NARROWING.
    * ``ACCIDENTAL`` — the environment that differs is an incidental
      artifact of the *evaluation* (e.g. test-harness stubs, sandbox
      credentials, mocked upstream). The regime itself is not the subject.
      Admits PROPOSE_SCOPE_NARROWING plus PROPOSE_PARALLEL_REGIME_TEST.
    * ``UNDETERMINED`` — the nature of the mismatch could not be ascertained.
      Treated conservatively like ACCIDENTAL (the wider action set).
    """

    INTRINSIC = "INTRINSIC"
    ACCIDENTAL = "ACCIDENTAL"
    UNDETERMINED = "UNDETERMINED"


class PermittedAction(str, Enum):
    """Hermes-native *proposal categories* — never executed by this module.

    The vocabulary deliberately contains no creation/mutation actions:
    proposing a mechanism substitution still requires the existing Director
    ``PROPOSE_RESEARCH_PROGRAM`` gateway path; rejecting a branch still
    requires the existing ABANDON/EVIDENCE_TRANSITION authority; narrowing
    scope still requires the S16 human amendment path.
    """

    REJECT_BRANCH = "REJECT_BRANCH"
    REVIEW_DOWNSTREAM_IMPACT = "REVIEW_DOWNSTREAM_IMPACT"
    PROPOSE_MECHANISM_SUBSTITUTION = "PROPOSE_MECHANISM_SUBSTITUTION"
    PROPOSE_PARALLEL_REGIME_TEST = "PROPOSE_PARALLEL_REGIME_TEST"
    PROPOSE_SCOPE_NARROWING = "PROPOSE_SCOPE_NARROWING"
    PARK_FOR_RESOURCE_REVIEW = "PARK_FOR_RESOURCE_REVIEW"
    ROUTE_TO_SCOPE_REVIEW = "ROUTE_TO_SCOPE_REVIEW"
    ESCALATE_TO_DIRECTOR = "ESCALATE_TO_DIRECTOR"


# ── the deterministic mapping (the ONLY mapping; computed, never executed) ──
# Base action sets for every class except ENVIRONMENT_MISMATCH (which is
# resolved by ``_action_map_for`` since its set depends on ConditionType).
_ACTION_MAP_BASE: dict[FailureClass, frozenset[PermittedAction]] = {
    FailureClass.DECLARED_CONSTRAINT_VIOLATION: frozenset({
        PermittedAction.REJECT_BRANCH,
        PermittedAction.REVIEW_DOWNSTREAM_IMPACT,
    }),
    FailureClass.IMPLEMENTATION_FAILURE: frozenset({
        PermittedAction.PROPOSE_MECHANISM_SUBSTITUTION,
    }),
    FailureClass.RESOURCE_CONSTRAINT: frozenset({
        PermittedAction.PARK_FOR_RESOURCE_REVIEW,
    }),
    FailureClass.FRAMING_ERROR: frozenset({
        PermittedAction.ROUTE_TO_SCOPE_REVIEW,
    }),
    # MECHANISM_DECAYED: the mechanism was not falsified in this regime at
    # one time, but a LATER FalsificationRecord falsified it in the SAME
    # regime (a temporal, not cross-sectional, decay of the mechanism's
    # survival record). The semantically-aligned permitted proposal is
    # PROPOSE_MECHANISM_SUBSTITUTION — the mechanism that survived a prior
    # regime is now falsified in that same regime, so the advisory action is
    # to propose a replacement mechanism via the existing Director
    # PROPOSE_RESEARCH_PROGRAM path. REJECT_BRANCH is not used because
    # MECHANISM_DECAYED is NOT a falsification of the hypothesis itself
    # (it is a falsification of a mechanism within the regime), so the
    # surviving idea's branch is not rejected — only the mechanism is.
    FailureClass.MECHANISM_DECAYED: frozenset({
        PermittedAction.PROPOSE_MECHANISM_SUBSTITUTION,
    }),
    FailureClass.UNKNOWN: frozenset({
        PermittedAction.ESCALATE_TO_DIRECTOR,
    }),
}

# ENVIRONMENT_MISMATCH action sets keyed by ConditionType:
#   INTRINSIC  → narrow only (the mismatch is a property of the hypothesis)
#   ACCIDENTAL → narrow + propose a parallel regime test (the mismatch is an
#                artifact of the evaluation)
#   UNDETERMINED → treated identically to ACCIDENTAL (conservative)
_ENVIRONMENT_MISMATCH_ACTIONS: dict[ConditionType, frozenset[PermittedAction]] = {
    ConditionType.INTRINSIC: frozenset({
        PermittedAction.PROPOSE_SCOPE_NARROWING,
    }),
    ConditionType.ACCIDENTAL: frozenset({
        PermittedAction.PROPOSE_SCOPE_NARROWING,
        PermittedAction.PROPOSE_PARALLEL_REGIME_TEST,
    }),
    ConditionType.UNDETERMINED: frozenset({
        PermittedAction.PROPOSE_SCOPE_NARROWING,
        PermittedAction.PROPOSE_PARALLEL_REGIME_TEST,
    }),
}


def _action_map_for(
    failure_class: FailureClass,
    condition_type: ConditionType,
) -> frozenset[PermittedAction]:
    """Resolve the permitted-action set as a function of
    ``(FailureClass, ConditionType)``.

    ``ConditionType`` is meaningful ONLY for ``ENVIRONMENT_MISMATCH``; for
    every other class it is ignored (the base set is returned unchanged).
    """
    if failure_class is FailureClass.ENVIRONMENT_MISMATCH:
        return _ENVIRONMENT_MISMATCH_ACTIONS[condition_type]
    return _ACTION_MAP_BASE[failure_class]


# Backward-compatible ACTION_MAP: the UNDETERMINED (default) view of the
# mapping, for external consumers that still index by FailureClass alone.
# New code should use ``permitted_actions_for`` or ``_action_map_for``.
ACTION_MAP: dict[FailureClass, frozenset[PermittedAction]] = {
    fc: _action_map_for(fc, ConditionType.UNDETERMINED)
    for fc in FailureClass
}

# The classes that REQUIRE a supporting evidence citation (UNKNOWN may cite
# none). The evidence must always be the falsifying evidence of the record.
_EVIDENCE_REQUIRED_CLASSES = frozenset({
    FailureClass.DECLARED_CONSTRAINT_VIOLATION,
    FailureClass.IMPLEMENTATION_FAILURE,
    FailureClass.ENVIRONMENT_MISMATCH,
    FailureClass.RESOURCE_CONSTRAINT,
    FailureClass.FRAMING_ERROR,
    FailureClass.MECHANISM_DECAYED,
})


class ClassificationVerdict(str, Enum):
    """Deterministic verdict of a failure classification (fail-closed)."""

    ADMITTED = "ADMITTED"   # schema + citations + identity valid
    REJECTED = "REJECTED"   # any structured error


# ── inputs ──

@dataclass(frozen=True, slots=True)
class FalsificationRecord:
    """The record being classified — the shape the future REFUTED write path
    will persist. The substrate defines this shape NOW so the ladder can land
    the classification as a metadata field + citation edges later.

    ``falsifying_evidence_refs`` are the evidence artifacts that falsified
    the hypothesis (the record's own evidence); a classification may only
    cite a subset of these — it can never reach outside the record.
    """

    project_id: str
    hypothesis_ref: str
    program_ref: str
    falsifying_evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResourceGap:
    """A MEASURED resource deficit (RESOURCE_CONSTRAINT citation).

    ``observed < required`` is a deterministic numeric check — a bare claim
    of "not enough resources" without a measurable deficit is REJECTED.
    """

    resource_kind: str
    observed: float
    required: float
    unit: str


@dataclass(frozen=True, slots=True)
class FailureClassificationDraft:
    """The LLM-proposed classification; the deterministic validator decides.

    ``classifier_version`` is REQUIRED and enters the identity (the taxonomy
    is versioned — a reclassification under a new version is a new derived
    record, never a mutation of history). Class-specific citations are
    validated per-class; a citation the class does not require is REJECTED
    (never silently dropped — the closed-schema discipline).
    """

    failure_class: str
    explanation: str
    evidence_refs: tuple[str, ...] = ()
    contributing_factors: tuple[str, ...] = ()
    constraint_ref: str | None = None        # DECLARED_CONSTRAINT_VIOLATION
    failed_mechanism_ref: str | None = None  # IMPLEMENTATION_FAILURE / MECHANISM_DECAYED (a prediction/observable)
    regime_ref: str | None = None            # ENVIRONMENT_MISMATCH
    resource_gap: ResourceGap | None = None  # RESOURCE_CONSTRAINT
    scope_brief_ref: str | None = None       # FRAMING_ERROR
    scope_brief_field: str | None = None     # FRAMING_ERROR
    proposed_by: str = ""
    classifier_version: str = ""
    condition_type: ConditionType = ConditionType.UNDETERMINED


# ── outputs ──

@dataclass(frozen=True, slots=True)
class ClassificationError:
    """A single structured reason for a non-ADMITTED verdict (fail-closed)."""

    code: str
    field_path: str
    requirement: str
    explanation: str
    suggested_next_action: str


@dataclass(frozen=True, slots=True)
class FailureClassification:
    """The ADMITTED advisory classification — never a decision.

    ``permitted_actions`` is the deterministic lookup result (proposal
    categories); ``requires_human_confirmation`` is True iff the class is
    FRAMING_ERROR (it implicates the ScopeBrief itself). Identity is derived,
    never authored.
    """

    classification_id: str
    schema_version: str
    classifier_version: str
    project_id: str
    hypothesis_ref: str
    program_ref: str
    failure_class: FailureClass
    contributing_factors: tuple[FailureClass, ...]
    evidence_refs: tuple[str, ...]
    constraint_ref: str | None
    failed_mechanism_ref: str | None
    regime_ref: str | None
    resource_gap: ResourceGap | None
    scope_brief_ref: str | None
    scope_brief_field: str | None
    explanation: str
    proposed_by: str
    condition_type: ConditionType
    permitted_actions: tuple[PermittedAction, ...]
    requires_human_confirmation: bool
    content_hash: str


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    """The deterministic outcome of classifying a falsification record."""

    verdict: ClassificationVerdict
    errors: tuple[ClassificationError, ...] = ()
    classification: FailureClassification | None = None

    @property
    def admitted(self) -> bool:
        return self.verdict is ClassificationVerdict.ADMITTED


# ── injected resolver protocol (the write path supplies real resolvers) ──
# Every resolver is project-scoped — a classification from another project
# cannot dereference (attack class 9). A resolver missing for a REQUIRED
# citation fails closed (thesis.py contract).
EvidenceResolver = Callable[[str, str], bool]                       # (project_id, ref)
ConstraintResolver = Callable[[str, str, str], bool]                # (project_id, program_ref, constraint_ref)
MechanismResolver = Callable[[str, str, str], bool]                 # (project_id, program_ref, mechanism_ref)
RegimeResolver = Callable[[str, str], bool]                         # (project_id, regime_ref)
ScopeFieldResolver = Callable[[str, str, str], bool]                # (project_id, brief_ref, field)


# ── the validator ──

def _err(code: str, path: str, requirement: str, why: str,
         fix: str) -> ClassificationError:
    return ClassificationError(code, path, requirement, why, fix)


def classify_failure(
    record: FalsificationRecord,
    draft: FailureClassificationDraft,
    *,
    evidence_resolver: EvidenceResolver | None = None,
    constraint_resolver: ConstraintResolver | None = None,
    mechanism_resolver: MechanismResolver | None = None,
    regime_resolver: RegimeResolver | None = None,
    scope_field_resolver: ScopeFieldResolver | None = None,
) -> ClassificationResult:
    """Deterministically classify a falsification record (pure, never raises).

    Checks, in order (fail-closed; all errors in a class collected): record
    schema → failure_class vocabulary → classifier_version → explanation →
    evidence refs (non-empty for evidence-required classes, ⊆ the record's
    falsifying evidence, no duplicates, each resolving project-scoped) →
    contributing factors (vocabulary, disjoint from primary) → class-specific
    required citation (present + resolving) → anti-extraneous citation rule
    (a citation the class does not require is rejected) → resource-gap
    numeric rule → identity + action map.

    Any failure ⇒ ``ClassificationResult(REJECTED, errors)`` with
    ``classification=None``. No resolver is consulted for a citation the
    class does not require, so UNKNOWN needs no resolvers.
    """
    errors: list[ClassificationError] = _validate_record(record)
    errors.extend(_validate_draft(record, draft))
    errors.extend(_validate_evidence(record, draft, evidence_resolver))
    errors.extend(_validate_contributing_factors(draft))
    errors.extend(_validate_class_citations(record, draft, {
        "constraint": constraint_resolver,
        "mechanism": mechanism_resolver,
        "regime": regime_resolver,
        "scope": scope_field_resolver,
    }))
    if errors:
        return ClassificationResult(
            ClassificationVerdict.REJECTED, tuple(errors))

    classification = _build_classification(record, draft)
    return ClassificationResult(
        ClassificationVerdict.ADMITTED, (), classification)


def _validate_record(record: FalsificationRecord) -> list[ClassificationError]:
    errors: list[ClassificationError] = []
    for field in ("project_id", "hypothesis_ref", "program_ref"):
        value = getattr(record, field)
        if not isinstance(value, str) or not value.strip():
            errors.append(_err(
                "MALFORMED_RECORD", field,
                "the falsification record fields must be non-empty strings",
                f"got {value!r}",
                "supply a schema-conforming falsification record"))
    evidence = record.falsifying_evidence_refs
    if not isinstance(evidence, tuple) or not evidence:
        errors.append(_err(
            "RECORD_NO_EVIDENCE", "falsifying_evidence_refs",
            "the falsification record must carry its falsifying evidence",
            "no falsifying evidence on the record",
            "bind the falsifying evidence artifacts to the record"))
    else:
        for i, ref in enumerate(evidence):
            if not isinstance(ref, str) or not ref.strip():
                errors.append(_err(
                    "MALFORMED_RECORD", f"falsifying_evidence_refs[{i}]",
                    "evidence refs must be non-empty strings",
                    f"got {ref!r}",
                    "supply the artifact refs in 'artifact_type:ref' form"))
    return errors


def _validate_draft(
    record: FalsificationRecord,
    draft: FailureClassificationDraft,
) -> list[ClassificationError]:
    errors: list[ClassificationError] = []
    if not isinstance(draft, FailureClassificationDraft):
        errors.append(_err(
            "MALFORMED_DRAFT", "draft",
            "classify_failure requires a FailureClassificationDraft",
            f"got {type(draft).__name__}",
            "construct a schema-conforming draft"))
        return errors

    try:
        failure_class = FailureClass(draft.failure_class)
    except ValueError:
        errors.append(_err(
            "UNKNOWN_FAILURE_CLASS", "failure_class",
            "failure_class must be one of the closed FailureClass vocabulary",
            f"got {draft.failure_class!r} — a forged class is rejected, "
            f"never coerced",
            "use a declared FailureClass value"))
        return errors  # further class checks are meaningless

    if not isinstance(draft.classifier_version, str) or not draft.classifier_version.strip():
        errors.append(_err(
            "MISSING_CLASSIFIER_VERSION", "classifier_version",
            "classifier_version is required (it is part of the identity)",
            "no classifier version on the draft",
            "supply the classifier/mapping policy version"))

    # Validate condition_type unconditionally — dataclasses do not enforce type
    # annotations at runtime, so a malformed value would otherwise sail through
    # and raise KeyError inside _ENVIRONMENT_MISMATCH_ACTIONS during
    # _build_classification, violating classify_failure's "(pure, never
    # raises)" contract.
    try:
        ConditionType(draft.condition_type)
    except (ValueError, TypeError):
        errors.append(_err(
            "UNKNOWN_CONDITION_TYPE", "condition_type",
            "condition_type must be one of the closed ConditionType vocabulary",
            f"got {draft.condition_type!r} — a forged condition is rejected, "
            f"never coerced",
            "use a declared ConditionType value"))

    if not isinstance(draft.explanation, str) or not draft.explanation.strip():
        errors.append(_err(
            "EMPTY_EXPLANATION", "explanation",
            "the explanation must be a non-empty string",
            "no rationale supplied",
            "state why the hypothesis failed"))
    elif len(draft.explanation) > MAX_EXPLANATION_LENGTH:
        errors.append(_err(
            "EXPLANATION_TOO_LONG", "explanation",
            f"explanation must be at most {MAX_EXPLANATION_LENGTH} characters",
            f"got {len(draft.explanation)}",
            "shorten the rationale"))

    if not isinstance(draft.proposed_by, str) or not draft.proposed_by:
        errors.append(_err(
            "MISSING_PROPOSED_BY", "proposed_by",
            "proposed_by is required advisory provenance",
            "no proposer recorded",
            "record the proposing agent profile"))

    # The draft never targets a hypothesis other than the record's — the
    # hypothesis comes from the record, never from the draft (no mismatch).
    if failure_class is FailureClass.UNKNOWN and (
        draft.constraint_ref is not None
        or draft.failed_mechanism_ref is not None
        or draft.regime_ref is not None
        or draft.resource_gap is not None
        or draft.scope_brief_ref is not None
        or draft.scope_brief_field is not None
    ):
            errors.append(_err(
                "CITATION_NOT_REQUIRED_FOR_CLASS", "failure_class",
                "UNKNOWN admits no class-specific citations",
                "a citation was supplied with an UNKNOWN classification",
                "drop the citation or classify the failure honestly"))
    return errors


def _validate_evidence(
    record: FalsificationRecord,
    draft: FailureClassificationDraft,
    evidence_resolver: EvidenceResolver | None,
) -> list[ClassificationError]:
    """Evidence discipline: required for every class except UNKNOWN; must be a
    subset of the record's OWN falsifying evidence; no duplicates; each ref
    must resolve project-scoped (fail-closed without the resolver)."""
    errors: list[ClassificationError] = []
    try:
        failure_class = FailureClass(draft.failure_class)
    except ValueError:
        return errors

    evidence = draft.evidence_refs
    if not isinstance(evidence, tuple):
        errors.append(_err(
            "MALFORMED_EVIDENCE", "evidence_refs",
            "evidence_refs must be a tuple of strings",
            f"got {type(evidence).__name__}",
            "supply the citation refs as a tuple"))
        return errors

    if failure_class in _EVIDENCE_REQUIRED_CLASSES and not evidence:
        errors.append(_err(
            "NO_SUPPORTING_EVIDENCE", "evidence_refs",
            f"{failure_class.value} requires at least one cited falsifying "
            "evidence artifact",
            "no evidence cited for the classification",
            "cite the falsifying evidence the classification rests on"))

    record_evidence = set(record.falsifying_evidence_refs)
    seen: set[str] = set()
    for i, ref in enumerate(evidence):
        if not isinstance(ref, str) or not ref.strip():
            errors.append(_err(
                "MALFORMED_EVIDENCE", f"evidence_refs[{i}]",
                "evidence refs must be non-empty strings",
                f"got {ref!r}",
                "supply the artifact refs in 'artifact_type:ref' form"))
            continue
        if ref in seen:
            errors.append(_err(
                "DUPLICATE_EVIDENCE_REF", f"evidence_refs[{i}]",
                "evidence refs must be unique",
                f"{ref!r} cited more than once",
                "drop the duplicate citation"))
            continue
        seen.add(ref)
        if ref not in record_evidence:
            errors.append(_err(
                "EVIDENCE_OUTSIDE_RECORD", f"evidence_refs[{i}]",
                "a classification may only cite the falsifying evidence of "
                "the record it classifies",
                f"{ref!r} is not among the record's falsifying evidence — "
                "forged/foreign evidence is rejected",
                "cite only the record's falsifying evidence"))
            continue
        if evidence_resolver is None:
            errors.append(_err(
                "EVIDENCE_UNDEREFERENCEABLE", f"evidence_refs[{i}]",
                "cited evidence must dereference (project-scoped) or the "
                "classification is REJECTED",
                "no evidence resolver supplied",
                "supply the write-path evidence resolver"))
        elif not evidence_resolver(record.project_id, ref):
            errors.append(_err(
                "EVIDENCE_DOES_NOT_RESOLVE", f"evidence_refs[{i}]",
                "cited evidence must resolve in the project",
                f"{ref!r} does not resolve for project "
                f"{record.project_id!r} — stale/foreign/cross-project "
                "evidence is rejected",
                "cite existing, project-scoped falsifying evidence"))
    return errors


def _validate_contributing_factors(
    draft: FailureClassificationDraft,
) -> list[ClassificationError]:
    errors: list[ClassificationError] = []
    try:
        primary = FailureClass(draft.failure_class)
    except ValueError:
        return errors
    factors = draft.contributing_factors
    if not isinstance(factors, tuple):
        errors.append(_err(
            "MALFORMED_FACTORS", "contributing_factors",
            "contributing_factors must be a tuple of FailureClass values",
            f"got {type(factors).__name__}",
            "supply the contributing classes as a tuple"))
        return errors
    if not factors:
        return errors
    seen: set[FailureClass] = set()
    for i, raw in enumerate(factors):
        if not isinstance(raw, str):
            errors.append(_err(
                "MALFORMED_FACTORS", f"contributing_factors[{i}]",
                "contributing factors must be FailureClass values",
                f"got {type(raw).__name__}",
                "supply declared FailureClass values"))
            continue
        try:
            factor = FailureClass(raw)
        except ValueError:
            errors.append(_err(
                "UNKNOWN_CONTRIBUTING_FACTOR", f"contributing_factors[{i}]",
                "contributing factors must be declared FailureClass values",
                f"got {raw!r}",
                "use a declared FailureClass value"))
            continue
        if factor is primary:
            errors.append(_err(
                "FACTOR_EQUALS_PRIMARY", f"contributing_factors[{i}]",
                "a contributing factor cannot equal the primary class",
                f"{factor.value} duplicates the primary classification",
                "drop the duplicate or change the primary"))
        elif factor in seen:
            errors.append(_err(
                "DUPLICATE_CONTRIBUTING_FACTOR", f"contributing_factors[{i}]",
                "contributing factors must be unique",
                f"{factor.value} listed more than once",
                "drop the duplicate factor"))
        seen.add(factor)
    return errors


def _validate_class_citations(
    record: FalsificationRecord,
    draft: FailureClassificationDraft,
    resolvers: Mapping[str, Callable[..., bool] | None],
) -> list[ClassificationError]:
    """Per-class required citations (present + resolving) and the anti-
    extraneous rule (a citation the class does not require is REJECTED —
    class-mismatch evidence cannot hide inside an unrelated class)."""
    errors: list[ClassificationError] = []
    try:
        failure_class = FailureClass(draft.failure_class)
    except ValueError:
        return errors

    # --- required citations per class ---
    if failure_class is FailureClass.DECLARED_CONSTRAINT_VIOLATION:
        _require_citation(errors, "constraint_ref", draft.constraint_ref,
                          "a declared constraint citation is mandatory",
                          "constraint_ref", resolvers["constraint"],
                          lambda r: r(record.project_id,
                                      record.program_ref,
                                      str(draft.constraint_ref)))
    elif failure_class is FailureClass.IMPLEMENTATION_FAILURE:
        if draft.failed_mechanism_ref is None:
            errors.append(_err(
                "NO_MECHANISM_REF", "failed_mechanism_ref",
                "IMPLEMENTATION_FAILURE must cite the failed mechanism "
                "(a prediction/observable of the program), never only the "
                "top-level claim",
                "no mechanism-level citation supplied",
                "cite the prediction/observable that failed"))
        elif draft.failed_mechanism_ref == record.hypothesis_ref:
            errors.append(_err(
                "MECHANISM_EQUALS_CLAIM", "failed_mechanism_ref",
                "the failed mechanism must be BELOW the claim (a "
                "prediction/observable); evidence contradicting only the "
                "top-level goal is not an implementation failure",
                f"{draft.failed_mechanism_ref!r} equals the hypothesis ref",
                "cite the mechanism-level component that failed"))
        else:
            _require_citation(errors, "failed_mechanism_ref",
                              draft.failed_mechanism_ref,
                              "the failed mechanism citation must resolve "
                              "to a prediction/observable of the program",
                              "failed_mechanism_ref", resolvers["mechanism"],
                              lambda r: r(record.project_id,
                                          record.program_ref,
                                          str(draft.failed_mechanism_ref)))
    elif failure_class is FailureClass.ENVIRONMENT_MISMATCH:
        _require_citation(errors, "regime_ref", draft.regime_ref,
                          "an explicit declared regime citation is mandatory "
                          "(ENVIRONMENT_MISMATCH is a regime claim)",
                          "regime_ref", resolvers["regime"],
                          lambda r: r(record.project_id,
                                      str(draft.regime_ref)))
    elif failure_class is FailureClass.RESOURCE_CONSTRAINT:
        gap = draft.resource_gap
        if gap is None:
            errors.append(_err(
                "NO_RESOURCE_GAP", "resource_gap",
                "RESOURCE_CONSTRAINT requires a MEASURED resource deficit "
                "(a bare claim of insufficient resources is rejected)",
                "no resource gap supplied",
                "quantify the deficit (resource_kind, observed, required)"))
        elif not isinstance(gap, ResourceGap):
            errors.append(_err(
                "MALFORMED_RESOURCE_GAP", "resource_gap",
                "resource_gap must be a ResourceGap",
                f"got {type(gap).__name__}",
                "supply a structured ResourceGap"))
        else:
            for field in ("resource_kind", "unit"):
                value = getattr(gap, field)
                if not isinstance(value, str) or not value.strip():
                    errors.append(_err(
                        "MALFORMED_RESOURCE_GAP", f"resource_gap.{field}",
                        "resource_gap fields must be non-empty strings",
                        f"got {value!r}",
                        "name the resource kind and its unit"))
            for field in ("observed", "required"):
                value = getattr(gap, field)
                if not isinstance(value, (int, float)) \
                        or isinstance(value, bool) or not math.isfinite(value):
                    errors.append(_err(
                        "MALFORMED_RESOURCE_GAP", f"resource_gap.{field}",
                        "resource_gap quantities must be finite numbers",
                        f"got {value!r}",
                        "supply a measurable quantity"))
            if not errors and gap.observed >= gap.required:
                errors.append(_err(
                    "RESOURCE_GAP_NOT_A_DEFICIT", "resource_gap",
                    "a resource constraint requires observed < required",
                    f"observed {gap.observed} >= required "
                    f"{gap.required} — no deficit demonstrated",
                    "correct the measurement or choose another class"))
    elif failure_class is FailureClass.FRAMING_ERROR:
        if draft.scope_brief_ref is None:
            errors.append(_err(
                "NO_SCOPE_REF", "scope_brief_ref",
                "FRAMING_ERROR must cite the originating ScopeBrief",
                "no scope brief reference supplied",
                "cite the frozen brief whose framing is in question"))
        elif draft.scope_brief_field is None:
            errors.append(_err(
                "NO_SCOPE_FIELD", "scope_brief_field",
                "FRAMING_ERROR must cite the SPECIFIC ScopeBrief field "
                "whose framing is wrong",
                "no scope field supplied",
                "name the specific field of the frozen brief"))
        else:
            _require_citation(errors, "scope_brief_ref", draft.scope_brief_ref,
                              "the scope brief reference must resolve and the "
                              "cited field must exist in the frozen brief",
                              "scope_brief_ref", resolvers["scope"],
                              lambda r: r(record.project_id,
                                          str(draft.scope_brief_ref),
                                          str(draft.scope_brief_field)))
    elif failure_class is FailureClass.MECHANISM_DECAYED:
        # Handled like IMPLEMENTATION_FAILURE: the failed_mechanism_ref is
        # mandatory, must differ from the hypothesis_ref (it must be a
        # mechanism-level component, not the top-level claim), and must
        # resolve via the mechanism resolver. The semantic difference is
        # that MECHANISM_DECAYED marks a mechanism that was previously NOT
        # falsified in this regime but is now falsified by a LATER
        # FalsificationRecord in the SAME regime (temporal decay).
        if draft.failed_mechanism_ref is None:
            errors.append(_err(
                "NO_MECHANISM_REF", "failed_mechanism_ref",
                "MECHANISM_DECAYED must cite the mechanism that decayed "
                "(a prediction/observable of the program), never only the "
                "top-level claim",
                "no mechanism-level citation supplied",
                "cite the prediction/observable that decayed in this regime"))
        elif draft.failed_mechanism_ref == record.hypothesis_ref:
            errors.append(_err(
                "MECHANISM_EQUALS_CLAIM", "failed_mechanism_ref",
                "the failed mechanism must be BELOW the claim (a "
                "prediction/observable); a top-level-only contradiction is "
                "not a mechanism decay",
                f"{draft.failed_mechanism_ref!r} equals the hypothesis ref",
                "cite the mechanism-level component that decayed"))
        else:
            _require_citation(errors, "failed_mechanism_ref",
                              draft.failed_mechanism_ref,
                              "the failed mechanism citation must resolve "
                              "to a prediction/observable of the program",
                              "failed_mechanism_ref", resolvers["mechanism"],
                              lambda r: r(record.project_id,
                                          record.program_ref,
                                          str(draft.failed_mechanism_ref)))

    # --- anti-extraneous: a citation the class does not require is rejected ---
    required = _class_required_citations(failure_class)
    for field_name, value in (
        ("constraint_ref", draft.constraint_ref),
        ("failed_mechanism_ref", draft.failed_mechanism_ref),
        ("regime_ref", draft.regime_ref),
        ("resource_gap", draft.resource_gap),
        ("scope_brief_ref", draft.scope_brief_ref),
        ("scope_brief_field", draft.scope_brief_field),
    ):
        if value is not None and field_name not in required:
            errors.append(_err(
                "CITATION_NOT_REQUIRED_FOR_CLASS", field_name,
                f"{failure_class.value} does not require {field_name} — a "
                "class-mismatched citation is rejected, never silently "
                "dropped",
                f"{field_name} set on a {failure_class.value} draft",
                "drop the citation or choose the class that requires it"))
    return errors


def _class_required_citations(failure_class: FailureClass) -> frozenset[str]:
    return {
        FailureClass.DECLARED_CONSTRAINT_VIOLATION: frozenset({"constraint_ref"}),
        FailureClass.IMPLEMENTATION_FAILURE: frozenset({"failed_mechanism_ref"}),
        FailureClass.ENVIRONMENT_MISMATCH: frozenset({"regime_ref"}),
        FailureClass.RESOURCE_CONSTRAINT: frozenset({"resource_gap"}),
        FailureClass.FRAMING_ERROR: frozenset({"scope_brief_ref", "scope_brief_field"}),
        FailureClass.MECHANISM_DECAYED: frozenset({"failed_mechanism_ref"}),
        FailureClass.UNKNOWN: frozenset(),
    }[failure_class]


def _require_citation(
    errors: list[ClassificationError],
    field_path: str,
    value: str | None,
    requirement: str,
    label: str,
    resolver: Callable[..., bool] | None,
    resolved: Callable[[Callable[..., bool]], bool],
) -> None:
    """Fail-closed citation rule: present → resolve (resolver required)."""
    if value is None:
        errors.append(_err(
            "MISSING_CITATION", field_path, requirement,
            f"no {label} supplied", f"supply the {label}"))
        return
    if resolver is None:
        errors.append(_err(
            "CITATION_UNDEREFERENCEABLE", field_path,
            "citations must dereference (project-scoped) or the "
            "classification is REJECTED",
            f"no {label} resolver supplied",
            "supply the write-path resolver"))
    elif not resolved(resolver):
        errors.append(_err(
            "CITATION_DOES_NOT_RESOLVE", field_path,
            "citations must resolve to the referenced artifact",
            f"{value!r} does not resolve (wrong object / foreign project / "
            "superseded)",
            "cite an existing, project-scoped artifact"))


# ── identity + construction (never authored by the caller) ──

def _build_classification(
    record: FalsificationRecord,
    draft: FailureClassificationDraft,
) -> FailureClassification:
    failure_class = FailureClass(draft.failure_class)
    condition_type = ConditionType(draft.condition_type)
    contributors = tuple(
        FailureClass(f) for f in draft.contributing_factors
    )
    content = {
        "schema_version": FAILURE_CLASS_SCHEMA_VERSION,
        "classifier_version": draft.classifier_version,
        "project_id": record.project_id,
        "hypothesis_ref": record.hypothesis_ref,
        "program_ref": record.program_ref,
        "failure_class": failure_class.value,
        "contributing_factors": sorted(f.value for f in contributors),
        "evidence_refs": sorted(draft.evidence_refs),
        "constraint_ref": draft.constraint_ref,
        "failed_mechanism_ref": draft.failed_mechanism_ref,
        "regime_ref": draft.regime_ref,
        "resource_gap": (
            {"resource_kind": draft.resource_gap.resource_kind,
             "observed": draft.resource_gap.observed,
             "required": draft.resource_gap.required,
             "unit": draft.resource_gap.unit}
            if draft.resource_gap is not None else None),
        "scope_brief_ref": draft.scope_brief_ref,
        "scope_brief_field": draft.scope_brief_field,
        "explanation": draft.explanation,
        "proposed_by": draft.proposed_by,
        "condition_type": condition_type.value,
    }
    content_hash = sha256_hex(canonical_json(content))
    return FailureClassification(
        classification_id="fc_" + content_hash[:24],
        schema_version=FAILURE_CLASS_SCHEMA_VERSION,
        classifier_version=draft.classifier_version,
        project_id=record.project_id,
        hypothesis_ref=record.hypothesis_ref,
        program_ref=record.program_ref,
        failure_class=failure_class,
        contributing_factors=tuple(
            sorted(contributors, key=lambda c: c.value)),
        evidence_refs=tuple(sorted(draft.evidence_refs)),
        constraint_ref=draft.constraint_ref,
        failed_mechanism_ref=draft.failed_mechanism_ref,
        regime_ref=draft.regime_ref,
        resource_gap=draft.resource_gap,
        scope_brief_ref=draft.scope_brief_ref,
        scope_brief_field=draft.scope_brief_field,
        explanation=draft.explanation,
        proposed_by=draft.proposed_by,
        condition_type=condition_type,
        permitted_actions=tuple(sorted(
            _action_map_for(failure_class, condition_type),
            key=lambda a: a.value)),
        requires_human_confirmation=requires_human_confirmation_for(
            failure_class, contributors),
        content_hash=content_hash,
    )


# ── public helpers ──

def permitted_actions_for(
    failure_class: FailureClass,
    condition_type: ConditionType = ConditionType.UNDETERMINED,
) -> frozenset[PermittedAction]:
    """The deterministic permitted-action set for a class (never executed).

    ``ConditionType`` is meaningful only for ``ENVIRONMENT_MISMATCH``; for
    every other class it is ignored."""
    return _action_map_for(failure_class, condition_type)


def parse_contributing_factors(raw: Any) -> tuple[FailureClass, ...]:
    """Parse stored contributing-factor strings into ratified FailureClass
    values — malformed or non-ratified entries are skipped, never a crash
    (fail-closed to the ratified set; a garbage contributor can never
    toggle the human gate)."""
    if not isinstance(raw, (list, tuple)):
        return ()
    out: list[FailureClass] = []
    for v in raw:
        try:
            out.append(FailureClass(v))
        except (ValueError, TypeError):
            continue
    return tuple(out)


def requires_human_confirmation_for(
    failure_class: FailureClass,
    contributing_factors: tuple[FailureClass, ...] = (),
) -> bool:
    """The deterministic human-confirmation flag — derived, never a stored
    fact: True iff the class is FRAMING_ERROR (the one class whose fix
    routes to scope authority) OR any CONTRIBUTING FACTOR is FRAMING_ERROR
    (red-team §2 remediation: a FRAMING_ERROR contribution on a
    non-authority primary class must not bypass the gate — the safeguard
    fires on the framing assertion itself). The classification record's
    stored ``requires_human_confirmation`` field is derived from THIS (the
    digest re-verifies stored vs derived, F2)."""
    return (failure_class is FailureClass.FRAMING_ERROR
            or FailureClass.FRAMING_ERROR in contributing_factors)


# The ACTION-shaped confirmation gate (IDR-041 decision, ratified): the
# proposal lifecycle gates on the ACTION, not only the class — the
# authority-shaped actions (branch rejection; the two S16 scope routes;
# mechanism substitution, which substitutes a ratified program's mechanism
# and feeds the PROPOSE_RESEARCH_PROGRAM admission as ratified rationale)
# require human confirmation regardless of class, so their approvals become
# REACHABLE through the gate. REVIEW_DOWNSTREAM_IMPACT (a review
# obligation), PARK_FOR_RESOURCE_REVIEW, and ESCALATE_TO_DIRECTOR stay
# EFFECTIVE — advisory or proposal-shaped, no gate.
AUTHORITY_SHAPED_ACTIONS: frozenset[PermittedAction] = frozenset({
    PermittedAction.REJECT_BRANCH,
    PermittedAction.ROUTE_TO_SCOPE_REVIEW,
    PermittedAction.PROPOSE_SCOPE_NARROWING,
    PermittedAction.PROPOSE_MECHANISM_SUBSTITUTION,
})


def requires_human_confirmation_for_action(action: PermittedAction) -> bool:
    """The deterministic human-confirmation flag for an ACTION — True iff
    the action is authority-shaped (REJECT_BRANCH / ROUTE_TO_SCOPE_REVIEW /
    PROPOSE_SCOPE_NARROWING)."""
    return action in AUTHORITY_SHAPED_ACTIONS


def proposal_requires_human_confirmation(
    failure_class: FailureClass, action: PermittedAction,
    contributing_factors: tuple[FailureClass, ...] = (),
) -> bool:
    """The proposal gate: a classification-action proposal needs human
    confirmation iff its CLASS requires it (FRAMING_ERROR) OR any
    CONTRIBUTING FACTOR requires it (red-team §2 — a FRAMING_ERROR
    contribution on a non-authority primary class is still gated) OR its
    ACTION is authority-shaped. All branches are derived, never stored —
    the admission, the replay, and the decision validator recompute this
    (F2)."""
    return (requires_human_confirmation_for(
                failure_class, contributing_factors)
            or requires_human_confirmation_for_action(action))


def certifies_decisive_falsification(
    failure_class: FailureClass, hypothesis_ref: str,
    constraint_ref: str | None,
) -> bool:
    """The ratified falsification predicate for the bare-classification
    REFUTED driver (IDR-041 AC-2 deferred branch, ratified): a digest-valid
    Q-05 classification alone certifies a DECISIVE falsification iff its
    class is DECLARED_CONSTRAINT_VIOLATION (the one falsification-shaped
    class — its action map is REJECT_BRANCH) AND the cited constraint is
    the hypothesis's OWN declared falsification condition
    (``hypothesis:<H>:falsification_condition``). A methodology-constraint
    violation is a process failure, never a falsification; every other
    class (mechanism failure, environment mismatch, resource deficit,
    framing, unknown) is explicitly NOT decisive — derived from the
    ratified taxonomy, never a stored flag (F2)."""
    return (failure_class is FailureClass.DECLARED_CONSTRAINT_VIOLATION
            and constraint_ref == (
                f"hypothesis:{hypothesis_ref}:falsification_condition"))


def summarize_classification(
    classification: FailureClassification,
) -> str:
    """Deterministic human-readable summary (no new UI)."""
    factors = ", ".join(c.value for c in classification.contributing_factors)
    return (
        f"FailureClassification {classification.classification_id}\n"
        f"  versions: schema={classification.schema_version} "
        f"classifier={classification.classifier_version}\n"
        f"  record: project={classification.project_id} "
        f"hypothesis={classification.hypothesis_ref} "
        f"program={classification.program_ref}\n"
        f"  class: {classification.failure_class.value}"
        + (f" (+ {factors})" if factors else "")
        + "\n"
        "  permitted actions: "
        + ", ".join(a.value for a in classification.permitted_actions)
        + ("\n  REQUIRES HUMAN CONFIRMATION (implicates ScopeBrief)"
           if classification.requires_human_confirmation else "")
    )


def classification_command_hash(command: Mapping[str, Any]) -> str:
    """Deterministic identity for an operator-asserted classification
    command (P6 — the HumanDecision binding, mirroring the
    curation_command_hash precedent).

    Covers every command field EXCEPT ``human_decision_ref`` and
    ``operator_id`` (the approver's identity, not the approved
    command): program/hypothesis refs, failure class, evidence sets
    (sorted), explanation, classifier version, class citations,
    contributing factors (sorted), proposer, and producing task.
    Returns ``"classify_" + sha256(canonical)[:24]``. Raises
    ``TypeError``/``ValueError`` on misshapen fields (fail-closed —
    callers surface refusal-as-data, never a hash of garbage).
    """
    def _str_list(key: str) -> list:
        value = command.get(key)
        if value is None:
            return []
        if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value):
            raise TypeError(
                f"classification command field {key!r} must be a list "
                f"of strings")
        return sorted(value)

    gap = command.get("resource_gap")
    canonical_gap = None
    if isinstance(gap, dict):
        canonical_gap = {
            "resource_kind": gap.get("resource_kind"),
            "observed": gap.get("observed"),
            "required": gap.get("required"),
            "unit": gap.get("unit"),
        }
    raw = canonical_json({
        "program_ref": command.get("program_ref"),
        "hypothesis_ref": command.get("hypothesis_ref"),
        "failure_class": command.get("failure_class"),
        "evidence_refs": _str_list("evidence_refs"),
        "falsifying_evidence_refs": _str_list("falsifying_evidence_refs"),
        "explanation": command.get("explanation"),
        "classifier_version": command.get("classifier_version"),
        "constraint_ref": command.get("constraint_ref"),
        "failed_mechanism_ref": command.get("failed_mechanism_ref"),
        "regime_ref": command.get("regime_ref"),
        "resource_gap": canonical_gap,
        "scope_brief_ref": command.get("scope_brief_ref"),
        "scope_brief_field": command.get("scope_brief_field"),
        "contributing_factors": _str_list("contributing_factors"),
        "proposed_by": command.get("proposed_by"),
        "producing_task_id": command.get("producing_task_id"),
    })
    return "classify_" + sha256_hex(raw)[:24]
