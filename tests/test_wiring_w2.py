"""W2 wiring tests — the model binding (BIND-2) and the runtime driver (BIND-3).

These fixtures prove the *binding* (`WIRING_DESIGN.md` §7 "BIND-2"/"BIND-3"), not
the planes themselves (those are `tests/test_model_plane.py` and
`tests/test_agent_runtime.py`). The suite is self-contained: it builds its own
provider, router, policies and profiles rather than reaching into another suite's
fixtures, so a change to those fixtures cannot silently weaken a wiring
assertion.

Five properties, one group each:

- **per-task policy resolution** — a task does not choose its tier; the binding
  resolves it from declared policy data, overrides a caller's hint, and refuses a
  task with no resolvable tier rather than reaching a model;
- **credential absence** — a credential-class option name is refused before the
  router is reached (and by the router if that first guard is neutralized), and
  a live credential value never reaches a payload, a request or a recorded row;
- **accounting per dispatch** — every dispatch lands exactly one ordered row,
  refusals included, and a gap fails closed;
- **the InMemory-only pin** — a file-backed store is refused at construction, and
  a *neutralized* pin lets the same construction through and writes a durable
  file — which is what makes the pin load-bearing rather than decorative;
- **lease-attributed, fenced runs** — every run/checkpoint/delegation/trace
  record carries the fence generation; a foreign generation refuses `LOCK`
  before dispatch; a mid-run lease loss aborts, surfaces `LOCK`, and stops
  writing.

Plus the mechanical no-write-surface pins: each module's imports are checked by
AST against an exact allowlist, and the wiring never names a file store, a
connection, a transaction or SQL.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, cast

import pytest

import hermes.agents.runtime.wiring as wiring_module
import hermes.tools.models.binding as binding_module
from hermes.agents.runtime.checkpoint import (
    FileCheckpointStore,
    InMemoryCheckpointStore,
)
from hermes.agents.runtime.config import ProfileSpec, parse_profile
from hermes.agents.runtime.delegate import (
    FileDelegationStore,
    InMemoryDelegationStore,
)
from hermes.agents.runtime.supervisor import RunCancelToken
from hermes.agents.runtime.types import (
    LOCK,
    MALFORMED_PAYLOAD,
    DelegationState,
    RunLimits,
    TaskContext,
    child_task_id_of,
    digest_of,
)
from hermes.agents.runtime.wiring import (
    FencedIntentApplier,
    LeaseFence,
    RuntimeWiring,
    WiredRun,
    WiringError,
)
from hermes.core.intents import Intent, IntentKind
from hermes.core.task_status import TaskStatus
from hermes.security.boundaries import UntrustedContent
from hermes.tools.models.binding import (
    DispatchAccount,
    ModelBinding,
    ModelPolicyTable,
    ModelPort,
    bind_model_port,
)
from hermes.tools.models.router import (
    Credential,
    ModelCall,
    ModelPlaneInvariantError,
    ModelPlanePolicy,
    ModelProfile,
    ModelProposal,
    ModelRefusal,
    ModelRequest,
    ModelResponse,
    TokenUsage,
)
from hermes.tools.research_sources import RetryPolicy

BINDING_PATH = Path(str(binding_module.__file__))
WIRING_PATH = Path(str(wiring_module.__file__))

TASK = "task-root"
PROJECT = "p1"
LEASE = "lease-gen-7"
SECRET = "sk-live-DO-NOT-RECORD-0123456789"
STAMP = "2026-10-06T12:00:00.000000+00:00"


# ═══════════════════════ fakes ═══════════════════════


class FakeClock:
    """One frozen clock for both halves: callable, `now_utc`, monotonic, sleep."""

    def __init__(self) -> None:
        self.slept: list[float] = []

    def __call__(self) -> str:
        return STAMP

    def now_utc(self) -> str:
        return STAMP

    def monotonic(self) -> float:
        return 0.0

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)


class FixedCredentials:
    """A `CredentialResolver` handing out one live value per provider id."""

    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = dict(values)

    def resolve(self, provider_id: str) -> Credential | None:
        if provider_id not in self._values:
            return None
        return Credential(name="model_api_key", _value=self._values[provider_id])


class ScriptedProvider:
    """A `ModelProvider` answering from a script; records every call it gets."""

    provider_id = "alpha"

    def __init__(self, profiles: tuple[ModelProfile, ...],
                 script: list[Any] | None = None) -> None:
        self._profiles = tuple(profiles)
        self._script = list(script or [])
        self.calls: list[ModelCall] = []

    def describe(self) -> tuple[ModelProfile, ...]:
        return self._profiles

    def invoke(self, call: ModelCall) -> ModelResponse:
        self.calls.append(call)
        if not self._script:
            return ModelResponse(text="{}", usage=TokenUsage(3, 2))
        action = self._script.pop(0)
        if isinstance(action, BaseException):
            raise action
        return action

    def stream(self, call: ModelCall) -> tuple[Any, ...]:
        return ()


@dataclass(frozen=True, slots=True)
class _Applied:
    """The shape `run._apply` reads off an injected Orchestration API result."""

    entity_id: str
    duplicate: bool


class RecordingApplier:
    """The spine's injection point as a recording double (content-addressed)."""

    def __init__(self) -> None:
        self.calls: list[Intent] = []
        self._seen: dict[str, str] = {}

    def __call__(self, intent: Intent) -> Any:
        self.calls.append(intent)
        key = digest_of({"kind": intent.kind.value,
                         "project": intent.project_id,
                         "payload": dict(intent.payload)})
        if key in self._seen:
            return _Applied(entity_id=self._seen[key], duplicate=True)
        entity = "task_" + key[:16]
        self._seen[key] = entity
        return _Applied(entity_id=entity, duplicate=False)


