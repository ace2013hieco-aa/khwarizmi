"""Methodology plane — the first methodology as CONFIG over the R4 runtime.

What a methodology is
---------------------
A methodology is **data**: an ordered composition of R4 runtime profiles, a
termination policy and the governance actions its stages perform. It is loaded,
checked fail-closed, and *driven* through the runtime's
one public entry (``hermes.agents.runtime.run.run``) — the same runtime, the
same profiles and the same governance entry every other caller uses. Adding a
methodology adds a document; it touches no runtime, governance or model code.
That is what makes it swappable, and it is what ``swap_test.py`` exercises.

Exactly one methodology ships here — ``literature-review``. A second document
is a fixture (``swap_test.py``), never a second shipped methodology.

The driver's contract
---------------------
:func:`run_methodology` does four things and nothing else:

1. for each declared stage, evaluates the stage's governance action through
   the governance plane's public entry ``evaluate_authority`` with the
   canonical policy (never a substituted one) and refuses the stage when the
   verdict refuses — the plane's own code and detail travel verbatim;
2. calls ``run(profile, task_context, …)`` for the stage, bounded by the
   methodology's stage limits, and **reads the run's terminal state**: a stage
   whose run did not reach ``SUCCEEDED`` is not recorded and does not continue
   the chain — a FAILED stage never contributes a transition to a COMPLETE run;
3. records one substrate node for the stage, with the provenance edge to its
   predecessor, through the substrate plane's write boundary;
4. stops at the methodology's own bounds, never past them.

It reads no clock, opens no connection, holds no lease and decides no
transition: every durable effect belongs to whoever owns the Orchestration
API. Prohibited-claims discipline applies here as everywhere — nothing in this
module asserts the standing of any result, and replay/derivation is never
presented as anything more than what it is.

Import discipline
-----------------
Imports are exactly: the runtime's public entry and the argument/return value
types of that entry, the governance plane's public ``evaluate_authority`` and
its request/context types, this package's own modules, and the standard
library. No runtime internals past ``run()``, no governance internals past the
canonical-policy entry, no model vendor named anywhere.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Mapping

from hermes.agents.runtime.run import run as runtime_run
from hermes.agents.runtime.types import (
    Proposal,
    ProposalSet,
    RunLimits,
    TaskContext,
    TaskStatus,
)
from hermes.governance.authority import (
    ActionRequest,
    EvidenceContext,
    evaluate_authority,
)
from hermes.methodology.substrate import (
    CHAIN_KINDS,
    MALFORMED_PAYLOAD,
    REF_NAMESPACES,
    ChainReconstruction,
    SubstrateNode,
    SubstrateRefusal,
    SubstrateStore,
    digest_of,
    reconstruct_chain,
    write_node,
)

__all__ = [
    "GOVERNANCE_ACTIONS",
    "LITERATURE_REVIEW_DOCUMENT",
    "MAX_STAGE_TICKS",
    "METHODOLOGY_SCHEMA_VERSION",
    "STAGE_KEYS",
    "TERMINATION_KEYS",
    "MethodologyConfig",
    "MethodologyConfigError",
    "MethodologyInputs",
    "MethodologyRefusal",
    "MethodologyRun",
    "StageOutcome",
    "StageSpec",
    "TerminationPolicy",
    "literature_review",
    "methodology_identity",
    "parse_methodology",
    "run_methodology",
]

METHODOLOGY_SCHEMA_VERSION = "1"

#: The bound on a stage's own tick budget (inclusive). Enough for
#: search–fetch–cite plus two corrections, and below the largest profile
#: default; a value outside ``1..MAX_STAGE_TICKS`` is refused at load, never
#: clamped.
MAX_STAGE_TICKS = 5

#: The closed stage-spec vocabulary. A stage names the profile that runs it,
#: the governance action it performs, whether it is required, the tick budget
#: its own work needs and the plain-language job it is given. Toolsets are
#: deliberately absent: the runtime's ``run()`` exposes no toolset surface, so
#: a *declared* toolset could not be enforced — declaring one would be an inert
#: control, so the key is refused rather than silently carried.
STAGE_KEYS: frozenset[str] = frozenset({
    "stage", "profile", "governance_action", "required",
    "max_ticks", "objective",
})

#: The closed termination vocabulary.
TERMINATION_KEYS: frozenset[str] = frozenset({
    "max_stages", "max_ticks_per_stage", "max_proposals_per_stage",
    "deadline_seconds",
})

#: The governance actions a stage may declare. These are the governance plane's
#: own action names — this module adds none and renames none; a stage that
#: declares anything else fails to load.
GOVERNANCE_ACTIONS: frozenset[str] = frozenset({
    "WEB_SEARCH", "WEB_READ", "SANDBOX_RUN", "HYPOTHESIS_MODIFY",
    "CONTRADICTION_DECLARE", "EVIDENCE_DELETE", "DIRECTION_CHANGE", "PUBLISH",
    "EXTERNAL",
})


class MethodologyConfigError(ValueError):
    """A configuration this plane cannot read — fail-closed at the boundary."""


# ═══════════════════════ configuration as data ═══════════════════════


@dataclass(frozen=True, slots=True)
class StageSpec:
    """One stage: which profile runs, what gates it, its budget and its job.

    ``max_ticks`` is the stage's own tick budget. It is optional and additive:
    a document that does not declare it serializes exactly as before, parses to
    ``None`` and inherits the methodology-wide ``max_ticks_per_stage``. The
    budget is the *bound*: a stage that proposes early still stops early.

    ``objective`` is the stage's job in plain words — how the profile should
    spend the ticks it was given. It is methodology **data** (stage
    configuration), never operator text and never instruction authority: it
    enters the stage prompt through the existing payload envelope port,
    origin-labelled like every other payload value, and it is deliberately
    absent from ``predecessor_content`` so it cannot re-enter a later prompt
    as chain content. A document without it renders no objective at all.

    Both keys are omitted by :meth:`to_mapping` when unset, so an old-form
    document keeps its digest to the byte.
    """

    stage: str
    profile: str
    governance_action: str = ""
    required: bool = True
    max_ticks: int | None = None
    objective: str | None = None

    def effective_ticks(self, default: int) -> int:
        """This stage's tick budget — its own, or the methodology default."""
        return default if self.max_ticks is None else self.max_ticks

    def to_mapping(self) -> dict[str, Any]:
        mapping: dict[str, Any] = {
            "stage": self.stage,
            "profile": self.profile,
            "governance_action": self.governance_action,
            "required": self.required,
        }
        if self.max_ticks is not None:
            mapping["max_ticks"] = self.max_ticks
        if self.objective is not None:
            mapping["objective"] = self.objective
        return mapping

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "StageSpec":
        unknown = sorted(set(data) - STAGE_KEYS)
        if unknown:
            raise MethodologyConfigError(f"unknown stage keys: {unknown}")
        stage = str(data.get("stage", ""))
        profile = str(data.get("profile", ""))
        if not stage:
            raise MethodologyConfigError("a stage needs a non-empty 'stage' kind")
        if not profile:
            raise MethodologyConfigError(f"stage {stage!r} needs a profile name")
        if stage not in CHAIN_KINDS:
            raise MethodologyConfigError(
                f"stage {stage!r} is not a chain kind {CHAIN_KINDS}")
        action = str(data.get("governance_action", ""))
        if action and action not in GOVERNANCE_ACTIONS:
            raise MethodologyConfigError(
                f"stage {stage!r} declares governance action {action!r}, which "
                f"is not a governance plane action")
        return cls(stage=stage, profile=profile, governance_action=action,
                   required=bool(data.get("required", True)),
                   max_ticks=_stage_ticks(stage, data),
                   objective=_stage_objective(stage, data))


