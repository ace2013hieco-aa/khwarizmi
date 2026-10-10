"""Advisory candidate ranking plane (O5 — NEW, not wired).

Clean-room re-derivation of a tool-ranker *behaviour* only — no vendored
code, standard library only. Provenance: ``ADOPTION_AUDIT_R2.md`` §4
rejected the "Jev" ranker as an authority because its decision is a
host-supplied model evaluator behind a probability threshold
(``tinytools@8e5008c:crates/tinytools-jev/src/lib.rs:1-4``,
``src/types.rs:82``) — that violates the no-scalar discipline
(``src/hermes/research/evaluation.py:11``) and admits a model where no
model may decide. What survives here is the advisory residue: a
deterministic, code-derived, **lexicographic** ranking of
already-admissible candidates, exposed as advice — never a decision.
The published "22.5%→62%" / "26→1" figures are struck
(``ADOPTION_AUDIT_R2.md`` §0: "They are not evidence."); the only
savings this plane claims are the ones its own fixtures measure.

ADVISORY ONLY (the Q-02 precedent, ``evaluation.py``):

- **Inputs are code-derived facts.** Every field of
  :class:`CandidateFacts` is a stored/derived fact a program computes
  (registry capability match, scope match, grant state, declared cost /
  risk tier, append-only outcome counts). There is no LLM score, no
  probability, no heuristic, and no float anywhere in the ordering key.
- **No scalar-threshold decisions.** There is no score to compare
  against a cutoff: the order is a documented, versioned lexicographic
  policy over closed-vocabulary levels (mirroring
  ``TASK_ORDERING_POLICY``), and the Choice/Score/None classification is
  derived from *set equality* on the decisive key — never from a numeric
  threshold.
- **Eligibility is not this plane's to change.** ``admissible`` is the
  caller's authority (the eligibility gate's decision), read as an input
  fact. An inadmissible candidate is classified ``NONE``, excluded from
  the ordering, and can never be resurrected by a better fact profile.
  The plane reorders only the already-admissible set (Q-02 §6); it never
  reorders eligibility.
- **Ties break deterministically and never manufacture a choice.** The
  ordering key ends in ``candidate_ref`` (content-derived identity), so
  the order is total and input-order-invariant. ``CHOICE`` is asserted
  only when one candidate *strictly* dominates every other on the
  decisive key; when the decisive maximum is shared the classifier emits
  ``SCORE`` for the tied head plus a ``NO_DECISIVE_CHOICE`` diagnostic —
  it refuses to invent a decision the facts do not support.
- **No write path, no persistence, no network, no clock, no random.**
  The module is pure: same facts + same version triple ⇒ identical
  ranking identity (``ranking_id``), across processes and input
  orderings.
- **Every public output carries its policy binding.** The classifier
  result, the ranking artifact, and the harness result all record the
  version triple and the ordering policy they were produced under
  (:class:`PolicyBinding`), and a blank version string is refused: an
  output that cannot name its ranker/policy/schema is not re-derivable
  (the O5_REDTEAM P2 closure).

The Choice/Score/None classifier (:func:`classify_candidate_set`) over
tool/candidate sets:

- ``CHOICE`` — the unique strict-winner candidate;
- ``SCORE`` — a comparable, ranked alternative (no strict advantage);
- ``NONE`` — inadmissible: not this plane's to rank.

The measurement harness (:func:`compare_against_baseline`) reports
calls-saved on a supplied fixture task set. The baseline policy is "try
the candidates in the order presented"; the ranker's policy is "try them
in ranked order"; both count the 1-based position of the single candidate
that satisfies the task. A negative ``calls_saved`` is reported as
measured — the harness is a measurement, not a claim.

Refusals use the FROZEN vocabulary only (mirrored, never extended):

- ``MALFORMED_PAYLOAD`` (``research/gateway.py:110``) — a malformed
  candidate set: not iterable, empty, a non-fact member, a
  ``candidate_ref`` that is blank or outside the ref grammar (a
  whole-string identifier, so a trailing space or newline is never part
  of an identity), a duplicate ``candidate_ref``, a negative outcome
  count or one past the renderable payload magnitude, an out-of-vocabulary
  level, a blank version string, or a bad envelope budget;
- ``RATIONALE`` (``research/controller.py:1803``) — the facts envelope
  exceeds the bounded-payload discipline; the detail names sizes only,
  never content (the PS3-07 discipline).

Integration: NOT wired in this slice. The later tool-phase wiring point
is named by :data:`RANKING_INTEGRATION_POINT` and nothing else;
``tests/test_ranking_plane.py`` pins that no module outside this plane
and its own test references it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from hermes.research.programs import canonical_json, sha256_hex

__all__ = [
    "DEFAULT_RANKER_VERSION",
    "DEFAULT_RANKING_POLICY_VERSION",
    "FACT_DIMENSION_ORDER",
    "FROZEN_RANKING_REFUSAL_CODES",
    "MALFORMED_PAYLOAD",
    "MAX_FACTS_ENVELOPE_BYTES",
    "RANKING_INTEGRATION_POINT",
    "RANKING_POLICY",
    "RANKING_SCHEMA_VERSION",
    "CandidateClass",
    "CandidateFacts",
    "CandidateJudgment",
    "CandidateRankingArtifact",
    "CandidateSetClassification",
    "ClassificationReason",
    "CostTier",
    "FixtureTask",
    "GrantState",
    "MatchLevel",
    "PolicyBinding",
    "RankingComparison",
    "RankingDiagnostic",
    "RankingDiagnosticKind",
    "RankingRefusal",
    "RiskTier",
    "TaskComparison",
    "candidate_set_envelope_bytes",
    "classify_candidate_set",
    "compare_against_baseline",
    "decisive_key",
    "ordering_key",
    "rank_candidates",
    "summarize_comparison",
    "summarize_ranking",
]

# ── artifact schema + versions (recorded on every ranking) ──

RANKING_SCHEMA_VERSION = "1"
DEFAULT_RANKER_VERSION = "1.0.0"
DEFAULT_RANKING_POLICY_VERSION = "tool-rank-2026.1"

#: The later gate's wiring point (the R4 tool phase;
#: ``agents/runtime/run.py`` model call site). Name only — NOT wired here.
RANKING_INTEGRATION_POINT = "hermes.agents.runtime.run:tool-phase"

#: Default facts-envelope bound: the 4 KiB bounded-payload discipline
#: (``persistence/event_validation.py`` ``DEFAULT_PAYLOAD_MAX_BYTES`` —
#: cited, not imported, so this module stays stdlib-only;
#: ``tests/test_ranking_plane.py`` pins the equality).
MAX_FACTS_ENVELOPE_BYTES = 4096

#: Documented, versioned lexicographic ordering policy. Not a weighted
#: score: a stable, auditable dimension order with ``candidate_ref`` as
#: the deterministic tie-break and ``UNKNOWN`` always last.
RANKING_POLICY = (
    "lexicographic over: capability_match (EXACT first), scope_match "
    "(EXACT first), grant_state (GRANTED first, UNKNOWN last), cost_tier "
    "(LOW first, UNKNOWN last), risk_tier (LOW first), observed_successes "
    "(higher first), observed_failures (lower first), candidate_ref "
    "(deterministic tie-break)"
)

#: The decisive dimensions, in policy order (the tie-break is separate).
FACT_DIMENSION_ORDER = (
    "capability_match",
    "scope_match",
    "grant_state",
    "cost_tier",
    "risk_tier",
    "observed_successes",
    "observed_failures",
)

# ── frozen refusal vocabulary (mirrored, never extended) ──

#: Schema violation or unknown key — research/gateway.py:110.
MALFORMED_PAYLOAD = "MALFORMED_PAYLOAD"

# NOTE: no module-level RATIONALE binding on purpose. The controller owns
# the literal (controller.py:1803 emits it inline); this plane names it in
# the frozen set and emits the string where needed (the O4 precedent).
FROZEN_RANKING_REFUSAL_CODES: frozenset[str] = frozenset(
    {MALFORMED_PAYLOAD, "RATIONALE"}
)


class RankingRefusal(Exception):
    """Fail-closed refusal carrying a FROZEN code (never a new code)."""

    def __init__(self, code: str, detail: str) -> None:
        if code not in FROZEN_RANKING_REFUSAL_CODES:
            raise ValueError(f"unknown ranking refusal code {code!r}")
        self.code = code
        self.detail = detail
        super().__init__(f"ranking refused ({code}): {detail}")

    def to_refusal(self) -> dict[str, object]:
        """The refusal-as-data shape (``rejected`` / ``code`` / ``detail``)."""
        return {"rejected": True, "code": self.code, "detail": self.detail}


# ── the policy binding every public output carries ──


@dataclass(frozen=True, slots=True)
class PolicyBinding:
    """The version triple + ordering-policy string a public output carries.

    Every public output of this plane records the policy it was produced
    under, so the output can be re-derived and audited against the policy
    that made it. A blank version string is refused: an output that cannot
    name its ranker/policy/schema is exactly the gap this type closes (the
    O5_REDTEAM P2 finding on the classifier surface).
    """

    ranker_version: str = DEFAULT_RANKER_VERSION
    policy_version: str = DEFAULT_RANKING_POLICY_VERSION
    schema_version: str = RANKING_SCHEMA_VERSION
    ordering_policy: str = RANKING_POLICY

    def __post_init__(self) -> None:
        for name, part in (
            ("ranker_version", self.ranker_version),
            ("policy_version", self.policy_version),
            ("schema_version", self.schema_version),
            ("ordering_policy", self.ordering_policy),
        ):
            if not isinstance(part, str) or not part.strip():
                raise RankingRefusal(
                    MALFORMED_PAYLOAD,
                    f"{name} must be a non-blank version string — an "
                    "unversioned output is not re-derivable",
                )


# ── closed fact vocabulary (descriptive levels, never values to spend) ──


class MatchLevel(str, Enum):
    """How well a declared capability/scope matches the request."""

    NONE = "NONE"
    PARTIAL = "PARTIAL"
    EXACT = "EXACT"


class GrantState(str, Enum):
    """The caller's grant fact; ``UNKNOWN`` is never treated as GRANTED."""

    UNKNOWN = "UNKNOWN"
    NOT_GRANTED = "NOT_GRANTED"
    GRANTED = "GRANTED"


