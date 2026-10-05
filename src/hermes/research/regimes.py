"""IDR-044 (Step 4 / S-R1) — the regime-axis registry substrate.

The claims path has dereference-assumed a versioned regime axis since the
P7 substrate (``claims.py``: ``regime`` ∈ ``CONTEXT_DIMENSIONS`` and
``DEREFERENCE_DIMENSIONS``, tag form ``ICSS-v1:low-vol``), and the
failure-classification path has deferred it fail-closed (IDR-037 D5:
``persistence/failure_classifications.py`` refuses ``ENVIRONMENT_MISMATCH``
"until the regime axis (ICSS-v1) lands"; ``repositories.py`` records the
``regime`` tag as form-checked-only, ``DEREFERENCE_DEFERRED``;
``programs.py`` validates ``target_regime`` as a free string). This module
lands the FIRST implementable piece of that axis: a pure, deterministic,
stdlib-only registry of versioned regime definitions — no wiring, no writes,
no persistence, no events, no model calls, and no behavior change to any
existing module (the ``target_regime`` wiring is S-R2/R4).

Non-negotiables (structural properties of this module, not rules):

- **Closed registry.** ``REGISTRY`` is a ``frozenset`` seeded with exactly
  the ICSS-v1 axis entries the live tree already assumes — verified, never
  invented. Today that is exactly one entry (``low-vol`` under ``ICSS-v1``);
  adding an entry is a deliberate change to this module and its fixtures.
- **Versioned references.** A regime is referenced as ``RegimeRef(id,
  version)`` in the live tag form ``VERSION:id``. A bare/unversioned form
  refuses (``UNVERSIONED_REGIME``); an unregistered (version, id) pair
  refuses (``UNREGISTERED_REGIME``) — fail-closed, never a guess.
- **Classification-time snapshots only.** ``RegimeSnapshot`` exposes ONLY
  the ``FalsificationRecord`` field set plus the claim context present at
  classification. Post-outcome fields are structurally unrepresentable —
  the snapshot cannot carry what did not exist when the classification ran.
- **Deterministic membership.** Same (definition, snapshot) ⇒ identical
  evaluation, every call. No clock, no randomness, no model.
- **Decision-inertness.** The verdict vocabulary is a closed three-member
  enum (``IN_REGIME`` / ``NOT_IN_REGIME`` / ``INDETERMINATE``) with no
  free-text reason field; an INDETERMINATE evaluation submitted as
  authority refuses. The registry classifies; it never decides a
  transition (determinism owns control).

Step 4 / S-R2 adds the transition layer: a classified regime resolution
(``RegimeTransition``) whose response is RE-DERIVED from the registry +
snapshot via ``derive_transition`` — a caller-supplied evaluation is never
consumed (C1, S-R1 audit condition C1 / F-3 / A2 precedent). A resolved
response is cited (non-empty ``evidence_refs``); INDETERMINATE stays
decision-inert (no evidence may attach; refuses as authority). Every
transition carries the statically-typed ``Literal["SIMULATED"]``
provenance — simulated, never a live regime determination.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Literal, cast

__all__ = [
    "REGIME_CONTEXT_KEY",
    "REGISTRY",
    "REGISTRY_TAXONOMY_VERSION",
    "Predicate",
    "RegimeDefinition",
    "RegimeEvaluation",
    "RegimeRef",
    "RegimeResolutionError",
    "RegimeSnapshot",
    "RegimeVerdict",
    "TransitionProvenance",
    "TransitionResponse",
    "authoritative_transition",
    "authoritative_verdict",
    "derive_transition",
    "evaluate_regime",
    "parse_regime_ref",
    "resolve_regime",
]

# The live dereference dimension (claims.py CONTEXT/DEREFERENCE_DIMENSIONS):
# the one claim-context key a regime definition may read from a snapshot.
REGIME_CONTEXT_KEY = "regime"

# The ratified day-one taxonomy version (v3/v6 §27: ICSS-v1 structural-break
# axis, recorded via ``regime_taxonomy_version`` on spec and manifest).
REGISTRY_TAXONOMY_VERSION = "ICSS-v1"

# Ref separator — the live tag form is ``VERSION:id`` (``ICSS-v1:low-vol``).
REF_SEP = ":"


class RegimeResolutionError(ValueError):
    """A fail-closed refusal with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


