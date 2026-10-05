"""ActionEvaluation — deterministic candidate-action comparison (Optimizer decision).

Part 1 (Research Process Optimizer) verdict: **ADOPT AS A DETERMINISTIC
EVALUATION LIBRARY**. The optimizer-as-authority was rejected: selection
judgment belongs to the Director (v4 §13), and S3/GR6 already generate the
candidate set (v4 §7). What survives is pure, deterministic comparison of
**existing admissible candidate actions** into a hashed, versioned
``CandidateRanking`` consumed by the Director as advisory input.

Non-negotiables (Part 1 §2, §7, §13, §14):
- **No scalar score, no weighted utility.** The ranking is a multidimensional
  comparison table + a documented, versioned lexicographic ordering policy.
  There is nothing to maximize, so there is nothing to Goodhart.
- **No LLM in evaluation.** Fully deterministic given (candidate set, state
  facts, version triple) — reproducible across processes (AC-12).
- **No write path.** This module has no repository imports, no SQL, no
  mutation. It can never create tasks, spend budget, or promote evidence.
- **No candidate generation.** The evaluator compares candidates it is given;
  it never invents actions (Part 1 protest §3).
- **Gate-blocked candidates are excluded, never ranked** (AC-03); costs are
  ``LOW|MEDIUM|HIGH|UNKNOWN`` tiers with ``UNKNOWN`` never treated as a value
  (AC-08); stale inputs and starved candidates are flagged as diagnostics
  (AC-09/AC-10), never silently trusted and never auto-remediated.

The ordering is a *recommendation to judgment*, never a decision: the full
comparison table and the ordering policy are exposed so the Director can see
exactly why one candidate precedes another (Part 1 §16, §25).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from hermes.research.programs import canonical_json, sha256_hex

# ── artifact schema version (Part 1 §17: evaluator_version + policy_version + schema_version) ──
EVALUATION_SCHEMA_VERSION = "1"

DIMENSION_ORDER = (
    "evidence_gap_closure", "contradiction_reduction", "rival_discrimination",
    "replication_value", "frontier_value", "coverage",
)

# Documented, versioned lexicographic ordering policy (Part 1 §7). Not a
# weighted score: a stable, auditable primary-dimension order with cost as
# the final tiebreak and UNKNOWN cost always last (AC-08).
DEFAULT_ORDERING_POLICY = (
    "lexicographic over: evidence_gap_closure, contradiction_reduction, "
    "rival_discrimination, replication_value, frontier_value, coverage, "
    "cost (UNKNOWN last), time (UNKNOWN last), compute (UNKNOWN last), "
    "candidate_ref (deterministic tie-break)"
)


class DimensionLevel(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class CostTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Reversibility(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class CandidateStatus(str, Enum):
    ADMISSIBLE = "ADMISSIBLE"
    EXCLUDED_GATE = "EXCLUDED_GATE"          # HARD exclusion — never ranked (AC-03)
    BLOCKED_DEPENDENCY = "BLOCKED_DEPENDENCY"  # surfaced for engineering-plane routing


class DiagnosticKind(str, Enum):
    STARVED_CANDIDATE = "STARVED_CANDIDATE"
    STALE_INPUT = "STALE_INPUT"
    EMPTY_CANDIDATE_SET = "EMPTY_CANDIDATE_SET"
    NO_IMPROVEMENT = "NO_IMPROVEMENT"


# ── inputs ──

@dataclass(frozen=True, slots=True)
class CandidateAction:
    """An EXISTING admissible action the evaluator compares (never invents).

    ``candidate_ref`` points at the real candidate: an S3 gap entry, a GR6
    graph-computed gap, an S14 freshness proposal, or a ResearchProgram
    obligation. The evaluator consumes, never generates.
    """

    candidate_ref: str
    action_type: str
    objective_ref: str
    obligation_refs: tuple[str, ...] = ()
    # Dimension facts supplied from state (label + basis). Keys must be in
    # DIMENSION_ORDER; values are DimensionLevel.
    dimensions: Mapping[str, DimensionLevel] = field(default_factory=dict)
    cost: CostTier = CostTier.UNKNOWN
    time: CostTier = CostTier.UNKNOWN
    compute: CostTier = CostTier.UNKNOWN
    implementation_risk: RiskLevel = RiskLevel.LOW
    dependency_risk: RiskLevel = RiskLevel.LOW
    reversibility: Reversibility = Reversibility.HIGH
    blocked_by: tuple[str, ...] = ()              # gate ids → HARD exclusion
    dependency_unsatisfied: tuple[str, ...] = ()  # skill/tool/methodology → BLOCKED
    basis_refs: tuple[str, ...] = ()              # per-dimension evidence refs (AC-07)


# ── outputs ──

@dataclass(frozen=True, slots=True)
class ActionEvaluation:
    """One candidate's full comparison record (never a scalar)."""

    candidate_ref: str
    status: CandidateStatus
    exclusion_reason: str
    action_type: str
    objective_ref: str
    obligation_refs: tuple[str, ...]
    dimensions: tuple[tuple[str, DimensionLevel], ...]  # DIMENSION_ORDER
    cost: CostTier
    time: CostTier
    compute: CostTier
    implementation_risk: RiskLevel
    dependency_risk: RiskLevel
    reversibility: Reversibility
    basis_refs: tuple[str, ...]
    staleness: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RankingDiagnostic:
    kind: DiagnosticKind
    candidate_ref: str | None
    detail: str


@dataclass(frozen=True, slots=True)
class CandidateRanking:
    """The advisory comparison artifact (transient, hashed, versioned).

    ``ranking_id`` is content-derived: same inputs + same version triple ⇒
    same identity (AC-01/AC-12). Re-derivable on demand like ``GraphDiagnostics``
    — never persisted as evidence, never a gate input.
    """

    ranking_id: str
    evaluator_version: str
    policy_version: str
    schema_version: str
    input_state_hash: str
    ordering_policy: str
    comparison: tuple[ActionEvaluation, ...]      # full table, ordered (admissible first)
    exclusions: tuple[ActionEvaluation, ...]      # gate/dependency excluded — never ranked
    diagnostics: tuple[RankingDiagnostic, ...]
    content_hash: str


# ── deterministic evaluation ──

_DIM_LEVEL_ORDER = {
    DimensionLevel.NONE: 0,
    DimensionLevel.LOW: 1,
    DimensionLevel.MEDIUM: 2,
    DimensionLevel.HIGH: 3,
}
_COST_ORDER = {
    CostTier.LOW: 3,
    CostTier.MEDIUM: 2,
    CostTier.HIGH: 1,
    CostTier.UNKNOWN: 0,   # AC-08: unknown never treated as a value; sorts last
}