class ScriptedModel:
    """A `ModelPort` for the runtime half, scripted per profile, in order."""

    def __init__(self, scripts: Mapping[str, list[Any]] | list[Any],
                 *, on_call: Any = None) -> None:
        if isinstance(scripts, Mapping):
            self._scripts = {name: list(items) for name, items in scripts.items()}
        else:
            self._scripts = {"*": list(scripts)}
        self.calls: list[ModelRequest] = []
        self.on_call = on_call

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def invoke(self, request: ModelRequest) -> ModelProposal | ModelRefusal:
        self.calls.append(request)
        if self.on_call is not None:
            self.on_call(request)
        script = self._scripts.get(request.profile) or self._scripts.get("*")
        if not script:
            return ModelRefusal(code=MALFORMED_PAYLOAD,
                                detail=f"no scripted response for {request.profile!r}")
        entry = script.pop(0)
        return cast("ModelProposal | ModelRefusal",
                    entry(request) if callable(entry) else entry)


class ForeignStore:
    """A store of no known shape — the positive-allowlist negative."""

    def put(self, value: object) -> None:
        raise AssertionError("a foreign store must never be used")

    def get(self, key: str) -> None:
        return None

    def owned(self, key: str, lease_generation: str) -> None:
        return None

    def run_ids(self) -> tuple[str, ...]:
        return ()

    def delete(self, key: str) -> None:
        return None


# ═══════════════════════ model-half helpers ═══════════════════════


def _model_profile() -> ModelProfile:
    return ModelProfile(provider_id="alpha", model_id="m1",
                        context_window_tokens=8000, max_output_tokens=1024,
                        supports_streaming=True, supports_tool_calls=True,
                        supports_structured_output=True,
                        input_cost_per_1k_tokens=0.5,
                        output_cost_per_1k_tokens=1.5)


def _plane_policy() -> ModelPlanePolicy:
    return ModelPlanePolicy(
        tier_refs={"frontier": "alpha:m1", "baseline": "alpha:m1",
                   "cheap": "alpha:m1"},
        fallback_chain=(),
        retry_policy=RetryPolicy(max_retries=1, base_delay_seconds=0.1,
                                 max_delay_seconds=1.0, jitter=False))


