"""The bounded agent loop — `run(profile, task_context) -> ProposalSet` (§2.3).

What a run is
-------------
One bounded piece of agent work:

1. resolve the profile **by name** from configuration (`config.py`) — there is no
   profile class anywhere in this package;
2. build one model request per tick through the Model plane port, with the
   profile's own output contract and the lease-generation tag — the prompt's
   content envelopes come from the injected context assembler (LOOP-1);
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
  `max_tool_calls`, `max_model_calls_per_tick` and `deadline_seconds` each stop
  the loop; the delegation depth and the child-run budget are *refusal* bounds —
  the delegation that exceeds one is refused and recorded, and the run carries on
  within its tick budget. Either way the loop has no unbounded branch. (The
  distinction is deliberate: a bound on the run's own work ends the run, while a
  bound on a *delegation* declines that one child and leaves the parent's other
  work intact — see `_delegate_one`. `Termination` therefore has no
  `DELEGATION_LIMIT`, LOOP-4 E6.)
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

A review verdict is loop state too, and it is *consumed* (LOOP-3)
-----------------------------------------------------------------
LOOP-0 triage G4: the review child ran, its verdict was thrown away, and
`max_review_rounds` was parsed but never read — so a reviewer's disagreement left
the run `SUCCEEDED` beside unrevised drafts. LOOP-3 reads the child's own proposal
set as a verdict (a reviewer that raised nothing found nothing to object to —
`stop_when: no_proposals`) and makes a *failing* verdict consequential: it is
retained as a `ReviewVerdict`, carried into the next round as an origin-marked
data envelope, and re-drives drafting inside a bound of `max_review_rounds`
rounds. The default cap is 1, so an undeclared profile behaves exactly as before.
Rounds terminate on the cap *and* on the verdict's evidence stability, so no
infinite review loop is possible. A verdict revises DRAFTS only: it never
approves, records, resolves or mutates anything durable, and a reviewer's text is
untrusted data the next round reads — never an instruction it obeys.

Feedback is loop state, composed after the port (LOOP-2)
-------------------------------------------------------
A tick's model prompt is the context assembler's envelopes (LOOP-1), then this
run's retained tool feedback, then any consumed review verdicts (LOOP-3), then —
on a retry — the refusal that ended the previous attempt (LOOP-4 E5), then the
tick marker. The trailing four are facts about the *run* rather than about its
context, so they are composed after the port rather than smuggled into the context
— the context digest a resume is checked against is therefore still a digest of
the run's inputs alone. A retained result is evidence-shaped data (artifact refs,
the payload's size and digest, a refusal or failure signal); nothing in it is ever
an instruction, and no observation payload's text enters a prompt.

A retry is informed, and never sleeps past the run's bound (LOOP-4 E5)
---------------------------------------------------------------------
A retry used to re-issue the *identical* request, so a second attempt could only
fail the way the first did. The refusal that ended attempt N-1 is now rendered
into attempt N's prompt as an origin-marked data envelope (`runtime.retry`) — the
same seam LOOP-2 gave tool feedback, applied to the model plane's own answer. The
wait between attempts is bounded by the retry budget (a finite, deterministic
schedule) and again by the run's deadline: the supervisor never sleeps *past* the
instant the run must stop, because that would spend the run's bound on waiting
rather than on work.

A cancel is observed in four places, never only at the top of a tick: before a
model call, before each capability call in a batch, whenever a tick is about to
report the run's stop, and after the terminal act (the review). A cancel that
lands during the run's last piece of work is therefore recorded as the run's
terminal state — a cancelled run is never reported as `SUCCEEDED`.

The deadline is the *run's* bound, not the attempt's (LOOP-4 E2/E3/M1)
-----------------------------------------------------------------
`deadline_seconds` is resolved once per run into a monotonic instant, held on the
run's state, and checked at the same four places the cancel is — including the
terminal act, which used to drop it. It is also carried across a resume, and it
is carried as an *absolute instant*: the checkpoint records the run's deadline
instant once, and `resume` re-enters the run with that very instant, so
"bounded in time" is a statement about the run and not about one attempt at it.
An instant — not a remaining duration — is what makes this true across repeated
resumes: a duration re-bases against each entry's own start, so a run that keeps
crashing before it makes progress would keep being handed the full declared
bound. With the instant fixed, every later resume computes a strictly smaller
remaining and eventually resumes already-expired. The instant is a monotonic
reading, and so is meaningful within one process — which is the scope this plane
claims, since its recovery is process-local and derived (see `supervisor.py`).

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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from hermes.agents.runtime.assembly import (
    ContextAssembler,
    contract_feedback_envelope,
    default_context_assembler,
    feedback_envelopes,
    proposal_envelopes,
    retry_envelope,
    review_envelopes,
)
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
    Proposal,
    ProposalSet,
    RecoveryVerdict,
    ReviewVerdict,
    RuntimeFormatError,
    RuntimeRefusal,
    TaskContext,
    Termination,
    ToolFeedback,
    TraceEvent,
    canonical_json,
    child_idempotency_key_of,
    child_task_id_of,
    digest_of,
    evidence_digests,
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
    bounded_excerpt,
)

#: The legacy model-refusal codes this plane retries (LOOP-4). A request-side
#: `MALFORMED_PAYLOAD` is deterministic and would fail identically (the R2
#: report makes the same split at the provider edge), and the code alone cannot
#: tell an output-shape refusal from a request guard — which is why OPS-15 adds
#: the site-set `contract_feedback` marker below. This set stays as the fallback
#: for `RATIONALE`; it is not the complete retryability rule.
RETRYABLE_MODEL_REFUSALS: frozenset[str] = frozenset({RATIONALE})


def _retryable_model_refusal(item: object) -> bool:
    """The complete retryability predicate for one model-phase result (OPS-15).

    A refusal is retryable when the model plane marked it a whole-reply,
    contract-shape failure before any draft existed (`contract_feedback`), or
    when it is the LOOP-4 `RATIONALE` case this plane already retried. The
    marker is the refusing site's decision, not a code guess: `ROLE` is emitted
    at partition, capability, credential and sidecar-route sites that must stay
    terminal, and a request-side `MALFORMED_PAYLOAD` would fail identically on a
    second call. A hand-built refusal defaults to False, so a new port that does
    not set the marker can never silently gain a retry.
    """
    if not isinstance(item, ModelRefusal):
        return False
    if item.contract_feedback:
        return True
    return item.code in RETRYABLE_MODEL_REFUSALS


#: The top-level array field a reply carries tool calls in. The runtime reads
#: this name and the composition renders it, so the prompt and the check cannot
#: disagree about where a call goes (OPS-5G).
TOOL_CALLS_FIELD: str = "tool_calls"

#: Keys a draft, a tool call and a delegation item may carry. Closed schemas:
#: an unknown key is refused, never ignored. ``TOOL_CALL_ARGUMENTS_KEY`` is
#: named separately because the validator requires it to be a mapping, and the
#: prompt renders that one key as an object rather than a string (OPS-5G).
DRAFT_KEYS: frozenset[str] = frozenset({"kind", "rationale", "payload"})
TOOL_CALL_ARGUMENTS_KEY: str = "arguments"
TOOL_CALL_KEYS: frozenset[str] = frozenset({"capability_id",
                                            TOOL_CALL_ARGUMENTS_KEY,
                                            "rationale"})
DELEGATION_KEYS: frozenset[str] = frozenset({"profile", "spec", "task_type"})

#: The two mutually exclusive proposal forms. The validator refuses a reply
#: that carries both; the contract renders this rule from these names, so the
#: prompt and the check cannot drift apart (OPS-9).
SINGLE_PROPOSAL_FIELD: str = "kind"
MULTI_PROPOSAL_FIELD: str = "proposals"

#: Keys the runtime *derives*. A draft that supplies one is refused: §2.3 forbids
#: any plane from authoring — or trusting — an identity.
AUTHORED_KEYS: frozenset[str] = frozenset({"proposed_by", "project_id",
                                            "task_id", "idempotency_key"})

#: Contract sections and the JSON types they may carry.
_CONTRACT_SECTIONS: Mapping[str, str] = {
    "proposals": "array",
    TOOL_CALLS_FIELD: "array",
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
#: (`docs/archive/WIRING_DESIGN.md` BIND-3 seam note).
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


def output_contract_for(
    spec: ProfileSpec, *,
    capability_tool_note: str = "",
) -> OutputContract:
    """The profile's declared output contract, built from configuration.

    ``capability_tool_note`` is the composition's registry-generated statement
    of the legal capability ids, their schemas and the observation handle/ref
    forms. It rides the ``tool_calls`` field note; it is prompt data, never a
    validator. The runtime's ``spec.tools`` check and the plane's grant remain
    the authority.
    """
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
    field_names = {field.name for field in fields}
    field_notes: list[tuple[str, str]] = []
    if spec.model_policy.kind_field in field_names:
        field_notes.append((
            spec.model_policy.kind_field,
            ("required in the single-proposal form; omit it in the "
             "multi-proposal form")))
    if MULTI_PROPOSAL_FIELD in field_names:
        field_notes.append((
            MULTI_PROPOSAL_FIELD,
            "use this array alone; do not also supply the single-form field"))
    if TOOL_CALLS_FIELD in field_names and capability_tool_note:
        field_notes.append((TOOL_CALLS_FIELD, capability_tool_note))
    return OutputContract(
        name=spec.model_policy.contract,
        fields=tuple(fields),
        kind_field=spec.model_policy.kind_field,
        rationale_field=spec.model_policy.rationale_field,
        allows_decision=False,
        # The same tuple `ProfileSpec.refuses_by_authority` enforces. Listing
        # it in the contract is prompt guidance; the runtime's check remains
        # the authority.
        proposable_kinds=spec.authority.proposable_kinds,
        # OPS-9: both statements are rendered from the validator's own names,
        # so a change to the form fields or the delegation-key set is reflected
        # in the prompt (the drift guard is in test_ops9_contract_rules).
        single_form_field=SINGLE_PROPOSAL_FIELD,
        multi_form_field=MULTI_PROPOSAL_FIELD,
        delegation_keys=tuple(sorted(DELEGATION_KEYS)),
        # OPS-12: the validator's derived-identity set and the conditional
        # field wording are read here, not hand-typed into the prompt.
        derived_keys=tuple(sorted(AUTHORED_KEYS)),
        field_notes=tuple(field_notes),
        # OPS-17: the same constant the overflow refusal interpolates
        # (`_run_phase`), so the stated cap and the refusal cannot disagree.
        max_proposal_bytes=MAX_PAYLOAD_BYTES,
    )


#: R3: the bounded success detail a tool may put in front of the next tick.
#: It is the tool's own note (size/handles/status), never the observation
#: payload's text; the feedback envelope's 4 KiB cap still applies above it.
TOOL_DETAIL_MAX_BYTES = 1024


def _bounded_tool_detail(detail: str) -> str:
    """Truncate a tool note to the stated bound, deterministically.

    The marker is included in the bound, so the returned string never exceeds
    ``TOOL_DETAIL_MAX_BYTES`` encoded bytes. Refusals and failures have their
    own paths; this is the success-detail bridge R3 approved.
    """
    if not detail:
        return ""
    encoded = detail.encode("utf-8")
    if len(encoded) <= TOOL_DETAIL_MAX_BYTES:
        return detail
    marker = " ... (truncated)"
    budget = max(0, TOOL_DETAIL_MAX_BYTES - len(marker.encode("utf-8")))
    return encoded[:budget].decode("utf-8", errors="ignore") + marker


def _tool_feedback(tick: int, index: int, capability_id: str, *,
                   outcome: str, refusal_code: str = "", failure: str = "",
                   detail: str = "", artifacts: tuple[str, ...] = (),
                   payload: UntrustedContent | None = None,
                   invocation_ref: str = "") -> ToolFeedback:
    """One retained tool-phase result (LOOP-2) — measured, never inlined.

    The observation payload's *size and digest* plus the tool's bounded detail
    (``TOOL_DETAIL_MAX_BYTES``) are what a next tick learns about it: the
    payload text stays behind the artifact handles, which is the certified
    route for fetched content to reach a judgment surface. The invocation ref
    is the call's derived key, so a feedback envelope is attributable back to
    the exact call it came from — and never carries a random or authored
    identity (§2.3).
    """
    text = payload.text if payload is not None else ""
    return ToolFeedback(
        tick=tick, index=index, capability_id=capability_id, outcome=outcome,
        refusal_code=refusal_code, failure=failure, detail=detail,
        artifacts=tuple(artifacts),
        payload_bytes=len(text.encode("utf-8")),
        payload_digest=(digest_of(text) if payload is not None else ""),
        invocation_ref=invocation_ref)


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
    #: Retained tool-phase results, in arrival order (LOOP-2). Every tick's model
    #: request carries them, so tick N is asked with what ticks 1..N-1 observed.
    feedback: list[ToolFeedback] = field(default_factory=list)
    #: The *content* identities of everything observed so far — the evidence set
    #: `stop_when: converged` is a statement about (LOOP-2).
    evidence: set[str] = field(default_factory=set)
    #: Consumed review verdicts, in round order (LOOP-3). Each is carried into the
    #: next round as an origin-marked data envelope; a failing one may re-drive
    #: drafting while rounds remain.
    review_verdicts: list[ReviewVerdict] = field(default_factory=list)
    #: The content identities of the verdicts already consumed — the stability set
    #: the re-draft loop terminates on when a reviewer's judgment stops moving.
    seen_verdicts: set[str] = field(default_factory=set)
    #: The run's absolute monotonic deadline, or `None` when it declared none
    #: (LOOP-4 E2/E3/M1). Derived once per *run* — not once per attempt — and
    #: carried across a resume as the same absolute instant, so the bound belongs
    #: to the run rather than to whichever entry happened to be executing.
    deadline: float | None = None

    def refuse(self, code: str, detail: str, *, tick: int, kind: str = "",
               excerpt: str = "") -> RuntimeRefusal:
        item = RuntimeRefusal(code=code, detail=detail, profile=self.profile,
                              tick=tick, lease_generation=self.lease_generation,
                              kind=kind, excerpt=excerpt)
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
        assembler: ContextAssembler | None = None,
        checkpoints: CheckpointStore | None = None,
        delegations: DelegationStore | None = None,
        profiles: Mapping[str, ProfileSpec] | None = None,
        grants: Mapping[str, ToolGrant] | None = None,
        capability_tool_notes: Mapping[str, str] | None = None,
        clock: Clock = utc_now,
        monotonic: Monotonic | None = None,
        supervisor: Supervisor | None = None,
        retry: RetryBudget | None = None,
    ) -> None:
        self._model = model
        self._orchestration = orchestration
        self._capabilities = capabilities
        self._artifacts = artifacts
        self._assembler: ContextAssembler = (
            assembler if assembler is not None else default_context_assembler)
        self._checkpoints: CheckpointStore = (checkpoints if checkpoints is not None
                                              else InMemoryCheckpointStore())
        self._profiles = dict(profiles if profiles is not None
                              else load_profiles())
        self._grants = dict(grants or {})
        self._capability_tool_notes = dict(capability_tool_notes or {})
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
                        deadline=None, token=token)
            return self._assemble(spec, context, working, run_id,
                                  resumed_from_tick=start_tick - 1)

        self._emit(kind="RUN_RESUMED" if resumed else "RUN_STARTED", run_id=run_id,
                   tick=working.tick,
                   lease_generation=context.lease_generation,
                   detail={"profile": spec.name, "depth": context.depth,
                           "start_tick": start_tick})
        # The deadline is the *run's* bound, resolved once and kept on the state
        # (LOOP-4 E2/E3/M1): a resume inherits the run's absolute deadline instant
        # rather than a fresh one, and every act below — including the terminal
        # act — is checked against this same instant.
        deadline = self._run_deadline(spec, context, working)
        # The opening checkpoint: a crash during the first tick still leaves a
        # record to classify, which is what makes the NO_SIGNAL chain reachable.
        self._write_checkpoint(spec, context, working, run_id,
                               resumed_from_generation=resumed_from_generation)

        max_ticks = self._max_ticks(spec, context)
        # LOOP-3: the run is a bounded sequence of drafting rounds, each closed by
        # one review. `max_review_rounds` caps the sequence; a passing review, an
        # exhausted cap, or a reviewer whose judgment stops moving ends it.
        max_rounds = self._review_rounds(spec)
        round_index = 1
        tick = start_tick
        while True:
            while tick <= max_ticks:
                working.tick = tick
                stop = self._tick(spec, context, working, run_id, tick, token,
                                  deadline)
                if (stop and working.state == TaskStatus.SUCCEEDED.value
                        and self._review_pending(spec, context, working,
                                                 round_index)):
                    # The review act has not happened yet, so no terminal-shaped
                    # record may be written for this tick: a crash inside the
                    # review must resume as a *replay* of the tick, not as a no-op
                    # read of a run whose review never ran (R4 probe 1b).
                    break
                self._write_checkpoint(spec, context, working, run_id,
                                       resumed_from_generation=resumed_from_generation)
                if stop:
                    break
                tick += 1
            if working.termination == "":
                working.terminate(TaskStatus.SUCCEEDED.value,
                                  Termination.TICK_LIMIT.value)
            if not self._close(spec, context, working, run_id,
                               resumed_from_generation, round_index=round_index,
                               max_rounds=max_rounds, deadline=deadline,
                               token=token):
                break
            # A failing review with a round left owes another drafting round: the
            # verdict is retained (and re-injected as data), so reopen the run and
            # let the next ticks draft again.
            round_index += 1
            tick = working.tick + 1
            working.state = TaskStatus.RUNNING.value
            working.termination = ""
        return self._assemble(spec, context, working, run_id,
                              resumed_from_tick=start_tick - 1)

    def _close(self, spec: ProfileSpec, context: TaskContext, state: _RunState,
               run_id: str, resumed_from_generation: str, *,
               round_index: int = 1, max_rounds: int = 1,
               deadline: float | None = None,
               token: RunCancelToken | None = None) -> bool:
        """Review (when configured), then — unless a round is owed — the checkpoint.

        The review is the run's terminal act and the longest-running part of the
        run, so the supervisor check brackets it with the *run's own deadline* as
        well as the cancel: a cancel already observed skips it, and a cancel **or
        a deadline expiry** that lands while it runs becomes the run's terminal
        state — never a silent `SUCCEEDED` (LOOP-4 E2; the deadline used to be
        dropped here by passing `None`).

        Returns `True` when a failing verdict with a round remaining must be
        re-drafted: the verdict is retained (LOOP-3) and no terminal record is
        written, because the run is still in flight. Returns `False` when the run
        is finished and its terminal checkpoint is on file.
        """
        verdict = self._supervisor.check(token, deadline)
        if not verdict and state.state == TaskStatus.SUCCEEDED.value:
            review = self._maybe_review(spec, context, state, run_id,
                                        round_index=round_index, token=token)
            verdict = self._supervisor.check(token, deadline)
            if review is not None:
                state.review_verdicts.append(review)
                if (not verdict and state.state == TaskStatus.SUCCEEDED.value
                        and self._round_continues(state, review, round_index,
                                                  max_rounds)):
                    return True
        if verdict and state.state == TaskStatus.SUCCEEDED.value:
            self._interrupt(state, state.tick, verdict,
                            detail=f"run {verdict.lower()} during the terminal act")
        self._emit(kind="RUN_TERMINATED", run_id=run_id, tick=state.tick,
                   lease_generation=context.lease_generation,
                   detail={"state": state.state, "termination": state.termination})
        self._write_checkpoint(spec, context, state, run_id, terminal=True,
                               resumed_from_generation=resumed_from_generation)
        return False

    def _review_rounds(self, spec: ProfileSpec) -> int:
        """How many drafting→review rounds this run may take (LOOP-3).

        `max_review_rounds` is now READ and enforced: it caps the re-draft cycle a
        failing review can drive. The default (1) is conservative — exactly one
        review and no re-draft — which is the pre-LOOP-3 behaviour, so a profile
        that declares no review (or the default cap) never loops. A profile that
        is not reviewed has exactly one round.
        """
        if not spec.review.required:
            return 1
        return max(1, spec.review.max_review_rounds)

    def _round_continues(self, state: _RunState, review: ReviewVerdict,
                         round_index: int, max_rounds: int) -> bool:
        """True when a failing verdict owes another drafting round (LOOP-3).

        Two bounds stop the loop, never one. The **round cap** is the declared
        `max_review_rounds`. **Evidence stability** is the LOOP-2 discipline: the
        verdict's content identity (`ReviewVerdict.evidence_digest`) is the
        reviewer's judgment, and a judgment that recurs unchanged means another
        round would re-draft against the same objection — convergence, not
        progress. Together they make an infinite review loop impossible: rounds
        are finite by the cap, and each consumes a *new* verdict.
        """
        if review.passed or round_index >= max_rounds:
            return False
        digest = review.evidence_digest()
        if digest in state.seen_verdicts:
            return False
        state.seen_verdicts.add(digest)
        return True

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
        """One bounded tick. Returns True when the run must stop.

        Ordering contract: the model response carries both the draft set and
        the tool calls. The proposals are admitted before the tool batch runs;
        the tools are siblings of the proposals, not their justification. The
        tool phase reads no proposal/admission state, so no tool consumes a
        same-tick admitted artifact. A TOOL_FAILED run therefore keeps the
        proposals admitted before the sibling tool failed.
        """
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

        retained = len(state.feedback)
        if not self._tool_phase(structured, spec, context, state, run_id, tick,
                                deadline=deadline, token=token):
            # A capability that failed (or was refused) stops the run: the state
            # says so, rather than falling through to the tick-limit SUCCEEDED.
            state.terminate(TaskStatus.FAILED.value, Termination.TOOL_FAILED.value)
            return True
        self._delegation_phase(structured, spec, context, state, run_id, tick,
                               token)

        raised = len(drafted)
        novel = sum(1 for digest in drafted if digest not in state.seen_drafts)
        state.seen_drafts.update(drafted)
        evidence_stable = self._absorb_evidence(state, state.feedback[retained:])

        termination = self._tick_termination(spec, context, state, raised, novel,
                                             evidence_stable)
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

    def _absorb_evidence(self, state: _RunState,
                         observed: Sequence[ToolFeedback]) -> bool:
        """Absorb one tick's feedback; True when the evidence stopped moving.

        The run's evidence is a *set* of content identities (`evidence_digest()`),
        so "stable" means this tick introduced no evidence the run had not already
        observed — which is the LOOP-2 meaning of convergence, and a statement
        about the evidence rather than about the model's phrasing. A run that has
        never observed anything has no evidence to stabilise, which is exactly why
        the pre-LOOP-2 draft-digest signal survives as the secondary trip.
        """
        fresh = set(evidence_digests(observed)) - state.evidence
        state.evidence.update(evidence_digests(observed))
        return bool(state.evidence) and not fresh

    def _tick_termination(self, spec: ProfileSpec, context: TaskContext,
                          state: _RunState, raised: int, novel: int,
                          evidence_stable: bool = False
                          ) -> str | None:
        """Why this tick stops the run, or `None` when the run continues.

        One place, in precedence order, so every declared policy has a handler:
        `review_complete` is a real stop condition — the run stops once it has a
        proposal set for its declared review to consider (the review itself is the
        close act), instead of falling through to the tick limit with a
        configuration knob that does nothing (R4 probe 5d).

        `converged` means the run's **evidence stopped moving** (LOOP-2). The
        draft-digest signal it used to be — which only ever said "the model
        repeated itself" — is now the *secondary* trip, and it applies only where
        there is no evidence to stabilise: a run that has never observed anything
        (no tool call returned, no refusal was recorded). When evidence exists, it
        governs — a moving evidence set is not convergence, however repetitive the
        drafts are.
        """
        policy = spec.termination.stop_when
        if policy == "proposals_raised" and raised:
            return Termination.STOP_WHEN.value
        if policy == "no_proposals" and raised == 0:
            return Termination.NO_PROPOSALS.value
        if policy == "converged" and raised:
            if evidence_stable:
                return Termination.STOP_WHEN.value
            if novel == 0 and not state.evidence:
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
        stop. A model refusal is data: it is recorded. A contract-shape refusal
        gets one informed re-prompt when the profile's call cap allows it
        (OPS-15); a second refusal, or any non-retryable refusal, ends the run.

        The bound is **model calls per phase per tick** and nothing else.
        Model calls are not charged to `per_run_tokens` today (OPS-16), so this
        makes no token or dollar-boundedness claim.
        """
        verdict = self._supervisor.check(token, deadline)
        if verdict:
            self._interrupt(
                state, tick, verdict,
                detail=f"run {verdict.lower()} before the model call")
            return None

        call_budget = max(1, spec.termination.max_model_calls_per_tick)
        # OPS-15: one informed retry per model phase per tick. The `1` is
        # deliberate: the cap is model *calls*, not the supervisor's general
        # retry schedule, so a profile with three slots still gets one retry.
        # The declared bound is calls per phase per tick and nothing else —
        # model calls are not charged to per_run_tokens (OPS-16), so no token
        # or dollar bound is claimed here.
        budget = RetryBudget(
            max_retries=min(1, self._supervisor.retry.max_retries,
                            call_budget - 1),
            base_delay_seconds=self._supervisor.retry.base_delay_seconds)
        request = self._model_request(spec, context, state, tick)
        self._emit(kind="MODEL_REQUESTED", run_id=run_id, tick=tick,
                   lease_generation=context.lease_generation,
                   detail={"tier": spec.model_policy.tier,
                           "call_budget": call_budget})
        # A retry is *informed* (LOOP-4 E5, OPS-15): the refusal that ended
        # attempt N-1 is rendered into attempt N's prompt as an origin-marked
        # data envelope, so the second call is not the same question asked
        # twice. The first attempt is the plain request, and its trace detail
        # is unchanged; only a retry adds the attempt-2 request and the
        # attempt-level refusal.
        refused: list[ModelRefusal] = []

        def attempt_request(attempt: int) -> ModelProposal | ModelRefusal:
            if attempt == 1 or not refused:
                result = self._model.invoke(request)
            else:
                self._emit(
                    kind="MODEL_REQUESTED", run_id=run_id, tick=tick,
                    lease_generation=context.lease_generation,
                    detail={"tier": spec.model_policy.tier,
                            "call_budget": call_budget, "attempt": attempt})
                result = self._model.invoke(self._model_request(
                    spec, context, state, tick, retry_refusal=refused[-1],
                    retry_attempt=attempt - 1))
            if isinstance(result, ModelRefusal):
                refused.append(result)
            return result

        def record_attempt_refusal(attempt: int, result: object) -> None:
            """Keep the refusal that ended an attempt, before it is retried.

            The supervisor calls this only when a retry will actually happen
            (OPS-15 R4). A retryable refusal that is terminal for budget or
            deadline reasons is recorded by the terminal branch below instead,
            with exactly today's event detail. A `SUCCEEDED` retried run
            therefore retains this refusal: it succeeded *after* a refusal, and
            hiding that would understate the refusal rate.
            """
            if not isinstance(result, ModelRefusal):
                return
            state.refuse(result.code, f"model refusal: {result.detail}",
                         tick=tick, excerpt=result.excerpt)
            self._emit(kind="MODEL_REFUSED", run_id=run_id, tick=tick,
                       lease_generation=context.lease_generation,
                       detail={"code": result.code, "attempt": attempt,
                               "attempts": list(range(1, attempt + 1)),
                               "retryable": True})

        result, attempts = self._supervisor.attempt(
            attempt_request,
            retryable=_retryable_model_refusal,
            budget=budget, deadline=deadline,
            on_retry=record_attempt_refusal)

        if isinstance(result, ModelRefusal):
            state.refuse(result.code, f"model refusal: {result.detail}",
                         tick=tick, excerpt=result.excerpt)
            terminal: dict[str, Any] = {"code": result.code,
                                        "attempts": list(attempts)}
            if len(attempts) > 1:
                # Attempt-attributed only when a retry actually happened; a
                # first-attempt terminal refusal keeps today's detail shape.
                terminal["attempt"] = attempts[-1]
            self._emit(kind="MODEL_REFUSED", run_id=run_id, tick=tick,
                       lease_generation=context.lease_generation,
                       detail=terminal)
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
        raw_excerpt = (bounded_excerpt(result.content.text)
                       if result.content is not None else "")
        drafted = self._emit_drafts(structured, spec, context, state, run_id,
                                    tick, model_ref, raw_excerpt=raw_excerpt)
        return structured, drafted

    def _emit_drafts(self, structured: Mapping[str, Any], spec: ProfileSpec,
                     context: TaskContext, state: _RunState, run_id: str, tick: int,
                     model_ref: str, *, raw_excerpt: str = "") -> tuple[str, ...]:
        """Validate every draft, then emit the survivors as intents."""
        drafts, refusals = self._validate_drafts(
            structured, spec, context, tick, raw_excerpt=raw_excerpt)
        evidence_refs = self._evidence_refs(state)
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
                    tick=tick, kind=kind.value, excerpt=raw_excerpt)
                self._emit(kind="PROPOSAL_REFUSED", run_id=run_id, tick=tick,
                           lease_generation=context.lease_generation,
                           detail={"code": refusal.code, "kind": kind.value})
                continue
            proposal = self._emit_intent(intent, rationale, spec, context, state,
                                        run_id, tick, model_ref, artifact_ref,
                                        capability_refs=evidence_refs)
            state.proposals.append(proposal)
            digests.append(proposal.draft_digest())
        return tuple(digests)

    def _evidence_refs(self, state: _RunState) -> tuple[str, ...]:
        """The calls whose retained evidence a draft is being drafted on (E8).

        A draft is authored *before* its own tick's capability calls run, so what
        actually informed it is the evidence the run had already retained — the
        very records the prompt carried (`feedback_envelopes`). The refs are the
        calls' **derived** invocation keys, so the link is to the exact calls and
        never to an authored identity (§2.3). Sorted and de-duplicated: a set, so
        equal evidence yields an equal tuple, exactly like the evidence set itself.
        """
        return tuple(sorted({record.invocation_ref for record in state.feedback
                             if record.invocation_ref}))

    def _validate_drafts(self, structured: Mapping[str, Any], spec: ProfileSpec,
                         context: TaskContext, tick: int, *,
                         raw_excerpt: str = ""
                         ) -> tuple[list[tuple[IntentKind, str, dict[str, Any], str]],
                                    list[RuntimeRefusal]]:
        """The draft schema plus the profile authority rule, in one place."""
        refusals: list[RuntimeRefusal] = []

        def refuse(code: str, detail: str, *, kind: str = "") -> None:
            refusals.append(RuntimeRefusal(
                code=code, detail=detail, profile=spec.name, tick=tick,
                lease_generation=context.lease_generation, kind=kind,
                excerpt=raw_excerpt))

        allowed = {"kind", "rationale", "payload"} | set(
            spec.model_policy.structured_fields)
        unknown = sorted(set(structured) - allowed)
        if unknown:
            refuse(MALFORMED_PAYLOAD,
                   f"the model output declares keys this profile does not accept: "
                   f"{unknown} (allowed: {sorted(allowed)})")
            return [], refusals
        if (structured.get(MULTI_PROPOSAL_FIELD) is not None
                and structured.get(SINGLE_PROPOSAL_FIELD)):
            refuse(MALFORMED_PAYLOAD,
                   "the model output carries both the single-proposal and the "
                   "multi-proposal form — exactly one is allowed")
            return [], refusals
        if structured.get(MULTI_PROPOSAL_FIELD) is not None:
            items = structured[MULTI_PROPOSAL_FIELD]
            if not isinstance(items, list):
                refuse(MALFORMED_PAYLOAD,
                       f"proposals must be a list, got {type(items).__name__}")
                return [], refusals
        elif structured.get(SINGLE_PROPOSAL_FIELD):
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
                authored = sorted(set(payload) & AUTHORED_KEYS)
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
        if set(payload) & AUTHORED_KEYS:
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
                     model_ref: str, artifact_ref: str,
                     capability_refs: tuple[str, ...] = ()) -> Proposal:
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
            capability_refs=capability_refs,
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
                    tick: int, *, deadline: float | None = None,
                    token: RunCancelToken | None = None) -> bool:
        """Run the declared capability calls. False stops the run.

        A cancel *or a deadline expiry* that lands mid-batch stops the batch: no
        further capability call starts once the run's supervisor says stop (R4
        probe 3b; LOOP-4 G8 — the batch used to read `token.cancelled` directly
        and never observe the deadline, the one place in the run that did).
        """
        items = structured.get(TOOL_CALLS_FIELD)
        if not items:
            return True
        # OPS-5B / OPS-5 §7.2: the field the contract asks for is the field the
        # runtime will read. A profile must BOTH allow tool calls and declare
        # `tool_calls` in structured_fields; otherwise the item is a shape the
        # contract forbids, refused whole and skipped (F4).
        if not (spec.model_policy.allows_tool_calls
                and TOOL_CALLS_FIELD in spec.model_policy.structured_fields):
            state.refuse(
                MALFORMED_PAYLOAD,
                f"{TOOL_CALLS_FIELD} is outside {spec.name}'s declared contract "
                f"(allows_tool_calls={spec.model_policy.allows_tool_calls}, "
                f"structured_fields={list(spec.model_policy.structured_fields)})",
                tick=tick)
            return True
        if not isinstance(items, list) or not all(isinstance(item, Mapping)
                                                  for item in items):
            state.refuse(MALFORMED_PAYLOAD,
                         f"{TOOL_CALLS_FIELD} must be a list of mappings, got "
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
            if self._supervisor.check(token, deadline):
                # The batch stops here; the tick's teardown records the
                # cancellation (or the expiry) as the run's terminal state.
                break
            if not self._one_tool_call(item, index, spec, context, state, run_id,
                                       tick, deadline=deadline):
                return False
        return True

    def _one_tool_call(self, item: Mapping[str, Any], index: int,
                       spec: ProfileSpec, context: TaskContext, state: _RunState,
                       run_id: str, tick: int, *,
                       deadline: float | None = None) -> bool:
        """Run one declared capability call. `False` stops the run.

        One severity rule, stated here and applied at every site (LOOP-4 E7):

        * **A call the plane actually invoked, and that refused or failed, stops
          the run.** The work the run declared could not be done, and reporting a
          proposal set built beside it would misstate what happened.
        * **A malformed call — a shape the contract forbids (no `capability_id`,
          arguments that are not a mapping, an unknown key) — is refused and
          skipped, and the batch carries on.** The model's mistake is data, and
          one bad field must not end a run whose other calls and drafts are fine.
          A capability outside the profile's declared tools is refused *before it
          is ever invoked*, so it is the benign case too.

        Before LOOP-4 the two malformed-call sites here were fatal while every
        other malformed-output site was benign, with nothing stating which was
        which; the rule above is what makes them consistent.
        """
        capability_id = str(item.get("capability_id", ""))
        if not capability_id:
            state.refuse(MALFORMED_PAYLOAD, "a tool call needs a capability_id",
                         tick=tick)
            return True
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
            # The refusal is what shapes the next tick's proposal space (LOOP-2):
            # the model is told *which* capability its profile does not open, and
            # why — the authority decision itself stays where it was made.
            state.feedback.append(_tool_feedback(
                tick, index, capability_id, outcome="TOOL_SKIPPED",
                refusal_code=refusal.code, detail=refusal.detail,
                invocation_ref=tool_idempotency_key_of(run_id, tick, index,
                                                       capability_id)))
            return True
        if self._capabilities is None:
            refusal = state.refuse(
                ROLE, "no capability port is wired — the call is refused rather "
                      "than executed ungated", tick=tick)
            self._emit(kind="TOOL_SKIPPED", run_id=run_id, tick=tick,
                       lease_generation=context.lease_generation,
                       detail={"capability_id": capability_id, "code": refusal.code})
            state.feedback.append(_tool_feedback(
                tick, index, capability_id, outcome="TOOL_SKIPPED",
                refusal_code=refusal.code, detail=refusal.detail,
                invocation_ref=tool_idempotency_key_of(run_id, tick, index,
                                                       capability_id)))
            return True
        arguments = item.get(TOOL_CALL_ARGUMENTS_KEY) or {}
        if not isinstance(arguments, Mapping):
            state.refuse(MALFORMED_PAYLOAD, "tool call arguments must be a mapping",
                         tick=tick)
            return True
        request = InvokeRequest(
            capability_id=capability_id,
            arguments=dict(arguments),
            idempotency_key=tool_idempotency_key_of(run_id, tick, index,
                                                    capability_id),
            lease_generation=context.lease_generation,
            profile=spec.agent_profile,
            rationale=str(item.get("rationale") or spec.role),
            grant=self._grants.get(spec.agent_profile),
            # R8: the call may not outlive the run. The invoker lowers its
            # tool timeout to this remaining run budget; None means no run
            # deadline was declared, so the tool's own bound applies.
            deadline_seconds=self._supervisor.remaining(deadline),
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
            state.feedback.append(_tool_feedback(
                tick, index, capability_id, outcome="TOOL_FAILED",
                refusal_code=code, detail=f"{result.code}: {result.detail}",
                invocation_ref=request.idempotency_key))
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
            state.feedback.append(_tool_feedback(
                tick, index, capability_id, outcome="TOOL_FAILED",
                failure=str(getattr(failure, "value", failure)), detail=detail,
                invocation_ref=request.idempotency_key))
            return False
        self._emit(kind="TOOL_OBSERVED", run_id=run_id, tick=tick,
                   lease_generation=context.lease_generation,
                   detail={"capability_id": capability_id,
                           "artifacts": list(result.artifacts)})
        # The evidence itself is retained — refs, size and digest — so the next
        # tick knows what this one observed instead of asking again (LOOP-2).
        state.feedback.append(_tool_feedback(
            tick, index, capability_id, outcome="TOOL_OBSERVED",
            detail=_bounded_tool_detail(str(getattr(result, "detail", ""))),
            artifacts=tuple(result.artifacts), payload=result.payload,
            invocation_ref=request.idempotency_key))
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
                      tick: int, *, token: RunCancelToken | None = None,
                      context_envelopes: tuple[UntrustedContent, ...] | None = None
                      ) -> ProposalSet | None:
        """Plan, admit and run one child task — including the review child.

        The child inherits the parent's cancellation token: a cancel is a fact
        about the *run*, so a child that ignored it would put the child's work
        outside the run's stated bound (R4 probe 3a). Returns the child's own
        `ProposalSet` (what the reviewer *said*, for LOOP-3's verdict) or `None`
        when the delegation was refused before any child ran.
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
            return None

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
            return None
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
            return None

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
            return None

        child_spec = self._profiles[child_profile]
        child_context = self._delegator.child_context(
            record,
            context=(context_envelopes if context_envelopes is not None
                     else (UntrustedContent(text=digest_of(dict(child_payload)),
                                      origin="runtime.delegation",
                                      ref=record.delegation_id),)),
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
        return child_set

    # ── review (a child run, declared as configuration) ──

    def _review_pending(self, spec: ProfileSpec, context: TaskContext,
                        state: _RunState, round_index: int = 1) -> bool:
        """True when `_close` will run a review child for this round.

        One predicate for both users: the loop (which must not put a terminal
        record on file while the review is outstanding) and the close act (which
        runs it). Deliberately read-only — it never refuses and never emits.

        LOOP-3: a review is pending until a *verdict for this round* exists, not
        merely until a reviewer has ever run. That is what lets a re-draft round
        be reviewed in turn — the first round's completed review no longer
        suppresses the second's — while keeping the R4-probe-1b rule for the
        single-round case (no terminal record while the review is outstanding).
        """
        if not spec.review.required or context.depth != 0:
            return False
        if not state.proposals:
            return False
        reviewer = spec.review.reviewer_profile
        if reviewer not in self._profiles:
            return False
        return all(verdict.round != round_index
                   for verdict in state.review_verdicts)

    def _maybe_review(self, spec: ProfileSpec, context: TaskContext,
                      state: _RunState, run_id: str, *, round_index: int = 1,
                      token: RunCancelToken | None = None
                      ) -> ReviewVerdict | None:
        """Run the review child for this round and return its *consumed* verdict.

        Review is a top-level act: a reviewer never reviews its own reviewer.
        The child is handed the drafts themselves (`proposal_envelopes`), not a
        digest of the spec that names them (LOOP-1).

        LOOP-3 turns the child's own proposal set into a `ReviewVerdict`: a
        reviewer that raised nothing found nothing to object to (the documented
        `stop_when: no_proposals` reading) and its verdict *passes*; a reviewer
        that raised proposals *fails* the round and names them as objections.
        `None` means no review ran (not required, depth > 0, no proposals, an
        undeclared reviewer, or a reviewer already done this run).
        """
        if not spec.review.required or context.depth != 0:
            return None
        if not state.proposals:
            return None
        reviewer = spec.review.reviewer_profile
        if reviewer not in self._profiles:
            state.refuse(MALFORMED_PAYLOAD,
                         f"review profile {reviewer!r} is not declared",
                         tick=state.tick)
            return None
        if not self._review_pending(spec, context, state, round_index):
            return None
        child_set = self._delegate_one(
            {"profile": reviewer,
             "spec": {"run_id": run_id,
                      "review_round": round_index,
                      "proposal_digests": [proposal.draft_digest()
                                           for proposal in state.proposals]},
             "task_type": "AGENT_TASK"},
            spec, context, state, run_id, state.tick, token=token,
            context_envelopes=proposal_envelopes(tuple(state.proposals)))
        return self._review_verdict(reviewer, round_index, run_id, child_set)

    def _review_verdict(self, reviewer: str, round_index: int, run_id: str,
                        child_set: ProposalSet | None) -> ReviewVerdict:
        """Turn a review child's output into a consumed verdict (LOOP-3).

        The verdict is derived, never authored: `passed` is the review child's own
        proposal set being empty, `objections` are the draft digests it raised,
        and `verdict_ref` is a derived identity over `(run_id, round, reviewer)`
        — the same discipline LOOP-2 gave tool feedback. The reviewer's free text
        is carried verbatim as `detail` (untrusted data); nothing here reads it as
        an instruction or an authority, and the caller never uses the verdict to
        approve, record or resolve anything durable.
        """
        proposals = child_set.proposals if child_set is not None else ()
        objections = tuple(proposal.draft_digest() for proposal in proposals)
        detail = "; ".join(
            f"{proposal.intent.kind.value}: {proposal.rationale}"
            for proposal in proposals if proposal.rationale)
        return ReviewVerdict(
            round=round_index,
            reviewer=reviewer,
            passed=not objections,
            objections=objections,
            detail=detail,
            verdict_ref=digest_of({"run_id": run_id, "round": round_index,
                                   "reviewer": reviewer}),
            child_run_id=(child_set.run_id if child_set is not None else ""))

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

    def _run_deadline(self, spec: ProfileSpec, context: TaskContext,
                      state: _RunState) -> float | None:
        """The run's absolute deadline — resolved once, then carried (E2/E3/M1).

        A fresh run derives it from the declared bound (the context's limit, else
        the profile's). A resumed run already carries one: `resume` seeded it from
        the *absolute* instant the checkpoint recorded, so re-entering the run
        continues its original bound instead of granting a fresh one — which is
        what makes "bounded in time" a statement about the run rather than about
        one attempt at it. Because the carried value is an instant rather than a
        duration, it is not re-based against this entry's start: every later
        resume computes a strictly smaller remaining and eventually resumes
        already-expired.
        """
        if state.deadline is None:
            state.deadline = self._supervisor.deadline(
                context.limits.deadline_seconds
                if context.limits.deadline_seconds is not None
                else spec.termination.deadline_seconds)
        return state.deadline

    def _max_proposals(self, spec: ProfileSpec, context: TaskContext) -> int:
        return context.limits.max_proposals or spec.termination.max_proposals

    def _model_request(self, spec: ProfileSpec, context: TaskContext,
                       state: _RunState, tick: int, *,
                       retry_refusal: ModelRefusal | None = None,
                       retry_attempt: int = 0) -> ModelRequest:
        """One request per tick; the prompt is the assembler port's job.

        The prompt is the port's envelopes, then this run's retained tool feedback
        (LOOP-2), then any consumed review verdicts (LOOP-3), then — on a retry —
        the refusal that ended the previous attempt (LOOP-4 E5, OPS-15), then the
        tick marker. The retry note keeps `runtime.retry` for the LOOP-4
        `RATIONALE` case and uses `runtime.contract_feedback` for a whole-reply
        contract-shape refusal. All four trailing halves are *loop state*, not
        context: they are
        composed after the port, so the assembler keeps owning what a run's own
        context contributes and the runtime adds only what happened during the
        run — which is also why the context digest a resume is checked against
        stays a digest of the run's inputs alone.
        Payloads reach the model as content, never as a digest standing in for them
        (LOOP-1); the same is true of an observation's artifacts, which travel as
        their own refs, and of a reviewer's verdict, which travels as data.
        """
        prompt = list(self._assembler(context))
        prompt.extend(feedback_envelopes(state.feedback))
        prompt.extend(review_envelopes(state.review_verdicts))
        if retry_refusal is not None:
            if retry_refusal.contract_feedback:
                prompt.append(contract_feedback_envelope(
                    retry_refusal.code, retry_refusal.detail,
                    attempt=retry_attempt))
            else:
                prompt.append(retry_envelope(retry_refusal.code,
                                             retry_refusal.detail,
                                             attempt=retry_attempt))
        prompt.append(UntrustedContent(
            text=f"tick {tick} of {self._max_ticks(spec, context)}",
            origin="runtime.tick", ref=context.task_id))
        return ModelRequest(
            tier=spec.model_policy.tier,
            profile=spec.name,
            lease_generation=context.lease_generation,
            prompt=tuple(prompt),
            output_contract=output_contract_for(
                spec,
                capability_tool_note=self._capability_tool_notes.get(
                    spec.name, "")),
            rationale=spec.role,
            max_output_tokens=spec.model_policy.max_output_tokens,
            # OPS-5B Path A: ModelRequest.tools is the *native* tool
            # advertisement, not "what this stage may call". The capability ids
            # and their schemas travel in the contract's tool_calls note, which
            # is a JSON field the provider does not refuse. The router's
            # tool-allowlist and supports_tool_calls guards therefore stay
            # unreachable for Hermes callers and keep their teeth for any
            # caller that does set tools.
            tools=(),
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
            deadline_mono=state.deadline,
            context=context.to_mapping(),
            context_digest=context.digest(),
            proposals=tuple(state.proposals),
            refusals=tuple(state.refusals),
            delegations=tuple(state.delegations),
            tool_calls=state.tool_calls,
            feedback=tuple(state.feedback),
            review_verdicts=tuple(state.review_verdicts),
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
            review_verdicts=tuple(state.review_verdicts),
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
                review_verdicts=checkpoint.review_verdicts,
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
            # The run's own bound, continued rather than restarted (E3/M1): the
            # checkpoint carries the run's *absolute* deadline instant, so the
            # resumed run keeps the very same instant — never a fresh full bound
            # per attempt, and never a duration re-based against this entry's
            # start. An anchor already at or before now resumes expired (fails
            # closed on the first supervisor check).
            deadline=checkpoint.deadline_mono,
            proposals=[self._refresh(proposal)
                       for proposal in checkpoint.proposals],
            refusals=list(checkpoint.refusals),
            delegations=list(checkpoint.delegations),
            tool_calls=checkpoint.tool_calls,
            seen_drafts={proposal.draft_digest()
                         for proposal in checkpoint.proposals},
            feedback=list(checkpoint.feedback),
            evidence=set(evidence_digests(checkpoint.feedback)),
            review_verdicts=list(checkpoint.review_verdicts),
            seen_verdicts={verdict.evidence_digest()
                           for verdict in checkpoint.review_verdicts},
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
    capability_tool_notes: Mapping[str, str] | None = None,
    clock: Clock = utc_now,
    monotonic: Monotonic | None = None,
    supervisor: Supervisor | None = None,
    retry: RetryBudget | None = None,
    assembler: ContextAssembler | None = None,
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
        artifacts=artifacts, assembler=assembler,
        checkpoints=checkpoints, delegations=delegations,
        profiles=profiles, grants=grants,
        capability_tool_notes=capability_tool_notes,
        clock=clock, monotonic=monotonic,
        supervisor=supervisor, retry=retry)
    return runtime.run(profile, task_context, token=token)