# ── versioned reference type ──


@dataclass(frozen=True, slots=True)
class RegimeRef:
    """A versioned regime reference: ``RegimeRef(id, version)``.

    The canonical external tag form is ``VERSION:id`` (``ICSS-v1:low-vol``),
    the exact form the claims path already form-checks and dereference-stubs.
    """

    id: str
    version: str

    def __post_init__(self) -> None:
        for name in ("id", "version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise RegimeResolutionError(
                    "UNVERSIONED_REGIME",
                    f"RegimeRef.{name} must be a non-empty, unpadded string; "
                    f"got {value!r}")
        if REF_SEP in self.id:
            raise RegimeResolutionError(
                "UNVERSIONED_REGIME",
                f"RegimeRef.id must not contain the separator {REF_SEP!r}; "
                f"got {self.id!r}")

    @property
    def tag(self) -> str:
        """The canonical external tag form: ``VERSION:id``."""
        return f"{self.version}{REF_SEP}{self.id}"


def parse_regime_ref(raw: str) -> RegimeRef:
    """Parse the live tag form ``VERSION:id`` into a ``RegimeRef``.

    A bare id (no version), an empty side, or extra separators refuse with
    ``UNVERSIONED_REGIME`` — a regime is never referenced without its
    version (identity is version-scoped; determinism lives within a
    version).
    """
    if not isinstance(raw, str):
        raise RegimeResolutionError(
            "UNVERSIONED_REGIME", f"regime ref must be a string; got {raw!r}")
    version, sep, regime_id = raw.partition(REF_SEP)
    if (not sep or not version.strip() or not regime_id.strip()
            or version != version.strip() or regime_id != regime_id.strip()
            or REF_SEP in regime_id):
        raise RegimeResolutionError(
            "UNVERSIONED_REGIME",
            f"regime ref must have the form VERSION{REF_SEP}id "
            f"(a bare/unversioned ref is refused); got {raw!r}")
    return RegimeRef(id=regime_id, version=version)


# ── classification-time snapshot ──


def _canonical_tags(
    raw: Mapping[str, str] | Iterable[tuple[str, str]],
) -> tuple[tuple[str, str], ...]:
    """Canonical (deterministic) form of the claim context: sorted pairs."""
    if isinstance(raw, str):
        # A bare string is neither a mapping nor pairs — refuse (C2/F-2):
        # silently unpacking it would corrupt the citation channel.
        raise RegimeResolutionError(
            "MALFORMED_REGIME_CONTEXT",
            "claim_context_tags must be a mapping or (str, str) pairs, not "
            f"a bare string; got {raw!r}")
    # (the runtime isinstance check is what makes the cast sound)
    items = cast(
        "Iterable[Sequence[object]]",
        raw.items() if isinstance(raw, Mapping) else raw,
    )
    pairs: list[tuple[str, str]] = []
    for item in items:
        if (not isinstance(item, (tuple, list)) or len(item) != 2
                or not isinstance(item[0], str) or not isinstance(item[1], str)):
            raise RegimeResolutionError(
                "MALFORMED_REGIME_CONTEXT",
                "claim context tags must be (str, str) pairs; got "
                f"{item!r}")
        pairs.append((item[0], item[1]))
    return tuple(sorted(pairs))