def evaluate_candidates(
    candidates: tuple[CandidateAction, ...] | list[CandidateAction],
    *,
    selection_history: Mapping[str, tuple[int, int]] | None = None,
    stale_input_ids: frozenset[str] = frozenset(),
    evaluator_version: str = "1.0.0",
    policy_version: str = "eval-2026.1",
    ordering_policy: str = DEFAULT_ORDERING_POLICY,
) -> CandidateRanking:
    """Deterministically compare a candidate set into a ``CandidateRanking``.

    Pure: no clock, no random, no SQL, no write path (AC-04/05/06). Same
    inputs + same version triple ⇒ same ranking identity (AC-01/AC-12).
    """
    candidates = tuple(candidates)
    if not candidates:
        return _build_ranking(
            candidates=(), comparisons=(), exclusions=(), ordering_policy=ordering_policy,
            evaluator_version=evaluator_version, policy_version=policy_version,
            diagnostics=(RankingDiagnostic(
                DiagnosticKind.EMPTY_CANDIDATE_SET, None,
                "no admissible candidates were supplied — none are invented"),),
            selection_history=selection_history or {},
            stale_input_ids=set(stale_input_ids or ()),
        )

    stale = set(stale_input_ids or ())
    diagnostics: list[RankingDiagnostic] = []

    comparisons: list[ActionEvaluation] = []
    exclusions: list[ActionEvaluation] = []

    for cand in candidates:
        # Hard exclusions first (AC-03: gate-blocked never ranked).
        if cand.blocked_by:
            exclusions.append(_evaluate_one(cand, CandidateStatus.EXCLUDED_GATE,
                                            f"blocked by gate(s): {', '.join(cand.blocked_by)}",
                                            stale))
            continue
        if cand.dependency_unsatisfied:
            exclusions.append(_evaluate_one(
                cand, CandidateStatus.BLOCKED_DEPENDENCY,
                "unsatisfied dependency (route via engineering plane): "
                + ", ".join(cand.dependency_unsatisfied), stale))
            continue
        comparisons.append(_evaluate_one(cand, CandidateStatus.ADMISSIBLE, "", stale))

    # AC-10: starvation — proposed across rounds but never selected.
    hist = selection_history or {}
    for cand in candidates:
        proposed, selected = hist.get(cand.candidate_ref, (0, 0))
        if proposed >= 1 and selected == 0:
            diagnostics.append(RankingDiagnostic(
                DiagnosticKind.STARVED_CANDIDATE, cand.candidate_ref,
                f"proposed {proposed} time(s), never selected — surfaced, "
                f"never auto-promoted"))
    # AC-09: stale inputs flagged, not silently trusted.
    for sid in sorted(stale):
        diagnostics.append(RankingDiagnostic(
            DiagnosticKind.STALE_INPUT, None,
            f"input {sid!r} is stale — dimension facts referencing it are "
            f"flagged and marked stale"))
    # No-improvement diagnostic: all dimensions at NONE.
    if comparisons and all(
        all(v == DimensionLevel.NONE for _, v in e.dimensions) for e in comparisons):
        diagnostics.append(RankingDiagnostic(
            DiagnosticKind.NO_IMPROVEMENT, None,
            "no admissible candidate improves any tracked dimension — "
            "Director decides continue / pause / human (limit = stop, never pass)"))

    ordered = sorted(
        comparisons,
        key=lambda e: (_ordering_key(e), e.candidate_ref),
        reverse=True,
    )
    return _build_ranking(
        candidates=candidates, comparisons=tuple(ordered),
        exclusions=tuple(exclusions), ordering_policy=ordering_policy,
        evaluator_version=evaluator_version, policy_version=policy_version,
        diagnostics=tuple(diagnostics),
        selection_history=hist, stale_input_ids=stale,
    )


def _evaluate_one(
    cand: CandidateAction,
    status: CandidateStatus,
    exclusion_reason: str,
    stale: set[str],
) -> ActionEvaluation:
    dims: list[tuple[str, DimensionLevel]] = []
    for dim in DIMENSION_ORDER:
        level = cand.dimensions.get(dim, DimensionLevel.NONE)
        dims.append((dim, level))
    return ActionEvaluation(
        candidate_ref=cand.candidate_ref,
        status=status,
        exclusion_reason=exclusion_reason,
        action_type=cand.action_type,
        objective_ref=cand.objective_ref,
        obligation_refs=cand.obligation_refs,
        dimensions=tuple(dims),
        cost=cand.cost,
        time=cand.time,
        compute=cand.compute,
        implementation_risk=cand.implementation_risk,
        dependency_risk=cand.dependency_risk,
        reversibility=cand.reversibility,
        basis_refs=cand.basis_refs,
        staleness=tuple(sorted(
            sid for sid in stale if _references_stale(cand, sid))),
    )


def _references_stale(cand: CandidateAction, stale_id: str) -> bool:
    """Conservative staleness: any candidate whose refs mention the stale id."""
    refs = (cand.basis_refs + cand.obligation_refs
            + (cand.objective_ref, cand.candidate_ref))
    return any(stale_id in r for r in refs)


def _ordering_key(e: ActionEvaluation) -> tuple[Any, ...]:
    """Documented lexicographic ordering key (Part 1 §7, DEFAULT_ORDERING_POLICY).

    Not a score: each element is a named dimension level; the whole policy is
    embedded in the ranking so the ordering is auditable and the Director can
    disagree. Unknown costs/times sort last (AC-08).
    """
    dim_key = tuple(_DIM_LEVEL_ORDER[v] for _, v in e.dimensions)
    return dim_key + (_COST_ORDER[e.cost], _COST_ORDER[e.time], _COST_ORDER[e.compute])


def _build_ranking(
    *,
    candidates: tuple[CandidateAction, ...],
    comparisons: tuple[ActionEvaluation, ...],
    exclusions: tuple[ActionEvaluation, ...],
    ordering_policy: str,
    evaluator_version: str,
    policy_version: str,
    diagnostics: tuple[RankingDiagnostic, ...],
    selection_history: Mapping[str, tuple[int, int]],
    stale_input_ids: set[str],
) -> CandidateRanking:
    input_state = {
        "candidate_refs": sorted(c.candidate_ref for c in candidates),
        "selection_history": {
            ref: list(v) for ref, v in sorted(selection_history.items())},
        "stale_input_ids": sorted(stale_input_ids),
        "evaluator_version": evaluator_version,
        "policy_version": policy_version,
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "ordering_policy": ordering_policy,
    }
    input_state_hash = sha256_hex(canonical_json(input_state))

    body = {
        "comparison": [_e_to_dict(e) for e in comparisons],
        "exclusions": [_e_to_dict(e) for e in exclusions],
        "diagnostics": [
            {"kind": d.kind.value, "candidate_ref": d.candidate_ref,
             "detail": d.detail} for d in diagnostics],
        "ordering_policy": ordering_policy,
        "evaluator_version": evaluator_version,
        "policy_version": policy_version,
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "input_state_hash": input_state_hash,
    }
    content_hash = sha256_hex(canonical_json(body))
    return CandidateRanking(
        ranking_id=f"eval_{content_hash[:24]}",
        evaluator_version=evaluator_version,
        policy_version=policy_version,
        schema_version=EVALUATION_SCHEMA_VERSION,
        input_state_hash=input_state_hash,
        ordering_policy=ordering_policy,
        comparison=comparisons,
        exclusions=exclusions,
        diagnostics=diagnostics,
        content_hash=content_hash,
    )


