"""ResearchProgram — the epistemic contract (approved architecture, P2 slice).

Part 2 (MERGE INTO EXISTING COMPONENT) adopted a typed, immutable
``ResearchProgram`` artifact produced by the Director and validated by a
deterministic ``ResearchProgramValidator`` (a new row in the v4 §5 services
family). The compiler *service* was rejected; this module is the data model +
validator only.

Semantics
---------
The program answers: *what must be established, tested, verified, or
falsified for this project to achieve its declared epistemic objective.*
It does NOT mean "the task list" — the task graph owns execution structure
(v4 §7). The program carries no tasks, no budgets, no statuses. Its only
operational element is an optional reference to a GR7 task-graph template
(the template registry itself is P6; until then any non-null reference is
``UNSUPPORTED``).

Authority boundaries (Part 2 §10, §15, §22)
------------------------------------------
- The program DEFINES obligations (evidence/gate requirements derived from
  declared ladder targets against the §10.2 precondition map). It never
  decides whether obligations are satisfied, never promotes a claim, never
  writes state. The only mutation path for a compiled program is the
  ``ResearchProgramRepository`` (persistence/repositories.py), which rejects
  anything that is not ``COMPILED``.
- The LLM boundary: the Director produces a schema'd draft (the payload);
  this module is the deterministic validator. Malformed output fails closed
  with a structured ``CompilationResult`` — never an exception, never a
  partial program.

Determinism (Part 2 §7, §17)
----------------------------
Identical inputs + versions ⇒ identical program identity and structure.
No wall-clock time, no random UUIDs, no unordered iteration: ``content_hash``
and ``input_hash`` are SHA-256 over canonically sorted serializations.
``program_id = "rp_" + content_hash[:24]``.

Phase discipline
----------------
P2 slice only. Prediction/DiscriminationRequirement are structured inline
entries with stable refs (their promotion to first-class artifact tables is
P8, when ExperimentSpecification binding lands). GR7 template instantiation
(P6), graph-sourced rivals (P7/P8), and the gateway wiring (P3, via
``compile_from_payload``) are deferred and documented where they appear.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from hermes.research.regimes import (
    RegimeResolutionError,
    parse_regime_ref,
    resolve_regime,
)

# ── enums ──

# v4 §10.1 ladder. "Confirmatory" = SUPPORTED and above (Part 2 E1).
class LadderTarget(str, Enum):
    SPECULATIVE = "SPECULATIVE"
    PLAUSIBLE = "PLAUSIBLE"
    SUPPORTED = "SUPPORTED"
    ROBUST = "ROBUST"
    REPLICATED = "REPLICATED"

    @classmethod
    def confirmatory(cls) -> frozenset["LadderTarget"]:
        """Targets that require pre-registered evidence obligations (§10.2)."""
        return frozenset({cls.SUPPORTED, cls.ROBUST, cls.REPLICATED})


class PredictionDirection(str, Enum):
    FOR = "FOR"
    AGAINST = "AGAINST"
    NEUTRAL = "NEUTRAL"


class RivalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNRESOLVED = "UNRESOLVED"


class CompilationStatus(str, Enum):
    """Deterministic compilation verdict (Part 2 §12) — never vague.

    COMPILED       all checks pass; the artifact is emitted
    INCOMPLETE     missing required epistemic content (actionable revision)
    CONTRADICTORY  requirements conflict; no artifact
    UNSUPPORTED    requires a capability the project cannot yet supply
    INVALID        structural failure; fail closed, no artifact
    """

    COMPILED = "COMPILED"
    INCOMPLETE = "INCOMPLETE"
    CONTRADICTORY = "CONTRADICTORY"
    UNSUPPORTED = "UNSUPPORTED"
    INVALID = "INVALID"

    @classmethod
    def worst(cls, *statuses: "CompilationStatus") -> "CompilationStatus":
        """Highest-severity class present (INVALID > CONTRADICTORY >
        UNSUPPORTED > INCOMPLETE > COMPILED). Never downgrades a failure."""
        for candidate in (cls.INVALID, cls.CONTRADICTORY,
                          cls.UNSUPPORTED, cls.INCOMPLETE, cls.COMPILED):
            if candidate in statuses:
                return candidate
        return cls.COMPILED


# ── artifact schema version (Part 2 §17: schema_version is part of identity) ──
# C1 (Step 3, ratified Option A — hermes_c1_step3_schema_version_spec_conflict.md):
# the CURRENT program schema version is "2"; the SUPPORTED set retains the
# legacy "1" so pre-C1 programs remain valid and recompile to the IDENTICAL
# content_hash/program_id (AC-1 Delta=0). Unsupported versions are rejected
# consistently at both the validation and persistence boundaries (EC-V6-15).
PROGRAM_SCHEMA_VERSION = "2"
SUPPORTED_PROGRAM_SCHEMA_VERSIONS = frozenset({"1", "2"})

# ── canonical constants (Part 2 §11) ──

# §10.2 distilled: the citable artifact classes each confirmatory rung
# requires, and the integrity gates (§12) that gate it. E2/E3 check against
# this single source — the validator derives obligations from it, never
# from free-form proposal text.
LADDER_OBLIGATIONS: dict[LadderTarget, tuple[tuple[str, ...], tuple[str, ...]]] = {
    LadderTarget.SUPPORTED: (
        ("pre_registered_experiment", "statistical_analysis",
         "validation", "adversarial_critique"),
        ("data", "leakage", "statistical", "methodology", "adversarial"),
    ),
    LadderTarget.ROBUST: (
        ("pre_registered_experiment", "statistical_analysis",
         "validation", "adversarial_critique",
         "robustness_validation", "out_of_sample_validation", "regime_analysis"),
        ("data", "leakage", "statistical", "methodology",
         "adversarial", "robustness"),
    ),
    LadderTarget.REPLICATED: (
        ("pre_registered_experiment", "statistical_analysis",
         "validation", "adversarial_critique",
         "robustness_validation", "out_of_sample_validation",
         "regime_analysis", "replication_report"),
        ("data", "leakage", "statistical", "methodology",
         "adversarial", "robustness", "replication"),
    ),
}

ALLOWED_EVIDENCE_CLASSES = frozenset(
    artifact
    for artifacts, _ in LADDER_OBLIGATIONS.values()
    for artifact in artifacts
)

# v4 §9.1 — the three mandatory human gates. The hypothesis gate applies to
# every project; pre-compute/pre-live apply to any program with confirmatory
# hypotheses (Part 2 §23: two-stage approval maps onto the existing gates).
MANDATORY_HUMAN_GATES = ("hypothesis", "pre_compute", "pre_live")

# Well-formed reference pattern. Hypothesis/experiment artifacts do not yet
# have persistence tables on this baseline, so refs are format-validated now;
# dereference checks land with those artifacts (P4/P8).
_REF_RE = re.compile(r"^[A-Za-z0-9_\-:.]+\Z")

# C1 (design gate §2.2): slot_ref format — ``slot:<snake_case_label>``,
# ASCII, ≤ 128 characters total. The ``slot:`` prefix namespaces the
# vocabulary away from every other ref family (hypothesis:, evidence:,
# claim:). snake_case = lowercase ASCII letters/digits/underscores, starting
# with a letter.
_SLOT_REF_RE = re.compile(r"^slot:[a-z][a-z0-9_]*\Z")
_SLOT_REF_MAX_LENGTH = 128
# Rationale cap discipline (same as MAX_SCOPE_RATIONALE / gateway rationale
# fields): non-empty, ≤ 2000 characters.
MAX_SLOT_RATIONALE = 2000


# ── structured errors (Part 2 §12) ──

@dataclass(frozen=True, slots=True)
class CompilationError:
    """A single structured reason for a non-COMPILED verdict."""

    code: str
    field_path: str
    requirement: str
    explanation: str
    suggested_next_action: str


@dataclass(frozen=True, slots=True)
class CompilationResult:
    """The deterministic outcome of compiling a draft (Part 2 §12)."""

    status: CompilationStatus
    errors: tuple[CompilationError, ...] = ()
    program: "ResearchProgram | None" = None

    @property
    def compiled(self) -> bool:
        return self.status == CompilationStatus.COMPILED


# ── schema'd proposal structures (the Director's draft, Part 2 §6) ──

@dataclass(frozen=True, slots=True)
class HypothesisSpec:
    """One hypothesis in the program (ref resolves to a §10.2 Hypothesis).

    ``rival_of`` marks a rival explanation: either ACTIVE (with a
    structurally distinct prediction — E5) or explicitly UNRESOLVED
    (Part 2 §14: representation-or-record, never a checkbox rival).
    """

    ref: str
    ladder_target: LadderTarget
    falsification_condition: str
    rival_of: str | None = None
    rival_status: RivalStatus | None = None
    # C1 (design gate §4.1) — design-concept identity: the abstract slot this
    # hypothesis fills. Identity metadata only — never an eligibility,
    # ordering, ladder, or budget input (design gate §3). Optional (gate §7.2
    # pins it permanently optional); serialized into hypothesis_json and
    # content-addressed with the program ONLY when non-None (§4.2.3).
    slot_ref: str | None = None


@dataclass(frozen=True, slots=True)
class Prediction:
    """A schema'd prediction: claim + observable + direction + condition."""

    ref: str
    claim_ref: str
    observable: str
    direction: PredictionDirection
    condition: str
    falsification_relevance: str = ""


@dataclass(frozen=True, slots=True)
class DiscriminationRequirement:
    """'An experiment whose outcome differentiates H_a from H_b' (Part 2 §13).

    A structured declaration — observable, condition, expected difference,
    measurement method — never a computed information-gain score.
    """

    ref: str
    hypothesis_a: str
    hypothesis_b: str
    observable: str
    expected_difference: str
    required_condition: str
    measurement_method_ref: str


