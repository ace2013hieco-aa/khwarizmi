"""Methodology execution driver — the W3 binding of BIND-5 over the W2 runtime.

`WIRING_DESIGN.md` BIND-5 asks one question: *how does a methodology run
orchestrate R4+R3+R2 and record only through existing boundaries?* This module is
the W3 answer — a **new-files-only** slice; it edits nothing that already exists
(including ``hermes.methodology.workflows`` and ``hermes.methodology.substrate``).

What the driver does, once per stage, in this order
---------------------------------------------------
1. **Projects** each stage of a parsed workflow document onto one task
   (``stage_projections`` / ``project_stage``): the stage's profile, its declared
   governance action and a :class:`TaskContext` whose lease generation is the
   wiring's own fence generation. Projection is pure data — no run, no model and
   no write happens here.
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
that boundary on every admission (``ADMISSION_BOUNDARY``) and counts what reached
it per stage; everything else it produces is working state.

Claim limits (BIND-5, §8 item 9)
--------------------------------
A wired methodology run may claim its **stage execution, stage outcomes/digests
and the durable admissions its proposals made through** ``apply_intent``. It may
**not** claim durable substrate state, a durable chain, or any ``mnode_``/``medge_``
reference readable after the process ends: that needs a table + an intent kind +
a gateway validator (the ``ARCHITECTURE_DELTA.md`` §8 item 9 gate), which this
slice refuses rather than implements (:func:`claim_limits` /
:func:`refuse_durable_claim`).

Import discipline
-----------------
``hermes.agents.runtime.wiring`` + ``.types`` (the W2 driver it binds),
``hermes.core.task_status``, the methodology plane's public surface
(``hermes.methodology.workflows``, whose declared preflight this exercises) and
``hermes.methodology.substrate`` (the derived-state boundary), plus stdlib.
Never ``hermes.persistence``, never a repository, never a raw connection or
transaction, and no new consumer of the governance plane.

Refusal vocabulary (frozen)
---------------------------
This module emits no code of its own: ``MALFORMED_PAYLOAD`` (the plane's own
shape/gate refusal, reused for a workflow-document load failure and for a
durability claim), and whatever :func:`preflight` or :func:`write_node` return,
which are their own frozen sets. No new code, kind, event or table is introduced
anywhere in this slice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from hermes.agents.runtime.types import TaskContext
from hermes.agents.runtime.wiring import RuntimeWiring, WiredRun
from hermes.core.task_status import TaskStatus
from hermes.methodology import workflows as methodology_plane
from hermes.methodology.substrate import (
    MALFORMED_PAYLOAD,
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

__all__ = [
    "ADMISSION_BOUNDARY",
    "DURABILITY_GATE",
    "AdmissionRef",
    "ClaimLimits",
    "MethodologyExecution",
    "StageProjection",
    "StageRecord",
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
DURABILITY_GATE = "ARCHITECTURE_DELTA.md §8 item 9"


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
) -> StageProjection:
    """Project one declared stage onto one task context — pure, no execution.

    The context carries the ``(project, task, lease)`` attribution and the
    stage's structural payload; the recorded predecessor *node* is deliberately
    absent here (it is derived during the run and added by the driver), so the
    projection is a function of the document alone.
    """
    stage_task_id = f"{task_id}:{stage.stage}"
    context = TaskContext(
        task_id=stage_task_id,
        project_id=project_id,
        lease_generation=lease_generation,
        payload={
            "stage": stage.stage,
            "methodology_id": config.methodology_id,
            "predecessor_stage": predecessor_stage,
        },
        limits=config.termination.limits())
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
) -> tuple[StageProjection, ...]:
    """Project every declared stage of a workflow document, in chain order.

    Deterministic and total: the same document, project, task and lease yield the
    same projections, and each projection names its declared predecessor stage
    (the first names none). Nothing runs, so a caller can inspect the shape of a
    run before any plane is touched.
    """
    projections: list[StageProjection] = []
    predecessor_stage = ""
    for stage in config.stages:
        projections.append(project_stage(
            config, stage, project_id=project_id, task_id=task_id,
            lease_generation=lease_generation,
            predecessor_stage=predecessor_stage))
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
class StageRecord:
    """One stage's result: the run's terminal state, its node and its admission.

    ``node_id`` is a derived ``mnode_`` id in the run's in-memory store — never a
    durable reference. ``admission_boundary`` names the existing write boundary
    the stage's ordinary intents reached; ``intents_applied`` is how many reached
    it for this stage.
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
    aborted: bool

    def to_mapping(self) -> dict[str, Any]:
        return {
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
            "aborted": self.aborted,
        }


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


def run_methodology(
    config: MethodologyConfig,
    inputs: MethodologyInputs,
    *,
    wiring: RuntimeWiring,
    project_id: str,
    task_id: str,
    actor: str = "methodology-driver",
) -> MethodologyExecution | MethodologyRefusal:
    """Drive one parsed workflow document through the W2 runtime wiring.

    Refusal is data at every layer and stops the run: a governance preflight
    denial returns the governance plane's own code (source ``"governance"``); a
    substrate write that fails closed returns the substrate code (source
    ``"substrate"``). A stage whose run does not reach ``SUCCEEDED`` is **not
    recorded** and does not extend the chain, so a run never reports ``COMPLETE``
    over a stage that did not run.
    """
    lease_generation = wiring.lease_generation
    store = SubstrateStore()
    for ref in inputs.admission_refs:
        store.admit_ref(ref, project_id)
    for ref in inputs.retracted_refs:
        store.retract(ref)

    stages: list[StageRecord] = []
    question_id = ""
    predecessor_id = ""
    termination = "COMPLETE"
    applied_so_far = 0
    content_cache: dict[str, Mapping[str, Any]] = {}

    for projection in stage_projections(
            config, project_id=project_id, task_id=task_id,
            lease_generation=lease_generation):
        if (config.termination.max_stages
                and len(stages) >= config.termination.max_stages):
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
            continue

        # BIND-4 consult BEFORE the stage runs. A denial stops the run here —
        # the governance plane's own code travels verbatim, never a silent skip.
        governance, denial = preflight(
            projection.spec, inputs, project_id=project_id, actor=actor,
            rationale=inputs.question)
        if denial is not None:
            return denial

        context = projection.context
        if predecessor_id:
            context = context.with_changes(payload={
                **dict(context.payload),
                "predecessor": predecessor_id,
                "predecessor_content": dict(
                    content_cache.get(predecessor_id, {})),
            })
        wired: WiredRun = wiring.run(projection.profile, context)
        applied = max(0, wired.spine_writes - applied_so_far)
        applied_so_far = max(applied_so_far, wired.spine_writes)

        if wired.result.state != TaskStatus.SUCCEEDED.value:
            # The runtime's terminal state is authoritative. A stage whose run
            # did not succeed is not recorded and does not extend the chain: the
            # chain stops at the stage that did not run.
            termination = wired.result.termination or wired.result.state
            break

        content = dict(methodology_plane._default_content(
            projection.stage, inputs, predecessor_id, question_id))
        if predecessor_id:
            content["predecessors"] = (predecessor_id,)
        node = SubstrateNode(
            kind=projection.stage,
            project_id=project_id,
            producing_task_id=context.task_id,
            content=content,
            rationale=f"stage {projection.stage} via profile "
                      f"{projection.profile}")
        recorded = write_node(store, node)
        if isinstance(recorded, SubstrateRefusal):
            return MethodologyRefusal(code=recorded.code, detail=recorded.detail,
                                      stage=projection.stage, source="substrate")
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
            aborted=wired.aborted))
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
        question_id=question_id)