def _e_to_dict(e: ActionEvaluation) -> dict:
    return {
        "candidate_ref": e.candidate_ref,
        "status": e.status.value,
        "exclusion_reason": e.exclusion_reason,
        "action_type": e.action_type,
        "objective_ref": e.objective_ref,
        "obligation_refs": list(e.obligation_refs),
        "dimensions": {k: v.value for k, v in e.dimensions},
        "cost": e.cost.value,
        "time": e.time.value,
        "compute": e.compute.value,
        "implementation_risk": e.implementation_risk.value,
        "dependency_risk": e.dependency_risk.value,
        "reversibility": e.reversibility.value,
        "basis_refs": list(e.basis_refs),
        "staleness": list(e.staleness),
    }


def summarize_ranking(ranking: CandidateRanking) -> str:
    """Deterministic human-readable summary (Part 1 §16 — no new UI)."""
    lines = [
        f"CandidateRanking {ranking.ranking_id}",
        (f"  versions: evaluator={ranking.evaluator_version} policy="
        f"{ranking.policy_version} schema={ranking.schema_version}"),
        f"  input_state_hash: {ranking.input_state_hash}",
        f"  ordering policy: {ranking.ordering_policy}",
    ]
    if ranking.comparison:
        lines.append("  admissible (ordered):")
        for e in ranking.comparison:
            dims = ", ".join(f"{k}={v.value}" for k, v in e.dimensions
                             if v.value != "NONE")
            lines.append(
                f"    {e.candidate_ref} [{e.action_type}] cost={e.cost.value} "
                f"risk={e.implementation_risk.value}/{e.dependency_risk.value}"
                + (f" dims: {dims}" if dims else ""))
    if ranking.exclusions:
        lines.append("  excluded (never ranked):")
        for e in ranking.exclusions:
            lines.append(f"    {e.candidate_ref} — {e.exclusion_reason}")
    for d in ranking.diagnostics:
        lines.append(f"  [diag {d.kind.value}] {d.detail}")
    return "\n".join(lines)

# ── Q-02: EligibleTask mode (controller ordering policy, Model B) ──
#
# The second surface of ActionEvaluation: the same DimensionLevel / CostTier
# vocabulary, the same lexicographic ordering shape, the same version triple
# and hashed/versioned result pattern — applied to the controller's
# ALREADY-eligible READY/PENDING/RETRYING set instead of candidate actions.
# It is deterministic control policy, not advice: the controller consumes the
# resulting order when claiming tasks (Q-02 design §5–§10). The pure function
# takes only code-derived facts (task state, cost_class, program obligation
# facts); no LLM input can reach it, so the forbidden chain
# (LLM → "high ROI" → hidden scheduler → execution priority) is structurally
# impossible (Q-02 §8).

TASK_ORDERING_SCHEMA_VERSION = "1"

# Documented, versioned lexicographic ordering policy (Q-02 §18.5): the
# DIMENSION_ORDER levels (NONE < LOW < MEDIUM < HIGH), then cost (LOW first,
# UNKNOWN last — AC-08), then created_at (earliest first), then task_ref
# (unique PK) — a total, deterministic order.
TASK_ORDERING_POLICY = (
    "lexicographic over: evidence_gap_closure, contradiction_reduction, "
    "rival_discrimination, replication_value, frontier_value, coverage, "
    "cost (LOW first, UNKNOWN last), created_at (earliest first), "
    "task_ref (deterministic tie-break)"
)

DEFAULT_TASK_EVALUATOR_VERSION = "1.2.0"
DEFAULT_TASK_POLICY_VERSION = "task-eval-2026.1"


class TaskDiagnosticKind(str, Enum):
    EMPTY_ELIGIBLE_SET = "EMPTY_ELIGIBLE_SET"
    DEGENERATE_TO_BASELINE = "DEGENERATE_TO_BASELINE"
    # C4 exploration floor vocabulary (ratified design gate §2.4, additive).
    # Advisory observables on the transient ranking — never gate inputs,
    # never persisted as mutable state; the durable record is the
    # FloorGrantRecorded event (design gate §4.3).
    FLOOR_GRANTED = "FLOOR_GRANTED"
    FLOOR_INERT = "FLOOR_INERT"
    FLOOR_DEGENERATE_TO_BASELINE = "FLOOR_DEGENERATE_TO_BASELINE"
    FLOOR_STAGNANT = "FLOOR_STAGNANT"
    FLOOR_ENTITLEMENT_WITHDRAWN = "FLOOR_ENTITLEMENT_WITHDRAWN"
    FLOOR_SUSPENDED = "FLOOR_SUSPENDED"
    FLOOR_READMITTED = "FLOOR_READMITTED"


class FloorStagnationMode(str, Enum):
    """The F-C decay-or-kill-switch modes (C4 design gate §2.3).

    Both modes are designed and deterministic; neither reads wall-clock
    time. ``DECAY`` withdraws the floor entitlement for a versioned
    cooldown (the forgiving reading); ``KILL_SWITCH`` suspends the
    trajectory until a NEW eligible obligation appears for one of its
    programs (the strict reading of "the floor protects exploration, not
    stagnation"). Mode selection is a versioned policy parameter.
    """

    DECAY = "decay"
    KILL_SWITCH = "kill_switch"