@dataclass(frozen=True, slots=True)
class EvidenceRequirement:
    """Derived obligation: what a claim must establish under §10.2.

    Derived by the validator from ``ladder_target`` — never authored free-
    form. E2 guarantees every class is §10.2-citable.
    """

    claim_ref: str
    ladder_target: LadderTarget
    required_artifacts: tuple[str, ...]
    associated_gates: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SlotDeclaration:
    """A new-slot declaration in the admission payload (C1 design gate §4.4).

    Payload-only admission-time evidence: validated at compile (E6) and
    recorded in the admission event payload — NEVER part of
    ``canonical_content_dict`` (rationale is provenance for vocabulary
    growth, not program semantics; AC-5).
    """

    slot_ref: str
    rationale: str


@dataclass(frozen=True, slots=True)
class ResearchProgramDraft:
    """The Director's schema'd proposal — the only LLM-produced input."""

    scope_ref: str
    epistemic_objective: str
    hypotheses: tuple[HypothesisSpec, ...]
    predictions: tuple[Prediction, ...] = ()
    discrimination_requirements: tuple[DiscriminationRequirement, ...] = ()
    methodology_constraints: tuple[str, ...] = ()
    task_graph_template_ref: str | None = None
    compiler_version: str = ""
    policy_version: str = ""
    schema_version: str = PROGRAM_SCHEMA_VERSION
    # C1 (§4.4): new-slot declarations carried with the draft for E6.
    # Never copied into ResearchProgram / canonical_content_dict by
    # _build_program — admission-time evidence only (AC-5).
    new_slot_declarations: tuple[SlotDeclaration, ...] = ()
    supersedes_ref: str | None = None
    # parallel-regime-test linkage (all-or-nothing): parent_program_id,
    # parent_hypothesis_ref, and target_regime are set together or all None.
    parent_program_id: str | None = None
    parent_hypothesis_ref: str | None = None
    target_regime: str | None = None


@dataclass(frozen=True, slots=True)
class ResearchProgram:
    """The immutable, content-addressed epistemic contract (Part 2 §5).

    ``evidence_requirements``/``gate_requirements`` are DERIVED by the
    validator. ``content_hash``/``input_hash``/``program_id`` are computed
    deterministically. Creation provenance (created_at/created_by/version)
    lives on the persisted row, never inside the hash — AC-01 requires
    identical inputs ⇒ identical identity.
    """

    program_id: str
    project_id: str
    scope_ref: str
    scope_content_hash: str  # governance: the frozen brief's content hash the
                             # program was compiled against (R-02); part of
                             # input_hash, never part of content_hash
    epistemic_objective: str
    hypotheses: tuple[HypothesisSpec, ...]
    predictions: tuple[Prediction, ...]
    discrimination_requirements: tuple[DiscriminationRequirement, ...]
    evidence_requirements: tuple[EvidenceRequirement, ...]
    gate_requirements: tuple[str, ...]
    methodology_constraints: tuple[str, ...]
    task_graph_template_ref: str | None
    compiler_version: str
    policy_version: str
    schema_version: str
    input_hash: str
    content_hash: str
    supersedes_ref: str | None
    # parallel-regime-test linkage (all-or-nothing, same as draft).
    parent_program_id: str | None = None
    parent_hypothesis_ref: str | None = None
    target_regime: str | None = None


# ── deterministic serialization (Part 2 §7: stable ordering) ──