@dataclass(frozen=True, slots=True)
class RegimeSnapshot:
    """The classification-time world a regime predicate may observe.

    ONLY the ``FalsificationRecord`` field set (project, hypothesis,
    program, falsifying evidence) plus the claim context present at
    classification. Deliberately NO outcome fields: a post-outcome fact
    (falsified flag, observed return, realized volatility after the fact)
    has no field to live in — constructing the attempt raises ``TypeError``
    (slots), so the snapshot cannot smuggle hindsight into membership.
    """

    project_id: str
    hypothesis_ref: str
    program_ref: str
    falsifying_evidence_refs: tuple[str, ...] = ()
    claim_context_tags: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        refs_in = self.falsifying_evidence_refs
        if isinstance(refs_in, str):
            # C2/F-1: a bare string is not a ref sequence — refusing (rather
            # than silently char-splitting it into individual characters)
            # keeps the evidence channel typed.
            raise RegimeResolutionError(
                "MALFORMED_EVIDENCE_REFS",
                "falsifying_evidence_refs must be a sequence of evidence-ref "
                f"strings, not a bare string; got {refs_in!r}")
        refs = tuple(refs_in)
        if any(not isinstance(r, str) or not r for r in refs):
            raise RegimeResolutionError(
                "MALFORMED_EVIDENCE_REFS",
                "falsifying_evidence_refs must contain only non-empty "
                f"strings; got {refs!r}")
        tags = _canonical_tags(self.claim_context_tags)
        # Deterministic canonical form, frozen in place.
        object.__setattr__(self, "falsifying_evidence_refs", refs)
        object.__setattr__(self, "claim_context_tags", tags)


# ── closed verdict vocabulary (no free-text reason, ever) ──


class RegimeVerdict(str, Enum):
    """The closed membership-verdict vocabulary (closed enum, no reasons).

    ``INDETERMINATE`` is the honest fallback when the snapshot declares no
    regime at all (mirrors ``ConditionType.UNDETERMINED`` /
    ``FailureClass.UNKNOWN`` discipline) — it carries no free-text reason
    and is refused when submitted as authority (decision-inertness).
    """

    IN_REGIME = "IN_REGIME"
    NOT_IN_REGIME = "NOT_IN_REGIME"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True, slots=True)
class RegimeEvaluation:
    """The deterministic result of evaluating a ref against a snapshot.

    Identity is exactly (ref, verdict) — there is no free-text reason field
    by construction, so an INDETERMINATE cannot grow a rationale.
    """

    ref: RegimeRef
    verdict: RegimeVerdict


def authoritative_verdict(evaluation: RegimeEvaluation) -> RegimeVerdict:
    """Accept an evaluation as decision input — INDETERMINATE refuses.

    The registry's outputs are classification metadata, never decisions;
    the one verdict that may never act as authority is INDETERMINATE (a
    non-answer). Resolved verdicts pass through unchanged.
    """
    if evaluation.verdict is RegimeVerdict.INDETERMINATE:
        raise RegimeResolutionError(
            "INDETERMINATE_NOT_AUTHORITY",
            f"the INDETERMINATE evaluation of {evaluation.ref.tag!r} cannot "
            "be submitted as authority — resolve the regime declaration "
            "first (decision-inertness)")
    return evaluation.verdict


# ── versioned definitions + closed registry ──


Predicate = Callable[[RegimeSnapshot], bool]


@dataclass(frozen=True, slots=True, eq=False)
class RegimeDefinition:
    """A versioned regime axis entry.

    Identity is (``regime_id``, ``version``) ONLY — ``notes`` and the
    predicate are excluded from equality and hash, so a definition is the
    same definition however its annotation or implementation is worded,
    and the ``frozenset`` registry dedupes on the versioned identity.

    ``predicate`` is a pure deterministic function of a ``RegimeSnapshot``;
    it must read no other source (no clock, no filesystem, no model).
    """

    regime_id: str
    version: str
    predicate: Predicate
    notes: str = ""

    def __post_init__(self) -> None:
        ref = RegimeRef(id=self.regime_id, version=self.version)
        if not callable(self.predicate):
            raise RegimeResolutionError(
                "MALFORMED_REGIME_DEFINITION",
                f"the predicate of {ref.tag!r} must be callable")
        if not isinstance(self.notes, str):
            raise RegimeResolutionError(
                "MALFORMED_REGIME_DEFINITION",
                f"the notes of {ref.tag!r} must be a string")

    @property
    def ref(self) -> RegimeRef:
        return RegimeRef(id=self.regime_id, version=self.version)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RegimeDefinition):
            return NotImplemented
        return (self.regime_id == other.regime_id
                and self.version == other.version)

    def __hash__(self) -> int:
        return hash((self.regime_id, self.version))