def _stage_ticks(stage: str, data: Mapping[str, Any]) -> int | None:
    """The declared budget, if any — an integer in ``1..MAX_STAGE_TICKS``.

    A missing key is ``None`` (inherit the methodology default). Anything else
    must be a real integer in range: a bool, a float, a string, zero, a
    negative or an over-cap value is refused rather than clamped, because a
    silently adjusted budget would make the cost table a fiction.
    """
    if "max_ticks" not in data:
        return None
    value = data["max_ticks"]
    if isinstance(value, bool) or not isinstance(value, int):
        raise MethodologyConfigError(
            f"stage {stage!r} max_ticks must be an integer, not "
            f"{type(value).__name__}")
    if not 1 <= value <= MAX_STAGE_TICKS:
        raise MethodologyConfigError(
            f"stage {stage!r} max_ticks {value} is outside 1.."
            f"{MAX_STAGE_TICKS}")
    return value


def _stage_objective(stage: str, data: Mapping[str, Any]) -> str | None:
    """The declared objective, if any — non-empty text, never a blank job."""
    if "objective" not in data:
        return None
    value = data["objective"]
    if not isinstance(value, str) or not value.strip():
        raise MethodologyConfigError(
            f"stage {stage!r} objective must be non-empty text when declared")
    return value


