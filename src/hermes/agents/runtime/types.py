"""Runtime plane — closed value vocabulary (ARCHITECTURE_DELTA §2.3).

What lives here, and why
------------------------
Every value the runtime plane hands across its own boundary, plus the *pure*
derivation rules that name its working state. There is no behaviour here beyond
deterministic derivation: no port call, no store, no I/O, no clock read.

Identity discipline (§2.3 *Identity rules*, §3.3)
-------------------------------------------------
A proposal carries **no identity**. Identity is recomputed by rule at whichever
write boundary a proposal reaches. This module therefore never mints a research
id, and `Proposal.admitted_entity_id` exists only to *record* what the write
boundary derived after admission — it is never an input to anything.

The plane's own working-state keys (`run_id`, `child_task_id`,
`delegation_id`, `tool_idempotency_key`) are **derived by rule from content**,
never authored and never random, for the same reason §3.3 recomputes content
hashes: a crash and a resume must re-derive the same key (that is what makes
"kill mid-run → resume → same terminal state" true), and a re-emitted command
must collide with its own earlier admission so the deterministic spine returns a
duplicate instead of a second mutation.

Refusal vocabulary (§2.3 *Errors*)
----------------------------------
`RUNTIME_REFUSAL_CODES` is exactly the existing gateway / controller vocabulary
— this plane introduces no code. `GATEWAY_DEFINED_CODES` and
`CONTROLLER_EMITTED_CODES` mirror the provenance split R3 records, and the test
suite re-derives that split from the two source files so drift fails the build.

`TRACE_KINDS` is **not** an event catalog
-----------------------------------------
Trace kinds are the runtime's own derived working-state vocabulary. Nothing here
is appended to the `events` journal, and `repositories.py:92` remains the only
journal writer (§3.2). The suite asserts no trace kind is a member of
`hermes.core.events.EventType`, which is what makes "not an event" mechanical
rather than aspirational.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from dataclasses import fields as dataclass_fields
from enum import Enum
from typing import Any, Mapping

from hermes.core.intents import Intent, IntentKind
from hermes.core.task_status import TaskStatus
from hermes.security.boundaries import UntrustedContent

# ── refusal codes: the existing vocabulary only (§2.3 Errors) ──

ROLE = "ROLE"
LOCK = "LOCK"
PROPOSAL = "PROPOSAL"
RATIONALE = "RATIONALE"
STALE = "STALE"
MALFORMED_PAYLOAD = "MALFORMED_PAYLOAD"

#: Codes `research/gateway.py` declares as named constants.
GATEWAY_DEFINED_CODES: frozenset[str] = frozenset(
    {ROLE, PROPOSAL, MALFORMED_PAYLOAD, STALE})
#: Codes `research/controller.py` emits as inline string literals.
CONTROLLER_EMITTED_CODES: frozenset[str] = frozenset({LOCK, RATIONALE})
#: The complete set this plane may emit. No member is invented here.
RUNTIME_REFUSAL_CODES: frozenset[str] = GATEWAY_DEFINED_CODES | CONTROLLER_EMITTED_CODES

#: The event-payload cap (§3.3). A proposal payload, a rationale and a derived
#: record payload are all event-payload-shaped crossings, so they inherit it.
MAX_PAYLOAD_BYTES = 4096

#: Terminal task statuses (a run's terminal states are task statuses — this
#: plane invents no status vocabulary of its own).
_TERMINAL_STATES: frozenset[str] = frozenset(
    {TaskStatus.SUCCEEDED.value, TaskStatus.FAILED.value,
     TaskStatus.CANCELLED.value, TaskStatus.SKIPPED.value,
     TaskStatus.INVALIDATED.value, TaskStatus.NO_SIGNAL.value})


class RuntimeFormatError(ValueError):
    """A stored runtime record could not be parsed.

    Derived working state is not a plane crossing, so a corrupt record is an
    integrity incident (raise) rather than a refusal-as-data: nothing downstream
    may proceed against a record it could not read.
    """


class Admission(str, Enum):
    """How the Orchestration API answered a proposal."""

    PENDING = "PENDING"        # emitted but not answered (should not persist)
    ADMITTED = "ADMITTED"      # the spine applied it
    DUPLICATE = "DUPLICATE"    # the spine already had it (idempotent re-emit)
    REFUSED = "REFUSED"        # the spine refused it (refusal-as-data)


class Termination(str, Enum):
    """Why a run stopped.

    A *run diagnostic*, never a state transition: the run's state remains a
    `TaskStatus` value and this plane decides no transition (§2.3).
    """

    PROPOSAL_LIMIT = "PROPOSAL_LIMIT"
    TICK_LIMIT = "TICK_LIMIT"
    NO_PROPOSALS = "NO_PROPOSALS"
    STOP_WHEN = "STOP_WHEN"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    MODEL_REFUSED = "MODEL_REFUSED"
    TOOL_FAILED = "TOOL_FAILED"
    DELEGATION_LIMIT = "DELEGATION_LIMIT"
    PORT_FAILURE = "PORT_FAILURE"


class DelegationState(str, Enum):
    """The B-2 derived-record lifecycle (pending → done, plus pruning)."""

    PENDING = "PENDING"
    DONE = "DONE"
    NO_SIGNAL = "NO_SIGNAL"    # conclusive miss: never re-dispatched (B-2)
    PRUNED = "PRUNED"
    REFUSED = "REFUSED"


#: The runtime's own trace vocabulary — derived working state, never journal
#: rows (§3.2, and the suite asserts none of these is an `EventType`).
TRACE_KINDS: tuple[str, ...] = (
    "RUN_STARTED",
    "RUN_RESUMED",
    "TICK_STARTED",
    "MODEL_REQUESTED",
    "MODEL_REFUSED",
    "PROPOSAL_DRAFTED",
    "PROPOSAL_REFUSED",
    "INTENT_EMITTED",
    "INTENT_ADMITTED",
    "INTENT_DUPLICATE",
    "INTENT_REFUSED",
    "TOOL_REQUESTED",
    "TOOL_OBSERVED",
    "TOOL_FAILED",
    "TOOL_SKIPPED",
    "DELEGATION_PLANNED",
    "DELEGATION_REFUSED",
    "DELEGATION_COMPLETED",
    "DELEGATION_NOT_RESTARTED",
    "CHECKPOINT_WRITTEN",
    "RECOVERY_CLASSIFIED",
    "RESUME_REQUESTED",
    "RESUME_REJECTED",
    "RESUME_NOOP",
    "RUN_TERMINATED",
)


# ═══════════════════════ pure derivation ═══════════════════════


def canonical_json(value: Any) -> str:
    """Deterministic JSON for digests and size accounting.

    Local to this package on purpose: importing `research.programs` for its
    canonicaliser would drag the research layer into the runtime plane (§3.1),
    and the two must agree only on *determinism*, not on an implementation.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