def _request(*, profile: str = "research", tier: str = "frontier",
             options: Mapping[str, str] | None = None,
             lease: str = LEASE) -> ModelRequest:
    return ModelRequest(
        tier=tier, profile=profile, lease_generation=lease,
        prompt=(UntrustedContent(text="hello", origin="test.prompt", ref="r1"),),
        rationale="because", options=dict(options or {}))


class ModelRig:
    """One binding over a recording provider — the BIND-2 test rig."""

    def __init__(self, *, task_policy: ModelPolicyTable | None = None,
                 credentials: Any = None, script: list[Any] | None = None) -> None:
        self.provider = ScriptedProvider((_model_profile(),), script=script)
        self.clock = FakeClock()
        self.binding: ModelBinding = bind_model_port(
            providers=[self.provider], policy=_plane_policy(), clock=self.clock,
            task_policy=(task_policy if task_policy is not None
                         else ModelPolicyTable(tiers={"research": "frontier"},
                                               default_tier="baseline")),
            credentials=credentials)

    def invoke(self, **overrides: Any) -> ModelProposal | ModelRefusal:
        return self.binding.invoke(_request(**overrides))

    def log_json(self) -> str:
        return json.dumps([row.to_mapping() for row in self.binding.dispatch_log()])


# ═══════════════════════ runtime-half helpers ═══════════════════════


def _profile(name: str, *, tier: str = "research",
             agent_profile: str = "RESEARCHER",
             proposable: tuple[str, ...] = ("INSERT_TASK",),
             structured: tuple[str, ...] = ("proposals",),
             max_ticks: int = 1, max_proposals: int = 5,
             stop_when: str = "proposals_raised",
             review: Mapping[str, Any] | None = None,
             tools: tuple[str, ...] = ()) -> ProfileSpec:
    document: dict[str, Any] = {
        "name": name,
        "role": f"{name} role",
        "agent_profile": agent_profile,
        "model_policy": {"tier": tier, "structured_fields": list(structured)},
        "tools": list(tools),
        "authority": {"proposable_kinds": list(proposable)},
        "termination": {"max_ticks": max_ticks, "max_proposals": max_proposals,
                        "stop_when": stop_when},
    }
    if review is not None:
        document["review"] = dict(review)
    return parse_profile(document, source=name)


def _proposal(structured: Mapping[str, Any],
              *, profile: str = "research") -> ModelProposal:
    return ModelProposal(provider_id="alpha", model_id="m1", tier="research",
                         profile=profile, lease_generation=LEASE,
                         structured=dict(structured))


def _draft(kind: str = "INSERT_TASK", *, rationale: str = "because",
           payload: Mapping[str, Any] | None = None) -> ModelProposal:
    return _proposal({"kind": kind, "rationale": rationale,
                      "payload": dict(payload or {})})


def _silent(rationale: str = "nothing to propose") -> ModelProposal:
    return _proposal({"rationale": rationale})


def _ctx(**overrides: Any) -> TaskContext:
    fields: dict[str, Any] = {"task_id": TASK, "project_id": PROJECT,
                              "lease_generation": LEASE,
                              "limits": RunLimits(max_ticks=1)}
    fields.update(overrides)
    return TaskContext(**fields)


class RuntimeRig:
    """One wired runtime over a recording spine — the BIND-3 test rig."""

    def __init__(self, *, scripts: Mapping[str, list[Any]] | list[Any],
                 profiles: Mapping[str, ProfileSpec],
                 lease: str = LEASE, grants: Any = None,
                 checkpoints: Any = None, delegations: Any = None) -> None:
        self.applier = RecordingApplier()
        self.model = ScriptedModel(scripts)
        self.wiring = RuntimeWiring(
            model=self.model, orchestration=self.applier, lease_generation=lease,
            profiles=profiles, grants=grants, clock=FakeClock(),
            checkpoints=checkpoints, delegations=delegations)

    def run(self, profile: str, context: TaskContext | None = None, *,
            token: RunCancelToken | None = None) -> WiredRun:
        return self.wiring.run(
            profile,
            context if context is not None else _ctx(),
            token=token)


# ═══════════════════════ BIND-2: policy resolution ═══════════════════════