class CostTier(str, Enum):
    """Declared cost tier (descriptive; ``UNKNOWN`` sorts last)."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class RiskTier(str, Enum):
    """Declared risk tier (lower risk ranks first)."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class CandidateClass(str, Enum):
    """The Choice/Score/None classifier's closed labels."""

    CHOICE = "CHOICE"
    SCORE = "SCORE"
    NONE = "NONE"


class ClassificationReason(str, Enum):
    """Why a candidate carries its label (frozen, auditable)."""

    STRICT_WINNER = "STRICT_WINNER"
    RANKED_ALTERNATIVE = "RANKED_ALTERNATIVE"
    INADMISSIBLE = "INADMISSIBLE"


class RankingDiagnosticKind(str, Enum):
    """Advisory observables (never gate inputs, never persisted)."""

    NO_ADMISSIBLE_CANDIDATE = "NO_ADMISSIBLE_CANDIDATE"
    NO_DECISIVE_CHOICE = "NO_DECISIVE_CHOICE"


# Ascending sort over inverted ranks: better facts first. UNKNOWN is the
# lowest rank on every dimension that has it, so it always sorts last.
_MATCH_RANK: dict[MatchLevel, int] = {
    MatchLevel.NONE: 0,
    MatchLevel.PARTIAL: 1,
    MatchLevel.EXACT: 2,
}
_GRANT_RANK: dict[GrantState, int] = {
    GrantState.UNKNOWN: 0,
    GrantState.NOT_GRANTED: 1,
    GrantState.GRANTED: 2,
}
_COST_RANK: dict[CostTier, int] = {
    CostTier.UNKNOWN: 0,
    CostTier.HIGH: 1,
    CostTier.MEDIUM: 2,
    CostTier.LOW: 3,
}
_RISK_RANK: dict[RiskTier, int] = {
    RiskTier.HIGH: 0,
    RiskTier.MEDIUM: 1,
    RiskTier.LOW: 2,
}