@dataclass(frozen=True, slots=True)
class FloorPolicy:
    """The versioned C4 floor clause parameters (design gate §4.1).

    Every parameter is version-bound: any change bumps the ordering
    policy version. ``floor_slots`` is validated against the per-tick
    call cap at construction — a violating configuration is REJECTED,
    never clamped (fail-closed, observable; AC-3). Day-one defaults:
    ``floor_slots=1`` (§7.2 flat default), ``floor_stagnation_rounds=3``,
    ``floor_decay_cooldown_rounds=2``, mode ``DECAY`` — the §7.3 open
    values, pinned as the versioned day-one choice (a team re-decision is
    a policy_version change, not a contract change).
    """

    floor_slots: int = 1
    floor_stagnation_rounds: int = 3
    floor_stagnation_mode: FloorStagnationMode = FloorStagnationMode.DECAY
    floor_decay_cooldown_rounds: int = 2

    def __post_init__(self) -> None:
        if self.floor_slots < 1:
            raise ValueError(
                "floor_slots must be >= 1 — the floor reserves at least "
                "one slot when it fires (C4 §2.1)")
        if self.floor_stagnation_rounds < 1:
            raise ValueError(
                "floor_stagnation_rounds must be >= 1 — F-C needs at "
                "least one stagnant grant before it fires (C4 §2.3)")
        if self.floor_decay_cooldown_rounds < 1:
            raise ValueError(
                "floor_decay_cooldown_rounds must be >= 1 — a decay "
                "withdrawal must last at least one round (C4 §2.3)")

    def validate_capacity(self, max_calls_per_tick: int) -> None:
        """AC-3: ``floor_slots`` is always < ``max_calls_per_tick`` — a
        configuration violating this is rejected, not clamped."""
        if self.floor_slots >= max_calls_per_tick:
            raise ValueError(
                f"floor_slots={self.floor_slots} must be < "
                f"max_calls_per_tick={max_calls_per_tick} — the floor "
                f"consumes capacity, it never expands it (C4 §2.2)")

    def policy_clause(self) -> str:
        """The floor clause appended to the TASK_ORDERING_POLICY string —
        the ordering identity reflects the floor (C4 §4.1)."""
        return (
            "exploration floor (C4): when pure policy ordering would "
            "allocate every available slot to a single "
            "trajectory and a non-leading eligible task exists, promote "
            f"the highest-policy-ranked non-leading task into the last "
            f"reserved slot; floor_slots={self.floor_slots}, "
            f"stagnation_rounds={self.floor_stagnation_rounds}, "
            f"stagnation_mode={self.floor_stagnation_mode.value}, "
            f"decay_cooldown_rounds={self.floor_decay_cooldown_rounds}; "
            "the floor reorders only — it never admits, gates, expands "
            "the call cap, or reads sunk cost")


@dataclass(frozen=True, slots=True)
class FloorEventRecord:
    """One persisted ``FloorGrantRecorded`` event row projected for the
    pure F-C derivation (C4 §4.3) — append-only facts, event_id order.

    Every floor transition (grant, stagnant, withdrawn, suspended,
    readmitted) rides this one event type; ``kind`` distinguishes them.
    ``round_index`` is the grant's position in the project's floor-grant
    sequence (the durable round vocabulary — no wall-clock reads); only
    ``FLOOR_GRANTED`` events advance it, transitions carry the round they
    occurred in.

    ``satisfaction_count`` (FLOOR_GRANTED) is the trajectory's total
    verdict-covered satisfaction-link count at grant time. Satisfaction
    links are append-only and idempotent (IDR-038 §3.1) over immutable
    artifacts, so the count is a monotone witness: a round is productive
    iff the count grew since the previous grant — no timestamp
    snapshots, no stored counter.
    """

    kind: TaskDiagnosticKind
    trajectory: str
    round_index: int
    created_at: str
    task_ref: str | None = None
    satisfaction_count: int = 0
    outstanding_obligations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FloorTransition:
    """One floor state transition the controller persists as a
    ``FloorGrantRecorded`` event (C4 §4.3 side channel).

    The pure floor function derives transitions; the controller appends
    them to the journal within the tick. ``kind`` is the §2.4 diagnostic
    vocabulary; ``detail`` is deterministic, human-readable, and carries
    no secret-bearing field names (S6 payload validation applies at the
    persistence boundary).

    ``round_index`` is the project-wide floor-grant sequence position the
    transition occurs in (grants advance it; F-C transitions carry the
    round they accompany) — the durable round vocabulary, no wall-clock
    reads. ``satisfaction_count`` is the trajectory's satisfaction-link
    row count at transition time (the monotone productivity witness).
    """

    kind: TaskDiagnosticKind
    trajectory: str
    task_ref: str | None
    slot: int | None
    detail: str
    round_index: int = 0
    counter_after: int = 0
    satisfaction_count: int = 0
    outstanding_obligations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FloorState:
    """One trajectory's derived F-C state (never stored — re-derived each
    round from the append-only floor-grant records + satisfaction links;
    C4 §2.3 F2 discipline).

    ``consecutive_unproductive`` counts completed unproductive intervals
    up to the last grant (after any readmission/withdrawal reset).
    ``readmitted_now`` signals that the kill-switch re-admission
    condition holds and no ``FLOOR_READMITTED`` has been recorded since
    the suspension — the floor function emits the transition.
    """

    trajectory: str
    consecutive_unproductive: int = 0
    in_cooldown: bool = False
    cooldown_until_grant_index: int | None = None
    halted: bool = False
    halted_outstanding: frozenset[str] = frozenset()
    readmitted_now: bool = False


@dataclass(frozen=True, slots=True)
class EligibleTask:
    """An ALREADY-eligible task the policy orders — never admits (Q-02 §6).

    The controller derives every field from stored task state and compiled
    program obligation facts — never from an LLM suggestion (Q-02 §8).
    ``created_at`` is the stored, deterministic tie-break fact (Q-02 §18.5),
    not the wall clock.
    """

    task_ref: str
    template: str
    cost_class: CostTier = CostTier.UNKNOWN
    # Dimension facts supplied from state (label + basis). Keys must be in
    # DIMENSION_ORDER; values are DimensionLevel.
    dimensions: Mapping[str, DimensionLevel] = field(default_factory=dict)
    basis_refs: tuple[str, ...] = ()
    created_at: str = ""
    # C4 §2.1: the task's gateway-validated ``research_program:<id>``
    # provenance refs — the trajectory label input (the same refs the
    # obligation derivation keys on). Empty ⇒ the trajectory label is
    # unresolvable (the floor degenerates to baseline, AC-5). Never an
    # ordering-key input — the ratified ``_task_ordering_key`` is unchanged.
    program_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EligibleTaskEvaluation:
    """One eligible task's full ordering record (never a scalar)."""

    task_ref: str
    template: str
    cost_class: CostTier
    dimensions: tuple[tuple[str, DimensionLevel], ...]  # DIMENSION_ORDER
    basis_refs: tuple[str, ...]
    created_at: str
    # C4 §2.1: the task's program provenance refs (trajectory-label input).
    # Carried for the floor only — NEVER an ordering-key input and NEVER
    # hashed into the pure-path content identity (the ratified
    # ``_task_ordering_key`` and ``_te_to_dict`` are unchanged). The
    # floor-aware wrapper folds the derived labels into its own
    # input-state so the floor-aware ranking identity reflects them (AC-4).
    program_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TaskRankingDiagnostic:
    kind: TaskDiagnosticKind
    task_ref: str | None
    detail: str