def test_the_binding_is_a_structural_model_port() -> None:
    assert isinstance(ModelRig().binding, ModelPort)


def test_the_tier_is_resolved_per_task_and_overrides_a_caller_hint() -> None:
    rig = ModelRig(task_policy=ModelPolicyTable(tiers={"research": "frontier"},
                                                default_tier="baseline"))
    outcome = rig.invoke(profile="research", tier="cheap")
    assert isinstance(outcome, ModelProposal)
    row = rig.binding.dispatch_log()[0]
    assert (row.requested_tier, row.resolved_tier) == ("cheap", "frontier")
    # The router saw the resolved tier, not the caller's hint.
    assert rig.binding.model_ledger()[0].tier == "frontier"


def test_a_task_with_no_declared_tier_falls_back_to_the_default() -> None:
    rig = ModelRig()
    outcome = rig.invoke(profile="an-undeclared-task")
    assert isinstance(outcome, ModelProposal)
    assert rig.binding.dispatch_log()[0].resolved_tier == "baseline"


def test_a_task_with_no_tier_anywhere_refuses_malformed_payload() -> None:
    rig = ModelRig(task_policy=ModelPolicyTable(tiers={}, default_tier=""))
    outcome = rig.invoke(profile="orphan-task")
    assert isinstance(outcome, ModelRefusal)
    assert outcome.code == MALFORMED_PAYLOAD
    assert "orphan-task" in outcome.detail
    assert rig.provider.calls == []
    row = rig.binding.dispatch_log()[0]
    assert (row.outcome, row.attempt, row.refusal_code) == (
        "REFUSED", 0, MALFORMED_PAYLOAD)


def test_the_policy_table_is_declared_data_only() -> None:
    table = ModelPolicyTable(tiers={"a": "x"}, default_tier="y")
    assert table.tier_for("a") == "x"
    assert table.tier_for("absent") == "y"
    assert ModelPolicyTable().tier_for("anything") == ""


# ═══════════════════════ BIND-2: credential absence ═══════════════════════


def test_a_credential_class_option_is_refused_before_any_call() -> None:
    rig = ModelRig()
    outcome = rig.invoke(options={"api_key": SECRET})
    assert isinstance(outcome, ModelRefusal)
    assert outcome.code == MALFORMED_PAYLOAD
    assert "api_key" in outcome.detail        # the parameter is named
    assert SECRET not in outcome.detail       # its value never is
    assert rig.provider.calls == []
    assert SECRET not in rig.log_json()


def test_a_live_credential_never_reaches_a_payload_or_a_record() -> None:
    rig = ModelRig(credentials=FixedCredentials({"alpha": SECRET}))
    outcome = rig.invoke()
    assert isinstance(outcome, ModelProposal)
    call = rig.provider.calls[0]
    assert SECRET not in json.dumps(dict(call.payload), default=str)
    assert SECRET not in json.dumps(dict(call.options), default=str)
    assert SECRET not in json.dumps(
        [dict(row.normalized_request) for row in rig.binding.model_ledger()],
        default=str)
    assert SECRET not in rig.log_json()
    # The credential's own string form is masked, so a log cannot leak it.
    assert SECRET not in str(
        FixedCredentials({"alpha": SECRET}).resolve("alpha"))


def test_the_credential_guard_is_backed_by_the_router(monkeypatch: Any) -> None:
    """Neutralize the binding's guard: the router refuses anyway."""
    rig = ModelRig()
    monkeypatch.setattr(binding_module, "_credential_option_names",
                        lambda options: [])
    outcome = rig.invoke(options={"api_key": SECRET})
    assert isinstance(outcome, ModelRefusal)
    assert outcome.code == MALFORMED_PAYLOAD
    assert rig.provider.calls == []
    assert SECRET not in rig.log_json()


# ═══════════════════════ BIND-2: accounting per dispatch ═══════════════════


