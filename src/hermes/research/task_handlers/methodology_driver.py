"""Methodology execution driver — the W3 binding of BIND-5 over the W2 runtime.

`docs/archive/WIRING_DESIGN.md` BIND-5 asks one question: *how does a methodology run
orchestrate R4+R3+R2 and record only through existing boundaries?* This module is
the W3 answer — a **new-files-only** slice; it edits nothing that already exists
(including ``hermes.methodology.workflows`` and ``hermes.methodology.substrate``).

What the driver does, once per stage, in this order
---------------------------------------------------
1. **Projects** each stage of a parsed workflow document onto one task
   (``stage_projections`` / ``project_stage``): the stage's profile, its declared
   governance action and a :class:`TaskContext` whose lease generation is the
   wiring's own fence generation and whose ``runtime.task`` envelope carries the
   operator's question and ref ids. Projection is pure data — no run, no model
   and no write happens here.
2. **Consults governance before the stage runs** (:func:`preflight`): the BIND-4
   read-only consult, reached through the *one already-declared* consumer — this
   driver exercises the methodology plane's own per-stage preflight rather than
   adding a new reader of the governance plane. A denial stops the run right
   there and travels back as data with the governance plane's own code, verbatim
   — never a silent skip.
3. **Drives the W2** :class:`RuntimeWiring` **once per stage**
   (:func:`run_methodology`): the lease fence, the attribution tag and the
   InMemory-only stores are the wiring's, not the driver's. The driver never
   acquires, renews or releases a lease, opens no transaction and appends no
   journal row; it reads the wiring's fence generation and threads it into every
   projected context.
4. **Records the stage's substrate node as derived working state** in the run's
   in-memory ``SubstrateStore`` (:func:`write_node`) — the plane's own boundary,
   whose identity is recomputed by rule. No intent, no repository, no table:
   nothing about a node or edge is durable, and no ``mnode_``/``medge_``
   reference outlives the process.
5. **Recomputes the chain** from that derived state on demand
   (:meth:`MethodologyExecution.reconstruction`) — purely, from the store, never
   from a cached view.

Where durability actually happens
---------------------------------
Every durable effect of a stage is an ordinary intent the stage's run proposed
through the injected ``IntentApplier`` — in production the gateway's one mutation
path, ``apply_intent`` (``src/hermes/research/gateway.py``). The driver names
that boundary on every admission (``ADMISSION_BOUNDARY``) and counts, per stage,
what the spine **recorded** — read off the proposals' own admission records
(OPS-5T), never off a call counter; everything else it produces is working state.

Claim limits (BIND-5, §8 item 9)
--------------------------------
A wired methodology run may claim its **stage execution, stage outcomes/digests
and the durable admissions its proposals made through** ``apply_intent``. It may
**not** claim durable substrate state, a durable chain, or any ``mnode_``/``medge_``
reference readable after the process ends: that needs a table + an intent kind +
a gateway validator (the ``docs/archive/ARCHITECTURE_DELTA.md`` §8 item 9 gate), which this
slice refuses rather than implements (:func:`claim_limits` /
:func:`refuse_durable_claim`).

Import discipline
-----------------
``hermes.agents.runtime.wiring`` + ``.types`` + ``.assembly`` (the W2 driver it
binds, its context types, and the one context-assembly port that renders task
input), ``hermes.core.task_status``, the methodology plane's public surface
(``hermes.methodology.workflows``, whose declared preflight this exercises) and
``hermes.methodology.substrate`` (the derived-state boundary), plus stdlib.
OPS-5L adds one read-side vocabulary import,
``hermes.research.evidence_transitions`` (``canonical_evidence_ref`` and its
``EVIDENCE_REF_PREFIX``) — the citation grammar the gateway already normalises
with (OPS-5K), a pure function of a string — so the evidence selector reads an
admitted ``evidence/<id>`` handle as the same canonical ``evidence:<id>`` the
gateway stored. It is not a second artifact-row check: the gateway's
``EVIDENCE_REF`` remains the only one.
OPS-5Z5 adds the claim gate (``hermes.research.grounding``, deterministic
regexes, no provider or model) and the one content model
(``hermes.tools.capabilities.content``, pure JSON/HTML rendering) — the same
reader the envelope uses, so the gate binds over the prose the model was shown.
OPS-5Z Group E adds the verification round (``hermes.research.verification``):
a conflict proposal's terminal record is written through the same injected
applier, and the round's fetch is an injected runner (the capability plane's
``source_fetch``), so this module still performs no I/O and opens no
transaction of its own. Never ``hermes.persistence``, never a repository,
never a raw connection, and no new consumer of the governance plane.

Refusal vocabulary (frozen)
---------------------------
This module emits no code of its own: ``MALFORMED_PAYLOAD`` (the plane's own
shape/gate refusal, reused for a workflow-document load failure and for a
durability claim), and whatever :func:`preflight` or :func:`write_node` return,
which are their own frozen sets. The round's own statuses (RESOLVED /
DISPUTED / REFUSED) are a record, not a refusal code, and the gateway's
``BUDGET``/``STALE`` travel verbatim when a round or its outcome is refused.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping

import hermes.research.verification as verification
from hermes.agents.runtime.assembly import (
    ProjectIndexChainNode,
    ProjectIndexPort,
    evidence_envelope,
    project_index_envelope,
    task_input_envelope,
)
from hermes.agents.runtime.types import Admission, Proposal, TaskContext
from hermes.agents.runtime.wiring import RuntimeWiring, WiredRun
from hermes.core.intents import Intent, IntentKind, IntentRejectedError
from hermes.core.node import AgentProfile
from hermes.core.task_status import TaskStatus
from hermes.methodology import workflows as methodology_plane
from hermes.methodology.substrate import (
    MALFORMED_PAYLOAD,
    MAX_CLAIM_SUBJECT_CHARS,
    MAX_CLAIM_SUBJECTS,
    MINTED_NODE_KINDS,
    ChainReconstruction,
    SubstrateNode,
    SubstrateRefusal,
    SubstrateStore,
    digest_of,
    reconstruct_chain,
    write_node,
)
from hermes.methodology.workflows import (
    MethodologyConfig,
    MethodologyConfigError,
    MethodologyInputs,
    MethodologyRefusal,
    StageSpec,
)
from hermes.research.evidence_transitions import (
    EVIDENCE_REF_PREFIX,
    canonical_evidence_ref,
)
from hermes.research.grounding import GroundingVerdict, check_claim, figures_in
from hermes.tools.capabilities.content import ArtifactRead, read_content

__all__ = [
    "ADMISSION_BOUNDARY",
    "DURABILITY_GATE",
    "METHODOLOGY_COMPLETE",
    "AdmissionRef",
    "ClaimLimits",
    "GroundingRecord",
    "MethodologyExecution",
    "StageProjection",
    "StageRecord",
    "VerificationRecord",
    "claim_limits",
    "is_consequential",
    "parse_workflow",
    "preflight",
    "project_stage",
    "refuse_durable_claim",
    "run_methodology",
    "stage_projections",
]

#: The one durable write boundary every stage admission routes through — the
#: gateway's single mutation path. A stage's run proposes intents; the injected
#: ``IntentApplier`` applies them; in production that applier *is* ``apply_intent``
#: (``src/hermes/research/gateway.py``). The driver names it on every admission so
#: the mapping "which boundary admitted this stage" is explicit, not implied.
ADMISSION_BOUNDARY = "apply_intent"

#: The gate that durable substrate rows would need. Until it passes, a wired run
#: holds nodes/edges as derived working state only and claims no durable
#: substrate state, durable chain or durable node/edge reference.
DURABILITY_GATE = "docs/archive/ARCHITECTURE_DELTA.md §8 item 9"

#: The one termination value that means **the chain finished** (OPS-5M).
#:
#: :attr:`MethodologyExecution.termination` holds this value when, and only when,
#: the stage loop below ran to its end without breaking: every required stage of
#: the document was projected, consulted, run and recorded, and every recorded
#: stage's run reached ``SUCCEEDED``. A stage the document marks not-required is
#: skipped by design and does not affect it; a stage already recorded (an
#: idempotent resume) counts as run. Neither stops the loop.
#:
#: Every other value the field can hold means the loop **broke before the last
#: stage** — the chain is truncated. The field is assigned in exactly two places,
#: each immediately followed by that break:
#:
#: - ``STAGE_LIMIT`` — this driver's own value: ``termination.max_stages`` was
#:   reached before the next stage could run.
#: - the stopping stage run's own ``termination``, or its ``state`` when that run
#:   recorded none. In vocabulary that is any
#:   :class:`hermes.agents.runtime.types.Termination` member — ``PROPOSAL_LIMIT``,
#:   ``TICK_LIMIT``, ``NO_PROPOSALS``, ``STOP_WHEN``, ``CANCELLED``, ``TIMEOUT``,
#:   ``MODEL_REFUSED``, ``TOOL_FAILED``, ``PORT_FAILURE`` — or, for a run that
#:   ended without a reason, a terminal ``TaskStatus`` value (``FAILED``,
#:   ``CANCELLED``, ``SKIPPED``, ``INVALIDATED``, ``NO_SIGNAL``).
#:
#: None of those is legitimate *at this level*. A stage that stops early on
#: ``STOP_WHEN``, ``NO_PROPOSALS``, ``PROPOSAL_LIMIT`` or ``TICK_LIMIT`` and
#: still reaches ``SUCCEEDED`` is a stage that did its job: it is recorded, the
#: chain extends, and this field stays ``COMPLETE`` — a succeeded stage's own
#: termination never reaches it. Only a stage that did **not** succeed assigns
#: here, and a chain that stopped at a stage that did not succeed did not finish.
#:
#: A consumer must therefore test ``termination != METHODOLOGY_COMPLETE``, never
#: membership in a list of known failures: the predicate is an equality against
#: completion, so a termination value added to the runtime later fails closed
#: rather than passing as complete (the handler's OPS-5M gate).
METHODOLOGY_COMPLETE = "COMPLETE"


# ═══════════════════════ projection (stage → task) ═══════════════════════


@dataclass(frozen=True, slots=True)
class StageProjection:
    """One stage projected onto one task — the document, as a task context.

    Projection is a **pure derivation**: it reads the parsed workflow document
    and the caller's project/task/lease and produces the :class:`TaskContext` the
    stage will run under. It runs nothing, mints no identity and writes nothing;
    the task id is the run's own naming convention (``{task}:{stage}``), not an
    authored record id.
    """

    spec: StageSpec
    task_id: str
    project_id: str
    lease_generation: str
    predecessor_stage: str
    context: TaskContext

    @property
    def stage(self) -> str:
        """The declared stage kind (a chain kind, never free text)."""
        return self.spec.stage

    @property
    def profile(self) -> str:
        """The R4 profile the stage runs on."""
        return self.spec.profile

    @property
    def governance_action(self) -> str:
        """The governance action the stage declares — ``""`` when none."""
        return self.spec.governance_action

    @property
    def required(self) -> bool:
        """Whether the stage must run for the chain to continue."""
        return self.spec.required

    def to_mapping(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "profile": self.profile,
            "governance_action": self.governance_action,
            "required": self.required,
            "task_id": self.task_id,
            "project_id": self.project_id,
            "lease_generation": self.lease_generation,
            "predecessor_stage": self.predecessor_stage,
        }


def project_stage(
    config: MethodologyConfig,
    stage: StageSpec,
    *,
    project_id: str,
    task_id: str,
    lease_generation: str,
    predecessor_stage: str = "",
    inputs: MethodologyInputs | None = None,
) -> StageProjection:
    """Project one declared stage onto one task context — pure, no execution.

    The context carries the ``(project, task, lease)`` attribution, the
    stage's structural payload and — when the caller supplies the run's
    :class:`MethodologyInputs` — one ``runtime.task`` envelope holding the
    operator's question and the ref **ids** they supplied. That envelope is
    the OPS-7 seam: operator text reaches the model as untrusted content,
    origin-labelled, rather than only as a governance rationale.

    The recorded predecessor *node* is deliberately absent here (it is derived
    during the run and added by the driver), so the projection is a function of
    the document, the caller's inputs and the run's attribution alone — never
    of execution state.

    OPS-5F: the stage's own tick budget is projected as the context's
    ``max_ticks`` (a stage that declares none inherits the methodology-wide
    value), and a declared ``objective`` rides the stage-identity payload as
    untrusted, origin-labelled data — the existing ``runtime.payload`` port,
    no new origin, no second envelope. A stage without an objective adds no
    payload key at all.
    """
    stage_task_id = f"{task_id}:{stage.stage}"
    task_envelopes = ()
    if inputs is not None:
        task_envelopes = (task_input_envelope(
            task_id=stage_task_id,
            question=inputs.question,
            external_refs=inputs.external_refs,
            admission_refs=inputs.admission_refs),)
    payload: dict[str, Any] = {
        "stage": stage.stage,
        "methodology_id": config.methodology_id,
        "predecessor_stage": predecessor_stage,
    }
    if stage.objective is not None:
        payload["objective"] = stage.objective
    if methodology_plane._stage_requires_statement(stage.stage, inputs):
        # OPS-5Z: the same helper the plane driver uses, so the spine and the
        # plane cannot drift. `inputs=None` means the projection cannot see an
        # override, so a minting stage requires the statement.
        payload["requires_statement"] = True
    context = TaskContext(
        task_id=stage_task_id,
        project_id=project_id,
        lease_generation=lease_generation,
        context=task_envelopes,
        payload=payload,
        limits=config.termination.limits(stage.max_ticks))
    return StageProjection(
        spec=stage,
        task_id=stage_task_id,
        project_id=project_id,
        lease_generation=lease_generation,
        predecessor_stage=predecessor_stage,
        context=context)


def stage_projections(
    config: MethodologyConfig,
    *,
    project_id: str,
    task_id: str,
    lease_generation: str,
    inputs: MethodologyInputs | None = None,
) -> tuple[StageProjection, ...]:
    """Project every declared stage of a workflow document, in chain order.

    Deterministic and total: the same document, project, task, lease and
    inputs yield the same projections, and each projection names its declared
    predecessor stage (the first names none). The operator's task input is
    projected into every stage, so a later stage sees the question too. Nothing
    runs, so a caller can inspect the shape of a run before any plane is
    touched.
    """
    projections: list[StageProjection] = []
    predecessor_stage = ""
    for stage in config.stages:
        projections.append(project_stage(
            config, stage, project_id=project_id, task_id=task_id,
            lease_generation=lease_generation,
            predecessor_stage=predecessor_stage, inputs=inputs))
        predecessor_stage = stage.stage
    return tuple(projections)


def is_consequential(stage: StageSpec) -> bool:
    """True when a stage declares a governance action — it needs the preflight.

    A stage with no declared action is not gated by the governance plane and runs
    without a consult; a stage that declares one is *consequential* and is
    consulted before it runs.
    """
    return bool(stage.governance_action)


# ═══════════════════════ governance preflight (BIND-4 consult) ═════════════


def preflight(
    stage: StageSpec,
    inputs: MethodologyInputs,
    *,
    project_id: str,
    actor: str,
    rationale: str,
) -> tuple[str, MethodologyRefusal | None]:
    """Consult governance before the stage runs — read-only, refusal-as-data.

    Routed through the methodology plane's own per-stage preflight (its declared
    governance consumer), reused rather than forked so the verdict a stage sees
    here cannot drift from the one the plane's driver computes. Returns the
    verdict and, on a denial, the governance plane's own refusal — code verbatim,
    never translated.
    """
    return methodology_plane._governance_outcome(
        stage, inputs, project_id, actor, rationale)


# ═══════════════════════ result records ═══════════════════════


@dataclass(frozen=True, slots=True)
class AdmissionRef:
    """One stage's durable footprint: the boundary that admitted its intents."""

    stage: str
    boundary: str
    intents_applied: int

    def to_mapping(self) -> dict[str, Any]:
        return {"stage": self.stage, "boundary": self.boundary,
                "intents_applied": self.intents_applied}