@dataclass(frozen=True, slots=True)
class TerminationPolicy:
    """The methodology's own bounds — closed, explicit, never inferred."""

    max_stages: int = 0
    max_ticks_per_stage: int = 1
    max_proposals_per_stage: int = 1
    deadline_seconds: float | None = None

    def to_mapping(self) -> dict[str, Any]:
        return {
            "max_stages": self.max_stages,
            "max_ticks_per_stage": self.max_ticks_per_stage,
            "max_proposals_per_stage": self.max_proposals_per_stage,
            "deadline_seconds": self.deadline_seconds,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "TerminationPolicy":
        unknown = sorted(set(data) - TERMINATION_KEYS)
        if unknown:
            raise MethodologyConfigError(f"unknown termination keys: {unknown}")
        deadline = data.get("deadline_seconds")
        return cls(
            max_stages=int(data.get("max_stages", 0)),
            max_ticks_per_stage=int(data.get("max_ticks_per_stage", 1)),
            max_proposals_per_stage=int(data.get("max_proposals_per_stage", 1)),
            deadline_seconds=(None if deadline is None else float(deadline)))

    def limits(self, max_ticks: int | None = None) -> RunLimits:
        """This policy's per-stage bounds, as the runtime's own limits value.

        ``max_ticks`` is the stage's own budget when it declares one; a ``None``
        (the usual case) keeps the methodology-wide value. Nothing else in the
        limits changes, so a stage budget can never widen a proposal, tool or
        deadline bound.
        """
        return RunLimits(
            max_ticks=(self.max_ticks_per_stage if max_ticks is None
                       else max_ticks),
            max_proposals=self.max_proposals_per_stage,
            deadline_seconds=self.deadline_seconds)


@dataclass(frozen=True, slots=True)
class MethodologyConfig:
    """A whole methodology, as versioned data with a content digest."""

    methodology_id: str
    version: str
    name: str
    description: str
    stages: tuple[StageSpec, ...]
    termination: TerminationPolicy

    def stage_kinds(self) -> tuple[str, ...]:
        return tuple(stage.stage for stage in self.stages)

    def profiles(self) -> tuple[str, ...]:
        return tuple(stage.profile for stage in self.stages)

    def digest(self) -> str:
        """Deterministic digest of the document — the swap evidence's unit."""
        return digest_of(self.to_mapping())

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": METHODOLOGY_SCHEMA_VERSION,
            "methodology_id": self.methodology_id,
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "stages": [stage.to_mapping() for stage in self.stages],
            "termination": self.termination.to_mapping(),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "MethodologyConfig":
        return parse_methodology(data)


def parse_methodology(data: Mapping[str, Any]) -> MethodologyConfig:
    """Read a methodology document — closed schema, fail-closed, total checks.

    Beyond the schema, two structural rules make a document *drivable*:

    * stages are unique and follow the chain order (a subsequence of the
      substrate chain), so every transition the driver records is one the
      substrate's transition map allows;
    * a document that declares a ``CONCLUSION`` stage must also *declare* every
      stage that precedes it, because a conclusion is drawn from a complete
      lineage.

    The second rule is a check on the **declared** stage list, not on the run
    that follows: a stage marked ``required: False`` may still be skipped by the
    driver, so the load-time rule cannot by itself promise a complete lineage.
    What stops a conclusion being drawn from a partial chain is the run-time
    floor — the substrate refuses ``PREMATURE_CONCLUSION`` when the lineage
    reaching a conclusion is missing a kind (see
    :func:`~hermes.methodology.substrate.write_node`). Load-time rejection is a
    fail-fast convenience; the run-time floor is the enforcement.

    A ``toolset`` key is refused (unknown): this plane's runtime surface exposes
    no toolset, so a declared one could not be enforced — an inert control.
    """
    if not isinstance(data, Mapping):
        raise MethodologyConfigError(
            f"a methodology must be a mapping, not {type(data).__name__}")
    unknown = sorted(set(data) - {
        "schema_version", "methodology_id", "version", "name", "description",
        "stages", "termination"})
    if unknown:
        raise MethodologyConfigError(f"unknown methodology keys: {unknown}")
    schema = str(data.get("schema_version", METHODOLOGY_SCHEMA_VERSION))
    if schema != METHODOLOGY_SCHEMA_VERSION:
        raise MethodologyConfigError(
            f"unsupported methodology schema_version {schema!r} "
            f"(this plane reads {METHODOLOGY_SCHEMA_VERSION!r})")
    methodology_id = str(data.get("methodology_id", ""))
    version = str(data.get("version", ""))
    if not methodology_id:
        raise MethodologyConfigError("a methodology needs a non-empty id")
    if not version:
        raise MethodologyConfigError("a methodology needs a non-empty version")
    raw_stages = data.get("stages")
    if not isinstance(raw_stages, (list, tuple)) or not raw_stages:
        raise MethodologyConfigError("a methodology needs a non-empty stage list")
    stages = tuple(StageSpec.from_mapping(dict(item)) for item in raw_stages)
    kinds = [stage.stage for stage in stages]
    if len(set(kinds)) != len(kinds):
        raise MethodologyConfigError(f"duplicate stages declared: {kinds}")
    order = {kind: index for index, kind in enumerate(CHAIN_KINDS)}
    positions = [order[kind] for kind in kinds]
    if positions != sorted(positions):
        raise MethodologyConfigError(
            f"stages {kinds} are not in chain order {CHAIN_KINDS}")
    if "CONCLUSION" in kinds:
        missing = [kind for kind in CHAIN_KINDS[:CHAIN_KINDS.index("CONCLUSION")]
                   if kind not in kinds]
        if missing:
            raise MethodologyConfigError(
                f"a methodology declaring CONCLUSION must declare its whole "
                f"lineage; missing {missing}")
    termination = TerminationPolicy.from_mapping(
        dict(data.get("termination") or {}))
    return MethodologyConfig(
        methodology_id=methodology_id,
        version=version,
        name=str(data.get("name", methodology_id)),
        description=str(data.get("description", "")),
        stages=stages,
        termination=termination)


#: The one methodology this plane ships.
LITERATURE_REVIEW_DOCUMENT: Mapping[str, Any] = {
    "schema_version": METHODOLOGY_SCHEMA_VERSION,
    "methodology_id": "literature-review",
    # The content revision, distinct from the schema version: document version
    # 2 is the revision that declares a stage budget and each stage's job. It
    # is a governed-document event — see docs/idr/LIVE-STAGE-BUDGET.md §6.2.
    "version": "2",
    "name": "literature-review",
    "description": (
        "A cited search of admitted sources: frame the question, draw a "
        "hypothesis from prior art, pre-register what would count against it, "
        "run the discriminating step, record the observation, admit the "
        "evidence, state the claim, subject it to adversarial critique and "
        "draw the conclusion. Every stage is an R4 runtime profile; every "
        "source-reading stage passes the governance plane's own web-action "
        "gate."),
    "stages": [
        {"stage": "QUESTION", "profile": "planner",
         "governance_action": "WEB_SEARCH",
         "objective": (
             "State the question this run must answer, in terms the recorded "
             "evidence could settle.")},
        {"stage": "HYPOTHESIS", "profile": "researcher",
         "governance_action": "WEB_SEARCH",
         "objective": (
             "Propose a testable hypothesis and cite the prior art you were "
             "given: the hypothesis: ref in the task input.")},
        {"stage": "PREDICTION", "profile": "experimenter",
         "objective": (
             "State what your hypothesis predicts, and the observation that "
             "would refute it.")},
        {"stage": "EXPERIMENT", "profile": "experimenter",
         "governance_action": "SANDBOX_RUN",
         "objective": (
             "Describe the test that would discriminate between the hypothesis "
             "and the observation that would refute it.")},
        {"stage": "OBSERVATION", "profile": "researcher",
         "governance_action": "WEB_READ",
         # OPS-5F: search, fetch, cite. A proposal ends the stage, so the model
         # must gather before it proposes; the objective spells out that order.
         "max_ticks": 3,
         "objective": (
             "Gather first, propose last. Call source_search to find a source; "
             "its reply carries a search handle. Then call source_fetch with "
             "that handle and a row index; its reply names the artifact it "
             "wrote. Only once you hold a fetched artifact should you propose "
             "an EVIDENCE_TRANSITION whose payload.evidence_artifact_ref is "
             "that artifact as evidence:<artifact_id>. A proposal ends this "
             "stage (stop_when: proposals_raised), so a proposal made before "
             "you have fetched cites nothing.")},
        {"stage": "EVIDENCE", "profile": "verifier",
         "objective": (
             "Cite the artifact this run observed: the evidence: ref the "
             "observation admitted, as this stage's external_ref.")},
        {"stage": "CLAIM", "profile": "synthesizer",
         "objective": (
             "State what the cited evidence supports, and only what it "
             "supports.")},
        {"stage": "CRITIQUE", "profile": "critic",
         "objective": (
             "Attack the claim: say what would break it, and whether the cited "
             "evidence already does.")},
        {"stage": "CONCLUSION", "profile": "synthesizer",
         "objective": (
             "Answer the question the run started from, in light of the "
             "recorded chain.")},
    ],
    "termination": {
        "max_stages": 9,
        "max_ticks_per_stage": 1,
        "max_proposals_per_stage": 1,
        "deadline_seconds": 180,
    },
}


def literature_review() -> MethodologyConfig:
    """The shipped methodology, re-parsed from its document (never cached)."""
    return parse_methodology(dict(LITERATURE_REVIEW_DOCUMENT))


# ═══════════════════════ driver ═══════════════════════


@dataclass(frozen=True, slots=True)
class MethodologyInputs:
    """What a caller must supply for one methodology run — nothing is invented.

    ``external_refs`` maps a **prior-art** referenced-kind stage to the artifact
    ref the caller observed (``hypothesis:…`` / ``prediction:…`` /
    ``claim:…``). It deliberately has no evidence position: OPS-5D makes the
    ``EVIDENCE`` ref agent-derived (the admitted ``EVIDENCE_TRANSITION``), and
    a seed evidence ref is refused. ``admission_refs`` names the prior-art refs
    that resolve in the project — the citation registry; a node citing a ref
    that is not registered fails closed, which is exactly the intended
    behaviour for a ref nobody observed. ``retracted_refs`` is the N9
    projection the caller supplies; an evidence ref there is allowed because a
    retraction can only remove support, never make a ref resolve.
    """

    question: str
    external_refs: Mapping[str, str] = field(default_factory=dict)
    admission_refs: tuple[str, ...] = ()
    retracted_refs: tuple[str, ...] = ()
    stage_content: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    governance_context: EvidenceContext | None = None


@dataclass(frozen=True, slots=True)
class MethodologyRefusal:
    """Refusal-as-data from the driver, naming the layer that refused."""

    code: str
    detail: str
    stage: str = ""
    source: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"rejected": True, "code": self.code, "detail": self.detail,
                "stage": self.stage, "source": self.source}

    def to_mapping(self) -> dict[str, Any]:
        return {"code": self.code, "detail": self.detail, "stage": self.stage,
                "source": self.source}