def digest_of(value: Any) -> str:
    """SHA-256 over the canonical encoding."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def size_of(value: Any) -> int:
    """Canonical encoded size in bytes — the 4 KiB cap's unit (§3.3)."""
    return len(canonical_json(value).encode("utf-8"))


def run_id_of(profile: str, task_id: str, project_id: str, iteration: int) -> str:
    """The run's working-state key: derived by rule, never authored."""
    preimage = {"profile": profile, "task_id": task_id,
                "project_id": project_id, "iteration": int(iteration)}
    return "run_" + digest_of(preimage)[:32]


def child_task_id_of(parent_task_id: str, profile: str, slot: int) -> str:
    """A child task's id: derived from the delegating command, never authored.

    Deterministic so that a resumed run re-emits the *same* child admission and
    the spine answers `duplicate=True` instead of creating a second task.
    """
    preimage = {"parent_task_id": parent_task_id, "profile": profile,
                "slot": int(slot)}
    return "task_" + digest_of(preimage)[:32]


def child_idempotency_key_of(parent_task_id: str, profile: str, slot: int,
                             spec: Mapping[str, Any]) -> str:
    """The child command's idempotency key, derived by the same rule.

    `NodeContract` states the key is a SHA-256 of spec + inputs; the delegating
    command *is* the spec, so the digest is taken over the derived child
    identity plus the delegated specification.
    """
    return digest_of({"child_task_id": child_task_id_of(parent_task_id, profile, slot),
                      "spec_digest": digest_of(dict(spec))})