@dataclass(frozen=True, slots=True)
class GroundingRecord:
    """What the deterministic claim gate said about the CLAIM stage's prose.

    OPS-5Z5: the caveat channel. ``SupportState.PARTIAL`` is a *model-declared*
    field on extraction drafts; it is not a channel a gate can write, and its
    values do not map ("partial support" is not "nothing was checked"). This
    record is the gate's own answer, produced from bytes: ``GROUNDED`` when
    every figure bound, ``CAVEATED`` when nothing checkable was asserted or the
    read fell back. A refusal never produces a record — it stops the run as a
    named ``MethodologyRefusal``.
    """

    verdict: str                     # "GROUNDED" | "CAVEATED"
    code: str = ""                   # the gate's caveat code, when caveated
    detail: str = ""

    def to_mapping(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "code": self.code,
                "detail": self.detail}


@dataclass(frozen=True, slots=True)
class VerificationRecord:
    """What one verification round did about a conflict (OPS-5Z Group E).

    ``status`` is the round's terminal answer: ``RESOLVED`` (one side is
    established by the fetched evidence), ``DISPUTED`` (neither side is, or
    the conflict persisted past the one-round bound) or ``REFUSED`` (the
    round could not run; ``code`` names why). ``conflict_kind``/``detail``
    name the conflict that caused the round — the journal's OPENED event
    carries the full object; this is the stage-visible summary.
    """

    status: str
    round_id: str = ""
    mode: str = ""
    winner_ref: str = ""
    code: str = ""
    detail: str = ""
    conflict_kind: str = ""
    conflict_detail: str = ""
    evidence_refs: tuple[str, ...] = ()

    def to_mapping(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "round_id": self.round_id,
            "mode": self.mode,
            "winner_ref": self.winner_ref,
            "code": self.code,
            "detail": self.detail,
            "conflict_kind": self.conflict_kind,
            "conflict_detail": self.conflict_detail,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True, slots=True)