def _low_vol_predicate(snapshot: RegimeSnapshot) -> bool:
    """Deterministic membership for the ``ICSS-v1:low-vol`` entry.

    The only classification-time signal the live tree carries for a regime
    is the claim context's declared ``regime`` tag (the claims-path tag
    form ``ICSS-v1:low-vol``). The predicate compares the declared tag to
    this entry's canonical tag — nothing else, no derived or post-outcome
    data (none is representable in the snapshot).
    """
    tags = dict(snapshot.claim_context_tags)
    return tags.get(REGIME_CONTEXT_KEY) == RegimeRef(
        id="low-vol", version=REGISTRY_TAXONOMY_VERSION).tag


# The closed registry — seeded ONLY with the ICSS-v1 axis entries the live
# tree already assumes (verified against claims.py CONTEXT/DEREFERENCE
# dimensions + the claims fixtures' resolver stub; the failure-classification
# path's DEFERRED regime resolver; nothing invented). Exactly one entry.
REGISTRY: frozenset[RegimeDefinition] = frozenset({
    RegimeDefinition(
        regime_id="low-vol",
        version=REGISTRY_TAXONOMY_VERSION,
        predicate=_low_vol_predicate,
        notes=(
            "ICSS-v1 structural-break axis entry, the one regime value the "
            "live claims path already assumes (tag form 'ICSS-v1:low-vol'; "
            "claims.py CONTEXT/DEREFERENCE_DIMENSIONS; the P7 fixtures' "
            "regime resolver stub). Seed-verified against live assumptions; "
            "no entry is invented. Wiring (target_regime, the deferred "
            "regime resolver) is S-R2/R4 — NOT this substrate."
        ),
    ),
})


def resolve_regime(ref: RegimeRef) -> RegimeDefinition:
    """Resolve a versioned ref against the closed registry (fail-closed).

    An unregistered (version, id) pair refuses with ``UNREGISTERED_REGIME``
    — including a known id under an unknown version (identity is the pair).
    """
    for definition in REGISTRY:
        if definition.regime_id == ref.id and definition.version == ref.version:
            return definition
    raise RegimeResolutionError(
        "UNREGISTERED_REGIME",
        f"regime {ref.tag!r} is not in the closed registry — a regime is "
        "only ever referenced by a registered (version, id) pair")


def evaluate_regime(
    ref: RegimeRef | str, snapshot: RegimeSnapshot
) -> RegimeEvaluation:
    """Deterministic membership evaluation (pure; no hidden inputs).

    Resolution refuses first (``UNREGISTERED_REGIME`` for an unregistered
    pair, ``UNVERSIONED_REGIME`` for a bare/unversioned string form). Then:

    - the claim context declares no ``regime`` tag ⇒ ``INDETERMINATE``
      (nothing declared — the honest fallback, never a guess);
    - otherwise the definition's own predicate decides
      ``IN_REGIME``/``NOT_IN_REGIME`` deterministically.

    Same (ref, snapshot) ⇒ the same ``RegimeEvaluation``, every call.
    """
    parsed = parse_regime_ref(ref) if isinstance(ref, str) else ref
    definition = resolve_regime(parsed)
    declared = dict(snapshot.claim_context_tags).get(REGIME_CONTEXT_KEY)
    if declared is None:
        return RegimeEvaluation(ref=parsed, verdict=RegimeVerdict.INDETERMINATE)
    if definition.predicate(snapshot):
        return RegimeEvaluation(ref=parsed, verdict=RegimeVerdict.IN_REGIME)
    return RegimeEvaluation(ref=parsed, verdict=RegimeVerdict.NOT_IN_REGIME)


