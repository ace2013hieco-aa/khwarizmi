"""Runtime wiring — the composed R4 driver for tick use (WIRING_DESIGN BIND-3).

`WIRING_DESIGN.md` BIND-3 asks one question: *how does an agent run/delegation
produce only proposals with B-2 discipline?* The runtime answers the plane half
(`src/hermes/agents/runtime/run.py`: bounded ticks, drafts validated against the
profile's allowlist, one intent emitted per draft through an injected
`IntentApplier`, checkpoints as derived state). This module is the **composition**
half: it builds the runtime, fixes what it is constructed with, and threads the
lease-generation attribution through every run it drives.

This is a new-files-only slice that **does not edit the controller**. The
controller call-site lands in W4; what this slice proves is the composition
itself — the dependency wiring, the store injection, and the lease fence.

Three rules the composition makes mechanical
--------------------------------------------
1. **`InMemory*` stores only.** `InMemoryCheckpointStore` and
   `InMemoryDelegationStore` are the only stores this wiring will inject, and it
   refuses anything else at construction (`WiringError`). A file-backed store is
   test-harness-only: each `put` is a durable per-run/per-delegation document
   write outside the repository transaction *and* outside the journal, so it is
   neither journal-scoped nor project-scoped — exactly the durable-derived-record
   prohibition BIND-3 names. The check is a positive allowlist over the in-memory
   implementations, so this module never imports, names or reaches a file store.
2. **One injection point, fenced.** The spine's `apply_intent` is injected
   through `FencedIntentApplier` (W4 connects the real one here). An intent is
   applied only while the lease fence is held; a mid-run lease loss lands as the
   spine's own `LOCK` via `LeaseLostRejection`, cancels every run watching the
   applier, and stops the work — no write happens after the loss.
3. **Attribution from the lease, never ambient (B-4).** The wiring carries the
   generation it acts under; a run whose context is attributed to a different
   generation is refused `LOCK` *before* anything is dispatched, and every
   record the plane produces (proposal, refusal, checkpoint, delegation, trace
   event) carries that same generation because the plane takes it from the
   context the wiring handed it.

What the wiring is not
----------------------
It is **not** a scheduler, a lease authority, or a second write path. It never
acquires, renews or releases a lease (custody is the controller's), opens no
transaction, and appends no journal row. Recovery is classification only: the
runtime's `recover` never re-dispatches.

Import discipline
-----------------
`hermes.agents.runtime.*`, `hermes.core` types, `hermes.tools.*` port shapes and
stdlib. Never `hermes.persistence`, never a repository, never SQL, never
`hermes.research`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from hermes.agents.runtime.checkpoint import (
    CheckpointStore,
    InMemoryCheckpointStore,
)
from hermes.agents.runtime.config import ProfileSpec
from hermes.agents.runtime.delegate import (
    ArtifactOverflowPort,
    DelegationStore,
    InMemoryDelegationStore,
)
from hermes.agents.runtime.run import (
    AgentRuntime,
    CapabilityPort,
    IntentApplier,
    ModelPort,
)
from hermes.agents.runtime.supervisor import RunCancelToken, Supervisor
from hermes.agents.runtime.types import (
    LOCK,
    Checkpoint,
    DelegationRecord,
    ProposalSet,
    RecoveryVerdict,
    RuntimeRefusal,
    TaskContext,
    TraceEvent,
)
from hermes.core import Clock, utc_now
from hermes.core.intents import Intent, IntentRejectedError
from hermes.core.task_status import TaskStatus
from hermes.tools.capabilities.types import ToolGrant

__all__ = [
    "LEASE_LOST_DETAIL",
    "FencedIntentApplier",
    "LeaseFence",
    "LeaseLostRejection",
    "RuntimeWiring",
    "WiredRun",
    "WiringError",
    "require_inmemory_checkpoints",
    "require_inmemory_delegations",
]

#: The detail a fence reports when it is lost without a caller-supplied reason.
LEASE_LOST_DETAIL = (
    "the run's lease generation was lost mid-run — the spine refuses the write "
    "(LOCK) and this process stops working the run (lock_lost)"
)


class WiringError(ValueError):
    """A composition error — a mis-wired runtime is refused, not tolerated.

    Not a refusal code: this is raised at wiring time, before any run exists, for
    a construction nobody should be able to make (a file-backed store, a fence
    with no attribution). The runtime's own refusals stay refusal-as-data.
    """


class LeaseLostRejection(IntentRejectedError):
    """The `LOCK` the lease fence raises when a mid-run loss meets a write.

    Mirrors `research/gateway.py:GatewayRejection`, which likewise subclasses
    ``IntentRejectedError`` and carries a stable ``code``: the runtime's
    ``_apply`` reads ``code`` off the rejection and forwards it verbatim when it
    is a member of the plane's frozen set — ``LOCK`` is — so a lease loss
    surfaces to the caller as ``LOCK``, never coerced to ``PROPOSAL``. No new
    code is introduced; this reuses the controller-emitted ``LOCK``.
    """

    code: str = LOCK


class LeaseFence:
    """The run's lease-generation tag plus its liveness — attribution, not custody.

    The fence never acquires, renews or releases anything: custody is the
    controller's (B-4). It records the generation this process acts under and
    whether that attribution is still live, which is the whole of what a plane
    may know about a lease. A blank generation is a composition error, because a
    fence with no attribution could not refuse anything.
    """

    def __init__(self, generation: str) -> None:
        if not generation.strip():
            raise WiringError(
                "a runtime wiring needs the lease generation it acts under "
                "(B-4) — a fence with no attribution could not refuse a write")
        self._generation = generation
        self._held = True
        self._detail = ""

    @property
    def generation(self) -> str:
        return self._generation

    @property
    def held(self) -> bool:
        return self._held

    @property
    def detail(self) -> str:
        return self._detail

    def lose(self, detail: str = "") -> None:
        """Record a mid-run lease loss. Custody was already someone else's."""
        self._held = False
        self._detail = detail or LEASE_LOST_DETAIL

    def require(self, intent: Intent) -> None:
        """Raise the spine's `LOCK` unless the fence is still held."""
        if not self._held:
            raise LeaseLostRejection(intent.kind, self._detail)