@dataclass(frozen=True, slots=True)
class EligibleTaskRanking:
    """The deterministic ordering artifact (transient, hashed, versioned).

    ``ranking_id`` is content-derived: same eligible set + same version
    triple ⇒ same identity (AC-01/AC-12). Re-derived whenever the controller claims tasks —
    never persisted, never a gate input, never a write path.

    ``floor_transitions`` is the C4 side channel: the floor state
    transitions the controller must persist as ``FloorGrantRecorded``
    events (C4 design gate §4.3) — empty when the floor was not applied.
    The ranking itself stays transient; the append-only events are the
    durable record, and the F-C stagnation counter is re-derived from
    them + the satisfaction links, never stored here.
    """

    ranking_id: str
    evaluator_version: str
    policy_version: str
    schema_version: str
    input_state_hash: str
    ordering_policy: str
    comparison: tuple[EligibleTaskEvaluation, ...]   # ordered — the policy result
    diagnostics: tuple[TaskRankingDiagnostic, ...]
    content_hash: str
    floor_transitions: tuple[FloorTransition, ...] = ()


def evaluate_eligible_tasks(
    tasks: tuple[EligibleTask, ...] | list[EligibleTask],
    *,
    evaluator_version: str = DEFAULT_TASK_EVALUATOR_VERSION,
    policy_version: str = DEFAULT_TASK_POLICY_VERSION,
    ordering_policy: str = TASK_ORDERING_POLICY,
) -> EligibleTaskRanking:
    """Deterministically order an already-eligible task set (Q-02 Model B).

    Pure: no clock, no random, no SQL, no write path, no LLM input (Q-02
    §7–§8). Same inputs + same version triple ⇒ same ordering identity.
    Tasks whose obligation facts are unresolvable carry all-NONE dimensions
    and degenerate to the created_at/task_ref tie-break — the designed
    baseline, never a heuristic fill (Q-02 §18.4).
    """
    tasks = tuple(tasks)
    if not tasks:
        return _build_task_ranking(
            tasks=tasks, evaluations=(), ordering_policy=ordering_policy,
            evaluator_version=evaluator_version, policy_version=policy_version,
            diagnostics=(TaskRankingDiagnostic(
                TaskDiagnosticKind.EMPTY_ELIGIBLE_SET, None,
                "no eligible tasks were supplied — none are admitted"),),
        )

    evaluations = [_evaluate_eligible_one(t) for t in tasks]
    ordered = sorted(evaluations, key=_task_ordering_key)

    diagnostics: list[TaskRankingDiagnostic] = []
    if all(all(v == DimensionLevel.NONE for _, v in e.dimensions)
           for e in evaluations):
        diagnostics.append(TaskRankingDiagnostic(
            TaskDiagnosticKind.DEGENERATE_TO_BASELINE, None,
            "no eligible task exposes resolvable obligation facts — the "
            "ordering degenerates to the created_at/task_ref tie-break "
            "(the designed baseline, Q-02 §18.4)"))

    return _build_task_ranking(
        tasks=tasks, evaluations=tuple(ordered),
        ordering_policy=ordering_policy,
        evaluator_version=evaluator_version, policy_version=policy_version,
        diagnostics=tuple(diagnostics),
    )


def _evaluate_eligible_one(task: EligibleTask) -> EligibleTaskEvaluation:
    dims: list[tuple[str, DimensionLevel]] = []
    for dim in DIMENSION_ORDER:
        dims.append((dim, task.dimensions.get(dim, DimensionLevel.NONE)))
    return EligibleTaskEvaluation(
        task_ref=task.task_ref,
        template=task.template,
        cost_class=task.cost_class,
        dimensions=tuple(dims),
        basis_refs=task.basis_refs,
        created_at=task.created_at,
        program_refs=task.program_refs,
    )


def _task_ordering_key(e: EligibleTaskEvaluation) -> tuple[Any, ...]:
    """The Q-02 §18.5 lexicographic ordering key (TASK_ORDERING_POLICY).

    Ascending sort over inverted ranks: HIGH dimensions first, LOW cost
    first (UNKNOWN last, AC-08), earliest created_at first, task_ref last —
    total and deterministic.
    """
    dim_key = tuple(-_DIM_LEVEL_ORDER[v] for _, v in e.dimensions)
    return dim_key + (-_COST_ORDER[e.cost_class], e.created_at, e.task_ref)


def _build_task_ranking(
    *,
    tasks: tuple[EligibleTask, ...],
    evaluations: tuple[EligibleTaskEvaluation, ...],
    ordering_policy: str,
    evaluator_version: str,
    policy_version: str,
    diagnostics: tuple[TaskRankingDiagnostic, ...],
    floor_transitions: tuple[FloorTransition, ...] = (),
    extra_input_state: Mapping[str, Any] | None = None,
) -> EligibleTaskRanking:
    input_state = {
        "task_refs": sorted(t.task_ref for t in tasks),
        "evaluator_version": evaluator_version,
        "policy_version": policy_version,
        "schema_version": TASK_ORDERING_SCHEMA_VERSION,
        "ordering_policy": ordering_policy,
    }
    # C4: the floor-aware wrapper folds its decision inputs into the input
    # state so the ordering identity reflects them (AC-4). ``None`` (the
    # pure path) adds nothing — the ratified hash is byte-identical.
    if extra_input_state:
        input_state.update(extra_input_state)
    input_state_hash = sha256_hex(canonical_json(input_state))

    body = {
        "comparison": [_te_to_dict(e) for e in evaluations],
        "diagnostics": [
            {"kind": d.kind.value, "task_ref": d.task_ref,
             "detail": d.detail} for d in diagnostics],
        "ordering_policy": ordering_policy,
        "evaluator_version": evaluator_version,
        "policy_version": policy_version,
        "schema_version": TASK_ORDERING_SCHEMA_VERSION,
        "input_state_hash": input_state_hash,
    }
    content_hash = sha256_hex(canonical_json(body))
    return EligibleTaskRanking(
        ranking_id=f"task_ord_{content_hash[:24]}",
        evaluator_version=evaluator_version,
        policy_version=policy_version,
        schema_version=TASK_ORDERING_SCHEMA_VERSION,
        input_state_hash=input_state_hash,
        ordering_policy=ordering_policy,
        comparison=evaluations,
        diagnostics=diagnostics,
        content_hash=content_hash,
        floor_transitions=floor_transitions,
    )


def _te_to_dict(e: EligibleTaskEvaluation) -> dict:
    return {
        "task_ref": e.task_ref,
        "template": e.template,
        "cost_class": e.cost_class.value,
        "dimensions": {k: v.value for k, v in e.dimensions},
        "basis_refs": list(e.basis_refs),
        "created_at": e.created_at,
    }