# ── transitions (Step 4 / S-R2) ──


class TransitionResponse(str, Enum):
    """The closed transition-response vocabulary — mirrors ``RegimeVerdict``.

    Same closed three members, no free-text reason, ever.
    """

    IN_REGIME = "IN_REGIME"
    NOT_IN_REGIME = "NOT_IN_REGIME"
    INDETERMINATE = "INDETERMINATE"


# The ONLY provenance a transition may carry, statically typed. The entire
# substrate is deterministic; a transition is simulated, never a live regime
# determination. Omitting or mistagging it refuses (below).
TransitionProvenance = Literal["SIMULATED"]

_TRANSITION_PROVENANCE_VALUE = "SIMULATED"


def _typed_refs(
    raw: Sequence[str], code: str, subject: str
) -> tuple[str, ...]:
    """Typed-input hardening (S-R1 audit C2/F-1 pattern) for ref sequences."""
    if isinstance(raw, (str, bytes)):
        raise RegimeResolutionError(
            code,
            f"{subject} must be a sequence of ref strings, not a bare "
            f"string (char-split coercion would corrupt the channel); "
            f"got {raw!r}")
    try:
        refs = tuple(raw)
    except TypeError:
        raise RegimeResolutionError(
            code,
            f"{subject} must be a sequence of ref strings; "
            f"got {raw!r}") from None
    if any(not isinstance(r, str) or not r for r in refs):
        raise RegimeResolutionError(
            code,
            f"{subject} must contain only non-empty strings; got {refs!r}")
    return refs