class FencedIntentApplier:
    """The `IntentApplier` injection point, fenced by the lease generation.

    Whatever the composition root injects — the real `apply_intent` in W4, a
    recording double in a test — one rule holds. An intent is applied only while
    the fence is held; a loss cancels every run watching this applier and then
    raises `LeaseLostRejection`, so the run stops and no write follows the loss.
    `writes`/`refusals` count what actually reached the spine, which is what
    makes "no partial rows after a loss" checkable.
    """

    def __init__(self, *, fence: LeaseFence, inner: IntentApplier) -> None:
        self._fence = fence
        self._inner = inner
        self._tokens: list[RunCancelToken] = []
        self.writes = 0
        self.refusals = 0

    @property
    def fence(self) -> LeaseFence:
        return self._fence

    def watch(self, token: RunCancelToken) -> None:
        """Register a run's cancel token to be cancelled if the lease is lost."""
        if all(item is not token for item in self._tokens):
            self._tokens.append(token)

    def unwatch(self, token: RunCancelToken) -> None:
        self._tokens = [item for item in self._tokens if item is not token]

    def __call__(self, intent: Intent) -> Any:
        if not self._fence.held:
            self.refusals += 1
            for token in tuple(self._tokens):
                token.cancel(self._fence.detail)
            self._fence.require(intent)  # raises LeaseLostRejection (LOCK)
        self.writes += 1
        return self._inner(intent)


@dataclass(frozen=True, slots=True)
class WiredRun:
    """One driven run: the plane's report plus the wiring's lease verdict.

    `result` is the runtime's `ProposalSet` **unmodified** — the wiring may not
    rewrite the plane's report. `aborted` is the wiring's own statement: this run
    is not a complete run, either because the lease generation it was dispatched
    under was lost before it finished, or because its attribution never matched
    the fence and nothing was dispatched at all. `spine_writes`/`spine_refusals`
    are what the fenced applier actually let through.
    """

    result: ProposalSet
    lease_generation: str
    lease_lost: bool
    aborted: bool
    spine_writes: int
    spine_refusals: int

    @property
    def state(self) -> str:
        return self.result.state

    @property
    def run_id(self) -> str:
        return self.result.run_id

    def refusal_codes(self) -> tuple[str, ...]:
        return self.result.refusal_codes()


def require_inmemory_checkpoints(store: CheckpointStore | None) -> CheckpointStore:
    """The checkpoint store the composition may use: in-memory, or nothing.

    A file-backed store is refused here rather than at its first `put`, because
    a wiring that could accept one would be a wiring that writes durable derived
    state outside `apply_intent` (BIND-3). The check is a positive allowlist: any
    store that is not the in-memory implementation — including one this module
    does not know about — is refused, named only by its class.
    """
    if store is None:
        return InMemoryCheckpointStore()
    if not isinstance(store, InMemoryCheckpointStore):
        raise WiringError(
            f"the runtime wiring injects InMemory stores only; got "
            f"{type(store).__name__} — a file-backed derived-state store is "
            f"test-harness-only (BIND-3: its put is a durable derived-document "
            f"write outside apply_intent, the journal and project scoping)")
    return store


def require_inmemory_delegations(store: DelegationStore | None) -> DelegationStore:
    """The delegation store the composition may use: in-memory, or nothing.

    Same rule and same reason as `require_inmemory_checkpoints`: `Delegator`'s
    records are derived working state, and a file-backed store's `put` is a
    durable derived-document write outside the one mutation path.
    """
    if store is None:
        return InMemoryDelegationStore()
    if not isinstance(store, InMemoryDelegationStore):
        raise WiringError(
            f"the runtime wiring injects InMemory stores only; got "
            f"{type(store).__name__} — a file-backed derived-record store is "
            f"test-harness-only (BIND-3: its put is a durable derived-document "
            f"write outside apply_intent, the journal and project scoping)")
    return store