def delegation_id_of(run_id: str, parent_task_id: str, child_task_id: str) -> str:
    """A delegation record's key: derived by rule, never authored."""
    return "del_" + digest_of({"run_id": run_id, "parent_task_id": parent_task_id,
                               "child_task_id": child_task_id})[:32]


def tool_idempotency_key_of(run_id: str, tick: int, index: int,
                            capability_id: str) -> str:
    """A capability call's idempotency key, derived by rule.

    Because it is derived (not random), a resumed run replays the *same* call
    key and the capability plane's ledger answers from its record instead of
    executing a second side effect.
    """
    return digest_of({"run_id": run_id, "tick": int(tick), "index": int(index),
                      "capability_id": capability_id})


# ═══════════════════════ inputs ═══════════════════════


@dataclass(frozen=True, slots=True)
class RunLimits:
    """Explicit bounds for one run. `0`/`None` defers to the profile's config."""

    max_ticks: int = 0
    max_proposals: int = 0
    max_tool_calls: int = 0
    deadline_seconds: float | None = None
    max_delegation_depth: int = 1
    allow_child_runs: bool = True
    max_child_runs: int = 4


@dataclass(frozen=True, slots=True)
class TaskContext:
    """The bounded context one run is given (§2.3 *Inputs*).

    Everything that reaches a judgment surface arrives as `UntrustedContent`
    (`security/boundaries.py`) — fetched text, prior proposals, observations —
    so no bare string can enter a model prompt.
    """

    task_id: str
    project_id: str
    lease_generation: str
    iteration: int = 1
    context: tuple[UntrustedContent, ...] = ()
    inputs: tuple[str, ...] = ()
    payload: Mapping[str, Any] = field(default_factory=dict)
    limits: RunLimits = field(default_factory=RunLimits)
    depth: int = 0
    parent_run_id: str = ""
    parent_task_id: str = ""
    run_id: str = ""

    def resolved_run_id(self, profile: str) -> str:
        """The given run id, or the one this context derives by rule."""
        if self.run_id:
            return self.run_id
        return run_id_of(profile, self.task_id, self.project_id, self.iteration)

    def digest(self) -> str:
        """Content digest of everything a run depends on — except the lease.

        The lease generation is excluded because recovery legitimately changes
        it (that is what the fence is for); every other field is included, so a
        resume against a *changed* context is detectable (§2.3 `STALE`).
        """
        return digest_of({
            "task_id": self.task_id,
            "project_id": self.project_id,
            "iteration": self.iteration,
            "context": [{"text": item.text, "origin": item.origin,
                         "ref": item.ref} for item in self.context],
            "inputs": list(self.inputs),
            "payload": dict(self.payload),
            "limits": _limits_mapping(self.limits),
        })

    def with_changes(self, **changes: Any) -> "TaskContext":
        """A copy with fields replaced — the same idiom the stores use.

        `resume` retargets a checkpointed context onto the generation that is
        actually taking the run over; nothing else about it may change, which the
        context digest (lease excluded) is what detects.
        """
        return replace(self, **changes)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "project_id": self.project_id,
            "lease_generation": self.lease_generation,
            "iteration": self.iteration,
            "context": [{"text": item.text, "origin": item.origin,
                         "ref": item.ref} for item in self.context],
            "inputs": list(self.inputs),
            "payload": dict(self.payload),
            "limits": _limits_mapping(self.limits),
            "depth": self.depth,
            "parent_run_id": self.parent_run_id,
            "parent_task_id": self.parent_task_id,
            "run_id": self.run_id,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "TaskContext":
        unknown = sorted(set(data) - set(_field_names(cls)))
        if unknown:
            raise RuntimeFormatError(f"unknown TaskContext keys: {unknown}")
        missing = [key for key in ("task_id", "project_id", "lease_generation")
                   if not data.get(key)]
        if missing:
            raise RuntimeFormatError(f"missing TaskContext keys: {missing}")
        limits = dict(data.get("limits") or {})
        unknown_limits = sorted(set(limits) - set(_field_names(RunLimits)))
        if unknown_limits:
            raise RuntimeFormatError(f"unknown RunLimits keys: {unknown_limits}")
        return cls(
            task_id=str(data["task_id"]),
            project_id=str(data["project_id"]),
            lease_generation=str(data["lease_generation"]),
            iteration=int(data.get("iteration", 1)),
            context=tuple(
                UntrustedContent(text=str(item["text"]),
                                 origin=str(item.get("origin", "")),
                                 ref=str(item.get("ref", "")))
                for item in (data.get("context") or ())),
            inputs=tuple(str(ref) for ref in (data.get("inputs") or ())),
            payload=dict(data.get("payload") or {}),
            limits=RunLimits(**{key: limits[key] for key in limits}),
            depth=int(data.get("depth", 0)),
            parent_run_id=str(data.get("parent_run_id", "")),
            parent_task_id=str(data.get("parent_task_id", "")),
            run_id=str(data.get("run_id", "")))