class StageRecord:
    """One stage's result: the run's terminal state, its node and its admission.

    ``node_id`` is a derived ``mnode_`` id in the run's in-memory store — never a
    durable reference. ``admission_boundary`` names the existing write boundary
    the stage's ordinary intents reached.

    ``intents_applied`` is how many of this stage's proposals the spine recorded
    as a **new row** (OPS-5T). It is counted from the proposals' own admission
    records, never from a call counter: a refused proposal and a duplicate both
    reached the write path and neither created a row, so neither is an
    admission. ``intents_proposed``, ``intents_duplicate`` and
    ``intents_refused`` make the four numbers add up, and ``refusal_codes``
    carries the spine's own codes for the refused ones — so a zero-admission
    stage can say *why* it admitted nothing.
    """

    stage: str
    profile: str
    state: str
    termination: str
    run_id: str
    run_digest: str
    node_id: str
    governance: str
    lease_generation: str
    admission_boundary: str
    intents_applied: int
    intents_proposed: int
    intents_duplicate: int
    intents_refused: int
    refusal_codes: tuple[str, ...]
    aborted: bool
    #: ``"MINTED"`` for the three stages whose node content the run produces
    #: itself (OPS-5Y), empty otherwise. Included in the mapping only when
    #: non-empty, so every other stage record keeps its previous shape.
    content_origin: str = ""
    #: The evidence ref's backing class, carried by the stage that admitted it
    #: (OPS-5Y). Empty everywhere else, and omitted from the mapping when empty.
    backing_class: str = ""
    #: OPS-5Z5: the claim gate's verdict, carried only by the CLAIM stage.
    #: ``None`` everywhere else and omitted from the mapping when absent.
    grounding: GroundingRecord | None = None
    #: OPS-5Z Group E: the verification round opened on a conflict, carried by
    #: the stage that proposed it and by the CLAIM stage it examined. ``None``
    #: everywhere else and omitted from the mapping when absent.
    verification: VerificationRecord | None = None

    def to_mapping(self) -> dict[str, Any]:
        mapping = {
            "stage": self.stage,
            "profile": self.profile,
            "state": self.state,
            "termination": self.termination,
            "run_id": self.run_id,
            "run_digest": self.run_digest,
            "node_id": self.node_id,
            "governance": self.governance,
            "lease_generation": self.lease_generation,
            "admission_boundary": self.admission_boundary,
            "intents_applied": self.intents_applied,
            "intents_proposed": self.intents_proposed,
            "intents_duplicate": self.intents_duplicate,
            "intents_refused": self.intents_refused,
            "refusal_codes": list(self.refusal_codes),
            "aborted": self.aborted,
        }
        if self.content_origin:
            mapping["content_origin"] = self.content_origin
        if self.backing_class:
            mapping["backing_class"] = self.backing_class
        if self.grounding is not None:
            mapping["grounding"] = self.grounding.to_mapping()
        if self.verification is not None:
            mapping["verification"] = self.verification.to_mapping()
        return mapping