def _canonicalize(value: Any) -> Any:
    """Recursively normalize for stable serialization.

    Dicts sort their keys; lists of dicts sort by their canonical JSON (so
    semantically identical lists serialize identically regardless of input
    order — this covers DERIVED structures like ``evidence_requirements``,
    whose dicts are keyed by ``claim_ref`` rather than ``ref``; R-01); lists
    of scalars sort. This defeats ordering nondeterminism (adversarial D).
    """
    if isinstance(value, dict):
        return {k: _canonicalize(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        items = [_canonicalize(v) for v in value]
        if items and all(isinstance(i, dict) for i in items):
            return sorted(
                items,
                key=lambda i: json.dumps(
                    i, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
            )
        if items and all(not isinstance(i, (dict, list, tuple)) for i in items):
            return sorted(items, key=str)
        return items
    if isinstance(value, Enum):
        return value.value
    return value


def canonical_json(value: Any) -> str:
    """Deterministic JSON serialization (stable ordering, compact separators)."""
    return json.dumps(_canonicalize(value), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str | bytes) -> str:
    """The deterministic content hash. Accepts bytes as-is (the fetch
    payloads are hashed over raw bytes — matches the driver's own
    ``hashlib.sha256(raw).hexdigest()``); strings are UTF-8 encoded."""
    if isinstance(text, bytes):
        return hashlib.sha256(text).hexdigest()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── obligation derivation (Part 2 §8, §15) ──

def _derive_evidence_requirements(
    hypotheses: tuple[HypothesisSpec, ...],
) -> tuple[EvidenceRequirement, ...]:
    """Derive §10.2 obligations for every confirmatory hypothesis."""
    derived: list[EvidenceRequirement] = []
    for hyp in hypotheses:
        if hyp.ladder_target not in LadderTarget.confirmatory():
            continue
        artifacts, gates = LADDER_OBLIGATIONS[hyp.ladder_target]
        derived.append(EvidenceRequirement(
            claim_ref=hyp.ref,
            ladder_target=hyp.ladder_target,
            required_artifacts=artifacts,
            associated_gates=gates,
        ))
    return tuple(derived)


def _derive_gate_requirements(
    hypotheses: tuple[HypothesisSpec, ...],
) -> tuple[str, ...]:
    """Mandatory human gates + integrity gates for each confirmatory target."""
    gates: set[str] = {MANDATORY_HUMAN_GATES[0]}  # hypothesis gate: every project
    has_confirmatory = any(
        h.ladder_target in LadderTarget.confirmatory() for h in hypotheses
    )
    if has_confirmatory:
        gates.update(MANDATORY_HUMAN_GATES)  # + pre_compute, pre_live
        for hyp in hypotheses:
            if hyp.ladder_target in LadderTarget.confirmatory():
                _, integrity = LADDER_OBLIGATIONS[hyp.ladder_target]
                gates.update(integrity)
    return tuple(sorted(gates))


def validate_program_epistemic(program: "ResearchProgram") -> tuple[CompilationError, ...]:
    """Re-run the prediction-level epistemic checks (E1/E4/E5 + the
    contradiction rule) directly on a compiled program (AR-01 hardening).

    The repository's integrity boundary re-derives identity and obligations
    but deliberately does not re-run the validator. This is the cheap,
    pure complement: the E-checks that depend on *predictions* — which do
    not feed the obligation derivation, so a forged-but-self-consistent
    program could omit them without tripping EC-V6-11..16. E2/E3 are
    already covered by ``derive_program_obligations`` (the repository
    re-derives and compares the declared obligations).

    Pure and deterministic: no clock, no SQL. Returns the structured
    ``CompilationError`` reasons (empty when the program is epistemically
    sound) — the write path fails closed on any. Mirrors the compiler's own
    checks (Part 2 §11) so the write path and the validator never disagree.
    """
    errors: list[CompilationError] = []
    confirmatory = [h for h in program.hypotheses
                    if h.ladder_target in LadderTarget.confirmatory()]
    preds_by_claim: dict[str, list[Prediction]] = {}
    for p in program.predictions:
        preds_by_claim.setdefault(p.claim_ref, []).append(p)

    # E1 — every confirmatory hypothesis has ≥1 prediction.
    for h in confirmatory:
        if not preds_by_claim.get(h.ref):
            errors.append(CompilationError(
                "E1_PREDICTIONS_MISSING", f"hypotheses.{h.ref}",
                "E1: every confirmatory hypothesis has ≥1 prediction",
                f"no prediction cites claim {h.ref!r}",
                "add a prediction for the hypothesis"))

    # E4 — discrimination requirements need predictions on both sides, and a
    # requirement whose hypotheses predict identically cannot discriminate.
    for d in program.discrimination_requirements:
        a_preds = preds_by_claim.get(d.hypothesis_a, [])
        b_preds = preds_by_claim.get(d.hypothesis_b, [])
        if not a_preds or not b_preds:
            errors.append(CompilationError(
                "E4_DISCRIMINATION_NO_PREDICTIONS",
                f"discrimination_requirements.{d.ref}",
                "E4: both sides of a discrimination requirement have predictions",
                f"missing predictions for {d.hypothesis_a!r}/{d.hypothesis_b!r}",
                "add predictions for both hypotheses"))
            continue
        a_sigs = {_prediction_signature(p) for p in a_preds}
        b_sigs = {_prediction_signature(p) for p in b_preds}
        if a_sigs == b_sigs and a_sigs:
            errors.append(CompilationError(
                "E4_DISCRIMINATION_NO_DIFFERENCE",
                f"discrimination_requirements.{d.ref}",
                "E4: a discrimination requirement differentiates its hypotheses",
                f"{d.hypothesis_a!r} and {d.hypothesis_b!r} predict identically",
                "choose an observable/condition where the rivals diverge"))

    # E5 — rival coverage: every confirmatory program has a rival or an
    # explicit UNRESOLVED rival record.
    if confirmatory and not any(h.rival_of is not None for h in program.hypotheses):
        errors.append(CompilationError(
            "E5_RIVAL_COVERAGE", "hypotheses",
            "E5: a confirmatory program includes a rival or an explicit "
            "UNRESOLVED rival record",
            "no rival (or UNRESOLVED rival) in a program with confirmatory claims",
            "add a rival (a NullHypothesis qualifies) or record an "
            "UNRESOLVED rival with a stated reason"))

    # E5 — ACTIVE rivals must be structurally distinguishable; UNRESOLVED
    # rivals are preserved as records.
    for h in program.hypotheses:
        if h.rival_of is None:
            continue
        if h.rival_status == RivalStatus.UNRESOLVED:
            continue
        rival_preds = preds_by_claim.get(h.ref, [])
        if not rival_preds:
            errors.append(CompilationError(
                "E5_RIVAL_NO_PREDICTION", f"hypotheses.{h.ref}",
                "E5: an ACTIVE rival has at least one prediction",
                f"rival {h.ref!r} is ACTIVE but has no prediction",
                "add a prediction for the rival or record it UNRESOLVED"))
            continue
        primary_preds = preds_by_claim.get(h.rival_of, [])
        rival_sigs = {_prediction_signature(p) for p in rival_preds}
        primary_sigs = {_prediction_signature(p) for p in primary_preds}
        if rival_sigs == primary_sigs and rival_sigs:
            errors.append(CompilationError(
                "E5_RIVAL_NOT_DISTINGUISHABLE", f"hypotheses.{h.ref}",
                "E5: a rival must be materially distinguishable at the "
                "prediction level",
                f"rival {h.ref!r} predicts exactly what its primary predicts",
                "distinguish the prediction (observable/condition/direction) "
                "or record the rival UNRESOLVED"))

    # Contradiction rule — a claim cannot predict both directions for the
    # same observable under the same condition.
    seen: dict[tuple[str, str, str], PredictionDirection] = {}
    for p in program.predictions:
        key = (p.claim_ref, p.observable, p.condition)
        if key in seen and seen[key] != p.direction:
            errors.append(CompilationError(
                "PREDICTION_CONFLICT", f"predictions.{p.ref}",
                "a claim cannot predict both directions for the same "
                "observable under the same condition",
                "conflicts with a prediction for the same claim, "
                "observable and condition",
                "resolve the conflicting predictions"))
        seen[key] = p.direction

    return tuple(errors)


def _prediction_signature(p: Prediction) -> tuple[str, str, str]:
    """The structural signature E5 compares: (observable, condition, direction)."""
    return (p.observable, p.condition, p.direction.value)


# ── the validator (Part 2 §11: only genuinely enforceable checks) ──

def compile_research_program(
    draft: ResearchProgramDraft,
    *,
    project_id: str,
    scope_content_hash: str | None = None,
    superseded_program_ids: frozenset[str] = frozenset(),
    known_program_ids: frozenset[str] = frozenset(),
    known_hypothesis_refs: frozenset[str] = frozenset(),
    slot_vocabulary: frozenset[str] = frozenset(),
) -> CompilationResult:
    """Compile a Director draft into a ``ResearchProgram`` (or a verdict).

    Pure and deterministic: no clock, no random, no SQL. The persistence
    layer supplies the governance context (``scope_content_hash``,
    ``superseded_program_ids``) from the database.

    C1 (design gate §4.5): ``slot_vocabulary`` is the project's append-only
    slot vocabulary — the union of ``slot_ref`` values over ALL program
    versions in the project's supersession history (a read-only projection
    supplied by the persistence layer). E6 checks every carried
    ``slot_ref`` against it. Default empty: a slot-less draft compiles
    exactly as before C1 (Delta=0).

    Verdict precedence: INVALID > CONTRADICTORY > UNSUPPORTED > INCOMPLETE
    > COMPILED. Every non-COMPILED verdict carries structured reasons.

    Fail-closed contract (EC-F02): a malformed *typed* draft — e.g. an
    ``int`` ref inside ``HypothesisSpec`` — returns an ``INVALID`` verdict
    with a ``MALFORMED_DRAFT`` reason instead of raising, matching the
    payload entry's semantics. This is the documented contract the P3
    gateway will depend on.
    """
    try:
        return _compile_research_program_checked(
            draft, project_id=project_id,
            scope_content_hash=scope_content_hash,
            superseded_program_ids=superseded_program_ids,
            known_program_ids=known_program_ids,
            known_hypothesis_refs=known_hypothesis_refs,
            slot_vocabulary=slot_vocabulary)
    except (TypeError, ValueError, AttributeError) as exc:
        return CompilationResult(CompilationStatus.INVALID, (
            CompilationError(
                "MALFORMED_DRAFT", "draft",
                "the typed draft must conform to the ResearchProgramDraft "
                "schema",
                f"malformed draft: {exc}",
                "construct a schema-conforming draft"),))


def _compile_research_program_checked(
    draft: ResearchProgramDraft,
    *,
    project_id: str,
    scope_content_hash: str | None = None,
    superseded_program_ids: frozenset[str] = frozenset(),
    known_program_ids: frozenset[str] = frozenset(),
    known_hypothesis_refs: frozenset[str] = frozenset(),
    slot_vocabulary: frozenset[str] = frozenset(),
) -> CompilationResult:
    """The unchecked compile body (wrapped by ``compile_research_program``)."""
    errors: list[CompilationError] = []
    statuses: list[CompilationStatus] = []

    # ── structural (INVALID) ──
    if not project_id or not isinstance(project_id, str):
        return CompilationResult(CompilationStatus.INVALID, (
            CompilationError("MISSING_PROJECT", "project_id",
                             "project_id is required",
                             "compilation needs a project context",
                             "provide the project_id from the gateway"),))
    if not draft.scope_ref or not isinstance(draft.scope_ref, str):
        errors.append(CompilationError(
            "MISSING_SCOPE_REF", "scope_ref", "a frozen ScopeBrief ref is required",
            "the program must cite the frozen brief (v4 §6.1/S16)",
            "reference the ScopeBrief produced at SCOPING"))
        statuses.append(CompilationStatus.INVALID)
    if not draft.epistemic_objective or not draft.epistemic_objective.strip():
        errors.append(CompilationError(
            "MISSING_OBJECTIVE", "epistemic_objective",
            "the declared epistemic objective is required",
            "E3 completeness cannot be checked without a declared target",
            "state what must be established for this program"))
        statuses.append(CompilationStatus.INVALID)
    if not draft.compiler_version or not draft.policy_version:
        errors.append(CompilationError(
            "MISSING_VERSION", "versions",
            "compiler_version and policy_version are required",
            "program identity depends on the version triple (Part 2 §17)",
            "supply the ratified compiler/policy versions"))
        statuses.append(CompilationStatus.INVALID)
    if draft.schema_version not in SUPPORTED_PROGRAM_SCHEMA_VERSIONS:
        errors.append(CompilationError(
            "SCHEMA_VERSION_MISMATCH", "schema_version",
            f"schema_version must be one of the supported versions "
            f"{sorted(SUPPORTED_PROGRAM_SCHEMA_VERSIONS)}",
            f"got {draft.schema_version!r}",
            "recompile with a supported artifact schema"))
        statuses.append(CompilationStatus.INVALID)
    if not draft.hypotheses:
        errors.append(CompilationError(
            "NO_HYPOTHESES", "hypotheses",
            "at least one hypothesis is required",
            "a research program with no claims is not a program; the "
            "null-result path belongs to S3 gaps / Director ABANDON",
            "add the hypothesis set or record the null result via S3 gaps"))
        statuses.append(CompilationStatus.INVALID)

    hyp_refs = [h.ref for h in draft.hypotheses]
    if len(hyp_refs) != len(set(hyp_refs)):
        errors.append(CompilationError(
            "DUP_HYPOTHESIS_REF", "hypotheses", "hypothesis refs must be unique",
            "duplicate hypothesis ref detected", "use distinct refs"))
        statuses.append(CompilationStatus.INVALID)
    for h in draft.hypotheses:
        if not _REF_RE.match(h.ref):
            errors.append(CompilationError(
                "BAD_REF_FORMAT", f"hypotheses.{h.ref}.ref",
                "refs must match ^[A-Za-z0-9_\\-:.]+$",
                f"malformed ref {h.ref!r}",
                "fix the reference format"))
            statuses.append(CompilationStatus.INVALID)
        if not h.falsification_condition or not h.falsification_condition.strip():
            errors.append(CompilationError(
                "NO_FALSIFICATION", f"hypotheses.{h.ref}.falsification_condition",
                "every hypothesis needs a falsification condition (v4 §10.2)",
                "falsification condition missing", "state the falsification condition"))
            statuses.append(CompilationStatus.INVALID)
        if h.rival_of is not None:
            if h.rival_of == h.ref:
                errors.append(CompilationError(
                    "SELF_RIVAL", f"hypotheses.{h.ref}.rival_of",
                    "a hypothesis cannot be its own rival",
                    "rival_of points at the hypothesis itself",
                    "point rival_of at a different hypothesis"))
                statuses.append(CompilationStatus.INVALID)
            elif h.rival_of not in hyp_refs:
                errors.append(CompilationError(
                    "UNRESOLVABLE_RIVAL", f"hypotheses.{h.ref}.rival_of",
                    "rival_of must reference a hypothesis in the program",
                    f"no hypothesis {h.rival_of!r} in the program",
                    "add the primary hypothesis or fix the ref"))
                statuses.append(CompilationStatus.INVALID)
            if h.rival_status is None:
                errors.append(CompilationError(
                    "RIVAL_STATUS_MISSING", f"hypotheses.{h.ref}.rival_status",
                    "a rival must be ACTIVE or explicitly UNRESOLVED (Part 2 §14)",
                    "rival_status missing",
                    "record ACTIVE (with a distinct prediction) or UNRESOLVED"))
                statuses.append(CompilationStatus.INVALID)
        elif h.rival_status is not None:
            errors.append(CompilationError(
                "RIVAL_STATUS_WITHOUT_RIVAL", f"hypotheses.{h.ref}.rival_status",
                "rival_status applies only to rivals (rival_of set)",
                "rival_status set on a non-rival hypothesis",
                "clear rival_status or set rival_of"))
            statuses.append(CompilationStatus.INVALID)

    pred_refs = [p.ref for p in draft.predictions]
    if len(pred_refs) != len(set(pred_refs)):
        errors.append(CompilationError(
            "DUP_PREDICTION_REF", "predictions", "prediction refs must be unique",
            "duplicate prediction ref detected", "use distinct refs"))
        statuses.append(CompilationStatus.INVALID)
    for p in draft.predictions:
        if not _REF_RE.match(p.ref):
            errors.append(CompilationError(
                "BAD_REF_FORMAT", f"predictions.{p.ref}.ref",
                "refs must match ^[A-Za-z0-9_\\-:.]+$",
                f"malformed ref {p.ref!r}", "fix the reference format"))
            statuses.append(CompilationStatus.INVALID)
        if p.claim_ref not in hyp_refs:
            errors.append(CompilationError(
                "UNRESOLVABLE_CLAIM", f"predictions.{p.ref}.claim_ref",
                "claim_ref must reference a hypothesis in the program",
                f"no hypothesis {p.claim_ref!r} in the program",
                "add the hypothesis or fix the claim_ref"))
            statuses.append(CompilationStatus.INVALID)
        if not p.observable or not p.observable.strip():
            errors.append(CompilationError(
                "MISSING_OBSERVABLE", f"predictions.{p.ref}.observable",
                "a prediction needs an observable",
                "observable missing", "state the measured quantity"))
            statuses.append(CompilationStatus.INVALID)

    disc_refs = [d.ref for d in draft.discrimination_requirements]
    if len(disc_refs) != len(set(disc_refs)):
        errors.append(CompilationError(
            "DUP_DISCRIMINATION_REF", "discrimination_requirements",
            "discrimination refs must be unique",
            "duplicate discrimination ref detected", "use distinct refs"))
        statuses.append(CompilationStatus.INVALID)
    for d in draft.discrimination_requirements:
        if d.hypothesis_a == d.hypothesis_b:
            errors.append(CompilationError(
                "DISCRIMINATION_SAME_HYPOTHESIS", f"discrimination_requirements.{d.ref}",
                "a discrimination requirement needs two distinct hypotheses",
                "hypothesis_a == hypothesis_b",
                "pick two different hypotheses"))
            statuses.append(CompilationStatus.INVALID)
        if d.hypothesis_a not in hyp_refs or d.hypothesis_b not in hyp_refs:
            errors.append(CompilationError(
                "UNRESOLVABLE_DISCRIMINATION", f"discrimination_requirements.{d.ref}",
                "both hypotheses must be in the program",
                "a referenced hypothesis is absent from the program",
                "add the hypotheses or fix the refs"))
            statuses.append(CompilationStatus.INVALID)
        for field_name in ("observable", "expected_difference",
                           "required_condition", "measurement_method_ref"):
            value = getattr(d, field_name)
            if not value or not isinstance(value, str) or not value.strip():
                errors.append(CompilationError(
                    "MISSING_DISCRIMINATION_FIELD",
                    f"discrimination_requirements.{d.ref}.{field_name}",
                    f"a discrimination requirement needs {field_name}",
                    f"{field_name} missing",
                    "complete the structured declaration"))
                statuses.append(CompilationStatus.INVALID)

    if draft.task_graph_template_ref is not None and not draft.task_graph_template_ref.strip():
        errors.append(CompilationError(
            "EMPTY_TEMPLATE_REF", "task_graph_template_ref",
            "template ref must be a non-empty string or None",
            "empty template ref", "drop the field or name a template"))
        statuses.append(CompilationStatus.INVALID)
    for i, c in enumerate(draft.methodology_constraints):
        if not isinstance(c, str) or not c.strip():
            errors.append(CompilationError(
                "BAD_CONSTRAINT", f"methodology_constraints[{i}]",
                "constraints must be non-empty strings",
                "malformed methodology constraint", "fix the constraint"))

    # ── governance (Part 2 §11) ──
    if scope_content_hash is None:
        errors.append(CompilationError(
            "SCOPE_NOT_GOVERNED", "scope_ref",
            "the frozen ScopeBrief's content hash must be supplied",
            "compilation cannot verify scope governance without the brief",
            "resolve the current frozen brief before compiling"))
        statuses.append(CompilationStatus.INVALID)
    elif not isinstance(scope_content_hash, str):
        errors.append(CompilationError(
            "SCOPE_HASH_NOT_STRING", "scope_ref",
            "scope_content_hash must be a string",
            f"got {type(scope_content_hash).__name__}",
            "resolve the brief's content hash and pass it as a string"))
        statuses.append(CompilationStatus.INVALID)
    if draft.supersedes_ref is not None and draft.supersedes_ref not in superseded_program_ids:
        errors.append(CompilationError(
            "UNRESOLVABLE_SUPERSEDES", "supersedes_ref",
            "supersedes_ref must reference an existing immutable program",
            f"program {draft.supersedes_ref!r} is not in the superseded set",
            "reference the actual prior program (or omit supersedes_ref)"))
        statuses.append(CompilationStatus.INVALID)
    # ── parallel-regime-test linkage (all-or-nothing + resolvability) ──
    parallel_fields = (draft.parent_program_id, draft.parent_hypothesis_ref,
                       draft.target_regime)
    if any(f is not None for f in parallel_fields) and not all(
        f is not None for f in parallel_fields):
        errors.append(CompilationError(
            "PARTIAL_PARALLEL_REGIME_TEST_FIELDS",
            "parent_program_id/parent_hypothesis_ref/target_regime",
            "parallel-regime-test fields are all-or-nothing: either all "
            "three are set or all three are None",
            "partial parallel-regime-test linkage detected",
            "set all three or none of parent_program_id, "
            "parent_hypothesis_ref, target_regime"))
        statuses.append(CompilationStatus.INVALID)
    if draft.parent_program_id is not None and \
            draft.parent_program_id not in known_program_ids:
        errors.append(CompilationError(
            "UNRESOLVABLE_PARENT_PROGRAM", "parent_program_id",
            "parent_program_id must reference a known program",
            f"program {draft.parent_program_id!r} is not in known_program_ids",
            "reference an existing program id"))
        statuses.append(CompilationStatus.INVALID)
    if draft.parent_hypothesis_ref is not None and \
            draft.parent_hypothesis_ref not in known_hypothesis_refs:
        errors.append(CompilationError(
            "UNRESOLVABLE_PARENT_HYPOTHESIS", "parent_hypothesis_ref",
            "parent_hypothesis_ref must reference a known hypothesis",
            f"hypothesis {draft.parent_hypothesis_ref!r} is not in "
            "known_hypothesis_refs",
            "reference an existing hypothesis ref"))
        statuses.append(CompilationStatus.INVALID)
    if draft.target_regime is not None and (
        not isinstance(draft.target_regime, str)
        or not draft.target_regime.strip()):
        errors.append(CompilationError(
            "INVALID_TARGET_REGIME", "target_regime",
            "target_regime must be a non-empty string",
            f"got {draft.target_regime!r}",
            "provide a non-empty target regime label"))
        statuses.append(CompilationStatus.INVALID)
    # Target-regime registry validation (Step 4 / S-R2 wiring, IDR-044):
    # a regime is referenced by its registered versioned tag only — the
    # free-string form is no longer admitted. A bare/unversioned tag
    # refuses (UNVERSIONED_REGIME); an unregistered (version, id) pair
    # refuses (UNREGISTERED_REGIME). Identity still hashes the raw draft
    # value (the content hash captures what was proposed).
    if draft.target_regime and draft.target_regime.strip():
        try:
            resolve_regime(parse_regime_ref(draft.target_regime))
        except RegimeResolutionError as exc:
            errors.append(CompilationError(
                exc.code, "target_regime",
                "target_regime must reference a registered regime versioned "
                "tag (VERSION:VERSION-ID, e.g. 'ICSS-v1:low-vol')",
                f"got {draft.target_regime!r}: {exc}",
                f"{exc.code}: reference a registry-registered versioned tag"))
            statuses.append(CompilationStatus.INVALID)

    # ── epistemic (E1, E2, E3, E4, E5 — Part 2 §11) ──
    confirmatory = [h for h in draft.hypotheses
                    if h.ladder_target in LadderTarget.confirmatory()]
    preds_by_claim: dict[str, list[Prediction]] = {}
    for p in draft.predictions:
        preds_by_claim.setdefault(p.claim_ref, []).append(p)

    # E1 — every confirmatory hypothesis has ≥1 prediction.
    for h in confirmatory:
        if not preds_by_claim.get(h.ref):
            errors.append(CompilationError(
                "E1_PREDICTIONS_MISSING", f"hypotheses.{h.ref}",
                "E1: every confirmatory hypothesis has ≥1 prediction",
                f"no prediction cites claim {h.ref!r}",
                "add a prediction for the hypothesis"))
            statuses.append(CompilationStatus.INCOMPLETE)

    # E3 — derived obligations cover the target's §10.2 preconditions.
    derived = _derive_evidence_requirements(draft.hypotheses)
    derived_by_claim = {e.claim_ref: e for e in derived}
    for h in confirmatory:
        req = derived_by_claim.get(h.ref)
        if req is None:
            errors.append(CompilationError(
                "E3_OBLIGATIONS_MISSING", f"hypotheses.{h.ref}",
                "E3: promotion-blocking requirements are represented",
                "no evidence obligation derived for a confirmatory claim",
                "ensure the ladder map covers this target"))
            statuses.append(CompilationStatus.INCOMPLETE)
        else:
            # E2 guard — derived classes must be §10.2-citable (by construction,
            # but checked so a map regression fails loudly instead of silently).
            bad = [a for a in req.required_artifacts
                   if a not in ALLOWED_EVIDENCE_CLASSES]
            if bad:
                errors.append(CompilationError(
                    "E2_UNALLOWED_CLASS", f"hypotheses.{h.ref}",
                    "E2: evidence requirements map to §10.2-citable classes",
                    f"derived classes not citable: {bad}",
                    "fix LADDER_OBLIGATIONS"))
                statuses.append(CompilationStatus.INVALID)

    # E5 — rival coverage: every confirmatory program has a rival or an
    # explicit UNRESOLVED rival record (Part 2 §14 rule 1).
    if confirmatory and not any(h.rival_of is not None for h in draft.hypotheses):
        errors.append(CompilationError(
            "E5_RIVAL_COVERAGE", "hypotheses",
            "E5: a confirmatory program includes a rival or an explicit "
            "UNRESOLVED rival record",
            "no rival (or UNRESOLVED rival) in a program with confirmatory claims",
            "add a rival (a NullHypothesis qualifies) or record an "
            "UNRESOLVED rival with a stated reason"))
        statuses.append(CompilationStatus.INCOMPLETE)

    # E5 — ACTIVE rivals must be structurally distinguishable; UNRESOLVED
    # rivals are preserved as records (Part 2 §14 rule 3 — no checkbox rivals).
    for h in draft.hypotheses:
        if h.rival_of is None:
            continue
        if h.rival_status == RivalStatus.UNRESOLVED:
            continue  # recorded-unresolved: preserved, not collapsed
        rival_preds = preds_by_claim.get(h.ref, [])
        if not rival_preds:
            errors.append(CompilationError(
                "E5_RIVAL_NO_PREDICTION", f"hypotheses.{h.ref}",
                "E5: an ACTIVE rival has at least one prediction",
                f"rival {h.ref!r} is ACTIVE but has no prediction",
                "add a prediction for the rival or record it UNRESOLVED"))
            statuses.append(CompilationStatus.INCOMPLETE)
            continue
        primary_preds = preds_by_claim.get(h.rival_of, [])
        rival_sigs = {_prediction_signature(p) for p in rival_preds}
        primary_sigs = {_prediction_signature(p) for p in primary_preds}
        # Structurally identical prediction sets ⇒ not materially
        # distinguishable ⇒ the "rival" is a checkbox (Part 2 §14 rule 3).
        if rival_sigs == primary_sigs and rival_sigs:
            errors.append(CompilationError(
                "E5_RIVAL_NOT_DISTINGUISHABLE", f"hypotheses.{h.ref}",
                "E5: a rival must be materially distinguishable at the "
                "prediction level",
                f"rival {h.ref!r} predicts exactly what its primary predicts",
                "distinguish the prediction (observable/condition/direction) "
                "or record the rival UNRESOLVED"))
            statuses.append(CompilationStatus.INCOMPLETE)

    # E4 — discrimination requirements need predictions on both sides, and a
    # requirement whose hypotheses predict identically cannot discriminate.
    for d in draft.discrimination_requirements:
        a_preds = preds_by_claim.get(d.hypothesis_a, [])
        b_preds = preds_by_claim.get(d.hypothesis_b, [])
        if not a_preds or not b_preds:
            errors.append(CompilationError(
                "E4_DISCRIMINATION_NO_PREDICTIONS", f"discrimination_requirements.{d.ref}",
                "E4: both sides of a discrimination requirement have predictions",
                f"missing predictions for {d.hypothesis_a!r}/{d.hypothesis_b!r}",
                "add predictions for both hypotheses"))
            statuses.append(CompilationStatus.INCOMPLETE)
            continue
        a_sigs = {_prediction_signature(p) for p in a_preds}
        b_sigs = {_prediction_signature(p) for p in b_preds}
        if a_sigs == b_sigs and a_sigs:
            errors.append(CompilationError(
                "E4_DISCRIMINATION_NO_DIFFERENCE", f"discrimination_requirements.{d.ref}",
                "E4: a discrimination requirement differentiates its hypotheses",
                f"{d.hypothesis_a!r} and {d.hypothesis_b!r} predict identically",
                "choose an observable/condition where the rivals diverge"))
            statuses.append(CompilationStatus.CONTRADICTORY)

    # ── E6 — slot vocabulary discipline (C1 design gate §4.5) ──
    # For every hypothesis carrying a slot_ref: format valid (§2.2); the
    # label is in the project vocabulary OR validly declared new in this
    # payload (§4.4); declarations and uses agree in both directions.
    # Identity metadata only — E6 never touches eligibility, ordering,
    # ladder state, or budget (design gate §3).
    used_slots: dict[str, str] = {}  # slot_ref -> first hypothesis ref using it
    for h in draft.hypotheses:
        if h.slot_ref is None:
            continue
        if (not isinstance(h.slot_ref, str)
                or not _SLOT_REF_RE.match(h.slot_ref)
                or len(h.slot_ref) > _SLOT_REF_MAX_LENGTH):
            errors.append(CompilationError(
                "E6_SLOT_MALFORMED", f"hypotheses.{h.ref}.slot_ref",
                "E6: slot_ref must be 'slot:<snake_case_label>', ASCII, "
                f"at most {_SLOT_REF_MAX_LENGTH} characters",
                f"malformed slot_ref {h.slot_ref!r}",
                "fix the slot_ref format"))
            statuses.append(CompilationStatus.INVALID)
            continue
        used_slots.setdefault(h.slot_ref, h.ref)

    declared_slots: dict[str, SlotDeclaration] = {}
    for i, decl in enumerate(draft.new_slot_declarations):
        if (not isinstance(decl.slot_ref, str)
                or not _SLOT_REF_RE.match(decl.slot_ref)
                or len(decl.slot_ref) > _SLOT_REF_MAX_LENGTH):
            errors.append(CompilationError(
                "E6_SLOT_MALFORMED", f"new_slot_declarations[{i}].slot_ref",
                "E6: a declared slot_ref must be 'slot:<snake_case_label>', "
                f"ASCII, at most {_SLOT_REF_MAX_LENGTH} characters",
                f"malformed declared slot_ref {decl.slot_ref!r}",
                "fix the declared slot_ref format"))
            statuses.append(CompilationStatus.INVALID)
            continue
        if not isinstance(decl.rationale, str) or not decl.rationale.strip():
            errors.append(CompilationError(
                "E6_SLOT_MALFORMED", f"new_slot_declarations[{i}].rationale",
                "E6: a new-slot declaration needs a non-empty rationale",
                "rationale missing or empty",
                "state the abstract function the slot names"))
            statuses.append(CompilationStatus.INVALID)
            continue
        if len(decl.rationale) > MAX_SLOT_RATIONALE:
            errors.append(CompilationError(
                "E6_SLOT_MALFORMED", f"new_slot_declarations[{i}].rationale",
                "E6: rationale must be at most "
                f"{MAX_SLOT_RATIONALE} characters",
                f"rationale is {len(decl.rationale)} characters",
                "shorten the rationale"))
            statuses.append(CompilationStatus.INVALID)
            continue
        if decl.slot_ref in declared_slots:
            errors.append(CompilationError(
                "E6_SLOT_MALFORMED", f"new_slot_declarations[{i}].slot_ref",
                "E6: a slot may be declared at most once per payload",
                f"duplicate declaration of {decl.slot_ref!r}",
                "declare each new slot exactly once"))
            statuses.append(CompilationStatus.INVALID)
            continue
        if decl.slot_ref in slot_vocabulary:
            errors.append(CompilationError(
                "E6_SLOT_ALREADY_DECLARED",
                f"new_slot_declarations[{i}].slot_ref",
                "E6: a slot already in the project vocabulary must be "
                "USED, not re-declared",
                f"{decl.slot_ref!r} already exists in the project "
                "vocabulary",
                "use the existing slot without a declaration"))
            statuses.append(CompilationStatus.INVALID)
            continue
        declared_slots[decl.slot_ref] = decl

    # Every used slot must be in the vocabulary or validly declared new.
    for slot in sorted(used_slots):
        if slot not in slot_vocabulary and slot not in declared_slots:
            errors.append(CompilationError(
                "E6_SLOT_UNDECLARED",
                f"hypotheses.{used_slots[slot]}.slot_ref",
                "E6: a slot_ref not in the project vocabulary must be "
                "declared new in the same payload",
                f"slot {slot!r} is not in the vocabulary and not declared",
                "declare the slot with a rationale, or use an existing "
                "slot"))
            statuses.append(CompilationStatus.INVALID)

    # Every declaration must be used by ≥1 hypothesis (no orphans).
    for slot in sorted(declared_slots):
        if slot not in used_slots:
            errors.append(CompilationError(
                "E6_SLOT_DECLARATION_UNUSED", "new_slot_declarations",
                "E6: every new-slot declaration must be used by at least "
                "one hypothesis in the same payload",
                f"declaration of {slot!r} is not used by any hypothesis",
                "use the declared slot or drop the declaration"))
            statuses.append(CompilationStatus.INVALID)

    # ── contradictory requirements (Part 2 §22 mode G) ──
    # Two predictions for the SAME claim with the same observable+condition
    # but different directions cannot both hold. Different claims may
    # legitimately predict the same observable differently (that is what a
    # discrimination requirement exploits) — so the key is per-claim.
    seen: dict[tuple[str, str, str], PredictionDirection] = {}
    for p in draft.predictions:
        key = (p.claim_ref, p.observable, p.condition)
        if key in seen and seen[key] != p.direction:
            errors.append(CompilationError(
                "PREDICTION_CONFLICT", f"predictions.{p.ref}",
                "a claim cannot predict both directions for the same "
                "observable under the same condition",
                "conflicts with a prediction for the same claim, "
                "observable and condition",
                "resolve the conflicting predictions"))
            statuses.append(CompilationStatus.CONTRADICTORY)
        seen[key] = p.direction

    # ── operational (Part 2 §11) ──
    # GR7 task-graph templates are admitted through the engineering plane at
    # P6. Until the template registry exists, a program that requires one is
    # UNSUPPORTED — the validator never invents an execution path.
    if draft.task_graph_template_ref is not None:
        errors.append(CompilationError(
            "UNSUPPORTED_TEMPLATE", "task_graph_template_ref",
            "task-graph template instantiation requires the GR7 template "
            "registry (P6)",
            f"template {draft.task_graph_template_ref!r} cannot be resolved "
            "on this phase",
            "defer template instantiation to P6, or drop the ref"))
        statuses.append(CompilationStatus.UNSUPPORTED)

    # ── verdict (Part 2 §12: worst class wins; all reasons preserved) ──
    status = CompilationStatus.worst(*statuses) if statuses else CompilationStatus.COMPILED
    if status != CompilationStatus.COMPILED:
        return CompilationResult(status, tuple(errors))

    # The governance check above guarantees a non-None, non-empty string by
    # the time status is COMPILED (a None/non-string appends an INVALID
    # status and returns earlier). Narrow for the type checker.
    assert scope_content_hash is not None
    program = _build_program(
        draft, project_id=project_id, scope_content_hash=scope_content_hash,
    )
    return CompilationResult(CompilationStatus.COMPILED, (), program)


def _build_program(
    draft: ResearchProgramDraft,
    *,
    project_id: str,
    scope_content_hash: str,
) -> ResearchProgram:
    """Build the compiled program (only called when all checks pass).

    Identity is never authored by the caller: ``content_hash``, ``input_hash``
    and ``program_id`` are derived here with the same pure helpers the
    persistence layer re-runs at the write path (v6 §28.2, Model D — one
    deterministic derivation, never two).
    """
    derived_evidence, gate_requirements = derive_program_obligations(
        draft.hypotheses)
    program = ResearchProgram(
        program_id="",
        project_id=project_id,
        scope_ref=draft.scope_ref,
        scope_content_hash=scope_content_hash,
        epistemic_objective=draft.epistemic_objective,
        hypotheses=draft.hypotheses,
        predictions=draft.predictions,
        discrimination_requirements=draft.discrimination_requirements,
        evidence_requirements=derived_evidence,
        gate_requirements=gate_requirements,
        methodology_constraints=draft.methodology_constraints,
        task_graph_template_ref=draft.task_graph_template_ref,
        compiler_version=draft.compiler_version,
        policy_version=draft.policy_version,
        schema_version=draft.schema_version,
        input_hash="",
        content_hash="",
        supersedes_ref=draft.supersedes_ref,
        parent_program_id=draft.parent_program_id,
        parent_hypothesis_ref=draft.parent_hypothesis_ref,
        target_regime=draft.target_regime,
    )
    content_hash = content_hash_of(program)
    return replace(
        program,
        content_hash=content_hash,
        input_hash=input_hash_of(program),
        program_id=program_id_of(content_hash),
    )


# ── payload boundary (Part 2 §10: fail closed; the P3 gateway wiring point) ──

_KNOWN_PAYLOAD_KEYS = frozenset({
    "scope_ref", "epistemic_objective", "hypotheses", "predictions",
    "discrimination_requirements", "methodology_constraints",
    "task_graph_template_ref", "compiler_version", "policy_version",
    "schema_version", "supersedes_ref",
    # parallel-regime-test linkage (all-or-nothing): set together or absent.
    "parent_program_id", "parent_hypothesis_ref", "target_regime",
    # IDR-041 AC-5: optional ratified rationale evidence — an APPROVED
    # PROPOSE_MECHANISM_SUBSTITUTION proposal id. Validated at the gateway;
    # the compiler never reads it (rationale evidence only).
    "ratification_ref",
    # B2 (ADR-041 AC-5): optional gateway-only — an ADMITTED
    # FailureClassification id that triggers PROPOSE_PARALLEL_REGIME_test.
    # Resolved + validated at the gateway; NEVER read by the compiler
    # or copied into ResearchProgramDraft.
    "triggering_classification_id",
    # C1 (design gate §4.4): payload-only admission-time new-slot
    # declarations. Validated by E6; recorded in the admission event
    # payload; NEVER part of canonical_content_dict.
    "new_slot_declarations",
})
_HYPOTHESIS_KEYS = frozenset({
    "ref", "ladder_target", "falsification_condition", "rival_of",
    "rival_status",
    # C1 (design gate §4.1): optional design-concept identity.
    "slot_ref",
})
_NEW_SLOT_DECLARATION_KEYS = frozenset({"slot_ref", "rationale"})
_PREDICTION_KEYS = frozenset({
    "ref", "claim_ref", "observable", "direction", "condition",
    "falsification_relevance",
})
_DISCRIMINATION_KEYS = frozenset({
    "ref", "hypothesis_a", "hypothesis_b", "observable",
    "expected_difference", "required_condition", "measurement_method_ref",
})


def _validate_payload_keys(payload: dict[str, Any]) -> list[CompilationError]:
    """Recursively reject unknown keys at every depth (EC-F01).

    The schema is closed not only at the top level: a nested ``status`` or
    ``sql`` key inside a hypothesis/prediction/discrimination entry is a
    boundary violation and must be *rejected* — never silently dropped — so
    the audit trail records the attempt. No impact on valid payloads.
    """
    errors: list[CompilationError] = []

    unknown = set(payload) - _KNOWN_PAYLOAD_KEYS
    if unknown:
        errors.append(CompilationError(
            "UNKNOWN_PAYLOAD_KEY", "payload",
            "the proposal schema is closed; unknown keys are rejected",
            f"unknown keys: {sorted(unknown)}",
            "remove the unknown fields"))

    for i, h in enumerate(payload.get("hypotheses", [])):
        if isinstance(h, dict):
            uk = set(h) - _HYPOTHESIS_KEYS
            if uk:
                errors.append(CompilationError(
                    "UNKNOWN_PAYLOAD_KEY", f"payload.hypotheses[{i}]",
                    "hypothesis entries have a closed schema; unknown keys "
                    "are rejected",
                    f"unknown keys: {sorted(uk)}",
                    "remove the unknown fields"))
    for i, p in enumerate(payload.get("predictions", [])):
        if isinstance(p, dict):
            uk = set(p) - _PREDICTION_KEYS
            if uk:
                errors.append(CompilationError(
                    "UNKNOWN_PAYLOAD_KEY", f"payload.predictions[{i}]",
                    "prediction entries have a closed schema; unknown keys "
                    "are rejected",
                    f"unknown keys: {sorted(uk)}",
                    "remove the unknown fields"))
    for i, d in enumerate(payload.get("discrimination_requirements", [])):
        if isinstance(d, dict):
            uk = set(d) - _DISCRIMINATION_KEYS
            if uk:
                errors.append(CompilationError(
                    "UNKNOWN_PAYLOAD_KEY",
                    f"payload.discrimination_requirements[{i}]",
                    "discrimination entries have a closed schema; unknown "
                    "keys are rejected",
                    f"unknown keys: {sorted(uk)}",
                    "remove the unknown fields"))
    for i, s in enumerate(payload.get("new_slot_declarations", [])):
        if isinstance(s, dict):
            uk = set(s) - _NEW_SLOT_DECLARATION_KEYS
            if uk:
                errors.append(CompilationError(
                    "UNKNOWN_PAYLOAD_KEY",
                    f"payload.new_slot_declarations[{i}]",
                    "new-slot declaration entries have a closed schema; "
                    "unknown keys are rejected",
                    f"unknown keys: {sorted(uk)}",
                    "remove the unknown fields"))
    return errors


def compile_from_payload(
    payload: dict[str, Any],
    *,
    project_id: str,
    scope_content_hash: str | None = None,
    superseded_program_ids: frozenset[str] = frozenset(),
    known_program_ids: frozenset[str] = frozenset(),
    known_hypothesis_refs: frozenset[str] = frozenset(),
    slot_vocabulary: frozenset[str] = frozenset(),
) -> CompilationResult:
    """The gateway-facing entry: payload → deterministic verdict.

    This is the exact function the P3 ``apply_intent`` per-kind validator
    for ``PROPOSE_RESEARCH_PROGRAM`` will call (Part 2 §8/§10). Unknown keys
    at any depth fail closed (EC-F01) — the schema has no room for evidence
    status, task state, or any authority the program must not carry.

    C1 (design gate §4.5): ``slot_vocabulary`` is the project's append-only
    slot vocabulary (read-only projection over the project's program rows),
    consumed by E6.
    """
    if not isinstance(payload, dict):
        return CompilationResult(CompilationStatus.INVALID, (
            CompilationError(
                "PAYLOAD_NOT_DICT", "payload",
                "the proposal payload must be a schema'd dict",
                f"got {type(payload).__name__}",
                "send the schema'd ResearchProgramDraft payload"),))
    key_errors = _validate_payload_keys(payload)
    if key_errors:
        return CompilationResult(CompilationStatus.INVALID, tuple(key_errors))

    try:
        draft = _draft_from_payload(payload)
    except (KeyError, TypeError, ValueError) as exc:
        return CompilationResult(CompilationStatus.INVALID, (
            CompilationError(
                "MALFORMED_PAYLOAD", "payload",
                "the payload must conform to the ResearchProgramDraft schema",
                f"malformed: {exc}",
                "resend a schema-conforming draft"),))

    return compile_research_program(
        draft, project_id=project_id,
        scope_content_hash=scope_content_hash,
        superseded_program_ids=superseded_program_ids,
        known_program_ids=known_program_ids,
        known_hypothesis_refs=known_hypothesis_refs,
        slot_vocabulary=slot_vocabulary,
    )


def _require_str(value: Any, field_name: str) -> str:
    """Require a string value; fail closed on any other type (R-03).

    The LLM boundary is structural: a numeric ``ref`` or a dict ``objective``
    is malformed output and must be rejected, never coerced into a plausible
    string. Coercion would let malformed proposals enter the compiled
    artifact under a different shape than the model produced.
    """
    if not isinstance(value, str):
        raise TypeError(
            f"{field_name} must be a string, got {type(value).__name__}")
    return value


def _draft_from_payload(payload: dict[str, Any]) -> ResearchProgramDraft:
    """Convert a validated payload to a draft (raises on malformed input)."""

    def _to_enum(enum_cls, value, field_name: str):
        try:
            return enum_cls(_require_str(value, field_name))
        except ValueError as exc:
            raise ValueError(f"{field_name}: unknown {enum_cls.__name__} {value!r}") from exc

    hypotheses = tuple(
        HypothesisSpec(
            ref=_require_str(h["ref"], f"hypotheses[{i}].ref"),
            ladder_target=_to_enum(
                LadderTarget, h["ladder_target"], f"hypotheses[{i}].ladder_target"),
            falsification_condition=_require_str(
                h["falsification_condition"],
                f"hypotheses[{i}].falsification_condition"),
            rival_of=(_require_str(h["rival_of"], f"hypotheses[{i}].rival_of")
                      if h.get("rival_of") is not None else None),
            rival_status=(
                _to_enum(RivalStatus, h["rival_status"], f"hypotheses[{i}].rival_status")
                if h.get("rival_status") is not None else None),
            # C1 (§4.1): optional design-concept identity. Absent/None stays
            # None — the validator never invents a slot (design gate §2.2).
            slot_ref=(_require_str(h["slot_ref"], f"hypotheses[{i}].slot_ref")
                      if h.get("slot_ref") is not None else None),
        )
        for i, h in enumerate(payload.get("hypotheses", []))
    )
    # C1 (§4.4): payload-only new-slot declarations (validated by E6;
    # recorded in the admission event; never part of canonical content).
    new_slot_declarations = tuple(
        SlotDeclaration(
            slot_ref=_require_str(
                s["slot_ref"], f"new_slot_declarations[{i}].slot_ref"),
            rationale=_require_str(
                s["rationale"], f"new_slot_declarations[{i}].rationale"),
        )
        for i, s in enumerate(payload.get("new_slot_declarations", []))
    )
    predictions = tuple(
        Prediction(
            ref=_require_str(p["ref"], f"predictions[{i}].ref"),
            claim_ref=_require_str(p["claim_ref"], f"predictions[{i}].claim_ref"),
            observable=_require_str(p["observable"], f"predictions[{i}].observable"),
            direction=_to_enum(
                PredictionDirection, p["direction"], f"predictions[{i}].direction"),
            condition=_require_str(p.get("condition", ""), f"predictions[{i}].condition"),
            falsification_relevance=_require_str(
                p.get("falsification_relevance", ""),
                f"predictions[{i}].falsification_relevance"),
        )
        for i, p in enumerate(payload.get("predictions", []))
    )
    discrimination = tuple(
        DiscriminationRequirement(
            ref=_require_str(d["ref"], f"discrimination_requirements[{i}].ref"),
            hypothesis_a=_require_str(
                d["hypothesis_a"], f"discrimination_requirements[{i}].hypothesis_a"),
            hypothesis_b=_require_str(
                d["hypothesis_b"], f"discrimination_requirements[{i}].hypothesis_b"),
            observable=_require_str(
                d["observable"], f"discrimination_requirements[{i}].observable"),
            expected_difference=_require_str(
                d["expected_difference"],
                f"discrimination_requirements[{i}].expected_difference"),
            required_condition=_require_str(
                d["required_condition"],
                f"discrimination_requirements[{i}].required_condition"),
            measurement_method_ref=_require_str(
                d["measurement_method_ref"],
                f"discrimination_requirements[{i}].measurement_method_ref"),
        )
        for i, d in enumerate(payload.get("discrimination_requirements", []))
    )
    constraints = tuple(
        _require_str(c, f"methodology_constraints[{i}]") if c is not None else ""
        for i, c in enumerate(payload.get("methodology_constraints", []))
    )
    template_ref = payload.get("task_graph_template_ref")
    if template_ref is not None and not isinstance(template_ref, str):
        raise TypeError("task_graph_template_ref must be a string or null")

    return ResearchProgramDraft(
        scope_ref=_require_str(payload["scope_ref"], "scope_ref"),
        epistemic_objective=_require_str(
            payload["epistemic_objective"], "epistemic_objective"),
        hypotheses=hypotheses,
        predictions=predictions,
        discrimination_requirements=discrimination,
        methodology_constraints=constraints,
        task_graph_template_ref=template_ref,
        compiler_version=_require_str(payload.get("compiler_version", ""), "compiler_version"),
        policy_version=_require_str(payload.get("policy_version", ""), "policy_version"),
        schema_version=_require_str(
            payload.get("schema_version", PROGRAM_SCHEMA_VERSION), "schema_version"),
        new_slot_declarations=new_slot_declarations,
        supersedes_ref=(_require_str(payload["supersedes_ref"], "supersedes_ref")
                        if payload.get("supersedes_ref") is not None else None),
        # parallel-regime-test linkage (all-or-nothing, validated above).
        parent_program_id=(_require_str(payload["parent_program_id"],
                            "parent_program_id")
                           if payload.get("parent_program_id") is not None else None),
        parent_hypothesis_ref=(_require_str(payload["parent_hypothesis_ref"],
                                 "parent_hypothesis_ref")
                            if payload.get("parent_hypothesis_ref") is not None else None),
        target_regime=(_require_str(payload["target_regime"], "target_regime")
                       if payload.get("target_regime") is not None else None),
    )


# ── serialization helpers (stable, for the DB row + observability) ──

def _h_to_dict(h: HypothesisSpec) -> dict:
    d = {
        "ref": h.ref,
        "ladder_target": h.ladder_target.value,
        "falsification_condition": h.falsification_condition,
        "rival_of": h.rival_of,
        "rival_status": h.rival_status.value if h.rival_status else None,
    }
    # C1 (design gate §4.2.3 — the load-bearing AC-1 clause): slot_ref is
    # emitted ONLY when non-None. Including "slot_ref": None would change
    # the content_hash of EVERY pre-C1 program (canonical_json serializes
    # None values) — an identity break of the entire corpus. This rule
    # covers BOTH consumers of this helper: canonical_content_dict
    # (identity) and program_to_dict (the DB row JSON).
    if h.slot_ref is not None:
        d["slot_ref"] = h.slot_ref
    return d


def _p_to_dict(p: Prediction) -> dict:
    return {
        "ref": p.ref,
        "claim_ref": p.claim_ref,
        "observable": p.observable,
        "direction": p.direction.value,
        "condition": p.condition,
        "falsification_relevance": p.falsification_relevance,
    }


def _d_to_dict(d: DiscriminationRequirement) -> dict:
    return {
        "ref": d.ref,
        "hypothesis_a": d.hypothesis_a,
        "hypothesis_b": d.hypothesis_b,
        "observable": d.observable,
        "expected_difference": d.expected_difference,
        "required_condition": d.required_condition,
        "measurement_method_ref": d.measurement_method_ref,
    }


# ── shared integrity helpers (v6 §28.2 Model D: one derivation, never two) ──
# The compiler derives identity + obligations here, and the persistence layer
# RE-DERIVES them at the write path with these same functions — the repository
# verifies self-consistency without re-running the epistemic validator.

def derive_program_obligations(
    hypotheses: tuple[HypothesisSpec, ...],
) -> tuple[tuple[EvidenceRequirement, ...], tuple[str, ...]]:
    """The validator's obligation derivation, shared with the repository.

    Returns ``(evidence_requirements, gate_requirements)`` exactly as the
    compiler would derive them for the given hypothesis set. The repository
    compares these against the caller-claimed values (EC-V6-14).
    """
    return (
        _derive_evidence_requirements(hypotheses),
        _derive_gate_requirements(hypotheses),
    )


def canonical_content_dict(program: ResearchProgram) -> dict:
    """The canonical semantic content dict — the identity source of truth.

    Shared by the compiler (identity derivation) and the repository
    (persistence integrity boundary, v6 §28.2). Obligations are read as
    declared; their agreement with the hypotheses is a separate deterministic
    assertion (``derive_program_obligations``).
    """
    d = {
        "scope_ref": program.scope_ref,
        "epistemic_objective": program.epistemic_objective,
        "hypotheses": [_h_to_dict(h) for h in program.hypotheses],
        "predictions": [_p_to_dict(p) for p in program.predictions],
        "discrimination_requirements": [
            _d_to_dict(d) for d in program.discrimination_requirements],
        "evidence_requirements": [
            {"claim_ref": e.claim_ref, "ladder_target": e.ladder_target.value,
             "required_artifacts": list(e.required_artifacts),
             "associated_gates": list(e.associated_gates)}
            for e in program.evidence_requirements],
        "gate_requirements": list(program.gate_requirements),
        "methodology_constraints": list(program.methodology_constraints),
        "task_graph_template_ref": program.task_graph_template_ref,
        "compiler_version": program.compiler_version,
        "policy_version": program.policy_version,
        "schema_version": program.schema_version,
    }
    # parallel-regime-test linkage: emitted ONLY when non-None. Including
    # None values would change the content_hash of every pre-regime program
    # (canonical_json serializes None) — an identity break. Same AC-1 clause
    # as slot_ref: identity metadata only, optional.
    if program.parent_program_id is not None:
        d["parent_program_id"] = program.parent_program_id
        d["parent_hypothesis_ref"] = program.parent_hypothesis_ref
        d["target_regime"] = program.target_regime
    return d


def content_hash_of(program: ResearchProgram) -> str:
    """The content identity: SHA-256 over the canonical content dict."""
    return sha256_hex(canonical_json(canonical_content_dict(program)))


def input_hash_of(program: ResearchProgram) -> str:
    """The input identity: SHA-256 over the governance-relevant inputs."""
    d = {
        "scope_ref": program.scope_ref,
        "scope_content_hash": program.scope_content_hash,
        "hypothesis_refs": sorted(h.ref for h in program.hypotheses),
        "prediction_refs": sorted(p.ref for p in program.predictions),
        "discrimination_refs": sorted(d.ref for d in program.discrimination_requirements),
        "constraints": sorted(program.methodology_constraints),
        "compiler_version": program.compiler_version,
        "policy_version": program.policy_version,
        "schema_version": program.schema_version,
        "supersedes_ref": program.supersedes_ref,
    }
    # parallel-regime-test linkage: emitted ONLY when non-None (AC-1 Delta=0
    # — ordinary programs with all three None must hash identically to
    # pre-regime programs). all-or-nothing invariant means either all three
    # appear or none do.
    if program.parent_program_id is not None:
        d["parent_program_id"] = program.parent_program_id
        d["parent_hypothesis_ref"] = program.parent_hypothesis_ref
        d["target_regime"] = program.target_regime
    return sha256_hex(canonical_json(d))


def program_id_of(content_hash: str) -> str:
    """The program identity: ``rp_`` + the first 24 hex chars of the hash."""
    return f"rp_{content_hash[:24]}"


def program_to_dict(program: ResearchProgram) -> dict:
    """Canonical program serialization (the DB row's JSON payload)."""
    return {
        "scope_ref": program.scope_ref,
        "epistemic_objective": program.epistemic_objective,
        "hypotheses": [_h_to_dict(h) for h in program.hypotheses],
        "predictions": [_p_to_dict(p) for p in program.predictions],
        "discrimination_requirements": [
            _d_to_dict(d) for d in program.discrimination_requirements],
        "evidence_requirements": [
            {"claim_ref": e.claim_ref, "ladder_target": e.ladder_target.value,
             "required_artifacts": list(e.required_artifacts),
             "associated_gates": list(e.associated_gates)}
            for e in program.evidence_requirements],
        "gate_requirements": list(program.gate_requirements),
        "methodology_constraints": list(program.methodology_constraints),
        "task_graph_template_ref": program.task_graph_template_ref,
        "compiler_version": program.compiler_version,
        "policy_version": program.policy_version,
        "schema_version": program.schema_version,
        "input_hash": program.input_hash,
        "content_hash": program.content_hash,
        "supersedes_ref": program.supersedes_ref,
        # parallel-regime-test linkage.
        "parent_program_id": program.parent_program_id,
        "parent_hypothesis_ref": program.parent_hypothesis_ref,
        "target_regime": program.target_regime,
    }



def program_from_dict(d: dict) -> ResearchProgram:  # type: ignore[no-untyped-def]
    """Reconstruct a ResearchProgram from a row-dict (_research_program_row_to_dict).

    IDR-045 D1 uses it to rebuild the compiled program from the filtered primary
    head for deterministic plan admission (build_task_plan / plan_to_payloads).
    The dict is the already-parsed shape from _research_program_row_to_dict
    (JSON columns parsed, advisory linkage keys present) — not a raw DB row.

    NOT the inverse of ``program_to_dict`` (MERGE-AUDIT-045 F5): that function
    omits ``program_id``/``project_id`` because they are identity metadata kept
    out of the content hash, so a round-trip through it would silently yield
    ``program_id == ""``. ``_identity`` (task_plan.py) hashes ``program_id``
    into every plan task_id, so an empty one collides across every project and
    program. Both keys are therefore REQUIRED here and raise rather than
    defaulting.
    """
    for _required in ("program_id", "project_id"):
        if not d.get(_required):
            raise ValueError(
                f"program_from_dict requires a non-empty {_required!r} "
                f"(program_to_dict omits it — it is not an inverse source): "
                f"got {d.get(_required)!r}"
            )

    def _h(h: dict) -> HypothesisSpec:  # type: ignore[no-untyped-def]
        return HypothesisSpec(
            ref=str(h.get("ref", "")),
            ladder_target=LadderTarget(h.get("ladder_target", "SPECULATIVE")),
            falsification_condition=str(h.get("falsification_condition", "")),
            rival_of=h.get("rival_of"),
            rival_status=(RivalStatus(h["rival_status"]) if h.get("rival_status") else None),
            slot_ref=h.get("slot_ref"),
        )

    def _p(pp: dict) -> Prediction:  # type: ignore[no-untyped-def]
        return Prediction(
            ref=str(pp.get("ref", "")),
            claim_ref=str(pp.get("claim_ref", "")),
            observable=str(pp.get("observable", "")),
            direction=PredictionDirection(pp.get("direction", "NEUTRAL")),
            condition=str(pp.get("condition", "")),
            falsification_relevance=str(pp.get("falsification_relevance", "")),
        )

    def _dr(dd: dict) -> DiscriminationRequirement:  # type: ignore[no-untyped-def]
        return DiscriminationRequirement(
            ref=str(dd.get("ref", "")),
            hypothesis_a=str(dd.get("hypothesis_a", "")),
            hypothesis_b=str(dd.get("hypothesis_b", "")),
            observable=str(dd.get("observable", "")),
            expected_difference=str(dd.get("expected_difference", "")),
            required_condition=str(dd.get("required_condition", "")),
            measurement_method_ref=str(dd.get("measurement_method_ref", "")),
        )

    def _ev(ev: dict) -> EvidenceRequirement:  # type: ignore[no-untyped-def]
        arts = ev.get("required_artifacts", [])
        gates = ev.get("associated_gates", [])
        return EvidenceRequirement(
            claim_ref=str(ev.get("claim_ref", "")),
            ladder_target=LadderTarget(ev.get("ladder_target", "SPECULATIVE")),
            required_artifacts=tuple(str(a) for a in arts) if arts else (),
            associated_gates=tuple(str(g) for g in gates) if gates else (),
        )

    return ResearchProgram(
        program_id=str(d.get("program_id", "")),
        project_id=str(d.get("project_id", "")),
        scope_ref=str(d.get("scope_ref", "")),
        scope_content_hash=str(d.get("scope_content_hash", "")),
        epistemic_objective=str(d.get("epistemic_objective", "")),
        hypotheses=tuple(_h(h) for h in (d.get("hypotheses") or [])),
        predictions=tuple(_p(pp) for pp in (d.get("predictions") or [])),
        discrimination_requirements=tuple(_dr(dd) for dd in (d.get("discrimination_requirements") or [])),
        evidence_requirements=tuple(_ev(ev) for ev in (d.get("evidence_requirements") or [])),
        gate_requirements=tuple(str(g) for g in (d.get("gate_requirements") or [])),
        methodology_constraints=tuple(str(c) for c in (d.get("methodology_constraints") or [])),
        task_graph_template_ref=d.get("task_graph_template_ref"),
        compiler_version=str(d.get("compiler_version", "")),
        policy_version=str(d.get("policy_version", "")),
        schema_version=str(d.get("schema_version", "1")),
        input_hash=str(d.get("input_hash", "")),
        content_hash=str(d.get("content_hash", "")),
        supersedes_ref=d.get("supersedes_ref"),
        parent_program_id=d.get("parent_program_id"),
        parent_hypothesis_ref=d.get("parent_hypothesis_ref"),
        target_regime=d.get("target_regime"),
    )


def summarize(program: ResearchProgram) -> str:
    """Deterministic human-readable summary (Part 2 §20 observability).

    Rendered through the existing vault/renderer pipeline; no UI subsystem.
    """
    lines = [
        f"ResearchProgram {program.program_id}",
        f"  objective: {program.epistemic_objective}",
        f"  scope_ref: {program.scope_ref}",
        (f"  versions: compiler={program.compiler_version} policy="
        f"{program.policy_version} schema={program.schema_version}"),
        f"  input_hash: {program.input_hash}  content_hash: {program.content_hash}",
        f"  supersedes_ref: {program.supersedes_ref or '-'}",
    ]
    lines.append("  hypotheses:")
    for h in program.hypotheses:
        if h.rival_of and h.rival_status is not None:
            rival = f" rival_of={h.rival_of} ({h.rival_status.value})"
        else:
            rival = ""
        lines.append(
            f"    {h.ref} → {h.ladder_target.value}{rival}")
    lines.append("  predictions:")
    for p in program.predictions:
        lines.append(
            f"    {p.ref} claims {p.claim_ref}: {p.observable} "
            f"{p.direction.value} under {p.condition}")
    lines.append("  discrimination requirements:")
    for d in program.discrimination_requirements:
        lines.append(
            f"    {d.ref}: {d.hypothesis_a} vs {d.hypothesis_b} on {d.observable} "
            f"({d.expected_difference})")
    lines.append("  evidence obligations:")
    for e in program.evidence_requirements:
        lines.append(
            f"    {e.claim_ref} [{e.ladder_target.value}]: "
            f"{', '.join(e.required_artifacts)}")
    lines.append(f"  gates: {', '.join(program.gate_requirements)}")
    return "\n".join(lines)