def summarize_task_ranking(ranking: EligibleTaskRanking) -> str:
    """Deterministic human-readable summary (Q-02 §16 — no new UI)."""
    lines = [
        f"EligibleTaskRanking {ranking.ranking_id}",
        (f"  versions: evaluator={ranking.evaluator_version} policy="
        f"{ranking.policy_version} schema={ranking.schema_version}"),
        f"  input_state_hash: {ranking.input_state_hash}",
        f"  ordering policy: {ranking.ordering_policy}",
    ]
    if ranking.comparison:
        lines.append("  ordered:")
        for e in ranking.comparison:
            dims = ", ".join(f"{k}={v.value}" for k, v in e.dimensions
                             if v.value != "NONE")
            lines.append(
                f"    {e.task_ref} [{e.template}] cost={e.cost_class.value}"
                + (f" dims: {dims}" if dims else "")
                + f" created={e.created_at}")
    for d in ranking.diagnostics:
        lines.append(f"  [diag {d.kind.value}] {d.detail}")
    return "\n".join(lines)


# ── C4: the exploration floor (ratified design gate §2–§6) ──
#
# The floor is a RESERVATION clause in the ratified Q-02 ordering policy,
# not a quota, not a second scheduler, not a scalar. It permutes the OUTPUT
# of the ratified ``_task_ordering_key`` under a documented, versioned
# constraint — the key itself is UNCHANGED (AC-9/AC-10). Pure: no clock,
# no random, no SQL, no write path, no LLM input — the same purity
# contract as ``evaluate_eligible_tasks`` (§4.2).

FLOOR_POLICY_VERSION_SUFFIX = "-floor.1"


def trajectory_label(program_refs: tuple[str, ...]) -> str | None:
    """The day-one trajectory label (C4 §2.1): the task's program
    provenance ref. Deterministic: the first SORTED ``research_program:``
    ref (``_prov_refs`` returns them sorted). ``None`` when the label is
    unresolvable (no refs) — the floor then degenerates to baseline
    (AC-5), never a guess."""
    if not program_refs:
        return None
    return sorted(program_refs)[0]


@dataclass(frozen=True, slots=True)
class FloorDecision:
    """The pure floor function's output (C4 §4.2 steps 2–9).

    ``ordered`` is the floor-permuted pure-policy order (identical to the
    pure order when the floor is inert or degenerate). ``diagnostics`` are
    the §2.4 advisory observables; ``transitions`` are the durable facts
    the controller persists as ``FloorGrantRecorded`` events (§4.3) —
    the ranking itself is transient, the events are the audit substrate.
    """

    ordered: tuple[EligibleTaskEvaluation, ...]
    diagnostics: tuple[TaskRankingDiagnostic, ...]
    transitions: tuple[FloorTransition, ...]
    granted_task_ref: str | None = None


def derive_floor_states(
    event_records: tuple[FloorEventRecord, ...],
    policy: FloorPolicy,
) -> tuple[dict[str, FloorState], int]:
    """Re-derive every trajectory's F-C state from the append-only
    ``FloorGrantRecorded`` history (C4 §2.3: the counter is a pure
    derivation, never a stored mutable counter; F2 — the derivation is
    the authority).

    Returns ``(states, grant_count)`` where ``grant_count`` is the number
    of ``FLOOR_GRANTED`` events replayed — the project-wide floor-grant
    sequence position (the durable round vocabulary; no wall-clock reads).
    Records are replayed in round_index order (the controller supplies
    event_id order); malformed records are skipped fail-closed.

    Replay semantics (mirrors the live round logic exactly):
    - the FIRST grant to a trajectory is the productivity baseline (a
      trajectory cannot be judged stagnant before it has had a chance to
      produce); a later grant is productive iff the satisfaction-link
      count grew since the previous grant (append-only links ⇒ the count
      is a monotone witness); productive resets the counter, unproductive
      increments it;
    - at ``floor_stagnation_rounds`` consecutive unproductive grants the
      configured mode fires: DECAY withdraws entitlement for
      ``floor_decay_cooldown_rounds`` further project-wide grants;
      KILL_SWITCH suspends until a NEW outstanding obligation appears (the
      re-admission rides the FLOOR_READMITTED event, which is not
      derivable from grants alone). The fire is re-derived from the
      grant's counter — the explicit WITHDRAWN / SUSPENDED events are the
      durable audit, never a second source of state (no double-apply).
    """
    states: dict[str, FloorState] = {}
    last_sat: dict[str, int] = {}
    grant_count = 0
    for rec in sorted(event_records, key=lambda r: r.round_index):
        traj = rec.trajectory
        st = states.get(traj) or FloorState(trajectory=traj)
        if rec.kind is TaskDiagnosticKind.FLOOR_GRANTED:
            # Resolve a decay-cooldown expiry BEFORE processing (the
            # trajectory re-qualifies once enough project-wide grants have
            # passed). A trajectory in cooldown receives no grants, so this
            # only matters for malformed histories; the final pass below
            # covers the well-formed case.
            if (st.in_cooldown and st.cooldown_until_grant_index is not None
                    and grant_count >= st.cooldown_until_grant_index):
                st = FloorState(trajectory=traj)
            productive = (
                traj in last_sat
                and rec.satisfaction_count > last_sat[traj])
            first = traj not in last_sat
            last_sat[traj] = rec.satisfaction_count
            grant_count += 1  # this grant is now counted project-wide
            if first or productive:
                # Baseline / productive: the counter resets. (A grant
                # implies the trajectory is not suspended; a productive
                # grant cannot occur mid-cooldown in a well-formed history.)
                st = FloorState(trajectory=traj, consecutive_unproductive=0)
            else:
                counter = st.consecutive_unproductive + 1
                if counter >= policy.floor_stagnation_rounds:
                    if (policy.floor_stagnation_mode
                            is FloorStagnationMode.DECAY):
                        st = FloorState(
                            trajectory=traj,
                            consecutive_unproductive=0,
                            in_cooldown=True,
                            cooldown_until_grant_index=(
                                grant_count
                                + policy.floor_decay_cooldown_rounds),
                        )
                    else:
                        st = FloorState(
                            trajectory=traj,
                            consecutive_unproductive=0,
                            halted=True,
                            halted_outstanding=frozenset(
                                rec.outstanding_obligations),
                        )
                else:
                    st = FloorState(
                        trajectory=traj,
                        consecutive_unproductive=counter,
                    )
        elif rec.kind is TaskDiagnosticKind.FLOOR_READMITTED:
            # Kill-switch re-admission is not derivable from grants alone —
            # it rides this event (a new eligible obligation appeared).
            st = FloorState(trajectory=traj)
        # FLOOR_ENTITLEMENT_WITHDRAWN / FLOOR_SUSPENDED / FLOOR_STAGNANT /
        # FLOOR_INERT are the durable AUDIT of transitions the grant counter
        # already implies — never a second source of state (no double-apply).
        states[traj] = st
    # Final pass: resolve any decay cooldown that expired after the last
    # recorded event (the trajectory re-qualifies).
    for traj, st in states.items():
        if (st.in_cooldown and st.cooldown_until_grant_index is not None
                and grant_count >= st.cooldown_until_grant_index):
            states[traj] = FloorState(trajectory=traj)
    return states, grant_count