# ═══════════════════════ claim limits (§8 item 9) ═══════════════════════


@dataclass(frozen=True, slots=True)
class ClaimLimits:
    """What a wired methodology run may and may not claim (BIND-5).

    ``claimable`` is what the run's evidence actually establishes; ``not_claimable``
    is what would need the durability gate and is therefore not established by any
    wired run. ``may_claim`` is the single predicate both lists are read through.
    """

    claimable: tuple[str, ...]
    not_claimable: tuple[str, ...]
    gate: str

    def may_claim(self, claim: str) -> bool:
        return claim in self.claimable

    def to_mapping(self) -> dict[str, Any]:
        return {"claimable": list(self.claimable),
                "not_claimable": list(self.not_claimable),
                "gate": self.gate}


def claim_limits() -> ClaimLimits:
    """The fixed claim limits of a wired methodology run (BIND-5)."""
    return ClaimLimits(
        claimable=("stage_execution", "stage_outcomes", "stage_digests",
                   "admissions_via_apply_intent"),
        not_claimable=("durable_substrate_state", "durable_chain", "mnode_refs",
                       "medge_refs"),
        gate=DURABILITY_GATE)


def refuse_durable_claim(claim: str) -> MethodologyRefusal:
    """Refuse any durability claim beyond derived working state — as data.

    Durable substrate rows would need a table, an intent kind and a gateway
    validator (§8 item 9). This slice **refuses rather than implements** that
    gate, so a caller asking a wired run to establish a durable chain gets a
    refusal naming the gate — not a silently absent answer. The code is the
    plane's own shape refusal ``MALFORMED_PAYLOAD``: frozen vocabulary, no new
    code invented.
    """
    return MethodologyRefusal(
        code=MALFORMED_PAYLOAD,
        detail=(
            f"claim {claim!r} is not established by a wired methodology run: "
            f"durable substrate rows need the {DURABILITY_GATE} gate (a table, "
            f"an intent kind and a gateway validator); this driver holds nodes "
            f"and edges as derived in-process working state only"),
        source="claim-limits")


# ═══════════════════════ the run ═══════════════════════


@dataclass(frozen=True, slots=True)
class MethodologyExecution:
    """A whole wired run: derived substrate state, stage records, termination."""

    methodology_id: str
    version: str
    project_id: str
    task_id: str
    lease_generation: str
    store: SubstrateStore
    stages: tuple[StageRecord, ...]
    termination: str
    question_id: str = ""
    #: The stage whose run was attempted last, or whose run stopped the chain
    #: (OPS-5Y). On a complete run this is the last recorded stage.
    stage_reached: str = ""
    #: OPS-5Z: the runtime refusal that stopped the chain, when there was one.
    #: Empty on a complete run, and on a truncation that produced no refusal.
    refusal_code: str = ""
    refusal_detail: str = ""

    def reconstruction(self) -> ChainReconstruction | SubstrateRefusal:
        """Recompute the recorded chain from the derived store — a read.

        Pure recomputation on every call: nothing about the chain is cached, and
        the walk re-derives each stage's identity from its content, so a torn or
        forged record cannot reconstruct.
        """
        return reconstruct_chain(self.store, self.question_id)

    def admissions(self) -> tuple[AdmissionRef, ...]:
        """One admission reference per recorded stage, naming its boundary."""
        return tuple(
            AdmissionRef(stage=record.stage, boundary=record.admission_boundary,
                         intents_applied=record.intents_applied)
            for record in self.stages)

    def claim_limits(self) -> ClaimLimits:
        """The run's claim limits — what its evidence does and does not establish."""
        return claim_limits()

    def digest(self) -> str:
        """Deterministic digest of the run's derived state and stage records."""
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
            "task_id": self.task_id,
            "lease_generation": self.lease_generation,
            "stages": [stage.to_mapping() for stage in self.stages],
            "termination": self.termination,
            "question_id": self.question_id,
            **({"refusal_code": self.refusal_code}
               if self.refusal_code else {}),
            **({"refusal_detail": self.refusal_detail}
               if self.refusal_detail else {}),
        }


def parse_workflow(data: Mapping[str, Any]) -> MethodologyConfig | MethodologyRefusal:
    """Read a workflow document, mapping a load refusal to data.

    The plane's parser is fail-closed and raises for a document it cannot read;
    a spine-side driver returns refusal-as-data, so this maps the load failure to
    ``MALFORMED_PAYLOAD`` (the plane's own shape refusal) rather than letting an
    exception escape a boundary that reports everything else as data.
    """
    try:
        return methodology_plane.parse_methodology(data)
    except MethodologyConfigError as error:
        return MethodologyRefusal(code=MALFORMED_PAYLOAD, detail=str(error),
                                  source="parse")


def _admission_tally(proposals: tuple[Proposal, ...]
                     ) -> tuple[int, int, int, int]:
    """``(proposed, applied, duplicate, refused)`` — the spine's answers.

    OPS-5T: this is the only place a stage's durable footprint is counted, and
    it reads the admission record the runtime wrote on each proposal — the
    verdict `apply_intent` actually returned — rather than any counter that
    describes the call. ``applied`` counts ``ADMITTED`` alone: a ``DUPLICATE``
    is a replay of a row the spine already held (the identity matched, so this
    run added nothing), and a ``REFUSED`` is a call that wrote nothing at all.
    Both are counted separately so a zero-admission stage can say which of the
    two it was, instead of reporting a bare zero.
    """
    applied = duplicate = refused = 0
    for proposal in proposals:
        if proposal.admission == Admission.ADMITTED.value:
            applied += 1
        elif proposal.admission == Admission.DUPLICATE.value:
            duplicate += 1
        elif proposal.admission == Admission.REFUSED.value:
            refused += 1
    return len(proposals), applied, duplicate, refused


