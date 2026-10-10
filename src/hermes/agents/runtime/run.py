"""The bounded agent loop — `run(profile, task_context) -> ProposalSet` (§2.3).

What a run is
-------------
One bounded piece of agent work:

1. resolve the profile **by name** from configuration (`config.py`) — there is no
   profile class anywhere in this package;
2. build one model request per tick through the Model plane port, with the
   profile's own output contract and the lease-generation tag;
3. turn the model's *validated* structured output into intent drafts, each one
   checked against the profile's declared authority (allowlist, internal-only
   partition, Director-only rule) and against the 4 KiB payload cap;
4. emit every surviving draft through the **Orchestration API** and record the
   verdict the spine returned;
5. do side-effectful things — capability calls, child runs — **only** as the
   profile's configuration declares, and only when the spine admitted the
   corresponding intent;
6. checkpoint before the first tick and after every tick, so a crash is a resume
   and not a restart.

Five rules, mechanically
------------------------
* **Nothing here decides a transition.** The runtime emits `Intent` proposals and
  reads back `admitted` / `duplicate` / `refused`. There is no repository, no
  connection, no SQL, no journal append anywhere in this package (§3.2: the
  journal writer stays `repositories.py:92`).
* **A profile proposes only inside its allowlist.** `ProfileSpec.refuses_by_authority`
  is the single rule, applied before any intent exists — an internal-only kind is
  refused even if a configuration declared it (the loader refuses that too, which
  is why it holds on both sides).
* **The model never supplies an identity.** `proposed_by`, `project_id`,
  `task_id` and `idempotency_key` are supplied or *derived by rule* here; a draft
  that tries to author any of them is refused (`MALFORMED_PAYLOAD`).
* **Bounds are honoured, never approached.** `max_ticks`, `max_proposals`,
  `max_tool_calls`, `max_model_calls_per_tick`, `deadline_seconds` and the
  delegation depth and child-run budget all stop the loop; the loop has no
  unbounded branch.
* **Attribution comes from the lease.** Every proposal, refusal, trace event,
  checkpoint and delegation record carries the run's `lease_generation`, taken
  from the injected `TaskContext` — never from a settable ambient variable (B-4).

The terminal act, and why it is never checkpointed early
-------------------------------------------------------
A run's terminal act is its review child run (when the profile declares one), and
it is the *last* thing a run does. Nothing terminal may be on record before it
completes: the loop therefore leaves its most recent checkpoint at an earlier tick
while the review is outstanding, so a crash inside the review resumes as a
**replay** of the terminating tick instead of as a no-op read of a run that never
actually finished. That is the same contract a mid-tick crash already has, and it
is what makes "kill it and resume" reproduce the uninterrupted terminal set at
every crash point rather than at most of them.

A cancel is observed in four places, never only at the top of a tick: before a
model call, before each capability call in a batch, whenever a tick is about to
report the run's stop, and after the terminal act (the review). A cancel that
lands during the run's last piece of work is therefore recorded as the run's
terminal state — a cancelled run is never reported as `SUCCEEDED`.

The wire shape a profile's contract expects:

```json
{"rationale": "<proposal-set rationale, contract-required>",
 "kind": "INSERT_TASK", "payload": {...},
 "proposals": [{"kind": "...", "rationale": "...", "payload": {...}}],
 "tool_calls": [{"capability_id": "...", "arguments": {...}, "rationale": "..."}],
 "delegations": [{"profile": "critic", "spec": {...}, "task_type": "AGENT_TASK"}]}
```

Either the single-proposal form (`kind` + `payload`) or the multi-proposal form
(`proposals`) — never both, and only the optional sections the profile declares
in `model_policy.structured_fields`. Tool calls and delegations are *top-level*:
they describe what the run asks for, not what a proposal is.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from hermes.agents.runtime.checkpoint import (
    CheckpointStore,
    InMemoryCheckpointStore,
)
from hermes.agents.runtime.config import (
    ProfileConfigError,
    ProfileSpec,
    load_profiles,
)
from hermes.agents.runtime.delegate import (
    ArtifactOverflowPort,
    DelegationStore,
    Delegator,
    InMemoryDelegationStore,
)
from hermes.agents.runtime.supervisor import (
    Monotonic,
    RetryBudget,
    RunCancelToken,
    Supervisor,
)
from hermes.agents.runtime.types import (
    LOCK,
    MALFORMED_PAYLOAD,
    MAX_PAYLOAD_BYTES,
    PROPOSAL,
    RATIONALE,
    ROLE,
    STALE,
    Admission,
    Checkpoint,
    DelegationRecord,
    DelegationState,
    Proposal,
    ProposalSet,
    RecoveryVerdict,
    RuntimeFormatError,
    RuntimeRefusal,
    TaskContext,
    Termination,
    TraceEvent,
    canonical_json,
    child_idempotency_key_of,
    child_task_id_of,
    digest_of,
    size_of,
    tool_idempotency_key_of,
)
from hermes.core import Clock, utc_now
from hermes.core.intents import Intent, IntentKind, IntentRejectedError
from hermes.core.task_status import TaskStatus
from hermes.security.boundaries import UntrustedContent
from hermes.tools.capabilities.types import (
    CapabilityRefusal,
    InvokeRequest,
    Observation,
    ToolGrant,
)
from hermes.tools.models.router import (
    FieldSpec,
    ModelProposal,
    ModelRefusal,
    ModelRequest,
    OutputContract,
)

#: A model refusal this plane retries. Only an *output-side* refusal is worth a
#: second call: a request-side `MALFORMED_PAYLOAD` is deterministic and would
#: fail identically (the R2 report makes the same split at the provider edge).
RETRYABLE_MODEL_REFUSALS: frozenset[str] = frozenset({RATIONALE})

#: Keys a draft, a tool call and a delegation item may carry. Closed schemas:
#: an unknown key is refused, never ignored.
DRAFT_KEYS: frozenset[str] = frozenset({"kind", "rationale", "payload"})
TOOL_CALL_KEYS: frozenset[str] = frozenset({"capability_id", "arguments",
                                            "rationale"})
DELEGATION_KEYS: frozenset[str] = frozenset({"profile", "spec", "task_type"})

#: Keys the runtime *derives*. A draft that supplies one is refused: §2.3 forbids
#: any plane from authoring — or trusting — an identity.
_AUTHORED_KEYS: frozenset[str] = frozenset({"proposed_by", "project_id",
                                            "task_id", "idempotency_key"})

#: Contract sections and the JSON types they may carry.
_CONTRACT_SECTIONS: Mapping[str, str] = {
    "proposals": "array",
    "tool_calls": "array",
    "delegations": "array",
}

#: Refusal codes the runtime forwards verbatim; anything else is mapped into this
#: plane's own set with the original code kept in the detail (see R4_REPORT
#: §"decisions a gate should rule on"). W4 extends the set with exactly one
#: member, the gateway's `OPERATOR` (an unratified operator credential, A4), so a
#: spine `OPERATOR` reaches the caller **verbatim** through `_apply` and
#: `_code_of` instead of being coerced to `PROPOSAL`. It is the same frozen
#: vocabulary the gateway declares (`research/gateway.py:120`), written as the
#: closed set's literal rather than imported: this plane may not import
#: `research/`, and the value is an existing code, never a new one. The
#: full-vocabulary pass-through stays a future R4-contract gate
#: (`WIRING_DESIGN.md` BIND-3 seam note).
_PLANE_REFUSAL_CODES: frozenset[str] = frozenset(
    {PROPOSAL, ROLE, MALFORMED_PAYLOAD, STALE, LOCK, RATIONALE, "OPERATOR"})


@runtime_checkable
class ModelPort(Protocol):
    """The Model plane's `invoke` (§2.1 operation 1) — proposals or refusals."""

    def invoke(self, request: ModelRequest) -> ModelProposal | ModelRefusal: ...