def _limits_mapping(limits: RunLimits) -> dict[str, Any]:
    return {name: getattr(limits, name) for name in _field_names(RunLimits)}


# ═══════════════════════ refusals ═══════════════════════


@dataclass(frozen=True, slots=True)
class RuntimeRefusal:
    """Refusal-as-data: `{"rejected": True, "code", "detail"}` plus provenance.

    `code` is always a member of `RUNTIME_REFUSAL_CODES`.
    """

    code: str
    detail: str
    profile: str = ""
    tick: int = 0
    lease_generation: str = ""
    kind: str = ""

    def as_dict(self) -> dict[str, Any]:
        """The shape §2.4 gives gateway refusals, so a plane refusal and a spine
        refusal are recognisably the same discipline."""
        return {"rejected": True, "code": self.code, "detail": self.detail}

    def to_mapping(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in _field_names(self)}

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "RuntimeRefusal":
        unknown = sorted(set(data) - set(_field_names(cls)))
        if unknown:
            raise RuntimeFormatError(f"unknown RuntimeRefusal keys: {unknown}")
        return cls(
            code=str(data["code"]),
            detail=str(data.get("detail", "")),
            profile=str(data.get("profile", "")),
            tick=int(data.get("tick", 0)),
            lease_generation=str(data.get("lease_generation", "")),
            kind=str(data.get("kind", "")))


# ═══════════════════════ proposals ═══════════════════════


def intent_to_mapping(intent: Intent) -> dict[str, Any]:
    return {
        "kind": intent.kind.value,
        "proposed_by": intent.proposed_by,
        "project_id": intent.project_id,
        "payload": dict(intent.payload),
        "justification": intent.justification,
    }


def intent_from_mapping(data: Mapping[str, Any]) -> Intent:
    try:
        kind = IntentKind(str(data["kind"]))
    except (KeyError, ValueError) as exc:
        raise RuntimeFormatError(
            f"unknown intent kind: {data.get('kind')!r}") from exc
    return Intent(
        kind=kind,
        proposed_by=str(data.get("proposed_by", "")),
        project_id=str(data.get("project_id", "")),
        payload=dict(data.get("payload") or {}),
        justification=str(data.get("justification", "")))