def _canonical_citation(ref: str) -> str | None:
    """The canonical ``evidence:<artifact_id>`` an admitted ref cites, or None.

    OPS-5L: the evidence selector's grammar. ``canonical_evidence_ref`` maps
    both spellings the gateway admits (``evidence:<id>`` / ``evidence/<id>``)
    and deliberately leaves the id to the gateway. A ref with no artifact id at
    all (``evidence:`` / ``evidence/``) names nothing to cite or to render, so
    it selects as *no* admitted ref — the run then stops at ``EVIDENCE`` on the
    substrate's own refusal — rather than raising in the next stage's
    ``runtime.evidence`` envelope. The real gateway never admits one (it
    refuses an empty id, ``MALFORMED_PAYLOAD``); this guards an injected
    applier. It is a shape check of a string, never an artifact-row check.
    """
    canonical = canonical_evidence_ref(ref)
    if canonical is None or canonical == EVIDENCE_REF_PREFIX:
        return None
    return canonical


#: A CLAIM's declared entities are bounded by the substrate's own node-field
#: limits (imported, not redefined): the driver validates before the node does.


def _claim_subjects(inputs: MethodologyInputs, statement: str,
                    ) -> tuple[str, ...] | MethodologyRefusal:
    """The validated subjects a CLAIM declares, or a named shape refusal.

    OPS-5Z5: subjects are a *field*, not a derivation. Deriving them from the
    claim would need entity recognition, and entity recognition is a model —
    exactly the authority the gate forbids. Deriving them from the artifact
    would say what the source is about, not what the claim's figures attach to.
    So the caller declares them (``stage_content["CLAIM"]["subjects"]``) and
    the gate binds only to names the claim itself contains: a figure-bearing
    claim with a subject it never names cannot bind, so accepting that pair
    would pretend to a check ``check_claim`` would not perform.

    A claim with no figure binds nothing. Its subjects are validated for shape
    but not recorded: declaring an entity a figure-free claim never mentions
    would be an inert name, and refusing the pair would refuse a correct
    qualitative claim for a field the gate cannot use either way.
    """
    override = inputs.stage_content.get("CLAIM")
    if not isinstance(override, Mapping):
        return ()
    supplied = override.get("subjects")
    if supplied is None:
        return ()
    if isinstance(supplied, str) or not isinstance(supplied, (list, tuple)):
        return MethodologyRefusal(
            code=MALFORMED_PAYLOAD,
            detail=("CLAIM subjects must be an array of strings, got "
                    f"{type(supplied).__name__}; a bare string names one "
                    "subject and is refused as a shape error"),
            stage="CLAIM", source="grounding")
    names: list[str] = []
    for item in supplied:
        if not isinstance(item, str) or not item.strip():
            return MethodologyRefusal(
                code=MALFORMED_PAYLOAD,
                detail=("CLAIM subjects must be non-empty strings; got "
                        f"{item!r}"),
                stage="CLAIM", source="grounding")
        name = item.strip()
        if len(name) > MAX_CLAIM_SUBJECT_CHARS:
            return MethodologyRefusal(
                code=MALFORMED_PAYLOAD,
                detail=(f"CLAIM subject {name[:40]!r}… is longer than "
                        f"{MAX_CLAIM_SUBJECT_CHARS} characters"),
                stage="CLAIM", source="grounding")
        if name not in names:
            names.append(name)
    if len(names) > MAX_CLAIM_SUBJECTS:
        return MethodologyRefusal(
            code=MALFORMED_PAYLOAD,
            detail=(f"a CLAIM may declare at most {MAX_CLAIM_SUBJECTS} "
                    f"subjects; got {len(names)}"),
            stage="CLAIM", source="grounding")
    if not figures_in(statement):
        return ()
    for name in names:
        if name.casefold() not in statement.casefold():
            return MethodologyRefusal(
                code=MALFORMED_PAYLOAD,
                detail=(f"CLAIM subject {name!r} does not occur in the "
                        "claim's statement; the gate can only bind a figure "
                        "to a subject the claim names"),
                stage="CLAIM", source="grounding")
    return tuple(names)


def _ground_claim(
    *,
    statement: str,
    inputs: MethodologyInputs,
    artifact: ArtifactRead | None,
) -> tuple[GroundingVerdict, tuple[str, ...]] | MethodologyRefusal:
    """Run the deterministic claim gate over the admitted artifact's content.

    ``artifact`` is the same read the evidence envelope used on this stage —
    one port, one read, so the gate cannot bind over different bytes than the
    model was shown. Its declared format dispatches the read; a fallback or an
    unreadable artifact is never mined. Neither a missing reader nor an
    unreadable artifact is a refusal of the claim: ``check_claim`` returns a
    named caveat, so the run records "nothing was checked" instead of passing
    it as checked. A figure the gate could not find is a refusal.

    OPS-5Z Group C: a partial read (a title whose abstract could not be
    reconstructed) is content for what it extracted, but the gate treats the
    artifact as not fully readable — the absent part may be exactly what the
    claim quotes, and blaming the claim for it would be a false refusal.
    """
    subjects = _claim_subjects(inputs, statement)
    if isinstance(subjects, MethodologyRefusal):
        return subjects
    artifact_text: str | None = None
    unreadable = ""
    if artifact is not None:
        read = read_content(artifact.data, format=artifact.format)
        if read.is_content and not read.detail:
            artifact_text = read.text
        else:
            unreadable = read.detail or (
                f"the content reader returned {read.state.value}")
    verdict = check_claim(statement, artifact_text, subjects=subjects,
                          unreadable_detail=unreadable)
    return verdict, subjects


def _grounding_refusal(
    verdict: GroundingVerdict, *,
    stages_recorded: int, stages_declared: int, backing_class: str,
) -> MethodologyRefusal:
    """A refused claim stops the chain as data, naming the gate's own code.

    The code travels verbatim from the gate's closed ``RefusalCode`` enum —
    the same pass-through discipline the governance preflight uses. The driver
    invents no code: ``assertion_not_found`` is the gate's answer, not this
    module's.
    """
    refusal = verdict.refusal.value if verdict.refusal is not None else "refused"
    return MethodologyRefusal(
        code=refusal,
        detail=(f"CLAIM refused by the grounding gate: {refusal}: "
                f"{verdict.detail}"),
        stage="CLAIM", source="grounding",
        stages_recorded=stages_recorded,
        stages_declared=stages_declared,
        backing_class=backing_class)