@runtime_checkable
class CapabilityPort(Protocol):
    """The Capability plane's `invoke` (§2.2 operation 2)."""

    def invoke(self, request: InvokeRequest) -> Observation | CapabilityRefusal: ...


@runtime_checkable
class IntentApplier(Protocol):
    """The Orchestration API's mutation entry point (`apply_intent`).

    The port is a callable so the spine can be injected without this package
    importing it: the runtime must not depend on `research/`, and the tests bind
    the real `apply_intent` to prove the wiring.
    """

    def __call__(self, intent: Intent) -> Any: ...


def output_contract_for(spec: ProfileSpec) -> OutputContract:
    """The profile's declared output contract, built from configuration."""
    fields = [
        FieldSpec(spec.model_policy.kind_field, "string", required=False),
        FieldSpec(spec.model_policy.rationale_field, "string"),
        FieldSpec("payload", "object", required=False),
    ]
    for section in spec.model_policy.structured_fields:
        field_type = _CONTRACT_SECTIONS.get(section)
        if field_type is None:
            raise ProfileConfigError(
                f"profile {spec.name!r} declares structured field {section!r}, "
                f"which is not one of {sorted(_CONTRACT_SECTIONS)}")
        fields.append(FieldSpec(section, field_type, required=False))
    return OutputContract(
        name=spec.model_policy.contract,
        fields=tuple(fields),
        kind_field=spec.model_policy.kind_field,
        rationale_field=spec.model_policy.rationale_field,
        allows_decision=False,
    )


@dataclass
class _RunState:
    """Mutable working state inside one `run()` call (never persisted as such)."""

    profile: str = ""
    lease_generation: str = ""
    tick: int = 0
    state: str = TaskStatus.RUNNING.value
    termination: str = ""
    proposals: list[Proposal] = field(default_factory=list)
    refusals: list[RuntimeRefusal] = field(default_factory=list)
    delegations: list[DelegationRecord] = field(default_factory=list)
    tool_calls: int = 0
    child_runs: int = 0
    seen_drafts: set[str] = field(default_factory=set)

    def refuse(self, code: str, detail: str, *, tick: int, kind: str = ""
               ) -> RuntimeRefusal:
        item = RuntimeRefusal(code=code, detail=detail, profile=self.profile,
                              tick=tick, lease_generation=self.lease_generation,
                              kind=kind)
        self.refusals.append(item)
        return item

    def terminate(self, state: str, termination: str) -> None:
        self.state = state
        self.termination = termination