@dataclass(frozen=True, slots=True)
class Proposal:
    """One intent *draft* plus its provenance and its admission verdict.

    The draft is the intent and its rationale; the verdict is what the
    Orchestration API answered. `draft_digest()` covers only the draft, which is
    what makes a resumed run's terminal digest equal an uninterrupted run's:
    the same command re-emitted is the same draft, even when the spine answers
    `DUPLICATE` instead of `ADMITTED` (and even when a different provider route
    produced it).
    """

    intent: Intent
    rationale: str
    tick: int
    profile: str
    agent_profile: str
    lease_generation: str
    model: str = ""
    capability_refs: tuple[str, ...] = ()
    artifact_ref: str = ""
    admission: str = Admission.PENDING.value
    admission_detail: str = ""
    admitted_entity_id: str = ""

    def draft_digest(self) -> str:
        """Content digest of a draft — deliberately *excluding* the tick.

        The tick it happened to be raised on is not part of the draft's identity:
        `stop_when: converged` must recognise the same draft raised twice, a
        checkpoint's prefix must re-digest identically after a resume, and the
        review spec must name the drafts rather than the moments.
        """
        return digest_of({
            "profile": self.profile,
            "agent_profile": self.agent_profile,
            "kind": self.intent.kind.value,
            "project_id": self.intent.project_id,
            "payload": dict(self.intent.payload),
            "justification": self.intent.justification,
            "rationale": self.rationale,
            "artifact_ref": self.artifact_ref,
        })

    def with_changes(self, **changes: Any) -> "Proposal":
        """A copy with fields replaced (used when a resume re-emits a draft)."""
        return replace(self, **changes)

    def was_admitted(self) -> bool:
        return self.admission in (Admission.ADMITTED.value,
                                  Admission.DUPLICATE.value)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "intent": intent_to_mapping(self.intent),
            "rationale": self.rationale,
            "tick": self.tick,
            "profile": self.profile,
            "agent_profile": self.agent_profile,
            "lease_generation": self.lease_generation,
            "model": self.model,
            "capability_refs": list(self.capability_refs),
            "artifact_ref": self.artifact_ref,
            "admission": self.admission,
            "admission_detail": self.admission_detail,
            "admitted_entity_id": self.admitted_entity_id,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Proposal":
        unknown = sorted(set(data) - set(_field_names(cls)))
        if unknown:
            raise RuntimeFormatError(f"unknown Proposal keys: {unknown}")
        return cls(
            intent=intent_from_mapping(dict(data["intent"])),
            rationale=str(data.get("rationale", "")),
            tick=int(data.get("tick", 0)),
            profile=str(data.get("profile", "")),
            agent_profile=str(data.get("agent_profile", "")),
            lease_generation=str(data.get("lease_generation", "")),
            model=str(data.get("model", "")),
            capability_refs=tuple(str(ref) for ref in
                                  (data.get("capability_refs") or ())),
            artifact_ref=str(data.get("artifact_ref", "")),
            admission=str(data.get("admission", Admission.PENDING.value)),
            admission_detail=str(data.get("admission_detail", "")),
            admitted_entity_id=str(data.get("admitted_entity_id", "")))


@dataclass(frozen=True, slots=True)
class ProposalSet:
    """A run's whole output: drafts, refusals, derived delegation records.

    This is *not* a mutation and *not* an authority: nothing in it decides a
    transition. It is the plane's report to whoever called `run()`.
    """

    run_id: str
    profile: str
    agent_profile: str
    task_id: str
    project_id: str
    lease_generation: str
    state: str = TaskStatus.RUNNING.value
    termination: str = ""
    ticks: int = 0
    proposals: tuple[Proposal, ...] = ()
    refusals: tuple[RuntimeRefusal, ...] = ()
    delegations: tuple["DelegationRecord", ...] = ()
    tool_calls: int = 0
    resumed_from_tick: int = 0

    def is_terminal(self) -> bool:
        return self.state in _TERMINAL_STATES

    def digest(self) -> str:
        """The run's terminal-state digest (drafts + state + termination).

        Deliberately excludes admission verdicts, delegation outcomes and the
        resume marker: those describe *this process's* passage, while the digest
        is the claim "the same run reached the same terminal state".
        """
        return digest_of({
            "run_id": self.run_id,
            "profile": self.profile,
            "state": self.state,
            "termination": self.termination,
            "ticks": self.ticks,
            "drafts": [proposal.draft_digest() for proposal in self.proposals],
        })

    def admitted(self) -> tuple[Proposal, ...]:
        return tuple(proposal for proposal in self.proposals
                     if proposal.was_admitted())

    def refusal_codes(self) -> tuple[str, ...]:
        return tuple(refusal.code for refusal in self.refusals)