def _conflict_summary(payload: Mapping[str, Any]) -> tuple[str, str]:
    """The conflict's kind and detail, for the stage-visible summary."""
    conflict = payload.get("conflict")
    if not isinstance(conflict, Mapping):
        return "", ""
    return (str(conflict.get("kind") or ""),
            str(conflict.get("detail") or "")[:900])


def _verification_after_stage(
    *,
    wired: WiredRun,
    wiring: RuntimeWiring,
    project_id: str,
    verification_runner: Callable[
        [verification.VerificationRound],
        verification.VerificationOutcome] | None,
) -> VerificationRecord | None:
    """Run the round a stage just opened, and record its terminal outcome.

    The critic proposes; the gateway decides; the spine executes and records.
    A round proposal that was refused is not silently dropped: ``BUDGET`` (a
    claim already had its one round) becomes ``DISPUTED`` — the conflict
    persisted past the bound — and any other refusal is ``REFUSED`` with the
    spine's own code. An admitted round is executed through the injected
    runner (the capability plane's ``source_fetch``) and its outcome is
    recorded through the one mutation path as ``RECORD_VERIFICATION_OUTCOME``.
    """
    proposals = [
        proposal for proposal in wired.result.proposals
        if proposal.intent.kind is IntentKind.REQUEST_ADDITIONAL_EXPERIMENT]
    if not proposals:
        return None
    proposal = proposals[0]
    payload = (proposal.intent.payload
               if isinstance(proposal.intent.payload, Mapping) else {})
    conflict_kind, conflict_detail = _conflict_summary(payload)
    mode = str(payload.get("mode") or "")
    if not proposal.was_admitted():
        refusal = next(
            (item for item in reversed(wired.result.refusals)
             if item.kind == IntentKind.REQUEST_ADDITIONAL_EXPERIMENT.value),
            None)
        code = refusal.code if refusal is not None else "PROPOSAL"
        detail = (refusal.detail if refusal is not None
                  else proposal.admission_detail)
        return VerificationRecord(
            status=("DISPUTED" if code == "BUDGET" else "REFUSED"),
            mode=mode, code=code, detail=detail,
            conflict_kind=conflict_kind, conflict_detail=conflict_detail)
    round_id = proposal.admitted_entity_id
    try:
        round_ = verification.parse_round_payload(
            payload, project_id=project_id)
    except verification.VerificationError as exc:
        # The gateway admitted it, so this is a drift between the two
        # validators; fail closed as a refused round rather than run it.
        return VerificationRecord(
            status="REFUSED", round_id=round_id, mode=mode,
            code="MALFORMED_PAYLOAD", detail=str(exc),
            conflict_kind=conflict_kind, conflict_detail=conflict_detail)
    if verification_runner is None:
        outcome = verification.VerificationOutcome(
            status="REFUSED", code="NO_RUNNER",
            detail="no verification runner is wired; the round could not run")
    else:
        outcome = verification_runner(round_)
        if not isinstance(outcome, verification.VerificationOutcome):
            outcome = verification.VerificationOutcome(
                status="REFUSED", code="MALFORMED_PAYLOAD",
                detail="the verification runner returned no outcome")
    try:
        wiring.applier(Intent(
            kind=IntentKind.RECORD_VERIFICATION_OUTCOME,
            proposed_by=AgentProfile.DETERMINISTIC.value,
            project_id=project_id,
            payload=outcome.to_payload(round_id),
            justification=(
                f"verification round {round_id}: {outcome.status}; "
                f"conflict {conflict_kind}: {conflict_detail}")[:900],
            origin_kind="deterministic",
            # The round id is `vr_<64 hex>`; the provenance ref bound is 64,
            # so the record carries the content key without its kind prefix.
            origin_ref=round_id[len(verification.VERIFICATION_ROUND_PREFIX):]))
    except IntentRejectedError as exc:
        code = str(getattr(exc, "code", "") or "PROPOSAL")
        return VerificationRecord(
            status="REFUSED", round_id=round_id, mode=round_.mode,
            code=code,
            detail=(f"the round outcome could not be recorded "
                    f"({code}: {getattr(exc, 'reason', exc)})"),
            conflict_kind=conflict_kind, conflict_detail=conflict_detail,
            evidence_refs=outcome.evidence_refs)
    return VerificationRecord(
        status=outcome.status, round_id=round_id, mode=round_.mode,
        winner_ref=outcome.winner_ref, code=outcome.code,
        detail=outcome.detail,
        conflict_kind=conflict_kind, conflict_detail=conflict_detail,
        evidence_refs=outcome.evidence_refs)