class RuntimeWiring:
    """The composed runtime driver for one lease-held run (BIND-3).

    Construct one per composition root. `run` is the tick entry point: build a
    `TaskContext`, hand it over, read a `WiredRun`. The plane's read surfaces
    (`checkpoint`, `delegation_records`, `trace`, `recover`) are passed through
    so a caller never needs the runtime itself.
    """

    def __init__(
        self,
        *,
        model: ModelPort,
        orchestration: IntentApplier,
        lease_generation: str,
        profiles: Mapping[str, ProfileSpec] | None = None,
        grants: Mapping[str, ToolGrant] | None = None,
        capabilities: CapabilityPort | None = None,
        artifacts: ArtifactOverflowPort | None = None,
        clock: Clock = utc_now,
        supervisor: Supervisor | None = None,
        checkpoints: CheckpointStore | None = None,
        delegations: DelegationStore | None = None,
    ) -> None:
        self._fence = LeaseFence(lease_generation)
        self._applier = FencedIntentApplier(fence=self._fence,
                                            inner=orchestration)
        self._runtime = AgentRuntime(
            model=model,
            orchestration=self._applier,
            capabilities=capabilities,
            artifacts=artifacts,
            checkpoints=require_inmemory_checkpoints(checkpoints),
            delegations=require_inmemory_delegations(delegations),
            profiles=profiles,
            grants=grants,
            clock=clock,
            supervisor=supervisor,
        )

    # ── wiring surfaces ──

    @property
    def fence(self) -> LeaseFence:
        return self._fence

    @property
    def lease_generation(self) -> str:
        return self._fence.generation

    @property
    def applier(self) -> FencedIntentApplier:
        return self._applier

    def lose_lease(self, detail: str = "") -> None:
        """Record that this process no longer holds the run's lease."""
        self._fence.lose(detail)

    def profiles(self) -> Mapping[str, ProfileSpec]:
        return self._runtime.profiles

    def profile(self, name: str) -> ProfileSpec:
        return self._runtime.profile(name)

    def checkpoint(self, run_id: str) -> Checkpoint | None:
        return self._runtime.checkpoint(run_id)

    def delegation_records(self, *, run_id: str = "") -> tuple[DelegationRecord, ...]:
        return self._runtime.delegation_records(run_id=run_id)

    def trace(self, run_id: str) -> tuple[TraceEvent, ...]:
        return self._runtime.trace(run_id)

    def recover(self, run_id: str, *, now: str = ""
                ) -> tuple[RecoveryVerdict | None, Checkpoint | None]:
        """Classify an interrupted run — never re-dispatch (B-2)."""
        return self._runtime.recover(run_id, now=now)

    # ── the tick entry point ──

    def run(self, profile: str | ProfileSpec, task_context: TaskContext, *,
            token: RunCancelToken | None = None) -> WiredRun:
        """Drive one run under this wiring's lease generation."""
        refusal = self._attribution_refusal(profile, task_context)
        if refusal is not None:
            return self._without_dispatch(refusal, profile, task_context)
        active = token if token is not None else RunCancelToken()
        self._applier.watch(active)
        try:
            result = self._runtime.run(profile, task_context, token=active)
        finally:
            self._applier.unwatch(active)
        lease_lost = not self._fence.held
        return WiredRun(
            result=result,
            lease_generation=self._fence.generation,
            lease_lost=lease_lost,
            aborted=lease_lost,
            spine_writes=self._applier.writes,
            spine_refusals=self._applier.refusals,
        )

    # ── helpers ──

    def _attribution_refusal(self, profile: str | ProfileSpec,
                             context: TaskContext) -> RuntimeRefusal | None:
        """`LOCK` unless the context is attributed to the fence's generation.

        Attribution must match before anything is dispatched: a run tagged with
        another generation is another lease's run, and this process has no
        business driving it (a stale writer must not act on a recorded
        attribution, B-4).
        """
        if self._fence.held and context.lease_generation == self._fence.generation:
            return None
        detail = (
            f"run {_name_of(profile)!r} is attributed to lease generation "
            f"{context.lease_generation!r}, but this wiring acts under "
            f"{self._fence.generation!r}"
            + (" — and that lease has been lost" if not self._fence.held else "")
            + "; attribution must match before a run is dispatched (B-4)")
        return RuntimeRefusal(code=LOCK, detail=detail, profile=_name_of(profile),
                              lease_generation=self._fence.generation)

    def _without_dispatch(self, refusal: RuntimeRefusal, profile: str | ProfileSpec,
                          context: TaskContext) -> WiredRun:
        """A refused-before-dispatch result: no model call, no store, no write."""
        name = _name_of(profile)
        result = ProposalSet(
            run_id=context.resolved_run_id(name),
            profile=name,
            agent_profile="",
            task_id=context.task_id,
            project_id=context.project_id,
            lease_generation=self._fence.generation,
            state=TaskStatus.FAILED.value,
            termination=refusal.code,
            refusals=(refusal,),
        )
        return WiredRun(
            result=result,
            lease_generation=self._fence.generation,
            lease_lost=not self._fence.held,
            aborted=True,
            spine_writes=self._applier.writes,
            spine_refusals=self._applier.refusals,
        )


def _name_of(profile: str | ProfileSpec) -> str:
    return profile if isinstance(profile, str) else profile.name