# ── inputs: code-derived facts only ──


@dataclass(frozen=True, slots=True)
class CandidateFacts:
    """One candidate's code-derived fact profile (never a score).

    ``admissible`` is the caller's eligibility decision, read as an input;
    the plane never writes it. Defaults are the fail-closed worst case so
    a caller must opt in to every favourable fact. ``observed_successes``
    / ``observed_failures`` are append-only history counts (integers, not
    ratios — no division, no threshold anywhere).
    """

    candidate_ref: str
    admissible: bool
    capability_match: MatchLevel = MatchLevel.NONE
    scope_match: MatchLevel = MatchLevel.NONE
    grant_state: GrantState = GrantState.UNKNOWN
    cost_tier: CostTier = CostTier.UNKNOWN
    risk_tier: RiskTier = RiskTier.HIGH
    observed_successes: int = 0
    observed_failures: int = 0

    def __post_init__(self) -> None:
        _require_ref(self.candidate_ref)
        _require_level("capability_match", self.capability_match, MatchLevel)
        _require_level("scope_match", self.scope_match, MatchLevel)
        _require_level("grant_state", self.grant_state, GrantState)
        _require_level("cost_tier", self.cost_tier, CostTier)
        _require_level("risk_tier", self.risk_tier, RiskTier)
        _require_count("observed_successes", self.observed_successes)
        _require_count("observed_failures", self.observed_failures)