def run_methodology(
    config: MethodologyConfig,
    inputs: MethodologyInputs,
    *,
    wiring: RuntimeWiring,
    project_id: str,
    task_id: str,
    actor: str = "methodology-driver",
    on_stage: Callable[[RuntimeWiring, Any], None] | None = None,
    project_index: ProjectIndexPort | None = None,
    provenance_of: Callable[[str, str], str | None] | None = None,
    artifact_reader: Callable[[str, str], bytes | ArtifactRead | None] | None = None,
    verification_runner: Callable[
        [verification.VerificationRound],
        verification.VerificationOutcome] | None = None,
) -> MethodologyExecution | MethodologyRefusal:
    """Drive one parsed workflow document through the W2 runtime wiring.

    Refusal is data at every layer and stops the run: a governance preflight
    denial returns the governance plane's own code (source ``"governance"``); a
    substrate write that fails closed returns the substrate code (source
    ``"substrate"``). A stage whose run does not reach ``SUCCEEDED`` is **not
    recorded** and does not extend the chain, so a run never reports ``COMPLETE``
    over a stage that did not run.

    ``termination`` is ``METHODOLOGY_COMPLETE`` only when the loop reached the
    document's last stage without breaking; every other value names why it broke
    early (the constant's own note is the closed definition). The two are
    different facts about the run — a truncated chain is still an *execution*,
    carrying the stages it did record — so this function returns the execution
    either way and leaves the verdict to its caller.

    OPS-18: when ``project_index`` is supplied, it is called once per stage —
    after the previous stage's committed admissions and before ``wiring.run`` —
    and its envelope is appended to the stage's context. The chain half of the
    index is read from this run's in-memory ``store``, never from a table; a
    fresh process therefore starts with no chain nodes (B-5). A provider that
    raises fails the stage: the index is never silently omitted.

    OPS-5D: the evidence position is agent-derived. A seed evidence ref is
    refused before any stage; an admitted ``EVIDENCE_TRANSITION`` in the
    OBSERVATION/EVIDENCE runs supplies the ``EVIDENCE`` node's ref. A run with
    no admitted transition stops at ``EVIDENCE`` rather than recording a
    synthetic ref.

    OPS-5Y: ``provenance_of`` is the composition-injected read-only port
    (``(project_id, ref) -> "FETCHED" | "ROW" | None``). Every
    ``admission_refs`` entry is registered before any stage, governance
    consult or model call and only with a backing the port reports; an
    unbacked entry is refused as data at intake. Omitted, every non-empty
    ``admission_refs`` refuses — fail closed.

    OPS-5Z3: ``artifact_reader`` is the composition-injected byte port
    ``(project_id, artifact_id) -> bytes | None``. When supplied, the
    ``runtime.evidence`` envelope carries a bounded excerpt of the admitted
    artifact, so the EVIDENCE stage can describe or quote what the chain
    actually fetched. Omitted, the envelope keeps its OPS-5L shape (ref and id
    only) — the reader is a pure lookup here, and this package still imports no
    persistence.

    OPS-5Z5: the same bytes feed the deterministic claim gate at the CLAIM
    stage. ``check_claim`` runs over ``read_content``'s rendering — the one
    content model — with the subjects the caller declared on the CLAIM draft.
    A refused claim is a named ``MethodologyRefusal`` carrying the gate's own
    refusal code, and the stage is not recorded; a caveat rides
    :class:`GroundingRecord` on the stage. A missing reader or an unreadable
    artifact is a caveat, never a silent pass: the gate says what it could not
    check.
    """
    seed_refusal = methodology_plane._seeded_evidence_refusal(inputs)
    if seed_refusal is not None:
        return replace(seed_refusal, stages_declared=len(config.stages))
    lease_generation = wiring.lease_generation
    store = SubstrateStore()
    for ref in inputs.admission_refs:
        refused = store.admit_ref(
            ref, project_id,
            backing=methodology_plane._resolved_backing(
                provenance_of, project_id, ref, witness="RESOLVER"))
        if refused is not None:
            return MethodologyRefusal(code=refused.code, detail=refused.detail,
                                      source="inputs",
                                      stages_declared=len(config.stages))
    for ref in inputs.retracted_refs:
        store.retract(ref)

    stages: list[StageRecord] = []
    question_id = ""
    predecessor_id = ""
    termination = METHODOLOGY_COMPLETE
    content_cache: dict[str, Mapping[str, Any]] = {}
    evidence_ref = ""
    evidence_proposal: Any = None
    stage_reached = ""
    refusal_code = ""
    refusal_detail = ""

    verification_records: list[dict[str, Any]] = []
    for projection in stage_projections(
            config, project_id=project_id, task_id=task_id,
            lease_generation=lease_generation, inputs=inputs):
        if (config.termination.max_stages
                and len(stages) >= config.termination.max_stages):
            stage_reached = projection.stage
            termination = "STAGE_LIMIT"
            break
        if not projection.required:
            continue
        existing = store.nodes_of_kind(projection.stage, project_id=project_id)
        if existing:
            # Idempotent by construction: a stage already recorded is not run
            # twice, and its node is the predecessor of the next stage.
            predecessor_id = existing[0][0]
            if projection.stage == "QUESTION":
                question_id = question_id or predecessor_id
            stage_reached = projection.stage
            continue

        # BIND-4 consult BEFORE the stage runs. A denial stops the run here —
        # the governance plane's own code travels verbatim, never a silent skip.
        governance, denial = preflight(
            projection.spec, inputs, project_id=project_id, actor=actor,
            rationale=inputs.question)
        if denial is not None:
            return replace(
                denial, stages_recorded=len(stages),
                stages_declared=len(config.stages),
                backing_class=methodology_plane._evidence_backing_class(
                    store, evidence_ref))

        context = projection.context
        if predecessor_id:
            context = context.with_changes(payload={
                **dict(context.payload),
                "predecessor": predecessor_id,
                "predecessor_content": dict(
                    content_cache.get(predecessor_id, {})),
            })
        if verification_records:
            # OPS-5Z Group E: a round that ran is a fact later stages must see.
            # The latest round's verdict rides the stage payload (untrusted,
            # like every other stage fact), so the conclusion can say what the
            # disputed claim became instead of reasoning over the chain alone.
            context = context.with_changes(payload={
                **dict(context.payload),
                "verification": verification_records[-1],
            })
        if project_index is not None:
            chain_nodes = tuple(
                ProjectIndexChainNode(
                    project_id=node.project_id, node_id=node_id, kind=node.kind)
                for node_id, node in sorted(store.nodes.items()))
            view = project_index(project_id, chain_nodes)
            context = context.with_changes(
                context=context.context
                + (project_index_envelope(project_id, view),))
        artifact: ArtifactRead | None = None
        read_failure = ""
        if evidence_ref:
            # OPS-5L: the run's admitted evidence fact, on its own origin. It is
            # appended only when a ref exists; before an admission there is no
            # envelope (never a "none" sentinel). The stage that admits the ref
            # cannot see it in its own prompt (the prompt predates the
            # admission); every later stage can, and the EVIDENCE stage must.
            #
            # OPS-5Z3: an id is not a source. When the composition wires the
            # byte reader, the envelope also carries a bounded excerpt of the
            # admitted artifact. The read is scoped to this project by the
            # port; the envelope's 4 KiB bound is independent of the artifact's
            # size.
            if artifact_reader is not None:
                fetched = artifact_reader(
                    project_id, evidence_ref.partition(":")[2])
                # OPS-5Z Group C: the port may carry the artifact's declared
                # format beside its bytes. A bare-bytes reader keeps working
                # (its artifact is undeclared, which reads as a fallback for a
                # serialization and as text for prose).
                if isinstance(fetched, ArtifactRead):
                    artifact = fetched
                elif isinstance(fetched, (bytes, bytearray, memoryview)):
                    artifact = ArtifactRead(data=bytes(fetched))
                if artifact is None:
                    # OPS-5Z5: a wired read that returned nothing is a failed
                    # read, not a ref-only envelope. Say so; otherwise the
                    # stage cannot tell "no source" from "not read".
                    read_failure = (
                        "the artifact's bytes could not be read in this "
                        "project")
            context = context.with_changes(
                context=context.context
                + (evidence_envelope(
                    task_id=context.task_id,
                    evidence_ref=evidence_ref,
                    artifact_bytes=(artifact.data
                                    if artifact is not None else None),
                    artifact_format=(artifact.format
                                     if artifact is not None else ""),
                    read_failure=read_failure),))
        wired: WiredRun = wiring.run(projection.profile, context)
        if on_stage is not None:
            # The surface is handed out, never interpreted here: the live
            # composition retains it and collects the vector after ctrl.run
            # (OPS-1 R3). A callback that raises must not turn a stage into a
            # failure, so the recorder is responsible for its own safety.
            on_stage(wiring, wired.result)
        # OPS-5T: the stage's durable footprint is what the spine *answered*,
        # read off the proposals' own admission records. The applier's call
        # counter is deliberately not consulted here: it says a call reached the
        # spine, not that a row appeared, and a counter named after an effect
        # may not be the evidence that the effect happened.
        proposed, applied, duplicate, refused = _admission_tally(
            wired.result.proposals)
        if wired.result.state != TaskStatus.SUCCEEDED.value:
            # The runtime's terminal state is authoritative. A stage whose run
            # did not succeed is not recorded and does not extend the chain: the
            # chain stops at the stage that did not run.
            stage_reached = projection.stage
            if wired.result.refusals:
                # OPS-5Z: the last refusal is the one that stopped this stage.
                # Carried out so the handler's reason can name it instead of
                # reporting only that the chain was truncated. Placed before
                # `termination` so the assignment stays adjacent to `break` —
                # the ops5m source scan encodes that adjacency.
                refusal_code = wired.result.refusals[-1].code
                refusal_detail = wired.result.refusals[-1].detail
            termination = wired.result.termination or wired.result.state
            break

        if projection.stage in methodology_plane._EVIDENCE_STAGES:
            selected = methodology_plane._admitted_evidence_proposal(
                wired.result.proposals,
                canonicalise=_canonical_citation)
            if selected is not None:
                evidence_proposal = selected
                evidence_ref = methodology_plane._evidence_ref_of(
                    selected, canonicalise=_canonical_citation)
                # Projection of the gateway's admission into the in-memory
                # registry the substrate's write boundary reads. Not a second
                # validation: the gateway already checked the artifact row.
                # OPS-5Y: the backing is GATEWAY-witnessed; the port supplies
                # only the FETCHED/ROW classification support reads.
                store.admit_ref(
                    evidence_ref, project_id,
                    backing=methodology_plane._evidence_backing(
                        provenance_of, project_id, evidence_ref))

        statement = methodology_plane._stage_prose(
            projection.stage, inputs, wired.result.proposals)
        # OPS-5Z5: the claim gate runs at the only live claim path, on the
        # content the model was shown, before the claim is recorded. A
        # refusal stops the chain here (the claim is not a node); a caveat is
        # recorded on the stage, never rendered as a pass.
        grounding: GroundingRecord | None = None
        subjects: tuple[str, ...] = ()
        if projection.stage == "CLAIM":
            verdict = _ground_claim(
                statement=statement, inputs=inputs, artifact=artifact)
            if isinstance(verdict, MethodologyRefusal):
                return replace(
                    verdict, stages_recorded=len(stages),
                    stages_declared=len(config.stages),
                    backing_class=methodology_plane._evidence_backing_class(
                        store, evidence_ref))
            grounding_verdict, subjects = verdict
            if grounding_verdict.refusal is not None:
                return _grounding_refusal(
                    grounding_verdict,
                    stages_recorded=len(stages),
                    stages_declared=len(config.stages),
                    backing_class=methodology_plane._evidence_backing_class(
                        store, evidence_ref))
            grounding = GroundingRecord(
                verdict=("GROUNDED" if grounding_verdict.grounded
                         else "CAVEATED"),
                code=(grounding_verdict.caveat.value
                      if grounding_verdict.caveat is not None else ""),
                detail=grounding_verdict.detail)

        content = dict(methodology_plane._default_content(
            projection.stage, inputs, predecessor_id, question_id,
            evidence_ref=evidence_ref, statement=statement))
        if projection.stage == "CLAIM":
            if subjects:
                # The one new CLAIM field (OPS-5Z5): the entities the gate
                # bound the claim's figures to. Validated by _claim_subjects
                # and again by the substrate's shape gate.
                content["subjects"] = subjects
            else:
                # A figure-free claim binds nothing; a shape-valid list the
                # gate did not use is not recorded as if it had. The override
                # itself may have carried it into ``content``.
                content.pop("subjects", None)
        if predecessor_id:
            content["predecessors"] = (predecessor_id,)
        node = SubstrateNode(
            kind=projection.stage,
            project_id=project_id,
            producing_task_id=context.task_id,
            content=content,
            rationale=methodology_plane._node_rationale(
                projection.stage, projection.stage, projection.profile,
                wired.result.proposals, evidence_proposal))
        recorded = write_node(store, node)
        if isinstance(recorded, SubstrateRefusal):
            return MethodologyRefusal(
                code=recorded.code, detail=recorded.detail,
                stage=projection.stage, source="substrate",
                stages_recorded=len(stages),
                stages_declared=len(config.stages),
                backing_class=methodology_plane._evidence_backing_class(
                    store, evidence_ref))
        node_id = recorded
        if projection.stage == "QUESTION":
            question_id = node_id
        content_cache[node_id] = content
        stages.append(StageRecord(
            stage=projection.stage,
            profile=projection.profile,
            state=wired.result.state,
            termination=wired.result.termination,
            run_id=wired.result.run_id,
            run_digest=wired.result.digest(),
            node_id=node_id,
            governance=governance,
            lease_generation=lease_generation,
            admission_boundary=ADMISSION_BOUNDARY,
            intents_applied=applied,
            intents_proposed=proposed,
            intents_duplicate=duplicate,
            intents_refused=refused,
            refusal_codes=wired.result.refusal_codes(),
            aborted=wired.aborted,
            content_origin=("MINTED" if projection.stage in MINTED_NODE_KINDS
                            else ""),
            backing_class=(methodology_plane._evidence_backing_class(
                store, evidence_ref)
                if projection.stage in methodology_plane._EVIDENCE_STAGES
                else ""),
            grounding=grounding))
        # OPS-5Z Group E: a stage's admitted verification round runs here,
        # after its node is recorded and before the next stage. The record is
        # carried by the stage that proposed it and by the CLAIM stage it
        # examined, so "the claim is disputed" is visible where the claim is.
        verification_record = _verification_after_stage(
            wired=wired, wiring=wiring, project_id=project_id,
            verification_runner=verification_runner)
        if verification_record is not None:
            stages[-1] = replace(stages[-1],
                                 verification=verification_record)
            for index in range(len(stages) - 1, -1, -1):
                if stages[index].stage == "CLAIM":
                    stages[index] = replace(
                        stages[index], verification=verification_record)
                    break
            verification_records.append(verification_record.to_mapping())
        stage_reached = projection.stage
        predecessor_id = node_id

    return MethodologyExecution(
        methodology_id=config.methodology_id,
        version=config.version,
        project_id=project_id,
        task_id=task_id,
        lease_generation=lease_generation,
        store=store,
        stages=tuple(stages),
        termination=termination,
        question_id=question_id,
        stage_reached=stage_reached,
        refusal_code=refusal_code,
        refusal_detail=refusal_detail)