@dataclass(frozen=True, slots=True)
class StageOutcome:
    """One stage's result: the run's terminal state and the recorded node."""

    stage: str
    profile: str
    state: str
    termination: str
    run_digest: str
    node_id: str
    governance: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "profile": self.profile,
            "state": self.state,
            "termination": self.termination,
            "run_digest": self.run_digest,
            "node_id": self.node_id,
            "governance": self.governance,
        }


@dataclass(frozen=True, slots=True)
class MethodologyRun:
    """The whole run: the substrate state, the stage outcomes, the termination."""

    methodology_id: str
    version: str
    project_id: str
    store: SubstrateStore
    stages: tuple[StageOutcome, ...]
    termination: str
    question_id: str = ""

    def reconstruction(self) -> ChainReconstruction | SubstrateRefusal:
        """Reconstruct the chain the run recorded (a read, not a claim)."""
        return reconstruct_chain(self.store, self.question_id)

    def digest(self) -> str:
        return digest_of({
            "methodology_id": self.methodology_id,
            "version": self.version,
            "project_id": self.project_id,
            "stages": [stage.to_mapping() for stage in self.stages],
            "termination": self.termination,
            "store": self.store.to_mapping(),
        })

    def to_mapping(self) -> dict[str, Any]:
        return {
            "methodology_id": self.methodology_id,
            "version": self.version,
            "project_id": self.project_id,
            "stages": [stage.to_mapping() for stage in self.stages],
            "termination": self.termination,
            "question_id": self.question_id,
        }