# ═══════════════════════ B-2 derived records ═══════════════════════


@dataclass(frozen=True, slots=True)
class DelegationRecord:
    """One subagent dispatch/completion — the B-2 derived-record shape.

    Binding constraints (ARCHITECTURE_DELTA §4 B-2), each one visible in the
    fields rather than in prose:

    * **no private lock** — the store is lock-free (atomic replace per record);
    * **no restart re-dispatch** — a `PENDING` record read after a restart is
      classified `NO_SIGNAL` and never executed (`delegate.Delegator.recover`);
    * **lease-generation attribution** — `lease_generation` is on every record,
      and a record may only be completed under the generation that created it;
    * **artifact-ref overflow** — `payload_digest` is always present and
      `artifact_ref` carries anything over the 4 KiB cap.

    A record is derived working state, never a record of record: nothing here is
    journaled, and the child's *admission* is an intent proposal.
    """

    delegation_id: str
    run_id: str
    parent_task_id: str
    child_task_id: str
    project_id: str
    profile: str
    agent_profile: str
    lease_generation: str
    state: str = DelegationState.PENDING.value
    intent_kind: str = ""
    payload_digest: str = ""
    artifact_ref: str = ""
    child_intent_id: str = ""
    child_run_id: str = ""
    child_state: str = ""
    child_digest: str = ""
    misses: int = 0
    outcome: str = ""
    created_at: str = ""
    updated_at: str = ""

    def with_changes(self, **changes: Any) -> "DelegationRecord":
        return replace(self, **changes)

    def is_terminal(self) -> bool:
        return self.state in (DelegationState.DONE.value,
                              DelegationState.PRUNED.value,
                              DelegationState.REFUSED.value)

    def to_mapping(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in _field_names(self)}

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "DelegationRecord":
        unknown = sorted(set(data) - set(_field_names(cls)))
        if unknown:
            raise RuntimeFormatError(f"unknown DelegationRecord keys: {unknown}")
        missing = [key for key in ("delegation_id", "run_id", "parent_task_id",
                                   "child_task_id", "project_id", "profile",
                                   "agent_profile", "lease_generation")
                   if not data.get(key)]
        if missing:
            raise RuntimeFormatError(f"missing DelegationRecord keys: {missing}")
        return cls(
            delegation_id=str(data["delegation_id"]),
            run_id=str(data["run_id"]),
            parent_task_id=str(data["parent_task_id"]),
            child_task_id=str(data["child_task_id"]),
            project_id=str(data["project_id"]),
            profile=str(data["profile"]),
            agent_profile=str(data["agent_profile"]),
            lease_generation=str(data["lease_generation"]),
            state=str(data.get("state", DelegationState.PENDING.value)),
            intent_kind=str(data.get("intent_kind", "")),
            payload_digest=str(data.get("payload_digest", "")),
            artifact_ref=str(data.get("artifact_ref", "")),
            child_intent_id=str(data.get("child_intent_id", "")),
            child_run_id=str(data.get("child_run_id", "")),
            child_state=str(data.get("child_state", "")),
            child_digest=str(data.get("child_digest", "")),
            misses=int(data.get("misses", 0)),
            outcome=str(data.get("outcome", "")),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")))


# ═══════════════════════ checkpoint + recovery ═══════════════════════

#: The recovery chain's vocabulary (`RUNNING → NO_SIGNAL → FAILED`, v4 §6.3).
RECOVERY_LIVE = "LIVE"
RECOVERY_RESUMABLE = "RESUMABLE"
RECOVERY_NO_SIGNAL = "NO_SIGNAL"
RECOVERY_FAILED = "FAILED"
RECOVERY_COMPLETE = "COMPLETE"


@dataclass(frozen=True, slots=True)
class RecoveryVerdict:
    """The classification of an interrupted run.

    `may_dispatch` is always `False`: recovery classifies, it never restarts
    work. Resuming is a separate, explicit act (`Supervisor.recover` returns the
    verdict; only `resume(...)` continues a run, and only from its checkpoint).
    """

    kind: str
    misses: int
    reason: str
    may_resume: bool = False
    may_dispatch: bool = False


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """One run's durable derived working state (never a record of record)."""

    run_id: str
    profile: str
    agent_profile: str
    task_id: str
    project_id: str
    lease_generation: str
    resumed_from_generation: str = ""
    tick: int = 0
    state: str = TaskStatus.RUNNING.value
    termination: str = ""
    context: Mapping[str, Any] = field(default_factory=dict)
    context_digest: str = ""
    proposals: tuple[Proposal, ...] = ()
    refusals: tuple[RuntimeRefusal, ...] = ()
    delegations: tuple[DelegationRecord, ...] = ()
    tool_calls: int = 0
    misses: int = 0
    last_heartbeat: str = ""
    created_at: str = ""
    updated_at: str = ""

    def is_terminal(self) -> bool:
        return self.state in _TERMINAL_STATES

    def proposals_digest(self) -> str:
        return digest_of([proposal.draft_digest() for proposal in self.proposals])

    def with_changes(self, **changes: Any) -> "Checkpoint":
        return replace(self, **changes)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "profile": self.profile,
            "agent_profile": self.agent_profile,
            "task_id": self.task_id,
            "project_id": self.project_id,
            "lease_generation": self.lease_generation,
            "resumed_from_generation": self.resumed_from_generation,
            "tick": self.tick,
            "state": self.state,
            "termination": self.termination,
            "context": dict(self.context),
            "context_digest": self.context_digest,
            "proposals": [proposal.to_mapping() for proposal in self.proposals],
            "refusals": [refusal.to_mapping() for refusal in self.refusals],
            "delegations": [record.to_mapping() for record in self.delegations],
            "tool_calls": self.tool_calls,
            "misses": self.misses,
            "last_heartbeat": self.last_heartbeat,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Checkpoint":
        unknown = sorted(set(data) - set(_field_names(cls)))
        if unknown:
            raise RuntimeFormatError(f"unknown Checkpoint keys: {unknown}")
        missing = [key for key in ("run_id", "profile", "agent_profile",
                                   "task_id", "project_id", "lease_generation")
                   if not data.get(key)]
        if missing:
            raise RuntimeFormatError(f"missing Checkpoint keys: {missing}")
        return cls(
            run_id=str(data["run_id"]),
            profile=str(data["profile"]),
            agent_profile=str(data["agent_profile"]),
            task_id=str(data["task_id"]),
            project_id=str(data["project_id"]),
            lease_generation=str(data["lease_generation"]),
            resumed_from_generation=str(data.get("resumed_from_generation", "")),
            tick=int(data.get("tick", 0)),
            state=str(data.get("state", TaskStatus.RUNNING.value)),
            termination=str(data.get("termination", "")),
            context=dict(data.get("context") or {}),
            context_digest=str(data.get("context_digest", "")),
            proposals=tuple(Proposal.from_mapping(item)
                            for item in (data.get("proposals") or ())),
            refusals=tuple(RuntimeRefusal.from_mapping(item)
                           for item in (data.get("refusals") or ())),
            delegations=tuple(DelegationRecord.from_mapping(item)
                              for item in (data.get("delegations") or ())),
            tool_calls=int(data.get("tool_calls", 0)),
            misses=int(data.get("misses", 0)),
            last_heartbeat=str(data.get("last_heartbeat", "")),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")))


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """One execution-trace event (streaming, in-memory derived state).

    Traces are deliberately **not** persisted: B-5 forbids the plane a second
    durable log, so the durable lineage lives in the checkpoint's digests and a
    resumed run starts a fresh trace.
    """

    sequence: int
    kind: str
    run_id: str
    tick: int
    lease_generation: str
    at: str
    detail: Mapping[str, Any] = field(default_factory=dict)


def _field_names(cls: Any) -> tuple[str, ...]:
    """Field names of a dataclass, in declaration order."""
    return tuple(item.name for item in dataclass_fields(cls))