#: The candidate-ref grammar: a whole-string identifier, ``\A``/``\Z``
#: anchored so a trailing newline (or any other whitespace) is never part
#: of an identity — the shared identifier lesson, and never ``$``. Mirrors
#: the shared ref family (``research/programs.py`` ``_REF_RE``). Refs are
#: echoed into public outputs, so a label outside the grammar refuses
#: instead of aliasing a cleaner neighbour (O5_REDTEAM 3f).
_REF_GRAMMAR = re.compile(r"\A[A-Za-z0-9_.:-]+\Z")

#: A count must render inside the bounded payload: the envelope's digit
#: budget. CPython refuses ``int``-to-``str`` past
#: ``sys.int_info.default_max_str_digits`` (4300), so a pathological tally
#: would escape the frozen vocabulary as a raw ``ValueError`` inside
#: ``canonical_json`` (O5_REDTEAM 3e). A renderability bound, never a merit
#: bound — it cannot promote, demote, or rank anything.
_MAX_COUNT_DIGITS = MAX_FACTS_ENVELOPE_BYTES
_MAX_COUNT = 10 ** _MAX_COUNT_DIGITS


def _require_ref(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise RankingRefusal(
            MALFORMED_PAYLOAD, "candidate_ref must be a non-blank string"
        )
    if _REF_GRAMMAR.match(value) is None:
        raise RankingRefusal(
            MALFORMED_PAYLOAD,
            "candidate_ref must be a whole-string identifier matching "
            "[A-Za-z0-9_.:-]+ (no trailing newline, no whitespace) — "
            "refs are echoed into public outputs, so a label outside the "
            "grammar (whitespace, control characters, punctuation) refuses "
            "instead of aliasing a cleaner neighbour",
        )


def _require_level(name: str, value: object, level: type[Enum]) -> None:
    if not isinstance(value, level):
        raise RankingRefusal(
            MALFORMED_PAYLOAD, f"{name} is not a {level.__name__} level"
        )


def _require_count(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RankingRefusal(
            MALFORMED_PAYLOAD, f"{name} must be a non-negative integer"
        )
    if value >= _MAX_COUNT:
        raise RankingRefusal(
            MALFORMED_PAYLOAD,
            f"{name} is past the renderable payload magnitude "
            f"(10^{_MAX_COUNT_DIGITS}) — the count is echoed into the facts "
            "envelope, so it must render inside the bounded payload",
        )


# ── outputs: judgments, diagnostics, classification, ranking ──


@dataclass(frozen=True, slots=True)
class CandidateJudgment:
    """One candidate's advisory classification (auditable, never a scalar)."""

    candidate_ref: str
    classification: CandidateClass
    reason: ClassificationReason
    rank: int | None
    facts: CandidateFacts


@dataclass(frozen=True, slots=True)
class RankingDiagnostic:
    kind: RankingDiagnosticKind
    detail: str


@dataclass(frozen=True, slots=True)
class CandidateSetClassification:
    """The classifier's output: labels over a candidate set (advisory).

    Carries its :class:`PolicyBinding`, so this public surface is
    re-derivable exactly like the ranking artifact — no public output of
    this plane is unversioned (the O5_REDTEAM P2 closure).
    """

    binding: PolicyBinding
    ordered_refs: tuple[str, ...]
    ranking: tuple[CandidateJudgment, ...]
    excluded: tuple[CandidateJudgment, ...]
    choice_ref: str | None
    diagnostics: tuple[RankingDiagnostic, ...]

    def classifications(self) -> tuple[tuple[str, str], ...]:
        """``(candidate_ref, label)`` rows in canonical order."""
        return tuple(
            (j.candidate_ref, j.classification.value)
            for j in (*self.ranking, *self.excluded)
        )


@dataclass(frozen=True, slots=True)
class CandidateRankingArtifact:
    """The versioned, hashed ranking artifact (transient, never persisted).

    ``ranking_id`` is content-derived: same facts + same version triple ⇒
    same identity, re-derivable on demand (the IDR-019 ``CandidateRanking``
    / ``EligibleTaskRanking`` artifact pattern in
    :mod:`hermes.research.evaluation` — this plane's artifact carries a
    distinct name so a bare ``CandidateRanking`` never has two meanings).
    Never a gate input, never a write path — the ``ranking``/``excluded``
    tuples are the full comparison record so a reader can see exactly why
    one candidate precedes another.
    """

    ranking_id: str
    ranker_version: str
    policy_version: str
    schema_version: str
    input_state_hash: str
    ordering_policy: str
    ranking: tuple[CandidateJudgment, ...]
    excluded: tuple[CandidateJudgment, ...]
    choice_ref: str | None
    diagnostics: tuple[RankingDiagnostic, ...]
    content_hash: str


# ── the ordering key (lexicographic, no scalars) ──


def decisive_key(facts: CandidateFacts) -> tuple[int, ...]:
    """The lexicographic key over the decisive dimensions (RANKING_POLICY).

    Ascending over inverted ranks: better facts first, worse last;
    ``UNKNOWN`` cost/grant always sort last. No float, no weight, no
    threshold — every term is a small integer from a closed vocabulary.
    """
    return (
        -_MATCH_RANK[facts.capability_match],
        -_MATCH_RANK[facts.scope_match],
        -_GRANT_RANK[facts.grant_state],
        -_COST_RANK[facts.cost_tier],
        -_RISK_RANK[facts.risk_tier],
        -facts.observed_successes,
        facts.observed_failures,
    )


def ordering_key(facts: CandidateFacts) -> tuple[int | str, ...]:
    """The total ordering key: decisive dimensions then ``candidate_ref``."""
    return (*decisive_key(facts), facts.candidate_ref)


# ── validation (fail-closed, frozen vocabulary) ──


def _facts_to_dict(facts: CandidateFacts) -> dict[str, Any]:
    return {
        "candidate_ref": facts.candidate_ref,
        "admissible": facts.admissible,
        "capability_match": facts.capability_match.value,
        "scope_match": facts.scope_match.value,
        "grant_state": facts.grant_state.value,
        "cost_tier": facts.cost_tier.value,
        "risk_tier": facts.risk_tier.value,
        "observed_successes": facts.observed_successes,
        "observed_failures": facts.observed_failures,
    }


def _judgment_to_dict(judgment: CandidateJudgment) -> dict[str, Any]:
    return {
        "candidate_ref": judgment.candidate_ref,
        "classification": judgment.classification.value,
        "reason": judgment.reason.value,
        "rank": judgment.rank,
        "facts": _facts_to_dict(judgment.facts),
    }


def _canonical_candidates(
    candidates: Iterable[CandidateFacts],
) -> tuple[CandidateFacts, ...]:
    """Validate membership and canonicalize (ref-sorted, deduplicated)."""
    try:
        items = tuple(candidates)
    except TypeError:
        raise RankingRefusal(
            MALFORMED_PAYLOAD, "the candidate set is not iterable"
        ) from None
    if not items:
        raise RankingRefusal(
            MALFORMED_PAYLOAD,
            "the candidate set is empty — there is nothing to rank",
        )
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, CandidateFacts):
            raise RankingRefusal(
                MALFORMED_PAYLOAD,
                "a candidate set member is not a CandidateFacts record",
            )
        if item.candidate_ref in seen:
            raise RankingRefusal(
                MALFORMED_PAYLOAD,
                "the candidate set carries a duplicate candidate_ref",
            )
        seen.add(item.candidate_ref)
    return tuple(sorted(items, key=lambda f: f.candidate_ref))


def _envelope_size(facts: tuple[CandidateFacts, ...]) -> int:
    return len(canonical_json([_facts_to_dict(f) for f in facts]).encode("utf-8"))


def candidate_set_envelope_bytes(candidates: Iterable[CandidateFacts]) -> int:
    """The canonical facts-envelope size in bytes (the RATIONALE gate's input).

    Public so a caller can measure before ranking; the bound itself is
    applied by :func:`rank_candidates` / :func:`classify_candidate_set`.
    Raises :class:`RankingRefusal` if the set is malformed.
    """
    return _envelope_size(_canonical_candidates(candidates))


def _validate_candidate_set(
    candidates: Iterable[CandidateFacts],
    *,
    max_envelope_bytes: int,
) -> tuple[CandidateFacts, ...]:
    """Schema-validate a candidate set and apply the facts-envelope bound."""
    if (
        isinstance(max_envelope_bytes, bool)
        or not isinstance(max_envelope_bytes, int)
        or max_envelope_bytes <= 0
    ):
        raise RankingRefusal(
            MALFORMED_PAYLOAD, "the envelope budget must be a positive integer"
        )
    facts = _canonical_candidates(candidates)
    size = _envelope_size(facts)
    if size > max_envelope_bytes:
        # Sizes only — never content (the controller's RATIONALE shape).
        raise RankingRefusal(
            "RATIONALE",
            f"the facts envelope is {size} bytes, over the "
            f"{max_envelope_bytes}-byte bounded-payload discipline",
        )
    return facts


# ── the Choice/Score/None classifier ──


def _decide(
    facts: tuple[CandidateFacts, ...], *, binding: PolicyBinding
) -> CandidateSetClassification:
    """Classify an already-validated (ref-sorted) candidate set."""
    admissible = tuple(f for f in facts if f.admissible)
    inadmissible = tuple(f for f in facts if not f.admissible)
    excluded = tuple(
        CandidateJudgment(
            candidate_ref=f.candidate_ref,
            classification=CandidateClass.NONE,
            reason=ClassificationReason.INADMISSIBLE,
            rank=None,
            facts=f,
        )
        for f in inadmissible
    )

    if not admissible:
        return CandidateSetClassification(
            binding=binding,
            ordered_refs=(),
            ranking=(),
            excluded=excluded,
            choice_ref=None,
            diagnostics=(
                RankingDiagnostic(
                    RankingDiagnosticKind.NO_ADMISSIBLE_CANDIDATE,
                    "no candidate in the set is admissible — admissibility "
                    "is the caller's authority and the plane ranks nothing",
                ),
            ),
        )

    ordered = sorted(admissible, key=ordering_key)
    strict_winner = (
        len(ordered) == 1
        or decisive_key(ordered[1]) != decisive_key(ordered[0])
    )
    choice_ref = ordered[0].candidate_ref if strict_winner else None
    diagnostics: list[RankingDiagnostic] = []
    if not strict_winner:
        diagnostics.append(
            RankingDiagnostic(
                RankingDiagnosticKind.NO_DECISIVE_CHOICE,
                "the decisive key is shared by the leading candidates — "
                "they are ordered by candidate_ref only, and no CHOICE is "
                "asserted (the facts do not support a decision)",
            )
        )

    ranking: list[CandidateJudgment] = []
    for position, candidate in enumerate(ordered, start=1):
        if strict_winner and position == 1:
            classification = CandidateClass.CHOICE
            reason = ClassificationReason.STRICT_WINNER
        else:
            classification = CandidateClass.SCORE
            reason = ClassificationReason.RANKED_ALTERNATIVE
        ranking.append(
            CandidateJudgment(
                candidate_ref=candidate.candidate_ref,
                classification=classification,
                reason=reason,
                rank=position,
                facts=candidate,
            )
        )
    return CandidateSetClassification(
        binding=binding,
        ordered_refs=tuple(j.candidate_ref for j in ranking),
        ranking=tuple(ranking),
        excluded=excluded,
        choice_ref=choice_ref,
        diagnostics=tuple(diagnostics),
    )


def classify_candidate_set(
    candidates: Iterable[CandidateFacts],
    *,
    ranker_version: str = DEFAULT_RANKER_VERSION,
    policy_version: str = DEFAULT_RANKING_POLICY_VERSION,
    ordering_policy: str = RANKING_POLICY,
    max_envelope_bytes: int = MAX_FACTS_ENVELOPE_BYTES,
) -> CandidateSetClassification:
    """Classify a tool/candidate set as CHOICE / SCORE / NONE (advisory).

    Pure and input-order-invariant: the set is canonicalized by
    ``candidate_ref`` before any decision, so the same membership yields
    the same labels regardless of how it was presented. The result carries
    the :class:`PolicyBinding` it was produced under — the same version
    triple :func:`rank_candidates` records — so no public output is
    unversioned. Raises :class:`RankingRefusal` for a malformed set.
    """
    facts = _validate_candidate_set(
        candidates, max_envelope_bytes=max_envelope_bytes
    )
    binding = PolicyBinding(
        ranker_version=ranker_version,
        policy_version=policy_version,
        schema_version=RANKING_SCHEMA_VERSION,
        ordering_policy=ordering_policy,
    )
    return _decide(facts, binding=binding)


def rank_candidates(
    candidates: Iterable[CandidateFacts],
    *,
    ranker_version: str = DEFAULT_RANKER_VERSION,
    policy_version: str = DEFAULT_RANKING_POLICY_VERSION,
    ordering_policy: str = RANKING_POLICY,
    max_envelope_bytes: int = MAX_FACTS_ENVELOPE_BYTES,
) -> CandidateRankingArtifact:
    """Rank an already-admissible candidate set into a versioned artifact.

    Pure: same facts + same version triple ⇒ identical ``ranking_id``.
    The version triple and the ordering-policy string are recorded on the
    artifact. Never a decision, never a gate input, never persisted.
    """
    facts = _validate_candidate_set(
        candidates, max_envelope_bytes=max_envelope_bytes
    )
    binding = PolicyBinding(
        ranker_version=ranker_version,
        policy_version=policy_version,
        schema_version=RANKING_SCHEMA_VERSION,
        ordering_policy=ordering_policy,
    )
    classification = _decide(facts, binding=binding)

    input_state = {
        "candidate_refs": [f.candidate_ref for f in facts],
        "ranker_version": binding.ranker_version,
        "policy_version": binding.policy_version,
        "schema_version": binding.schema_version,
        "ordering_policy": binding.ordering_policy,
    }
    input_state_hash = sha256_hex(canonical_json(input_state))

    body = {
        "ranking": [_judgment_to_dict(j) for j in classification.ranking],
        "excluded": [_judgment_to_dict(j) for j in classification.excluded],
        "choice_ref": classification.choice_ref,
        "diagnostics": [
            {"kind": d.kind.value, "detail": d.detail}
            for d in classification.diagnostics
        ],
        "ranker_version": binding.ranker_version,
        "policy_version": binding.policy_version,
        "schema_version": binding.schema_version,
        "ordering_policy": binding.ordering_policy,
        "input_state_hash": input_state_hash,
    }
    content_hash = sha256_hex(canonical_json(body))
    return CandidateRankingArtifact(
        ranking_id=f"rank_{content_hash[:24]}",
        ranker_version=binding.ranker_version,
        policy_version=binding.policy_version,
        schema_version=binding.schema_version,
        input_state_hash=input_state_hash,
        ordering_policy=ordering_policy,
        ranking=classification.ranking,
        excluded=classification.excluded,
        choice_ref=classification.choice_ref,
        diagnostics=classification.diagnostics,
        content_hash=content_hash,
    )


def summarize_ranking(ranking: CandidateRankingArtifact) -> str:
    """Deterministic human-readable summary (no new UI)."""
    lines = [
        f"CandidateRankingArtifact {ranking.ranking_id}",
        (
            f"  versions: ranker={ranking.ranker_version} policy="
            f"{ranking.policy_version} schema={ranking.schema_version}"
        ),
        f"  input_state_hash: {ranking.input_state_hash}",
        f"  ordering policy: {ranking.ordering_policy}",
    ]
    if ranking.choice_ref is None:
        lines.append("  choice: none (no strict winner on the decisive key)")
    else:
        lines.append(f"  choice: {ranking.choice_ref}")
    for judgment in ranking.ranking:
        lines.append(
            f"    {judgment.rank}. {judgment.candidate_ref} "
            f"[{judgment.classification.value}] capability="
            f"{judgment.facts.capability_match.value} cost="
            f"{judgment.facts.cost_tier.value}"
        )
    for judgment in ranking.excluded:
        lines.append(
            f"    excluded {judgment.candidate_ref} "
            f"[{judgment.classification.value}] ({judgment.reason.value})"
        )
    for diagnostic in ranking.diagnostics:
        lines.append(f"  [diag {diagnostic.kind.value}] {diagnostic.detail}")
    return "\n".join(lines)


# ── measurement harness: calls-saved on a fixture task set ──


@dataclass(frozen=True, slots=True)
class FixtureTask:
    """One pinned fixture task for the measurement harness.

    ``candidates`` is the set *in the order it was presented* — that
    presented order is the baseline policy ("try them in the order
    given"). ``success_ref`` names the single candidate that satisfies the
    task (the fixture's ground truth). A fixture whose ``success_ref`` is
    not an admissible candidate is refused: its ground truth would
    contradict the authority's eligibility decision.
    """

    task_ref: str
    candidates: tuple[CandidateFacts, ...]
    success_ref: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class TaskComparison:
    """One fixture task's baseline-vs-ranker call counts."""

    task_ref: str
    note: str
    baseline_order: tuple[str, ...]
    ranked_order: tuple[str, ...]
    baseline_calls: int
    ranked_calls: int
    calls_saved: int
    choice_ref: str | None
    classifications: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class RankingComparison:
    """The harness result over a fixture task set (measured, not claimed)."""

    comparison_id: str
    fixture_set_version: str
    ranker_version: str
    policy_version: str
    schema_version: str
    tasks: tuple[TaskComparison, ...]
    total_baseline_calls: int
    total_ranked_calls: int
    total_calls_saved: int
    content_hash: str


def _task_comparison_to_dict(row: TaskComparison) -> dict[str, Any]:
    return {
        "task_ref": row.task_ref,
        "note": row.note,
        "baseline_order": list(row.baseline_order),
        "ranked_order": list(row.ranked_order),
        "baseline_calls": row.baseline_calls,
        "ranked_calls": row.ranked_calls,
        "calls_saved": row.calls_saved,
        "choice_ref": row.choice_ref,
        "classifications": [list(pair) for pair in row.classifications],
    }


def compare_against_baseline(
    fixtures: Iterable[FixtureTask],
    *,
    fixture_set_version: str = "1",
    ranker_version: str = DEFAULT_RANKER_VERSION,
    policy_version: str = DEFAULT_RANKING_POLICY_VERSION,
) -> RankingComparison:
    """Measure calls-saved: presented order (baseline) vs ranked order.

    For each fixture task, the baseline tries the candidates in the order
    presented and the ranker tries them in ranked order; each count is the
    1-based position of ``success_ref`` in that order. ``calls_saved`` is
    reported as measured and may be negative — the harness measures, it
    does not flatter. Raises :class:`RankingRefusal` for a malformed
    fixture task set.
    """
    try:
        tasks = tuple(fixtures)
    except TypeError:
        raise RankingRefusal(
            MALFORMED_PAYLOAD, "the fixture task set is not iterable"
        ) from None
    if not tasks:
        raise RankingRefusal(
            MALFORMED_PAYLOAD, "the fixture task set is empty"
        )

    rows: list[TaskComparison] = []
    for task in tasks:
        if not isinstance(task, FixtureTask):
            raise RankingRefusal(
                MALFORMED_PAYLOAD,
                "a fixture task set member is not a FixtureTask record",
            )
        ranking = rank_candidates(
            task.candidates,
            ranker_version=ranker_version,
            policy_version=policy_version,
        )
        admitted = {
            facts.candidate_ref for facts in task.candidates if facts.admissible
        }
        if task.success_ref not in admitted:
            raise RankingRefusal(
                MALFORMED_PAYLOAD,
                "a fixture success_ref is not an admissible candidate in "
                "its task set",
            )
        baseline_order = tuple(f.candidate_ref for f in task.candidates)
        ranked_order = tuple(j.candidate_ref for j in ranking.ranking)
        baseline_calls = baseline_order.index(task.success_ref) + 1
        ranked_calls = ranked_order.index(task.success_ref) + 1
        rows.append(
            TaskComparison(
                task_ref=task.task_ref,
                note=task.note,
                baseline_order=baseline_order,
                ranked_order=ranked_order,
                baseline_calls=baseline_calls,
                ranked_calls=ranked_calls,
                calls_saved=baseline_calls - ranked_calls,
                choice_ref=ranking.choice_ref,
                classifications=tuple(
                    (j.candidate_ref, j.classification.value)
                    for j in (*ranking.ranking, *ranking.excluded)
                ),
            )
        )

    total_baseline = sum(r.baseline_calls for r in rows)
    total_ranked = sum(r.ranked_calls for r in rows)
    body = {
        "fixture_set_version": fixture_set_version,
        "ranker_version": ranker_version,
        "policy_version": policy_version,
        "schema_version": RANKING_SCHEMA_VERSION,
        "tasks": [_task_comparison_to_dict(r) for r in rows],
        "total_baseline_calls": total_baseline,
        "total_ranked_calls": total_ranked,
        "total_calls_saved": total_baseline - total_ranked,
    }
    content_hash = sha256_hex(canonical_json(body))
    return RankingComparison(
        comparison_id=f"rankcmp_{content_hash[:24]}",
        fixture_set_version=fixture_set_version,
        ranker_version=ranker_version,
        policy_version=policy_version,
        schema_version=RANKING_SCHEMA_VERSION,
        tasks=tuple(rows),
        total_baseline_calls=total_baseline,
        total_ranked_calls=total_ranked,
        total_calls_saved=total_baseline - total_ranked,
        content_hash=content_hash,
    )


def summarize_comparison(comparison: RankingComparison) -> str:
    """Deterministic savings table (task, baseline, ranked, saved)."""
    lines = [
        f"RankingComparison {comparison.comparison_id}",
        (
            f"  versions: ranker={comparison.ranker_version} policy="
            f"{comparison.policy_version} schema={comparison.schema_version}"
        ),
        "  shape                          baseline ranked saved",
    ]
    for row in comparison.tasks:
        lines.append(
            f"  {row.task_ref:<30} {row.baseline_calls:>8} "
            f"{row.ranked_calls:>6} {row.calls_saved:>5}"
        )
    lines.append(
        f"  {'TOTAL':<30} {comparison.total_baseline_calls:>8} "
        f"{comparison.total_ranked_calls:>6} {comparison.total_calls_saved:>5}"
    )
    return "\n".join(lines)