#: OPS-5D — the positions whose content is agent-derived. The evidence ref is
#: selected from an admitted EVIDENCE_TRANSITION in one of these stage runs.
_EVIDENCE_STAGES: tuple[str, ...] = ("OBSERVATION", "EVIDENCE")

#: The labels the design requires on the prior-art remainder. They are node
#: `rationale` text (not content), so they never re-enter a prompt through
#: `predecessor_content`.
_PRIOR_ART_LABEL = "prior-art citation (no producer in this build)"
_CLAIM_IDENTITY_LABEL = (
    "claim identity is prior art; support is the recorded evidence ref")

_EVIDENCE_POSITION_KEYS: Mapping[str, tuple[str, ...]] = {
    "OBSERVATION": ("cited_refs",),
    "EVIDENCE": ("external_ref",),
    "CLAIM": ("admitted_refs",),
}


def _seeded_evidence_refusal(
        inputs: MethodologyInputs) -> MethodologyRefusal | None:
    """Refuse an operator-supplied evidence ref before any stage runs.

    The evidence position is the agent's: its ref is the admitted
    ``EVIDENCE_TRANSITION`` payload, not a seed string. A seed evidence ref
    would pre-empt the agent exactly as run 13 measured, so it is refused with
    the plane's own shape code. ``retracted_refs`` is deliberately **not**
    refused: it is the N9 projection, not a citation or a resolver entry, and
    an evidence ref there can only remove support.
    """
    def refuse(detail: str) -> MethodologyRefusal:
        return MethodologyRefusal(code=MALFORMED_PAYLOAD, detail=detail,
                                  source="inputs")

    for name, ref in inputs.external_refs.items():
        text = str(ref)
        if name == "EVIDENCE" and text:
            return refuse(
                "the evidence position is agent-derived: external_refs may not "
                "supply EVIDENCE; the admitted EVIDENCE_TRANSITION supplies "
                "the ref (OPS-5D)")
        if text.startswith("evidence:"):
            return refuse(
                f"external_refs[{name!r}] carries an evidence: ref; the "
                f"evidence position is agent-derived (OPS-5D)")
    for ref in inputs.admission_refs:
        if str(ref).startswith("evidence:"):
            return refuse(
                "admission_refs may not make an evidence: ref resolve; the "
                "admitted EVIDENCE_TRANSITION is the only source (OPS-5D)")
    for stage, fields in _EVIDENCE_POSITION_KEYS.items():
        override = inputs.stage_content.get(stage)
        if not isinstance(override, Mapping):
            continue
        for key in fields:
            if key not in override:
                continue
            value = override[key]
            if isinstance(value, (list, tuple)):
                if any(str(item) for item in value):
                    return refuse(
                        f"stage_content[{stage!r}][{key!r}] may not supply "
                        f"the evidence position's ref; it is agent-derived "
                        f"(OPS-5D)")
            elif str(value or ""):
                return refuse(
                    f"stage_content[{stage!r}][{key!r}] may not supply the "
                    f"evidence position's ref; it is agent-derived (OPS-5D)")
    return None