class AgentRuntime:
    """One runtime, every profile: ports in, proposals out.

    Dependencies are injected and nothing is ambient: the model plane, the
    capability plane, the Orchestration API, the artifact port, the stores, the
    clock, the supervisor and the tool grants. A missing port is a *refusal*,
    never a silently degraded run.
    """

    def __init__(
        self,
        *,
        model: ModelPort,
        orchestration: IntentApplier,
        capabilities: CapabilityPort | None = None,
        artifacts: ArtifactOverflowPort | None = None,
        checkpoints: CheckpointStore | None = None,
        delegations: DelegationStore | None = None,
        profiles: Mapping[str, ProfileSpec] | None = None,
        grants: Mapping[str, ToolGrant] | None = None,
        clock: Clock = utc_now,
        monotonic: Monotonic | None = None,
        supervisor: Supervisor | None = None,
        retry: RetryBudget | None = None,
    ) -> None:
        self._model = model
        self._orchestration = orchestration
        self._capabilities = capabilities
        self._artifacts = artifacts
        self._checkpoints: CheckpointStore = (checkpoints if checkpoints is not None
                                              else InMemoryCheckpointStore())
        self._profiles = dict(profiles if profiles is not None
                              else load_profiles())
        self._grants = dict(grants or {})
        self._supervisor = supervisor if supervisor is not None else Supervisor(
            clock=clock, monotonic=monotonic, retry=retry)
        self._delegator = Delegator(
            store=delegations if delegations is not None
            else InMemoryDelegationStore(),
            profiles=self._profiles, clock=clock, artifacts=artifacts)

    # ── read surfaces ──

    @property
    def supervisor(self) -> Supervisor:
        return self._supervisor

    @property
    def profiles(self) -> Mapping[str, ProfileSpec]:
        return dict(self._profiles)

    def profile(self, name: str) -> ProfileSpec:
        spec = self._profiles.get(name)
        if spec is None:
            raise ProfileConfigError(
                f"profile {name!r} is not declared ({sorted(self._profiles)})")
        return spec

    def delegation_records(self, *, run_id: str = "") -> tuple[DelegationRecord, ...]:
        return self._delegator.records(run_id=run_id)

    def trace(self, run_id: str) -> tuple[TraceEvent, ...]:
        return self._supervisor.events(run_id)

    def checkpoint(self, run_id: str) -> Checkpoint | None:
        return self._checkpoints.get(run_id)

    # ── the run ──

    def run(self, profile: str | ProfileSpec, task_context: TaskContext, *,
            token: RunCancelToken | None = None) -> ProposalSet:
        """One bounded agent run: proposals only, nothing decided here."""
        spec = self._resolve_profile(profile)
        if spec is None:
            name = profile if isinstance(profile, str) else repr(profile)
            return self._refused_set(name, task_context, MALFORMED_PAYLOAD,
                                     f"profile {name!r} is not declared "
                                     f"({sorted(self._profiles)})")
        return self._run_spec(spec, task_context, token=token)

    def _run_spec(self, spec: ProfileSpec, context: TaskContext, *,
                  token: RunCancelToken | None = None,
                  state: _RunState | None = None,
                  start_tick: int = 1,
                  resumed_from_generation: str = "") -> ProposalSet:
        run_id = context.resolved_run_id(spec.name)
        working = state if state is not None else _RunState()
        working.profile = spec.name
        working.lease_generation = context.lease_generation
        resumed = start_tick > 1

        guard = self._validate_inputs(spec, context)
        if guard is not None:
            self._emit(kind="RUN_STARTED", run_id=run_id, tick=working.tick,
                       lease_generation=context.lease_generation,
                       detail={"profile": spec.name})
            working.refuse(guard, _guard_detail(guard, spec, context),
                           tick=working.tick)
            working.terminate(TaskStatus.FAILED.value, guard)
            self._close(spec, context, working, run_id, resumed_from_generation,
                        token=token)
            return self._assemble(spec, context, working, run_id,
                                  resumed_from_tick=start_tick - 1)

        self._emit(kind="RUN_RESUMED" if resumed else "RUN_STARTED", run_id=run_id,
                   tick=working.tick,
                   lease_generation=context.lease_generation,
                   detail={"profile": spec.name, "depth": context.depth,
                           "start_tick": start_tick})
        # The opening checkpoint: a crash during the first tick still leaves a
        # record to classify, which is what makes the NO_SIGNAL chain reachable.
        self._write_checkpoint(spec, context, working, run_id,
                               resumed_from_generation=resumed_from_generation)

        deadline = self._supervisor.deadline(
            context.limits.deadline_seconds
            if context.limits.deadline_seconds is not None
            else spec.termination.deadline_seconds)
        max_ticks = self._max_ticks(spec, context)
        for tick in range(start_tick, max_ticks + 1):
            working.tick = tick
            stop = self._tick(spec, context, working, run_id, tick, token, deadline)
            if (stop and working.state == TaskStatus.SUCCEEDED.value
                    and self._review_pending(spec, context, working)):
                # The terminal act (the review child run) has not happened yet, so
                # no terminal-shaped record may be written for this tick: a crash
                # inside the review must resume as a *replay* of the tick, not as
                # a no-op read of a run whose review never ran (R4 probe 1b).
                break
            self._write_checkpoint(spec, context, working, run_id,
                                   resumed_from_generation=resumed_from_generation)
            if stop:
                break
        else:
            working.terminate(TaskStatus.SUCCEEDED.value,
                              Termination.TICK_LIMIT.value)

        if working.termination == "":
            working.terminate(TaskStatus.SUCCEEDED.value,
                              Termination.TICK_LIMIT.value)
        self._close(spec, context, working, run_id, resumed_from_generation,
                    token=token)
        return self._assemble(spec, context, working, run_id,
                              resumed_from_tick=start_tick - 1)

    def _close(self, spec: ProfileSpec, context: TaskContext, state: _RunState,
               run_id: str, resumed_from_generation: str,
               token: RunCancelToken | None = None) -> None:
        """Review (when configured), then the terminal checkpoint.

        The review is the run's terminal act, so the cancel check brackets it: a
        cancel already observed skips it, and a cancel that lands *while* it runs
        becomes the run's terminal state — never a silent `SUCCEEDED`.
        """
        verdict = self._supervisor.check(token, None)
        if not verdict and state.state == TaskStatus.SUCCEEDED.value:
            self._maybe_review(spec, context, state, run_id, token=token)
            verdict = self._supervisor.check(token, None)
        if verdict and state.state == TaskStatus.SUCCEEDED.value:
            self._interrupt(state, state.tick, verdict,
                            detail=f"run {verdict.lower()} during the terminal act")
        self._emit(kind="RUN_TERMINATED", run_id=run_id, tick=state.tick,
                   lease_generation=context.lease_generation,
                   detail={"state": state.state, "termination": state.termination})
        self._write_checkpoint(spec, context, state, run_id, terminal=True,
                               resumed_from_generation=resumed_from_generation)

    # ── one tick ──

    def _interrupt(self, state: _RunState, tick: int, verdict: str, *,
                   detail: str) -> None:
        """Record a supervisor verdict as the run's terminal state.

        `Supervisor.check` answers `CANCELLED`, `TIMEOUT` or "go", and the first
        two map onto the two existing terminal states: no new vocabulary and no
        new authority — the run only reports *why* it stopped early (§2.3).
        """
        cancelled = verdict == "CANCELLED"
        state.refuse(PROPOSAL, detail, tick=tick)
        state.terminate(
            TaskStatus.CANCELLED.value if cancelled else TaskStatus.FAILED.value,
            (Termination.CANCELLED.value if cancelled
             else Termination.TIMEOUT.value))

    def _tick(self, spec: ProfileSpec, context: TaskContext, state: _RunState,
              run_id: str, tick: int, token: RunCancelToken | None,
              deadline: float | None) -> bool:
        """One bounded tick. Returns True when the run must stop."""
        self._emit(kind="TICK_STARTED", run_id=run_id, tick=tick,
                   lease_generation=context.lease_generation,
                   detail={"profile": spec.name})
        verdict = self._supervisor.check(token, deadline)
        if verdict:
            self._interrupt(
                state, tick, verdict,
                detail=f"run {verdict.lower()} before the tick made any call")
            return True

        produced = self._model_phase(spec, context, state, run_id, tick, token,
                                     deadline)
        if produced is None:
            return True
        structured, drafted = produced

        if not self._tool_phase(structured, spec, context, state, run_id, tick,
                                token):
            # A capability that failed (or was refused) stops the run: the state
            # says so, rather than falling through to the tick-limit SUCCEEDED.
            state.terminate(TaskStatus.FAILED.value, Termination.TOOL_FAILED.value)
            return True
        self._delegation_phase(structured, spec, context, state, run_id, tick,
                               token)

        raised = len(drafted)
        novel = sum(1 for digest in drafted if digest not in state.seen_drafts)
        state.seen_drafts.update(drafted)

        termination = self._tick_termination(spec, context, state, raised, novel)
        if termination is None:
            return False
        # The run is about to report its terminal state: a cancel (or a deadline
        # expiry) observed during this tick's work *is* that terminal state, never
        # a silent SUCCEEDED (R4 probe 3b).
        verdict = self._supervisor.check(token, deadline)
        if verdict:
            self._interrupt(
                state, tick, verdict,
                detail=f"run {verdict.lower()} during the tick's work")
            return True
        state.terminate(TaskStatus.SUCCEEDED.value, termination)
        return True

    def _tick_termination(self, spec: ProfileSpec, context: TaskContext,
                          state: _RunState, raised: int, novel: int
                          ) -> str | None:
        """Why this tick stops the run, or `None` when the run continues.

        One place, in precedence order, so every declared policy has a handler:
        `review_complete` is a real stop condition — the run stops once it has a
        proposal set for its declared review to consider (the review itself is the
        close act), instead of falling through to the tick limit with a
        configuration knob that does nothing (R4 probe 5d).
        """
        policy = spec.termination.stop_when
        if policy == "proposals_raised" and raised:
            return Termination.STOP_WHEN.value
        if policy == "no_proposals" and raised == 0:
            return Termination.NO_PROPOSALS.value
        if policy == "converged" and raised and novel == 0:
            return Termination.STOP_WHEN.value
        if policy == "review_complete" and raised:
            return Termination.STOP_WHEN.value
        if len(state.proposals) >= self._max_proposals(spec, context):
            return Termination.PROPOSAL_LIMIT.value
        return None

    def _model_phase(self, spec: ProfileSpec, context: TaskContext,
                     state: _RunState, run_id: str, tick: int,
                     token: RunCancelToken | None, deadline: float | None
                     ) -> tuple[Mapping[str, Any], tuple[str, ...]] | None:
        """Call the Model plane, validate the output, emit the drafts.

        Returns `(structured_output, draft_digests)` or `None` when the run must
        stop. A model refusal is data: it is recorded, and it ends the run.
        """
        verdict = self._supervisor.check(token, deadline)
        if verdict:
            self._interrupt(
                state, tick, verdict,
                detail=f"run {verdict.lower()} before the model call")
            return None

        call_budget = max(1, spec.termination.max_model_calls_per_tick)
        budget = RetryBudget(
            max_retries=min(self._supervisor.retry.max_retries, call_budget - 1),
            base_delay_seconds=self._supervisor.retry.base_delay_seconds)
        request = self._model_request(spec, context, tick)
        self._emit(kind="MODEL_REQUESTED", run_id=run_id, tick=tick,
                   lease_generation=context.lease_generation,
                   detail={"tier": spec.model_policy.tier,
                           "call_budget": call_budget})
        result, attempts = self._supervisor.attempt(
            lambda attempt: self._model.invoke(request),
            retryable=lambda item: (isinstance(item, ModelRefusal)
                                    and item.code in RETRYABLE_MODEL_REFUSALS),
            budget=budget)

        if isinstance(result, ModelRefusal):
            state.refuse(result.code, f"model refusal: {result.detail}", tick=tick)
            self._emit(kind="MODEL_REFUSED", run_id=run_id, tick=tick,
                       lease_generation=context.lease_generation,
                       detail={"code": result.code, "attempts": list(attempts)})
            state.terminate(TaskStatus.FAILED.value,
                            Termination.MODEL_REFUSED.value)
            return None

        if not isinstance(result, ModelProposal):
            state.refuse(MALFORMED_PAYLOAD,
                         f"the model port returned {type(result).__name__}, which "
                         f"is neither a proposal nor a refusal", tick=tick)
            state.terminate(TaskStatus.FAILED.value, Termination.PORT_FAILURE.value)
            return None

        if result.overflow is not None:
            reference = ""
            if self._artifacts is not None:
                reference = self._artifacts.store(
                    result.overflow.body,
                    media_type=result.overflow.media_type)
            state.refuse(
                RATIONALE,
                f"the model proposal exceeded the {MAX_PAYLOAD_BYTES}-byte cap "
                f"({result.overflow.size_bytes} bytes)"
                + (f"; body preserved as {reference}" if reference
                   else "; no artifact overflow port is wired, so the body is not "
                        "preserved")
                + " — an overflowed body is not parsed",
                tick=tick)
            state.terminate(TaskStatus.FAILED.value,
                            Termination.MODEL_REFUSED.value)
            return None

        structured = dict(result.structured)
        model_ref = f"{result.provider_id}:{result.model_id}"
        drafted = self._emit_drafts(structured, spec, context, state, run_id,
                                    tick, model_ref)
        return structured, drafted

    def _emit_drafts(self, structured: Mapping[str, Any], spec: ProfileSpec,
                     context: TaskContext, state: _RunState, run_id: str, tick: int,
                     model_ref: str) -> tuple[str, ...]:
        """Validate every draft, then emit the survivors as intents."""
        drafts, refusals = self._validate_drafts(structured, spec, context, tick)
        for refusal in refusals:
            state.refusals.append(refusal)
            self._emit(kind="PROPOSAL_REFUSED", run_id=run_id, tick=tick,
                       lease_generation=context.lease_generation,
                       detail={"code": refusal.code, "kind": refusal.kind})
        digests: list[str] = []
        for kind, rationale, payload, artifact_ref in drafts:
            self._emit(kind="PROPOSAL_DRAFTED", run_id=run_id, tick=tick,
                       lease_generation=context.lease_generation,
                       detail={"kind": kind.value, "model": model_ref})
            intent = Intent(kind=kind, proposed_by=spec.agent_profile,
                            project_id=context.project_id, payload=payload,
                            justification=rationale)
            payload_size = size_of(intent.payload)
            if payload_size > MAX_PAYLOAD_BYTES:
                reference = ""
                if self._artifacts is not None:
                    reference = self._artifacts.store(
                        canonical_json(intent.payload).encode("utf-8"),
                        media_type="application/json")
                refusal = state.refuse(
                    RATIONALE,
                    f"{kind.value} payload is {payload_size} bytes, over the "
                    f"{MAX_PAYLOAD_BYTES}-byte cap"
                    + (f" (preserved as {reference})" if reference else "")
                    + " — the plane will not hand the spine a payload it would have "
                      "to truncate",
                    tick=tick, kind=kind.value)
                self._emit(kind="PROPOSAL_REFUSED", run_id=run_id, tick=tick,
                           lease_generation=context.lease_generation,
                           detail={"code": refusal.code, "kind": kind.value})
                continue
            proposal = self._emit_intent(intent, rationale, spec, context, state,
                                        run_id, tick, model_ref, artifact_ref)
            state.proposals.append(proposal)
            digests.append(proposal.draft_digest())
        return tuple(digests)

    def _validate_drafts(self, structured: Mapping[str, Any], spec: ProfileSpec,
                         context: TaskContext, tick: int
                         ) -> tuple[list[tuple[IntentKind, str, dict[str, Any], str]],
                                    list[RuntimeRefusal]]:
        """The draft schema plus the profile authority rule, in one place."""
        refusals: list[RuntimeRefusal] = []

        def refuse(code: str, detail: str, *, kind: str = "") -> None:
            refusals.append(RuntimeRefusal(
                code=code, detail=detail, profile=spec.name, tick=tick,
                lease_generation=context.lease_generation, kind=kind))

        allowed = {"kind", "rationale", "payload"} | set(
            spec.model_policy.structured_fields)
        unknown = sorted(set(structured) - allowed)
        if unknown:
            refuse(MALFORMED_PAYLOAD,
                   f"the model output declares keys this profile does not accept: "
                   f"{unknown} (allowed: {sorted(allowed)})")
            return [], refusals
        if structured.get("proposals") is not None and structured.get("kind"):
            refuse(MALFORMED_PAYLOAD,
                   "the model output carries both the single-proposal and the "
                   "multi-proposal form — exactly one is allowed")
            return [], refusals
        if structured.get("proposals") is not None:
            items = structured["proposals"]
            if not isinstance(items, list):
                refuse(MALFORMED_PAYLOAD,
                       f"proposals must be a list, got {type(items).__name__}")
                return [], refusals
        elif structured.get("kind"):
            items = [{key: structured[key] for key in DRAFT_KEYS
                      if key in structured}]
        else:
            return [], refusals

        drafts: list[tuple[IntentKind, str, dict[str, Any], str]] = []
        for position, item in enumerate(items):
            if not isinstance(item, Mapping):
                refuse(MALFORMED_PAYLOAD,
                       f"proposal {position} is {type(item).__name__}, not a "
                       f"mapping")
                continue
            unknown_item = sorted(set(item) - DRAFT_KEYS)
            if unknown_item:
                refuse(MALFORMED_PAYLOAD,
                       f"proposal {position} declares unknown keys: {unknown_item}")
                continue
            kind_name = item.get("kind")
            if not isinstance(kind_name, str) or not kind_name:
                refuse(MALFORMED_PAYLOAD, f"proposal {position} needs a kind")
                continue
            try:
                kind = IntentKind(kind_name)
            except ValueError:
                refuse(MALFORMED_PAYLOAD,
                       f"proposal {position} names {kind_name!r}, which is not an "
                       f"IntentKind", kind=kind_name)
                continue
            refusal = spec.refuses_by_authority(kind)
            if refusal:
                # The *reason* picks the code: a kind the profile declared as
                # needing a bound HumanDecisionReceived is a PROPOSAL this plane
                # can never make (§2.3); anything else is a ROLE partition breach.
                code = (PROPOSAL
                        if kind.value in spec.authority.requires_human_for
                        else ROLE)
                refuse(code, refusal, kind=kind.value)
                continue
            rationale = item.get("rationale")
            if not isinstance(rationale, str) or not rationale.strip():
                refuse(RATIONALE, f"proposal {position} carries no rationale",
                       kind=kind.value)
                continue
            payload = item.get("payload")
            if payload is None:
                payload = {}
            if not isinstance(payload, Mapping):
                refuse(MALFORMED_PAYLOAD,
                       f"proposal {position} payload is {type(payload).__name__}, "
                       f"not a mapping", kind=kind.value)
                continue
            built, artifact_ref = self._derive_payload(kind, dict(payload), context,
                                                      spec, len(drafts))
            if built is None and artifact_ref:
                refuse(RATIONALE,
                       f"{kind.value} payload is over the {MAX_PAYLOAD_BYTES}-byte "
                       f"cap; the body is preserved as {artifact_ref} rather than "
                       f"truncated, and the draft is refused so the spine never "
                       f"sees a partial command", kind=kind.value)
                continue
            if built is None:
                authored = sorted(set(payload) & _AUTHORED_KEYS)
                if not authored:
                    refuse(RATIONALE,
                           f"{kind.value} payload is over the {MAX_PAYLOAD_BYTES}-"
                           f"byte cap and no artifact overflow port is wired — "
                           f"refused rather than truncated", kind=kind.value)
                    continue
                refuse(MALFORMED_PAYLOAD,
                       f"proposal {position} supplies the derived key(s) "
                       f"{authored} — identity is derived by rule at the write "
                       f"boundary, never authored", kind=kind.value)
                continue
            drafts.append((kind, rationale, built, artifact_ref))
        return drafts, refusals

    def _derive_payload(self, kind: IntentKind, payload: dict[str, Any],
                        context: TaskContext, spec: ProfileSpec, slot: int
                        ) -> tuple[dict[str, Any] | None, str]:
        """Supply (or derive) the identity fields a kind needs — never accept one.

        Only `INSERT_TASK` carries identity fields, and `NodeContract` states the
        idempotency key is a digest of spec + inputs. So the runtime derives both
        from the delegating command: deterministic, so a re-emitted command
        collides with its own earlier admission instead of creating a second task.
        Returns `(payload, artifact_ref)`, or `(None, artifact_ref)` when the
        draft authored an identity field or when the derived payload does not fit
        the cap (refused rather than handed over partially).
        """
        if kind is not IntentKind.INSERT_TASK:
            return payload, ""
        if set(payload) & _AUTHORED_KEYS:
            return None, ""
        payload.setdefault("task_type", "AGENT_TASK")
        payload.setdefault("profile", spec.agent_profile)
        payload["task_id"] = child_task_id_of(context.task_id, spec.name, slot)
        payload["idempotency_key"] = child_idempotency_key_of(
            context.task_id, spec.name, slot, payload)
        if size_of(payload) > MAX_PAYLOAD_BYTES:
            reference = ""
            if self._artifacts is not None:
                reference = self._artifacts.store(
                    canonical_json(payload).encode("utf-8"),
                    media_type="application/json")
            # Never hand the spine a partial command: the derived identity fields
            # travel with the body, so a payload that does not fit is refused —
            # with the body preserved as an artifact — rather than emptied.
            return None, reference
        return payload, ""

    def _emit_intent(self, intent: Intent, rationale: str, spec: ProfileSpec,
                     context: TaskContext, state: _RunState, run_id: str, tick: int,
                     model_ref: str, artifact_ref: str) -> Proposal:
        """Emit one intent through the Orchestration API and record its verdict."""
        self._emit(kind="INTENT_EMITTED", run_id=run_id, tick=tick,
                   lease_generation=context.lease_generation,
                   detail={"kind": intent.kind.value})
        admission, detail, entity_id = self._apply(intent)
        self._emit(
            kind={"ADMITTED": "INTENT_ADMITTED", "DUPLICATE": "INTENT_DUPLICATE",
                  "REFUSED": "INTENT_REFUSED"}[admission],
            run_id=run_id, tick=tick,
            lease_generation=context.lease_generation,
            detail={"kind": intent.kind.value, "entity_id": entity_id,
                    "detail": detail})
        if admission == Admission.REFUSED.value:
            state.refuse(_code_of(detail), detail or "the spine refused the intent",
                         tick=tick, kind=intent.kind.value)
        return Proposal(
            intent=intent,
            rationale=rationale,
            tick=tick,
            profile=spec.name,
            agent_profile=spec.agent_profile,
            lease_generation=context.lease_generation,
            model=model_ref,
            artifact_ref=artifact_ref,
            admission=admission,
            admission_detail=detail,
            admitted_entity_id=entity_id,
        )

    def _apply(self, intent: Intent) -> tuple[str, str, str]:
        """`apply_intent` through the port: verdict as data, never an exception."""
        try:
            result = self._orchestration(intent)
        except IntentRejectedError as exc:
            original = str(getattr(exc, "code", "") or "")
            code = original if original in _PLANE_REFUSAL_CODES else PROPOSAL
            detail = str(getattr(exc, "reason", "") or exc)
            if original and original != code:
                # Keep the spine's own code visible: the plane's vocabulary is
                # closed, but the operator must still see *why* it refused.
                detail = f"{detail} (spine code {original})"
            return Admission.REFUSED.value, f"{code}: {detail}", ""
        entity_id = str(getattr(result, "entity_id", "") or "")
        duplicate = bool(getattr(result, "duplicate", False))
        return (Admission.DUPLICATE.value if duplicate else Admission.ADMITTED.value,
                "", entity_id)

    # ── tools ──

    def _tool_phase(self, structured: Mapping[str, Any], spec: ProfileSpec,
                    context: TaskContext, state: _RunState, run_id: str,
                    tick: int, token: RunCancelToken | None = None) -> bool:
        """Run the declared capability calls. False stops the run.

        A cancel that lands mid-batch stops the batch: no further capability call
        starts once the cancel is observed (R4 probe 3b).
        """
        items = structured.get("tool_calls")
        if not items:
            return True
        if not isinstance(items, list) or not all(isinstance(item, Mapping)
                                                  for item in items):
            state.refuse(MALFORMED_PAYLOAD,
                         f"tool_calls must be a list of mappings, got "
                         f"{type(items).__name__}", tick=tick)
            return True
        bound = context.limits.max_tool_calls or spec.termination.max_tool_calls
        if len(items) > bound:
            state.refuse(MALFORMED_PAYLOAD,
                         f"{len(items)} tool calls declared against a bound of "
                         f"{bound} — the batch is refused whole, nothing runs",
                         tick=tick)
            return True
        for item in items:
            unknown = sorted(set(item) - TOOL_CALL_KEYS)
            if unknown:
                state.refuse(MALFORMED_PAYLOAD,
                             f"a tool call declares unknown keys: {unknown}",
                             tick=tick)
                return True
        for index, item in enumerate(items):
            if token is not None and token.cancelled:
                # The batch stops here; the tick's teardown records the
                # cancellation as the run's terminal state.
                break
            if not self._one_tool_call(item, index, spec, context, state, run_id,
                                       tick):
                return False
        return True

    def _one_tool_call(self, item: Mapping[str, Any], index: int,
                       spec: ProfileSpec, context: TaskContext, state: _RunState,
                       run_id: str, tick: int) -> bool:
        capability_id = str(item.get("capability_id", ""))
        if not capability_id:
            state.refuse(MALFORMED_PAYLOAD, "a tool call needs a capability_id",
                         tick=tick)
            return False
        self._emit(kind="TOOL_REQUESTED", run_id=run_id, tick=tick,
                   lease_generation=context.lease_generation,
                   detail={"capability_id": capability_id})
        if capability_id not in spec.tools:
            refusal = state.refuse(
                ROLE,
                f"capability {capability_id!r} is outside {spec.name}'s declared "
                f"tools ({list(spec.tools)})", tick=tick)
            self._emit(kind="TOOL_SKIPPED", run_id=run_id, tick=tick,
                       lease_generation=context.lease_generation,
                       detail={"capability_id": capability_id, "code": refusal.code})
            return True
        if self._capabilities is None:
            refusal = state.refuse(
                ROLE, "no capability port is wired — the call is refused rather "
                      "than executed ungated", tick=tick)
            self._emit(kind="TOOL_SKIPPED", run_id=run_id, tick=tick,
                       lease_generation=context.lease_generation,
                       detail={"capability_id": capability_id, "code": refusal.code})
            return True
        arguments = item.get("arguments") or {}
        if not isinstance(arguments, Mapping):
            state.refuse(MALFORMED_PAYLOAD, "tool call arguments must be a mapping",
                         tick=tick)
            return False
        request = InvokeRequest(
            capability_id=capability_id,
            arguments=dict(arguments),
            idempotency_key=tool_idempotency_key_of(run_id, tick, index,
                                                    capability_id),
            lease_generation=context.lease_generation,
            profile=spec.agent_profile,
            rationale=str(item.get("rationale") or spec.role),
            grant=self._grants.get(spec.agent_profile),
        )
        result = self._capabilities.invoke(request)
        state.tool_calls += 1
        if isinstance(result, CapabilityRefusal):
            code = (result.code if result.code in _PLANE_REFUSAL_CODES
                    else MALFORMED_PAYLOAD)
            state.refuse(
                code,
                f"capability plane refused {capability_id!r} with {result.code}: "
                f"{result.detail}", tick=tick)
            self._emit(kind="TOOL_FAILED", run_id=run_id, tick=tick,
                       lease_generation=context.lease_generation,
                       detail={"capability_id": capability_id, "code": result.code})
            return False
        if not isinstance(result, Observation) or not result.ok():
            failure = getattr(result, "failure", None)
            detail = getattr(result, "detail", "")
            state.refuse(
                MALFORMED_PAYLOAD,
                f"capability {capability_id!r} failed "
                f"({getattr(failure, 'value', failure)}): {detail}", tick=tick)
            self._emit(kind="TOOL_FAILED", run_id=run_id, tick=tick,
                       lease_generation=context.lease_generation,
                       detail={"capability_id": capability_id,
                               "failure": str(getattr(failure, "value", failure))})
            return False
        self._emit(kind="TOOL_OBSERVED", run_id=run_id, tick=tick,
                   lease_generation=context.lease_generation,
                   detail={"capability_id": capability_id,
                           "artifacts": list(result.artifacts)})
        return True

    # ── delegation ──

    def _delegation_phase(self, structured: Mapping[str, Any], spec: ProfileSpec,
                          context: TaskContext, state: _RunState, run_id: str,
                          tick: int, token: RunCancelToken | None = None) -> None:
        items = structured.get("delegations")
        if not items:
            return
        if not isinstance(items, list) or not all(isinstance(item, Mapping)
                                                  for item in items):
            state.refuse(MALFORMED_PAYLOAD,
                         "delegations must be a list of mappings", tick=tick)
            return
        for item in items:
            unknown = sorted(set(item) - DELEGATION_KEYS)
            if unknown:
                state.refuse(MALFORMED_PAYLOAD,
                             f"a delegation declares unknown keys: {unknown}",
                             tick=tick)
                return
        for item in items:
            self._delegate_one(item, spec, context, state, run_id, tick,
                               token=token)

    def _delegate_one(self, item: Mapping[str, Any], spec: ProfileSpec,
                      context: TaskContext, state: _RunState, run_id: str,
                      tick: int, *, token: RunCancelToken | None = None) -> None:
        """Plan, admit and run one child task — including the review child.

        The child inherits the parent's cancellation token: a cancel is a fact
        about the *run*, so a child that ignored it would put the child's work
        outside the run's stated bound (R4 probe 3a).
        """
        child_profile = str(item.get("profile", ""))
        child_payload = item.get("spec") or {}
        task_type = str(item.get("task_type") or "AGENT_TASK")
        refusal_code = ""
        detail = ""
        if not context.limits.allow_child_runs:
            refusal_code = MALFORMED_PAYLOAD
            detail = ("child runs are disabled by the run's limits — a delegation "
                      "is refused, not silently skipped")
        elif context.depth + 1 > context.limits.max_delegation_depth:
            refusal_code = MALFORMED_PAYLOAD
            detail = (f"delegation depth {context.depth + 1} exceeds the declared "
                      f"maximum {context.limits.max_delegation_depth} — subagents "
                      f"are child tasks, and this child may not delegate further")
        elif state.child_runs >= context.limits.max_child_runs:
            refusal_code = MALFORMED_PAYLOAD
            detail = (f"child-run budget {context.limits.max_child_runs} is "
                      f"exhausted")
        elif not isinstance(child_payload, Mapping):
            refusal_code = MALFORMED_PAYLOAD
            detail = "a delegation spec must be a mapping"
        if refusal_code:
            state.refuse(refusal_code, detail, tick=tick,
                         kind=IntentKind.INSERT_TASK.value)
            self._emit(kind="DELEGATION_REFUSED", run_id=run_id, tick=tick,
                       lease_generation=context.lease_generation,
                       detail={"profile": child_profile, "code": refusal_code})
            return

        slot = len(state.delegations)
        planned = self._delegator.plan(
            run_id=run_id,
            parent_task_id=context.task_id,
            project_id=context.project_id,
            child_profile=child_profile,
            lease_generation=context.lease_generation,
            slot=slot,
            spec=dict(child_payload),
            intent_kind=IntentKind.INSERT_TASK.value,
        )
        if isinstance(planned, RuntimeRefusal):
            state.refusals.append(planned)
            self._emit(kind="DELEGATION_REFUSED", run_id=run_id, tick=tick,
                       lease_generation=context.lease_generation,
                       detail={"profile": child_profile, "code": planned.code})
            return
        record = planned
        self._emit(kind="DELEGATION_PLANNED", run_id=run_id, tick=tick,
                   lease_generation=context.lease_generation,
                   detail={"child_task_id": record.child_task_id,
                           "profile": record.profile,
                           "artifact_ref": record.artifact_ref})

        command = self._delegator.child_command(record, spec=dict(child_payload),
                                                slot=slot, task_type=task_type)
        command_size = size_of(command)
        if command_size > MAX_PAYLOAD_BYTES:
            refusal = state.refuse(
                RATIONALE,
                f"the child command is {command_size} bytes, over the "
                f"{MAX_PAYLOAD_BYTES}-byte cap — the delegation is refused rather "
                f"than truncated (its payload is preserved as "
                f"{record.artifact_ref or 'nothing'})",
                tick=tick, kind=IntentKind.INSERT_TASK.value)
            refused = self._delegator.refuse(
                record, lease_generation=context.lease_generation,
                detail=refusal.detail)
            if isinstance(refused, DelegationRecord):
                state.delegations.append(refused)
            return

        intent = Intent(kind=IntentKind.INSERT_TASK, proposed_by=spec.agent_profile,
                        project_id=context.project_id, payload=command,
                        justification=f"delegate to {child_profile}")
        proposal = self._emit_intent(intent, intent.justification, spec, context,
                                     state, run_id, tick, "", record.artifact_ref)
        state.proposals.append(proposal)
        if not proposal.was_admitted():
            refused = self._delegator.refuse(
                record, lease_generation=context.lease_generation,
                detail=proposal.admission_detail or "the spine refused the child")
            if isinstance(refused, DelegationRecord):
                state.delegations.append(refused)
            return

        child_spec = self._profiles[child_profile]
        child_context = self._delegator.child_context(
            record,
            context=(UntrustedContent(text=digest_of(dict(child_payload)),
                                      origin="runtime.delegation",
                                      ref=record.delegation_id),),
            limits=context.limits,
            depth=context.depth + 1)
        child_set = self._run_spec(child_spec, child_context, start_tick=1,
                                   token=token)
        state.child_runs += 1
        completed = self._delegator.complete(
            record,
            lease_generation=context.lease_generation,
            child_intent_id=proposal.admitted_entity_id,
            child_run_id=child_set.run_id,
            child_state=child_set.state,
            child_digest=child_set.digest(),
            outcome=child_set.termination)
        if isinstance(completed, DelegationRecord):
            state.delegations.append(completed)
        self._emit(kind="DELEGATION_COMPLETED", run_id=run_id, tick=tick,
                   lease_generation=context.lease_generation,
                   detail={"child_task_id": record.child_task_id,
                           "child_run_id": child_set.run_id,
                           "child_state": child_set.state})

    # ── review (a child run, declared as configuration) ──

    def _review_pending(self, spec: ProfileSpec, context: TaskContext,
                        state: _RunState) -> bool:
        """True when `_close` will run a review child for this state.

        One predicate for both users: the loop (which must not put a terminal
        record on file while the review is outstanding) and the close act (which
        runs it). Deliberately read-only — it never refuses and never emits.
        """
        if not spec.review.required or context.depth != 0:
            return False
        if not state.proposals:
            return False
        reviewer = spec.review.reviewer_profile
        if reviewer not in self._profiles:
            return False
        return not any(record.profile == reviewer
                       and record.state == DelegationState.DONE.value
                       for record in state.delegations)

    def _maybe_review(self, spec: ProfileSpec, context: TaskContext,
                      state: _RunState, run_id: str,
                      token: RunCancelToken | None = None) -> None:
        """Review is a top-level act: a reviewer never reviews its own reviewer."""
        if not spec.review.required or context.depth != 0:
            return
        if not state.proposals:
            return
        reviewer = spec.review.reviewer_profile
        if reviewer not in self._profiles:
            state.refuse(MALFORMED_PAYLOAD,
                         f"review profile {reviewer!r} is not declared",
                         tick=state.tick)
            return
        if not self._review_pending(spec, context, state):
            return
        self._delegate_one(
            {"profile": reviewer,
             "spec": {"run_id": run_id,
                      "review_round": 1,
                      "proposal_digests": [proposal.draft_digest()
                                           for proposal in state.proposals]},
             "task_type": "AGENT_TASK"},
            spec, context, state, run_id, state.tick, token=token)

    # ── input guards, bounds, checkpointing ──

    def _validate_inputs(self, spec: ProfileSpec,
                         context: TaskContext) -> str | None:
        """The pre-flight guards, in order. Returns a refusal code, or `None`."""
        if not context.lease_generation.strip():
            return LOCK
        if not context.project_id.strip() or not context.task_id.strip():
            return MALFORMED_PAYLOAD
        if size_of(dict(context.payload)) > MAX_PAYLOAD_BYTES:
            return RATIONALE
        if any(len(item.text.encode("utf-8")) > MAX_PAYLOAD_BYTES
               for item in context.context):
            return RATIONALE
        if context.depth > context.limits.max_delegation_depth:
            return MALFORMED_PAYLOAD
        return None

    def _max_ticks(self, spec: ProfileSpec, context: TaskContext) -> int:
        return context.limits.max_ticks or spec.termination.max_ticks

    def _max_proposals(self, spec: ProfileSpec, context: TaskContext) -> int:
        return context.limits.max_proposals or spec.termination.max_proposals

    def _model_request(self, spec: ProfileSpec, context: TaskContext,
                       tick: int) -> ModelRequest:
        prompt = list(context.context)
        prompt.append(UntrustedContent(
            text=f"tick {tick} of {self._max_ticks(spec, context)}",
            origin="runtime.tick", ref=context.task_id))
        return ModelRequest(
            tier=spec.model_policy.tier,
            profile=spec.name,
            lease_generation=context.lease_generation,
            prompt=tuple(prompt),
            output_contract=output_contract_for(spec),
            rationale=spec.role,
            max_output_tokens=spec.model_policy.max_output_tokens,
            tools=tuple(spec.tools) if spec.model_policy.allows_tool_calls else (),
            options=dict(spec.model_policy.options),
        )

    def _write_checkpoint(self, spec: ProfileSpec, context: TaskContext,
                          state: _RunState, run_id: str, *,
                          terminal: bool = False,
                          resumed_from_generation: str = "") -> Checkpoint:
        existing = self._checkpoints.get(run_id)
        stamp = self._supervisor.now()
        checkpoint = Checkpoint(
            run_id=run_id,
            profile=spec.name,
            agent_profile=spec.agent_profile,
            task_id=context.task_id,
            project_id=context.project_id,
            lease_generation=context.lease_generation,
            resumed_from_generation=(resumed_from_generation
                                     or (existing.resumed_from_generation
                                         if existing is not None else "")),
            tick=state.tick,
            state=state.state,
            termination=state.termination,
            context=context.to_mapping(),
            context_digest=context.digest(),
            proposals=tuple(state.proposals),
            refusals=tuple(state.refusals),
            delegations=tuple(state.delegations),
            tool_calls=state.tool_calls,
            misses=existing.misses if existing is not None else 0,
            last_heartbeat=stamp,
            created_at=(existing.created_at if existing is not None else stamp),
            updated_at=stamp,
        )
        self._checkpoints.put(checkpoint)
        self._emit(kind="CHECKPOINT_WRITTEN", run_id=run_id, tick=state.tick,
                   lease_generation=context.lease_generation,
                   detail={"state": checkpoint.state,
                           "proposals": len(checkpoint.proposals),
                           "terminal": terminal})
        return checkpoint

    def _assemble(self, spec: ProfileSpec, context: TaskContext, state: _RunState,
                  run_id: str, *, resumed_from_tick: int = 0) -> ProposalSet:
        if state.termination == "":
            state.terminate(TaskStatus.SUCCEEDED.value,
                            Termination.TICK_LIMIT.value)
        return ProposalSet(
            run_id=run_id,
            profile=spec.name,
            agent_profile=spec.agent_profile,
            task_id=context.task_id,
            project_id=context.project_id,
            lease_generation=context.lease_generation,
            state=state.state,
            termination=state.termination,
            ticks=state.tick,
            proposals=tuple(state.proposals),
            refusals=tuple(state.refusals),
            delegations=tuple(state.delegations),
            tool_calls=state.tool_calls,
            resumed_from_tick=resumed_from_tick,
        )

    # ── resume + recovery ──

    def resume(self, run_id: str, *, lease_generation: str = "",
               context: TaskContext | None = None, takeover: bool = False,
               token: RunCancelToken | None = None
               ) -> ProposalSet | RuntimeRefusal:
        """Continue a run from its checkpoint — explicitly, never automatically.

        Five refusals guard it: an unknown run, and a record whose body disagrees
        with the id it is stored under (`MALFORMED_PAYLOAD`); a blank caller
        generation, and a checkpoint attributed to another lease generation
        without an explicit `takeover=True` (`LOCK` — the fence applies to
        terminal reads too, because a terminal checkpoint is still attributed); a
        context whose digest has changed since the checkpoint — including the
        context *recorded in* the checkpoint, which must prove itself against the
        digest it carries (`STALE` — a run resumes against the state it was
        checkpointed on). A terminal checkpoint is a no-op read: it returns the
        recorded terminal set, which is what makes a crash-and-resume comparable
        to an uninterrupted run.
        """
        checkpoint = self._checkpoints.get(run_id)
        if checkpoint is None:
            return RuntimeRefusal(
                code=MALFORMED_PAYLOAD,
                detail=f"no checkpoint for run {run_id!r} — there is nothing to "
                       f"resume")
        # The store's key is the record's identity (a file *name*, for the file
        # store): a body that disagrees with it is a forged or torn record, and
        # nothing here will act on the identity it claims (R4 probe 2g).
        if checkpoint.run_id != run_id:
            return RuntimeRefusal(
                code=MALFORMED_PAYLOAD,
                detail=f"checkpoint {run_id} carries run_id "
                       f"{checkpoint.run_id!r}, which is not the id it is stored "
                       f"under — a record that disagrees with its own identity is "
                       f"not resumable")
        recorded = checkpoint.lease_generation
        stated = lease_generation.strip()
        if not stated and not takeover:
            # B-4: a resume states the generation it acts under and never inherits
            # one from the record. Adopting the recorded generation silently is
            # exactly the forgery path (R4 probe 2e): a tampered generation would
            # satisfy the fence by itself. `takeover=True` is the explicit
            # recovery act that may adopt it.
            refusal = RuntimeRefusal(
                code=LOCK,
                detail=f"resume of run {run_id} needs the lease generation it "
                       f"acts under — pass one, or `takeover=True` to adopt the "
                       f"recorded attribution {recorded!r} as an explicit "
                       f"recovery act (B-4)",
                profile=checkpoint.profile)
            self._emit(kind="RESUME_REJECTED", run_id=run_id, tick=checkpoint.tick,
                       lease_generation=recorded, detail={"code": refusal.code})
            return refusal
        target = stated or recorded
        self._emit(kind="RESUME_REQUESTED", run_id=run_id, tick=checkpoint.tick,
                   lease_generation=target,
                   detail={"terminal": checkpoint.is_terminal(),
                           "takeover": takeover})
        if recorded != target and not takeover:
            # The fence applies to *every* read, terminal or not: a terminal
            # checkpoint is still attributed to a lease, and a caller that is not
            # that lease may not act on it (R4 probe 2e2).
            refusal = RuntimeRefusal(
                code=LOCK,
                detail=f"run {run_id} is attributed to lease generation "
                       f"{recorded!r}, not {target!r} — pass takeover=True to "
                       f"resume under a new generation (a recovery act, never an "
                       f"implicit one)",
                profile=checkpoint.profile)
            self._emit(kind="RESUME_REJECTED", run_id=run_id, tick=checkpoint.tick,
                       lease_generation=target, detail={"code": refusal.code})
            return refusal
        spec = self._profiles.get(checkpoint.profile)
        if checkpoint.is_terminal():
            self._emit(kind="RESUME_NOOP", run_id=run_id, tick=checkpoint.tick,
                       lease_generation=target, detail={"state": checkpoint.state})
            return ProposalSet(
                run_id=checkpoint.run_id,
                profile=checkpoint.profile,
                agent_profile=(spec.agent_profile if spec is not None
                               else checkpoint.agent_profile),
                task_id=checkpoint.task_id,
                project_id=checkpoint.project_id,
                lease_generation=checkpoint.lease_generation,
                state=checkpoint.state,
                termination=checkpoint.termination,
                ticks=checkpoint.tick,
                proposals=checkpoint.proposals,
                refusals=checkpoint.refusals,
                delegations=checkpoint.delegations,
                tool_calls=checkpoint.tool_calls,
                resumed_from_tick=checkpoint.tick,
            )
        if spec is None:
            return RuntimeRefusal(
                code=MALFORMED_PAYLOAD,
                detail=f"checkpoint {run_id} names profile {checkpoint.profile!r}, "
                       f"which is not declared", profile=checkpoint.profile)

        if context is None:
            # No caller context: rebuild it from the record *and verify it*, so a
            # tampered body cannot pass itself off as the state the run was
            # checkpointed on (R4 probe 2c). The digest excludes the lease, which
            # recovery legitimately changes.
            try:
                restored = TaskContext.from_mapping(dict(checkpoint.context))
            except RuntimeFormatError as exc:
                return RuntimeRefusal(
                    code=MALFORMED_PAYLOAD,
                    detail=f"checkpoint {run_id} carries a context that cannot be "
                           f"read back ({exc})",
                    profile=checkpoint.profile)
            if restored.digest() != checkpoint.context_digest:
                refusal = RuntimeRefusal(
                    code=STALE,
                    detail=f"the context recorded in checkpoint {run_id} does not "
                           f"match its own context digest — a run resumes against "
                           f"the state it was checkpointed on, and this record "
                           f"cannot prove that it is that state",
                    profile=checkpoint.profile)
                self._emit(kind="RESUME_REJECTED", run_id=run_id,
                           tick=checkpoint.tick, lease_generation=target,
                           detail={"code": refusal.code})
                return refusal
            context = restored.with_changes(lease_generation=target)
        elif context.digest() != checkpoint.context_digest:
            refusal = RuntimeRefusal(
                code=STALE,
                detail=f"the supplied context does not match the checkpoint of run "
                       f"{run_id} — a run resumes against the state it was "
                       f"checkpointed on", profile=spec.name)
            self._emit(kind="RESUME_REJECTED", run_id=run_id, tick=checkpoint.tick,
                       lease_generation=target, detail={"code": refusal.code})
            return refusal
        else:
            context = context.with_changes(lease_generation=target)

        state = _RunState(
            profile=spec.name,
            lease_generation=target,
            tick=checkpoint.tick,
            proposals=[self._refresh(proposal)
                       for proposal in checkpoint.proposals],
            refusals=list(checkpoint.refusals),
            delegations=list(checkpoint.delegations),
            tool_calls=checkpoint.tool_calls,
            seen_drafts={proposal.draft_digest()
                         for proposal in checkpoint.proposals},
        )
        return self._run_spec(
            spec, context, token=token, state=state,
            start_tick=checkpoint.tick + 1,
            resumed_from_generation=(checkpoint.lease_generation
                                     if checkpoint.lease_generation != target
                                     else ""))

    def _refresh(self, proposal: Proposal) -> Proposal:
        """Re-emit a checkpointed proposal: the spine answers, idempotently."""
        admission, detail, entity_id = self._apply(proposal.intent)
        return proposal.with_changes(
            admission=admission, admission_detail=detail,
            admitted_entity_id=(entity_id or proposal.admitted_entity_id))

    def recover(self, run_id: str, *, now: str = ""
                ) -> tuple[RecoveryVerdict | None, Checkpoint | None]:
        """Classify an interrupted run and its pending delegations.

        `may_dispatch` is `False` on every branch, and the delegation pass marks
        `PENDING` records `NO_SIGNAL` without executing anything: recovery
        observes, it never becomes a second scheduler (B-2).
        """
        checkpoint = self._checkpoints.get(run_id)
        if checkpoint is None:
            return None, None
        verdict, updated = self._supervisor.recover(checkpoint, now=now or None)
        self._checkpoints.put(updated)
        for record in self._delegator.recover(run_id=run_id):
            self._emit(kind="DELEGATION_NOT_RESTARTED", run_id=run_id,
                       tick=updated.tick,
                       lease_generation=updated.lease_generation,
                       detail={"delegation_id": record.delegation_id,
                               "state": record.state})
        return verdict, updated

    # ── helpers ──

    def _resolve_profile(self, profile: str | ProfileSpec) -> ProfileSpec | None:
        if isinstance(profile, ProfileSpec):
            return profile
        return self._profiles.get(profile)

    def _emit(self, *, kind: str, run_id: str, tick: int, lease_generation: str,
              detail: Mapping[str, Any] | None = None) -> None:
        self._supervisor.emit(kind=kind, run_id=run_id, tick=tick,
                              lease_generation=lease_generation,
                              detail=dict(detail or {}))

    def _refused_set(self, profile: str, context: TaskContext, code: str,
                     detail: str) -> ProposalSet:
        return ProposalSet(
            run_id=context.resolved_run_id(profile),
            profile=profile,
            agent_profile="",
            task_id=context.task_id,
            project_id=context.project_id,
            lease_generation=context.lease_generation,
            state=TaskStatus.FAILED.value,
            termination=code,
            refusals=(RuntimeRefusal(code=code, detail=detail, profile=profile,
                                     lease_generation=context.lease_generation),))