def test_every_dispatch_is_accounted_including_a_refusal() -> None:
    rig = ModelRig(task_policy=ModelPolicyTable(tiers={"research": "frontier"},
                                                default_tier=""))
    assert isinstance(rig.invoke(profile="research"), ModelProposal)
    assert isinstance(rig.invoke(profile="orphan"), ModelRefusal)
    rig.binding.verify_accounting()
    assert rig.binding.dispatches == 2
    rows = rig.binding.dispatch_log()
    assert [row.sequence for row in rows] == [0, 1]
    assert [row.outcome for row in rows] == ["OK", "REFUSED"]
    assert rows[0].request_digest != ""       # a real attempt, digests recorded
    assert rows[0].total_tokens == 5
    assert rows[0].price_usd is not None


def test_the_dispatch_ledger_fails_closed_on_a_gap() -> None:
    rig = ModelRig()
    assert isinstance(rig.invoke(), ModelProposal)
    rig.binding._dispatch_log.append(DispatchAccount(
        sequence=99, profile="research", requested_tier="frontier",
        resolved_tier="frontier", lease_generation=LEASE, outcome="OK"))
    with pytest.raises(ModelPlaneInvariantError):
        rig.binding.verify_accounting()


# ═══════════════════════ BIND-3: the InMemory-only pin ═══════════════════════


def _wiring(**overrides: Any) -> RuntimeWiring:
    fields: dict[str, Any] = {
        "model": ScriptedModel([]),
        "orchestration": RecordingApplier(),
        "lease_generation": LEASE,
        "profiles": {"lead": _profile("lead")},
        "clock": FakeClock(),
    }
    fields.update(overrides)
    return RuntimeWiring(**fields)


def test_the_wiring_refuses_a_file_checkpoint_store(tmp_path: Path) -> None:
    with pytest.raises(WiringError) as caught:
        _wiring(checkpoints=FileCheckpointStore(tmp_path))
    assert "FileCheckpointStore" in str(caught.value)
    assert "InMemory" in str(caught.value)


def test_the_wiring_refuses_a_file_delegation_store(tmp_path: Path) -> None:
    with pytest.raises(WiringError) as caught:
        _wiring(delegations=FileDelegationStore(tmp_path))
    assert "FileDelegationStore" in str(caught.value)


def test_the_wiring_refuses_a_store_of_no_known_shape() -> None:
    with pytest.raises(WiringError) as caught:
        _wiring(checkpoints=ForeignStore())
    assert "ForeignStore" in str(caught.value)
    with pytest.raises(WiringError):
        _wiring(delegations=ForeignStore())


def test_the_inmemory_stores_are_what_a_default_composition_installs() -> None:
    rig = RuntimeRig(scripts={"lead": [_draft()]}, profiles={"lead": _profile("lead")})
    wired = rig.run("lead")
    assert rig.wiring.checkpoint(wired.run_id) is not None


def test_the_inmemory_pin_is_load_bearing(tmp_path: Path, monkeypatch: Any) -> None:
    """Neutralize the pin: the same file store is used and writes a document.

    The file appears *outside* any `BEGIN IMMEDIATE` and outside the journal,
    which is exactly the durable-derived-document write the pin exists to keep
    out of production wiring — so the pin is not decorative.
    """
    monkeypatch.setattr(
        wiring_module, "require_inmemory_checkpoints",
        lambda store: (store if store is not None else InMemoryCheckpointStore()))
    store = FileCheckpointStore(tmp_path)
    rig = RuntimeRig(scripts={"lead": [_draft()]},
                     profiles={"lead": _profile("lead")}, checkpoints=store)
    wired = rig.run("lead")
    assert store.get(wired.run_id) is not None
    assert list(tmp_path.glob("*.json")) != []