def _admitted_evidence_proposal(
        proposals: tuple[Proposal, ...],
        *,
        canonicalise: Callable[[str], str | None] | None = None,
) -> Proposal | None:
    """The latest admitted EVIDENCE_TRANSITION naming an ``evidence:`` ref.

    The gateway already validated the ref (``EVIDENCE_REF`` / in-project); this
    selector only checks the admitted verdict and the ref shape. It never reads
    the artifact table.

    OPS-5L: the gateway normalises both the citation form (``evidence:<id>``)
    and the observation handle (``evidence/<id>``) at admission, but the
    admitted proposal's intent payload still carries the raw spelling. A caller
    that owns the citation grammar (the live driver, which passes the research
    plane's ``canonical_evidence_ref``) injects it here, so an admitted handle
    is not silently skipped. The default keeps this plane's historical
    colon-only reading for callers with no capability plane (the plane's
    reference/swap driver); it never weakens the gateway's check.
    """
    selected: Proposal | None = None
    for proposal in proposals:
        if not proposal.was_admitted():
            continue
        if proposal.intent.kind.value != "EVIDENCE_TRANSITION":
            continue
        ref = proposal.intent.payload.get("evidence_artifact_ref")
        if not isinstance(ref, str):
            continue
        if canonicalise is not None:
            canonical = canonicalise(ref)
        else:
            canonical = ref if ref.startswith("evidence:") else None
        if canonical:
            selected = proposal
    return selected


def _evidence_ref_of(
        proposal: Proposal | None,
        *,
        canonicalise: Callable[[str], str | None] | None = None,
) -> str:
    if proposal is None:
        return ""
    ref = proposal.intent.payload.get("evidence_artifact_ref")
    if not isinstance(ref, str):
        return ""
    if canonicalise is not None:
        return canonicalise(ref) or ""
    return ref