def apply_exploration_floor(
    pure_ranking: EligibleTaskRanking,
    *,
    capacity: int,
    floor_policy: FloorPolicy,
    event_records: tuple[FloorEventRecord, ...] = (),
    satisfaction_counts: Mapping[str, int] | None = None,
) -> FloorDecision:
    """The C4 floor function (design gate §4.2, steps 2–9) — pure.

    Permutes the pure-policy order under the versioned reservation rule;
    never admits, gates, budgets, expands the call cap, or reads spent
    budget (§4.4). Any underivable input ⇒ pure policy stands with an
    observable diagnostic (AC-5), never a crash, never a silent skip.
    """
    ordered = pure_ranking.comparison
    counts = satisfaction_counts or {}
    if not ordered:
        return FloorDecision(ordered=ordered, diagnostics=(), transitions=())

    # Step 2: cap binding — the floor consumes capacity, never creates it.
    if capacity <= 0:
        return FloorDecision(
            ordered=ordered,
            diagnostics=(TaskRankingDiagnostic(
                TaskDiagnosticKind.FLOOR_INERT, None,
                "remaining call capacity is zero — the floor grants "
                "nothing and the tick idles on the cap (C4 §2.2)"),),
            transitions=())

    # Step 3: the leading trajectory is DERIVED from this round's pure
    # order — never stored (C4 §2.1).
    lead_label = trajectory_label(_program_refs_of(ordered[0]))
    if lead_label is None:
        return _floor_degenerate(
            ordered, "the pure-policy leader carries no resolvable "
            "trajectory label (no research_program: provenance ref) — "
            "pure policy ordering stands (C4 §2.4)")

    # The round's available slot count: the floor can only reserve within
    # the eligible set (§2.2 — min(floor-eligible, remaining capacity)).
    slots = min(len(ordered), capacity)

    # Step 4: pure policy already diversifies the top slots ⇒ inert.
    top_labels: set[str] = set()
    top_unresolvable = False
    for e in ordered[:slots]:
        lab = trajectory_label(_program_refs_of(e))
        if lab is None:
            top_unresolvable = True
        else:
            top_labels.add(lab)
    if top_unresolvable:
        return _floor_degenerate(
            ordered, "a top-slot task carries no resolvable trajectory "
            "label — pure policy ordering stands (C4 §2.4)")
    if len(top_labels) > 1:
        return FloorDecision(
            ordered=ordered,
            diagnostics=(TaskRankingDiagnostic(
                TaskDiagnosticKind.FLOOR_INERT, None,
                f"the top {slots} slots already span "
                f"{len(top_labels)} trajectories — pure policy already "
                f"diversifies (C4 §4.2 step 4)"),),
            transitions=())
    if len(ordered) < capacity:
        # Fewer eligible tasks than slots: no monopoly of the available
        # capacity exists — the floor has nothing to bound.
        return FloorDecision(
            ordered=ordered,
            diagnostics=(TaskRankingDiagnostic(
                TaskDiagnosticKind.FLOOR_INERT, None,
                f"only {len(ordered)} eligible task(s) for {capacity} "
                "slot(s) — no monopoly to bound (C4 §2.1)"),),
            transitions=())

    # F-C state: re-derived from the append-only history, never stored.
    states, grant_count = derive_floor_states(event_records, floor_policy)

    # Outstanding obligation facts per trajectory — the same pure facts
    # the ordering reads (basis_refs cite outstanding obligations only).
    outstanding: dict[str, set[str]] = {}
    labels_by_ref: dict[str, str] = {}
    for e in ordered:
        lab = trajectory_label(_program_refs_of(e))
        if lab is None:
            continue
        labels_by_ref[e.task_ref] = lab
        outstanding.setdefault(lab, set()).update(e.basis_refs)

    transitions: list[FloorTransition] = []
    diagnostics: list[TaskRankingDiagnostic] = []

    # Kill-switch re-admission (AC-8): automatic and deterministic the
    # round a NEW eligible obligation appears — no human, no agent.
    if (floor_policy.floor_stagnation_mode
            is FloorStagnationMode.KILL_SWITCH):
        for traj in sorted(states):
            st = states[traj]
            if not st.halted:
                continue
            current = outstanding.get(traj, set())
            if current - st.halted_outstanding:
                transitions.append(FloorTransition(
                    kind=TaskDiagnosticKind.FLOOR_READMITTED,
                    trajectory=traj, task_ref=None, slot=None,
                    detail=("a new eligible obligation appeared for a "
                            "halted trajectory — automatic "
                            "re-admission (C4 §2.3 kill-switch)"),
                    round_index=grant_count,
                    outstanding_obligations=tuple(sorted(current)),
                ))
                diagnostics.append(TaskRankingDiagnostic(
                    TaskDiagnosticKind.FLOOR_READMITTED, None,
                    f"trajectory {traj} re-admitted to the floor"))
                states[traj] = FloorState(trajectory=traj)

    # Step 5: non-leading candidates, excluding F-C-suspended/cooldown.
    candidates = []
    for e in ordered:
        lab = labels_by_ref.get(e.task_ref)
        if lab is None or lab == lead_label:
            continue
        st = states.get(lab)
        if st is not None and (st.halted or st.in_cooldown):
            continue
        candidates.append(e)
    if not candidates:
        return FloorDecision(
            ordered=ordered,
            diagnostics=(TaskRankingDiagnostic(
                TaskDiagnosticKind.FLOOR_INERT, None,
                "no non-leading eligible task is floor-eligible (all "
                "are F-C halted/in cooldown, or none exist) — pure "
                "policy stands (C4 §4.2 step 6)"),),
            transitions=tuple(transitions))

    # Step 7: promote the highest-policy-ranked non-leading task into the
    # LAST available slot; the leader keeps the top slots−1 in pure order.
    promoted = candidates[0]
    rest = [e for e in ordered if e.task_ref != promoted.task_ref]
    new_order = tuple(rest[:slots - 1]) + (promoted,) + tuple(rest[slots - 1:])
    promoted_label = labels_by_ref[promoted.task_ref]
    slot_index = slots - 1

    # Step 8: the F-C counter update — a pure derivation from the grant
    # history + the satisfaction-link count (the monotone witness).
    st = states.get(promoted_label) or FloorState(trajectory=promoted_label)
    sat_count = counts.get(promoted_label, 0)
    prev_sat: int | None = None
    for rec in event_records:
        if (rec.kind is TaskDiagnosticKind.FLOOR_GRANTED
                and rec.trajectory == promoted_label):
            prev_sat = rec.satisfaction_count
    productive = prev_sat is not None and sat_count > prev_sat
    counter = 0 if (prev_sat is None or productive) else (
        st.consecutive_unproductive + 1)

    transitions.append(FloorTransition(
        kind=TaskDiagnosticKind.FLOOR_GRANTED,
        trajectory=promoted_label,
        task_ref=promoted.task_ref,
        slot=slot_index,
        detail=(f"floor slot {slot_index} reserved for the "
                f"highest-policy-ranked non-leading task "
                f"(leader {lead_label} keeps slots 0..{slot_index - 1})"),
        round_index=grant_count,
        counter_after=counter,
        satisfaction_count=sat_count,
        outstanding_obligations=tuple(
            sorted(outstanding.get(promoted_label, set()))),
    ))
    diagnostics.append(TaskRankingDiagnostic(
        TaskDiagnosticKind.FLOOR_GRANTED, promoted.task_ref,
        f"trajectory {promoted_label} promoted into slot {slot_index}"))

    if counter > 0:
        diagnostics.append(TaskRankingDiagnostic(
            TaskDiagnosticKind.FLOOR_STAGNANT, promoted.task_ref,
            f"trajectory {promoted_label}: {counter} consecutive "
            f"unproductive floor grant(s) (F-C threshold "
            f"{floor_policy.floor_stagnation_rounds})"))
    if counter >= floor_policy.floor_stagnation_rounds:
        if (floor_policy.floor_stagnation_mode
                is FloorStagnationMode.DECAY):
            transitions.append(FloorTransition(
                kind=TaskDiagnosticKind.FLOOR_ENTITLEMENT_WITHDRAWN,
                trajectory=promoted_label,
                task_ref=promoted.task_ref, slot=None,
                detail=(f"{counter} consecutive unproductive grants — "
                        f"floor entitlement withdrawn for "
                        f"{floor_policy.floor_decay_cooldown_rounds} "
                        f"grant round(s) (C4 §2.3 decay)"),
                round_index=grant_count,
                counter_after=counter,
                satisfaction_count=sat_count,
            ))
            diagnostics.append(TaskRankingDiagnostic(
                TaskDiagnosticKind.FLOOR_ENTITLEMENT_WITHDRAWN,
                promoted.task_ref,
                f"trajectory {promoted_label} floor entitlement "
                f"withdrawn (decay cooldown)"))
        else:
            transitions.append(FloorTransition(
                kind=TaskDiagnosticKind.FLOOR_SUSPENDED,
                trajectory=promoted_label,
                task_ref=promoted.task_ref, slot=None,
                detail=(f"{counter} consecutive unproductive grants — "
                        f"halted from the floor until a new eligible "
                        f"obligation appears (C4 §2.3 kill-switch)"),
                round_index=grant_count,
                counter_after=counter,
                satisfaction_count=sat_count,
                outstanding_obligations=tuple(
                    sorted(outstanding.get(promoted_label, set()))),
            ))
            diagnostics.append(TaskRankingDiagnostic(
                TaskDiagnosticKind.FLOOR_SUSPENDED, promoted.task_ref,
                f"trajectory {promoted_label} halted from the floor"))

    return FloorDecision(
        ordered=new_order,
        diagnostics=tuple(diagnostics),
        transitions=tuple(transitions),
        granted_task_ref=promoted.task_ref,
    )