@dataclass(frozen=True, slots=True)
class RegimeTransition:
    """A classified regime resolution (Step 4 / S-R2) — advisory metadata.

    Shape (charter): the (id, regime_ref) pairs -- here a single versioned
    ``RegimeRef`` -- plus ``timestamp``, ``program_ref``, ``hypothesis_ref``,
    the closed ``TransitionResponse``, ``evidence_refs``, and the
    ``Literal["SIMULATED"]`` provenance (required; omission and mistag both
    refuse). Construction rules:

    - the regime must be a REGISTERED (version, id) pair — a transition
      about an unregistered regime is meaningless (``UNREGISTERED_REGIME``);
    - citation rule: resolved responses REQUIRE non-empty ``evidence_refs``
      (``TRANSITION_EVIDENCE_REQUIRED``); the INDETERMINATE response is
      decision-inert — it carries no evidence and refuses any (EXTRANEOUS
      evidence refuses, ``EXTRANEOUS_TRANSITION_EVIDENCE``);
    - ``provenance`` is required with no default: omitting it is a
      ``TypeError`` at construction, and any value other than "SIMULATED"
      refuses (``INVALID_TRANSITION_PROVENANCE``) — an omission is not
      admitted with a default and a tag is not silently correctable;
    - ref sequences are typed (no bare-string coercion, C2).

    Only ``derive_transition`` output is authoritative: it re-derives the
    response from the registry + snapshot (C1, S-R1 audit condition C1 /
    F-3 / A2 precedent — a caller-supplied response or evaluation is never
    consumed). S-R4 consumers must re-derive, never trust.
    """

    regime: RegimeRef
    timestamp: str
    program_ref: str
    hypothesis_ref: str
    response: TransitionResponse
    provenance: str
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, str):
            raise RegimeResolutionError(
                "INVALID_TRANSITION_PROVENANCE",
                f"provenance must be the literal 'SIMULATED'; got "
                f"{self.provenance!r}")
        if self.provenance != _TRANSITION_PROVENANCE_VALUE:
            raise RegimeResolutionError(
                "INVALID_TRANSITION_PROVENANCE",
                f"provenance must be the literal 'SIMULATED'; got "
                f"{self.provenance!r} — a transition is simulated, never "
                "a live regime determination")
        if (not isinstance(self.timestamp, str) or not self.timestamp.strip()):
            raise RegimeResolutionError(
                "MALFORMED_TRANSITION",
                f"timestamp must be a non-empty string; got "
                f"{self.timestamp!r}")
        for name in ("program_ref", "hypothesis_ref"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise RegimeResolutionError(
                    "MALFORMED_TRANSITION",
                    f"{name} must be a non-empty string; got {value!r}")
        if not isinstance(self.response, TransitionResponse):
            raise RegimeResolutionError(
                "MALFORMED_TRANSITION",
                f"response must be a closed TransitionResponse member; "
                f"got {self.response!r}")
        resolve_regime(self.regime)  # registered pair only
        refs = _typed_refs(self.evidence_refs, "MALFORMED_EVIDENCE_REFS",
                           "evidence_refs")
        if self.response is TransitionResponse.INDETERMINATE:
            # Decision-inert: no evidence may attach to a non-answer.
            if refs:
                raise RegimeResolutionError(
                    "EXTRANEOUS_TRANSITION_EVIDENCE",
                    "the INDETERMINATE transition is decision-inert — it "
                    f"carries no evidence; got {refs!r}")
        elif not refs:
            raise RegimeResolutionError(
                "TRANSITION_EVIDENCE_REQUIRED",
                f"the {self.response.value} transition of "
                f"{self.regime.tag!r} requires non-empty evidence_refs — "
                "resolved responses are cited, not asserted")
        object.__setattr__(self, "evidence_refs", refs)


def derive_transition(
    regime: RegimeRef | str,
    snapshot: RegimeSnapshot,
    *,
    timestamp: str,
    program_ref: str,
    hypothesis_ref: str,
    evidence_refs: Sequence[str] = (),
) -> RegimeTransition:
    """The C1-safe production path for transitions.

    The response is RE-DERIVED from the registry + snapshot via
    ``evaluate_regime`` — a caller-supplied evaluation or response is not
    an input (nothing to forge; the S-R1 audit's forged-evaluation attack
    dies here by construction). Resolution/refusal semantics are exactly
    ``evaluate_regime``'s; the provenance is hard-coded "SIMULATED".

    Citation rule: callers must cite the evidence behind a resolved
    response (``TRANSITION_EVIDENCE_REQUIRED`` otherwise); the honest
    INDETERMINATE fallback takes no evidence (decision-inert, EXTRANEOUS
    evidence refuses).
    """
    evaluation = evaluate_regime(regime, snapshot)
    return RegimeTransition(
        regime=evaluation.ref,
        timestamp=timestamp,
        program_ref=program_ref,
        hypothesis_ref=hypothesis_ref,
        response=TransitionResponse(evaluation.verdict.value),
        provenance=_TRANSITION_PROVENANCE_VALUE,
        evidence_refs=tuple(evidence_refs),
    )


def authoritative_transition(transition: RegimeTransition) -> TransitionResponse:
    """Accept a transition as decision input — INDETERMINATE refuses.

    Decision-inertness for the transition layer, mirroring
    ``authoritative_verdict``: the one response that may never act as
    authority is INDETERMINATE (a non-answer); resolved responses pass
    through unchanged.
    """
    if transition.response is TransitionResponse.INDETERMINATE:
        raise RegimeResolutionError(
            "INDETERMINATE_NOT_AUTHORITY",
            f"the INDETERMINATE transition of {transition.regime.tag!r} "
            "cannot be submitted as authority — resolve the regime "
            "declaration first (decision-inertness)")
    return transition.response