def _node_rationale(kind: str, stage: str, profile: str,
                    proposals: tuple[Proposal, ...],
                    evidence_proposal: Proposal | None) -> str:
    """The node's rationale: model text as a node field, never as content.

    OPS-5D approval: the rationale is a node field, not content, and it does not
    re-enter the next prompt. The prior-art positions are labelled here because
    their external_ref is still an operator citation.
    """
    admitted = [proposal for proposal in proposals if proposal.was_admitted()]
    rationale = admitted[0].rationale if admitted else ""
    if not rationale and kind == "EVIDENCE" and evidence_proposal is not None:
        rationale = evidence_proposal.rationale
    if not rationale:
        rationale = f"stage {stage} via profile {profile}"
    if kind in ("HYPOTHESIS", "PREDICTION"):
        rationale = f"{rationale}; {_PRIOR_ART_LABEL}"
    elif kind == "CLAIM":
        rationale = f"{rationale}; {_CLAIM_IDENTITY_LABEL}"
    return rationale


def _default_content(kind: str, inputs: MethodologyInputs,
                     predecessor_id: str, question_id: str,
                     *, evidence_ref: str = "",
                     ) -> Mapping[str, Any]:
    """The plainest well-formed content for a stage — never a fabricated ref.

    OPS-5D: the evidence position is not read from the seed. ``EVIDENCE`` gets
    the admitted ``evidence_ref``; ``OBSERVATION`` cites it; ``CLAIM`` admits
    it. The prior-art positions (``HYPOTHESIS``, ``PREDICTION``, ``CLAIM``'s own
    identity) still read ``inputs.external_refs``; they have no producer in
    this build and are labelled in the node rationale.
    """
    override = inputs.stage_content.get(kind)
    content: dict[str, Any] = dict(override) if override is not None else {}
    if kind == "QUESTION":
        content.setdefault("question", inputs.question)
    elif kind == "CLAIM":
        content.setdefault("external_ref", inputs.external_refs.get("CLAIM", ""))
        content["admitted_refs"] = ((evidence_ref,) if evidence_ref else ())
    elif kind == "EVIDENCE":
        # The admitted ref is the only source; an empty value reaches the
        # substrate's own shape refusal and the stage is not recorded.
        content["external_ref"] = evidence_ref
    elif kind in REF_NAMESPACES:
        content.setdefault("external_ref", inputs.external_refs.get(kind, ""))
    elif kind == "OBSERVATION":
        if evidence_ref:
            content["cited_refs"] = (evidence_ref,)
    elif kind == "CRITIQUE":
        content.setdefault("subject_ref", predecessor_id)
    elif kind == "CONCLUSION":
        content.setdefault("question_ref", question_id)
    return content


def _governance_outcome(stage: StageSpec, inputs: MethodologyInputs,
                        project_id: str, actor: str, rationale: str
                        ) -> tuple[str, MethodologyRefusal | None]:
    """Evaluate the stage's governance action through the public entry."""
    if not stage.governance_action:
        return "NOT_DECLARED", None
    request = ActionRequest(
        action=stage.governance_action,
        project_id=project_id,
        actor=actor,
        rationale=rationale)
    verdict = evaluate_authority(request, inputs.governance_context)
    if verdict.is_allowed():
        return verdict.verdict, None
    refusal = verdict.refusal
    detail = refusal.detail if refusal is not None else verdict.as_dict().get(
        "detail", "")
    code = refusal.code if refusal is not None else "ROLE"
    return verdict.verdict, MethodologyRefusal(
        code=code, detail=str(detail), stage=stage.stage, source="governance")