def _guard_detail(code: str, spec: ProfileSpec, context: TaskContext) -> str:
    """A refusal detail that names the bound the guard actually measured."""
    if code == LOCK:
        return "a run cannot be attributed without a lease generation (B-4)"
    if code == MALFORMED_PAYLOAD:
        if not context.project_id.strip() or not context.task_id.strip():
            return "a run needs a task and a project"
        return (f"delegation depth {context.depth} exceeds the declared maximum "
                f"{context.limits.max_delegation_depth}")
    if size_of(dict(context.payload)) > MAX_PAYLOAD_BYTES:
        return (f"the task payload is {size_of(dict(context.payload))} bytes, over "
                f"the {MAX_PAYLOAD_BYTES}-byte cap — artifact-sized content crosses "
                f"as an artifact ref (`inputs`), not inline (profile {spec.name})")
    return (f"a context item exceeds the {MAX_PAYLOAD_BYTES}-byte cap — "
            f"document-sized content crosses as an artifact ref (`inputs`), not "
            f"inline text (profile {spec.name})")


def _code_of(detail: str) -> str:
    """Recover the refusal code from `_apply`'s formatted detail (`CODE: reason`)."""
    prefix = detail.split(":", 1)[0].strip()
    if prefix in _PLANE_REFUSAL_CODES:
        return prefix
    return PROPOSAL


