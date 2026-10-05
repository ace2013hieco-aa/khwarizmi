"""ResearchClaim / ResearchAssumption — P7 CONTRA substrate (v6 §29, DESIGNED → IMPLEMENTED + TESTED).

The deterministic core of the CONTRA / internal-adversarial-memory amendment
(Part 1 protest ``hermes_contra_adversarial_review.md``; Part 2 reconciliation
``docs/idr/IDR-024.md``; normative text v6 §29):

- ``ResearchClaim`` — an atomic assertion extracted from a research artifact
  (statement + source/span refs + structured context tags + linked
  assumptions). Content-addressed identity ``cl_<hash>``.
- ``ResearchAssumption`` — a declared premise with ``dependent_claim_ids``
  maintained deterministically by the validator. Content-addressed identity
  ``as_<hash>``.
- ``validate_extraction`` — the **ClaimAssumptionValidator** entry point
  (mirrors ``compile_from_payload`` as the ResearchProgramValidator entry
  point): closed-schema validation (unknown keys rejected, strict typing),
  content-derived identity, batch-internal assumption↔claim linkage, context
  dimension checks, and optional authoritative-ref dereference via an injected
  resolver. Pure: no DB, no clock, no writes.

Advisory substrate only (v6 §29.2 rules 1–2, CT-R2/CT-R3): neither artifact is
ever a ``Validation``, ladder-citable, or a gate input; a governed claim may
cite corpus claims; assumptions never bear obligations. This module has no
persistence and no event surface — the extraction-task pipeline, persistence,
and the write-path dereference are the P7 runtime integration, explicitly
deferred per the manual-proof-first rule (v6 §29.2 rule 7).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping

from hermes.research.programs import canonical_json, sha256_hex

__all__ = [
    "CAUSAL_CLAIM_TYPES",
    "CLAIM_SCHEMA_VERSION",
    "CONTEXT_DIMENSIONS",
    "DEREFERENCE_DIMENSIONS",
    "EXPERIMENT_ARTIFACT_TYPE",
    "REF_SEP",
    "SUPPORT_STATES",
    "ClaimValidationError",
    "ExtractionDraft",
    "ExtractionResult",
    "ExtractionVerdict",
    "ResearchAssumption",
    "ResearchAssumptionDraft",
    "ResearchClaim",
    "ResearchClaimDraft",
    "SupportState",
    "assumption_id_of",
    "claim_id_of",
    "validate_extraction",
]

CLAIM_SCHEMA_VERSION = "2"


class SupportState(str, Enum):
    """The closed claim support-state vocabulary (HR-05/M4).

    Claim admission was structural-only (audit HR-05, PROBE P4): a
    fabricated causal overclaim citing a nonexistent span was ADMITTED
    with zero errors, because the substrate could not mechanically
    distinguish directly-supported / partially-supported / inferred /
    speculative / contradicted claims. M4 closes that: every claim
    declares its support state at extraction, admission is deterministic
    (closed vocabulary + source-shape rules), and no LLM judge is ever
    consulted (audit §Over-Engineering rule 1).
    """

    DIRECT = "DIRECT"              # the cited source states this directly
    PARTIAL = "PARTIAL"            # the source supports part of the claim
    INFERRED = "INFERRED"          # derived from the source by inference
    SPECULATIVE = "SPECULATIVE"    # not supported by the source; declared
    CONTRADICTED = "CONTRADICTED"  # the cited source opposes the claim
    UNSUPPORTED = "UNSUPPORTED"    # no support established (fail-closed
                                   #   reading of pre-vocabulary rows)


# The closed membership set (admission checks never parse the enum lazily).
SUPPORT_STATES = frozenset(s.value for s in SupportState)

# Claim types that assert a causal/experimental relation (compared
# casefolded — claim_type is advisory free text, so the rule normalizes).
CAUSAL_CLAIM_TYPES = frozenset({"causal", "experimental"})

# The artifact type of a declared (pre-registered) experiment — the only
# source shape that can DIRECTLY/PARTIALLY support a causal claim (M4
# invariant: causal/experimental claims require an experiment ref).
EXPERIMENT_ARTIFACT_TYPE = "pre_registered_experiment"

# Closed context-tag vocabulary (v6 §29.3): tags dereference existing
# authoritative carriers where they exist (dataset_ref → DatasetManifest;
# regime → the versioned ICSS-v1 axis); the rest are structured free strings.
CONTEXT_DIMENSIONS = frozenset({
    "regime", "timeframe", "population", "methodology",
    "dataset_ref", "theoretical_framework",
})

# Dimensions whose values must dereference to an authoritative carrier when a
# resolver is supplied (the write path supplies the resolver at P7).
DEREFERENCE_DIMENSIONS = frozenset({"dataset_ref", "regime"})

# Ref form for source_ref / supporting artifact refs: "artifact_type:ref".
REF_SEP = ":"
_REF_SEP = REF_SEP  # private alias (kept for backward compatibility)


class ExtractionVerdict(str, Enum):
    """Deterministic verdict of a claim/assumption extraction batch."""

    ADMITTED = "ADMITTED"     # schema + identity + links valid; dereference ok
    INVALID = "INVALID"       # any structured error (fail-closed)


@dataclass(frozen=True, slots=True)
class ClaimValidationError:
    """A single structured reason for a non-ADMITTED verdict."""

    code: str
    field_path: str
    requirement: str
    explanation: str
    suggested_next_action: str


@dataclass(frozen=True, slots=True)
class ResearchClaimDraft:
    """An LLM-proposed atomic assertion (C-tier proposal; the validator decides).

    ``ref`` is a batch-local id used for error paths and assumption links; it
    never enters the content identity (identical assertions from different
    batches collide on purpose — PA4 dedup).

    ``support_state`` (HR-05/M4) is REQUIRED and must be a member of the
    closed ``SUPPORT_STATES`` vocabulary — the extractor's declared answer
    to "how does the cited source support this assertion". Omission or an
    unknown state is a validation error (fail-closed); no LLM judge is
    ever consulted.
    """

    ref: str
    statement: str
    source_ref: str                       # "artifact_type:ref" — dereferenced at the write path (V6-P7-F02)
    support_state: str | None = None      # required at admission — closed SUPPORT_STATES vocabulary (HR-05/M4)
    span_ref: str | None = None           # optional span within the source artifact — dereferenced at the write path (HR-05)
    claim_type: str = ""                  # advisory classification, capped length
    context_tags: Mapping[str, str] = field(default_factory=dict)
    assumption_refs: tuple[str, ...] = ()  # batch-local refs of ResearchAssumptionDraft
    related_claims: tuple[str, ...] = ()   # content-addressed cl_ IDs of other claims
    supersedes_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ResearchAssumptionDraft:
    """An LLM-proposed declared premise (C-tier proposal)."""

    ref: str
    statement: str
    context_tags: Mapping[str, str] = field(default_factory=dict)
    supporting_artifact_refs: tuple[str, ...] = ()
    supersedes_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractionDraft:
    """The validated batch: claims + assumptions extracted from one source."""

    source_ref: str                       # the extraction's own source (task output context)
    claims: tuple[ResearchClaimDraft, ...] = ()
    assumptions: tuple[ResearchAssumptionDraft, ...] = ()
    extracted_by: str = ""                # advisory provenance: model_ref / task id
    schema_version: str = CLAIM_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class ResearchClaim:
    """The admitted atomic assertion — immutable, content-addressed, advisory.

    ``claim_id`` derives from the assertion content (statement + source/span
    refs + claim_type + support_state + context tags), never from batch refs,
    provenance, or creation data (AC-01 discipline: identical inputs ⇒
    identical identity).

    ``support_state`` (HR-05/M4) is the admitted member of the closed
    ``SUPPORT_STATES`` vocabulary — how the cited source supports this
    assertion. It is part of the content identity: the same statement with
    a different support state is a different claim.
    """

    claim_id: str
    statement: str
    source_ref: str
    support_state: str
    span_ref: str | None
    claim_type: str
    context_tags: tuple[tuple[str, str], ...]
    assumption_ids: tuple[str, ...]       # resolved, sorted — links maintained by the validator
    related_claim_ids: tuple[str, ...]    # sorted — content-addressed cross-ref (advisory)
    content_hash: str
    schema_version: str
    supersedes_ref: str | None


@dataclass(frozen=True, slots=True)
class ResearchAssumption:
    """The admitted declared premise — immutable, content-addressed, advisory.

    ``dependent_claim_ids`` is maintained deterministically by the validator:
    every claim whose batch links reference this assumption. Status is the
    advisory lifecycle (ACTIVE → SUSPENDED/SUPERSEDED by human/Director
    decision or deterministic supersession), never evidence.
    """

    assumption_id: str
    statement: str
    context_tags: tuple[tuple[str, str], ...]
    supporting_artifact_refs: tuple[str, ...]
    dependent_claim_ids: tuple[str, ...]  # deterministic back-references
    status: str                           # ACTIVE | SUSPENDED | SUPERSEDED (advisory)
    content_hash: str
    schema_version: str
    supersedes_ref: str | None


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """The deterministic outcome of validating an extraction batch.

    ``source_ref`` is the extraction's own source (the artifact the batch was
    extracted from, i.e. the draft's ``source_ref``). It is threaded through
    so the write path can bind the batch to its producing task's
    ``spec.source_ref`` (V6-P7-A2-01) without re-reading the draft.
    """

    verdict: ExtractionVerdict
    errors: tuple[ClaimValidationError, ...] = ()
    claims: tuple[ResearchClaim, ...] = ()
    assumptions: tuple[ResearchAssumption, ...] = ()
    source_ref: str = ""

    @property
    def admitted(self) -> bool:
        return self.verdict is ExtractionVerdict.ADMITTED


# ── content-derived identity (one canonical derivation, never two) ──

def claim_id_of(
    statement: str,
    source_ref: str,
    span_ref: str | None,
    claim_type: str,
    context_tags: Mapping[str, str],
    support_state: str = "",
    related_claims: tuple[str, ...] = (),
) -> str:
    """Content-derived identity: ``cl_<sha256(canonical assertion)>[:24]``.

    ``support_state`` (HR-05/M4) is part of the assertion content: the same
    statement with a different support state is a different claim. The
    default ``""`` keeps the derivation total for pre-vocabulary callers;
    every admitted v2 claim carries its closed-vocabulary state.

    ``related_claims`` are content-addressed cl_ IDs of other claims; when
    present they are part of the assertion content (same statement + different
    related claims ⇒ different claim). They enter the preimage ONLY when
    non-empty — the empty case must still reproduce the pre-vocabulary hash
    byte-for-byte, mirroring ``programs.py``'s ``parent_program_id`` rule. A
    key emitted unconditionally (even as ``[]``) would silently re-identify
    every claim persisted before the field existed: AC-1 Delta=0.
    """
    d: dict[str, Any] = {
        "statement": statement,
        "source_ref": source_ref,
        "span_ref": span_ref,
        "claim_type": claim_type,
        "support_state": support_state,
        "context_tags": dict(context_tags),
    }
    # related_claims: emitted ONLY when non-empty. An unconditional key (even
    # an empty one) would change the id of every claim persisted before the
    # field existed — the same identity break programs.py guards against for
    # parent_program_id (AC-1 Delta=0).
    if related_claims:
        d["related_claims"] = sorted(related_claims)
    return "cl_" + sha256_hex(canonical_json(d))[:24]


def assumption_id_of(
    statement: str,
    context_tags: Mapping[str, str],
    supporting_artifact_refs: tuple[str, ...],
) -> str:
    """Content-derived identity: ``as_<sha256(canonical premise)>[:24]``."""
    return "as_" + sha256_hex(canonical_json({
        "statement": statement,
        "context_tags": dict(context_tags),
        "supporting_artifact_refs": sorted(supporting_artifact_refs),
    }))[:24]


# ── the validator ──

# Resolver protocol: (dimension, value) → authoritative record exists.
# The P7 write path supplies a resolver over DatasetManifest / regime axis.
ContextResolver = Callable[[str, str], bool]

# Span-dereference protocol (HR-05): (source_ref, span_ref) → the span
# actually exists within the cited source. The P7 write path supplies a
# resolver that reads the stored source content; a fabricated span_ref
# pointing at a nonexistent section is then rejected deterministically
# (audit PROBE P4 / T-CAUSAL-OVERCLAIM). None = no dereference available
# (substrate-level fixtures), in which case span_ref is form-checked only.
SpanResolver = Callable[[str, str], bool]


def _err(code: str, path: str, requirement: str, explanation: str,
         next_action: str) -> ClaimValidationError:
    return ClaimValidationError(
        code, path, requirement, explanation, next_action)


def _validate_context_tags(
    tags: Mapping[str, str], path: str, errors: list[ClaimValidationError],
    resolver: ContextResolver | None,
) -> list[tuple[str, str]]:
    """Closed-dimension + typed-value + (optionally) dereference checks."""
    if not isinstance(tags, Mapping):
        errors.append(_err(
            "invalid_context_tags", path,
            "context_tags must be a mapping of string → string",
            f"got {type(tags).__name__}",
            "supply a mapping keyed by CONTEXT_DIMENSIONS"))
        return []
    validated: list[tuple[str, str]] = []
    for key, value in tags.items():
        if key not in CONTEXT_DIMENSIONS:
            errors.append(_err(
                "unknown_context_dimension", f"{path}.context_tags[{key!r}]",
                "context tags must use the closed CONTEXT_DIMENSIONS set",
                f"{key!r} is not a known dimension "
                f"({sorted(CONTEXT_DIMENSIONS)})",
                "use a known dimension or drop the tag"))
            continue
        if not isinstance(value, str) or not value:
            errors.append(_err(
                "invalid_context_value", f"{path}.context_tags[{key!r}]",
                "context tag values must be non-empty strings",
                f"got {type(value).__name__}: {value!r}",
                "supply a non-empty string value"))
            continue
        if (key in DEREFERENCE_DIMENSIONS and resolver is not None
                and not resolver(key, value)):
                errors.append(_err(
                    "dangling_context_ref", f"{path}.context_tags[{key!r}]",
                    "authoritative context refs must dereference "
                    "(v6 §29.3; CT-R1/IDR-022 discipline)",
                    f"{key}:{value!r} does not dereference to an "
                    f"authoritative carrier",
                    "reference an existing DatasetManifest / regime axis "
                    "record"))
        validated.append((key, value))
    return sorted(validated)


def validate_extraction(
    draft: ExtractionDraft,
    *,
    context_resolver: ContextResolver | None = None,
    span_resolver: SpanResolver | None = None,
) -> ExtractionResult:
    """The ClaimAssumptionValidator entry point (deterministic, pure).

    Checks, in order (fail-closed on the first structural class, collecting
    all errors in the class): batch non-emptiness → per-claim schema (statement,
    source/span refs, claim_type, support_state, context tags, dereference) →
    per-assumption schema → batch-local ref uniqueness → assumption_ref
    resolution → self-supersession → content-derived identity →
    dependent-claim maintenance. Returns ``ExtractionResult`` — never raises.

    ``context_resolver`` is optional at the substrate level (fixtures prove
    the dereference rule with a stub); the P7 write path supplies the real
    resolver over DatasetManifest / the regime axis.

    ``span_resolver`` (HR-05) is optional at the substrate level; the P7
    write path supplies a resolver that dereferences ``span_ref`` against
    the cited source's stored content, so a fabricated span pointing at a
    nonexistent section is rejected deterministically. When None, span_ref
    is form-checked only (non-empty string or None).
    """
    if not isinstance(draft, ExtractionDraft):
        raise TypeError(
            f"validate_extraction requires an ExtractionDraft, "
            f"got {type(draft).__name__}")

    errors: list[ClaimValidationError] = []

    # 1. Batch non-emptiness
    if not draft.claims and not draft.assumptions:
        errors.append(_err(
            "empty_extraction", "draft",
            "an extraction must contain at least one claim or assumption",
            "batch has neither claims nor assumptions",
            "supply at least one claim or assumption"))

    # 2. Batch-local ref uniqueness (claims ∪ assumptions)
    seen: dict[str, str] = {}
    for c in draft.claims:
        if c.ref in seen:
            errors.append(_err(
                "duplicate_ref", f"claims[ref={c.ref!r}]",
                "batch-local refs must be unique within the batch",
                f"ref {c.ref!r} already used by {seen[c.ref]}",
                "use a distinct batch-local ref"))
        seen[c.ref] = "claim"
    for a in draft.assumptions:
        if a.ref in seen:
            errors.append(_err(
                "duplicate_ref", f"assumptions[ref={a.ref!r}]",
                "batch-local refs must be unique within the batch",
                f"ref {a.ref!r} already used by {seen[a.ref]}",
                "use a distinct batch-local ref"))
        seen[a.ref] = "assumption"

    # 3. Per-claim schema
    for i, c in enumerate(draft.claims):
        path = f"claims[{i}]"
        if not isinstance(c.statement, str) or not c.statement.strip():
            errors.append(_err(
                "empty_statement", f"{path}.statement",
                "a claim statement must be a non-empty string",
                f"got {c.statement!r}",
                "supply the assertion text"))
        if not isinstance(c.source_ref, str) or _REF_SEP not in c.source_ref:
            errors.append(_err(
                "invalid_source_ref", f"{path}.source_ref",
                "source_ref must be an 'artifact_type:ref' reference",
                f"got {c.source_ref!r}",
                "supply a dereferenceable artifact reference "
                "(e.g. 'dataset_manifest:dm-1')"))
        if c.span_ref is not None and (
                not isinstance(c.span_ref, str) or not c.span_ref.strip()):
            errors.append(_err(
                "invalid_span_ref", f"{path}.span_ref",
                "span_ref must be a non-empty string or None",
                f"got {c.span_ref!r}",
                "supply a span reference or omit it"))
        elif (c.span_ref is not None and span_resolver is not None
                and isinstance(c.source_ref, str)
                and not span_resolver(c.source_ref, c.span_ref)):
            # HR-05 — span dereference: the cited span must actually exist
            # within the cited source. A fabricated span_ref pointing at a
            # nonexistent section is rejected deterministically (audit
            # PROBE P4 admitted exactly this; the write path supplies the
            # resolver that reads the stored source content).
            errors.append(_err(
                "dangling_span_ref", f"{path}.span_ref",
                "span_ref must dereference into the cited source "
                "(HR-05 span dereference)",
                f"span_ref {c.span_ref!r} does not resolve within "
                f"source {c.source_ref!r}",
                "cite a span that exists in the source, or drop the "
                "span_ref"))
        if not isinstance(c.claim_type, str) or len(c.claim_type) > 64:
            errors.append(_err(
                "invalid_claim_type", f"{path}.claim_type",
                "claim_type must be a string of at most 64 characters",
                f"got {c.claim_type!r}",
                "shorten or drop the advisory claim type"))
        # HR-05/M4 — the closed support-state vocabulary. Every claim must
        # declare how the cited source supports it; omission or an unknown
        # state is a validation error (fail-closed, no LLM judge).
        if c.support_state is None:
            errors.append(_err(
                "missing_support_state", f"{path}.support_state",
                "support_state is required — one of the closed "
                "SUPPORT_STATES vocabulary (HR-05/M4)",
                "support_state was omitted",
                f"declare one of {sorted(SUPPORT_STATES)}"))
        elif (not isinstance(c.support_state, str)
                or c.support_state not in SUPPORT_STATES):
            errors.append(_err(
                "invalid_support_state", f"{path}.support_state",
                "support_state must be a member of the closed "
                "SUPPORT_STATES vocabulary (HR-05/M4)",
                f"got {c.support_state!r}",
                f"use one of {sorted(SUPPORT_STATES)}"))
        else:
            # M4 invariant — a causal/experimental claim asserting REAL
            # source support (DIRECT/PARTIAL) must cite a declared
            # experiment. An observational source cannot directly support a
            # causal claim; the overclaim is rejected deterministically
            # (audit T-CAUSAL-OVERCLAIM). SPECULATIVE/INFERRED/CONTRADICTED/
            # UNSUPPORTED causal claims do not assert direct source support,
            # so they are exempt (the vocabulary stays usable, not rigid).
            if (c.claim_type.strip().casefold() in CAUSAL_CLAIM_TYPES
                    and c.support_state in (
                        SupportState.DIRECT.value,
                        SupportState.PARTIAL.value)
                    and isinstance(c.source_ref, str)
                    and _REF_SEP in c.source_ref
                    and c.source_ref.partition(_REF_SEP)[0]
                    != EXPERIMENT_ARTIFACT_TYPE):
                errors.append(_err(
                    "causal_overclaim", f"{path}.support_state",
                    "a causal/experimental claim with DIRECT or PARTIAL "
                    "support must cite a declared experiment "
                    f"({EXPERIMENT_ARTIFACT_TYPE}:...) as its source "
                    "(HR-05/M4)",
                    f"claim_type {c.claim_type!r} with support_state "
                    f"{c.support_state!r} cites non-experiment source "
                    f"{c.source_ref!r}",
                    "cite a pre_registered_experiment source, or lower the "
                    "support_state (INFERRED/SPECULATIVE)"))
        _validate_context_tags(c.context_tags, path, errors, context_resolver)
        for r in c.related_claims:
            if not isinstance(r, str) or not r.strip():
                errors.append(_err(
                    "invalid_related_claim_id", f"{path}.related_claims",
                    "related_claims must be a tuple of non-empty strings",
                    f"got {r!r}",
                    "supply content-addressed cl_ IDs or omit the field"))

    # 4. Per-assumption schema
    for i, a in enumerate(draft.assumptions):
        path = f"assumptions[{i}]"
        if not isinstance(a.statement, str) or not a.statement.strip():
            errors.append(_err(
                "empty_statement", f"{path}.statement",
                "an assumption statement must be a non-empty string",
                f"got {a.statement!r}",
                "supply the premise text"))
        _validate_context_tags(a.context_tags, path, errors, context_resolver)
        for r in a.supporting_artifact_refs:
            if not isinstance(r, str) or _REF_SEP not in r:
                errors.append(_err(
                    "invalid_artifact_ref", f"{path}.supporting_artifact_refs",
                    "supporting artifact refs must use the "
                    "'artifact_type:ref' form",
                    f"got {r!r}",
                    "supply dereferenceable artifact references"))

    # 5. assumption_refs resolve within the batch
    assumption_refs = {a.ref for a in draft.assumptions}
    for i, c in enumerate(draft.claims):
        path = f"claims[{i}]"
        for r in c.assumption_refs:
            if r not in assumption_refs:
                errors.append(_err(
                    "unresolved_assumption_ref", f"{path}.assumption_refs",
                    "claim assumption_refs must resolve to a batch assumption",
                    f"ref {r!r} does not match any assumption in the batch",
                    "add the assumption to the batch or drop the ref"))

    # 6. Content-derived identity + artifacts (only when schema is clean)
    claims: list[ResearchClaim] = []
    assumptions: list[ResearchAssumption] | tuple[ResearchAssumption, ...] = []
    if not errors:
        # 6a. build assumptions first (ids are needed for claim links)
        for a in draft.assumptions:
            assumptions.append(ResearchAssumption(
                assumption_id=assumption_id_of(
                    a.statement, a.context_tags, a.supporting_artifact_refs),
                statement=a.statement,
                context_tags=tuple(sorted(
                    (k, v) for k, v in a.context_tags.items())),
                supporting_artifact_refs=tuple(sorted(a.supporting_artifact_refs)),
                dependent_claim_ids=(),   # filled after claims are built
                status="ACTIVE",
                content_hash=assumption_id_of(
                    a.statement, a.context_tags, a.supporting_artifact_refs),
                schema_version=draft.schema_version,
                supersedes_ref=a.supersedes_ref,
            ))
        assumption_by_ref = {
            a.ref: aid.assumption_id for a, aid in zip(draft.assumptions, assumptions)
        }
        # 6b. claims with resolved assumption ids
        for c in draft.claims:
            # support_state is a validated closed-vocabulary member here
            # (step 3 rejects None / unknown before identity is derived).
            claims.append(ResearchClaim(
                claim_id=claim_id_of(
                    c.statement, c.source_ref, c.span_ref, c.claim_type,
                    c.context_tags, c.support_state or "", c.related_claims),
                statement=c.statement,
                source_ref=c.source_ref,
                support_state=c.support_state or "",
                span_ref=c.span_ref,
                claim_type=c.claim_type,
                context_tags=tuple(sorted(
                    (k, v) for k, v in c.context_tags.items())),
                assumption_ids=tuple(sorted(
                    assumption_by_ref[r] for r in c.assumption_refs)),
                related_claim_ids=tuple(sorted(c.related_claims)),
                content_hash=claim_id_of(
                    c.statement, c.source_ref, c.span_ref, c.claim_type,
                    c.context_tags, c.support_state or "", c.related_claims),
                schema_version=draft.schema_version,
                supersedes_ref=c.supersedes_ref,
            ))
        # 6c. dependent-claim maintenance (deterministic back-references)
        dependent: dict[str, list[str]] = {a.assumption_id: []
                                           for a in assumptions}
        for cl in claims:
            for aid in cl.assumption_ids:
                dependent[aid].append(cl.claim_id)
        assumptions = tuple(
            ResearchAssumption(
                assumption_id=a.assumption_id,
                statement=a.statement,
                context_tags=a.context_tags,
                supporting_artifact_refs=a.supporting_artifact_refs,
                dependent_claim_ids=tuple(sorted(dependent[a.assumption_id])),
                status=a.status,
                content_hash=a.content_hash,
                schema_version=a.schema_version,
                supersedes_ref=a.supersedes_ref,
            )
            for a in assumptions)
        # 6d. self-supersession is a structural contradiction
        {cl.claim_id for cl in claims}
        {a.assumption_id for a in assumptions}
        for cl in claims:
            if cl.supersedes_ref == cl.claim_id:
                errors.append(_err(
                    "self_supersession", f"claims[{cl.claim_id}]",
                    "a claim cannot supersede itself",
                    "supersedes_ref equals the claim's own content identity",
                    "drop the supersedes_ref"))
        for a in assumptions:
            if a.supersedes_ref == a.assumption_id:
                errors.append(_err(
                    "self_supersession", f"assumptions[{a.assumption_id}]",
                    "an assumption cannot supersede itself",
                    "supersedes_ref equals the assumption's own content "
                    "identity",
                    "drop the supersedes_ref"))

    if errors:
        return ExtractionResult(
            ExtractionVerdict.INVALID, tuple(errors),
            source_ref=draft.source_ref,
        )
    return ExtractionResult(
        ExtractionVerdict.ADMITTED,
        claims=tuple(claims),
        assumptions=tuple(assumptions),
        source_ref=draft.source_ref,
    )