def run_methodology(
    config: MethodologyConfig,
    project_id: str,
    task_id: str,
    lease_generation: str,
    inputs: MethodologyInputs,
    *,
    model: Any,
    orchestration: Any,
    capabilities: Any = None,
    profiles: Mapping[str, Any] | None = None,
    actor: str = "methodology-plane",
) -> MethodologyRun | MethodologyRefusal:
    """Drive one methodology through the R4 runtime's public ``run()``.

    Refusal is data at every layer: a governance refusal returns the
    governance plane's own code and detail; a runtime that cannot run the
    stage returns the runtime's terminal ``FAILED`` state (recorded, never
    hidden); a substrate write that fails closed returns the substrate code.
    A stage that cannot be *recorded* is a stage that did not happen — the run
    stops there rather than reporting a chain it cannot show.

    OPS-5D: the evidence position is agent-derived. A seed evidence ref is
    refused before any stage; an admitted ``EVIDENCE_TRANSITION`` in the
    OBSERVATION/EVIDENCE runs supplies the ``EVIDENCE`` node's ref. A run with
    no admitted transition stops at ``EVIDENCE`` rather than recording a
    synthetic ref.
    """
    seed_refusal = _seeded_evidence_refusal(inputs)
    if seed_refusal is not None:
        return seed_refusal
    store = SubstrateStore()
    for ref in inputs.admission_refs:
        store.admit_ref(ref, project_id)
    for ref in inputs.retracted_refs:
        store.retract(ref)

    stages: list[StageOutcome] = []
    question_id = ""
    predecessor_id = ""
    termination = "COMPLETE"
    content_cache: dict[str, Mapping[str, Any]] = {}
    evidence_ref = ""
    evidence_proposal: Proposal | None = None

    for stage in config.stages:
        if config.termination.max_stages and len(stages) >= (
                config.termination.max_stages):
            termination = "STAGE_LIMIT"
            break
        if not stage.required:
            continue
        existing = store.nodes_of_kind(stage.stage, project_id=project_id)
        if existing:
            # Idempotent by construction: a stage already recorded is not run
            # twice, and its node is the predecessor of the next stage.
            predecessor_id = existing[0][0]
            question_id = question_id or (
                predecessor_id if stage.stage == "QUESTION" else question_id)
            continue

        governance, refusal = _governance_outcome(
            stage, inputs, project_id, actor, inputs.question)
        if refusal is not None:
            return refusal

        payload: dict[str, Any] = {
            "stage": stage.stage,
            "methodology_id": config.methodology_id,
            "predecessor": predecessor_id,
            "predecessor_content": dict(content_cache.get(
                predecessor_id, {})),
        }
        if stage.objective is not None:
            # Stage configuration, rendered by the existing payload port
            # (`runtime.payload`): untrusted, origin-labelled data, never
            # operator text and never an instruction authority. A document
            # without an objective adds no key, so an old stage renders none.
            payload["objective"] = stage.objective
        context = TaskContext(
            task_id=f"{task_id}:{stage.stage}",
            project_id=project_id,
            lease_generation=lease_generation,
            payload=payload,
            limits=config.termination.limits(stage.max_ticks))
        result: ProposalSet = runtime_run(
            stage.profile, context, model=model, orchestration=orchestration,
            capabilities=capabilities, profiles=profiles)

        if result.state != TaskStatus.SUCCEEDED.value:
            # The runtime's terminal state is authoritative. A stage whose run
            # did not succeed is **not recorded** and does not extend the chain,
            # so a FAILED (or cancelled) stage can never contribute a transition
            # to a run that reports COMPLETE — the chain stops at the stage that
            # did not run, and `termination` carries the runtime's own reason.
            termination = result.termination or result.state
            break

        if stage.stage in _EVIDENCE_STAGES:
            selected = _admitted_evidence_proposal(result.proposals)
            if selected is not None:
                evidence_proposal = selected
                evidence_ref = _evidence_ref_of(selected)
                # Projection of the gateway's admission into the in-memory
                # registry the substrate's write boundary reads. Not a second
                # validation: the gateway already checked the artifact row.
                store.admit_ref(evidence_ref, project_id)

        content = dict(_default_content(stage.stage, inputs, predecessor_id,
                                        question_id,
                                        evidence_ref=evidence_ref))
        if predecessor_id:
            content["predecessors"] = (predecessor_id,)
        node = SubstrateNode(
            kind=stage.stage,
            project_id=project_id,
            producing_task_id=context.task_id,
            content=content,
            rationale=_node_rationale(
                stage.stage, stage.stage, stage.profile, result.proposals,
                evidence_proposal))
        recorded = write_node(store, node)
        if isinstance(recorded, SubstrateRefusal):
            return MethodologyRefusal(code=recorded.code, detail=recorded.detail,
                                      stage=stage.stage, source="substrate")
        node_id = recorded
        if stage.stage == "QUESTION":
            question_id = node_id
        content_cache[node_id] = content

        stages.append(StageOutcome(
            stage=stage.stage,
            profile=stage.profile,
            state=result.state,
            termination=result.termination,
            run_digest=result.digest(),
            node_id=node_id,
            governance=governance))
        predecessor_id = node_id

    return MethodologyRun(
        methodology_id=config.methodology_id,
        version=config.version,
        project_id=project_id,
        store=store,
        stages=tuple(stages),
        termination=termination,
        question_id=question_id)


def methodology_identity(config: MethodologyConfig) -> str:
    """A short, by-rule handle for a methodology document (diagnostics only)."""
    return "mth_" + digest_of(config.to_mapping())[:24]