def run(
    profile: str | ProfileSpec,
    task_context: TaskContext,
    *,
    model: ModelPort,
    orchestration: IntentApplier,
    capabilities: CapabilityPort | None = None,
    artifacts: ArtifactOverflowPort | None = None,
    checkpoints: CheckpointStore | None = None,
    delegations: DelegationStore | None = None,
    profiles: Mapping[str, ProfileSpec] | None = None,
    grants: Mapping[str, ToolGrant] | None = None,
    clock: Clock = utc_now,
    monotonic: Monotonic | None = None,
    supervisor: Supervisor | None = None,
    retry: RetryBudget | None = None,
    token: RunCancelToken | None = None,
) -> ProposalSet:
    """`run(profile, task_context) -> ProposalSet` — the plane's one entry point.

    Ports are keyword-injected; everything else is the profile's configuration and
    the context's bounds. The function builds a runtime and delegates, so the
    contract's signature stays exactly as §2.3 states it.

    The injected checkpoint store carries a **one-writer-per-run-id**
    precondition, which the lease serialises (`checkpoint.py`): two concurrent
    runtimes running the same run under the same generation are a configuration
    error, not a shape this plane arbitrates — it takes no lock and holds no lease
    custody (B-2/B-4).
    """
    runtime = AgentRuntime(
        model=model, orchestration=orchestration, capabilities=capabilities,
        artifacts=artifacts, checkpoints=checkpoints, delegations=delegations,
        profiles=profiles, grants=grants, clock=clock, monotonic=monotonic,
        supervisor=supervisor, retry=retry)
    return runtime.run(profile, task_context, token=token)
