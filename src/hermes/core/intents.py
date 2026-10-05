"""Typed intents (v4 §8) — the only vocabulary of state mutation.

Every effect on research state is a typed ``Intent`` validated by a single
deterministic ``apply_intent`` gateway. There is no second write path (v4 §2
principle 2). ``ADMIT_TASK`` is internal-only — never LLM-proposable.

Phase 1: the intent *types* are defined for forward compatibility, but the
gateway itself (apply_intent) lands in P3 (deterministic runtime). Phase 1
uses the repository's direct transition methods, which are the persistence
implementation of the same validation logic the gateway will use.

HR-03 closure: the proposable set is exactly the wired set. ``CONTRADICTION_``
``RESOLUTION`` was declared-but-deferred (§19 machinery is agent-runtime
scope); CHG-1 wires it as internal-only (deterministic ingestion of a
ratified human verdict — never LLM-proposable, never Director-proposed).
``RECORD_CONTRADICTION`` is likewise internal-only (deterministic
derived-state admission).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class IntentKind(str, Enum):
    """v4 §8 intent kinds.

    LLM-proposable kinds are listed first; ``ADMIT_TASK`` is internal-only
    (scheduler / reconciling pass — never LLM-proposable, v4 §8).
    ``CONTRADICTION_RESOLUTION`` is wired (CHG-1) as internal-only —
    deterministic ingestion of a ratified human verdict — and
    ``RECORD_CONTRADICTION`` records deterministic detection. Neither is
    proposable (HR-03 closure — see the enum member comment).
    ``RECORD_CLASSIFICATION`` records an operator-asserted failure
    classification (P6 — judgment authorship is the operator's).
    """

    # LLM-proposable
    INSERT_TASK = "INSERT_TASK"
    BRANCH = "BRANCH"
    ABANDON = "ABANDON"
    EVIDENCE_TRANSITION = "EVIDENCE_TRANSITION"
    REQUEST_HUMAN = "REQUEST_HUMAN"
    REQUEST_REPLICATION = "REQUEST_REPLICATION"
    REQUEST_ADDITIONAL_EXPERIMENT = "REQUEST_ADDITIONAL_EXPERIMENT"
    PROPOSE_GATE_OVERRIDE = "PROPOSE_GATE_OVERRIDE"
    # CHG-1: contradiction recording — a deterministic derived-state
    # admission (detection over admitted classifications). Internal-only:
    # detectors propose pairs, the deterministic layer records through
    # this intent (never LLM-proposable — an LLM must not assert
    # contradictions directly). Idempotent by deterministic
    # contradiction ID.
    RECORD_CONTRADICTION = "RECORD_CONTRADICTION"
    # CHG-1 wiring: internal-only (DETERMINISTIC ingestion of a ratified
    # human verdict through the record_contradiction_resolution
    # precedent — IDR-040 §3). Never LLM-proposable, never
    # Director-proposed: resolution authority is human verdict only.
    # (HR-03 history: this kind was declared-but-deferred until the
    # contradiction record substrate it resolves landed.)
    CONTRADICTION_RESOLUTION = "CONTRADICTION_RESOLUTION"
    # P6: the deterministic layer records an operator-asserted failure
    # classification through this intent (the record_operator_decision
    # precedent, IDR-040 §3 — judgment authorship is the operator's;
    # the substrate re-validates everything deterministically).
    # Internal-only (the human has no agent profile). Never
    # LLM-proposable: an LLM must not assert classifications directly.
    RECORD_CLASSIFICATION = "RECORD_CLASSIFICATION"
    # Approved architecture (IDR-018): the Director proposes a schema'd
    # ResearchProgram draft; the deterministic ResearchProgramValidator
    # (research/programs.py) checks it. Never a compiler service — the
    # program is a proposal artifact admitted through this gateway only.
    PROPOSE_RESEARCH_PROGRAM = "PROPOSE_RESEARCH_PROGRAM"
    # IDR-040: the Director PROPOSES a Q-05 permitted action for a
    # re-review candidate. Proposal-only — the action is never
    # executed here; acting still requires the existing authority
    # (ABANDON / EVIDENCE_TRANSITION / PROPOSE_RESEARCH_PROGRAM /
    # S16 human amendment). The admission is the audit record.
    PROPOSE_CLASSIFICATION_ACTION = "PROPOSE_CLASSIFICATION_ACTION"
    # IDR-040: the deterministic layer records a ratified HUMAN decision
    # on a pending classification-action proposal. Internal-only — never
    # LLM-proposable: the human has no agent profile; the controller
    # ingests the operator verdict through this internal intent.
    RESOLVE_CLASSIFICATION_PROPOSAL = "RESOLVE_CLASSIFICATION_PROPOSAL"
    # IDR-041: the deterministic layer records the S16 scope-review intake —
    # the human's scope verdict on an APPROVED ROUTE_TO_SCOPE_REVIEW /
    # PROPOSE_SCOPE_NARROWING proposal, with the approval id as its
    # ratification ref. Internal-only (the human has no agent profile).
    RECORD_SCOPE_REVIEW_DECISION = "RECORD_SCOPE_REVIEW_DECISION"

    # v6 §7/S5 (implemented Step 5): the supersede-and-invalidate cascade
    # trigger — human-initiated per the §9.2 override discipline,
    # gateway-validated, requires a cited reason and a recorded
    # HumanDecision (dereferenced fail-closed at admission against the
    # HumanDecisionReceived journal). Internal-only in this phase: the
    # human has no agent profile; the deterministic layer ingests the
    # ratified verdict through this intent (the record_operator_decision
    # precedent, IDR-040 §3). Never LLM-proposable.
    RETRACT_SOURCE = "RETRACT_SOURCE"

    # Step 7 (v6 §16.6): the curated-knowledge registry admission trigger —
    # a ratified operator decision to admit (or supersede) a REFUTED_PATTERN
    # entry derived from a REFUTED hypothesis's FeatureBinding. Internal-only
    # (the human has no agent profile; the deterministic layer ingests the
    # ratified verdict through this intent — the record_operator_decision
    # precedent, IDR-040 §3). Never LLM-proposable: admission requires a
    # recorded HumanDecision whose payload binds the full-command
    # ``curation_id`` hash, verified fail-closed at the gateway.
    CURATE_KNOWLEDGE = "CURATE_KNOWLEDGE"

    # ADR-041 B3: the deterministic controller consumes an APPROVED
    # PROPOSE_PARALLEL_REGIME_TEST classification-action proposal and
    # emits this internal-only intent. The gateway validates the
    # triggering_classification_id, clones the parent program's substance,
    # and records the parallel-regime-test program. The trail shows
    # DETERMINISTIC origin (the controller) — no authorship re-attribution.
    # Internal-only — never LLM-proposable, never Director-proposed.
    EMIT_PARALLEL_REGIME_PROGRAM = "EMIT_PARALLEL_REGIME_PROGRAM"

    # Internal-only — scheduler / reconciling pass only
    ADMIT_TASK = "ADMIT_TASK"

    @classmethod
    def llm_proposable(cls) -> frozenset["IntentKind"]:
        return frozenset({
            cls.INSERT_TASK, cls.BRANCH, cls.ABANDON,
            cls.EVIDENCE_TRANSITION, cls.REQUEST_HUMAN,
            cls.REQUEST_REPLICATION, cls.REQUEST_ADDITIONAL_EXPERIMENT,
            cls.PROPOSE_GATE_OVERRIDE, cls.PROPOSE_RESEARCH_PROGRAM,
        })

    @classmethod
    def director_only(cls) -> frozenset["IntentKind"]:
        """Kinds only the Director may propose (IDR-018).

        The Director is the semantic proposer (v4 §13); the gateway's
        per-kind validator enforces ``proposed_by`` (P3). Declared now so
        the authority boundary is encoded at the type level.
        """
        return frozenset({cls.PROPOSE_RESEARCH_PROGRAM,
                          cls.PROPOSE_CLASSIFICATION_ACTION})

    @classmethod
    def internal_only(cls) -> frozenset["IntentKind"]:
        return frozenset({cls.ADMIT_TASK,
                          cls.RESOLVE_CLASSIFICATION_PROPOSAL,
                          cls.RECORD_SCOPE_REVIEW_DECISION,
                          cls.RETRACT_SOURCE,
                          cls.CURATE_KNOWLEDGE,
                          cls.RECORD_CONTRADICTION,
                          cls.CONTRADICTION_RESOLUTION,
                          cls.RECORD_CLASSIFICATION,
                          cls.EMIT_PARALLEL_REGIME_PROGRAM,
        })


class IntentRejectedError(Exception):
    """Raised when the Intent gateway rejects a proposed intent."""

    def __init__(self, kind: IntentKind, reason: str):
        self.kind = kind
        self.reason = reason
        super().__init__(f"Intent rejected ({kind.value}): {reason}")


# IDR-045 D2 — additive provenance fields (records, never authority — V1).
# Defaults keep the 11 src + 186 test ``Intent(`` sites byte-identical on
# ``IntentApplied`` (V2/V3 — missing keys = ``\"origin unrecorded\"``).
# Per-field max lengths (C5) enforced fail-closed here at construction and
# pre-write in ``gateway._require_provenance_bounds`` (called from
# ``apply_intent`` before validator dispatch) — never after a validator has
# committed its row (MERGE-AUDIT-045 F2).
ORIGIN_KIND_VALUES: frozenset[str] = frozenset({"deterministic", "llm"})
ORIGIN_KIND_MAX_LENGTH = 13
ORIGIN_REF_MAX_LENGTH = 64
MODEL_REF_MAX_LENGTH = 128
RUN_ID_MAX_LENGTH = 64
PROMPT_TEMPLATE_VERSION_MAX_LENGTH = 32
CHARTER_VERSION_MAX_LENGTH = 32

@dataclass(frozen=True, slots=True)
class Intent:
    """v4 §8: ``Intent { kind, proposed_by, project_id, payload, justification }``.

    IDR-045 D2 extends this with six additive provenance fields — records only,
    never authority (V1: the gateway's ``_require_role`` reads ``proposed_by``
    only). Defaults (``None``) keep the payload byte-identical on
    ``IntentApplied``; non-default keys are appended ``only when non-default``
    in ``_append_audit_event`` (V2/V3).
    """

    kind: IntentKind
    proposed_by: str
    project_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    justification: str = ""
    origin_kind: str | None = None
    origin_ref: str | None = None
    model_ref: str | None = None
    run_id: str | None = None
    prompt_template_version: str | None = None
    charter_version: str | None = None

    def __post_init__(self) -> None:
        if self.origin_kind is not None:
            if self.origin_kind not in ORIGIN_KIND_VALUES:
                msg = f"origin_kind must be one of {sorted(ORIGIN_KIND_VALUES)}, got {self.origin_kind!r}"
                raise ValueError(msg)
            if len(self.origin_kind) > ORIGIN_KIND_MAX_LENGTH:
                msg2 = f"origin_kind exceeds max length {ORIGIN_KIND_MAX_LENGTH}: {len(self.origin_kind)}"
                raise ValueError(msg2)
        for name, value, limit in (
            ("origin_ref", self.origin_ref, ORIGIN_REF_MAX_LENGTH),
            ("model_ref", self.model_ref, MODEL_REF_MAX_LENGTH),
            ("run_id", self.run_id, RUN_ID_MAX_LENGTH),
            ("prompt_template_version", self.prompt_template_version,
             PROMPT_TEMPLATE_VERSION_MAX_LENGTH),
            ("charter_version", self.charter_version, CHARTER_VERSION_MAX_LENGTH),
        ):
            if value is not None:
                if not isinstance(value, str):
                    msg3 = f"{name} must be a string, got {type(value).__name__}"
                    raise ValueError(msg3)
                if len(value) > limit:
                    msg4 = f"{name} exceeds max length {limit}: {len(value)}"
                    raise ValueError(msg4)

    def is_llm_proposable(self) -> bool:
        return self.kind in IntentKind.llm_proposable()

    def is_internal_only(self) -> bool:
        return self.kind in IntentKind.internal_only()