def _program_refs_of(e: EligibleTaskEvaluation) -> tuple[str, ...]:
    """The trajectory-label input carried by an ordered evaluation (C4
    §2.1): the task's own gateway-validated ``research_program:`` refs,
    propagated from ``EligibleTask.program_refs``. NOT the basis_refs —
    those cite only OUTSTANDING obligations, so an all-satisfied task
    would lose its label. Never an ordering-key input."""
    return tuple(sorted(
        r for r in e.program_refs if r.startswith("research_program:")))


def _floor_degenerate(
    ordered: tuple[EligibleTaskEvaluation, ...],
    detail: str,
) -> FloorDecision:
    """AC-5: underivable floor input ⇒ pure policy stands, observable."""
    return FloorDecision(
        ordered=ordered,
        diagnostics=(TaskRankingDiagnostic(
            TaskDiagnosticKind.FLOOR_DEGENERATE_TO_BASELINE, None,
            detail),),
        transitions=())


def evaluate_eligible_tasks_with_floor(
    tasks: tuple[EligibleTask, ...] | list[EligibleTask],
    *,
    capacity: int,
    floor_policy: FloorPolicy | None = None,
    event_records: tuple[FloorEventRecord, ...] = (),
    satisfaction_counts: Mapping[str, int] | None = None,
    evaluator_version: str = DEFAULT_TASK_EVALUATOR_VERSION,
    policy_version: str = DEFAULT_TASK_POLICY_VERSION,
) -> EligibleTaskRanking:
    """The floor-aware wrapper (C4 §5.1): calls the ratified pure ordering
    FIRST, then applies §4.2 steps 2–9 to its output. It EXTENDS
    ``evaluate_eligible_tasks``; it does not replace the ratified ordering
    key (unchanged — AC-9).

    The floor clause amends the ``TASK_ORDERING_POLICY`` string and the
    policy version (``-floor.1`` suffix), so the ordering identity
    reflects the floor (C4 §4.1): same inputs + same version triple +
    same derived facts ⇒ same ``ranking_id`` and same floor decision,
    independent of replay order or schedule (AC-4).
    """
    policy = floor_policy or FloorPolicy()
    floor_policy_version = policy_version + FLOOR_POLICY_VERSION_SUFFIX
    floor_ordering_policy = (
        TASK_ORDERING_POLICY + "; " + policy.policy_clause())
    pure = evaluate_eligible_tasks(
        tasks,
        evaluator_version=evaluator_version,
        policy_version=floor_policy_version,
        ordering_policy=floor_ordering_policy,
    )
    decision = apply_exploration_floor(
        pure,
        capacity=capacity,
        floor_policy=policy,
        event_records=event_records,
        satisfaction_counts=satisfaction_counts,
    )
    extra_input_state = {
        "floor_capacity": capacity,
        "floor_slots": policy.floor_slots,
        "floor_stagnation_rounds": policy.floor_stagnation_rounds,
        "floor_stagnation_mode": policy.floor_stagnation_mode.value,
        "floor_decay_cooldown_rounds": policy.floor_decay_cooldown_rounds,
        "floor_history": [
            {"kind": r.kind.value, "trajectory": r.trajectory,
             "round_index": r.round_index,
             "satisfaction_count": r.satisfaction_count,
             "outstanding_obligations": list(r.outstanding_obligations)}
            for r in sorted(event_records, key=lambda r: r.round_index)],
        "floor_satisfaction_counts": dict(satisfaction_counts or {}),
    }
    return _build_task_ranking(
        tasks=tuple(tasks),
        evaluations=decision.ordered,
        ordering_policy=floor_ordering_policy,
        evaluator_version=evaluator_version,
        policy_version=floor_policy_version,
        diagnostics=pure.diagnostics + decision.diagnostics,
        floor_transitions=decision.transitions,
        extra_input_state=extra_input_state,
    )