def test_the_neutralized_delegation_pin_is_load_bearing(
        tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(
        wiring_module, "require_inmemory_delegations",
        lambda store: (store if store is not None else InMemoryDelegationStore()))
    store = FileDelegationStore(tmp_path)
    lead = _profile("lead", agent_profile="DIRECTOR",
                    structured=("proposals", "delegations"))
    worker = _profile("worker", stop_when="no_proposals")
    rig = RuntimeRig(
        scripts={"lead": [_proposal({"rationale": "delegate", "delegations": [
            {"profile": "worker", "spec": {"goal": "g"}}]})],
            "worker": [_silent()]},
        profiles={"lead": lead, "worker": worker}, delegations=store)
    rig.run("lead")
    assert list(tmp_path.glob("*.json")) != []


# ═══════════════════════ BIND-3: lease fence + attribution ═══════════════════════


def test_the_wiring_needs_the_lease_generation_it_acts_under() -> None:
    with pytest.raises(WiringError):
        _wiring(lease_generation="   ")


def test_a_run_is_attributed_to_the_fence_generation() -> None:
    rig = RuntimeRig(scripts={"lead": [_draft()]}, profiles={"lead": _profile("lead")})
    wired = rig.run("lead")
    assert wired.aborted is False
    assert wired.lease_generation == LEASE
    assert wired.spine_writes == 1
    result = wired.result
    assert result.lease_generation == LEASE
    assert result.proposals and all(p.lease_generation == LEASE
                                    for p in result.proposals)
    assert rig.wiring.trace(result.run_id)
    assert all(event.lease_generation == LEASE
               for event in rig.wiring.trace(result.run_id))
    checkpoint = rig.wiring.checkpoint(result.run_id)
    assert checkpoint is not None
    assert checkpoint.lease_generation == LEASE


def test_a_foreign_generation_refuses_lock_before_dispatch() -> None:
    rig = RuntimeRig(scripts={"lead": [_draft()]}, profiles={"lead": _profile("lead")})
    wired = rig.run("lead", _ctx(lease_generation="someone-elses-lease"))
    assert wired.aborted is True
    assert wired.lease_lost is False
    assert wired.refusal_codes() == (LOCK,)
    assert wired.spine_writes == 0
    assert rig.applier.calls == []
    assert rig.model.call_count == 0
    assert rig.wiring.checkpoint(wired.run_id) is None


def test_a_mid_run_lease_loss_aborts_and_stops_writing() -> None:
    profiles = {"lead": _profile("lead", max_ticks=3, stop_when="converged")}
    rig = RuntimeRig(scripts={"lead": [_draft(), _draft()]}, profiles=profiles)

    def lose_on_second_call(request: ModelRequest) -> None:
        if rig.model.call_count >= 2:
            rig.wiring.lose_lease("the lease was lost mid-run")

    rig.model.on_call = lose_on_second_call

    wired = rig.run("lead", _ctx(limits=RunLimits(max_ticks=3)))
    assert rig.model.call_count == 2
    assert wired.lease_lost is True
    assert wired.aborted is True
    assert wired.spine_writes == 1                 # only tick 1 reached the spine
    assert wired.spine_refusals == 1               # tick 2's write was fenced
    assert LOCK in wired.refusal_codes()
    assert wired.state == TaskStatus.CANCELLED.value
    assert len(rig.applier.calls) == 1             # no partial write after the loss
    checkpoint = rig.wiring.checkpoint(wired.run_id)
    assert checkpoint is not None
    assert checkpoint.lease_generation == LEASE


def test_the_fence_refuses_a_write_and_cancels_watchers() -> None:
    fence = LeaseFence(LEASE)
    applier = FencedIntentApplier(fence=fence, inner=RecordingApplier())
    token = RunCancelToken()
    applier.watch(token)
    fence.lose("gone")
    with pytest.raises(wiring_module.LeaseLostRejection) as caught:
        applier(Intent(kind=IntentKind.BRANCH, proposed_by="X",
                       project_id=PROJECT, payload={}))
    assert caught.value.code == LOCK
    assert token.cancelled is True
    assert applier.writes == 0 and applier.refusals == 1


def test_a_delegated_child_record_carries_the_lease_generation() -> None:
    lead = _profile("lead", agent_profile="DIRECTOR",
                    structured=("proposals", "delegations"))
    worker = _profile("worker", stop_when="no_proposals")
    rig = RuntimeRig(
        scripts={"lead": [_proposal({"rationale": "delegate", "delegations": [
            {"profile": "worker", "spec": {"goal": "g"}}]})],
            "worker": [_silent()]},
        profiles={"lead": lead, "worker": worker})
    wired = rig.run("lead")
    records = rig.wiring.delegation_records(run_id=wired.run_id)
    assert len(records) == 1
    record = records[0]
    assert record.profile == "worker"
    assert record.lease_generation == LEASE
    assert record.state == DelegationState.DONE.value


# ═══════════════════════ BIND-3: drafts have no identity ═══════════════════════


def test_a_draft_may_not_author_an_identity() -> None:
    rig = RuntimeRig(scripts={"lead": [_draft(payload={"task_id": "forged"})]},
                     profiles={"lead": _profile("lead")})
    wired = rig.run("lead")
    assert MALFORMED_PAYLOAD in wired.refusal_codes()
    assert rig.applier.calls == []
    assert wired.spine_writes == 0


def test_an_admitted_draft_gets_its_identity_derived_by_rule() -> None:
    rig = RuntimeRig(scripts={"lead": [_draft(payload={"goal": "g"})]},
                     profiles={"lead": _profile("lead")})
    wired = rig.run("lead")
    assert wired.spine_writes == 1
    intent = rig.applier.calls[0]
    assert intent.payload["task_id"] == child_task_id_of(TASK, "lead", 0)
    assert intent.payload["idempotency_key"] != ""
    assert intent.payload["task_id"] != "forged"


# ═══════════════════════ no write surface (mechanical) ═══════════════════════

#: Exactly what the binding may import: the router (the plane it binds) + stdlib.
BINDING_IMPORTS = frozenset({
    "__future__", "collections.abc", "dataclasses", "json", "typing",
    "hermes.tools.models.router",
})

#: Exactly what the wiring may import: its own plane, core types, port shapes.
WIRING_IMPORTS = frozenset({
    "__future__", "collections.abc", "dataclasses", "typing",
    "hermes.agents.runtime.checkpoint",
    "hermes.agents.runtime.config",
    "hermes.agents.runtime.delegate",
    "hermes.agents.runtime.run",
    "hermes.agents.runtime.supervisor",
    "hermes.agents.runtime.types",
    "hermes.core",
    "hermes.core.intents",
    "hermes.core.task_status",
    "hermes.tools.capabilities.types",
})

#: Names a module with a write surface — or a file-backed store — would mention.
FORBIDDEN_NAMES = frozenset({
    "conn", "connection", "cursor", "commit", "rollback", "executemany",
    "execute", "BEGIN", "sqlite3", "FileCheckpointStore", "FileDelegationStore",
})


def _tree_of(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _imports_of(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(_tree_of(path)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _imported_names_from(path: Path, module: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(_tree_of(path)):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            names.update(alias.name for alias in node.names)
    return names


def _code_identifiers(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(_tree_of(path)):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
    return found


def test_the_binding_imports_the_router_and_stdlib_only() -> None:
    assert _imports_of(BINDING_PATH) == set(BINDING_IMPORTS)
    assert _code_identifiers(BINDING_PATH) & FORBIDDEN_NAMES == set()


def test_the_wiring_imports_ports_and_core_types_only() -> None:
    assert _imports_of(WIRING_PATH) == set(WIRING_IMPORTS)
    assert _code_identifiers(WIRING_PATH) & FORBIDDEN_NAMES == set()


def test_the_wiring_never_imports_a_file_store() -> None:
    """The pin is only honest if the wiring cannot reach a File store at all."""
    from_checkpoint = _imported_names_from(WIRING_PATH,
                                           "hermes.agents.runtime.checkpoint")
    from_delegate = _imported_names_from(WIRING_PATH,
                                         "hermes.agents.runtime.delegate")
    assert "FileCheckpointStore" not in from_checkpoint
    assert "FileDelegationStore" not in from_delegate
    assert from_checkpoint == {"CheckpointStore", "InMemoryCheckpointStore"}
    assert from_delegate == {"ArtifactOverflowPort", "DelegationStore",
                             "InMemoryDelegationStore"}
